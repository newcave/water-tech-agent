#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kci_counts — 한국 저널(J11·J12) 연도별 논문 수를 KCI Open API로 실측 (트렌드 분석 분모 보완)

배경: OpenAlex는 한국수자원학회논문집·대한토목학회논문집을 2021년까지만, 그것도 과소 연결
      (예: J11 2021년 OpenAlex 63건 vs KCI 117건) → 이 두 저널의 분모는 KCI를 기준으로 한다.

동작 (2026-09-29 점검으로 확인한 API 특성 반영):
  · articleSearch의 journal= 조건과 dateFrom/dateTo(YYYYMM)만 유효 (pubiYr·issn 조건은 무시됨)
  · journal= 는 부분일치 → 레코드의 journal-name을 레지스트리 kci.names와 대조해 걸러서 셈
  · 연도마다 dateFrom=YYYY01, dateTo=YYYY12로 받아 100건씩 페이지 순회
    (연도 필터 없이 전체를 순회하면 페이지 간 정렬이 흔들려 연도별 집계가 어긋남)

KCI 이용 준수: 원천 데이터(제목·초록 등)는 저장하지 않고 연도별 건수만 기록한다.
출처: KCI(한국학술지인용색인) 데이터 활용
"""
import json
import os
import sys
import time
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

import requests

from water_journals import load_registry

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data_seed" / "kci_counts.json"
API = "https://open.kci.go.kr/po/openapi/openApiSearch.kci"
KEY = os.environ.get("KCI_API_KEY", "").strip()
PAGE = 100
PAUSE = 1.0                                           # 요청 간격 (초) — 천천히
MAX_PAGES = 30                                        # 연도당 안전장치 (3,000건)


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def text_of(el, name: str):
    for x in el.iter():
        if local(x.tag) == name and (x.text or "").strip():
            return x.text.strip()
    return None


def norm(name) -> str:
    return "".join((name or "").split())             # 공백 차이 무시 ("한국수자원학회 논문집")


def call(params: dict):
    r = requests.get(API, params={"apiCode": "articleSearch", "key": KEY, **params}, timeout=60)
    time.sleep(PAUSE)
    r.raise_for_status()
    return ET.fromstring(r.content)


def year_counts(journal: str, names: set, year: int):
    """→ (포함 건수, 학술지명 분포, API total)."""
    got, dist, total = 0, Counter(), None
    for page in range(1, MAX_PAGES + 1):
        root = call({"journal": journal, "dateFrom": f"{year}01", "dateTo": f"{year}12",
                     "displayCount": PAGE, "page": page})
        total = total if total is not None else int(text_of(root, "total") or 0)
        recs = [el for el in root.iter() if local(el.tag) == "record"]
        for rec in recs:
            dist[text_of(rec, "journal-name")] += 1
        got += len(recs)
        if not recs or got >= total:
            break
    n = sum(c for nm, c in dist.items() if norm(nm) in names)
    return n, dict(dist), total


def main():
    if not KEY:
        print("❌ KCI_API_KEY 환경변수 없음 — 저장소 Settings → Secrets → Actions에 등록 필요")
        return 1
    reg = load_registry()
    y0, y1 = int(reg.get("archive_from_year", 2000)), time.gmtime().tm_year
    prev = {}
    try:
        prev = json.loads(OUT.read_text(encoding="utf-8"))
    except Exception:
        pass
    out = {"source": "KCI(한국학술지인용색인) 데이터 활용",
           "note": "연도별 건수 집계만 저장 (원천 데이터 미저장)",
           "updated": int(time.time()), "journals": prev.get("journals", {})}
    errors = []
    for j in reg.get("journals", []):
        kci = j.get("kci")
        if not kci:
            continue
        names = {norm(n) for n in kci.get("names", [])}
        by_year, excluded = {}, Counter()
        try:
            for y in range(y0, y1 + 1):
                n, dist, total = year_counts(kci["journal"], names, y)
                if total:
                    by_year[str(y)] = n
                    for nm, c in dist.items():
                        if norm(nm) not in names:
                            excluded[nm] += c
                    print(f"   {j['code']} {y}: {n}건 (API total {total}, 분포 {dist})")
        except Exception as e:
            errors.append(f"{j['code']}: {e}")
            print(f"⚠️ {j['code']} 중단: {e} — 이전 값 유지")
            continue
        out["journals"][j["code"]] = {
            "name": j["name"], "kci_journal": kci["journal"], "names": kci.get("names", []),
            "total": sum(by_year.values()), "by_year": by_year,
            "last_year": max((int(y) for y, n in by_year.items() if n), default=None),
            "excluded_names": dict(excluded)}
        print(f"✅ {j['code']} {j['name']}: {sum(by_year.values()):,}건 ({len(by_year)}개 연도)")
    if errors:
        out["errors"] = errors
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("출처: KCI(한국학술지인용색인) 데이터 활용")
    return 0


if __name__ == "__main__":
    sys.exit(main())
