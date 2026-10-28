#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
openalex_lite — GitHub Actions에서 6시간마다 실행되는 경량 논문 에이전트 (STEP A)

하는 일 (전부 실측 — 연출 없음):
  1. OpenAlex에서 K-water(ROR 04dtgat87) 소속 논문 수 확인 (2020~, 키 불필요)
  2. search_topics.json의 7개 연구소 대표 키워드로 최근 1년 관련논문 수 확인 (트렌드 감시)
     + 최근 5년(TREND_YEARS) 연도별 실측(group_by=publication_year) — 연구소별 5년 추이 (v3.12)
     + 같은 5년의 OpenAlex 전체 논문 수(해외 전체 기준선) — 연구소 키워드의 상대 성장 비교용
     + 연구소 키워드 5~6개 전체: 키워드별 연도 수(by_kw)와 합집합(OR 검색, by_year_all) — 소별 트렌드 (v3.13)
       (by_year·recent_1y는 수집 기준인 대표 키워드 1개 그대로 — 수집률 비교용)
     + 피인용 질 (v3.15): 같은 검색에 '피인용 상위 10%' 조건을 더한 연도별 수 — by_year_all_top10 · by_kw_top10,
       OpenAlex 전체 기준선 baseline.by_year_top10, K-water 소속 논문 kwater_citation
       (OpenAlex citation_normalized_percentile: 같은 분야·같은 출판연도 논문 안에서의 피인용 백분위 → 세계 평균 약 10%)
  2b. water_journals.json의 수자원 12개 핵심 저널 × 연도 논문 수 실측 (트렌드 분석 분모 코퍼스)
      — 연관성·트렌드 분석 자체는 아직 미실시, 분모만 기록
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

from water_journals import load_registry, resolve_sources, source_filter

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "data_seed"
API = "https://api.openalex.org/works"
MAILTO = "newcave.kwater@gmail.com"          # OpenAlex polite pool (아무 연락용 메일이면 됨)
RECENT_FROM = "2025-07-01"                   # '최근 1년' 트렌드 창
TREND_YEARS = 5                              # 연구소별 연도 추이 창 (올해 포함 5개 연도, 2026-10-27 사용자 지정)
TOP10 = "citation_normalized_percentile.is_in_top_10_percent:true"   # 피인용 상위 10% (분야·연도 보정, OpenAlex 계산)
# OpenAlex 무키 사용량은 하루 $0.10(검색 1건 ≈ $0.001 → 검색 약 100건). 지금 실측이 검색 약 56건을 쓰므로
# 피인용(검색 약 7건/연구소)은 한 번에 다 하지 않고 6시간 실행마다 연구소를 4묶음으로 돌려 하루에 한 바퀴 (2026-10-28 429 확인)
CIT_SLOTS = 4

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


def oa_by_year(filter_expr: str) -> dict:
    """OpenAlex works 연도별 카운트 (group_by=publication_year) → {연도: 건수}."""
    r = requests.get(API, params={"filter": filter_expr, "group_by": "publication_year",
                                  "mailto": MAILTO}, timeout=30)
    r.raise_for_status()
    return {str(g["key"]): int(g["count"]) for g in r.json().get("group_by", [])}


def union_search(kws: list) -> str:
    """키워드 여러 개 → OpenAlex 불리언 검색 (각 키워드는 지금과 같은 띄어쓰기 검색, OR로 묶음)."""
    return " OR ".join(f"({k})" for k in kws)


def union_ok(u: dict, by_kw: dict, years: list) -> bool:
    """합집합 검산: 키워드별 최댓값 이상, 합계 이하 (OR가 낱말로 읽히는 등 해석이 어긋나면 False). 2% 여유."""
    for y in years:
        mx = max(v.get(y, 0) for v in by_kw.values())
        sm = sum(v.get(y, 0) for v in by_kw.values())
        if u.get(y, 0) < mx * 0.98 or u.get(y, 0) > sm * 1.02 + 1:
            return False
    return True


