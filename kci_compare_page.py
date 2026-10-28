#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🆚 K-water 비교(KCI) — 최근 5년 KCI 논문을 7개 연구소 분야로 나눠 K-water 논문과 국내 학회지 전체를 견줌 (v3.17)

재료: data_seed/kci_inst.json (agents/kci_inst.py — kci-rising 워크플로가 매주 비공개 원천에서 집계만 씀)
  · scopes.domestic            국내 학회지(한국수자원학회논문집 + 대한토목학회논문집) 전체
  · scopes.kwater              K-water 소속 논문 (KCI 전체 학회지)
  · scopes.kwater_in_domestic  국내 학회지 안의 K-water 논문 — 같은 학회지끼리의 점유율
  · 각 scope: N(전체 편수) · inst.<INST>.n / by_year · unclassified · journals(게재지 상위)
한 논문이 여러 연구소 분야에 들 수 있어(중복 집계) 분야 비중의 합은 100%를 넘을 수 있다.
"""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

DOM_C, KW_C, INK, MUTED = "#94A3B8", "#17549A", "#0F2744", "#64748B"
UP_C, DOWN_C = "#17549A", "#D97706"     # 특화도 1보다 큼 / 작음
SMALL_N = 20                              # 이보다 적은 편수는 '편수 적음'


def _short(name: str) -> str:
    return name[:-3] if name.endswith("연구소") and len(name) > 3 else name


def _rows(d: dict, names: dict) -> list:
    sc = d.get("scopes") or {}
    dom, kw, kin = sc.get("domestic") or {}, sc.get("kwater") or {}, sc.get("kwater_in_domestic") or {}
    codes = sorted(set(dom.get("inst", {})) | set(kw.get("inst", {})) | set(names))
    rows = []
    for c in codes:
        dn = (dom.get("inst", {}).get(c) or {}).get("n", 0)
        kn = (kw.get("inst", {}).get(c) or {}).get("n", 0)
        inn = (kin.get("inst", {}).get(c) or {}).get("n", 0)
        ds = dn / dom["N"] * 100 if dom.get("N") else None
        ks = kn / kw["N"] * 100 if kw.get("N") else None
        rows.append({"code": c, "name": names.get(c, c), "short": _short(names.get(c, c)),
                     "dom_n": dn, "dom_s": ds, "kw_n": kn, "kw_s": ks,
                     "rta": ks / ds if ds and ks is not None else None,
                     "in_n": inn, "occ": inn / dn * 100 if dn else None})
    return rows


def render(d: dict, names: dict, colors: dict, layout: dict):
    st.markdown('<div class="sect">🆚 K-water 비교 (KCI) — 연구소 분야별 K-water 논문 vs 국내 학회지, 최근 5년</div>',
                unsafe_allow_html=True)
    sc = (d or {}).get("scopes") or {}
    if not sc.get("domestic", {}).get("N"):
        st.info("집계가 아직 없습니다 — kci-rising 워크플로(매주 월요일)의 kci_inst 단계가 data_seed/kci_inst.json을 씁니다.")
        return
    ys = d.get("years") or []
    span = f"{ys[0]}~{ys[-1]}" if ys else ""
    dom, kw, kin = sc["domestic"], sc["kwater"], sc.get("kwater_in_domestic") or {}
    rows = _rows(d, names)
    occ_all = kin.get("N", 0) / dom["N"] * 100 if dom.get("N") else None

    st.markdown('<div class="kpis">' + "".join(
        f'<div class="kpi" style="border-left-color:{c}"><div class="k-val">{v}</div><div class="k-lab">{l}</div>'
        f'<div class="k-sub">{s}</div></div>' for v, l, s, c in (
            (f"{dom['N']:,}편", "국내 학회지", "한국수자원학회논문집 + 대한토목학회논문집", DOM_C),
            (f"{kw['N']:,}편", "K-water 소속 논문", "KCI 전체 학회지", KW_C),
            (f"{kin.get('N', 0):,}편", "국내 학회지 안 K-water", f"점유율 {occ_all:.1f}%" if occ_all is not None else "", "#1FA8C9"),
            (f"{kw.get('unclassified', 0) / kw['N'] * 100:.0f}%" if kw.get("N") else "-", "K-water 미분류",
             "7개 분야 키워드에 안 걸린 논문", "#CBD5E1"))) + "</div>", unsafe_allow_html=True)
    st.caption(f"KCI(한국학술지인용색인) 데이터 활용 · {span} 출판(올해 제외) · 국문 제목·초록에서 연구소별 한국어 키워드로 분야를 나눔 "
               "(한 논문이 여러 분야에 들 수 있음) · 집계만 공개")

    c1, c2 = st.columns(2)
    with c1:
        st.markdown('<div class="sect">분야 구성 — 전체 논문 중 그 분야 비중</div>', unsafe_allow_html=True)
        rr = rows[::-1]
        fig = go.Figure()
        for lab, key, nkey, col in (("국내 학회지", "dom_s", "dom_n", DOM_C), ("K-water", "kw_s", "kw_n", KW_C)):
            fig.add_trace(go.Bar(y=[r["short"] for r in rr], x=[r[key] or 0 for r in rr], orientation="h", name=lab,
                                 marker=dict(color=col, cornerradius=3),
                                 text=[f"{r[key]:.1f}%" if r[key] is not None else "" for r in rr], textposition="outside",
                                 cliponaxis=False, customdata=[r[nkey] for r in rr],
                                 hovertemplate=lab + " · %{y}<br>%{x:.1f}% (%{customdata:,}편)<extra></extra>"))
        fig.update_layout(height=420, barmode="group", bargap=0.28, bargroupgap=0.08,
                          legend=dict(orientation="h", y=1.08, x=0), **layout)
        fig.update_xaxes(ticksuffix="%", gridcolor="#EEF2F7", range=[0, max(max(r["dom_s"] or 0, r["kw_s"] or 0) for r in rows) * 1.18])
        st.plotly_chart(fig, width="stretch", key="kcik_mix")
    with c2:
        st.markdown('<div class="sect">K-water 특화도 — K-water 비중 ÷ 국내 학회지 비중</div>', unsafe_allow_html=True)
        rr = [r for r in rows if r["rta"] is not None][::-1]
        fig = go.Figure(go.Bar(
            y=[r["short"] for r in rr], x=[r["rta"] - 1 for r in rr], base=1, orientation="h",
            marker=dict(color=[UP_C if r["rta"] >= 1 else DOWN_C for r in rr], cornerradius=3),
            text=[f"{r['rta']:.2f}배" for r in rr], textposition="outside", cliponaxis=False,
            customdata=[[r["kw_s"], r["dom_s"]] for r in rr],
            hovertemplate="%{y}<br>특화도 %{text}<br>K-water %{customdata[0]:.1f}% ÷ 국내 %{customdata[1]:.1f}%<extra></extra>"))
        fig.add_vline(x=1, line=dict(color=INK, width=1.5))
        hi = max(r["rta"] for r in rr) if rr else 2
        fig.update_layout(height=420, showlegend=False, **layout)
        fig.update_xaxes(range=[0, hi * 1.2], gridcolor="#EEF2F7", ticksuffix="배")
        st.plotly_chart(fig, width="stretch", key="kcik_rta")
    st.caption("특화도 1보다 크면(파랑) K-water가 국내 학회지 평균보다 그 분야 논문을 상대적으로 많이 냄, 작으면(주황) 상대적으로 적게 냄. "
               "⚠️ K-water 논문은 상하수도학회지·환경공학회지 등 여러 학회지에 실리고, 국내 학회지 기준은 수자원·토목 두 학회지라 "
               "상하수도·에너지 분야는 특화도가 크게 나오기 쉬움 — 같은 학회지끼리 비교는 아래 '점유율'.")

    c3, c4 = st.columns(2)
    with c3:
        st.markdown('<div class="sect">같은 학회지 안 K-water 점유율 — 분야별</div>', unsafe_allow_html=True)
        rr = [r for r in rows if r["occ"] is not None][::-1]
        fig = go.Figure(go.Bar(
            y=[r["short"] for r in rr], x=[r["occ"] for r in rr], orientation="h",
            marker=dict(color=[colors.get(r["code"], KW_C) for r in rr], cornerradius=3,
                        opacity=[0.45 if r["in_n"] < 5 else 0.95 for r in rr]),
            text=[f"{r['occ']:.1f}% ({r['in_n']}/{r['dom_n']})" for r in rr], textposition="outside", cliponaxis=False,
            hovertemplate="%{y} · 국내 학회지 그 분야 논문 중 K-water %{x:.1f}%<extra></extra>"))
        if occ_all is not None:
            fig.add_vline(x=occ_all, line=dict(color=INK, width=1.5, dash="dash"))
        fig.update_layout(height=380, showlegend=False, **layout)
        fig.update_xaxes(ticksuffix="%", gridcolor="#EEF2F7",
                         range=[0, max([r["occ"] for r in rr] + [occ_all or 0]) * 1.45 if rr else 10])
        st.plotly_chart(fig, width="stretch", key="kcik_occ")
        st.caption(f"한국수자원학회논문집 + 대한토목학회논문집의 그 분야 논문 중 K-water 소속 비중 · 점선 = 전체 점유율"
                   + (f" {occ_all:.1f}%" if occ_all is not None else "") + " · 흐린 막대 = 5편 미만이라 참고만")
    with c4:
        st.markdown('<div class="sect">K-water 논문 연도별 — 분야별 편수</div>', unsafe_allow_html=True)
        fig = go.Figure()
        for r in rows:
            by = (kw.get("inst", {}).get(r["code"]) or {}).get("by_year") or {}
            if not by:
                continue
            fig.add_trace(go.Scatter(x=ys, y=[by.get(y, 0) for y in ys], mode="lines+markers", name=r["short"],
                                     line=dict(color=colors.get(r["code"], KW_C), width=2), marker=dict(size=7),
                                     hovertemplate=r["short"] + " %{x}년 · %{y}편<extra></extra>"))
        fig.add_trace(go.Bar(x=ys, y=[kw["by_year_N"].get(y, 0) for y in ys], name="K-water 전체", marker_color="#E2E8F0",
                             opacity=0.7, hovertemplate="K-water 전체 %{x}년 · %{y}편<extra></extra>"))
        fig.update_layout(height=380, legend=dict(orientation="h", y=-0.2), **layout)
        fig.update_xaxes(type="category")
        fig.update_yaxes(gridcolor="#EEF2F7", rangemode="tozero")
        st.plotly_chart(fig, width="stretch", key="kcik_years")
        st.caption("회색 막대 = 그 해 K-water 소속 KCI 논문 전체 · 선 = 분야별 (여러 분야에 드는 논문은 겹쳐 셈)")

    st.markdown('<div class="sect">표로 보기</div>', unsafe_allow_html=True)
    df = pd.DataFrame([{"연구소": r["name"], "국내 학회지 편수": r["dom_n"],
                        "국내 비중(%)": round(r["dom_s"], 1) if r["dom_s"] is not None else None,
                        "K-water 편수": r["kw_n"], "K-water 비중(%)": round(r["kw_s"], 1) if r["kw_s"] is not None else None,
                        "특화도": round(r["rta"], 2) if r["rta"] is not None else None,
                        "학회지 안 K-water": r["in_n"], "점유율(%)": round(r["occ"], 1) if r["occ"] is not None else None,
                        "비고": "편수 적음" if r["kw_n"] < SMALL_N else ""} for r in rows]
                      + [{"연구소": "미분류", "국내 학회지 편수": dom.get("unclassified", 0),
                          "국내 비중(%)": round(dom.get("unclassified", 0) / dom["N"] * 100, 1),
                          "K-water 편수": kw.get("unclassified", 0),
                          "K-water 비중(%)": round(kw.get("unclassified", 0) / kw["N"] * 100, 1) if kw.get("N") else None,
                          "특화도": None, "학회지 안 K-water": kin.get("unclassified", 0), "점유율(%)": None, "비고": ""}])
    st.dataframe(df, hide_index=True, width="stretch",
                 column_config={"특화도": st.column_config.NumberColumn(format="%.2f배")})

    with st.expander("방법 · 주의할 점 · K-water 게재 학회지"):
        st.markdown(
            f"- **기간**: {span} 출판 (올해는 진행 중이라 제외)\n"
            f"- **분야 나누기**: {d.get('method', '')}. 키워드 고치기: `data_seed/label_review_profiles.json`의 `keywords.<연구소>.ko`\n"
            "- **특화도** = K-water 논문 중 그 분야 비중 ÷ 국내 학회지 논문 중 그 분야 비중 (1 = 국내 평균과 같음)\n"
            "- **점유율** = 국내 학회지(같은 두 학회지)의 그 분야 논문 중 K-water 소속 비중 — 학회지 차이를 뺀 비교지만 편수가 적음\n"
            "- **주의**: 국내 학회지 기준은 수자원·토목 두 학회지뿐이라 상하수도·에너지·환경 분야 논문이 적게 잡힘. "
            "K-water 소속 판정은 저자 소속 규칙 + 사람 판정(K-water 문헌 적정성 화면)\n"
            "- **출처**: KCI(한국학술지인용색인) 데이터 활용 — 공개 화면에는 건수 집계만")
        jr = kw.get("journals") or []
        if jr:
            st.dataframe(pd.DataFrame(jr, columns=["K-water 게재 학회지", f"{span} 편수"]), hide_index=True, width="stretch")
