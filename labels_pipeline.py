#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""labels_pipeline.py (v3) — 자율 수집·라벨링 에이전트 (GitHub Actions 상주)"""
import argparse, calendar, json, os, sys, time, urllib.parse, urllib.request
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

OA = "https://api.openalex.org/works"
PAGE = 100
BATCH = 50
RETRY = 4
DOMAIN_VER = "v0.1"
FORWARD_SWEEP_DAYS = 45
HISTORY_START_YEAR = 2025      # 첫 역사 수집 연도 (2025 상반기 공백 보완)
HISTORY_FLOOR_YEAR = 2015      # 여기까지 후진하면 역사 수집 완료
MAX_PAGES_FORWARD = 120
MAX_PAGES_PER_MONTH = 60
COLLECT_ALL_KEYWORDS = False   # 연구소 키워드 전체(5~6개)로 수집 — 2026-10-27 승인 뒤 실측 규모(최근 5년 약 20.7만 편 → 약 17만 편 추가,
                               #   라벨링 30~50달러)가 추정의 3배라 사용자 지시로 '일단 대기'. True로 바꾸면 키워드마다 따로 검색해 id로 합침.
                               #   False = 대표 키워드 1개 (최근 5년 하루 1년 다시 훑기는 그대로 진행)
RESWEEP_YEARS = 5              # 역사 수집 완주 뒤: 최근 5년(올해 포함)을 하루에 1년씩 다시 훑음 (2026-10-27 사용자 지정)
                               #   첫 차례는 작년(2025 상반기 공백) → 2024 → … → 5년 전 → 올해 → 작년 … 순환. id로 중복 제거
TOPICS_URL = ("https://raw.githubusercontent.com/newcave/water-tech-agent/"
              "main/data_seed/search_topics.json")

INST_NAME = {"INST-01": "경영연구소", "INST-02": "수자원환경연구소", "INST-03": "상하수도연구소",
             "INST-04": "물인프라안전연구소", "INST-05": "물에너지연구소",
             "INST-06": "수자원위성연구소", "INST-07": "AI연구소"}
DOMAINS = {
    "W1": "유역·수문: 강우-유출, 하천, 홍수·가뭄, 수문 관측·모델링",
    "W2": "댐·저수지 운영: 저수지 운영규칙, 용수공급 의사결정, 방류",
    "W3": "수질·수생태: 조류(녹조), 오염원, 수생태, 미량오염물질",
    "W4": "취·정수 공정: 정수장 단위공정, 응집·여과·소독, 공정제어",
    "W5": "관망·급수 서비스: 상수관망 누수·수압, 수요예측, 계량, 급수",
    "W6": "하수·재이용: 하수처리, 재이용수, 하수관로",
    "W7": "물인프라 안전·자산: 댐·관로·구조물 진단, 노후화, 안전관리",
    "W8": "물에너지: 수력, 수상태양광, 수열, 물-에너지 넥서스",
    "W9": "관측 인프라: 위성 탑재체·검보정, 계측망·센서 자체의 개발",
    "W0": "경영·정책·서비스: 물 정책, 요금·경제, 경영, 거버넌스, 해외사업",
    "W0_UNCLASSIFIED": "위 어디에도 명확히 속하지 않음",
}
CODES = list(DOMAINS.keys())
DOM_ORDER = CODES

EXTRACT_SYSTEM = (
    "You extract fields from a research abstract in the water/AI domain. "
    "Answer in Korean. Do NOT classify into any taxonomy — only describe.\n"
    "- relevant: 정상적인 연구 초록이면 반드시 true 가 기본이다. 실제 연구 내용을 담고 "
    "있으면(문제·방법·결과 등) true. false 는 오직 초록이 연구가 아닐 때만 — 학회 안내, "
    "학술지 서문/사설, 논평, 정오표(erratum), 특집호 소개 등. 판단이 서지 않으면 true.\n"
    "- object: 이 연구가 최종적으로 상태를 개선·이해하려는 '대상'. 구체 명사구로. "
    "AI/모델/기법은 object 가 아니라 수단이다.\n"
    "- problem: 그 대상에서 풀려는 '문제'를 짧은 동사구로.\n"
    "relevant=false 일 때만 object·problem 을 빈 문자열로 둔다. "
    "표면 키워드 나열이 아니라 연구가 무엇을 개선하려는지의 본질을 한 구절로 압축한다."
)
EXTRACT_SCHEMA = {"name": "object_problem", "strict": True, "schema": {
    "type": "object", "additionalProperties": False,
    "properties": {"relevant": {"type": "boolean"}, "object": {"type": "string"},
                   "problem": {"type": "string"}},
    "required": ["relevant", "object", "problem"]}}

