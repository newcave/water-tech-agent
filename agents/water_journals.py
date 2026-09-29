#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
water_journals — 수자원 12개 핵심 저널 공용 헬퍼 (openalex_lite · openalex_collect 공용)

  · data_seed/water_journals.json 레지스트리 로드
  · ISSN 그룹 → OpenAlex source ID 해석 (Print/Electronic ISSN을 한 저널로 취급)
  · works 필터 = primary_location.source.id (+ 연도) — 저널×연도 샤드 기대 건수 기준과 동일
"""
import json
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "data_seed" / "water_journals.json"
SOURCES_API = "https://api.openalex.org/sources"


def load_registry() -> dict:
    try:
        return json.loads(REGISTRY.read_text(encoding="utf-8"))
    except Exception:
        return {"journals": []}


def resolve_sources(issns: list, mailto: str) -> list:
    """ISSN 목록 → [{id, name, issn_l}] (중복 source 제거). 실패 시 빈 리스트."""
    if not issns:
        return []
    r = requests.get(SOURCES_API, params={"filter": "issn:" + "|".join(issns),
                                          "select": "id,display_name,issn_l",
                                          "mailto": mailto}, timeout=30)
    r.raise_for_status()
    out, seen = [], set()
    for s in r.json().get("results", []):
        sid = (s.get("id") or "").rsplit("/", 1)[-1]
        if sid and sid not in seen:
            seen.add(sid)
            out.append({"id": sid, "name": s.get("display_name"), "issn_l": s.get("issn_l")})
    return out


def source_filter(source_ids: list) -> str:
    return "primary_location.source.id:" + "|".join(source_ids)
