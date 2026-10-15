# 작업 보드

> 자동 생성 — `ops/board.json` 을 고치고 `python scripts/board.py` 로 다시 만든다. 이 파일을 직접 고치지 말 것.

기준일 2026-10-16 · 작업 23개 · 진행 2 · 검수 4 · 대기 7 · 보류 0 · 완료 10

## 진행 (2)

| 우선 | id | 작업 | 담당 | 시작 | 기한 | 파일 | 선행 | 메모 |
|---|---|---|---|---|---|---|---|---|
| P1 | `earn-brief-pb` | 보유 종목 실적 브리프 (비공개) | 애널 | 2026-10-16 | 2026-10-16 | private 전용 | — |  |
| P1 | `deriv-hist` | 수급·파생 일별 이력 적재 (투자자별 현물·선물, 프로그램, 베이시스, OI, PCR, 벽, 감마) + 백필 | 파생 | 2026-10-16 | 2026-10-20 | `screener/deriv_hist.py`<br>`data/deriv/*`<br>`.github/workflows/deriv_hist.yml` | — | 검증의 전제. 라이브 화면·텔레그램 추가 없음. |

## 검수 (4)

| 우선 | id | 작업 | 담당 | 시작 | 기한 | 파일 | 선행 | 메모 |
|---|---|---|---|---|---|---|---|---|
| P1 | `earn-cal-q3` | 국장 3분기 실적 시즌 캘린더 (회사 확정일 반영) | 애널 | 2026-10-16 | 2026-10-16 | `screener/calendar_ev.py`<br>`reports/calendar.json` | — |  |
| P1 | `drivers-audit` | EARNINGS DRIVERS 내용 감사 (체인 매핑·부호·문구) + 퀀트 감사 반영 | 애널 | 2026-10-16 | 2026-10-17 | `screener/drivers.py`<br>`apps-script/Index.html` | — | 지주사·기계·운송 업종 체인 오매핑 제거, 매크로 가정 축소, 10년물 bp, 뉴스 반대말 규칙, 날짜별 보관 |
| P1 | `view-registry` | VIEW 레지스트리 — 관점(렌즈) 기록·일관 적용·수명주기 | CIO | 2026-10-16 | — | `views/registry.json`<br>`views/README.md`<br>`screener/views.py`<br>`scripts/view_attribution.py`<br>`screener/duel.py`<br>`screener/committee.py`<br>`screener/main.py`<br>`apps-script/Index.html`<br>`apps-script/Code.gs`<br>`scripts/build_pages.py` | — | 공개 레지스트리엔 개인 수치 없음 — 개인 렌즈는 pb-private views/personal.json 에서만. |
| P3 | `study-derivs` | STUDY 모듈: 선물·옵션 읽는 법 (초보용) | 파생 | 2026-10-16 | 2026-10-23 | `content/study.json` | — |  |

## 대기 (7)

| 우선 | id | 작업 | 담당 | 시작 | 기한 | 파일 | 선행 | 메모 |
|---|---|---|---|---|---|---|---|---|
| P0 | `close-swap-verify` | 16:20 잠정→확정 종가 교체 검증 | PB | — | 2026-10-16 | `.github/workflows/screener.yml`<br>`screener/data_krx.py` | — | 16:20 screener.yml 실행 후 당일 KR 종가가 정규장 확정치로 바뀌었는지 (지수·종목 상세·데일리 일치). |
| P0 | `gas-sched-verify` | GAS 예약기 실전 검증 (08:40 / 15:45 / 22:20) | PB | — | 2026-10-16 | `apps-script/Scheduler.gs`<br>`.github/workflows/live.yml`<br>`.github/workflows/briefing.yml` | `ops-system` | SYSTEM › 운영 상태의 'GAS 예약기' 표로 확인: 슬롯별 dispatch 도착 여부·지연(분), 같은 시각 GitHub 예약 중복 실행이 건너뛰어졌는지. |
| P0 | `repo-cleanup` | 저장소 대청소: 데이터 브랜치 분리·Pages Actions 배포·기록 정리(filter-repo) | 개발 | — | 2026-10-18 | `.github/workflows/*`<br>`scripts/build_pages.py` | — | 겸이 승인(10/16 00:51): 10/18(일) 오전 실행. ①② 사전 준비, ③ 기록 정리는 실행 직전 겸이 최종 확인. 모든 예약·에이전트 일시 정지 후 진행, 이후 재클론. |
| P0 | `rebalance-support` | 리밸런싱 실행 지원 (상세는 private) | PB | — | — | private 전용 | — | private 저장소 전용. 종목·수량·금액은 이 판에 적지 않는다. |
| P2 | `derivs-audit` | derivs.py 계산·문구 점검 (벽·PCR·감마·최대고통) | 파생 | — | 2026-10-20 | `screener/derivs.py` | — |  |
| P2 | `night-futures-line` | 장전 브리핑에 야간선물 한 줄 (마감 등락 → 예상 시초가) | 파생 | — | 2026-10-20 | `screener/briefings.py`<br>`screener/deriv_hist.py` | — | 실시간 밤 티커는 만들지 않음 — 08:50 장전 메시지·텔레그램 한 줄만. 데이터 소스(KRX 야간 K200F) 확인 필요, 거래량 적은 날 표시. |
| P2 | `derivs-validate` | 파생 신호 사전등록 검증 (선물 외국인·베이시스·PCR·감마·야간선물→시가갭) | 파생 | — | 2026-10-23 | `reports/studies/derivs_signals.*`<br>`scripts/study_derivs_signals.py` | `deriv-hist` | 결과는 views 레지스트리 등급 입력으로 (lens_id·grade·n·effect). |

