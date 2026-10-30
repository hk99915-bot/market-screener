# 예약 일원화 표 — 결정 C (리팩토링 2단계, 2026-10-18)

작성 2026-10-17 · 운영 데스크 · 근거 docs/refactor_plan_2026-10-18.md §3 결정 C · 검사 `tests/test_schedule_single.py` · 표 재생성 `python scripts/slot_guard.py --table`

## 0. 오너 붙여넣기 체크리스트 (1회, 5분)
1. GitHub 에서 `apps-script/Scheduler.gs` 를 열어 전체 복사 (Raw 버튼).
2. script.google.com → 기존 예약기 프로젝트 → 코드 전체 선택 → 붙여넣기로 교체 → 저장. 스크립트 속성 `GH_TOKEN`·트리거는 그대로 둔다(install 다시 안 함).
3. 함수 `tickTest` 실행 → 로그 첫 줄이 `예약기 버전 2026-10-21 이중화 · 창 10분` 인지 확인 (10/21: install 은 tick 트리거만 갈아끼움 — tgPoll 은 그대로. TelegramHook.gs 도 같이 붙여넣고 `tgInstallPolling` 1회 → tgPoll 5분).
4. 다음 슬롯 뒤 Actions 탭에서 실행 이름이 `briefing [premarket_kr] commit=true` 형태인지 확인.
5. 시각: 슬롯 창(예정 시각~+10분) 밖에서 붙여넣기. 일요일이면 02:00–02:10, 03:30–03:40 만 피하면 된다(그날 GAS 슬롯은 이 둘뿐).
- 붙여넣기 전에도 안전: 구버전 GAS 는 commit 입력을 안 보내므로 워크플로가 `commit=auto` 로 받는다 → 슬롯 시각(+25분) 안이면 커밋. 그래서 월요일 08:50 장전 알림은 붙여넣기 여부와 무관하게 돈다.
- 토큰 점검: fine-grained 토큰은 만료일이 있다. 만료되면 GAS 가 멈추고 cron 대기 실행이 +12분 늦게 대신 돈다(알림이 12분 늦어지는 것으로 알 수 있음). [확인 필요: 토큰 만료일, 오너, 10/18 붙여넣기 때]

## 1. 원칙
- **산출물 하나 = 실행 주체 하나.** 슬롯 = (워크플로 · 작업 키 · KST 시각 · 요일). 작업 키 = briefing 의 mode, screener 의 market, deriv_hist 의 task, backfill 의 market.
- **GAS 슬롯** (Scheduler.gs SCHEDULE 에 있는 슬롯): GAS 가 주 실행 주체. 같은 시각 GitHub cron 은 **대기(fallback)** — `scripts/slot_guard.py` 가 예정 +12분까지 기다린 뒤 같은 키의 dispatch 가 있으면 건너뛰고, 없으면 대신 실행한다. GAS 는 예정 +10분 안에만 보내므로(WINDOW_MIN 20→10) 둘이 겹칠 수 없다.
- **수동 dispatch 는 기본 읽기 전용.** 입력 `commit`: `true` 커밋 · `false` 읽기 전용 · `auto`(기본, GAS 대상 워크플로 6개) = GAS 슬롯 시각 +25분 안이면 커밋, 밖이면 읽기 전용. 나머지 cron 워크플로 7개는 기본 `false`. 읽기 전용이어도 텔레그램·구글시트 같은 외부 부작용은 그대로다(git 커밋만 막음).
  - 신선도 ⛔ 알림의 복구 명령(`ops/freshness.json` `fix`)은 전부 `-f commit=true` 를 붙인다 — 알림대로 실행하면 저장까지 된다(감사 M2 10/17, `tests/test_freshness_fix.py` 가 commit 입력이 있는 워크플로마다 강제). 역행은 `guard.write_json` asof 가드가 따로 막는다.
