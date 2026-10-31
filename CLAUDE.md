# Water Co-Scientist — 작업 규칙 (Claude 세션 공통)

K-water연구원 AI연구소의 R&D 데이터 에이전트 플랫폼. 수집(OpenAlex·KCI·ALIO·KIPRIS) → 처리(초록·대상/문제·도메인 라벨) →
지식(연구소 지식노트·KCI 트렌드) → 사람 검토(HITL) → 활용(관제센터·FT)을 GitHub Actions와 Streamlit 앱으로 돌린다.
이 파일은 **클라우드든 PC든 이 저장소에서 일하는 모든 Claude 세션이 먼저 지키는 규칙**이다 (2026-10-26 사용자 확정).

## 1. 병행 작업 규칙 (클라우드 + PC)

1. **GitHub가 유일한 기준이다.**
   - 시작 전 항상 최신을 받는다: `git fetch origin && git checkout -B claude/<주제> origin/main`
   - 어느 쪽에서 작업하든 **브랜치 → PR → 머지**. main에 직접 커밋하지 않는다 (자동 실행 봇 커밋은 예외).
   - **같은 기능은 한쪽에서만 맡는다.** 시작 전 열린 PR·최근 커밋을 확인하고, 같은 파일을 다른 세션이 고치고 있으면 멈추고 사용자에게 묻는다.
   - 세션끼리 기억을 공유하지 않는다 → 결정·맥락은 PR 본문과 이 파일에 남긴다.
2. **역할을 나눈다 — 주력은 클라우드 + Streamlit 앱, PC는 백업.**
   - 클라우드: 자동 실행·스케줄, 오래 걸리는 분석, 앱 기능 개발과 PR. 결과물의 주 무대는 main을 자동 배포하는 Streamlit 앱이다.
   - PC(백업 위주): 클라우드 세션이나 Streamlit Cloud를 못 쓸 때 같은 저장소로 이어서 작업하고 앱을 로컬로 띄운다
     (`streamlit run app_mission_control.py` — 데이터는 GitHub에서 읽으므로 그대로 동작). 그 밖에 내부 문서(HWP 등)·내부망 자료·시연 확인·agent4d 관찰.
   - 기본은 **클라우드 세션 하나를 PC에 연결**(Claude 데스크톱 앱 → 이 작업 열기 → "이 컴퓨터에 연결")해서 쓴다. 세션이 하나라 기억이 갈라지지 않는다.
   - PC에서 고친 것도 규칙 1대로 브랜치 → PR → 머지로 올린다 (PC 로컬에만 남은 변경은 백업이 아니라 갈라진 사본이다).
3. **비밀값은 GitHub Secrets와 Streamlit Secrets에만 둔다.**
   - 코드·문서·커밋·PR·채팅에 토큰·키를 쓰지 않는다. 예시는 `github_pat_...`처럼 줄임표로만.
   - 예외: 홈서버 self-hosted 러너의 `.env` (PC 안에서만, `.gitignore` 등록됨 — 절대 커밋 금지).
   - **KCI 원천 자료는 비공개 저장소 `newcave/water-tech-kci-private` 밖으로 내보내지 않는다** (재배포 금지). 공개 저장소에는 집계(건수·용어·검정 결과)만.
   - `newcave/openalex-data`(openalex 수집 원본·분석 결과, 비공개)도 공개 저장소에는 집계만 — 논문 해석 원문·검토 메모·전체 논문 목록·코퍼스 원본은 옮기지 않는다.
   - PR마다 `guard` 워크플로가 토큰 꼴 문자열·비밀 파일·KCI 원천 필드를 검사한다.

## 2. 저장소 지도

| 위치 | 내용 |
|---|---|
| `main` | 앱(`app_mission_control.py` + 모듈), 에이전트 코드(`agents/`), 집계(`data_seed/`), 워크플로 — Streamlit Cloud가 main을 자동 배포 |
| `data` 브랜치 | 수집 원본(`live/`), 라벨(`labels/`), 판정 기록(`labels/hitl/<INST>/ledger.jsonl` 등) — 봇이 수시로 push, **강제 push 금지** |
| `water-tech-kci-private` | KCI 원천(`raw/`), 사람 판정 오버라이드(`review/`), WCS 특허 원천(`wcs/patents.csv` — 🗺️ 기술 지도용, 공개 저장소엔 집계만) |

