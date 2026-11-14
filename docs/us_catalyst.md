<!-- short: 미국 촉매 배관 보강 — 18건 미진입 원인과 수정 -->
<!-- oneliner: 미장 촉매 정의를 실적 30종목 → 실적 캘린더 2종 + EPS 상향 558종목으로 넓히고, 계획 판정, 중복 제안 게이트를 붙여 11/14 판은 전건 '대기 — 계획 관찰' 로 남김 -->
# 미국 촉매 배관 보강 (2026-11-14)

기준 2026-11-14 KST ,  작성 개발 데스크 ,  근거 `reports/idea_tracking.json`, `reports/committee_us.json`, `reports/us_eps.json` ,  코드 `screener/us_catalyst.py`

## 상단 요약

- ① What: 미장 제안 18건이 2026-10-21~11-13 전부 `대기 — 촉매 없음` 으로 미진입(no_entry 18/18). 원인은 촉매 정의가 `calendar.json` 실적 이벤트 하나였고 그 목록이 `calendar_ev.US_EARN` 30종목뿐이던 것 — 후보 풀(peers_US 626종목)의 96%가 목록 밖이다.
- ② So What: 촉매 칸이 구조적으로 비어 '판정' 자체가 없었다. 촉매만 넓히면 저E[R] 제안이 모의 체결로 부풀 수 있어, 계획 판정 `채택`(E[R] > 무조건 기준선)과 같은 종목 10일 중복 금지를 함께 걸었다. 결과적으로 11/14 판은 실행 0건이지만 사유가 '촉매 없음'이 아니라 '계획 관찰(E[R] +0.10 ≤ 기준선 +0.12)' 로 바뀐다.
- ③ Now What: 검증은 `pytest`(신규 16건), `check_rules_terms`, `slop_audit` 통과. 문턱(`US_EPS_UP_30`)은 검증전이므로 사전등록 후 백테스트로 확정 필요. 되돌리기는 `screener/defs.py` 스위치 4개(`US_PLAN_ADOPT` 등) 또는 `us_committee.ideas_top_us` 촉매 호출 한 줄.

## 1. 원인 (코드 위치)

| # | 위치 | 내용 |
|---|---|---|
| 1 | `screener/us_committee.py` `ideas_top_us` (수정 전) | `cat = [ ... for e in cal if e.get("type") == "실적" ... 14일 안]` — 촉매를 실적 예정일 하나로만 셈. |
| 2 | `screener/calendar_ev.py` `US_EARN` | 실적 캘린더 수집 대상 = 빅테크, 반도체 30종목. `reports/calendar.json` 실적 이벤트가 이 목록에서만 나온다. |
| 3 | `screener/earnings_cal.py` `members()` | 두 번째 실적일 원천도 `universe/semis_basket.json` 49종목 한정 — `ideas_top_us` 는 이 파일을 아예 읽지 않았다. |
| 4 | `screener/us_committee.py` status 식 | `촉매 없음 → 촉매 없음` 이 첫 분기라 확신, 게이트, 추세를 볼 것도 없이 '대기' 로 끝났다. |

10/21~11/13 실제 후보(VEEV VLO CTAS XOM COP IEX CVNA PKG EXPD ISRG HAS)는 전부 30종목 밖이다(교차 확인: `reports/earnings_cal.json` 49행에 이 티커 없음). 같은 진단이 `docs/desk_kb/rounds/2026-11-01/quant_signal_review.md` §4 에 이미 있었다.

## 2. 연결한 원천 ,  넣지 않은 원천

| 원천 | 파일 | 범위 | 촉매 정의 | 등급 |
|---|---|---|---|---|
| 실적 예정일 | `reports/calendar.json` + `reports/earnings_cal.json` | 30 + 49종목 | 오늘~+14일(양끝 포함), 같은 날짜 1건 | 검증전 |
| 이익 추정 상향 | `reports/us_eps.json`(`data` 558종목) | 558종목 | 30일 변화율 ≥ +2% ,  상향 리비전 > 하향 ,  올해, 내년 엇갈리지 않음 ,  스냅숏 7일 이내 | 검증전 |
| 미장 공시 | 없음 | — | `reports/disclosures.json` 은 DART 전용(3,434건 전부 6자리 국장 코드) | 데이터 없음 |
| 미장 애널 목표가 | 없음 | — | `reports/detail/US/*.json` `research.consensus_tp`, `tp_upside` 전 종목 null, `reports/analysts.json` 은 국장 애널만 | 데이터 없음 |

EPS 추정 상향을 쓴 이유: 국장 촉매 `research:tp_up`(목표가 상향)의 미장 대응물이면서, 저장소에서 실제 값이 채워진 유일한 애널 추정 원천이다. 값 = yfinance `eps_trend` chg30(0.02 = +2%), 기준일 = `us_eps.json` `asof`(KST).

## 3. 함께 건 게이트 (리스크, 피어리뷰 합동 점검 2026-11-14)

