# 예약 일원화 표 — 결정 C (리팩토링 2단계, 2026-10-18)

작성 2026-10-17 · 운영 데스크 · 근거 docs/refactor_plan_2026-10-18.md §3 결정 C · 검사 `tests/test_schedule_single.py` · 표 재생성 `python scripts/slot_guard.py --table`

## 0. 오너 붙여넣기 체크리스트 (1회, 5분)
1. GitHub 에서 `apps-script/Scheduler.gs` 를 열어 전체 복사 (Raw 버튼).
2. script.google.com → 기존 예약기 프로젝트 → 코드 전체 선택 → 붙여넣기로 교체 → 저장. 스크립트 속성 `GH_TOKEN`·트리거는 그대로 둔다(install 다시 안 함).
3. 함수 `tickTest` 실행 → 로그 첫 줄이 `예약기 버전 2026-10-18 결정C · 창 10분` 인지 확인.
4. 다음 슬롯 뒤 Actions 탭에서 실행 이름이 `briefing [premarket_kr] commit=true` 형태인지 확인.
5. 시각: 슬롯 창(예정 시각~+10분) 밖에서 붙여넣기. 일요일이면 02:00–02:10, 03:30–03:40 만 피하면 된다(그날 GAS 슬롯은 이 둘뿐).
- 붙여넣기 전에도 안전: 구버전 GAS 는 commit 입력을 안 보내므로 워크플로가 `commit=auto` 로 받는다 → 슬롯 시각(+25분) 안이면 커밋. 그래서 월요일 08:50 장전 알림은 붙여넣기 여부와 무관하게 돈다.
- 토큰 점검: fine-grained 토큰은 만료일이 있다. 만료되면 GAS 가 멈추고 cron 대기 실행이 +12분 늦게 대신 돈다(알림이 12분 늦어지는 것으로 알 수 있음). [확인 필요: 토큰 만료일, 오너, 10/18 붙여넣기 때]

## 1. 원칙
- **산출물 하나 = 실행 주체 하나.** 슬롯 = (워크플로 · 작업 키 · KST 시각 · 요일). 작업 키 = briefing 의 mode, screener 의 market, deriv_hist 의 task, backfill 의 market.
- **GAS 슬롯** (Scheduler.gs SCHEDULE 에 있는 슬롯): GAS 가 주 실행 주체. 같은 시각 GitHub cron 은 **대기(fallback)** — `scripts/slot_guard.py` 가 예정 +12분까지 기다린 뒤 같은 키의 dispatch 가 있으면 건너뛰고, 없으면 대신 실행한다. GAS 는 예정 +10분 안에만 보내므로(WINDOW_MIN 20→10) 둘이 겹칠 수 없다.
- **수동 dispatch 는 기본 읽기 전용.** 입력 `commit`: `true` 커밋 · `false` 읽기 전용 · `auto`(기본, GAS 대상 워크플로 6개) = GAS 슬롯 시각 +25분 안이면 커밋, 밖이면 읽기 전용. 나머지 cron 워크플로 7개는 기본 `false`. 읽기 전용이어도 텔레그램·구글시트 같은 외부 부작용은 그대로다(git 커밋만 막음).
- **API 실패 = 실행(fail-open)** + `::warning`. 알림 누락이 중복보다 나쁘다고 판단 [가정: 오너 선호, 뒤집힐 조건 — 중복 텔레그램 불만이 누락보다 크면 fail-closed 로].
- 정의: "이중 실행 슬롯" = 한 슬롯에 가드 없이 실행할 수 있는 주체가 2개 이상. "수동 덮어쓰기 경로" = 자동 트리거가 있는 워크플로에서 수동 dispatch 가 기본값으로 커밋하는 경로.

## 2. 결과 (측정: `slot_guard.analyze()`, 이 커밋 전 HEAD fc5210d2 대비)
| 항목 | 전 | 후 |
|---|---|---|
| 이중 실행 슬롯 | **20** (GAS 20개 전부. briefing 15·screener 1 은 한쪽 방향 가드 — GAS 가 먼저면 cron 건너뜀, cron 이 먼저면 GAS 가 또 실행 / backfill·fin·deriv_hist·live×2 는 가드 없음) | **0** |
| 수동 덮어쓰기 경로 | **13** 워크플로 (10/17 detail_us 역행의 직접 원인) | **0** (+ 10/17 새로 생긴 accum.yml 1개는 퀀트 잠금 — 보드 `schedule-single-accum`) |
| 월 08:50 장전(premarket_kr) 실행 주체 | GAS + cron (한쪽 가드) | GAS 1 + cron 대기 |

