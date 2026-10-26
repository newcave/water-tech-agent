#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kci_rising — 한국 저널(KCI) 상승 연구주제 탐지 v0.2 (유니그램 + 바이그램)

입력: {KCI_RAW_DIR}/raw/{코드}/{연도}.jsonl  (kci_collect.py가 비공개 저장소에 모은 원천)
출력: data_seed/kci_rising.json               (공개 — 용어·연도별 빈도와 검정 결과 같은 집계만)
      data_seed/kci_kwater.json               (공개 — K-water 소속 논문 연도별 수·학회지 내 비중·게재지·협업기관 집계)

방법 (논문 설계 그대로):
  1. 용어 추출: 국문 제목+초록(없으면 영문)을 Kiwi 형태소 분석 → 띄어쓰기 없이 붙은 명사열을
     복합어로 묶음(예: 딥+러닝 → 딥러닝, 유출+량 → 유출량). 영문 약어(SL)도 포함. 논문당 집합(문서빈도).
  2. 상대 문서빈도 rel_y = DF_y / N_y  (N_y = 그 해 논문 수, 진행 중인 올해 제외)
  3. Hamed–Rao 수정 Mann–Kendall + Sen 기울기 → Benjamini–Hochberg FDR (q<0.05)
  4. 공출현 네트워크: 상승 용어끼리 최근 5년 논문에서 함께 나온 횟수 → Louvain 커뮤니티
  5. 바이그램(v0.2): 띄어 쓴 두 명사(복합어)가 바로 이어지거나 '의'로 이어진 구 — "홍수 피해", "저수지 운영",
     "하천의 수질" → "하천 수질". 붙여 쓴 형태("하천수질")도 같은 구로 센다. 그 붙여 쓴 형태가 이미 단어 탭의
     상승 용어면 중복이라 뺀다. 구는 드물어(연도별 0이 많음) MK 검정력이 낮으므로, 같은 상대빈도를
     준포아송 회귀(연도 추세, 분모 = 그 해 논문 수, 과산포 보정)로 검정 → BH FDR(구끼리 따로).
     두 단어 모두 단어 단위로는 상승 목록에 없으면 '구로만 보이는 신호'(novel).
     구에서는 뜻이 살아나는 머리말(관리·대응·구축·개선)은 불용어에서 풀고, 수식어(실제·일반 등)와
     숫자에 붙은 단위어(2차원의 '차원')는 구를 만들지 않는다. 제목과 초록 사이는 끊는다.

범위: 'J11'(한국수자원학회논문집 단독), 'J11+J12'(대한토목학회논문집 포함),
      'KWATER'(KCI 전체의 K-water 소속 논문 — 분모도 K-water 논문 수)로 계산.
  J12는 2012년까지 분야별 분책 A~D(구조·교통 등 포함)였다가 2013년에 통합 → 토목 전반 용어가 섞임.
