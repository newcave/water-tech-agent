"""
에이전트 상태 프로토콜 — 관제센터의 심장박동

모든 에이전트(크롤러/파서/수집기)가 실행 시작·진행·종료 때 이걸 호출하면
data_seed/agents/<이름>.json 이 갱신되고, GITHUB_TOKEN이 있으면 repo에도 push
→ Streamlit Cloud 관제센터가 30초 내 반영 (진짜 "돌고 있는 것처럼"이 아니라 진짜 돌고 있음)

사용 (각 에이전트 코드에 3줄):
    from agent_status import report
    report("openalex_collector", "run", "K-water 논문 수집 중", {"수집 논문": n}, "페이지 3 처리")
    ...
    report("openalex_collector", "idle", "수집 완료", {"수집 논문": total}, f"완료: {total}건")

환경변수(선택): GITHUB_TOKEN, GITHUB_REPO(기본 newcave/2607alioreport)
"""

import os
import json
import time
import base64
from pathlib import Path

SEED = Path(os.environ.get("SEED_DIR", "data_seed")) / "agents"
REPO = os.environ.get("GITHUB_REPO", "newcave/2607alioreport")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
MAX_EVENTS = 40


def report(agent: str, state: str, summary: str = None,
           counts: dict = None, event_msg: str = None, next_run: str = None,
           push: bool = True):
    """state: run | idle | standby | error"""
    SEED.mkdir(parents=True, exist_ok=True)
    p = SEED / f"{agent}.json"
    d = json.loads(p.read_text(encoding="utf-8")) if p.exists() else \
        {"agent": agent, "events": [], "counts": {}}

    d["state"] = state
    d["last_run"] = time.time()
    if summary is not None:
        d["summary"] = summary
    if counts:
        d["counts"] = {**d.get("counts", {}), **counts}
    if next_run is not None:
        d["next_run"] = next_run
    if event_msg:
        d.setdefault("events", []).append({"ts": time.time(), "msg": event_msg})
        d["events"] = d["events"][-MAX_EVENTS:]

    p.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")

    if push and TOKEN:
        _push_github(f"data_seed/agents/{agent}.json", p.read_text(encoding="utf-8"))
    return d


def _push_github(path: str, content: str):
    import requests
    url = f"https://api.github.com/repos/{REPO}/contents/{path}"
    h = {"Authorization": f"Bearer {TOKEN}"}
    body = {"message": f"status: {path.split('/')[-1]}",
            "content": base64.b64encode(content.encode()).decode()}
    r0 = requests.get(url, headers=h, timeout=10)
    if r0.status_code == 200:
        body["sha"] = r0.json()["sha"]
    try:
        requests.put(url, headers=h, json=body, timeout=15)
    except Exception as e:
        print(f"[agent_status] push 실패(로컬은 저장됨): {e}")


if __name__ == "__main__":
    # 자기검증
    os.environ.pop("GITHUB_TOKEN", None)
    report("selftest", "run", "자기검증", {"n": 1}, "이벤트1", push=False)
    report("selftest", "idle", counts={"n": 2}, event_msg="이벤트2", push=False)
    d = json.loads((SEED / "selftest.json").read_text())
    assert d["state"] == "idle" and d["counts"]["n"] == 2 and len(d["events"]) == 2
    (SEED / "selftest.json").unlink()
    print("agent_status self-check OK")
