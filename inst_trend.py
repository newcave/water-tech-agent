#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
연구소별 5년 추이 — 해외(OpenAlex) 실측 (📄 논문 트렌드 화면, v3.12)

재료: data_seed/openalex_trends.json (openalex_lite가 6시간마다 기록)
  · institutes.<INST>.by_year_all  연구소 키워드 전체(5~6개)를 OR로 묶은 출판연도별 OpenAlex 논문 수 (v3.13 — 카드·차트 기준)
  · institutes.<INST>.by_kw        키워드별 출판연도별 수 — 연구소 안에서 어떤 세부 주제가 오르는지
  · institutes.<INST>.by_year      대표 키워드 1개(= 실제 수집 검색식)의 연도별 수 — 수집률 비교 기준 (by_year_all 없으면 이것으로 대신)
  · baseline.by_year            같은 연도의 OpenAlex 전체 논문 수 (해외 전체 기준선)
  · trend_years                 올해 포함 최근 5개 연도
  · *_top10 (v3.15)             같은 검색에 '피인용 상위 10%'(OpenAlex citation_normalized_percentile — 같은 분야·같은 해 논문 안의
                                피인용 백분위) 조건을 더한 연도별 수 → 피인용 상위 10% 비중(세계 평균 약 10%)
올해는 진행 중이고 색인 지연이 있어 증감 계산은 끝난 해(작년까지)만 쓴다.
수집률 = 우리가 모은 논문(live + labels/openalex_extended, id 중복 제거) / 실측 — 공백 연도를 드러내는 용도.
"""
import time

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

GRAY = "#94A3B8"
KW_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#4a3aa7", "#008300", "#e34948"]


def _short(name: str) -> str:
    """카드용 짧은 이름 (물인프라안전연구소 → 물인프라안전) — 라벨 판정 화면 INST_SHORT와 같은 규칙."""
    return name[:-3] if name.endswith("연구소") and len(name) > 3 else name


def _pct(a, b):
    return (b / a - 1) * 100 if a else None


def trend_of(ent: dict):
    """연구소 한 곳의 연도별 수 → (by_year, 키워드 전체 여부). 합집합이 있으면 그것, 없으면 대표 키워드."""
    if ent.get("by_year_all"):
        return ent["by_year_all"], True
    return ent.get("by_year") or {}, False


def top10_of(ent: dict) -> dict:
    """trend_of와 같은 검색 기준의 '피인용 상위 10%' 연도별 수 (아직 실측 전이면 {})."""
    if ent.get("by_year_all"):
        return ent.get("by_year_all_top10") or {}
    return (ent.get("by_kw_top10") or {}).get(ent.get("keyword"), {})


def top_share(top: dict, tot: dict, years: list):
    """연도 합산 피인용 상위 10% 비중(%) — 분모가 없거나 상위 10% 값이 없으면 None."""
    n = sum((tot or {}).get(y, 0) for y in years)
    t = sum((top or {}).get(y, 0) for y in years)
    return t / n * 100 if n and top else None


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
        by, all_kw = trend_of(insts[c])
        g = _pct(by.get(a, 0), by.get(b, 0))
        kws = insts[c].get("keywords") or [insts[c].get("keyword", "")]
        rows.append({"code": c, "name": names.get(c) or insts[c].get("name") or c, "all": all_kw,
                     "keyword": (f"{len(kws)}개: " + " · ".join(kws)) if all_kw else insts[c].get("keyword", ""),
                     "first": by.get(a, 0), "last": by.get(b, 0),
                     "growth": g, "vs_base": (g - bg) if g is not None and bg is not None else None,
                     "per10k": by.get(b, 0) / base[b] * 1e4 if base.get(b) else None,
                     "top10": top_share(top10_of(insts[c]), by, full)})
    return rows


def render_overview(tr: dict, names: dict, colors: dict, layout: dict):
    years, full, insts, base = series(tr)
    st.markdown('<div class="sect">🌐 해외 연구 동향 × 연구소 관련 논문 — 최근 5년 (OpenAlex 실측)</div>',
                unsafe_allow_html=True)
    if not years or not insts:
        st.info("연구소별 5년 실측은 다음 정기 실측(6시간 주기 heartbeat의 openalex_lite) 뒤에 나타납니다 — "
                "연구소 키워드 전체의 연도별 OpenAlex 논문 수와 OpenAlex 전체 논문 수를 openalex_trends.json에 기록합니다.")
        return
    rows = growth_rows(tr, names)
    a, b = (full[0], full[-1]) if len(full) >= 2 else (years[0], years[-1])
    bg = _pct(base.get(a, 0), base.get(b, 0))

    def card(r):
        g, d = r["growth"], r["vs_base"]
        col = "#16A34A" if (d or 0) > 5 else "#DC2626" if (d or 0) < -5 else GRAY
        g_s = f"{g:+.0f}%" if g is not None else "-"
        d_s = f"해외 대비 {d:+.0f}%p" if d is not None else ""
        t_s = f'<br>피인용 상위10% <b>{r["top10"]:.1f}%</b>' if r.get("top10") is not None else ""
        return (f'<div class="kpi" style="border-left-color:{colors.get(r["code"], GRAY)}">'
                f'<div class="k-val">{r["last"]:,}</div>'
                f'<div class="k-lab" title="{r["name"]}">{_short(r["name"])}</div>'
                f'<div class="k-sub"><b style="color:{col}">{g_s}</b> ({a[2:]}→{b[2:]})<br>{d_s}{t_s}</div></div>')
    if rows:
        st.markdown('<div class="kpis k7">' + "".join(card(r) for r in rows) + '</div>', unsafe_allow_html=True)
        n_all = sum(r["all"] for r in rows)
        basis = ("연구소 키워드 전체(5~6개) 합집합" if n_all == len(rows) else
                 "연구소 대표 키워드 1개" if n_all == 0 else f"키워드 전체 {n_all}곳 · 대표 키워드 {len(rows) - n_all}곳")
        st.caption(f"카드 숫자 = {b}년 연구소 관련 논문 수 (OpenAlex, {basis} — 연구소가 쓴 논문이 아님) · 증감은 끝난 해 {a}→{b}"
                   + (f" · OpenAlex 전체는 같은 기간 {bg:+.0f}%" if bg is not None else ""))

    y_now = str(time.gmtime().tm_year)
    c1, c2 = st.columns(2)
    with c1:
        st.markdown('<div class="sect">연구소 관련 논문 연도 추이 (편수)</div>', unsafe_allow_html=True)
        fig = go.Figure()
        for c in sorted(insts):
            by, nm, col = trend_of(insts[c])[0], names.get(c) or insts[c].get("name") or c, colors.get(c, GRAY)
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
        st.markdown(f'<div class="sect">연구소 관련 논문 상대 성장 지수 ({a}년 = 100, 해외 전체와 비교)</div>', unsafe_allow_html=True)
        fig = go.Figure()
        if base.get(a):
            fig.add_trace(go.Scatter(x=full, y=[base.get(y, 0) / base[a] * 100 for y in full], mode="lines",
                                     name="OpenAlex 전체", line=dict(color="#0F2744", width=3, dash="dash"),
                                     hovertemplate="OpenAlex 전체 %{x}년 · 지수 %{y:.0f}<extra></extra>"))
        for c in sorted(insts):
            by, nm, col = trend_of(insts[c])[0], names.get(c) or insts[c].get("name") or c, colors.get(c, GRAY)
            if not by.get(a):
                continue
            fig.add_trace(go.Scatter(x=full, y=[by.get(y, 0) / by[a] * 100 for y in full], mode="lines+markers",
                                     name=nm, line=dict(color=col, width=2), marker=dict(size=6),
                                     hovertemplate=nm + " %{x}년 · 지수 %{y:.0f}<extra></extra>"))
        fig.update_layout(height=330, legend=dict(orientation="h", y=-0.22), **layout)
        fig.update_xaxes(type="category")
        fig.update_yaxes(gridcolor="#EEF2F7")
        st.plotly_chart(fig, width="stretch", key="inst5_index")

    render_citation(tr, rows, names, colors, layout, full, more=True)

    with st.expander("연도별 표 · 방법"):
        tbl = [{"연구소": r["name"], "키워드": r["keyword"],
                **{y: trend_of(insts[r["code"]])[0].get(y, 0) for y in years},
                f"{a}→{b}": f"{r['growth']:+.0f}%" if r["growth"] is not None else "-",
                "해외 대비": f"{r['vs_base']:+.0f}%p" if r["vs_base"] is not None else "-",
                f"{b} 만 편당": round(r["per10k"], 2) if r["per10k"] is not None else None,
                "피인용 상위10%": f"{r['top10']:.1f}%" if r.get("top10") is not None else "-"} for r in rows]
        if base:
            tbl.append({"연구소": "OpenAlex 전체", "키워드": "(전 분야)", **{y: base.get(y, 0) for y in years},
                        f"{a}→{b}": f"{bg:+.0f}%" if bg is not None else "-", "해외 대비": "", f"{b} 만 편당": None,
                        "피인용 상위10%": (lambda v: f"{v:.1f}%" if v is not None else "-")(
                            top_share((tr.get("baseline") or {}).get("by_year_top10"), base, full))})
        st.dataframe(pd.DataFrame(tbl), hide_index=True, width="stretch")
        st.caption((tr.get("trend_basis") or "") + ". 해외 대비 = 연구소 증감 − OpenAlex 전체 증감 (DB 자체가 커지는 효과를 뺀 상대 성장). "
                   "만 편당 = OpenAlex 전체 1만 편 가운데 그 연구소 관련 논문 수. 키워드 수와 폭이 연구소마다 달라 "
                   "연구소끼리 규모를 견주기보다 같은 연구소 안에서의 추이를 보는 지표.")


CIT_INK = "#0F2744"


def _alt_pos(ys: list) -> list:
    """점 이름이 겹치지 않게 — 세로로 이웃한 점끼리 이름을 위·아래로 번갈아 둠."""
    order = sorted(range(len(ys)), key=lambda i: ys[i])
    pos = [""] * len(ys)
    for n, i in enumerate(order):
        pos[i] = "bottom center" if n % 2 == 0 else "top center"
    return pos


def render_citation(tr: dict, rows: list, names: dict, colors: dict, layout: dict, full: list, more: bool = False):
    """피인용 질 — 연구소 관련 논문 중 피인용 상위 10% 비중 (끝난 해 합산) + 성장 × 피인용 위치."""
    rows = [r for r in rows if r.get("top10") is not None]
    if not rows or not full:
        st.caption("피인용 질(피인용 상위 10% 비중)은 다음 정기 실측(6시간 주기) 뒤에 나타납니다.")
        return
    base = (tr.get("baseline") or {})
    b_share = top_share(base.get("by_year_top10"), base.get("by_year"), full)
    kw = tr.get("kwater_citation") or {}
    k_share = top_share(kw.get("by_year_top10"), kw.get("by_year"), full)
    a, b = full[0], full[-1]
    st.markdown(f'<div class="sect">피인용 질 — 피인용 상위 10% 논문 비중 ({a}~{b} 합산, 분야·연도 보정)</div>',
                unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        rr = sorted(rows, key=lambda r: r["top10"])
        ys = [_short(r["name"]) for r in rr]
        xs = [r["top10"] for r in rr]
        cols = [colors.get(r["code"], GRAY) for r in rr]
        if k_share is not None:                        # K-water 소속 논문 — 참고 막대
            ys, xs, cols = ["K-water 소속 논문"] + ys, [k_share] + xs, ["#64748B"] + cols
        fig = go.Figure(go.Bar(x=xs, y=ys, orientation="h", marker=dict(color=cols, cornerradius=4),
                               text=[f"{v:.1f}%" for v in xs], textposition="outside", cliponaxis=False,
                               hovertemplate="%{y} · 피인용 상위 10% 비중 %{x:.1f}%<extra></extra>"))
        if b_share is not None:
            fig.add_vline(x=b_share, line=dict(color=CIT_INK, width=1.5, dash="dash"))
        fig.update_layout(height=330, showlegend=False, **layout)
        fig.update_xaxes(ticksuffix="%", gridcolor="#EEF2F7", rangemode="tozero",
                         range=[0, max(xs + [b_share or 0]) * 1.22])
        st.plotly_chart(fig, width="stretch", key="inst5_top10")
        st.caption("점선 = OpenAlex 전체 논문의 같은 비중"
                   + (f" ({b_share:.1f}%)" if b_share is not None else "")
                   + " · 정의상 세계 평균은 약 10% — 이보다 높으면 그 연구소 관련 논문이 평균보다 많이 인용됨")
    with c2:
        pts = [r for r in rows if r.get("vs_base") is not None]
        fig = go.Figure()
        if pts:
            mx = max(r["last"] for r in pts) or 1
            fig.add_trace(go.Scatter(
                x=[r["vs_base"] for r in pts], y=[r["top10"] for r in pts], mode="markers+text",
                text=[_short(r["name"]) for r in pts],
                textposition=_alt_pos([r["top10"] for r in pts]),
                textfont=dict(size=11, color=CIT_INK),
                marker=dict(size=[12 + 26 * (r["last"] / mx) ** 0.5 for r in pts],
                            color=[colors.get(r["code"], GRAY) for r in pts], opacity=0.85,
                            line=dict(color="#FFFFFF", width=1.5)),
                customdata=[[r["name"], r["growth"], r["last"]] for r in pts],
                hovertemplate="<b>%{customdata[0]}</b><br>해외 대비 성장 %{x:+.0f}%p (" + f"{a}→{b} " +
                              "%{customdata[1]:+.0f}%)<br>피인용 상위 10% %{y:.1f}%<br>" + f"{b}년 " +
                              "%{customdata[2]:,}편<extra></extra>", showlegend=False))
            fig.add_vline(x=0, line=dict(color="#CBD5E1", width=1))
            if b_share is not None:
                fig.add_hline(y=b_share, line=dict(color=CIT_INK, width=1.2, dash="dash"))
            fig.add_annotation(xref="paper", yref="paper", x=1, y=1, text="빨리 크고 많이 인용 ↗", showarrow=False,
                               xanchor="right", yanchor="top", font=dict(size=10, color="#94A3B8"))
        fig.update_layout(height=330, **layout)
        fig.update_xaxes(title_text=f"해외 전체 대비 성장 ({a}→{b}, %p)", ticksuffix="%p", gridcolor="#EEF2F7",
                         zeroline=False)
        fig.update_yaxes(title_text="피인용 상위 10% 비중", ticksuffix="%", gridcolor="#EEF2F7")
        st.plotly_chart(fig, width="stretch", key="inst5_cit_map")
        st.caption(f"오른쪽 위 = 해외 전체보다 빨리 크면서 많이 인용되는 분야 · 점 크기 = {b}년 편수 · 가로 실선 0 = 해외 전체와 같은 성장")
    st.caption("피인용 상위 10% = OpenAlex가 논문마다 계산한 '같은 분야·같은 출판연도 논문 중 피인용 백분위'가 상위 10%인 논문. "
               "분야와 연도를 보정한 값이라 오래된 논문이 유리하지 않음. 최근 해의 논문은 아직 인용이 쌓이는 중이라 "
               "값이 해마다 조금씩 바뀔 수 있음. 우리가 받아 둔 피인용 수(받은 날의 숫자)는 쓰지 않음."
               + (" 키워드 순위·연도별 추이는 사이드바 '🏅 피인용 질'." if more else ""))


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
                    next_year=None, by_year_all: dict = None, basis: str = None, basis_since: str = None):
    """연도별 수집 vs 실측. 수집 기준(basis)은 labels 파이프라인이 pipeline_state.json에 남김:
    all = 연구소 키워드 전체로 수집 (2026-10-27~) → 키워드 전체 실측과 비교 / 그 밖 = 대표 키워드 1개."""
    all_basis = basis == "all" and bool(by_year_all)
    ref, ref_lab = (by_year_all, "키워드 전체") if all_basis else (by_year, "대표 키워드")
    other, other_lab = (by_year, "대표 키워드") if all_basis else (by_year_all, "키워드 전체")
    rows = coverage_rows(df, ref, years)
    st.markdown('<div class="sect">연도별 수집 vs OpenAlex 실측 (최근 5년)</div>', unsafe_allow_html=True)
    fig = go.Figure(go.Bar(x=[r["연도"] for r in rows], y=[r["수집"] for r in rows], name="수집",
                           marker_color=color, hovertemplate="%{x}년 수집 %{y:,}편<extra></extra>"))
    if other and other != ref:
        fig.add_trace(go.Scatter(x=[r["연도"] for r in rows], y=[other.get(r["연도"], 0) for r in rows],
                                 name=f"실측 · {other_lab}", mode="lines+markers",
                                 line=dict(color=GRAY, width=2, dash="dash"), marker=dict(size=7),
                                 hovertemplate="%{x}년 " + other_lab + " %{y:,}편<extra></extra>"))
    if ref:
        fig.add_trace(go.Scatter(x=[r["연도"] for r in rows], y=[r["실측"] for r in rows], name=f"실측 · {ref_lab}(수집 기준)",
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
    elif not ref:
        st.caption("OpenAlex 실측(점선)은 다음 정기 실측 뒤에 나타납니다 · 수집 = 실시간 수집분 + labels 파이프라인의 지난 연도"
                   f" · 최근 5년은 하루에 1년씩 다시 받는 중{nxt}.")
    if basis == "all":
        st.caption(f"수집 기준: 연구소 키워드 전체{f' ({basis_since}부터)' if basis_since else ''} — 키워드마다 따로 검색해 id로 합침. "
                   f"최근 5년은 하루에 1년씩 키워드 전체로 다시 받는 중{nxt}, 새 논문은 초록 보강 → LLM 라벨링(회차당 상한 3,000편)."
                   + ("" if by_year_all else " 키워드 전체 실측은 다음 정기 실측 뒤에 나타남."))
    else:
        full = [y for y in years if int(y) < time.gmtime().tm_year]
        if by_year_all and by_year and full and by_year_all != by_year:
            y = full[-1]
            extra = by_year_all.get(y, 0) - by_year.get(y, 0)
            st.caption(f"수집은 대표 키워드 1개 기준 — 키워드 전체로 넓히면 {y}년 기준 연 약 {extra:,}편 더 "
                       f"({by_year.get(y, 0):,} → {by_year_all.get(y, 0):,}).")
    return rows


def render_keywords(ent: dict, years: list, base: dict, color: str, layout: dict, key: str, base_top10: dict = None):
    """연구소 키워드별 5년 추이 — 연구소 안에서 어떤 세부 주제가 오르는지 (by_kw)."""
    by_kw = ent.get("by_kw") or {}
    if len(by_kw) < 2:
        return
    y_now = str(time.gmtime().tm_year)
    full = [y for y in years if int(y) < int(y_now)]
    if len(full) < 2:
        return
    a, b = full[0], full[-1]
    st.markdown(f'<div class="sect">키워드별 5년 추이 — 어떤 세부 주제가 오르나 (OpenAlex 실측, {len(by_kw)}개)</div>',
                unsafe_allow_html=True)
    rows = sorted(({"kw": k, "first": v.get(a, 0), "last": v.get(b, 0), "now": v.get(y_now, 0),
                    "g": _pct(v.get(a, 0), v.get(b, 0))} for k, v in by_kw.items()),
                  key=lambda r: (r["g"] is None, -(r["g"] or 0), r["kw"]))
    c1, c2 = st.columns(2)
    with c1:
        fig = go.Figure()
        for i, k in enumerate(by_kw):
            v, col = by_kw[k], KW_COLORS[i % len(KW_COLORS)]
            fig.add_trace(go.Scatter(x=full, y=[v.get(y, 0) for y in full], mode="lines+markers", name=k,
                                     legendgroup=k, line=dict(color=col, width=2), marker=dict(size=6),
                                     hovertemplate=k + " %{x}년 · %{y:,}편<extra></extra>"))
            if y_now in years:
                fig.add_trace(go.Scatter(x=[y_now], y=[v.get(y_now, 0)], mode="markers", legendgroup=k, showlegend=False,
                                         marker=dict(size=7, color="#FFFFFF", line=dict(color=col, width=2)),
                                         hovertemplate=k + " %{x}년(진행 중) · %{y:,}편<extra></extra>"))
        fig.update_layout(height=340, legend=dict(orientation="h", y=-0.25), yaxis_rangemode="tozero", **layout)
        fig.update_xaxes(type="category")
        fig.update_yaxes(gridcolor="#EEF2F7")
        st.plotly_chart(fig, width="stretch", key=f"{key}_lines")
    with c2:
        all_by, _ = trend_of(ent)
        g_inst = _pct(all_by.get(a, 0), all_by.get(b, 0))
        g_base = _pct(base.get(a, 0), base.get(b, 0)) if base else None
        rr = [r for r in rows if r["g"] is not None][::-1]
        fig = go.Figure(go.Bar(x=[r["g"] for r in rr], y=[r["kw"] for r in rr], orientation="h",
                               marker=dict(color=[color if (g_base is None or r["g"] >= g_base) else GRAY for r in rr]),
                               customdata=[[r["first"], r["last"]] for r in rr],
                               hovertemplate="%{y}<br>" + f"{a}→{b} " + "%{x:+.0f}% (%{customdata[0]:,}→%{customdata[1]:,}편)<extra></extra>"))
        refs = [(v, lab, dash) for v, lab, dash in ((g_inst, "연구소 관련 전체", "solid"), (g_base, "OpenAlex 전체", "dash"))
                if v is not None]
        for val, lab, dash in refs:                    # 기준선 값은 글자 겹침을 피해 차트 위 한 줄로
            fig.add_vline(x=val, line=dict(color="#0F2744", width=1.5, dash=dash))
        st.caption(f"{a}→{b} 증감 · 기준선 " + " · ".join(
            f"{'실선' if d == 'solid' else '점선'} {lab} {v:+.0f}%" for v, lab, d in refs))
        fig.update_layout(height=320, yaxis=dict(automargin=True), **layout)
        fig.update_xaxes(gridcolor="#EEF2F7", zeroline=True, zerolinecolor="#CBD5E1")
        st.plotly_chart(fig, width="stretch", key=f"{key}_growth")
    st.caption("키워드마다 OpenAlex title_and_abstract 검색의 출판연도별 논문 수. 막대 색 = 해외 전체(OpenAlex)보다 빨리 느는 키워드, "
               "회색 = 해외 전체보다 느린 키워드. 키워드끼리 겹치는 논문이 있어 키워드 합은 연구소 관련 전체보다 큼. 키워드 고치기: data_seed/search_topics.json")

    render_kw_citation(ent, years, base, layout, key, base_top10)


def kw_citation_points(ent: dict, years: list):
    """연구소 키워드별 (성장, 피인용 상위 10% 비중, 편수) — 끝난 해 첫해→마지막 해, 피인용은 끝난 해 합산."""
    by_kw = ent.get("by_kw") or {}
    full = [y for y in years if int(y) < time.gmtime().tm_year]
    if len(full) < 2:
        return [], full
    a, b = full[0], full[-1]
    top_kw = ent.get("by_kw_top10") or {}
    pts = []
    for i, k in enumerate(by_kw):
        sh = top_share(top_kw.get(k), by_kw[k], full)
        g = _pct(by_kw[k].get(a, 0), by_kw[k].get(b, 0))
        if sh is not None and g is not None:
            pts.append({"kw": k, "g": g, "top10": sh, "last": by_kw[k].get(b, 0), "first": by_kw[k].get(a, 0),
                        "n": sum(by_kw[k].get(y, 0) for y in full), "col": KW_COLORS[i % len(KW_COLORS)]})
    return pts, full


def render_kw_citation(ent: dict, years: list, base: dict, layout: dict, key: str, base_top10: dict = None):
    """키워드별 성장 × 피인용 질 산점도 (v3.15) — 연구소 트랙과 🏅 피인용 질 화면이 함께 씀."""
    pts, full = kw_citation_points(ent, years)
    if not pts:
        return
    a, b = full[0], full[-1]
    g_base = _pct(base.get(a, 0), base.get(b, 0)) if base else None
    all_by, _ = trend_of(ent)
    b_share = top_share(base_top10, base, full) if base_top10 else None
    i_share = top_share(top10_of(ent), all_by, full)
    st.markdown(f'<div class="sect">키워드별 성장 × 피인용 질 — 어디가 크면서 영향력도 있나 ({a}→{b})</div>',
                unsafe_allow_html=True)
    mx = max(p["last"] for p in pts) or 1
    fig = go.Figure(go.Scatter(
        x=[p["g"] for p in pts], y=[p["top10"] for p in pts], mode="markers+text", text=[p["kw"] for p in pts],
        textposition=_alt_pos([p["top10"] for p in pts]), textfont=dict(size=11, color=CIT_INK),
        marker=dict(size=[12 + 26 * (p["last"] / mx) ** 0.5 for p in pts], color=[p["col"] for p in pts], opacity=0.85,
                    line=dict(color="#FFFFFF", width=1.5)),
        customdata=[[p["last"]] for p in pts],
        hovertemplate="<b>%{text}</b><br>" + f"{a}→{b} " + "%{x:+.0f}%<br>피인용 상위 10% %{y:.1f}%<br>"
                      + f"{b}년 " + "%{customdata[0]:,}편<extra></extra>"))
    refs = []
    if g_base is not None:
        fig.add_vline(x=g_base, line=dict(color="#0F2744", width=1.2, dash="dash"))
        refs.append(f"세로 점선 OpenAlex 전체 성장 {g_base:+.0f}%")
    if b_share is not None:
        fig.add_hline(y=b_share, line=dict(color="#0F2744", width=1.2, dash="dash"))
        refs.append(f"가로 점선 OpenAlex 전체 피인용 상위 10% 비중 {b_share:.1f}%")
    if i_share is not None:
        refs.append(f"이 연구소 관련 전체 {i_share:.1f}%")
    fig.update_layout(height=360, showlegend=False, **layout)
    fig.update_xaxes(title_text=f"{a}→{b} 증감", ticksuffix="%", gridcolor="#EEF2F7", zeroline=True, zerolinecolor="#CBD5E1")
    fig.update_yaxes(title_text="피인용 상위 10% 비중", ticksuffix="%", gridcolor="#EEF2F7")
    st.plotly_chart(fig, width="stretch", key=f"{key}_cit")
    st.caption("오른쪽 위 = 해외 전체보다 빨리 크면서 평균보다 많이 인용되는 키워드 · 점 크기 = " + f"{b}년 편수 · "
               + " · ".join(refs) + f" · 피인용 비중은 {a}~{b} 합산(분야·연도 보정)")
