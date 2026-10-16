# macro 데스크 KB

(자문·연구 과정에서 추가. 형식은 README.md. 2026-10-16 교육 자문 `consult:macro` 답변에서 추출.)

## 정의
1. [교과서] 서프라이즈 = 실제 − 컨센서스. 표준화 서프라이즈 z = 서프라이즈 ÷ 과거 서프라이즈 σ(지표 간 비교용). 시장은 수치가 아니라 **예상과의 차이**, 그리고 그 차이가 바꾸는 **금리 경로 기대**에 반응한다. (출처: A1 모듈; Citi Economic Surprise Index·Bloomberg 관행 `[확인 필요]`)
2. [자체연구-검증전] 터미널 `macro_releases.json`은 FRED `value` vs `prev`(직전 발표치) 비교 — **컨센서스 없음, 개정 전 잠정치**. '예상 대비'가 아니라 '직전 대비 방향'으로만 읽는다. 대용: 가격 반응의 이례성 — `macro_view.json` `z20`(20일 변화의 2년 분포 z), `committee.macro.changed`(하루 변화 ÷ 60일 σ). (출처: `screener/macroview.py` `_stats`, `screener/committee.py` `_zmove`)
3. [자체연구-검증전] 매크로 바람 점수 = Σ(W × 지표 impact −1~+1) ÷ ΣW. W: SPX 1·NASDAQ 1·RUT .5·VIX 1·US10Y 1·DXY .7·USDKRW 1·USDJPY .3·WTI .5·GOLD .4·BTC .3. 라벨 ≤−0.4 강한 역풍 / ≤−0.15 역풍 / ≥+0.15 순풍 / ≥+0.4 강한 순풍. 한국 지수(KOSPI·KOSDAQ)·닛케이·TOPIX·JGB는 **점수 제외**(결과이지 원인 아님 / 표시만). 가중치 사후 설정 → 참고만. (출처: `screener/macroview.py` `W`/`explain`/`build`, registry `macro_wind` 검증전)
4. [자체연구-C] 레짐(코스피): 하락장 = 200일선 아래 또는 20일 고점 대비 ≤ −15% / 회복 확인 전 = 200일선 위·20일선 아래 / 상승장 = 둘 다 위. 운용회의 macro.regime 문구는 200·50일선 대비 %를 같이 적는다. 역할: 위험 축소 스위치(노출 상한), 알파 아님. (출처: registry `kr_regime` C, `reports/committee.json` macro.regime)
5. [자체연구-검증전] 코스피 vs S&P 20일 격차: gap = KOSPI chg20 − SPX chg20. gap < −8%p면 "한국 고유 요인(반도체 쏠림·외국인 매도)", > +8%p면 "한국이 강함". 격차가 크면 요약에 "매크로 반전만으론 회복 근거 부족"을 붙인다. (출처: `screener/macroview.py` `explain` KOSPI 분기·`build` 요약)

## 공식
6. [교과서] 실질금리 ≈ 명목 − 기대인플레(피셔 근사). 10년 4.0 − BEI 2.5 = 1.5%. 금·성장주·신흥국 통화는 실질금리에 반응. 터미널에 TIPS·BEI 시리즈 **없음**(CPI 대용 시 명시). (출처: 0-4 모듈; FRED DFII10·T10YIE `[확인 필요]`)
7. [교과서] 할인율→멀티플: PER ≈ 1/(r−g). 10년물 +50bp → r 8→8.5%, g 4%: 25→22.2배(−11%); g 1%: −7%. 성장주가 더 민감. (출처: 고든 모형, CFA L1 Equity)
8. [교과서] 테일러 준칙 i = r* + π + 0.5(π−π*) + 0.5(y−y*). r* 1%→0.5%만 바꿔도 적정 금리 50bp 차이 — 결론은 **r* 가정**에 좌우. 0-4(수준 1)엔 넣지 않고 A2에만. (출처: A2 모듈; CFA L1 'Monetary and Fiscal Policy' `[확인 필요]`)
9. [자체연구-검증전] 지표별 점수 규칙(요지): SPX/NASDAQ = clip(chg20/6%)×0.6 + (50일선 위 +0.4/아래 −0.4) · US10Y = clip(−bp20/40)×0.7 + (5% 이상 −0.3) · USDKRW = clip(−chg20/3%)×0.6(원화 약세 = 역풍) · DXY = clip(−chg20/3%)×0.6 · VIX 계단(≥30 −1 … <15 +0.2, 5일 +25% 시 −0.3). (출처: `screener/macroview.py` `explain`)

