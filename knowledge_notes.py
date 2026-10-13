"""
연구소 지식노트 (Water Co-Scientist) — 계산 모듈

관제센터의 '📒 연구소 지식노트' 화면과 노트 내보내기(zip)가 공통으로 쓰는 순수 함수 모음.
Streamlit에 의존하지 않으므로 단독으로 시험할 수 있다.

입력 (data 브랜치, 라벨링 파이프라인 산출물 — 새 토큰 사용 없음):
  live/openalex/papers_<INST>.jsonl   논문 메타 (id, title, year, date, venue, doi, cited, type)
  labels/extract/<INST>.jsonl         대상·문제 추출 (object, problem, relevant)
  labels/domain/<INST>.jsonl          W 도메인 배정 (domain_primary, confidence)
  data_seed/kci_rising.json           국내 학회지(KCI) 상승 용어·공출현 네트워크

방법:
  1) 대상·문제 문구에서 핵심어를 뽑는다 (조사·일반 서술어 제거).
  2) 핵심어 공출현 네트워크 → 코사인 정규화 가중치 c_ij / sqrt(f_i f_j) → Louvain 묶음.
     (AI연구소 '상승 연구주제 탐지' 파이프라인과 같은 정규화·군집 방식을 연구소 단위로 적용)
  3) KCI 상승 용어와 연구소 문헌의 접점, 그리고 '각각은 다루지만 함께는 다루지 않은' 결합 공백 후보.
  4) 최근 N일 브리핑과 마크다운(YAML 머리말) 노트 묶음 — 특정 열람 도구에 종속되지 않음.
"""

from __future__ import annotations

import datetime as dt
import io
import json
import math
import re
import zipfile
from collections import Counter, defaultdict
from itertools import combinations

import networkx as nx

UNCLASSIFIED = "W0_UNCLASSIFIED"

DOMAIN_NAMES = {
    "W1": "유역·수문", "W2": "댐·저수지 운영", "W3": "수질·수생태", "W4": "취·정수 공정",
    "W5": "관망·급수 서비스", "W6": "하수·재이용", "W7": "물인프라 안전·자산", "W8": "물에너지",
    "W9": "관측 인프라", "W0": "경영·정책·서비스", UNCLASSIFIED: "미분류",
}

# 대상·문제 문구에 흔한 일반 서술어 — 주제를 가르지 못하므로 핵심어에서 뺀다
STOPWORDS = {
    "분석", "평가", "개선", "향상", "이해", "해결", "지원", "제공", "식별", "개발", "연구", "조사",
    "규명", "탐색", "비교", "적용", "활용", "이용", "사용", "기반", "방법", "방안", "접근", "구축",
    "설계", "성능", "효과", "영향", "변화", "문제", "과정", "결과", "감소", "증가", "강화", "확보",
    "추정", "정량화", "결정", "수준", "기능", "가능성", "잠재력", "전략", "지속", "시스템", "모델",
    "모델링", "관리", "정확도", "정확성", "효율", "효율성", "세계", "지구", "지역", "구역", "인간",
    "과학", "일일", "전체", "대규모", "국가", "주요", "특성", "요인", "관계", "상관", "메커니즘",
    "역할", "필요", "필요성", "현황", "동향", "사례", "검토", "도출", "제시", "고려", "기여",
    "높은", "낮은", "작은", "좋은", "많은", "새로운", "다양한", "위한", "통한", "대한", "관한",
    "따른", "인한", "의한", "미치는", "간의", "및", "등", "중", "간", "내", "수", "것",
    "물의", "물을", "물에", "물과", "물이",
}

# KCI 상승 용어 중 논문 서술에 흔한 일반어 — 접점·공백 계산에서 뺀다
GENERIC_KCI = {
    "진행", "규모", "반면", "바탕", "과거", "미래", "상황", "중심", "추가", "최대", "최소", "평균",
    "정보", "수집", "지표", "필수", "우수", "종합", "생성", "검증", "분류", "선정", "분야", "기초자료",
    "사회", "면적", "안정", "변동", "기술", "공간", "운영", "환경", "성능", "정확도", "지속", "단위",
    "해당", "마련", "세계", "관련", "계획", "유형", "설정", "존재", "패턴", "연계", "위치", "포함",
    "동안", "전반", "개별", "시행", "최종", "심도", "이동", "실정", "사상", "한계점", "실무", "확대",
    "현황", "강화", "지원", "사전", "추후", "시기", "인근", "전국", "발달", "제약", "시점", "지수",
    "상관", "상관계수", "국가", "한국", "한반도", "지상", "예방", "시설", "생산", "수리", "추세",
    "재현", "시공간", "유입", "고도", "국지", "대책", "전략",
}