- **API 실패 = 실행(fail-open)** + `::warning`. 알림 누락이 중복보다 나쁘다고 판단 [가정: 오너 선호, 뒤집힐 조건 — 중복 텔레그램 불만이 누락보다 크면 fail-closed 로].
- **장중 루프 취소·재시작 절차** (감사 D5, req-ops-6cec6000 · 신설 dd197829 · **10/24 겸이 확인(감사 M1 종결)** — 결재 req-ops-6bc87511, 감사 req-ops-c6da52a2): live.yml 등 장중 루프 run 을 수동으로 취소·재시작할 땐 ① PB 승인 ② 보드 작업 노트에 사유 1줄 + 취소한 run id ③ 가능하면 장 마감 뒤. 긴급(데이터 오염·중복 알림 폭주)으로 장중에 하면 사후 1시간 안에 ①② 기록.
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
| 00:07 | live.yml | 화수목금토 | cron 7 14-20 * * 1-5 | — |
| 00:07 | ops.yml | 월화수목금토일 | cron 7 15 * * * | — |
| 01:07 | live.yml | 화수목금토 | cron 7 14-20 * * 1-5 | — |
| 02:00 | backfill.yml [ALL] | 월화수목금토일 | GAS(주) + cron 0 17 * * *(대기) | — |
| 02:07 | live.yml | 화수목금토 | cron 7 14-20 * * 1-5 | — |
| 03:07 | live.yml | 화수목금토 | cron 7 14-20 * * 1-5 | — |
| 03:30 | fin.yml | 월화수목금토일 | GAS(주) + cron 30 18 * * *(대기) | — |
| 03:52 | briefing.yml [intraday_us] | 화수목금토 | GAS(주) + cron 52 18 * * 1-5(대기) | — |
| 04:07 | live.yml | 화수목금토 | cron 7 14-20 * * 1-5 | — |
| 05:00 | hist.yml | 일 | cron 0 20 * * 6 | — |
| 05:07 | live.yml | 화수목금토 | cron 7 14-20 * * 1-5 | — |
| 06:52 | briefing.yml [screen_us] | 화수목금토 | GAS(주) + cron 52 21 * * 1-5(대기) | — |
| 07:10 | briefing.yml [valuation] | 화수목금토 | cron 10 22 * * 1-5 | — |
| 07:10 | study_daily.yml | 월화수목금 | cron 10 22 * * 0-4 | — |
| 07:37 | us_accum.yml | 화수목금토 | cron 37 22 * * 1-5 | — |
| 08:20 | health.yml | 월화수목금토일 | cron 20 23 * * * | — |
| 08:30 | scorecard.yml | 일 | cron 30 23 * * 6 | — |
| 08:40 | live.yml | 월화수목금 | GAS(주) + cron 40 23 * * 0-4(대기) | — |
| 08:50 | briefing.yml [premarket_kr] | 월화수목금 | GAS(주) + cron 50 23 * * 0-4(대기) | — |
| 08:52 | briefing.yml [detail_us_retry] | 화수목금토 | cron 52 23 * * 1-5 | — |
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
| 20:17 | data_store.yml | 금 | cron 17 11 * * 5 | — |
| 20:52 | briefing.yml [premarket_us] | 월화수목금 | GAS(주) + cron 52 11 * * 1-5(대기) | — |
| 21:52 | briefing.yml [premarket_us] | 월화수목금 | GAS(주) + cron 52 12 * * 1-5(대기) | — |
| 22:00 | health.yml | 일 | cron 0 13 * * 0 | — |
| 22:20 | live.yml | 월화수목금 | cron 20 13 * * 1-5 | — |
| 22:52 | briefing.yml [intraday_us] | 월화수목금 | GAS(주) + cron 52 13 * * 1-5(대기) | — |
| 23:00 | lab.yml | 일 | cron 0 14 * * 0 | — |
| 23:07 | live.yml | 월화수목금 | cron 7 14-20 * * 1-5 | — |
| 23:20 | live.yml | 월화수목금 | GAS(주) + cron 20 14 * * 1-5(대기) | — |
| 23:47 | ops.yml | 월화수목금토일 | cron 47 14 * * * | — |

- live 매시 백업(`7 0-6`·`7 14-20`)은 '루프 재개' 트리거다: concurrency `live` 로 동시 1개, 루프가 끝난 뒤 대기열에서 깨어난 실행은 장 시간 밖이면 아무것도 안 한다(전: 1회 시세 커밋).
- 수동 전용(요청형, dispatch 가 유일한 주체): `flowq.yml`(종목 수급 조회), `pb_call.yml`(PB 예약 세션 → 판단 기록). 이슈 트리거: `pick.yml`·`study.yml`. push 트리거: `tests.yml`. 매시: `team.yml`(17분, 10/21 push 트리거→매시).

