"""
관제센터 '🌊 에이전트 흐름' — 보여 주기용 화면 (운영 화면은 '🛰️ 관제센터' 그대로)

원천 → 수집 → 처리 → 지식 → 사람 검토 → 활용 을 육각 노드·곡선 빔·빔을 타고 흐르는 패킷으로 그린다.
  · 처음 그림은 앱이 넘겨준 스냅숏으로, 그 뒤에는 브라우저가 60초마다 GitHub(data 브랜치)의 작은 상태
    파일을 직접 읽어 갱신한다 (Streamlit을 다시 그리지 않으므로 애니메이션이 끊기지 않음).
  · 상태 색: 가동(초록·맥동) / 정상 대기(파랑) / 준비·예정(주황) / 설계(회색 점선) / 오류(빨강)
  · 세션 내용·개인정보 없이 집계 숫자와 상태만 쓴다 → 공개 화면에 띄워도 안전.
시각 언어 참고: agent4d (burn001, Apache-2.0)의 '흐름' 표현과 그 원형인 patoles/agent-flow (Apache-2.0).
코드는 가져오지 않고 새로 작성했다.
"""
from __future__ import annotations

import calendar
import json
import time

REPO = "newcave/water-tech-agent"
POLL_AGENTS = ["openalex_collector", "alio_crawler", "kipris_collector", "article_collector",
               "alio_parser", "normalizer", "ft_trainer"]


def _iso_ts(s):
    try:
        return calendar.timegm(time.strptime(s, "%Y-%m-%dT%H:%M:%SZ"))
    except Exception:
        return None


def snapshot(agents: dict, state_fn, totals: dict, kr: dict | None, kw: dict | None,
             runs: list, daily: list, hitl: dict | None, ft: dict | None = None, stats: dict | None = None) -> dict:
    """화면 첫 그림용 스냅숏 (모두 집계·상태만)."""
    ag = {}
    for k, a in (agents or {}).items():
        ag[k] = {"state": state_fn(a), "last_run": a.get("last_run"), "summary": a.get("summary") or "",
                 "counts": a.get("counts") or {}, "events": (a.get("events") or [])[-6:]}
    sc = ((kr or {}).get("scopes") or {}).get("J11+J12") or {}
    kci = {"updated": (kr or {}).get("updated"), "uni": sc.get("n_rising", 0),
           "bi": (sc.get("bigram") or {}).get("n_rising", 0), "docs": sum(sc.get("denominator") or []),
           "top_uni": [r["term"] for r in (sc.get("rising") or []) if not r.get("minor")][:3],
           "top_bi": [r["term"] for r in ((sc.get("bigram") or {}).get("rising") or []) if not r.get("minor")][:3],
           "kwater": (kw or {}).get("total", 0)}
    last_run = runs[-1] if runs else {}
    tot = (daily[-1].get("totals") if daily else {}) or {}
    labels = {"ts": _iso_ts(last_run.get("ts")) if last_run.get("ts") else None,
              "extracted": last_run.get("extracted", 0), "assigned": last_run.get("assigned", 0),
              "total": last_run.get("total", tot.get("assigned", 0)), "collected": tot.get("collected", 0),
              "abstract_ok": tot.get("abstract_ok", 0),
              "runs": [{"ts": _iso_ts(r.get("ts")), "extracted": r.get("extracted", 0), "assigned": r.get("assigned", 0),
                        "forward": r.get("forward", 0), "hist": r.get("hist", 0)} for r in runs[-8:]]}
    h = hitl or {}
    hitl_s = {"records": h.get("records", 0), "papers": h.get("papers_judged", 0),
              "reviewers": len(h.get("by_reviewer") or {}), "updated": _iso_ts(h.get("updated_at")) if h.get("updated_at") else None,
              "final": h.get("final") or {}}
    return {"generated": int(time.time()), "repo": REPO, "poll_agents": POLL_AGENTS, "agents": ag,
            "totals": {"papers": totals.get("papers", 0)}, "kci": kci, "labels": labels, "hitl": hitl_s,
            "ft": ft or {}, "stats": stats or {}}


def html(snap: dict, height: int = 720) -> str:
    data = json.dumps(snap, ensure_ascii=False).replace("</", "<\\/")
    return _TEMPLATE.replace("__SNAP__", data).replace("__H__", str(height))


_TEMPLATE = r"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{--bg0:#050f22;--bg1:#0b2447;--ink:#e6eefb;--mut:#8ea6c8;--line:rgba(140,170,215,.16);
 --run:#22c55e;--idle:#38bdf8;--standby:#f59e0b;--plan:#64748b;--error:#ef4444}
