# data 데스크 KB

(자문·연구 과정에서 추가. 형식은 README.md)

## 정의
- **companyfacts 태그 전환(tag switch)**: 한 회사의 같은 재무 항목이 연도에 따라 다른 us-gaap 요소로 태그되는 현상. 대표: ASC 606(2018 회계연도부터) 도입 때 매출이 `SalesRevenueNet`/`Revenues` → `RevenueFromContractWithCustomerExcludingAssessedTax` 로 옮겨감. 태그를 하나만 고르는 파서는 옛 연도 또는 새 연도 한쪽만 얻는다. `[규정]`

## 공식

## 현업 vs 교과서

## 흔한 오해
- "매출 태그는 회사당 하나" — 아니다. 10-K 의 전년 비교치까지 같은 companyfacts 에 들어오므로 전환 연도 전후 태그가 공존하고, 분사 신설 법인(SNDK 형)만 태그가 하나다. 파서는 태그 전부를 합치고 같은 분기말만 우선순위로 골라야 한다 (2026-10-17 수정, `screener/sec.py parse()`). `[자체연구-A: 합성 companyfacts 테스트 2건 통과, 실데이터 54.23B 대조는 검증전]`
- "값이 분기마다 단조 증가하면 누적(YTD) 버그" — 아니다. 신설 법인·고성장 분기도 같은 모양이 난다. 모양 휴리스틱(CUM_RATIO)은 '검증전' 표시만, 판정은 원문(8-K/10-Q) 대조 파일(universe/fin_verified.json)이 한다. `[경험 2026-10-16~17]`

## 터미널에서 보는 자리

## 우리 연구와의 차이

## 애널 요청 (2026-10-17, 애널리스트 데스크 → 데이터 데스크, 보드 `mu-revenue-tag`)

**증상**: data/fin/us_quarterly.parquet 에 MU 의 item 이 `liab, op, assets, ni, cfo, equity, da, shares, capex, cash, div_paid` 뿐이고 `revenue` 행이 하나도 없다 (SNDK 는 있음). 그래서 valuation 표의 MU 가 "매출 —", 매출 YoY·OPM 공란.

**원인 분석 (코드만 보고 — SEC 원문은 이 세션 네트워크(data.sec.gov 403)로 확인 못 함 → 아래 가설 1·2 중 어느 쪽인지 `검증전`)**

1. `screener/sec.py parse()` 의 FLOW 루프는 태그 목록 `["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet", "RevenueFromContractWithCustomerIncludingAssessedTax"]` 를 순서대로 돌다가 **분기를 하나라도 만든 첫 태그에서 `break`** 한다. MU 처럼 회계 기준 변경(ASC 606, FY2019) 전후로 태그가 바뀐 회사는 앞선 태그(`Revenues` 또는 `SalesRevenueNet`)가 **옛 연도 분기만** 만들고 루프가 끝나며, 최신 태그는 시도조차 안 된다. 그 뒤 `update()` 의 `r["end"] >= "2019-01-01"` 필터가 옛 분기를 전부 버리면 결과가 '매출 0행'이 된다 — 증상과 정확히 일치. (SNDK 는 2025 분사 신설 법인이라 태그가 하나뿐이어서 걸리지 않음.)
2. 대안 가설: MU 의 총매출 fact 가 제품 차원(DRAM/NAND 멤버)으로만 태그되고 비차원 합계가 없을 가능성 — companyfacts 는 비차원 fact 만 주므로 그러면 어떤 태그로도 안 잡힌다. 다만 10-K 손익계산서 총매출 줄은 보통 비차원이라 가능성 낮음.

**제안 (수정은 데이터 데스크)**: `break` 대신 **태그별 분기를 합치고 같은 분기말은 앞선 태그 우선**(dict 병합: 뒤 태그 `setdefault`). 한 줄이 아니라 루프 구조 변경이고 tests/test_sec_parse.py 에 "태그 전환 회사" 케이스 추가가 필요해 애널이 대리 수정하지 않음. 검증 방법: `SEC_USER_AGENT` 환경에서 CIK0000723125 companyfacts 의 네 태그별 `end` 최소·최대 연도를 출력하면 가설 1·2 가 바로 갈린다. 수정 후 FQ4(2026-09-03) 매출이 fin_verified.json 54.23B 와 1% 안에서 맞아야 한다.

**같이 봐 줄 것**: SK하이닉스 2026Q2 DART 단독분기(fin.quarterly)가 매출 79.3조 < 순이익 93.8조. 영업 외 대형 이익이 아니면 분기 차감(누적−전분기) 오류 의심 — 사업보고서 원문 대조 요청. valuation 런레이트 PER 2.4 가 이 숫자에 기대고 있어 노트에는 ⚠ 표기. `[자체연구-검증전]`

## 복기
- **2026-10-17 'YTD 누적 버그' 판정** — 틀림: 10/16 14:47 MU ni 5.2→13.8→28.2→37.7 모양만 보고 P0 "파서 결함"으로 올렸고, 15:25 수정 때 넣은 모양 가드(CUM_RATIO 1.8)가 SNDK revenue 3.0→6.0→9.0 을 같은 누적 버그로 '검증전' 처리했다. → 왜: MU 는 실제 누적치 누수(맞음)였지만 SNDK 는 분사 직후 정상 성장이었고, 두 경우를 모양으로는 구분할 수 없다는 걸 원문(8-K) 대조(23:43) 전까지 인정하지 않았다. → 다음부터: 파서 버그 의심은 (1) start/end 기간(일수)으로 누적 여부를 **구조적으로** 판정하고, (2) 모양 휴리스틱은 플래그만, 확정·해제는 fin_verified.json 원문 대조로만 한다. 같은 날 MU '매출 0행'도 모양이 아니라 코드 경로(첫 태그 break)로 먼저 확인했다.

## 출처
- FASB ASC 606 / us-gaap 2018 taxonomy: `SalesRevenueNet` 등 옛 매출 요소 deprecated, `RevenueFromContractWithCustomerExcludingAssessedTax` 신설 `[규정]` (이 세션은 외부망 제한으로 원문 재확인 못 함 — 다음 라운드 원문 링크 보강)
- screener/sec.py FLOW/INSTANT 태그 매핑, parse() 루프 (2026-10-17 기준 코드)
