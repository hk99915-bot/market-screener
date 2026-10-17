# 감사·검증 라운드 — 리팩토링 단계 5 (2026-10-17 13:30 KST 이후 main 커밋 전수)

- 발행: 감사+검증 데스크 · 2026-10-17 15:20 KST · 무편집 원칙(규칙 #11 — 지적만, 남의 코드는 고치지 않음) · 등급 **검증전**(정적 읽기 + 로컬 재현, 실전 Actions 실행 아님) · 신뢰도 **중**
- 근거 문서: `docs/refactor_plan_2026-10-18.md` §4 단계 5, `docs/desk_kb/STANDARD.md`, `docs/desk_kb/LOOP.md`
- 범위: `git log --since="2026-10-17 13:30 +0900"` = 103건(에이전트 59 · 봇 44), 끝 커밋 `60a8eda4`. 접두 개발·데이터·백테스트·운영·퀀트·애널·pm·pb 전부. 잠금·보드만 바꾼 커밋 25건은 형식만 확인.
- 용어 한 줄: **GAS 슬롯** = Apps Script 예약기(`apps-script/Scheduler.gs`)가 주 실행 주체인 시각. **cron 대기** = 같은 시각 GitHub cron 이 +12분 기다렸다가 GAS 실행이 없을 때만 대신 도는 것(`scripts/slot_guard.py`). **RING_KINDS** = 소리 나는 알림 5종 표(`screener/alerts.py:30`).

## 1. 주장
**게이트 통과 — 치명 0 · 중 4 · 경 13 · 정보 1 · 해소 1.** 월 10/19 08:50 장전 알림은 정상 경로에서 **정확히 1회** 발송된다(예외 2개는 §2.3). 단 37eee5cd(오너 지시 "전체 무음")로 **모든 텔레그램이 무음** — 규정 [12] D-day(10/22)·손절 2일·신선도 ⛔ 도 소리가 나지 않는다. 오너 선행 조건 3건(§2.3) 중 Scheduler.gs 붙여넣기가 월 08:40 전 필수.

## 2. 근거
### 2.1 자동 검사 (10/17 15:15 KST, worktree = origin/main)
| 검사 | 결과 |
|---|---|
| pytest 전체 | **374 통과 / 0 실패** (이 문서 추가 후 `tests/test_peer_reviews.py` 양식 포함, 경고 7 = pandas 지원 중단 예고) |
| `scripts/check_functions.py` | 통과 (빌드 최신·잠금 충돌 없음·JSON 정상) |
| `scripts/board.py --check` | board OK |
| `scripts/check_rules_terms.py` | 6 files OK — defs.py 이전 전/후 상수 값 동일(diff 대조) |
| `scripts/slot_guard.py --table` | 이중 실행 슬롯 0 · 수동 덮어쓰기 경로 0 |
| `scripts/slop_audit.py` | 치명 0 · 중 6 · 경 48 · 정보 34 (오늘 커밋 해당 중 1 = 42954487 테스트 없음 → M4) |
| `scripts/ui_smoke.py home my kr deriv bond` | 5뷰 + 신선도 배지 2종 + US 상세 팝업 전부 OK |
| 개인정보(공개 저장소) | 에이전트 59건 diff·새 문서·보고서: 금액·보유 수량·연봉·계좌·의료·토큰·개인 이메일 **0건**(비율만). `hk99915-bot` 은 저장소 소유자 이름 |
| 커밋 신원 | 에이전트 59건 모두 `Claude <noreply@anthropic.com>`(작성자=커미터), 봇 44건 `screener-bot` |

### 2.2 지적 (치명 → 중 → 경)
| 등급 | 커밋 | 파일:줄 | 실패 시나리오 | 담당 |
|---|---|---|---|---|
| 정보 I1 | 37eee5cd (pb 직접) | `screener/defs.py` `TELEGRAM_ALL_SILENT=True` · `screener/report.py:238` | 오너 지시대로 전부 무음. 결과: RING_KINDS 5종이 현재 효력 0 — D-day·stop2·touch·서킷·신선도 ⛔ 모두 무음. alerts.py 머리말·`docs/schedule_table.md` 는 '5종 소리' 그대로(문서 불일치). 오너가 이 결과를 알고 있는지 1줄 확인 권고 | PB |
| 중 M1 | 5c8d9ac1 (결재 #9) | `screener/pb.py:567` · `:512` · `:522` · `screener/alerts.py:30` | PB 아침 점검을 무음 고정. 그 안의 ⛔ 2종 — **보유 종목 기준가(MY_RULES price) 2일 연속 이탈 "실행"**, **손실 한도 도달 "메모리 절반 축소 실행"** — 은 RING_KINDS 어디에도 없다(`stop2` = 코스피 규정 [12] 선만). 변경 전엔 ⛔ 포함 시 소리. 지금은 I1 로 잠복, 전체 무음을 끄는 순간 발현 | 개발 (+오너 해석) |
| 중 M2 | a0080e69 (결정 C) × 42c4a0d6 | `ops/freshness.json` `fix` 21항목 · `screener/freshness.py:168` · `scripts/slot_guard.py:121` | ⛔ 신선도 알림의 복구 명령(`gh workflow run briefing.yml -f mode=…`)이 결정 C 뒤로 `commit=auto` → 슬롯 밖이면 **읽기 전용**. 오너가 알림대로 실행해도 산출물이 저장되지 않고 다음 점검에서 같은 항목이 또 늦음 | 개발 (freshness 소유) · 운영 |
| 중 M3 | 42c4a0d6 | `screener/main.py:291` · `ops/freshness.json` macro_series · `screener/alerts.py:209` | macro_series `asof` = 전 시리즈 최대 날짜 → 24시간 시리즈(BTC·USDKRW)가 끌어올림(현재 파일 asof **2026-10-17 토**, KOSPI 끝 행 10/16). KOSPI 갱신이 실패해도 신선도 계약은 '정상'. 16:20 손절선 점검은 KOSPI 끝 행 ≠ 오늘이면 `log.info` 로 건너뜀 → 규정 [12] 점검이 **조용히** 빠지고 감시도 못 잡음 | 개발 · 데이터 |
| 중 M4 | 42954487 (pb 직접) | `screener/committee.py:623` · `:1163` · `screener/main.py:318` | 운용회의 채점·아이디어 채점·KR 상세 재생성이 조정가로 바뀜 → 과거 성적이 소급 변동. 회귀 테스트 0건, 커밋 메시지에 영향·롤백 줄 없음(STANDARD §3). 개발 소유 파일을 PB가 직접 수정 | PB → 개발 검수 |
| 경 L1 | a0080e69 | `apps-script/Scheduler.gs`(붙여넣기 전 구버전 창 20분) | 구 GAS 가 첫 3틱(08:50·55·09:00)을 놓쳐 09:02 뒤에 보내면 cron 대기(09:02 판정)와 겹쳐 **장전 브리핑 2통**. 붙여넣기(창 10분)로 해소 — 문서 남은 위험 (a)와 동일 | 사용자(오너) |
| 경 L2 | a0080e69 | `.github/workflows/live.yml:28` | live 는 cron·GAS 가 같은 concurrency `live`. cron 08:40 이 먼저 뜨면 12분 대기 동안 GAS 실행이 대기열에 묶임 → 국장 루프 시작 최대 08:53(개장 전) | 운영 |
| 경 L3 | a0080e69 | `scripts/slot_guard.py` `primary_ran` | GAS 실행이 생성 뒤 실패(설치 오류 등)해도 cron 은 '실행됨'으로 보고 건너뜀 → 그 슬롯 0통. 변경 전 curl 가드와 같은 한계 | 운영 |
| 경 L4 | 3a89134b (결재 #3) | `screener/pb.py:471` · `:378` · `screener/regime_tag.py:23` | ① 레짐 상한이 MY_RULES `SEMI_CAP` 을 덮음 → 보드 `my-rules-secret`(SEMI_CAP 0.40 설정)이 효과 없음, 진실 원천 2개(D3) ② KOSPI 없으면 하락장 가정 → 상한 35%·VaR 1.5% → '반도체 신규 매수 금지' 표시(무음·표시만) ③ 종가 200개 미만이면 200일선 조건 없이 '상승장' 가능 | 개발 |
| 경 L5 | bb9437b3 | `screener/prices.py:58` | `adjust()` 가 `join(how="left")` 행 순서에 의존(누적곱 `.over`, momentum 위치 정렬). polars 2.0 문서: `maintain_order` 기본 'none' = 보장 없음. 오늘 전 기간 KR 일봉 재현에선 순서 유지 — 버전 올리면 조정 배수가 섞일 수 있음 | 데이터 |
| 경 L6 | 42c4a0d6 | `screener/valuation_daily.py:478` | valuation `asof` = 생성일 → 역행 가드·신선도가 실제 가격일을 보지 않음(STANDARD §1) | 개발 |
| 경 L7 | 97b1fa01 | `scripts/data_branch.py:101` | `push --force`(lease 없음) + fetch 실패 시 원격 없음으로 간주해 검사 생략. 지금은 pages-build 단독 작성이라 안전, 2단계 전 `--force-with-lease=data:<sha>` 필요 | 개발 |
| 경 L8 | 7b29358d | `screener/us_accum.py:39` | 입력이 main 의 `reports/detail/US`. 단계 4에서 US 상세를 main 에서 빼면 빈 스캔 | 퀀트 · 개발 |
| 경 L9 | 24ca45a6·84f19082·928184b8 | `.github/workflows/accum.yml` 저장 단계 | `data/flows/kr_inv_2026.parquet`(5.7 MB)를 평일마다 main 에 재커밋 → 결정 A 게이트(20 MB/일) 잠식. 47db1267·84f19082 재시도·호출 제한 변경은 테스트 갱신 없음 | 퀀트 |
| 경 L10 | 42c4a0d6 | `ops/freshness.json:24` (team) | 내부 지표 team.json 도 ⛔ 소리 대상 → ops 00:07 cron 이 밀리면 시장 데이터와 무관한 알림(전체 무음 해제 시) | 개발 · PM |
| 경 L11 | 8c73cefb (pb 직접) | `apps-script/tab_my.html:110` | 오너가 쓴 회고를 committer `Claude` 로 커밋(작성자 귀속 오류). 테스트 없음(ui_smoke `my` 444자 렌더만), 영향·롤백 줄 없음 | PB |
| 경 L12 | 92332e97 외 3건 (flowq) | `scripts/flow_query.py` | 파서 3회 교체 동안 테스트 0건. 수동 전용이라 운영 영향 없음 | 데이터 |
| 경 L13 | 25f73e33 | `screener/detail.py` `_sim_one` `rets` | 상세 JSON 종목마다 전략×(long·ls) 거래별 수익 목록 추가 → detail/KR·US 일일 재기록 크기 증가(측정 없음) — 결정 A 측정 기준선이 바뀜 | 퀀트 |
| 해소 | a103bb65 → 928184b8 | `.gitignore` `!data/flows/` | 첫 백필(05:07Z) 때 data/flows 가 무시 목록이라 46거래일 수집분 미커밋 → 84f19082 예외 추가 뒤 06:00Z 재백필로 커밋 확인 | — |

반대 근거(M1): 커밋 메시지와 `tests/test_telegram_silent.py` 가 PB 점검 무음을 의도로 고정 — 결재 #9 원문이 '코스피 [12]만'이면 M1 은 경. 탐색 범위: 공개 저장소만(비공개 저장소 pb-private 의 합의서 §7-3 미열람).

### 2.3 월요일(10/19) 모의 — 08:20 → 08:50
| KST | 실행 주체 | 재현 결과 |
|---|---|---|
| 08:20 | health.yml cron 단독 → `--mode freshness_alert` | 현재 파일·now=10/19 08:20 로 `freshness.check`: 늦음 = team.json 1건(주말 무실행 가정 탓, ops 00:07 가 돌면 0). 늦음이 있으면 ⛔ 1통(지금은 무음) |
| 08:40 | live: GAS(주) + cron 대기 | GAS 실행 있으면 cron 건너뜀 |
| 08:50 | briefing premarket_kr: GAS(주) + cron 대기(09:02 판정) | `slot_guard.decide` 재현: A GAS 08:51 → cron 건너뜀 · B GAS 없음 → cron 09:02 실행 · C 구 GAS(commit=auto 08:52) → 커밋 · D 구 GAS 09:05 → **2통**(L1) |
| 08:50 내용 | 장전 브리핑 + PB 아침 점검(무음) | 가드·계약은 쓰기만 막고 예외를 내지 않음 → 발송 차단 경로 없음 |

판정: 정상 경로 1회. 예외 = 구 GAS 가 09:02 뒤 발송(2회, 붙여넣기로 해소) · GAS 실행 생성 후 실패(0회, 기존 한계).
오너 선행 조건(월 08:40 전):
1. `apps-script/Scheduler.gs` 붙여넣기 → `tickTest` 첫 줄 `예약기 버전 2026-10-18 결정C · 창 10분` 확인(일요일 02:00–02:10·03:30–03:40 피함). GH_TOKEN 만료일 확인.
2. 시크릿 `MY_RULES`(touch·price 줄)·`MY_HOLDINGS` 등록 확인 — 없으면 터치·PB 점검이 조용히 건너뜀(보드 `secret-missing-warning` 미완). SEMI_CAP 줄은 레짐 상한에 덮여 무효(L4).
3. Pages Actions 변수(`PAGES_ACTIONS`·`DATA_BRANCH_US`)는 월요일 장 운영 1회 확인 전까지 끔(계획 §7). 전체 무음(I1) 유지 여부 확인.

## 3. 반증 가능 조건
- **R1 (판정 10/19 09:10, 검증 데스크):** 월 08:50 장전 브리핑이 Actions 실행 목록에 2건(dispatch + cron 둘 다 '실행') 또는 0건이면 "정확히 1회" 판정을 철회하고 slot_guard 를 치명으로 올린다.
- **R2 (판정 10/19, PB 회신):** 결재 #9 원문 '손절 2일'이 코스피 규정 [12] 선만 뜻하면 M1 을 경으로 내린다.
- **R3 (판정 10/20 16:30):** 10/19 16:20 실행에서 macro_series KOSPI 끝 행이 당일이고 손절선 점검 로그가 정상이면 M3 은 '잠재'로 유지하되 등급 경으로 내린다.

## 4. 채점 3항목
| # | 항목 | 기준 | 판정일 |
|---|---|---|---|
| S1 | 월 08:50 장전 알림 횟수 | 1회 = 적중 | 10/19 |
| S2 | 중 4건 처리 | 보드 `audit-*` 4건이 검수 이상 | 10/21 |
| S3 | 다음 감사 라운드 치명 | 0건 유지 | 10/24 |

## 5. 보드 등록(이 커밋)
`audit-ring-pb`(M1, 개발 P1 10/19) · `audit-fix-commit`(M2, 개발 P1 10/19) · `audit-macro-asof`(M3, 개발 P1 10/20) · `audit-pb-direct-test`(M4, PB P2 10/20) · `audit-1017-minor`(L2~L13 묶음, 개발 P3 10/24).

VOC: 결재 #9 원문(pb-private)을 감사 데스크가 못 읽어 M1 등급을 확정 못 함 — PB가 §7-3 '손절 2일' 범위 1줄 회신 필요.
요청→개발: M2·M3 를 월 08:20 전에 처리(둘 다 10줄 안팎), 처리 불가면 보드에 사유.
현재 상태: 게이트 통과(치명 0) / 중 4건 보드 등록 / 월요일은 Scheduler.gs 붙여넣기만 되면 장전 알림 1회(전부 무음).
