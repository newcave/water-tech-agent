"""
관제센터 '🔭 상승 연구주제' 화면 — openalex(newcave/openalex) 분석 결과 연동 (1단계)

데이터: data_seed/oa_rising/index.json + <key>.json (agents/oa_rising.py가 비공개 openalex-data에서 집계만 뽑아 씀,
        .github/workflows/oa-rising.yml · secrets.OPENALEX_DATA_TOKEN)
방법의 주인은 openalex 저장소 — 여기서는 다시 계산하지 않고 보여 주기만 한다.
"""
from __future__ import annotations

import datetime as dt
import html

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

CAT8 = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
NAVY, BLUE, CYAN, GREEN, RED, GRAY, AMBER = "#0A3D74", "#0B5FAE", "#1FA8C9", "#16A34A", "#DC2626", "#94A3B8", "#D97706"
INST_NAME = {"INST-01": "경영연구소", "INST-02": "수자원환경연구소", "INST-03": "상하수도연구소",
             "INST-04": "물인프라안전연구소", "INST-05": "물에너지연구소", "INST-06": "수자원위성연구소", "INST-07": "AI연구소"}
CSS = """<style>
.oa-card {background:#fff; border:1px solid #E3EAF3; border-radius:14px; padding:12px 14px; margin:4px 0 8px;}
.oa-chip {display:inline-block; font-size:.74rem; background:#EAF1FA; color:#17549A; border-radius:999px;
  padding:1px 8px; margin:2px 3px 2px 0;}
.oa-chip b {color:#0A3D74;}
.oa-badge {display:inline-block; font-size:.7rem; font-weight:700; border-radius:6px; padding:1px 7px; margin-left:6px;}
.oa-mini {font-size:.8rem; color:#475569; line-height:1.6;}
.oa-paper {font-size:.82rem; color:#1E293B; line-height:1.45; margin:4px 0;}
.oa-paper a {color:#17549A; text-decoration:none;} .oa-paper a:hover {text-decoration:underline;}
.oa-win {background:#F6F9FD; border:1px solid #E1E8F2; border-radius:10px; padding:8px 10px; margin-bottom:6px;}
</style>"""


def _kpis(rows):
    st.markdown('<div class="kpis">' + "".join(
        f'<div class="kpi" style="border-left-color:{c}"><div class="k-val">{v}</div>'
        f'<div class="k-lab">{l}</div><div class="k-sub">{s}</div></div>' for l, v, s, c in rows) + "</div>",
        unsafe_allow_html=True)


def _when(iso: str | None) -> str:
    try:
        t = dt.datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
        return t.astimezone(dt.timezone(dt.timedelta(hours=9))).strftime("%Y-%m-%d %H:%M KST")
    except Exception:
        return iso or "-"


def _short(label: str, n: int = 22) -> str:
    return label if len(label) <= n else label[: n - 1] + "…"