def journal_corpus(errors: list) -> dict:
    """12개 저널 × 연도 기대 건수 (archive_from_year~). 실패 저널은 errors에 기록하고 건너뜀."""
    reg = load_registry()
    y0 = int(reg.get("archive_from_year", 2000))
    out = {}
    for j in reg.get("journals", []):
        try:
            srcs = resolve_sources(j.get("issns", []), MAILTO)
            if not srcs:
                errors.append(f"{j['code']}: ISSN 해석 0건")
                continue
            by_year = oa_by_year(f"{source_filter([s['id'] for s in srcs])},"
                                 f"from_publication_date:{y0}-01-01")
            years = [int(y) for y, c in by_year.items() if c]
            rec = {"name": j["name"], "sources": srcs,
                   "total": sum(by_year.values()),
                   "last_year": max(years) if years else None,   # 커버리지 끊김 감지용
                   "by_year": dict(sorted(by_year.items()))}
            if j.get("openalex_coverage_to"):
                rec["coverage_to"] = j["openalex_coverage_to"]
            if j.get("check_issns"):                  # 확인용 ISSN — 수집 필터엔 미포함
                rec["check_sources"] = resolve_sources(j["check_issns"], MAILTO)
            out[j["code"]] = rec
            print(f"   {j['code']} {j['name'][:40]}: {rec['total']:,}건 ({y0}~) "
                  f"← {', '.join(s['id'] for s in srcs)}")
            time.sleep(0.4)                           # polite
        except Exception as e:
            errors.append(f"{j['code']}: {e}")
    return out


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

    # ── 2. 연구소별 대표 키워드 × 최근 1년 (트렌드 감시) + 최근 5년 연도별 ──
    y1 = time.gmtime(now).tm_year
    trend_years = [str(y) for y in range(y1 - TREND_YEARS + 1, y1 + 1)]
    span = f"from_publication_date:{trend_years[0]}-01-01,to_publication_date:{y1}-12-31"   # 미래 날짜(오기) 제외
    per_inst, n_related = {}, 0
    cit_slot = (now // (6 * 3600)) % CIT_SLOTS
    for idx, inst in enumerate(topics.get("institutes", [])):
        do_cit = idx % CIT_SLOTS == cit_slot              # 이번 실행에 피인용을 새로 셀 연구소
        kws = inst.get("openalex_keywords") or []
        if not kws:
            continue
        kw = kws[0]                                   # 대표 키워드 1개 (경량 유지)
        try:
            c = oa_count(f"title_and_abstract.search:{kw},from_publication_date:{RECENT_FROM}")
            per_inst[inst["code"]] = {"name": inst.get("name_ko"), "keyword": kw,
                                      "recent_1y": c}
            n_related += c
            time.sleep(0.4)                           # polite
            by = oa_by_year(f"title_and_abstract.search:{kw},{span}")
            per_inst[inst["code"]]["by_year"] = {y: by.get(y, 0) for y in trend_years}
            print(f"   {inst['code']} {inst.get('name_ko','')}: '{kw}' 최근1년 {c:,}건 · "
                  + " ".join(f"{y}:{by.get(y, 0):,}" for y in trend_years))
            time.sleep(0.4)
        except Exception as e:
            errors.append(f"{inst['code']}: {e}")
            continue
        try:                                          # 키워드 전체 — 키워드별 + 합집합 (실패해도 대표 키워드 값은 유지)
            ent = per_inst[inst["code"]]
            by_kw = {kw: ent["by_year"]}
            for k in kws[1:]:
                b = oa_by_year(f"title_and_abstract.search:{k},{span}")
                by_kw[k] = {y: b.get(y, 0) for y in trend_years}
                time.sleep(0.4)
            ent["keywords"], ent["by_kw"] = kws, by_kw
            try:                                      # 피인용 상위 10% — 키워드별 (실패해도 편수 값은 유지)
                if not do_cit:
                    raise StopIteration
                by_kw_top = {}
                for k in kws:
                    b = oa_by_year(f"title_and_abstract.search:{k},{span},{TOP10}")
                    by_kw_top[k] = {y: min(b.get(y, 0), by_kw[k].get(y, 0)) for y in trend_years}
                    time.sleep(0.4)
                ent["by_kw_top10"] = by_kw_top
                ent["cit_updated"] = now
            except StopIteration:
                pass
            except Exception as e:
                errors.append(f"{inst['code']} 피인용(키워드): {e}")
            if len(kws) > 1:
                b = oa_by_year(f"title_and_abstract.search:{union_search(kws)},{span}")
                u = {y: b.get(y, 0) for y in trend_years}
                time.sleep(0.4)
                if union_ok(u, by_kw, trend_years):
                    ent["by_year_all"] = u
                    try:                              # 피인용 상위 10% — 합집합 (이번 차례 연구소만)
                        if not do_cit:
                            raise StopIteration
                        b = oa_by_year(f"title_and_abstract.search:{union_search(kws)},{span},{TOP10}")
                        ent["by_year_all_top10"] = {y: min(b.get(y, 0), u.get(y, 0)) for y in trend_years}
                        time.sleep(0.4)
                    except StopIteration:
                        pass
                    except Exception as e:
                        errors.append(f"{inst['code']} 피인용(합집합): {e}")
                else:
                    errors.append(f"{inst['code']}: 키워드 합집합 검산 어긋남 {u} — 합집합 미기록")
            else:
                ent["by_year_all"] = ent["by_year"]
                if ent.get("by_kw_top10"):
                    ent["by_year_all_top10"] = ent["by_kw_top10"][kw]
            print(f"      키워드 {len(kws)}개 합집합: "
                  + " ".join(f"{y}:{ent.get('by_year_all', {}).get(y, '-')}" for y in trend_years)
                  + " · 피인용 상위10%: "
                  + " ".join(f"{y}:{ent.get('by_year_all_top10', {}).get(y, '-')}" for y in trend_years))
        except Exception as e:
            errors.append(f"{inst['code']} 키워드 전체: {e}")

    # ── 2a. 해외 전체 기준선: 같은 5년의 OpenAlex 전체 논문 수 (연구소 키워드 비중 = 키워드 / 전체) ──
    baseline = None
    try:
        by = oa_by_year(span)
        baseline = {"label": "OpenAlex 전체", "by_year": {y: by.get(y, 0) for y in trend_years}}
        print("   OpenAlex 전체: " + " ".join(f"{y}:{by.get(y, 0):,}" for y in trend_years))
        time.sleep(0.4)
        bt = oa_by_year(f"{span},{TOP10}")
        baseline["by_year_top10"] = {y: bt.get(y, 0) for y in trend_years}
        print("   OpenAlex 전체 피인용 상위10%: " + " ".join(f"{y}:{bt.get(y, 0):,}" for y in trend_years))
    except Exception as e:
        errors.append(f"전체 기준선: {e}")

    # ── 2a'. K-water 소속 논문의 피인용 질 (같은 5년) — 연구소 관련 논문과 견주는 참고값 ──
    kwater_cit = None
    if inst_id:
        try:
            kf = f"authorships.institutions.lineage:{inst_id},{span}"
            ka, kt = oa_by_year(kf), oa_by_year(f"{kf},{TOP10}")
            kwater_cit = {"label": inst_name or "K-water", "by_year": {y: ka.get(y, 0) for y in trend_years},
                          "by_year_top10": {y: min(kt.get(y, 0), ka.get(y, 0)) for y in trend_years}}
            print("   K-water 소속 논문 (상위10%/전체): "
                  + " ".join(f"{y}:{kwater_cit['by_year_top10'][y]}/{kwater_cit['by_year'][y]}" for y in trend_years))
            time.sleep(0.4)
        except Exception as e:
            errors.append(f"K-water 피인용: {e}")

    # ── 2b. 수자원 12개 핵심 저널 × 연도 (분모 코퍼스) ──
    journals = journal_corpus(errors)
    n_corpus = sum(j["total"] for j in journals.values())

    ok = n_kwater is not None and not errors

    # ── 3. 에이전트 심박 갱신 ──
    ag = load(AGENT, {})
    ev = ag.get("events") or []
    if n_kwater is not None:
        ag.update(state="idle", last_run=now, next_run="6시간 주기 (GitHub Actions)",
                  summary=f"OpenAlex 실측 감시 [{inst_name or 'ROR 폴백'}] — 논문 {n_kwater:,}건(2020~) · "
                          f"7개 소 키워드 트렌드 추적 · 수자원 {len(journals)}개 저널 코퍼스 {n_corpus:,}건",
                  counts={"K-water 논문(실측)": n_kwater, "관련논문(최근1년)": n_related,
                          "12개 저널 코퍼스": n_corpus})
        msg = (f"☁️ 정기 실측 — K-water {n_kwater:,}건 · 관련(최근1년) {n_related:,}건"
               f" · 저널 코퍼스 {n_corpus:,}건({len(journals)}개)"
               + (f" · 일부 오류 {len(errors)}" if errors else ""))
    else:
        ag["state"] = "error"
        ag["last_run"] = now
        msg = "⚠️ OpenAlex API 오류: " + "; ".join(str(e)[:60] for e in errors[:2])
    ev.append({"ts": now, "msg": msg})
    ag["events"] = ev[-20:]                           # 최근 20개만 유지
    ag["last_errors"] = [str(e)[:200] for e in errors[:15]]   # 원인 확인용 (429 = OpenAlex 하루 사용량 초과)
    save(AGENT, ag)

    # ── 4. 트렌드 기록 (위크시그널 재료) ──
    if per_inst or journals:
        tr = load(TRENDS, {"history": []})
        tr["updated"] = now
        tr["window_from"] = RECENT_FROM
        if per_inst:
            for code, v in per_inst.items():          # 연도별 조회만 실패한 연구소는 지난 값 유지
                old = (tr.get("institutes") or {}).get(code, {})
                for f in ("by_year", "by_year_all", "by_kw", "keywords", "by_year_all_top10", "by_kw_top10", "cit_updated"):
                    if f not in v and old.get(f):
                        v[f] = old[f]
            tr["institutes"] = per_inst
            tr["trend_years"] = trend_years
            tr["trend_basis"] = ("연구소 키워드 전체(5~6개)를 OR로 묶은 title_and_abstract.search, 출판연도별 실측 "
                                 "(키워드마다 지금 수집과 같은 띄어쓰기 검색 · 올해는 진행 중·색인 지연)")
        if baseline:
            if "by_year_top10" not in baseline and (tr.get("baseline") or {}).get("by_year_top10"):
                baseline["by_year_top10"] = tr["baseline"]["by_year_top10"]
            tr["baseline"] = baseline
        if kwater_cit:
            tr["kwater_citation"] = kwater_cit
        tr["citation_basis"] = ("피인용 상위 10% = OpenAlex citation_normalized_percentile.is_in_top_10_percent "
                                "(같은 분야·같은 출판연도 논문 중 피인용 상위 10%) — 세계 평균 약 10%, 최근 연도는 인용이 쌓이는 중")
        if journals:                                  # 일부 실패 시 이전 값 유지
            tr["journals"] = {**tr.get("journals", {}), **journals}
        tr.setdefault("history", []).append(
            {"ts": now, "kwater": n_kwater, "related_1y": n_related,
             "journal_corpus": n_corpus})
        tr["history"] = tr["history"][-120:]          # ~30일치(6h 주기)
        save(TRENDS, tr)

    # ── 5. summary: 실측 모집단만 (수집됨 papers와 구분 — 정직 원칙) ──
    if n_kwater is not None:
        sm = load(SUMMARY, {"totals": {}})
        sm.setdefault("totals", {})["papers_available"] = n_kwater
        if journals:
            sm["totals"]["journal_corpus_available"] = sum(
                j["total"] for j in load(TRENDS, {}).get("journals", {}).values())
        sm["generated_at"] = now
        save(SUMMARY, sm)

    print("결과:", "정상" if ok else f"부분 오류 {errors}")
    return 0                                          # 오류도 기록·커밋되도록 항상 0


if __name__ == "__main__":
    sys.exit(main())
