"""
data 브랜치 원본 파일 공용 캐시 — 관제센터 여러 화면(지식노트·라벨 판정)이 같은 파일을 한 번만 받는다.

속도 원칙
  · st.cache_resource: 캐시된 객체를 '복사 없이' 그대로 돌려준다 (cache_data는 부를 때마다 통째로
    복사 — 수 MB짜리 목록이면 화면을 다시 그릴 때마다 그만큼 느려짐). 대신 받은 목록·dict를 고치지 말 것.
  · 한 연구소에 필요한 파일 여러 개는 동시에(병렬) 받는다.
  · 라벨링 파이프라인은 6시간마다 돌므로 30분 캐시로 충분하다.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

import requests
import streamlit as st

REPO = "newcave/water-tech-agent"
RAW = f"https://raw.githubusercontent.com/{REPO}"


def parse_jsonl(text: str | None) -> list[dict]:
    """\\n으로만 나눈다 (제목 속 U+2028 같은 유니코드 줄바꿈 보호). 깨진 줄은 건너뜀."""
    out = []
    for line in (text or "").split("\n"):
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out


def fetch_text(url: str, timeout: int = 40, params: dict | None = None) -> str | None:
    try:
        r = requests.get(url, params=params, timeout=timeout)
        if r.status_code == 200:
            return r.text
    except Exception:
        pass
    return None


def fetch_many(urls: list[str], timeout: int = 40, workers: int = 8) -> list[str | None]:
    """여러 파일을 동시에 받는다 (순서 유지). 캐시 함수 안에서만 부를 것 — 스레드는 st.* 를 쓰지 않는다."""
    if not urls:
        return []
    with ThreadPoolExecutor(max_workers=min(workers, len(urls))) as ex:
        return list(ex.map(lambda u: fetch_text(u, timeout), urls))


@st.cache_resource(ttl=1800, show_spinner=False, max_entries=64)
def data_jsonl(rel_path: str) -> list[dict]:
    """data 브랜치 JSONL 하나 → list[dict] (공유 객체 — 고치지 말 것)."""
    return parse_jsonl(fetch_text(f"{RAW}/data/{rel_path}"))


@st.cache_resource(ttl=1800, show_spinner=False, max_entries=16)
def inst_core(inst: str) -> dict:
    """연구소 하나의 논문 메타(1차+확장)·대상/문제 추출·도메인 라벨을 동시에 받는다 (공유 객체)."""
    paths = [f"live/openalex/papers_{inst}.jsonl", f"labels/openalex_extended/papers_{inst}.jsonl",
             f"labels/extract/{inst}.jsonl", f"labels/domain/{inst}.jsonl"]
    live, ext, extract, domain = (parse_jsonl(t) for t in fetch_many([f"{RAW}/data/{p}" for p in paths]))
    return {"papers": live + ext, "extract": extract, "domain": domain}


@st.cache_resource(ttl=1800, show_spinner=False, max_entries=16)
def inst_abstracts(inst: str) -> list[dict]:
    """연구소 하나의 초록 (라벨 판정 점수·카드, 지식노트 내보내기)."""
    return data_jsonl(f"labels/abstracts/{inst}.jsonl")
