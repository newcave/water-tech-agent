#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kwater_rules — K-water 소속 판정 한 곳 (수집·검증표·분석 공용)

판정 = 저자 소속 문자열 규칙(search_topics.json kwater_affiliation.kci_affiliation_pattern)
     + 사람 판정(비공개 저장소 review/overrides*.json — tools/kwater_hitl.html 게임 결과)

overrides 우선순위: 논문 단위(paper_include/exclude) > 소속 단위(affiliation_include/exclude) > 규칙
여러 사람의 결과 파일(review/overrides*.json)은 모두 합친다. 같은 항목을 서로 다르게 판정했으면
'제외' 쪽을 따르지 않고 규칙대로 두며 conflicts에 남긴다 (사람이 다시 보도록).
"""
import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_KW = json.loads((ROOT / "data_seed" / "search_topics.json").read_text(encoding="utf-8")).get("kwater_affiliation", {})
QUERIES = _KW.get("kci_affiliation", ["한국수자원공사", "K-water"])
PATTERN = re.compile(_KW.get("kci_affiliation_pattern", "한국수자원공사|k-?water"), re.I)


def paper_key(r: dict) -> str:
    """게임과 같은 논문 키: URL, 없으면 '연도|제목'."""
    return r.get("url") or f"{r.get('year')}|{r.get('title_ko') or r.get('title_en')}"


def load_overrides(raw_dir=None) -> dict:
    d = Path(raw_dir or os.environ.get("KCI_RAW_DIR", "private")) / "review"
    sets = {k: {} for k in ("affiliation_include", "affiliation_exclude", "paper_include", "paper_exclude")}
    files = sorted(d.glob("overrides*.json")) if d.exists() else []
    for p in files:
        try:
            o = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"⚠️ {p.name} 읽기 실패: {e}")
            continue
        for k in sets:
            for v in o.get(k, []):
                sets[k].setdefault(v, set()).add(o.get("reviewer", p.name))
    conflicts = {"affiliation": sorted(set(sets["affiliation_include"]) & set(sets["affiliation_exclude"])),
                 "paper": sorted(set(sets["paper_include"]) & set(sets["paper_exclude"]))}
    for kind in ("affiliation", "paper"):               # 엇갈린 항목은 규칙에 맡김
        for v in conflicts[kind]:
            sets[f"{kind}_include"].pop(v, None)
            sets[f"{kind}_exclude"].pop(v, None)
    ov = {k: set(v) for k, v in sets.items()}
    ov["files"] = [p.name for p in files]
    ov["conflicts"] = conflicts
    return ov


EMPTY = {"affiliation_include": set(), "affiliation_exclude": set(), "paper_include": set(),
         "paper_exclude": set(), "files": [], "conflicts": {"affiliation": [], "paper": []}}


def affil_is_kwater(affil: str, ov: dict = EMPTY) -> bool:
    if not affil:
        return False
    if affil in ov["affiliation_exclude"]:
        return False
    return affil in ov["affiliation_include"] or bool(PATTERN.search(affil))


def is_kwater(r: dict, ov: dict = EMPTY) -> bool:
    k = paper_key(r)
    if k in ov["paper_exclude"]:
        return False
    if k in ov["paper_include"]:
        return True
    return any(affil_is_kwater(a.get("affil", ""), ov) for a in r.get("authors", []))
