# 주간 성적표 (공개) 10/12~10/18

- 기준: 2026-10-16 18:35 KST · ISO 주 2026-W42 (2026-10-12 ~ 2026-10-18) · 비율·건수만 (금액·보유는 비공개 성적표)
- 코스피 주간: −14.5% (2026-10-08 → 2026-10-16)

## 모의 대결 (이번 주 판단일 기준)

채점 2건 · 제외 1건 · 채점 대기 1건 — 모의 금액 기준, 실계좌 아님

| 참가자 | 판 | 승 | 승률 | 진입 | 적중 | 평균 수익률 | 모의 손익 |
|---|---|---|---|---|---|---|---|
| 나 | 2 | 2 | 100% | 2 | 100% | +4.28% | +81,903 |
| 나🔥 | 0 | 0 | n/a | 0 | n/a | n/a | +0 |
| └ 나🔥(감) | 0 | 0* | n/a | 0 | n/a | n/a | +0 |
| └ 나🔥(판단) | 0 | 0* | n/a | 0 | n/a | n/a | +0 |
| PB | 2 | 0 | 0% | 0 | n/a | n/a | +0 |
| PB🔥 | 0 | 0 | n/a | 0 | n/a | n/a | +0 |
| 규칙 | 0 | 0 | n/a | 0 | n/a | n/a | +0 |

\* 나🔥 의 '승' = 같은 판에서 '나'보다 손익이 큰 횟수 (레버리지 해금 조건 판정용)

누적 (전체 기간): 나 2/2 (적중 100%) · PB 0/2

## 레짐 (운용회의)

| 날짜 | 세션 | 레짐 | 강세/기본/약세 | 스탠스 |
|---|---|---|---|---|
| 2026-10-15 | 장후 |  | 47%/28%/25% | 관망 |
| 2026-10-16 | 장후 | 하락장 | 44%/35%/22% | 관망 |

## 이벤트 · 운영

- 서킷·사이드카: 실제 3건 (서킷 2 · 사이드카 1) · 경보(기준 근접) 3건
- 워크플로 실패 (7일): 1건 — briefing 1 · 데이터 이슈 0건 (health 2026-10-15 19:01)

## 관점(렌즈) 등급

등급별: A 0 · B 5 · C 14 · F 6 · 검증전 14 (총 39, registry 2026-10-16)

