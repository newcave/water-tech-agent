#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""classify_kwater_pubs.py — K-water연구원 논문·학술발표(1996~2026) 도메인축 배정"""
import argparse, hashlib, json, os, re, sys, time
from pathlib import Path

MODEL = "gpt-4o-mini"
RETRY = 4
DOMAIN_VER = "v0.1"

DOMAINS = {
    "W1": "유역·수문: 강우-유출, 하천, 홍수·가뭄, 수문 관측·모델링, 지하수",
    "W2": "댐·저수지 운영: 저수지 운영, 용수공급 의사결정, 방류, 수문(水門)",
    "W3": "수질·수생태: 조류(녹조), 오염원, 수생태, 미량오염물질, 담수생물",
    "W4": "취·정수 공정: 정수장 단위공정, 응집·여과·소독, 막여과, 공정제어",
    "W5": "관망·급수 서비스: 상수관망 누수·수압, 수요예측, 계량, 급수, 수도운영",
    "W6": "하수·재이용: 하수처리, 슬러지, 재이용수, 하수관로",
    "W7": "물인프라 안전·자산: 댐·제방·관로·구조물 진단, 지반, 내진, 노후화",
    "W8": "물에너지: 수력·수차, 수상태양광, 수열, 물-에너지 넥서스",
    "W9": "관측 인프라: 위성 탑재체·검보정, 계측기·센서 자체의 개발",
    "W0": "경영·정책·서비스: 물 정책, 요금·경제, 경영, 거버넌스, 해외사업",
    "W0_UNCLASSIFIED": "위 어디에도 명확히 속하지 않음 (물과 무관한 일반 주제)",
}
CODES = list(DOMAINS.keys())

