#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""assign_domain.py — object/problem 을 K-water 도메인축(스트로맨 v0.1)에 배정"""
import argparse, json, os, sys, time
from pathlib import Path

MODEL = "gpt-4o-mini"
RETRY = 4
DOMAIN_VER = "v0.1"

DOMAINS = {
    "W1": "유역·수문: 강우-유출, 하천, 홍수·가뭄, 수문 관측·모델링",
    "W2": "댐·저수지 운영: 저수지 운영규칙, 용수공급 의사결정, 방류",
    "W3": "수질·수생태: 조류(녹조), 오염원, 수생태, 미량오염물질",
    "W4": "취·정수 공정: 정수장 단위공정, 응집·여과·소독, 공정제어",
    "W5": "관망·급수 서비스: 상수관망 누수·수압, 수요예측, 계량, 급수",
    "W6": "하수·재이용: 하수처리, 재이용수, 하수관로",
    "W7": "물인프라 안전·자산: 댐·관로·구조물 진단, 노후화, 안전관리",
    "W8": "물에너지: 수력, 수상태양광, 수열, 물-에너지 넥서스",
    "W9": "관측 인프라: 위성 탑재체·검보정, 계측망·센서 자체의 개발",
    "W0": "경영·정책·서비스: 물 정책, 요금·경제, 경영, 거버넌스, 해외사업",
    "W0_UNCLASSIFIED": "위 어디에도 명확히 속하지 않음 (스트로맨이 놓친 대상)",
}
CODES = list(DOMAINS.keys())

SYSTEM = (
    "너는 물 분야 연구 문헌을 K-water 도메인축에 배정하는 분류기다. "
    "입력은 한 문헌의 object(개선 대상)와 problem(푸는 문제)이다.\n"
    "다음 축 중에서 고른다:\n"
    + "\n".join(f"  {k}: {v}" for k, v in DOMAINS.items()) + "\n\n"
    "규칙:\n"
    "1) 판정 기준은 '조직'이 아니라 '개선 대상(object)'이다. AI·위성·센서·모델은 "
    "수단이므로 그것만 보고 W9 로 보내지 마라. 위성으로 녹조를 탐지하면 대상은 수질(W3)이다. "
    "단, 위성 탑재체/검보정/센서 자체를 개발하는 연구여야 W9 다.\n"
    "2) primary 는 반드시 1개. 가장 핵심적인 개선 대상 하나.\n"
    "3) secondary 는 본질적으로 겹치는 도메인이 있을 때만 0~2개. 없으면 빈 배열.\n"
    "4) 어느 축에도 명확히 안 맞으면 primary 를 W0_UNCLASSIFIED 로. 억지로 끼워맞추지 마라. "
    "일반 기상·기후·농업·해양·에너지 일반 등 물과 거리가 있으면 여기로.\n"
    "5) confidence: 배정 확신도 0.0~1.0."
)

SCHEMA = {
    "name": "domain_assign",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "primary": {"type": "string", "enum": CODES},
            "secondary": {"type": "array", "items": {"type": "string", "enum": CODES}},
            "confidence": {"type": "number"},
        },
        "required": ["primary", "secondary", "confidence"],
    },
}


def get_client():
    try:
        from openai import OpenAI
    except ImportError:
        sys.exit("[중단] openai 패키지 없음 → pip install openai")
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        env = Path(".env")
        if env.exists():
            for line in env.read_text(encoding="utf-8").splitlines():
                if line.startswith("OPENAI_API_KEY"):
                    key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    if not key:
        sys.exit("[중단] OPENAI_API_KEY 없음 (환경변수 또는 .env)")
    return OpenAI(api_key=key)


def load_done(out_path):
    done = set()
    if out_path.exists():
        for line in out_path.open(encoding="utf-8"):
            line = line.strip()
            if line:
                try:
                    done.add(json.loads(line)["id"])
                except Exception:
                    pass
    return done


def assign_one(client, model, obj, prob):
    user = f"object: {obj}\nproblem: {prob}"
    delay = 1.0
    for attempt in range(1, RETRY + 1):
        try:
            r = client.chat.completions.create(
                model=model, temperature=0,
                messages=[{"role": "system", "content": SYSTEM},
                          {"role": "user", "content": user}],
                response_format={"type": "json_schema", "json_schema": SCHEMA},
            )
            return json.loads(r.choices[0].message.content)
        except Exception as e:
            msg = str(e)
            if attempt == RETRY:
                sys.stderr.write(f"  실패(최종): {type(e).__name__}: {msg[:120]}\n")
                return None
            delay = min(delay * 2, 20) if "rate" in msg.lower() or "429" in msg else delay
            time.sleep(delay)
    return None


def process_inst(inst, repo, client, model, limit):
    ext_path = repo / "labels" / "extract" / f"{inst}.jsonl"
    if not ext_path.exists():
        sys.stderr.write(f"[건너뜀] {ext_path} 없음\n")
        return
    out_dir = repo / "labels" / "domain"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{inst}.jsonl"
    done = load_done(out_path)

    rows = []
    for line in ext_path.open(encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        d = json.loads(line)
        if d.get("relevant") and d["id"] not in done:
            rows.append(d)
    if limit:
        rows = rows[:limit]

    print(f"[{inst}] 배정 대상 {len(rows)} · 이미완료 {len(done)}")
    if not rows:
        return

    from collections import Counter
    tally = Counter()
    with out_path.open("a", encoding="utf-8") as f:
        for i, d in enumerate(rows, 1):
            res = assign_one(client, model, d.get("object", ""), d.get("problem", ""))
            if res is None:
                print(f"  {i}/{len(rows)} {d['id']} · 실패(재시도 대상)", flush=True)
                continue
            rec = {"id": d["id"], "domain_primary": res["primary"],
                   "domain_secondary": res["secondary"],
                   "confidence": res["confidence"], "domain_ver": DOMAIN_VER,
                   "object": d.get("object", ""), "problem": d.get("problem", "")}
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            tally[res["primary"]] += 1
            if i % 50 == 0 or i == len(rows):
                unc = tally.get("W0_UNCLASSIFIED", 0)
                print(f"  {i}/{len(rows)} · 미분류 {unc} ({unc*100//max(i,1)}%)", flush=True)
    print(f"[{inst}] 완료 → {out_path}")
    top = ", ".join(f"{k}:{v}" for k, v in tally.most_common())
    print(f"  분포: {top}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".")
    ap.add_argument("--inst", default=None)
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    repo = Path(args.repo).resolve()
    if not (repo / "labels" / "extract").exists():
        sys.exit(f"[중단] {repo}/labels/extract 없음. object/problem 추출 먼저.")
    client = get_client()

    insts = [args.inst] if args.inst else [f"INST-{i:02d}" for i in range(1, 8)]
    for inst in insts:
        process_inst(inst, repo, client, args.model, args.limit)


if __name__ == "__main__":
    main()
