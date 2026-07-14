#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
openalex_collect — 논문 실수집 에이전트 (매 1분 100편, 누적·재개형)

동작:
  · GitHub Actions에서 실행 (기본 55분/회, 매시 자동 + 수동 시작 가능)
  · 10분마다 OpenAlex에서 100편 수집 → `data` 브랜치 live/에 즉시 push
    → 관제센터가 재배포 없이 10분 단위로 실시간 갱신 (main 커밋 아님!)
  · 수집 순서: ① K-water 소속 전체(2020~) → ② 7개 연구소 대표키워드 최근1년
  · 커서(cursor)를 state.json에 저장 → 끊겨도/재시작해도 이어서 누적
  · 전 작업 완료 시 이후 실행은 심박만 남기고 조기 종료 (정직)

산출 (data 브랜치):
  live/openalex/papers_<tag>.jsonl   수집 논문 (append-only)
  live/openalex/state.json           커서·진행 상태 (재개용)
  live/openalex/stats.json           집계 → 관제센터 KPI
  live/agents/openalex_collector.json  1분 심박 → 함대 카드·활동피드
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import requests

REPO_DIR = Path(__file__).resolve().parents[1]
API = "https://api.openalex.org/works"
MAILTO = "newcave.kwater@gmail.com"
PAGE = 100                                   # 1회 100편
INTERVAL = 600                               # 10분 주기
RUN_MINUTES = int(os.environ.get("RUN_MINUTES", "55"))
RECENT_FROM = "2025-07-01"                   # 관련논문 최근 1년 창
HB_EVENT_EVERY = 1                           # 수집 1회당 피드 이벤트 1개 (10분 간격)

LIVE = Path("/tmp/live_wt")                  # data 브랜치 워크트리


# ─────────────────── git (data 브랜치) ───────────────────
def sh(*cmd, cwd=None) -> bool:
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0:
        print("⚠️ git:", " ".join(cmd[:3]), "→", (r.stderr or r.stdout).strip()[:180])
    return r.returncode == 0


def setup_worktree():
    sh("git", "config", "--global", "user.name", "co-scientist-bot")
    sh("git", "config", "--global", "user.email",
       "co-scientist-bot@users.noreply.github.com")
    if not sh("git", "fetch", "origin", "data:data", cwd=REPO_DIR):
        print("· data 브랜치 최초 생성")
        sh("git", "push", "origin", "HEAD:refs/heads/data", cwd=REPO_DIR)
        sh("git", "fetch", "origin", "data:data", cwd=REPO_DIR)
    sh("git", "worktree", "add", str(LIVE), "data", cwd=REPO_DIR)
    (LIVE / "live" / "openalex").mkdir(parents=True, exist_ok=True)
    (LIVE / "live" / "agents").mkdir(parents=True, exist_ok=True)


def push_live(msg: str):
    sh("git", "add", "-A", cwd=LIVE)
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=LIVE).returncode == 0:
        return
    sh("git", "commit", "-m", msg, cwd=LIVE)
    if not sh("git", "push", "origin", "data", cwd=LIVE):
        sh("git", "pull", "--rebase", "origin", "data", cwd=LIVE)
        sh("git", "push", "origin", "data", cwd=LIVE)