## 3. 슬롯 × 실행 주체 (자동 생성 — `python scripts/slot_guard.py --table`)
| KST | 워크플로 [키] | 요일 | 실행 주체 | 이중 |
|---|---|---|---|---|
| 00:07 | live.yml | 화수목금토 | cron 7 14-19 * * 1-5 | — |
| 00:07 | ops.yml | 월화수목금토일 | cron 7 15 * * * | — |
| 01:07 | live.yml | 화수목금토 | cron 7 14-19 * * 1-5 | — |
| 02:00 | backfill.yml [ALL] | 월화수목금토일 | GAS(주) + cron 0 17 * * *(대기) | — |
| 02:07 | live.yml | 화수목금토 | cron 7 14-19 * * 1-5 | — |
| 03:07 | live.yml | 화수목금토 | cron 7 14-19 * * 1-5 | — |
| 03:30 | fin.yml | 월화수목금토일 | GAS(주) + cron 30 18 * * *(대기) | — |
| 03:52 | briefing.yml [intraday_us] | 화수목금토 | GAS(주) + cron 52 18 * * 1-5(대기) | — |
| 04:07 | live.yml | 화수목금토 | cron 7 14-19 * * 1-5 | — |
| 05:00 | hist.yml | 일 | cron 0 20 * * 6 | — |
| 06:52 | briefing.yml [screen_us] | 화수목금토 | GAS(주) + cron 52 21 * * 1-5(대기) | — |
| 07:10 | briefing.yml [valuation] | 화수목금토 | cron 10 22 * * 1-5 | — |
| 07:10 | study_daily.yml | 월화수목금 | cron 10 22 * * 0-4 | — |
| 07:37 | us_accum.yml | 화수목금토 | cron 37 22 * * 1-5 | — |
| 08:20 | health.yml | 월화수목금토일 | cron 20 23 * * * | — |
| 08:30 | scorecard.yml | 일 | cron 30 23 * * 6 | — |
| 08:40 | live.yml | 월화수목금 | GAS(주) + cron 40 23 * * 0-4(대기) | — |
| 08:50 | briefing.yml [premarket_kr] | 월화수목금 | GAS(주) + cron 50 23 * * 0-4(대기) | — |
| 09:07 | live.yml | 월화수목금 | cron 7 0-6 * * 1-5 | — |
| 10:07 | live.yml | 월화수목금 | cron 7 0-6 * * 1-5 | — |
| 10:30 | briefing.yml [intraday_kr] | 월화수목금 | GAS(주) + cron 30 1 * * 1-5(대기) | — |
| 11:07 | live.yml | 월화수목금 | cron 7 0-6 * * 1-5 | — |
| 11:35 | briefing.yml [committee] | 월화수목금 | GAS(주) + cron 35 2 * * 1-5(대기) | — |
| 12:07 | live.yml | 월화수목금 | cron 7 0-6 * * 1-5 | — |
| 13:07 | live.yml | 월화수목금 | cron 7 0-6 * * 1-5 | — |
| 13:30 | briefing.yml [intraday_kr] | 월화수목금 | GAS(주) + cron 30 4 * * 1-5(대기) | — |
| 14:07 | live.yml | 월화수목금 | cron 7 0-6 * * 1-5 | — |
| 14:15 | briefing.yml [committee] | 월화수목금 | GAS(주) + cron 15 5 * * 1-5(대기) | — |
| 14:25 | briefing.yml [rebound] | 월화수목금 | GAS(주) + cron 25 5 * * 1-5(대기) | — |
| 15:05 | briefing.yml [crash_check] | 월화수목금 | GAS(주) + cron 5 6 * * 1-5(대기) | — |
| 15:07 | live.yml | 월화수목금 | cron 7 0-6 * * 1-5 | — |
| 15:45 | briefing.yml [close_kr] | 월화수목금 | GAS(주) + cron 45 6 * * 1-5(대기) | — |
| 16:20 | screener.yml [KR] | 월화수목금 | GAS(주) + cron 20 7 * * 1-5(대기) | — |
| 16:40 | deriv_hist.yml [run] | 월화수목금 | GAS(주) + cron 40 7 * * 1-5(대기) | — |
| 18:37 | accum.yml | 월화수목금 | cron 37 9 * * 1-5 | — |
| 19:10 | briefing.yml [reports] | 월화수목금 | GAS(주) + cron 10 10 * * 1-5(대기) | — |
| 20:10 | health.yml | 월화수목금토일 | cron 10 11 * * * | — |
| 20:52 | briefing.yml [premarket_us] | 월화수목금 | GAS(주) + cron 52 11 * * 1-5(대기) | — |
| 21:52 | briefing.yml [premarket_us] | 월화수목금 | GAS(주) + cron 52 12 * * 1-5(대기) | — |
| 22:00 | health.yml | 일 | cron 0 13 * * 0 | — |
| 22:20 | live.yml | 월화수목금 | GAS(주) + cron 20 13 * * 1-5(대기) | — |
| 22:52 | briefing.yml [intraday_us] | 월화수목금 | GAS(주) + cron 52 13 * * 1-5(대기) | — |
| 23:00 | lab.yml | 일 | cron 0 14 * * 0 | — |
| 23:07 | live.yml | 월화수목금 | cron 7 14-19 * * 1-5 | — |
| 23:47 | ops.yml | 월화수목금토일 | cron 47 14 * * * | — |