SYSTEM = (
    "너는 K-water(한국수자원공사) 연구원의 논문·학술발표 제목을 물 도메인축에 배정하는 "
    "분류기다. 입력은 제목(주로 한글)과 학회명(또는 게재지)이다.\n"
    "다음 축 중에서 고른다:\n"
    + "\n".join(f"  {k}: {v}" for k, v in DOMAINS.items()) + "\n\n"
    "규칙:\n"
    "1) 판정 기준은 연구의 '개선 대상'이다. AI·센서·위성·모델·공법은 수단이다. "
    "예: '딥러닝 기반 조류 예측' → 대상은 수질(W3).\n"
    "2) 학회명·게재지는 보조 신호다. 제목이 모호할 때 참고하되, 제목이 명확하면 제목을 따른다.\n"
    "3) primary 는 반드시 1개. secondary 는 본질적으로 겹칠 때만 0~2개.\n"
    "4) 물과 무관한 일반 주제(순수 재료·화학, 일반 전기·통신, 일반 경영 등이 물 맥락 없이)만 "
    "W0_UNCLASSIFIED. K-water 성과 특성상 대부분은 물 도메인에 속하지만, 억지로 끼워맞추지는 마라.\n"
    "5) confidence: 0.0~1.0."
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
        sys.exit("[중단] openai 패키지 없음 -> pip install openai")
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


def norm_title(t):
    t = str(t).strip()
    t = re.sub(r"^\s*\[[^\]]{1,14}\]\s*", "", t)
    return re.sub(r"\s+", " ", t)


def assign_one(client, model, title, venue):
    user = f"제목: {title}\n학회/게재지: {venue}"
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


def build_summary(df, out_path):
    d = df.dropna(subset=["_year"]).copy()
    d["_year"] = d["_year"].astype(int)
    by_year = {}
    for (y, dom), n in d.groupby(["_year", "domain_primary"]).size().items():
        by_year.setdefault(str(y), {})[dom] = int(n)
    dom_tot = df["domain_primary"].value_counts().to_dict()
    grand = int(len(df))
    summary = {
        "domain_ver": DOMAIN_VER,
        "status": "v0.1",
        "source": "K-water연구원 논문·학술발표 목록 (STP, 1996~2026, 전수 아님·누락 존재)",
        "method": "제목+학회명 -> mini 배정 (개인정보 미전송)",
        "total": grand,
        "domains": {c: {"name": DOMAINS[c].split(":")[0], "count": int(dom_tot.get(c, 0)),
                        "pct": round(dom_tot.get(c, 0) * 100 / grand, 1)} for c in CODES},
        "by_year_domain": by_year,
    }
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    json.dump(summary, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return summary


def main():
    import pandas as pd
    ap = argparse.ArgumentParser()
    ap.add_argument("--xlsx", required=True)
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    df = pd.read_excel(args.xlsx)
    df = df.dropna(subset=["논문명"]).copy()
    df["_title"] = df["논문명"].map(norm_title)
    df["_venue"] = df["학회명"].fillna(df["게제지"]).fillna("")
    df = df[df["_title"].str.len() >= 4].copy()
    df["_tid"] = df["_title"].map(lambda t: hashlib.md5(t.encode()).hexdigest()[:12])
    df["_year"] = pd.to_numeric(df["년도"], errors="coerce")

    uniq = df.drop_duplicates("_tid")[["_tid", "_title", "_venue"]]
    print(f"전체 {len(df)}행 · 고유 제목 {len(uniq)}건")

    cache_dir = Path("local_kwater"); cache_dir.mkdir(exist_ok=True)
    cache_path = cache_dir / "pub_domain_cache.jsonl"
    done = {}
    if cache_path.exists():
        for line in cache_path.open(encoding="utf-8"):
            line = line.strip()
            if line:
                try:
                    r = json.loads(line); done[r["tid"]] = r
                except Exception:
                    pass

    todo = uniq[~uniq["_tid"].isin(done)].reset_index(drop=True)
    if args.limit:
        todo = todo.head(args.limit)
    print(f"배정 대상 {len(todo)} · 캐시완료 {len(done)}")

    if len(todo):
        client = get_client()
        from collections import Counter
        tally = Counter()
        with cache_path.open("a", encoding="utf-8") as f:
            for i, row in todo.iterrows():
                res = assign_one(client, args.model, row["_title"], row["_venue"])
                if res is None:
                    print(f"  {i+1}/{len(todo)} 실패(재시도 대상)", flush=True)
                    continue
                rec = {"tid": row["_tid"], "title": row["_title"], "venue": row["_venue"],
                       "primary": res["primary"], "secondary": res["secondary"],
                       "confidence": res["confidence"], "domain_ver": DOMAIN_VER}
                f.write(json.dumps(rec, ensure_ascii=False) + "\n"); f.flush()
                done[row["_tid"]] = rec
                tally[res["primary"]] += 1
                if (i + 1) % 50 == 0 or i + 1 == len(todo):
                    unc = tally.get("W0_UNCLASSIFIED", 0)
                    print(f"  {i+1}/{len(todo)} · 미분류 {unc} ({unc*100//max(i+1,1)}%)", flush=True)
        print("배정 분포:", ", ".join(f"{k}:{v}" for k, v in tally.most_common()))

    df["domain_primary"] = df["_tid"].map(lambda t: done.get(t, {}).get("primary"))
    df["domain_confidence"] = df["_tid"].map(lambda t: done.get(t, {}).get("confidence"))
    labeled = df.dropna(subset=["domain_primary"]).copy()
    print(f"병합 완료: {len(labeled)}/{len(df)}행에 도메인 부여")

    if not args.limit and len(labeled) == len(df):
        out_csv = cache_dir / "kwater_pubs_labeled.csv"
        cols = ["No", "관리번호", "년도", "분류", "논문명", "학회명", "게제지",
                "domain_primary", "domain_confidence"]
        labeled[[c for c in cols if c in labeled.columns]].to_csv(
            out_csv, index=False, encoding="utf-8-sig")
        print(f"로컬 CSV -> {out_csv}  (커밋 금지: 실명 포함 원장)")
        s = build_summary(labeled, "labels/domain/kwater_pubs_summary.json")
        print("집계 JSON -> labels/domain/kwater_pubs_summary.json (repo 푸시 가능)")
        top = sorted(s["domains"].items(), key=lambda x: -x[1]["count"])[:4]
        print("상위:", ", ".join(f"{k} {v['name']} {v['pct']}%" for k, v in top))
    elif args.limit:
        print("")
        print("[맛보기 결과 미리보기]")
        for t in list(done.values())[-min(args.limit, len(done)):]:
            print(f"  {t['primary']:<16} conf {t['confidence']:.2f} | {t['title'][:44]}")


if __name__ == "__main__":
    main()