| 렌즈 | 등급 | 상태 | 진입/청산/배분 |
|---|---|---|---|
| 국장 레짐 (200일선·20일 낙폭) (`kr_regime`) | C | 채택 | alert/reference/gate |
| 급락일 종가 진입 (기다리지 않기) (`crash_day_close`) | B | 채택 | weight/none/none |
| 반등 확인 신호 (저점 지지·5일 고점·저점 2일 이탈) (`confirm_signals`) | F | 강등 | reference/none/none |
| 외국인 현물 순매수 (코스피) (`foreign_flow`) | 검증전 | 검증중 | reference/reference/none |
| 매크로 바람 (금리·환율·미국 지수 합성) (`macro_wind`) | 검증전 | 검증중 | reference/reference/reference |
| 시장 폭 (국장 200일선 위 종목 비율) (`breadth_kr`) | 검증전 | 검증중 | reference/none/reference |
| 시나리오 기저확률 (1999~ 조건부 통계) (`scenario_base_rate`) | C | 채택 | reference/reference/reference |
| 종목 추세·모멘텀 점수 (스크리너) (`stock_trend_score`) | F | 강등 | reference/none/none |
| 지수 절대모멘텀 (12개월 > 0 이면 보유) (`index_abs_momentum`) | F | 강등 | none/none/reference |
| 옵션 감마·풋콜 (코스피200) (`options_gamma`) | 검증전 | 검증중 | alert/reference/none |
| 감마 레짐 (숏감마 구간 흔들림·추세 지속) (`gamma_regime`) | 검증전 | 사전등록 | reference/reference/none |
| AI 인프라 신용 감시 (`ai_credit`) | 검증전 | 검증중 | alert/alert/alert |
| 주식–채권 상관 (IEF vs S&P500, 1년) (`stock_bond_corr`) | C | 채택 | none/none/reference |
| 미 10년 금리 (수준·1개월 변화) (`us10y`) | 검증전 | 검증중 | reference/reference/reference |
| 엔 캐리 청산 경계 (엔/달러 5일) (`yen_carry`) | 검증전 | 검증중 | alert/alert/none |
| 일본 반도체 장비·메모리 동행 (`japan_semi_lead`) | C | 검증중 | reference/reference/none |
| 공급망 체인 점수 (업종 비중 의견) (`supply_chain`) | 검증전 | 검증중 | reference/reference/reference |
| 운용회의 매수 후보 (이익 신호 좋고 과하게 빠진 종목) (`committee_ideas`) | 검증전 | 검증중 | reference/none/none |
| 핵심 이벤트 (7일 안 CPI·FOMC·빅테크 실적) (`event_calendar`) | 검증전 | 채택 | alert/reference/none |
| 종목 손절선 (20일 저점·2×ATR) (`atr_stop`) | C | 채택 | none/gate/none |
| 미장 레짐 (S&P500 50일선·20일 낙폭·VIX) (`us_regime`) | 검증전 | 검증중 | reference/reference/reference |
| 상품 금지 (레버리지·인버스·신규상장·미수) (`personal.instrument_ban`) | B | 채택 | gate/none/none |
| 위성 북 상한 사용률 (`personal.satellite_cap`) | B | 채택 | gate/weight/gate |
| 반도체 테마 집중도 (`personal.theme_concentration`) | B | 채택 | gate/gate/gate |
| 손실 한도·쿨다운·매매 금지 (`personal.loss_limit`) | C | 채택 | gate/none/none |
| 이벤트·서킷 당일 장중 진입 금지 (`personal.event_day_ban`) | C | 채택 | gate/none/none |
| 보유기간 습관 (10일+ 보유) (`personal.hold_period`) | C | 강등 | none/reference/none |
| 코어 북 적립 진행 (`personal.isa_dca`) | B | 채택 | none/none/weight |
| 후보: 10일 안 추가 −5% 하락 시 2차 진입 (`cand.add_on_drop`) | 검증전 | 후보 | none/none/none |
| 후보: 프로그램 비차익 막판 매수 = 바닥 신호? (`cand.program_nonarb`) | 검증전 | 후보 | none/none/none |
| 피보나치 되돌림·하방 Fib 지지선 (`fib_levels`) | F | 강등 | reference/reference/none |
| 후보: 강세 전환 신호 대체 — 급락일 종가 진입 (확인 신호 기다리지 않기) (`entry_trigger`) | C | 후보 | alert/none/none |
| 후보: 추격 진입(RSI14>70 또는 전일 +5%) 사이즈 축소 — 유지·강화 쪽 근거 (`cand.chase_sizing`) | C | 후보 | alert/none/none |
| 후보: 반등일(+0.5%) 매도 대기 — 즉시 매도보다 나음 (`cand.rebound_day_sell`) | C | 후보 | none/alert/reference |
| 후보: 하락장(200일선 아래) 노출 50% 상한의 비용 — 완화 검토 (`cand.bear_cap_cost`) | C | 후보 | none/none/reference |
| 참고: 손절 −8%·20일선 트레일·1R/2R 부분익절 대안 비교 (차이 없음) (`cand.exit_rules_audit`) | F | 후보 | none/reference/none |
| 실행 대본 신호 1 — 외국인 당일 순매수 (코드 fl[0] > 0) (`exec_signal_1`) | F | 강등 | reference/none/none |
| 실행 대본 신호 2 — 저점 지지 (코드: 종가 ≥ 당일 저가 → 항상 참 / 의도: 저가 +1% 위 마감) (`exec_signal_2`) | C | 후보 | alert/none/none |
| 급락 뒤 비반도체 섹터 기록 (KRX 업종 24개, 동일가중) (`sector_postcrash`) | C | 후보 | reference/none/reference |

## 연구 등급 (reports/studies)