_ADJ_ENDINGS = ("적인", "한", "된", "른", "운", "던", "는", "하기", "하여", "하고")
_JEOK_NOUNS = ("축적", "면적", "누적", "체적", "목적", "흔적", "표적", "실적", "업적", "지적")
_JOSA = ("에서의", "에서", "으로", "에의", "과의", "와의", "의", "에", "을", "를", "은", "과", "와", "로", "적")
_TOKEN_RE = re.compile(r"[가-힣]+|[A-Za-z][A-Za-z0-9\-]+")
_KEEP_SINGLE = {"댐"}                                 # 한 글자지만 주제를 가르는 명사


# ───────────────────────── 핵심어 ─────────────────────────
def normalize_token(tok: str) -> str | None:
    """조사·형용사 어미를 정리한 핵심어. 버릴 토큰이면 None."""
    if not tok:
        return None
    if tok[0].isascii():
        if len(tok) < 3 and not tok.isupper():
            return None
        return tok if tok.isupper() else tok.lower()
    if tok in STOPWORDS:
        return None
    if len(tok) == 1:
        return tok if tok in _KEEP_SINGLE else None
    if len(tok) == 2 and tok[0] in _KEEP_SINGLE and tok[1] in "의에을를은과와로이가":
        return tok[0]                                 # 댐의·댐을 → 댐
    if len(tok) >= 3 and tok.endswith(_ADJ_ENDINGS):
        return None
    for j in _JOSA:
        if j == "적" and tok.endswith(_JEOK_NOUNS):
            continue                                  # 축적·면적·누적 등은 명사 그대로
        if tok.endswith(j) and len(tok) - len(j) >= 2:
            tok = tok[: -len(j)]
            break
    if len(tok) < 2 or tok in STOPWORDS:
        return None
    return tok


def keywords(text: str) -> set[str]:
    out = set()
    for raw in _TOKEN_RE.findall(text or ""):
        t = normalize_token(raw)
        if t:
            out.add(t)
    return out


# ───────────────────────── 코퍼스 ─────────────────────────
def build_corpus(papers: list[dict], extract: list[dict], domain: list[dict],
                 water_only: bool = True) -> list[dict]:
    """논문 메타 + 대상·문제 + 도메인을 id로 합친 레코드. 물 관련(relevant)만 남긴다."""
    ex = {e.get("id"): e for e in extract if e.get("id")}
    dm = {d.get("id"): d for d in domain if d.get("id")}
    recs, seen = [], set()
    for p in papers:
        pid = p.get("id")
        if not pid or pid in seen or pid not in ex:
            continue
        seen.add(pid)
        e = ex[pid]
        if not e.get("relevant", True):
            continue
        dom = (dm.get(pid) or {}).get("domain_primary")
        if water_only and dom == UNCLASSIFIED:
            continue
        obj, prob = (e.get("object") or "").strip(), (e.get("problem") or "").strip()
        recs.append({
            "id": pid, "title": p.get("title") or "", "year": p.get("year"),
            "date": p.get("date") or "", "venue": p.get("venue") or "", "doi": p.get("doi") or "",
            "cited": int(p.get("cited") or 0), "type": p.get("type") or "",
            "object": obj, "problem": prob, "domain": dom,
            "text": f"{obj} {prob}", "compact": re.sub(r"\s+", "", f"{obj}{prob}").lower(),
            "kw": sorted(keywords(f"{obj} {prob}")),
        })
    return recs


