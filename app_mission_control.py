"""
K-water Co-Scientist ─ 에이전트 관제센터 (Mission Control)

모두에게 보여주는 실시간 현황판:
  🛰️ 관제센터   : 에이전트별 상태(펄스)·핵심지표·활동 피드
  📚 수집 현황  : 소스별(ALIO/논문/특허) 파이프라인 진행
  🏢 7개 연구소 : K-water연구원 연구소별 문서·데이터·협업 네트워크
  🔥 FT 모니터  : 코랩 학습 실시간 loss (ft_logs)
  🗂️ 인벤토리   : 공유 데이터소스 랭킹

데이터 소스(이중 모드):
  - 로컬: ./data_seed/*.json  (홈서버/개발노트북에서 export 스크립트가 갱신)
  - 클라우드: GitHub raw (repo의 data_seed/ 폴더) — Streamlit Cloud 배포 시

실행:  streamlit run app_mission_control.py
"""

import json
import time
import datetime as dt
from pathlib import Path

import requests
import pandas as pd
import streamlit as st
import plotly.graph_objects as go

st.set_page_config(page_title="K-water Co-Scientist 관제센터", page_icon="🛰️",
                   layout="wide", initial_sidebar_state="expanded")

GITHUB_REPO = "newcave/newcave/water-tech-agent"   # 클라우드 모드에서 data_seed/ft_logs를 읽을 repo
LOCAL_SEED = Path("data_seed")

INST_COLORS = {"INST-01": "#8b5cf6", "INST-02": "#0ea5e9", "INST-03": "#10b981",
               "INST-04": "#f59e0b", "INST-05": "#ef4444", "INST-06": "#6366f1",
               "INST-07": "#ec4899"}
AGENT_ORDER = ["alio_crawler", "alio_parser", "normalizer",
               "openalex_collector", "kipris_collector", "ft_trainer"]
AGENT_ICONS = {"alio_crawler": "📥", "alio_parser": "🧠", "normalizer": "🧩",
               "openalex_collector": "📄", "kipris_collector": "📜", "ft_trainer": "🔥"}

# ── 스타일: 펄스 도트 + 터미널 피드 ─────────────────────
st.markdown("""<style>
.pulse{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px}
.pulse.run{background:#22c55e;box-shadow:0 0 0 rgba(34,197,94,.6);animation:pulse 1.6s infinite}
.pulse.idle{background:#22c55e;opacity:.85}
.pulse.standby{background:#f59e0b;animation:pulse 2.4s infinite}
.pulse.error{background:#ef4444;animation:pulse 1s infinite}
@keyframes pulse{0%{box-shadow:0 0 0 0 rgba(34,197,94,.5)}70%{box-shadow:0 0 0 10px rgba(34,197,94,0)}100%{box-shadow:0 0 0 0 rgba(34,197,94,0)}}
.agent-card{border:1px solid rgba(128,128,128,.25);border-radius:12px;padding:14px 16px;margin-bottom:10px}
.agent-title{font-weight:700;font-size:1.02rem}
.agent-sub{opacity:.75;font-size:.85rem;margin-top:2px}
.feed{font-family:ui-monospace,Consolas,monospace;font-size:.83rem;line-height:1.55;
      background:rgba(15,23,42,.92);color:#d1fae5;border-radius:10px;padding:14px 16px;max-height:340px;overflow-y:auto}
.feed .t{color:#64748b}
.kpi-note{opacity:.65;font-size:.8rem}
</style>""", unsafe_allow_html=True)


# ── 데이터 로딩 (로컬 우선 → 깃헙 raw) ───────────────────
@st.cache_data(ttl=30)
def load_json(rel_path: str):
    p = LOCAL_SEED / rel_path
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/data_seed/{rel_path}"
    r = requests.get(url, timeout=10)
    return r.json() if r.status_code == 200 else None


@st.cache_data(ttl=30)
def load_agents():
    out = {}
    for name in AGENT_ORDER:
        d = load_json(f"agents/{name}.json")
        if d:
            out[name] = d
    return out


