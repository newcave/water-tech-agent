#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🗄️ 지식자산 현황 — 통합 물 지식 자산 정보검색 시스템(WCS)의 연구보고서·논문·특허 구성 (v3.14)

숫자: data_seed/wcs_assets.json (as_of 기준일과 건수만 고치면 화면이 따라감)
그림: 전체 구성 도넛(3조각) + 논문을 뺀 K-water 자료(보고서·특허) 도넛 + 건수·비중 카드·표
"""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# 조각 색 — 순서 고정(보고서·논문·특허). 색만으로 구분하지 않게 조각 옆에 이름·건수·%를 직접 적는다.
COLORS = {"reports": "#17549A", "papers": "#1FA8C9", "patents": "#D97706"}
INK, MUTED = "#0F2744", "#64748B"


def _pct(n, total):
    return n / total * 100 if total else 0.0


def _fmt_pct(p):
    return f"{p:.1f}%" if p >= 1 else f"{p:.2f}%"


INSIDE_INK = {"reports": "#FFFFFF", "papers": INK, "patents": "#FFFFFF"}   # 조각 안 글씨 — 바탕색 대비


def _donut(items, total, center_top, center_bottom, key, layout, height=400):
    big = [_pct(i["count"], total) >= 25 for i in items]            # 큰 조각은 안쪽, 작은 조각은 바깥 + 안내선
    fig = go.Figure(go.Pie(
        labels=[i["label"] for i in items], values=[i["count"] for i in items],
        hole=0.58, sort=False, direction="clockwise", rotation=90,
        marker=dict(colors=[COLORS.get(i["key"], "#94A3B8") for i in items], line=dict(color="#FFFFFF", width=2)),
        text=[f"<b>{i['label']}</b><br>{i['count']:,}{i['unit']} · {_fmt_pct(_pct(i['count'], total))}" for i in items],
        textinfo="text", textposition=["inside" if b else "outside" for b in big],
        insidetextorientation="horizontal",
        insidetextfont=dict(size=13, color=[INSIDE_INK.get(i["key"], INK) for i in items]),
        outsidetextfont=dict(size=13, color=INK),
        customdata=[[i["unit"], _fmt_pct(_pct(i["count"], total))] for i in items],
        hovertemplate="<b>%{label}</b><br>%{value:,}%{customdata[0]} · %{customdata[1]}<extra></extra>",
        pull=[0.06 if _pct(i["count"], total) < 3 else 0 for i in items],   # 작은 조각은 살짝 빼서 보이게
    ))
    fig.update_layout(height=height, showlegend=False, **{k: v for k, v in layout.items() if k != "margin"},
                      margin=dict(t=40, b=40, l=110, r=110), uniformtext=dict(minsize=11, mode="show"),
                      annotations=[dict(text=f"<b>{center_top}</b>", x=0.5, y=0.54, showarrow=False,
                                        font=dict(size=22, color=INK)),
                                   dict(text=center_bottom, x=0.5, y=0.44, showarrow=False,
                                        font=dict(size=12, color=MUTED))])
    st.plotly_chart(fig, width="stretch", key=key)


def render(load_json, layout):
    d = load_json("wcs_assets.json") or {}
    items = [i for i in d.get("items", []) if i.get("count")]
    as_of = d.get("as_of", "-")
    st.markdown(f'<div class="sect">🗄️ 통합 물 지식 자산 현황 — 연구보고서·논문·특허 '
                f'<span class="gchip">기준 {as_of}</span></div>', unsafe_allow_html=True)
    if not items:
        st.info("자산 숫자가 없습니다 — data_seed/wcs_assets.json을 확인하세요.")
        return
    total = sum(i["count"] for i in items)
    st.caption(f"{d.get('system', 'WCS')}에서 검색할 수 있는 자료 — 연구보고서는 K-water 자체 성과, "
               "논문·특허는 외부 문헌을 함께 모은 것")

    cards = [("전체 지식 자산", f"{total:,}건", "보고서 + 논문 + 특허", "#0A3D74")] + [
        (i["label"], f"{i['count']:,}{i['unit']}", f"전체의 {_fmt_pct(_pct(i['count'], total))}", COLORS.get(i["key"], "#94A3B8"))
        for i in items]
    st.markdown('<div class="kpis">' + "".join(
        f'<div class="kpi" style="border-left-color:{c}"><div class="k-val">{v}</div>'
        f'<div class="k-lab">{l}</div><div class="k-sub">{s}</div></div>' for l, v, s, c in cards) + "</div>",
        unsafe_allow_html=True)

    a, b = st.columns(2)
    with a:
        st.markdown('<div class="sect">전체 구성 (건수 비중)</div>', unsafe_allow_html=True)
        _donut(items, total, f"{total:,}", "전체 건수", "asset_all", layout)
    own = [i for i in items if i["key"] != "papers"]
    with b:
        own_total = sum(i["count"] for i in own)
        st.markdown('<div class="sect">논문을 뺀 보고서·특허</div>', unsafe_allow_html=True)
        if own_total:
            _donut(own, own_total, f"{own_total:,}", "보고서 + 특허", "asset_own", layout)
        st.caption("논문이 전체의 대부분이라, 보고서와 특허의 비율은 따로 그렸습니다.")

    st.markdown('<div class="sect">표로 보기</div>', unsafe_allow_html=True)
    st.dataframe(pd.DataFrame([{"구분": i["label"], "건수": i["count"], "단위": i["unit"],
                                "전체 대비(%)": round(_pct(i["count"], total), 2), "출처": i.get("note", "")}
                               for i in items] + [{"구분": "합계", "건수": total, "단위": "건", "전체 대비(%)": 100.0,
                                                   "출처": f"기준일 {as_of}"}]),
                 hide_index=True, width="stretch",
                 column_config={"건수": st.column_config.NumberColumn(format="localized")})
    st.caption("숫자 고치기: data_seed/wcs_assets.json의 count·as_of (보고서 수는 담당자 제공 값, 논문·특허는 WCS DB 건수)")
