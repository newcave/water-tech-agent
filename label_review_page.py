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
import os
import re
import threading
import time
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

import data_cache as dc
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
@st.cache_resource(ttl=1800, show_spinner=False, max_entries=16)
def _items(inst: str, prof_json: str) -> list[dict]:
    """판정 항목(점수 포함). cache_resource라 다시 그릴 때 복사하지 않는다 — 항목 dict를 고치지 말 것.
    원본 4개 파일은 동시에 받고(data_cache), 지식노트와 같은 캐시를 함께 쓴다."""
    prof = json.loads(prof_json)
    core = dc.inst_core(inst)
    return lr.build_items(inst, core["papers"], core["extract"], core["domain"], dc.inst_abstracts(inst), prof)


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


@st.cache_data(ttl=90, show_spinner=False)
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


@st.cache_resource(show_spinner=False)
def _batch_store() -> dict:
    """sha → 판정 기록. 묶음 파일은 새 이름으로만 쌓이므로(sha 고정) 한 번 받으면 계속 쓴다."""
    return {}


def _remote_records(inst: str) -> tuple[list[dict], int, str]:
    files, err = _list_batches(inst)
    store = _batch_store()
    missing = [f for f in files if f["sha"] not in store]
    if missing:                                    # 처음 여는 묶음 파일들은 동시에 받는다
        for f, text in zip(missing, dc.fetch_many([f["url"] for f in missing], timeout=20)):
            if text is not None:
                store[f["sha"]] = lr.parse_jsonl(text)
    recs = []
    for f in files:
        recs += store.get(f["sha"], [])
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
        k = lr.rec_key(r)
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out


def _rerun():
    """이 화면(fragment)만 다시 그린다. fragment 재실행 중이 아니면(앱 전체 실행 중) 앱 전체를 다시 그린다."""
    try:
        st.rerun(scope="fragment")
    except st.errors.StreamlitAPIException:
        st.rerun()


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


QKIND = {"audit": ("감사 표본 (무작위)", "#7C3AED", "#F3EEFF"),
         "triage": ("선별 (기계가 헷갈리거나 바꾸자고 한 것)", "#0B5FAE", "#EAF1FA"),
         "sample1": ("1차 샘플 (무작위 · 판정자마다 따로)", "#0F766E", "#E6F6F4")}


def _card(it: dict, qkind: str, pos: int, total: int, prof: dict, jstate: dict, blind: bool = False):
    qtxt, *qcol = QKIND.get(qkind, QKIND["triage"])
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
        if blind:
            st.markdown("""<div class="lr-card"><div class="lr-meta">기계 적합도 점수</div>
  <div class="lr-score" style="color:#CBD5E1">?</div>
  <div class="lr-why">블라인드 판정 중 — 기계 점수·제안을 가려 사람 판단이 기계에 끌려가지 않게 합니다.
  판정 뒤 <b>1차 결과</b> 탭에서 기계와 얼마나 맞았는지 공개됩니다.</div></div>""", unsafe_allow_html=True)
            return
        st.markdown(f"""<div class="lr-card">
  <div class="lr-meta">기계 적합도 점수</div>
  <div class="lr-score" style="color:{_score_col(sc)}">{sc}<span style="font-size:1rem;color:#94A3B8"> / 100</span></div>
  <div style="margin-top:8px"><span class="lr-sugg" style="background:{SUGG_COL[sg]}1A;color:{SUGG_COL[sg]}">기계 제안: {html.escape(sg_txt)}</span></div>
  <div class="lr-why">{_why_html(it, prof)}</div>
</div>""", unsafe_allow_html=True)