ASSIGN_SYSTEM = (
    "너는 물 분야 연구 문헌을 K-water 도메인축에 배정하는 분류기다. "
    "입력은 한 문헌의 object(개선 대상)와 problem(푸는 문제)이다.\n다음 축 중에서 고른다:\n"
    + "\n".join(f"  {k}: {v}" for k, v in DOMAINS.items()) + "\n\n규칙:\n"
    "1) 판정 기준은 '개선 대상'이다. AI·위성·센서·모델은 수단이므로 그것만 보고 W9 로 "
    "보내지 마라. 위성으로 녹조를 탐지하면 대상은 수질(W3)이다. 탑재체/검보정/센서 자체 "
    "개발이어야 W9 다.\n2) primary 는 반드시 1개.\n3) secondary 는 본질적으로 겹칠 때만 0~2개.\n"
    "4) 어느 축에도 명확히 안 맞으면 W0_UNCLASSIFIED. 억지로 끼워맞추지 마라.\n"
    "5) confidence: 0.0~1.0.")
ASSIGN_SCHEMA = {"name": "domain_assign", "strict": True, "schema": {
    "type": "object", "additionalProperties": False,
    "properties": {"primary": {"type": "string", "enum": CODES},
                   "secondary": {"type": "array", "items": {"type": "string", "enum": CODES}},
                   "confidence": {"type": "number"}},
    "required": ["primary", "secondary", "confidence"]}}

# ── 실패 기록 (회차 끝에 metrics_snapshot이 labels/metrics/failures.jsonl에 남김) ──
FAILS = Counter()          # (stage, inst, kind) → 건수
FAIL_DETAIL = {}           # (stage, inst, kind) → 대표 설명


def fail(stage, inst, kind, n=1, detail=""):
    FAILS[(stage, inst, kind)] += n
    FAIL_DETAIL.setdefault((stage, inst, kind), detail)


def fail_list():
    return [{"stage": s, "inst": i, "kind": k, "count": n, "detail": FAIL_DETAIL.get((s, i, k), "")}
            for (s, i, k), n in sorted(FAILS.items(), key=lambda x: str(x[0]))]


def oa_get(params):
    params = dict(params)
    if os.environ.get("OPENALEX_MAILTO"):
        params["mailto"] = os.environ["OPENALEX_MAILTO"]
    url = OA + "?" + urllib.parse.urlencode(params)
    delay = 0.5
    for attempt in range(1, RETRY + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "kwater-labels-pipeline"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except Exception as e:
            if attempt == RETRY:
                sys.stderr.write(f"  OpenAlex 실패: {e}\n"); return None
            time.sleep(delay); delay = min(delay * 2, 8)
    return None


def jsonl_iter(path):
    if path.exists():
        for line in path.open(encoding="utf-8"):
            line = line.strip()
            if line:
                try:
                    yield json.loads(line)
                except Exception:
                    pass


def done_ids(path, key="id"):
    return {r[key] for r in jsonl_iter(path) if key in r}


def rebuild_abstract(inv):
    if not inv:
        return ""
    pos = {}
    for w, ps in inv.items():
        for p in ps:
            pos[p] = w
    return " ".join(pos[i] for i in range(max(pos) + 1) if i in pos) if pos else ""


def get_client():
    from openai import OpenAI
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        env = Path(".env")
        if env.exists():
            for line in env.read_text(encoding="utf-8").splitlines():
                if line.startswith("OPENAI_API_KEY"):
                    key = line.split("=", 1)[1].strip().strip('"').strip("'"); break
    if not key:
        sys.exit("[중단] OPENAI_API_KEY 없음")
    return OpenAI(api_key=key)


def llm_json(client, model, system, schema, user):
    delay = 1.0
    for attempt in range(1, RETRY + 1):
        try:
            r = client.chat.completions.create(
                model=model, temperature=0,
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": user}],
                response_format={"type": "json_schema", "json_schema": schema})
            return json.loads(r.choices[0].message.content)
        except Exception as e:
            if attempt == RETRY:
                sys.stderr.write(f"  LLM 실패: {type(e).__name__}: {str(e)[:100]}\n")
                return None
            m = str(e).lower()
            delay = min(delay * 2, 20) if ("rate" in m or "429" in m) else delay
            time.sleep(delay)
    return None


def paper_ids_by_inst(repo):
    out = {}
    for base in (repo / "live" / "openalex", repo / "labels" / "openalex_extended"):
        if not base.exists():
            continue
        for p in sorted(base.glob("papers_INST-*.jsonl")):
            inst = p.stem.replace("papers_", "")
            d = out.setdefault(inst, {})
            for r in jsonl_iter(p):
                rid = str(r.get("id", "")).rsplit("/", 1)[-1]
                if rid and rid not in d:
                    r = dict(r); r["id"] = rid; d[rid] = r
    return out


def load_topics(repo, log):
    """연구소 키워드는 main의 data_seed/search_topics.json이 기준 (연구소가 직접 고치는 곳) → main 먼저, 실패하면 이 브랜치 사본."""
    try:
        with urllib.request.urlopen(TOPICS_URL, timeout=30) as r:
            return json.load(r)
    except Exception as e:
        log(f"수집: main의 search_topics 로드 실패({e}) — data 브랜치 사본 사용")
    tj = repo / "data_seed" / "search_topics.json"
    if tj.exists():
        return json.loads(tj.read_text(encoding="utf-8"))
    return None


def state_path(repo):
    return repo / "labels" / "pipeline_state.json"


def load_state(repo):
    p = state_path(repo)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"last_collect_date": "", "history_next_year": HISTORY_START_YEAR}


