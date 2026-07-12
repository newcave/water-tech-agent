# 홈서버 가이드 — 집 노트북 (RTX 3050 Ti Laptop, RAM 32GB)

집에서 24시간 켜두는 **상시 에이전트 서버**. GPU가 4GB(3050 Ti Laptop)라
FT 학습은 못 하지만, 이 체계에서 진짜 필요한 건 학습이 아니라 "상시 가동"입니다.

## 역할 분담 (정직한 하드웨어 매핑)

| 작업 | 홈서버(3050Ti) | 개발노트북(레노버) | 코랩 A100 |
|---|---|---|---|
| PostgreSQL 상시 가동 | ✅ **주력** | 개발용 사본 | - |
| 수집 에이전트 스케줄 실행 (OpenAlex/KIPRIS/ALIO) | ✅ **주력** | 수동 실행 | - |
| self-hosted 러너 (상시 온라인) | ✅ **주력** | 낮에만 | - |
| 임베딩 생성 (BGE-m3, 배치 작게) | ✅ 가능(4GB) | CPU 밤샘 | 가능 |
| 관제센터 status push | ✅ 자동 | - | FT 지표만 |
| **FT 학습 (QLoRA 8B)** | ❌ 불가(4GB) | ❌ | ✅ **전담** |
| FT 후 추론 서빙 | △ 3B 양자화까지 | - | - |

## 설치 (1회, 30분)

1. **Anaconda 확인** (이미 있음) → 환경 생성:
   ```
   conda env create -f environment.yml    # kwater 환경 (개발노트북과 동일)
   ```
2. **PostgreSQL 16** — postgresql.org Windows 설치 → `kwater` DB 생성 → `schema.sql` 적용
   → `load_to_postgres.py`로 121건 적재 (개발노트북에서 검증된 그대로)
3. **repo clone**: `git clone https://github.com/newcave/2607alioreport.git`
4. **.env**: OPENAI_API_KEY, PG_DSN, GITHUB_TOKEN(status push용), KIPRIS_KEY(승인 후)
5. **전원 설정**: 덮개 닫아도 절전 안 함 / 자동 절전 해제 (제어판 → 전원 옵션)

## 상시 스케줄 등록 (Windows 작업 스케줄러)

작업 스케줄러(taskschd.msc) → 기본 작업 만들기, 아래 3개:

| 작업 | 주기 | 명령 (프로그램: cmd, 인수:) |
|---|---|---|
| 논문 수집 | 매일 06:00 | `/c cd C:\\2607alioreport && conda run -n kwater python collectors\\collect_openalex.py --mode kwater --max 500` |
| 특허 수집 | 매주 월 06:30 | `/c cd C:\\2607alioreport && conda run -n kwater python collectors\\collect_kipris.py --applicant 한국수자원공사 --max 200` |
| 대시보드 export | 매시간 | `/c cd C:\\2607alioreport && conda run -n kwater python export_dashboard_data.py` |

각 수집기는 `agent_status.report(...)`를 호출하므로, 실행될 때마다
**관제센터의 펄스가 뛰고 활동 피드에 줄이 올라갑니다** — 연출이 아니라 실제 하트비트.

## self-hosted 러너 (선택, 권장)

개발노트북 대신 홈서버를 러너로 등록하면 "로컬 연결 시에만"이 "항상"이 됩니다:
repo → Settings → Actions → Runners → New self-hosted runner → 라벨 `local-kwater`
→ `./svc.sh install`(서비스 등록)로 부팅 시 자동 시작.

## 임베딩 (4GB에서 되는 것)

```
pip install sentence-transformers
python - << 'PY'
from sentence_transformers import SentenceTransformer
m = SentenceTransformer("BAAI/bge-m3", device="cuda")   # 4GB: batch 8~16
# documents.abstract → 벡터 → pgvector 저장 (다음 단계 스크립트로 제공)
PY
```
수만 건도 밤새 돌리면 됩니다. 학습이 아니라 추론이라 4GB로 충분합니다.

## 요약: 이 노트북의 정체성

"놀고 있는 노트북" → **Co-Scientist의 심장**. 매일 아침 논문을 긁고, 매주 특허를 채우고,
매시간 관제센터에 심박을 보내는 무인 에이전트 스테이션. 무거운 근육(FT)은 코랩이 빌려주고,
심장은 집에서 24시간 뜁니다.
