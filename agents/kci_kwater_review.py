#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kci_kwater_review — K-water 소속 논문 분류 검증용 표 만들기 (사람이 눈으로 확인)

KCI 전체에서 affiliation=검색어(한국수자원공사·K-water 등)로 다시 조회해,
저자 소속 문자열 재확인(kci_affiliation_pattern)에서
  · 채택된 논문(accepted)  → 오탐(K-water가 아닌데 들어옴) 확인용
  · 탈락한 논문(rejected)  → 누락(K-water인데 빠짐) 확인용
을 모두 표로 남긴다. 소속 문자열별 빈도표도 만든다.

출력 (비공개 저장소에만 — KCI 이용 준수: 원천 데이터 재배포 금지):
  {KCI_RAW_DIR}/review/kwater_papers.csv        논문 단위 (판정·연도·학술지·제목·K-water 저자 소속·URL)
  {KCI_RAW_DIR}/review/kwater_affiliations.csv  소속 문자열 단위 (빈도·판정·걸린 검색어)
  {KCI_RAW_DIR}/review/README.md                보는 법
로그에는 건수만 출력 (제목·이름 미출력).
"""
import csv
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

from kci_collect import KEY, KW_PATTERN, KW_QUERIES, fetch_year
from water_journals import load_registry

OUT = Path(os.environ.get("KCI_RAW_DIR", "private")) / "review"


def main():
    if not KEY:
        print("❌ KCI_API_KEY 없음")
        return 1
    reg = load_registry()
    y0, y1 = int(reg.get("archive_from_year", 2000)), time.gmtime().tm_year
    papers, aff_n, aff_q = {}, Counter(), defaultdict(set)
    for y in range(y0, y1 + 1):
        for q in KW_QUERIES:
            kept, _, _ = fetch_year(None, None, y, {"affiliation": q})
            for r in kept:
                k = r["id"] or (r["title_ko"], r["journal"], r["volume"], r["issue"])
                p = papers.setdefault(k, {**r, "queries": set()})
                p["queries"].add(q)
                for a in r.get("authors", []):
                    if a.get("affil"):
                        aff_n[a["affil"]] += 1
                        aff_q[a["affil"]].add(q)
        print(f"   {y}: 누적 {len(papers)}편")

    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "kwater_papers.csv", "w", newline="", encoding="utf-8-sig") as f:   # 엑셀 한글 깨짐 방지
        w = csv.writer(f)
        w.writerow(["판정", "연도", "학술지", "국문 제목", "영문 제목", "K-water로 본 소속", "전체 저자 소속",
                    "걸린 검색어", "URL"])
        rows = []
        for p in papers.values():
            affs = [a.get("affil", "") for a in p.get("authors", [])]
            hit = [a for a in affs if KW_PATTERN.search(a)]
            rows.append(["채택" if hit else "탈락", p.get("year"), p.get("journal"), p.get("title_ko"),
                         p.get("title_en"), " | ".join(dict.fromkeys(hit)), " | ".join(dict.fromkeys(affs)),
                         ", ".join(sorted(p["queries"])), p.get("url")])
        rows.sort(key=lambda r: (r[0] != "탈락", str(r[1]), str(r[2])))                  # 탈락 먼저
        w.writerows(rows)
    with open(OUT / "kwater_affiliations.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["판정", "소속 문자열", "저자 수", "걸린 검색어"])
        w.writerows(sorted((["K-water" if KW_PATTERN.search(a) else "아님", a, n, ", ".join(sorted(aff_q[a]))]
                            for a, n in aff_n.items()), key=lambda r: (r[0], -r[2])))
    acc = sum(r[0] == "채택" for r in rows)
    (OUT / "README.md").write_text(f"""# K-water 소속 논문 분류 검증표

KCI(한국학술지인용색인) 데이터 활용 — **비공개 보관, 재배포 금지**. 갱신: {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}

- 검색어: {', '.join(KW_QUERIES)} (KCI `affiliation=` 검색)
- 재확인 규칙(정규식, 대소문자 무시): `{KW_PATTERN.pattern}`
- 검색에 걸린 논문 {len(rows):,}편 → **채택 {acc:,}편 · 탈락 {len(rows) - acc:,}편**

## 보는 법
1. `kwater_affiliations.csv` — 소속 문자열별 빈도. '판정=K-water'인데 K-water가 아닌 것(오탐),
   '판정=아님'인데 K-water인 것(누락, 예: 표기 변형)을 찾으면 규칙을 고칩니다.
2. `kwater_papers.csv` — 논문 단위. **탈락이 먼저** 나옵니다. 탈락 논문의 '전체 저자 소속'에
   K-water 표기가 숨어 있으면 누락입니다. 채택 논문은 'K-water로 본 소속'이 맞는지 확인합니다.
""", encoding="utf-8")
    print(f"✅ 검증표: 검색 결과 {len(rows):,}편 → 채택 {acc:,} · 탈락 {len(rows) - acc:,} · 소속 문자열 {len(aff_n):,}종")
    return 0


if __name__ == "__main__":
    sys.exit(main())