def save_state(repo, st):
    p = state_path(repo)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")


def collect_range(repo, topics, since, until, cap_pages, log, tag):
    ext_dir = repo / "labels" / "openalex_extended"; ext_dir.mkdir(parents=True, exist_ok=True)
    existing = paper_ids_by_inst(repo)
    total = 0
    for inst in topics.get("institutes", []):
        code = inst.get("code"); kws = inst.get("openalex_keywords") or []
        if not code or not kws:
            continue
        have = set(existing.get(code, {}))
        out = ext_dir / f"papers_{code}.jsonl"
        added = 0
        with out.open("a", encoding="utf-8") as f:
            for kw in (kws if COLLECT_ALL_KEYWORDS else kws[:1]):   # 키워드마다 따로 → id로 합침 (OR 검색 해석에 기대지 않음)
                filt = f"title_and_abstract.search:{kw},from_publication_date:{since}"
                if until:
                    filt += f",to_publication_date:{until}"
                cursor, pages = "*", 0
                while cursor and pages < cap_pages:
                    j = oa_get({"filter": filt, "per-page": PAGE, "cursor": cursor,
                                "sort": "publication_date:desc",
                                "select": "id,doi,title,publication_year,publication_date,"
                                          "cited_by_count,type,primary_location"})
                    if not j:
                        fail("collect", code, "api_error", 1,
                             f"OpenAlex 검색 실패 ({tag}, '{kw}', {pages + 1}쪽) — 이 구간·키워드 수집 중단")
                        break
                    for w in j.get("results", []):
                        rid = (w.get("id") or "").rsplit("/", 1)[-1]
                        if not rid or rid in have:
                            continue
                        src = ((w.get("primary_location") or {}).get("source") or {})
                        f.write(json.dumps({"id": rid, "doi": w.get("doi"),
                            "title": w.get("title"), "year": w.get("publication_year"),
                            "date": w.get("publication_date"), "cited": w.get("cited_by_count"),
                            "venue": src.get("display_name"), "type": w.get("type"), "kw": kw},
                            ensure_ascii=False) + "\n")
                        have.add(rid); added += 1
                    cursor = (j.get("meta") or {}).get("next_cursor")
                    pages += 1
        existing.setdefault(code, {}).update({h: {} for h in have})
        if added:
            log(f"  {tag} {code}: +{added}")
        total += added
    return total