*{box-sizing:border-box}html,body{margin:0;height:100%;background:var(--bg0);font-family:'Noto Sans KR','Malgun Gothic',system-ui,sans-serif;color:var(--ink);overflow:hidden}
#wrap{position:relative;width:100%;height:__H__px;background:radial-gradient(1200px 700px at 55% 40%,#0e2c57 0%,var(--bg1) 35%,var(--bg0) 100%);border-radius:14px;overflow:hidden}
#wrap:fullscreen{height:100vh;border-radius:0}
canvas{position:absolute;inset:0;width:100%;height:100%;cursor:grab}
canvas:active{cursor:grabbing}
.hud{position:absolute;pointer-events:none}
#top{left:18px;top:14px;right:18px;display:flex;align-items:flex-start;gap:14px}
#ttl{font-weight:900;font-size:19px;letter-spacing:-.2px}
#ttl small{display:block;font-weight:500;font-size:12px;color:var(--mut);margin-top:2px}
#kpis{display:flex;gap:8px;flex-wrap:wrap;margin-left:auto;justify-content:flex-end}
.chip{background:rgba(16,40,80,.72);border:1px solid rgba(120,160,220,.25);border-radius:999px;padding:4px 11px;font-size:12px;color:#cfe0f7;white-space:nowrap;backdrop-filter:blur(4px)}
.chip b{color:#fff;font-weight:800}
.live{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--run);margin-right:6px;box-shadow:0 0 0 0 rgba(34,197,94,.6);animation:pl 1.8s infinite}
@keyframes pl{0%{box-shadow:0 0 0 0 rgba(34,197,94,.55)}70%{box-shadow:0 0 0 9px rgba(34,197,94,0)}100%{box-shadow:0 0 0 0 rgba(34,197,94,0)}}
#feed{right:16px;top:64px;width:272px;max-height:46%;overflow:hidden;background:linear-gradient(180deg,rgba(9,26,54,.86),rgba(9,26,54,.55));border:1px solid rgba(120,160,220,.18);border-radius:12px;padding:10px 12px;font-size:12px}
#feed h4{margin:0 0 6px;font-size:12px;color:var(--mut);font-weight:700;letter-spacing:.06em}
.ev{display:flex;gap:8px;padding:5px 0;border-bottom:1px solid rgba(120,160,220,.08);line-height:1.35}
.ev .t{color:var(--mut);white-space:nowrap;min-width:46px}
.ev.new{animation:fl 2.4s ease-out}
@keyframes fl{0%{background:rgba(56,189,248,.28)}100%{background:transparent}}
#legend{left:16px;bottom:12px;display:flex;gap:12px;font-size:11.5px;color:var(--mut);background:rgba(9,26,54,.6);border-radius:10px;padding:6px 10px}
#legend i{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:5px;vertical-align:-1px}
#card{right:16px;bottom:12px;width:300px;background:rgba(9,26,54,.92);border:1px solid rgba(120,160,220,.25);border-radius:12px;padding:12px 14px;font-size:12.5px;display:none;pointer-events:auto}
#card h3{margin:0 0 4px;font-size:15px}
#card .st{font-size:11.5px;font-weight:700}
#card .kv{display:flex;justify-content:space-between;color:#cfe0f7;padding:2px 0}
#card .kv b{color:#fff}
#card .x{position:absolute;right:10px;top:8px;cursor:pointer;color:var(--mut)}
#tip{position:absolute;pointer-events:none;background:rgba(5,15,34,.95);border:1px solid rgba(120,160,220,.3);border-radius:8px;padding:7px 10px;font-size:12px;display:none;max-width:280px;line-height:1.45}
#btns{position:absolute;left:16px;top:62px;display:flex;gap:6px}
#btns button{background:rgba(16,40,80,.8);color:#cfe0f7;border:1px solid rgba(120,160,220,.3);border-radius:8px;padding:4px 10px;font-size:12px;cursor:pointer;font-family:inherit}
#btns button:hover{background:rgba(36,70,130,.9)}
#clock{font-variant-numeric:tabular-nums}
</style></head><body>
<div id="wrap">
 <canvas id="cv"></canvas>
 <div class="hud" id="top">
  <div id="ttl">💧 Water Co-Scientist · 에이전트 흐름<small>원천 → 수집 → 처리 → 지식 → 사람 검토 → 활용 · K-water연구원</small></div>
  <div id="kpis"></div>
 </div>
 <div id="btns"><button id="fs">⛶ 전체 화면</button><button id="rs">⟲ 시점 초기화</button><button id="pa">⏸ 정지</button><button id="fd">☰ 실황 숨기기</button></div>
 <div class="hud" id="feed"><h4><span class="live"></span>실황 · <span id="clock"></span> KST</h4><div id="evs"></div></div>
 <div class="hud" id="legend"><span><i style="background:var(--run)"></i>가동</span><span><i style="background:var(--idle)"></i>정상 대기</span><span><i style="background:var(--standby)"></i>준비·예정</span><span><i style="background:var(--plan)"></i>설계</span><span style="opacity:.75">점 하나 = 데이터 흐름 · 빠를수록 최근 활동</span></div>
 <div class="hud" id="card"><span class="x" id="cx">✕</span><div id="cb"></div></div>
 <div id="tip"></div>
</div>
<script>
const SNAP = __SNAP__;
const RAW = "https://raw.githubusercontent.com/" + SNAP.repo + "/data/";
const cv = document.getElementById("cv"), ctx = cv.getContext("2d");
const ST = {run:["가동 중","#22c55e"], idle:["정상 대기","#38bdf8"], standby:["준비·예정","#f59e0b"], plan:["설계","#64748b"], error:["오류","#ef4444"]};
const GC = {src:"#7dd3fc", col:"#3b82f6", pro:"#14b8a6", kno:"#a78bfa", hit:"#f472b6", use:"#fb923c"};
const COLS = [["원천",95],["수집",325],["처리",555],["지식",790],["사람 검토",1020],["활용",1245]];
const VW = 1340, VH = 860;
let D = JSON.parse(JSON.stringify(SNAP));
const now = () => Date.now() / 1000;
const fmt = n => (n || 0).toLocaleString("ko-KR");
function ago(ts){ if(!ts) return "-"; const s = Math.max(0, now() - ts);
  if (s < 60) return Math.round(s) + "초 전"; if (s < 3600) return Math.round(s/60) + "분 전";
  if (s < 86400) return Math.round(s/3600) + "시간 전"; return Math.round(s/86400) + "일 전"; }
function agentState(a){ if(!a) return "standby"; try{ const e = a.events||[]; if(e.length && now()-e[e.length-1].ts < 600) return "run"; }catch(x){}
  return ST[a.state] ? a.state : "standby"; }
function recency(ts){ if(!ts) return 0; const s = now()-ts; return s<900?1 : s<6*3600?0.55 : s<86400?0.35 : s<7*86400?0.15 : 0.05; }

// ── 노드 (col, row(0..6), 그룹) ──
const N = [
 {id:"src_openalex", col:0, row:0.5, g:"src", icon:"🌐", label:"OpenAlex", sub:"국제 학술 DB"},
 {id:"src_kci", col:0, row:1.7, g:"src", icon:"🇰🇷", label:"KCI", sub:"국내 학회지"},
 {id:"src_alio", col:0, row:2.9, g:"src", icon:"🏛️", label:"ALIO", sub:"공공기관 보고서"},
 {id:"src_kipris", col:0, row:4.0, g:"src", icon:"📜", label:"KIPRIS", sub:"특허"},
 {id:"src_news", col:0, row:5.1, g:"src", icon:"📰", label:"기사·아티클", sub:"웹"},
 {id:"openalex_collector", col:1, row:0.5, g:"col", icon:"📄", label:"논문 수집", agent:"openalex_collector"},
 {id:"kci", col:1, row:1.7, g:"col", icon:"🔎", label:"KCI 수집·분석"},
 {id:"alio_crawler", col:1, row:2.9, g:"col", icon:"📥", label:"ALIO 수집", agent:"alio_crawler"},
 {id:"kipris_collector", col:1, row:4.0, g:"col", icon:"📜", label:"특허 수집", agent:"kipris_collector"},
 {id:"article_collector", col:1, row:5.1, g:"col", icon:"📰", label:"기사 수집", agent:"article_collector"},
 {id:"labels", col:2, row:0.5, g:"pro", icon:"🏷️", label:"라벨링 파이프라인"},
 {id:"alio_parser", col:2, row:2.9, g:"pro", icon:"🧠", label:"파싱·추출", agent:"alio_parser"},
 {id:"normalizer", col:2, row:4.0, g:"pro", icon:"🧩", label:"정규화", agent:"normalizer"},
 {id:"kn", col:3, row:1.25, g:"kno", icon:"📒", label:"연구소 지식노트"},
 {id:"kci_trend", col:3, row:2.5, g:"kno", icon:"📈", label:"KCI 트렌드"},
 {id:"achieve", col:3, row:0.0, g:"kno", icon:"🎯", label:"수집 달성도"},
 {id:"hitl_label", col:4, row:0.6, g:"hit", icon:"🧪", label:"라벨 판정"},
 {id:"hitl_kwater", col:4, row:2.5, g:"hit", icon:"🎮", label:"K-water 판정"},
 {id:"dash", col:5, row:1.45, g:"use", icon:"🛰️", label:"관제센터"},
 {id:"ft_trainer", col:5, row:4.0, g:"use", icon:"🔥", label:"FT 학습", agent:"ft_trainer"},
];
const E = [
 ["src_openalex","openalex_collector"],["src_kci","kci"],["src_alio","alio_crawler"],["src_kipris","kipris_collector",1],["src_news","article_collector",1],
 ["openalex_collector","labels"],["labels","kn"],["labels","achieve"],["labels","hitl_label"],["hitl_label","kn",0,1],
 ["kci","kci_trend"],["kci_trend","kn"],["kci","hitl_kwater"],["hitl_kwater","kci_trend",0,1],
 ["alio_crawler","alio_parser"],["alio_parser","normalizer"],["normalizer","ft_trainer"],
 ["kn","dash"],["kci_trend","dash"],["achieve","dash"],["hitl_label","dash"],
 ["kipris_collector","labels",1],["article_collector","kn",1],
];
const byId = Object.fromEntries(N.map(n => [n.id, n]));
N.forEach(n => { n.x = COLS[n.col][1]; n.y = 110 + n.row * 124; n.r = n.g === "src" ? 34 : 44; n.flash = 0; });

// ── 상태·숫자 묶기 ──
function bind(){
  const A = D.agents || {};
  const L = D.labels || {}, K = D.kci || {}, H = D.hitl || {};
  const set = (id, st, metric, last, extra) => Object.assign(byId[id], {st, metric, last, extra: extra||[]});
  ["src_openalex","src_kci","src_alio"].forEach(i => set(i, "idle", "", null));
  set("src_kipris", "standby", "서비스키 승인 대기", null); set("src_news", "plan", "설계 예정", null);
  for (const n of N) if (n.agent) { const a = A[n.agent]; const c = (a && a.counts) || {};
    const m = Object.entries(c).slice(0,2).map(([k,v]) => k + " " + (typeof v === "number" ? fmt(v) : v)).join(" · ");
    set(n.id, agentState(a), m, a && a.last_run, a ? [a.summary] : []); }
  const lst = L.ts && now()-L.ts < 900 ? "run" : L.ts ? "idle" : "standby";
  set("labels", lst, "라벨 " + fmt(L.total) + "편", L.ts, ["초록 보강 → 대상·문제 추출 → W 도메인 배정 · 6시간마다",
      "최근 회차: 추출 " + fmt(L.extracted) + " · 배정 " + fmt(L.assigned), "수집 문헌 " + fmt(L.collected) + " · 초록 확보 " + fmt(L.abstract_ok)]);
  const kst = K.updated && now()-K.updated < 8*86400 ? "idle" : "standby";
  set("kci", kst, "단어 " + fmt(K.uni) + " · 구 " + fmt(K.bi) + " 상승", K.updated, ["국내 학회지 " + fmt(K.docs) + "편 · 주 1회(월)",
      "상승 단어: " + (K.top_uni||[]).join(", "), "상승 구: " + (K.top_bi||[]).join(", ")]);
  set("kci_trend", kst, (K.top_bi||[]).slice(0,2).join(" · "), K.updated, ["단어(유니그램)·구(바이그램) 상승 · 주제 묶음"]);
  set("kn", lst, "7개 연구소", L.ts, ["토픽 지도 · 상승 용어·구 접점 · 공백 후보 · 브리핑"]);
  set("achieve", lst, "목표 대비 · 실패 기록", L.ts, []);
  const hst = H.updated && now()-H.updated < 3600 ? "run" : H.updated ? "idle" : "standby";
  set("hitl_label", hst, "판정 " + fmt(H.records) + "건 · " + fmt(H.reviewers) + "명", H.updated,
      ["OK " + fmt((H.final||{}).ok) + " · NG " + fmt((H.final||{}).ng) + " · 이관 " + fmt((H.final||{}).move), "판정 대장 자동 정리"]);
  set("hitl_kwater", "idle", "K-water 소속 " + fmt(K.kwater) + "편", K.updated, ["소속 규칙 사람 검증"]);
  set("dash", "run", "Streamlit · 13개 화면", now(), ["지금 보고 있는 화면"]);
  for (const n of N) n.act = n.st === "run" ? 1 : n.st === "plan" ? 0 : recency(n.last);
}
bind();

// ── 실황 피드 ──
let seen = new Set();
function events(){
  const out = [], A = D.agents || {};
  for (const [k, a] of Object.entries(A)) for (const e of (a.events||[])) if (e && e.ts) out.push({ts:e.ts, node:k, msg:e.msg});
  const runs = (D.labels||{}).runs || [];
  for (const r of runs) if (r.ts && ((r.forward||0) + (r.hist||0) + (r.extracted||0) + (r.assigned||0)) > 0) out.push({ts:r.ts, node:"labels",
     msg:"🏷️ 라벨링 회차 — 수집 " + fmt((r.forward||0)+(r.hist||0)) + " · 추출 " + fmt(r.extracted) + " · 배정 " + fmt(r.assigned)});
  const lastRun = runs.length ? runs[runs.length - 1] : null;
  if (lastRun && lastRun.ts && !((lastRun.forward||0) + (lastRun.hist||0) + (lastRun.extracted||0) + (lastRun.assigned||0)))
    out.push({ts:lastRun.ts, node:"labels", msg:"🏷️ 라벨링 회차 — 새 문헌 없음 (점검 완료)"});
  const K = D.kci||{}; if (K.updated) out.push({ts:K.updated, node:"kci", msg:"📈 KCI 주간 분석 — 상승 단어 " + K.uni + " · 구 " + K.bi});
  const H = D.hitl||{}; if (H.updated) out.push({ts:H.updated, node:"hitl_label", msg:"🧾 판정 대장 정리 — 누적 " + H.records + "건"});
  out.sort((a,b) => b.ts - a.ts);
  const uniq = [], key = new Set();                       // 같은 노드의 같은 문구는 가장 최근 것 하나만
  for (const e of out){ const k = e.node + "|" + e.msg; if (!key.has(k)){ key.add(k); uniq.push(e); } }
  return uniq.slice(0, 10);
}
function renderFeed(first){
  const el = document.getElementById("evs"); const evs = events(); let html = "";
  for (const e of evs) { const key = e.node + e.ts + e.msg; const isNew = !first && !seen.has(key);
    if (isNew && byId[e.node]) { byId[e.node].flash = 1; burst(e.node); }
    seen.add(key);
    html += `<div class="ev${isNew ? " new" : ""}"><span class="t">${ago(e.ts)}</span><span>${(e.msg||"").replace(/</g,"&lt;")}</span></div>`; }
  el.innerHTML = html || '<div class="ev">최근 활동 없음</div>';
}
function renderKpis(){
  const K = D.kci||{}, L = D.labels||{}, H = D.hitl||{};
  const pap = (D.stats && D.stats.collected_total) || (D.totals||{}).papers || 0;
  document.getElementById("kpis").innerHTML = [
    ["논문", fmt(pap) + "편"], ["라벨", fmt(L.total) + "편"], ["KCI 상승", "단어 " + fmt(K.uni) + " · 구 " + fmt(K.bi)],
    ["사람 판정", fmt(H.records) + "건"], ["<span class='live'></span>LIVE", "60초 갱신"]].map(([a,b]) => `<span class="chip">${a} <b>${b}</b></span>`).join("");
}

// ── 패킷 ──
let packets = [];
function edgeAct(e){ const a = byId[e[0]]; return e[2] ? 0 : Math.max(0.04, a.act || 0); }
function burst(id){ for (const e of E) if (e[0] === id && !e[2]) for (let i = 0; i < 6; i++) packets.push({e, t: -i * 0.07, sp: 0.5 + Math.random() * 0.2, big: 1}); }

// ── 카메라 ──
let W = 0, H = 0, DPR = Math.max(1, window.devicePixelRatio || 1), zoom = 1, panX = 0, panY = 0, paused = false;
function resize(){ const r = cv.getBoundingClientRect(); W = r.width; H = r.height; cv.width = W * DPR; cv.height = H * DPR; }
window.addEventListener("resize", resize); document.addEventListener("fullscreenchange", () => setTimeout(resize, 60));
// 그래프 자리: 위 HUD(제목·단추) 95px, 아래 범례 40px, 넓은 화면이면 오른쪽 실황 패널(330px)을 비켜 둔다
let showFeed = true;
function area(){ const aw = (showFeed && W > 900) ? W - 300 : W; return {aw, ah: H - 135}; }
function base(){ const {aw, ah} = area(); return Math.min(aw / VW, ah / VH); }
function tf(t){ const s = base() * zoom; const {aw, ah} = area(); const drift = paused ? 0 : 1;
  const ox = (aw - VW * s) / 2 + 8 + panX + Math.sin(t * 0.07) * 6 * drift;
  const oy = 95 + (ah - VH * s) / 2 + panY + Math.cos(t * 0.05) * 4 * drift; return {s, ox, oy}; }

// ── 그리기 도우미 ──
function bez(a, b, t, bend){ const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2 + bend; const u = 1 - t;
  return [u*u*a.x + 2*u*t*mx + t*t*b.x, u*u*a.y + 2*u*t*my + t*t*b.y]; }
function bendOf(e){ const a = byId[e[0]], b = byId[e[1]]; return e[3] ? 70 : (b.y - a.y) * 0.12; }
function hex(x, y, r){ ctx.beginPath(); for (let i = 0; i < 6; i++){ const ang = Math.PI / 3 * i; const px = x + r * Math.cos(ang), py = y + r * Math.sin(ang);
  i ? ctx.lineTo(px, py) : ctx.moveTo(px, py); } ctx.closePath(); }
const stars = Array.from({length: 140}, () => ({x: Math.random(), y: Math.random(), z: Math.random() * 0.8 + 0.2}));

function draw(ms){
  const t = ms / 1000; ctx.setTransform(DPR, 0, 0, DPR, 0, 0); ctx.clearRect(0, 0, W, H);
  // 별
  for (const s of stars){ const x = (s.x * W + t * 6 * s.z) % W, y = s.y * H; ctx.globalAlpha = 0.25 + 0.5 * s.z * (0.6 + 0.4 * Math.sin(t * s.z * 2 + s.x * 9));
    ctx.fillStyle = "#bcd3f5"; ctx.fillRect(x, y, s.z * 1.6, s.z * 1.6); } ctx.globalAlpha = 1;
  const {s, ox, oy} = tf(t); ctx.setTransform(DPR * s, 0, 0, DPR * s, DPR * ox, DPR * oy);
  // 단계 머리글·안내선
  ctx.textAlign = "center"; ctx.font = "700 17px 'Noto Sans KR',sans-serif";
  for (const [name, x] of COLS){ ctx.strokeStyle = "rgba(140,170,215,.10)"; ctx.lineWidth = 1; ctx.setLineDash([4, 8]);
    ctx.beginPath(); ctx.moveTo(x, 50); ctx.lineTo(x, VH - 10); ctx.stroke(); ctx.setLineDash([]);
    ctx.fillStyle = "rgba(170,195,230,.75)"; ctx.fillText(name, x, 36); }
  // 빔
  for (const e of E){ const a = byId[e[0]], b = byId[e[1]], bend = bendOf(e), act = edgeAct(e);
    const ca = GC[a.g], cb = GC[b.g]; const g = ctx.createLinearGradient(a.x, a.y, b.x, b.y);
    g.addColorStop(0, ca); g.addColorStop(1, cb);
    if (e[2]) { ctx.setLineDash([6, 7]); ctx.strokeStyle = "rgba(120,140,170,.35)"; ctx.lineWidth = 1.6; ctx.beginPath();
      for (let i = 0; i <= 24; i++){ const [x, y] = bez(a, b, i / 24, bend); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); } ctx.stroke(); ctx.setLineDash([]); continue; }
    // 끝이 가늘어지는 곡선 빔 (다각형)
    const L = [], R = [], w0 = 3.2 + 3 * act, w1 = 0.9;
    for (let i = 0; i <= 28; i++){ const tt = i / 28; const [x, y] = bez(a, b, tt, bend); const [x2, y2] = bez(a, b, Math.min(1, tt + 0.01), bend);
      let dx = x2 - x, dy = y2 - y; const l = Math.hypot(dx, dy) || 1; dx /= l; dy /= l; const w = w0 * (1 - tt) + w1 * tt;
      L.push([x - dy * w, y + dx * w]); R.push([x + dy * w, y - dx * w]); }
    ctx.globalAlpha = 0.18 + 0.32 * act; ctx.fillStyle = g; ctx.beginPath(); L.forEach((p, i) => i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1]));
    R.reverse().forEach(p => ctx.lineTo(p[0], p[1])); ctx.closePath(); ctx.fill(); ctx.globalAlpha = 1;
    if (e[3]) { const [x, y] = bez(a, b, 0.5, bend); ctx.fillStyle = "rgba(244,114,182,.9)"; ctx.font = "600 13px 'Noto Sans KR'"; ctx.fillText("사람 판정 반영", x, y - 8); }
  }
  // 패킷
  if (!paused) for (const e of E){ if (e[2]) continue; const r = 0.15 + 2.6 * edgeAct(e); if (Math.random() < r / 60) packets.push({e, t: 0, sp: 0.18 + 0.32 * edgeAct(e) + Math.random() * 0.06}); }
  packets = packets.filter(p => p.t <= 1);
  for (const p of packets){ if (!paused) p.t += p.sp / 60; if (p.t < 0) continue; const a = byId[p.e[0]], b = byId[p.e[1]];
    const [x, y] = bez(a, b, p.t, bendOf(p.e)); const rr = p.big ? 7 : 4.5; const col = GC[a.g];
    const g = ctx.createRadialGradient(x, y, 0, x, y, rr * 2.4); g.addColorStop(0, "#ffffff"); g.addColorStop(0.25, col); g.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = g; ctx.beginPath(); ctx.arc(x, y, rr * 2.4, 0, Math.PI * 2); ctx.fill(); }
  // 노드
  for (const n of N){ const [, sc] = ST[n.st] || ST.standby; const col = GC[n.g];
    // 그림자·유광
    ctx.save(); ctx.shadowColor = n.st === "plan" ? "transparent" : col; ctx.shadowBlur = 18 + 22 * (n.act || 0) + 30 * n.flash;
    hex(n.x, n.y, n.r); const g = ctx.createLinearGradient(n.x, n.y - n.r, n.x, n.y + n.r); g.addColorStop(0, "#16345f"); g.addColorStop(1, "#0a1d3c");
    ctx.fillStyle = g; ctx.fill(); ctx.restore();
    ctx.lineWidth = 2.2; ctx.strokeStyle = col; if (n.st === "plan") ctx.setLineDash([5, 5]); hex(n.x, n.y, n.r); ctx.stroke(); ctx.setLineDash([]);
    // 상태 고리 (가동이면 맥동)
    ctx.lineWidth = 2.6; ctx.strokeStyle = sc; const pr = n.st === "run" ? n.r + 6 + 6 * ((t * 0.8) % 1) : n.r + 6;
    ctx.globalAlpha = n.st === "run" ? 1 - ((t * 0.8) % 1) : 0.85; hex(n.x, n.y, pr); ctx.stroke(); ctx.globalAlpha = 1;
    if (n.flash > 0) n.flash = Math.max(0, n.flash - 0.008);
    ctx.font = (n.g === "src" ? 26 : 32) + "px 'Segoe UI Emoji','Apple Color Emoji','Noto Color Emoji',sans-serif"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.fillText(n.icon, n.x, n.y + 1); ctx.textBaseline = "alphabetic";
    ctx.fillStyle = "#eaf2ff"; ctx.font = "800 18px 'Noto Sans KR',sans-serif"; ctx.fillText(n.label, n.x, n.y + n.r + 25);
    const sub = n.metric || n.sub || ""; if (sub){ ctx.fillStyle = "#9fb6d8"; ctx.font = "500 14px 'Noto Sans KR',sans-serif"; ctx.fillText(sub.length > 22 ? sub.slice(0, 21) + "…" : sub, n.x, n.y + n.r + 45); }
  }
  requestAnimationFrame(draw);
}

