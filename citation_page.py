#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🏅 피인용 질 — 연구소 관련 논문의 '피인용 상위 10%' 비중 (v3.16, 사이드바 탭)

재료: data_seed/openalex_trends.json (agents/openalex_lite.py가 6시간마다 기록)
  · institutes.<INST>.by_year_all_top10 / by_kw_top10  같은 검색 + 피인용 상위 10% 조건의 연도별 수
  · baseline.by_year_top10                           OpenAlex 전체 (기준선)
  · kwater_citation                                  K-water 소속 논문 (참고)
  · institutes.<INST>.cit_updated                    피인용을 마지막으로 센 때 (연구소 4묶음을 실행마다 돌려 하루 한 바퀴)
피인용 상위 10% = OpenAlex citation_normalized_percentile — 같은 분야·같은 출판연도 논문 안의 피인용 백분위가 상위 10%.
분야·연도를 보정한 값이라 오래된 논문이 유리하지 않다. 비중은 끝난 해(올해 제외) 합산.
"""
import time

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import inst_trend as itr

INK, GRAY = "#0F2744", "#94A3B8"
SMALL_N = 300            # 끝난 해 합산 편수가 이보다 적으면 '편수 적음' — 비중이 크게 흔들릴 수 있음


def _fmt(v, suf="%"):
    return f"{v:.1f}{suf}" if v is not None else "-"


def render(tr: dict, names: dict, colors: dict, layout: dict):
    st.markdown('<div class="sect">🏅 피인용 질 — 연구소 관련 논문의 피인용 상위 10% 비중 (OpenAlex · 분야·연도 보정)</div>',
                unsafe_allow_html=True)
    years, full, insts, base = itr.series(tr)
    if not years or not insts or len(full) < 2:
        st.info("연구소별 실측이 아직 없습니다 — 다음 정기 실측(6시간 주기) 뒤에 나타납니다.")
        return
    a, b = full[0], full[-1]
    bl = tr.get("baseline") or {}
    b_share = itr.top_share(bl.get("by_year_top10"), base, full)
    kw = tr.get("kwater_citation") or {}
    k_share = itr.top_share(kw.get("by_year_top10"), kw.get("by_year"), full)
    st.caption(f"논문마다 OpenAlex가 '같은 분야·같은 출판연도 논문 중 피인용 상위 10%인가'를 판정해 둔 값을 연구소 키워드 검색 결과에서 셈 "
               f"({a}~{b} 합산, 올해 제외). 기준선 = OpenAlex 전체 논문의 같은 비중"
               + (f" {b_share:.1f}%" if b_share is not None else "")
               + " (이론상 10%지만 인용 백분위가 없는 논문까지 분모에 들어가 조금 낮음). 연구소가 쓴 논문이 아니라 연구소 관련 분야의 논문.")

    # ── 연구소 카드: 비중 + 기준선 대비 배수 ──
    rows = itr.growth_rows(tr, names)
    def card(r):
        v = r.get("top10")
        x = f"기준선의 {v / b_share:.1f}배" if v is not None and b_share else "다음 실측 차례에 채워짐"
        return (f'<div class="kpi" style="border-left-color:{colors.get(r["code"], GRAY)}">'
                f'<div class="k-val">{_fmt(v)}</div>'
                f'<div class="k-lab" title="{r["name"]}">{itr._short(r["name"])}</div>'
                f'<div class="k-sub">{x}</div></div>')
    st.markdown('<div class="kpis k7">' + "".join(card(r) for r in rows) + "</div>", unsafe_allow_html=True)
    extra = []
    if b_share is not None:
        extra.append(f"OpenAlex 전체 {b_share:.1f}%")
    if k_share is not None:
        extra.append(f"K-water 소속 논문 {k_share:.1f}% ({sum(kw['by_year_top10'].get(y, 0) for y in full):,}/"
                     f"{sum(kw['by_year'].get(y, 0) for y in full):,}편 — 편수가 적어 참고)")
    if extra:
        st.caption("참고: " + " · ".join(extra))

    # ── 막대 + 성장 × 피인용 위치 (논문 트렌드 화면과 같은 그림) ──
    itr.render_citation(tr, rows, names, colors, layout, full)

    # ── 연도별 비중 추이 ──
    st.markdown('<div class="sect">연도별 피인용 상위 10% 비중 — 연구소 관련 논문</div>', unsafe_allow_html=True)
    fig = go.Figure()
    for c in sorted(insts):
        top, tot = itr.top10_of(insts[c]), itr.trend_of(insts[c])[0]
        if not top:
            continue
        nm = names.get(c) or insts[c].get("name") or c
        fig.add_trace(go.Scatter(x=full, y=[itr.top_share(top, tot, [y]) for y in full], mode="lines+markers", name=nm,
                                 line=dict(color=colors.get(c, GRAY), width=2), marker=dict(size=7),
                                 hovertemplate=nm + " %{x}년 · %{y:.1f}%<extra></extra>"))
    if bl.get("by_year_top10"):
        fig.add_trace(go.Scatter(x=full, y=[itr.top_share(bl["by_year_top10"], base, [y]) for y in full], mode="lines",
                                 name="OpenAlex 전체", line=dict(color=INK, width=2.5, dash="dash"),
                                 hovertemplate="OpenAlex 전체 %{x}년 · %{y:.1f}%<extra></extra>"))
    if kw.get("by_year_top10"):
        fig.add_trace(go.Scatter(x=full, y=[itr.top_share(kw["by_year_top10"], kw["by_year"], [y]) for y in full],
                                 mode="lines+markers", name="K-water 소속 논문", line=dict(color="#64748B", width=1.5, dash="dot"),
                                 marker=dict(size=6, symbol="diamond"),
                                 hovertemplate="K-water 소속 %{x}년 · %{y:.1f}%<extra></extra>"))
    fig.update_layout(height=340, legend=dict(orientation="h", y=-0.22), **layout)
    fig.update_xaxes(type="category")
    fig.update_yaxes(ticksuffix="%", gridcolor="#EEF2F7", rangemode="tozero")
    st.plotly_chart(fig, width="stretch", key="cit_years")
    st.caption(f"{b}년처럼 최근 해의 논문은 아직 인용이 쌓이는 중이라 해마다 값이 조금씩 바뀔 수 있음 — 비교는 합산 값 위주로.")

    # ── 키워드 순위 (7개 연구소 전체) ──
    st.markdown(f'<div class="sect">키워드별 피인용 상위 10% 비중 — 7개 연구소 전체 ({a}~{b} 합산)</div>',
                unsafe_allow_html=True)
    tbl = []
    for c in sorted(insts):
        pts, _ = itr.kw_citation_points(insts[c], years)
        for p in pts:
            tbl.append({"연구소": itr._short(names.get(c) or insts[c].get("name") or c), "키워드": p["kw"],
                        "피인용 상위10%": round(p["top10"], 1),
                        "기준선 대비": round(p["top10"] / b_share, 2) if b_share else None,
                        f"{a}→{b} 증감": round(p["g"]), f"{b} 편수": p["last"], "합산 편수": p["n"],
                        "비고": "편수 적음" if p["n"] < SMALL_N else ""})
    if tbl:
        df = pd.DataFrame(tbl).sort_values("피인용 상위10%", ascending=False)
        mx = float(df["피인용 상위10%"].max() or 1)
        st.dataframe(df, hide_index=True, width="stretch", height=min(38 * len(df) + 40, 620), column_config={
            "피인용 상위10%": st.column_config.ProgressColumn("피인용 상위10%", format="%.1f%%", min_value=0, max_value=mx),
            "기준선 대비": st.column_config.NumberColumn("기준선 대비", format="%.2f배"),
            f"{a}→{b} 증감": st.column_config.NumberColumn(f"{a}→{b} 증감", format="%+d%%"),
            f"{b} 편수": st.column_config.NumberColumn(format="localized"),
            "합산 편수": st.column_config.NumberColumn(format="localized")})
        st.caption(f"편수 적음 = {a}~{b} 합산 {SMALL_N}편 미만 — 몇 편만으로도 비중이 크게 움직이니 참고만. "
                   "키워드끼리 겹치는 논문이 있음. 키워드 고치기: data_seed/search_topics.json")

    # ── 연구소 하나 골라 보기 ──
    codes = [c for c in sorted(insts) if (insts[c].get("by_kw_top10") or {})]
    if codes:
        pick = st.segmented_control("연구소 고르기", codes, format_func=lambda c: itr._short(names.get(c) or c),
                                    default=codes[0], key="cit_inst") or codes[0]
        itr.render_kw_citation(insts[pick], years, base, layout, key=f"cit_{pick}", base_top10=bl.get("by_year_top10"))

    with st.expander("방법 · 갱신"):
        upd = {c: (insts[c].get("cit_updated")) for c in sorted(insts)}
        st.markdown(
            "- **피인용 상위 10%**: OpenAlex `citation_normalized_percentile.is_in_top_10_percent` — 같은 분야(subfield)·같은 출판연도 "
            "논문 안에서 피인용 백분위가 상위 10%인 논문. 연구소 키워드 검색(제목·초록)에 이 조건을 더해 출판연도별로 셈\n"
            "- **비중** = 상위 10% 논문 수 ÷ 전체 논문 수 (끝난 해 합산). 기준선 = 같은 계산을 OpenAlex 전체에 한 값\n"
            "- **우리가 받아 둔 피인용 수는 쓰지 않음** — 받은 날의 숫자라 오래된 논문일수록 크게 나옴\n"
            "- **갱신**: OpenAlex 무키 사용량(하루 검색 약 100건) 안에서 돌리려고 6시간 실행마다 연구소 4묶음 중 하나씩 — 하루 한 바퀴")
        st.caption("연구소별 피인용 마지막 갱신: " + " · ".join(
            f"{itr._short(names.get(c) or c)} {time.strftime('%m-%d %H:%M', time.gmtime(v + 9 * 3600))}" if v else
            f"{itr._short(names.get(c) or c)} 아직" for c, v in upd.items()) + " (한국 시각)")