1. **계획 판정 게이트** (`us_committee.apply_plan_gate`, `defs.US_PLAN_ADOPT`): `실행 후보` 는 매매 계획 판정이 `채택(모의)` 일 때만 유지. `관찰(모의)`(E[R] ≤ 무조건 기준선), `보류`(손절폭, R:R, 필터, 컨빅션), 계획 없음은 `대기 — 계획 …` 으로 내린다. 촉매가 채워졌다는 이유만으로 모의 체결되지 않는다.
2. **중복 제안 금지** (`idea_tracking.recent_entries`, `defs.US_REPROPOSE_DAYS` = 10달력일): 같은 종목이 앞선 10일 안에 `실행` 제안이었거나 실제 진입했으면 `대기 — 중복 제안`. 같은 날 재생성은 같은 제안으로 보고 세지 않는다. (HAS 11/06~11/13 6회 연속 같은 종목 재제안이 이 규칙의 대상이다.)
3. **촉매 기준일, 노후 한도**: `us_eps` asof 7일 초과 = 촉매 미사용(`defs.US_EPS_MAX_AGE_DAYS`), 판정 사유에 기준일을 남긴다(`catalyst_check` 예: `EPS 30일 상향 올해 +0.8% < 문턱 2%(us_eps 2026-11-14)`).
4. **소급 체결 금지**: 과거 18건 `original` 은 손대지 않는다. 촉매 배관을 넓혀도 `idea_tracking.evaluate` 는 `not_entered` 를 유지한다(`tests/test_us_catalyst.py::test_past_us_rows_are_not_retroactively_entered`). 근거 = `docs/idea_tracking.md`.

## 4. 11/14 판 실측 (모의)

| 종목 | 촉매 판정 | 계획 판정 | 최종 상태 |
|---|---|---|---|
| HAS | EPS 추정 상향 올해 +15.8%, 내년 +7.3%(상향 11/하향 0) | 관찰(모의) ,  E[R] +0.10 ≤ 기준선 +0.12 | 대기 — 계획 관찰(모의) |
| PODD | EPS 추정 상향 올해 +4.1%, 내년 +2.4%(상향 11/하향 5) | 관찰(모의) ,  E[R] +0.08 ≤ 기준선 +0.10 | 대기 — 계획 관찰(모의) |
| VLTO | EPS 추정 상향 올해 +2.2%, 내년 +1.5%(상향 9/하향 2) | 관찰(모의) ,  E[R] +0.10 ≤ 기준선 +0.12 | 대기 — 계획 관찰(모의) |
| IBM | 실적 14일 안 없음 ,  EPS 30일 +0.9% < 문턱 | 관찰(모의) | 대기 — 촉매 없음 |
| TYL | 실적 14일 안 없음 ,  EPS 30일 +1.3% < 문턱 | 관찰(모의) | 대기 — 촉매 없음 |

- 실행 0건은 유지되지만 사유가 바뀐다. 진입은 E[R] 이 무조건 기준선을 넘는 칸(현재 `us_trend` struct 1.5/3.0 = 0.10 vs 0.12)이 나올 때 생긴다.
- 반대 근거: 촉매, 게이트를 모두 통과해야 하므로 실제 체결 빈도는 낮다. 표본이 쌓이기 전에는 '촉매 배관이 성적을 올린다'를 말할 수 없다(검증전).

## 5. 영향 범위 ,  롤백

- 바뀌는 산출물: 미장 운용회의 `ideas_top.items[].catalyst`, `catalyst_check`, `status`, `idea_tracking` US 신규 행. 국장 경로, 주문, 알림 소리, 포트폴리오 한도는 읽지 않는다(`test_cio_top3_v2.py::Scope` 유지).
- 롤백: ① `defs.US_PLAN_ADOPT = False` → 계획 게이트만 해제 ② `us_committee.ideas_top_us` 의 `CAT.evaluate(...)` 를 실적 캘린더 한 줄로 되돌리면 11/14 이전 동작 ③ `US_REPROPOSE_DAYS` 를 0 으로 두면 중복 금지 해제.
- 검사: `python3 -m pytest` (기존 환경 실패 7건 외 신규 실패 0), `python3 scripts/check_rules_terms.py` 통과, `python3 scripts/slop_audit.py --ci` 경고만.

## 원본

- `screener/us_catalyst.py` ,  `screener/us_committee.py:ideas_top_us` ,  `screener/idea_tracking.py:recent_entries` ,  `screener/defs.py` ,  `tests/test_us_catalyst.py`
- `reports/idea_tracking.json`(US 18행) ,  `reports/us_eps.json`(asof 2026-11-14 07:01) ,  `reports/calendar.json`(asof 2026-11-14 03:37) ,  `reports/earnings_cal.json`(asof 2026-11-14 03:37)
- `docs/desk_kb/rounds/2026-11-01/quant_signal_review.md` §4, §6 ,  `docs/idea_tracking.md` ,  `docs/rules_terms.md`