def render(load_json, plotly_layout: dict):
    st.markdown(CSS, unsafe_allow_html=True)
    st.markdown('<div class="sect">🔭 상승 연구주제 — OpenAlex 저널 논문 (openalex 분석 연동)</div>', unsafe_allow_html=True)
    idx = load_json("oa_rising/index.json") or {}
    srcs = idx.get("sources") or []
    if not srcs:
        st.info("아직 연동된 결과가 없습니다. 저장소 Secrets에 `OPENALEX_DATA_TOKEN`(newcave/openalex-data 읽기 전용)을 넣으면 "
                "oa-rising 워크플로가 매주 openalex 분석 결과를 읽어 이 화면을 채웁니다.")
        return
    keys = [s["key"] for s in srcs]
    by = {s["key"]: s for s in srcs}
    key = st.radio("자료", keys, horizontal=True, key="oa_src",
                   format_func=lambda k: by[k]["title"] + (f" · {INST_NAME.get(by[k]['inst'], '')}" if by[k].get("inst") else ""),
                   label_visibility="collapsed") if len(keys) > 1 else keys[0]
    d = load_json(by[key]["file"]) or {}
    if not d:
        st.warning("결과 파일을 읽지 못했습니다.")
        return
    run, lab, cl = d.get("run") or {}, d.get("labels") or {}, d.get("clusters") or []
    y0, y1 = (d.get("years") or ["?", "?"])
    miss = idx.get("fields_missing") or []

    steps = [("① 저널 수집", f"{y0}–{y1}", "OpenAlex · openalex 수집기"),
             ("② 코퍼스", f"{(d.get('documents') or 0):,}편", "article·review·letter · 영어 제목"),
             ("③ 추세 검정", f"{d.get('candidates', 0):,}개 용어", "Hamed–Rao MK · 15건 이상"),
             ("④ FDR 보정", f"Rising {lab.get('Rising', 0):,}", "BH q ≤ 0.05 · τ > 0"),
             ("⑤ 네트워크", f"연결 {(run.get('edges') or 0):,}", f"association strength · 동시출현 ≥ {run.get('min_cooccurrence', 2)}"),
             ("⑥ 커뮤니티", f"{len(cl)}개 · Q {run.get('modularity') or 0:.3f}", f"Louvain (seed {run.get('louvain_seed', 0)})")]
    st.markdown('<div class="flow">' + '<div class="arr">›</div>'.join(
        f'<div class="stage"><div class="s-t">{t}</div><div class="s-v">{v}</div><div class="s-s">{s}</div></div>'
        for t, v, s in steps) + '</div>', unsafe_allow_html=True)
    st.caption(f"{d.get('note', '')} · 방법: newcave/openalex · 데이터 openalex-data@{d.get('data_commit') or '?'} · "
               f"연동 {_when(d.get('updated'))}" + (f" · 분야별 결과 대기: {', '.join(miss)}" if miss else ""))

    rising = d.get("rising") or []
    hot = max((r for r in rising if r.get("z3") is not None and (r.get("docs") or 0) >= 200), key=lambda r: r["z3"], default=None)
    steady = max(rising, key=lambda r: r.get("tau") or 0, default=None)
    _kpis([("검정 용어", f"{d.get('candidates', 0):,}", "전체 기간 15건 이상 제목 단어", BLUE),
           ("Rising (유의)", f"{lab.get('Rising', 0):,}", "q ≤ 0.05 · τ > 0", GREEN),
           ("Declining (유의)", f"{lab.get('Declining', 0):,}", "q ≤ 0.05 · τ < 0", RED),
           ("연구주제 커뮤니티", f"{len(cl)}", f"modularity {run.get('modularity') or 0:.3f}", NAVY),
           ("가장 꾸준한 상승", steady["term"] if steady else "-", f"τ {steady['tau']} · {steady['sen']:+.3f}%p/년" if steady else "", CYAN),
           ("최근 급등", hot["term"] if hot else "-", f"최근 3년 z {hot['z3']:+.1f} · 논문 200편 이상 중" if hot else "", "#7C3AED")])

    labels = {c["cluster"]: c["label"] for c in cl}
    col = {c["cluster"]: CAT8[i] if i < len(CAT8) else GRAY for i, c in enumerate(sorted(cl, key=lambda c: -c["size"]))}
    t1, t2, t3, t4, t5 = st.tabs(["🧩 연구주제 커뮤니티", "📈 Rising 용어", "🪟 구간별 흐름", "📉 Declining 용어", "ℹ️ 방법·연동"])

    # ── 커뮤니티 ──
    with t1:
        big = [c for c in sorted(cl, key=lambda c: -c["size"]) if c["series"]]
        a, b = st.columns([3, 2])
        with a:
            st.markdown('<div class="sect">커뮤니티별 논문 비중 추이 (그 해 논문 중 해당 용어가 든 비율)</div>', unsafe_allow_html=True)
            fig = go.Figure()
            for c in big[:8]:
                fig.add_scatter(x=[y for y, _ in c["series"]], y=[v for _, v in c["series"]], mode="lines",
                                name=f"C{c['cluster']} {_short(c['label'], 18)}", line=dict(color=col[c["cluster"]], width=2.4),
                                hovertemplate=f"C{c['cluster']} · %{{x}}: %{{y:.1f}}%<extra></extra>")
            fig.update_layout(**plotly_layout, height=360, legend=dict(orientation="h", y=-0.18, font=dict(size=11)),
                              yaxis=dict(title="논문 비중 (%)", rangemode="tozero"), xaxis=dict(dtick=5))
            st.plotly_chart(fig, width="stretch")
        with b:
            st.markdown('<div class="sect">커뮤니티 사이 연결 (함께 나온 논문 수)</div>', unsafe_allow_html=True)
            links = [l for l in (d.get("links") or []) if l[0] in labels and l[1] in labels]
            if links:
                mx = max(l[2] for l in links)
                rows = "".join(
                    f'<div class="oa-mini"><span style="color:{col[x]}">●</span> C{x} ↔ <span style="color:{col[y]}">●</span> C{y} '
                    f'<span style="display:inline-block;height:7px;width:{max(4, int(120 * n / mx))}px;background:#9DB8DA;'
                    f'border-radius:4px;vertical-align:middle;margin:0 6px"></span>{n:,}</div>' for x, y, n in links[:10])
                st.markdown(f'<div class="oa-card">{rows}</div>', unsafe_allow_html=True)
            st.caption("엣지 가중치는 association strength c_ij/√(f_i·f_j) — 여기 숫자는 두 커뮤니티 용어가 함께 나온 논문 수(원시)입니다.")
        for c in sorted(cl, key=lambda c: -c["size"]):
            badge_c = {"검토 라벨": ("#E6F6F4", "#0F766E"), "AI 라벨 (참고용)": ("#F3EEFF", "#7C3AED")}.get(c["label_src"], ("#EEF1F5", "#475569"))
            with st.expander(f"C{c['cluster']} · {c['label']} — 용어 {c['size']}개 · τ {c['tau']} · {c['sen']:+.2f}%p/년", expanded=False):
                st.markdown(f'<span class="oa-badge" style="background:{badge_c[0]};color:{badge_c[1]};margin-left:0">{c["label_src"]}</span>',
                            unsafe_allow_html=True)
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("평균 논문 비중", f"{c['share']:.1f}%")
                m2.metric("추세 τ (MK)", f"{c['tau']}", f"p {c['p']:.1e}" if c.get("p") is not None else None, delta_color="off")
                m3.metric("Sen 기울기", f"{c['sen']:+.3f}%p/년")
                m4.metric("최근5년 − 처음5년", f"{c['gain']:+.1f}%p")
                chips = []
                for t in c["top"]:
                    n_docs = f" {t['docs']:,}" if t.get("docs") else ""
                    chips.append(f'<span class="oa-chip"><b>{html.escape(t["term"])}</b>{n_docs}</span>')
                st.markdown("**대표 용어** (커뮤니티 안 연결이 강한 순 · 숫자 = 논문 수)<br>" + "".join(chips),
                            unsafe_allow_html=True)
                if c.get("themes"):
                    st.markdown("**하위 주제** " + " · ".join(
                        f'{html.escape(t["name"] or "")} <span class="oa-mini">({", ".join("–".join(p) for p in t.get("pairs", [])[:3])})</span>'
                        for t in c["themes"]), unsafe_allow_html=True)
                if c.get("ai_insight"):
                    st.caption("AI 해설 (참고용): " + c["ai_insight"])
                if c.get("papers"):
                    st.markdown("**근거 논문** (대표 용어를 많이 담은 제목 — 표시용 선정, 대표 표본 아님)")
                    st.markdown("".join(
                        f'<div class="oa-paper">· <a href="https://openalex.org/{p["id"]}" target="_blank">{html.escape(p["title"])}</a> '
                        f'<span class="oa-mini">— {p.get("journal", "")} {p.get("year") or ""}</span></div>' for p in c["papers"]),
                        unsafe_allow_html=True)

    # ── Rising 용어 ──
    with t2:
        f1, f2, f3, f4 = st.columns([3, 2, 2, 2])
        pick = f1.multiselect("커뮤니티", sorted(labels), format_func=lambda x: f"C{x} {_short(labels[x], 20)}",
                              key="oa_cl", placeholder="전체")
        q = f2.text_input("용어 찾기", key="oa_q", placeholder="예: learning")
        sort = f3.selectbox("정렬", ["Sen 기울기", "τ (추세 강도)", "최근 3년 z", "평균 비중"], key="oa_sort")
        new_only = f4.toggle("2015년 이후 첫 등장만", key="oa_new")
        rows = [r for r in rising if (not pick or r.get("cluster") in pick) and (not q or q.lower() in r["term"])
                and (not new_only or r.get("new"))]
        sk = {"Sen 기울기": "sen", "τ (추세 강도)": "tau", "최근 3년 z": "z3", "평균 비중": "share"}[sort]
        rows = sorted(rows, key=lambda r: -(r.get(sk) if r.get(sk) is not None else -9e9))
        a, b = st.columns([2, 3])
        with a:
            st.markdown(f'<div class="sect">상위 25 · {sort}</div>', unsafe_allow_html=True)
            top = rows[:25][::-1]
            fig = go.Figure(go.Bar(x=[r.get(sk) or 0 for r in top], y=[r["term"] for r in top], orientation="h",
                                   marker_color=[col.get(r.get("cluster"), GRAY) for r in top],
                                   hovertemplate="%{y}: %{x}<extra></extra>"))
            fig.update_layout(**plotly_layout, height=560, xaxis_title=sort, yaxis=dict(tickfont=dict(size=11)))
            st.plotly_chart(fig, width="stretch")
            st.caption("막대 색 = 커뮤니티")
        with b:
            st.markdown(f'<div class="sect">Rising 용어 {len(rows):,}개</div>', unsafe_allow_html=True)
            df = pd.DataFrame([{"용어": r["term"], "커뮤니티": f"C{r['cluster']} {_short(labels.get(r['cluster'], ''), 14)}" if r.get("cluster") is not None else "",
                                "τ": r["tau"], "q": r["q"], "Sen (%p/년)": r["sen"], "최근3년 z": r["z3"],
                                "평균 비중(%)": r["share"], "최근5년 비중(%)": r["share5"], "논문": r["docs"],
                                "첫 등장": r["first"], "버스트 연도": r["burst_year"]} for r in rows])
            st.dataframe(df, hide_index=True, width="stretch", height=560)
            st.download_button(f"⬇️ Rising 용어 CSV ({len(df):,})", df.to_csv(index=False).encode("utf-8-sig"),
                               file_name=f"oa_rising_{key}.csv", mime="text/csv")

    # ── 구간별 ──
    with t3:
        wins = d.get("windows") or []
        st.caption("5–6년 비중복 구간마다 따로 분석합니다. 구간 안 연도가 5–6개뿐이라 FDR 보정 뒤 Rising이 거의 남지 않아, "
                   "**τ > 0(그 구간에서 증가 방향)** 용어로 커뮤니티를 만듭니다 — '유의하게 부상한 주제'가 아니라 "
                   "'그 시기에 늘어나는 쪽이던 용어의 구조'로 읽어야 합니다. Louvain은 다시 돌리면 구성이 조금 달라질 수 있습니다.")
        if not wins:
            st.info("구간별 결과가 없습니다.")
        else:
            st.dataframe(pd.DataFrame([{"구간": w["window"], "연수": w["n_years"], "논문": w["docs"], "후보 용어": w["candidates"],
                                        "τ>0 용어": w["tau_pos"], "커뮤니티": w["clusters"], "modularity": w["modularity"]}
                                       for w in wins]), hide_index=True, width="stretch")
            cols = st.columns(len(wins))
            for cc, w in zip(cols, wins):
                with cc:
                    st.markdown(f"**{w['window']}**")
                    for g in w["groups"][:5]:
                        st.markdown(f'<div class="oa-win"><div class="oa-mini"><b>C{g["cluster"]}</b> · {g["size"]}개</div>'
                                    + "".join(f'<span class="oa-chip">{html.escape(t)}</span>' for t in g["top"][:7]) + "</div>",
                                    unsafe_allow_html=True)

    # ── Declining ──
    with t4:
        dec = d.get("declining") or []
        st.caption(f"유의하게 줄어드는 용어 {lab.get('Declining', 0):,}개 중 τ가 가장 낮은 {len(dec)}개. "
                   "포화된 핵심어(예: water·model)는 Not Significant가 정상 — 크기(평균 비중)는 따로 봐야 합니다.")
        st.dataframe(pd.DataFrame([{"용어": r["term"], "τ": r["tau"], "q": r["q"], "Sen (%p/년)": r["sen"],
                                    "평균 비중(%)": r["share"], "최근5년 비중(%)": r["share5"], "논문": r["docs"]} for r in dec]),
                     hide_index=True, width="stretch", height=460)

    # ── 방법·연동 ──
    with t5:
        st.markdown(f"""
#### 무엇을 보여 주나
[newcave/openalex](https://github.com/newcave/openalex)가 계산한 **상승 연구주제 분석 결과**를 그대로 보여 줍니다 (이 앱은 다시 계산하지 않음).
현재 자료: **{d.get('title')}** — {d.get('note', '')}.

| 단계 | 방법 (openalex 코드) |
|---|---|
| 코퍼스 | article·review·letter, comment/reply 제목 패턴 제외, 영어 제목 (`n_01_build_corpus`) |
| 용어 | 제목 유니그램, 태그·하이픈·접두어 정리, 정규화 사전 (`n_02`, `normalization`) |
| 추세 | 연도별 논문 비중의 Hamed–Rao 수정 Mann–Kendall + Sen 기울기, 후보 = 전체 15건 이상 (`trend_tags`) |
| 보정 | Benjamini–Hochberg FDR q ≤ 0.05 → Rising(τ>0) / Declining(τ<0) (`n_03`) |
| 네트워크 | Rising 용어 동시출현 ≥ {run.get('min_cooccurrence', 2)}, association strength c_ij/√(f_i·f_j) (`n_04`) |
| 커뮤니티 | Louvain resolution 1.0 · seed {run.get('louvain_seed', 0)} → {len(cl)}개, modularity {run.get('modularity') or 0:.3f} |
| 구간별 | 5–6년 구간 · τ > 0 (유의성 검정 없음) (`n_06`) |

#### 연동 방식
- 매주 `oa-rising` 워크플로가 비공개 저장소 **openalex-data**에서 결과 폴더만 읽어(`secrets.OPENALEX_DATA_TOKEN`, 읽기 전용)
  `agents/oa_rising.py`로 **집계만** `data_seed/oa_rising/`에 씁니다.
- 옮기지 않는 것: 논문 해석 원문, 검토 메모, 전체 논문 목록, 코퍼스 원본.
- 라벨: **검토 라벨**(사람이 검토해 붙인 이름) > AI 라벨(참고용) > 분석 코드 라벨 순으로 씁니다.
- 분야별(AI·수자원환경·물인프라안전·상하수도·물에너지·경영) 결과는 openalex 웹앱에서 '분석 진행하기'를 하면 다음 연동부터 자동으로 나타납니다
  (수자원위성연구소에 해당하는 분야는 openalex에 아직 없음).

#### 🇰🇷 KCI 트렌드와의 관계
같은 계열 방법(Hamed–Rao MK + BH)의 국내 학회지판입니다. 다만 KCI 쪽 주제 묶음은 아직 원시 동시출현(≥3, 상위 80개, 최근 5년)이라
연결 방식이 다릅니다 — 다음 단계에서 association strength로 맞출 예정입니다.
""")
