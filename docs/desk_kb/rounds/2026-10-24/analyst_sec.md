# analyst — SEC 커버리지 확장 (2026-10-24 00시대, 겸이 "sec 데이터 대체 언제 받아올 거야!")

**사과·원인:** 10/16 23:02 요청 → 마감 10/21 을 3일 넘겼다. 보드 ra-sec-coverage 가 담당 '데이터'·시작일 공란·'대기'로만 걸려 있었고, 요청을 받은 애널이 담당을 잡지 않아 아무도 착수하지 않았다(10/21 P1 승격 후에도 무착수). 10/16 수집분은 우선 목록 9종목(MU·SNDK·INTC·AMD·TXN·AMAT·KLAC·ADI·LRCX)뿐이었다.

1. **구성 확정** — 소스 = 운용사가 SEC 에 낸 N-PORT-P(보유 전 종목·순자산 비중). SOXX 기준일 2026-06-30(acc 0002071691-26-019781), PSI 2026-07-31(acc 0001209466-26-001443). 운용사 웹 CSV 는 이 컨테이너에서 HTML 만 반환(iShares)·406(Invesco)이라 N-PORT 사용 — 최대 약 3개월 지연. 주식 합집합 48 + SNDK(겸이 지정, 두 N-PORT 보유 목록에는 없음) = **49종목** → `universe/semis_basket.json`(ISIN 대조). CIK 매핑 49/49.
2. **수집** — `screener/sec.py` 기존 스키마 그대로. 바스켓 커버리지(parquet 에 있는 종목): **21/49 → 49/49**, 전체 parquet 526 → 558종목. 오늘 밤 2배치 실행(UA·초당 약 6회): ①80(companyfacts 80) ②80(companyfacts 73·증분 생략 7) + 20-F 7종목 상태 재분류 → 새 체계 확인 153/560. NXPI·AMKR·RMBS 는 companyfacts 에 2026 Q2 10-Q 가 아직 없음(SEC API 측, 최신 분기 03-29~03-31) → '재무 오래됨' 검증전. 분기 손익이 안 나오는 7종목 = IFRS 20-F(TSM·ASX·UMC)·US-GAAP 20-F 연간만(ASML·STM·NVMI) + TSEM(옛 10-Q 2024-06 까지만 → valuation '재무 오래됨' 검증전). → req-data-3c64a717. 하이닉스·삼성 = 기존 DART 경로(valuation BASKET KR 행) 그대로.
3. **MU 매출(mu-revenue-tag) 검수 완료** — 태그 `RevenueFromContractWithCustomerExcludingAssessedTax`(2017-08~2026-09). companyfacts→parse 결과 vs 8-K ex99.1 원문(백만달러): FQ4(09-03) 54,229 = 54,229 · FQ3 41,456 = 41,456 · FQ2 23,860 = 23,860 · 전년 FQ4 11,315 = 11,315(오차 0). 순이익 37,701·28,243·13,785, 영업이익 43,751·33,318·16,135 일치, CFO Q4 = 89,675 − 45,702 = 43,973 일치 → sec-ytd-bug 도 완료(누적치 아님 재확인, FQ1 은 원문 미대조). 실데이터 반영이 늦은 이유 = 10/17 코드 수정 후 MU 갱신 주기 7일(10/16 → 10/23).
4. **회전 배치(PB 추가 지시)** — 대상 = 스크리닝 유니버스(지수 518 ∪ 관찰) + 바스켓 = **560종목**. 실행당 `SEC_BUDGET` 80(fin.yml 03:30 KST 매일), 바스켓 우선 → 나머지는 마지막 확인이 오래된 순. 증분: submissions 의 최신 정기보고서(10-Q/10-K/20-F) 제출일이 지난번과 같으면 companyfacts 생략. 진행 상태 `data/fin/sec_progress.json`(종목별 ok·unchanged·fail·no_cik·ifrs·no_data·never + 완주 예상일). CIK 없음 1건 = CYBR. 오늘 확인 153 · 미확인 406 → 첫 바퀴 완주 예상 2026-10-29(406 ÷ 80, fin.yml 매일 가정). 미확인 406 중 다수는 10/16 수집분이 parquet 에 이미 있음(새 체계로 재확인만 남음).
5. **valuation** — `valuation_daily.basket()` = 고정 16 + 바스켓 신규 US 종목 → 54행(10/23 가격 기준 재생성: 검증 39/54, 가격 27/54, 중앙 PER 42.2 — 16종목 때 35.9 와 구성이 달라 비교 불가). 비율만, 기존 ⚠검증전 규칙 + 'SEC 상태'·'재무 오래됨' 플래그. 가격 없는 27종목은 us_watch 에 추가 → 다음 US 상세 생성부터 가격·PER 채워짐(그 전엔 '가격 없음' 플래그).
6. **실적일·컨센 조사**

| 소스 | 키 | 결과(10/24 실측) | 판정 |
|---|---|---|---|
| 야후(yfinance) calendar·earnings_estimate | 없음 | 49/49 예정일·0q EPS 평균·애널 수 | **붙임** `screener/earnings_cal.py` → reports/earnings_cal.json(추정 등급), fin.yml 매일 |
| Nasdaq api/calendar/earnings | 없음(비공식) | 200, 날짜별 전 종목·Consensus EPS·# of Ests | 예비(교차검증용), 미연결 |
| Alpha Vantage EARNINGS_CALENDAR | demo 키로 응답 | CSV 전 종목·estimate | demo 키 운영 사용 부적절 → 무료 키 발급 시 가능 |
| Finnhub | 필요 | 401 | 안 됨(키 없음) |
| SEC EDGAR | 없음 | 발표 후 8-K item 2.02 만, 예정일·컨센 없음 | 사후 확인용 |

VOC: 담당 칸이 '데이터'인데 요청 받은 건 나 — 담당 없는 일처럼 굴렀다. 보드에 내 이름이 없으면 내 일이 아니라고 본 게 원인.
현재 상태: ① 바스켓 49 수집 끝, 회전은 fin.yml 이 매일 80씩 ② 남은 것 = 20-F 7종목 경로(데이터, 10/30), 신규 27종목 가격(다음 US 상세 생성), N-PORT 다음 분기 구성 갱신(수동, 12월) ③ 검수 포인트 = 다음 fin.yml 실행 후 sec_progress.summary 와 valuation 가격 채움.
요청→데이터: 20-F 제출사(TSM·ASX·UMC·ASML·STM·NVMI·TSEM) 분기 재무 무료 경로 판단·연결(req-data-3c64a717, 10/30).