// ── 마우스: 끌기·확대·호버·클릭 ──
let drag = null; const tip = document.getElementById("tip");
function hit(mx, my){ const {s, ox, oy} = tf(performance.now() / 1000); const x = (mx - ox) / s, y = (my - oy) / s;
  return N.find(n => Math.hypot(n.x - x, n.y - y) < n.r + 8); }
cv.addEventListener("mousedown", e => { drag = {x: e.clientX, y: e.clientY, px: panX, py: panY, moved: false}; });
window.addEventListener("mouseup", e => { if (drag && !drag.moved){ const r = cv.getBoundingClientRect(); const n = hit(e.clientX - r.left, e.clientY - r.top); if (n) showCard(n); } drag = null; });
cv.addEventListener("mousemove", e => { const r = cv.getBoundingClientRect(); const mx = e.clientX - r.left, my = e.clientY - r.top;
  if (drag){ const dx = e.clientX - drag.x, dy = e.clientY - drag.y; if (Math.abs(dx) + Math.abs(dy) > 3) drag.moved = true; panX = drag.px + dx; panY = drag.py + dy; tip.style.display = "none"; return; }
  const n = hit(mx, my); if (!n){ tip.style.display = "none"; return; }
  const [stl, sc] = ST[n.st] || ST.standby;
  tip.innerHTML = `<b>${n.icon} ${n.label}</b> <span style="color:${sc}">● ${stl}</span><br>${n.metric || n.sub || ""}${n.last ? "<br><span style='color:#8ea6c8'>최근 활동 " + ago(n.last) + "</span>" : ""}`;
  tip.style.display = "block"; tip.style.left = Math.min(mx + 14, W - 290) + "px"; tip.style.top = (my + 12) + "px"; });
