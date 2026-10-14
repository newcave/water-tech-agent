"""
관제센터 '🏷️ 연구소 라벨 판정' 화면 (HITL 검토) — 계산은 label_review.py

저장 방식 두 가지 (자동 선택)
  A. 직접 저장: Streamlit secrets에 [hitl] github_token(+ passcode)이 있으면 판정 묶음을 data 브랜치
     labels/hitl/<INST>/<시각>_<판정자>.jsonl 로 바로 커밋 (공개 앱이므로 암호를 맞춘 사람만)
  B. 링크 저장: 토큰이 없으면 판정 내용이 미리 채워진 GitHub '새 파일' 링크 → 저장소 권한자가 Commit
"""
from __future__ import annotations

import base64
import html
import json
import re
import time

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

import label_review as lr

REPO = "newcave/water-tech-agent"
BRANCH = "data"
NAVY, BLUE, CYAN = "#0A3D74", "#0B5FAE", "#1FA8C9"
GREEN, AMBER, RED, GRAY = "#16A34A", "#D97706", "#DC2626", "#94A3B8"
STATE_COL = {"소장 확정": "#0A3D74", "담당자 판정": "#2E77C6", "자동 확정": "#1FA8C9", "미검토": "#CBD5E1"}
SUGG_COL = {"ok": GREEN, "ng": RED, "move": AMBER}
SUGG_KO = {"ok": "OK", "ng": "NG 후보", "move": "이관 후보"}
_TAG = re.compile(r"<[^>]+>")

CSS = """<style>
.lr-card {background:#fff; border:1px solid #E3EAF3; border-radius:16px; padding:16px 18px; margin:6px 0 10px;
  box-shadow:0 1px 2px rgba(15,39,68,.04);}
.lr-q {display:inline-block; font-size:.72rem; font-weight:700; border-radius:999px; padding:2px 9px; margin-right:6px;}
.lr-title {font-size:1.12rem; font-weight:800; color:#0F2744; line-height:1.4; margin:6px 0 4px;}
.lr-title a {color:#0F2744; text-decoration:none;} .lr-title a:hover {text-decoration:underline;}
.lr-meta {font-size:.8rem; color:#64748B;}
.lr-op {background:#F4F7FB; border-radius:10px; padding:8px 11px; margin:10px 0 6px; font-size:.88rem; color:#0F2744;}
.lr-op b {color:#17427C;}
.lr-abs {font-size:.86rem; color:#334155; line-height:1.6;}
.lr-score {font-size:2.4rem; font-weight:900; line-height:1;}
.lr-sugg {display:inline-block; font-weight:800; border-radius:8px; padding:3px 10px; font-size:.86rem;}
.lr-why {font-size:.8rem; color:#475569; line-height:1.55; margin-top:8px;}
.lr-why code {font-size:.74rem; background:#EEF3F9; color:#17427C; border-radius:5px; padding:0 4px;}
.lr-chip {display:inline-block; font-size:.72rem; background:#EAF1FA; color:#17549A; border-radius:6px;
  padding:1px 7px; margin:1px 2px;}
.lr-mini {font-size:.78rem; color:#64748B; line-height:1.7;}
</style>"""