# ───────────────────────── 기록 쌓기 ─────────────────────────
class _Pending:
    """서버 임시 보관함 — 판정 버튼을 누르는 즉시 서버 디스크에 한 줄씩 쌓는다.
    새로고침·창 닫기·세션 끊김에도 남고, 모든 판정자 화면에 바로 누적된다. GitHub에 올라간 것은
    다음 화면부터 자동으로 빠진다(대조). 앱 서버를 새로 띄우면(재배포·잠듦) 사라질 수 있으므로
    GitHub 저장(직접 저장 또는 링크 Commit)이 최종 기록이다."""

    def __init__(self):
        self.lock = threading.Lock()
        self.dir = Path(os.environ.get("HITL_PENDING_DIR") or (Path.home() / ".wta_hitl"))
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, inst: str) -> Path:
        return self.dir / f"pending_{inst}.jsonl"

    def read(self, inst: str) -> list[dict]:
        p = self._path(inst)
        with self.lock:
            return lr.parse_jsonl(p.read_text(encoding="utf-8")) if p.exists() else []

    def _write(self, inst: str, rows: list[dict]):
        p = self._path(inst)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(lr.to_jsonl(rows), encoding="utf-8")
        tmp.replace(p)

    def add(self, rec: dict):
        with self.lock:
            with self._path(rec["inst"]).open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def update(self, inst: str, fn):
        """fn(rows) → 새 rows. 읽기·쓰기를 한 번에 (다른 판정자와 동시에 눌러도 안전)."""
        p = self._path(inst)
        with self.lock:
            rows = lr.parse_jsonl(p.read_text(encoding="utf-8")) if p.exists() else []
            new = fn(rows)
            if new is not None:
                self._write(inst, new)
            return new

    def reconcile(self, inst: str, remote_keys: set) -> int:
        """GitHub에 이미 올라간 것과, 올린 지 1시간이 지난 것은 보관함에서 뺀다 → 뺀 건수."""
        now = time.time()
        out = {}

        def fn(rows):
            keep = [r for r in rows if lr.rec_key(r) not in remote_keys
                    and not (r.get("_flushed") and now - r["_flushed"] > 3600)]
            out["n"] = len(rows) - len(keep)
            return keep if out["n"] else None
        self.update(inst, fn)
        return out.get("n", 0)


@st.cache_resource(show_spinner=False)
def _pending() -> _Pending:
    return _Pending()


def _push(rec: dict):
    _pending().add(rec)
    st.session_state["lr_last"] = rec


def _on_decide(it: dict, decision: str, qkind: str, who: str, role: str):
    k = it["id"]
    to = st.session_state.get(f"lr_to_{k}") if decision == "move" else None
    reason = st.session_state.get(f"lr_reason_{k}") if decision == "ng" else None
    also = st.session_state.get(f"lr_also_{k}") or [] if decision in ("ok", "move") else []
    note = st.session_state.get(f"lr_note_{k}") or ""
    _push(lr.make_record(it, decision, who, role, qkind, to=to, also=list(also), reason=reason, note=note))


def _undo_last(inst: str, who: str):
    """내 가장 최근 판정(아직 GitHub에 안 올린 것) 하나를 지운다."""
    def fn(rows):
        for i in range(len(rows) - 1, -1, -1):
            if rows[i].get("reviewer") == who and not rows[i].get("_flushed"):
                return rows[:i] + rows[i + 1:]
        return None
    _pending().update(inst, fn)
    st.session_state["lr_last"] = None


def _my_unsaved(inst: str, who: str) -> list[dict]:
    return [r for r in _pending().read(inst) if r.get("reviewer") == who and not r.get("_flushed")]


def _clean_rec(r: dict) -> dict:
    return {k: v for k, v in r.items() if not k.startswith("_")}


def _my_unsaved_clean(inst: str, who: str) -> list[dict]:
    return [_clean_rec(r) for r in _my_unsaved(inst, who)]


def _save_direct(inst: str, who: str) -> tuple[bool, str]:
    """내 미저장 판정을 묶음 파일 하나로 data 브랜치에 커밋 (보관함에는 '올림' 표시만, GitHub에서 보이면 자동 정리)."""
    rows = _my_unsaved(inst, who)
    if not rows:
        return True, "저장할 판정 없음"
    ok, msg = _gh_put(lr.batch_path(inst, who), lr.to_jsonl([_clean_rec(r) for r in rows]),
                      f"🏷️ HITL 라벨 판정 {inst} {len(rows)}건 ({who})")
    if not ok:
        return False, msg
    keys, now = {lr.rec_key(r) for r in rows}, time.time()
    _pending().update(inst, lambda all_: [({**r, "_flushed": now} if lr.rec_key(r) in keys else r) for r in all_])
    _list_batches.clear()
    return True, f"GitHub 저장 {len(rows)}건"


