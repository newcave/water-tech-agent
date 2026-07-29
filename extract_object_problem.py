#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
extract_object_problem.py — 로컬 수동 실행용 object/problem 추출기 (v2: relevant 수정)
"""
import argparse, json, os, sys, time
from pathlib import Path

MODEL = "gpt-4o-mini"
MAXCHARS = 3500
RETRY = 4

SYSTEM = (
    "You extract fields from a research abstract in the water/AI domain. "
    "Answer in Korean. Do NOT classify into any taxonomy — only describe.\n"
    "- relevant: 정상적인 연구 초록이면 반드시 true 가 기본이다. 실제 연구 내용을 담고 "
    "있으면(문제·방법·결과 등) true. false 는 오직 초록이 연구가 아닐 때만 — 학회 안내, "
    "학술지 서문/사설, 논평, 정오표(erratum), 특집호 소개 등. 판단이 서지 않으면 true.\n"
    "- object: 이 연구가 최종적으로 상태를 개선·이해하려는 '대상'. 물리적 시설/자연계/"
    "제도 등 구체 명사구로. 예: '노후 상수관망', '댐 저수지 운영', '도시 우수 배제', "
    "'하천 홍수', '정수장 응집공정'. AI/모델/기법은 object 가 아니라 수단이다.\n"
    "- problem: 그 대상에서 풀려는 '문제'를 짧은 동사구로. 예: '누수 위치 조기 탐지', "
    "'홍수 위험지역 예측', '강수 상태 실시간 판별'.\n"
    "relevant=false 일 때만 object·problem 을 빈 문자열로 둔다. "
    "핵심 원칙: 초록에 등장하는 표면 키워드를 나열하지 말고, 연구가 무엇을 개선하려는지의 "
    "본질을 한 구절로 압축한다."
)

SCHEMA = {
    "name": "object_problem",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "relevant": {"type": "boolean"},
            "object": {"type": "string"},
            "problem": {"type": "string"},
        },
        "required": ["relevant", "object", "problem"],
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


def load_titles(inst, repo):
    t = {}
    p = repo / "live" / "openalex" / f"papers_{inst}.jsonl"
    if p.exists():
        for line in p.open(encoding="utf-8"):
            line = line.strip()
            if line:
                d = json.loads(line)
                t[d["id"].rsplit("/", 1)[-1]] = d.get("title", "")
    return t


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


def extract_one(client, model, title, abstract):
    user = f"[Title] {title}\n\n[Abstract] {abstract[:MAXCHARS]}"
    delay = 1.0
    for attempt in range(1, RETRY + 1):
        try:
            r = client.chat.completions.create(
                model=model,
                temperature=0,
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
    abs_path = repo / "labels" / "abstracts" / f"{inst}.jsonl"
    if not abs_path.exists():
        sys.stderr.write(f"[건너뜀] {abs_path} 없음\n")
        return
    titles = load_titles(inst, repo)
    out_dir = repo / "labels" / "extract"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{inst}.jsonl"
    done = load_done(out_path)

    rows = []
    for line in abs_path.open(encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        d = json.loads(line)
        if d.get("abstract_ok") and d["id"] not in done:
            rows.append(d)
    if limit:
        rows = rows[:limit]

    print(f"[{inst}] 초록보유 대상 {len(rows)} · 이미완료 {len(done)}")
    if not rows:
        return

    n_ok = n_irrel = 0
    with out_path.open("a", encoding="utf-8") as f:
        for i, d in enumerate(rows, 1):
            wid = d["id"]
            res = extract_one(client, model, titles.get(wid, ""), d["abstract"])
            if res is None:
                print(f"  {i}/{len(rows)} {wid} · 실패(다음 실행에 재시도)", flush=True)
                continue
            rec = {"id": wid, "object": res["object"], "problem": res["problem"],
                   "relevant": res["relevant"], "model": model}
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            if res["relevant"]:
                n_ok += 1
            else:
                n_irrel += 1
            if i % 25 == 0 or i == len(rows):
                print(f"  {i}/{len(rows)} · 유효 {n_ok} · 비연구 {n_irrel}", flush=True)
    print(f"[{inst}] 완료 → {out_path}  (유효 {n_ok} · 비연구 {n_irrel})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".")
    ap.add_argument("--inst", default=None)
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    repo = Path(args.repo).resolve()
    if not (repo / "labels" / "abstracts").exists():
        sys.exit(f"[중단] {repo}/labels/abstracts 없음. 초록 백필 먼저 하세요.")
    client = get_client()

    insts = [args.inst] if args.inst else [f"INST-{i:02d}" for i in range(1, 8)]
    for inst in insts:
        process_inst(inst, repo, client, args.model, args.limit)


if __name__ == "__main__":
    main()