# ───────────────────────── 데이터 ─────────────────────────
@st.cache_data(ttl=1800, show_spinner=False)
def _data_jsonl(rel_path: str) -> list:
    try:
        r = requests.get(f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/{rel_path}", timeout=40)
        if r.status_code == 200:
            return lr.parse_jsonl(r.text)
    except Exception:
        pass
    return []


@st.cache_data(ttl=1800, show_spinner=False)
def _items(inst: str, prof_json: str) -> list[dict]:
    prof = json.loads(prof_json)
    papers = _data_jsonl(f"live/openalex/papers_{inst}.jsonl") + \
        _data_jsonl(f"labels/openalex_extended/papers_{inst}.jsonl")
    return lr.build_items(inst, papers, _data_jsonl(f"labels/extract/{inst}.jsonl"),
                          _data_jsonl(f"labels/domain/{inst}.jsonl"),
                          _data_jsonl(f"labels/abstracts/{inst}.jsonl"), prof)


def _secrets() -> dict:
    try:
        return dict(st.secrets.get("hitl", {}))
    except Exception:
        return {}


def _gh_headers() -> dict:
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    tok = _secrets().get("github_token")
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h


@st.cache_data(ttl=60, show_spinner=False)
def _list_batches(inst: str) -> tuple[list[dict], str]:
    """labels/hitl/<inst>/ 의 판정 묶음 파일 목록 → ([{name, sha, download_url}], 오류문구)."""
    try:
        r = requests.get(f"https://api.github.com/repos/{REPO}/contents/{lr.HITL_DIR}/{inst}",
                         params={"ref": BRANCH}, headers=_gh_headers(), timeout=15)
        if r.status_code == 404:
            return [], ""
        if r.status_code == 200:
            return [{"name": f["name"], "sha": f["sha"], "url": f["download_url"]} for f in r.json()
                    if f.get("type") == "file" and f["name"].endswith(".jsonl")], ""
        return [], f"GitHub API {r.status_code} — {r.json().get('message', '')[:80]}"
    except Exception as e:
        return [], f"GitHub API 연결 실패 ({type(e).__name__})"


@st.cache_data(ttl=None, show_spinner=False, max_entries=5000)
def _fetch_batch(url: str, sha: str) -> list[dict]:
    """묶음 파일은 새 이름으로만 쌓이므로(sha 고정) 한 번 받으면 계속 캐시."""
    try:
        r = requests.get(url, timeout=20)
        if r.status_code == 200:
            return lr.parse_jsonl(r.text)
    except Exception:
        pass
    return []


def _remote_records(inst: str) -> tuple[list[dict], int, str]:
    files, err = _list_batches(inst)
    recs = []
    for f in files:
        recs += _fetch_batch(f["url"], f["sha"])
    return recs, len(files), err


def _gh_put(path: str, text: str, message: str) -> tuple[bool, str]:
    body = {"message": message, "branch": BRANCH,
            "content": base64.b64encode(text.encode("utf-8")).decode("ascii")}
    for attempt in range(3):
        try:
            r = requests.put(f"https://api.github.com/repos/{REPO}/contents/{path}",
                             headers=_gh_headers(), json=body, timeout=20)
            if r.status_code in (200, 201):
                return True, "저장됨"
            if r.status_code in (409, 422) and attempt < 2:      # 브랜치 머리가 막 움직였거나 같은 이름 — 이름 바꿔 재시도
                path = path.replace(".jsonl", f"_{attempt + 1}.jsonl")
                time.sleep(1.5)
                continue
            return False, f"GitHub {r.status_code}: {r.json().get('message', '')[:120]}"
        except Exception as e:
            if attempt == 2:
                return False, f"연결 실패 ({type(e).__name__})"
            time.sleep(1.5)
    return False, "저장 실패"


def _dedupe(recs: list[dict]) -> list[dict]:
    seen, out = set(), []
    for r in recs:
        k = (r.get("id"), r.get("ts"), r.get("reviewer"), r.get("decision"), r.get("role"))
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out


# ───────────────────────── 화면 조각 ─────────────────────────
def _clean(t: str) -> str:
    return html.escape(_TAG.sub("", t or "").replace("&amp;", "&"))


def _kpis(rows):
    st.markdown('<div class="kpis">' + "".join(
        f'<div class="kpi" style="border-left-color:{c}"><div class="k-val" style="font-size:1.3rem">{v}</div>'
        f'<div class="k-lab">{l}</div><div class="k-sub">{s}</div></div>' for l, v, s, c in rows) + "</div>",
        unsafe_allow_html=True)


def _score_col(s: int) -> str:
    return GREEN if s >= 80 else (BLUE if s >= 60 else (AMBER if s >= 40 else RED))


def _why_html(it: dict, prof: dict) -> str:
    inst = it["inst"]
    dn = lr.DOMAIN_NAME.get(it["domain_primary"], it["domain_primary"])
    aff = prof.get("domain_affinity", {}).get(inst, {}).get(it["domain_primary"], 0)
    terms = " ".join(f"<code>{html.escape(t)}</code>" for t in it["home_terms"][:7]) or "없음"
    lines = [f"• 본 연구소 적합 <b>{it['home_fit']:.2f}</b> = 도메인 {html.escape(dn)} ({aff:.1f}) · "
             f"키워드 {it['home_kw']:.2f} {terms}"]
    if it.get("best_other") and it["best_other_fit"] >= 0.15:
        ot = " ".join(f"<code>{html.escape(t)}</code>" for t in it["best_other_terms"][:5]) or "–"
        lines.append(f"• 가장 가까운 다른 연구소: {lr.INST_NAME[it['best_other']]} <b>{it['best_other_fit']:.2f}</b> {ot}")
    for m in prof.get("method_institutes", []):
        if m != inst and it["kws"].get(m, 0) >= 0.45:
            lines.append(f"• 수단 키워드: {lr.INST_NAME[m]} {it['kws'][m]:.2f}")
    if it["nonresearch"]:
        lines.append(f"• 연구 문헌이 아닌 유형·제목 (유형 <code>{html.escape(it['type'])}</code>) — 점수 ×{it['type_factor']}")
    elif it["type_factor"] < 1:
        lines.append(f"• 논문이 아닌 유형 <code>{html.escape(it['type'])}</code> — 점수 ×{it['type_factor']}")
    if it.get("also"):
        lines.append("• 공유 후보: " + ", ".join(lr.INST_NAME[x] for x in it["also"]))
    return "<br>".join(lines)


def _card(it: dict, qkind: str, pos: int, total: int, prof: dict, jstate: dict):
    qcol = ("#7C3AED", "#F3EEFF") if qkind == "audit" else ("#0B5FAE", "#EAF1FA")
    qtxt = "감사 표본 (무작위)" if qkind == "audit" else "선별 (기계가 헷갈리거나 바꾸자고 한 것)"
    doi = it.get("doi") or ""
    title = _clean(it["title"]) or "(제목 없음)"
    title_html = f'<a href="{html.escape(doi)}" target="_blank">{title} ↗</a>' if doi.startswith("http") else title
    meta = " · ".join(x for x in [str(it.get("year") or ""), _clean(it.get("venue") or "")[:70],
                                  it.get("type") or "", f"인용 {it.get('cited', 0)}"] if x)
    dups = len(it.get("dups") or [])
    js = jstate.get(it["id"]) or {}
    extra = []
    if dups:
        extra.append(f'<span class="lr-chip">같은 제목 레코드 {dups}건 함께 판정</span>')
    if js.get("skips"):
        extra.append(f'<span class="lr-chip">건너뜀 {js["skips"]}회</span>')
    dn = lr.DOMAIN_NAME.get(it["domain_primary"], it["domain_primary"])
    sc = it["score"]
    sg = it["suggestion"]
    sg_txt = SUGG_KO[sg] + (f" → {lr.INST_NAME[it['to']]}" if it.get("to") else "") + \
        (f" ({lr.REASON_KO.get(it['reason'], '')})" if it.get("reason") else "")
    abstract = _clean(it.get("abstract") or "")
    short = abstract if len(abstract) <= 900 else abstract[:900] + " …"
    left, right = st.columns([5, 2])
    with left:
        st.markdown(f"""<div class="lr-card">
  <span class="lr-q" style="color:{qcol[0]};background:{qcol[1]}">{qtxt}</span>
  <span class="lr-meta">{pos} / {total}</span> {''.join(extra)}
  <div class="lr-title">{title_html}</div>
  <div class="lr-meta">{meta}</div>
  <div class="lr-op"><b>대상</b> {_clean(it['object'])} &nbsp;·&nbsp; <b>문제</b> {_clean(it['problem'])}
    &nbsp;<span class="lr-chip">{html.escape(it['domain_primary'])} {html.escape(dn)}</span></div>
  <div class="lr-abs">{short or '<i>초록 없음</i>'}</div>
</div>""", unsafe_allow_html=True)
        if len(abstract) > 900:
            with st.expander("초록 전체"):
                st.markdown(f'<div class="lr-abs">{abstract}</div>', unsafe_allow_html=True)
    with right:
        st.markdown(f"""<div class="lr-card">
  <div class="lr-meta">기계 적합도 점수</div>
  <div class="lr-score" style="color:{_score_col(sc)}">{sc}<span style="font-size:1rem;color:#94A3B8"> / 100</span></div>
  <div style="margin-top:8px"><span class="lr-sugg" style="background:{SUGG_COL[sg]}1A;color:{SUGG_COL[sg]}">기계 제안: {html.escape(sg_txt)}</span></div>
  <div class="lr-why">{_why_html(it, prof)}</div>
</div>""", unsafe_allow_html=True)


# ───────────────────────── 기록 쌓기 ─────────────────────────
def _push(rec: dict):
    st.session_state.setdefault("lr_buf", []).append(rec)
    st.session_state["lr_last"] = rec


def _on_decide(it: dict, decision: str, qkind: str, who: str, role: str):
    k = it["id"]
    to = st.session_state.get(f"lr_to_{k}") if decision == "move" else None
    reason = st.session_state.get(f"lr_reason_{k}") if decision == "ng" else None
    also = st.session_state.get(f"lr_also_{k}") or [] if decision in ("ok", "move") else []
    note = st.session_state.get(f"lr_note_{k}") or ""
    _push(lr.make_record(it, decision, who, role, qkind, to=to, also=list(also), reason=reason, note=note))


def _undo_last():
    buf = st.session_state.get("lr_buf", [])
    if buf:
        buf.pop()
    st.session_state["lr_last"] = None


def _save_direct(who: str) -> tuple[bool, str]:
    buf = st.session_state.get("lr_buf", [])
    if not buf:
        return True, "저장할 판정 없음"
    by_inst = {}
    for r in buf:
        by_inst.setdefault(r["inst"], []).append(r)
    msgs = []
    for inst, rows in by_inst.items():
        ok, msg = _gh_put(lr.batch_path(inst, who), lr.to_jsonl(rows),
                          f"🏷️ HITL 라벨 판정 {inst} {len(rows)}건 ({who})")
        if not ok:
            return False, msg
        st.session_state.setdefault("lr_saved", []).extend(rows)
        msgs.append(f"{inst} {len(rows)}건")
    st.session_state["lr_buf"] = []
    _list_batches.clear()
    return True, "저장됨 — " + ", ".join(msgs)


# ───────────────────────── 탭 ─────────────────────────
def _tab_judge(items, jstate, prof, inst, who, role, direct, tau_info):
    tau = tau_info["tau"]
    rv = prof.get("review", {})
    q = lr.build_queue(items, jstate, prof, who, tau=tau)
    R = lr.reps(items)
    mine = sum(1 for r in st.session_state.get("lr_buf", []) + st.session_state.get("lr_saved", [])
               if r.get("inst") == inst and r.get("decision") != "skip")
    n_aud = sum(1 for _, k in q if k == "audit")
    auto_n = sum(1 for it in R if not lr.human_decision(jstate.get(it["id"])) and it["suggestion"] == "ok"
                 and it["score"] >= tau)
    _kpis([("남은 판정 카드", f"{len(q):,}", f"감사 {n_aud} · 선별 {len(q) - n_aud}", NAVY),
           ("이번 세션 내 판정", f"{mine}", f"미저장 {len(st.session_state.get('lr_buf', []))}건", BLUE),
           ("자동 확정 (사람 생략)", f"{auto_n:,}", f"제안 OK & 점수 ≥ τ {tau}" + ("" if tau_info["calibrated"] else " (잠정)"), CYAN),
           ("판정 단위", f"{len(R):,}", f"레코드 {len(items):,} (같은 제목 {len(items) - len(R)}건 묶음)", GRAY)])

    bulk = lr.bulk_candidates(items, jstate)
    if bulk:
        with st.expander(f"⚡ 일괄 판정 — 기계가 '연구 문헌 아님'으로 본 {len(bulk)}건 (심사평·답변·안내 등)", expanded=False):
            st.caption("한 장씩 볼 필요가 적은 것들입니다. 제목을 훑고 동의하지 않는 줄만 체크를 풀고 저장하세요. "
                       "체크된 줄은 NG(연구 문헌 아님)로 기록됩니다.")
            df = pd.DataFrame([{"동의": True, "점수": it["score"], "유형": it["type"],
                                "제목": _TAG.sub("", it["title"])[:110], "대상": it["object"][:40], "id": it["id"]}
                               for it in bulk])
            ed = st.data_editor(df, key=f"lr_bulk_{inst}", hide_index=True, width="stretch",
                                disabled=["점수", "유형", "제목", "대상", "id"], height=min(420, 40 + 35 * len(df)),
                                column_config={"동의": st.column_config.CheckboxColumn("NG 동의", width="small"),
                                               "id": None})
            chosen = ed[ed["동의"]]["id"].tolist()
            if st.button(f"체크한 {len(chosen)}건 NG로 판정", key=f"lr_bulk_go_{inst}", disabled=not chosen):
                byid = {it["id"]: it for it in bulk}
                for pid in chosen:
                    _push(lr.make_record(byid[pid], "ng", who, role, "bulk", reason="nonresearch"))
                st.rerun()

    if not q:
        st.success("판정할 카드가 없습니다 — 남은 논문은 모두 사람 판정 또는 자동 확정 구간입니다. 👏")
        return
    it, qkind = q[0]
    _card(it, qkind, 1, len(q), prof, jstate)
    k = it["id"]
    others = [i for i in lr.INSTS if i != inst]
    default_to = it.get("to") or it.get("best_other") or others[0]
    c1, c2, c3, c4 = st.columns([2, 2, 3, 3])
    c1.selectbox("NG 사유", list(lr.REASON_KO), key=f"lr_reason_{k}",
                 index=list(lr.REASON_KO).index(it.get("reason") or "out_of_scope"),
                 format_func=lambda x: lr.REASON_KO[x])
    c2.selectbox("이관할 연구소", others, key=f"lr_to_{k}", index=others.index(default_to) if default_to in others else 0,
                 format_func=lambda x: lr.INST_NAME[x])
    c3.multiselect("함께 볼 연구소 (공유, 선택)", others, key=f"lr_also_{k}",
                   default=[x for x in it.get("also", []) if x in others], format_func=lambda x: lr.INST_NAME[x])
    c4.text_input("메모 (선택)", key=f"lr_note_{k}", placeholder="판정 근거·애매한 점")
    b1, b2, b3, b4, b5 = st.columns([2, 2, 2, 2, 1.4])
    b1.button("✅ OK — 이 연구소 맞음", key=f"lr_ok_{k}", type="primary", width="stretch",
              on_click=_on_decide, args=(it, "ok", qkind, who, role))
    b2.button("❌ NG — 빼기", key=f"lr_ng_{k}", width="stretch",
              on_click=_on_decide, args=(it, "ng", qkind, who, role))
    b3.button("↪️ 이관 — 다른 연구소로", key=f"lr_mv_{k}", width="stretch",
              on_click=_on_decide, args=(it, "move", qkind, who, role))
    b4.button("⏭️ 건너뛰기", key=f"lr_sk_{k}", width="stretch",
              on_click=_on_decide, args=(it, "skip", qkind, who, role))
    b5.button("↩︎ 되돌리기", key=f"lr_undo_{k}", width="stretch", on_click=_undo_last,
              disabled=not st.session_state.get("lr_buf"))
    last = st.session_state.get("lr_last")
    if last:
        st.caption(f"방금: {lr.DECISION_KO.get(last['decision'], last['decision'])}"
                   + (f" → {lr.INST_NAME.get(last.get('to'), '')}" if last.get("to") else "")
                   + f" · {last['id']}")
    if len(q) > 1:
        nxt = "".join(f"<div>{'🟣' if kk == 'audit' else '🔵'} <b>{x['score']}</b> "
                      f"<span style='color:{SUGG_COL[x['suggestion']]}'>{SUGG_KO[x['suggestion']]}</span> — "
                      f"{_clean(x['title'])[:90]}</div>" for x, kk in q[1:6])
        st.markdown(f'<div class="lr-mini"><b>다음 카드</b>{nxt}</div>', unsafe_allow_html=True)
    if direct and len(st.session_state.get("lr_buf", [])) >= rv.get("save_every", 10):
        ok, msg = _save_direct(who)
        (st.toast if ok else st.error)(f"자동 저장: {msg}")


def _tab_director(items, jstate, prof, inst, who):
    dq = lr.director_queue(items, jstate)
    if not dq:
        st.success("소장 확인을 기다리는 담당자 판정이 없습니다.")
        return
    st.caption("담당자 판정 중 아직 소장 확인이 없는 것입니다. 기계 제안과 다른 판정·NG·이관이 위에 옵니다. "
               "'정정'을 고르지 않으면 담당자 판정 그대로 확정됩니다.")
    opts = ["그대로"] + ["ok", "ng"] + [f"move:{i}" for i in lr.INSTS if i != inst]

    def fmt(x):
        if x == "그대로":
            return "그대로 확정"
        if x.startswith("move:"):
            return "이관 → " + lr.INST_NAME[x[5:]]
        return lr.DECISION_KO[x]

    rows = []
    for it, r in dq[:200]:
        dec = lr.DECISION_KO[r["decision"]] + (f"→{lr.INST_NAME.get(r.get('to'), '')}" if r.get("to") else "")
        rows.append({"확정": True, "정정": "그대로", "담당자 판정": dec, "담당자": r.get("reviewer"),
                     "기계": SUGG_KO[it["suggestion"]] + (f"→{lr.INST_NAME[it['to']]}" if it.get("to") else ""),
                     "점수": it["score"], "제목": _TAG.sub("", it["title"])[:100], "메모": r.get("note") or "",
                     "id": it["id"]})
    df = pd.DataFrame(rows)
    ed = st.data_editor(df, key=f"lr_dir_{inst}", hide_index=True, width="stretch",
                        disabled=["담당자 판정", "담당자", "기계", "점수", "제목", "메모", "id"],
                        column_config={"확정": st.column_config.CheckboxColumn("확정", width="small"),
                                       "정정": st.column_config.SelectboxColumn("정정", options=opts, width="medium"),
                                       "id": None})
    sel = ed[ed["확정"]]
    if st.button(f"체크한 {len(sel)}건 소장 확정", type="primary", key=f"lr_dir_go_{inst}", disabled=sel.empty):
        byid = {it["id"]: (it, r) for it, r in dq}
        for _, row in sel.iterrows():
            it, r = byid[row["id"]]
            fix = row["정정"] or "그대로"
            if fix == "그대로":
                dec, to = r["decision"], r.get("to")
            elif fix.startswith("move:"):
                dec, to = "move", fix[5:]
            else:
                dec, to = fix, None
            _push(lr.make_record(it, dec, who, "director", "director", to=to, also=r.get("also") or [],
                                 reason=r.get("reason") if dec == "ng" else None,
                                 note=("" if fix == "그대로" else f"소장 정정 (담당자: {r['decision']})")))
        st.rerun()


def _tab_metrics(items, jstate, prof, inst, tau_info, plotly_layout):
    tau = tau_info["tau"]
    m = lr.metrics(items, jstate, tau)
    p, lo, hi = m["accuracy"]
    MIN_AUD = 10                      # 감사 판정이 이보다 적으면 비율을 숫자로 내세우지 않음
    enough = m["audit_judged"] >= MIN_AUD
    acc_v = f"{p:.0%}" if enough else "–"
    acc_s = (f"감사 표본 {m['audit_judged']}/{m['audit_size']}건 판정 · 95% {lo:.0%}–{hi:.0%}" if enough else
             f"감사 표본 {m['audit_judged']}/{m['audit_size']}건 판정 — {MIN_AUD}건부터 표시")
    S = m["states"]
    N = m["N"] or 1
    human = S.get("소장 확정", 0) + S.get("담당자 판정", 0)
    _kpis([("기존 라벨 적합률 (추정)", acc_v, acc_s, NAVY),
           ("자동 확정 문턱 τ", f"{tau}" + ("" if tau_info["calibrated"] else " (잠정)"), tau_info["why"][:60], BLUE),
           ("자동 확정 비율", f"{S.get('자동 확정', 0) / N:.0%}", f"{S.get('자동 확정', 0):,} / {m['N']:,} 레코드", CYAN),
           ("사람 판정 비율 (HITL)", f"{human / N:.0%}", f"담당자 {S.get('담당자 판정', 0)} · 소장 확정 {S.get('소장 확정', 0)}", GREEN),
           ("미검토", f"{S.get('미검토', 0) / N:.0%}", f"{S.get('미검토', 0):,} 레코드", GRAY),
           ("기계–사람 일치", "–" if not m["judged"] else f"{m['agree_rate']:.0%}", f"판정 {m['judged']}묶음", AMBER)])
    if enough and m["expected_bad"] is not None:
        st.caption(f"감사 표본으로 추정하면 {lr.INST_NAME[inst]} 라벨 {m['N']:,}건 중 약 **{m['expected_bad']:,}건**이 "
                   f"NG 또는 다른 연구소 몫입니다 (95% 범위 {round((1 - hi) * m['N']):,}–{round((1 - lo) * m['N']):,}).")

    c1, c2 = st.columns(2)
    with c1:
        st.markdown('<div class="sect">자동 / HITL 비율</div>', unsafe_allow_html=True)
        fig = go.Figure()
        for s in lr.STATE_ORDER:
            v = S.get(s, 0)
            fig.add_bar(y=["라벨"], x=[v], name=s, orientation="h", marker_color=STATE_COL[s],
                        text=[f"{s} {v:,} ({v / N:.0%})" if v / N >= 0.08 else ""], textposition="inside",
                        hovertemplate=f"{s}: %{{x:,}}<extra></extra>")
        fig.update_layout(**plotly_layout, barmode="stack", height=150, showlegend=True,
                          legend=dict(orientation="h", y=-0.35), xaxis=dict(visible=False), yaxis=dict(visible=False))
        st.plotly_chart(fig, width="stretch")
        st.caption("자동 확정 = 기계 제안 OK이고 점수 ≥ τ인데 아직 사람이 안 본 것. 기계의 NG·이관 제안은 사람이 "
                   "판정하기 전까지 '미검토'로 남습니다.")

        st.markdown('<div class="sect">점수 분포 (판정 단위)</div>', unsafe_allow_html=True)
        R = lr.reps(items)
        fig = go.Figure()
        for sg in ["ok", "move", "ng"]:
            fig.add_histogram(x=[it["score"] for it in R if it["suggestion"] == sg], name=SUGG_KO[sg],
                              marker_color=SUGG_COL[sg], xbins=dict(start=0, end=101, size=5))
        fig.add_vline(x=tau, line_dash="dash", line_color=NAVY,
                      annotation_text=f"τ {tau}", annotation_position="top")
        fig.update_layout(**plotly_layout, barmode="stack", height=260, legend=dict(orientation="h", y=1.12),
                          xaxis_title="기계 적합도 점수", yaxis_title="묶음 수")
        st.plotly_chart(fig, width="stretch")
    with c2:
        st.markdown('<div class="sect">점수 보정 — 구간별 사람 판정 OK 비율</div>', unsafe_allow_html=True)
        cal = lr.calibration(items, jstate)
        xs = [c["bin"] for c in cal]
        ys = [None if c["judged"] == 0 else c["ok_rate"] for c in cal]
        fig = go.Figure(go.Bar(
            x=xs, y=ys, marker_color=[_score_col(c["lo"] + 5) for c in cal],
            error_y=dict(type="data", symmetric=False,
                         array=[0 if c["judged"] == 0 else c["ci_hi"] - c["ok_rate"] for c in cal],
                         arrayminus=[0 if c["judged"] == 0 else c["ok_rate"] - c["ci_lo"] for c in cal],
                         color="#64748B"),
            text=[f"{c['ok']}/{c['judged']}" if c["judged"] else "판정 없음" for c in cal], textposition="outside",
            hovertemplate="%{x}: OK %{y:.0%}<extra></extra>"))
        fig.add_hline(y=prof.get("review", {}).get("tau_precision", .95), line_dash="dot", line_color=GREEN,
                      annotation_text="자동 확정 기준 95%", annotation_position="bottom left")
        fig.update_layout(**plotly_layout, height=260, yaxis=dict(range=[0, 1.12], tickformat=".0%"),
                          xaxis_title="점수 구간 (막대 위: OK/판정)", showlegend=False)
        st.plotly_chart(fig, width="stretch")
        st.caption("오른쪽으로 갈수록 OK 비율이 높아야 점수가 쓸모 있습니다. 판정이 쌓이면 τ가 이 표로 다시 계산됩니다.")

        st.markdown('<div class="sect">기계 제안 vs 사람 판정</div>', unsafe_allow_html=True)
        conf = m["confusion"]
        if conf:
            dfc = pd.DataFrame([[conf.get((a, b), 0) for b in ["ok", "ng", "move"]] for a in ["ok", "ng", "move"]],
                               index=[f"기계 {SUGG_KO[a]}" for a in ["ok", "ng", "move"]],
                               columns=["사람 OK", "사람 NG", "사람 이관"])
            st.dataframe(dfc, width="stretch")
            npv, nlo, _ = m["ng_precision"]
            if not (npv != npv):
                st.caption(f"기계 NG 제안이 맞은 비율 {npv:.0%} (95% 하한 {nlo:.0%}) — 하한이 90%를 넘으면 "
                           "'NG 후보 자동 적용'을 검토할 수 있습니다.")
        else:
            st.caption("아직 사람 판정이 없습니다.")

    c3, c4, c5 = st.columns(3)
    with c3:
        st.markdown('<div class="sect">이관 흐름</div>', unsafe_allow_html=True)
        mv = m["moves"]
        if mv:
            st.dataframe(pd.DataFrame([{"이관처": lr.INST_NAME.get(k, k), "건": v} for k, v in
                                       sorted(mv.items(), key=lambda x: -x[1])]), hide_index=True,
                         width="stretch")
        else:
            sg = [it for it in lr.reps(items) if it["suggestion"] == "move"]
            st.caption(f"사람 판정 이관 없음 · 기계 이관 후보 {len(sg)}건")
    with c4:
        st.markdown('<div class="sect">NG 사유</div>', unsafe_allow_html=True)
        if m["ng_reasons"]:
            st.dataframe(pd.DataFrame([{"사유": lr.REASON_KO.get(k, k), "건": v} for k, v in
                                       sorted(m["ng_reasons"].items(), key=lambda x: -x[1])]),
                         hide_index=True, width="stretch")
        else:
            st.caption("사람 판정 NG 없음")
    with c5:
        st.markdown('<div class="sect">판정자</div>', unsafe_allow_html=True)
        if m["reviewers"]:
            st.dataframe(pd.DataFrame([{"판정자": k[0], "역할": k[1], "묶음": v} for k, v in
                                       sorted(m["reviewers"].items(), key=lambda x: -x[1])]),
                         hide_index=True, width="stretch")
        else:
            st.caption("아직 없음")
    with st.expander("τ 후보표 — 문턱별 판정 수·OK 비율"):
        st.dataframe(pd.DataFrame(tau_info["table"]).rename(columns={
            "tau": "τ", "n": "판정", "ok": "OK", "precision": "OK 비율", "ci_lo": "95% 하한", "pass": "기준 통과"}),
            hide_index=True, width="stretch",
            column_config={"OK 비율": st.column_config.NumberColumn(format="percent"),
                           "95% 하한": st.column_config.NumberColumn(format="percent")})


def _tab_log(items, jstate, records, inst, tau, n_files, err):
    ft = pd.DataFrame(lr.final_table(items, jstate, tau))
    c1, c2, c3 = st.columns([2, 2, 3])
    sf = c1.multiselect("상태", lr.STATE_ORDER, default=[s for s in lr.STATE_ORDER if s != "자동 확정"],
                        key=f"lr_lf_s_{inst}")
    df_ = c2.multiselect("판정", ["ok", "ng", "move", "pending"], default=["ok", "ng", "move", "pending"],
                         key=f"lr_lf_d_{inst}",
                         format_func=lambda x: lr.DECISION_KO[x])
    qtxt = c3.text_input("제목 검색", key=f"lr_lf_q_{inst}")
    v = ft[ft["state"].isin(sf) & ft["decision"].isin(df_)]
    if qtxt:
        v = v[v["title"].str.contains(qtxt, case=False, na=False, regex=False)]
    show = v.assign(title=v["title"].map(lambda t: _TAG.sub("", t or "")),
                    decision=v["decision"].map(lambda d: lr.DECISION_KO.get(d, d)),
                    to=v["to"].map(lambda t: lr.INST_NAME.get(t, "") if t else ""))
    show = show.fillna("")
    st.dataframe(show[["state", "decision", "to", "score", "machine", "title", "year", "domain", "reviewer",
                       "role", "reason", "also", "dup_of", "doi"]].rename(columns={
                           "state": "상태", "decision": "판정", "to": "이관처", "score": "점수", "machine": "기계 제안",
                           "title": "제목", "year": "연도", "domain": "도메인", "reviewer": "판정자", "role": "역할",
                           "reason": "NG 사유", "also": "공유", "dup_of": "중복 대표", "doi": "DOI"}),
                 hide_index=True, width="stretch", height=420,
                 column_config={"DOI": st.column_config.LinkColumn(display_text="열기")})
    d1, d2 = st.columns(2)
    d1.download_button(f"⬇️ 최종 라벨표 CSV ({len(ft):,}건)", ft.to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"label_final_{inst}.csv", mime="text/csv")
    d2.download_button(f"⬇️ 판정 원기록 JSONL ({len(records):,}줄)", lr.to_jsonl(records).encode("utf-8"),
                       file_name=f"label_judgments_{inst}.jsonl", mime="application/json")
    st.caption(f"원기록 위치: data 브랜치 `{lr.HITL_DIR}/{inst}/` 묶음 파일 {n_files}개 (append-only, 지우지 않고 "
               "새 판정이 이전 판정을 덮음 · 소장 기록이 담당자 기록보다 우선)" + (f" · ⚠️ {err}" if err else ""))


def _tab_guide(direct, has_token):
    st.markdown(f"""
#### 이 화면이 하는 일
논문은 **어느 연구소 키워드로 검색됐는가**로 연구소 라벨이 붙습니다. 이 라벨이 맞는지 사람이 판정합니다.
**OK**(맞음) · **NG**(빼기: 연구소 범위 밖, 연구 문헌 아님, 물 분야 아님, 중복) · **이관**(다른 연구소 몫) · **건너뛰기**.

#### 사람 손을 아끼는 방법 — 기계 점수 + 두 갈래 표본
1. **기계 적합도 점수(0–100)** — 본 연구소 적합(W 도메인 0.5 + 제목·초록·대상/문제 키워드 0.5)과
   가장 가까운 다른 연구소와의 차이로 계산. 심사평·답변·정오표 같은 비연구 문헌은 크게 감점.
   키워드와 도메인 친화도는 `data_seed/label_review_profiles.json`에서 연구소가 직접 고칩니다.
2. **감사 표본(무작위 20%)** — 점수와 상관없이 고정된 무작위 표본. 이것만으로 *기존 라벨이 얼마나 맞는지*를
   편향 없이 추정합니다 (95% 신뢰구간과 함께).
3. **선별 큐** — 기계가 NG·이관을 제안한 것 먼저, 그다음 점수 낮은 OK 순. 같은 제목의 중복 레코드는 한 장으로 묶습니다.
4. **자동 확정 문턱 τ** — 판정이 쌓이면 "점수 τ 이상이면 사람이 봐도 95% 이상 OK"인 가장 낮은 τ를 다시 계산합니다.
   τ 이상의 OK 제안은 사람이 안 봐도 확정(자동), 그 아래만 사람이 봅니다. 판정이 쌓일수록 τ가 내려가 사람 몫이 줄어듭니다.
5. **안전장치** — 기계는 라벨을 *지우거나 옮기지* 못합니다. NG·이관은 사람이 판정해야 적용됩니다.
   점수 공식을 바꿔도 과거 판정은 그대로라서 바로 다시 보정됩니다.

#### 최종 상태 우선순위
**소장 확정 > 담당자 판정 > 자동 확정 > 미검토**. 지금은 시범(수자원환경연구소)이고, 다음 단계에서 연구소마다
담당자가 판정하고 소장이 '소장 확인' 화면에서 일괄 확정합니다.

#### 저장 방식 — 지금: {'**직접 저장** (앱이 data 브랜치에 바로 커밋)' if direct else '**링크 저장** (GitHub 새 파일 링크 → Commit)'}
- 토큰이 없으면: 판정이 이 브라우저에 모였다가, 판정 내용이 미리 채워진 GitHub '새 파일' 링크로 저장합니다
  (저장소 쓰기 권한이 있는 사람만 Commit 가능). 브라우저를 닫으면 미저장 판정은 사라집니다.
- 직접 저장으로 바꾸려면 Streamlit Cloud → 앱 Settings → **Secrets**에 아래를 넣습니다 (채팅·코드에 붙여넣지 마세요).
```toml
[hitl]
github_token = "github_pat_..."   # fine-grained PAT · 저장소 newcave/water-tech-agent · Contents: Read and write
passcode = "담당자 암호"
director_passcode = "소장 암호"
```
  앱은 공개라서 암호가 없으면 토큰이 있어도 직접 저장을 켜지 않습니다. 판정은 `data` 브랜치 `labels/hitl/` 아래에만 씁니다.
{'' if has_token else '- 현재 secrets에 토큰이 없습니다.'}
""")


# ───────────────────────── 진입점 ─────────────────────────
def render(load_json, plotly_layout: dict):
    st.markdown(CSS, unsafe_allow_html=True)
    st.markdown('<div class="sect">🏷️ 연구소 라벨 판정 — 이 논문이 이 연구소 것이 맞나요?</div>', unsafe_allow_html=True)
    st.caption("기계가 모든 논문에 적합도 점수를 매기고, 사람은 무작위 감사 표본과 기계가 헷갈리거나 바꾸자고 한 논문만 봅니다. "
               "판정이 쌓이면 '사람이 안 봐도 되는 점수 문턱(τ)'을 다시 계산합니다. 원리는 맨 오른쪽 탭.")
    prof = load_json("label_review_profiles.json") or {}
    if not prof:
        st.error("data_seed/label_review_profiles.json을 읽지 못했습니다.")
        return
    sec = _secrets()
    has_token = bool(sec.get("github_token"))
    direct_possible = has_token and bool(sec.get("passcode"))
    pilot = prof.get("pilot") or ["INST-02"]

    c1, c2, c3, c4 = st.columns([2.2, 2, 1.6, 2])
    inst = c1.selectbox("연구소", pilot, key="lr_inst", format_func=lambda x: f"{lr.INST_NAME[x]} ({x})",
                        help="시범: 수자원환경연구소. 다른 연구소는 label_review_profiles.json의 pilot에 추가하면 열립니다.")
    who = c2.text_input("판정자 이름", key="lr_who", placeholder="예: 홍길동").strip()
    role = c3.radio("역할", ["reviewer", "director"], key="lr_role", horizontal=True,
                    format_func=lambda x: lr.ROLE_KO[x])
    direct, auth_msg = False, ""
    if direct_possible:
        code = c4.text_input("판정 암호", type="password", key="lr_code",
                             help="직접 저장(앱 → GitHub)용 암호. 소장은 소장 암호.")
        want = sec.get("director_passcode") if role == "director" else sec.get("passcode")
        if code and want and code == want:
            direct = True
        elif code:
            auth_msg = "암호가 맞지 않습니다" + (" (소장 암호 확인)" if role == "director" else "")
        elif role == "director" and not sec.get("director_passcode"):
            auth_msg = "secrets에 director_passcode가 없어 소장 직접 저장은 꺼져 있습니다"
    else:
        c4.markdown('<div class="note" style="margin-top:30px">저장: GitHub 링크 방식 '
                    '(secrets에 토큰·암호를 넣으면 직접 저장)</div>', unsafe_allow_html=True)
    if auth_msg:
        st.warning(auth_msg)

    with st.spinner(f"{lr.INST_NAME[inst]} 라벨 불러오는 중…"):
        items = _items(inst, json.dumps(prof, sort_keys=True, ensure_ascii=False))
    if not items:
        st.warning("라벨 데이터를 불러오지 못했습니다 (data 브랜치 labels/domain·extract).")
        return
    remote, n_files, err = _remote_records(inst)
    records = _dedupe(remote + st.session_state.get("lr_saved", []) + st.session_state.get("lr_buf", []))
    records = [r for r in records if r.get("inst") == inst]
    jstate = lr.judgment_state(records, inst, lr.canon_map(items))
    tau_info = lr.recommend_tau(items, jstate, prof)

    # ── 저장 상태 줄 ──
    buf = [r for r in st.session_state.get("lr_buf", [])]
    if buf:
        s1, s2 = st.columns([5, 2])
        if direct:
            s1.info(f"미저장 판정 {len(buf)}건 — {prof.get('review', {}).get('save_every', 10)}건마다 자동 저장됩니다.")
            if s2.button("💾 지금 저장", key="lr_save_now", type="primary", width="stretch"):
                ok, msg = _save_direct(who)
                (st.toast if ok else st.error)(msg)
                if ok:
                    st.rerun()
        else:
            s1.info(f"미저장 판정 {len(buf)}건 — 아래 링크를 열어 GitHub에서 **Commit changes**를 누르면 저장됩니다 "
                    "(저장소 쓰기 권한 필요). 브라우저를 닫으면 사라집니다.")
            links = lr.prefill_urls(REPO, BRANCH, inst, who or "anon", [r for r in buf if r["inst"] == inst])
            with s2:
                for i, (u, n) in enumerate(links):
                    st.link_button(f"💾 GitHub에 저장 {i + 1}/{len(links)} ({n}건)", u, width="stretch")
            with s1:
                d1, d2 = st.columns(2)
                d1.download_button("⬇️ 판정 파일 받기 (.jsonl)", lr.to_jsonl(buf).encode("utf-8"),
                                   file_name=lr.batch_path(inst, who or "anon").split("/")[-1],
                                   mime="application/json", width="stretch")
                if d2.button("✔︎ GitHub에 Commit 했음 — 목록 비우기", width="stretch", key="lr_mark_saved"):
                    st.session_state.setdefault("lr_saved", []).extend(buf)
                    st.session_state["lr_buf"] = []
                    _list_batches.clear()
                    st.rerun()

    tabs = st.tabs(["✍️ 판정하기", "📊 현황·지표", "🗂️ 판정 기록", "ℹ️ 운영 원리"])
    with tabs[0]:
        if not who:
            st.info("위에 **판정자 이름**을 넣으면 판정 카드가 열립니다. (이름은 판정 기록에 남습니다)")
        elif role == "director":
            mode = st.radio("소장 화면", ["소장 확인 대기", "직접 판정"], horizontal=True, key="lr_dir_mode",
                            label_visibility="collapsed")
            if mode == "소장 확인 대기":
                _tab_director(items, jstate, prof, inst, who)
            else:
                _tab_judge(items, jstate, prof, inst, who, role, direct, tau_info)
        else:
            _tab_judge(items, jstate, prof, inst, who, role, direct, tau_info)
    with tabs[1]:
        _tab_metrics(items, jstate, prof, inst, tau_info, plotly_layout)
    with tabs[2]:
        _tab_log(items, jstate, records, inst, tau_info["tau"], n_files, err)
    with tabs[3]:
        _tab_guide(direct, has_token)
