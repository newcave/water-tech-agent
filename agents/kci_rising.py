#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kci_rising — 한국 저널(KCI) 상승 연구주제 탐지 v0.1

입력: {KCI_RAW_DIR}/raw/{코드}/{연도}.jsonl  (kci_collect.py가 비공개 저장소에 모은 원천)
출력: data_seed/kci_rising.json               (공개 — 용어·연도별 빈도와 검정 결과 같은 집계만)
      data_seed/kci_kwater.json               (공개 — K-water 소속 논문 연도별 수·학회지 내 비중·게재지·협업기관 집계)

방법 (논문 설계 그대로):
  1. 용어 추출: 국문 제목+초록(없으면 영문)을 Kiwi 형태소 분석 → 띄어쓰기 없이 붙은 명사열을
     복합어로 묶음(예: 딥+러닝 → 딥러닝, 유출+량 → 유출량). 영문 약어(SL)도 포함. 논문당 집합(문서빈도).
  2. 상대 문서빈도 rel_y = DF_y / N_y  (N_y = 그 해 논문 수, 진행 중인 올해 제외)
  3. Hamed–Rao 수정 Mann–Kendall + Sen 기울기 → Benjamini–Hochberg FDR (q<0.05)
  4. 공출현 네트워크: 상승 용어끼리 최근 5년 논문에서 함께 나온 횟수 → Louvain 커뮤니티

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
                docs.setdefault(y, []).append(" ".join(x for x in (r.get("title_ko"), r.get("abstract_ko")) if x))
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
        y = int(r.get("year") or 0)
        by_year[y] += 1
        journals[r.get("journal")] += 1
        for a in r.get("authors", []):
            aff = a.get("affil") or ""
            if not aff:
                continue
            if re.search(r"한국수자원공사|케이워터|k-?water|korea water resources? corp", aff, re.I):
                units[aff] += 1
            else:
                partners[aff.split(",")[-1].strip()] += 1          # 기관 단위(마지막 쉼표 뒤)
    share = {}
    for code in ("J11", "J12"):
        tot, kw = Counter(), Counter()
        for r in read_raw(code):
            y = int(r.get("year") or 0)
            tot[y] += 1
            kw[y] += bool(r.get("kwater"))
        share[code] = {str(y): {"n": tot[y], "kwater": kw[y]} for y in sorted(tot) if y <= y1}
    return {"source": "KCI(한국학술지인용색인) 데이터 활용 — 집계만 공개, 원천 데이터·개인 이름 미포함",
            "updated": int(time.time()),
            "by_year": {str(y): by_year[y] for y in sorted(by_year)},
            "total": sum(by_year.values()),
            "journals": journals.most_common(25),
            "kwater_units": units.most_common(20),
            "partners": partners.most_common(25),
            "journal_share": share}


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
            if not HANGUL.search(w):                  # 영문: 약어(대문자 포함)만, 일반 영어 단어 제외
                w = w if ACRONYM.match(w) else ""
            if len(w) >= 2 and w not in STOP and w.lower() not in STOP and not w.isdigit():
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
