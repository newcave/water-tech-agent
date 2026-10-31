#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tech_map_patents — 논문 × 특허 기술 지도의 '특허 축' 재료: WCS 특허(archive.patents) → 세부 기술별·출원연도별 '건수'만 (v3.18)

원천: WCS 특허 CSV (내부 자료 — 비공개 저장소 newcave/water-tech-kci-private의 wcs/patents.csv, 또는 PATENTS_CSV로 지정한 파일)
  열: application_number, application_date, invention_title, applicant_name, register_status, ipc, open_date,
      register_date, abstract, search_keyword  (WCS: \\copy (SELECT … FROM archive.patents) TO 'patents.csv' CSV HEADER)
매칭: units.json의 ko 말(제목+요약, 띄어쓰기 무시). 'A+B'는 둘 다 있어야 함. 영문 약어(SAR·LLM·AI)는 앞뒤가 영문자가 아닐 때만.
출력 data_seed/tech_map/patents.json — 공개 저장소에는 집계만 (출원번호·발명 명칭·출원인 이름·요약은 싣지 않음):
  units.<id>.by_year.<출원연도> = [출원, 등록, 기업 출원, 대학, 공공·연구기관, K-water, 개인]  (한 특허에 출원인이 여럿이면 해당 칸 모두 +1)
  units.<id>.ipc = 상위 IPC 4자리 [[코드, 건수]] · ipc_fit = units.json ipc 힌트와 맞는 비율(매칭 품질 점검용) · terms = 말별 적중 수
