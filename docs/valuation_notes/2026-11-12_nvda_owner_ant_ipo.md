<!-- short: 젠슨 리스크·ANT 상장 -->
<!-- oneliner: 젠슨 지분 3.4%·2026 시장매도 0, ANT 공모 578~644억$ — 수급·지배구조 이벤트 겹침 -->
<!-- kpi: NVDA 20일 ln −0.30(전부 배수) · ANT 기본주 시총 9,161~10,208억$ · 컴퓨트 약정 9,009억$ -->
# 젠슨 리스크·ANT 상장 겹치나? (검증전)
**이해상충 고지: 이 분석을 지시한 PB 세션과 작성 데스크는 Anthropic이 만든 AI(Claude)다. Anthropic 서술은 원문 인용·숫자 위주, 가치 판단엔 반대 근거 병기. 회사 자체 투자 의견 없음.**
애널 데스크 · 기준 2026-11-12 09:10 KST · 요청 겸이 11/12 09:01 · 매매 지시 아님 · 개인 금액·보유 0건 · 매크로(금리·레짐) 해석은 macro 데스크 몫
출처 등급: `[1차]` SEC EDGAR·회사 IR 원문 / `[2차×2]` 기사 2곳 이상 일치 / `[2차×1]` 1곳 → 미확인 취급 / `(애널 환산)` 원문 입력으로 계산

## 결론 줄
- NVDA · PER TTM 21.3 / 런레이트 17.2 / 컨센 다음분기×4 17.1(야후 추정, 가이던스 아님) / 정규화 26.9 · E/P−rf −0.28%p · 20일 분해 ln −0.302 = 전부 배수(EPS 변화 0, 검증전) · 등급 검증전 · 신뢰도 중 · 뒤집을 숫자: NVDA 8-K Item 5.02(CEO 변경) 접수 여부
- 입력: `reports/valuation.json`(가격 11/10 168.89$, EPS TTM 7.94·런레이트 9.82, US10Y 4.98%) · 정규화 EPS 6.28$(`reports/detail/US/NVDA.json`, 5년 평균 ROE 66.6%)

## What
- NVDA: 11/8 Huang 사내 서한 "I was unfaithful to my wife"·이사회 독립 조사 착수 [1차 IR] · 11/10 독립이사회가 Joon H. Kim·Wachtell 선임 [1차 IR] · 11/11 종가 173.73$, 5일 −13.2%·20일 −21.5% (`NVDA.json`)
- Huang 2026 Form 4 5건 중 시장 매도(코드 S) 0건, 2026 10b5-1 채택 공시 없음(FY26 10-K 9B·FY27 1Q·2Q 10-Q Item 5) [1차]
- ANT: S-1/A 2호(11/10) 825백만주·주당 70~78$, 동시 사모 260억$(NVIDIA 100억$ 포함) [1차] · 9M26 매출 332.4억$·영업손실 −12.6억$·순손실 −1,040억$ [1차]
## So What
- 오너 리스크 본질 = 지분 매도 물량이 아니라 경영 공백·규제(대중 수출) 경로. 지분 3.37%(애널 환산)로 지배력 없음 → 이사회가 교체 가능 구조
- ANT 상장 = AI 주식 공급 이벤트: 공모 578~644억$ + 그린슈 87~97억$ (애널 환산), 10/26 메타 발행 350억$ 포함 4주 합산 약 928~1,091억$
- 유의: NVDA 20일 하락은 11/8 이전부터 진행(3개월 −25%, `chains_view.json`) → 스캔들 단독 효과 분리 불가(표본 n=1)
## Now What
- 11/18 07:00 KST NVDA 3Q FY27 실적 [1차 IR 공지] / 애널 / 11/18 / 가이던스 하향 + CEO 변경 동시면 '오너+펀더멘털' 이중 훼손 판정
- ANT 가격 결정(11/18 미국, [2차×2] 보도) / 애널 / 11/19 / 범위 하단 70$ 미만 결정 시 AI 랩 조달 비용 상승 쪽 재판정
- 3Q FY27 10-Q Item 5(Huang 10b5-1 신규 여부) / 애널 / [확인 필요: NVDA 10-Q 접수, 2026-11-25]
- 조치 없음(실계좌): 매매 판단 아님 · 관찰 꼬리표

