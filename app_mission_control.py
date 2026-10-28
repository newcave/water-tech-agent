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

import base64
import json
import math
import time
import datetime as dt
from collections import Counter
from pathlib import Path

import requests
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
import plotly.graph_objects as go
from plotly.subplots import make_subplots

import agent_flow as af
import data_cache as dcache   # (dc는 지식노트 화면에서 Counter 변수명으로 쓰여 피함)
import knowledge_notes as kn
import label_review_page as lrp
import oa_rising_page as oarp
import inst_trend as itr      # 연구소별 5년 추이 — 해외(OpenAlex) 실측 (v3.12)
import citation_page as citp   # 🏅 피인용 질 — 피인용 상위 10% 비중 (v3.16)
import kci_compare_page as kcip   # 🆚 K-water 비교(KCI) — 연구소 분야별 K-water vs 국내 학회지 (v3.17)
import asset_page as astp     # 🗄️ 지식자산 현황 — WCS 연구보고서·논문·특허 구성 (v3.14)


def _fresh_modules(*mods):
    """Streamlit Cloud가 git pull 뒤에도 예전 보조 모듈을 메모리에 쥐고 있는 일이 있어(2026-10-28 🏅 피인용 질 탭
    AttributeError — 새 citation_page가 예전 inst_trend를 봄), 처음 보는 모듈은 한 번, 그 뒤로는 파일이 바뀌면 다시 읽음.
    importlib.reload는 같은 모듈 객체를 고쳐 쓰므로 다른 모듈이 쥔 참조(citation_page의 itr 등)도 함께 새것이 됨."""
    import importlib
    import os
    for m in mods:
        try:
            mt = os.path.getmtime(m.__file__)
            if getattr(m, "_wca_mtime", None) is None or mt > m._wca_mtime:
                importlib.reload(m)
                m._wca_mtime = mt
        except Exception:
            pass


_fresh_modules(itr, citp, kcip, astp, oarp, kn, lrp, af)   # data_cache는 캐시를 쥐고 있어 제외 · 순서: 기반 모듈(itr) 먼저

st.set_page_config(page_title="K-water Co-Scientist 관제센터", page_icon="💧",
                   layout="wide", initial_sidebar_state="expanded")
st.session_state["_full_run_ts"] = time.time()      # 자동 새로고침 타이머가 '마지막 전체 그리기' 시각으로 씀

# ═══════════════════════ 설정 (확장 포인트) ═══════════════════════
GITHUB_REPO = "newcave/water-tech-agent"
LOCAL_SEED = Path("data_seed")
APP_VERSION = "v3.17 · 2026-10-28"   # 화면·기능 추가는 v3.N, 이름·순서·문구 같은 작은 수정은 v3.N.x
KN_PAGE = "📒 연구소 지식노트"
AC_PAGE = "🎯 수집 달성도"
HITL_PAGE = "K-water 문헌 적정성"            # HITL (전문가) 검토 — K-water 소속 논문 판정 게임 (사이드바 구분선 아래 별도 항목)
FLOW_PAGE = "🌊 에이전트 흐름"              # 보여 주기용 흐름 화면 (agent_flow.py) — 운영 화면은 관제센터 그대로
LR_PAGE = "연구소별 분류 적정성"             # HITL (전문가) 검토 — 연구소 라벨 OK·NG·이관 판정 (label_review_page.py)
LR1_PAGE = "라벨링 1차 샘플링"              # HITL (전문가) 검토 — 무작위 고정 60장, 판정자마다 따로·블라인드
ASSET_PAGE = "🗄️ 지식자산 현황"                 # WCS 연구보고서·논문·특허 구성 파이 (asset_page.py · data_seed/wcs_assets.json)
KCIKW_PAGE = "🆚 K-water 비교(KCI)"              # 최근 5년 KCI — 연구소 분야별 K-water 논문 vs 국내 학회지 (kci_compare_page.py · kci_inst.json)
CIT_PAGE = "🏅 피인용 질"                       # 연구소 관련 논문의 피인용 상위 10% 비중 (citation_page.py · openalex_trends.json *_top10)
OA_PAGE = "🔭 상승 연구주제"                  # openalex 상승 연구주제 분석 결과 연동 (oa_rising_page.py · data_seed/oa_rising/)
# Agent Flow 확인用 버튼 이름 (2026-10-26 사용자 지정 · 순서는 AGENT_FLOWS 순서)
WCS_FLOW_PAGE = "Co-Scientist 개념도"        # WCS(연구자료 검색) 흐름도 (flows/wcs_agent_flow.html)
RNDHELP_FLOW_PAGE = "수탁과제 관리 Tool"       # rndhelp 흐름도 (flows/rndhelp_agent_flow*.html)
HECRAS_FLOW_PAGE = "Surrogate 모델링"         # HECRAS-surrogate 흐름도 (flows/hecras_agent_flow*.html)
LORA_FLOW_PAGE = "AI연구소 자체 LLM"          # kwater-ailab-4b-lora 흐름도 (flows/lora4b_agent_flow*.html)
OPENALEX_FLOW_PAGE = "OpenAlex 연구트렌드"      # newcave/openalex 흐름도 (flows/openalex_agent_flow*.html)
# Agent Flow 확인用 화면: 버튼 이름 → (흐름도 파일, 제목, 설명, 도움말, 공개 메모). 새 흐름도는 flows/에 파일을 두고 여기 한 줄만 더한다
# 파일 자리에 {보기 이름: 파일}을 주면 화면 위에 보기 전환 버튼이 생긴다 (한 번에 하나만 보임). 사이드바 버튼 순서 = 이 표의 순서
AGENT_FLOWS = {
    WCS_FLOW_PAGE: ("flows/wcs_agent_flow.html", "Co-Scientist 개념도 — WCS 연구자료 검색의 에이전트 흐름",
                    "원천 자료 → 자료 준비 → 저장·모델 → 검색 창구 → AI 답변 → 화면 → 사람. 실제 코드 경로(WCS main 90edc2d, 2026-10-26)를 질문 유형별로 재생",
                    "WCS(K-water 연구자료 검색)의 에이전트 흐름 — 실제 코드 경로를 질문 유형별로 재생하는 구조도 (실시간 상태 아님)",
                    "hjhj(학준) 동의 후 공개 (2026-10-26)."),
    RNDHELP_FLOW_PAGE: ({"🌊 기본 보기": "flows/rndhelp_agent_flow.html", "🔬 전문가 보기": "flows/rndhelp_agent_flow_expert.html"},
                        "수탁과제 관리 Tool — RND-HELP(국가R&D 과제관리 도우미) 흐름",
                        "원천 자료 → 판정 엔진(룰·AI·점검·현물·편성·검색) → 결합 → 업무 화면 → 산출물 → 피드백 재학습. 실제 코드 경로(newcave/rndhelp main 9ebf611, 2026-10-23)를 업무별로 재생",
                        "RND-HELP(rndaid.streamlit.app)의 흐름 — 비목 매핑·정산 점검·현물·제안서·FAQ를 실제 코드 경로대로 재생하는 구조도 (실시간 상태 아님)",
                        "공개 저장소 newcave/rndhelp 기준 (자료는 가상 샘플)."),
    HECRAS_FLOW_PAGE: ({"🌊 기본 보기": "flows/hecras_agent_flow.html", "🔬 전문가 보기": "flows/hecras_agent_flow_expert.html"},
                       "Surrogate 모델링 — HEC-RAS Surrogate Studio(1D HEC-RAS × AI 방류 설계) 흐름",
                       "HEC-RAS 정답 → 자료 → 학습·검증 → 서로게이트 → 후보 탐색 → 방류 설계(P1·P2·P3) → HEC-RAS 1회 확인. 실제 코드 경로(newcave/HECRAS-surrogate main 30c0fc5, 2026-08-18)를 단계별로 재생",
                       "HEC-RAS Surrogate Studio의 흐름 — 학습·검증부터 P1·P2·P3 방류 설계까지 실제 코드 경로를 재생하는 구조도 (실시간 상태 아님)",
                       "공개 저장소 newcave/HECRAS-surrogate 기준."),
    LORA_FLOW_PAGE: ({"🌊 기본 보기": "flows/lora4b_agent_flow.html", "🔬 전문가 보기": "flows/lora4b_agent_flow_expert.html"},
                     "AI연구소 자체 LLM — kwater-ailab-4b-lora(첫 LoRA 언어모델 v0.1) 흐름",
                     "공개 연구보고서 105건 → 데이터소스 추출 → instruction 쌍 → Qwen3-4B + LoRA 학습 → 전/후 평가 → Hugging Face 공개 → 추론, 그리고 로드맵(v0.2~v1.x). 저장소(newcave/kwater-ailab-4b-lora main 46453b2, 2026-07-10) 기준으로 단계별 재생",
                     "kwater-ailab-4b-lora의 흐름 — 데이터 구축·LoRA 학습·배포·로드맵을 재생하는 구조도 (학습 코드는 저장소 밖이라 README 기준 단계는 점선, 실시간 상태 아님)",
                     "공개 저장소 newcave/kwater-ailab-4b-lora 기준 — 학습 단계는 README 기준(코드는 Colab)."),
    OPENALEX_FLOW_PAGE: ({"🌊 기본 보기": "flows/openalex_agent_flow.html", "🔬 전문가 보기": "flows/openalex_agent_flow_expert.html"},
                         "OpenAlex 연구트렌드 — 연구소별 떠오르는 연구주제(Rising 용어 → 커뮤니티) 흐름",
                         "분야별 저널 수집(OpenAlex) → 코퍼스·제목 용어 → Mann-Kendall + BH-FDR로 Rising 용어 → 동시출현 네트워크·Louvain 커뮤니티 → 근거문서·AI 해석 → Dash 대시보드·Streamlit 뷰어. 실제 코드 경로(newcave/openalex main b1a9f10, 2026-10-27)를 단계별로 재생",
                         "newcave/openalex의 흐름 — 수집·추세검정·커뮤니티·AI 해석·화면을 실제 코드 경로대로 재생하는 구조도 (실시간 상태 아님)",
                         "공개 저장소 newcave/openalex 기준 — 수집 원본·분석 결과는 비공개 리포(openalex-data)."),
}

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
    "oa_rising":          dict(icon="🔭", ko="상승 주제 연동", role="openalex 분석 결과 연동 (MK+FDR·Louvain)", grp="분석"),
    "ft_trainer":         dict(icon="🔥", ko="FT 학습",     role="QLoRA 파인튜닝 (코랩)",   grp="학습"),
}
STATE_LABEL = {"run": ("가동 중", GREEN), "idle": ("정상 대기", BLUE),
               "standby": ("준비/예정", AMBER), "plan": ("설계", GRAY), "error": ("오류", RED)}