def stage_collect_daily(repo, log):
    st = load_state(repo)
    today = date.today().isoformat()
    if st.get("last_collect_date") == today:
        log("수집: 오늘 이미 완료 — 라벨링만 진행"); return 0, None, 0
    topics = load_topics(repo, log)
    if not topics:
        return 0, None, 0
    since_f = (date.today() - timedelta(days=FORWARD_SWEEP_DAYS)).isoformat()
    log(f"수집(전진): 최근 {FORWARD_SWEEP_DAYS}일 ({since_f}~)")
    n_fwd = collect_range(repo, topics, since_f, None, MAX_PAGES_FORWARD, log, "전진")

    y = int(st.get("history_next_year", HISTORY_START_YEAR))
    n_hist, hist_year = 0, None
    if y >= HISTORY_FLOOR_YEAR:
        hist_year = y
        log(f"수집(후진): {y}년 (월 단위 12조각)")
        for m in range(12, 0, -1):
            last = calendar.monthrange(y, m)[1]
            n_hist += collect_range(repo, topics, f"{y}-{m:02d}-01",
                                    f"{y}-{m:02d}-{last:02d}",
                                    MAX_PAGES_PER_MONTH, log, f"{y}-{m:02d}")
        st["history_next_year"] = y - 1
        nxt = y - 1
        log(f"수집(후진): {y}년 +{n_hist} — 다음 회차는 "
            + (f"{nxt}년" if nxt >= HISTORY_FLOOR_YEAR else "없음(완주)"))
    elif RESWEEP_YEARS > 0:
        n_hist, hist_year = stage_resweep(repo, topics, st, log)
    else:
        log(f"수집(후진): {HISTORY_FLOOR_YEAR}년까지 완주 — 종료 상태")
    basis = "all" if COLLECT_ALL_KEYWORDS else "rep"      # 앱의 수집률 비교 기준 (all = 키워드 전체 실측과 비교)
    if st.get("collect_basis") != basis:
        st["collect_basis"], st["collect_basis_since"] = basis, today
    st["last_collect_date"] = today
    save_state(repo, st)
    return n_fwd, hist_year, n_hist


def stage_resweep(repo, topics, st, log):
    """최근 RESWEEP_YEARS년 가운데 오늘 차례인 한 해를 월 단위로 다시 훑는다 (하루 1년).
    늦게 색인된 논문과 지난 수집에서 빠진 달(2025년 1~6월 등)을 채운다. 이미 있는 id는 건너뜀."""
    today = date.today()
    lo = today.year - RESWEEP_YEARS + 1
    y = int(st.get("resweep_next_year") or today.year - 1)
    if y < lo or y > today.year:
        y = today.year
    last_m = 12 if y < today.year else today.month
    log(f"수집(다시 훑기): 최근 {RESWEEP_YEARS}년 중 {y}년 (월 단위 {last_m}조각)")
    n = 0
    for m in range(last_m, 0, -1):
        last = calendar.monthrange(y, m)[1]
        n += collect_range(repo, topics, f"{y}-{m:02d}-01", f"{y}-{m:02d}-{last:02d}",
                           MAX_PAGES_PER_MONTH, log, f"다시 {y}-{m:02d}")
    nxt = y - 1 if y - 1 >= lo else today.year
    st["resweep_next_year"] = nxt
    st["resweep_window"] = [lo, today.year]
    st["resweep_log"] = (st.get("resweep_log") or [])[-9:] + [{"date": today.isoformat(), "year": y, "added": n}]
    log(f"수집(다시 훑기): {y}년 +{n} — 다음 회차는 {nxt}년")
    return n, y


def stage_backfill(repo, log, recheck=0):
    """초록 보강. OpenAlex 호출이 실패한 묶음은 기록하지 않는다 → 다음 회차에 자동 재시도.
    (2026-07-29~08-08 회차는 실패한 묶음까지 빈 초록으로 '완료' 기록해 약 4.3만 편이 재시도되지 않았음)
    recheck>0 이면 초록이 빈 값으로만 남은 문헌을 이번 회차에 최대 recheck편 다시 조회한다."""
    papers = paper_ids_by_inst(repo)
    abs_dir = repo / "labels" / "abstracts"; abs_dir.mkdir(parents=True, exist_ok=True)
    total_new, budget = 0, recheck
    for inst, recs in sorted(papers.items()):
        out = abs_dir / f"{inst}.jsonl"
        rows = list(jsonl_iter(out))
        seen = {r["id"] for r in rows if "id" in r}
        ok_ids = {r["id"] for r in rows if r.get("abstract_ok")}
        todo = [i for i in recs if i not in seen]
        retry = set()
        if budget > 0:
            retry = {i for i in recs if i in seen and i not in ok_ids}
            retry = set(sorted(retry)[:budget]); budget -= len(retry)
            todo += sorted(retry)
        if not todo:
            continue
        got, failed = 0, 0
        with out.open("a", encoding="utf-8") as f:
            for i in range(0, len(todo), BATCH):
                chunk = todo[i:i + BATCH]
                j = oa_get({"filter": "openalex_id:" + "|".join(chunk),
                            "select": "id,abstract_inverted_index", "per-page": str(len(chunk))})
                if not j:                                 # 호출 실패 — 기록하지 않고 다음 회차로
                    failed += len(chunk)
                    time.sleep(0.15)
                    continue
                res = {}
                for w in j.get("results", []):
                    res[w["id"].rsplit("/", 1)[-1]] = rebuild_abstract(
                        w.get("abstract_inverted_index"))
                for rid in chunk:
                    a = res.get(rid, "")
                    if rid in retry and not a:            # 재조회에서도 없으면 중복 줄을 남기지 않음
                        continue
                    f.write(json.dumps({"id": rid, "abstract": a, "abstract_ok": bool(a)},
                                       ensure_ascii=False) + "\n")
                    got += bool(a)
                time.sleep(0.15)
        if failed:
            fail("backfill", inst, "api_error", failed,
                 "OpenAlex 초록 조회 실패 — 빈 값으로 기록하지 않고 다음 회차에 재시도")
        log(f"백필 {inst}: +{len(todo) - failed} (초록 {got}, 재조회 {len(retry)}, 실패 {failed})")
        total_new += len(todo) - failed
    return total_new