# ───────────────────────── 주제 네트워크 ─────────────────────────
def topic_network(recs: list[dict], max_terms: int = 60, min_df: int = 3,
                  min_co: int = 2, seed: int = 0) -> dict:
    """핵심어 공출현 네트워크 + Louvain 묶음 + 문헌별 묶음 배정."""
    df = Counter(t for r in recs for t in r["kw"])
    terms = [t for t, n in df.most_common() if n >= min_df][:max_terms]
    tset = set(terms)
    co = Counter()
    for r in recs:
        ks = sorted(t for t in r["kw"] if t in tset)
        for a, b in combinations(ks, 2):
            co[(a, b)] += 1
    G = nx.Graph()
    G.add_nodes_from(terms)
    for (a, b), c in co.items():
        if c >= min_co:
            G.add_edge(a, b, weight=c / math.sqrt(df[a] * df[b]), count=c)
    G.remove_nodes_from([n for n in list(G) if G.degree(n) == 0])

    comms = []
    if G.number_of_edges():
        parts = nx.community.louvain_communities(G, weight="weight", seed=seed)
        parts = sorted(parts, key=lambda s: (-len(s), -sum(df[t] for t in s)))
        for i, part in enumerate(parts):
            ts = sorted(part, key=lambda t: -df[t])
            comms.append({"id": f"T{i + 1:02d}", "terms": ts, "size": len(ts),
                          "label": " · ".join(ts[:3])})
    term_comm = {t: c["id"] for c in comms for t in c["terms"]}

    assign = {}
    for r in recs:
        hits = Counter(term_comm[t] for t in r["kw"] if t in term_comm)
        if hits:
            best = max(hits.values())
            assign[r["id"]] = min(c for c, n in hits.items() if n == best)
    for c in comms:
        c["papers"] = [r["id"] for r in recs if assign.get(r["id"]) == c["id"]]

    return {
        "nodes": [{"term": t, "df": df[t], "comm": term_comm.get(t)} for t in G.nodes],
        "edges": [(u, v, round(d["weight"], 4), d["count"]) for u, v, d in G.edges(data=True)],
        "communities": comms, "assign": assign, "term_comm": term_comm,
    }


# ───────────────────────── 상승 용어 접점 ─────────────────────────
def _term_hits(term: str, recs: list[dict]) -> list[str]:
    key = term.lower()
    return [r["id"] for r in recs if key in r["compact"]]


def rising_touchpoints(recs: list[dict], scope: dict, include_minor: bool = False) -> list[dict]:
    """KCI 상승 용어 각각이 연구소 문헌(대상·문제)에 몇 편 등장하는지."""
    out = []
    for r in scope.get("rising", []):
        term = r.get("term", "")
        if not term or term in GENERIC_KCI or term in STOPWORDS:
            continue
        if r.get("minor") and not include_minor:
            continue
        ids = _term_hits(term, recs)
        out.append({"term": term, "sen": r.get("sen", 0.0), "recent_docs": r.get("recent_docs", 0),
                    "lift": r.get("lift"), "q": r.get("q"), "minor": bool(r.get("minor")),
                    "n_inst": len(ids), "share": len(ids) / max(1, len(recs)), "ids": ids})
    return out


def gap_candidates(touch: list[dict], scope: dict, top: int = 12, min_inst: int = 2) -> list[dict]:
    """결합 공백 후보: 두 상승 용어를 연구소가 각각은 다루지만 함께 다룬 문헌이 없는 조합.
    국내 학회지에서도 함께 나온 적이 드물수록(서로 다른 묶음, 공출현 적음) 위로 올린다."""
    net = scope.get("network", {})
    kdf = {n["term"]: n.get("df", 0) for n in net.get("nodes", [])}
    kcomm = {t: c["id"] for c in net.get("communities", []) for t in c["terms"]}
    kw = {}
    for u, v, w in net.get("edges", []):
        kw[frozenset((u, v))] = w
    cand = [t for t in touch if t["n_inst"] >= min_inst and t["term"] in kdf]
    out = []
    for a, b in combinations(cand, 2):
        if a["term"] in b["term"] or b["term"] in a["term"]:
            continue                                  # 기후 ⊂ 기후변화 같은 포함 관계 제외
        both = set(a["ids"]) & set(b["ids"])
        if both:
            continue
        w = kw.get(frozenset((a["term"], b["term"])), 0)
        cross = kcomm.get(a["term"]) != kcomm.get(b["term"])
        score = min(a["n_inst"], b["n_inst"]) * math.sqrt(kdf[a["term"]] * kdf[b["term"]]) / (1 + w)
        if cross:
            score *= 1.5
        out.append({"a": a["term"], "b": b["term"], "n_a": a["n_inst"], "n_b": b["n_inst"],
                    "kci_co": w, "cross": cross, "score": round(score, 2),
                    "ids_a": a["ids"], "ids_b": b["ids"]})
    out.sort(key=lambda g: -g["score"])
    return out[:top]