주요 모듈: `knowledge_notes.py`(지식노트) · `label_review.py`/`label_review_page.py`(라벨 판정 HITL) · `data_cache.py`(공용 캐시) ·
`agent_flow.py`(🌊 흐름 화면) · `flows/*_agent_flow.html`(사이드바 Agent Flow 확인用 — WCS·HEC-RAS 서로게이트·RND-HELP·4B LoRA·OpenAlex 연구트렌드 흐름도, 표 N·E·SCN만 고침, 버튼은 `AGENT_FLOWS` 한 줄, 보기가 여럿이면 {보기: 파일} — WCS 외에는 기본·전문가 두 보기) · `agents/kci_rising.py`(KCI 단어·구 상승 분석) · `agents/oa_rising.py`·`oa_rising_page.py`(🔭 상승 연구주제 — 방법의 주인은 newcave/openalex, 여기서는 비공개 newcave/openalex-data 결과를 `secrets.OPENALEX_DATA_TOKEN`(읽기 전용)으로 매주 읽어 집계만 `data_seed/oa_rising/`에 씀 · 다시 계산하지 않음 · 에이전트 `oa_rising` 심박은 data 브랜치 `live/agents/oa_rising.json` — 관제센터 KPI·함대·🌊 흐름에 연결) · 연구소 배정 판정 기록: `decision`은 예전 값(ok·ng·move·skip) 그대로, 누른 버튼은 `action`(keep·add·move·drop·later / 받는 쪽 accept·share·reject, role=receiver, 보낸 연구소 폴더에 기록) — data 브랜치 `hitl_ledger.py`와 호환 · `inst_trend.py`(📄 논문 트렌드 맨 위 '해외 × 연구소 최근 5년' — `agents/openalex_lite.py`가 6시간마다 `openalex_trends.json`에 씀: 연구소 키워드 전체 OR 합집합 `institutes.<INST>.by_year_all`(카드·차트 기준) · 키워드별 `by_kw`(연구소 트랙의 키워드별 추이) · 대표 키워드 1개 `by_year`(= 실제 수집 검색식, 수집률 기준) · OpenAlex 전체 기준선 `baseline` · 피인용 질(v3.15) — 같은 검색에 `citation_normalized_percentile.is_in_top_10_percent:true`를 더한 `*_top10`(분야·연도 보정, 세계 평균 약 10%)과 K-water 소속 `kwater_citation`, 받아 둔 피인용 수(받은 날 숫자)는 비교에 쓰지 않음 · OpenAlex 무키 사용량은 하루 $0.10(검색 약 100건)이라 피인용 조회는 실행마다 연구소 4묶음으로 돌려 하루 한 바퀴(`CIT_SLOTS`), 오류 원인은 `agents/openalex_collector.json`의 `last_errors` · 연구소 트랙은 live + `labels/openalex_extended`를 id로 합쳐 5년 창만 봄 · **수집 검색식은 대표 키워드 1개 (키워드 전체 수집은 '일단 대기', 2026-10-27)** — 승인 뒤 실측해 보니 최근 5년 약 20.7만 편(약 17만 편 추가, 라벨링 30~50달러)이라 보류. 다시 켜려면 data 브랜치 `labels_pipeline.py`의 `COLLECT_ALL_KEYWORDS = True`(키워드마다 따로 검색해 id로 합침) · `pipeline_state.json`의 `collect_basis`(all/rep)로 앱이 비교 기준을 고름 · main의 `openalex_collect.py` 실시간 수집(2025-07~)은 대표 키워드 1개 그대로) · `kci_compare_page.py`(🆚 K-water 비교(KCI) 탭, v3.17 — 최근 5년 KCI 논문을 연구소 한국어 키워드(`label_review_profiles.json` keywords.ko, 제목 2점·초록 1점, 2점 이상)로 7개 분야에 나눠 K-water 논문과 국내 학회지(J11+J12)를 견줌: 분야 구성·특화도·같은 학회지 안 점유율·연도별, 재료 `data_seed/kci_inst.json` — `agents/kci_inst.py`가 kci-rising 워크플로 분석 단계(월요일)에서 비공개 원천을 읽어 건수만 씀) · `citation_page.py`(🏅 피인용 질 사이드바 탭, v3.16 — 연구소 카드·막대·성장×피인용·연도별 추이·키워드 순위표·연구소별 키워드 산점도, 재료는 `openalex_trends.json`의 `*_top10`) · `asset_page.py`(🗄️ 지식자산 현황 — WCS 연구보고서·논문·특허 구성 도넛, 숫자는 `data_seed/wcs_assets.json`의 count·as_of만 고침) · `agents/tech_map.py`·`tech_map_patents.py`·`tech_map_score.py`(🗺️ 논문 × 특허 기술 지도, 2026-11-01 — 세부 기술 정의서 `data_seed/tech_map/units.json`(41개: en = OpenAlex 검색어 = 연구소 키워드, ko = 특허 찾기 말 'A+B'는 둘 다, ipc 힌트 — 연구소가 고침) · `tech-map` 워크플로 6시간마다 OpenAlex 2016~작년 건수를 이어 받음(by_year·피인용 상위10%·기업 공저·K-water·주제·연도별 게재 저널, `secrets.OPENALEX_API_KEY` 있으면 한 번에) · 저널 IF는 JCR 대신 OpenAlex 2년 평균 피인용(`journals.json`, 받은 날 값) · WCS 특허 CSV 원천은 비공개 `water-tech-kci-private/wcs/patents.csv`에만, 공개엔 세부 기술·출원연도별 건수 `patents.json`만 · `scores.json` = 해마다 41개 사이 백분위 X(논문: 규모·성장·질·저널) · Y(실용화: 특허 규모·성장·등록률·기업 비율 + 논문 산업계 공저, 특허 없으면 산업계 공저만으로 '임시') · 사분면 주력·코어/실용화 과제/실용화 성숙/검토 필요(성장 70 이상은 위크시그널 후보)) · 설정 `data_seed/*.json`(키워드·목표·문턱 — 연구소가 직접 고침).