# ═══════════════════════ 스타일 ═══════════════════════
st.markdown("""<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;700;900&display=swap');
html, body, [class*="st-"], [class*="css"] {font-family:'Noto Sans KR','Malgun Gothic',sans-serif;}
/* 아이콘 글꼴은 되돌림 — 위 글꼴 규칙이 아이콘까지 바꿔 'keyboard_double_arrow_right' 같은 이름이 글자로 보였음 (v3.7.4) */
[data-testid="stIconMaterial"], [class*="material-symbols"], .material-icons {font-family:'Material Symbols Rounded','Material Icons' !important;}
.stApp {background:#F3F7FC;}
[data-testid="stSidebar"] {background:linear-gradient(180deg,#17549A 0%,#3E8ED0 100%);}
[data-testid="stSidebar"] * {color:#fff !important;}
[data-testid="stSidebar"] label[data-baseweb="radio"] {background:rgba(255,255,255,.13);
  border:1px solid rgba(255,255,255,.28); border-radius:12px; padding:9px 12px;
  margin-bottom:7px; width:100%;}
[data-testid="stSidebar"] label[data-baseweb="radio"]:has(input:checked)
  {background:rgba(255,255,255,.30); font-weight:700;}
[data-testid="stSidebar"] hr {border-color:rgba(255,255,255,.3);}
.side-brand {margin:2px 0 16px; text-align:center; container-type:inline-size;}
.side-brand .sb-name {font-size:1.35rem; font-size:min(1.45rem, 12.5cqi); font-weight:900; letter-spacing:-.3px; line-height:1.3; white-space:nowrap;}
.side-brand .sb-sub {display:flex; justify-content:center; align-items:center; gap:6px; margin-top:4px;
  font-size:.92rem; font-size:min(.95rem, 7.5cqi); opacity:.9; line-height:1.4; white-space:nowrap;}
.side-brand .sb-mark {flex-shrink:0;}
.side-brand .sb-logo {background:#FFFFFF; border-radius:10px; padding:9px 12px; margin:0 auto; max-width:214px;
  box-shadow:0 1px 3px rgba(4,30,66,.25);}
.side-brand .sb-logo img {display:block; width:100%; height:auto;}
.side-brand .sb-logo + .sb-sub {margin-top:9px;}
.side-sep {display:flex; align-items:center; gap:8px; margin:6px 0 0; font-size:.72rem;
  letter-spacing:.12em; opacity:.85;}
.side-sep::before, .side-sep::after {content:""; flex:1; border-top:1px solid rgba(255,255,255,.45);}
/* 사이드바 단추(HITL 검토·Agent Flow): 폭은 모두 사이드바 너비로 같게, 높이·간격은 작게 (v3.7.2) */
[data-testid="stSidebar"] [data-testid="stElementContainer"]:has(.stButton) {width:100% !important; margin-bottom:-10px;}
[data-testid="stSidebar"] .stButton, [data-testid="stSidebar"] .stButton > div,
[data-testid="stSidebar"] .stButton [data-testid="stTooltipIcon"],
[data-testid="stSidebar"] .stButton [data-testid="stTooltipHoverTarget"] {width:100% !important;}
[data-testid="stSidebar"] .stButton button {width:100%; justify-content:flex-start; border-radius:9px;
  background:rgba(255,255,255,.13); border:1px dashed rgba(255,255,255,.55); color:#fff;
  padding:2px 10px !important; min-height:0 !important; height:auto !important;}
[data-testid="stSidebar"] .stButton button > div {justify-content:flex-start; width:100%;}
[data-testid="stSidebar"] .stButton button, [data-testid="stSidebar"] .stButton button * {
  font-size:.8rem !important; line-height:1.3 !important; white-space:nowrap;}
[data-testid="stSidebar"] .stButton button p {text-align:left; margin:0 !important; overflow:hidden; text-overflow:ellipsis;}
[data-testid="stSidebar"] .stButton button[kind="primary"] {background:rgba(255,255,255,.30); border-style:solid;
  font-weight:700;}
.block-container {padding-top:3.8rem; max-width:1500px;}   /* 위쪽 도구줄(60px)에 머리띠가 가리지 않게 (v3.7.4) */

/* 헤더 밴드 */
.hdr {background:linear-gradient(100deg,#0F3A73 0%,#17549A 55%,#2E77C6 100%);
      border-radius:16px; padding:20px 26px; color:#fff; margin-bottom:16px;
      box-shadow:0 6px 18px rgba(15,58,115,.25); box-sizing:border-box; max-width:100%; overflow-wrap:anywhere;}
.hdr .org {font-size:.8rem; letter-spacing:.14em; opacity:.85; font-weight:500;}
.hdr .ttl {font-size:1.5rem; font-weight:900; margin-top:2px;}
.hdr .sub {font-size:.85rem; opacity:.85; margin-top:4px;}
.hdr .badge {display:inline-block; background:rgba(255,255,255,.16); border:1px solid rgba(255,255,255,.35);
      border-radius:999px; padding:3px 12px; font-size:.78rem; margin-left:6px; font-weight:500;}

/* KPI 카드 */
.kpis {display:flex; gap:12px; flex-wrap:wrap; margin-bottom:4px;}
.kpi-grp {font-size:.8rem; font-weight:800; color:#17427C; margin:10px 0 6px; letter-spacing:.02em;}
.kpi {flex:1 1 150px; background:#fff; border:1px solid #E8EBF8; border-radius:14px;
      padding:14px 16px; box-shadow:0 3px 8px rgba(15,58,115,.08); border-left:6px solid #17549A;}
.kpi .k-lab {font-size:.78rem; color:#64748B; font-weight:500;}
.kpi .k-val {font-size:1.7rem; font-weight:900; color:#17427C; line-height:1.2;}
.kpi .k-sub {font-size:.74rem; color:#94A3B8; margin-top:2px;}
.lens-desc {display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:8px; margin:2px 0 10px;}   /* 보는 관점 설명 (v3.13.2) */
.lens-desc .ld {font-size:.74rem; line-height:1.4; color:#94A3B8; padding:6px 9px; border-radius:8px; border:1px solid transparent;}
.lens-desc .ld b {display:block; font-size:.78rem; color:#64748B; margin-bottom:1px;}
.lens-desc .ld.on {background:#EAF1FA; border-color:#C9DAF0; color:#475569;}
.lens-desc .ld.on b {color:#17427C;}
@media (max-width:900px) {.lens-desc {grid-template-columns:repeat(2,minmax(0,1fr));}}
.kpis.k7 {display:grid; grid-template-columns:repeat(auto-fit,minmax(128px,1fr)); gap:10px;}   /* 7개 연구소 한 줄 (v3.12) */
.kpis.k7 .kpi {padding:12px 12px; border-left-width:5px;}
.kpis.k7 .k-val {font-size:1.45rem;}
.kpis.k7 .k-lab {font-size:.74rem; letter-spacing:-.03em; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;}

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

@st.cache_data(ttl=300, show_spinner=False)
def load_labels(rel_path: str):
    """`data` 브랜치 labels/ — 분류·집계 결과 (도메인 트렌드용)."""
    try:
        r = requests.get(
            f"https://raw.githubusercontent.com/{GITHUB_REPO}/data/labels/{rel_path}",
            params={"t": int(time.time() // 300)}, timeout=8)     # 라벨은 6시간 주기 → 5분 단위면 충분
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None

@st.cache_data(ttl=300, show_spinner=False)
def load_labels_jsonl(rel_path: str):
    """`data` 브랜치 labels/ 의 JSONL → list[dict] (파이프라인 런로그 등)."""
    try:
        r = requests.get(
            f"https://raw.githubusercontent.com/{GITHUB_REPO}/data/labels/{rel_path}",
            params={"t": int(time.time() // 300)}, timeout=8)     # 라벨은 6시간 주기 → 5분 단위면 충분
        if r.status_code == 200:
            out = []
            for line in r.text.split("\n"):        # splitlines()는 제목 속 유니코드 줄바꿈(U+2028)까지 잘라 JSON을 깨뜨림
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except Exception:
                        pass
            return out
    except Exception:
        pass
    return []


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
    """에이전트 상태 — data 브랜치 live/agents/*.json 을 동시에 받고, 없으면 로컬 data_seed/agents."""
    out = {}
    names = list(AGENT_META)
    t = int(time.time() // 20)                     # raw CDN 캐시 무력화 (load_live와 같은 규칙)
    texts = dcache.fetch_many([f"https://raw.githubusercontent.com/{GITHUB_REPO}/data/live/agents/{n}.json?t={t}"
                           for n in names], timeout=8)
    for name, text in zip(names, texts):          # 레지스트리 순서
        d = None
        try:
            d = json.loads(text) if text else None
        except Exception:
            d = None
        d = d or load_json(f"agents/{name}.json")
        if d:
            out[name] = d
    try:                                          # 로컬에 미등록 에이전트가 있으면 자동 발견
        for f in sorted((LOCAL_SEED / "agents").glob("*.json")):
            if f.stem not in out:
                out[f.stem] = json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        pass
    return out


@st.cache_data(ttl=120, show_spinner=False)
def load_ft_index() -> list:
    """run 이력: ① ft_logs/index.json(raw, 노트북 v3가 유지) → ② 로컬 폴더(배포된 main과 같음) → ③ API 폴더목록.
    API는 비인증 시간당 60회 한도라 마지막에만 쓴다."""
    try:
        r = requests.get(_raw("ft_logs/index.json"), timeout=8)
        if r.status_code == 200:
            runs = r.json().get("runs", [])
            if runs:
                return sorted(runs, key=lambda x: x.get("started", 0), reverse=True)
    except Exception:
        pass
    try:
        local = [{"id": p.name} for p in sorted(Path("ft_logs").iterdir(), reverse=True) if p.is_dir()]
        if local:
            return local
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


@st.cache_data(ttl=300, show_spinner=False)
def load_papers(tag: str, history: bool = False) -> pd.DataFrame:
    """data 브랜치의 수집 논문 jsonl (선택 작업만 로드, 5분 캐시).
    history=True: 연구소 트랙에 labels 파이프라인이 모은 지난 연도(labels/openalex_extended)를 합침 — id 중복 제거, live 우선."""
    paths = [f"live/openalex/papers_{tag}.jsonl"] + ([f"labels/openalex_extended/papers_{tag}.jsonl"] if history else [])
    rows = {}
    for path in paths:
        try:
            r = requests.get(f"https://raw.githubusercontent.com/{GITHUB_REPO}/data/{path}",
                             params={"t": int(time.time() // 120)}, timeout=30)
            if r.status_code != 200:
                continue
            for line in r.text.split("\n"):        # splitlines()는 제목 속 U+2028에서 잘림
                if not line.strip():
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                rid = str(d.get("id") or "").rsplit("/", 1)[-1] or f"_{len(rows)}"
                rows.setdefault(rid, d)
        except Exception:
            continue
    return pd.DataFrame(list(rows.values()))


def load_data_jsonl(rel_path: str) -> list:
    """`data` 브랜치 JSONL → list[dict] (30분, 복사 없는 공용 캐시 — data_cache.py). 받은 목록은 고치지 말 것."""
    return dcache.data_jsonl(rel_path)


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
oa_idx = load_json("oa_rising/index.json") or {}                # openalex 상승 연구주제 연동 (agents/oa_rising.py)
oa_main = (oa_idx.get("sources") or [{}])[0]


def oa_population(years) -> int:
    """openalex 연동 코퍼스와 같은 연도 범위의 OpenAlex 모집단(수자원 12저널, 모든 유형) — openalex_lite 실측(openalex_trends.json)."""
    try:
        y0, y1 = int(years[0]), int(years[-1])
        js = (load_json("openalex_trends.json") or {}).get("journals", {})
        return sum(c for j in js.values() for y, c in (j.get("by_year") or {}).items() if y0 <= int(y) <= y1)
    except Exception:
        return 0


@st.cache_data(ttl=300, show_spinner=False)
def hitl_totals() -> dict:
    """연구소별 판정 대장 요약(data 브랜치 labels/hitl/<INST>/summary.json)을 합친 숫자 — 관제센터 KPI용."""
    insts = [f"INST-0{i}" for i in range(1, 8)]
    texts = dcache.fetch_many([f"https://raw.githubusercontent.com/{GITHUB_REPO}/data/labels/hitl/{i}/summary.json" for i in insts], timeout=8)
    out = {"records": 0, "papers": 0, "ok": 0, "ng": 0, "move": 0, "insts": 0, "reviewers": set()}
    for t in texts:
        try:
            d = json.loads(t) if t else None
        except Exception:
            d = None
        if not d:
            continue
        out["insts"] += 1
        out["records"] += d.get("judgments", d.get("records", 0)) or 0
        out["papers"] += d.get("papers_judged", 0) or 0
        for k in ("ok", "ng", "move"):
            out[k] += (d.get("final") or {}).get(k, 0) or 0
        out["reviewers"] |= set(d.get("by_reviewer") or {})
    out["reviewers"] = len(out["reviewers"])
    return out

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
    """GitHub Actions cron(17 */6 UTC) 기준 다음 수행 예정시간(KST)."""
    u = dt.datetime.now(dt.timezone.utc)
    cand = u.replace(minute=17, second=0, microsecond=0, hour=(u.hour // 6) * 6)
    if cand <= u:
        cand += dt.timedelta(hours=6)
    return (cand + dt.timedelta(hours=9)).strftime("%H:%M")

last_hb = max([a.get("last_run") or 0 for a in agents.values()] + [0])

@st.cache_resource(show_spinner=False)
def _logo_b64() -> str:
    """사이드바 기관 로고 (없으면 빈 문자열 → 글자로 대신)."""
    try:
        return base64.b64encode((Path(__file__).parent / "assets" / "kwater_institute_logo.png").read_bytes()).decode("ascii")
    except Exception:
        return ""


# ═══════════════════════ 사이드바 ═══════════════════════
with st.sidebar:
    # 사이드바 이름: 2단 워드마크 (머리띠에 'Water Co-Scientist 에이전트 관제센터'가 있어 짧게 · v3.10.1)
    # 기관 로고(assets/kwater_institute_logo.png, 흰 바탕 카드) / 작은 물벗 마크 + '물벗 : R&D 에이전트' (v3.10.6)
    #   로고 파일이 없으면 글자 'K-water연구원'으로 대신함. 더 선명한 원본(CI 가이드 PNG·SVG)을 같은 이름으로 넣으면 그대로 바뀜.
    _logo = _logo_b64()
    _top = (f'<div class="sb-logo"><img src="data:image/png;base64,{_logo}" alt="K-water 연구원"></div>' if _logo
            else '<div class="sb-name">K-water연구원</div>')
    st.markdown('<div class="side-brand">' + _top + '<div class="sb-sub">'
                '<svg class="sb-mark" width="17" height="20" viewBox="0 0 34 40" role="img" aria-label="물벗 로고">'
                '<path d="M17 2 C17 2 3 18 3 26 a14 14 0 0 0 28 0 C31 18 17 2 17 2Z" fill="#FFFFFF" fill-opacity=".95"/>'
                '<g stroke="#17549A" stroke-width="2.4" fill="#17549A"><line x1="11" y1="28" x2="17" y2="20"/>'
                '<line x1="17" y1="20" x2="23" y2="28"/><line x1="11" y1="28" x2="23" y2="28"/>'
                '<circle cx="11" cy="28" r="3"/><circle cx="17" cy="20" r="3"/><circle cx="23" cy="28" r="3"/></g></svg>'
                '<span>물벗 : R&amp;D 에이전트</span></div></div>', unsafe_allow_html=True)
    PAGES = ["🛰️ 관제센터", FLOW_PAGE, "📚 수집 현황", ASSET_PAGE, AC_PAGE, "📄 논문 트렌드", CIT_PAGE, "🇰🇷 KCI 트렌드", KCIKW_PAGE, OA_PAGE, "🏷️ 라벨링 로그", "🏢 7개 연구소",
             KN_PAGE, "🔥 FT 모니터", "🗂️ 인벤토리"]
    if "nav_start" not in st.session_state:          # ?inst=INST-0x 주소로 들어오면 지식노트부터 (세션당 1회만 결정)
        st.session_state["nav_start"] = PAGES.index(KN_PAGE) if st.query_params.get("inst") else 0

    def _to_main_menu():                              # 본 메뉴를 고르면 HITL 검토 화면에서 빠져나옴
        st.session_state["side_page"] = None

    def _to_side(name):                               # HITL 검토·Agent Flow 항목을 고르면 본 메뉴 선택을 비움
        st.session_state["side_page"] = name
        st.session_state["nav_radio"] = None

    nav_kw = {} if "nav_radio" in st.session_state else {"index": st.session_state["nav_start"]}
    page = st.radio("메뉴", PAGES, key="nav_radio", label_visibility="collapsed", on_change=_to_main_menu, **nav_kw)
    st.markdown('<div class="side-sep">HITL (전문가) 검토</div>', unsafe_allow_html=True)
    st.button(HITL_PAGE, key="side_hitl", on_click=_to_side, args=(HITL_PAGE,),
              type="primary" if st.session_state.get("side_page") == HITL_PAGE else "secondary",
              help="KCI K-water 소속 분류를 사람이 검증하는 판정 게임 (HITL)")
    st.button(LR1_PAGE, key="side_lr1", on_click=_to_side, args=(LR1_PAGE,),
              type="primary" if st.session_state.get("side_page") == LR1_PAGE else "secondary",
              help="라벨링 1차 샘플링 — 무작위 고정 60장을 판정자마다 따로(블라인드) 판정해 적합률·기계 일치·판정자 간 일치를 먼저 확인")
    st.button(LR_PAGE, key="side_lr", on_click=_to_side, args=(LR_PAGE,),
              type="primary" if st.session_state.get("side_page") == LR_PAGE else "secondary",
              help="연구소 라벨이 맞는지 OK·NG·이관 판정 — 기계 적합도 점수 + 감사 표본 (시범: 수자원환경연구소)")
    st.markdown('<div class="side-sep">- Agent Flow 확인用 -</div>', unsafe_allow_html=True)
    for i_, (name_, spec_) in enumerate(AGENT_FLOWS.items()):
        st.button(name_, key=f"side_flow_{i_}", on_click=_to_side, args=(name_,),
                  type="primary" if st.session_state.get("side_page") == name_ else "secondary", help=spec_[3])
    if st.session_state.get("side_page"):
        page = st.session_state["side_page"]
    elif page is None:
        page = PAGES[0]
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
    <span class="badge">🕒 최근 수행 {ago(last_hb)}</span>
    <span class="badge">⏱️ 다음 수행 예정시간 ~{next_heartbeat_kst()} KST</span>
  </div></div>""", unsafe_allow_html=True)

