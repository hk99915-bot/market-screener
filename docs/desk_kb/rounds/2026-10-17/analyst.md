# analyst 라운드 — 2026-10-17 (기준: docs/desk_kb/STANDARD.md) · 주제: US 밸류에이션 공백(오너 지적 "미장은 안 돼있네")

1. **읽기** — 자기 KB 전체 + 복기 2건, 피어 데이터 데스크(SEC 태그·mu-revenue-tag), LOOP·STANDARD, screener/valuation.py·detail.py·valuation_daily.py·sec.py, docs/valuation_notes/2026-10-17_memory.md.
2. **배우기** — Damodaran implied ERP 2026-01 = 4.23%, 2025-01 = 4.33% (BVR 요약 기사, 2차 인용 · 원문 histimpl 미확인 → `[확인 필요: 스턴 원문, 10/24 analyst]`). 우리 US 가정 ERP 5.0% 는 이보다 0.8%p 보수. 반대 근거: 2026-07 국가위험 조정 후 성숙시장 ERP 4.20% — 낮춰야 한다는 쪽. KB '현업 vs 교과서'에 등급과 함께 추가.
3. **고치기** — 원인: detail.py `if market == "KR"` 만 가치평가 → US 517종목 `valuation` 빈 dict. `valuation.us_all(prices)` 신설(SEC 분기→6모델, COE = 미10Y 5.10% + ERP 5.0% = 10.1% [가정], g 2.5% [가정], USD 그대로, `currency:'USD'`), 품질 가드(분기<4·분기 불연속·누적치 의심(fin_verified 대조 시 해제)·자본 음수 → 검증전, PBR>100·현재가 1/20~20배 밖 → 범위 제외), 사이클 업종 `cycle_view`(최근 이익률 지속 PER vs 장기 평균 순이익률×현재 매출 PER). KR 출력은 무변경(구판과 300건 무작위 대조 0 차이).
   - 테스트 `tests/test_valuation_us.py` 9건 / 롤백 `git revert <이 커밋>` / 영향: 미장 마감 워크플로(06:52 KST) 종목 상세 JSON 의 valuation 키만. 탭 표시는 아래 요청 전까지 안 바뀜.
   - 5종목 (10/15 종가, reports/detail/US): MU PER 12.4·PBR 7.61·범위 $130~2,378 중앙 $621(−33%) / SNDK 17.8·12.94 / NVDA 27.4·23.06 / AAPL 38.8·46.47 / JPM 13.9·2.42(금융, DCF 제외). 모두 '검증전' 아님.
   - 대조: MU TTM PER = valuation_daily 11.7(10/16 종가 878.84)과 같은 EPS $75.13. NVDA FQ2 순이익 59,688M = 8-K q2fy27pr 일치. JPM 2Q26 21.2B = 실적 발표 일치(단 Visa 4.6B+투자 1.0B 일회성 포함 → TTM ROE 17.4% 는 과대, 제외 시 약 15.9%).
4. **피어(데이터)** — 반대 의견: US 517종목 중 156종목이 SEC 매출 태그 미수집(MU·AAPL·JPM 포함), 72종목은 주식 수 없음(SEC·시총 모두) → 가치평가 생략. 매출이 없으면 사이클 정규화가 이익률 대신 ROE 로 대체돼 MU 정규화 PER 이 65(ROE 법) vs 노트 24~40(이익률 법)으로 갈린다. 태그 확장(RevenueFromContractWithCustomer… 의 회사별 변형)이 밸류에이션보다 먼저.
5. **복기** — 10/16~17 내내 '밸류에이션 = KR 6모델 + US 바스켓 배수표'로 나눠 놓고 US 상세 빈칸을 못 봤다 → 산출물 존재 여부만 보고 시장별 커버리지(빈 dict 비율)를 안 셌기 때문 → 다음부터 상세 JSON 키별 채움률을 시장별로 라운드마다 1줄 기록.

VOC: tab_detail.html 이 개발 잠금(sim-fresh)으로 표시돼 US VALUATION 패널을 못 켰다 — 잠금은 be662797 에서 해제됐다가 652ff101(공부 화면 커밋)이 locks.json 을 되살린 것으로 보임. 또 09ea9efbd detail_us 재생성이 asof 를 10-16→10-15 로 되돌림(MU 종가 878.84→931.24).
요청→개발: tab_detail.html 228행 `${kr?…VALUATION…:''}` 을 `s.valuation?.models` 있으면 US 도 표시로, valPanel 에서 `v.currency==='USD'` 면 금액 `$`·소수 2자리, 가정 줄 COE `toFixed(1)` + `a.rf_src`·ERP, `v.cycle_view.lines` 2줄, `v.quality.verified===false` 면 (검증전) 배지, `v.excluded` 목록 — 10/20까지. 그리고 locks.json 의 개발 잠금 4건이 의도인지 확인.
현재 상태: ① screener/valuation.py `us_all`·`cycle_view`·`value(…, currency, outlier)` 반영, detail.py vals 블록 3줄만 변경. ② reports/detail/US/{MU,SNDK,NVDA,AAPL,JPM}.json 의 valuation 만 즉시 갱신, 나머지 종목은 다음 06:52 미장 마감 실행부터. ③ 열린 항목: ERP 원문 확인(10/24) · 탭 표시(개발) · 매출 태그(데이터).