# ───────────────────────── 최근 브리핑 ─────────────────────────
def _parse_date(s: str):
    try:
        return dt.date.fromisoformat((s or "")[:10])
    except ValueError:
        return None


def recent(recs: list[dict], today: dt.date, days: int = 30) -> list[dict]:
    lo = today - dt.timedelta(days=days)
    rs = [r for r in recs if (d := _parse_date(r["date"])) and lo <= d <= today]
    return sorted(rs, key=lambda r: (r["date"], r["cited"]), reverse=True)


def briefing_markdown(code: str, name: str, recs_recent: list[dict], n_all: int, days: int,
                      today: dt.date, touch: list[dict], net: dict,
                      domain_names: dict | None = None) -> str:
    dn = domain_names or DOMAIN_NAMES
    lines = [f"# {code} {name} · 최근 {days}일 문헌 브리핑",
             "", f"- 기준일: {today.isoformat()} · 발행일 기준 · 물 관련 문헌 {n_all:,}편 중 {len(recs_recent)}편", ""]
    if not recs_recent:
        lines.append("이 기간에 발행된 수집 문헌이 없습니다.")
        return "\n".join(lines) + "\n"
    dc = Counter(r["domain"] for r in recs_recent if r["domain"])
    lines.append("## 도메인")
    lines += [f"- {d} {dn.get(d, d)}: {n}편" for d, n in dc.most_common(5)]
    kc = Counter(t for r in recs_recent for t in r["kw"])
    lines += ["", "## 자주 나온 핵심어", "- " + ", ".join(f"{t}({n})" for t, n in kc.most_common(10))]
    ids = {r["id"] for r in recs_recent}
    tp = sorted(((t["term"], len(ids & set(t["ids"]))) for t in touch), key=lambda x: -x[1])
    tp = [(t, n) for t, n in tp if n]
    if tp:
        lines += ["", "## 국내 상승 용어와 겹친 문헌", "- " + ", ".join(f"{t}({n})" for t, n in tp[:8])]
    tc = Counter(net["assign"].get(r["id"]) for r in recs_recent if net["assign"].get(r["id"]))
    lab = {c["id"]: c["label"] for c in net["communities"]}
    if tc:
        lines += ["", "## 토픽 묶음별", *[f"- {c} {lab.get(c, '')}: {n}편" for c, n in tc.most_common(5)]]
    lines += ["", "## 주목 문헌 (피인용·최신순)"]
    for r in sorted(recs_recent, key=lambda r: (r["cited"], r["date"]), reverse=True)[:8]:
        link = f" — {r['doi']}" if r["doi"] else ""
        lines.append(f"- {r['date']} · {r['title']} ({r['venue'] or '출처 미상'}){link}"
                     f"\n  - 대상: {r['object']} / 문제: {r['problem']}")
    lines += ["", "> 규칙 기반 자동 요약입니다(LLM 미사용). 대상·문제는 라벨링 파이프라인 추출값입니다."]
    return "\n".join(lines) + "\n"


# ───────────────────────── 노트 내보내기 (zip) ─────────────────────────
def _y(v) -> str:
    """YAML 값 — JSON 문자열/배열은 그대로 유효한 YAML이다."""
    return json.dumps(v, ensure_ascii=False)


def _yaml(d: dict) -> str:
    return "---\n" + "\n".join(f"{k}: {_y(v)}" for k, v in d.items() if v not in (None, "")) + "\n---\n"


