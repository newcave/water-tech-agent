#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
oa_rising 심박 — 관제센터 '에이전트 함대' 카드·활동 피드·🌊 흐름 화면용 상태 (data 브랜치 live/agents/oa_rising.json)

oa-rising 워크플로가 실행마다(토큰이 없어도, 실패해도) 부른다. 표준 라이브러리만 쓴다.
env: OA_HB_PREV  이전 심박 파일 (없어도 됨 — 활동 기록을 이어 붙이는 데만 씀)
     OA_HB_OUT   출력 파일
     OA_TOKEN_OK 1 = 토큰 있음 · 0 = 없음
     OA_JOB_OK   1 = 연동 단계 성공 · 0 = 실패
     OA_CHANGED  1 = 집계가 바뀌어 커밋함 · 0 = 변경 없음
"""
import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "data_seed" / "oa_rising" / "index.json"
FIELDS_TOTAL = 6          # openalex 분야 수 (AI·수자원환경·물인프라안전·상하수도·물에너지·경영)


def _load(p) -> dict:
    try:
        return json.loads(Path(p).read_text(encoding="utf-8")) if p and Path(p).exists() else {}
    except Exception:
        return {}


def main() -> int:
    now = int(time.time())
    prev = _load(os.environ.get("OA_HB_PREV"))
    idx = _load(INDEX)
    srcs = idx.get("sources") or []
    main_src = srcs[0] if srcs else {}
    n_fields = sum(1 for s in srcs if s.get("inst"))
    token_ok = os.environ.get("OA_TOKEN_OK") == "1"
    job_ok = os.environ.get("OA_JOB_OK", "1") == "1"
    changed = os.environ.get("OA_CHANGED") == "1"
    counts = {"연동 논문": main_src.get("documents") or 0, "Rising 용어": main_src.get("rising") or 0,
              "커뮤니티": main_src.get("clusters") or 0, "분야별 결과": f"{n_fields}/{FIELDS_TOTAL}"}
    if not token_ok:
        state, summary = "standby", "OPENALEX_DATA_TOKEN 없음 — openalex 연동 대기"
        msg = "⏸ openalex 연동 건너뜀 (토큰 없음)"
    elif not job_ok:
        state, summary = "error", "openalex 연동 실패 — Actions 로그 확인"
        msg = "⚠️ openalex 연동 실패"
    else:
        state = "idle"
        summary = (f"openalex 연동 — {main_src.get('title', '')} {counts['연동 논문']:,}편 · Rising {counts['Rising 용어']:,} · "
                   f"커뮤니티 {counts['커뮤니티']} · 분야별 결과 {n_fields}/{FIELDS_TOTAL}")
        msg = (f"🔭 openalex 연동 {'갱신' if changed else '확인 (변경 없음)'} — Rising {counts['Rising 용어']:,} · "
               f"커뮤니티 {counts['커뮤니티']} · {counts['연동 논문']:,}편")
    out = {"agent": "oa_rising", "state": state, "summary": summary, "counts": counts, "last_run": now,
           "next_run": "매주 월 07:23 KST (GitHub Actions)",
           "events": ((prev.get("events") or [])[-19:]) + [{"ts": now, "msg": msg}]}
    Path(os.environ.get("OA_HB_OUT", "oa_rising_hb.json")).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[oa_rising_heartbeat] {state} · {msg}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