@st.cache_data(ttl=20)
def load_ft_runs():
    r = requests.get(f"https://api.github.com/repos/{GITHUB_REPO}/contents/ft_logs", timeout=8)
    if r.status_code != 200:
        return []
    return sorted([x["name"] for x in r.json() if x["type"] == "dir"], reverse=True)


def ago(ts):
    if not ts:
        return "-"
    s = int(time.time() - ts)
    if s < 90: return f"{s}초 전"
    if s < 5400: return f"{s//60}분 전"
    if s < 172800: return f"{s//3600}시간 전"
    return f"{s//86400}일 전"


def state_of(a):
    """상태 판정: 최근 10분 내 이벤트면 run으로 승격"""
    st_ = a.get("state", "standby")
    if a.get("events") and time.time() - a["events"][-1].get("ts", 0) < 600:
        return "run"
    return st_


summary = load_json("summary.json") or {"totals": {}, "inst_docs": {}, "inst_names": {}}
agents = load_agents()
T = summary["totals"]

# ── 사이드바 ────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🛰️ Co-Scientist")
    st.caption("K-water연구원 7개 연구소 · R&D 데이터 에이전트")
    page = st.radio("메뉴", ["🛰️ 관제센터", "📚 수집 현황", "🏢 7개 연구소",
                            "🔥 FT 모니터", "🗂️ 인벤토리"], label_visibility="collapsed")
    st.divider()
    auto = st.toggle("실시간 갱신 (30초)", value=True)
    st.caption(f"데이터 기준: {ago(summary.get('generated_at'))}")

# ═══════════════ 페이지 1: 관제센터 ═══════════════
if page == "🛰️ 관제센터":
    st.markdown(f"### 🛰️ 에이전트 관제센터")
    st.caption(f"현재 시각 {dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} · "
               f"대상: K-water연구원 7개 연구소 (경영·수자원환경·상하수도·물인프라안전·물에너지·수자원위성·AI)")

    c = st.columns(5)
    c[0].metric("ALIO 보고서", f"{T.get('alio_collected',0)}건",
                f"파싱 {T.get('alio_parsed_ok',0)} · 오류 {T.get('alio_errors',0)}")
    c[1].metric("데이터소스 mention", f"{T.get('mentions',0):,}건")
    c[2].metric("고유 데이터소스", f"{T.get('unique_datasources',0):,}개")
    c[3].metric("논문 (OpenAlex)", f"{T.get('papers',0)}건", "수집 대기", delta_color="off")
    c[4].metric("특허 (KIPRIS)", f"{T.get('patents',0)}건", "키 승인 대기", delta_color="off")

    st.divider()
    left, right = st.columns([1.15, 1])

    with left:
        st.markdown("#### 에이전트 상태")
        for name in AGENT_ORDER:
            a = agents.get(name)
            if not a:
                continue
            s = state_of(a)
            label = {"run": "가동 중", "idle": "정상 대기", "standby": "준비/예정", "error": "오류"}[s]
            counts = " · ".join(f"{k} <b>{v:,}</b>" for k, v in (a.get("counts") or {}).items())
            nxt = f" · 다음: {a['next_run']}" if a.get("next_run") else ""
            st.markdown(f"""<div class="agent-card">
              <div class="agent-title"><span class="pulse {s}"></span>{AGENT_ICONS[name]} {name}
                <span style="float:right;font-size:.8rem;opacity:.7">{label} · {ago(a.get('last_run'))}{nxt}</span></div>
              <div class="agent-sub">{a.get('summary','')}</div>
              <div style="margin-top:6px;font-size:.88rem">{counts}</div>
            </div>""", unsafe_allow_html=True)

    with right:
        st.markdown("#### 활동 피드")
        events = []
        for name, a in agents.items():
            for e in a.get("events", []):
                events.append((e.get("ts", 0), name, e.get("msg", "")))
        events.sort(reverse=True)
        rows = "".join(
            f'<div><span class="t">[{dt.datetime.fromtimestamp(ts).strftime("%m-%d %H:%M")}]</span> '
            f'<b>{AGENT_ICONS.get(n,"")} {n}</b> ▸ {m}</div>'
            for ts, n, m in events[:40])
        st.markdown(f'<div class="feed">{rows or "이벤트 없음"}</div>', unsafe_allow_html=True)
        st.markdown('<div class="kpi-note">에이전트가 실행될 때마다 status가 갱신되어 여기에 흐릅니다.</div>',
                    unsafe_allow_html=True)

