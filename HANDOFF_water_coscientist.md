# Water Co-Scientist 프로젝트 인수인계 (새 대화용 컨텍스트)

> 이 문서를 새 대화에 첨부하면 Claude가 프로젝트 맥락을 이어받습니다.
> 마지막 업데이트: 2026-07-12 (관제센터 Streamlit Cloud 배포 성공 직후)

## 1. 프로젝트 정체

**K-water연구원(KIWE) Water Co-Scientist 1단계** — 자료 수집·정리 + 협업관계 구축.
대상: 7개 연구소 전체 (INST-01 경영 / 02 수자원환경 / 03 상하수도 / 04 물인프라안전 / 05 물에너지 / 06 수자원위성 / 07 AI연구소).
소원장·원장 보고 예정. 이후 온프렘/연구용 클라우드(AWS·네이버) 이전, 전산직 인계 로드맵.
확장 계획: 논문(OpenAlex) + 특허(KIPRIS) + 기타 보고서 → 통합 DB → FT(KONI/Qwen)까지.

## 2. 완료·검증된 것 (실데이터 기준)

**ALIO 파이프라인 (1~5단계) 완주:**
- 보고서 121건 크롤링(전산직 부하 제작 크롤러) → 4단계(gpt-4o) 파싱 완료
- 결과: **정상 105건, 오류 16건**(Connection error 13 + JSON파싱 3, 재처리 대기)
- 데이터소스 mention **1,695건**, 고유 소스 **1,285개**, 파라미터 정규화 1,629건
- 결과 파일: `4_datasource_mentions_test_260708_kim.jsonl` (개발노트북에 있음)
- 핵심 설계: 페이지근거(evidence_pages) 100%, extraction_confidence, 체크포인트(jsonl), registry 2개(datasource/param) 별칭 정규화

**통합 PostgreSQL (스키마 실검증 완료):**
- documents(doc_type: report_alio/paper/patent/internal 등 5종 통합) + datasources/mentions/parameters/edges/institutes star schema
- 실적재 검증: 문서 105 / mention 1,491 / 협업 edge 39, 연구소 rule 분류 7개 소 분포
- 협업 인사이트 실증: "K-water 내부DB 7개 소 전부 공유(82건), 수자원환경↔물인프라안전 협업 최강"

**FT 체계 (코랩 학습 + Streamlit 모니터):**
- `make_ft_dataset.py`(PDF에서 입력 청크 복원→distillation 쌍), `colab_train_kwater.ipynb`(KONI-Llama3-8B/Qwen2.5-7B QLoRA, 지표를 깃헙 ft_logs/에 push하는 콜백 내장), `ft_monitor.py`
- 학습은 코랩 A100 전담 (사용자가 토큰/비용 부담 의사 표명)

**에이전트 관제센터 (오늘 배포 성공!):**
- `app_mission_control.py` — 5탭: 🛰️관제센터(펄스 상태카드+활동피드) / 📚수집현황 / 🏢7개 연구소(협업 히트맵) / 🔥FT모니터 / 🗂️인벤토리
- `agent_status.py` — 에이전트가 report() 한 줄로 status/json push → 관제센터 실시간 반영 프로토콜
- **Streamlit Cloud 배포 완료**: repo `newcave/water-tech-agent`, 시드는 실데이터 121건 기준

## 3. 인프라 현황

| 자산 | 상태 |
|---|---|
| repo `newcave/2607alioreport` | 파이프라인 코드 전체 (Public) |
| repo `newcave/rnddata` | 예전 대시보드 (200개 데이터 기반, 보존) |
| repo `newcave/water-tech-agent` | **관제센터 (방금 배포)** — app+data_seed 13파일 |
| Streamlit Cloud | water-tech-agent 앱 가동 (무료, sleep 특성 있음) |
| 개발노트북 (레노버 x64 16GB) | kwater conda env, 파이프라인 실행처, PDF 121개 보유 |
| 집 노트북 (RTX 3050 Ti **4GB**, RAM 32GB) | 홈서버 후보 — git·conda 설치됨, kwater env 아직 없음. FT 불가(4GB), 역할=상시 수집·DB·러너·임베딩. `SERVER_HOME_LAPTOP.md` 가이드 있음 |
| pro 500 (소장님, VRAM 6GB) | 학습 불가 → 코랩 Pro+ 사용 방침 |

주요 파일 위치: 개발노트북 `C:\202607_AlioReport`(파이프라인), `C:\rnddata_report`(기존앱+121데이터), 집노트북 `C:\water-tech-agent`(관제센터).

## 4. 미완/대기 항목 (다음 세션 후보)

1. **에러 16건 재처리** — jsonl에서 error 줄만 제거 후 4단계 재실행 (명령 제공 예정이었음)
2. **홈서버 세팅** — 집노트북에 kwater env + PostgreSQL + 작업스케줄러(수집기+status push) → 관제센터 펄스 실가동
3. **OpenAlex 첫 수집** — `collect_openalex.py --mode kwater` (ROR 04dtgat87 검증완료, 키 불필요)
4. **KIPRIS 키 신청** — data.go.kr 활용신청 (월 1,000회 무료), 승인 대기 필요
5. **FT run_001** — 코랩에서 노트북 실행 (Secrets에 GITHUB_TOKEN)
6. **self-hosted 러너 등록** — 라벨 `local-kwater`, pipeline.yml 연동
7. **B 보고자료** — 아키텍처 요약 + 전산직 요청서 (실숫자 반영)
8. rnddata_report 로컬 앱: data/ 폴더에 121개 CSV 덮어쓰기 후 실행 확인 중이었음

## 5. 핵심 설계 결정 (변경 금지 아님, 맥락용)

- NotebookLM 대체 이유: 120건→20행 뭉개짐, 페이지 추적 불가, 비재현 → per-document 추출로 해결
- 저장 추상화 `storage.py`: local↔s3(AWS/네이버/R2) 백엔드 .env 스위치, 클라우드 이전 무수정
- 모델 교체성: `EXTRACT_MODEL` env — FT 성공 시(필드 F1≥90%) 로컬 vLLM 엔드포인트로 교체해 OpenAI 의존 제거
- KONI는 물 전문 아님(KISTI 일반 과학기술 한국어 8B) — 물 전문성은 우리 FT 데이터에서 나옴
- 관제센터 원칙: 가짜 연출 없이 status 프로토콜로 "진짜 심박"; 미가동 에이전트는 🟡 대기로 정직 표기
- 사용자 성향: step-by-step 진행 선호, 화면 스크린샷으로 확인하며 감, git/conda 초보→이제 push 자립, PowerShell($env: 문법) 사용

## 6. 새 대화 시작 시 추천 첫 질문

"인수인계 문서 첨부했습니다. [하고 싶은 작업] 이어서 진행해주세요."
예: "홈서버 세팅부터" / "에러 16건 재처리부터" / "관제센터 화면 다듬기부터(스크린샷 첨부)"