def build_vault_zip(code: str, name: str, recs: list[dict], net: dict, touch: list[dict],
                    gaps: list[dict], brief_md: str, scope_label: str,
                    abstracts: dict | None = None, domain_names: dict | None = None,
                    today: dt.date | None = None) -> tuple[bytes, int]:
    """연구소 지식노트 폴더(zip). 반환: (zip 바이트, 파일 수)."""
    dn = domain_names or DOMAIN_NAMES
    today = today or dt.date.today()
    root = f"{code}_{name}"
    comm = {c["id"]: c for c in net["communities"]}
    rising_terms = {t["term"] for t in touch if t["n_inst"]}
    by_id = {r["id"]: r for r in recs}
    files: dict[str, str] = {}

    def plink(pid: str, base: str = "..") -> str:
        r = by_id[pid]
        return f"[{r['title'] or pid}]({base}/papers/{pid}.md)"

    # 문헌 노트
    for r in recs:
        tid = net["assign"].get(r["id"])
        head = _yaml({
            "id": r["id"], "title": r["title"], "year": r["year"], "date": r["date"],
            "venue": r["venue"], "doi": r["doi"], "cited": r["cited"],
            "institute": code, "institute_name": name,
            "domain": r["domain"], "domain_name": dn.get(r["domain"]) if r["domain"] else None,
            "object": r["object"], "problem": r["problem"], "topic": tid,
            "keywords": r["kw"], "tags": [code, *( [r["domain"]] if r["domain"] else [] ), *( [tid] if tid else [] )],
        })
        body = [f"# {r['title'] or r['id']}", "",
                f"- **대상:** {r['object']}", f"- **문제:** {r['problem']}"]
        if r["domain"]:
            body.append(f"- **도메인:** {r['domain']} {dn.get(r['domain'], '')}")
        if tid:
            body.append(f"- **토픽:** [{tid} · {comm[tid]['label']}](../topics/{tid}.md)")
        if r["doi"]:
            body.append(f"- **DOI:** <{r['doi']}>")
        ab = (abstracts or {}).get(r["id"])
        if ab:
            body += ["", "## 초록", "", ab]
        files[f"papers/{r['id']}.md"] = head + "\n" + "\n".join(body) + "\n"

    # 토픽 노트
    for c in net["communities"]:
        ps = sorted((by_id[p] for p in c["papers"]), key=lambda r: (-r["cited"], r["date"]))
        dc = Counter(r["domain"] for r in ps if r["domain"])
        head = _yaml({"id": c["id"], "label": c["label"], "institute": code, "terms": c["terms"],
                      "papers": len(ps), "tags": [code, "topic"]})
        body = [f"# {c['id']} · {c['label']}", "", "## 대표 용어", "",
                ", ".join(f"**{t}**" if t in rising_terms else t for t in c["terms"]),
                "", "_굵은 글씨 = 국내 학회지 상승 용어와 겹침_", "", "## 도메인 구성", ""]
        body += [f"- {d} {dn.get(d, d)}: {n}편" for d, n in dc.most_common()] or ["- (도메인 라벨 없음)"]
        body += ["", f"## 문헌 ({len(ps)}편, 피인용순)", ""]
        body += [f"- {plink(r['id'])} ({r['year'] or '-'}, {r['venue'] or '출처 미상'})" for r in ps]
        files[f"topics/{c['id']}.md"] = head + "\n" + "\n".join(body) + "\n"

    # 상승 용어 접점
    rl = [_yaml({"institute": code, "kci_scope": scope_label, "tags": [code, "rising"]}),
          f"# {code} {name} · 국내 상승 용어 접점 ({scope_label})", "",
          "| 용어 | 기울기(‰/년) | 국내 최근3년 논문 | 우리 문헌 | 비율 |", "|---|---:|---:|---:|---:|"]
    for t in sorted(touch, key=lambda t: (-t["n_inst"], -t["sen"])):
        rl.append(f"| {t['term']} | {t['sen'] * 1000:.2f} | {t['recent_docs']} | {t['n_inst']} | {t['share'] * 100:.1f}% |")
    files["rising.md"] = "\n".join(rl) + "\n"

    # 결합 공백 후보
    gl = [_yaml({"institute": code, "kci_scope": scope_label, "tags": [code, "gap"]}),
          f"# {code} {name} · 결합 공백 후보", "",
          "두 상승 용어를 우리 연구소 문헌이 **각각은** 다루지만 **함께 다룬 문헌은 없는** 조합입니다. "
          "국내 학회지에서도 함께 나온 적이 드물수록 위에 둡니다. 후보일 뿐이며 전문가 검토가 필요합니다.", ""]
    for i, g in enumerate(gaps, 1):
        gl += [f"## {i}. {g['a']} × {g['b']}", "",
               f"- 우리 문헌: {g['a']} {g['n_a']}편 · {g['b']} {g['n_b']}편 · 함께 0편",
               f"- 국내 학회지 최근 5년 함께 등장: {g['kci_co']}편" + (" · 서로 다른 국내 묶음" if g["cross"] else ""),
               f"- {g['a']} 대표 문헌: " + "; ".join(plink(p, ".") for p in g["ids_a"][:3]),
               f"- {g['b']} 대표 문헌: " + "; ".join(plink(p, ".") for p in g["ids_b"][:3]), ""]
    files["gaps.md"] = "\n".join(gl) + "\n"

    files["briefing.md"] = brief_md

    # 첫 화면
    dc_all = Counter(r["domain"] for r in recs if r["domain"])
    idx = [_yaml({"institute": code, "institute_name": name, "generated": today.isoformat(),
                  "papers": len(recs), "topics": len(net["communities"]), "tags": [code, "index"]}),
           f"# {code} {name} · 연구 지식노트", "",
           f"생성일 {today.isoformat()} · 물 관련 문헌 {len(recs):,}편 · 토픽 묶음 {len(net['communities'])}개", "",
           "## 토픽 묶음", ""]
    idx += [f"- [{c['id']} · {c['label']}](topics/{c['id']}.md) — 문헌 {len(c['papers'])}편, 용어 {c['size']}개"
            for c in net["communities"]]
    idx += ["", "## 도메인", ""] + [f"- {d} {dn.get(d, d)}: {n}편" for d, n in dc_all.most_common()]
    idx += ["", "## 바로가기", "", "- [최근 브리핑](briefing.md)", f"- [국내 상승 용어 접점](rising.md) ({scope_label})",
            "- [결합 공백 후보](gaps.md)", "",
            "## 열어 보는 법", "",
            "이 폴더는 마크다운 + YAML 머리말이라 특정 프로그램에 묶이지 않습니다. "
            "Logseq·Obsidian·VS Code(Foam)에서 폴더째 열거나, Quartz로 사내 웹페이지로 배포할 수 있습니다.", "",
            "## 출처와 방법", "",
            "- 문헌: OpenAlex 수집 (Water Co-Scientist openalex-collector)",
            "- 대상·문제·도메인: 라벨링 파이프라인 추출값 (labels/extract, labels/domain)",
            "- 토픽 묶음: 대상·문제 핵심어 공출현 → 코사인 정규화 → Louvain (seed 0)",
            f"- 상승 용어: 국내 학회지 KCI 상승 용어 ({scope_label}), Hamed–Rao MK + BH 보정"]
    files["README.md"] = "\n".join(idx) + "\n"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for path, text in sorted(files.items()):
            z.writestr(f"{root}/{path}", text)
    return buf.getvalue(), len(files)


