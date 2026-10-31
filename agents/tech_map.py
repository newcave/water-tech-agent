#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tech_map — 논문 × 특허 기술 지도의 '논문 축' 재료를 OpenAlex에서 연도별로 모은다 (v3.18)

단위: data_seed/tech_map/units.json (세부 기술 41개 — en = OpenAlex 제목·초록 검색어, 연구소 키워드와 같음)
연도: 2016 ~ 작년 (올해는 진행 중이라 제외)
모으는 것 (단위마다, 학술 논문 type:article|review만, 모두 '건수' — 논문 목록은 저장하지 않음):
  · by_year   출판연도별 논문 수                                       (group_by=publication_year, 검색 1회)
  · top10     같은 검색 + 피인용 상위 10%(분야·연도 보정)의 연도별 수      (검색 1회)
  · industry  같은 검색 + 기업 소속 저자가 1명 이상인 논문의 연도별 수     (검색 1회) — 실용화 쪽 보조 지표
  · kwater    같은 검색 + K-water 소속(계열 포함) 논문의 연도별 수         (검색 1회) — '우리 논문' 겹쳐 보기
  · topics    10년 합산 OpenAlex 주제(topic) 상위 10개 — 세세부 기술 후보   (검색 1회)
  · venue     연도별 게재 저널 상위 60개 [저널 id, 편수]                  (연도마다 검색 1회, 최근 해부터)
  · baseline  OpenAlex 전체 연도별 논문 수 (목록 조회 1회)
저널 지표: venue에 나온 저널마다 /sources/{id} (단건 조회 — 무료) → 2년 평균 피인용(summary_stats.2yr_mean_citedness = JIF와 같은 꼴,
  현재 값), h-index, 연도별 [논문 수, 받은 피인용] → data_seed/tech_map/journals.json  (JCR은 유료 라이선스라 쓰지 않음)

사용량: 검색 1건 ≈ $0.001. 키가 없으면 하루 $0.10(검색 약 100회)이라 6시간마다 25회씩(하루 약 100회), OPENALEX_API_KEY(Secrets)가 있으면
  하루 $1이라 한 번에 다 모은다(700회). 429(한도)를 만나면 멈추고 다음 실행이 이어서 한다. 받은 값은 30일(최근 2년)·90일 뒤 다시 셈.