출처: KCI(한국학술지인용색인) 데이터 활용
"""
import json
import os
import re
import sys
import time
from collections import Counter
from itertools import combinations
from pathlib import Path

import networkx as nx
import numpy as np
import pymannkendall as mk
from kiwipiepy import Kiwi

from kwater_rules import affil_is_kwater, is_kwater, load_overrides

OV = load_overrides(os.environ.get("KCI_RAW_DIR", "private"))    # 사람 판정 (tools/kwater_hitl.html 결과)

ROOT = Path(__file__).resolve().parents[1]
RAW = Path(os.environ.get("KCI_RAW_DIR", "private")) / "raw"
OUT = ROOT / "data_seed" / "kci_rising.json"
OUT_KW = ROOT / "data_seed" / "kci_kwater.json"
Q = 0.05
MIN_TOTAL_DF = 20                  # 검정 대상 최소 누적 문서빈도
MIN_YEARS_PRESENT = 5              # 검정 대상 최소 등장 연도 수
MIN_RECENT_DOCS = 8                # 최근 3년 문서빈도가 이보다 적으면 '저빈도' 표시
NET_TERMS = 80                     # 공출현 네트워크에 넣을 상승 용어 수
NET_WINDOW = 5                     # 공출현을 셀 최근 연도 수
NET_MIN_CO = 3                     # 간선 최소 공출현 수
SCOPES = {"J11": ["J11"], "J11+J12": ["J11", "J12"], "KWATER": ["KWATER"]}
NOUN = {"NNG", "NNP", "SL"}
STOP = set("""
연구 분석 결과 방법 본연구 경우 사용 적용 이용 제시 검토 평가 비교 고려 대상 기존 모형 모델 방안 특성 영향
정도 이상 이하 각각 조건 변화 과정 차이 효과 관계 경향 가능성 필요 수행 개발 제안 확인 도출 산정 파악 활용
자료 데이터 기반 기법 시스템 요소 지역 대한 따른 통한 위한 이후 이전 전체 부분 기간 시간 연도 수준 범위 목적
문제 기준 측면 결과값 본논문 논문 사례 실험 연구결과 분석결과 study analysis results method model data using
based paper proposed approach case korea korean
발생 증가 감소 가능 대비 다양 기대 최근 향후 중요 국내 국외 제공 주요 판단 개선 구축 수립 정량 정성 대응 관리
기여 도움 향상 확보 실시 고찰 파악 규명 제고 도입 반영 필요성 문제점 한계 장점 단점 측면 관점 사항 내용 부분
일부 대부분 다수 상대 가지 이상 이하 이내 정도 수치 결과값 분석결과 연구결과 본연구 본논문 선행연구 기존연구
시사점 의미 의의 중요성 효율 효율성 적절 유의 유의미 통계 비교분석 사용 경우 형태 방식 구성 과정 단계 수행
""".split())
BI_HEAD_OK = {"관리", "대응", "구축", "개선"}   # 바이그램에서는 살려 두는 불용어 (예: 저수지 관리, 가뭄 대응)
BI_MODIFIER = set("실제 일반 각종 해당 여러 모든 새로운 기타 각각 동일 특정 전반 일련 다음 아래 위 상기".split())
BI_STOP = (STOP - BI_HEAD_OK) | BI_MODIFIER
BI_MIN_TOTAL_DF = 8                # 바이그램은 드물어 문턱을 낮춤
BI_MIN_YEARS_PRESENT = 3
BI_MIN_RECENT_DOCS = 5
HANGUL_MIN_RATIO = 0.5             # 이 비율 미만 초록 보유 학회지·연도는 제외 (초록 유무 편향 방지)
ACRONYM = re.compile(r"^[A-Z][A-Z0-9]{1,11}$")   # 영문은 전부 대문자인 약어(LSTM·SWAT·GIS·SSP)만
HANGUL = re.compile("[가-힣]")


def load_docs(codes: list):
    """→ ({연도: [국문 제목+초록, ...]}, 제외 통계).
    · 국문 제목·초록이 없는 영문 전용 논문은 제외 (영어 기능어가 섞이는 문제, 영문 분석은 다음 단계)
    · 국문 초록 보유율이 HANGUL_MIN_RATIO 미만인 학회지·연도는 통째로 제외 (예: 대한토목학회논문집 2002–2003)"""
    docs, excl = {}, {"english_only": 0, "low_abstract_years": []}
    for c in codes:
        for p in sorted((RAW / c).glob("*.jsonl")):
            rows = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
            if c == "KWATER":                                    # 검색 결과 중 K-water 판정된 것만
                rows = [r for r in rows if is_kwater(r, OV)]
            if not rows:
                continue
            ko = [r for r in rows if HANGUL.search((r.get("title_ko") or "") + (r.get("abstract_ko") or ""))]
            excl["english_only"] += len(rows) - len(ko)
            with_abs = sum(bool(r.get("abstract_ko")) for r in ko)
            if ko and with_abs / len(ko) < HANGUL_MIN_RATIO:
                excl["low_abstract_years"].append(f"{c}-{p.stem}")
                continue
            for r in ko:
                y = int(r.get("year") or p.stem)
                ti, ab = r.get("title_ko"), r.get("abstract_ko")
                text = " ".join(x for x in (ti, ab) if x)
                # 제목·초록 경계 위치 — 바이그램만 여기서 끊는다 (단어 추출은 v0.1과 똑같은 글로 해 결과 불변)
                docs.setdefault(y, []).append((text, len(ti) if ti and ab else None, c))
    return docs, excl


def read_raw(code: str):
    for p in sorted((RAW / code).glob("*.jsonl")):
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                yield json.loads(line)


def kwater_summary(y1: int) -> dict:
    """K-water 소속 논문 집계 (공개용 — 개인 이름 없음, 기관명·건수만)."""
    by_year, journals, units, partners = Counter(), Counter(), Counter(), Counter()
    for r in read_raw("KWATER"):
        if not is_kwater(r, OV):
            continue
        y = int(r.get("year") or 0)
        by_year[y] += 1
        journals[r.get("journal")] += 1
        for a in r.get("authors", []):
            aff = a.get("affil") or ""
            if not aff:
                continue
            if affil_is_kwater(aff, OV):
                units[aff] += 1
            else:
                partners[aff.split(",")[-1].strip()] += 1          # 기관 단위(마지막 쉼표 뒤)
    share = {}
    for code in ("J11", "J12"):
        tot, kw = Counter(), Counter()
        for r in read_raw(code):
            y = int(r.get("year") or 0)
            tot[y] += 1
            kw[y] += is_kwater(r, OV)
        share[code] = {str(y): {"n": tot[y], "kwater": kw[y]} for y in sorted(tot) if y <= y1}
    return {"source": "KCI(한국학술지인용색인) 데이터 활용 — 집계만 공개, 원천 데이터·개인 이름 미포함",
            "human_review": {"files": len(OV["files"]),
                             "rules": {k: len(OV[k]) for k in ("affiliation_include", "affiliation_exclude",
                                                               "paper_include", "paper_exclude")},
                             "conflicts": sum(len(v) for v in OV["conflicts"].values())},
            "updated": int(time.time()),
            "by_year": {str(y): by_year[y] for y in sorted(by_year)},
            "total": sum(by_year.values()),
            "journals": journals.most_common(25),
            "kwater_units": units.most_common(20),
            "partners": partners.most_common(25),
            "journal_share": share,
            "refresh": refresh_info()}


def refresh_info() -> dict:
    """최근 연도 창 다시 받기 현황 (비공개 manifest의 연도별 마지막 수집 시각만 — 원천 데이터 아님)."""
    try:
        man = json.loads((RAW.parent / "manifest.json").read_text(encoding="utf-8"))
    except Exception:
        return {}
    rf = man.get("refresh") or {}
    yrs = (man.get("journals", {}).get("KWATER") or {}).get("years", {})
    return {"window_years": rf.get("window_years"), "rotate": rf.get("rotate"),
            "fetched": {y: v["fetched"] for y, v in sorted(yrs.items()) if v.get("fetched")}}


def _compound(run: list) -> str:
    w = "".join(run)
    if not HANGUL.search(w):                          # 영문: 약어(대문자 포함)만, 일반 영어 단어 제외
        w = w if ACRONYM.match(w) else ""
    return w


def _ok(w: str, stop: set) -> bool:
    return bool(w) and len(w) >= 2 and w not in stop and w.lower() not in stop and not w.isdigit()


def terms_and_phrases(kiwi: Kiwi, text: str, boundary: int | None = None) -> tuple:
    """한 번 형태소 분석해 (유니그램 집합, 바이그램 집합).
    유니그램: 붙어 있는 명사열 → 복합어 (v0.1과 동일). 바이그램: 복합어 둘이 띄어쓰기만 두고 이어지거나
    '의'(관형격 조사) 하나로 이어진 구. 그 사이에 다른 형태소(동사·부호 등)가 끼면 끊는다."""
    units, run, last_end = [], [], -1                  # units: ("N"|"n", 복합어) | ("G", "의") | ("X", None)
    num_end, num_run = -2, False                       # "n": 숫자 바로 뒤에 붙은 명사열 (2차원 → 차원) — 단어로는 쓰고 구는 안 만듦
    for tok in kiwi.tokenize(text):
        if boundary is not None and tok.start > boundary:  # 제목 → 초록으로 넘어가는 자리: 구를 끊음 (단어엔 영향 없음)
            if run:
                units.append(("n" if num_run else "N", _compound(run)))
                run = []
            units.append(("X", None))
            boundary = None
        if tok.tag in NOUN:
            if run and tok.start == last_end:
                run.append(tok.form)
            else:
                if run:
                    units.append(("n" if num_run else "N", _compound(run)))
                run = [tok.form]
                num_run = tok.start == num_end
            last_end = tok.start + tok.len
            continue
        if run:
            units.append(("n" if num_run else "N", _compound(run)))
            run = []
        if tok.tag == "SN":
            num_end = tok.start + tok.len
        units.append(("G", "의") if tok.tag == "JKG" and tok.form == "의" else ("X", None))
    if run:
        units.append(("n" if num_run else "N", _compound(run)))
    uni = {w for k, w in units if k in ("N", "n") and _ok(w, STOP)}
    bi = set()
    for i in range(len(units) - 1):
        if units[i][0] != "N":
            continue
        if units[i + 1][0] == "N":
            j = i + 1
        elif units[i + 1][0] == "G" and i + 2 < len(units) and units[i + 2][0] == "N":
            j = i + 2
        else:
            continue
        a, b = units[i][1], units[j][1]
        if a != b and _ok(a, BI_STOP) and _ok(b, BI_STOP):
            bi.add(f"{a} {b}")
    return uni, bi


def terms_of(kiwi: Kiwi, text: str) -> set:
    """붙어 있는 명사열 → 복합어. 한 글자 한글·불용어·숫자 제외."""
    return terms_and_phrases(kiwi, text)[0]   # (v0.1 호환용)


def bh(pvals: np.ndarray) -> np.ndarray:
    out = np.full(len(pvals), np.nan)
    ok = ~np.isnan(pvals)
    p = pvals[ok]
    if not len(p):
        return out
    order = np.argsort(p)
    ranked = p[order] * len(p) / np.arange(1, len(p) + 1)
    q = np.minimum.accumulate(ranked[::-1])[::-1]
    qq = np.empty(len(p))
    qq[order] = np.clip(q, 0, 1)
    out[ok] = qq
    return out


def trend_test(rel: np.ndarray):
    with np.errstate(invalid="ignore"):
        t = mk.hamed_rao_modification_test(rel)
        if np.isfinite(t.p):
            return t, "hamed_rao"
        return mk.original_test(rel), "original(HR 분산<0)"


def _trend_rows(df: dict, N: np.ndarray, min_total: int, min_years: int, min_recent: int) -> list:
    rows = []
    for w, v in df.items():
        if v.sum() < min_total or (v > 0).sum() < min_years:
            continue
        rel = v / N
        t, how = trend_test(rel)
        recent_docs = int(v[-3:].sum())
        early = rel[:max(3, len(rel) // 2)].mean()
        rows.append({"term": w, "total": int(v.sum()), "test": how, "tau": round(float(t.Tau), 3),
                     "p": float(t.p), "sen": float(t.slope),
                     "recent_share": round(float(rel[-3:].mean()), 5), "recent_docs": recent_docs,
                     "lift": round(float(rel[-3:].mean() / early), 2) if early else None,
                     "minor": recent_docs < min_recent,
                     "df": [int(x) for x in v]})
    return rows


def poisson_trend(c: np.ndarray, N: np.ndarray):
    """준포아송 회귀 log E[c_y] = log N_y + b0 + b1·(연도 중심화) → (b1, p). 과산포는 Pearson χ²/(n−2)로 보정.
    드문 구(연도별 0이 많음)에서 MK보다 검정력이 높다. 반복가중최소제곱(IRLS)."""
    import math
    n = len(c)
    t = np.arange(n, dtype=float) - (n - 1) / 2
    X = np.column_stack([np.ones(n), t])
    off = np.log(N)
    b = np.array([np.log(max(c.sum(), 0.5) / N.sum()), 0.0])
    for _ in range(50):
        eta = X @ b + off
        mu = np.exp(np.clip(eta, -30, 30))
        z = eta - off + (c - mu) / mu
        XtW = X.T * mu
        try:
            nb = np.linalg.solve(XtW @ X, XtW @ z)
        except np.linalg.LinAlgError:
            return 0.0, 1.0
        if np.max(np.abs(nb - b)) < 1e-8:
            b = nb
            break
        b = nb
    mu = np.exp(np.clip(X @ b + off, -30, 30))
    try:
        cov = np.linalg.inv((X.T * mu) @ X)
    except np.linalg.LinAlgError:
        return float(b[1]), 1.0
    phi = max(1.0, float(((c - mu) ** 2 / mu).sum()) / max(1, n - 2))
    se = math.sqrt(max(cov[1, 1] * phi, 1e-12))
    zst = b[1] / se
    return float(b[1]), float(math.erfc(abs(zst) / math.sqrt(2)))


def _bigram_rows(dfb: dict, N: np.ndarray) -> list:
    rows = []
    for w, v in dfb.items():
        if v.sum() < BI_MIN_TOTAL_DF or (v > 0).sum() < BI_MIN_YEARS_PRESENT:
            continue
        rel = v / N
        b1, p = poisson_trend(v, N)
        with np.errstate(invalid="ignore"):
            sen = mk.sens_slope(rel).slope
        recent_docs = int(v[-3:].sum())
        early = rel[:max(3, len(rel) // 2)].mean()
        slope = float(np.polyfit(np.arange(len(rel), dtype=float), rel, 1)[0])   # 비중의 연 변화(선형) — 드문 구는 Sen이 0이 되기 쉬워 정렬용
        rows.append({"term": w, "total": int(v.sum()), "test": "quasi_poisson", "rate": round(float(np.expm1(b1)), 4),
                     "p": p, "sen": float(sen), "slope": slope,
                     "recent_share": round(float(rel[-3:].mean()), 5), "recent_docs": recent_docs,
                     "lift": round(float(rel[-3:].mean() / early), 2) if early else None,
                     "minor": recent_docs < BI_MIN_RECENT_DOCS, "df": [int(x) for x in v], "_b1": b1})
    return rows


def _fdr_split(rows: list) -> tuple:
    q = bh(np.array([r["p"] for r in rows])) if rows else []
    for r, qq in zip(rows, q):
        r["q"] = float(qq)
        r["p"] = round(r["p"], 6)
    sig = [r for r in rows if np.isfinite(r["q"]) and r["q"] < Q]
    up = (lambda r: r["_b1"] > 0) if rows and "_b1" in rows[0] else (lambda r: r["sen"] > 0)   # 구: 회귀 기울기 부호
    key = "slope" if rows and "slope" in rows[0] else "sen"
    rising = sorted((r for r in sig if up(r)), key=lambda r: (r["minor"], -r[key]))
    falling = sorted((r for r in sig if not up(r) and (r.get("_b1", r["sen"]) < 0)), key=lambda r: (r["minor"], r[key]))
    return rising, falling


def analyze(kiwi: Kiwi, docs: dict, y1: int) -> dict:
    years = [y for y in sorted(docs) if y <= y1]
    N = np.array([len(docs[y]) for y in years], dtype=float)
    parsed = {y: [terms_and_phrases(kiwi, t, bd) for t, bd, _ in docs[y]] for y in years}
    codes = {y: [c for _, _, c in docs[y]] for y in years}
    doc_terms = {y: [u for u, _ in parsed[y]] for y in years}
    doc_phr = {y: [b for _, b in parsed[y]] for y in years}
    df = {}
    for i, y in enumerate(years):
        for ts in doc_terms[y]:
            for w in ts:
                df.setdefault(w, np.zeros(len(years)))[i] += 1

    rows = _trend_rows(df, N, MIN_TOTAL_DF, MIN_YEARS_PRESENT, MIN_RECENT_DOCS)
    rising, falling = _fdr_split(rows)

    # ── 바이그램: 띄어 쓴 구 + 붙여 쓴 형태를 한 구로 → 단어 탭 상승 용어와 같은 건 제외 → 준포아송 추세 → FDR ──
    uni_rising_all = {r["term"] for r in rising}
    seen_bi = Counter(w for y in years for bs in doc_phr[y] for w in bs)
    comp2bi = {w.replace(" ", ""): w for w in seen_bi}            # "하천수질" → "하천 수질"
    dfb, j11b = {}, Counter()
    for i, y in enumerate(years):
        for ts, bs, c in zip(doc_terms[y], doc_phr[y], codes[y]):
            present = set(bs) | {comp2bi[u] for u in ts if u in comp2bi}
            for w in present:
                dfb.setdefault(w, np.zeros(len(years)))[i] += 1
            if c == "J11":
                j11b.update(present)
    multi = len(set(c for y in years for c in codes[y])) > 1
    variants = 0
    for w in list(dfb):
        if w.replace(" ", "") in uni_rising_all:                  # 붙여 쓴 형태가 이미 단어 탭에 상승 용어로 있음
            del dfb[w]
            variants += 1
    brows = _bigram_rows(dfb, N)
    b_rising, b_falling = _fdr_split(brows)
    for r in brows:
        r.pop("_b1", None)
    uni_rising = {r["term"] for r in rising if not r["minor"]}
    n_all = float(N.sum())
    for r in b_rising + b_falling:
        a, b = r["term"].split(" ", 1)
        r["parts"] = [a, b]
        r["parts_rising"] = [x for x in (a, b) if x in uni_rising]
        r["novel"] = not r["parts_rising"]
        if multi:                                        # 수자원학회+토목학회: 수자원학회 논문에서 나온 비율 (토목 구조 분야 구와 구분)
            r["j11_share"] = round(j11b[r["term"]] / max(1, r["total"]), 2)
        da, db = df.get(a), df.get(b)                   # 결합도(PMI, log2): 두 단어가 우연보다 얼마나 자주 붙어 나오나
        r["pmi"] = (round(float(np.log2(r["total"] * n_all / (da.sum() * db.sum()))), 2)
                    if da is not None and db is not None and da.sum() and db.sum() else None)

    # ── 공출현 네트워크 + Louvain (상승 용어, 최근 NET_WINDOW년) ──
    top = [r["term"] for r in rising if not r["minor"]][:NET_TERMS]
    tops = set(top)
    co, dfr = Counter(), Counter()
    for y in years[-NET_WINDOW:]:
        for ts in doc_terms[y]:
            hit = sorted(ts & tops)
            dfr.update(hit)
            co.update(combinations(hit, 2))
    G = nx.Graph()
    G.add_nodes_from(top)
    for (a, b), c in co.items():
        if c >= NET_MIN_CO:
            G.add_edge(a, b, weight=c)
    comms = []
    if G.number_of_edges():
        parts = nx.community.louvain_communities(G, weight="weight", seed=42)
        for i, part in enumerate(sorted(parts, key=lambda s: -sum(dfr[t] for t in s))):
            if len(part) < 2:
                continue
            deg = G.subgraph(part).degree(weight="weight")
            comms.append({"id": i, "size": len(part),
                          "terms": [t for t, _ in sorted(deg, key=lambda x: -x[1])]})
    return {"years": years, "denominator": [int(n) for n in N], "tested": len(rows),
            "n_rising": len(rising), "n_falling": len(falling),
            "n_hr_fallback": sum(r["test"] != "hamed_rao" for r in rows),
            "rising": rising[:150], "falling": falling[:60],
            "bigram": {"test": "quasi_poisson", "tested": len(brows), "n_rising": len(b_rising),
                       "n_falling": len(b_falling), "same_as_word_excluded": variants, "min_total": BI_MIN_TOTAL_DF,
                       "head_ok": sorted(BI_HEAD_OK), "rising": b_rising[:150], "falling": b_falling[:60]},
            "network": {"window": years[-NET_WINDOW:], "nodes": [{"term": t, "df": dfr[t]} for t in top],
                        "edges": [[a, b, d["weight"]] for a, b, d in G.edges(data=True)],
                        "communities": comms}}


def main():
    if not RAW.exists():
        print(f"❌ 원천 폴더 없음: {RAW} — kci_collect.py 먼저 실행")
        return 1
    y1 = time.gmtime().tm_year - 1
    kiwi = Kiwi()
    out = {"method": "Kiwi 명사(복합어) 문서빈도 → 상대 문서빈도 → Hamed–Rao 수정 MK + Sen → BH FDR "
                     "→ 상승 용어 공출현 네트워크 → Louvain · 바이그램(띄어 쓴 명사구) 같은 검정",
           "source": "KCI(한국학술지인용색인) 데이터 활용 — 집계만 공개, 원천 데이터 미포함",
           "q": Q, "updated": int(time.time()), "scopes": {}}
    for name, codes in SCOPES.items():
        docs, excl = load_docs(codes)
        if not docs:
            continue
        res = analyze(kiwi, docs, y1)
        res["excluded"] = excl
        out["scopes"][name] = res
        print(f"✅ {name}: 논문 {sum(res['denominator']):,}편 · 검정 {res['tested']} → "
              f"상승 {res['n_rising']} · 하강 {res['n_falling']} · 커뮤니티 {len(res['network']['communities'])} "
              f"(제외: 영문 전용 {excl['english_only']}편, 초록 부족 {excl['low_abstract_years']})")
        for r in res["rising"][:12]:
            print(f"     ↑ {r['term']}: {r['sen'] * 1000:+.2f}‰/년 · 최근 {r['recent_docs']}편 · "
                  f"lift {r['lift']} · q={r['q']:.2g}{' (저빈도)' if r['minor'] else ''}")
        bg = res["bigram"]
        print(f"     ▸ 바이그램: 검정 {bg['tested']} → 상승 {bg['n_rising']} · 하강 {bg['n_falling']} "
              f"(단어 탭과 같은 것 제외 {bg['same_as_word_excluded']})")
        for r in bg["rising"][:15]:
            print(f"     ⇈ {r['term']}: {r['slope'] * 1000:+.2f}‰/년 · 연 {r['rate'] * 100:+.0f}% · 최근 {r['recent_docs']}편 · lift {r['lift']} · "
                  f"q={r['q']:.2g}{' · 구로만' if r['novel'] else ''}{' (저빈도)' if r['minor'] else ''}")
        for c in res["network"]["communities"][:6]:
            print(f"     ◇ 커뮤니티 {c['id']} ({c['size']}): {', '.join(c['terms'][:8])}")
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    if (RAW / "KWATER").exists():
        kw = kwater_summary(y1)
        OUT_KW.write_text(json.dumps(kw, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"✅ K-water 소속 논문 {kw['total']:,}편 · 게재지 {len(kw['journals'])}곳 이상")
    return 0


if __name__ == "__main__":
    sys.exit(main())
