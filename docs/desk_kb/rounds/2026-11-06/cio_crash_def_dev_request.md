# CIO → dev 구현 요청 초안 — 급락일 1차 신호 종가 정의 정정 (결재 후에만 착수)

> 상태: **초안 · 결재 대기** (`req-pb-1f2aca39` open, 근거 `rounds/2026-11-05/cio_crash_day_def.md`, 퀀트 대조 `req-pb-52aa3926` open). 이 문서는 결재 전 코드·정의 변경 지시가 아니다. 결재가 나면 PB 가 `ask.py --to dev` 로 이 파일 경로와 함께 정식 요청을 올린다. 투자 권유 아님.
> 사후 최적화 금지: 정정 근거는 등록 정의(10/16, 결과 전)와 코드의 불일치이지 11/5·11/6 의 숫자가 아니다. 문턱 −5%·−4%(`screener/defs.py` CRASH_PCT·CRASH_NEAR_PCT) 불변. 오늘(11/5·11/6) 신호를 소급 재판정하지 않는다. 문턱·정의의 이후 변경은 새 사전등록 + 월간 구조 리뷰(kb:cio#16) 없이 금지.

## 확인된 사실 (11/6 파일 직접 확인)
- `screener/committee.py` `crash_flag`(120~143행 부근)는 아직 정정 전: `worst = min(ret1, low_ret)` 로 `crash`/`near` 를 정한다. `_exec_plan` 신호표 `ok` = `bool(cf["crash"])`(약 327행), `now` 칸에 `저가 {low_ret}` 를 같이 표시. 이 파일은 11/5 판정 이후 수정 이력 없음(마지막 변경은 퀀트 kospi_ma 커밋).
- 즉 화면이 장중 저가 기준으로 True 인 것은 **결재 대기라 의도적으로 안 바꾼 상태**와 일치한다(11/5 판정문 "결재 전까지 코드는 그대로"). HF 가 말한 '전향 적용(11/6)'은 결재를 조건으로 한 것이라 코드에 자동 반영되지 않는다.

## 결재 후 변경 목록
1. `screener/committee.py::crash_flag`
   - `crash` = `ret1 <= CRASH_PCT`(종가 일수익률만). `near` = 장중 저가 `low_ret <= CRASH_PCT` 이면서 `crash` 가 아닌 경우 + 기존 `ret1 <= CRASH_NEAR_PCT`. 반환에 `touch: bool`(장중 저가 ≤ −5%) 추가. 기존 키(`crash, near, ret1, low_ret, grade, thr`) 유지 — 소비처 호환.
   - 장중(15:30 전)에는 `ret1` 이 잠정값이므로 `provisional: bool` 로 `k["src"]` 가 '확정 종가'가 아니면 True. 화면에 '잠정(종가 확정 전)' 병기.
   - dd20 ≤ −10% 조건은 이 건에 **넣지 않는다**(퀀트 대조 `req-pb-52aa3926` 결재 뒤 별건).
2. `screener/committee.py::_exec_plan` 신호표(321~327행): 1차 행 라벨을 '급락일 종가 ≤ −5% — 1차 신호 (등급 B)' 로, `now` 는 종가 수익률을 앞에, 저가는 '장중 터치 · 표본 밖 · 등급 없음' 으로 분리. 신호표에 near 행 1줄 추가(`ok` 아님, 등급 없음). `steps[0]` 문구의 '오늘 충족/미충족' 은 `crash`(종가)만 본다. 모듈 docstring 9행의 '장중/종가' 도 '종가'로.
3. `screener/committee.py::_stance`(231~288행): `cf["crash"]` 분기는 그대로 종가 기준이 되어 '분할 매수 — 급락일 종가 1차 집행' 이 장중 터치만으로 뜨지 않는다. `touch and not crash` 일 때 reasons 에 관측 한 줄("장중 −5% 터치 · 종가 미달 · 표본 밖 · 등급 없음 — 판단 근거 아님") 추가, stance 는 바꾸지 않는다.
4. 소비처 확인(코드 변경 불요, 회귀만): `screener/duel.py::is_crash_day`(647행 — committee.json `crash_day.crash` 우선이라 자동으로 종가 기준. 단 폴백 경로는 `chg ≤ −5%` 로 장중 등락률이므로 폴백도 확정 종가에서만 True 가 되도록 `provisional` 조건 검토), `screener/dotplot.py`(16행 docstring, 369~373행 `crash_today`, 532행 문구 '급락일 종가(등급 X)'), `scripts/scorecard_week.py`(`crash_day` 항목 집계 — 11/6 이전 항목은 소급하지 않음).
5. 테스트 `tests/test_crash_day.py`: `test_crash_flag_close_and_intraday_low`(38~46행)가 '종가 −3% · 장중 −5% → crash True' 를 기대 — **11/6 전향 이후 정의에 맞게 기대값 교체**(crash False, near True, touch True). 추가: ① 종가 −5.2% → crash True · touch 무관 ② 종가 −3% · 저가 −8.8% → crash False·touch True·stance ≠ '분할 매수' ③ `_exec_plan` 신호표 1차 `ok` 가 종가만 따름 ④ `provisional` 표시. 실행: `pytest tests/test_crash_day.py tests/test_dotplot.py tests/test_pb_call_escape.py`, `python3 scripts/check_functions.py`, `python3 scripts/check_rules_terms.py`, UI 는 `scripts/ui_smoke.py`.
6. 전향 적용 표기: 코드 주석에 결재 id·적용일(결재 후 첫 거래일)을 남기고, 그 이전 날짜 산출물(reports/committee.json 이력)은 재생성하지 않는다.

## 별건 제안 (HF 요청) — 연속 급락 2일차 표시, 이 정정과 분리
- HF 제안: 전일 1차 집행분이 손절된 직후의 급락일은 독립 1차가 아니라 2차로 표시. 퀀트 집계는 이틀 연속 −5% 30년 10회(표본 작음).
- CIO 판단: **표시 라벨만, 신호 `ok`·문턱 불변**으로 한정하면 설계 가능. 단 '전일 집행 손절'은 집행 장부 상태라 재현 가능·재량 0 이 아님 → 조건은 **전일 종가도 ≤ −5%(`prev_close` 일수익률)** 로만 정의. 등급 없음·검증전·n 작음 명기. 이것도 새 규칙이므로 정정과 같은 결재 건에 섞지 않고 별도 결재·사전등록 후에만 코드화. 오늘 숫자를 본 뒤 만든 라벨이라는 점을 결재문에 적는다(전향 적용만).