"""
import json
import os
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / "data_seed" / "tech_map"
UNITS = DIR / "units.json"
OUT = DIR / "papers.json"
JOURNALS = DIR / "journals.json"
AGENT = ROOT / "data_seed" / "agents" / "tech_map.json"
API = "https://api.openalex.org"
MAILTO = "newcave.kwater@gmail.com"
def _keys() -> list:
    """OpenAlex 키 목록 — newcave/openalex와 같은 규칙: OPENALEX_API_KEY(콤마로 여러 개 가능) 다음 _2, _3 … 순서.
    앞 키의 하루 한도가 차면(429) 다음 키로 바꿔 받던 요청부터 이어 간다."""
    ks = []
    for name in ["OPENALEX_API_KEY"] + [f"OPENALEX_API_KEY_{i}" for i in range(2, 6)]:
        for k in os.environ.get(name, "").split(","):
            if k.strip() and k.strip() not in ks:
                ks.append(k.strip())
    return ks


KEYS = _keys()
KEY = KEYS[0] if KEYS else ""
BUDGET = int(os.environ.get("TECHMAP_MAX_CALLS") or (700 if KEY else 25))      # 무키: 6시간 4회 × 25 = 하루 약 100회(무료 한도)
SRC_BUDGET = int(os.environ.get("TECHMAP_MAX_SOURCES") or 1500)
KWATER_ROR = "04dtgat87"
Y0 = 2016
TOP10 = "citation_normalized_percentile.is_in_top_10_percent:true"
COMPANY = "authorships.institutions.type:company"
TYPES = "type:article|review"         # 학술 논문만 (데이터셋·책 장·프리프린트·편집물 제외) — 저널 IF와 짝이 맞게
QV = "a1"                             # 검색식 판 — 바뀌면 그 단위를 처음부터 다시 받음
VENUE_KEEP, TOPIC_KEEP = 60, 10
STAGES = ("by_year", "top10", "industry", "kwater", "topics", "venue")


def load(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def save(p: Path, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")


def clean(msg) -> str:
    """오류 문장에 붙는 요청 주소에서 키를 지운다 (papers.json은 공개 저장소에 커밋됨)."""
    s = str(msg)
    for k in KEYS:
        s = s.replace(k, "***")
    return s[:200]


class Budget(Exception):
    pass


class OA:
    def __init__(self, budget: int):
        self.left, self.used, self.errors, self.last_429, self.ki = budget, 0, [], None, 0

    def _get(self, path: str, params: dict, search: bool):
        if search:
            if self.left <= 0:
                raise Budget()
            self.left -= 1
            self.used += 1
        p = {"mailto": MAILTO, **params}
        if KEYS:
            p["api_key"] = KEYS[self.ki]
        r = None
        for i in range(3 + len(KEYS)):
            try:
                r = requests.get(f"{API}{path}", params=p, timeout=45)
            except requests.RequestException as e:
                if i == 2:
                    raise RuntimeError(clean(e)) from None
                time.sleep(3 * (i + 1))
                continue
            if r.status_code == 429:                # 하루 사용량 끝 — 다음 실행에 이어서 (잠깐 막힌 것이면 한 번 기다림)
                wait = r.headers.get("Retry-After", "")
                if i == 0 and wait.isdigit() and int(wait) <= 90:
                    time.sleep(int(wait) + 1)
                    continue
                if self.ki + 1 < len(KEYS):             # 다음 키로 바꿔 같은 요청부터
                    self.ki += 1
                    p["api_key"] = KEYS[self.ki]
                    print(f"🔑 키 {self.ki}번 한도 → {self.ki + 1}번 키로")
                    continue
                self.last_429 = clean(r.text)[:160]
                raise Budget()
            if r.status_code >= 500:
                time.sleep(3 * (i + 1))
                continue
            if r.status_code >= 400:
                raise RuntimeError(f"HTTP {r.status_code} {path} {clean(params.get('filter', ''))[:90]}")
            return r.json()
        raise RuntimeError(f"HTTP {r.status_code if r is not None else '-'} {path} (3회 재시도)")

    def group(self, filt: str, by: str, search=True) -> list:
        return self._get("/works", {"filter": filt, "group_by": by}, search).get("group_by", [])

    def entity(self, path: str, select: str) -> dict:
        return self._get(path, {"select": select}, search=False)


def age(ts) -> float:
    return (time.time() - ts) / 86400 if ts else 1e9


def by_year(g: list, years: list) -> dict:
    d = {str(x["key"]): int(x["count"]) for x in g}
    return {y: d.get(y, 0) for y in years}


def main():
    now = int(time.time())
    y1 = time.gmtime(now).tm_year - 1
    years = [str(y) for y in range(Y0, y1 + 1)]
    span = f"from_publication_date:{Y0}-01-01,to_publication_date:{y1}-12-31"
    units = load(UNITS, {}).get("units", [])
    st = load(OUT, {})
    st.setdefault("units", {})
    oa = OA(BUDGET)
    fresh_days = lambda y: 30 if int(y) >= y1 - 1 else 120          # 최근 2년은 색인·인용이 계속 늘어나 자주 다시 셈

    # K-water 기관 ID (단건 조회 — 무료)
    kw = st.get("kwater_inst") or {}
    if not kw.get("id") or age(kw.get("ts")) > 90:
        try:
            j = oa.entity(f"/institutions/ror:{KWATER_ROR}", "id,display_name")
            kw = {"id": j["id"].rsplit("/", 1)[-1], "name": j.get("display_name"), "ror": KWATER_ROR, "ts": now}
            st["kwater_inst"] = kw
        except Exception as e:
            oa.errors.append(f"K-water 기관 ID: {clean(e)}")

    for u in units:                                                   # 검색어가 바뀐 단위는 처음부터
        e = st["units"].setdefault(u["id"], {})
        if (e.get("en") and e["en"] != u["en"]) or (e and e.get("qv") != QV):
            st["units"][u["id"]] = e = {}
        e.update(en=u["en"], inst=u["inst"], name=u["name"], qv=QV)
        e.setdefault("ts", {})

    try:
        if age((st.get("baseline") or {}).get("ts")) > 30 or (st.get("baseline") or {}).get("qv") != QV:
            g = oa.group(f"{span},{TYPES}", "publication_year", search=False)
            st["baseline"] = {"by_year": by_year(g, years), "ts": now, "qv": QV}
        # 값싼 것부터 모든 단위에: 연도별 수 → 피인용 상위10% → 기업 참여 → K-water → 주제 → 연도별 저널(최근 해부터)
        for stage in STAGES:
            for u in units:
                e = st["units"][u["id"]]
                ts = e["ts"]
                q = f"title_and_abstract.search:{u['en']},{TYPES}"
                if stage == "venue":
                    vts = ts.setdefault("venue", {})
                    for y in reversed(years):
                        if age(vts.get(y)) < fresh_days(y):
                            continue
                        g = oa.group(f"{q},publication_year:{y}", "primary_location.source.id")
                        e.setdefault("venue", {})[y] = [[str(x["key"]).rsplit("/", 1)[-1], int(x["count"])]
                                                        for x in g if x.get("key") and "unknown" not in str(x["key"])][:VENUE_KEEP]
                        vts[y] = now
                        time.sleep(0.12)
                    continue
                if age(ts.get(stage)) < (90 if stage == "topics" else 30):
                    continue
                if stage == "by_year":
                    e["by_year"] = by_year(oa.group(f"{q},{span}", "publication_year"), years)
                elif stage == "top10":
                    e["top10"] = by_year(oa.group(f"{q},{span},{TOP10}", "publication_year"), years)
                elif stage == "industry":
                    e["industry"] = by_year(oa.group(f"{q},{span},{COMPANY}", "publication_year"), years)
                elif stage == "kwater":
                    if not kw.get("id"):
                        continue
                    e["kwater"] = by_year(oa.group(f"{q},{span},authorships.institutions.lineage:{kw['id']}", "publication_year"), years)
                elif stage == "topics":
                    g = oa.group(f"{q},{span}", "topics.id")
                    e["topics"] = [[str(x["key"]).rsplit("/", 1)[-1], x.get("key_display_name"), int(x["count"])] for x in g[:TOPIC_KEEP]]
                ts[stage] = now
                time.sleep(0.12)
    except Budget:
        print(f"⏸ 사용량 한도 — 검색 {oa.used}회 쓰고 멈춤, 다음 실행이 이어서 함")
        if oa.last_429:                                               # 429 = OpenAlex 하루 한도 (무키는 IP 공용이라 시작부터 막히기도 함)
            oa.errors.append(f"OpenAlex 429 (검색 {oa.used}회 뒤){'' if KEY else ' · 무키 공용 한도 — secrets.OPENALEX_API_KEY 필요'}: {oa.last_429}")
    except Exception as e:
        oa.errors.append(clean(e))
        print("⚠️", clean(e))

    # 저널 지표 (단건 조회 — 무료, 새로 나온 저널과 180일 지난 것만)
    jr = load(JOURNALS, {})
    jr.setdefault("journals", {})
    seen = {sid for e in st["units"].values() for v in (e.get("venue") or {}).values() for sid, _ in v}
    todo = [s for s in sorted(seen) if s not in jr["journals"] or age(jr["journals"][s].get("ts")) > 180][:SRC_BUDGET]
    got = 0
    for sid in todo:
        try:
            s = oa.entity(f"/sources/{sid}", "id,display_name,issn_l,summary_stats,counts_by_year,type,works_count")
            ss = s.get("summary_stats") or {}
            jr["journals"][sid] = {"name": s.get("display_name"), "issn_l": s.get("issn_l"), "type": s.get("type"),
                                   "if2": ss.get("2yr_mean_citedness"), "h": ss.get("h_index"), "i10": ss.get("i10_index"),
                                   "by_year": {str(c["year"]): [c.get("works_count", 0), c.get("cited_by_count", 0)]
                                               for c in s.get("counts_by_year") or []},
                                   "ts": now}
            got += 1
            time.sleep(0.1)
        except Exception as e:
            oa.errors.append(f"source {sid}: {clean(e)[:120]}")
            if len(oa.errors) > 30:
                break
    jr["_doc"] = ("저널 지표 보관 — OpenAlex /sources (CC0). if2 = 최근 2년 논문당 평균 피인용(summary_stats.2yr_mean_citedness — "
                  "JIF와 같은 꼴의 공개 지표, 받은 날의 현재 값), h = h-index, by_year = 연도별 [논문 수, 그해 받은 피인용]. "
                  "연도별 SJR(Cites/Doc 2년)이 들어오면 그 해 값으로 바꿔 씀")
    jr["updated"] = now
    save(JOURNALS, jr)

    # 남은 일 세기
    pend = 0
    for u in units:
        ts = st["units"][u["id"]]["ts"]
        pend += sum(age(ts.get(k)) >= (90 if k == "topics" else 30) for k in STAGES if k != "venue")
        pend += sum(age((ts.get("venue") or {}).get(y)) >= fresh_days(y) for y in years)
    st.update({"_doc": "논문 × 특허 기술 지도 — 논문 축 재료 (OpenAlex 건수 집계만, 논문 목록 없음, 학술 논문 type:article|review만). units.<id>: by_year·top10·industry·kwater "
                       "(연도별 수: 전체·피인용 상위10%·기업 저자 참여·K-water 소속), topics(10년 합산 주제 상위 [id, 이름, 편수]), "
                       "venue(연도별 게재 저널 상위 [저널 id, 편수]). 저널 지표는 journals.json",
               "updated": now, "years": years, "api_key": len(KEYS), "calls_last_run": oa.used, "pending_tasks": pend,
               "errors": oa.errors[:10]})
    save(OUT, st)

    ag = load(AGENT, {"agent": "tech_map", "events": []})
    done = len(units) * (len(STAGES) - 1 + len(years))
    ag.update(agent="tech_map", state="error" if oa.errors and not oa.used else ("standby" if pend else "idle"), last_run=now,
              next_run="6시간마다 (GitHub Actions)" + ("" if KEY else " · API 키 없음 — 한 번에 25회씩"),
              summary=f"기술 지도 논문 축 — 세부 기술 {len(units)}개 · {Y0}~{y1} · 진행 {max(0, done - pend)}/{done} · 저널 {len(jr['journals'])}곳",
              counts={"세부 기술": len(units), "남은 조회": pend, "저널 지표": len(jr["journals"]), "이번 검색": oa.used},
              last_errors=oa.errors[:10])
    ag["events"] = (ag.get("events") or [])[-19:] + [{"ts": now, "msg": f"🗺️ 검색 {oa.used}회 · 새 저널 {got}곳 · 남은 조회 {pend}건"}]
    ag["_doc"] = "tech_map 에이전트 상태 — tech-map 워크플로가 실행마다 갱신"
    save(AGENT, ag)
    print(f"✅ 검색 {oa.used}회 · 저널 {len(jr['journals'])}곳(+{got}) · 남은 조회 {pend}건 · 키 {len(KEYS)}개 (마지막 {oa.ki + 1 if KEYS else 0}번)")
    for m in oa.errors[:10]:
        print("  ·", m)
    return 0


if __name__ == "__main__":
    sys.exit(main())
