#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backfill_abstracts.py — 로컬 수동 실행용 초록 백필기

무엇을 하나:
  data 브랜치의 live/openalex/papers_INST-*.jsonl 에는 id/title/year 만 있고
  abstract 가 없다. 여기서는 id(W...)로 OpenAlex를 재조회해
  abstract_inverted_index 를 문장으로 복원하여 labels/abstracts/INST-*.jsonl 에 저장한다.
  papers 원본은 절대 건드리지 않는다(심박 소관).

왜 이 위치인가:
  labels/ 는 6시간 심박이 안 건드리는 우리 전용 영역. 심박이 papers_*.jsonl 을
  덮어써도 라벨/초록은 안전하다.

특징:
  - 재개 가능: 이미 저장된 id 는 건너뛴다. 중간에 죽어도 다시 돌리면 이어감.
  - 폴라이트 풀: mailto 붙여 OpenAlex 정중 요청(빠르고 안정적).
  - 50개씩 OR 필터로 묶어 조회 → 13,746건 ≈ 275콜, 무료.
  - abstract 없는 문헌(dataset/software 등 다수)은 abstract_ok=false 로 기록.

사용:
  # 로컬 water-tech-agent 저장소에서 data 브랜치 체크아웃 상태로:
  #   git checkout data && git pull
  export OPENALEX_MAILTO="your@email.com"     # 폴라이트 풀 (선택이지만 권장)
  python3 backfill_abstracts.py --repo .        # 저장소 루트 경로
  python3 backfill_abstracts.py --repo . --inst INST-07   # 한 기관만
"""
import argparse, json, os, sys, time, urllib.parse, urllib.request
from pathlib import Path

OA = "https://api.openalex.org/works"
BATCH = 50          # OR 필터 한 번에 묶는 id 수 (OpenAlex 권장 상한 이내)
SLEEP = 0.2         # 콜 간 간격(초). 폴라이트 풀 넉넉. 429 나면 자동 증가.
RETRY = 4


def rebuild_abstract(inv):
    """abstract_inverted_index(단어->위치들) → 원문 문자열."""
    if not inv:
        return ""
    pos = {}
    for word, places in inv.items():
        for p in places:
            pos[p] = word
    if not pos:
        return ""
    return " ".join(pos[i] for i in range(max(pos) + 1) if i in pos)


def chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def fetch_batch(ids, mailto):
    """id 리스트 → {id: abstract_str}. abstract 없으면 빈 문자열."""
    oa_ids = "|".join(ids)  # 'W123|W456|...'
    params = {
        "filter": f"openalex_id:{oa_ids}",
        "select": "id,abstract_inverted_index",
        "per-page": str(len(ids)),
    }
    if mailto:
        params["mailto"] = mailto
    url = OA + "?" + urllib.parse.urlencode(params)

    delay = SLEEP
    for attempt in range(1, RETRY + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": f"kwater-backfill ({mailto or 'no-mail'})"})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.load(r)
            out = {}
            for w in data.get("results", []):
                wid = w["id"].rsplit("/", 1)[-1]  # 'https://openalex.org/W123' → 'W123'
                out[wid] = rebuild_abstract(w.get("abstract_inverted_index"))
            return out
        except urllib.error.HTTPError as e:
            if e.code == 429:  # rate limit
                delay = min(delay * 2, 5)
                sys.stderr.write(f"  429 → {delay}s 대기 후 재시도({attempt}/{RETRY})\n")
                time.sleep(delay)
            else:
                sys.stderr.write(f"  HTTP {e.code} (배치 {ids[0]}...): {e}\n")
                if attempt == RETRY:
                    return {}
                time.sleep(delay)
        except Exception as e:
            sys.stderr.write(f"  오류({attempt}/{RETRY}) {type(e).__name__}: {e}\n")
            if attempt == RETRY:
                return {}
            time.sleep(delay)
    return {}


def load_done(out_path):
    """이미 저장된 id 집합 (재개용)."""
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


def process_inst(inst, repo, mailto):
    src = repo / "live" / "openalex" / f"papers_{inst}.jsonl"
    if not src.exists():
        sys.stderr.write(f"[건너뜀] {src} 없음\n")
        return
    out_dir = repo / "labels" / "abstracts"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{inst}.jsonl"

    # id 수집 (짧은 W... 형태로 통일)
    ids = []
    for line in src.open(encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        wid = json.loads(line)["id"]
        ids.append(wid.rsplit("/", 1)[-1])

    done = load_done(out_path)
    todo = [i for i in ids if i not in done]
    print(f"[{inst}] 전체 {len(ids)} · 완료 {len(done)} · 처리대상 {len(todo)}")
    if not todo:
        return

    got_abs = 0
    with out_path.open("a", encoding="utf-8") as f:
        for bi, batch in enumerate(chunks(todo, BATCH), 1):
            res = fetch_batch(batch, mailto)
            for wid in batch:  # 응답 누락 id 도 기록해 재개 시 무한루프 방지
                abs_text = res.get(wid, "")
                ok = bool(abs_text)
                got_abs += ok
                f.write(json.dumps({"id": wid, "abstract": abs_text, "abstract_ok": ok},
                                   ensure_ascii=False) + "\n")
            f.flush()
            print(f"  배치 {bi}: +{len(batch)}건 (초록보유 누적 {got_abs})", flush=True)
            time.sleep(SLEEP)
    print(f"[{inst}] 완료 → {out_path}  (초록보유 {got_abs}/{len(todo)})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".", help="water-tech-agent 저장소 루트 (data 브랜치 체크아웃 상태)")
    ap.add_argument("--inst", default=None, help="INST-07 처럼 한 기관만. 생략 시 01~07 전부")
    ap.add_argument("--mailto", default=os.environ.get("OPENALEX_MAILTO", ""))
    args = ap.parse_args()

    repo = Path(args.repo).resolve()
    if not (repo / "live" / "openalex").exists():
        sys.exit(f"[중단] {repo}/live/openalex 없음. data 브랜치인지 확인하세요 (git checkout data).")
    if not args.mailto:
        sys.stderr.write("[경고] mailto 미설정 — 느릴 수 있음. export OPENALEX_MAILTO=you@email.com 권장\n")

    insts = [args.inst] if args.inst else [f"INST-{i:02d}" for i in range(1, 8)]
    for inst in insts:
        process_inst(inst, repo, args.mailto)


if __name__ == "__main__":
    main()