cv.addEventListener("wheel", e => { e.preventDefault(); zoom = Math.min(2.2, Math.max(0.6, zoom * (e.deltaY < 0 ? 1.08 : 0.93))); }, {passive: false});
cv.addEventListener("dblclick", () => { zoom = 1; panX = panY = 0; });
function showCard(n){ const [stl, sc] = ST[n.st] || ST.standby; const a = n.agent ? (D.agents || {})[n.agent] : null;
  let h = `<h3>${n.icon} ${n.label}</h3><div class="st" style="color:${sc}">● ${stl}${n.last ? " · 최근 활동 " + ago(n.last) : ""}</div>`;
  if (n.sub) h += `<div style="color:#8ea6c8;margin:4px 0">${n.sub}</div>`;
  for (const x of (n.extra || [])) if (x) h += `<div style="margin:3px 0">${String(x).replace(/</g, "&lt;")}</div>`;
  if (a && a.counts) for (const [k, v] of Object.entries(a.counts)) h += `<div class="kv"><span>${k}</span><b>${typeof v === "number" ? fmt(v) : v}</b></div>`;
  if (a && (a.events || []).length){ h += "<div style='margin-top:6px;color:#8ea6c8'>최근 기록</div>";
    for (const e of a.events.slice(-3).reverse()) h += `<div style="margin:2px 0">· ${ago(e.ts)} — ${String(e.msg || "").replace(/</g, "&lt;")}</div>`; }
  document.getElementById("cb").innerHTML = h; document.getElementById("card").style.display = "block"; }