def stage_extract(repo, client, model, cap, log):
    papers = paper_ids_by_inst(repo)
    n = 0
    for inst in sorted(papers):
        abs_p = repo / "labels" / "abstracts" / f"{inst}.jsonl"
        out = repo / "labels" / "extract" / f"{inst}.jsonl"
        out.parent.mkdir(parents=True, exist_ok=True)
        have = done_ids(out)
        titles = {i: r.get("title", "") for i, r in papers[inst].items()}
        with out.open("a", encoding="utf-8") as f:
            for r in jsonl_iter(abs_p):
                if n >= cap:
                    log(f"추출: 상한 {cap} 도달"); return n
                if not r.get("abstract_ok") or r["id"] in have:
                    continue
                res = llm_json(client, model, EXTRACT_SYSTEM, EXTRACT_SCHEMA,
                               f"[Title] {titles.get(r['id'],'')}\n\n[Abstract] {r['abstract'][:3500]}")
                if res is None:
                    fail("extract", inst, "llm_error", 1, "대상·문제 추출 LLM 호출 실패 — 다음 회차에 재시도")
                    continue
                f.write(json.dumps({"id": r["id"], "object": res["object"],
                    "problem": res["problem"], "relevant": res["relevant"],
                    "model": model}, ensure_ascii=False) + "\n"); f.flush()
                n += 1
        if n:
            log(f"추출 {inst}: 누적 {n}")
    return n


def stage_assign(repo, client, model, cap, log):
    n = 0
    for inst in sorted(INST_NAME):
        ext_p = repo / "labels" / "extract" / f"{inst}.jsonl"
        out = repo / "labels" / "domain" / f"{inst}.jsonl"
        out.parent.mkdir(parents=True, exist_ok=True)
        have = done_ids(out)
        with out.open("a", encoding="utf-8") as f:
            for r in jsonl_iter(ext_p):
                if n >= cap:
                    log(f"배정: 상한 {cap} 도달"); return n
                if not r.get("relevant") or r["id"] in have:
                    continue
                res = llm_json(client, model, ASSIGN_SYSTEM, ASSIGN_SCHEMA,
                               f"object: {r.get('object','')}\nproblem: {r.get('problem','')}")
                if res is None:
                    fail("assign", inst, "llm_error", 1, "도메인 배정 LLM 호출 실패 — 다음 회차에 재시도")
                    continue
                f.write(json.dumps({"id": r["id"], "domain_primary": res["primary"],
                    "domain_secondary": res["secondary"], "confidence": res["confidence"],
                    "domain_ver": DOMAIN_VER, "object": r.get("object", ""),
                    "problem": r.get("problem", "")}, ensure_ascii=False) + "\n"); f.flush()
                n += 1
        if n:
            log(f"배정 {inst}: 누적 {n}")
    return n