- live 매시 백업(`7 0-6`·`7 14-19`)은 '루프 재개' 트리거다: concurrency `live` 로 동시 1개, 루프가 끝난 뒤 대기열에서 깨어난 실행은 장 시간 밖이면 아무것도 안 한다(전: 1회 시세 커밋).
- 수동 전용(요청형, dispatch 가 유일한 주체): `flowq.yml`(종목 수급 조회), `pb_call.yml`(PB 예약 세션 → 판단 기록). 이슈 트리거: `pick.yml`·`study.yml`. push 트리거: `team.yml`·`tests.yml`.

## 4. 산출물 × 생산자
| 산출물 | 주 실행 주체 (KST) | 다른 생산자 | 판정 |
|---|---|---|---|
| reports/detail/US/* · peers_US · latest_US.md | briefing screen_us 06:52 화~토 (GAS) | 수동 detail_us·screen_us | 수동 = 읽기 전용 기본 → 단일 |
| reports/detail/KR/* · peers_KR · latest_KR.md · watchlist_KR | screener KR 16:20 평일 (GAS) | 수동 detail_kr · screener 수동 | 수동 = 읽기 전용 기본 → 단일 |
| reports/valuation.json·.md | briefing valuation 07:10 화~토 (cron 단독) | screener KR 16:20 (KR 종가분) | 시장별 종가 순서상 2슬롯 — 의도. 역행은 개발 asof 가드(screener/guard.py)가 차단 |
| committee.json · committee_hist · dashboard* · daily_brief · macro_view · japan · bonds · derivs | briefing 08:50·10:30·11:35·13:30·14:15·15:45·19:10 (GAS) | — | 시각별 갱신, 슬롯마다 단일 |
| committee_us.json | briefing 20:52·21:52·22:52·03:52 (GAS) | — | 단일 |
| reports/live.json · events.json | live 루프 08:40·22:20 (GAS) + 매시 재개 | 수동 live(읽기 전용 기본) | 동시 1개(concurrency) |
| reports/decisions.json | live 14:50–15:15 duel · briefing premarket_us duel · screener 규칙 판정 | pick.yml(이슈) · pb_call(PB 예약 세션 14:42) | 필드 병합 방식(각자 자기 칸만) — 슬롯 이중 아님. 1.5단계에서 재점검 |
| data/deriv/daily.csv · deriv_hist_status · studies/gamma_regime | deriv_hist 16:40 평일 (GAS) | 수동 backfill/probe (commit=true 필요) | 단일 |
| data/fin · universe/sec_* · portfolios · momentum · analysts | fin 03:30 매일 (GAS) | — | 단일 |
| data/hist/kr_YYYY (백필) | backfill 02:00 매일 (GAS) | — | 단일 |
| data/hist/*_daily.parquet (시세 창고) | hist 일 05:00 (cron) | — | 단일 |
| reports/freshness.json | briefing 실행 끝마다 | health 08:20·20:10 | 멱등 재계산(현재 상태 스냅샷) — 덮어써도 역행 없음 |
| health.json | health 일 22:00 | — | 단일 |
| lab.json · scorecard_week · study_daily.json | lab 일 23:00 · scorecard 일 08:30 · study_daily 평일 07:10 | — | 단일 |
| changelog · reports/ops · ops/BOARD.md | ops 23:47 | — | 단일 |
| ops/team.json | ops 23:47·00:07 + team(push) — auto 블록 | PM 22:30 Claude 예약 — runs 블록 | 블록 분리 |
| reports/english/* | Claude 예약 '오늘의 영어' 평일 07:18 | — | 단일(세션이 직접 커밋) |

Claude 원격 예약 작업(10/17 list_triggers 기준): 오늘의 영어 07:18 · PB 진입·매도 14:42(→pb_call) · PB 미장 21:52(꺼짐) · 기록 12:50/16:00/22:30(pb-private·team.json runs) · 데스크 라운드 평일 21:10(docs) · ISA 리마인드 10/19 10:00(1회). 위 GitHub 산출물과 겹치는 슬롯 없음.

## 5. 바뀐 것 · 영향 · 롤백
- 코드: `scripts/slot_guard.py`(가드·파서·분석) · 워크플로 14개(us_accum 포함, `run-name`, `commit` 입력, 저장 단계 조건, GAS 6개는 가드 단계 + `actions: read`) · `apps-script/Scheduler.gs`(WINDOW_MIN 10, 모든 슬롯 `commit: 'true'`, 버전 표시) · `tests.yml`(pyyaml 설치, 워크플로·Scheduler.gs 변경 때도 테스트).
- 영향: GitHub cron 이 정시에 울린 GAS 슬롯은 러너가 최대 12분 대기(분 단위 과금 없음, 공개 저장소). GAS 가 죽은 날엔 해당 슬롯이 최대 12분 늦게 실행. 수동 실행 후 결과가 안 보이면 `commit=true` 로 다시.
- 롤백: 이 커밋 revert. **단, 새 Scheduler.gs 를 이미 붙여넣었다면 구버전 Scheduler.gs 도 다시 붙여넣을 것** — 새 GAS 는 `commit` 입력을 보내는데, 되돌린 워크플로엔 그 입력이 없어 GitHub 가 422 로 전부 거부한다.
- 남은 위험: (a) 구버전 GAS(창 20분)가 첫 두 틱을 놓쳐 +12분 뒤 보내면 그 슬롯만 이중 가능 — 붙여넣기로 해소. (b) live 22:20 대기 cron 이 루프 종료(약 04:00) 뒤 깨어나면 재개 대신 건너뜀 — 매시 백업(04:07)이 재개. (c) 새 워크플로는 cron+dispatch+커밋이면 `commit` 입력이 있어야 테스트 통과. us_accum.yml 은 이 커밋에서 반영, **accum.yml 은 퀀트 잠금 중이라 미반영**(테스트 PENDING, 보드 `schedule-single-accum` P2 10/20) — 그때까지 accum 수동 실행은 기본값으로 커밋됨.

VOC: GAS 붙여넣기 전까지 '창 20분' 잔여 위험이 남는다 — 10/18 체크리스트 0번을 결재(14:00) 전에 처리 요청.
요청→개발: 1단계 asof 가드와 함께 `commit=auto` 의 슬롯 판정(`slot_guard.gas_slot_near`)을 검토 — 붙여넣기 확인 뒤 auto 를 false 로 좁힐지.
현재 상태: 이중 슬롯 0·수동 덮어쓰기 0(테스트로 고정) / 오너 GAS 붙여넣기 대기 / 롤백은 revert + 구 GAS 재붙여넣기.