## 1. 엔비디아 오너 리스크 — 정량
| 항목 | 값 | 출처 |
|---|---|---|
| Huang 보유 | 870,604,104주 = 3.58% (3/23 기준) | [1차] DEF 14A 2026-05-12 |
| Huang 보유(최신) | 811,521,160주 (10개 보유 줄 합) | [1차] Form 4 9/18 접수 (애널 합산) |
| 지분율·평가액 | 811.5백만 / 24.1십억주 = 3.37% · ×168.89$ = 약 1,371억$ | 10-Q 8/21 주식수 (애널 환산) |
| 2026 처분 내역 | 세금 원천징수(F) 529,359주 · 기부(G) 838,000주 · 시장 매도 0 | [1차] Form 4 3/4·3/20·6/18·6/23·9/18 |
| 2025 12/18 이전 | 39,850,418주 → 독립 운용 LLC 이전, "no longer beneficially owns" | [1차] Form 4 2025-12-19 |
| 2025 10b5-1 | 2025년 말까지 최대 600만주 매도 계획 | [2차, 원문 미열람] 검색 요약(StockTwits·iTiger) → 미확인 |
| 승계 공시 | 10-K "highly dependent on … longstanding executive team" 일반 문구만, proxy에 승계 계획 문구 없음 · 의장 없이 Lead Director 체제 | [1차] 10-K FY26 · DEF 14A |
| 경영진 변동 | EVP 현장영업 Puri 은퇴 통보(6/28)·후임 Parker 선임(7/1) | [1차] 8-K 2026-07-02 |
- 870.6 vs 811.5백만주 차이 59.1백만주 원인 미확인(GRAT 이전 58.96백만주와 근접 — 집계 기준 차이 추정[가정: proxy 이중 계상 또는 기준일 차])
- 이사회 축출 준비 보도: WSJ 원출처를 Fortune·Japan Times가 전언 → 원출처 1곳이라 미확인 · 11/12 00:10 UTC 기준 NVDA 8-K 신규 접수 없음 [1차 EDGAR]
- 의회 소환·상원의원 사임 요구·대중 수출 규제 강화 움직임: CNBC [2차×1] → 미확인
- 공급자=투자자 쪽 기존 사례: NVIDIA, OpenAI 임차 SB Energy 부지에 잔존가치 보증 최대 1,050억$ [1차] 8-K 2026-08-17

## 2. 앤트로픽 상장 — 일정·규모·밸류에이션
| 출처 | 기준 | 시가총액 | 등급 |
|---|---|---|---|
| S-1/A 2호 | 기본주 13,086,672,593 × 70~78$ | 9,161~10,208억$ (중간 74$ 9,684억$) | [1차] 입력 (애널 환산) |
| S-1/A 2호 | 그린슈 포함 13,210,422,593 × 78$ | 10,304억$ | (애널 환산) |
| Yahoo·SoftTechHub(제목)·CNBC(전언) | 완전희석 상단 | 최대 약 1.4조$ | [2차×2, 원문 미열람] |
| WSJ(범위 공시 전) | 조달 1,000억$+·1.5~2조$ | — | [2차×1] 미확인 |
| 우리 11/1 파일 | 출처 상충 3,500억$ vs 9,650억$ | — | `rounds/2026-11-01/analyst_company_links.md` |
- 일정: 가격 결정 11/18·거래 11/19(미국) [2차×2: CNBC 전언·FinanceFeeds 제목, 원문 미열람] · 회사 미확정, S-1/A 날짜 칸 공란 [1차]
- 회사 순수입 약 846억$(공모+사모, 74$ 가정), 그린슈 행사 시 937억$ [1차] · 공모 중 기존 주주 매출 23,648,646주(회사 수입 아님)
- 시총/런레이트 매출: 9,161~10,208 / 678(3Q 169.6억$×4) = 13.5~15.1배 (애널 환산) — 반대 근거: 3Q 영업손실 −5.7억$, 2Q만 흑자(+9.7억$) [1차]
- 순손실 −1,040억$ 중 −943억$ = 전환사채·파생 공정가치 변동(비현금) [1차] · 9M26 영업현금흐름 +65.7억$ [1차]