# ───────────────────────── 탭 ─────────────────────────
def _tab_judge(items, jstate, prof, inst, who, role, direct, tau_info):
    tau = tau_info["tau"]
    rv = prof.get("review", {})
    q = lr.build_queue(items, jstate, prof, who, tau=tau)
    R = lr.reps(items)
    rv_me = (lr.by_reviewer(st.session_state.get("lr_records", []), inst, lr.canon_map(items)).get(who)
             or {"dec": {}})
    mine = len(rv_me["dec"])
    unsaved = len(_my_unsaved(inst, who))
    n_aud = sum(1 for _, k in q if k == "audit")
    auto_n = sum(1 for it in R if not lr.human_decision(jstate.get(it["id"])) and it["suggestion"] == "ok"
                 and it["score"] >= tau)
    _kpis([("남은 판정 카드", f"{len(q):,}", f"감사 {n_aud} · 선별 {len(q) - n_aud}", NAVY),
           ("내 판정 (누적)", f"{mine}", f"GitHub 미저장 {unsaved}건 (서버 임시 보관)", BLUE),
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
                _rerun()

    if not q:
        st.success("판정할 카드가 없습니다 — 남은 논문은 모두 사람 판정 또는 자동 확정 구간입니다. 👏")
        return
    it, qkind = q[0]
    _card(it, qkind, 1, len(q), prof, jstate)
    _controls(it, qkind, inst, who, role, direct, prof, nxt=[(x, kk) for x, kk in q[1:6]])


def _controls(it, qkind, inst, who, role, direct, prof, nxt=(), blind=False):
    """판정 입력줄(NG 사유·이관처·공유·메모) + OK/NG/이관/건너뛰기/되돌리기 + 다음 카드."""
    k = it["id"]
    others = [i for i in lr.INSTS if i != inst]
    default_to = others[0] if blind else (it.get("to") or it.get("best_other") or others[0])
    c1, c2, c3, c4 = st.columns([2, 2, 3, 3])
    c1.selectbox("NG 사유", list(lr.REASON_KO), key=f"lr_reason_{k}",
                 index=list(lr.REASON_KO).index("out_of_scope" if blind else (it.get("reason") or "out_of_scope")),
                 format_func=lambda x: lr.REASON_KO[x])
    c2.selectbox("이관할 연구소", others, key=f"lr_to_{k}", index=others.index(default_to) if default_to in others else 0,
                 format_func=lambda x: lr.INST_NAME[x])
    c3.multiselect("함께 볼 연구소 (공유, 선택)", others, key=f"lr_also_{k}",
                   default=[] if blind else [x for x in it.get("also", []) if x in others], format_func=lambda x: lr.INST_NAME[x])
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
    b5.button("↩︎ 되돌리기", key=f"lr_undo_{k}", width="stretch", on_click=_undo_last, args=(inst, who),
              disabled=not _my_unsaved(inst, who))
    last = st.session_state.get("lr_last")
    if last:
        st.caption(f"방금: {lr.DECISION_KO.get(last['decision'], last['decision'])}"
                   + (f" → {lr.INST_NAME.get(last.get('to'), '')}" if last.get("to") else "")
                   + f" · {last['id']}")
    if nxt:
        dot = {"audit": "🟣", "triage": "🔵", "sample1": "🟢"}
        rows = "".join(f"<div>{dot.get(kk, '🔵')} " + ("" if blind else
                       f"<b>{x['score']}</b> <span style='color:{SUGG_COL[x['suggestion']]}'>"
                       f"{SUGG_KO[x['suggestion']]}</span> — ") + f"{_clean(x['title'])[:90]}</div>" for x, kk in nxt)
        st.markdown(f'<div class="lr-mini"><b>다음 카드</b>{rows}</div>', unsafe_allow_html=True)


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
        _rerun()


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


def _ledger_section(items, records, inst, saved_keys, plotly_layout, key):
    """📒 판정 대장 — 한 번 누른 판정은 모두 여기 누적된다 (판정자별 집계 · 날짜별 누적 · 전체 기록)."""
    if not records:
        st.info("아직 판정 기록이 없습니다.")
        return
    n_saved = sum(1 for r in records if lr.rec_key(r) in saved_keys)
    st.caption(f"전체 {len(records):,}줄 — GitHub 저장 {n_saved:,} · 서버 임시 {len(records) - n_saved:,}. "
               f"GitHub에 올라간 묶음은 자동으로 `{lr.HITL_DIR}/{inst}/ledger.jsonl` 하나로 합쳐지고 "
               "`summary.json`·`final.csv`로 정리됩니다.")
    c1, c2 = st.columns([3, 2])
    with c1:
        st.markdown('<div class="sect">판정자별 누적</div>', unsafe_allow_html=True)
        st.dataframe(pd.DataFrame(lr.reviewer_summary(records, saved_keys)), hide_index=True, width="stretch")
    with c2:
        st.markdown('<div class="sect">날짜별 누적 판정</div>', unsafe_allow_html=True)
        cum = lr.daily_cumulative(records)
        fig = go.Figure()
        for w, pts in cum.items():
            fig.add_scatter(x=[d for d, _ in pts], y=[n for _, n in pts], name=w, mode="lines+markers",
                            line_shape="hv", hovertemplate=f"{w} · %{{x}}: 누적 %{{y}}<extra></extra>")
        fig.update_layout(**plotly_layout, height=230, legend=dict(orientation="h", y=1.15),
                          xaxis=dict(type="category", title=None), yaxis=dict(title="누적 판정", rangemode="tozero"))
        st.plotly_chart(fig, width="stretch", key=f"lr_cum_{key}")
    st.markdown('<div class="sect">전체 판정 기록 (최신순)</div>', unsafe_allow_html=True)
    rows = pd.DataFrame(lr.ledger_rows(records, items, saved_keys))
    who_f = st.multiselect("판정자", sorted(rows["판정자"].unique()), key=f"lr_led_w_{key}", placeholder="전체")
    v = rows[rows["판정자"].isin(who_f)] if who_f else rows
    st.dataframe(v.drop(columns=["id"]), hide_index=True, width="stretch", height=min(460, 40 + 35 * len(v)))
    st.download_button(f"⬇️ 판정 대장 CSV ({len(v):,}줄)", v.to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"hitl_ledger_{inst}.csv", mime="text/csv", key=f"lr_led_dl_{key}")


def _tab_log(items, jstate, records, inst, tau, n_files, err, saved_keys=frozenset(), plotly_layout=None):
    st.markdown('<div class="sect">📒 판정 대장 (누적)</div>', unsafe_allow_html=True)
    _ledger_section(items, records, inst, saved_keys, plotly_layout or {}, key="full")
    st.divider()
    st.markdown('<div class="sect">🏷️ 논문별 최종 라벨</div>', unsafe_allow_html=True)
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
    st.caption(f"원기록 위치: data 브랜치 `{lr.HITL_DIR}/{inst}/` 파일 {n_files}개 (판정 대장 ledger.jsonl + 아직 합쳐지지 않은 "
               "묶음). 지우지 않고 쌓으며 같은 논문은 새 판정이 이전 판정을 덮음 · 소장 기록이 담당자 기록보다 우선"
               + (f" · ⚠️ {err}" if err else ""))


def _tab_sample(items, sample, rvw, prof, inst, who, role, blind):
    mine = rvw.get(who) or {"dec": {}, "skip": set()}
    q = lr.sample_queue(sample, mine)
    done = sum(1 for it in sample if it["id"] in mine["dec"])
    n = len(sample)
    others = {w: sum(1 for it in sample if it["id"] in d["dec"]) for w, d in rvw.items() if w != who}
    others = {w: c for w, c in others.items() if c}
    _kpis([("내 진행", f"{done} / {n}", "남은 " + f"{n - done}장" + (f" (건너뜀 {len(mine['skip'])})" if mine["skip"] else ""), "#0F766E"),
           ("함께 판정 중", f"{len(others)}명", ", ".join(f"{w} {c}" for w, c in list(others.items())[:4]) or "아직 없음", BLUE),
           ("GitHub 미저장", f"{len(_my_unsaved(inst, who))}건", "서버에 임시 보관 중 — GitHub 저장이 최종 기록", AMBER),
           ("예상 소요", f"약 {max(1, round((n - done) * 0.6))}분", "장당 30–40초 기준", GRAY)])
    st.progress(done / n if n else 0.0, text=f"1차 샘플 {done}/{n}")
    if not q:
        st.success(f"1차 샘플 {n}장을 모두 판정했습니다 👏 — 저장한 뒤 **📋 1차 결과** 탭에서 기계와의 일치, "
                   "다른 판정자와의 일치를 확인하세요.")
        return
    it = q[0]
    _card(it, "sample1", done + 1, n, prof, {}, blind=blind)
    _controls(it, "sample1", inst, who, role, False, prof, nxt=[(x, "sample1") for x in q[1:4]], blind=blind)


KAPPA_TXT = [(0.8, "거의 완벽"), (0.6, "상당히 일치"), (0.4, "보통"), (0.2, "약함"), (-1, "낮음 — 판정 기준 정리 필요")]


def _tab_sample_result(items, sample, records, prof, inst, plotly_layout):
    canon = lr.canon_map(items)
    sm = lr.sample_summary(sample, records, inst, canon)
    if not sm["judged"]:
        st.info("아직 저장된 1차 샘플 판정이 없습니다. 판정을 저장하면(링크 Commit 또는 직접 저장) 여기에 결과가 나옵니다.")
        return
    p, lo, hi = sm["accuracy"]
    best = max(sm["pairs"], key=lambda x: x["n"]) if sm["pairs"] else None
    kap = best["kappa"] if best else float("nan")
    ktxt = "" if kap != kap else next(t for th, t in KAPPA_TXT if kap >= th)      # kap != kap → NaN(값 없음)
    enough = sm["judged"] >= 10                       # 10장 미만이면 비율을 숫자로 내세우지 않음
    _kpis([("기존 라벨 적합률 (1차)", f"{p:.0%}" if enough else "–",
            f"합의 판정 {sm['judged']}/{sm['size']}장 · 95% {lo:.0%}–{hi:.0%}" if enough else
            f"합의 판정 {sm['judged']}/{sm['size']}장 — 10장부터 표시", NAVY),
           ("기계 제안과 일치", f"{sm['machine_agree'] / sm['judged']:.0%}", f"{sm['machine_agree']}/{sm['judged']}장", BLUE),
           ("판정자 간 일치 (κ)", "–" if not best else f"{best['kappa']:.2f}",
            (f"{best['a']}·{best['b']} {best['n']}장 · 일치 {best['agree']:.0%} · {ktxt}") if best else "2명 이상이 5장 이상 겹치면 표시", CYAN),
           ("의견 갈림", f"{len(sm['split'])}장", "판정자끼리 다르게 본 카드 — 기준 논의 대상", AMBER)])
    if enough:
        st.caption(f"{lr.INST_NAME[inst]} 라벨 {len(items):,}건에 적용하면 약 {round((1 - p) * len(items)):,}건"
                   f"(95% 범위 {round((1 - hi) * len(items)):,}–{round((1 - lo) * len(items)):,})이 NG 또는 다른 연구소 몫으로 "
                   "추정됩니다. 1차 샘플은 무작위라 이 추정은 편향이 없지만, 장 수가 적어 범위가 넓습니다.")
    by = {it["id"]: it for it in sample}
    c1, c2 = st.columns([3, 2])
    with c1:
        st.markdown('<div class="sect">카드별 결과 — 갈린 것·기계와 다른 것 먼저</div>', unsafe_allow_html=True)
        rows = []
        for i, v in sm["consensus"].items():
            it = by[i]
            mach = it["suggestion"] + (f":{it['to']}" if it["suggestion"] == "move" else "")
            fmt = lambda lab: (lr.DECISION_KO[lab.split(":")[0]] +
                               (f"→{lr.INST_NAME.get(lab.split(':')[1], '')}" if ":" in lab else ""))
            rows.append({"갈림": "⚠️" if not v["unanimous"] else "", "기계 일치": "✔︎" if v["label"] == mach else "✘",
                         "합의 판정": fmt(v["label"]), "기계 제안": fmt(mach), "점수": it["score"], "판정자 수": v["n"],
                         "제목": _TAG.sub("", it["title"])[:90], "_k": (v["unanimous"], v["label"] == mach, -it["score"])})
        df = pd.DataFrame(rows).sort_values("_k").drop(columns="_k")
        st.dataframe(df, hide_index=True, width="stretch", height=min(400, 40 + 35 * len(df)))
    with c2:
        st.markdown('<div class="sect">점수 구간별 (1차 샘플)</div>', unsafe_allow_html=True)
        bins = [(0, 40), (40, 60), (60, 80), (80, 90), (90, 101)]
        brow = []
        for a, b in bins:
            ids = [i for i in sm["consensus"] if a <= by[i]["score"] < b]
            k = sum(1 for i in ids if sm["consensus"][i]["decision"] == "ok")
            brow.append({"점수": f"{a}–{min(b, 100) - (0 if b > 100 else 1)}", "판정": len(ids), "OK": k,
                         "OK 비율": f"{k / len(ids):.0%}" if ids else "–"})
        st.dataframe(pd.DataFrame(brow), hide_index=True, width="stretch")
        st.caption("높은 점수 구간이 거의 다 OK면 τ를 85보다 낮춰도 됩니다. 1차 판정은 전체 지표·τ 계산에도 그대로 들어갑니다.")
        st.markdown('<div class="sect">판정자 진행</div>', unsafe_allow_html=True)
        st.dataframe(pd.DataFrame([{"판정자": w, "판정": c, "진행": c / sm["size"]} for w, c in
                                   sorted(sm["progress"].items(), key=lambda x: -x[1])]),
                     hide_index=True, width="stretch",
                     column_config={"진행": st.column_config.ProgressColumn(min_value=0, max_value=1, format="percent")})
        if sm["pairs"]:
            st.dataframe(pd.DataFrame([{"판정자 쌍": f"{x['a']} · {x['b']}", "겹친 장": x["n"], "일치": x["agree"],
                                        "κ": round(x["kappa"], 2) if x["kappa"] == x["kappa"] else None}
                                       for x in sm["pairs"]]), hide_index=True, width="stretch",
                         column_config={"일치": st.column_config.NumberColumn(format="percent")})


def _tab_sample_guide(n):
    st.markdown(f"""
#### 1차 샘플은 무엇인가
수자원환경연구소 라벨 가운데 **무작위로 고정한 {n}장**입니다. 누가 열어도 같은 {n}장이 같은 순서로 나옵니다.
전체 판정(🏷️ 연구소 라벨 판정)을 시작하기 전에 이것부터 보면 세 가지를 바로 알 수 있습니다.

1. **기존 라벨이 몇 % 맞는가** — 무작위 표본이라 편향 없는 추정 (95% 범위 함께)
2. **기계 점수가 쓸 만한가** — 점수 구간별 OK 비율, 기계 제안과의 일치율
3. **사람끼리 기준이 같은가** — 2명 이상이 같은 {n}장을 따로 보면 일치율·Cohen κ가 나오고, 갈린 카드가 기준 논의 목록이 됩니다

#### 진행 방법
- 기본은 **블라인드**(기계 점수·제안 가림)입니다. 기계에 끌려가지 않은 판단이어야 기계 일치율이 정직하게 나옵니다.
- 판정자마다 따로 봅니다. 다른 사람이 이미 본 카드도 내 큐에서는 빠지지 않습니다.
- 장당 30–40초, {n}장이면 30–40분 정도. 저장은 위쪽 저장 줄(링크 Commit 또는 직접 저장)로 합니다.
- 여기서 한 판정은 감사 표본 판정으로 전체 지표·τ 계산에 그대로 들어갑니다 (같은 카드를 여러 명이 보면 최신 판정 기준).

#### 끝나면
**📋 1차 결과** 탭 → 갈린 카드로 판정 기준(예: 정책·거버넌스 논문은 수자원환경 OK인가 경영 이관인가)을 정하고,
필요하면 `data_seed/label_review_profiles.json`의 키워드·문턱을 고친 뒤 전체 판정으로 넘어갑니다.
""")


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
- 판정 버튼을 누르는 즉시 **서버 임시 보관함**에 쌓입니다 — 새로고침·창 닫기에도 남고, 모든 판정자 화면에 바로 누적됩니다.
  다만 앱 서버가 새로 뜨면(재배포·잠듦) 임시 보관분은 사라질 수 있으니 GitHub 저장이 최종 기록입니다.
- 토큰이 없으면: 판정 내용이 미리 채워진 GitHub '새 파일' 링크를 열어 Commit (저장소 쓰기 권한자만). 올라간 것은
  자동으로 임시 보관함에서 빠지고, data 브랜치에서 **판정 대장(ledger.jsonl) 하나로 합쳐져 summary.json·final.csv로 정리**됩니다.
- 직접 저장이면 5건마다 앱이 알아서 GitHub에 올립니다 (링크 누를 필요 없음).
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
def render(load_json, plotly_layout: dict, mode: str = "full"):
    """mode='full' 전체 판정 화면, mode='sample' 1차 샘플(무작위 고정 n장, 판정자마다 따로·블라인드).
    화면 전체를 fragment로 감싸, 판정 버튼을 누를 때 관제센터 머리띠·사이드바·에이전트 현황은 다시 그리지 않고
    이 화면만 다시 그린다 (클릭 반응이 빨라짐)."""
    _render_body(load_json, plotly_layout, mode)


@st.fragment
def _render_body(load_json, plotly_layout: dict, mode: str):
    st.markdown(CSS, unsafe_allow_html=True)
    prof = load_json("label_review_profiles.json") or {}
    if not prof:
        st.error("data_seed/label_review_profiles.json을 읽지 못했습니다.")
        return
    n1 = (prof.get("first_round") or {}).get("size", 60)
    if mode == "sample":
        st.markdown(f'<div class="sect">🧪 라벨 1차 샘플 — 무작위 {n1}장으로 먼저 감 잡기</div>', unsafe_allow_html=True)
        st.caption(f"누가 열어도 같은 {n1}장(무작위 고정)을 판정자마다 따로, 기계 점수를 가린 채 봅니다. 끝나면 기존 라벨 적합률·"
                   "기계 일치율·판정자 간 일치도가 나옵니다. 여기 판정은 전체 판정 지표에도 그대로 들어갑니다.")
    else:
        st.markdown('<div class="sect">🏷️ 연구소 라벨 판정 — 이 논문이 이 연구소 것이 맞나요?</div>', unsafe_allow_html=True)
        st.caption("기계가 모든 논문에 적합도 점수를 매기고, 사람은 무작위 감사 표본과 기계가 헷갈리거나 바꾸자고 한 논문만 봅니다. "
                   "판정이 쌓이면 '사람이 안 봐도 되는 점수 문턱(τ)'을 다시 계산합니다. 원리는 맨 오른쪽 탭.")
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
    save_every = prof.get("review", {}).get("save_every", 5)
    if direct and who and len(_my_unsaved(inst, who)) >= save_every:
        ok, msg = _save_direct(inst, who)                     # 직접 저장: save_every건마다 자동 커밋 (화면 그리기 전에)
        (st.toast if ok else st.error)(f"자동 저장: {msg}")
    remote, n_files, err = _remote_records(inst)
    if not err:                                               # GitHub에 올라간 건 보관함에서 자동으로 뺀다
        _pending().reconcile(inst, {lr.rec_key(r) for r in remote})
    saved_keys = {lr.rec_key(r) for r in remote}
    pend = [_clean_rec(r) for r in _pending().read(inst)]
    records = _dedupe(remote + st.session_state.get("lr_saved", []) + pend)
    records = [r for r in records if r.get("inst") == inst]
    st.session_state["lr_records"] = records
    jstate = lr.judgment_state(records, inst, lr.canon_map(items))
    tau_info = lr.recommend_tau(items, jstate, prof)

    # ── 저장 상태 줄: 판정은 누르는 즉시 서버에 쌓이고(누적), GitHub 저장이 최종 기록 ──
    mine = _my_unsaved_clean(inst, who) if who else []
    others_pending = sum(1 for r in pend if r.get("reviewer") != who)
    if mine:
        s1, s2 = st.columns([5, 2])
        if direct:
            s1.info(f"내 판정 {len(mine)}건이 서버에 임시 보관 중 — {save_every}건마다 GitHub에 자동 저장됩니다.")
            if s2.button("💾 지금 저장", key="lr_save_now", type="primary", width="stretch"):
                ok, msg = _save_direct(inst, who)
                (st.toast if ok else st.error)(msg)
                if ok:
                    _rerun()
        else:
            s1.info(f"내 판정 **{len(mine)}건이 서버에 임시 보관** 중입니다 (새로고침·창 닫기에도 유지, 화면에는 이미 누적 반영). "
                    "최종 기록은 오른쪽 링크를 열어 GitHub에서 **Commit changes** — 올라가면 1–2분 안에 자동 정리됩니다.")
            links = lr.prefill_urls(REPO, BRANCH, inst, who, mine)
            with s2:
                for i, (u, n) in enumerate(links):
                    st.link_button(f"💾 GitHub에 저장 {i + 1}/{len(links)} ({n}건)", u, width="stretch")
            with s1:
                d1, d2 = st.columns(2)
                d1.download_button("⬇️ 판정 파일 받기 (.jsonl)", lr.to_jsonl(mine).encode("utf-8"),
                                   file_name=lr.batch_path(inst, who).split("/")[-1],
                                   mime="application/json", width="stretch")
                if d2.button("🔄 GitHub 저장 확인", width="stretch", key="lr_check_saved",
                             help="Commit 뒤 누르면 바로 대조해 임시 보관함을 정리합니다 (안 눌러도 1–2분 안에 자동)"):
                    _list_batches.clear()
                    _rerun()
    if others_pending > 0:
        st.caption(f"다른 판정자의 임시 보관 판정 {others_pending}건도 화면에 함께 누적되어 있습니다 (GitHub 저장 전).")

    if mode == "sample":
        sample = lr.first_round(items, prof)
        rvw = lr.by_reviewer(records, inst, lr.canon_map(items))
        tabs = st.tabs(["✍️ 샘플 판정", "📋 1차 결과", "📒 판정 대장", "ℹ️ 1차 샘플이란"])
        with tabs[0]:
            if not who:
                st.info("위에 **판정자 이름**을 넣으면 1차 샘플 카드가 열립니다. 이름이 같아야 이어서 할 수 있습니다.")
            else:
                blind = st.toggle("기계 점수 가리기 (블라인드 판정 — 권장)", value=True, key="lr_blind")
                _tab_sample(items, sample, rvw, prof, inst, who, role, blind)
        with tabs[1]:
            _tab_sample_result(items, sample, records, prof, inst, plotly_layout)
        with tabs[2]:
            sids = {it["id"] for it in sample}
            only = st.toggle("1차 샘플 판정만", value=True, key="lr_led_only_sample")
            _ledger_section(items, [r for r in records if r.get("id") in sids] if only else records, inst,
                            saved_keys, plotly_layout, key="sample")
        with tabs[3]:
            _tab_sample_guide(len(sample))
        return

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
        _tab_log(items, jstate, records, inst, tau_info["tau"], n_files, err, saved_keys, plotly_layout)
    with tabs[3]:
        _tab_guide(direct, has_token)
