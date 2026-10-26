#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
연구소별 5년 추이 — 해외(OpenAlex) 실측 (📄 논문 트렌드 화면, v3.12)

재료: data_seed/openalex_trends.json (openalex_lite가 6시간마다 기록)
  · institutes.<INST>.by_year   연구소 대표 키워드 1개(title_and_abstract.search)의 출판연도별 OpenAlex 논문 수
  · baseline.by_year            같은 연도의 OpenAlex 전체 논문 수 (해외 전체 기준선)
  · trend_years                 올해 포함 최근 5개 연도
올해는 진행 중이고 색인 지연이 있어 증감 계산은 끝난 해(작년까지)만 쓴다.
수집률 = 우리가 모은 논문(live + labels/openalex_extended, id 중복 제거) / 실측 — 공백 연도를 드러내는 용도.
"""
import time

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

GRAY = "#94A3B8"


def _short(name: str) -> str:
    """카드용 짧은 이름 (물인프라안전연구소 → 물인프라안전) — 라벨 판정 화면 INST_SHORT와 같은 규칙."""
    return name[:-3] if name.endswith("연구소") and len(name) > 3 else name


def _pct(a, b):
    return (b / a - 1) * 100 if a else None


def series(tr: dict):
    """→ (연도 목록, 끝난 연도 목록, {연구소: by_year}, 기준선 by_year). 실측 전이면 빈 값."""
    years = [str(y) for y in (tr or {}).get("trend_years") or []]
    insts = {c: v for c, v in ((tr or {}).get("institutes") or {}).items() if v.get("by_year")}
    base = ((tr or {}).get("baseline") or {}).get("by_year") or {}
    y_now = time.gmtime().tm_year
    full = [y for y in years if int(y) < y_now]
    return years, full, insts, base


def growth_rows(tr: dict, names: dict) -> list:
    """연구소별 끝난 해 첫해→마지막 해 증감(%)과 해외 전체 대비 차이(%p)."""
    years, full, insts, base = series(tr)
    if len(full) < 2:
        return []
    a, b = full[0], full[-1]
    bg = _pct(base.get(a, 0), base.get(b, 0))
    rows = []
    for c in sorted(insts):
        by = insts[c]["by_year"]
        g = _pct(by.get(a, 0), by.get(b, 0))
        rows.append({"code": c, "name": names.get(c) or insts[c].get("name") or c,
                     "keyword": insts[c].get("keyword", ""), "first": by.get(a, 0), "last": by.get(b, 0),
                     "growth": g, "vs_base": (g - bg) if g is not None and bg is not None else None,
                     "per10k": by.get(b, 0) / base[b] * 1e4 if base.get(b) else None})
    return rows


def render_overview(tr: dict, names: dict, colors: dict, layout: dict):
    years, full, insts, base = series(tr)
    st.markdown('<div class="sect">🌐 해외 연구 동향 × 연구소 — 최근 5년 (OpenAlex 실측)</div>',
                unsafe_allow_html=True)
    if not years or not insts:
        st.info("연구소별 5년 실측은 다음 정기 실측(6시간 주기 heartbeat의 openalex_lite) 뒤에 나타납니다 — "
                "연구소 대표 키워드의 연도별 OpenAlex 논문 수와 OpenAlex 전체 논문 수를 openalex_trends.json에 기록합니다.")
        return
    rows = growth_rows(tr, names)
    a, b = (full[0], full[-1]) if len(full) >= 2 else (years[0], years[-1])
    bg = _pct(base.get(a, 0), base.get(b, 0))

    def card(r):
        g, d = r["growth"], r["vs_base"]
        col = "#16A34A" if (d or 0) > 5 else "#DC2626" if (d or 0) < -5 else GRAY
        g_s = f"{g:+.0f}%" if g is not None else "-"
        d_s = f"해외 대비 {d:+.0f}%p" if d is not None else ""
        return (f'<div class="kpi" style="border-left-color:{colors.get(r["code"], GRAY)}">'
                f'<div class="k-val">{r["last"]:,}</div>'
                f'<div class="k-lab" title="{r["name"]}">{_short(r["name"])}</div>'
                f'<div class="k-sub"><b style="color:{col}">{g_s}</b> ({a[2:]}→{b[2:]})<br>{d_s}</div></div>')
    if rows:
        st.markdown('<div class="kpis k7">' + "".join(card(r) for r in rows) + '</div>', unsafe_allow_html=True)
        st.caption(f"카드 숫자 = {b}년 OpenAlex 논문 수(연구소 대표 키워드) · 증감은 끝난 해 {a}→{b} · "
                   f"OpenAlex 전체는 같은 기간 {bg:+.0f}%" if bg is not None else "")

    y_now = str(time.gmtime().tm_year)
    c1, c2 = st.columns(2)
    with c1:
        st.markdown('<div class="sect">연구소별 연도 추이 (논문 수)</div>', unsafe_allow_html=True)
        fig = go.Figure()
        for c in sorted(insts):
            by, nm, col = insts[c]["by_year"], names.get(c) or insts[c].get("name") or c, colors.get(c, GRAY)
            fig.add_trace(go.Scatter(x=full, y=[by.get(y, 0) for y in full], mode="lines+markers", name=nm,
                                     legendgroup=c, line=dict(color=col, width=2), marker=dict(size=7),
                                     hovertemplate=nm + " %{x}년 · %{y:,}편<extra></extra>"))
            if y_now in years:                              # 올해(진행 중) — 빈 동그라미
                fig.add_trace(go.Scatter(x=[y_now], y=[by.get(y_now, 0)], mode="markers", legendgroup=c,
                                         showlegend=False, marker=dict(size=8, color="#FFFFFF", line=dict(color=col, width=2)),
                                         hovertemplate=nm + " %{x}년(진행 중) · %{y:,}편<extra></extra>"))
        fig.update_layout(height=330, legend=dict(orientation="h", y=-0.22), yaxis_rangemode="tozero", **layout)
        fig.update_xaxes(type="category")
        fig.update_yaxes(gridcolor="#EEF2F7")
        st.plotly_chart(fig, width="stretch", key="inst5_counts")
    with c2:
        st.markdown(f'<div class="sect">상대 성장 지수 ({a}년 = 100, 해외 전체와 비교)</div>', unsafe_allow_html=True)
        fig = go.Figure()
        if base.get(a):
            fig.add_trace(go.Scatter(x=full, y=[base.get(y, 0) / base[a] * 100 for y in full], mode="lines",
                                     name="OpenAlex 전체", line=dict(color="#0F2744", width=3, dash="dash"),
                                     hovertemplate="OpenAlex 전체 %{x}년 · 지수 %{y:.0f}<extra></extra>"))
        for c in sorted(insts):
            by, nm, col = insts[c]["by_year"], names.get(c) or insts[c].get("name") or c, colors.get(c, GRAY)
            if not by.get(a):
                continue
            fig.add_trace(go.Scatter(x=full, y=[by.get(y, 0) / by[a] * 100 for y in full], mode="lines+markers",
                                     name=nm, line=dict(color=col, width=2), marker=dict(size=6),
                                     hovertemplate=nm + " %{x}년 · 지수 %{y:.0f}<extra></extra>"))
        fig.update_layout(height=330, legend=dict(orientation="h", y=-0.22), **layout)
        fig.update_xaxes(type="category")
        fig.update_yaxes(gridcolor="#EEF2F7")
        st.plotly_chart(fig, width="stretch", key="inst5_index")

    with st.expander("연도별 표 · 방법"):
        tbl = [{"연구소": r["name"], "대표 키워드": r["keyword"],
                **{y: insts[r["code"]]["by_year"].get(y, 0) for y in years},
                f"{a}→{b}": f"{r['growth']:+.0f}%" if r["growth"] is not None else "-",
                "해외 대비": f"{r['vs_base']:+.0f}%p" if r["vs_base"] is not None else "-",
                f"{b} 만 편당": round(r["per10k"], 2) if r["per10k"] is not None else None} for r in rows]
        if base:
            tbl.append({"연구소": "OpenAlex 전체", "대표 키워드": "(전 분야)", **{y: base.get(y, 0) for y in years},
                        f"{a}→{b}": f"{bg:+.0f}%" if bg is not None else "-", "해외 대비": "", f"{b} 만 편당": None})
        st.dataframe(pd.DataFrame(tbl), hide_index=True, width="stretch")
        st.caption((tr.get("trend_basis") or "") + ". 해외 대비 = 연구소 증감 − OpenAlex 전체 증감 (DB 자체가 커지는 효과를 뺀 상대 성장). "
                   "만 편당 = OpenAlex 전체 1만 편 가운데 그 키워드 논문 수. 연구소 화제를 키워드 하나로 대표하므로 "
                   "절대 규모보다 같은 연구소 안에서의 추이를 보는 지표.")


def coverage_rows(df: pd.DataFrame, by_year: dict, years: list) -> list:
    """연도별 수집(우리 파일) / 실측(OpenAlex) → 수집률."""
    got = df["year"].dropna().astype(int).astype(str).value_counts() if "year" in df else pd.Series(dtype=int)
    out = []
    for y in years:
        n, pop = int(got.get(y, 0)), int((by_year or {}).get(y, 0))
        out.append({"연도": y, "수집": n, "실측": pop, "수집률": f"{min(n / pop, 9.99) * 100:.0f}%" if pop else "-",
                    "_rate": n / pop if pop else None})
    return out


def render_coverage(df: pd.DataFrame, by_year: dict, years: list, color: str, layout: dict, key: str,
                    next_year=None):
    rows = coverage_rows(df, by_year, years)
    st.markdown('<div class="sect">연도별 수집 vs OpenAlex 실측 (최근 5년)</div>', unsafe_allow_html=True)
    fig = go.Figure(go.Bar(x=[r["연도"] for r in rows], y=[r["수집"] for r in rows], name="수집",
                           marker_color=color, hovertemplate="%{x}년 수집 %{y:,}편<extra></extra>"))
    if by_year:
        fig.add_trace(go.Scatter(x=[r["연도"] for r in rows], y=[r["실측"] for r in rows], name="OpenAlex 실측",
                                 mode="lines+markers", line=dict(color="#0F2744", width=2, dash="dot"),
                                 marker=dict(size=8, symbol="diamond"),
                                 hovertemplate="%{x}년 실측 %{y:,}편<extra></extra>"))
    fig.update_layout(height=300, legend=dict(orientation="h", y=-0.2), **layout)
    fig.update_xaxes(type="category")
    fig.update_yaxes(gridcolor="#EEF2F7")
    st.plotly_chart(fig, width="stretch", key=key)
    low = [r for r in rows if r["_rate"] is not None and r["_rate"] < 0.7 and int(r["연도"]) < time.gmtime().tm_year]
    nxt = f" (다음 차례 {next_year}년)" if next_year else ""
    if low:
        st.caption("⚠️ 수집이 실측보다 많이 적은 해: " + " · ".join(f"{r['연도']} {r['수집률']}" for r in low) +
                   f" — labels 파이프라인이 최근 5년을 하루에 1년씩 다시 받아 채우는 중{nxt}.")
    elif not by_year:
        st.caption("OpenAlex 실측(점선)은 다음 정기 실측 뒤에 나타납니다 · 수집 = 실시간 수집분 + labels 파이프라인의 지난 연도"
                   f" · 최근 5년은 하루에 1년씩 다시 받는 중{nxt}.")
    return rows
