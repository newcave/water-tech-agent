#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kci_collect — 한국 저널(J11·J12) KCI 논문 메타데이터 전량 수집 → 비공개 저장소에만 저장

KCI 이용 준수: 원천 데이터(제목·초록 등)는 재배포 금지 → 공개 저장소에 두지 않는다.
  · 저장 위치 = 환경변수 KCI_RAW_DIR (워크플로가 비공개 저장소 water-tech-kci-private를 체크아웃한 경로)
  · 공개 저장소에는 kci_rising.py가 만든 집계(용어별 연도 빈도·검정 결과)만 커밋
  · 로그에는 건수만 출력 (제목·초록 미출력)

동작 (2026-09-29 점검으로 확인한 API 특성):
  · articleSearch의 journal= (부분일치) + dateFrom/dateTo(YYYYMM) + displayCount=100 + page
  · journal-name을 레지스트리 kci.names와 대조해 걸러 저장 (정기학술대회논문집 등 제외)
  · 첫 실행은 전 연도, 이후에는 파일이 없는 연도 + 최근 2년만 다시 받음 (KCI_FULL=1이면 전량 재수집)

K-water 사이드 수집 (search_topics.json kwater_affiliation.kci_affiliation):
  · J11·J12 레코드에 저자 소속이 K-water이면 kwater=true 표시
  · KCI 전체에서 affiliation=검색어(한국수자원공사·K-water 등)로 연도별 수집 → 합치고 중복 제거 →
    저자 소속 문자열을 다시 확인(kci_affiliation_pattern)해 맞는 것만 raw/KWATER/{연도}.jsonl에 저장

