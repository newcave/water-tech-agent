#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_openai — B500(사내망) OpenAI 사전점검 (0단계, 단독 실행)

러너(llm_classify.py)가 쓰는 것과 동일한 경로를 4단계로 검증:
  [1] .env / OPENAI_API_KEY 존재
  [2] 망+인증: GET /v1/models (토큰 과금 없음) → 사내 프록시/SSL인스펙션 여부가 여기서 드러남
  [3] 모델 접근권한: gpt-4o-mini / gpt-4.1계열 등 분류용 모델 사용 가능 목록
  [4] 1회 초소형 판정 핑: strict json_schema + usage(cached_tokens) 필드 확인 — 비용 $0.0001 미만

사용:
  pip install requests
  python check_openai.py                # 기본
  python check_openai.py --insecure     # SSL 오류 원인분리용 (검증 생략 — 진단에만!)

실패 시 진단:
  SSLError            → 사내 SSL 인스펙션. 사내 루트인증서(pem) 받아
                        set REQUESTS_CA_BUNDLE=C:\\certs\\company_ca.pem 후 재시도
  ProxyError/Timeout  → set HTTPS_PROXY=http://프록시주소:포트  (requests가 자동 사용)
  401                 → 키 오류/폐기됨
  429 insufficient_quota → 결제/크레딧 없음 (조직 Billing 확인)
  404 model_not_found → 해당 모델 접근권한 없음 → 목록의 다른 모델로 CLF_MODEL 변경
"""
import json
import os
import sys
from pathlib import Path

import requests

BASE = "https://api.openai.com/v1"
VERIFY = "--insecure" not in sys.argv
if not VERIFY:
    print("⚠️  --insecure: SSL 검증 생략 (원인분리 전용 — 상시 사용 금지)")
    requests.packages.urllib3.disable_warnings()

PREF = ["gpt-4o-mini", "gpt-4.1-mini", "gpt-4.1-nano", "gpt-4o", "gpt-4.1"]


def load_dotenv():
    p = Path(__file__).resolve().parent / ".env"
    for cand in (p, p.parent.parent / ".env"):           # 스크립트 옆 / 레포 루트
        if cand.exists():
            for line in cand.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            return str(cand)
    return None


def main():
    print("═" * 56)
    print(" OpenAI 사전점검 (B500 사내망)")
    print("═" * 56)

    # [1] 키
    envp = load_dotenv()
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        print("❌ [1] OPENAI_API_KEY 없음 — .env(레포 루트)에 한 줄:")
        print("      OPENAI_API_KEY=sk-...   (⚠️ .gitignore에 .env 추가 먼저!)")
        return 1
    print(f"✅ [1] 키 확인 ({key[:7]}…{key[-4:]})"
          + (f" · .env: {envp}" if envp else " · 환경변수"))
    H = {"Authorization": f"Bearer {key}"}

    # [2] 망+인증 (과금 없음)
    try:
        r = requests.get(f"{BASE}/models", headers=H, timeout=20, verify=VERIFY)
    except requests.exceptions.SSLError as e:
        print("❌ [2] SSLError — 사내 SSL 인스펙션 가능성 큼.")
        print("      ① IT에서 사내 루트인증서(pem) 수령 → set REQUESTS_CA_BUNDLE=경로")
        print("      ② 원인분리만: python check_openai.py --insecure")
        print("      상세:", str(e)[:150])
        return 2
    except requests.exceptions.RequestException as e:
        print("❌ [2] 연결 실패 — 프록시/방화벽 가능성.")
        print("      set HTTPS_PROXY=http://프록시:포트  (사내 프록시 주소는 IT 확인)")
        print("      상세:", str(e)[:150])
        return 2
    if r.status_code == 401:
        print("❌ [2] 401 인증 실패 — 키 오탈자/폐기 여부 확인")
        return 2
    r.raise_for_status()
    print(f"✅ [2] api.openai.com 도달 + 인증 OK (models {r.status_code})")

    # [3] 모델 접근권한
    ids = sorted(m["id"] for m in r.json().get("data", []))
    fam = [i for i in ids if i.startswith(("gpt-4o", "gpt-4.1", "gpt-5", "o3", "o4"))]
    print(f"✅ [3] 사용 가능 모델 {len(ids)}종 — 분류후보:")
    for i in fam[:15]:
        print("      ·", i)
    model = next((p for p in PREF if p in ids), None) or (fam[0] if fam else None)
    if not model:
        print("❌ [3] 분류용 모델 후보 없음 — 목록을 공유해 주세요")
        return 3
    print(f"→ 핑 모델: {model}")

    # [4] 초소형 판정 핑 (strict schema + usage 필드)
    schema = {"name": "ping", "strict": True,
              "schema": {"type": "object", "additionalProperties": False,
                         "required": ["ok"], "properties": {"ok": {"type": "boolean"}}}}
    body = {"model": model, "max_completion_tokens": 20, "temperature": 0,
            "messages": [{"role": "system", "content": "JSON only."},
                         {"role": "user", "content": '{"ok": true} 를 반환'}],
            "response_format": {"type": "json_schema", "json_schema": schema}}
    r = requests.post(f"{BASE}/chat/completions", headers={**H,
                      "Content-Type": "application/json"},
                      json=body, timeout=60, verify=VERIFY)
    if r.status_code != 200:
        print(f"❌ [4] {r.status_code}:", r.text[:300])
        return 4
    j = r.json()
    u = j.get("usage", {})
    cached = (u.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
    content = j["choices"][0]["message"]["content"]
    ok = json.loads(content).get("ok") is True
    print(f"✅ [4] strict schema 응답 {'OK' if ok else '이상'} — {content}")
    print(f"      usage: prompt {u.get('prompt_tokens')} (cached {cached}) / "
          f"completion {u.get('completion_tokens')}")
    print("═" * 56)
    print(f"🏁 전체 통과 — 러너 기본값으로 CLF_MODEL={model} 사용 가능.")
    print("   다음: 번들 5파일 커밋 → python agents/llm_classify.py --local")
    return 0


if __name__ == "__main__":
    sys.exit(main())
