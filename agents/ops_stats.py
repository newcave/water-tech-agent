#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ops_stats — 에이전트 '수집 현황판' 재료: 지금까지 에이전트가 실제로 한 일을 건수로 모아 live/ops/ops.json에 쓴다 (2026-11-01)

재료 (모두 이 저장소 안의 실제 기록 — 숫자를 만들지 않는다):
  · git 기록 (main + data 브랜치)       봇·사람 커밋을 일자·시간대·에이전트별로 셈 (이 현황판 자신의 커밋은 뺌)
  · GitHub Actions 실행 기록 (API)        워크플로별 실행 수·성공/실패·걸린 시간, 최근 실행 로그
  · data 브랜치 labels/metrics/daily.jsonl     날짜별 누적 수집·초록 확보·LLM 추출·도메인 배정 (연구소별)
  · data 브랜치 labels/pipeline_runs.jsonl     라벨링 파이프라인 회차별 처리량·걸린 시간
  · data 브랜치 labels/metrics/failures.jsonl  장애 기록과 복구 여부
  · data 브랜치 live/openalex/stats.json       논문 수집 작업별 목표 대비 수집 (12개 핵심 저널·7개 연구소·K-water)
  · main data_seed (kci_*·oa_rising·tech_map·wcs_assets·agents) 공개 집계와 에이전트 사건 기록