## 4. 산출물 × 생산자
| 산출물 | 주 실행 주체 (KST) | 다른 생산자 | 판정 |
|---|---|---|---|
| reports/detail/US/* · peers_US · latest_US.md | briefing screen_us 06:52 화~토 (GAS) | 수동 detail_us·screen_us | 수동 = 읽기 전용 기본 → 단일 |
| reports/detail/KR/* · peers_KR · latest_KR.md · watchlist_KR | screener KR 16:20 평일 (GAS) | 수동 detail_kr · screener 수동 | 수동 = 읽기 전용 기본 → 단일 |
| reports/valuation.json·.md | briefing valuation 07:10 화~토 (cron 단독) | screener KR 16:20 (KR 종가분) | 시장별 종가 순서상 2슬롯 — 의도. 역행은 개발 asof 가드(screener/guard.py)가 차단 |
| reports/research_synthesis.json | fin 03:30 매일 (research_views 수집 직후 1줄) | 수동 `python -m screener.research_synthesis`(로컬) | 단일 — 애널 research-synthesis |
| reports/public_reports.json · reports/views/jiang.json | fin 03:30 매일 (research_views 다음 · research_synthesis 앞 1줄) | 수동 `python -m screener.public_reports --probe`(저장 안 함) | 단일 — 애널 public-reports |
| committee.json · committee_hist · dashboard* · daily_brief · macro_view · japan · bonds · derivs | briefing 08:50·10:30·11:35·13:30·14:15·15:45·19:10 (GAS) | — | 시각별 갱신, 슬롯마다 단일 |
| committee_us.json | briefing 20:52·21:52·22:52·03:52 (GAS) | — | 단일 |
| reports/live.json · events.json | live 루프 08:40·23:20 (GAS, 11/02~ 겨울. 여름 22:20) + 매시 재개 | 수동 live(읽기 전용 기본) | 동시 1개(concurrency) |
| 장중 이벤트 텔레그램(touch·지수 −4/−5%·서킷/사이드카·보유 손절선/−5%·미장 SPX/NDX −3%·VIX +25%) · reports/event_state.json | **live 루프** 안 백그라운드 `screener.event_watch` 약 60초마다 (2026-10-17 신설) | — (15:05 crash_check 종가 판단 메시지·14:25/16:20 규정 알림은 별도 산출물로 유지) | 단일. touch: 이벤트 감시는 규정 알림이 이미 보낸 코드면 건너뜀(평생 1회). 반대 방향(규정 알림이 이벤트 감시 기록을 보는 것)은 alerts.py 잠금 해제 뒤 — 보드 event-watch, 서킷·사이드카는 뉴스 감지(events.check)와 소리 1회 공유 |
| reports/decisions.json | live 14:50–15:15 duel · briefing premarket_us duel · screener 규칙 판정 | pick.yml(이슈) · pb_call(PB 예약 세션 14:42) | 필드 병합 방식(각자 자기 칸만) — 슬롯 이중 아님. 1.5단계에서 재점검 |
| data/deriv/daily.csv · deriv_hist_status · studies/gamma_regime | deriv_hist 16:40 평일 (GAS) | 수동 backfill/probe (commit=true 필요) | 단일 |
| data/fin · universe/sec_* · portfolios · momentum · analysts | fin 03:30 매일 (GAS) | — | 단일 |
| data/hist/kr_YYYY (백필) | backfill 02:00 매일 (GAS) | — | 단일 |
| data/hist/*_daily.parquet (시세 창고) | hist 일 05:00 (cron) | — | 단일 |
| reports/freshness.json | briefing 실행 끝마다 | health 08:20·20:10 | 멱등 재계산(현재 상태 스냅샷) — 덮어써도 역행 없음 |
| health.json | health 일 22:00 | — | 단일 |
| lab.json · scorecard_week · study_daily.json | lab 일 23:00 · scorecard 일 08:30 · study_daily 평일 07:10 | — | 단일 |
| changelog · reports/ops · ops/BOARD.md | ops 23:47 | — | 단일 |
| ops/team.json | ops 23:47·00:07 + team(매시 17분) — auto 블록 | PM 22:30 Claude 예약 — runs 블록 | 블록 분리 |
| reports/english/* | Claude 예약 '오늘의 영어' 평일 07:18 | — | 단일(세션이 직접 커밋) |
| reports/audit/<날짜>.md (정기 감사) | Claude 예약 '정기 감사' 수·토 07:53 새 세션 (trig_01Lc79ufM6xsA2RHqFD4cJsg, 10/24 겸이 승인, 첫 실행 10/28) | 수시 감사(요청 시) | 단일(세션이 직접 커밋) |
| (저장소 밖) ~/toss_md_data/* — 토스 시세 파일럿(지수 1분·투자자별 매매대금·USDKRW·KR/US 달력) | **겸이 노트북(파일럿, 공개 산출물 없음)** — Windows 작업 스케줄러 평일 09:00–15:50 10분마다 · 매일 08:30·18:30 | — (토큰 재발급 시 이전 토큰 무효 → 다른 주체 금지, GitHub Actions·러너 연결 금지) | 단일. 보드 `toss-md-pilot`, 가이드 docs/toss_md_laptop_setup.md |

Claude 원격 예약 작업(10/17 list_triggers 기준): 오늘의 영어 07:18 · PB 진입·매도 14:42(→pb_call) · PB 미장 21:52(꺼짐) · 기록 12:50/16:00/22:30(pb-private·team.json runs) · 데스크 라운드 평일 21:10(docs) · ISA 리마인드 10/19 10:00(1회). 위 GitHub 산출물과 겹치는 슬롯 없음.

## 4-1. 장중 이벤트 알림 (오너 10/17 15시대 "사건이 터지면 바로 텔레로 오게, 특정 시간이 아니라")
- 실행 주체 = live 루프 하나(결정 C). `.github/workflows/live.yml` 루프 단계가 시작할 때 `python -m screener.event_watch` 를 60초 주기 백그라운드로 띄운다. 국장 평일 09:00–15:31 KST·미장 09:30–16:00 뉴욕 밖이면 시세를 받지 않고 끝난다.
- 소리: `alerts.silent(키)` 하나로만 결정 — touch·halt 만 RING_KINDS(소리), 나머지 무음. **현재는 `defs.TELEGRAM_ALL_SILENT=True`(오너 10/17 "전체 무음")라 전부 무음**, 표는 되돌릴 때를 위해 보존.
- 중복: 같은 사건은 하루 1회(touch 는 평생 1회), 상태 `reports/event_state.json`(금액 0, 보유 종목 코드는 HMAC 해시). 작업 중엔 `/tmp/ev` 사본을 쓰고 5분 커밋 때 같이 올린다. 전송 ≤ 1통/분, 같은 분의 사건은 1통으로 묶음.
- 신선도: 시세 시각(네이버 `localTradedAt`, 야후 마지막 1분봉)이 KR 180초·US 300초보다 오래면 알리지 않음.
- 지연(측정 근거: 10/15–10/17 live.yml 실행 기록, `gh run list`):
  | 경우 | 사건 → 텔레그램 |
  |---|---|
  | 정상(루프 살아 있음) | 감시 주기 60초 + 실행 ~5–10초 → **≤ 약 70초**, 직전 1분 안에 보낸 게 있으면 +≤60초 → ≤ 약 2분 |
  | 서킷·사이드카 프록시 | 조건 진입 뒤 '1분 지속' 확인 2표본 → 조건 진입 +60~130초 (거래소 실제 발동은 +60초) |
  | 340분 상한 교대(국장 08:40 시작 → 약 14:20, 미장 22:20 → 약 04:00) | 대기열에 매시 백업 실행이 있으면 바로 이어받음 → 공백 약 1–3분(작업 준비 시간). 10/15 실측: 09:46 시작 → 15:33 종료 → 대기 실행 15:33 시작 |
  | 루프가 죽고 대기 실행이 없음 | 다음 매시 :07 cron. GitHub cron 지연 실측 최대 **약 3–5시간**(10/15 15:07 예약 → 20:19 실행, 10/16 04:07 → 07:05) → 최악은 그 장 남은 시간 전부 공백 |
  | GAS 08:40 시작 누락 | cron 08:40 대기(+12분) → 08:52 시작, 09:00 개장 전이라 공백 없음. cron 도 늦으면 첫 매시 백업까지(10/15 실측 09:46 시작 → 09:00–09:46 공백) |
- 남은 위험: (a) 위 '루프가 죽고 대기 실행 없음' — 개선안 = 루프 끝에 자기 재개 dispatch(`actions: write` 권한 필요, 10/17 개발 세션에선 권한 확대가 승인되지 않아 보류) 또는 GAS 슬롯 14:20·04:00 에 live 재개 추가(Scheduler.gs 붙여넣기 필요). 보드 `live-resume-gap`. (b) ~~11/02 겨울 시간 창~~ → 10/30 반영(아래 §4-2). 3월 둘째 일요일 여름 복귀 때 반대로 되돌려야 함 — 보드 `live-us-dst-march`. (c) 60초 폴링은 1분 안에 찍고 되돌아간 꼬리(touch)를 놓칠 수 있음 — 종목 basic 응답에 장중 저가가 없으면 현재가로 판정.
- 롤백: live.yml 의 이벤트 감시 3줄과 커밋 목록의 `reports/event_state.json` 제거(또는 이 커밋 revert). 15:05·14:25·16:20 슬롯 알림은 그대로라 롤백해도 기존 알림은 산다.

## 5. 바뀐 것 · 영향 · 롤백
- 코드: `scripts/slot_guard.py`(가드·파서·분석) · 워크플로 14개(us_accum 포함, `run-name`, `commit` 입력, 저장 단계 조건, GAS 6개는 가드 단계 + `actions: read`) · `apps-script/Scheduler.gs`(WINDOW_MIN 10, 모든 슬롯 `commit: 'true'`, 버전 표시) · `tests.yml`(pyyaml 설치, 워크플로·Scheduler.gs 변경 때도 테스트).
- 영향: GitHub cron 이 정시에 울린 GAS 슬롯은 러너가 최대 12분 대기(분 단위 과금 없음, 공개 저장소). GAS 가 죽은 날엔 해당 슬롯이 최대 12분 늦게 실행. 수동 실행 후 결과가 안 보이면 `commit=true` 로 다시.
- 롤백: 이 커밋 revert. **단, 새 Scheduler.gs 를 이미 붙여넣었다면 구버전 Scheduler.gs 도 다시 붙여넣을 것** — 새 GAS 는 `commit` 입력을 보내는데, 되돌린 워크플로엔 그 입력이 없어 GitHub 가 422 로 전부 거부한다.
- 남은 위험: (a) 구버전 GAS(창 20분)가 첫 두 틱을 놓쳐 +12분 뒤 보내면 그 슬롯만 이중 가능 — 붙여넣기로 해소. (b) live 22:20 대기 cron 이 루프 종료(약 04:00) 뒤 깨어나면 재개 대신 건너뜀 — 매시 백업(04:07)이 재개. (c) 새 워크플로는 cron+dispatch+커밋이면 `commit` 입력이 있어야 테스트 통과. us_accum.yml 은 이 커밋에서 반영, **accum.yml 은 퀀트 잠금 중이라 미반영**(테스트 PENDING, 보드 `schedule-single-accum` P2 10/20) — 그때까지 accum 수동 실행은 기본값으로 커밋됨.

VOC: GAS 붙여넣기 전까지 '창 20분' 잔여 위험이 남는다 — 10/18 체크리스트 0번을 결재(14:00) 전에 처리 요청.
요청→개발: 1단계 asof 가드와 함께 `commit=auto` 의 슬롯 판정(`slot_guard.gas_slot_near`)을 검토 — 붙여넣기 확인 뒤 auto 를 false 로 좁힐지.
현재 상태: 이중 슬롯 0·수동 덮어쓰기 0(테스트로 고정) / 오너 GAS 붙여넣기 대기 / 롤백은 revert + 구 GAS 재붙여넣기.

## 4-2. 미 서머타임 종료(11/01) 대응 — 2026-10-30 개발 (req-dev-cbd568fc)
11/02(월)부터 미장 = 09:30–16:00 ET = **23:30–06:00 KST**(여름 22:30–05:00). GitHub cron 은 UTC 고정이라 서머타임을 모른다 → 미장 시각에 묶인 cron 은 계절마다 손으로 바꾼다. 판정 코드는 tz(America/New_York) 로 한다.
| 항목 | 전(여름) | 후(겨울, 11/02~) | 근거 |
|---|---|---|---|
| live.yml 미장 루프 시작 cron | `20 13 * * 1-5` = 월~금 13:20 UTC = 22:20 KST | **`20 13` + `20 14` 둘 다 상시**(22:20·23:20 KST). 겨울엔 22:20 실행이 08:20 EST 라 in_window 가 바로 끝내고(약 1분), 여름엔 23:20 실행이 도는 루프 뒤 대기열로 이어받기 | 개장 09:30 ET = 14:30 UTC(EST −5) · 계절마다 손으로 안 바꿈(아래 10/30 21시 보강) |
| live.yml 미장 매시 백업 | `7 14-19` = 월~금 14:07–19:07 UTC = 23:07–04:07 KST(화~토) | `7 14-20` = 14:07–20:07 UTC = 23:07–**05:07** KST(화~토) | 루프 340분 상한: 23:20 시작 → 약 05:00 종료, 마감 06:00 까지 재개 필요 |
| live.yml `in_window()` 미장 | KST 22:15–05:15 하드코딩 | **09:15–16:15 ET**(`TZ=America/New_York`) = 겨울 23:15–06:15 · 여름 22:15–05:15 | 서머타임 자동 |
| Scheduler.gs 미장 루프 슬롯 | 22:20 | **23:20**(배포 필요 — 아래) | 위 cron 과 같은 시각이라야 slot_guard 가 같은 슬롯으로 봄 |
| `tradecal.us_open_kst()` (신설) | idea_tracking·practice_book 이 KST "22:30" 하드코딩, alphabook `hour < 22` | 날짜별 ET→KST 계산(여름 22:30·겨울 23:30, alphabook 은 개장 30분 전) | 하드코딩 제거 |
- 이미 tz 로 판정(변경 없음): `tradecal`(ET 세션·expected_session)·`heatmap.py`·`duel.us_open_kst`(마감 판정)·`event_watch`(뉴욕 09:30–16:00)·tab_home 마감 계산·`heatmap.yml`(13–21 UTC 가 양 계절을 덮음).
- 보류(PB 확인 필요, 바꾸지 않음): briefing.yml 미장 슬롯 — premarket_us 20:52·21:52, intraday_us 22:52(**겨울엔 개장 전**), intraday_us 03:52. 모드가 cron 문자열로 정해져 ET 기준 동일 시각(+1h)으로 옮기려면 모드 case 문 재배선이 필요. 06:52 screen_us·07:10 valuation·07:37 us_accum·08:52 재시도는 마감(06:00) 뒤라 그대로 유효(마감 +52분으로 짧아짐).
- 배포 필요(개발이 못 함): `apps-script/Scheduler.gs` 붙여넣기(§0 체크리스트, 로그 첫 줄 버전 `2026-10-30 겨울시간 · 이중화`). 붙여넣기 전엔 구 GAS 가 22:20(개장 전)에 live 를 깨우지만 in_window 가 곧 끝내고, 23:20 cron 이 대신 시작한다(+12분 대기).
- **10/30 21시 보강(개발 주간 라운드)**: 위 첫 변경은 `20 13` 을 지워서, 10/30(금) 밤 미장(아직 EDT, 22:30 개장)의 22:20 시작이 구버전 GAS 하나에만 걸려 있었다(오너가 오늘 밤 새 GAS 를 붙여넣거나 GAS 가 빠지면 23:07 백업까지 37분 공백). 날짜 분기 대신 **두 계절 시작 cron 상시 + in_window(ET) 가 고름** 으로 바꿈 — 날짜 조건 없이 오늘 밤·11/02 뒤·3월 뒤 모두 맞고, 비용은 평일 1분짜리 빈 실행 1회. 오늘 밤 22:20 은 cron(주)·구 GAS 가 같이 깨우지만 concurrency `live` 로 하나만 루프, 다른 하나는 대기열 이어받기.
- 3월 복귀(2027-03-14 일요일 서머타임 시작): live cron 은 **손댈 필요 없음**(위 보강). GAS 슬롯 23:20 은 여름에 cron 22:20 루프 뒤 대기열이 되어 무해 — 되돌릴지는 선택. in_window 도 그대로.