## 완료 (10)

| 우선 | id | 작업 | 담당 | 시작 | 기한 | 파일 | 선행 | 메모 |
|---|---|---|---|---|---|---|---|---|
| P1 | `ops-system` | 운영 체계 (작업 보드·잠금·함수 소실 검사·변경 이력·SYSTEM 탭) | 운영 | 2026-10-15 | 2026-10-15 | `ops/*`<br>`scripts/changelog.py`<br>`scripts/board.py`<br>`scripts/lock.py`<br>`scripts/check_functions.py`<br>`scripts/ops_runs.py`<br>`.github/workflows/ops.yml`<br>`apps-script/Index.html`<br>`apps-script/Code.gs`<br>`scripts/build_pages.py`<br>`reports/changelog.json`<br>`reports/ops/*` | — | Index.html 동시 편집으로 함수가 지워진 회귀(myRun) 재발 방지. 에이전트 규약은 ops/README.md. |
| P1 | `ai-credit` | AI 인프라 신용 감시 | 채권 | 2026-10-15 | — | `screener/bonds.py`<br>`screener/committee.py`<br>`apps-script/Index.html` | — | 업종 국지 신용 스트레스 경보(정상/주의/경계) → 운용회의 head 한 줄 + 채권 탭 섹션. 10/15 첫 커밋. |
| P1 | `core-weights` | 코어 자산배분 최적 비중 | 자산배분 | 2026-10-15 | — | private 전용 | — | private 저장소 전용. |
| P1 | `pm-usage` | 사용 기록(로컬 집계)·내보내기 + PM 지표 체계 | PM | 2026-10-15 | — | `apps-script/Index.html` | — | 웹은 일별 횟수만 localStorage 에 저장, 내보내기는 비공개 저장소 이슈 폼으로. 리포트·지표 정의는 private. |
| P1 | `weekly-scorecard` | 주간 성적표 자동화 | 리스크 | 2026-10-15 | — | private 전용 | — | private 저장소 전용. |
| P2 | `japan` | 일본 시장 연동 (닛케이·TOPIX·JGB10Y·엔 캐리·일본 피어 상관) | 매크로 | 2026-10-15 | — | `screener/japan.py`<br>`reports/japan.json`<br>`screener/macroview.py`<br>`screener/committee.py`<br>`screener/main.py` | — | 보드 밖에서 시작된 작업 — 운영 누나가 잠금(locks.json) 보고 사후 등록. 우선순위는 팀장 확인 필요. |
| P2 | `lab-r2` | 전략 연구소 2라운드 | 퀀트 | 2026-10-15 | — | `screener/lab.py`<br>`reports/lab.json`<br>`apps-script/Index.html` | — | 1라운드: 사전 등록 가설 7개 · 공통 하네스 · Bonferroni 관문. |
| P2 | `life-health-panel` | LIFE 탭 건강 패널 (체성분 차트·운동·e1RM) | 헬스 | 2026-10-15 | — | `apps-script/Index.html` | — | 데이터는 pb-private에서 런타임 토큰으로만 읽음 — 공개 파일에 수치 없음. |
| P2 | `phone-input` | 폰 빠른 입력 | LIFE | 2026-10-15 | — | private 전용 | — | private 저장소 전용. |
| P2 | `playbook-verify` | 실행 대본 신호 검증 | 백테스트 | 2026-10-15 | — | `reports/studies/playbook_signals.*` | — | 운용회의 실행 대본(신호·시간대별 단계)의 신호가 과거에 실제로 통했는지. |

## 충돌 주의 (진행 중 작업이 같은 파일을 고침)

- `apps-script/Index.html` ← `view-registry`, `drivers-audit` — 편집 전 `ops/locks.json` 잠금 필수

