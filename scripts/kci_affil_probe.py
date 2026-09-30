#!/usr/bin/env python3
"""1회성 점검: KCI 저자·소속 표기 형식과 affiliation= 검색 조건 확인 (개인 이름은 가려서 출력)."""
import os, re, time, xml.etree.ElementTree as ET
from collections import Counter
import requests

API = "https://open.kci.go.kr/po/openapi/openApiSearch.kci"
KEY = os.environ["KCI_API_KEY"].strip()
L = lambda t: t.rsplit("}", 1)[-1]


def call(**p):
    r = requests.get(API, params={"apiCode": "articleSearch", "key": KEY, **p}, timeout=60)
    time.sleep(1.2)
    return ET.fromstring(r.content)


def total(root):
    return next((x.text for x in root.iter() if L(x.tag) == "total"), None)


def mask(s):  # 괄호 밖 한글 이름·영문 이름 가림, 괄호 안(소속)만 남김
    return re.sub(r"[^()]+(?=\()", "○○○", s or "")


print("=== 1. author 태그 형식 (J11 2024, 이름 가림) ===")
root = call(journal="한국수자원학회논문집", dateFrom="202401", dateTo="202412", displayCount=10)
attrs, n = Counter(), 0
for a in (x for x in root.iter() if L(x.tag) == "author"):
    attrs.update(a.attrib.keys())
    if n < 8:
        print("  ", mask(a.text), "| 하위태그:", [L(c.tag) for c in a], "| 속성:", list(a.attrib))
        n += 1
print("  author 속성 키 빈도:", dict(attrs))
aff = Counter()
for a in (x for x in root.iter() if L(x.tag) == "author"):
    m = re.findall(r"\(([^()]*)\)", a.text or "")
    aff.update(m)
print("  괄호 안 소속 상위:", aff.most_common(10))

print("\n=== 2. affiliation= 검색 조건 ===")
for q in ["한국수자원공사", "K-water", "케이워터", "Korea Water Resources Corporation"]:
    t_all = total(call(affiliation=q, displayCount=1))
    t_j11 = total(call(affiliation=q, journal="한국수자원학회논문집", displayCount=1))
    t_y = total(call(affiliation=q, dateFrom="202401", dateTo="202412", displayCount=1))
    print(f"  [{q}] 전체 {t_all} · J11 {t_j11} · 2024년 {t_y}")
print("  (대조) 조건 없이 journal=J11 전체:", total(call(journal="한국수자원학회논문집", displayCount=1)))

print("\n=== 3. affiliation=한국수자원공사 2024 결과의 학술지 분포 ===")
root = call(affiliation="한국수자원공사", dateFrom="202401", dateTo="202412", displayCount=100)
print("  ", Counter(x.text for x in root.iter() if L(x.tag) == "journal-name").most_common(12))
