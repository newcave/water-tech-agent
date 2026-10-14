"""
연구소 라벨 판정(HITL) — 계산 모듈 (화면 없음, 관제센터 '🏷️ 연구소 라벨 판정'이 사용)

문제: 논문은 '어느 연구소 키워드로 검색됐는가'로 연구소 라벨이 붙는다. 이 라벨이 맞는지
     (OK) · 틀렸는지(NG) · 다른 연구소 것인지(이관)를 사람이 판정하되, 사람 손은 아끼고 싶다.

설계 (한 문장): 기계가 모든 논문에 '적합도 점수'를 매기고, 사람은 ① 무작위 감사 표본과
     ② 기계가 헷갈리거나 바꾸자고 제안한 논문만 본다. 쌓인 판정으로 점수를 보정해
     '이 점수 이상이면 사람이 안 봐도 95% 맞다'는 문턱 τ를 다시 계산한다.

  · 적합도 점수 0–100 = 본 연구소 적합(도메인 0.5 + 키워드 0.5)과 경쟁 연구소와의 차이,
    연구 문헌이 아닌 유형(심사평·답변 등)은 감점
  · 기계 제안: ok / ng(연구 문헌 아님·연구소 범위 밖) / move(→ 다른 연구소) + 공유 후보
  · 큐: 감사(audit, id 해시로 고정된 무작위 20%) + 선별(triage: 기계 제안≠ok 먼저,
    그다음 점수 낮은 ok 순)
  · 최종 상태 우선순위: 소장 확정 > 담당자 판정 > 자동 확정(제안 ok & 점수 ≥ τ) > 미검토
  · 기계의 NG·이관 제안은 사람이 판정하기 전엔 적용하지 않는다 (라벨을 지우는 건 사람만)
  · 판정 기록은 append-only JSONL (data 브랜치 labels/hitl/<INST>/*.jsonl). 점수는 판정에
    의존하지 않으므로, 점수 공식을 바꿔도 과거 판정으로 즉시 다시 보정할 수 있다.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import re
import urllib.parse
from collections import Counter

INST_NAME = {"INST-01": "경영연구소", "INST-02": "수자원환경연구소", "INST-03": "상하수도연구소",
             "INST-04": "물인프라안전연구소", "INST-05": "물에너지연구소",
             "INST-06": "수자원위성연구소", "INST-07": "AI연구소"}
INSTS = list(INST_NAME)
DOMAIN_NAME = {"W1": "유역·수문", "W2": "댐·저수지 운영", "W3": "수질·수생태", "W4": "취·정수 공정",
               "W5": "관망·급수 서비스", "W6": "하수·재이용", "W7": "물인프라 안전·자산",
               "W8": "물에너지", "W9": "관측 인프라", "W0": "경영·정책·서비스",
               "W0_UNCLASSIFIED": "미분류"}
DECISION_KO = {"ok": "OK", "ng": "NG", "move": "이관", "skip": "건너뜀", "pending": "미정"}
REASON_KO = {"nonresearch": "연구 문헌 아님 (심사평·답변·안내)", "out_of_scope": "연구소 범위 밖",
             "not_water": "물 분야 아님", "duplicate": "중복", "other": "기타"}
ROLE_KO = {"reviewer": "담당자", "director": "소장"}
STATE_ORDER = ["소장 확정", "담당자 판정", "자동 확정", "미검토"]
HITL_DIR = "labels/hitl"


# ───────────────────────── 공통 ─────────────────────────
def parse_jsonl(text: str) -> list[dict]:
    """\\n으로만 나눈다 (제목 속 U+2028 보호). 깨진 줄은 건너뛴다."""
    out = []
    for line in (text or "").split("\n"):
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out


def to_jsonl(rows: list[dict]) -> str:
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def stable_unit(key: str) -> float:
    """id → [0,1) 고정 난수 (감사 표본 추출용 — 누가 언제 열어도 같은 표본)."""
    return int(hashlib.sha1(key.encode("utf-8")).hexdigest()[:8], 16) / 0x100000000


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float, float]:
    """비율 k/n 과 95% Wilson 신뢰구간 (표본이 작아도 0·1 밖으로 안 나감)."""
    if n <= 0:
        return (float("nan"), 0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (p, max(0.0, c - h), min(1.0, c + h))


# ───────────────────────── 점수기 ─────────────────────────
_TAG = re.compile(r"<[^>]+>")


def _term_regex(term: str) -> re.Pattern:
    """단어 앞이 영숫자가 아니어야 맞음. 앞 경계는 정규식 대신 _count에서 확인한다 — 정규식이 글자(리터럴)로
    시작해야 파이썬 re가 빠른 탐색을 쓴다 (앞에 (?<!...)가 붙으면 글자마다 검사해 수십 배 느림)."""
    star = term.endswith("*")
    t = term[:-1] if star else term
    body = r"[\s\-–]+".join(re.escape(w) for w in re.split(r"[\s]+", t.strip()))
    return re.compile(body + ("" if star else r"(?:e?s)?(?![a-z0-9])"))


def _count(rx: re.Pattern, text: str, first: bool = False) -> int:
    """앞 경계(영숫자 아님)를 지키는 일치 수 (first=True면 하나 찾는 즉시 1)."""
    n = 0
    for m in rx.finditer(text):
        i = m.start()
        if i == 0 or not ("a" <= text[i - 1] <= "z" or "0" <= text[i - 1] <= "9"):
            n += 1
            if first:
                return 1
    return n


class Scorer:
    def __init__(self, profiles: dict):
        self.p = profiles
        self.sc = profiles.get("scoring", {})
        self.ver = self.sc.get("ver", "lr")
        self.method = set(profiles.get("method_institutes", []))
        self.aff = profiles.get("domain_affinity", {})
        self.en, self.ko = {}, {}
        for inst, kw in profiles.get("keywords", {}).items():
            # (표시 이름, 정규식, 미리 거르기용 첫 단어) — 첫 단어가 글에 없으면 정규식을 돌리지 않는다 (10배 이상 빠름)
            self.en[inst] = [(t.rstrip("*"), _term_regex(t.lower()), re.split(r"[\s\-–]+", t.lower().rstrip("*").strip())[0])
                             for t in kw.get("en", [])]
            self.ko[inst] = [t for t in kw.get("ko", []) if t]
        nr = profiles.get("nonresearch", {})
        self.nr_types = set(nr.get("types", []))
        self.nr_title = [re.compile(x, re.I) for x in nr.get("title_patterns", [])]
        self.weak = {k: v for k, v in profiles.get("weak_types", {}).items() if not k.startswith("_")}

    # 키워드 적합 0~1 + 맞은 단어
    def kw(self, inst: str, title: str, abstract: str, ko_text: str) -> tuple[float, list[str]]:
        s = self.sc
        w, hits = 0.0, []
        for name, rx, lit in self.en.get(inst, []):
            if lit in title and _count(rx, title, first=True):
                w += s.get("title_weight", 2.0)
                hits.append(name)
            elif abstract and lit in abstract:
                # 초록 한 번 언급은 약하게: 검색어 자체(예: hydrology)가 거의 모든 수집 논문 초록에 들어 있다
                n = _count(rx, abstract)
                if n:
                    w += s.get("abstract_weight", 1.0) * (1.0 if n >= 2 else s.get("abstract_once", 0.4))
                    hits.append(name)
        for t in self.ko.get(inst, []):
            if t in ko_text:
                w += s.get("ko_weight", 1.5)
                hits.append(t)
        return 1 - math.exp(-w / s.get("kw_scale", 3.0)), hits

    def dom(self, inst: str, primary: str, secondary: list) -> float:
        a = self.aff.get(inst, {})
        v = a.get(primary, 0.0)
        for x in secondary or []:
            v = max(v, self.sc.get("secondary_factor", 0.6) * a.get(x, 0.0))
        return v

    def nonresearch(self, ptype: str, title: str) -> bool:
        if (ptype or "") in self.nr_types:
            return True
        t = (title or "").strip()
        return any(rx.search(t) for rx in self.nr_title)

    def score(self, home: str, paper: dict) -> dict:
        """paper: title, abstract, type, domain_primary, domain_secondary, object, problem."""
        s = self.sc
        title = _TAG.sub(" ", paper.get("title") or "").lower()
        abstract = _TAG.sub(" ", paper.get("abstract") or "").lower()
        ko_text = f"{paper.get('object') or ''} {paper.get('problem') or ''}"
        prim, sec = paper.get("domain_primary") or "", paper.get("domain_secondary") or []
        fits, kws, terms, doms = {}, {}, {}, {}
        for inst in INSTS:
            k, h = self.kw(inst, title, abstract, ko_text)
            d = self.dom(inst, prim, sec)
            kws[inst], terms[inst], doms[inst] = k, h, d
            if inst in self.method:          # 수단 연구소: 키워드 위주 (W9 같은 소유 도메인이 있으면 함께)
                fits[inst] = max(k, s.get("w_domain", .5) * d + s.get("w_keyword", .5) * k)
            else:
                fits[inst] = s.get("w_domain", .5) * d + s.get("w_keyword", .5) * k
        h = fits[home]
        topical = [i for i in INSTS if i != home and i not in self.method]
        best_o = max(topical, key=lambda i: fits[i]) if topical else None
        bo = fits[best_o] if best_o else 0.0
        raw = s.get("home_weight", .75) * h + s.get("margin_weight", .25) * min(1.0, max(0.0, 0.5 + h - bo))
        nonres = self.nonresearch(paper.get("type"), paper.get("title"))
        q = s.get("nonresearch_factor", 0.3) if nonres else self.weak.get(paper.get("type") or "", 1.0)
        score = int(round(100 * raw * q))

        # 기계 제안
        sugg, to, reason = "ok", None, None
        cands = []     # 이관 후보 (적합도, 연구소)
        if (bo >= s.get("move_min", .45) and bo - h >= s.get("move_margin", .10)
                and kws[best_o] >= s.get("move_kw_min", .4)):   # 도메인만으로는 이관 제안 안 함 (키워드 근거 필요)
            cands.append((bo, best_o))
        for m in self.method:                                    # 수단 연구소: 수단이 본 주제를 압도할 때만
            if m != home and kws[m] >= s.get("method_move_kw", .75) and kws[m] - h >= s.get("method_move_margin", .25):
                cands.append((kws[m], m))
        if nonres:
            sugg, reason = "ng", "nonresearch"
        elif cands:
            sugg, to = "move", max(cands)[1]
        elif h < s.get("ng_home_max", .30) and bo < s.get("ng_other_max", .45):
            sugg, reason = "ng", "out_of_scope"
        also = sorted([i for i in INSTS if i not in (home, to) and (
            (i in self.method and kws[i] >= s.get("share_min", .6)) or
            (i not in self.method and fits[i] >= s.get("share_min", .6) and fits[i] >= h - 0.1))],
            key=lambda i: -fits[i])
        return {"score": score, "suggestion": sugg, "to": to, "reason": reason, "also": also,
                "home_fit": round(h, 3), "home_dom": doms[home], "home_kw": round(kws[home], 3),
                "home_terms": terms[home][:8], "best_other": best_o, "best_other_fit": round(bo, 3),
                "best_other_terms": terms.get(best_o, [])[:6] if best_o else [],
                "fits": {i: round(v, 3) for i, v in fits.items()},
                "kws": {i: round(v, 3) for i, v in kws.items()},
                "nonresearch": nonres, "type_factor": q, "score_ver": self.ver}


# ───────────────────────── 항목 만들기 ─────────────────────────
_TYPE_PREF = ["article", "review", "preprint", "book-chapter", "conference-paper", "dissertation", "book",
              "report", "dataset", "software", "other"]


def _dup_key(rec: dict) -> str:
    t = re.sub(r"[^0-9a-z가-힣]+", "", _TAG.sub("", rec.get("title") or "").lower())
    return t if len(t) >= 25 else f"{t}|{rec.get('object') or ''}"     # 'Reply on RC1' 같은 짧은 제목은 대상까지 같아야 중복


def build_items(home: str, papers: list, extract: list, domain: list, abstracts: list,
                profiles: dict) -> list[dict]:
    """라벨(도메인 배정)이 있는 논문 = 판정 대상. 논문 메타·초록·대상/문제·도메인을 합쳐 점수를 매긴다.
    같은 제목의 중복 레코드(버전·심사평 여러 개 등)는 대표 1건만 큐에 올리고 나머지는 대표 판정을 따른다."""
    sc = Scorer(profiles)
    rate = profiles.get("review", {}).get("audit_rate", 0.2)
    meta = {}
    for p in papers:
        if p.get("id"):
            meta.setdefault(p["id"], p)
    ex = {e.get("id"): e for e in extract if e.get("id")}
    ab = {a.get("id"): a.get("abstract") or "" for a in abstracts if a.get("id")}
    items, seen = [], set()
    for d in domain:
        pid = d.get("id")
        if not pid or pid in seen:
            continue
        seen.add(pid)
        p, e = meta.get(pid, {}), ex.get(pid, {})
        rec = {"id": pid, "inst": home, "title": p.get("title") or "", "year": p.get("year"),
               "date": p.get("date") or "", "venue": p.get("venue") or "", "doi": p.get("doi") or "",
               "type": p.get("type") or "", "cited": int(p.get("cited") or 0),
               "abstract": ab.get(pid, ""), "object": d.get("object") or e.get("object") or "",
               "problem": d.get("problem") or e.get("problem") or "",
               "domain_primary": d.get("domain_primary") or "", "domain_secondary": d.get("domain_secondary") or [],
               "confidence": d.get("confidence"), "dup_of": None, "dups": []}
        rec.update(sc.score(home, rec))
        items.append(rec)
    groups = {}
    for it in items:
        groups.setdefault(_dup_key(it), []).append(it)
    for g in groups.values():
        if len(g) > 1:
            g.sort(key=lambda x: (_TYPE_PREF.index(x["type"]) if x["type"] in _TYPE_PREF else 99,
                                  -x["cited"], -len(x["abstract"]), x["id"]))
            g[0]["dups"] = [x["id"] for x in g[1:]]
            for x in g[1:]:
                x["dup_of"] = g[0]["id"]
    for it in items:
        it["audit"] = stable_unit(f"{home}:{it['dup_of'] or it['id']}") < rate
    return items


def reps(items: list[dict]) -> list[dict]:
    """판정 단위 = 중복 묶음의 대표."""
    return [it for it in items if not it.get("dup_of")]


def canon_map(items: list[dict]) -> dict:
    return {it["id"]: it.get("dup_of") or it["id"] for it in items}


# ───────────────────────── 판정 기록 ─────────────────────────
def make_record(item: dict, decision: str, reviewer: str, role: str, queue: str,
                to: str | None = None, also: list | None = None, reason: str | None = None,
                note: str = "") -> dict:
    return {"id": item["id"], "inst": item["inst"], "decision": decision, "to": to,
            "also": also or [], "reason": reason, "note": (note or "").strip(), "reviewer": reviewer.strip(),
            "role": role, "queue": queue, "ts": now_iso(), "score": item.get("score"),
            "suggestion": item.get("suggestion") + (f":{item['to']}" if item.get("to") else ""),
            "score_ver": item.get("score_ver"), "dups": len(item.get("dups") or [])}


def rec_key(r: dict) -> tuple:
    """판정 기록 하나를 가리키는 키 (같은 키 = 같은 판정 — 여러 파일에 중복돼도 한 번만 센다)."""
    return (r.get("id"), r.get("ts"), r.get("reviewer"), r.get("decision"), r.get("role"))


def judgment_state(records: list[dict], inst: str, canon: dict | None = None) -> dict:
    """대표 id → {'reviewer': 최신 담당자 판정, 'director': 최신 소장 판정, 'skips': n, 'skippers', 'n'}.
    건너뜀은 판정이 아니라 '건너뛴 사람'으로만 센다. 중복 레코드에 남긴 판정은 대표로 모은다."""
    canon = canon or {}
    st = {}
    for r in sorted((r for r in records if r.get("inst") == inst and r.get("id")),
                    key=lambda r: r.get("ts") or ""):
        key = canon.get(r["id"], r["id"])
        s = st.setdefault(key, {"reviewer": None, "director": None, "skips": 0, "skippers": set(), "n": 0})
        s["n"] += 1
        if r.get("decision") == "skip":
            s["skips"] += 1
            s["skippers"].add(r.get("reviewer") or "")
            continue
        if r.get("decision") not in ("ok", "ng", "move"):
            continue
        s["director" if r.get("role") == "director" else "reviewer"] = r
    return st


def js_of(item: dict, jstate: dict) -> dict | None:
    return jstate.get(item.get("dup_of") or item["id"])


def human_decision(js: dict | None) -> dict | None:
    if not js:
        return None
    return js.get("director") or js.get("reviewer")


def final_state(item: dict, js: dict | None, tau: float | None) -> tuple[str, str, str | None]:
    """(상태, 판정, 이관처). 상태: 소장 확정 / 담당자 판정 / 자동 확정 / 미검토."""
    if js and js.get("director"):
        r = js["director"]
        return "소장 확정", r["decision"], r.get("to")
    if js and js.get("reviewer"):
        r = js["reviewer"]
        return "담당자 판정", r["decision"], r.get("to")
    if tau is not None and item["suggestion"] == "ok" and item["score"] >= tau:
        return "자동 확정", "ok", None
    return "미검토", item["suggestion"], item.get("to")


# ───────────────────────── 큐 ─────────────────────────
def build_queue(items: list[dict], jstate: dict, profiles: dict, reviewer: str = "",
                tau: float | None = None, limit: int = 400) -> list[tuple[dict, str]]:
    """담당자용 판정 큐 [(item, 'audit'|'triage')]. 사람 판정이 끝난 묶음은 빠진다.
    · 감사(audit): id 해시로 고정된 무작위 표본 — 감사 목표(audit_target)까지는 audit_every장마다 1장
    · 선별(triage): 기계가 바꾸자고 한 것(NG·이관) 먼저, 그다음 점수 낮은 OK 순
    · 자동 확정 구간(제안 OK & 점수 ≥ τ)의 비감사 논문은 큐에 넣지 않는다 — 사람 손을 아끼는 지점"""
    rv = profiles.get("review", {})
    every, target = rv.get("audit_every", 4), rv.get("audit_target", 60)
    R = reps(items)
    open_ = [it for it in R if not human_decision(jstate.get(it["id"]))]
    mine = {it["id"] for it in open_ if reviewer and reviewer in (jstate.get(it["id"], {}).get("skippers") or set())}
    audit_done = sum(1 for it in R if it["audit"] and human_decision(jstate.get(it["id"])))
    audit = sorted([it for it in open_ if it["audit"]], key=lambda it: stable_unit("order:" + it["id"]))
    triage = sorted([it for it in open_ if not it["audit"] and not (
        tau is not None and it["suggestion"] == "ok" and it["score"] >= tau)],
        key=lambda it: (it["suggestion"] == "ok", it["score"], it["id"]))
    audit = [x for x in audit if x["id"] not in mine] + [x for x in audit if x["id"] in mine]     # 내가 건너뛴 건 맨 뒤로
    triage = [x for x in triage if x["id"] not in mine] + [x for x in triage if x["id"] in mine]
    # 끼워 넣는 자리는 '지금까지 기록된 묶음 수'에서 이어 센다 → 한 장 판정할 때마다 감사·선별이 번갈아 나옴
    offset = sum(1 for v in jstate.values() if v.get("n"))
    q, ai, ti, k = [], 0, 0, offset
    need = max(0, target - audit_done)
    while len(q) < limit and (ai < len(audit) or ti < len(triage)):
        gap = every if need > 0 else every * 3
        if ai < len(audit) and (ti >= len(triage) or k % gap == 0):
            q.append((audit[ai], "audit"))
            ai += 1
            need -= 1
        else:
            q.append((triage[ti], "triage"))
            ti += 1
        k += 1
    return q


def bulk_candidates(items: list[dict], jstate: dict, reason: str = "nonresearch") -> list[dict]:
    """일괄 판정 후보: 기계가 '연구 문헌 아님'으로 본 미판정 묶음 (심사평·답변 등 — 한 장씩 볼 필요가 적음)."""
    return [it for it in reps(items) if it["suggestion"] == "ng" and it.get("reason") == reason
            and not human_decision(jstate.get(it["id"]))]


def director_queue(items: list[dict], jstate: dict) -> list[tuple[dict, dict]]:
    """소장 확인 대기: 담당자 판정 뒤에 소장 기록이 없는 것. 기계와 다른 판정·NG·이관을 먼저."""
    out = []
    for it in reps(items):
        js = jstate.get(it["id"])
        if not js or not js.get("reviewer"):
            continue
        r, d = js["reviewer"], js.get("director")
        if d and (d.get("ts") or "") >= (r.get("ts") or ""):
            continue
        out.append((it, r))
    out.sort(key=lambda x: (x[1]["decision"] == x[0]["suggestion"], x[1]["decision"] == "ok", x[1].get("ts") or ""))
    return out


# ───────────────────────── 1차 샘플 ─────────────────────────
def first_round(items: list[dict], profiles: dict) -> list[dict]:
    """1차 샘플 = 감사 표본(무작위)을 고정 순서로 세워 앞에서 size장. 누가 열어도 같은 묶음."""
    n = (profiles.get("first_round") or {}).get("size", 60)
    aud = sorted([it for it in reps(items) if it["audit"]], key=lambda it: stable_unit("order:" + it["id"]))
    return aud[:n]


def by_reviewer(records: list[dict], inst: str, canon: dict | None = None) -> dict:
    """판정자 → {'dec': {대표 id: 최신 판정}, 'skip': {건너뛴 id}} (담당자·소장 모두, 사람별로 따로)."""
    canon = canon or {}
    out = {}
    for r in sorted((r for r in records if r.get("inst") == inst and r.get("id")), key=lambda r: r.get("ts") or ""):
        who = (r.get("reviewer") or "?").strip()
        d = out.setdefault(who, {"dec": {}, "skip": set()})
        key = canon.get(r["id"], r["id"])
        if r.get("decision") == "skip":
            d["skip"].add(key)
        elif r.get("decision") in ("ok", "ng", "move"):
            d["dec"][key] = r
            d["skip"].discard(key)
    return out


def sample_queue(sample: list[dict], mine: dict | None) -> list[dict]:
    """1차 샘플 중 '내가' 아직 판정 안 한 것 (다른 사람 판정과 무관 — 판정자 간 일치도를 보려고 각자 따로 본다)."""
    mine = mine or {"dec": {}, "skip": set()}
    todo = [it for it in sample if it["id"] not in mine["dec"]]
    return [it for it in todo if it["id"] not in mine["skip"]] + [it for it in todo if it["id"] in mine["skip"]]


def _label(r: dict) -> str:
    return r["decision"] + (f":{r.get('to')}" if r["decision"] == "move" else "")


def cohen_kappa(a: list[str], b: list[str]) -> float:
    n = len(a)
    if n == 0:
        return float("nan")
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[k] * cb.get(k, 0) for k in ca) / (n * n)
    return float("nan") if pe >= 1 else (po - pe) / (1 - pe)


def sample_summary(sample: list[dict], records: list[dict], inst: str, canon: dict | None = None) -> dict:
    """1차 샘플 결과: 판정자별 진행, 합의 판정(다수결·동률이면 최신), OK 비율(=기존 라벨 적합률 추정),
    기계 일치율, 판정자 간 일치(쌍별 일치율·Cohen κ)."""
    ids = [it["id"] for it in sample]
    idset = set(ids)
    rv = by_reviewer(records, inst, canon)
    prog = {w: sum(1 for i in ids if i in d["dec"]) for w, d in rv.items()}
    prog = {w: n for w, n in prog.items() if n}
    cons = {}
    for it in sample:
        votes = [d["dec"][it["id"]] for d in rv.values() if it["id"] in d["dec"]]
        if not votes:
            continue
        c = Counter(_label(v) for v in votes)
        top = max(c.values())
        tied = {k for k, v in c.items() if v == top}
        latest = max((v for v in votes if _label(v) in tied), key=lambda v: v.get("ts") or "")
        cons[it["id"]] = {"label": _label(latest), "decision": latest["decision"], "to": latest.get("to"),
                          "n": len(votes), "unanimous": len(c) == 1}
    k = sum(1 for v in cons.values() if v["decision"] == "ok")
    acc = wilson(k, len(cons))
    by = {it["id"]: it for it in sample}
    agree = sum(1 for i, v in cons.items() if v["label"] == by[i]["suggestion"] + (
        f":{by[i]['to']}" if by[i]["suggestion"] == "move" else ""))
    pairs = []
    ws = sorted(prog, key=lambda w: -prog[w])
    for x in range(len(ws)):
        for y in range(x + 1, len(ws)):
            a, b = rv[ws[x]]["dec"], rv[ws[y]]["dec"]
            common = [i for i in ids if i in a and i in b]
            if len(common) >= 5:
                la, lb = [_label(a[i]) for i in common], [_label(b[i]) for i in common]
                pairs.append({"a": ws[x], "b": ws[y], "n": len(common),
                              "agree": sum(1 for p, q in zip(la, lb) if p == q) / len(common),
                              "kappa": cohen_kappa(la, lb)})
    split = [i for i, v in cons.items() if not v["unanimous"]]
    return {"size": len(sample), "progress": prog, "consensus": cons, "judged": len(cons), "ok": k,
            "accuracy": acc, "machine_agree": agree, "pairs": pairs, "split": split,
            "votes": sum(1 for d in rv.values() for i in d["dec"] if i in idset)}


# ───────────────────────── 지표 ─────────────────────────
def _is_ok(r: dict) -> bool:
    return r.get("decision") == "ok"


def calibration(items: list[dict], jstate: dict, edges=(0, 40, 60, 80, 90, 101)) -> list[dict]:
    """점수 구간별 사람 판정 OK 비율 — 점수가 믿을 만한지(높을수록 OK가 많은지) 보는 표."""
    rows, R = [], reps(items)
    for lo, hi in zip(edges[:-1], edges[1:]):
        inbin = [it for it in R if lo <= it["score"] < hi]
        judged = [r for r in (human_decision(jstate.get(it["id"])) for it in inbin) if r]
        k = sum(1 for r in judged if _is_ok(r))
        p, lo_ci, hi_ci = wilson(k, len(judged))
        rows.append({"bin": f"{lo}–{min(hi, 100) - (0 if hi > 100 else 1)}", "lo": lo, "hi": hi,
                     "papers": len(inbin), "judged": len(judged), "ok": k, "ok_rate": p,
                     "ci_lo": lo_ci, "ci_hi": hi_ci})
    return rows


def recommend_tau(items: list[dict], jstate: dict, profiles: dict) -> dict:
    """자동 확정 문턱 τ: '기계 제안 OK & 점수 ≥ τ'인 판정 묶음의 OK 비율이 tau_precision 이상이고
    Wilson 하한이 tau_lower_bound 이상인 가장 낮은 τ (그 구간 판정이 tau_min_n건 이상일 때만).
    아직 못 정하면 잠정값(tau_provisional)을 쓰고 '보정 전'으로 표시한다."""
    rv = profiles.get("review", {})
    need, prec, lb = rv.get("tau_min_n", 15), rv.get("tau_precision", .95), rv.get("tau_lower_bound", .90)
    judged = [(it, human_decision(jstate.get(it["id"]))) for it in reps(items) if it["suggestion"] == "ok"]
    judged = [(it, r) for it, r in judged if r]
    cand = []
    for t in range(40, 100, 5):
        sel = [r for it, r in judged if it["score"] >= t]
        k = sum(1 for r in sel if _is_ok(r))
        p, lo, _ = wilson(k, len(sel))
        cand.append({"tau": t, "n": len(sel), "ok": k, "precision": p, "ci_lo": lo,
                     "pass": len(sel) >= need and p >= prec and lo >= lb})
    passing = [c for c in cand if c["pass"]]
    if passing:
        c = passing[0]
        return {"tau": c["tau"], "calibrated": True, "table": cand,
                "why": f"점수 {c['tau']} 이상 판정 {c['n']}건 중 OK {c['precision']:.0%} (95% 하한 {c['ci_lo']:.0%})"}
    t0 = rv.get("tau_provisional", 85)
    c0 = next((c for c in cand if c["tau"] == t0), {"n": 0})
    if c0["n"] < need:
        why = f"보정 전 잠정값 — 점수 {t0} 이상 판정이 {c0['n']}건 (최소 {need}건 필요)"
    else:
        why = (f"보정 전 잠정값 — 점수 {t0} 이상 판정 {c0['n']}건 중 OK {c0['precision']:.0%}, "
               f"95% 하한 {c0['ci_lo']:.0%} (기준: OK {prec:.0%} 이상·하한 {lb:.0%} 이상)")
    return {"tau": t0, "calibrated": False, "table": cand, "why": why}


def metrics(items: list[dict], jstate: dict, tau: float | None) -> dict:
    """논문(레코드) 단위 상태 비율 + 묶음(대표) 단위 판정 지표."""
    states = Counter(final_state(it, js_of(it, jstate), tau)[0] for it in items)
    R = reps(items)
    # 감사 표본 = 무작위 → 기존 라벨 적합률의 편향 없는 추정
    aud_j = [r for r in (human_decision(jstate.get(it["id"])) for it in R if it["audit"]) if r]
    k = sum(1 for r in aud_j if _is_ok(r))
    acc = wilson(k, len(aud_j))
    pairs = [(it, human_decision(jstate.get(it["id"]))) for it in R]
    pairs = [(it, r) for it, r in pairs if r]
    agree = sum(1 for it, r in pairs if it["suggestion"] == r["decision"] and
                (it["suggestion"] != "move" or it.get("to") == r.get("to")))
    ng_prop = [r for it, r in pairs if it["suggestion"] == "ng"]
    roles = Counter(r.get("role") for _, r in pairs)
    return {"N": len(items), "groups": len(R), "dup_records": len(items) - len(R),
            "states": dict(states),
            "audit_size": sum(1 for it in R if it["audit"]), "audit_judged": len(aud_j), "audit_ok": k,
            "accuracy": acc,
            "expected_bad": (None if math.isnan(acc[0]) else round((1 - acc[0]) * len(items))),
            "judged": len(pairs), "agree": agree,
            "agree_rate": (agree / len(pairs)) if pairs else float("nan"),
            "confusion": dict(Counter((it["suggestion"], r["decision"]) for it, r in pairs)),
            "ng_precision": wilson(sum(1 for r in ng_prop if r["decision"] == "ng"), len(ng_prop)),
            "moves": dict(Counter(r.get("to") for _, r in pairs if r["decision"] == "move")),
            "ng_reasons": dict(Counter(r.get("reason") or "other" for _, r in pairs if r["decision"] == "ng")),
            "reviewers": dict(Counter((r.get("reviewer") or "?", ROLE_KO.get(r.get("role"), r.get("role")))
                                      for _, r in pairs)),
            "roles": dict(roles), "suggestions": dict(Counter(it["suggestion"] for it in R))}


def final_table(items: list[dict], jstate: dict, tau: float | None) -> list[dict]:
    """최종 라벨표 (레코드 단위). decision: ok/ng/move, state: 누가 정했는지."""
    rows = []
    for it in items:
        js = js_of(it, jstate)
        s, d, to = final_state(it, js, tau)
        r = human_decision(js)
        rows.append({"id": it["id"], "inst": it["inst"], "title": it["title"], "year": it["year"],
                     "domain": it["domain_primary"], "score": it["score"],
                     "machine": it["suggestion"] + (f"→{it['to']}" if it.get("to") else "")
                     + (f"({it['reason']})" if it.get("reason") else ""),
                     "state": s, "decision": (d if s != "미검토" else "pending"), "to": (to if s != "미검토" else None),
                     "also": ",".join((r or {}).get("also") or []),
                     "reason": (r or {}).get("reason"),
                     "reviewer": (r or {}).get("reviewer"), "role": ROLE_KO.get((r or {}).get("role"), ""),
                     "ts": (r or {}).get("ts"), "audit": it["audit"], "dup_of": it.get("dup_of"),
                     "doi": it["doi"]})
    return rows


# ───────────────────────── 판정 대장 (누적 기록 정리) ─────────────────────────
KST = dt.timezone(dt.timedelta(hours=9))


def to_kst(ts: str | None) -> str:
    try:
        return dt.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc) \
            .astimezone(KST).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ts or ""


def ledger_rows(records: list[dict], items: list[dict], saved_keys: set) -> list[dict]:
    """판정 대장 — 모든 판정 기록(건너뜀 포함)을 최신순으로, 제목·기계 제안·저장 상태와 함께."""
    by = {it["id"]: it for it in items}
    out = []
    for r in sorted(records, key=lambda r: r.get("ts") or "", reverse=True):
        it = by.get(r.get("id"), {})
        out.append({"시각(KST)": to_kst(r.get("ts")), "판정자": r.get("reviewer") or "",
                    "역할": ROLE_KO.get(r.get("role"), r.get("role") or ""),
                    "판정": DECISION_KO.get(r.get("decision"), r.get("decision")),
                    "이관처": INST_NAME.get(r.get("to"), "") if r.get("to") else "",
                    "NG 사유": REASON_KO.get(r.get("reason"), "") if r.get("reason") else "",
                    "제목": _TAG.sub("", it.get("title") or "")[:100], "점수": r.get("score"),
                    "기계 제안": r.get("suggestion") or "", "큐": r.get("queue") or "", "메모": r.get("note") or "",
                    "저장": "GitHub" if rec_key(r) in saved_keys else "임시", "id": r.get("id")})
    return out


def reviewer_summary(records: list[dict], saved_keys: set) -> list[dict]:
    """판정자별 누적: OK·NG·이관·건너뜀, 판정한 논문 수, 첫·최근 판정, GitHub 저장/임시."""
    agg = {}
    for r in records:
        w = (r.get("reviewer") or "?", ROLE_KO.get(r.get("role"), r.get("role") or ""))
        a = agg.setdefault(w, {"판정자": w[0], "역할": w[1], "OK": 0, "NG": 0, "이관": 0, "건너뜀": 0,
                               "논문": set(), "첫 판정": None, "최근 판정": None, "GitHub": 0, "임시": 0})
        d = r.get("decision")
        a[{"ok": "OK", "ng": "NG", "move": "이관"}.get(d, "건너뜀")] += 1
        if d in ("ok", "ng", "move"):
            a["논문"].add(r.get("id"))
        ts = r.get("ts") or ""
        a["첫 판정"] = min(a["첫 판정"] or ts, ts)
        a["최근 판정"] = max(a["최근 판정"] or ts, ts)
        a["GitHub" if rec_key(r) in saved_keys else "임시"] += 1
    rows = []
    for a in agg.values():
        rows.append({**a, "논문": len(a["논문"]), "첫 판정": to_kst(a["첫 판정"]), "최근 판정": to_kst(a["최근 판정"])})
    return sorted(rows, key=lambda x: -x["논문"])


def daily_cumulative(records: list[dict]) -> dict:
    """판정자 → [(날짜 KST, 그날까지 누적 판정 수)] (건너뜀 제외)."""
    per = {}
    for r in records:
        if r.get("decision") not in ("ok", "ng", "move"):
            continue
        day = to_kst(r.get("ts"))[:10]
        per.setdefault(r.get("reviewer") or "?", Counter())[day] += 1
    out = {}
    for w, c in per.items():
        run, pts = 0, []
        for day in sorted(c):
            run += c[day]
            pts.append((day, run))
        out[w] = pts
    return out


# ───────────────────────── 저장 경로 ─────────────────────────
def batch_path(inst: str, reviewer: str, ts: str | None = None) -> str:
    ts = (ts or now_iso()).replace(":", "").replace("-", "")
    rid = hashlib.sha1(reviewer.strip().encode("utf-8")).hexdigest()[:6]
    return f"{HITL_DIR}/{inst}/{ts}_r{rid}.jsonl"


def prefill_urls(repo: str, branch: str, inst: str, reviewer: str, records: list[dict],
                 max_url: int = 7000) -> list[tuple[str, int]]:
    """토큰 없이 저장: GitHub '새 파일' 화면을 판정 내용으로 미리 채운 링크.
    URL이 너무 길면 여러 개로 나눈다 → [(url, 건수)]. 사용자는 링크를 열어 Commit만 누르면 된다."""
    out, chunk = [], []

    def url_for(rows, idx):
        path = batch_path(inst, reviewer)
        if idx:
            path = path.replace(".jsonl", f"_{idx}.jsonl")
        q = urllib.parse.urlencode({"filename": path, "value": to_jsonl(rows),
                                    "message": f"HITL 라벨 판정 {inst} {len(rows)}건 ({reviewer})"},
                                   quote_via=urllib.parse.quote)
        return f"https://github.com/{repo}/new/{branch}?{q}"

    for r in records:
        if chunk and len(url_for(chunk + [r], len(out))) > max_url:
            out.append((url_for(chunk, len(out)), len(chunk)))
            chunk = []
        chunk.append(r)
    if chunk:
        out.append((url_for(chunk, len(out)), len(chunk)))
    return out
