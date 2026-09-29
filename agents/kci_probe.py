#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kci_probe — KCI Open API 연결·응답구조 점검 (J11·J12 2022~ 보완 준비, 1단계)

하는 일 (원천 데이터는 저장·커밋하지 않음 — KCI 이용 준수: 재배포 금지):
  1. 인증키(환경변수 KCI_API_KEY)로 articleSearch 호출, 응답 XML 태그 구조만 출력
  2. J11·J12 × 2022~올해 연도별 total(건수)을 검색 조건별로 비교 출력
     (학술지명 journal= / ISSN issn= 중 어느 조건이 실제로 먹히는지 확인)
  3. 첫 레코드 몇 건의 학술지명·ISSN·발행연도만 출력 (제목·초록 등 본문 정보 미출력)

출처: KCI(한국학술지인용색인) 데이터 활용
"""
import os
import sys
import time
import xml.etree.ElementTree as ET
from collections import Counter

import requests

API = "https://open.kci.go.kr/po/openapi/openApiSearch.kci"
KEY = os.environ.get("KCI_API_KEY", "").strip()
PAUSE = 1.5                                            # 요청 간격 (초) — 천천히

JOURNALS = [
    {"code": "J11", "name": "한국수자원학회논문집", "issns": ["2799-8746", "1226-6280", "2287-6138"]},
    {"code": "J12", "name": "대한토목학회논문집", "issns": ["2799-9629", "1015-6348"]},
]


def call(params: dict):
    """→ (status, root 또는 None, 원문 앞부분). 키는 로그에 남기지 않음."""
    p = {"apiCode": "articleSearch", "key": KEY, **params}
    try:
        r = requests.get(API, params=p, timeout=40)
    except Exception as e:
        return None, None, f"요청 오류: {e}"
    time.sleep(PAUSE)
    try:
        return r.status_code, ET.fromstring(r.content), r.text[:300]
    except ET.ParseError:
        return r.status_code, None, r.text[:300].replace(KEY, "***")


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def find_text(root, *names):
    """태그명(소문자 비교) 중 첫 번째로 값이 있는 것."""
    want = {n.lower() for n in names}
    for el in root.iter():
        if local(el.tag).lower() in want and (el.text or "").strip():
            return el.text.strip()
    return None


def records(root):
    return [el for el in root.iter() if local(el.tag).lower() == "record"]


def main():
    if not KEY:
        print("❌ KCI_API_KEY 환경변수 없음 — 저장소 Settings → Secrets → Actions에 등록 필요")
        return 1
    year_now = time.gmtime().tm_year

    # ── 1. 응답 구조 ──
    print("=== 1. 응답 구조 (J11, 2024, journal= 조건) ===")
    st, root, head = call({"journal": JOURNALS[0]["name"], "pubiYr": 2024, "displayCount": 5})
    print(f"HTTP {st}")
    if root is None:
        print("XML 파싱 실패 — 응답 앞부분:", head)
        return 0
    tags = Counter(local(el.tag) for el in root.iter())
    print("태그 목록(빈도):", dict(tags))
    print("total 후보:", find_text(root, "total", "totalCount", "total-count"))
    err = find_text(root, "error", "errMsg", "message", "result-msg")
    if err:
        print("메시지:", err)
    for rec in records(root)[:5]:
        print("  · 학술지:", find_text(rec, "journal-name", "journalName", "journal"),
              "| ISSN:", find_text(rec, "issn"),
              "| 연도:", find_text(rec, "pub-year", "pubYear", "pubi-year"),
              "| DOI 있음:", bool(find_text(rec, "doi")),
              "| 초록 있음:", bool(find_text(rec, "abstract")))

    # ── 2. 연도별 건수: 검색 조건 비교 ──
    print("\n=== 2. 연도별 total (조건별 비교) ===")
    for j in JOURNALS:
        conds = [("journal", {"journal": j["name"]})] + \
                [(f"issn {i}", {"issn": i}) for i in j["issns"]]
        for label, cond in conds:
            row = []
            for y in range(2021, year_now + 1):              # 2021 = OpenAlex와 겹치는 대조 연도
                st, root, head = call({**cond, "pubiYr": y, "displayCount": 1})
                row.append(f"{y}:{find_text(root, 'total', 'totalCount') if root is not None else f'HTTP{st}'}")
            print(f"  {j['code']} {j['name']} [{label}] → " + ", ".join(row))

    print("\n출처: KCI(한국학술지인용색인) 데이터 활용")
    return 0


if __name__ == "__main__":
    sys.exit(main())