document.getElementById("cx").onclick = () => document.getElementById("card").style.display = "none";
document.getElementById("fs").onclick = () => { const w = document.getElementById("wrap"); document.fullscreenElement ? document.exitFullscreen() : w.requestFullscreen && w.requestFullscreen(); };
document.getElementById("rs").onclick = () => { zoom = 1; panX = panY = 0; };
document.getElementById("pa").onclick = e => { paused = !paused; e.target.textContent = paused ? "▶ 재생" : "⏸ 정지"; };
document.getElementById("fd").onclick = e => { showFeed = !showFeed; document.getElementById("feed").style.display = showFeed ? "block" : "none";
  e.target.textContent = showFeed ? "☰ 실황 숨기기" : "☰ 실황 보기"; };

// ── 60초마다 GitHub data 브랜치에서 직접 갱신 (Streamlit 재실행 없음) ──
async function getJ(p){ try{ const r = await fetch(RAW + p + "?t=" + Math.floor(Date.now() / 30000), {cache: "no-store"}); if (r.ok) return await r.json(); }catch(x){} return null; }
async function getT(p){ try{ const r = await fetch(RAW + p + "?t=" + Math.floor(Date.now() / 30000), {cache: "no-store"}); if (r.ok) return await r.text(); }catch(x){} return null; }
async function poll(){
  const res = await Promise.all(SNAP.poll_agents.map(a => getJ("live/agents/" + a + ".json")));
  SNAP.poll_agents.forEach((a, i) => { const j = res[i]; if (j) D.agents[a] = Object.assign({}, D.agents[a] || {}, {state: j.state, last_run: j.last_run, summary: j.summary, counts: j.counts, events: (j.events || []).slice(-6)}); });
  const st = await getJ("live/openalex/stats.json"); if (st) D.stats = st;
  const hs = await getJ("labels/hitl/INST-02/summary.json");
  if (hs) D.hitl = {records: hs.records, papers: hs.papers_judged, reviewers: Object.keys(hs.by_reviewer || {}).length,
                    updated: Date.parse(hs.updated_at) / 1000, final: hs.final || {}};
  const rt = await getT("labels/pipeline_runs.jsonl");
  if (rt){ const rows = rt.split("\n").filter(Boolean).slice(-8).map(l => { try{ return JSON.parse(l); }catch(x){ return null; } }).filter(Boolean);
    if (rows.length){ const r = rows[rows.length - 1]; D.labels = Object.assign({}, D.labels, {ts: Date.parse(r.ts) / 1000, extracted: r.extracted, assigned: r.assigned, total: r.total,
      runs: rows.map(x => ({ts: Date.parse(x.ts) / 1000, extracted: x.extracted, assigned: x.assigned, forward: x.forward, hist: x.hist}))}); } }
  bind(); renderKpis(); renderFeed(false);
}
function tick(){ const d = new Date(Date.now() + 9 * 3600 * 1000); document.getElementById("clock").textContent = d.toISOString().slice(11, 19); }
resize(); renderKpis(); renderFeed(true); tick(); setInterval(tick, 1000); setInterval(() => renderFeed(false), 15000);
setInterval(poll, 60000); setTimeout(poll, 4000);
requestAnimationFrame(draw);
</script></body></html>"""
