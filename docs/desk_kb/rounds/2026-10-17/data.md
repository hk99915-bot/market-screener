# 데이터 데스크 — 라운드 1 (2026-10-17)

1. **읽기** — data.md(애널 요청 포함)·README·LOOP·_scoreboard·ops/LOCKS·보드 `mu-revenue-tag`/`sec-ytd-bug`. 피어 개발(dev.md)은 파일이 아직 없음 → 요청으로 대체.
2. **배우기** — us-gaap 2018 택소노미(ASC 606)에서 `SalesRevenueNet` 계열 deprecated, `RevenueFromContractWithCustomerExcludingAssessedTax` 신설 → 한 회사 안에서 매출 태그가 연도별로 갈린다 `[규정]`. KB '정의·흔한 오해'에 추가 (외부망 제한으로 원문 링크는 다음 라운드).
3. **고치기** — `screener/sec.py parse()`: FLOW 태그 루프의 첫-태그 `break` 제거, 태그별 분기 병합(같은 분기말은 앞선 태그 우선). 테스트 2건 추가(`tests/test_sec_parse.py::test_revenue_tag_switch_merges_old_and_new_tags`, `::test_revenue_same_quarter_end_earlier_tag_wins`). 보드 `mu-revenue-tag` 진행→검수 (실데이터 54.23B 대조는 다음 SEC 워크플로 실행 후).
4. **피어(개발)** — 반대/요청: 결재 #10 ② 보존 규칙(archive 90일·signals/anomalies 10일)을 워크플로 커밋 단계에 "한 줄 find -delete"로 넣는 제안은 반대 — 드라이런·목록 출력 없는 삭제는 되돌릴 수 없다. `scripts/retention.py`(드라이런 기본, `--apply` 시만 삭제, 삭제 목록을 reports/logs 에 남김)로 만들어 워크플로는 그 스크립트만 부르자. 데이터 데스크가 다음 라운드에 초안 가능.
5. **복기** — 'YTD 누적 버그': 모양(단조 증가)만으로 P0 판정 + 모양 가드가 SNDK 정상 성장을 오탐 → 구조(기간 일수)로 판정, 모양은 플래그만, 확정은 원문 대조. KB `## 복기`.

요청→개발: `scripts/retention.py`(드라이런 기본) 를 ops 워크플로에 어떻게 붙일지(실행 시점·--apply 승인 경로) 설계 의견 1줄 + dev.md KB 신설.
