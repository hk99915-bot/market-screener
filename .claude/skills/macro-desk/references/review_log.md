# 성격·복기·10년차 기준·출처

(원본: docs/desk_kb/macro.md 해당 절을 그대로 옮김 — 2026-10-31 스킬 시범. 내용 수정은 양쪽 같이. 번호 = `kb:macro#<n>`.)

## 성격·성향
- **한 줄:** 자기 지표가 라벨 한 줄로 잘려 인용되는 것을 가장 경계하는 맥락 보충형. "금리 하락 하루를 추세로 번역하지 말 것."
- **맹점:** '서프라이즈'를 컨센서스 없이 사용, 표기 규칙을 KB에만 쓰고 코드 방치(복기 10/17). **긴장:** ↔FRM — 금 비중 축소분 행선지. 원본 [PERSONAS.md#macro](PERSONAS.md#macro)(요약, 연기 지시 아님).

## 복기 (틀린 판단 → 왜 → 다음부터)
- 2026-10-16 · 아직 채점된 판단 없음(매크로 바람 성적은 `macro_view.json` track이 쌓이는 중). 다음부터: 바람 라벨을 인용할 때 항상 '검증전'과 코스피–S&P 격차를 같이 적는다 — 중립 라벨만 보면 오늘 같은 한국 고유 급락을 놓친다.
- 2026-10-17 · 2026-10-16 KB 13번에 "`prev`보다 높으니 서프라이즈"를 오해로 적어 놓고도 코드는 '직전'·'이전'·'전월' 세 가지 표기가 파일마다 달랐고(committee.py / calendar_ev.py) 격차는 summary에만 있었다 → 규칙을 KB에만 쓰고 생성 코드를 한 곳으로 모으지 않음 → 다음부터: 표기 규칙은 함수 1개 + 금지어 테스트로 고정하고, KB '터미널에서 보는 자리'에 그 함수명을 적는다.
- 2026-10-17 · 금 vs 실질금리 검증을 하려 했으나 터미널에 TIPS(DFII10)·미 10년 시계열이 없고 세션에서 FRED·야후가 막혀 명목 프록시(IEF 역산)로 대체 → 원인: KB #6에 "TIPS 없음"을 적어 두고도 시리즈를 추가하지 않음 → 다음부터: 매크로 데스크가 쓰는 핵심 시계열(DFII10·T10YIE·DGS10)은 `prices/fetch_long.py` FRED 목록에 넣어 캐시로 보관하고, 프록시를 쓰면 문장에 "명목·프록시"를 붙인다.

## 10년차 기준 (2026-10-23 교육)
- 체크리스트: ① 서프라이즈는 컨센서스 대비로만 말하고, 컨센서스가 없으면 '직전 대비'·'가격 반응 z'로 바꿔 부른다(#1·#2) `[교과서: CFA L1 Economics]` ② 금리는 실질·기대인플레·기간 프리미엄으로 분해(DFII10·T10YIE·DGS10 상시 보관) `[교과서: Fed·FRED 시리즈 정의]` ③ 판단마다 '다음 발표(날짜) 때 무엇이면 뒤집나'를 같은 줄에 `[현업 관행: 나우캐스트·시나리오 노트]`
- 격차: 복기 마지막 10/17(6일 공백)·실질금리 시계열 미보관(복기 10/17 처방 미이행 여부 [확인 필요: prices/fetch_long.py FRED 목록에 DFII10 존재, 2026-10-30])·바람 점수 예측력 미채점.
- 드릴 [macro-d1]: reports/macro_view.json(10/23) 바람 −0.07 '중립', 20일 코스피 −20.8% vs S&P −0.5%. 운용회의 한 줄은? — 답·채점 키 `content/drills/macro.json`(라운드 파일에 `드릴: macro-d1 <내 답>` 을 먼저 쓰고 열 것, round_collect 채점 · G1 10/24)
- 2026-10-24 · 지정학 홍해 축에 "10월 신규 공격 보도 못 찾음"(10/23 22:31)이라 썼는데 같은 날 Reuters·WaPo·OilPrice 헤드라인이 후티-사우디 공격을 보도(피어 C2) → WebSearch 한 번만 보고 같은 패널의 자동 뉴스(geo_news.json)와 대조하지 않음 → 다음부터: 축 상태 문장을 쓰기 전 geo_news.json 해당 축 헤드라인을 먼저 읽고, 충돌하면 '재검토 필요'를 같이 적는다.

## 출처
- 교과서·공식 자료: Dalio "How the Economic Machine Works"(2013) / 한국은행 통화정책 파급경로·통화신용정책보고서(중립금리 재추정) / CFA L1 Economics(Business Cycles, Monetary and Fiscal Policy) / FRED 시리즈 노트(CPIAUCSL·CPILFESL·PAYEMS·UNRATE·PPIFIS·DGS10). 2차 자료·요약 확인, 원문 `[확인 필요: 원문 대조, 2026-10-30]`.
- 자체: `reports/views/analyst_cmdty.json`, `screener/commodities.py`, `reports/commodities.json`, `reports/views/geopolitics.json`, `screener/macroview.py`, `reports/macro_view.json`, `reports/macro_releases.json`, `screener/calendar_ev.py`, `reports/committee.json` macro, `views/registry.json`(`macro_wind`·`kr_regime`·`us10y`·`foreign_flow`·`event_calendar`).
