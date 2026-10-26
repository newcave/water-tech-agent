#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
oa_rising — openalex(newcave/openalex) 상승 연구주제 분석 결과 연동 (1단계: 결과 읽기 → 집계만 공개)

openalex 저장소가 '방법의 주인'이다 (Hamed–Rao MK + BH-FDR → association strength 동시출현 네트워크 → Louvain,
5~6년 구간별 분석). 이 스크립트는 다시 계산하지 않고, 그 결과(비공개 newcave/openalex-data)에서 화면에 필요한
집계만 뽑아 공개 저장소 data_seed/oa_rising/에 쓴다.

입력: OA_DATA_DIR (기본 'oadata') = openalex-data 체크아웃 — 워크플로가 secrets.OPENALEX_DATA_TOKEN으로 결과 폴더만 받음
  · archive/수자원_논문/results   수자원 12개 핵심 저널(이 저장소 J01–J12와 같은 목록) 2000–2025 — 논문판
  · results/<분야>/               openalex 웹앱이 분야별로 만든 결과 (있는 분야만)
출력: data_seed/oa_rising/index.json, data_seed/oa_rising/<key>.json
공개 범위: 용어별 검정 통계 · 커뮤니티(크기·추이·대표 용어·연결 강도) · 검토 라벨 · 근거 논문 제목(OpenAlex 공개 메타)·
  구간별 요약. 옮기지 않는 것: 논문 해석 원문(paper_interpretations · paper_trajectories), 검토 메모(judgment · caution),
  전체 논문 목록(all_papers), 코퍼스 원본(01_corpus).
