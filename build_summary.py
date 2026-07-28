# -*- coding: utf-8 -*-
"""build_summary.py — labels/domain/INST-*.jsonl 을 읽어 대시보드용 summary 생성"""
import json, glob, os
from collections import Counter

DOMAIN_VER = "v0.1"
INST_NAME = {"INST-01":"경영연구소","INST-02":"수자원환경연구소","INST-03":"상하수도연구소",
    "INST-04":"물인프라안전연구소","INST-05":"물에너지연구소","INST-06":"수자원위성연구소","INST-07":"AI연구소"}
DOM_NAME = {"W1":"유역·수문","W2":"댐·저수지 운영","W3":"수질·수생태","W4":"취·정수 공정",
    "W5":"관망·급수","W6":"하수·재이용","W7":"물인프라 안전·자산","W8":"물에너지",
    "W9":"관측 인프라","W0":"경영·정책·서비스","W0_UNCLASSIFIED":"미분류"}
DOM_ORDER = ["W1","W2","W3","W4","W5","W6","W7","W8","W9","W0","W0_UNCLASSIFIED"]

per_inst = {}
for f in sorted(glob.glob("labels/domain/INST-*.jsonl")):
    inst = os.path.basename(f).replace(".jsonl","")
    c = Counter()
    for line in open(f, encoding="utf-8"):
        line = line.strip()
        if line:
            c[json.loads(line)["domain_primary"]] += 1
    per_inst[inst] = c

insts = sorted(per_inst)
grand = sum(sum(c.values()) for c in per_inst.values())
dom_tot = {d: sum(per_inst[i].get(d,0) for i in insts) for d in DOM_ORDER}

summary = {
    "domain_ver": DOMAIN_VER,
    "status": "v0.1 confirmed",
    "source": "OpenAlex 2025-07~2026 (최근 1년), 7개 연구소 관련문헌",
    "method": "abstract→object/problem(mini)→domain assign(mini, primary)",
    "total": grand,
    "domains": {d: {"name": DOM_NAME[d], "count": dom_tot[d],
                    "pct": round(dom_tot[d]*100/grand,1) if grand else 0} for d in DOM_ORDER},
    "institutes": {i: {
        "name": INST_NAME.get(i,i),
        "total": sum(per_inst[i].values()),
        "unclassified": per_inst[i].get("W0_UNCLASSIFIED",0),
        "unclassified_pct": round(per_inst[i].get("W0_UNCLASSIFIED",0)*100/max(sum(per_inst[i].values()),1),1),
        "by_domain": {d: per_inst[i].get(d,0) for d in DOM_ORDER},
    } for i in insts},
    "unclassified_analysis": {
        "verdict": "미분류는 물 도메인 밖 문헌(수집 검색식 유입). 스트로맨이 놓친 물 축 아님. v0.1 확정.",
        "INST-03": "의학·생물·축산 (treatment/removal/exposure 용어 겹침)",
        "INST-06": "지구관측 일반 (숲·열섬·농업·토지피복·대기; 위성은 수단, 대상 비물)",
        "INST-01": "농업 관개 (작물 재배·water use; 대상은 농작물)",
        "next_action": "수집 검색식 조정: INST-03 의학용어 배제, INST-06 지구관측 분리, INST-01 농업 구분",
    },
}
out = "labels/domain/domain_summary_v0.1.json"
json.dump(summary, open(out,"w",encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"생성 완료 -> {out}")
print(f"  총 {grand:,}건")
for i in insts:
    t = summary["institutes"][i]
    print(f"  {i} {t['name']:<12} {t['total']:>5}건 · 미분류 {t['unclassified_pct']}%")
