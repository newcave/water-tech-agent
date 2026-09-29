#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
trend_rising — 상승 연구주제 탐지 v0.1 (수자원 국제 저널 10종, OpenAlex 집계 API만 사용)

방법 (논문 설계: 상대 문서빈도 → Hamed–Rao Mann–Kendall + BH 보정 → [공출현 네트워크 → Louvain: 다음 단계])
  1. 분모 N_y  : J01–J10 × 연도 논문 수  (primary_location.source.id + type:article|review)
  2. 분자 DF_y : 같은 필터 + 연도별 group_by=topics.id / keywords.id → 주제·키워드별 논문 수
  3. 상대 문서빈도 rel_y = DF_y / N_y  (2000 ~ 작년, 진행 중인 올해 제외)
  4. 주제별 Hamed–Rao 수정 Mann–Kendall (자기상관 보정) + Sen 기울기
  5. Benjamini–Hochberg FDR (q=0.05) → 유의·증가 = '상승', 유의·감소 = '하강'

범위·한계 (정직 원칙):
  · 한국 저널(J11·J12)은 제외 — KCI에는 주제·키워드 분류가 없어 분자를 같은 기준으로 셀 수 없음
  · 주제·키워드는 OpenAlex가 기계적으로 소급 부여한 분류 → 분류기 특성이 추세에 섞일 수 있음
  · 원문(제목·초록) 기반 바이그램·공출현 분석은 다음 단계

출력: data_seed/trend_rising.json (집계·검정 결과만)
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pymannkendall as mk
import requests

from water_journals import load_registry, resolve_sources, source_filter

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data_seed" / "trend_rising.json"
API = "https://api.openalex.org/works"
MAILTO = "newcave.kwater@gmail.com"
PAUSE = 1.0                                   # 요청 간격 (초) — 429 방지
MAX_GROUP_PAGES = 20                          # 연도·분류당 group_by 최대 페이지 (200개/페이지)
MIN_TOTAL_DF = 60                             # 검정 대상 최소 누적 논문 수
MIN_YEARS_PRESENT = 6                         # 검정 대상 최소 등장 연도 수
Q = 0.05                                      # BH FDR 수준
MIN_RECENT_SHARE = 0.001                      # 순위 상단 조건: 최근 3년 비중 ≥ 1‰
KINDS = {"topics": "topics.id", "keywords": "keywords.id"}


def get(params: dict) -> dict:
    """OpenAlex GET — 429·5xx면 Retry-After(없으면 지수) 만큼 쉬고 최대 5회 재시도."""
    wait = 5.0
    for attempt in range(5):
        r = requests.get(API, params={**params, "mailto": MAILTO}, timeout=60)
        time.sleep(PAUSE)
        if r.status_code == 200:
            return r.json()
        if r.status_code == 429 or r.status_code >= 500:
            ra = r.headers.get("Retry-After")
            pause = float(ra) if ra and ra.replace(".", "", 1).isdigit() else wait
            print(f"   ⏳ HTTP {r.status_code} — {pause:.0f}초 대기 후 재시도 ({attempt + 1}/5)")
            time.sleep(min(pause, 120))
            wait *= 2
            continue
        r.raise_for_status()
    raise RuntimeError(f"OpenAlex 재시도 초과: {params.get('filter', '')[:80]}")


def group_by(filt: str, key: str):
    """group_by 전 페이지 → ({id: (count, display_name)}, 잘림 여부)."""
    out, cursor = {}, "*"
    for _ in range(MAX_GROUP_PAGES):
        j = get({"filter": filt, "group_by": key, "per-page": 200, "cursor": cursor})
        for g in j.get("group_by", []):
            if g.get("key") and g["key"] != "unknown":
                out[g["key"].rsplit("/", 1)[-1]] = (int(g["count"]), g.get("key_display_name"))
        cursor = (j.get("meta") or {}).get("next_cursor")
        if not cursor:
            return out, False
    return out, True


def bh(pvals: np.ndarray) -> np.ndarray:
    """Benjamini–Hochberg q값. NaN은 제외하고 계산 (NaN 하나가 전체를 NaN으로 만들지 않게)."""
    out = np.full(len(pvals), np.nan)
    ok = ~np.isnan(pvals)
    p = pvals[ok]
    n = len(p)
    if not n:
        return out
    order = np.argsort(p)
    ranked = p[order] * n / np.arange(1, n + 1)
    q = np.minimum.accumulate(ranked[::-1])[::-1]
    qq = np.empty(n)
    qq[order] = np.clip(q, 0, 1)
    out[ok] = qq
    return out


def trend_test(rel: np.ndarray):
    """Hamed–Rao 수정 MK. 희소 시계열에서 보정 분산이 음수(p=NaN)면 원 MK로 대체하고 표시."""
    t = mk.hamed_rao_modification_test(rel)
    if np.isfinite(t.p):
        return t, "hamed_rao"
    return mk.original_test(rel), "original(HR 분산<0)"


