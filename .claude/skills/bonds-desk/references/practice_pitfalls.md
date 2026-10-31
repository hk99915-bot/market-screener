# 현업 vs 교과서·흔한 오해·우리 연구와의 차이·출처 (kb:bonds#11–16·#19–23)

(원본: docs/desk_kb/bonds.md 해당 절을 그대로 옮김 — 2026-10-31 스킬 시범, `kb:bonds#<n>` 번호 동일. 내용 수정은 KB 먼저, 여기는 따라 고친다.)

## 현업 vs 교과서
11. [교과서 vs 자체연구] "보유기간 ≈ 듀레이션이면 금리 중립(가격 손실 = 재투자 이익)"은 **개별 채권** 얘기. 상시 만기 ETF(국고채 3년 ETF D 2.8 고정)는 만기·pull-to-par가 없어 갭이 0으로 수렴하지 않는다. 성립하는 근사: 1회성 +100bp 뒤 약 D년(≈2.8년)이면 총수익이 원래 경로를 따라잡음 → "코어 3년물은 3년 이상 들고 가는 돈". 반복 인상이면 시계가 매번 재시작. (출처: CFA L1 'Interest Rate Risk and Return' `[확인 필요: 원문 대조, 2026-10-30]`, `screener/bonds.py` ETFS 고정 듀레이션)
12. [교과서 vs 자체연구] 교과서 '채권 = 분산 자산'. 우리 `stock_bond_corr`(IEF–S&P 1년 상관, 임계 +0.2): 2026-10-16 +0.36(60일 +0.47), 국고 3년 ETF–코스피 +0.30 → "같이 빠지는 국면: 장기채 대신 단기·현금". 보험은 **성장 충격**(금리↓)에서만, **물가 충격**(2022형)에선 아님. (출처: registry `stock_bond_corr` C, `reports/bonds.json` corr/reco; Ilmanen growth/inflation `[확인 필요: 원문 대조, 2026-10-30]`)
13. [교과서 vs 현업 관행] 10Y−2Y 는 기대 + 기간 프리미엄이 섞인 값 → 어느 다리(2Y/10Y)가 움직였는지로 베어/불 × 스티프/플랫 4분면(`interpret`, m1 ≥ 10bp).
14. [교과서] '역전 뒤 정상화가 더 위험' 통설 — 정상화가 인하 기대(불 스티프닝)와 둔화 시점에 겹친 사례가 많음. 미국 침체 표본 8회 안팎, 시차 6~24개월, 코스피 예측력 미검증. (Estrella & Mishkin 1996)

## 흔한 오해
15. [경험] "채권은 손실 없다"(금리 위험 ≠ 신용 위험: TLT 2022 −30%대 `[확인 필요: 원문 대조, 2026-10-30]`) / "인하 = 채권 ETF 무조건 상승"(선반영·매파적 인하·장기 금리는 반대로) / "bp와 %p 혼동"(3.87%에서 −11.3bp = 3.757%) / "ETF도 만기까지 들면 회복"(만기 없음) / "kr_bbb 649bp = 위기"(상시 수준). (출처: `consult:bonds#q8·q11`)
16. [경험] 60/40을 'TLT 40'으로 짜면 2022형(주식 −20·금리 +100bp)에 −18.4%, '3년물 40'이면 −13.1% — 5%p가 듀레이션 선택의 값. (출처: `reports/bonds.json` duration scen, 산술)

## 우리 연구와의 차이
21. [현업 관행·공시 vs 자체연구] KODEX 국고채3년(114260) = 3년 국채선물 바스켓 국고 3종, 공시 D 2.96(2026-07-07) vs 코드 상수 2.8 → D 는 롤마다 2.6~3.0 을 오가는 **구간**. 라벨은 "D≈2.8 근사", 월 1회 공시 대조. 뒤집는 조건: 공시 D 2.5 미만/3.1 초과 2개월 연속이면 상수 교체. 신뢰도 중. (삼성자산운용 월간보고서 2026-09-30·funETF, `[확인 필요: MKF 지수 롤 규칙, 2026-10-31까지]`)
22. [자체연구-검증전] 결재 #15 ③: `reports/bonds.json` `etf[]`·`vehicles[]`에 `maturity`·`rate_line`("+100bp → 약 −2.8% · D≈2.8 근사 · 만기 없음") — `etf_rate_label`, 테스트 `tests/test_bonds_etf_label.py`, 롤백 `git revert 917e4292`. 화면 열은 `tab_bond.html` 잠금 필요(미반영). 단기채 대체 비교 `docs/bonds_short_duration_alts.md`.
23. [현업 관행·자체연구-검증전] 국고 3Y 공식 값 = KRX [14017] **장 마감 후 확정값**, 장중 값은 '잠정'(10/27 같은 출처 장중 3.785 vs 확정 3.758, 2.7bp — 출처별 3~4bp 차의 1차 후보 = 시각 차). 금융위 채권시세 V2 = 개별 종목 장내 종가 → 대조군(`screener/fsc_bond.py`, |차| ≤ 3bp). 환헤지 비용은 CIP 이론값(1년 −10.8원, −0.81%/년, 10/27)을 하한으로 쓰고 시장 스왑포인트 미확인 표기. (`rounds/2026-10-28/bonds_night.md`)
19. [자체연구-C] `stock_bond_corr`는 서술 통계(n=250)로 C. 비중 결정엔 쓰지 않고 **듀레이션 선택(3년 vs 10년)** 참고만. 비중은 연 1회 리밸런싱 규칙. (출처: registry `stock_bond_corr`)
20. [자체연구-검증전] 역전·스프레드 확대의 코스피 예측력, `ai_credit` 경보의 적중률 — 모두 미검증. 교육 모듈엔 '경보·참고'로만 쓰고 "팔아라"로 번역하지 않는다. (출처: registry `ai_credit`, `rule_audit.md` #17)

## 출처
- 교과서: Tuckman & Serrat *Fixed Income Securities* 4판(2022) 4·5·8장 · Fabozzi *Bond Markets* 10판 · CFA L1 Fixed Income · Estrella & Mishkin 1996 — 목차·2차 확인, 본문 `[확인 필요: 원문 대조, 2026-10-30]`
- 자체: `screener/bonds.py`(`par_bond`·`dur_only`·`corr`·`interpret`·`recommend`·`credit_alert`·`ai_credit`), `reports/bonds.json`, `views/registry.json`(`stock_bond_corr` C·`ai_credit` 검증전)

