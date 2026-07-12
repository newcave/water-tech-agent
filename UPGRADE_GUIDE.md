# 🌅 굿모닝 — v2 업그레이드 적용 가이드 (2026-07-13)

어젯밤 지시하신 8개 항목을 모두 반영했습니다. **파일 6개를 GitHub에 올리면 끝**입니다 (약 10분).

## 0. 무엇이 바뀌었나 (지시 항목 ↔ 반영)

| 지시 | 반영 |
|---|---|
| ① OpenAlex/KIPRIS 코드는 추후 입고 | 수집기 슬롯·인터페이스만 준비 (`search_topics.json` + 에이전트 카드) — 코드 주시면 바로 연결 |
| ② 7개 연구소 기준 × 물 키워드 검색 | `data_seed/search_topics.json` — 연구소별 논문(영문)/특허(국문) 키워드, 배열에 추가만 하면 확장 |
| ③ 기사 파이프라인 추후 | `article_collector` 에이전트 슬롯(⚪ 설계) + 수집현황 행 추가 |
| ④ FT 끊겨도 누적·버전관리 | `ft_logs/index.json` 자동 유지(노트북) + 관제센터 **run 이력 테이블** + resume 이어쓰기 + Drive 로컬 미러 |
| ⑤ 코랩 안 끊기게 | Pro+ 백그라운드 실행 안내 + **체크포인트 자동 재개**(끊겨도 최대 100스텝만 유실) — 노트북 v3 |
| ⑥ GUI 프로페셔널 (K-water풍) | 딥블루 기관 헤더밴드·화이트 카드·Noto Sans KR 전면 재설계 |
| ⑦ FT 계속 + 수집이 중심 | 관제센터 첫 화면 = **에이전트 함대** + 파이프라인 플로우, ft_trainer 카드는 최신 run과 자동 연동 |
| ⑧ 에이전트들이 돌아가는 이미지 | 함대 그리드(수집×4 + 처리×2 + 학습×1) + 운영 콘솔 피드, 정직 표기(🟡/⚪) 유지 |

앱은 컨테이너에서 **실데이터로 5개 탭 전부 구동 테스트 통과**했고, 노트북은 ipynb 유효성·문법·로거 단위테스트까지 통과했습니다. 기존 `data_seed` 형식·`agent_status.py` 프로토콜과 100% 호환 — 홈서버 쪽은 아무것도 안 바꿔도 됩니다.

## 1. GitHub에 올리기 (웹에서, 아무 노트북이나 OK)

repo **newcave/water-tech-agent** 에서:

| 파일 | 위치 | 방법 |
|---|---|---|
| `app_mission_control.py` | 루트 (기존 교체) | 파일 열기 → ✏️ → 전체 삭제 후 새 내용 붙여넣기 → Commit |
| `requirements.txt` | 루트 (기존 교체) | 위와 동일 |
| `config.toml` | `.streamlit/config.toml` (신규) | Add file → Create new file → 파일명에 `.streamlit/config.toml` 입력 |
| `search_topics.json` | `data_seed/` (신규) | Add file → Upload files |
| `article_collector.json` | `data_seed/agents/` (신규) | Add file → Upload files |
| `colab_train_kwater_v3.ipynb` | 루트 (신규, 권장) | Upload — 이러면 코랩에서 *파일→노트 열기→GitHub* 탭으로 바로 열림 |

집노트북(`C:\water-tech-agent`)에서 PowerShell로 하셔도 됩니다:
```powershell
git pull
# 다운로드한 파일들을 해당 위치에 복사한 뒤
git add -A; git commit -m "v2: 프로페셔널 관제센터 + FT 버전관리 + 에이전트 슬롯"; git push
```

커밋하면 Streamlit Cloud가 1~2분 내 자동 재배포합니다.

## 2. 배포 확인 체크리스트

- [ ] 상단에 **딥블루 헤더 밴드** (K-WATER INSTITUTE · 가동/대기 배지)
- [ ] 관제센터: KPI 6칸(기사 포함) → **파이프라인 플로우** → **에이전트 함대 7개 카드**
- [ ] 🔥 FT 모니터: **run 이력 테이블**에 `run_000_smoke` (✅ 완료) 표시
- [ ] 로컬 실행도 쓰신다면 한 번만: `pip install -U streamlit` (신규 API 사용)

## 3. 코랩 (v3 노트북)

- v2와 사용법 동일 + **끊김 대응 내장**: 재실행하면 지표 이어받고(resume) 마지막 체크포인트에서 학습 재개. `RUN_ID`만 유지하면 됩니다.
- Pro+ 백그라운드 실행: 런타임 → 런타임 유형 변경 → *백그라운드 실행* 체크 → 실행 후 브라우저 닫아도 진행.
- 남은 재료: 개발노트북의 학습데이터 jsonl 업로드 → T4 smoke → L4 본학습.

## 4. 문제 시 되돌리기

GitHub → 해당 커밋 → `Revert` 버튼 한 번이면 이전 버전으로 복귀합니다 (data_seed는 안 건드리므로 데이터 무손실).

## 5. 다음 후보 (코드 입고 시)

OpenAlex/KIPRIS 수집기 코드를 주시면: `search_topics.json` 읽기 + `agent_status.report()` 한 줄 + `summary.json`의 `papers`/`patents` 갱신 — 이 3가지만 연결하면 관제센터에 자동으로 살아납니다.