# ═══════════════ 페이지 2: 수집 현황 ═══════════════
elif page == "📚 수집 현황":
    st.markdown("### 📚 소스별 수집 현황")
    rows = [
        ("보고서① ALIO", T.get("alio_collected", 0), 121, "🟢 완료 (오류 16건 재처리 대기)"),
        ("보고서② 기타(PRISM 등)", 0, 500, "⚪ 설계"),
        ("논문 OpenAlex (K-water 소속)", T.get("papers", 0), 3000, "🟡 수집기 배치, 첫 실행 대기"),
        ("특허 KIPRIS (한국수자원공사)", T.get("patents", 0), 500, "🟡 서비스키 승인 대기"),
        ("내부자료", 0, 0, "🔒 별도 트랙 (사내망 DB)"),
    ]
    for name, cur, target, status in rows:
        col1, col2 = st.columns([3, 1])
        with col1:
            st.markdown(f"**{name}**  <span style='opacity:.6'>{cur:,} / 목표 {target:,}</span>",
                        unsafe_allow_html=True)
            st.progress(min(cur / target, 1.0) if target else 0.0)
        col2.markdown(status)
    st.divider()
    st.markdown("#### 파이프라인 단계 (ALIO 트랙)")
    steps = [("1 크롤링", 121, 121), ("2 메타추출", 121, 121), ("3 기술분류", 121, 121),
             ("4 데이터소스 추출", T.get("alio_parsed_ok", 0), 121),
             ("5 정규화", T.get("alio_parsed_ok", 0), 121)]
    cols = st.columns(len(steps))
    for col, (nm, cur, tot) in zip(cols, steps):
        col.metric(nm, f"{cur}/{tot}", f"{cur/tot*100:.0f}%")

# ═══════════════ 페이지 3: 7개 연구소 ═══════════════
elif page == "🏢 7개 연구소":
    st.markdown("### 🏢 K-water연구원 7개 연구소 현황")
    st.caption("연구소 배정은 rule 기반 추정(키워드) — LLM 분류·검수로 정확도 향상 예정")
    inst_docs = summary.get("inst_docs", {})
    inst_names = summary.get("inst_names", {})
    inst_top = summary.get("inst_top_ds", {})

    cols = st.columns(7)
    for col, code in zip(cols, sorted(inst_names)):
        with col:
            st.markdown(f"<div style='text-align:center'>"
                        f"<div style='width:14px;height:14px;border-radius:50%;"
                        f"background:{INST_COLORS[code]};margin:0 auto'></div>"
                        f"<b>{inst_names[code]}</b><br>"
                        f"<span style='font-size:1.6rem;font-weight:800'>{inst_docs.get(code,0)}</span>"
                        f"<span style='opacity:.6'> 건</span></div>", unsafe_allow_html=True)

    st.divider()
    a, b = st.columns([1, 1])
    with a:
        st.markdown("#### 연구소별 문서 수")
        df = pd.DataFrame({"연구소": [inst_names[k] for k in sorted(inst_names)],
                           "문서": [inst_docs.get(k, 0) for k in sorted(inst_names)]})
        fig = go.Figure(go.Bar(x=df["문서"], y=df["연구소"], orientation="h",
                               marker_color=[INST_COLORS[k] for k in sorted(inst_names)]))
        fig.update_layout(height=300, margin=dict(t=10, b=10, l=10, r=10))
        st.plotly_chart(fig, use_container_width=True)
    with b:
        st.markdown("#### 연구소 간 협업 강도 (공유 데이터소스 수)")
        edges = load_json("edges.json") or []
        codes = sorted(inst_names)
        mat = pd.DataFrame(0, index=codes, columns=codes)
        for e in edges:
            mat.loc[e["src"], e["dst"]] = e["w"]
            mat.loc[e["dst"], e["src"]] = e["w"]
        fig = go.Figure(go.Heatmap(z=mat.values,
                                   x=[inst_names[c] for c in codes],
                                   y=[inst_names[c] for c in codes],
                                   colorscale="Blues", showscale=False,
                                   text=mat.values, texttemplate="%{text}"))
        fig.update_layout(height=300, margin=dict(t=10, b=10, l=10, r=10))
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("#### 연구소별 핵심 데이터소스 Top 5")
    sel = st.selectbox("연구소", sorted(inst_names), format_func=lambda c: f"{c} {inst_names[c]}")
    top = inst_top.get(sel, [])
    if top:
        st.dataframe(pd.DataFrame(top).rename(
            columns={"cid": "canonical", "name": "데이터소스", "n": "mention"}),
            hide_index=True, use_container_width=True)
    else:
        st.info("해당 연구소로 분류된 문서가 아직 적습니다.")