## 현업 vs 교과서
10. [교과서 vs 자체연구] 교과서 파급경로(한국은행: 금리·자산가격·환율·신용·기대 경로)는 **수 분기 시차**; 여수신 금리는 기준금리만큼 움직이지 않음. 우리 macro 점수는 20일 가격 변화 — "경제에는 느리게, 가격에는 즉시(미래를 오늘 할인)". 같은 것을 다른 시계로 본다. (출처: 한국은행 통화정책 파급경로 — 2차 자료 확인, 원문 `[확인 필요]`; KDI 연구: 긴축은 시차를 두고 중소기업에 더 크게)
11. [교과서 vs 자체연구] Dalio 신용 사이클(지출 = 소득 + 신용, 금리로 조절)은 '왜'의 그림, 우리 macro는 '지금 어느 쪽'의 계기판. 신용 지표(스프레드·HYG/IEF·ai_credit)는 **채권 탭의 경보(alert)** 이며 macro 점수에 들어가지 않는다. (출처: Dalio 2013 `[확인 필요: 문구]`, `screener/macroview.py` W, registry `ai_credit` 검증전)
12. [현업 관행] '연준 의장 발언'을 **이벤트(imp 3 ★)** 로 추적하는 이유: 결정은 선물시장이 선반영하므로 가격을 움직이는 건 경로 힌트(톤)이고, 톤은 사전 예측 불가 → 결과 전 레버리지·방향 베팅 금지 규칙의 대상. (출처: `screener/calendar_ev.py` MACRO imp, `reports/committee.json` bottom_line.clock·stance.reasons '이벤트 대기', registry `personal.event_day_ban` C)

## 흔한 오해
13. [경험] "인하 = 호재" → 왜 내리는지(성장 둔화면 악재)와 경로. "점도표 = 계획" → 그때의 전망. "CPI 높음 = 매도" → 미국 장이 밤새 반영한 뒤 아침 한국장 추격은 '이미 반영된 가격에 반응'. "`prev`보다 높으니 서프라이즈" → 직전치 대비이지 컨센서스 대비 아님. (출처: `consult:macro#q6·q11`)
14. [경험] 같은 날 두 지표가 반대 방향이면(2026-10-15: PPI 6.35% 뜨거움 vs 비농업 29천 급랭) 금리 반응은 **더 크게 놀란 쪽**을 따른다(10년 −10bp, 60일 σ의 2.4배). 사후 해석임을 표시. (출처: `reports/committee.json` macro.releases/changed)

## 터미널에서 보는 자리
15. [자체연구-검증전] 1분 읽기: `committee.macro.changed`(이례적 변화) → `releases`(value vs prev) → `upcoming`(★) → `summary`(바람 + 격차 문장). 칩 US10Y/US2Y → 10Y−2Y 변화의 다리(2Y vs 10Y)로 베어/불 × 스티프닝/플래트닝 분류(`bonds.interpret`). (출처: `reports/committee.json` macro, `screener/bonds.py` `interpret`)
16. [자체연구-검증전] 한국 변수 중 먼저 볼 하나 = USDKRW. 미 금리↑·달러↑ → 원화 약세 → 외국인 환차손 → 매도 압력(수출주 이익 +보다 수급 −가 보통 큼). 한·미 10년 금리차(`spreads.krus_10`)는 장기 요인. 외국인 수급 자체의 예측력은 **검증전**(일별 이력 미저장). (출처: `screener/macroview.py` USDKRW 해설, registry `foreign_flow` 검증전)

## 우리 연구와의 차이
17. [자체연구-검증전] 매크로 바람과 코스피: 2026-10-16 바람 중립(+0.10)인데 코스피 20일 −15.2%(S&P +1.4%) — 매크로 점수는 **한국 고유 충격(업종 쏠림)을 못 잡는다**. 바람은 참고, 레짐(C)이 상한. 바람 점수의 예측력은 lab MACRO_TILT 대기(데이터 부족). (출처: `reports/macro_view.json`, registry `macro_wind`)

## 출처
- 교과서·공식 자료: Dalio "How the Economic Machine Works"(2013) / 한국은행 통화정책 파급경로·통화신용정책보고서(중립금리 재추정) / CFA L1 Economics(Business Cycles, Monetary and Fiscal Policy) / FRED 시리즈 노트(CPIAUCSL·CPILFESL·PAYEMS·UNRATE·PPIFIS·DGS10). 2차 자료·요약 확인, 원문 `[확인 필요]`.
- 자체: `screener/macroview.py`, `reports/macro_view.json`, `reports/macro_releases.json`, `screener/calendar_ev.py`, `reports/committee.json` macro, `views/registry.json`(`macro_wind`·`kr_regime`·`us10y`·`foreign_flow`·`event_calendar`).

## 복기 (틀린 판단 → 왜 → 다음부터)
- 2026-10-16 · 아직 채점된 판단 없음(매크로 바람 성적은 `macro_view.json` track이 쌓이는 중). 다음부터: 바람 라벨을 인용할 때 항상 '검증전'과 코스피–S&P 격차를 같이 적는다 — 중립 라벨만 보면 오늘 같은 한국 고유 급락을 놓친다.
