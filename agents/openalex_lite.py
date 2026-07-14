#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
openalex_lite — GitHub Actions에서 6시간마다 실행되는 경량 논문 에이전트 (STEP A)

하는 일 (전부 실측 — 연출 없음):
  1. OpenAlex에서 K-water(ROR 04dtgat87) 소속 논문 수 확인 (2020~, 키 불필요)
  2. search_topics.json의 7개 연구소 대표 키워드로 최근 1년 관련논문 수 확인 (트렌드 감시)
  3. data_seed/agents/openalex_collector.json 갱신 → 관제센터 심박
  4. data_seed/openalex_trends.json 기록 → 추후 위크시그널 분석 재료
  5. summary.json에는 papers_available(실측 모집단)만 기록 — '수집됨(papers)'과 구분 (정직 원칙)

본격 수집기 코드 입고 시 이 파일만 교체하면 됨. API 오류 시에도 죽지 않고
오류 이벤트를 기록해 커밋 (관제센터에 정직하게 표시).
"""
import json
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "data_seed"
API = "https://api.openalex.org/works"
MAILTO = "newcave.kwater@gmail.com"          # OpenAlex polite pool (아무 연락용 메일이면 됨)
RECENT_FROM = "2025-07-01"                   # '최근 1년' 트렌드 창

AGENT = SEED / "agents" / "openalex_collector.json"
TRENDS = SEED / "openalex_trends.json"
SUMMARY = SEED / "summary.json"


def load(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def save(p: Path, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def resolve_institution(ror: str):
    """ROR → OpenAlex 기관 ID·이름 해석 (축약 ROR 필터가 0건을 내는 문제의 근본 해결)."""
    try:
        r = requests.get(f"https://api.openalex.org/institutions/ror:{ror}",
                         params={"mailto": MAILTO}, timeout=30)
        if r.status_code == 200:
            j = r.json()
            return j["id"].rsplit("/", 1)[-1], j.get("display_name")
    except Exception:
        pass
    return None, None


def oa_count(filter_expr: str) -> int:
    """OpenAlex works 카운트 (per-page=1로 meta.count만)."""
    r = requests.get(API, params={"filter": filter_expr, "per-page": 1, "mailto": MAILTO},
                     timeout=30)
    r.raise_for_status()
    return int(r.json()["meta"]["count"])


def main():
    now = int(time.time())
    topics = load(SEED / "search_topics.json", {})
    ror = (topics.get("kwater_affiliation") or {}).get("openalex_ror", "04dtgat87")
    errors = []

    # ── 1. K-water 소속 논문 (2020~): ROR → 기관ID 해석 후 검색 ──
    n_kwater, inst_name = None, None
    inst_id, inst_name = resolve_institution(ror)
    try:
        since = ",from_publication_date:2020-01-01"
        cands = ([f"authorships.institutions.lineage:{inst_id}{since}",
                  f"institutions.id:{inst_id}{since}"] if inst_id else []) + \
                [f"institutions.ror:https://ror.org/{ror}{since}"]
        for f in cands:                                   # 0건 아닌 필터 채택 (3단 폴백)
            n_kwater = oa_count(f)
            print(f"· {n_kwater:,}건 ← {f[:70]}")
            if n_kwater:
                break
        if n_kwater == 0:
            errors.append("소속검색 0건 — ROR/기관ID 확인 필요")
    except Exception as e:
        errors.append(f"소속검색: {e}")

    # ── 2. 연구소별 대표 키워드 × 최근 1년 (트렌드 감시) ──
    per_inst, n_related = {}, 0
    for inst in topics.get("institutes", []):
        kws = inst.get("openalex_keywords") or []
        if not kws:
            continue
        kw = kws[0]                                   # 대표 키워드 1개 (경량 유지)
        try:
            c = oa_count(f"title_and_abstract.search:{kw},from_publication_date:{RECENT_FROM}")
            per_inst[inst["code"]] = {"name": inst.get("name_ko"), "keyword": kw,
                                      "recent_1y": c}
            n_related += c
            print(f"   {inst['code']} {inst.get('name_ko','')}: '{kw}' 최근1년 {c:,}건")
            time.sleep(0.4)                           # polite
        except Exception as e:
            errors.append(f"{inst['code']}: {e}")

    ok = n_kwater is not None and not errors

    # ── 3. 에이전트 심박 갱신 ──
    ag = load(AGENT, {})
    ev = ag.get("events") or []
    if n_kwater is not None:
        ag.update(state="idle", last_run=now, next_run="6시간 주기 (GitHub Actions)",
                  summary=f"OpenAlex 실측 감시 [{inst_name or 'ROR 폴백'}] — 논문 {n_kwater:,}건(2020~) · "
                          f"7개 소 키워드 트렌드 추적",
                  counts={"K-water 논문(실측)": n_kwater, "관련논문(최근1년)": n_related})
        msg = (f"☁️ 정기 실측 — K-water {n_kwater:,}건 · 관련(최근1년) {n_related:,}건"
               + (f" · 일부 오류 {len(errors)}" if errors else ""))
    else:
        ag["state"] = "error"
        ag["last_run"] = now
        msg = "⚠️ OpenAlex API 오류: " + "; ".join(str(e)[:60] for e in errors[:2])
    ev.append({"ts": now, "msg": msg})
    ag["events"] = ev[-20:]                           # 최근 20개만 유지
    save(AGENT, ag)

    # ── 4. 트렌드 기록 (위크시그널 재료) ──
    if per_inst:
        tr = load(TRENDS, {"history": []})
        tr["updated"] = now
        tr["window_from"] = RECENT_FROM
        tr["institutes"] = per_inst
        tr.setdefault("history", []).append(
            {"ts": now, "kwater": n_kwater, "related_1y": n_related})
        tr["history"] = tr["history"][-120:]          # ~30일치(6h 주기)
        save(TRENDS, tr)

    # ── 5. summary: 실측 모집단만 (수집됨 papers와 구분 — 정직 원칙) ──
    if n_kwater is not None:
        sm = load(SUMMARY, {"totals": {}})
        sm.setdefault("totals", {})["papers_available"] = n_kwater
        sm["generated_at"] = now
        save(SUMMARY, sm)

    print("결과:", "정상" if ok else f"부분 오류 {errors}")
    return 0                                          # 오류도 기록·커밋되도록 항상 0


if __name__ == "__main__":
    sys.exit(main())