저장: {KCI_RAW_DIR}/raw/{코드}/{연도}.jsonl, raw/KWATER/{연도}.jsonl, {KCI_RAW_DIR}/manifest.json
출처: KCI(한국학술지인용색인) 데이터 활용
"""
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

from water_journals import ROOT, load_registry

API = "https://open.kci.go.kr/po/openapi/openApiSearch.kci"
KEY = os.environ.get("KCI_API_KEY", "").strip()
RAW = Path(os.environ.get("KCI_RAW_DIR", "private")) / "raw"
FULL = os.environ.get("KCI_FULL") == "1"
PAGE = 100
PAUSE = 1.0
MAX_PAGES = 30
HANGUL = re.compile("[가-힣]")
TOPICS = json.loads((ROOT / "data_seed" / "search_topics.json").read_text(encoding="utf-8"))
KW = TOPICS.get("kwater_affiliation", {})
KW_QUERIES = KW.get("kci_affiliation", ["한국수자원공사", "K-water"])
KW_PATTERN = re.compile(KW.get("kci_affiliation_pattern", "한국수자원공사|k-?water"), re.I)


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def norm(name) -> str:
    return "".join((name or "").split())


def texts(el, name: str) -> list:
    return [(x.text or "").strip() for x in el.iter()
            if local(x.tag) == name and (x.text or "").strip()]


def first(el, name: str):
    t = texts(el, name)
    return t[0] if t else None


def pick(vals: list, korean: bool):
    for v in vals:
        if bool(HANGUL.search(v)) == korean:
            return v
    return None


def call(params: dict):
    wait = 5.0
    for attempt in range(4):
        try:
            r = requests.get(API, params={"apiCode": "articleSearch", "key": KEY, **params}, timeout=60)
            time.sleep(PAUSE)
            if r.status_code == 200:
                return ET.fromstring(r.content)
            print(f"   ⏳ HTTP {r.status_code} — {wait:.0f}초 후 재시도")
        except (requests.RequestException, ET.ParseError) as e:
            print(f"   ⏳ {type(e).__name__} — {wait:.0f}초 후 재시도")
        time.sleep(wait)
        wait *= 2
    raise RuntimeError("KCI 재시도 초과")


def authors_of(rec) -> list:
    """'이름(소속)' 형식 → [{name, affil}]. 비공개 저장소에만 저장."""
    out = []
    for a in (x for x in rec.iter() if local(x.tag) == "author"):
        t = (a.text or "").strip()
        m = re.match(r"^(.*?)\((.*)\)\s*$", t)
        out.append({"name": (m.group(1) if m else t).strip(), "affil": (m.group(2) if m else "").strip()})
    return out


def record(rec) -> dict:
    info = next((x for x in rec.iter() if local(x.tag) == "articleInfo"), rec)
    titles, abstracts = texts(rec, "article-title"), texts(rec, "abstract")
    authors = authors_of(rec)
    return {"kwater": any(KW_PATTERN.search(a["affil"]) for a in authors),
            "authors": authors,"id": info.attrib.get("article-id") or first(rec, "uci") or first(rec, "doi"),
            "journal": first(rec, "journal-name"), "year": first(rec, "pub-year"),
            "mon": first(rec, "pub-mon"), "volume": first(rec, "volume"), "issue": first(rec, "issue"),
            "category": first(rec, "article-categories"),
            "title_ko": pick(titles, True), "title_en": pick(titles, False),
            "abstract_ko": pick(abstracts, True), "abstract_en": pick(abstracts, False),
            "doi": first(rec, "doi"), "url": first(rec, "url"),
            "cited": first(rec, "citation-count")}


def fetch_year(journal, names, year: int, extra: dict = None) -> list:
    """journal= (names로 걸러냄) 또는 extra 조건(affiliation= 등, names=None이면 거르지 않음)."""
    out, got, total = [], 0, None
    base = {"journal": journal} if journal else {}
    for page in range(1, MAX_PAGES + 1):
        root = call({**base, **(extra or {}), "dateFrom": f"{year}01", "dateTo": f"{year}12",
                     "displayCount": PAGE, "page": page})
        total = total if total is not None else int(first(root, "total") or 0)
        recs = [el for el in root.iter() if local(el.tag) == "record"]
        got += len(recs)
        out += [r for r in map(record, recs) if names is None or norm(r["journal"]) in names]
        if not recs or got >= total:
            break
    seen, uniq = set(), []                            # 페이지 경계 중복 제거
    for r in out:
        k = r["id"] or (r["title_ko"], r["volume"], r["issue"])
        if k not in seen:
            seen.add(k)
            uniq.append(r)
    return uniq


def main():
    if not KEY:
        print("❌ KCI_API_KEY 없음")
        return 1
    reg = load_registry()
    y0, y1 = int(reg.get("archive_from_year", 2000)), time.gmtime().tm_year
    manifest_p = RAW.parent / "manifest.json"
    try:
        manifest = json.loads(manifest_p.read_text(encoding="utf-8"))
    except Exception:
        manifest = {"journals": {}}
    for j in reg.get("journals", []):
        kci = j.get("kci")
        if not kci:
            continue
        names = {norm(n) for n in kci.get("names", [])}
        d = RAW / j["code"]
        d.mkdir(parents=True, exist_ok=True)
        m = manifest["journals"].setdefault(j["code"], {"name": j["name"], "years": {}})
        for y in range(y0, y1 + 1):
            p = d / f"{y}.jsonl"
            if p.exists() and not FULL and y < y1 - 1:
                continue
            recs = fetch_year(kci["journal"], names, y)
            if not recs and not p.exists():
                continue
            p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs), encoding="utf-8")
            m["years"][str(y)] = {"n": len(recs), "kwater": sum(r["kwater"] for r in recs),
                                  "with_abstract": sum(bool(r["abstract_ko"] or r["abstract_en"]) for r in recs)}
            print(f"   {j['code']} {y}: {len(recs)}건 (K-water {m['years'][str(y)]['kwater']}, "
                  f"초록 {m['years'][str(y)]['with_abstract']})")
        print(f"✅ {j['code']} {j['name']}: {sum(v['n'] for v in m['years'].values()):,}건")

    # ── K-water 사이드: KCI 전체에서 K-water 소속 논문 ──
    d = RAW / "KWATER"
    d.mkdir(parents=True, exist_ok=True)
    m = manifest["journals"].setdefault("KWATER", {"name": "K-water 소속 논문 (KCI 전체)", "years": {}})
    for y in range(y0, y1 + 1):
        p = d / f"{y}.jsonl"
        if p.exists() and not FULL and y < y1 - 1:
            continue
        seen, recs, raw_n = set(), [], 0
        for q in KW_QUERIES:
            for r in fetch_year(None, None, y, {"affiliation": q}):
                raw_n += 1
                k = r["id"] or (r["title_ko"], r["journal"], r["volume"], r["issue"])
                if k not in seen and r["kwater"]:                 # 소속 문자열 재확인
                    seen.add(k)
                    recs.append(r)
        if not recs and not p.exists():
            continue
        p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs), encoding="utf-8")
        m["years"][str(y)] = {"n": len(recs), "hits": raw_n,
                              "with_abstract": sum(bool(r["abstract_ko"] or r["abstract_en"]) for r in recs)}
        print(f"   KWATER {y}: {len(recs)}건 (검색 결과 {raw_n}건 중 소속 확인)")
    print(f"✅ KWATER K-water 소속 논문: {sum(v['n'] for v in m['years'].values()):,}건")
    manifest["updated"] = int(time.time())
    manifest["source"] = "KCI(한국학술지인용색인) 데이터 활용 — 재배포 금지, 이용 목적 종료 시 파기"
    manifest_p.write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
