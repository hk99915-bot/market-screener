# bonds 데스크 KB

(자문·연구 과정에서 추가. 형식은 README.md. 2026-10-16 교육 자문 `consult:bonds` 답변에서 추출. 금액 없음 — 비율·가상 숫자만.)

## 성격·성향
- **한 줄:** 늦게 불렸다는 사실보다 "설명 없이 샀다"를 더 문제 삼는 설명 책임형.
- **판단 성향:** 보수 · 데이터 우선(듀레이션·손익분기 bp) · 과잉 반응도 경계(TH:bonds §4).
- **말버릇:** "틀린 건 구성이 아니라 설명 없이 샀다는 것이다."(TH:bonds §1) · "나는 오늘 밤 처음 불렸다. 그래서 목소리가 작다 — 내용은 작지 않다."(TH:bonds 머리말)
- **맹점:** ETF 듀레이션을 상수로 소수점까지 확정처럼 말함 — 과한 정밀도(KB:bonds 복기 10/17).
- **긴장:** ↔PB·자산배분 — 코어 채권 비중이 채권 데스크 호출 없이 정해짐(TH:bonds §1).
- 원본: [PERSONAS.md#bonds](PERSONAS.md#bonds) — 이 절은 요약, 갱신은 원본 먼저.

## 정의
1. [교과서] YTM = 가격을 미래 현금흐름의 현재가치와 같게 하는 단일 할인율. 현업 관행: 세전·미국채 연 2회 복리(BEY)·한국 국고채 반기 이표·회사채는 민평 '평가 수익률'. 가격 < 액면 ↔ YTM > 쿠폰. (출처: Fabozzi 가격 결정 장, CFA L1 'Yield and Yield Spread Measures' `[확인 필요]`; `screener/bonds.py` `par_bond(freq=2)`)
2. [교과서] 수정 듀레이션 D = 금리 1%p당 가격 변화 %(근사). DV01 = D × 가격 × 0.0001 = 1bp당 금액 변화. 교육 순서: 개인 투자자는 D(%) 먼저, DV01은 정의만(금액이 있어야 뜻이 생기는 딜러 숫자). (출처: Tuckman & Serrat 4판 4장 'DV01, Duration, and Convexity' — 목차 확인, 본문 `[확인 필요]`)
3. [자체연구-검증전] 터미널 `spreads`: us_10_2 = us_10Y − us_2Y, us_10_3m, kr_10_3, kr_aa = kr_AA − kr_3Y, kr_bbb = kr_BBB − kr_3Y, krus_10 = kr_10Y − us_10Y. 단위 %p(v), 변화 d1/w1/m1/y1는 **bp**. 한국 원자료 = KRX [14017] 장외 채권수익률(국고 1~30년·AA−·BBB−·CD, 민평). (출처: `screener/bonds.py` SP/KR_CODES/`_chg_bp`)
4. [현업 관행] 한국 `kr_bbb`(BBB− 3년 − 국고 3년 ≈ 650bp)는 거래 가격이 아니라 **평가 수익률** — 발행·유통이 AA 이상에 집중돼 BBB−는 사실상 투기등급 취급, 하루 변화 ≈ 0. 수준은 무시하고 `kr_aa`의 변화(m1 ±10bp 기준)를 본다. 가격 기반 대조군은 HYG/IEF 비율(`credit_us`). (출처: `screener/bonds.py` `interpret`, `reports/bonds.json`; 금투협 발행 잔액 분포 `[확인 필요]`)
5. [자체연구-검증전] `ai_credit` = 빚으로 데이터센터를 짓는 8종목의 주가 스트레스(52주 고점 대비·20일 수익률·변동성) + HYG 1개월 + VIX → 정상/주의/경계. CDS·개별 채권가 무료 소스가 없어 **주가로 본 신용 대용**. 역할은 경보뿐. (출처: `screener/bonds.py` `credit_alert`/`ai_credit`, registry `ai_credit` 검증전)

## 공식
6. [교과서] ΔP/P ≈ −D × Δy + ½ × C × Δy². D 7·+50bp → −3.5%(C 60이면 −3.43%). 국고 3년(D 2.81, C 9.5): +50bp −1.39% / +100bp −2.76% / −100bp +2.85%. 미 10년 D 7.76(+100bp −7.39%), 30년 D 14.73(−13.09%). (출처: `reports/bonds.json` duration, A3 모듈)
7. [교과서] 손익분기 금리 상승폭 be_bp ≈ 1년 캐리 ÷ D. 국고 3년 3.87/2.81 = 138bp, 국고 10년 52bp, 미 10년 66bp, 30년 37bp. "한은이 올려도 138bp 안이면 1년 이자가 손실을 덮는다". (출처: `screener/bonds.py` `par_bond`/`dur_only`, `reports/bonds.json` duration.be_bp)
8. [교과서] 가격↔금리 최소 예: 액면 100·쿠폰 5·1년, 5→6% → 105/1.06 = 99.06(−0.94%); 3년이면 ≈ −2.7%(D 2.72). 비유: 월세 50만원 2년 계약 — 옆집 시세가 60만원이 되면 내 계약(채권)의 가치↑. (출처: 0-6 모듈, 산술)
9. [교과서] 환헤지 비용 ≈ 미국 3M − 한국 CD(오늘 +1.03%p/년 = 미 10년 이자의 약 20%). 비헤지는 환율 ±5%가 1년 이자를 지우거나 두 배로. (출처: `screener/bonds.py` `recommend`, `reports/bonds.json` hedge_cost)
10. [교과서] 롤다운 ≈ D × (현재 만기 금리 − 1년 짧은 만기 금리). 국고 3Y 3.87·2Y 3.84 → 3bp × D 2 ≈ +0.06%/년(지금은 곡선 평평해 미미). 곡선이 가파를수록 커진다. (출처: Tuckman 8장 개념 `[확인 필요]`, `reports/bonds.json` kr.curve.now)

## 현업 vs 교과서
11. [교과서 vs 자체연구] "보유기간 ≈ 듀레이션이면 금리 중립(가격 손실 = 재투자 이익)"은 **개별 채권** 얘기. 상시 만기 ETF(국고채 3년 ETF D 2.8 고정)는 만기·pull-to-par가 없어 갭이 0으로 수렴하지 않는다. 성립하는 근사: 1회성 +100bp 뒤 약 D년(≈2.8년)이면 총수익이 원래 경로를 따라잡음 → "코어 3년물은 3년 이상 들고 가는 돈". 반복 인상이면 시계가 매번 재시작. (출처: CFA L1 'Interest Rate Risk and Return' `[확인 필요]`, `screener/bonds.py` ETFS 고정 듀레이션)
12. [교과서 vs 자체연구] 교과서 '채권 = 분산 자산'. 우리 `stock_bond_corr`(IEF–S&P 1년 상관, 임계 +0.2): 2026-10-16 +0.36(60일 +0.47), 국고 3년 ETF–코스피 +0.30 → "같이 빠지는 국면: 장기채 대신 단기·현금". 보험은 **성장 충격**(금리↓)에서만, **물가 충격**(2022형)에선 아님. (출처: registry `stock_bond_corr` C, `reports/bonds.json` corr/reco; Ilmanen growth/inflation `[확인 필요]`)
13. [교과서 vs 현업 관행] 기간구조 최소 이론 = "장기 금리 = 기대 단기 평균 + 기간 프리미엄". 10Y−2Y 한 숫자는 둘이 섞인 값 → 2Y·10Y 어느 다리가 움직였는지로 베어/불 × 스티프닝/플래트닝 4분면(터미널 `interpret`: m1 ≥ 10bp일 때 분류). 시장분할·선호서식지는 시험용 정의만. (출처: B7 모듈, `screener/bonds.py` `interpret`, Tuckman 8장 `[확인 필요]`)
14. [교과서] 역전 뒤 정상화가 더 위험하다는 통설: 정상화는 대개 단기 급락(불 스티프닝 = 인하 기대)으로 오고 그때가 둔화 시점과 겹친 사례가 많음. 한계: 전후 미국 침체 표본 8회 안팎, 시차 6~24개월. 코스피에 대한 예측력은 **미검증**. 터미널은 `min1y < 0`일 때만 "역전에서 정상화" 문장. (출처: Estrella & Mishkin 1996 `[확인 필요]`, `screener/bonds.py` `interpret`)

## 흔한 오해
15. [경험] "채권은 손실 없다"(금리 위험 ≠ 신용 위험: TLT 2022 −30%대 `[확인 필요]`) / "인하 = 채권 ETF 무조건 상승"(선반영·매파적 인하·장기 금리는 반대로) / "bp와 %p 혼동"(3.87%에서 −11.3bp = 3.757%) / "ETF도 만기까지 들면 회복"(만기 없음) / "kr_bbb 649bp = 위기"(상시 수준). (출처: `consult:bonds#q8·q11`)
16. [경험] 60/40을 'TLT 40'으로 짜면 2022형(주식 −20·금리 +100bp)에 −18.4%, '3년물 40'이면 −13.1% — 5%p가 듀레이션 선택의 값. (출처: `reports/bonds.json` duration scen, 산술)

## 터미널에서 보는 자리
17. [자체연구-검증전] 읽는 순서: `us.chg`/`kr.chg`(v·d1·w1·m1·y1 bp) → `spreads` → `duration`(scen·be_bp) → `corr` → `reco`. 칩 US2Y→US10_2(어느 다리?)→KR3Y→KRAA(변화)→KRBBB(변화만). 1개월 칩은 bp. (출처: `reports/bonds.json` 키 구조)
18. [자체연구-검증전] 금(비이자 헤지): 실질금리↓·위험 회피·달러 불신에 오름. 기회비용 = 실질금리. 주식·채권·금이 **같이** 빠지면 현금화(디레버리징) 신호. macro 점수 가중 0.4. 코어에선 상한(예: 15%)을 둔 비중 — 상한은 분산 숫자가 아니라 '조정 요구를 막는 행동용 숫자'. (출처: `screener/macroview.py` GOLD 해설, CIO 답변 q8/q15)

## 우리 연구와의 차이
21. [현업 관행·공시 vs 자체연구] KODEX 국고채3년(114260) 기초지수 = MKF 국고채 지수(총수익), 구성 = **3년 국채선물 최근월물 바스켓 국고채 3종**(운용사 2026-09-30 월간보고서). KRX/funETF 공시 듀레이션 2.96(2026-07-07 스냅샷) — 우리 코드 상수 2.8과 0.16 차이(+100bp에 −2.8% vs −3.0%). 바스켓이 선물 롤마다 바뀌므로 D는 약 2.6~3.0 사이를 오가는 **구간**이지 상수가 아니다. 따름: 교육·라벨엔 "D≈2.8 근사"로 두고 `etf_rate_label` 한 줄에 '근사' 명시; 월 1회 공시값과 대조. (출처: 삼성자산운용 2ETF19 월간보고서 2026-09-30, funETF KR7114260003 — 2차 열람, 지수 방법론 원문 `[확인 필요: MKF 지수 편입·롤 규칙, 2026-10-31까지]`; 반대 근거: 상수 라벨은 롤 시점 ±0.2년 오차를 숨김 → '근사'·구간 명시로 대응; 뒤집는 조건: 공시 D 2.5 미만/3.1 초과 2개월 연속이면 상수 교체; 신뢰도 중)
22. [자체연구-검증전] 결재 #15 ③ 반영: `reports/bonds.json` `etf[]`·`vehicles[]`에 `maturity`("없음(상시 듀레이션)" / "있음")와 `rate_line`("금리 +100bp → 가격 약 −2.8% (+50bp −1.4%) · D≈2.8 근사 · 만기 없음") 필드 추가(`screener/bonds.py` `etf_rate_label`, 테스트 `tests/test_bonds_etf_label.py`). 개인투자용 국채는 '만기 있음·시가 평가 없음'으로 분리. 단기채 대체 비교표 = `docs/bonds_short_duration_alts.md`(비율만). 화면 열 추가는 `apps-script/tab_bond.html` 잠금 필요 → 미반영. 영향 범위: bonds.json 필드 추가만(기존 키 불변, 탭·알림 무관). 롤백: `git revert 917e4292`.
19. [자체연구-C] `stock_bond_corr`는 서술 통계(n=250)로 C. 비중 결정엔 쓰지 않고 **듀레이션 선택(3년 vs 10년)** 참고만. 비중은 연 1회 리밸런싱 규칙. (출처: registry `stock_bond_corr`)
20. [자체연구-검증전] 역전·스프레드 확대의 코스피 예측력, `ai_credit` 경보의 적중률 — 모두 미검증. 교육 모듈엔 '경보·참고'로만 쓰고 "팔아라"로 번역하지 않는다. (출처: registry `ai_credit`, `rule_audit.md` #17)

## 출처
- 교과서: Tuckman & Serrat *Fixed Income Securities* 4판(Wiley 2022) 4장 DV01·듀레이션·컨벡시티, 5장 key-rate, 8장 기간구조(목차 확인, 본문 `[확인 필요]`) / Fabozzi *Bond Markets, Analysis and Strategies* 10판 가격·듀레이션·기간구조·신용 장 `[확인 필요]` / CFA L1 Fixed Income(Yield Measures, Term Structure, Interest Rate Risk and Return, Credit Risk) `[확인 필요]` / Estrella & Mishkin 1996 `[확인 필요]`.
- 자체: `screener/bonds.py`(`par_bond`·`dur_only`·`corr`·`interpret`·`recommend`·`guide`·`vehicles`·`credit_alert`·`ai_credit`), `reports/bonds.json`(2026-10-16), `views/registry.json`(`stock_bond_corr` C·`ai_credit` 검증전), `content/study.json` 0-6·A3·B7.

## 복기 (틀린 판단 → 왜 → 다음부터)
- 2026-10-16 · 틀린 판단 없음(채점 대상 판단 미발행). 점검에서 발견한 누락: 교육 모듈 0-6·A3 어디에도 "채권 ETF는 만기가 없다(상시 듀레이션·pull-to-par 없음)"가 없었다 → 학습자가 코어 ETF를 개별 채권처럼 "만기까지 들면 회복"으로 오해할 경로. 다음부터: ETF를 언급하는 모든 답변·KB 항목에 '상시 만기' 단서를 붙인다.
- 2026-10-17 · 애매했던 판단: ETF 듀레이션을 '상수 2.8'로 코드와 KB(#6·#11)에 적어 왔다. 공시값은 2.96(7월)으로 롤 주기에 따라 움직이는 구간값 → 교육 답변에서 "−2.8%"를 소수점까지 확정처럼 말한 것은 과한 정밀도. 다음부터: ETF 금리 민감도는 "약 −3%(D 2.6~3.0)"처럼 **구간+근사** 표기, 액면채 계산값(`par_bond`)만 소수점 둘째 자리.
