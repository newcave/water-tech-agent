#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""metrics_snapshot.py — 수집 달성도 스냅샷 + 실패 기록 (data 브랜치, labels-pipeline 회차마다 호출)

산출물 (관제센터 '🎯 수집 달성도' 탭이 읽음):
  labels/metrics/daily.jsonl     회차별 스냅샷 1줄 — 수집·초록·추출·배정 건수 (전체 + 연구소별)
  labels/metrics/failures.jsonl  실패 기록 1줄/건 — key로 중복 제거, 한 번 쓴 기록은 고치지 않음

실패의 출처 4가지:
  pipeline  labels_pipeline.py가 이번 회차에 겪은 실패 (OpenAlex·LLM 호출 실패 등)
  audit     데이터 점검 규칙 — 깨진 JSON 줄 증가, 초록 빈 값이 50편 이상 연속으로 새로 생김
  github    GitHub Actions 실패 회차 (GITHUB_TOKEN이 있을 때만)
  retro     사후 진단으로 추가한 과거 기록

LLM 토큰을 쓰지 않는다. 실패해도 파이프라인을 멈추지 않도록 호출부에서 예외를 삼킨다.
단독 실행:  python metrics_snapshot.py --repo .
"""
import argparse
import json
import os
import time
import urllib.request
from pathlib import Path

INSTS = [f"INST-0{i}" for i in range(1, 8)]
EMPTY_BLOCK = 50          # 초록 빈 값이 이만큼 연속이면 보강 호출 실패로 의심 (보강 묶음 크기)


def _jl(path: Path):
    """JSONL → (rows, 깨진 줄 수)."""
    rows, bad = [], 0
    if path.exists():
        for line in path.open(encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                bad += 1
    return rows, bad


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def compute(repo: Path) -> dict:
    """현재 적재 상태 — 전체·연구소별 건수와 점검용 부가 정보."""
    lab = repo / "labels"
    live = repo / "live" / "openalex"
    per, broken = {}, {}
    for inst in INSTS:
        ids = set()
        for p in (live / f"papers_{inst}.jsonl", lab / "openalex_extended" / f"papers_{inst}.jsonl"):
            rows, bad = _jl(p)
            if bad:
                broken[str(p.relative_to(repo))] = bad
            ids.update(str(r.get("id", "")).rsplit("/", 1)[-1] for r in rows if r.get("id"))
        primary = {str(r.get("id", "")).rsplit("/", 1)[-1] for r in _jl(live / f"papers_{inst}.jsonl")[0]}
        ab_rows, bad = _jl(lab / "abstracts" / f"{inst}.jsonl")
        if bad:
            broken[f"labels/abstracts/{inst}.jsonl"] = bad
        ok = {}
        for r in ab_rows:                          # 같은 id가 여러 줄이면 하나라도 초록이 있으면 확보
            rid = r.get("id")
            if rid:
                ok[rid] = ok.get(rid, False) or bool((r.get("abstract") or "").strip())
        run, block_rows = 0, 0                    # 50편 이상 연속 빈 값 = 보강 실패 의심 행 수
        for r in ab_rows:
            if (r.get("abstract") or "").strip():
                block_rows += run if run >= EMPTY_BLOCK else 0
                run = 0
            else:
                run += 1
        block_rows += run if run >= EMPTY_BLOCK else 0
        ex_rows, bad = _jl(lab / "extract" / f"{inst}.jsonl")
        if bad:
            broken[f"labels/extract/{inst}.jsonl"] = bad
        ex = {r["id"]: r for r in ex_rows if r.get("id")}
        dm_rows, bad = _jl(lab / "domain" / f"{inst}.jsonl")
        if bad:
            broken[f"labels/domain/{inst}.jsonl"] = bad
        dm = {r["id"] for r in dm_rows if r.get("id")}
        per[inst] = {
            "collected": len(ids),
            "primary": len(primary),
            "abstract_rows": len(ok),
            "abstract_ok": sum(1 for v in ok.values() if v),
            "extracted": len(ex),
            "relevant": sum(1 for r in ex.values() if r.get("relevant")),
            "assigned": len(dm),
            "empty_block_rows": block_rows,
        }
    tot = {k: sum(v[k] for v in per.values()) for k in next(iter(per.values()))}
    stats = json.loads((live / "stats.json").read_text(encoding="utf-8")) if (live / "stats.json").exists() else {}
    tot["primary_collected"] = stats.get("collected_total")
    tot["primary_target"] = stats.get("target_total")
    for inst in INSTS:
        t = (stats.get("tasks") or {}).get(inst) or {}
        per[inst]["primary_target"] = t.get("target")
    return {"totals": tot, "institutes": per, "broken_lines": broken}


def _load_failures(path: Path) -> list:
    return _jl(path)[0]


def _last_snapshot(path: Path):
    rows = [r for r in _jl(path)[0] if r.get("source") == "snapshot"]
    return rows[-1] if rows else None


def audit(cur: dict, prev, ts: str) -> list:
    """직전 스냅샷과 비교해 새로 생긴 이상만 실패로 남긴다."""
    out, day = [], ts[:10]
    prev_broken = (prev or {}).get("broken_lines", {})
    for f, n in cur["broken_lines"].items():
        d = n - prev_broken.get(f, 0)
        if d > 0:
            out.append({"key": f"audit:broken:{f}:{n}", "stage": "data_quality", "kind": "broken_lines",
                        "inst": next((i for i in INSTS if i in f), None), "count": d,
                        "detail": f"{f}에 깨진 JSON 줄 {d}개 (누적 {n})"})
    for inst, v in cur["institutes"].items():
        before = (((prev or {}).get("institutes") or {}).get(inst) or {}).get("empty_block_rows", 0)
        d = v["empty_block_rows"] - before
        if prev is not None and d > 0:
            out.append({"key": f"audit:empty_block:{inst}:{v['empty_block_rows']}", "stage": "backfill",
                        "kind": "empty_block", "inst": inst, "count": d,
                        "detail": f"초록 빈 값이 {EMPTY_BLOCK}편 이상 연속으로 {d}편 새로 기록됨 (보강 호출 실패 의심)"})
    for f in out:
        f.update({"ts": ts, "date": day, "source": "audit", "resolved": False})
    return out


def github_failures(ts: str) -> list:
    """GitHub Actions 실패 회차 (최근 100건 중 실패). 토큰이 없거나 권한이 없으면 빈 목록."""
    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        return []
    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{repo}/actions/runs?status=failure&per_page=100",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                     "User-Agent": "metrics-snapshot"})
        with urllib.request.urlopen(req, timeout=30) as r:
            runs = json.load(r).get("workflow_runs", [])
    except Exception as e:
        print(f"  (GitHub 실패 조회 생략: {e})")
        return []
    out = []
    for w in runs:
        created = w.get("created_at") or ts
        out.append({"key": f"github:{w.get('id')}", "ts": created, "date": created[:10],
                    "stage": "workflow", "kind": "workflow_failed", "inst": None, "count": 1,
                    "detail": f"{w.get('name')} 실패 · 브랜치 {w.get('head_branch')} · {w.get('event')}",
                    "url": w.get("html_url"), "source": "github", "resolved": False})
    return out


def record(repo, run_failures=None, ts=None) -> dict:
    """스냅샷 1줄 추가 + 새 실패 기록 추가. 반환: 이번에 추가된 실패 수 등."""
    repo = Path(repo)
    ts = ts or _now()
    mdir = repo / "labels" / "metrics"
    mdir.mkdir(parents=True, exist_ok=True)
    daily, fail_p = mdir / "daily.jsonl", mdir / "failures.jsonl"

    cur = compute(repo)
    prev = _last_snapshot(daily)
    new = []
    for f in run_failures or []:
        new.append({"key": f"pipeline:{ts}:{f['stage']}:{f.get('inst')}:{f['kind']}", "ts": ts, "date": ts[:10],
                    "source": "pipeline", "resolved": False, **f})
    new += audit(cur, prev, ts)
    new += github_failures(ts)

    have = {f.get("key") for f in _load_failures(fail_p)}
    added = [f for f in new if f["key"] not in have]
    if added:
        with fail_p.open("a", encoding="utf-8") as fh:
            for f in sorted(added, key=lambda x: x["ts"]):
                fh.write(json.dumps(f, ensure_ascii=False) + "\n")

    snap = {"ts": ts, "date": ts[:10], "source": "snapshot", **cur,
            "run_failures": sum(f.get("count", 0) for f in (run_failures or [])),
            "new_failure_records": len(added)}
    with daily.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(snap, ensure_ascii=False) + "\n")
    return {"totals": cur["totals"], "new_failures": len(added)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".")
    args = ap.parse_args()
    res = record(Path(args.repo).resolve())
    print(json.dumps(res, ensure_ascii=False))


if __name__ == "__main__":
    main()