"""
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get("OA_DATA_DIR", "oadata"))
OUT = ROOT / "data_seed" / "oa_rising"
# openalex config.py의 분야 이름 → (key, 연구소). 수자원위성(INST-06)은 openalex에 분야가 없다.
FIELDS = {"수자원환경": ("water_env", "INST-02"), "AI": ("ai", "INST-07"), "물인프라안전": ("infra", "INST-04"),
          "상하수도": ("sewerage", "INST-03"), "물에너지": ("energy", "INST-05"), "경영": ("management", "INST-01")}
TOP_TERMS, TOP_PAPERS, TOP_DECLINING, TOP_EDGES = 15, 8, 40, 300


def _r(x, n=4):
    try:
        return None if pd.isna(x) else round(float(x), n)
    except (TypeError, ValueError):
        return None


def _read(path: Path) -> pd.DataFrame | None:
    for p in (path, path.with_suffix(".csv"), path.with_suffix(".parquet")):
        if p.exists():
            return pd.read_parquet(p) if p.suffix == ".parquet" else pd.read_csv(p)
    return None


def _json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def build(src: Path, key: str, title: str, inst: str | None, note: str) -> dict | None:
    full, review, win = src / "02_full_period", src / "03_full_period_review", src / "04_windowed"
    tags = _read(full / "trend_tags_unigram_fdr.parquet")
    part = _read(full / "rising_unigram_clusters.parquet")
    series = _read(full / "cluster_trends_fdr_assoc.parquet")
    summ = _read(full / "cluster_trends_summary_fdr_assoc.csv")
    if tags is None or part is None or summ is None:
        print(f"[oa_rising] {key}: 전체기간 결과 없음 — 건너뜀 ({src})")
        return None
    run = _json(full / "run_summary.json")
    manifest = _json(review / "manifest.json")
    term_col = "용어" if "용어" in part.columns else "term"

    # ── 용어별 검정 결과 ──
    lab = tags["추세(MK-FDR)"].value_counts().to_dict()
    cl_of = dict(zip(part[term_col], part["cluster"]))

    def row(t):
        return {"term": t["용어"], "cluster": (int(cl_of[t["용어"]]) if t["용어"] in cl_of else None),
                "tau": _r(t.get("MK_tau"), 3), "q": (float(f"{t['BH_q']:.3g}") if pd.notna(t.get("BH_q")) else None), "sen": _r(t.get("Sen_slope(%p_연)"), 4),
                "z3": _r(t.get("최근3년_zscore"), 2), "burst": _r(t.get("최대버스트강도"), 3),
                "burst_year": (int(t["버스트연도"]) if pd.notna(t.get("버스트연도")) else None),
                "share": _r(t.get("전체기간_평균비중(%)"), 4), "share5": _r(t.get("최근5년_평균비중(%)"), 4),
                "docs": int(t.get("전체기간_총건수") or 0),
                "first": (int(t["첫등장연도"]) if pd.notna(t.get("첫등장연도")) else None),
                "new": bool(t.get("신규진입(2015~)", False))}
    rising = [row(t) for _, t in tags[tags["추세(MK-FDR)"].eq("Rising")].sort_values("MK_tau", ascending=False).iterrows()]
    declining = [row(t) for _, t in tags[tags["추세(MK-FDR)"].eq("Declining")].sort_values("MK_tau").head(TOP_DECLINING).iterrows()]

    # ── 커뮤니티 ──
    terms = _read(review / "terms.csv")
    edges = _read(review / "edges.csv")
    papers = _read(review / "selected_papers.csv")
    interp = {int(c["cluster"]): c for c in _json(review / "interpretations.json").get("clusters", [])}
    ai = {int(c["cluster"]): c for c in _json(review / "ai_labels.json").get("clusters", [])}
    clusters = []
    for _, s in summ.sort_values("cluster").iterrows():
        c = int(s["cluster"])
        if c in interp and interp[c].get("label"):
            label, label_src = interp[c]["label"], "검토 라벨"
        elif c in ai and ai[c].get("label"):
            label, label_src = ai[c]["label"], "AI 라벨 (참고용)"
        else:
            label, label_src = str(s.get("label") or f"군집 {c}"), "분석 코드 라벨"
        if terms is not None:
            tt = terms[terms["cluster"].eq(c)].sort_values("internal_strength", ascending=False).head(TOP_TERMS)
            top = [{"term": t["term"], "docs": int(t["document_count"]), "inside": _r(t["internal_weight_fraction"], 3)}
                   for _, t in tt.iterrows()]
        else:
            top = [{"term": x.strip(), "docs": None, "inside": None} for x in str(s.get("top_terms", "")).split("|")]
        ser = []
        if series is not None:
            ss = series[series["cluster"].eq(c)].sort_values("year")
            ser = [[int(y), _r(v, 3)] for y, v in zip(ss["year"], ss["document_share_pct"])]
        pp = []
        if papers is not None:
            for _, p in papers[papers["cluster"].eq(c)].head(TOP_PAPERS).iterrows():
                pp.append({"id": str(p["id"]).rsplit("/", 1)[-1], "title": str(p["display_name"]),
                           "year": int(p["year"]) if pd.notna(p["year"]) else None, "journal": str(p.get("journal") or ""),
                           "terms": str(p.get("matched_terms") or ""), "why": str(p.get("selection") or "")})
        themes = [{"name": t.get("name"), "pairs": t.get("pairs", [])} for t in interp.get(c, {}).get("themes", [])]
        clusters.append({
            "cluster": c, "label": label, "label_src": label_src, "size": int(s["term_count"]),
            "share": _r(s.get("mean_document_share_pct"), 3), "tau": _r(s.get("mk_tau"), 3), "p": _r(s.get("mk_p"), 6),
            "sen": _r(s.get("sen_slope_pct_point_per_year"), 4), "gain": _r(s.get("recent5_minus_first5_pct_point"), 3),
            "top": top, "series": ser, "papers": pp, "themes": themes,
            "ai_insight": (ai.get(c, {}).get("insight") if label_src.startswith("AI") else None)})

    links, top_edges = [], []
    if edges is not None and len(edges):
        inter = edges[edges["cluster_a"].ne(edges["cluster_b"])].copy()
        inter["p"] = inter[["cluster_a", "cluster_b"]].min(axis=1).astype(str) + "-" + inter[["cluster_a", "cluster_b"]].max(axis=1).astype(str)
        links = [[int(k.split("-")[0]), int(k.split("-")[1]), int(v)] for k, v in inter.groupby("p")["documents"].sum().sort_values(ascending=False).items()]
        top_edges = [[r["a"], r["b"], int(r["documents"])] for _, r in edges.sort_values("documents", ascending=False).head(TOP_EDGES).iterrows()]

    # ── 구간별 (5~6년, τ > 0 — 유의성 검정 없음) ──
    windows = []
    ws, wt = _read(win / "windows_summary.csv"), _read(win / "windows_cluster_topterms.csv")
    if ws is not None:
        for _, w in ws.iterrows():
            cl = []
            if wt is not None:
                for _, t in wt[wt["window"].eq(w["window"])].sort_values("size", ascending=False).iterrows():
                    cl.append({"cluster": int(t["cluster"]), "size": int(t["size"]),
                               "top": [x.strip() for x in str(t["top_terms"]).split("|")][:12]})
            windows.append({"window": str(w["window"]).replace("_", "–"), "n_years": int(w["n_years"]),
                            "docs": int(w["documents_in_window"]), "candidates": int(w["candidate_terms"]),
                            "tau_pos": int(w["tau_positive_terms"]), "clusters": int(w["clusters"]),
                            "modularity": _r(w.get("modularity"), 3), "groups": cl})

    years = sorted({y for c in clusters for y, _ in c["series"]})
    docs = manifest.get("english_documents")
    if not docs and series is not None:
        docs = int(series.drop_duplicates("year")["total_documents"].sum())
    return {
        "key": key, "title": title, "inst": inst, "note": note,
        "source": str(src.relative_to(DATA)) if src.is_relative_to(DATA) else str(src),
        "years": [years[0], years[-1]] if years else None, "documents": docs,
        "candidates": int(len(tags)), "labels": {k: int(v) for k, v in lab.items()},
        "run": {k: run.get(k) for k in ("rising_terms", "edges", "isolated_terms", "clusters", "cluster_sizes",
                                         "modularity", "weight_scheme", "min_cooccurrence", "louvain_seed", "fdr_alpha")},
        "clusters": clusters, "links": links, "top_edges": top_edges,
        "rising": rising, "declining": declining, "windows": windows,
        "input_sha256": manifest.get("source_sha256", {}),
    }


def main() -> int:
    if not DATA.exists():
        print(f"[oa_rising] {DATA} 없음 — openalex-data 체크아웃이 필요합니다 (secrets.OPENALEX_DATA_TOKEN).")
        return 0
    try:
        sha = subprocess.run(["git", "-C", str(DATA), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    except Exception:
        sha = ""
    jobs = [(DATA / "archive" / "수자원_논문" / "results", "water_paper", "수자원 12개 핵심 저널 (논문판)", None,
             "이 저장소의 수자원 12개 핵심 저널(J01–J12)과 같은 목록 · openalex 논문판 분석")]
    for name, (key, inst) in FIELDS.items():
        jobs.append((DATA / "results" / name, key, f"{name} 분야", inst, f"openalex 분야 '{name}' 대상 저널"))
    OUT.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    index = []
    for src, key, title, inst, note in jobs:
        if not src.exists():
            continue
        d = build(src, key, title, inst, note)
        if not d:
            continue
        fp = OUT / f"{key}.json"
        old = _json(fp)
        if old and {k: v for k, v in old.items() if k not in ("updated", "data_commit")} == json.loads(json.dumps(d, ensure_ascii=False)):
            d = old                                   # 내용이 같으면 파일을 그대로 둔다 (매주 시각만 바뀐 커밋 방지)
            print(f"[oa_rising] {key}: 변경 없음")
        else:
            d["data_commit"], d["updated"] = sha, now
            fp.write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        index.append({"key": key, "title": title, "inst": inst, "years": d["years"], "documents": d["documents"],
                      "rising": len(d["rising"]), "clusters": len(d["clusters"]), "modularity": d["run"].get("modularity"),
                      "windows": len(d["windows"]), "file": f"oa_rising/{key}.json"})
        print(f"[oa_rising] {key}: Rising {len(d['rising'])} · 커뮤니티 {len(d['clusters'])} · 구간 {len(d['windows'])}")
    old_idx = _json(OUT / "index.json")
    if old_idx.get("sources") == index and old_idx.get("fields_missing") == [n for n, (k, _) in FIELDS.items() if not (OUT / f"{k}.json").exists()]:
        print("[oa_rising] index: 변경 없음")
        return 0
    (OUT / "index.json").write_text(json.dumps({
        "_doc": "openalex(newcave/openalex) 상승 연구주제 분석 결과 집계 — agents/oa_rising.py가 비공개 openalex-data에서 읽어 씀. 방법: Hamed–Rao MK + BH-FDR(q≤0.05) → association strength 동시출현(≥2) → Louvain(res 1.0, seed 0); 구간별은 5~6년 · τ>0(유의성 검정 없음).",
        "updated": now, "data_commit": sha, "method_repo": "newcave/openalex",
        "fields_missing": [n for n, (k, _) in FIELDS.items() if not (OUT / f"{k}.json").exists()],
        "sources": index}, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