**연도 창 (2026-10-27 사용자 지정): 최근 5년, 하루에 1년씩.** KCI 원천은 `kci-rising` 워크플로가 매일 최근 5년 중 한 해를 다시 받고(`KCI_RECENT_YEARS=5`·`KCI_ROTATE=1`, 분석·공개 집계는 월요일만), OpenAlex 연구소 관련 논문은 data 브랜치 `labels_pipeline.py`가 역사 수집 완주 뒤 최근 5년을 하루 1년씩 다시 훑는다(`RESWEEP_YEARS=5`, 상태는 `labels/pipeline_state.json`의 `resweep_*`).

## 3. 개발·시험·배포

- 실행: `streamlit run app_mission_control.py`
- 시험: 바꾼 화면은 `streamlit.testing.v1.AppTest`로 열어 예외가 없는지, 가능하면 Playwright로 화면을 찍어 확인.
  자동 새로고침이 켜진 화면은 AppTest에서 멈출 수 있으니 `session_state["nav_start"]`로 화면을 고르고, 판정 화면 시험은
  `HITL_PENDING_DIR`를 임시 폴더로 지정한다 (실제 data 브랜치에 쓰지 말 것 — 직접 저장 시험은 GitHub API를 모의).
- 화면 추가: 사이드바 `PAGES`(또는 HITL 검토 버튼) + `elif page == …` + 입력 중 초기화되면 안 되는 화면은 자동 새로고침 제외 목록에 추가 + `APP_VERSION` 올림.
- 버전: 화면·기능 추가는 `v3.N`(예: v3.7 → v3.8), 이름·순서·문구 같은 작은 수정은 `v3.N.x`(예: v3.7 → v3.7.1) (2026-10-26 사용자 지정).
- 에이전트 추가: `AGENT_META` 한 줄 + `data_seed/agents/<id>.json` + 워크플로(실행마다 data 브랜치 상태 기록) + `agent_flow.py` 노드·연결선.
- PR: 한국어 본문(무엇·왜·시험), 시험 통과 후 **머지까지 진행**하고 사용자에게 무엇이 바뀌었는지 짧게 알린다.
- 토큰·비용이 드는 작업(LLM 대량 호출, 재수집)은 사용자 승인 후에만.
