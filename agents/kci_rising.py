#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kci_rising — 한국 저널(KCI) 상승 연구주제 탐지 v0.1

입력: {KCI_RAW_DIR}/raw/{코드}/{연도}.jsonl  (kci_collect.py가 비공개 저장소에 모은 원천)
출력: data_seed/kci_rising.json               (공개 — 용어·연도별 빈도와 검정 결과 같은 집계만)

방법 (논문 설계 그대로):
  1. 용어 추출: 국문 제목+초록(없으면 영문)을 Kiwi 형태소 분석 → 띄어쓰기 없이 붙은 명사열을
     복합어로 묶음(예: 딥+러닝 → 딥러닝, 유출+량 → 유출량). 영문 약어(SL)도 포함. 논문당 집합(문서빈도).
  2. 상대 문서빈도 rel_y = DF_y / N_y  (N_y = 그 해 논문 수, 진행 중인 올해 제외)
  3. Hamed–Rao 수정 Mann–Kendall + Sen 기울기 → Benjamini–Hochberg FDR (q<0.05)
  4. 공출현 네트워크: 상승 용어끼리 최근 5년 논문에서 함께 나온 횟수 → Louvain 커뮤니티

범위: 'J11'(한국수자원학회논문집 단독)과 'J11+J12'(대한토목학회논문집 포함) 두 가지로 계산.
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

ROOT = Path(__file__).resolve().parents[1]
RAW = Path(os.environ.get("KCI_RAW_DIR", "private")) / "raw"
OUT = ROOT / "data_seed" / "kci_rising.json"
Q = 0.05
MIN_TOTAL_DF = 20                  # 검정 대상 최소 누적 문서빈도
MIN_YEARS_PRESENT = 5              # 검정 대상 최소 등장 연도 수
MIN_RECENT_DOCS = 8                # 최근 3년 문서빈도가 이보다 적으면 '저빈도' 표시
NET_TERMS = 80                     # 공출현 네트워크에 넣을 상승 용어 수
NET_WINDOW = 5                     # 공출현을 셀 최근 연도 수
NET_MIN_CO = 3                     # 간선 최소 공출현 수
SCOPES = {"J11": ["J11"], "J11+J12": ["J11", "J12"]}
NOUN = {"NNG", "NNP", "SL"}
STOP = set("""
연구 분석 결과 방법 본연구 경우 사용 적용 이용 제시 검토 평가 비교 고려 대상 기존 모형 모델 방안 특성 영향
정도 이상 이하 각각 조건 변화 과정 차이 효과 관계 경향 가능성 필요 수행 개발 제안 확인 도출 산정 파악 활용
자료 데이터 기반 기법 시스템 요소 지역 대한 따른 통한 위한 이후 이전 전체 부분 기간 시간 연도 수준 범위 목적
문제 기준 측면 결과값 본논문 논문 사례 실험 연구결과 분석결과 study analysis results method model data using
based paper proposed approach case korea korean
""".split())
HANGUL = re.compile("[가-힣]")


def load_docs(codes: list) -> dict:
    """{연도: [문서텍스트, ...]}"""
    docs = {}
    for c in codes:
        for p in sorted((RAW / c).glob("*.jsonl")):
            for line in p.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                r = json.loads(line)
                y = int(r.get("year") or p.stem)
                t = " ".join(x for x in (r.get("title_ko") or r.get("title_en"),
                                         r.get("abstract_ko") or r.get("abstract_en")) if x)
                if t:
                    docs.setdefault(y, []).append(t)
    return docs


def terms_of(kiwi: Kiwi, text: str) -> set:
    """붙어 있는 명사열 → 복합어. 한 글자 한글·불용어·숫자 제외."""
    out, run, last_end = set(), [], -1
    for tok in kiwi.tokenize(text) + [None]:
        if tok is not None and tok.tag in NOUN and (not run or tok.start == last_end):
            run.append(tok.form)
            last_end = tok.start + tok.len
            continue
        if run:
            w = "".join(run)
            w = w.lower() if not HANGUL.search(w) else w
            if len(w) >= 2 and w not in STOP and not w.isdigit():
                out.add(w)
            run = []
        if tok is not None and tok.tag in NOUN:
            run, last_end = [tok.form], tok.start + tok.len
    return out


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


def analyze(kiwi: Kiwi, docs: dict, y1: int) -> dict:
    years = [y for y in sorted(docs) if y <= y1]
    N = np.array([len(docs[y]) for y in years], dtype=float)
    doc_terms = {y: [terms_of(kiwi, t) for t in docs[y]] for y in years}
    df = {}
    for i, y in enumerate(years):
        for ts in doc_terms[y]:
            for w in ts:
                df.setdefault(w, np.zeros(len(years)))[i] += 1

    rows = []
    for w, v in df.items():
        if v.sum() < MIN_TOTAL_DF or (v > 0).sum() < MIN_YEARS_PRESENT:
            continue
        rel = v / N
        t, how = trend_test(rel)
        recent_docs = int(v[-3:].sum())
        early = rel[:max(3, len(rel) // 2)].mean()
        rows.append({"term": w, "total": int(v.sum()), "test": how, "tau": round(float(t.Tau), 3),
                     "p": float(t.p), "sen": float(t.slope),
                     "recent_share": round(float(rel[-3:].mean()), 5), "recent_docs": recent_docs,
                     "lift": round(float(rel[-3:].mean() / early), 2) if early else None,
                     "minor": recent_docs < MIN_RECENT_DOCS,
                     "df": [int(x) for x in v]})
    q = bh(np.array([r["p"] for r in rows])) if rows else []
    for r, qq in zip(rows, q):
        r["q"] = float(qq)
        r["p"] = round(r["p"], 6)
    sig = [r for r in rows if np.isfinite(r["q"]) and r["q"] < Q]
    rising = sorted((r for r in sig if r["sen"] > 0), key=lambda r: (r["minor"], -r["sen"]))
    falling = sorted((r for r in sig if r["sen"] < 0), key=lambda r: (r["minor"], r["sen"]))

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
                     "→ 상승 용어 공출현 네트워크 → Louvain",
           "source": "KCI(한국학술지인용색인) 데이터 활용 — 집계만 공개, 원천 데이터 미포함",
           "q": Q, "updated": int(time.time()), "scopes": {}}
    for name, codes in SCOPES.items():
        docs = load_docs(codes)
        if not docs:
            continue
        res = analyze(kiwi, docs, y1)
        out["scopes"][name] = res
        print(f"✅ {name}: 논문 {sum(res['denominator']):,}편 · 검정 {res['tested']} → "
              f"상승 {res['n_rising']} · 하강 {res['n_falling']} · 커뮤니티 {len(res['network']['communities'])}")
        for r in res["rising"][:12]:
            print(f"     ↑ {r['term']}: {r['sen'] * 1000:+.2f}‰/년 · 최근 {r['recent_docs']}편 · "
                  f"lift {r['lift']} · q={r['q']:.2g}{' (저빈도)' if r['minor'] else ''}")
        for c in res["network"]["communities"][:6]:
            print(f"     ◇ 커뮤니티 {c['id']} ({c['size']}): {', '.join(c['terms'][:8])}")
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
