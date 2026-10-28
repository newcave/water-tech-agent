#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kci_inst — 최근 5년 KCI 논문을 7개 연구소 분야로 나눠, K-water 논문과 국내 학회지 전체를 견줌 (v3.17)

입력: {KCI_RAW_DIR}/raw/{J11,J12,KWATER}/{연도}.jsonl  (비공개 저장소 원천 — 여기서 읽기만)
출력: data_seed/kci_inst.json                         (공개 — 연구소 분야별 건수 집계만, 제목·초록·이름 없음)

분야 나누기: data_seed/label_review_profiles.json의 연구소별 한국어 키워드(keywords.<INST>.ko)를
  국문 제목·초록에서 찾음. 제목에서 찾으면 2점, 초록에서 찾으면 1점(키워드마다 한 번) → 2점 이상이면 그 연구소 분야.
  한 논문이 여러 분야에 들 수 있음(중복 집계 — 국가전략기술 특허 분석과 같은 방식). 어디에도 안 들면 '미분류'.
비교 대상 (끝난 해 최근 5년):
  · domestic           국내 학회지 — 한국수자원학회논문집(J11) + 대한토목학회논문집(J12) 전체
  · kwater             K-water 소속 논문 — KCI 전체 학회지 (kwater_rules 판정 + 사람 판정)
  · kwater_in_domestic 국내 학회지 안의 K-water 논문 (같은 학회지끼리 점유율 비교용)
출처: KCI(한국학술지인용색인) 데이터 활용
"""
import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path

from kwater_rules import is_kwater, load_overrides

ROOT = Path(__file__).resolve().parents[1]
RAW = Path(os.environ.get("KCI_RAW_DIR", "private")) / "raw"
OUT = ROOT / "data_seed" / "kci_inst.json"
PROFILES = ROOT / "data_seed" / "label_review_profiles.json"
RECENT = 5                       # 끝난 해 최근 5년 (2026-10-27 사용자 지정 창)
TITLE_W, ABS_W, MIN_SCORE = 2, 1, 2
HANGUL = re.compile("[가-힣]")


def load_keywords() -> dict:
    p = json.loads(PROFILES.read_text(encoding="utf-8"))
    return {inst: [k.lower() for k in (v.get("ko") or [])] for inst, v in (p.get("keywords") or {}).items()}


def classify(title: str, abstract: str, kws: dict) -> list:
    """→ 이 논문이 드는 연구소 목록 (점수 MIN_SCORE 이상)."""
    t, a = (title or "").lower(), (abstract or "").lower()
    out = []
    for inst, words in kws.items():
        s = sum(TITLE_W if w in t else ABS_W if w in a else 0 for w in words)
        if s >= MIN_SCORE:
            out.append(inst)
    return out


def read(code: str, years: list):
    for y in years:
        p = RAW / code / f"{y}.jsonl"
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    yield y, json.loads(line)


def empty(label: str, years: list) -> dict:
    return {"label": label, "N": 0, "by_year_N": {str(y): 0 for y in years}, "unclassified": 0,
            "inst": {}, "journals": Counter()}


def add(sc: dict, y: int, insts: list, journal: str = None):
    sc["N"] += 1
    sc["by_year_N"][str(y)] += 1
    if journal:
        sc["journals"][journal] += 1
    if not insts:
        sc["unclassified"] += 1
    for i in insts:
        e = sc["inst"].setdefault(i, {"n": 0, "by_year": {k: 0 for k in sc["by_year_N"]}})
        e["n"] += 1
        e["by_year"][str(y)] += 1


def main():
    if not RAW.exists():
        print(f"❌ 원천 폴더 없음: {RAW}")
        return 1
    ov = load_overrides(RAW.parent)
    kws = load_keywords()
    y1 = time.gmtime().tm_year - 1
    years = list(range(y1 - RECENT + 1, y1 + 1))
    sc = {"domestic": empty("국내 학회지 (한국수자원학회논문집 + 대한토목학회논문집)", years),
          "kwater": empty("K-water 소속 논문 (KCI 전체 학회지)", years),
          "kwater_in_domestic": empty("국내 학회지 안의 K-water 논문", years)}
    skipped = Counter()
    for code in ("J11", "J12"):
        for y, r in read(code, years):
            ti, ab = r.get("title_ko"), r.get("abstract_ko")
            if not HANGUL.search((ti or "") + (ab or "")):
                skipped["english_only"] += 1
                continue
            insts = classify(ti, ab, kws)
            add(sc["domestic"], y, insts)
            if is_kwater(r, ov):
                add(sc["kwater_in_domestic"], y, insts)
    for y, r in read("KWATER", years):
        if not is_kwater(r, ov):
            continue
        ti, ab = r.get("title_ko"), r.get("abstract_ko")
        if not HANGUL.search((ti or "") + (ab or "")):
            skipped["kwater_english_only"] += 1
            continue
        add(sc["kwater"], y, classify(ti, ab, kws), r.get("journal"))
    for s in sc.values():
        s["journals"] = s["journals"].most_common(12)
        s["inst"] = dict(sorted(s["inst"].items()))
    out = {"source": "KCI(한국학술지인용색인) 데이터 활용 — 연구소 분야별 건수 집계만 공개, 원천 데이터·개인 이름 미포함",
           "updated": int(time.time()), "years": [str(y) for y in years],
           "method": (f"국문 제목·초록에서 연구소별 한국어 키워드(label_review_profiles.json keywords.<INST>.ko) 찾기 — "
                      f"제목 {TITLE_W}점·초록 {ABS_W}점, {MIN_SCORE}점 이상이면 그 분야 (여러 분야 중복 가능). "
                      "영문 전용 논문 제외"),
           "skipped": dict(skipped), "scopes": sc}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    d, k = sc["domestic"], sc["kwater"]
    print(f"✅ {years[0]}~{years[-1]} · 국내 학회지 {d['N']:,}편(미분류 {d['unclassified']:,}) · "
          f"K-water {k['N']:,}편(미분류 {k['unclassified']:,}) · 학회지 안 K-water {sc['kwater_in_domestic']['N']:,}편")
    for inst in sorted(kws):
        dn, kn_ = d["inst"].get(inst, {}).get("n", 0), k["inst"].get(inst, {}).get("n", 0)
        ds, ks = dn / d["N"] if d["N"] else 0, kn_ / k["N"] if k["N"] else 0
        print(f"   {inst}: 국내 {dn:,}편 {ds:.1%} · K-water {kn_:,}편 {ks:.1%} · 특화도 {ks / ds if ds else 0:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