# ═══════════════ 페이지 1: 관제센터 ═══════════════
if page == "🛰️ 관제센터":
    # KPI 두 줄: 자체 수집 에이전트 / 처리·분석·지식 (openalex 연동 포함 · v3.11)
    _kc = (load_json("kci_counts.json") or {}).get("journals", {})
    _krs = ((load_json("kci_rising.json") or {}).get("scopes") or {}).get("J11+J12") or {}
    _runs = load_labels_jsonl("pipeline_runs.jsonl")
    _ht = hitl_totals()
    _pop12 = oa_population(oa_main.get("years") or [])
    _oa_y = oa_main.get("years") or ["", ""]
    lo = live_oa or {}
    row_col = [
        ("논문 OpenAlex", f"{lo.get('collected_total', T.get('papers', 0)):,}편",
         (f"K-water {lo.get('kwater_collected', 0):,} · 12저널 {lo.get('journal_collected', 0):,}(2020~) · "
          f"연구소 관련 {lo.get('related_collected', 0):,}") if lo else "수집 대기"),
        ("KCI 국내 학회지 (실측)", f"{sum(v.get('total', 0) for v in _kc.values()):,}편",
         " · ".join(f"{k} {v.get('total', 0):,}" for k, v in _kc.items()) + " (원천은 비공개 보관)" if _kc else "실측 대기"),
        ("ALIO 보고서", f"{T.get('alio_collected', 0)}건", f"파싱 {T.get('alio_parsed_ok', 0)} · 오류 {T.get('alio_errors', 0)}"),
        ("특허 KIPRIS", f"{T.get('patents', 0)}건", "키 승인 대기"),
        ("기사·아티클", f"{T.get('articles', 0)}건", "파이프라인 설계"),
    ]
    row_ana = [
        ("openalex 연동 코퍼스", f"{(oa_main.get('documents') or 0):,}편",
         f"수자원 12저널 {_oa_y[0]}–{_oa_y[-1]} · 영어·필터 후" + (f" (OpenAlex 모집단 {_pop12:,})" if _pop12 else ""))
        if oa_main else ("openalex 연동 코퍼스", "-", "OPENALEX_DATA_TOKEN 연동 대기"),
        ("상승 연구주제 Rising (OpenAlex)", f"{(oa_main.get('rising') or 0):,}개",
         f"커뮤니티 {oa_main.get('clusters', 0)} · Q {oa_main.get('modularity') or 0:.3f} · MK+BH q≤0.05") if oa_main
        else ("상승 연구주제 (OpenAlex)", "-", "연동 대기"),
        ("KCI 상승 용어 (단어)", f"{_krs.get('n_rising', 0):,}개",
         f"구 {(_krs.get('bigram') or {}).get('n_rising', 0):,} · 국내 학회지 {sum(_krs.get('denominator') or []):,}편 · "
         f"묶음 {len((_krs.get('network') or {}).get('communities') or [])}"),
        ("연구소 라벨", f"{(_runs[-1].get('total', 0) if _runs else 0):,}편", "초록 · 대상/문제 · W 도메인 (6시간마다)"),
        ("데이터소스 mention", f"{T.get('mentions', 0):,}건", f"고유 {T.get('unique_datasources', 0):,}개 · 페이지 근거 100%"),
        ("사람 판정 (HITL)", f"{_ht['records']:,}건",
         f"OK {_ht['ok']} · NG {_ht['ng']} · 이관 {_ht['move']} · 연구소 {_ht['insts']}곳 · 판정자 {_ht['reviewers']}명"),
    ]
    ACC = ["#17549A", "#2E77C6", "#3B82F6", "#C0392B", "#1E8449", "#0EA5E9"]
    for grp_, rows_, acc_ in (("📥 수집 — 자체 에이전트", row_col, ACC), ("🧠 처리 · 분석 · 지식 — openalex 연동 포함", row_ana,
                                                                      ["#0F766E", "#7C3AED", "#D97706", "#0284C7", "#475569", "#DB2777"])):
        st.markdown(f'<div class="kpi-grp">{grp_}</div><div class="kpis">' + "".join(
            f'<div class="kpi" style="border-left-color:{acc_[i % len(acc_)]}">'
            f'<div class="k-val">{v}</div><div class="k-lab">{k}</div>'
            f'<div class="k-sub">{s_}</div></div>' for i, (k, v, s_) in enumerate(rows_)) + "</div>",
            unsafe_allow_html=True)

    # 🏷️ 라벨링 봇 상태 배지
    if _runs:
        _r = _runs[-1]
        try:
            _t = dt.datetime.strptime(_r["ts"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
            _h = int((dt.datetime.now(dt.timezone.utc) - _t).total_seconds() // 3600)
            _when = "1시간 이내" if _h < 1 else f"{_h}시간 전"
        except Exception:
            _when = str(_r.get("ts", ""))
        st.markdown(
            '<div style="margin:6px 0 4px;padding:8px 14px;border-radius:10px;'
            'background:linear-gradient(90deg,#EEF2FF,#F0F9FF);border:1px solid #C7D2FE;'
            'font-size:0.85rem;color:#1E293B;">🏷️ <b>라벨링 봇</b> 최근 실행 ' + _when +
            f' · 신규 수집 +{_r.get("forward", 0) + _r.get("hist", 0)} · 신규 라벨 +{_r.get("assigned", 0)}'
            f' · 누적 {_r.get("total", 0):,}건'
            ' <span style="color:#64748B">— 상세: [🏷️ 라벨링 로그] 메뉴</span></div>',
            unsafe_allow_html=True)

    # 파이프라인 플로우 — "에이전트가 돌아가는 이미지"
    st.markdown('<div class="sect">데이터 파이프라인</div>', unsafe_allow_html=True)
    stages = [
        ("📡 소스", "5개 원천", "OpenAlex·KCI·ALIO·특허·기사"),
        ("📥 수집 에이전트", f"{T.get('alio_collected', 0) + T.get('papers', 0) + T.get('patents', 0) + T.get('articles', 0) + sum(v.get('total', 0) for v in _kc.values()):,}건",
         "논문·KCI·ALIO·특허·기사"),
        ("🔗 외부 연동", f"{(oa_main.get('documents') or 0):,}편" if oa_main else "대기", "openalex 분석 결과 · 주 1회"),
        ("🧠 파싱·추출", f"{T.get('mentions', 0):,} mention", "gpt-4o → FT모델 교체 예정"),
        ("🧩 정규화", f"{T.get('unique_datasources', 0):,} 소스", "registry·canonical"),
        ("🔭 트렌드 분석", f"상승 {(oa_main.get('rising') or 0) + _krs.get('n_rising', 0):,}개", f"OpenAlex {(oa_main.get('rising') or 0):,} · KCI {_krs.get('n_rising', 0):,}"),
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
            counts = " · ".join(                       # 숫자·문자 혼용 안전 (에이전트가 "1/8" 등도 보냄)
                f"{k} <b>{v:,}</b>" if isinstance(v, (int, float)) else f"{k} <b>{v}</b>"
                for k, v in (a.get("counts") or {}).items()) or "&nbsp;"
            nxt = f"다음 수행 예정: {a['next_run']}" if a.get("next_run") else ""
            cards += f"""<div class="agent" style="border-left-color:{color}">
              <div class="a-top">
                <span class="a-name">{meta['icon']} {meta['ko']} <span class="a-id">{name}</span><span class="gchip">{meta.get('grp','')}</span></span>
                <span class="pill" style="background:{color}1A;color:{color}">
                  <span class="pulse {on}" style="background:{color}"></span>{label}</span>
              </div>
              <div class="a-role">{a.get('summary') or meta['role']}</div>
              <div class="a-cnt">{counts}</div>
              <div class="a-next">최근 수행 {ago(a.get('last_run'))} &nbsp; {nxt}</div>
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
        ("📄 논문 OpenAlex — K-water 생산 + 수자원 12개 저널 + 도메인 관련(트렌드용)", T.get("papers", 0),
         (live_oa.get("target_total") if live_oa and live_oa.get("target_total") else 3000),
         ("🟢 누적 수집 중 — 10분당 100편" if live_oa and T.get("papers", 0) < live_oa.get("target_total", 0)
          else "✅ 1차 수집 완료") if live_oa else "🟡 수집기 배치 · search_topics.json 준비"),
        ("🇰🇷 KCI 국내 학회지 — 한국수자원학회논문집·대한토목학회논문집 (원천은 비공개 저장소)",
         sum((v.get("total", 0) for v in ((load_json("kci_counts.json") or {}).get("journals", {})).values())),
         sum((v.get("total", 0) for v in ((load_json("kci_counts.json") or {}).get("journals", {})).values())) or 1,
         "✅ 주 1회 실측·수집 (kci-counts · kci-rising)"),
        ("🔗 openalex 연동 — 수자원 12저널 2000–2025 (분석용 코퍼스, 영어·필터 후 / OpenAlex 모집단)",
         oa_main.get("documents") or 0,
         oa_population(oa_main.get("years") or []) or (oa_main.get("documents") or 0) or 1,
         "✅ 주 1회 연동 (oa-rising)" if oa_main else "🟡 OPENALEX_DATA_TOKEN 연동 대기"),
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

# ═══════════════ 페이지: 논문 트렌드 ═══════════════
elif page == "📄 논문 트렌드":
    inst_names = summary.get("inst_names", {})
    oa_tr = load_json("openalex_trends.json") or {}
    itr.render_overview(oa_tr, inst_names, INST_COLORS, PLOTLY_LAYOUT)    # 해외 × 연구소 5년 (v3.12)
    t_years, _, t_insts, t_base = itr.series(oa_tr)
    if not t_years:                                       # 실측 전: 올해 포함 5개 연도로 창만 정함
        t_years = [str(y) for y in range(time.gmtime().tm_year - 4, time.gmtime().tm_year + 1)]
    st.divider()
    st.markdown('<div class="sect">OpenAlex 수집 논문 · 연구소 관련 논문 트렌드</div>', unsafe_allow_html=True)
    st.caption("수집 필드: 제목·발행연도/일·저널·피인용·유형·DOI (메타정보 — 초록은 labels 파이프라인이 보강) · "
               f"연구소 트랙은 최근 5년({t_years[0]}–{t_years[-1]}) — 실시간 수집분 + labels 파이프라인이 모은 지난 연도를 합쳐 봄")
    wj = load_json("water_journals.json") or {}              # 수자원 12개 핵심 저널 레지스트리
    TAGS = [("kwater", "K-water 생산논문")] + \
           [(j["code"], f"[저널] {j['name']}") for j in wj.get("journals", [])] + \
           [(c, f"[관련] {inst_names.get(c, c)}") for c in sorted(inst_names)]

    # 작업별 수집 칩 (stats 기반 — 파일 로드 없이 가볍게)
    tstats = (live_oa or {}).get("tasks", {})
    chips = "".join(
        f'<div class="kpi" style="border-left-color:{"#17549A" if t == "kwater" else CYAN if t.startswith("J") else INST_COLORS.get(t, GRAY)}">'
        f'<div class="k-val">{tstats.get(t, {}).get("count", 0):,}</div>'
        f'<div class="k-lab">{lab}</div>'
        f'<div class="k-sub">목표 {tstats.get(t, {}).get("target", 0):,}'
        f'{" · ✅" if tstats.get(t, {}).get("done") else " · 수집중"}</div></div>'
        for t, lab in TAGS)
    st.markdown(f'<div class="kpis">{chips}</div>', unsafe_allow_html=True)

    sel = st.selectbox("연구소 / 트랙 선택", TAGS, format_func=lambda x: x[1])
    is_inst = sel[0].startswith("INST-")
    df = load_papers(sel[0], history=is_inst)
    if is_inst and not df.empty and "year" in df:          # 연구소 트랙 = 최근 5년 창
        yy = pd.to_numeric(df["year"], errors="coerce")
        df = df[(yy >= int(t_years[0])) & (yy <= int(t_years[-1]))]
    if df.empty:
        st.info("이 트랙은 아직 수집 전이거나 파일이 없습니다 — 수집기가 순서대로 진행 중입니다.")
    else:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("수집 논문" + (f" ({t_years[0]}–{t_years[-1]})" if is_inst else ""), f"{len(df):,}편")
        c2.metric("피인용 합계", f"{int(df['cited'].fillna(0).sum()):,}")
        c3.metric("최신 연도", int(df["year"].dropna().max()) if df["year"].notna().any() else "-")
        c4.metric("저널 수", df["venue"].dropna().nunique() if "venue" in df else 0)

        a, b = st.columns(2)
        with a:  # 연구소 트랙: 연도별 수집 vs 실측 / 그 밖: 월별(date 있으면) 또는 연도별
            if is_inst:
                _ps = load_labels("pipeline_state.json") or {}          # labels 파이프라인 상태 (다시 훑기 차례·수집 기준)
                itr.render_coverage(df, (t_insts.get(sel[0]) or {}).get("by_year") or {}, t_years,
                                    INST_COLORS.get(sel[0], BLUE), PLOTLY_LAYOUT, key=f"cov_{sel[0]}",
                                    next_year=_ps.get("resweep_next_year"),
                                    by_year_all=(t_insts.get(sel[0]) or {}).get("by_year_all"),
                                    basis=_ps.get("collect_basis"), basis_since=_ps.get("collect_basis_since"))
            else:
                monthly = None
                if "date" in df and df["date"].notna().sum() >= max(30, len(df) // 2):
                    d = pd.to_datetime(df["date"], errors="coerce").dropna()
                    monthly = d.dt.to_period("M").astype(str).value_counts().sort_index()
                if monthly is not None and len(monthly) >= 3:
                    st.markdown('<div class="sect">월별 발행 추이</div>', unsafe_allow_html=True)
                    fig = go.Figure(go.Bar(x=monthly.index, y=monthly.values, marker_color=BLUE))
                else:
                    st.markdown('<div class="sect">연도별 발행 추이</div>', unsafe_allow_html=True)
                    yr = df["year"].dropna().astype(int).value_counts().sort_index()
                    fig = go.Figure(go.Bar(x=yr.index.astype(str), y=yr.values, marker_color=BLUE))
                fig.update_layout(height=300, **PLOTLY_LAYOUT)
                st.plotly_chart(fig, width="stretch")
        with b:
            st.markdown('<div class="sect">Top 10 저널·출처</div>', unsafe_allow_html=True)
            vc = df["venue"].dropna().value_counts().head(10)[::-1] if "venue" in df else []
            if len(vc):
                fig = go.Figure(go.Bar(x=vc.values, y=[v[:38] for v in vc.index],
                                       orientation="h", marker_color=CYAN))
                fig.update_layout(height=300, **PLOTLY_LAYOUT)
                st.plotly_chart(fig, width="stretch")
            else:
                st.info("저널 정보 없음")

        if is_inst and t_insts.get(sel[0]):                 # 연구소 키워드별 5년 추이 (v3.13)
            itr.render_keywords(t_insts[sel[0]], t_years, t_base, INST_COLORS.get(sel[0], BLUE), PLOTLY_LAYOUT,
                                key=f"kw_{sel[0]}", base_top10=(oa_tr.get("baseline") or {}).get("by_year_top10"))
        st.markdown('<div class="sect">피인용 상위 논문</div>', unsafe_allow_html=True)
        top = (df.assign(cited=df["cited"].fillna(0).astype(int))
                 .sort_values("cited", ascending=False).head(15)
                 [["title", "year", "venue", "cited", "doi"]]
                 .rename(columns={"title": "제목", "year": "연도", "venue": "저널",
                                  "cited": "피인용", "doi": "DOI"}))
        st.dataframe(top, hide_index=True, width="stretch",
                     column_config={"DOI": st.column_config.LinkColumn("DOI", display_text="🔗 열기")})
        st.caption("피인용 = 우리가 논문을 받은 날의 피인용 수(그 뒤로 갱신 안 함) — 오래된 논문일수록 크게 나옴. "
                   "분야·연도를 보정한 비교는 위 '피인용 질' 그림(피인용 상위 10% 비중)을 볼 것.")

    # ═══════════════ 수자원 12개 핵심 저널 코퍼스 (분모) ═══════════════
    st.divider()
    st.markdown('<div class="sect">🌊 수자원 12개 핵심 저널 코퍼스 — 트렌드 분석 분모</div>',
                unsafe_allow_html=True)
    trj = dict((load_json("openalex_trends.json") or {}).get("journals", {}))
    kci = (load_json("kci_counts.json") or {}).get("journals", {})
    for c, v in kci.items():                                  # 한국 저널 분모는 KCI 실측으로 대체
        if v.get("by_year"):
            trj[c] = {**trj.get(c, {}), **v, "count_source": "KCI"}
    st.caption(f"OpenAlex 실측 저널×연도 건수 ({wj.get('archive_from_year', 2000)}~) · "
               f"연관성·트렌드 분석: {wj.get('analysis_status', '미실시')}")
    if not trj:
        st.info("저널 코퍼스 실측 전입니다 — 다음 수행(6시간 주기)에서 openalex_lite가 기록합니다.")
    else:
        cur_year = time.gmtime().tm_year
        cov_to = {j["code"]: j.get("openalex_coverage_to") for j in wj.get("journals", [])}

        def last_year(v):
            ys = [int(y) for y, n in (v.get("by_year") or {}).items() if n]
            return v.get("last_year") or (max(ys) if ys else None)

        def coverage(c, v):   # KCI 대체 / 레지스트리 표기 / 최근 2년 이상 0건 → 끊김
            ly = last_year(v)
            if v.get("count_source") == "KCI":
                return "✅ KCI 실측" if ly and ly >= cur_year - 1 else f"⚠️ KCI {ly}년까지"
            if cov_to.get(c) or (ly and ly < cur_year - 1):
                return f"⚠️ {cov_to.get(c) or ly}년까지"
            return "✅"
        jrows = [{"코드": c, "저널": v.get("name"), "전체": v.get("total", 0),
                  "최근연도": last_year(v) or "-", "커버리지": coverage(c, v),
                  "source": "KCI" if v.get("count_source") == "KCI"
                            else ", ".join(s["id"] for s in v.get("sources", []))}
                 for c, v in sorted(trj.items())]
        gaps = [r for r in jrows if r["커버리지"].startswith("⚠️")]
        if gaps:
            st.warning("커버리지 끊김 — " + " · ".join(
                f"{r['코드']} {r['저널']} ({r['커버리지'][2:]})" for r in gaps) +
                ". 이후 연도는 논문이 없는 것이 아니라 OpenAlex에 미연결 → 트렌드 분석 분모에서 제외, "
                "KCI 등 대체 출처로 보완 예정.")
        m1, m2 = st.columns(2)
        m1.metric("저널 수 (해석 성공)", f"{len(trj)} / {len(wj.get('journals', [])) or 12}")
        m2.metric("코퍼스 논문 수", f"{sum(r['전체'] for r in jrows):,}편")
        yrs = sorted({y for v in trj.values() for y in v.get("by_year", {})})
        fig = go.Figure()
        for c, v in sorted(trj.items()):
            by = v.get("by_year", {})
            fig.add_trace(go.Bar(x=yrs, y=[by.get(y, 0) for y in yrs], name=f"{c} {v.get('name', '')[:24]}"))
        fig.update_layout(barmode="stack", height=360, **PLOTLY_LAYOUT)
        st.plotly_chart(fig, width="stretch")
        st.dataframe(pd.DataFrame(jrows), hide_index=True, width="stretch")
        if kci:
            st.caption("🇰🇷 " + ", ".join(sorted(kci)) + " 연도별 건수: KCI(한국학술지인용색인) 데이터 활용 "
                       "— 연도별 집계만 표시 (원천 데이터 미저장)")

    # ═══════════════ 도메인 트렌드 (v0.1) — 아래 블록을 '논문 트렌드' 페이지 끝에 추가 ═══════════════
    # ═══════════════ K-water 연구기록 (16-25) ═══════════════
    st.divider()
    st.markdown('<div class="sect">🏛️ K-water 연구기록 (16-25) — 도메인축 v0.1</div>',
                unsafe_allow_html=True)
    ksum = load_labels("domain/kwater_pubs_summary.json")
    if not ksum:
        st.info("K-water 성과 집계 파일이 아직 없습니다 (labels/domain/kwater_pubs_summary.json).")
    else:
        KDOM = ["W1", "W2", "W3", "W4", "W5", "W6", "W7", "W8", "W9", "W0"]
        KUNC = "W0_UNCLASSIFIED"
        KCOL = {"W1": "#2563EB", "W2": "#0EA5E9", "W3": "#10B981", "W4": "#14B8A6",
                "W5": "#8B5CF6", "W6": "#6366F1", "W7": "#F59E0B", "W8": "#EF4444",
                "W9": "#64748B", "W0": "#94A3B8"}
        kd = ksum["domains"]
        st.caption(f"{ksum.get('source','')} · 총 {ksum['total']:,}건 · {ksum.get('method','')}")

        m1, m2, m3 = st.columns(3)
        m1.metric("성과 건수", f"{ksum['total']:,}건")
        ktop = max(KDOM, key=lambda c: kd[c]["count"])
        m2.metric("최다 도메인", f"{ktop} {kd[ktop]['name']}", f"{kd[ktop]['pct']}%")
        m3.metric("미분류(비물 주제)", f"{kd[KUNC]['pct']}%", delta_color="off")

        byd = ksum.get("by_year_domain", {})
        years = [y for y in sorted(byd) if 2016 <= int(y) <= 2025]
        if years:
            fig = go.Figure()
            for c in KDOM:
                tot = {y: sum(byd[y].get(d, 0) for d in KDOM) for y in years}
                fig.add_trace(go.Bar(
                    name=f"{c} {kd[c]['name']}", x=years,
                    y=[round(byd[y].get(c, 0) * 100 / max(tot[y], 1), 1) for y in years],
                    marker_color=KCOL[c],
                    customdata=[byd[y].get(c, 0) for y in years],
                    hovertemplate="%{x} · " + kd[c]["name"] + " %{y}% (%{customdata}건)<extra></extra>"))
            for y in years:
                fig.add_annotation(x=y, y=105, text=f"n={tot[y]}", showarrow=False,
                                   font=dict(size=10, color="#94A3B8"))
            fig.update_layout(barmode="stack", height=380,
                              yaxis=dict(title="도메인 구성비 %", range=[0, 112]),
                              legend=dict(orientation="h", y=-0.18), **PLOTLY_LAYOUT)
            st.plotly_chart(fig, width="stretch")
            st.caption("연도별 도메인 구성비(100%, 미분류 제외) · 막대 위 n=해당 연도 등록 건수 — "
                       "n이 작은 연도(2016 n=13 등)는 특정 학회 일괄등록만 남아 구성비 해석에 주의")

    st.divider()
    st.markdown('<div class="sect">🌍 글로벌 물연구 현황 (25 기준) — 도메인축 v0.1</div>',
                unsafe_allow_html=True)
    dsum = load_labels("domain/domain_summary_v0.1.json")
    if not dsum:
        st.info("도메인 집계 파일이 아직 없습니다 (labels/domain/domain_summary_v0.1.json).")
    else:
        DOM_ORDER = ["W1", "W2", "W3", "W4", "W5", "W6", "W7", "W8", "W9", "W0"]
        UNC = "W0_UNCLASSIFIED"
        doms = dsum["domains"]
        insts_d = dsum["institutes"]
        inst_ids = sorted(insts_d)
        total = dsum["total"]
        unc_all = doms[UNC]["count"]

        st.caption(f"기준: {dsum.get('source','')} · 총 {total:,}건 배정 · "
                   f"체계 {dsum.get('domain_ver','')} ({dsum.get('status','')})")

        k1, k2, k3 = st.columns(3)
        k1.metric("배정 문헌", f"{total:,}건")
        top_dom = max(DOM_ORDER, key=lambda c: doms[c]["count"])
        k2.metric("최다 도메인", f"{top_dom} {doms[top_dom]['name']}",
                  f"{doms[top_dom]['pct']}%")
        k3.metric("미분류(물 밖 유입)", f"{unc_all:,}건", f"{doms[UNC]['pct']}%",
                  delta_color="off")

        a, b = st.columns(2)
        with a:  # 전체 도메인 분포 (물 도메인만, 미분류 제외)
            st.markdown('<div class="sect">물 도메인 분포</div>', unsafe_allow_html=True)
            pairs = sorted(((c, doms[c]["count"]) for c in DOM_ORDER),
                           key=lambda x: x[1])
            fig = go.Figure(go.Bar(
                x=[n for _, n in pairs],
                y=[f"{c} {doms[c]['name']}" for c, _ in pairs],
                orientation="h", marker_color=BLUE,
                text=[f"{doms[c]['pct']}%" for c, _ in pairs], textposition="auto"))
            fig.update_layout(height=340, **PLOTLY_LAYOUT)
            st.plotly_chart(fig, width="stretch")
        with b:  # 기관별 미분류율
            st.markdown('<div class="sect">연구소별 미분류율 (수집 물-외 유입)</div>',
                        unsafe_allow_html=True)
            ids2 = sorted(inst_ids, key=lambda i: insts_d[i]["unclassified_pct"])
            fig = go.Figure(go.Bar(
                x=[insts_d[i]["unclassified_pct"] for i in ids2],
                y=[insts_d[i]["name"] for i in ids2],
                orientation="h",
                marker_color=[INST_COLORS.get(i, GRAY) for i in ids2],
                text=[f'{insts_d[i]["unclassified_pct"]}%' for i in ids2],
                textposition="auto"))
            fig.update_layout(height=340, xaxis_title="미분류 %", **PLOTLY_LAYOUT)
            st.plotly_chart(fig, width="stretch")

        # 기관 × 도메인 히트맵 (행 정규화 %, 미분류 제외)
        st.markdown('<div class="sect">연구소 × 도메인 히트맵 (행 기준 %, 미분류 제외)</div>',
                    unsafe_allow_html=True)
        z, txt = [], []
        for i in inst_ids:
            bd = insts_d[i]["by_domain"]
            base = sum(bd[c] for c in DOM_ORDER) or 1
            z.append([round(bd[c] * 100 / base, 1) for c in DOM_ORDER])
            txt.append([str(bd[c]) for c in DOM_ORDER])
        fig = go.Figure(go.Heatmap(
            z=z, x=[f"{c}<br>{doms[c]['name']}" for c in DOM_ORDER],
            y=[insts_d[i]["name"] for i in inst_ids],
            text=txt, texttemplate="%{text}", colorscale="Blues",
            hovertemplate="%{y} · %{x}<br>비중 %{z}%<br>건수 %{text}<extra></extra>"))
        fig.update_layout(height=360, **PLOTLY_LAYOUT)
        st.plotly_chart(fig, width="stretch")

        # K-water vs 글로벌 도메인 비중 비교 (물 도메인만 100% 정규화)
        if ksum:
            st.markdown('<div class="sect">⚖️ K-water 연구기록 vs 글로벌 — 도메인 비중 비교</div>',
                        unsafe_allow_html=True)
            kw_base = sum(ksum["domains"][c]["count"] for c in DOM_ORDER) or 1
            gl_base = sum(doms[c]["count"] for c in DOM_ORDER) or 1
            fig = go.Figure()
            fig.add_trace(go.Bar(
                name="K-water 연구기록 (16-25)",
                x=[f"{c}<br>{doms[c]['name']}" for c in DOM_ORDER],
                y=[round(ksum["domains"][c]["count"] * 100 / kw_base, 1) for c in DOM_ORDER],
                marker_color=BLUE))
            fig.add_trace(go.Bar(
                name="글로벌 (25 기준)",
                x=[f"{c}<br>{doms[c]['name']}" for c in DOM_ORDER],
                y=[round(doms[c]["count"] * 100 / gl_base, 1) for c in DOM_ORDER],
                marker_color="#94A3B8"))
            fig.update_layout(barmode="group", height=360, yaxis_title="비중 %",
                              legend=dict(orientation="h", y=1.12), **PLOTLY_LAYOUT)
            st.plotly_chart(fig, width="stretch")
            st.caption("양쪽 모두 미분류 제외 후 100% 정규화 — 같은 W축 좌표계 비교")

        # 미분류 원인 메모 (물 밖 유입 근거)
        ua = dsum.get("unclassified_analysis", {})
        if ua:
            with st.expander(f"❓ 미분류 {doms[UNC]['pct']}%는 무엇인가 — 물 도메인 밖 유입 분석"):
                st.markdown(f"**판정:** {ua.get('verdict','')}")
                for code in ("INST-03", "INST-06", "INST-01"):
                    if code in ua:
                        st.markdown(f"- **{code}**: {ua[code]}")
                if ua.get("next_action"):
                    st.caption(f"다음 조치: {ua['next_action']}")

# ═══════════════ 페이지: 라벨링 로그 ═══════════════
elif page == "🇰🇷 KCI 트렌드":
    # 범주 색: 검증된 8색 고정 순서 (묶음 id 순서대로, 9번째부터는 회색 '기타')
    CAT8 = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
    kr = load_json("kci_rising.json")
    kc = (load_json("kci_counts.json") or {}).get("journals", {})
    wj = load_json("water_journals.json") or {}

    # ── 준비·파이프라인 상태 ──
    n_docs = sum(v.get("total", 0) for v in kc.values())
    steps = [("① 인증키", "✅ 등록", "KCI Open API"),
             ("② 건수 실측", f"✅ {n_docs:,}편" if kc else "⏳ 대기", "kci-counts · 주 1회"),
             ("③ 원천 수집", "✅ 비공개 보관" if kr else "⏳ 비공개 저장소 준비", "water-tech-kci-private"),
             ("④ 용어 추출", "✅ Kiwi 명사·구" if kr else "⏳", "복합어 · 두 단어 구 · 불용어 제거"),
             ("⑤ 추세 검정", (f"✅ 단어 {sum(v['tested'] for v in kr['scopes'].values()):,} · 구 "
                             f"{sum((v.get('bigram') or {}).get('tested', 0) for v in kr['scopes'].values()):,}") if kr else "⏳",
              "MK(단어)·준포아송(구) + BH"),
             ("⑥ 주제 묶음", "✅ Louvain" if kr else "⏳", "공출현 네트워크")]
    st.markdown('<div class="flow">' + '<div class="arr">›</div>'.join(
        f'<div class="stage"><div class="s-t">{t}</div><div class="s-v">{v}</div><div class="s-s">{s_}</div></div>'
        for t, v, s_ in steps) + '</div>', unsafe_allow_html=True)

    if not kr or not kr.get("scopes"):
        st.info("상승 주제 분석 결과가 아직 없습니다. 비공개 저장소(water-tech-kci-private)와 "
                "KCI_PRIVATE_TOKEN을 준비하면 kci-rising 워크플로가 수집·분석해 이 화면을 채웁니다.")
    else:
        c1, c2 = st.columns([2, 3])
        scope = c1.radio("범위", list(kr["scopes"]), horizontal=True,
                         format_func=lambda s_: {"J11": "수자원학회 단독", "J11+J12": "수자원학회 + 토목학회",
                                                 "KWATER": "K-water 소속 논문"}.get(s_, s_))
        sd = kr["scopes"][scope]
        yrs, den = sd["years"], sd["denominator"]
        rising, falling = sd["rising"], sd["falling"]
        comms = sd["network"]["communities"]
        term_comm = {t: c["id"] for c in comms for t in c["terms"]}
        comm_rank = {c["id"]: i for i, c in enumerate(comms)}

        def ccolor(term):
            i = comm_rank.get(term_comm.get(term), 99)
            return CAT8[i] if i < len(CAT8) else GRAY

        c2.caption(f"{yrs[0]}–{yrs[-1]} · 논문 {sum(den):,}편 · FDR q<{kr['q']} · 갱신 {ago(kr.get('updated'))}  \n"
                   f"{kr['source']}")

        top_major = [r for r in rising if not r.get("minor")]
        best = top_major[0] if top_major else (rising[0] if rising else None)
        kpis = [("검정 용어", f"{sd['tested']:,}", "누적 논문 ≥20 · 5개 연도 이상", BLUE),
                ("상승 (유의)", f"{sd['n_rising']:,}", f"저빈도 제외 {len(top_major):,}", GREEN),
                ("하강 (유의)", f"{sd['n_falling']:,}", "q<0.05", RED),
                ("주제 묶음", f"{len(comms)}", f"{sd['network']['window'][0]}–{sd['network']['window'][-1]} 공출현", NAVY),
                ("가장 가파른 상승", best["term"] if best else "-",
                 f"+{best['sen'] * 1000:.2f}‰/년" if best else "", CYAN),
                ("상승 구 (바이그램)", f"{(sd.get('bigram') or {}).get('n_rising', 0):,}",
                 f"구로만 {sum(1 for r in (sd.get('bigram') or {}).get('rising', []) if r.get('novel') and not r.get('minor'))}",
                 "#7C3AED")]
        st.markdown('<div class="kpis">' + "".join(
            f'<div class="kpi" style="border-left-color:{c}"><div class="k-val">{v}</div>'
            f'<div class="k-lab">{l}</div><div class="k-sub">{s_}</div></div>'
            for l, v, s_, c in kpis) + '</div>', unsafe_allow_html=True)

        tab1, tabB, tab2, tab3, tab4, tab5 = st.tabs(["📈 상승 용어", "🔗 상승 구(바이그램)", "🕸️ 주제 묶음",
                                                      "🔍 용어·구 찾기", "📉 하강 용어·구", "🏢 K-water 논문"])
        bg = sd.get("bigram") or {}
        b_rising, b_falling = bg.get("rising") or [], bg.get("falling") or []
        has_j11 = any("j11_share" in r for r in b_rising + b_falling)
        PURPLE = "#7C3AED"

        def b_lift(r):
            return "신규" if r.get("lift") is None else f"{r['lift']}배"

        def b_slope(r):
            return r.get("slope", r.get("sen", 0.0))

        def b_water(rows, on):
            return [r for r in rows if not on or (r.get("j11_share") or 0) >= 0.2]

        # ── 탭1: 순위 막대 + 연도 히트맵 ──
        with tab1:
            show_minor = st.toggle("저빈도 용어 포함 (최근 3년 8편 미만)", value=False)
            rows = [r for r in rising if show_minor or not r.get("minor")][:25]
            if not rows:
                st.info("표시할 상승 용어가 없습니다.")
            else:
                a, b = st.columns([2, 3])
                with a:
                    st.markdown('<div class="sect">기울기 순위 (논문 1,000편당 연간 증가)</div>',
                                unsafe_allow_html=True)
                    rr = rows[::-1]
                    fig = go.Figure(go.Bar(
                        x=[r["sen"] * 1000 for r in rr], y=[r["term"] for r in rr], orientation="h",
                        marker=dict(color=BLUE, line=dict(color="#FFFFFF", width=2)),
                        customdata=[[r["recent_docs"], r["lift"], r["q"], r["total"]] for r in rr],
                        hovertemplate="<b>%{y}</b><br>기울기 %{x:.2f}‰/년<br>최근 3년 %{customdata[0]}편"
                                      "<br>최근/초기 배율 %{customdata[1]}<br>누적 %{customdata[3]}편"
                                      "<br>q = %{customdata[2]:.1e}<extra></extra>"))
                    fig.update_layout(height=max(320, 22 * len(rr) + 40), xaxis_title="‰ / 년",
                                      yaxis=dict(automargin=True), bargap=0.25, **PLOTLY_LAYOUT)
                    fig.update_xaxes(gridcolor="#EEF2F7", zeroline=False)
                    st.plotly_chart(fig, width="stretch")
                with b:
                    st.markdown('<div class="sect">연도별 비중 히트맵 (‰)</div>', unsafe_allow_html=True)
                    z = [[d / n * 1000 if n else 0 for d, n in zip(r["df"], den)] for r in rows]
                    fig = go.Figure(go.Heatmap(
                        z=z, x=[str(y) for y in yrs], y=[r["term"] for r in rows],
                        colorscale=[[0, "#F4F8FC"], [0.5, "#6FA3DC"], [1, "#0A3D74"]],
                        colorbar=dict(title="‰", thickness=10), xgap=2, ygap=2,
                        hovertemplate="<b>%{y}</b> · %{x}<br>%{z:.1f}‰<extra></extra>"))
                    fig.update_layout(height=max(320, 22 * len(rows) + 40),
                                      yaxis=dict(autorange="reversed", automargin=True), **PLOTLY_LAYOUT)
                    st.plotly_chart(fig, width="stretch")
                with st.expander("표로 보기"):
                    st.dataframe(pd.DataFrame([{
                        "용어": r["term"] + (" (저빈도)" if r.get("minor") else ""),
                        "기울기(‰/년)": round(r["sen"] * 1000, 2), "최근3년 논문": r["recent_docs"],
                        "최근/초기 배율": r["lift"], "누적 논문": r["total"], "q": f"{r['q']:.1e}",
                        "묶음": (comm_rank[term_comm[r["term"]]] + 1) if r["term"] in term_comm else "-"}
                        for r in rows]), hide_index=True, width="stretch")

        # ── 탭1-2: 상승 구(바이그램) ──
        with tabB:
            if not bg:
                st.info("이 범위에는 아직 바이그램 결과가 없습니다 — 주간 kci-rising 실행에서 채워집니다.")
            else:
                st.caption("국문 제목·초록에서 **두 단어로 된 구**(띄어 쓴 두 명사가 바로 이어지거나 ‘의’로 이어진 것 — 예: 침수 피해, "
                           "하천의 수질 → 하천 수질, 붙여 쓴 ‘하천수질’도 같은 구로 셈)를 뽑아 연도별 비중이 오르는지 봅니다. "
                           "구는 드물어 해마다 0인 경우가 많아 단어 탭의 Mann–Kendall 대신 **준포아송 회귀**(분모 = 그 해 논문 수, "
                           f"과산포 보정)로 검정하고 FDR q<{kr['q']}만 남겼습니다. 붙여 쓴 형태가 이미 단어 탭의 상승 용어면 중복이라 뺐습니다. "
                           "**구로만** = 두 단어 모두 단어 단위로는 상승 목록에 없는데 구로 묶으면 오르는 신호.")
                bmaj = [r for r in b_rising if not r.get("minor")]
                bbest = bmaj[0] if bmaj else None
                kb = [("검정 구", f"{bg.get('tested', 0):,}", f"누적 논문 ≥{bg.get('min_total', 8)} · 3개 연도 이상", BLUE),
                      ("상승 구 (유의)", f"{bg.get('n_rising', 0):,}", f"저빈도 제외 {len(bmaj):,}", GREEN),
                      ("하강 구 (유의)", f"{bg.get('n_falling', 0):,}", f"q<{kr['q']}", RED),
                      ("구로만 보이는 신호", f"{sum(1 for r in bmaj if r.get('novel'))}", "두 단어 모두 단어로는 상승 아님", PURPLE),
                      ("가장 가파른 상승 구", bbest["term"] if bbest else "-",
                       f"+{b_slope(bbest) * 1000:.2f}‰/년 · 연 {bbest.get('rate', 0) * 100:+.0f}%" if bbest else "", CYAN)]
                st.markdown('<div class="kpis">' + "".join(
                    f'<div class="kpi" style="border-left-color:{c}"><div class="k-val" style="font-size:1.35rem">{v}</div>'
                    f'<div class="k-lab">{l}</div><div class="k-sub">{s_}</div></div>' for l, v, s_, c in kb) + "</div>",
                    unsafe_allow_html=True)
                o1, o2, o3 = st.columns(3)
                b_minor = o1.toggle("저빈도 구 포함 (최근 3년 5편 미만)", value=False, key="kci_bi_minor")
                b_novel = o2.toggle("구로만 보이는 신호만", value=False, key="kci_bi_novel")
                b_wat = o3.toggle("수자원학회 쪽 구만", value=True, key="kci_bi_water", disabled=not has_j11,
                                  help="수자원학회+토목학회 범위에서 수자원학회 논문 비율이 20% 미만인 구"
                                       "(콘크리트·포장 등 토목 구조 분야)를 숨깁니다.") if has_j11 else False
                brows = [r for r in b_water(b_rising, b_wat) if (b_minor or not r.get("minor"))
                         and (not b_novel or r.get("novel"))][:25]
                if not brows:
                    st.info("조건에 맞는 상승 구가 없습니다.")
                else:
                    a, b = st.columns([2, 3])
                    with a:
                        st.markdown('<div class="sect">기울기 순위 (논문 1,000편당 연간 증가)</div>', unsafe_allow_html=True)
                        rr = brows[::-1]
                        fig = go.Figure(go.Bar(
                            x=[b_slope(r) * 1000 for r in rr], y=[r["term"] for r in rr], orientation="h",
                            marker=dict(color=[PURPLE if r.get("novel") else BLUE for r in rr],
                                        line=dict(color="#FFFFFF", width=2)),
                            customdata=[[r["recent_docs"], b_lift(r), r["q"], r["total"], round((r.get("rate") or 0) * 100),
                                         "구로만" if r.get("novel") else "단어로도 상승: " + "·".join(r.get("parts_rising") or [])]
                                        for r in rr],
                            hovertemplate="<b>%{y}</b><br>기울기 %{x:.2f}‰/년 · 연 %{customdata[4]:+d}%<br>최근 3년 %{customdata[0]}편"
                                          " · 최근/과거 %{customdata[1]}<br>누적 %{customdata[3]}편 · q = %{customdata[2]:.1e}"
                                          "<br>%{customdata[5]}<extra></extra>"))
                        fig.update_layout(height=max(320, 22 * len(rr) + 40), xaxis_title="‰ / 년",
                                          yaxis=dict(automargin=True), bargap=0.25, **PLOTLY_LAYOUT)
                        fig.update_xaxes(gridcolor="#EEF2F7", zeroline=False)
                        st.plotly_chart(fig, width="stretch", key="kci_bi_bar")
                        st.markdown(f'<span class="note"><span style="color:{PURPLE}">■</span> 구로만 보이는 신호 &nbsp; '
                                    f'<span style="color:{BLUE}">■</span> 단어로도 오르는 구</span>', unsafe_allow_html=True)
                    with b:
                        st.markdown('<div class="sect">연도별 비중 히트맵 (‰)</div>', unsafe_allow_html=True)
                        z = [[d / n * 1000 if n else 0 for d, n in zip(r["df"], den)] for r in brows]
                        fig = go.Figure(go.Heatmap(
                            z=z, x=[str(y) for y in yrs], y=[r["term"] for r in brows],
                            colorscale=[[0, "#F7F4FD"], [0.5, "#A58BE6"], [1, "#4A2A9C"]],
                            colorbar=dict(title="‰", thickness=10), xgap=2, ygap=2,
                            hovertemplate="<b>%{y}</b> · %{x}<br>%{z:.1f}‰<extra></extra>"))
                        fig.update_layout(height=max(320, 22 * len(brows) + 40),
                                          yaxis=dict(autorange="reversed", automargin=True), **PLOTLY_LAYOUT)
                        st.plotly_chart(fig, width="stretch", key="kci_bi_heat")
                    with st.expander("표로 보기"):
                        st.dataframe(pd.DataFrame([{
                            "구": r["term"] + (" (저빈도)" if r.get("minor") else ""), "구로만": "✔" if r.get("novel") else "",
                            "기울기(‰/년)": round(b_slope(r) * 1000, 2), "연 증가율(%)": round((r.get("rate") or 0) * 100),
                            "최근3년 논문": r["recent_docs"], "최근/과거": b_lift(r), "누적 논문": r["total"],
                            "q": f"{r['q']:.1e}", "단어로도 상승": "·".join(r.get("parts_rising") or []),
                            "수자원학회 비율": r.get("j11_share"), "결합도(PMI)": r.get("pmi")}
                            for r in brows]), hide_index=True, width="stretch")
                st.caption("단어 탭과 함께 보면: 단어 탭의 ‘예측’·‘수자원’ 같은 넓은 말이 구 탭에서는 ‘예측 정확도’·‘수자원 관리’처럼 "
                           "무엇에 쓰이는지로 갈라집니다. 하강 구는 📉 탭, 연도별 비교는 🔍 탭에서 볼 수 있습니다.")

        # ── 탭2: 공출현 네트워크 + 묶음 카드 ──
        with tab2:
            nodes = sd["network"]["nodes"]
            edges = sd["network"]["edges"]
            if not edges:
                st.info("공출현 간선이 없습니다 (상승 용어끼리 최근 논문에서 함께 나온 횟수가 적음).")
            else:
                import networkx as _nx
                G = _nx.Graph()
                G.add_nodes_from(n["term"] for n in nodes)
                G.add_weighted_edges_from(edges)
                G.remove_nodes_from([n for n in list(G) if G.degree(n) == 0])
                # 연결 덩어리별로 따로 배치 후 격자로 붙임 (떨어진 덩어리가 화면 끝으로 흩어지지 않게)
                comps = sorted(_nx.connected_components(G), key=len, reverse=True)
                ncol = max(1, math.ceil(math.sqrt(len(comps))))
                pos = {}
                for ci, comp in enumerate(comps):
                    sub = G.subgraph(comp)
                    lp = _nx.spring_layout(sub, weight="weight", seed=42) if len(comp) > 1 else {next(iter(comp)): (0, 0)}
                    ox, oy = (ci % ncol) * 2.6, -(ci // ncol) * 2.6
                    for t, (x, y) in lp.items():
                        pos[t] = (ox + x, oy + y)
                dfm = {n["term"]: n["df"] for n in nodes}
                wmax = max(w for _, _, w in edges) or 1
                fig = go.Figure()
                for u, v, w in edges:
                    if u in pos and v in pos:
                        fig.add_trace(go.Scatter(x=[pos[u][0], pos[v][0]], y=[pos[u][1], pos[v][1]],
                                                 mode="lines", hoverinfo="skip", showlegend=False,
                                                 line=dict(color="#C9D6E6", width=0.6 + 3 * w / wmax)))
                groups = {}
                for t in G:
                    groups.setdefault(comm_rank.get(term_comm.get(t), 99), []).append(t)
                for gi in sorted(groups):
                    ts = groups[gi]
                    fig.add_trace(go.Scatter(
                        x=[pos[t][0] for t in ts], y=[pos[t][1] for t in ts], mode="markers+text",
                        text=ts, textposition="top center", textfont=dict(size=11, color="#0F2744"),
                        name=f"묶음 {gi + 1}" if gi < 99 else "기타",
                        marker=dict(size=[10 + 26 * (dfm.get(t, 1) / max(dfm.values())) ** 0.5 for t in ts],
                                    color=CAT8[gi] if gi < len(CAT8) else GRAY,
                                    line=dict(color="#FFFFFF", width=2)),
                        customdata=[dfm.get(t, 0) for t in ts],
                        hovertemplate="<b>%{text}</b><br>최근 논문 %{customdata}편<extra></extra>"))
                fig.update_layout(height=560, xaxis=dict(visible=False), yaxis=dict(visible=False),
                                  legend=dict(orientation="h", y=-0.05), **PLOTLY_LAYOUT)
                st.plotly_chart(fig, width="stretch")
                st.caption("점 크기 = 최근 논문 수, 선 굵기 = 함께 나온 논문 수, 색 = Louvain 묶음. "
                           "묶음 이름은 붙이지 않았음 — 해석(라벨링)은 전문가 검토 몫.")
            if comms:
                cols = st.columns(2)
                for i, c in enumerate(comms[:8]):
                    col = CAT8[i] if i < len(CAT8) else GRAY
                    chips = " ".join(f'<span class="gchip" style="background:#F1F5FA;color:#0F2744">{t}</span>'
                                     for t in c["terms"][:14])
                    cols[i % 2].markdown(
                        f'<div class="card" style="border-left:6px solid {col};margin-bottom:10px">'
                        f'<b>묶음 {i + 1}</b> <span class="note">· 용어 {c["size"]}개</span>'
                        f'<div style="margin-top:6px;line-height:2">{chips}</div></div>',
                        unsafe_allow_html=True)

        # ── 탭3: 용어 찾기 ──
        with tab3:
            pool = {r["term"]: ("상승", r) for r in rising}
            pool.update({r["term"]: ("하강", r) for r in falling})
            pool.update({r["term"]: ("상승 구", r) for r in b_rising})
            pool.update({r["term"]: ("하강 구", r) for r in b_falling})
            picks = st.multiselect("용어·구 선택 (유의한 상승·하강 용어와 두 단어 구 중에서, 최대 5개)", sorted(pool),
                                   default=[r["term"] for r in top_major[:2]] + [r["term"] for r in b_rising[:1]],
                                   max_selections=5)
            if picks:
                fig = go.Figure()
                for i, t in enumerate(picks):
                    r = pool[t][1]
                    fig.add_trace(go.Scatter(x=yrs, y=[d / n * 1000 if n else 0 for d, n in zip(r["df"], den)],
                                             mode="lines+markers", name=f"{t} ({pool[t][0]})",
                                             line=dict(color=CAT8[i], width=2), marker=dict(size=8)))
                fig.update_layout(height=380, yaxis_title="‰ (논문 1,000편당)", hovermode="x unified",
                                  legend=dict(orientation="h", y=-0.18), **PLOTLY_LAYOUT)
                fig.update_yaxes(gridcolor="#EEF2F7")
                st.plotly_chart(fig, width="stretch")
                st.dataframe(pd.DataFrame([{"용어·구": t, "방향": pool[t][0],
                                            "기울기(‰/년)": round(pool[t][1].get("slope", pool[t][1]["sen"]) * 1000, 2),
                                            "q": f"{pool[t][1]['q']:.1e}", "누적 논문": pool[t][1]["total"]}
                                           for t in picks]), hide_index=True, width="stretch")
            st.caption("검정 대상이 아니었거나(빈도 부족) 유의하지 않은 용어는 목록에 없음.")

        # ── 탭4: 하강 (단어 · 구) ──
        with tab4:
            fa, fb = st.columns(2)
            with fa:
                st.markdown('<div class="sect">하강 용어 (단어)</div>', unsafe_allow_html=True)
                fr = [r for r in falling if not r.get("minor")][:20]
                if not fr:
                    st.info("유의한 하강 용어가 없습니다.")
                else:
                    rr = fr[::-1]
                    fig = go.Figure(go.Bar(x=[r["sen"] * 1000 for r in rr], y=[r["term"] for r in rr],
                                           orientation="h", marker=dict(color=GRAY, line=dict(color="#FFFFFF", width=2)),
                                           hovertemplate="<b>%{y}</b><br>기울기 %{x:.2f}‰/년<extra></extra>"))
                    fig.update_layout(height=max(300, 22 * len(rr) + 40), xaxis_title="‰ / 년",
                                      yaxis=dict(automargin=True), **PLOTLY_LAYOUT)
                    st.plotly_chart(fig, width="stretch", key="kci_fall_uni")
            with fb:
                st.markdown('<div class="sect">하강 구 (바이그램)</div>', unsafe_allow_html=True)
                fwat = st.toggle("수자원학회 쪽 구만", value=False, key="kci_bi_fall_water", disabled=not has_j11,
                                 help="끄면 토목 구조 분야(콘크리트·해석 등) 하강 구까지 모두") if has_j11 else False
                fbr = [r for r in b_water(b_falling, fwat) if not r.get("minor")][:20]
                if not fbr:
                    st.info("유의한 하강 구가 없습니다." if bg else "바이그램 결과가 아직 없습니다.")
                else:
                    rr = fbr[::-1]
                    fig = go.Figure(go.Bar(x=[b_slope(r) * 1000 for r in rr], y=[r["term"] for r in rr],
                                           orientation="h", marker=dict(color="#B8A6E3", line=dict(color="#FFFFFF", width=2)),
                                           customdata=[[r.get("j11_share", "-"), round((r.get("rate") or 0) * 100)] for r in rr],
                                           hovertemplate="<b>%{y}</b><br>기울기 %{x:.2f}‰/년 · 연 %{customdata[1]:+d}%"
                                                         "<br>수자원학회 비율 %{customdata[0]}<extra></extra>"))
                    fig.update_layout(height=max(300, 22 * len(rr) + 40), xaxis_title="‰ / 년",
                                      yaxis=dict(automargin=True), **PLOTLY_LAYOUT)
                    st.plotly_chart(fig, width="stretch", key="kci_fall_bi")

        # ── 탭5: K-water 소속 논문 (사이드 수집) ──
        with tab5:
            kw = load_json("kci_kwater.json")
            if not kw or not kw.get("total"):
                st.info("K-water 소속 논문 집계가 아직 없습니다 — kci-rising 워크플로가 KCI 전체에서 "
                        "소속(한국수자원공사·K-water 등)으로 모아 data_seed/kci_kwater.json을 만듭니다.")
            else:
                ky = [int(y) for y in kw["by_year"]]
                sh = kw.get("journal_share", {})
                recent = [kw["by_year"][str(y)] for y in ky if y >= max(ky) - 3]
                st.markdown('<div class="kpis">' + "".join(
                    f'<div class="kpi" style="border-left-color:{c}"><div class="k-val">{v}</div>'
                    f'<div class="k-lab">{l}</div><div class="k-sub">{s_}</div></div>'
                    for l, v, s_, c in [
                        ("K-water 소속 논문 (KCI 전체)", f"{kw['total']:,}", f"{min(ky)}–{max(ky)}", NAVY),
                        ("게재 학술지", f"{len(kw['journals'])}+", f"최다: {kw['journals'][0][0]}", BLUE),
                        ("최근 4년 연평균", f"{sum(recent) / max(1, len(recent)):.0f}편", "진행 중인 올해 포함", CYAN),
                        ("협업 기관", f"{len(kw['partners'])}+", f"최다: {kw['partners'][0][0][:18]}" if kw["partners"] else "", GREEN)]
                ) + '</div>', unsafe_allow_html=True)
                a, b = st.columns(2)
                with a:
                    st.markdown('<div class="sect">연도별 K-water 소속 논문 (KCI 전체)</div>', unsafe_allow_html=True)
                    fig = go.Figure(go.Bar(x=ky, y=[kw["by_year"][str(y)] for y in ky],
                                           marker=dict(color=NAVY, line=dict(color="#FFFFFF", width=2)),
                                           hovertemplate="%{x}년 · %{y}편<extra></extra>"))
                    fig.update_layout(height=300, **PLOTLY_LAYOUT)
                    fig.update_yaxes(gridcolor="#EEF2F7")
                    st.plotly_chart(fig, width="stretch")
                with b:
                    st.markdown('<div class="sect">학회지 안 K-water 비중 (%)</div>', unsafe_allow_html=True)
                    fig = go.Figure()
                    for i, (code, lab) in enumerate([("J11", "한국수자원학회논문집"), ("J12", "대한토목학회논문집")]):
                        d = sh.get(code, {})
                        yy = [int(y) for y in d]
                        fig.add_trace(go.Scatter(
                            x=yy, y=[d[str(y)]["kwater"] / d[str(y)]["n"] * 100 if d[str(y)]["n"] else 0 for y in yy],
                            mode="lines+markers", name=lab, line=dict(color=CAT8[i], width=2), marker=dict(size=8),
                            customdata=[[d[str(y)]["kwater"], d[str(y)]["n"]] for y in yy],
                            hovertemplate=lab + " %{x}년<br>%{y:.1f}% (%{customdata[0]}/%{customdata[1]}편)<extra></extra>"))
                    fig.update_layout(height=300, yaxis_title="%", yaxis_rangemode="tozero",
                                      legend=dict(orientation="h", y=-0.2), **PLOTLY_LAYOUT)
                    fig.update_yaxes(gridcolor="#EEF2F7")
                    st.plotly_chart(fig, width="stretch")
                a, b, c = st.columns(3)
                with a:
                    st.markdown('<div class="sect">게재 학술지 상위</div>', unsafe_allow_html=True)
                    st.dataframe(pd.DataFrame(kw["journals"][:15], columns=["학술지", "편수"]),
                                 hide_index=True, width="stretch")
                with b:
                    st.markdown('<div class="sect">K-water 내 소속 표기 상위</div>', unsafe_allow_html=True)
                    st.dataframe(pd.DataFrame(kw["kwater_units"][:15], columns=["소속", "저자 수"]),
                                 hide_index=True, width="stretch")
                with c:
                    st.markdown('<div class="sect">공동저자 기관 상위</div>', unsafe_allow_html=True)
                    st.dataframe(pd.DataFrame(kw["partners"][:15], columns=["기관", "저자 수"]),
                                 hide_index=True, width="stretch")
                hr = kw.get("human_review") or {}
                rl = hr.get("rules", {})
                st.caption(("사람 판정 반영: 결과 파일 {f}개 · 소속 포함 {ai} · 소속 제외 {ae} · 논문 포함 {pi} · 논문 제외 {pe}"
                            " · 엇갈림 {c} (엇갈린 항목은 규칙대로 둠). ").format(
                               f=hr.get("files", 0), ai=rl.get("affiliation_include", 0), ae=rl.get("affiliation_exclude", 0),
                               pi=rl.get("paper_include", 0), pe=rl.get("paper_exclude", 0), c=hr.get("conflicts", 0))
                           + "판정은 사이드바 HITL (전문가) 검토의 K-water 문헌 적정성(tools/kwater_hitl.html)으로 하고, 결과를 비공개 저장소 "
                             "review/overrides*.json으로 저장하면 다음 주간 분석부터 반영됨.")
                rf = kw.get("refresh") or {}
                _kst9 = dt.timezone(dt.timedelta(hours=9))
                if rf.get("fetched"):
                    _yrs = sorted(rf["fetched"])[-(rf.get("window_years") or 5):]
                    st.caption(f"🔄 최근 {rf.get('window_years') or 5}년은 매일 1년씩 다시 받아 최신화 (5일에 한 바퀴) — 연도별 마지막 수집: "
                               + " · ".join(f"{y} {dt.datetime.fromtimestamp(rf['fetched'][y], _kst9):%m-%d}" for y in _yrs))
                else:
                    st.caption("🔄 KCI 원천은 매일 최근 5년 가운데 1년씩 다시 받아 최신화 (5일에 한 바퀴) · 상승 주제 분석은 매주 월요일.")
                st.caption("범위 선택에서 'K-water 소속 논문'을 고르면 이 논문들만으로 상승 용어·묶음을 볼 수 있음. "
                           f"{kw['source']}")

        with st.expander("ℹ️ 방법과 한계"):
            st.markdown(f"""
- **방법:** {kr['method']}
- **용어:** 국문 제목+초록에서 Kiwi로 명사 추출, 띄어쓰기 없이 붙은 명사는 복합어로 묶음(예: 딥러닝, 유출량). 불용어(연구·분석·결과 등) 제외
- **구(바이그램):** 같은 분석에서 띄어 쓴 두 명사가 바로 이어지거나 ‘의’로 이어진 구(침수 피해, 하천의 수질 → 하천 수질), 붙여 쓴 형태도 같은 구로 셈. 붙여 쓴 형태가 단어 탭 상승 용어면 제외. 숫자 붙은 단위어·수식어(실제·일반 등)·제목/초록 경계는 구를 만들지 않음. 드물어서 준포아송 회귀(분모 = 그 해 논문 수, 과산포 보정) + BH FDR로 검정 — 누적 {bg.get('min_total', 8)}편·3개 연도 이상만
- **범위:** 대한토목학회논문집은 2012년까지 분책 A~D(구조·교통 등 포함)였다가 2013년 통합 → '수자원학회+토목학회' 범위에는 토목 전반 용어가 섞임
- **제외:** 국문 제목·초록이 없는 영문 전용 논문 {sd.get('excluded', {}).get('english_only', 0):,}편, 국문 초록 보유율 50% 미만 학회지·연도 {', '.join(sd.get('excluded', {}).get('low_abstract_years', [])) or '없음'}. 영문 용어는 대문자 약어(LSTM·SWAT 등)만 셈
- **해석:** 통계적으로 유의한 '추세 후보'이며, 묶음 이름·의미는 전문가 검토가 필요
- **데이터:** {kr['source']}
""")

# ═══════════════ 페이지: 지식자산 현황 (WCS 연구보고서·논문·특허) ═══════════════
elif page == ASSET_PAGE:
    astp.render(load_json, PLOTLY_LAYOUT)

# ═══════════════ 페이지: K-water 비교 (KCI 최근 5년, 연구소 분야별) ═══════════════
elif page == KCIKW_PAGE:
    kcip.render(load_json("kci_inst.json") or {}, summary.get("inst_names", {}), INST_COLORS, PLOTLY_LAYOUT)

# ═══════════════ 페이지: 피인용 질 (피인용 상위 10% 비중) ═══════════════
elif page == CIT_PAGE:
    citp.render(load_json("openalex_trends.json") or {}, summary.get("inst_names", {}), INST_COLORS, PLOTLY_LAYOUT)

# ═══════════════ 페이지: 상승 연구주제 (openalex 분석 연동) ═══════════════
elif page == OA_PAGE:
    oarp.render(load_json, PLOTLY_LAYOUT)

# ═══════════════ 페이지: 라벨링 로그 ═══════════════
elif page == "🏷️ 라벨링 로그":
    st.markdown('<div class="sect">🏷️ 라벨링 파이프라인 실행 로그</div>', unsafe_allow_html=True)
    st.caption("수집(하루 1회): 전진 45일 스윕 + 역사 1년/일 후진(2025→2015) · 라벨링: 6시간마다 자동")
    runs = load_labels_jsonl("pipeline_runs.jsonl")
    if not runs:
        st.info("아직 실행 로그가 없습니다 — 파이프라인 v2 첫 실행 후 이곳에 기록이 쌓입니다.")
    else:
        df_r = pd.DataFrame(runs)
        for c in ["forward", "hist", "backfilled", "extracted", "assigned", "total", "duration_s"]:
            if c not in df_r:
                df_r[c] = 0
            df_r[c] = pd.to_numeric(df_r[c], errors="coerce").fillna(0).astype(int)
        if "hist_year" not in df_r:
            df_r["hist_year"] = None
        df_r["collected"] = df_r["forward"] + df_r["hist"]

        def _kst(s):
            try:
                return (dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ")
                        + dt.timedelta(hours=9)).strftime("%m-%d %H:%M")
            except Exception:
                return str(s)
        df_r["시각(KST)"] = df_r["ts"].map(_kst)

        last = df_r.iloc[-1]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("최근 실행 (KST)", last["시각(KST)"])
        c2.metric("이번 신규 라벨", f"+{int(last['assigned'])}")
        c3.metric("누적 라벨", f"{int(last['total']):,}건")
        c4.metric("총 실행 횟수", f"{len(df_r)}회")

        a, b = st.columns(2)
        with a:
            st.markdown('<div class="sect">누적 라벨 성장</div>', unsafe_allow_html=True)
            fig = go.Figure(go.Scatter(x=df_r["시각(KST)"], y=df_r["total"],
                                       mode="lines+markers", fill="tozeroy",
                                       line=dict(color=BLUE, width=2)))
            fig.update_layout(height=300, **PLOTLY_LAYOUT)
            st.plotly_chart(fig, width="stretch")
        with b:
            st.markdown('<div class="sect">회차별 처리량</div>', unsafe_allow_html=True)
            fig = go.Figure()
            fig.add_trace(go.Bar(name="수집+", x=df_r["시각(KST)"], y=df_r["collected"],
                                 marker_color="#0EA5E9"))
            fig.add_trace(go.Bar(name="라벨+", x=df_r["시각(KST)"], y=df_r["assigned"],
                                 marker_color=BLUE))
            fig.update_layout(barmode="group", height=300,
                              legend=dict(orientation="h", y=1.15), **PLOTLY_LAYOUT)
            st.plotly_chart(fig, width="stretch")

        st.markdown('<div class="sect">실행 이력 (최근 30회)</div>', unsafe_allow_html=True)
        show = df_r.tail(30).iloc[::-1][["시각(KST)", "forward", "hist_year", "hist", "backfilled",
                                         "extracted", "assigned", "total", "duration_s"]]
        show = show.rename(columns={"forward": "전진+", "hist_year": "역사연도", "hist": "역사+", "backfilled": "초록+",
                                    "extracted": "추출+", "assigned": "배정+",
                                    "total": "누적", "duration_s": "소요(초)"})
        st.dataframe(show, hide_index=True, width="stretch")

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

# ═══════════════ 페이지: 수집 달성도 (목표 대비 · 날짜별 추이 · 실패 기록) ═══════════════
elif page == AC_PAGE:
    STAGE_KO = {"collect": "수집", "backfill": "초록 보강", "extract": "대상·문제 추출", "assign": "도메인 배정",
                "workflow": "워크플로", "data_quality": "데이터 품질"}
    STAGE_COL = {"collect": "#2a78d6", "backfill": "#eb6834", "extract": "#1baf7a", "assign": "#4a3aa7",
                 "workflow": "#e34948", "data_quality": "#eda100"}
    SRC_KO = {"pipeline": "파이프라인", "audit": "자동 점검", "github": "GitHub Actions", "retro": "사후 진단"}
    tg = load_json("collection_targets.json") or {}
    rule = tg.get("status_rule", {"achieved": 1.0, "near": 0.8})
    daily = load_labels_jsonl("metrics/daily.jsonl")
    fails = load_labels_jsonl("metrics/failures.jsonl")
    resolved = {r.get("key"): r for r in load_labels_jsonl("metrics/resolutions.jsonl") if r.get("key")}

    def status(ach):
        if ach is None:
            return "–", GRAY
        if ach >= rule.get("achieved", 1.0):
            return "달성", GREEN
        if ach >= rule.get("near", 0.8):
            return "근접", AMBER
        return "미달", RED

    def ratio(tot, m):
        n, d = tot.get(m["num"]), tot.get(m["den"])
        return (n / d) if (n is not None and d) else None

    st.markdown('<div class="sect">🎯 수집 달성도 — 목표 대비 현황 · 날짜별 추이 · 실패 기록</div>', unsafe_allow_html=True)
    st.caption("목표는 data_seed/collection_targets.json에서 고칩니다. 수치는 라벨링 파이프라인이 회차마다(6시간) "
               "labels/metrics/에 남기는 스냅샷이며, 2026-07-28 ~ 10-13 구간은 실행 로그로 재구성한 추정치입니다.")

    if not daily:
        st.info("달성도 스냅샷이 아직 없습니다 — 라벨링 파이프라인 다음 회차(6시간 주기)부터 labels/metrics/daily.jsonl이 쌓입니다.")
    else:
        snaps = [r for r in daily if r.get("source") == "snapshot"]
        last = snaps[-1] if snaps else daily[-1]
        T_ = last.get("totals", {})
        mets = tg.get("metrics", [])
        open_f = [f for f in fails if not (f.get("resolved") or resolved.get(f.get("key"), {}).get("resolved"))]
        items_f = sum(f.get("count", 0) for f in fails if f.get("stage") != "workflow")
        kp = [("연구소 관련 문헌", f"{T_.get('collected', 0):,}", "1차 + 확장 수집", BLUE),
              ("라벨 반영", f"{T_.get('assigned', 0):,}",
               f"{T_.get('assigned', 0) / max(1, T_.get('collected', 1)) * 100:.0f}% · 도메인 배정 완료", NAVY),
              ("실패 기록", f"{len(fails):,}건", f"미해결 {len(open_f)} · 영향 문헌 {items_f:,}편", RED if open_f else GREEN),
              ("마지막 스냅샷", (last.get("ts") or "")[:16].replace("T", " "), "UTC · 6시간 주기", CYAN)]
        st.markdown('<div class="kpis">' + "".join(
            f'<div class="kpi" style="border-left-color:{c}"><div class="k-val" style="font-size:1.35rem">{v}</div>'
            f'<div class="k-lab">{l}</div><div class="k-sub">{s_}</div></div>' for l, v, s_, c in kp) + '</div>',
            unsafe_allow_html=True)

        # ── 1. 지표별 목표 대비 (불릿 차트: 막대 = 현재, 세로선 = 목표) ──
        st.markdown('<div class="sect">지표별 목표 대비 달성 현황</div>', unsafe_allow_html=True)
        rows_m = []
        for m in mets:
            r_ = ratio(T_, m)
            ach = (r_ / m["target"]) if (r_ is not None and m.get("target")) else None
            lab, colr = status(ach)
            rows_m.append((m, r_, ach, lab, colr))
        if rows_m:
            rr = rows_m[::-1]
            fig = go.Figure()
            fig.add_trace(go.Bar(
                x=[(r_ or 0) * 100 for _, r_, _, _, _ in rr], y=[m["label"] for m, *_ in rr], orientation="h",
                marker=dict(color=[c for *_, c in rr]), showlegend=False,
                text=[f"{(r_ or 0) * 100:.1f}%  ·  {lab}" for _, r_, _, lab, _ in rr], textposition="outside",
                customdata=[[T_.get(m["num"], 0), T_.get(m["den"], 0), m["target"] * 100, m.get("desc", "")] for m, *_ in rr],
                hovertemplate="<b>%{y}</b><br>%{customdata[0]:,} / %{customdata[1]:,} = %{x:.1f}%"
                              "<br>목표 %{customdata[2]:.0f}%<br>%{customdata[3]}<extra></extra>"))
            fig.add_trace(go.Scatter(
                x=[m["target"] * 100 for m, *_ in rr], y=[m["label"] for m, *_ in rr], mode="markers", name="목표",
                marker=dict(symbol="line-ns", size=30, line=dict(width=3, color="#0F2744")),
                hovertemplate="목표 %{x:.0f}%<extra></extra>"))
            fig.update_layout(height=60 * len(rr) + 70, xaxis=dict(range=[0, 118], title="%", gridcolor="#EEF2F7"),
                              yaxis=dict(automargin=True), bargap=0.35, legend=dict(orientation="h", y=1.1),
                              **PLOTLY_LAYOUT)
            st.plotly_chart(fig, width="stretch")
            st.caption("막대 = 현재 비율, 검은 세로선 = 목표. 색: 초록 달성 · 주황 근접(목표의 80% 이상) · 빨강 미달")

        # ── 2. 연구소별 ──
        st.markdown('<div class="sect">연구소별 달성 현황</div>', unsafe_allow_html=True)
        inst_names = summary.get("inst_names", {})
        tgt = {m["key"]: m["target"] for m in mets}
        irows = []
        for code, v in sorted((last.get("institutes") or {}).items()):
            ab = v["abstract_ok"] / max(1, v["collected"])
            lc = v["assigned"] / max(1, v["collected"])
            irows.append({"연구소": f"{code} {inst_names.get(code, '')}", "관련 문헌": v["collected"],
                          "1차 수집 %": round(v["primary"] / max(1, v.get("primary_target") or v["primary"]) * 100, 1),
                          "초록 확보 %": round(ab * 100, 1),
                          "추출 % (초록 대비)": round(v["extracted"] / max(1, v["abstract_ok"]) * 100, 1),
                          "라벨 반영 %": round(lc * 100, 1),
                          "판정": status(min(ab / tgt.get("abstract", .8), lc / tgt.get("label_cover", .7)))[0],
                          "보강 실패 의심 (편)": v.get("empty_block_rows", 0)})
        if irows:
            pc = lambda t_: st.column_config.ProgressColumn(t_, format="%.0f%%", min_value=0, max_value=100)
            st.dataframe(pd.DataFrame(irows), hide_index=True, width="stretch",
                         column_config={"1차 수집 %": pc("1차 수집"), "초록 확보 %": pc("초록 확보"),
                                        "추출 % (초록 대비)": pc("추출 (초록 대비)"), "라벨 반영 %": pc("라벨 반영"),
                                        "관련 문헌": st.column_config.NumberColumn("관련 문헌", format="%d")})
            st.caption(f"판정 = 초록 확보(목표 {tgt.get('abstract', .8) * 100:.0f}%)와 라벨 반영(목표 "
                       f"{tgt.get('label_cover', .7) * 100:.0f}%) 중 낮은 쪽 기준 · 보강 실패 의심 = 초록 빈 값이 50편 이상 연속인 행")

        # ── 3. 날짜별 추이 + 같은 날짜축의 실패 ──
        st.markdown('<div class="sect">날짜별 추이와 실패 발생</div>', unsafe_allow_html=True)
        by_date = {}
        for r in daily:                                   # 날짜별 마지막 기록
            by_date[r.get("date") or (r.get("ts") or "")[:10]] = r
        dates = sorted(d for d in by_date if d)
        as_count = st.toggle("건수로 보기", value=False, key="ac_counts")
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.68, 0.32], vertical_spacing=0.06)
        if as_count:
            for key, lab, colr in (("collected", "관련 문헌", BLUE), ("abstract_ok", "초록 확보", CYAN),
                                   ("assigned", "라벨 반영", NAVY)):
                fig.add_trace(go.Scatter(x=dates, y=[by_date[d]["totals"].get(key) for d in dates], name=lab,
                                         mode="lines", line=dict(color=colr, width=2.5), connectgaps=True), row=1, col=1)
            fig.update_yaxes(title_text="편", row=1, col=1)
        else:
            for key, colr in (("abstract", CYAN), ("label_cover", NAVY)):
                m = next((x for x in mets if x["key"] == key), None)
                if not m:
                    continue
                ys = [(ratio(by_date[d]["totals"], m) or 0) * 100 if ratio(by_date[d]["totals"], m) is not None else None
                      for d in dates]
                fig.add_trace(go.Scatter(x=dates, y=ys, name=m["label"], mode="lines", line=dict(color=colr, width=2.5),
                                         connectgaps=True, hovertemplate="%{x} · %{y:.1f}%<extra>" + m["label"] + "</extra>"),
                              row=1, col=1)
                fig.add_trace(go.Scatter(x=[dates[0], dates[-1]], y=[m["target"] * 100] * 2, mode="lines",
                                         name=f"{m['label']} 목표", line=dict(color=colr, width=1.2, dash="dash"),
                                         hoverinfo="skip"), row=1, col=1)
            fig.update_yaxes(title_text="%", range=[0, 105], row=1, col=1)
        for stg in STAGE_KO:                               # 같은 날짜축에 실패 영향 규모
            agg = Counter()
            for f in fails:
                if f.get("stage") == stg and f.get("date"):
                    agg[f["date"]] += max(1, f.get("count", 1))
            if agg:
                fig.add_trace(go.Bar(x=list(agg), y=list(agg.values()), name=f"실패 · {STAGE_KO[stg]}",
                                     marker_color=STAGE_COL[stg],
                                     hovertemplate="%{x}<br>%{y:,}" + ("회" if stg == "workflow" else "편") + "<extra>"
                                                   + STAGE_KO[stg] + "</extra>"), row=2, col=1)
        fig.update_yaxes(title_text="실패 규모", type="log", range=[-0.3, 4.2], row=2, col=1)
        fig.update_layout(height=560, barmode="stack", legend=dict(orientation="h", y=-0.12), hovermode="x unified",
                          **PLOTLY_LAYOUT)
        fig.update_xaxes(gridcolor="#EEF2F7")
        fig.update_yaxes(gridcolor="#EEF2F7")
        st.plotly_chart(fig, width="stretch")
        snap_from = snaps[0]["date"] if snaps else None
        st.caption("위: 목표 대비 비율(점선 = 목표) · 아래: 같은 날짜의 실패 규모(로그 눈금, 워크플로는 회 · 나머지는 영향 문헌 편). "
                   + (f"{snap_from} 이전은 실행 로그 재구성 추정치, 이후는 회차별 실측 스냅샷." if snap_from else ""))

        # ── 4. 실패 기록 · 통계 ──
        st.markdown('<div class="sect">🧯 실패 기록 · 통계</div>', unsafe_allow_html=True)
        if not fails:
            st.success("기록된 실패가 없습니다.")
        else:
            today_ = dt.datetime.now(dt.timezone.utc).date()
            recent30 = [f for f in fails if f.get("date") and (today_ - dt.date.fromisoformat(f["date"])).days <= 30]
            a, b = st.columns([3, 2])
            with a:
                srows = []
                for stg in STAGE_KO:
                    fs = [f for f in fails if f.get("stage") == stg]
                    if fs:
                        srows.append({"단계": STAGE_KO[stg], "기록 (건)": len(fs),
                                      "영향 (편 · 회)": sum(f.get("count", 0) for f in fs),
                                      "최근 30일 (건)": sum(1 for f in recent30 if f.get("stage") == stg),
                                      "미해결 (건)": sum(1 for f in open_f if f.get("stage") == stg),
                                      "최근 발생": max(f.get("date", "") for f in fs)})
                st.dataframe(pd.DataFrame(srows), hide_index=True, width="stretch")
            with b:
                mon = Counter((f.get("date") or "")[:7] for f in fails if f.get("date"))
                months = sorted(mon)
                fig = go.Figure(go.Bar(x=months, y=[mon[m_] for m_ in months], marker_color=RED,
                                       hovertemplate="%{x} · %{y}건<extra></extra>"))
                fig.update_layout(height=230, yaxis_title="건", **PLOTLY_LAYOUT)
                fig.update_yaxes(gridcolor="#EEF2F7")
                st.plotly_chart(fig, width="stretch")
                st.caption("월별 실패 기록 건수")
            pick = st.multiselect("단계", [STAGE_KO[s_] for s_ in STAGE_KO if any(f.get("stage") == s_ for f in fails)],
                                  placeholder="전체")
            rev_ko = {v: k for k, v in STAGE_KO.items()}
            sel_st = {rev_ko[p] for p in pick} or set(STAGE_KO)
            st.dataframe(pd.DataFrame([{
                "날짜": f.get("date"), "단계": STAGE_KO.get(f.get("stage"), f.get("stage")),
                "연구소": f.get("inst") or "전체", "규모": f.get("count", 0), "내용": f.get("detail", ""),
                "출처": SRC_KO.get(f.get("source"), f.get("source")),
                "상태": "해결" if (f.get("resolved") or resolved.get(f.get("key"), {}).get("resolved")) else "미해결",
                "링크": f.get("url") or ""} for f in sorted(fails, key=lambda x: x.get("ts", ""), reverse=True)
                if f.get("stage") in sel_st]), hide_index=True, width="stretch", height=360,
                column_config={"링크": st.column_config.LinkColumn("링크", display_text="열기")})
            st.caption("출처: 파이프라인 = 회차 중 호출 실패 · 자동 점검 = 데이터 이상(초록 빈 값 연속 등) · GitHub Actions = 실패한 "
                       "워크플로 회차 · 사후 진단 = 과거 사고를 나중에 기록. 해결 처리는 labels/metrics/resolutions.jsonl에 "
                       '{"key": …, "resolved": true} 한 줄을 추가합니다.')

        # ── 5. 자료원별 ──
        with st.expander("자료원별 목표 대비 (ALIO · 특허 · 기사 · KCI)"):
            kr_ = load_json("kci_rising.json") or {}
            kc_ = (load_json("kci_counts.json") or {}).get("journals", {})
            sd_ = (kr_.get("scopes") or {}).get("J11+J12") or {}
            yrs_ = set(str(y) for y in sd_.get("years", []))
            kci_den = sum(sd_.get("denominator", []))
            kci_tot = sum(n for j in ("J11", "J12") for y, n in (kc_.get(j, {}).get("by_year") or {}).items() if y in yrs_)
            cur_src = {"alio": T.get("alio_collected", 0), "alio_parsed": T.get("alio_parsed_ok", 0),
                       "patents": T.get("patents", 0), "articles": T.get("articles", 0)}
            srow = []
            for s_ in tg.get("sources", []):
                if s_["key"] == "kci":
                    r_ = kci_den / kci_tot if kci_tot else None
                    ach = r_ / s_["target_ratio"] if r_ is not None else None
                    srow.append({"자료원": s_["label"], "현재": f"{kci_den:,} / {kci_tot:,}편", "달성률 %": round((r_ or 0) * 100, 1),
                                 "목표": f"{s_['target_ratio'] * 100:.0f}%", "판정": status(ach)[0], "비고": s_.get("note", "")})
                else:
                    c_ = cur_src.get(s_["key"], 0)
                    srow.append({"자료원": s_["label"], "현재": f"{c_:,}", "달성률 %": round(c_ / s_["target"] * 100, 1),
                                 "목표": f"{s_['target']:,}", "판정": status(c_ / s_["target"])[0], "비고": s_.get("note", "")})
            if srow:
                st.dataframe(pd.DataFrame(srow), hide_index=True, width="stretch",
                             column_config={"달성률 %": st.column_config.ProgressColumn("달성률", format="%.0f%%",
                                                                                     min_value=0, max_value=100)})

# ═══════════════ 페이지: 연구소 지식노트 (연구소 단위 그룹 작업공간) ═══════════════
elif page == KN_PAGE:
    import networkx as _nx
    KN8 = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
    RING = "#D97706"                                          # 국내 상승 용어와 겹친 용어 표시
    SCOPE_LABEL = {"J11": "수자원학회 단독", "J11+J12": "수자원학회 + 토목학회", "KWATER": "K-water 소속 논문"}
    inst_names = summary.get("inst_names", {})
    codes = sorted(inst_names)

    st.markdown('<div class="sect">📒 연구소 지식노트 — 연구소 단위 그룹 작업공간</div>', unsafe_allow_html=True)
    st.caption("연구소 관련 문헌(연구소 키워드로 모은 OpenAlex 논문 — 연구소가 쓴 논문이 아님)의 대상·문제 추출과 "
               "W 도메인 라벨(라벨링 파이프라인 산출물)로 연구소마다 지식노트를 만듭니다. "
               "추가 LLM 호출 없음 · 개인별 노트(관심 키워드·메모)는 다음 단계")

    if not codes:
        st.info("연구소 정보가 없습니다 (summary.json의 inst_names 확인).")
    else:
        qp = st.query_params.get("inst")
        if "kn_inst" not in st.session_state:
            st.session_state["kn_inst"] = qp if qp in codes else ("INST-07" if "INST-07" in codes else codes[0])
        sel = st.segmented_control("연구소", codes, key="kn_inst", label_visibility="collapsed",
                                   format_func=lambda c: inst_names[c])
        sel = sel if sel in codes else (qp if qp in codes else codes[0])
        if st.query_params.get("inst") != sel:
            st.query_params["inst"] = sel
        iname = inst_names[sel]

        kr = load_json("kci_rising.json") or {}
        scopes = list((kr.get("scopes") or {}).keys())
        cA, cB, cC = st.columns([3, 2, 2])
        cA.caption(f"이 화면 주소(…`?inst={sel}`)를 즐겨찾기하면 **{iname}** 화면으로 바로 열립니다.")
        water_only = cB.toggle("물 도메인 문헌만 (미분류 제외)", value=True,
                               help="W 도메인 라벨이 '미분류'인 문헌(물 밖 주제로 들어온 수집분)을 뺍니다.")
        scope_key = cC.selectbox("비교할 국내 상승 용어", scopes,
                                 index=scopes.index("J11+J12") if "J11+J12" in scopes else 0,
                                 format_func=lambda s_: SCOPE_LABEL.get(s_, s_)) if scopes else None
        scope = (kr.get("scopes") or {}).get(scope_key, {}) if scope_key else {}
        scope_label = SCOPE_LABEL.get(scope_key, scope_key or "-")

        with st.spinner(f"{iname} 관련 문헌·라벨을 불러오는 중… (처음 한 번만 수 초)"):
            core = dcache.inst_core(sel)                  # 논문 메타·추출·도메인 4개 파일 동시 받기 (라벨 판정과 공용 캐시)
            papers, extract, domain = core["papers"], core["extract"], core["domain"]
        dsum_kn = load_labels("domain/domain_summary_v0.1.json") or {}
        DN = {**kn.DOMAIN_NAMES, **{k: v.get("name", k) for k, v in (dsum_kn.get("domains") or {}).items()}}

        recs = kn.build_corpus(papers, extract, domain, water_only=water_only)
        if not recs:
            st.info(f"{iname}의 라벨링된 문헌이 아직 없습니다 — 라벨링 파이프라인(6시간 주기)이 대상·문제를 추출하면 채워집니다.")
        else:
            net = kn.topic_network(recs)
            comms = net["communities"]
            touch = kn.rising_touchpoints(recs, scope) if scope else []
            btouch = kn.bigram_touchpoints(recs, scope, include_minor=True) if scope else []
            gaps = kn.gap_candidates(touch, scope) if scope else []
            rising_hit = {t["term"] for t in touch if t["n_inst"]}
            today_kst = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date()
            latest = max((kn._parse_date(r["date"]) for r in recs if kn._parse_date(r["date"])), default=today_kst)
            anchor = min(today_kst, latest)
            r30 = kn.recent(recs, anchor, 30)
            col = INST_COLORS.get(sel, NAVY)

            kpis = [("연구소 관련 문헌", f"{len({p.get('id') for p in papers}):,}", "OpenAlex · 연구소 키워드로 수집", col),
                    ("노트 대상", f"{len(recs):,}", "대상·문제 추출 + 물 관련", BLUE),
                    ("토픽 묶음", f"{len(comms)}", "핵심어 공출현 · Louvain", NAVY),
                    ("상승 용어 접점", f"{len(rising_hit)}", f"KCI {scope_label}", CYAN),
                    ("최근 30일", f"{len(r30)}", f"기준 {anchor:%m-%d} (최신 발행일)", GREEN)]
            st.markdown('<div class="kpis">' + "".join(
                f'<div class="kpi" style="border-left-color:{c}"><div class="k-val">{v}</div>'
                f'<div class="k-lab">{l}</div><div class="k-sub">{s_}</div></div>'
                for l, v, s_, c in kpis) + '</div>', unsafe_allow_html=True)

            t1, t2, t3, tb, t4, t5 = st.tabs(["🗺️ 지식 지도", "📒 토픽 노트", "📈 상승 용어 접점·공백",
                                              "🔗 상승 구(바이그램)", "🗞️ 최근 브리핑", "⬇️ 노트 내보내기"])
            cidx = {c["id"]: i for i, c in enumerate(comms)}

            # ── 탭1: 지식 지도 (연구소 핵심어 네트워크) ──
            with t1:
                if not net["edges"]:
                    st.info("핵심어끼리 함께 나온 문헌이 적어 지도를 그릴 수 없습니다.")
                else:
                    G = _nx.Graph()
                    for u, v, w, c in net["edges"]:
                        G.add_edge(u, v, weight=w, count=c)
                    pos = _nx.spring_layout(G, weight="weight", seed=42, k=2.4 / math.sqrt(max(len(G), 1)), iterations=120)
                    dfm = {n["term"]: n["df"] for n in net["nodes"]}
                    wmax = max(w for _, _, w, _ in net["edges"]) or 1
                    fig = go.Figure()
                    for lo, hi, width in ((0, .34, 0.6), (.34, .67, 1.6), (.67, 1.01, 3.0)):   # 굵기 3단계로 묶어 그리기
                        xs, ys = [], []
                        for u, v, w, _ in net["edges"]:
                            if lo <= w / wmax < hi:
                                xs += [pos[u][0], pos[v][0], None]
                                ys += [pos[u][1], pos[v][1], None]
                        if xs:
                            fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines", hoverinfo="skip", showlegend=False,
                                                     line=dict(color="#C9D6E6", width=width)))
                    dmax = max(dfm.values()) or 1
                    for c in comms:
                        ts = [t for t in c["terms"] if t in pos]
                        i = cidx[c["id"]]
                        fig.add_trace(go.Scatter(
                            x=[pos[t][0] for t in ts], y=[pos[t][1] for t in ts], mode="markers+text",
                            text=ts, textposition="top center", textfont=dict(size=11, color="#0F2744"),
                            name=f"{c['id']} {c['label']}",
                            marker=dict(size=[9 + 26 * (dfm[t] / dmax) ** 0.5 for t in ts],
                                        color=KN8[i] if i < len(KN8) else GRAY,
                                        line=dict(color=[RING if t in rising_hit else "#FFFFFF" for t in ts],
                                                  width=[3.5 if t in rising_hit else 1.5 for t in ts])),
                            customdata=[[dfm[t], "국내 상승 용어와 겹침" if t in rising_hit else ""] for t in ts],
                            hovertemplate="<b>%{text}</b><br>문헌 %{customdata[0]}편<br>%{customdata[1]}<extra></extra>"))
                    fig.update_layout(height=600, xaxis=dict(visible=False), yaxis=dict(visible=False),
                                      legend=dict(orientation="h", y=-0.04), **PLOTLY_LAYOUT)
                    st.plotly_chart(fig, width="stretch")
                    st.caption("점 크기 = 그 핵심어가 나온 문헌 수 · 선 굵기 = 함께 나온 정도(코사인 정규화) · 색 = Louvain 묶음 · "
                               "주황 테두리 = 국내 학회지 상승 용어와 겹침. 묶음 이름은 대표 용어 3개를 이은 임시 이름이며 해석은 연구소 검토 몫.")

            # ── 탭2: 토픽 노트 ──
            with t2:
                if not comms:
                    st.info("토픽 묶음이 없습니다.")
                else:
                    by_id = {r["id"]: r for r in recs}
                    cols = st.columns(2)
                    for c in comms:
                        i = cidx[c["id"]]
                        cc = KN8[i] if i < len(KN8) else GRAY
                        dc = Counter(by_id[p]["domain"] for p in c["papers"] if by_id[p]["domain"])
                        chips = " ".join(
                            f'<span class="gchip" style="background:{"#FDEBD3" if t in rising_hit else "#F1F5FA"};'
                            f'color:#0F2744;display:inline-block;white-space:nowrap">{t}</span>' for t in c["terms"][:14])
                        dtxt = " · ".join(f"{d} {DN.get(d, d)} {n}" for d, n in dc.most_common(3))
                        cols[i % 2].markdown(
                            f'<div class="card" style="border-left:6px solid {cc};margin-bottom:10px">'
                            f'<b>{c["id"]} · {c["label"]}</b> <span class="note">· 문헌 {len(c["papers"])}편 · 용어 {c["size"]}개</span>'
                            f'<div style="margin-top:6px;line-height:2">{chips}</div>'
                            f'<div class="note" style="margin-top:4px">{dtxt}</div></div>', unsafe_allow_html=True)
                    st.caption("주황 칩 = 국내 학회지 상승 용어와 겹치는 용어")
                    pick = st.selectbox("토픽 노트 열기", [c["id"] for c in comms],
                                        format_func=lambda x: f"{x} · {comms[cidx[x]]['label']} ({len(comms[cidx[x]]['papers'])}편)")
                    pc = comms[cidx[pick]]
                    rows = sorted((by_id[p] for p in pc["papers"]), key=lambda r: (-r["cited"], r["date"]))
                    st.dataframe(pd.DataFrame([{
                        "제목": r["title"], "연도": r["year"], "대상": r["object"], "문제": r["problem"],
                        "도메인": f"{r['domain']} {DN.get(r['domain'], '')}" if r["domain"] else "-",
                        "피인용": r["cited"], "DOI": r["doi"] or None} for r in rows]),
                        hide_index=True, width="stretch", height=380,
                        column_config={"DOI": st.column_config.LinkColumn("DOI", display_text="🔗 열기")})
                    with st.expander("노트 미리보기 (마크다운 · 내보내기 파일과 같은 형식)"):
                        st.code(kn.topic_note_preview(pc, recs, sel, DN, rising_hit), language="markdown")

            # ── 탭3: 상승 용어 접점·결합 공백 후보 ──
            with t3:
                if not touch:
                    st.info("비교할 국내 상승 용어 결과가 없습니다 (kci_rising.json).")
                else:
                    hit = sorted([t for t in touch if t["n_inst"]], key=lambda t: (-t["n_inst"], -t["sen"]))
                    a, b = st.columns([3, 2])
                    with a:
                        st.markdown(f'<div class="sect">국내 상승 용어 × {iname} 관련 문헌</div>', unsafe_allow_html=True)
                        rr = hit[:20][::-1]
                        if rr:
                            fig = go.Figure(go.Bar(
                                x=[t["n_inst"] for t in rr], y=[t["term"] for t in rr], orientation="h",
                                marker=dict(color=col, line=dict(color="#FFFFFF", width=2)),
                                customdata=[[round(t["sen"] * 1000, 2), t["recent_docs"], round(t["share"] * 100, 1)] for t in rr],
                                hovertemplate="<b>%{y}</b><br>연구소 관련 문헌 %{x}편 (%{customdata[2]}%)"
                                              "<br>국내 기울기 %{customdata[0]}‰/년 · 최근3년 %{customdata[1]}편<extra></extra>"))
                            fig.update_layout(height=max(320, 22 * len(rr) + 40), xaxis_title="연구소 관련 문헌 수",
                                              yaxis=dict(automargin=True), bargap=0.25, **PLOTLY_LAYOUT)
                            fig.update_xaxes(gridcolor="#EEF2F7")
                            st.plotly_chart(fig, width="stretch")
                    with b:
                        st.markdown('<div class="sect">아직 연구소 관련 문헌에 없는 상승 용어</div>', unsafe_allow_html=True)
                        miss = sorted([t for t in touch if not t["n_inst"]], key=lambda t: -t["sen"])[:24]
                        if miss:
                            st.markdown('<div style="line-height:2.2">' + " ".join(
                                f'<span class="gchip" style="background:#F1F5FA;color:#0F2744;display:inline-block;white-space:nowrap">{t["term"]}</span>'
                                for t in miss) + "</div>", unsafe_allow_html=True)
                            st.caption("국내 학회지에서는 오르는데 이 연구소 관련 문헌의 대상·문제에는 나오지 않는 용어 (기울기 순). "
                                       "수집 키워드 보강 후보로도 볼 수 있음.")
                        else:
                            st.caption("모든 상승 용어가 연구소 관련 문헌에 한 번 이상 나옵니다.")

                    st.markdown('<div class="sect">🧩 결합 공백 후보 — 각각은 다루지만 함께 다룬 문헌이 없는 조합</div>',
                                unsafe_allow_html=True)
                    if not gaps:
                        st.info("조건에 맞는 조합이 없습니다 (두 용어 모두 연구소 관련 문헌 2편 이상 + 국내 네트워크에 있는 용어).")
                    else:
                        by_id = {r["id"]: r for r in recs}
                        gcols = st.columns(2)
                        for i, g in enumerate(gaps):
                            with gcols[i % 2]:
                                st.markdown(
                                    f'<div class="card" style="border-left:6px solid {RING};margin-bottom:6px">'
                                    f'<b>{i + 1}. {g["a"]} × {g["b"]}</b>'
                                    f'<div class="note" style="margin-top:4px">연구소 관련 문헌 {g["a"]} {g["n_a"]}편 · {g["b"]} {g["n_b"]}편 · '
                                    f'<b>함께 0편</b> · 국내 학회지 최근 5년 함께 {g["kci_co"]}편'
                                    f'{" · 국내에서도 서로 다른 묶음" if g["cross"] else ""}</div></div>',
                                    unsafe_allow_html=True)
                                with st.expander("근거 문헌 보기"):
                                    for term, ids in ((g["a"], g["ids_a"]), (g["b"], g["ids_b"])):
                                        st.markdown(f"**{term}**")
                                        for pid in ids[:3]:
                                            r = by_id[pid]
                                            st.markdown(f"- [{r['title'][:90]}]({r['doi'] or '#'}) · {r['year'] or '-'}"
                                                        f"  \n  <span class='note'>대상: {r['object']} / 문제: {r['problem']}</span>",
                                                        unsafe_allow_html=True)
                        st.caption("점수 = 두 용어 중 적은 쪽 문헌 수 × 국내 최근 빈도 ÷ (1 + 국내 공출현) · 국내 묶음이 다르면 가중. "
                                   "‘상승 연구주제 탐지’ 파이프라인의 공출현 관계를 연구소 단위로 뒤집어 본 후보이며, 의미 판단은 전문가 검토가 필요합니다.")
                    with st.expander("표로 보기 — 상승 용어 전체"):
                        st.dataframe(pd.DataFrame([{
                            "용어": t["term"], "국내 기울기(‰/년)": round(t["sen"] * 1000, 2), "국내 최근3년": t["recent_docs"],
                            "연구소 관련 문헌": t["n_inst"], "비율(%)": round(t["share"] * 100, 1)}
                            for t in sorted(touch, key=lambda t: (-t["n_inst"], -t["sen"]))]),
                            hide_index=True, width="stretch")

            # ── 탭3-2: 상승 구(바이그램) — 한 단어로는 흔한 말도 두 단어 구로 보면 쓰임이 드러남 ──
            with tb:
                bmeta = (scope or {}).get("bigram") or {}
                if not bmeta:
                    st.info("이 범위에는 아직 바이그램 분석 결과가 없습니다 — 주간 KCI 분석(kci-rising)이 다음에 돌면 채워집니다.")
                else:
                    yrs = scope.get("years") or []
                    st.caption("국내 학회지 국문 제목·초록에서 **두 단어로 된 구**(띄어 쓴 두 명사가 바로 이어지거나 ‘의’로 이어진 것 — "
                               "예: 침수 피해, 하천의 수질 → 하천 수질, 붙여 쓴 ‘하천수질’도 같은 구로 셈)의 비중이 해마다 오르는지 봅니다. "
                               "구는 드물어 연도별 0이 많으므로 단어 탭의 MK 대신 **준포아송 회귀**(분모 = 그 해 논문 수, 과산포 보정)로 "
                               "추세를 검정하고 FDR q<0.05만 남겼습니다. 붙여 쓴 형태가 이미 단어 탭의 상승 용어면 중복이라 뺐습니다. "
                               "**구로만** = 두 단어 모두 단어 단위로는 상승 목록에 없는데 구로 묶으면 오르는 신호.")
                    nb = [t for t in btouch if not t["minor"]]
                    kb_ = [("국내 상승 구", f"{bmeta.get('n_rising', 0)}", f"검정 {bmeta.get('tested', 0):,}개 중 · {scope_label}", NAVY),
                           ("구로만 보이는 신호", f"{sum(1 for t in nb if t['novel'])}", "두 단어 모두 단어로는 상승 아님", "#7C3AED"),
                           ("K-water 강점기술", f"{sum(1 for t in nb if t['n_inst'])}", f"{iname} 관련 문헌 대상·문제에 두 단어가 함께", col),
                           ("K-water 공백기술", f"{sum(1 for t in nb if not t['n_inst'])}", "연구소 관련 문헌 0편 — 공백 후보", AMBER)]
                    st.markdown('<div class="kpis">' + "".join(
                        f'<div class="kpi" style="border-left-color:{c}"><div class="k-val" style="font-size:1.35rem">{v}</div>'
                        f'<div class="k-lab">{l}</div><div class="k-sub">{s_}</div></div>' for l, v, s_, c in kb_) + "</div>",
                        unsafe_allow_html=True)
                    # 보는 관점 4가지 (v3.13.2 사용자 지정 이름) — 내부 키: main·new·gap·strong
                    BLENS = {"main": ("전체 흐름 (Main)", "국내 학회지에서 비중이 가장 가파르게 오르는 구 · 국내 기울기 순"),
                             "new": ("신규 상승", "국내 최근 3년 비중이 예전의 2배 이상(또는 처음 등장)인데 "
                                                "연구소 관련 문헌은 1–6편 — 막 떠오르는 초기 신호 · 배율 순"),
                             "gap": ("K-water 공백기술", "국내에서는 오르는데 연구소 관련 문헌에는 아직 없는 구 · 국내 기울기 순 "
                                                       "(‘기계 학습’ 같은 방법 구는 원래 잘 안 걸려 대상 구 위주로)"),
                             "strong": ("K-water 강점기술", "연구소 관련 문헌에 많이 나오면서 국내에서도 오르는 구 · 문헌 수 순")}
                    if st.session_state.get("kn_bi_lens") not in (None, *BLENS):     # 예전 이름으로 저장된 선택은 지움
                        st.session_state.pop("kn_bi_lens")
                    lens = st.segmented_control("보는 관점", list(BLENS), format_func=lambda k: BLENS[k][0],
                                                default="main", key="kn_bi_lens") or "main"       # 네 버튼이 다 보이게 한 줄 전체
                    st.markdown('<div class="lens-desc">' + "".join(          # 관점별 설명 (작은 글씨, 고른 것만 진하게)
                        f'<div class="ld{" on" if k == lens else ""}"><b>{nm}</b><span>{ds}</span></div>'
                        for k, (nm, ds) in BLENS.items()) + "</div>", unsafe_allow_html=True)
                    c2_, c3_, c4_ = st.columns(3)
                    only_novel = c2_.toggle("구로만 보이는 신호만", value=False, key="kn_bi_novel")
                    with_minor = c3_.toggle("저빈도 포함", value=False, key="kn_bi_minor",
                                            help="국내 최근 3년 5편 미만인 구도 보기")
                    has_j11 = any(t.get("j11_share") is not None for t in btouch)
                    water_bi = c4_.toggle("수자원학회 쪽 구만", value=True, key="kn_bi_water", disabled=not has_j11,
                                          help="수자원학회+토목학회 범위에서, 수자원학회 논문에서 나온 비율이 20% 미만인 구"
                                               "(콘크리트·포장 등 토목 구조 분야)를 숨깁니다.") if has_j11 else False
                    pool = [t for t in btouch if (with_minor or not t["minor"]) and (not only_novel or t["novel"])
                            and (not water_bi or (t.get("j11_share") or 0) >= 0.2)]
                    LIFT = lambda t: t["lift"] if t["lift"] is not None else 999.0       # 과거 0편 → '신규'(최상위)
                    LTXT = lambda t: "신규" if t["lift"] is None else f"{t['lift']}배"
                    if lens == "main":
                        view = sorted(pool, key=lambda t: -t["sen"])
                    elif lens == "new":
                        view = sorted([t for t in pool if 1 <= t["n_inst"] <= 6 and LIFT(t) >= 2],
                                      key=lambda t: (-LIFT(t), -t["sen"]))
                    elif lens == "gap":
                        view = sorted([t for t in pool if not t["n_inst"]], key=lambda t: -t["sen"])
                    else:
                        view = sorted([t for t in pool if t["n_inst"]], key=lambda t: (-t["n_inst"], -t["sen"]))
                    if not view:
                        st.info("이 관점·조건에 맞는 구가 없습니다.")
                    else:
                        a_, b_ = st.columns([3, 2])
                        with a_:
                            rr = view[:20][::-1]
                            xval = {"main": lambda t: t["sen"] * 1000, "gap": lambda t: t["sen"] * 1000,
                                    "new": lambda t: min(LIFT(t), 60), "strong": lambda t: t["n_inst"]}[lens]
                            xlab = {"main": "국내 기울기 (‰/년)", "gap": "국내 기울기 (‰/년)",
                                    "new": "최근3년 ÷ 과거 비중 (배, 과거 0편 '신규'는 60으로 표시)", "strong": "연구소 관련 문헌 수"}[lens]
                            fig = go.Figure(go.Bar(
                                x=[xval(t) for t in rr], y=[t["term"] for t in rr], orientation="h",
                                marker=dict(color=["#7C3AED" if t["novel"] else col for t in rr],
                                            line=dict(color="#FFFFFF", width=2)),
                                customdata=[[round(t["sen"] * 1000, 2), LTXT(t), t["recent_docs"], t["n_inst"],
                                             "구로만" if t["novel"] else "단어도 상승: " + "·".join(t["parts_rising"])] for t in rr],
                                hovertemplate="<b>%{y}</b><br>국내 기울기 %{customdata[0]}‰/년 · 최근/과거 %{customdata[1]}"
                                              "<br>국내 최근3년 %{customdata[2]}편 · 연구소 관련 문헌 %{customdata[3]}편"
                                              "<br>%{customdata[4]}<extra></extra>"))
                            fig.update_layout(height=max(320, 22 * len(rr) + 40), xaxis_title=xlab,
                                              yaxis=dict(automargin=True), bargap=0.25, **PLOTLY_LAYOUT)
                            fig.update_xaxes(gridcolor="#EEF2F7")
                            st.plotly_chart(fig, width="stretch", key="kn_bi_bar")
                            st.markdown(f'<span class="note"><span style="color:#7C3AED">■</span> 구로만 보이는 신호 &nbsp; '
                                        f'<span style="color:{col}">■</span> 단어로도 오르는 구</span>', unsafe_allow_html=True)
                        with b_:
                            pick = st.selectbox("구 자세히 보기", [t["term"] for t in view[:40]], key="kn_bi_pick")
                            t_ = next(t for t in view if t["term"] == pick)
                            if yrs and t_["series"]:
                                f2 = go.Figure(go.Scatter(x=yrs[:len(t_["series"])], y=[v * 100 for v in t_["series"]],
                                                          mode="lines+markers", line=dict(color="#7C3AED" if t_["novel"] else col),
                                                          hovertemplate="%{x}: %{y:.2f}%<extra></extra>"))
                                f2.update_layout(height=200, yaxis_title="국내 논문 중 비중(%)", **PLOTLY_LAYOUT)
                                f2.update_xaxes(gridcolor="#EEF2F7")
                                f2.update_yaxes(gridcolor="#EEF2F7", rangemode="tozero")
                                st.plotly_chart(f2, width="stretch", key="kn_bi_line")
                            st.markdown(
                                f'<div class="note">국내 기울기 <b>{t_["sen"] * 1000:.2f}‰/년</b>'
                                + (f' (연 {t_["rate"] * 100:+.0f}%)' if t_.get("rate") is not None else "")
                                + f' · 최근/과거 <b>{LTXT(t_)}</b> · '
                                f'최근3년 {t_["recent_docs"]}편 · 누적 {t_["total"]}편 · q={t_["q"]:.2g}'
                                + (f' · 결합도 {t_["pmi"]:+.1f}' if t_["pmi"] is not None else "") + "<br>"
                                + ("<b style='color:#7C3AED'>구로만 보이는 신호</b> — " + " · ".join(t_["parts"]) + " 각각은 단어로 상승 아님"
                                   if t_["novel"] else "단어로도 상승: " + " · ".join(t_["parts_rising"]))
                                + "</div>", unsafe_allow_html=True)
                            by_id_b = {r["id"]: r for r in recs}
                            if t_["ids"]:
                                st.markdown(f"**{iname} 관련 문헌 {t_['n_inst']}편** (두 단어 함께 · 붙어 나온 것 {t_['n_tight']}편)")
                                for pid in t_["ids"][:6]:
                                    r = by_id_b[pid]
                                    st.markdown(f"- [{r['title'][:80]}]({r['doi'] or '#'}) · {r['year'] or '-'}"
                                                f"  \n  <span class='note'>대상: {r['object']} / 문제: {r['problem']}</span>",
                                                unsafe_allow_html=True)
                            else:
                                st.caption(f"{iname} 관련 문헌의 대상·문제에는 아직 없습니다 — 수집 키워드 보강·기획 검토 후보.")
                    fall = [r for r in (bmeta.get("falling") or []) if not r.get("minor")
                            and (not water_bi or (r.get("j11_share") or 0) >= 0.2)][:16]
                    if fall:
                        st.markdown('<div class="sect">국내에서 줄어드는 구</div>', unsafe_allow_html=True)
                        st.markdown('<div style="line-height:2.2">' + " ".join(
                            f'<span class="gchip" style="background:#F1F5FA;color:#64748B;display:inline-block;white-space:nowrap">{r["term"]}</span>'
                            for r in fall) + "</div>", unsafe_allow_html=True)
                    with st.expander("표로 보기 — 상승 구 전체 (연도별 비중 추이 포함)"):
                        st.dataframe(pd.DataFrame([{
                            "구": t["term"], "구로만": "✔" if t["novel"] else "", "국내 기울기(‰/년)": round(t["sen"] * 1000, 2),
                            "최근/과거": LTXT(t), "연 증가율(%)": round(t["rate"] * 100) if t.get("rate") is not None else None,
                            "국내 최근3년": t["recent_docs"], "연구소 관련 문헌": t["n_inst"],
                            "수자원학회 비율": t.get("j11_share"),
                            "추이": [v * 100 for v in t["series"]], "저빈도": "✔" if t["minor"] else ""}
                            for t in sorted(btouch, key=lambda t: -t["sen"])]),
                            hide_index=True, width="stretch",
                            column_config={"추이": st.column_config.LineChartColumn("연도별 비중(%)", width="medium")})

            # ── 탭4: 최근 브리핑 ──
            with t4:
                days = st.segmented_control("기간", [7, 30, 90], default=30, key="kn_days",
                                            format_func=lambda d: f"최근 {d}일") or 30
                rr = kn.recent(recs, anchor, days)
                brief = kn.briefing_markdown(sel, iname, rr, len(recs), days, anchor, touch, net, DN)
                st.caption(f"기준일 {anchor.isoformat()} — 수집 문헌의 최신 발행일 (오늘 {today_kst.isoformat()})")
                if not rr:
                    st.info("이 기간에 발행된 수집 문헌이 없습니다.")
                else:
                    a, b = st.columns([2, 3])
                    with a:
                        dc = Counter(r["domain"] for r in rr if r["domain"])
                        pairs = dc.most_common()[::-1]
                        fig = go.Figure(go.Bar(x=[n for _, n in pairs], y=[f"{d} {DN.get(d, d)}" for d, _ in pairs],
                                               orientation="h", marker_color=col))
                        fig.update_layout(height=max(220, 30 * len(pairs) + 40), xaxis_title="편",
                                          yaxis=dict(automargin=True), **PLOTLY_LAYOUT)
                        st.markdown('<div class="sect">도메인</div>', unsafe_allow_html=True)
                        st.plotly_chart(fig, width="stretch")
                    with b:
                        st.markdown(f'<div class="sect">최근 {days}일 문헌 {len(rr)}편</div>', unsafe_allow_html=True)
                        st.dataframe(pd.DataFrame([{
                            "발행일": r["date"], "제목": r["title"], "대상": r["object"], "문제": r["problem"],
                            "토픽": net["assign"].get(r["id"], "-"), "DOI": r["doi"] or None} for r in rr]),
                            hide_index=True, width="stretch", height=340,
                            column_config={"DOI": st.column_config.LinkColumn("DOI", display_text="🔗 열기")})
                with st.expander("브리핑 문안 (마크다운)", expanded=bool(rr)):
                    st.markdown(brief)
                st.download_button("⬇️ 브리핑 내려받기 (.md)", brief.encode("utf-8"),
                                   file_name=f"{sel}_briefing_{anchor.isoformat()}_{days}d.md", mime="text/markdown")

            # ── 탭5: 노트 내보내기 ──
            with t5:
                st.markdown(f"""**{iname} 지식노트 폴더**를 zip으로 받습니다. 마크다운 + YAML 머리말이라 특정 프로그램에 묶이지 않습니다.
- 그대로 열기: **Logseq**·**Obsidian**·**VS Code(Foam)** 에서 폴더째 열기
- 사내 웹으로: **Quartz**(오픈소스)로 정적 사이트 배포 → 그래프 뷰·검색 포함
""")
                st.code(f"""{sel}_{iname}/
├── README.md      첫 화면: 토픽 목록·도메인·출처와 방법
├── briefing.md    최근 30일 브리핑
├── rising.md      국내 상승 용어 접점 ({scope_label})
├── gaps.md        결합 공백 후보
├── topics/T01.md …  토픽 노트 (대표 용어·도메인·문헌 링크)
└── papers/<OpenAlex ID>.md …  문헌 노트 {len(recs):,}개 (서지·대상·문제·도메인·토픽)""", language="text")
                inc_abs = st.checkbox("문헌 노트에 초록 포함 (파일이 커지고 만드는 데 시간이 더 걸림)", value=False)
                key = (sel, water_only, scope_key, inc_abs)
                if st.button("📦 노트 묶음 만들기", type="primary"):
                    with st.spinner("노트를 만드는 중…"):
                        abstracts = None
                        if inc_abs:
                            ids = {r["id"] for r in recs}
                            abstracts = {a.get("id"): a.get("abstract") for a in dcache.inst_abstracts(sel)
                                         if a.get("id") in ids and a.get("abstract")}
                        brief30 = kn.briefing_markdown(sel, iname, r30, len(recs), 30, anchor, touch, net, DN)
                        data, nfiles = kn.build_vault_zip(sel, iname, recs, net, touch, gaps, brief30, scope_label,
                                                          abstracts=abstracts, domain_names=DN, today=today_kst)
                        st.session_state["kn_zip"] = (key, data, nfiles)
                zz = st.session_state.get("kn_zip")
                if zz and zz[0] == key:
                    st.download_button(f"⬇️ {iname} 지식노트 내려받기 (zip · 파일 {zz[2]:,}개 · {len(zz[1]) / 1e6:.1f} MB)",
                                       zz[1], file_name=f"{sel}_{iname}_지식노트_{today_kst.isoformat()}.zip",
                                       mime="application/zip")
                st.caption("다음 단계(개인화): 연구원별 관심 키워드·읽음 표시·메모를 저장해 개인 노트로 확장 — 지금은 연구소 단위 그룹 노트입니다.")

# ═══════════════ HITL (전문가) 검토: K-water 문헌 적정성 (사람 판정 게임) ═══════════════
elif page == HITL_PAGE:
    st.markdown('<div class="sect">K-water 문헌 적정성 — 사람 판정(HITL) 게임</div>', unsafe_allow_html=True)
    st.caption("KCI에서 모은 K-water 소속 논문 분류(저자 소속 규칙)를 사람이 빠르게 검증합니다. 판정 파일은 이 브라우저 안에서만 "
               "열리고 서버로 보내지 않습니다. 처음엔 가상 연습 데이터로 열립니다.")
    hp = Path("tools/kwater_hitl.html")
    html = None
    try:
        html = hp.read_text(encoding="utf-8") if hp.exists() else None
    except Exception:
        html = None
    if html is None:
        try:
            r = requests.get(_raw("tools/kwater_hitl.html"), timeout=15)
            html = r.text if r.status_code == 200 else None
        except Exception:
            html = None
    kw_ = load_json("kci_kwater.json") or {}
    hr_ = kw_.get("human_review") or {}
    rl_ = hr_.get("rules", {})
    c1, c2 = st.columns([3, 2])
    with c1:
        st.markdown("""**쓰는 법**
1. 비공개 저장소 `review/kwater_review.xlsx`(또는 CSV)를 내려받아 아래 게임에 끌어다 놓고 판정 (키보드 D·A·S·Z, 휴대폰은 좌우 밀기)
2. 기계 판정과 다르게 고른 것만 결과 JSON으로 나옴 → 비공개 저장소에 `review/overrides_<이름>.json`으로 저장
3. 다음 주간 kci-rising부터 자동 반영 (판정이 엇갈린 항목은 규칙대로 둠)""")
    with c2:
        st.markdown('<div class="kpis">' + "".join(
            f'<div class="kpi" style="border-left-color:{c}"><div class="k-val" style="font-size:1.3rem">{v}</div>'
            f'<div class="k-lab">{l}</div></div>' for l, v, c in [
                ("반영된 판정 파일", f"{hr_.get('files', 0)}개", NAVY),
                ("소속 포함·제외", f"{rl_.get('affiliation_include', 0)} · {rl_.get('affiliation_exclude', 0)}", BLUE),
                ("논문 포함·제외", f"{rl_.get('paper_include', 0)} · {rl_.get('paper_exclude', 0)}", CYAN),
                ("엇갈림", f"{hr_.get('conflicts', 0)}", AMBER)]) + '</div>', unsafe_allow_html=True)
        if not hr_:
            st.caption("아직 반영된 사람 판정이 없습니다 (kci_kwater.json의 human_review).")
    if html is None:
        st.warning("게임 파일(tools/kwater_hitl.html)을 찾지 못했습니다.")
    else:
        st.download_button("⬇️ 게임 파일 내려받기 (새 창 · 전체 화면으로 쓰기)", html.encode("utf-8"),
                           file_name="kwater_hitl.html", mime="text/html")
        components.html(html, height=980, scrolling=True)
        st.caption("결과 복사가 막히는 브라우저에서는 게임의 '파일로 저장'을 쓰세요. 진행 상황은 이 브라우저에 자동 저장됩니다.")

elif page == FLOW_PAGE:
    st.markdown('<div class="sect">🌊 에이전트 흐름 — 데이터가 어디서 와서 어디로 가는지 한눈에 (보여 주기용)</div>',
                unsafe_allow_html=True)
    st.caption("원천 → 수집 → 처리 → 지식 → 사람 검토 → 활용. 점 하나가 데이터 흐름이고 최근에 일한 에이전트일수록 빠르게 흐릅니다. "
               "화면은 60초마다 GitHub에서 직접 갱신(새로고침 불필요) · 노드를 누르면 상세 · 끌기 이동 · 휠 확대 · ⛶ 전체 화면")
    _hitl = load_labels("hitl/INST-02/summary.json")
    _ft = {}
    if ft_index:
        _ft = {"latest": ft_index[0].get("id"), "status": run_status(*load_metrics(ft_index[0]["id"]))[0]}
    _snap = af.snapshot(agents, state_of, T, load_json("kci_rising.json"), load_json("kci_kwater.json"),
                        load_labels_jsonl("pipeline_runs.jsonl"), load_labels_jsonl("metrics/daily.jsonl"), _hitl,
                        _ft, live_oa, oa_idx)
    _html = af.html(_snap, height=740)
    components.html(_html, height=750, scrolling=False)
    c1_, c2_ = st.columns([1, 3])
    c1_.download_button("⬇️ 단독 HTML로 받기 (발표용)", _html.encode("utf-8"), file_name="water_coscientist_flow.html",
                        mime="text/html", help="브라우저로 바로 열리고, 인터넷이 되면 60초마다 스스로 갱신됩니다.")
    c2_.caption("세션 내용·개인정보 없이 집계 숫자와 상태만 씁니다. 시각 언어 참고: agent4d(burn001, Apache-2.0)의 ‘흐름’ 표현과 "
                "그 원형 patoles/agent-flow(Apache-2.0) — 코드는 새로 작성.")

elif page in AGENT_FLOWS:                              # Agent Flow 확인用 — 다른 시스템의 흐름도 (구조도, 실시간 아님)
    f_path, f_title, f_desc, _, f_note = AGENT_FLOWS[page]
    st.markdown(f'<div class="sect">{f_title}</div>', unsafe_allow_html=True)
    st.caption(f"{f_desc}하는 구조도이며 실시간 상태는 아닙니다. 오른쪽 패널에서 단계 고르기 · 노드를 누르면 상세 · 끌기 이동 · 휠 확대 · ⛶ 전체 화면")
    if isinstance(f_path, dict):                       # 보기가 여럿이면 전환 버튼 (한 번에 하나만 그려 겹치지 않게)
        views_ = list(f_path)
        vc1, vc2 = st.columns([2, 3])
        with vc1:
            view_ = st.segmented_control("보기", views_, default=views_[0], key=f"flow_view_{views_[0]}_{page}",
                                         label_visibility="collapsed") or views_[0]
        vc2.caption("전문가 보기: 기술 용어와 판정 기준·수식, 연결선 위에 넘겨주는 자료, 노드를 누르면 '사양·수식' 칸"
                    if "전문가" in view_ else "기본 보기: 처음 보는 사람도 따라갈 수 있게 쉬운 말로 정리한 흐름")
        f_path = f_path[view_]
    f_html = None
    try:
        f_html = Path(f_path).read_text(encoding="utf-8") if Path(f_path).exists() else None
    except Exception:
        f_html = None
    if f_html is None:
        try:
            r = requests.get(_raw(f_path), timeout=15)
            f_html = r.text if r.status_code == 200 else None
        except Exception:
            f_html = None
    if f_html is None:
        st.warning(f"흐름도 파일({f_path})을 찾지 못했습니다.")
    else:
        components.html(f_html, height=860, scrolling=False)
        st.download_button("⬇️ 단독 HTML로 받기 (발표용)", f_html.encode("utf-8"), file_name=Path(f_path).name,
                           mime="text/html", help="브라우저로 바로 열립니다 (인터넷 연결 불필요).")
        st.caption(f"코드가 바뀌면 파일 안의 노드·연결선·재생 단계 표(N·E·SCN)만 고칩니다. {f_note}")

elif page == LR_PAGE:
    lrp.render(load_json, PLOTLY_LAYOUT)

elif page == LR1_PAGE:
    lrp.render(load_json, PLOTLY_LAYOUT, mode="sample")

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

# ── 자동 갱신 (지식노트·달성도 화면은 제외 — 큰 파일 재다운로드 방지, 달성도 데이터는 6시간 주기) ──
@st.fragment(run_every=30)
def _auto_refresh_timer():
    """30초마다 브라우저 타이머가 이 조각만 깨움 → 마지막 전체 그리기에서 25초 넘었으면 앱 전체를 다시 그림.
    예전 방식(time.sleep(30) 뒤 전체 캐시 비우기)은 ① 대기 30초 동안 메뉴 클릭이 막히고 ② 모든 사용자의
    캐시를 지워 다른 화면까지 매번 처음부터 받게 했다. 이제 실시간 데이터는 각 캐시의 짧은 TTL(25초)로 갱신된다."""
    if time.time() - st.session_state.get("_full_run_ts", 0) >= 25:
        st.rerun(scope="app")


if auto and page not in (KN_PAGE, AC_PAGE, HITL_PAGE, LR_PAGE, LR1_PAGE, FLOW_PAGE, OA_PAGE, ASSET_PAGE, CIT_PAGE, KCIKW_PAGE, *AGENT_FLOWS):     # 판정·노트 화면은 입력 중 초기화 방지, 흐름 화면은 스스로 갱신
    _auto_refresh_timer()