## 3. 손실·컴퓨트 약정(take-or-pay)·순환 구조
| 항목 | 원문 수치 | 성격 |
|---|---|---|
| 총 약정(9/30 이후 포함) | 9,009억$ — 2030년까지 4,516억$, 향후 12개월 707억$ | [1차] 비취소 구매·리스 |
| 약정/런레이트 매출 | 9,009/678 = 13.3배 · 12개월분 707/678 = 1.04배 | (애널 환산) |
| NVIDIA GPU 경유 | SpaceXAI 최대 1,205억$(초기 비취소 기간 2027-01·03 종료) · Nscale 446억$(조달 최선노력 조건) · Lambda 413억$(이 중 349억$ 시설 임차 실패 시 해지) | [1차] 합 2,064억$ (애널 환산) |
| 동시 사모 260억$ | 구글 100·NVIDIA 100·AMD 25·브로드컴 10·마이크론 10·MS 10·TSMC 5억$ | [1차] 공모가 동일, 락업 비대상·제한증권 |
| 대주주(클래스N) | 아마존 19.2억주(14.7%)·구글 17.9억주(13.7%, 사모 포함) | [1차] 주식수 (비율 애널 환산) |
- 순환 배수: NVIDIA 사모 100억$ 대비 NVIDIA GPU 경유 약정 2,064억$ = 20.6배 (애널 환산) · 사모 100억$ = NVDA 시총 4.10조$의 0.24%
- 해석 유의: 2,064억$ 중 해지·조건부 비중 높음 → GPU 수요 '확정' 근거 불가(10/26 CIO 판정 유지, `rounds/2026-10-26/cio_s1_risk.md`)

## 4. 상장일 전후 수급
- 락업: 약 155억 주(클래스A 환산) 최대 180일, 공동창업자·지분 0.5% 초과 주주 최대 365일 [1차]
- 그중 36억 주는 180일 전 해제 가능, 비창업 임직원 락업분 최대 10% 상장 첫날부터 매도 가능 [1차]
- 180일 만료 약 2027-05 중순 [가정: 투자설명서 11/18일자] · 아마존 전환사채 잔여분 분기마다 클래스N 전환 [1차] = 상시 공급
- 유통 비율: 공모 825백만 / 클래스A 7,428백만 = 11.1%, 전체 13,087백만 대비 6.3% (애널 환산) — 저유통 고밸류
- 리테일 배정 약 20% [2차×1 CNBC] 미확인
- 나스닥100 fast entry: 상장 7거래일째 시총 순위 상위 40 판정, 15거래일 뒤 편입, 5월 1일 시행 [2차×2 Reuters(BNN) 원문·Bloomberg 검색 요약]
  - ANT 적용 시 7거래일째 ≈ 11/30, 편입 ≈ 12/11 전후 [가정: 11/19 상장·추수감사절 휴장] · 12월 정기 재구성(12/18 주) 충돌 시 연장 가능 [2차]
  - 미확인: 지수 산입 주식수(상장 클래스A만인지)·편입 비중 — Nasdaq 방법론 원문 [확인 필요: Nasdaq-100 방법론 PDF, 2026-11-20]
  - S-1 위험요인: 다중 클래스 구조로 일부 지수 편입 불가 가능 문구 [1차]

## 5. 이벤트 → 엔비디아·AI 인프라·NDX 경로
| 경로 | 방향 | 근거 등급 |
|---|---|---|
| 공모 자금 마련 매도(대형 AI주 차익 실현) | NVDA·AI 인프라 ➖ 수급 | 해석(검증전), 메타 발행 때 '수급 악재·수요 호재 분리' 판정과 동일 틀 |
| ANT 공모가 = AI 수요의 시장 가격 | 높게 결정 시 AI 인프라 ➕ 배수 / 낮게 결정 시 ➖ | 해석 |
| 사모 참여(NVIDIA·AMD·마이크론·TSMC) | 고객 지분 매입 = 매출 질 저하 신호, 규모는 NVDA 시총 0.24% | [1차] 수치 + 해석 |
| NDX fast entry | 지수 추종 자금이 ANT 매수·기존 종목 비례 매도 | 메커니즘 [2차×2], 규모 미확인 |
| Huang 리스크 | 대중 수출·경영 공백 → NVDA 배수 할인 | 사실(IR) + 미확인(축출·규제) |
- 우리 포트 경로: ISA 코어 15%(NDX) → NVDA의 NDX 비중(미확인, SOXX 내 6.81% `valuation.json`) × NVDA 충격 + ANT 편입 시 기존 종목 희석 매도 — 행동 지시 아님