"""
import csv
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / "data_seed" / "tech_map"
UNITS = DIR / "units.json"
OUT = DIR / "patents.json"
AGENT = ROOT / "data_seed" / "agents" / "tech_map.json"
CANDIDATES = [os.environ.get("PATENTS_CSV", ""), "private/wcs/patents.csv", "private/patents.csv"]
Y0 = 2006
COLS = ("n", "reg", "corp", "univ", "public", "kwater", "indiv")

csv.field_size_limit(10 ** 8)

KWATER = re.compile(r"한국수자원공사|K-?water|Korea Water Resources", re.I)
UNIV = re.compile(r"대학|산학협력|과학기술원|University|College|KAIST|POSTECH|UNIST|DGIST|GIST", re.I)
PUBLIC = re.compile(r"연구원|공사$|공사\b|공단|진흥원|대한민국|정부|특별시|광역시|특별자치|도청|시청|군청|구청|국립|청장|"
                    r"Institute|Agency|Ministry|Government|Republic of Korea|Council", re.I)
LEGAL = re.compile(r"주식회사|\(주\)|㈜|유한회사|유한책임|합자회사|합명회사|\bCo\b|Co\.|Ltd|Inc\b|Inc\.|Corp|GmbH|LLC|S\.A\.|\bAG\b", re.I)
COMPANY = re.compile(r"엔지니어링|건설|산업|테크|시스템|솔루션|에너지|전자|중공업|화학|환경|기술|코리아", re.I)
HANGUL_NAME = re.compile(r"^[가-힣]{2,4}$")


def applicant_types(raw: str) -> set:
    out = set()
    for a in re.split(r"[|;,/]| 외 ?\d*명?", raw or ""):
        a = a.strip()
        if not a:
            continue
        if KWATER.search(a):
            out.add("kwater")
        elif UNIV.search(a):
            out.add("univ")
        elif LEGAL.search(a):                                     # 법인 표기가 있으면 '연구원' 같은 말이 있어도 기업
            out.add("corp")
        elif PUBLIC.search(a):
            out.add("public")
        elif COMPANY.search(a):
            out.add("corp")
        elif HANGUL_NAME.match(a.replace(" ", "")):
            out.add("indiv")
        else:
            out.add("corp")                                       # 법인 표기 없는 상호 (영문 사명 등)
    return out


def term_regex(term: str):
    t = re.sub(r"\s+", "", term)
    pat = re.escape(t)
    if re.match(r"[A-Za-z]", t):
        pat = r"(?<![A-Za-z])" + pat
    if re.search(r"[A-Za-z]$", t):
        pat += r"(?![A-Za-z])"
    return re.compile(pat, 0 if t.isupper() else re.I)


def build_matchers(units: list) -> dict:
    """단위 → [(원래 말, [부분 정규식…])] — 'A+B'는 부분이 모두 맞아야 함."""
    return {u["id"]: [(k, [term_regex(p) for p in k.split("+") if p.strip()]) for k in u.get("ko", [])] for u in units}


def year_of(s: str):
    m = re.search(r"(19|20)\d{2}", s or "")
    return m.group(0) if m else None


def find_csv():
    for c in CANDIDATES:
        if c and Path(c).is_file():
            return Path(c)
    return None


def main():
    src = find_csv()
    if not src:
        print("특허 CSV 없음 — 건너뜀 (private/wcs/patents.csv 또는 PATENTS_CSV)")
        return 0
    units = json.loads(UNITS.read_text(encoding="utf-8"))["units"]
    match = build_matchers(units)
    hints = {u["id"]: tuple(u.get("ipc", [])) for u in units}
    y1 = time.gmtime().tm_year - 1
    agg = {u["id"]: defaultdict(lambda: [0] * len(COLS)) for u in units}
    ipc = {u["id"]: Counter() for u in units}
    fit = Counter()
    terms = {u["id"]: Counter() for u in units}
    total, in_span, matched = 0, 0, 0
    all_years = Counter()
    seen = set()
    with src.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            key = (row.get("application_number") or "").strip()
            if key and key in seen:                               # 같은 특허가 검색어마다 중복 저장된 경우
                continue
            seen.add(key)
            total += 1
            y = year_of(row.get("application_date"))
            if not y:
                continue
            all_years[y] += 1
            if not (Y0 <= int(y) <= y1):
                continue
            in_span += 1
            text = re.sub(r"\s+", "", f"{row.get('invention_title', '')} {row.get('abstract', '')}")
            reg = bool((row.get("register_date") or "").strip()) or any(
                s in (row.get("register_status") or "") for s in ("등록", "소멸", "만료"))
            types = applicant_types(row.get("applicant_name", ""))
            codes = {c.strip()[:4] for c in re.split(r"[|;,\s]+", row.get("ipc") or "") if len(c.strip()) >= 4}
            hit_any = False
            for uid, ms in match.items():
                hits = [k for k, parts in ms if all(p.search(text) for p in parts)]
                if not hits:
                    continue
                hit_any = True
                v = agg[uid][y]
                v[0] += 1
                v[1] += reg
                for i, c in enumerate(COLS[2:], start=2):
                    v[i] += c in types
                ipc[uid].update(codes)
                fit[uid] += any(c.startswith(hints[uid]) for c in codes) if hints[uid] else 0
                terms[uid].update(hits)
            matched += hit_any
    years = [str(y) for y in range(Y0, y1 + 1)]
    out_units = {}
    for u in units:
        uid = u["id"]
        n = sum(v[0] for v in agg[uid].values())
        out_units[uid] = {"inst": u["inst"], "name": u["name"], "n": n,
                          "by_year": {y: agg[uid][y] for y in years if y in agg[uid]},
                          "ipc": ipc[uid].most_common(6), "ipc_fit": round(fit[uid] / n, 3) if n else None,
                          "terms": terms[uid].most_common()}
    now = int(time.time())
    out = {"_doc": "논문 × 특허 기술 지도 — 특허 축 재료 (WCS 특허 집계만 · 원천은 비공개). by_year.<출원연도> = "
                   + "·".join(["출원", "등록", "기업", "대학", "공공·연구기관", "K-water", "개인"])
                   + " 건수 (출원인 유형은 한 특허에 여럿이면 모두 셈). ipc_fit = 기술 정의서 IPC 힌트와 맞는 비율 (매칭 점검용)",
           "updated": now, "source": "WCS archive.patents", "cols": list(COLS), "years": years,
           "total": total, "in_span": in_span, "matched": matched,
           "app_years": dict(sorted(all_years.items())), "units": out_units}
    DIR.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    try:
        ag = json.loads(AGENT.read_text(encoding="utf-8"))
        ag.setdefault("counts", {})["특허(매칭)"] = matched
        ag["events"] = (ag.get("events") or [])[-19:] + [{"ts": now, "msg": f"📜 특허 {total:,}건 중 {matched:,}건을 세부 기술에 연결"}]
        AGENT.write_text(json.dumps(ag, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    except Exception:
        pass
    print(f"✅ 특허 {total:,}건 · {Y0}~{y1} {in_span:,}건 · 세부 기술 연결 {matched:,}건")
    for u in sorted(units, key=lambda u: -out_units[u["id"]]["n"])[:10]:
        o = out_units[u["id"]]
        print(f"  {u['id']} {u['name']:<14} {o['n']:>6,}건 · IPC 일치 {o['ipc_fit'] or 0:.0%} · {o['terms'][:3]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