def stage_summary(repo, log):
    papers = paper_ids_by_inst(repo)
    id_year = {}
    for recs in papers.values():
        for rid, r in recs.items():
            y = r.get("year")
            if isinstance(y, int):
                id_year[rid] = y
    per_inst, by_year = {}, {}
    for inst in sorted(INST_NAME):
        c = Counter()
        for r in jsonl_iter(repo / "labels" / "domain" / f"{inst}.jsonl"):
            d = r.get("domain_primary")
            if d:
                c[d] += 1
                y = id_year.get(r["id"])
                if y:
                    by_year.setdefault(str(y), Counter())[d] += 1
        per_inst[inst] = c
    grand = sum(sum(c.values()) for c in per_inst.values())
    if not grand:
        log("집계: 라벨 없음"); return None
    dom_tot = {d: sum(per_inst[i].get(d, 0) for i in per_inst) for d in DOM_ORDER}
    summary = {
        "domain_ver": DOMAIN_VER, "status": "v0.1 confirmed",
        "source": "OpenAlex, 7개 연구소 관련문헌 (전진 45일 스윕 + 역사 연도별 수집)",
        "method": "abstract→object/problem(mini)→domain assign(mini, primary)",
        "generated_at": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
        "total": grand,
        "domains": {d: {"name": DOMAINS[d].split(":")[0], "count": dom_tot[d],
                        "pct": round(dom_tot[d] * 100 / grand, 1)} for d in DOM_ORDER},
        "institutes": {i: {"name": INST_NAME[i], "total": sum(per_inst[i].values()),
            "unclassified": per_inst[i].get("W0_UNCLASSIFIED", 0),
            "unclassified_pct": round(per_inst[i].get("W0_UNCLASSIFIED", 0) * 100
                                      / max(sum(per_inst[i].values()), 1), 1),
            "by_domain": {d: per_inst[i].get(d, 0) for d in DOM_ORDER}} for i in per_inst},
        "by_year_domain": {y: dict(c) for y, c in sorted(by_year.items())},
        "unclassified_analysis": {
            "verdict": "미분류는 물 도메인 밖 문헌(수집 검색식 유입). v0.1 확정.",
            "INST-03": "의학·생물·축산 (treatment/removal/exposure 용어 겹침)",
            "INST-06": "지구관측 일반 (위성은 수단, 대상 비물)",
            "INST-01": "농업 관개 (대상은 농작물)",
            "next_action": "수집 검색식 조정: 의학용어 배제, 지구관측 분리, 농업 구분"},
    }
    out = repo / "labels" / "domain" / "domain_summary_v0.1.json"
    json.dump(summary, out.open("w", encoding="utf-8"), ensure_ascii=False, indent=2)
    log(f"집계: 총 {grand:,}건")
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".")
    ap.add_argument("--max-items", type=int, default=3000)
    ap.add_argument("--model", default="gpt-4o-mini")
    ap.add_argument("--recheck-empty", type=int, default=0,
                    help="초록이 빈 값으로만 남은 문헌을 이번 회차에 최대 N편 다시 조회 (기본 0 = 안 함)")
    args = ap.parse_args()
    repo = Path(args.repo).resolve()
    if not (repo / "live" / "openalex").exists():
        sys.exit(f"[중단] {repo}/live/openalex 없음 — data 브랜치인지 확인")
    log = lambda m: print(m, flush=True)
    log(f"=== labels_pipeline v3 · cap={args.max_items} ===")
    t0 = time.time()
    n_fwd, hist_year, n_hist = stage_collect_daily(repo, log)
    n_bf = stage_backfill(repo, log, recheck=args.recheck_empty)
    client = get_client()
    n_ex = stage_extract(repo, client, args.model, args.max_items, log)
    n_as = stage_assign(repo, client, args.model, args.max_items, log)
    s = stage_summary(repo, log)
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "forward": n_fwd, "hist_year": hist_year, "hist": n_hist,
           "backfilled": n_bf, "extracted": n_ex, "assigned": n_as,
           "total": (s or {}).get("total", 0),
           "failures": sum(FAILS.values()),
           "duration_s": int(time.time() - t0)}
    runs = repo / "labels" / "pipeline_runs.jsonl"
    runs.parent.mkdir(parents=True, exist_ok=True)
    with runs.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    log(f"런로그: {rec}")
    try:                                           # 달성도 스냅샷·실패 기록 — 실패해도 파이프라인은 정상 종료
        import metrics_snapshot
        res = metrics_snapshot.record(repo, run_failures=fail_list(), ts=rec["ts"])
        log(f"달성도 스냅샷: 새 실패 기록 {res['new_failures']}건")
    except Exception as e:
        log(f"달성도 스냅샷 생략: {type(e).__name__}: {e}")
    log("=== 완료 ===")


if __name__ == "__main__":
    main()