# ═══════════════ 페이지 4: FT 모니터 ═══════════════
elif page == "🔥 FT 모니터":
    st.markdown("### 🔥 파인튜닝 학습 모니터 (코랩 A100)")
    runs = load_ft_runs()
    if not runs:
        st.info("아직 학습 run이 없습니다. 코랩에서 colab_train_kwater.ipynb를 실행하면 "
                "ft_logs/가 생성되며 여기에 실시간 표시됩니다.")
        st.markdown("- 모델 후보: **KONI-Llama3-8B** (KISTI 한국어 과학기술) / Qwen2.5-7B\n"
                    "- 학습데이터: 4단계 추출 쌍 (GPT-4o distillation)\n"
                    "- 목표: 필드 F1 ≥ 90% 달성 시 로컬 전환(OpenAI 의존 제거)")
    else:
        run_id = st.selectbox("run", runs)
        url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/ft_logs/{run_id}/metrics.jsonl"
        r = requests.get(url, timeout=10)
        rows, meta = [], {}
        for line in (r.text.splitlines() if r.status_code == 200 else []):
            d = json.loads(line)
            if d.get("event") == "start":
                meta.update(model=d.get("model"), start=d.get("ts"))
            elif d.get("event") == "end":
                meta["end"] = d.get("ts")
            else:
                rows.append(d)
        df = pd.DataFrame(rows)
        status = "✅ 완료" if meta.get("end") else (
            "🟢 학습 중" if len(df) and time.time() - df["ts"].max() < 300 else "⚠️ 지연")
        c1, c2, c3 = st.columns(3)
        c1.metric("상태", status)
        c2.metric("모델", (meta.get("model") or "?").split("/")[-1][:24])
        if len(df):
            c3.metric("train loss", f"{df['loss'].dropna().iloc[-1]:.4f}"
                      if "loss" in df and df["loss"].notna().any() else "-")
            fig = go.Figure()
            if "loss" in df:
                d = df[df["loss"].notna()]
                fig.add_trace(go.Scatter(x=d["step"], y=d["loss"], name="train"))
            if "eval_loss" in df and df["eval_loss"].notna().any():
                d = df[df["eval_loss"].notna()]
                fig.add_trace(go.Scatter(x=d["step"], y=d["eval_loss"], name="eval",
                                         line=dict(dash="dash")))
            fig.update_layout(height=360, xaxis_title="step", yaxis_title="loss")
            st.plotly_chart(fig, use_container_width=True)

# ═══════════════ 페이지 5: 인벤토리 ═══════════════
else:
    st.markdown("### 🗂️ 공유 데이터소스 인벤토리")
    st.caption("여러 연구소·여러 문서에서 공통으로 쓰이는 데이터 = 공동관리·협업 1순위")
    shared = load_json("shared_datasources.json") or []
    if shared:
        df = pd.DataFrame(shared)
        df["연구소"] = df["institutes"].apply(lambda L: " ".join(
            f"<span style='color:{INST_COLORS.get(c,'#999')}'>●</span>" for c in L))
        show = df.rename(columns={"name": "데이터소스", "avail": "접근성",
                                  "n_docs": "문서수", "n_inst": "연구소수"})
        st.write(show[["데이터소스", "접근성", "문서수", "연구소수", "연구소"]]
                 .to_html(escape=False, index=False), unsafe_allow_html=True)
    else:
        st.info("인벤토리 데이터가 없습니다.")

# ── 자동 갱신 ──
if auto:
    time.sleep(30)
    st.cache_data.clear()
    st.rerun()