출력은 건수·시각·상태뿐 (논문 제목·초록·KCI 원문 없음). 실행: python agents/ops_stats.py  (GH_TOKEN 있으면 Actions 기록 포함)
"""
import json
import os
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(os.environ.get("OPS_OUT") or (ROOT / "live_local" / "ops.json"))
REPO = os.environ.get("GITHUB_REPOSITORY", "newcave/water-tech-agent")
TOKEN = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
KST = timezone(timedelta(hours=9))
DATA = os.environ.get("OPS_DATA_REF", "origin/data")
MAIN = os.environ.get("OPS_MAIN_REF", "origin/main")
SELF_MSG = "🛰️ ops"                               # 이 현황판이 남기는 커밋 — 활동 집계에서 뺌

AGENT_OF = [                                       # (커밋 제목 앞부분, 에이전트 키)
    ("🤖 openalex", "collector"), ("🤖 heartbeat", "heartbeat"), ("labels: pipeline", "labels"),
    ("🤖 tech_map", "tech_map"), ("🤖 kci", "kci"), ("🤖 trend", "kci"), ("🤖 oa_rising", "oa_rising"),
    ("🧾 HITL", "hitl"), ("🤖 oa_rising 심박", "oa_rising"),
]
AGENT_LABEL = {"collector": "논문 수집 (OpenAlex)", "heartbeat": "해외 트렌드 심박", "labels": "LLM 라벨링 파이프라인",
               "tech_map": "기술 지도", "kci": "KCI 국내 학회지", "oa_rising": "상승 주제 연동", "hitl": "사람 판정 대장",
               "bot_other": "기타 자동 작업", "dev": "개발·개선 (사람+Claude)"}
WF_LABEL = {"openalex-collector": "논문 수집", "agents-heartbeat": "해외 트렌드 심박", "labels-pipeline": "LLM 라벨링",
            "tech-map": "기술 지도", "kci-rising": "KCI 상승 분석", "kci-counts": "KCI 건수", "kci-kwater-review": "K-water 소속 검토",
            "kci-probe": "KCI 탐색", "kci-affil-probe": "KCI 소속 탐색", "trend-rising": "트렌드 상승", "oa-rising": "상승 주제 연동",
            "hitl-ledger": "판정 대장", "guard": "보안 검사", "ops-stats": "수집 현황판"}
INST = ["INST-01", "INST-02", "INST-03", "INST-04", "INST-05", "INST-06", "INST-07"]


def git(*args) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=False).stdout


def show(ref: str, path: str):
    t = git("show", f"{ref}:{path}")
    return t if t else None


def jload(ref, path, default=None):
    t = show(ref, path)
    try:
        return json.loads(t) if t else default
    except Exception:
        return default


def jsonl(ref, path) -> list:
    out = []
    for line in (show(ref, path) or "").splitlines():
        try:
            out.append(json.loads(line))
        except Exception:
            pass
    return out


def kst(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, KST)


def iso_ts(s: str):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


# ── 1. 커밋 ──────────────────────────────────────────────────────────────
def commits():
    seen, rows = set(), []
    for ref in (MAIN, DATA):
        for line in git("log", ref, "--format=%H\x1f%at\x1f%an\x1f%s").splitlines():
            h, at, an, s = (line.split("\x1f") + ["", "", "", ""])[:4]
            if not h or h in seen or s.startswith(SELF_MSG):
                continue
            seen.add(h)
            if "bot" in an.lower():
                key = next((k for p, k in AGENT_OF if s.startswith(p)), "bot_other")
            else:
                key = "dev"
            rows.append((int(at), key))
    return rows


# ── 2. Actions 실행 기록 ──────────────────────────────────────────────────
def runs():
    f = os.environ.get("OPS_RUNS_FILE")                  # 로컬 시험용 (gh api로 받아 둔 목록)
    if f and Path(f).exists():
        return json.loads(Path(f).read_text())
    if not TOKEN:
        return []
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github+json"})
    out = []
    try:
        wfs = s.get(f"https://api.github.com/repos/{REPO}/actions/workflows", timeout=30).json().get("workflows", [])
    except Exception as e:
        print("⚠️ workflows:", e)
        return []
    for w in wfs:
        for page in range(1, 31):                          # 워크플로마다 최대 3,000회
            try:
                r = s.get(f"https://api.github.com/repos/{REPO}/actions/workflows/{w['id']}/runs",
                          params={"per_page": 100, "page": page}, timeout=30)
                items = r.json().get("workflow_runs", []) if r.status_code == 200 else []
            except Exception:
                items = []
            for x in items:
                out.append({"name": x.get("name") or w["name"], "event": x.get("event"), "status": x.get("status"),
                            "conclusion": x.get("conclusion"), "created_at": x.get("created_at"),
                            "run_started_at": x.get("run_started_at"), "updated_at": x.get("updated_at"),
                            "branch": x.get("head_branch")})
            if len(items) < 100:
                break
    return out


def main():
    now = time.time()
    rows = commits()
    first = min((t for t, _ in rows), default=now)

    # 일자별·시간대별 커밋
    daily_c = defaultdict(Counter)
    hourweek = [[0] * 24 for _ in range(7)]
    for t, k in rows:
        d = kst(t)
        daily_c[d.strftime("%Y-%m-%d")][k] += 1
        hourweek[d.weekday()][d.hour] += 1
    by_agent = Counter(k for _, k in rows)

    # Actions 실행
    rr = runs()
    wf = defaultdict(lambda: {"runs": 0, "success": 0, "failure": 0, "other": 0, "sec": 0.0, "max_s": 0.0, "durs": []})
    daily_r = defaultdict(Counter)
    daily_min = Counter()
    recent = []
    for x in rr:
        t0, t1 = iso_ts(x.get("run_started_at") or x.get("created_at") or ""), iso_ts(x.get("updated_at") or "")
        if not t0:
            continue
        dur = max(0.0, (t1 or t0) - t0) if x.get("status") == "completed" else max(0.0, now - t0)
        name = x.get("name") or "?"
        w = wf[name]
        w["runs"] += 1
        c = x.get("conclusion")
        w["success" if c == "success" else "failure" if c in ("failure", "timed_out") else "other"] += 1
        w["sec"] += dur
        w["max_s"] = max(w["max_s"], dur)
        w["durs"].append(round(dur))
        day = kst(t0).strftime("%Y-%m-%d")
        daily_r[day][name] += 1
        daily_min[day] += dur / 60
        recent.append({"ts": int(t0), "wf": name, "label": WF_LABEL.get(name, name), "event": x.get("event"),
                       "status": x.get("status"), "conclusion": c, "dur_s": round(dur)})
    recent.sort(key=lambda r: -r["ts"])
    workflows = {}
    for name, w in wf.items():
        ds = sorted(w["durs"])
        workflows[name] = {"label": WF_LABEL.get(name, name), "runs": w["runs"], "success": w["success"], "failure": w["failure"],
                           "other": w["other"], "minutes": round(w["sec"] / 60, 1), "avg_s": round(w["sec"] / max(1, w["runs"])),
                           "p50_s": ds[len(ds) // 2] if ds else 0, "max_s": round(w["max_s"]),
                           "durs": ds[-300:] if len(ds) > 300 else ds}

    # 라벨링 파이프라인 · 성장 · 장애
    daily_m = jsonl(DATA, "labels/metrics/daily.jsonl")
    growth = {}
    for m in daily_m:                                  # 날짜별 마지막 기록
        if m.get("date"):
            growth[m["date"]] = m
    growth_rows = []
    for d in sorted(growth):
        m = growth[d]
        t = m.get("totals") or {}
        growth_rows.append({"d": d, "collected": t.get("collected"), "abstract_ok": t.get("abstract_ok"),
                            "extracted": t.get("extracted"), "assigned": t.get("assigned"),
                            "inst": {c: (m.get("institutes") or {}).get(c, {}).get("collected") for c in INST}
                            if m.get("institutes") else None})
    pruns = jsonl(DATA, "labels/pipeline_runs.jsonl")
    pipeline = [{"ts": r.get("ts"), "forward": r.get("forward", 0), "hist": r.get("hist", 0), "hist_year": r.get("hist_year"),
                 "backfilled": r.get("backfilled", 0), "extracted": r.get("extracted", 0), "assigned": r.get("assigned", 0),
                 "total": r.get("total"), "dur_s": r.get("duration_s"), "fail": r.get("failures", 0)} for r in pruns]
    fails = jsonl(DATA, "labels/metrics/failures.jsonl")
    fsum = {"total": len(fails), "resolved": sum(1 for f in fails if f.get("resolved")),
            "items": sum(int(f.get("count") or 0) for f in fails),
            "by_stage": dict(Counter(f.get("stage") or "?" for f in fails)), "by_kind": dict(Counter(f.get("kind") or "?" for f in fails)),
            "recent": [{"ts": iso_ts(f.get("ts") or "") , "stage": f.get("stage"), "kind": f.get("kind"), "count": f.get("count"),
                        "resolved": bool(f.get("resolved"))} for f in fails[-12:]]}

    # 수집 작업 목표 대비
    stats = jload(DATA, "live/openalex/stats.json", {}) or {}
    jn = {j["code"]: j.get("name") for j in (jload(MAIN, "data_seed/water_journals.json", {}) or {}).get("journals", [])}
    jn.update({c: n for c, n in zip(INST, ["경영", "수자원환경", "상하수도", "물인프라안전", "물에너지", "수자원위성", "AI"])})
    tasks = [{"code": k, "name": jn.get(k) or ("K-water 소속" if k == "kwater" else k), "count": v.get("count"), "target": v.get("target")}
             for k, v in (stats.get("tasks") or {}).items()]

    # 공개 집계에서 가져오는 규모
    kr = jload(MAIN, "data_seed/kci_rising.json", {}) or {}
    kk = jload(MAIN, "data_seed/kci_kwater.json", {}) or {}
    oa = jload(MAIN, "data_seed/oa_rising/water_paper.json", {}) or {}
    tp = jload(MAIN, "data_seed/tech_map/papers.json", {}) or {}
    tj = jload(MAIN, "data_seed/tech_map/journals.json", {}) or {}
    wcs = jload(MAIN, "data_seed/wcs_assets.json", {}) or {}
    tr = jload(MAIN, "data_seed/openalex_trends.json", {}) or {}
    kci_docs = sum((kr.get("scopes") or {}).get("J11+J12", {}).get("denominator") or [])

    # 에이전트 사건 기록 (main data_seed + data 브랜치 live)
    events = []
    for f in git("ls-tree", "--name-only", f"{MAIN}:data_seed/agents").split():
        a = jload(MAIN, f"data_seed/agents/{f}", {}) or {}
        for e in (a.get("events") or [])[-15:]:
            if isinstance(e.get("ts"), (int, float)):
                events.append({"ts": int(e["ts"]), "agent": f[:-5], "msg": str(e.get("msg", ""))[:140]})
    live_c = jload(DATA, "live/agents/openalex_collector.json", {}) or {}
    for e in (live_c.get("events") or [])[-30:]:
        if isinstance(e.get("ts"), (int, float)):
            events.append({"ts": int(e["ts"]), "agent": "openalex_collector", "msg": str(e.get("msg", ""))[:140]})
    events = sorted({(e["ts"], e["agent"], e["msg"]): e for e in events}.values(), key=lambda e: -e["ts"])[:60]
    tm_calls = sum(int(m.group(1)) for e in ((jload(MAIN, "data_seed/agents/tech_map.json", {}) or {}).get("events") or [])
                   if (m := __import__("re").search(r"검색 (\d+)회", str(e.get("msg", "")))))

    # 월별
    monthly = defaultdict(lambda: {"commits": 0, "runs": 0, "run_min": 0.0})
    for d, c in daily_c.items():
        monthly[d[:7]]["commits"] += sum(v for k, v in c.items() if k != "dev")
    for d, c in daily_r.items():
        monthly[d[:7]]["runs"] += sum(c.values())
        monthly[d[:7]]["run_min"] += daily_min[d]
    prev = None
    for g in growth_rows:
        m = monthly[g["d"][:7]]
        m.setdefault("collected_end", g["collected"])
        m["collected_end"] = g["collected"]
        m["assigned_end"] = g["assigned"]
    for k in sorted(monthly):
        m = monthly[k]
        if m.get("collected_end") is not None:
            m["collected_add"] = (m["collected_end"] - prev[0]) if prev else m["collected_end"]
            m["assigned_add"] = (m["assigned_end"] - prev[1]) if prev else m["assigned_end"]
            prev = (m["collected_end"], m["assigned_end"])
        m["run_min"] = round(m["run_min"], 1)

    days = sorted(set(daily_c) | set(daily_r))
    last_g = growth_rows[-1] if growth_rows else {}
    data_bytes = 0
    if TOKEN:                                          # 파일 크기는 API 트리로 (내용을 받지 않음)
        try:
            tree = requests.get(f"https://api.github.com/repos/{REPO}/git/trees/data", params={"recursive": 1},
                                headers={"Authorization": f"Bearer {TOKEN}"}, timeout=30).json().get("tree", [])
            data_bytes = sum(int(x.get("size") or 0) for x in tree if x.get("type") == "blob")
        except Exception:
            data_bytes = 0
    if not data_bytes and not os.environ.get("CI"):
        data_bytes = sum(int(p.split()[3]) for p in git("ls-tree", "-r", "-l", DATA).splitlines()
                         if len(p.split()) >= 5 and p.split()[3].isdigit())
    out = {
        "_doc": "에이전트 수집 현황판 재료 — 저장소의 실제 기록(git·Actions·파이프라인 로그·공개 집계)을 건수로만 모음. ops_stats.py가 매시 갱신",
        "updated": int(now), "since": kst(first).strftime("%Y-%m-%d"),
        "days_active": len(days), "days_since": (kst(now).date() - kst(first).date()).days + 1,
        "totals": {
            "commits_bot": sum(v for k, v in by_agent.items() if k != "dev"), "commits_dev": by_agent.get("dev", 0),
            "runs": len(rr), "run_minutes": round(sum(w["sec"] for w in wf.values()) / 60),
            "workflows": len(workflows),
            "papers_core": stats.get("collected_total"), "papers_core_target": stats.get("target_total"),
            "journal_papers": stats.get("journal_collected"), "related_papers": stats.get("related_collected"),
            "kwater_papers": stats.get("kwater_collected"),
            "label_rows": last_g.get("collected"), "abstract_ok": last_g.get("abstract_ok"),
            "llm_extracted": last_g.get("extracted"), "assigned": last_g.get("assigned"),
            "pipeline_runs": len(pipeline), "pipeline_hours": round(sum((p["dur_s"] or 0) for p in pipeline) / 3600, 1),
            "kci_docs": kci_docs, "kwater_kci": kk.get("total"), "oa_docs": oa.get("documents"),
            "tech_map_calls": tm_calls, "journal_metrics": len(tj.get("journals") or {}),
            "venues": (tj.get("coverage") or {}).get("venues"), "trend_keywords": sum(len((e.get("by_kw") or {})) for e in (tr.get("institutes") or {}).values()),
            "wcs_assets": sum(i.get("count", 0) for i in wcs.get("items", [])),
            "data_mb": round(data_bytes / 1e6, 1),
            "failures": fsum["total"], "failures_resolved": fsum["resolved"],
        },
        "agents": {k: {"label": AGENT_LABEL.get(k, k), "commits": v} for k, v in by_agent.most_common()},
        "daily": [{"d": d, "c": dict(daily_c.get(d, {})), "r": sum(daily_r.get(d, {}).values()),
                   "rmin": round(daily_min.get(d, 0), 1)} for d in days],
        "hourweek": hourweek,
        "monthly": [{"m": k, **v} for k, v in sorted(monthly.items())],
        "growth": growth_rows,
        "pipeline": pipeline,
        "workflows": workflows,
        "recent": recent[:80],
        "events": events,
        "failures": fsum,
        "tasks": tasks,
        "inst_now": (growth[max(growth)].get("institutes") if growth else {}),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    t = out["totals"]
    print(f"✅ ops.json — {out['since']}부터 {out['days_since']}일 · 봇 커밋 {t['commits_bot']:,} · 실행 {t['runs']:,}회 "
          f"({t['run_minutes']:,}분) · 라벨 {t['assigned']} · {OUT.stat().st_size / 1024:.0f}KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