| 연구 | 가설 | 등급 | 메모 |
|---|---|---|---|
| derivs_signals | H1 | 검증전 | 외국인 선물 순매수 → 다음날 |
| derivs_signals | H2 | F | 외국인 현물 순매수 → 다음날 |
| derivs_signals | H3 | F | 외국인 현물 3일 순매도 후 순매수 전환 → 5일 |
| derivs_signals | H4 | 검증전 | 베이시스 음수(백워데이션) → 5일 |
| derivs_signals | H5-r5 | 검증전 | 풋콜(OI) 상위 20% → 5일 (역발상) |
| derivs_signals | H5-r20 | 검증전 | 풋콜(OI) 상위 20% → 20일 (역발상) |
| derivs_signals | H6-r5 | 검증전 | 풋콜(OI) 하위 20% → 5일 (낮음) |
| derivs_signals | H6-r20 | 검증전 | 풋콜(OI) 하위 20% → 20일 (낮음) |
| derivs_signals | H7 | 검증전 | 감마 하위 1/3 vs 상위 1/3 → 다음날 |수익률| (흔들림) |
| derivs_signals | H8 | A | 야간선물 등락 → 다음 정규장 시가 갭 (산수 확인) |
| derivs_signals | H9 | 검증전 | 프로그램 비차익 순매수 상위 20% → 다음날 |
| entry_signals | A | F | 대조군 대비 개선 없음(평균 +4.8%p, p=0.114) |
| entry_signals | B | F | 대조군 대비 개선 없음(평균 +5.3%p, p=0.112) |
| entry_signals | B2 | F | 대조군 대비 개선 없음(평균 +3.8%p, p=0.123) |
| entry_signals | C | F | 대조군 대비 개선 없음(평균 +2.9%p, p=0.198) |
| entry_signals | E | F | 대조군 대비 개선 없음(평균 +4.9%p, p=0.136) |
| entry_signals | F | C | 방향만(p=0.070, Bonferroni 미달) |
| fib_levels | lens | F |  |
| gamma_regime | gamma_regime | 검증전 | 숏감마(감마 음수) 구간을 노릴 수 있나? |
| rule_audit | T1/s5 | F | 현행과 구별 안 됨(p=0.29) |
| rule_audit | T1/s12 | F | 현행과 구별 안 됨(p=0.57) |
| rule_audit | T1/satr | F | 현행과 구별 안 됨(p=0.31) |
| rule_audit | T1/snone | F | 현행과 구별 안 됨(p=0.80) |
| rule_audit | T2/m10 | F | 현행과 구별 안 됨(p=0.90) |
| rule_audit | T2/m50 | F | 현행과 구별 안 됨(p=0.47) |
| rule_audit | T2/chand | F | 현행과 구별 안 됨(p=0.14) |
| rule_audit | T2/tnone | F | 현행과 구별 안 됨(p=0.28) |
| rule_audit | T3/nopart | F | 현행과 구별 안 됨(p=0.58) |
| rule_audit | T3/target2R | F | 현행과 구별 안 됨(p=0.82) |
| rule_audit | T4/imm | C | 방향만(p=0.013, Bonferroni α=0.0028 미달) |
| rule_audit | T4/th0 | F | 현행과 구별 안 됨(p=0.43) |
| rule_audit | T4/th1 | F | 현행과 구별 안 됨(p=0.74) |
| rule_audit | T5/c0 | C | 방향만(p=0.080, Bonferroni α=0.0028 미달) |
| rule_audit | T5/c70 | C | 방향만(p=0.084, Bonferroni α=0.0028 미달) |
| rule_audit | T5/c100 | C | 방향만(p=0.086, Bonferroni α=0.0028 미달) |
| rule_audit | T6/full | C | 방향만(p=0.011, Bonferroni α=0.0028 미달) |
| rule_audit | T6/ban | C | 방향만(p=0.011, Bonferroni α=0.0028 미달) |
| semis_cap | H1 BAND−CAP40M | C |  |
| semis_cap | H1 BAND−BH | F |  |
| semis_cap | H1 CAP40M−BH | F |  |
| semis_cap | H2 GLIDE−SELL35 | A |  |
| semis_cap | H3 CAP30−CAP40 | F |  |
| semis_cap | H3 CAP35−CAP40 | F |  |
| semis_cap | H3 CAP45−CAP40 | F |  |

## 규칙 간 정합성 (뼈대 — 값은 비공개 성적표 week_YYYY-WW.md)

| 규칙 | 한도·설정 (공개 입력) | 현재값 | 상태 |
|---|---|---|---|
| [3] 테마 집중도 | 목표 40% · 발동선 45% (주 1회 점검) | 비공개 (pb-private 성적표) | — |
| [11] 1일 VaR99 (60일 실현, 계기판) | 하락장 1.5% / 기본 2% — 판정 아님(계기판) | 비공개 (pb-private 성적표) | — |
| [11] 스트레스 | 어느 시나리오도 −15% 초과 금지 | 비공개 (pb-private 성적표) | — |
| [0] 위성 북 크기 | 상한 (비공개 금액) — 초과분 연말까지 코어 이전 | 비공개 (pb-private 성적표) | — |
| [5] 보유 백스톱 | 종목별 −20% 도달 시 2주 내 정리 | 비공개 (pb-private 성적표) | — |

---

공개 층은 비율·건수만 다룬다. 위성 북 vs 코스피 알파·위반·벌금·반도체 비중·순자산 목표 진행률은 비공개 성적표에.