# ─────────────────── 파일 유틸 ───────────────────
def jload(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def jsave(p: Path, obj):
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


# ─────────────────── OpenAlex ───────────────────
def resolve_institution(ror: str):
    try:
        r = requests.get(f"https://api.openalex.org/institutions/ror:{ror}",
                         params={"mailto": MAILTO}, timeout=30)
        if r.status_code == 200:
            j = r.json()
            return j["id"].rsplit("/", 1)[-1], j.get("display_name")
    except Exception as e:
        print("⚠️ 기관해석:", e)
    return None, None


def probe_count(filt: str) -> int:
    r = requests.get(API, params={"filter": filt, "per-page": 1, "mailto": MAILTO}, timeout=30)
    r.raise_for_status()
    return (r.json().get("meta") or {}).get("count", 0)


def fetch_page(filt: str, cursor):
    """100편 1페이지. → (records, next_cursor, total)"""
    r = requests.get(API, params={
        "filter": filt, "per-page": PAGE, "cursor": cursor or "*",
        "sort": "publication_date:desc", "mailto": MAILTO,
        "select": "id,doi,title,publication_year,cited_by_count,type,primary_location",
    }, timeout=30)
    r.raise_for_status()
    j = r.json()
    recs = []
    for w in j.get("results", []):
        src = ((w.get("primary_location") or {}).get("source") or {})
        recs.append({"id": (w.get("id") or "").rsplit("/", 1)[-1],
                     "doi": w.get("doi"), "title": w.get("title"),
                     "year": w.get("publication_year"),
                     "cited": w.get("cited_by_count"),
                     "venue": src.get("display_name"), "type": w.get("type")})
    meta = j.get("meta") or {}
    return recs, meta.get("next_cursor"), meta.get("count", 0)


# ─────────────────── 상태·심박 ───────────────────
def build_tasks(topics):
    ror = (topics.get("kwater_affiliation") or {}).get("openalex_ror", "04dtgat87")
    inst_id, inst_name = resolve_institution(ror)
    tasks = []
    since = ",from_publication_date:2020-01-01"
    cands = ([f"authorships.institutions.lineage:{inst_id}{since}",   # 본체+산하기관 (권장)
              f"institutions.id:{inst_id}{since}"] if inst_id else []) + \
            [f"institutions.ror:https://ror.org/{ror}{since}"]        # 공식 예시 형태
    tasks.append({"tag": "kwater", "kind": "kwater",
                  "name": f"K-water 생산논문 ({inst_name or 'ROR'})",
                  "filter": cands[0], "candidates": cands})
    for inst in topics.get("institutes", []):
        kws = inst.get("openalex_keywords") or []
        if kws:
            tasks.append({"tag": inst["code"], "kind": "related",
                          "name": f"[관련·도메인] {inst.get('name_ko')} '{kws[0]}'",
                          "filter": f"title_and_abstract.search:{kws[0]},"
                                    f"from_publication_date:{RECENT_FROM}"})
    return tasks


def heartbeat(state, cur_name, note, running=True, event=False):
    p = LIVE / "live" / "agents" / "openalex_collector.json"
    ag = jload(p, {})
    now = int(time.time())
    total = sum(t.get("count", 0) for t in state["tasks"].values())
    target = sum(t.get("target", 0) for t in state["tasks"].values())
    kw_c = state["tasks"].get("kwater", {}).get("count", 0)
    kw_t = state["tasks"].get("kwater", {}).get("target", 0)
    done = sum(1 for t in state["tasks"].values() if t.get("done"))
    ag.update(state="run" if running else "idle", last_run=now,
              next_run="매시 자동 (GitHub Actions)" if not running else "10분 후",
              summary=f"논문 실수집 {'가동' if running else '대기'} — {cur_name or '전 작업 완료'}",
              counts={"K-water 생산": kw_c, "관련(도메인)": total - kw_c,
                      "작업": f"{done}/{len(state['tasks'])}"})
    ev = ag.get("events") or []
    if event and note:
        ev.append({"ts": now, "msg": note})
    ag["events"] = ev[-20:]
    jsave(p, ag)
    jsave(LIVE / "live" / "openalex" / "stats.json",
          {"collected_total": total, "target_total": target, "updated": now,
           "kwater_collected": kw_c, "kwater_target": kw_t,
           "related_collected": total - kw_c, "related_target": target - kw_t,
           "tasks": {k: {"count": v.get("count", 0), "target": v.get("target", 0),
                         "done": v.get("done", False)}
                     for k, v in state["tasks"].items()}})


# ─────────────────── 메인 루프 ───────────────────
def main():
    setup_worktree()
    topics = jload(REPO_DIR / "data_seed" / "search_topics.json", {})
    tasks = build_tasks(topics)
    if not tasks:
        print("❌ 작업 없음 (search_topics.json 확인)")
        return 0

    state_p = LIVE / "live" / "openalex" / "state.json"
    state = jload(state_p, {"tasks": {}})
    for t in tasks:
        st = state["tasks"].setdefault(t["tag"], {"cursor": None, "count": 0,
                                                  "target": 0, "done": False})
        if st.get("done") and st.get("count", 0) == 0:           # 과거 오탐 자동 복구
            st.update(done=False, cursor=None, probed=False)
            print(f"↻ self-heal: {t['tag']} 재시도 (0건 완료 이력)")

    deadline = time.monotonic() + RUN_MINUTES * 60
    it = 0
    print(f"▶ 수집 시작 — 최대 {RUN_MINUTES}분, 10분당 {PAGE}편")

    while time.monotonic() < deadline:
        tick = time.monotonic()
        task = next((t for t in tasks if not state["tasks"][t["tag"]]["done"]), None)
        if task is None:
            heartbeat(state, None, "🏁 전 작업 수집 완료 — 대기 전환", running=False, event=(it == 0))
            jsave(state_p, state)
            push_live("🤖 openalex: 전 작업 완료")
            print("🏁 모든 작업 완료")
            return 0

        st = state["tasks"][task["tag"]]
        if task.get("candidates") and not st.get("probed"):      # 0건 아닌 필터 자동 선택
            for f in task["candidates"]:
                try:
                    c = probe_count(f)
                except Exception:
                    continue
                print(f"· 필터 후보({c:,}건): {f[:70]}")
                if c > 0:
                    task["filter"], st["target"] = f, c
                    break
                time.sleep(0.3)
            st["probed"] = True
        try:
            recs, nxt, total_cnt = fetch_page(task["filter"], st["cursor"])
            st["target"] = total_cnt or st["target"]
            if recs:
                with open(LIVE / "live" / "openalex" / f"papers_{task['tag']}.jsonl",
                          "a", encoding="utf-8") as f:
                    for rec in recs:
                        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                st["count"] += len(recs)
            st["cursor"] = nxt
            if not nxt or not recs:
                st["done"] = True
            it += 1
            note = (f"📥 {task['name']} — +{len(recs)}편, "
                    f"작업누적 {st['count']:,}/{st['target']:,}"
                    + ((" ✅ 작업 완료" if st["count"] else " ⚠️ 0건 종료 — 필터 확인 필요") if st["done"] else ""))
            print(f"[{it:03d}]", note)
            heartbeat(state, task["name"], note,
                      event=(it % HB_EVENT_EVERY == 1 or st["done"]))
            jsave(state_p, state)
            push_live(f"🤖 openalex +{len(recs)} ({task['tag']} {st['count']})")
        except Exception as e:
            print("⚠️ 수집 오류(계속):", str(e)[:160])
            heartbeat(state, task["name"], f"⚠️ 일시 오류: {str(e)[:80]}", event=True)
            push_live("🤖 openalex: 일시 오류 기록")

        time.sleep(max(0.0, INTERVAL - (time.monotonic() - tick)))

    heartbeat(state, None, f"⏸️ 이번 회차 종료 — 다음 시각 자동 재개 (누적 유지)",
              running=False, event=True)
    jsave(state_p, state)
    push_live("🤖 openalex: 회차 종료 (재개 예약)")
    print("⏸️ 시간 소진 — 커서 저장, 다음 실행에서 이어서")
    return 0


if __name__ == "__main__":
    sys.exit(main())