## 6. 세 칸 정리
| 사실(원문) | 해석(애널) | 모름 |
|---|---|---|
| Huang 3.37~3.58%, 2026 시장 매도 0, 10b5-1 신규 공시 없음(7/26까지) | 매도 물량 리스크 작음, 리스크는 경영 공백·규제 | 3Q FY27(7/27~10/25) 10b5-1 채택 여부 |
| 이사회 독립 조사·외부 로펌 선임, "confidence in Jensen"(11/8) | 단기 결론 유보 → 실적일까지 할인 지속 가능 | 축출 여부·후임·조사 기한 |
| ANT 70~78$·825백만주·사모 260억$, 9M 순손실 1,040억$ | 공급 이벤트 + 수요 가격 발견 동시 | 최종 가격·상장일·NDX 산입 주식수 |
| 약정 9,009억$, NVIDIA GPU 경유 2,064억$ 일부 해지형 | GPU 수요 '소프트' 부분 존재 | 해지형 계약 실제 전환 여부(R6, 2027-03-31) |

## 7. 반대 방향 쌍 (등급 검증전, 확률 미부여)
- 낙관: 조사 결과 기밀 침해 없음 + Huang 유지 또는 질서 있는 승계 + 11/17 실적 상회 → 오너 할인 해소, ANT 범위 상단 가격 결정이 AI 수요 가격 확인 → AI 인프라 배수 회복
  - 뒤집힘 숫자: NVDA 8-K 5.02 미접수 + ANT 78$ 이상 결정
- 비관: 축출·후임 부재 + 대중 수출 규제 강화 + ANT 공모·NDX 편입이 대형 AI주 수급 흡수 → 상장 후 ANT 하락 시 AI 랩 조달 비용 상승 → 해지형 GPU 약정 의문 확대
  - 뒤집힘 숫자: CEO 변경 8-K + ANT 70$ 미만 결정 또는 상장 후 공모가 하회
- 이해상충 반대 근거: 작성자가 Anthropic 모델이라 ANT 수요 쪽 해석에 낙관 편향 가능 → 해석 칸은 피어 검토 전 확정 금지

원본: [ANT S-1/A 2호](https://www.sec.gov/Archives/edgar/data/2130357/000162828026072484/anthropicpbc-sx1ax2.htm) · [NVDA DEF 14A](https://www.sec.gov/Archives/edgar/data/1045810/000104581026000036/nvda-20260512.htm) · [NVDA 10-Q 2Q FY27](https://www.sec.gov/Archives/edgar/data/1045810/000104581026000075/nvda-20260726.htm) · [Huang Form 4 목록(CIK 1197649)](https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0001197649&type=4) · [NVDA 8-K 8/17](https://www.sec.gov/Archives/edgar/data/1045810/000104581026000069/nvda-20260817.htm)
- IR: [A Message to Our Company](https://nvidianews.nvidia.com/news/a-message-to-our-company) · [이사회 성명 11/8](https://nvidianews.nvidia.com/news/statement-from-nvidia-board-of-directors) · [독립이사 성명 11/10](https://nvidianews.nvidia.com/news/statement-from-the-independent-members-of-the-nvidia-board) · [3Q 실적 일정](https://investor.nvidia.com/news/press-release-details/2026/NVIDIA-Sets-Conference-Call-for-Third-Quarter-Financial-Results/)
- 2차: [Fortune 11/11](https://fortune.com/2026/11/11/nvidia-oust-jensen-huang-spy-affairs/) · [Japan Times 11/12](https://www.japantimes.co.jp/business/2026/11/12/tech/nvidia-jensen-huang-affairs/) · [CNBC 11/11](https://www.cnbc.com/2026/11/11/nvidia-jensen-huang-congress-resign-ai-chips.html) · [Yahoo 범위](https://finance.yahoo.com/markets/stocks/articles/anthropic-sets-ipo-price-range-140602411.html) · [FinanceFeeds](https://financefeeds.com/anthropic-ipo-date-price-range-70-78-trading-19-november/) · [Reuters/BNN fast entry](https://www.bnnbloomberg.ca/business/2026/03/30/new-nasdaq-rules-to-include-fast-entry-for-new-listings-on-benchmark-index/) · [iTiger 2025 계획](https://www.itiger.com/news/1190569199)
- 내부: `reports/valuation.json` · `reports/detail/US/NVDA.json` · `rounds/2026-10-26/{analyst_s1_risk,analyst_ai_funding,cio_s1_risk}.md`