def topic_note_preview(c: dict, recs: list[dict], code: str, domain_names: dict | None = None,
                       rising_terms: set | None = None, max_papers: int = 8) -> str:
    """화면용 토픽 노트 미리보기 (내보내기 노트와 같은 형식, 문헌은 일부만)."""
    dn = domain_names or DOMAIN_NAMES
    by_id = {r["id"]: r for r in recs}
    ps = sorted((by_id[p] for p in c["papers"] if p in by_id), key=lambda r: (-r["cited"], r["date"]))
    dc = Counter(r["domain"] for r in ps if r["domain"])
    rt = rising_terms or set()
    out = [_yaml({"id": c["id"], "label": c["label"], "institute": code, "terms": c["terms"], "papers": len(ps)}),
           f"# {c['id']} · {c['label']}", "", "## 대표 용어", "",
           ", ".join(f"**{t}**" if t in rt else t for t in c["terms"]), "", "## 도메인 구성", ""]
    out += [f"- {d} {dn.get(d, d)}: {n}편" for d, n in dc.most_common()] or ["- (도메인 라벨 없음)"]
    out += ["", f"## 문헌 ({len(ps)}편 중 {min(len(ps), max_papers)}편)", ""]
    out += [f"- [{r['title']}](../papers/{r['id']}.md) ({r['year'] or '-'})" for r in ps[:max_papers]]
    return "\n".join(out) + "\n"
