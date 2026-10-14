"""
HITL 판정 대장 정리 — data 브랜치 labels/hitl/<INST>/ 정리 (GitHub Actions hitl-ledger.yml이 판정 묶음 push마다 실행)

  입력: 판정 묶음 파일들  labels/hitl/<INST>/<시각>_<판정자>.jsonl  (앱 '직접 저장' 또는 GitHub 링크 Commit)
  출력: ledger.jsonl  — 모든 판정 기록을 시간순으로 한 파일에 누적 (중복 제거, 지우지 않음)
        summary.json  — 판정자별·날짜별·판정별 집계 + 논문별 최종 판정 개수
        final.csv     — 논문별 최종 판정표 (소장 확정 > 담당자 최신 판정), 제목·연도·DOI 포함 → GitHub에서 표로 보임
  합친 묶음 파일은 지운다 (내용은 ledger.jsonl에 그대로 있음).

실행: python hitl_ledger.py            (변경 없으면 아무것도 쓰지 않음)
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
from collections import Counter
from pathlib import Path

ROOT = Path("labels/hitl")
KST = dt.timezone(dt.timedelta(hours=9))
INST_NAME = {"INST-01": "경영연구소", "INST-02": "수자원환경연구소", "INST-03": "상하수도연구소",
             "INST-04": "물인프라안전연구소", "INST-05": "물에너지연구소",
             "INST-06": "수자원위성연구소", "INST-07": "AI연구소"}
DEC_KO = {"ok": "OK", "ng": "NG", "move": "이관", "skip": "건너뜀"}
REASON_KO = {"nonresearch": "연구 문헌 아님", "out_of_scope": "연구소 범위 밖", "not_water": "물 분야 아님",
             "duplicate": "중복", "other": "기타"}


def parse(p: Path) -> list[dict]:
    out = []
    for line in p.read_text(encoding="utf-8").split("\n"):      # \n으로만 (U+2028 보호)
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out


def key(r: dict) -> tuple:
    return (r.get("id"), r.get("ts"), r.get("reviewer"), r.get("decision"), r.get("role"))


def kst(ts: str | None) -> str:
    try:
        return dt.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc) \
            .astimezone(KST).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ts or ""


def paper_meta(inst: str) -> dict:
    meta = {}
    for f in (Path(f"live/openalex/papers_{inst}.jsonl"), Path(f"labels/openalex_extended/papers_{inst}.jsonl")):
        if f.exists():
            for p in parse(f):
                if p.get("id") and p["id"] not in meta:
                    meta[p["id"]] = p
    return meta


def finals(recs: list[dict]) -> dict:
    """논문별 최종: 소장 최신 판정 > 담당자 최신 판정 (건너뜀 제외)."""
    out = {}
    for r in recs:                                   # 시간순
        if r.get("decision") not in ("ok", "ng", "move"):
            continue
        cur = out.setdefault(r["id"], {"reviewer": None, "director": None, "n": 0})
        cur["n"] += 1
        cur["director" if r.get("role") == "director" else "reviewer"] = r
    return out


def summarize(inst: str, recs: list[dict]) -> dict:
    fin = finals(recs)
    by_rv = {}
    for r in recs:
        w = r.get("reviewer") or "?"
        a = by_rv.setdefault(w, {"roles": set(), "ok": 0, "ng": 0, "move": 0, "skip": 0, "papers": set(),
                                 "first": None, "last": None})
        a["roles"].add(r.get("role") or "reviewer")
        d = r.get("decision")
        if d in a:
            a[d] += 1
        if d in ("ok", "ng", "move"):
            a["papers"].add(r.get("id"))
        ts = r.get("ts") or ""
        a["first"] = min(a["first"] or ts, ts)
        a["last"] = max(a["last"] or ts, ts)
    final_dec = Counter()
    moves, reasons = Counter(), Counter()
    for f in fin.values():
        r = f["director"] or f["reviewer"]
        final_dec[r["decision"]] += 1
        if r["decision"] == "move":
            moves[r.get("to")] += 1
        if r["decision"] == "ng":
            reasons[r.get("reason") or "other"] += 1
    return {
        "inst": inst, "inst_name": INST_NAME.get(inst, inst),
        "updated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "records": len(recs), "judgments": sum(1 for r in recs if r.get("decision") in ("ok", "ng", "move")),
        "papers_judged": len(fin), "director_confirmed": sum(1 for f in fin.values() if f["director"]),
        "final": dict(final_dec), "moves_to": dict(moves), "ng_reasons": dict(reasons),
        "by_queue": dict(Counter(r.get("queue") or "?" for r in recs)),
        "by_day_kst": dict(sorted(Counter(kst(r.get("ts"))[:10] for r in recs).items())),
        "by_reviewer": {w: {**{k: v for k, v in a.items() if k not in ("roles", "papers", "first", "last")},
                            "roles": sorted(a["roles"]), "papers": len(a["papers"]),
                            "first_kst": kst(a["first"]), "last_kst": kst(a["last"])}
                        for w, a in sorted(by_rv.items(), key=lambda x: -len(x[1]["papers"]))},
    }


def final_csv(inst: str, recs: list[dict]) -> str:
    meta = paper_meta(inst)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["논문ID", "제목", "연도", "최종 판정", "이관처", "공유", "NG 사유", "판정자", "역할", "판정 시각(KST)",
                "소장 확정", "판정 횟수", "메모", "DOI"])
    rows = []
    for pid, f in finals(recs).items():
        r = f["director"] or f["reviewer"]
        p = meta.get(pid, {})
        rows.append([pid, (p.get("title") or "").replace("\n", " ")[:200], p.get("year") or "",
                     DEC_KO.get(r["decision"], r["decision"]), INST_NAME.get(r.get("to"), "") if r.get("to") else "",
                     ",".join(INST_NAME.get(x, x) for x in r.get("also") or []),
                     REASON_KO.get(r.get("reason"), "") if r.get("reason") else "", r.get("reviewer") or "",
                     "소장" if r.get("role") == "director" else "담당자", kst(r.get("ts")),
                     "Y" if f["director"] else "", f["n"], r.get("note") or "", p.get("doi") or ""])
    for row in sorted(rows, key=lambda x: x[9], reverse=True):
        w.writerow(row)
    return "﻿" + buf.getvalue()             # 엑셀에서 한글 깨짐 방지(BOM)


def main() -> int:
    if not ROOT.exists():
        print("labels/hitl 없음")
        return 0
    changed = 0
    for d in sorted(x for x in ROOT.iterdir() if x.is_dir()):
        ledger = d / "ledger.jsonl"
        batches = sorted(p for p in d.glob("*.jsonl") if p.name != "ledger.jsonl")
        if not batches and (d / "summary.json").exists() and (d / "final.csv").exists():
            continue
        old = parse(ledger) if ledger.exists() else []
        seen, recs = set(), []
        for r in old + [r for b in batches for r in parse(b)]:
            k = key(r)
            if r.get("id") and k not in seen:
                seen.add(k)
                recs.append(r)
        recs.sort(key=lambda r: (r.get("ts") or "", r.get("id") or ""))
        ledger.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs), encoding="utf-8")
        (d / "summary.json").write_text(json.dumps(summarize(d.name, recs), ensure_ascii=False, indent=1) + "\n",
                                        encoding="utf-8")
        (d / "final.csv").write_text(final_csv(d.name, recs), encoding="utf-8")
        for b in batches:
            b.unlink()
        changed += 1
        print(f"{d.name}: 대장 {len(old)} → {len(recs)}줄 (묶음 {len(batches)}개 합침)")
    print("정리한 연구소", changed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