def main():
    reg = load_registry()
    y0, y1 = int(reg.get("archive_from_year", 2000)), time.gmtime().tm_year - 1
    years = list(range(y0, y1 + 1))

    # ── 1. 국제 저널 10종 source ID ──
    sids, used = [], []
    for j in reg.get("journals", []):
        if j.get("kci"):
            continue
        srcs = resolve_sources(j.get("issns", []), MAILTO)
        time.sleep(PAUSE)
        if srcs:
            sids += [s["id"] for s in srcs]
            used.append(j["code"])
    if not sids:
        print("❌ 저널 해석 실패")
        return 1
    base = f"{source_filter(sids)},type:article|review"
    print(f"▶ 대상 {len(used)}개 저널 ({', '.join(used)}), {y0}–{y1}")

    # ── 2. 분모 ──
    den = {int(g["key"]): int(g["count"])
           for g in get({"filter": f"{base},publication_year:{y0}-{y1}",
                         "group_by": "publication_year"}).get("group_by", [])}
    N = np.array([den.get(y, 0) for y in years], dtype=float)
    print("   분모:", {y: int(n) for y, n in zip(years, N)})

    result = {"method": "상대 문서빈도 → Hamed–Rao 수정 Mann–Kendall + Sen 기울기 → BH FDR",
              "source": "OpenAlex (topics·keywords group_by 집계)",
              "journals": used, "years": years, "denominator": [int(n) for n in N],
              "q": Q, "updated": int(time.time()), "kinds": {}}

    for kind, key in KINDS.items():
        # ── 3. 분자: 연도별 주제·키워드 문서빈도 ──
        # 목록이 잘린 연도는 빠진 항목을 0으로 보되, 그 해 최소 건수(floor)를 기록해 편향 여부를 드러냄
        df, names, floors = {}, {}, {}
        for i, y in enumerate(years):
            g, cut = group_by(f"{base},publication_year:{y}", key)
            for tid, (c, nm) in g.items():
                df.setdefault(tid, np.zeros(len(years)))[i] = c
                names[tid] = nm
            if cut and g:
                floors[y] = min(c for c, _ in g.values())
            print(f"   {kind} {y}: {len(g)}개 항목" + (f" (잘림, 최소 {floors[y]}건)" if y in floors else ""))

        # ── 4. 검정 ──
        rows = []
        for tid, v in df.items():
            if v.sum() < MIN_TOTAL_DF or (v > 0).sum() < MIN_YEARS_PRESENT:
                continue
            rel = np.divide(v, N, out=np.zeros_like(v), where=N > 0)
            with np.errstate(invalid="ignore"):
                t, how = trend_test(rel)
            recent, early = rel[-3:].mean(), rel[:max(3, len(rel) // 2)].mean()
            rows.append({"id": tid, "name": names.get(tid), "total": int(v.sum()), "test": how,
                         "tau": round(float(t.Tau), 3), "p": float(t.p),
                         "sen": float(t.slope),
                         "sen_rel": float(t.slope / rel.mean()) if rel.mean() else 0.0,
                         "recent_share": round(float(recent), 5),
                         "lift": round(float(recent / early), 2) if early else None,
                         "rel": [round(float(x), 5) for x in rel]})
        if not rows:
            continue
        qv = bh(np.array([r["p"] for r in rows]))
        for r, q in zip(rows, qv):
            r["q"] = float(q)
            r["p"] = round(r["p"], 6)
        # 순위: 상대 기울기는 저빈도 주제(분류기 오배정 포함)를 과대평가 → 절대 기울기(‰/년) 우선,
        #       최근 3년 비중이 MIN_RECENT_SHARE 미만인 주제는 '저빈도'로 표시해 뒤로 보냄
        sig = [r for r in rows if np.isfinite(r["q"]) and r["q"] < Q]
        for r in sig:
            r["minor"] = r["recent_share"] < MIN_RECENT_SHARE
        rising = sorted((r for r in sig if r["sen"] > 0), key=lambda r: (r["minor"], -r["sen"]))
        falling = sorted((r for r in sig if r["sen"] < 0), key=lambda r: (r["minor"], r["sen"]))
        result["kinds"][kind] = {"tested": len(rows), "n_rising": len(rising),
                                 "truncated_floor": floors,
                                 "n_falling": len(falling),
                                 "n_hr_fallback": sum(r["test"] != "hamed_rao" for r in rows),
                                 "rising": rising[:150], "falling": falling[:60]}
        print(f"✅ {kind}: 검정 {len(rows)}개 → 상승 {len(rising)} · 하강 {len(falling)} (q<{Q})")
        for r in rising[:10]:
            print(f"     ↑ {r['name']}: {r['sen'] * 1000:+.3f}‰/년 (상대 {r['sen_rel']:+.3f}) · "
                  f"최근 {r['recent_share'] * 1000:.1f}‰ · lift {r['lift']} · q={r['q']:.2g}")

    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
