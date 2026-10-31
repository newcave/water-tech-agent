#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tech_map_score — 세부 기술마다 해마다 '논문 점수(X)'와 '실용화 점수(Y)'를 매긴다 (v3.18). 계산만 하고 수집은 하지 않음.

재료: tech_map/units.json · papers.json(OpenAlex 2016~, tech_map.py) · journals.json(저널 2년 평균 피인용)
      · patents.json(WCS 특허 집계, tech_map_patents.py) · openalex_trends.json(papers.json이 아직 비어 있을 때 2022~ 임시)
점수는 모두 '그해 41개 세부 기술 사이의 백분위'(0~100, 50 = 가운데) — 서로 다른 단위를 같은 눈금에 올리려고.
  X 논문 = 규모 V(최근 3년 논문 수) · 성장 G(최근 5년 기울기) · 질 Q(피인용 상위 10% 비율, 3년) · 저널 J(게재 저널 2년 평균 피인용, 2년)
  Y 실용화 = 특허 규모 PV · 특허 성장 PG · 등록률 PR(2~4년 전 출원) · 기업 출원 비율 PC · 산업계 공저 비율 I(논문, 3년)
            특허 자료가 없으면 I만으로 임시 Y (화면에 '임시' 표시)
작은 표본 보정: 비율은 그해 전체 비율 쪽으로 당겨 줌 (경험적 베이즈, 논문 m=30 · 특허 m=10)
사분면(가운데 50 기준): 주력·코어 / 실용화 과제(논문↑ 특허↓) / 실용화 성숙(논문↓ 특허↑) / 검토 필요 — 이 가운데 성장 백분위 70 이상은 '위크시그널 후보'
"""
import json
import math
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / "data_seed" / "tech_map"
SEED = ROOT / "data_seed"
OUT = DIR / "scores.json"
WX = {"V": .25, "G": .25, "Q": .25, "J": .25}
WY = {"PV": .2, "PG": .2, "PR": .2, "PC": .2, "I": .2}
M_PAPER, M_PATENT = 30, 10
QUAD = {"core": "주력·코어", "gap": "실용화 과제", "applied": "실용화 성숙", "review": "검토 필요", "weak": "위크시그널 후보"}


def load(p: Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default if default is not None else {}


def pct_rank(vals: dict) -> dict:
    """{id: 값} → {id: 0~100 백분위} (같은 값은 평균 순위, None은 제외)."""
    xs = sorted((v, k) for k, v in vals.items() if v is not None and not (isinstance(v, float) and math.isnan(v)))
    n = len(xs)
    if n == 0:
        return {}
    if n == 1:
        return {xs[0][1]: 50.0}
    out, i = {}, 0
    while i < n:
        j = i
        while j + 1 < n and xs[j + 1][0] == xs[i][0]:
            j += 1
        r = (i + j) / 2
        for k in range(i, j + 1):
            out[xs[k][1]] = round(100 * r / (n - 1), 1)
        i = j + 1
    return out


def slope_log(series: list):
    """[(연도, 값)] → log(값+1)의 최소제곱 기울기 (연 단위). 점 3개 미만이면 None."""
    pts = [(x, math.log(v + 1)) for x, v in series if v is not None]
    if len(pts) < 3:
        return None
    mx = sum(x for x, _ in pts) / len(pts)
    my = sum(y for _, y in pts) / len(pts)
    den = sum((x - mx) ** 2 for x, _ in pts)
    return sum((x - mx) * (y - my) for x, y in pts) / den if den else None


def shrink(k, n, prior, m):
    if n is None or k is None:
        return None
    return (k + m * prior) / (n + m) if (n + m) else None


def main():
    units = load(DIR / "units.json").get("units", [])
    ids = [u["id"] for u in units]
    pap = load(DIR / "papers.json")
    jr = (load(DIR / "journals.json").get("journals") or {})
    pat = load(DIR / "patents.json")
    tr = load(SEED / "openalex_trends.json")
    this_year = time.gmtime().tm_year

    # ── 연도별 원자료 모으기 (papers.json 우선, 없으면 openalex_trends의 2022~ 키워드별 값) ──
    raw = {}
    src_used = set()
    for u in units:
        e = (pap.get("units") or {}).get(u["id"]) or {}
        by, t10 = e.get("by_year"), e.get("top10")
        if by:
            src_used.add("papers")
        else:
            ent = (tr.get("institutes") or {}).get(u["inst"]) or {}
            by = (ent.get("by_kw") or {}).get(u["en"])
            t10 = (ent.get("by_kw_top10") or {}).get(u["en"])
            if by:
                src_used.add("trends")
        by = {y: v for y, v in (by or {}).items() if int(y) < this_year}
        raw[u["id"]] = {"n": by, "top10": {y: v for y, v in (t10 or {}).items() if y in by},
                        "ind": e.get("industry") or {}, "kw": e.get("kwater") or {}, "venue": e.get("venue") or {},
                        "topics": e.get("topics") or []}
    yrs = sorted({int(y) for r in raw.values() for y in r["n"]})
    if not yrs:
        print("논문 자료 없음")
        return 0
    patents = (pat.get("units") or {}) if pat.get("units") else None
    cols = pat.get("cols") or ["n", "reg", "corp", "univ", "public", "kwater", "indiv"]

    def s(d, y0, y1):                                     # 연도 구간 합 (자료 없는 해는 건너뜀)
        v = [d.get(str(y)) for y in range(y0, y1 + 1) if d.get(str(y)) is not None]
        return sum(v) if v else None

    def pcol(uid, y0, y1, col):
        if not patents:
            return None
        by = (patents.get(uid) or {}).get("by_year") or {}
        i = cols.index(col)
        return sum((by.get(str(y)) or [0] * len(cols))[i] for y in range(y0, y1 + 1))

    def jour(uid, y0, y1):
        num = den = 0.0
        for y in range(y0, y1 + 1):
            for sid, c in raw[uid]["venue"].get(str(y), []):
                j = jr.get(sid) or {}
                if j.get("if2") is not None and j.get("type") in (None, "journal", "conference"):
                    num += c * j["if2"]
                    den += c
        return num / den if den >= 5 else None

    score_years = [t for t in yrs if t - 2 >= yrs[0]]
    out_units = {uid: {"x": {}, "y": {}, "q": {}, "c": {}, "r": {}} for uid in ids}
    for t in score_years:
        ty = str(t)
        n3 = {uid: s(raw[uid]["n"], t - 2, t) for uid in ids}
        t3 = {uid: s(raw[uid]["top10"], t - 2, t) for uid in ids}
        i3 = {uid: (s(raw[uid]["ind"], t - 2, t) if raw[uid]["ind"] else None) for uid in ids}
        tot_n = sum(v for v in n3.values() if v) or 1
        pq = sum(v for v in t3.values() if v) / tot_n
        pi = sum(v for v in i3.values() if v) / max(1, sum(n3[u] or 0 for u in ids if i3[u] is not None))
        # 물 분야 전체(41개 합) 대비 상대 성장 — 백분위에는 영향 없지만 화면 숫자(연 %)를 읽기 쉽게
        tot_series = [(y, sum(raw[u]["n"].get(str(y), 0) for u in ids)) for y in range(max(yrs[0], t - 4), t + 1)]
        g_all = slope_log(tot_series) or 0
        comp = {"V": n3,
                "G": {uid: (None if (g := slope_log([(y, raw[uid]["n"].get(str(y))) for y in range(max(yrs[0], t - 4), t + 1)])) is None
                            else g - g_all) for uid in ids},
                "Q": {uid: shrink(t3[uid], n3[uid], pq, M_PAPER) if t3[uid] is not None else None for uid in ids},
                "J": {uid: jour(uid, t - 1, t) for uid in ids},
                "I": {uid: shrink(i3[uid], n3[uid], pi, M_PAPER) if i3[uid] is not None else None for uid in ids}}
        if patents:
            pv = {uid: pcol(uid, t - 2, t, "n") for uid in ids}
            reg_n = {uid: pcol(uid, t - 4, t - 2, "n") for uid in ids}
            reg_k = {uid: pcol(uid, t - 4, t - 2, "reg") for uid in ids}
            corp = {uid: pcol(uid, t - 2, t, "corp") for uid in ids}
            p_reg = sum(reg_k.values()) / max(1, sum(reg_n.values()))
            p_corp = sum(corp.values()) / max(1, sum(pv.values()))
            comp["PV"] = pv
            comp["PG"] = {uid: slope_log([(y, ((patents.get(uid) or {}).get("by_year") or {}).get(str(y), [0])[0])
                                          for y in range(t - 4, t + 1)]) for uid in ids}
            comp["PR"] = {uid: shrink(reg_k[uid], reg_n[uid], p_reg, M_PATENT) for uid in ids}
            comp["PC"] = {uid: shrink(corp[uid], pv[uid], p_corp, M_PATENT) for uid in ids}
        pr = {k: pct_rank(v) for k, v in comp.items()}

        def wmean(uid, w):
            got = [(pr[k].get(uid), wt) for k, wt in w.items() if k in pr and pr[k]]
            got = [(v, wt) for v, wt in got if v is not None]
            return round(sum(v * wt for v, wt in got) / sum(wt for _, wt in got), 1) if got else None

        wy = WY if patents else {"I": 1.0}
        for uid in ids:
            o = out_units[uid]
            x, y = wmean(uid, WX), wmean(uid, wy)
            o["x"][ty], o["y"][ty] = x, y
            o["c"][ty] = {k: pr[k].get(uid) for k in pr if pr[k]}
            o["r"][ty] = {"n3": n3[uid], "g": None if comp["G"][uid] is None else round((math.exp(comp["G"][uid]) - 1) * 100, 1),
                          "q": None if comp["Q"][uid] is None else round(comp["Q"][uid] * 100, 1),
                          "j": None if comp["J"][uid] is None else round(comp["J"][uid], 2),
                          "i": None if comp["I"][uid] is None else round(comp["I"][uid] * 100, 1),
                          "kw": s(raw[uid]["kw"], t - 2, t) if raw[uid]["kw"] else None}
            if patents:
                o["r"][ty].update(pv=comp["PV"][uid], pr=None if comp["PR"][uid] is None else round(comp["PR"][uid] * 100, 1),
                                  pc=None if comp["PC"][uid] is None else round(comp["PC"][uid] * 100, 1),
                                  pg=None if comp["PG"][uid] is None else round((math.exp(comp["PG"][uid]) - 1) * 100, 1))
            if x is None or y is None:
                o["q"][ty] = None
            elif x >= 50 and y >= 50:
                o["q"][ty] = "core"
            elif x >= 50:
                o["q"][ty] = "gap"
            elif y >= 50:
                o["q"][ty] = "applied"
            else:
                growth = max(v for v in (pr["G"].get(uid), (pr.get("PG") or {}).get(uid)) if v is not None) \
                    if any(v is not None for v in (pr["G"].get(uid), (pr.get("PG") or {}).get(uid))) else 0
                o["q"][ty] = "weak" if growth >= 70 else "review"

    meta = {u["id"]: u for u in units}
    res_units = {}
    for uid in ids:
        u, o, r = meta[uid], out_units[uid], raw[uid]
        res_units[uid] = {"inst": u["inst"], "name": u["name"], "en": u["en"], **o,
                          "n": r["n"], "topics": r["topics"][:6],
                          "kw_total": sum(r["kw"].values()) if r["kw"] else None,
                          "patents_n": (patents.get(uid) or {}).get("n") if patents else None}
    out = {"_doc": "논문 × 특허 기술 지도 점수 — 세부 기술별·연도별 X(논문)·Y(실용화) 0~100 (그해 41개 사이 백분위). "
                   "c = 구성 지표 백분위, r = 원값(n3 최근3년 논문 수, g 물 분야 대비 연 성장 %, q 피인용 상위10% 비율 %, "
                   "j 게재 저널 2년 평균 피인용, i 산업계 공저 비율 %, kw K-water 논문 수, pv 특허 3년, pr 등록률 %, pc 기업 출원 %, pg 특허 연 성장 %), "
                   "q = 사분면 (core 주력·코어 · gap 실용화 과제 · applied 실용화 성숙 · review 검토 필요 · weak 위크시그널 후보)",
           "updated": int(time.time()), "years": [str(t) for t in score_years],
           "basis": {"x": sorted(k for k in ("V", "G", "Q", "J") if any(out_units[u]["c"].get(str(score_years[-1]), {}).get(k) is not None for u in ids)),
                     "y": "patents" if patents else ("industry" if any(raw[u]["ind"] for u in ids) else None),
                     "paper_source": sorted(src_used), "patents_total": pat.get("matched") if patents else None},
           "weights": {"x": WX, "y": WY if patents else {"I": 1.0}}, "quadrants": QUAD,
           "shrink": {"paper_m": M_PAPER, "patent_m": M_PATENT}, "units": res_units}
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    last = str(score_years[-1])
    qs = [res_units[u]["q"].get(last) for u in ids]
    print(f"✅ 점수 {score_years[0]}~{score_years[-1]} · 기준 X={out['basis']['x']} Y={out['basis']['y']} · "
          + " ".join(f"{QUAD[k]} {qs.count(k)}" for k in QUAD))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
