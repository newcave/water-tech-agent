"""
K-water연구원 Water Co-Scientist ─ R&D 데이터 에이전트 관제센터  (v2)

v2 변경점 (2026-07-13):
  - GUI 전면 재설계: K-water 기관 스타일 (딥블루/화이트, Noto Sans KR, 헤더 밴드)
  - 에이전트 함대(fleet)가 첫 화면 주인공 — 수집 에이전트들이 "돌아가는 이미지"
  - 파이프라인 플로우 시각화 (소스 → 수집 → 파싱 → 정규화 → DB → FT → 서비스)
  - FT 버전관리: ft_logs/index.json 기반 run 이력 누적 (끊겨도 기록 유지)
  - article_collector(기사) 슬롯 추가, 새 에이전트 추가는 AGENT_META 한 줄
  - 모든 로딩 try/except + 빈 데이터 대비 (정직한 표기 원칙: 미가동 = 🟡/⚪)

데이터 소스(이중 모드):
  - 로컬: ./data_seed/*.json   - 클라우드: GitHub raw (repo data_seed/)
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

st.set_page_config(page_title="K-water Co-Scientist 관제센터", page_icon="💧",
                   layout="wide", initial_sidebar_state="expanded")

# ═══════════════════════ 설정 (확장 포인트) ═══════════════════════
GITHUB_REPO = "newcave/water-tech-agent"
LOCAL_SEED = Path("data_seed")
APP_VERSION = "v2.3 · 2026-07-13"

# 브랜드 팔레트 (K-water 계열 딥블루)
NAVY, BLUE, CYAN, BG = "#0A3D74", "#0B5FAE", "#1FA8C9", "#F4F7FB"
GREEN, AMBER, RED, GRAY = "#16A34A", "#D97706", "#DC2626", "#94A3B8"

INST_COLORS = {"INST-01": "#7C3AED", "INST-02": "#0284C7", "INST-03": "#059669",
               "INST-04": "#D97706", "INST-05": "#DC2626", "INST-06": "#4F46E5",
               "INST-07": "#DB2777"}

# ── 에이전트 레지스트리: 새 에이전트 추가 = 여기 한 줄 + data_seed/agents/<id>.json ──
AGENT_META = {
    "alio_crawler":       dict(icon="📥", ko="ALIO 수집",   role="공공보고서 크롤링",       grp="수집"),
    "openalex_collector": dict(icon="📄", ko="논문 수집",   role="OpenAlex 논문·트렌드",    grp="수집"),
    "kipris_collector":   dict(icon="📜", ko="특허 수집",   role="KIPRIS 특허 검색",        grp="수집"),
    "article_collector":  dict(icon="📰", ko="기사 수집",   role="인터넷 아티클 (설계 예정)", grp="수집"),
    "alio_parser":        dict(icon="🧠", ko="파싱·추출",   role="데이터소스 추출 (4단계)",  grp="처리"),
    "normalizer":         dict(icon="🧩", ko="정규화",      role="레지스트리·인벤토리 (5단계)", grp="처리"),
    "ft_trainer":         dict(icon="🔥", ko="FT 학습",     role="QLoRA 파인튜닝 (코랩)",   grp="학습"),
}
STATE_LABEL = {"run": ("가동 중", GREEN), "idle": ("정상 대기", GREEN),
               "standby": ("준비/예정", AMBER), "plan": ("설계", GRAY), "error": ("오류", RED)}

# ═══════════════════════ 스타일 ═══════════════════════
st.markdown("""<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;700;900&display=swap');
html, body, [class*="st-"], [class*="css"] {font-family:'Noto Sans KR','Malgun Gothic',sans-serif;}
.stApp {background:#F3F7FC;}
[data-testid="stSidebar"] {background:linear-gradient(180deg,#17549A 0%,#3E8ED0 100%);}
[data-testid="stSidebar"] * {color:#fff !important;}
[data-testid="stSidebar"] label[data-baseweb="radio"] {background:rgba(255,255,255,.13);
  border:1px solid rgba(255,255,255,.28); border-radius:12px; padding:9px 12px;
  margin-bottom:7px; width:100%;}
[data-testid="stSidebar"] label[data-baseweb="radio"]:has(input:checked)
  {background:rgba(255,255,255,.30); font-weight:700;}
[data-testid="stSidebar"] hr {border-color:rgba(255,255,255,.3);}
.block-container {padding-top:1.1rem; max-width:1500px;}

/* 헤더 밴드 */
.hdr {background:linear-gradient(100deg,#0F3A73 0%,#17549A 55%,#2E77C6 100%);
      border-radius:16px; padding:20px 26px; color:#fff; margin-bottom:16px;
      box-shadow:0 6px 18px rgba(15,58,115,.25);}
.hdr .org {font-size:.8rem; letter-spacing:.14em; opacity:.85; font-weight:500;}
.hdr .ttl {font-size:1.5rem; font-weight:900; margin-top:2px;}
.hdr .sub {font-size:.85rem; opacity:.85; margin-top:4px;}
.hdr .badge {display:inline-block; background:rgba(255,255,255,.16); border:1px solid rgba(255,255,255,.35);
      border-radius:999px; padding:3px 12px; font-size:.78rem; margin-left:6px; font-weight:500;}

/* KPI 카드 */
.kpis {display:flex; gap:12px; flex-wrap:wrap; margin-bottom:4px;}
.kpi {flex:1 1 150px; background:#fff; border:1px solid #E8EBF8; border-radius:14px;
      padding:14px 16px; box-shadow:0 3px 8px rgba(15,58,115,.08); border-left:6px solid #17549A;}
.kpi .k-lab {font-size:.78rem; color:#64748B; font-weight:500;}
.kpi .k-val {font-size:1.7rem; font-weight:900; color:#17427C; line-height:1.2;}
.kpi .k-sub {font-size:.74rem; color:#94A3B8; margin-top:2px;}

/* 파이프라인 플로우 */
.flow {display:flex; align-items:stretch; gap:0; overflow-x:auto; padding:4px 0 8px;}
.stage {background:#fff; border:1px solid #E3EAF3; border-radius:12px; padding:10px 14px;
        min-width:128px; text-align:center; box-shadow:0 2px 5px rgba(15,40,80,.05);}
.stage .s-t {font-size:.8rem; font-weight:700; color:#17427C;}
.stage .s-v {font-size:.95rem; font-weight:900; color:#2E77C6; margin-top:2px;}
.stage .s-s {font-size:.7rem; color:#94A3B8;}
.arr {align-self:center; color:#9DB6D4; font-weight:900; padding:0 7px; font-size:1.05rem;}

/* 에이전트 카드 그리드 */
.fleet {display:grid; grid-template-columns:repeat(auto-fill,minmax(300px,1fr)); gap:12px;}
.agent {background:#fff; border:1px solid #E3EAF3; border-left:5px solid #0B5FAE;
        border-radius:14px; padding:14px 16px; box-shadow:0 2px 6px rgba(15,40,80,.05);}
.agent .a-top {display:flex; justify-content:space-between; align-items:center;}
.agent .a-name {font-weight:800; font-size:.98rem; color:#0F2744;}
.agent .a-id {font-size:.72rem; color:#94A3B8; font-family:ui-monospace,Consolas,monospace;}
.agent .a-role {font-size:.8rem; color:#64748B; margin-top:3px;}
.agent .a-cnt {font-size:.84rem; color:#0F2744; margin-top:7px;}
.agent .a-next {font-size:.73rem; color:#94A3B8; margin-top:5px;}
.pill {display:inline-flex; align-items:center; gap:5px; border-radius:999px;
       padding:2px 10px; font-size:.73rem; font-weight:700;}
.pulse {display:inline-block; width:8px; height:8px; border-radius:50%;}
.pulse.on {animation:pulse 1.6s infinite;}
@keyframes pulse {0%{box-shadow:0 0 0 0 rgba(22,163,74,.5)} 70%{box-shadow:0 0 0 9px rgba(22,163,74,0)} 100%{box-shadow:0 0 0 0 rgba(22,163,74,0)}}

/* 활동 피드 (운영 콘솔) */
.feed {font-family:ui-monospace,Consolas,monospace; font-size:.8rem; line-height:1.6;
       background:#0F2744; color:#D9E8F7; border-radius:14px; padding:14px 16px;
       max-height:400px; overflow-y:auto; box-shadow:inset 0 0 0 1px rgba(255,255,255,.06);}
.feed .t {color:#5B7A9D;}
.feed .a {color:#7FD1E8; font-weight:700;}

.sect {font-size:1.02rem; font-weight:800; color:#17427C; margin:6px 0 8px;}
.note {color:#94A3B8; font-size:.78rem;}
.card {background:#fff; border:1px solid #E3EAF3; border-radius:14px; padding:14px 16px;
       box-shadow:0 2px 6px rgba(15,40,80,.05);}
.livedot {display:inline-block; width:8px; height:8px; border-radius:50%;
  background:#3DDC84; animation:pulse 1.6s infinite; margin:0 4px 1px 2px;}
.gchip {font-size:.66rem; background:#EAF1FA; color:#17549A; border-radius:6px;
  padding:1px 7px; margin-left:6px; font-weight:700; vertical-align:middle;}
.ftr {text-align:center; color:#94A3B8; font-size:.75rem; margin-top:22px;}
</style>""", unsafe_allow_html=True)

PLOTLY_LAYOUT = dict(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="#FFFFFF",
                     font=dict(family="Noto Sans KR", color="#0F2744"),
                     margin=dict(t=14, b=10, l=10, r=10))


# ═══════════════════════ 데이터 로딩 (로컬 → 깃헙 raw) ═══════════════════════
def _raw(path: str) -> str:
    return f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/{path}"


@st.cache_data(ttl=30, show_spinner=False)
def load_json(rel_path: str):
    """data_seed/<rel_path> — 로컬 우선, 실패 시 GitHub raw. 항상 예외 안전."""
    try:
        p = LOCAL_SEED / rel_path
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    try:
        r = requests.get(_raw(f"data_seed/{rel_path}"), timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


@st.cache_data(ttl=25, show_spinner=False)
def load_live(rel_path: str):
    """`data` 브랜치 live/ — 수집 에이전트가 분 단위 push (main 무커밋 → 앱 재부팅 없음)."""
    try:
        r = requests.get(
            f"https://raw.githubusercontent.com/{GITHUB_REPO}/data/live/{rel_path}",
            params={"t": int(time.time() // 20)}, timeout=8)   # raw CDN 캐시 무력화
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


@st.cache_data(ttl=25, show_spinner=False)
def load_agents() -> dict:
    out = {}
    for name in AGENT_META:                       # 레지스트리 순서
        d = load_live(f"agents/{name}.json") or load_json(f"agents/{name}.json")
        if d:
            out[name] = d
    try:                                          # 로컬에 미등록 에이전트가 있으면 자동 발견
        for f in sorted((LOCAL_SEED / "agents").glob("*.json")):
            if f.stem not in out:
                out[f.stem] = json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        pass
    return out


@st.cache_data(ttl=25, show_spinner=False)
def load_ft_index() -> list:
    """run 이력: ① ft_logs/index.json(raw, 노트북 v3가 유지) → ② API 폴더목록 → ③ 로컬"""
    try:
        r = requests.get(_raw("ft_logs/index.json"), timeout=8)
        if r.status_code == 200:
            runs = r.json().get("runs", [])
            if runs:
                return sorted(runs, key=lambda x: x.get("started", 0), reverse=True)
    except Exception:
        pass
    try:
        r = requests.get(f"https://api.github.com/repos/{GITHUB_REPO}/contents/ft_logs", timeout=8)
        if r.status_code == 200:
            return [{"id": x["name"]} for x in sorted(r.json(), key=lambda x: x["name"], reverse=True)
                    if x["type"] == "dir"]
    except Exception:
        pass
    try:
        return [{"id": p.name} for p in sorted(Path("ft_logs").iterdir(), reverse=True) if p.is_dir()]
    except Exception:
        return []


@st.cache_data(ttl=25, show_spinner=False)
def load_metrics(run_id: str):
    """run 하나의 metrics.jsonl 파싱 → (rows_df, meta). 끊김(resume) 이벤트 포함."""
    text = None
    try:
        p = Path("ft_logs") / run_id / "metrics.jsonl"
        if p.exists():
            text = p.read_text(encoding="utf-8")
    except Exception:
        pass
    if text is None:
        try:
            r = requests.get(_raw(f"ft_logs/{run_id}/metrics.jsonl"), timeout=10)
            text = r.text if r.status_code == 200 else ""
        except Exception:
            text = ""
    rows, meta = [], {"resumes": 0}
    for line in text.splitlines():
        try:
            d = json.loads(line)
        except Exception:
            continue
        ev = d.get("event")
        if ev == "start":
            meta.update(model=d.get("model"), start=d.get("ts"), gpu=d.get("gpu"))
        elif ev == "end":
            meta["end"] = d.get("ts")
        elif ev == "resume":
            meta["resumes"] += 1
        elif "step" in d:
            rows.append(d)
    return pd.DataFrame(rows), meta


def ago(ts):
    if not ts:
        return "-"
    s = int(time.time() - ts)
    if s < 0:
        return "방금"
    if s < 90: return f"{s}초 전"
    if s < 5400: return f"{s // 60}분 전"
    if s < 172800: return f"{s // 3600}시간 전"
    return f"{s // 86400}일 전"


def state_of(a: dict) -> str:
    s = a.get("state", "standby")
    try:
        if a.get("events") and time.time() - a["events"][-1].get("ts", 0) < 600:
            return "run"
    except Exception:
        pass
    return s if s in STATE_LABEL else "standby"


def run_status(df, meta):
    if meta.get("end"):
        return "✅ 완료", GREEN
    if len(df) and time.time() - df["ts"].max() < 300:
        return "🟢 학습 중", GREEN
    if len(df):
        return "⚠️ 끊김 (재개 가능)", AMBER
    return "⚪ 대기", GRAY


# ═══════════════════════ 공통 데이터 ═══════════════════════
summary = load_json("summary.json") or {"totals": {}, "inst_docs": {}, "inst_names": {}}
agents = load_agents()
T = summary.get("totals", {})
live_oa = load_live("openalex/stats.json")               # 논문 실수집 현황 (data 브랜치)
if live_oa:
    T["papers"] = live_oa.get("collected_total", T.get("papers", 0))
ft_index = load_ft_index()

# ft_trainer 카드에 최신 run 라이브 주입 (FT는 계속된다 — 항목 7)
if ft_index:
    latest = ft_index[0]
    df0, meta0 = load_metrics(latest["id"])
    stat0, _ = run_status(df0, meta0)
    ft = agents.setdefault("ft_trainer", {})
    ft["summary"] = f"최신 {latest['id']} · {stat0}" + (
        f" · loss {df0['loss'].dropna().iloc[-1]:.3f}" if len(df0) and df0.get("loss") is not None
        and df0["loss"].notna().any() else "")
    if stat0.startswith("🟢"):
        ft["state"] = "run"
        ft["last_run"] = int(df0["ts"].max())

n_run = sum(1 for a in agents.values() if state_of(a) == "run")
n_idle = sum(1 for a in agents.values() if state_of(a) == "idle")
n_wait = len(agents) - n_run - n_idle


def next_heartbeat_kst() -> str:
    """GitHub Actions cron(17 */6 UTC) 기준 다음 심박 시각(KST)."""
    u = dt.datetime.now(dt.timezone.utc)
    cand = u.replace(minute=17, second=0, microsecond=0, hour=(u.hour // 6) * 6)
    if cand <= u:
        cand += dt.timedelta(hours=6)
    return (cand + dt.timedelta(hours=9)).strftime("%H:%M")

last_hb = max([a.get("last_run") or 0 for a in agents.values()] + [0])

# ═══════════════════════ 사이드바 ═══════════════════════
with st.sidebar:
    st.markdown(f"### 💧 Water Co-Scientist")
    st.caption("K-water연구원 · R&D 데이터 에이전트 플랫폼")
    page = st.radio("메뉴", ["🛰️ 관제센터", "📚 수집 현황", "🏢 7개 연구소",
                            "🔥 FT 모니터", "🗂️ 인벤토리"], label_visibility="collapsed")
    st.divider()
    auto = st.toggle("실시간 갱신 (30초)", value=True)
    st.caption(f"데이터 기준: {ago(summary.get('generated_at'))}")
    st.caption(APP_VERSION)

# ═══════════════════════ 헤더 밴드 (공통) ═══════════════════════
st.markdown(f"""<div class="hdr">
  <div class="org">K-WATER INSTITUTE &nbsp;·&nbsp; KIWE R&amp;D DATA PLATFORM</div>
  <div class="ttl">💧 Water Co-Scientist 에이전트 관제센터</div>
  <div class="sub">7개 연구소 (경영·수자원환경·상하수도·물인프라안전·물에너지·수자원위성·AI) —
    수집·파싱·정규화·학습 에이전트 실시간 현황
    <span class="badge">🟢 가동 {n_run}</span>
    <span class="badge">🟡 대기·예정 {n_wait}</span>
    <span class="badge">에이전트 {len(agents)}</span>
    <span class="badge"><span class="livedot"></span>LIVE · 30초 갱신</span>
    <span class="badge">💓 최근 심박 {ago(last_hb)}</span>
    <span class="badge">⏱️ 다음 자율심박 ~{next_heartbeat_kst()} KST</span>
  </div></div>""", unsafe_allow_html=True)

# ═══════════════ 페이지 1: 관제센터 ═══════════════
if page == "🛰️ 관제센터":
    kpis = [
        ("ALIO 보고서", f"{T.get('alio_collected', 0)}건",
         f"파싱 {T.get('alio_parsed_ok', 0)} · 오류 {T.get('alio_errors', 0)}"),
        ("데이터소스 mention", f"{T.get('mentions', 0):,}건", "페이지 근거 100%"),
        ("고유 데이터소스", f"{T.get('unique_datasources', 0):,}개", "canonical 정규화"),
        ("논문 OpenAlex", f"{T.get('papers', 0):,}건",
         f"실수집 {live_oa.get('collected_total', 0):,}/{live_oa.get('target_total', 0):,}"
         if live_oa else "수집 대기"),
        ("특허 KIPRIS", f"{T.get('patents', 0)}건", "키 승인 대기"),
        ("기사·아티클", f"{T.get('articles', 0)}건", "파이프라인 설계"),
    ]
    ACC = ["#17549A", "#2E77C6", "#3B82F6", "#C0392B", "#1E8449", "#0EA5E9"]
    st.markdown('<div class="kpis">' + "".join(
        f'<div class="kpi" style="border-left-color:{ACC[i % len(ACC)]}">'
        f'<div class="k-val">{v}</div><div class="k-lab">{k}</div>'
        f'<div class="k-sub">{s}</div></div>' for i, (k, v, s) in enumerate(kpis)) + "</div>",
        unsafe_allow_html=True)

    # 파이프라인 플로우 — "에이전트가 돌아가는 이미지"
    st.markdown('<div class="sect">데이터 파이프라인</div>', unsafe_allow_html=True)
    stages = [
        ("📡 소스", "ALIO·논문·특허·기사", "공공/학술/IP/웹"),
        ("📥 수집 에이전트", f"{T.get('alio_collected', 0) + T.get('papers', 0) + T.get('patents', 0) + T.get('articles', 0):,}건",
         "crawler·collector ×4"),
        ("🧠 파싱·추출", f"{T.get('mentions', 0):,} mention", "gpt-4o → FT모델 교체 예정"),
        ("🧩 정규화", f"{T.get('unique_datasources', 0):,} 소스", "registry·canonical"),
        ("🗄️ 통합 DB", "PostgreSQL", "star schema · 협업 edge"),
        ("🔥 FT 학습", f"run {len(ft_index)}회", "KONI/Qwen QLoRA"),
        ("🤝 Co-Scientist", "서비스", "보고·분석·질의응답"),
    ]
    flow = "".join(
        f'<div class="stage"><div class="s-t">{t}</div><div class="s-v">{v}</div>'
        f'<div class="s-s">{s}</div></div>' + ('<div class="arr">›</div>' if i < len(stages) - 1 else "")
        for i, (t, v, s) in enumerate(stages))
    st.markdown(f'<div class="flow">{flow}</div>', unsafe_allow_html=True)

    st.markdown("")
    left, right = st.columns([1.35, 1])

    with left:
        st.markdown('<div class="sect">에이전트 함대</div>', unsafe_allow_html=True)
        cards = ""
        for name, a in agents.items():
            meta = AGENT_META.get(name, dict(icon="🤖", ko=name, role="", grp="기타"))
            s = state_of(a)
            label, color = STATE_LABEL[s]
            on = "on" if s == "run" else ""
            counts = " · ".join(f"{k} <b>{v:,}</b>" for k, v in (a.get("counts") or {}).items()) or "&nbsp;"
            nxt = f"다음: {a['next_run']}" if a.get("next_run") else ""
            cards += f"""<div class="agent" style="border-left-color:{color}">
              <div class="a-top">
                <span class="a-name">{meta['icon']} {meta['ko']} <span class="a-id">{name}</span><span class="gchip">{meta.get('grp','')}</span></span>
                <span class="pill" style="background:{color}1A;color:{color}">
                  <span class="pulse {on}" style="background:{color}"></span>{label}</span>
              </div>
              <div class="a-role">{a.get('summary') or meta['role']}</div>
              <div class="a-cnt">{counts}</div>
              <div class="a-next">심박 {ago(a.get('last_run'))} &nbsp; {nxt}</div>
            </div>"""
        st.markdown(f'<div class="fleet">{cards or "에이전트 데이터 없음"}</div>', unsafe_allow_html=True)
        st.markdown('<div class="note" style="margin-top:6px">미가동 에이전트는 🟡 대기로 정직하게 표기됩니다 '
                    '(연출 없음). 새 에이전트 추가: AGENT_META + data_seed/agents/&lt;id&gt;.json</div>',
                    unsafe_allow_html=True)

    with right:
        st.markdown('<div class="sect">활동 피드 <span class="livedot"></span>'
                    '<span style="font-size:.72rem;color:#1E8449;font-weight:800">LIVE</span></div>',
                    unsafe_allow_html=True)
        events = []
        for name, a in agents.items():
            for e in (a.get("events") or []):
                events.append((e.get("ts", 0), name, e.get("msg", "")))
        events.sort(reverse=True)
        rows = "".join(
            f'<div{" style=\"background:rgba(127,209,232,.14);border-radius:6px;padding:1px 5px\"" if i == 0 else ""}>'
            f'<span class="t">[{dt.datetime.fromtimestamp(ts).strftime("%m-%d %H:%M")}]</span> '
            f'<span class="a">{AGENT_META.get(n, {}).get("icon", "")} {n}</span> ▸ {m}</div>'
            for i, (ts, n, m) in enumerate(events[:50]))
        st.markdown(f'<div class="feed">{rows or "이벤트 없음"}</div>', unsafe_allow_html=True)
        st.markdown('<div class="note" style="margin-top:6px">에이전트가 report() 한 줄로 status를 '
                    'push하면 이 콘솔에 실시간으로 흐릅니다.</div>', unsafe_allow_html=True)

# ═══════════════ 페이지 2: 수집 현황 ═══════════════
elif page == "📚 수집 현황":
    st.markdown('<div class="sect">소스별 수집 현황</div>', unsafe_allow_html=True)
    rows = [
        ("📥 보고서① ALIO 공공보고서", T.get("alio_collected", 0), 121, "🟢 완료 (오류 16건 재처리 대기)"),
        ("📄 논문 OpenAlex — 7개 연구소 키워드×물", T.get("papers", 0),
         (live_oa.get("target_total") if live_oa and live_oa.get("target_total") else 3000),
         ("🟢 누적 수집 중 — 1분당 100편" if live_oa and T.get("papers", 0) < live_oa.get("target_total", 0)
          else "✅ 1차 수집 완료") if live_oa else "🟡 수집기 배치 · search_topics.json 준비"),
        ("📜 특허 KIPRIS — 연구소 키워드×물", T.get("patents", 0), 500, "🟡 서비스키 승인 대기"),
        ("📰 기사·인터넷 아티클", T.get("articles", 0), 1000, "⚪ 파이프라인 설계 (추후 추가)"),
        ("📑 보고서② 기타(PRISM 등)", 0, 500, "⚪ 설계"),
        ("🔒 내부자료", 0, 0, "별도 트랙 (사내망 DB)"),
    ]
    for name, cur, target, status in rows:
        col1, col2 = st.columns([3, 1.2])
        with col1:
            st.markdown(f"**{name}** &nbsp;<span class='note'>{cur:,} / 목표 {target:,}</span>",
                        unsafe_allow_html=True)
            st.progress(min(cur / target, 1.0) if target else 0.0)
        col2.markdown(status)

    st.divider()
    st.markdown('<div class="sect">ALIO 트랙 파이프라인 단계</div>', unsafe_allow_html=True)
    steps = [("1 크롤링", T.get("alio_collected", 0), 121), ("2 메타추출", 121, 121),
             ("3 기술분류", 121, 121), ("4 데이터소스 추출", T.get("alio_parsed_ok", 0), 121),
             ("5 정규화", T.get("alio_parsed_ok", 0), 121)]
    cols = st.columns(len(steps))
    for col, (nm, cur, tot) in zip(cols, steps):
        pct = cur / tot * 100 if tot else 0
        col.metric(nm, f"{cur}/{tot}", f"{pct:.0f}%")
    st.caption("논문·특허 파이프라인은 동일 5단계 구조로 편입 예정 — 수집기 코드 입고 시 즉시 연결.")

# ═══════════════ 페이지 3: 7개 연구소 ═══════════════
elif page == "🏢 7개 연구소":
    st.markdown('<div class="sect">K-water연구원 7개 연구소 현황</div>', unsafe_allow_html=True)
    st.caption("연구소 배정은 rule 기반 추정(키워드) — LLM 분류·검수로 정확도 향상 예정")
    inst_docs = summary.get("inst_docs", {})
    inst_names = summary.get("inst_names", {})
    inst_top = summary.get("inst_top_ds", {})

    if not inst_names:
        st.info("연구소 데이터가 아직 없습니다 (summary.json 확인).")
    else:
        cols = st.columns(len(inst_names))
        for col, code in zip(cols, sorted(inst_names)):
            with col:
                st.markdown(f"<div class='card' style='text-align:center;padding:10px 6px'>"
                            f"<div style='width:12px;height:12px;border-radius:50%;"
                            f"background:{INST_COLORS.get(code, GRAY)};margin:0 auto 4px'></div>"
                            f"<b style='font-size:.82rem'>{inst_names[code]}</b><br>"
                            f"<span style='font-size:1.5rem;font-weight:900;color:{NAVY}'>"
                            f"{inst_docs.get(code, 0)}</span><span class='note'> 건</span></div>",
                            unsafe_allow_html=True)

        st.markdown("")
        a, b = st.columns(2)
        codes = sorted(inst_names)
        with a:
            st.markdown('<div class="sect">연구소별 문서 수</div>', unsafe_allow_html=True)
            fig = go.Figure(go.Bar(
                x=[inst_docs.get(k, 0) for k in codes], y=[inst_names[k] for k in codes],
                orientation="h", marker_color=[INST_COLORS.get(k, GRAY) for k in codes]))
            fig.update_layout(height=310, **PLOTLY_LAYOUT)
            st.plotly_chart(fig, width="stretch")
        with b:
            st.markdown('<div class="sect">연구소 간 협업 강도 (공유 데이터소스)</div>', unsafe_allow_html=True)
            edges = load_json("edges.json") or []
            mat = pd.DataFrame(0, index=codes, columns=codes)
            for e in edges:
                try:
                    mat.loc[e["src"], e["dst"]] = e["w"]
                    mat.loc[e["dst"], e["src"]] = e["w"]
                except Exception:
                    continue
            fig = go.Figure(go.Heatmap(z=mat.values,
                                       x=[inst_names[c] for c in codes],
                                       y=[inst_names[c] for c in codes],
                                       colorscale="Blues", showscale=False,
                                       text=mat.values, texttemplate="%{text}"))
            fig.update_layout(height=310, **PLOTLY_LAYOUT)
            st.plotly_chart(fig, width="stretch")

        st.markdown('<div class="sect">연구소별 핵심 데이터소스 Top 5</div>', unsafe_allow_html=True)
        sel = st.selectbox("연구소", codes, format_func=lambda c: f"{c} {inst_names[c]}")
        top = inst_top.get(sel, [])
        if top:
            st.dataframe(pd.DataFrame(top).rename(
                columns={"cid": "canonical", "name": "데이터소스", "n": "mention"}),
                hide_index=True, width="stretch")
        else:
            st.info("해당 연구소로 분류된 문서가 아직 적습니다.")

# ═══════════════ 페이지 4: FT 모니터 ═══════════════
elif page == "🔥 FT 모니터":
    st.markdown('<div class="sect">파인튜닝 학습 모니터 · run 버전 이력</div>', unsafe_allow_html=True)
    if not ft_index:
        st.info("아직 학습 run이 없습니다. 코랩에서 colab_train_kwater_v3.ipynb 실행 시 "
                "ft_logs/에 기록되어 여기 누적됩니다.")
        st.markdown("- 모델 후보: **KONI-Llama3-8B** (KISTI 한국어 과학기술) / Qwen2.5-7B\n"
                    "- 학습데이터: 4단계 추출 쌍 (GPT-4o distillation)\n"
                    "- 목표: 필드 F1 ≥ 90% → 로컬 vLLM 전환 (OpenAI 의존 제거)")
    else:
        # run 이력 테이블 (누적 버전 관리 — 끊긴 run도 기록 유지)
        hist = []
        for r in ft_index[:20]:
            rid = r["id"]
            dfh, mh = (pd.DataFrame(), {})
            if {"status", "final_loss"} <= set(r):        # index.json에 요약이 있으면 그대로
                stt = r.get("status", "-")
                if stt.startswith("🟢") and time.time() - r.get("last_ts", 0) > 300:
                    stt = "⚠️ 끊김 (재개 가능)"               # 심박 5분 끊기면 정직 표기
                hist.append(dict(run=rid, 상태=stt,
                                 모델=(r.get("model") or "-").split("/")[-1][:26],
                                 GPU=r.get("gpu", "-"), 스텝=r.get("steps", "-"),
                                 final_loss=r.get("final_loss", "-"),
                                 시작=dt.datetime.fromtimestamp(r["started"]).strftime("%m-%d %H:%M")
                                 if r.get("started") else "-"))
            else:                                          # 폴백: metrics 직접 파싱
                dfh, mh = load_metrics(rid)
                s, _ = run_status(dfh, mh)
                hist.append(dict(run=rid, 상태=s,
                                 모델=(mh.get("model") or "-").split("/")[-1][:26],
                                 GPU=mh.get("gpu", "-"),
                                 스텝=int(dfh["step"].max()) if len(dfh) else 0,
                                 final_loss=round(float(dfh["loss"].dropna().iloc[-1]), 4)
                                 if len(dfh) and "loss" in dfh and dfh["loss"].notna().any() else "-",
                                 시작=dt.datetime.fromtimestamp(mh["start"]).strftime("%m-%d %H:%M")
                                 if mh.get("start") else "-"))
        st.dataframe(pd.DataFrame(hist), hide_index=True, width="stretch")

        run_id = st.selectbox("상세 보기", [r["id"] for r in ft_index])
        df, meta = load_metrics(run_id)
        status, _ = run_status(df, meta)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("상태", status)
        c2.metric("모델", (meta.get("model") or "?").split("/")[-1][:22])
        c3.metric("train loss", f"{df['loss'].dropna().iloc[-1]:.4f}"
                  if len(df) and "loss" in df and df["loss"].notna().any() else "-")
        c4.metric("재개(resume)", f"{meta.get('resumes', 0)}회",
                  "끊겨도 이어서 기록" if meta.get("resumes") else None, delta_color="off")

        if len(df):
            fig = go.Figure()
            if "loss" in df:
                d = df[df["loss"].notna()]
                fig.add_trace(go.Scatter(x=d["step"], y=d["loss"], name="train",
                                         line=dict(color=BLUE, width=2.5)))
            if "eval_loss" in df and df["eval_loss"].notna().any():
                d = df[df["eval_loss"].notna()]
                fig.add_trace(go.Scatter(x=d["step"], y=d["eval_loss"], name="eval",
                                         line=dict(color=CYAN, width=2, dash="dash")))
            fig.update_layout(height=380, xaxis_title="step", yaxis_title="loss", **PLOTLY_LAYOUT)
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("이 run의 지표가 아직 없습니다.")

# ═══════════════ 페이지 5: 인벤토리 ═══════════════
else:
    st.markdown('<div class="sect">공유 데이터소스 인벤토리</div>', unsafe_allow_html=True)
    st.caption("여러 연구소·여러 문서에서 공통으로 쓰이는 데이터 = 공동관리·협업 1순위")
    shared = load_json("shared_datasources.json") or []
    if shared:
        df = pd.DataFrame(shared)
        df["연구소"] = df["institutes"].apply(lambda L: " ".join(
            f"<span style='color:{INST_COLORS.get(c, GRAY)}'>●</span>" for c in (L or [])))
        show = df.rename(columns={"name": "데이터소스", "avail": "접근성",
                                  "n_docs": "문서수", "n_inst": "연구소수"})
        st.write(show[["데이터소스", "접근성", "문서수", "연구소수", "연구소"]]
                 .to_html(escape=False, index=False), unsafe_allow_html=True)
    else:
        st.info("인벤토리 데이터가 없습니다.")

st.markdown(f'<div class="ftr">K-water연구원 Water Co-Scientist · 데이터는 30초마다 갱신 · {APP_VERSION}</div>',
            unsafe_allow_html=True)

# ── 자동 갱신 ──
if auto:
    time.sleep(30)
    st.cache_data.clear()
    st.rerun()
