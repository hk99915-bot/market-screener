# data 데스크 KB

(형식은 README.md. 2026-10-23 교육 정리: 빈 절·구축 취소 메모·해결된 요청 본문 압축 — 원문은 git 이력.)

## 성격·성향
- **한 줄:** 의견 대신 "뭐가 없고 얼마가 드는지"를 적는 창고지기. 결측·비용·편향을 먼저 표기.
- **맹점:** 모양만 보고 파서 결함으로 판정, 가드가 정상 데이터를 '검증전' 처리(복기 10/17). **긴장:** ↔퀀트 — 연구가 아직 창고를 읽지 않음(TH:quant_data §3).
- 원본: [PERSONAS.md#data](PERSONAS.md#data) — 요약(과거 행동 기록이지 연기 지시가 아님).

## 정의
- **companyfacts 태그 전환**: 같은 재무 항목이 연도에 따라 다른 us-gaap 요소로 태그됨. ASC 606(2018 회계연도~) 때 매출 `SalesRevenueNet`/`Revenues` → `RevenueFromContractWithCustomerExcludingAssessedTax`. 태그 하나만 고르는 파서는 한쪽 연도만 얻는다. `[규정]`
- **네이버 지수 `chg` 분모** = 전일 KRX 확정 종가, 소수 2자리 잘림 → `last/(1+chg)` 역산 오차 최대 ±0.005%p(코스피 5,500 기준 ±0.3pt). 정확한 전일 = `closePrice − compareToPreviousClosePrice`(부호 compareToPreviousPrice.code) 또는 integration `totalInfos[code=lastClosePrice]`. 대조 1건: 10/15 KPI200 '전일' 936.82 = pykrx 10/14 종가(data/hist/kr_index_daily, 릴리스 자산 — git 엔 미생성). `[자체연구-B: 1표본]` → screener/live.py `prev`·rebound.py `prev_src`.
- **ETF PDF(납입자산구성내역)**: 1CU 당 구성종목·수량, 국내 상장 ETF 는 액티브 포함 일간 공시 → 액티브 ETF 일간 편입·편출 추적 가능. `[규정-B: KRX 원문 조항 미확인]`
- **액티브 공모펀드 보유 공시**: 자산운용보고서(분기)·금투협 — 상위 보유 위주·수주 지연 → 분기·부분 데이터, 일간 신호 금지. `[규정-B]`
- **액티브 ETF 상관 요건**: 비교지수 대비 일간 상관 0.7 이상(패시브 0.9), 3개월 연속 미달 시 상폐 대상(상장 1년 미만 유예). 2026-09까지 이 사유 상폐 5개. `[언론-B: 머니투데이 2026-09-07 외 3건, 상장규정 원문 미확인]` → 편입 신호 대부분은 지수 비중 근처 미세 조정, 진짜 신호는 비중 밖 신규 편입·큰 수량 변화.

## 공식
- **실질 매매** = 1CU 당 주식 수 변화율 s_t/s_{t-1} − 1(설정·환매는 CU 개수만 바꿈). 비중 변화 Δw 는 주가 변동이 섞여 판정에 안 씀. `[자체연구-검증전]` — 10/17 수집기 축소 후 현행은 `screener/etf.py` active_consensus()(상위 20 비중·상대수익 비교).

## 흔한 오해
- "액티브 ETF 비중↑ = 매수 신호" → 아니다: ① 자금 유입은 비례 매수(1CU 수량 불변) ② 주가 상승만으로 비중↑ ③ 분할·무상증자 ④ 코스피200 정기변경(6·12월) 추종 ⑤ 같은 운용사 동시 매매 — 걸러야 한다. `[자체연구-검증전]`
- "매출 태그는 회사당 하나" → 전년 비교치 때문에 전환 전후 태그 공존. 파서는 태그 전부 합치고 같은 분기말만 우선순위로(10/17 수정, `screener/sec.py parse()`). `[자체연구-A: 합성 테스트 2건, 실데이터 대조는 검증전]`
- "값이 단조 증가하면 누적(YTD) 버그" → 신설 법인·고성장도 같은 모양. 모양 휴리스틱(CUM_RATIO)은 플래그만, 판정은 원문 대조 파일(universe/fin_verified.json). `[경험]`

## 처리 기록 (압축)
- 애널 요청 `mu-revenue-tag`(10/17): MU 매출 0행 원인 = parse() FLOW 루프가 첫 태그에서 `break` + 2019 필터 → 태그 병합으로 수정(위 오해 2). 검증 기준: FQ4(2026-09-03) 매출이 fin_verified.json 과 1% 안.
- 미결: SK하이닉스 2026Q2 DART 단독분기 매출 < 순이익 — 분기 차감(누적−전분기) 오류 의심, 사업보고서 원문 대조 필요 `[자체연구-검증전]`.

## 소스 목록 — 원자재·지정학 뉴스 (2026-10-23, req-data-3dda8f42 · 겸이 "야후파이낸스나 토스에 원자재 선물? 지정학은 뉴스트래킹")
- **쓰는 원자재 일간 대용(야후)**: 니켈 `NICK.L`·아연 `ZINC.L`(WisdomTree ETC, LSE, $) · 주석 `TINM.MI`(WisdomTree, 밀라노, €, 거래 얇음) · JKM `JKM=F`(NYMEX 정산가, 장내 거래량 0) · 우라늄 `SRUUF`(Sprott 실물 신탁). ETC 가격은 $/t 가 아니라 증권 가격 — 방향·변화율만. `[자체연구-B: 2026-10-23 실조회]`
- **대조(reconciliation)**: 위 일간 대용의 월평균 변화율 vs FRED IMF 월평균, 최근 24개월 상관 — 니켈 0.99+ · 아연 0.95 · 주석 0.95 · JKM↔일본 LNG 0.97 · 우라늄 0.93. `[자체연구-B: 24표본, 1회]` → 승격 근거(10년차 기준 ③).
- **월간 공식 수준(FRED fredgraph.csv, 키 불필요)**: PNICKUSDM·PZINCUSDM·PTINUSDM·PNGASJPUSDM·PURANUSDM — commodities.json `freq='월간'`, 화면 '월간 N월'. **주의:** FRED 는 브라우저/커스텀 UA 로 읽기 타임아웃, 기본 requests UA 는 0.5초(10/23 실측, 샌드박스 프록시 경유) — 첫 타임아웃이면 나머지 건너뜀.
- **못 쓰는 것(이유)**: 야후 `NI=F`·`SN=F`·`JJN`·`JJU` 없음 · `ZNC=F` 호가 정체(거래 0 → ZINC.L 로 교체) · `LTH=F`·`COB=F`·`UX=F` 3개월 1행 · **`CB=F` 는 코발트가 아니라 버터 선물** · FRED 코발트·리튬 시리즈 없음 · 싱가포르 복합정제마진·희토류 산화물 현물 = 유료 · 토스증권 Open API(v1.2.24) 원자재·선물 없음(시장지표 8종: 코스피·코스닥·국채), 웹 크롤링은 약관 금지 · investing.com 403+약관 · westmetall 접속되나 LME 가격 재배포 라이선스 → 저장 안 함 · EIA API 키 필요(시크릿 없음).
- **지정학 뉴스 RSS(screener/geo_news.py → reports/geo_news.json)**: 직접 = BBC World·BBC Business·Al Jazeera·Guardian World·NYT World·NPR World·Yonhap(영문)·gCaptain·OilPrice·야후 파이낸스 헤드라인 RSS(CL=F 등, 간헐 오류 페이지) / 검색 = Google News RSS 축별 8쿼리(로이터·AP 기사 제목도 여기로 들어옴, 연속 호출 시 간헐 503 → 3초 뒤 1회 재시도). 실패: AP index.rss 403 · CNBC 403 · DW 404 · 로이터 공개 RSS 2020 종료.
- **피드 이용 조건(10/24 피어 G3, 원문 실조회 2026-10-24 00시대 KST) → 공개 산출물 처리**:
  - Google News RSS — 피드 `<copyright>` 원문: "made available solely for the purpose of rendering Google News results within a personal feed reader for personal, non-commercial use. Any other use of the feed is expressly prohibited." `[규정-A: 피드 원문]` → **공개 저장소·Pages 엔 제목 비공개**(`title=null`·`title_withheld`), 매체·시각·축·링크만. 제목은 축 매칭·중복 판정에만 메모리에서 쓰고 저장 안 함. 같은 사건이 직접 피드에도 있으면 직접 피드판으로 교체. geo_news·realestate 공통(`geo_news.public_item`). 남은 위험: 매체·시각·링크 게시도 엄밀히는 '그 밖의 이용' — R4 철회 조건 미충족, 완전 해소는 Google News 검색 중단(로이터·AP 제목 대체 직접 피드 없음 → 겸이 결재 사항). git 이력의 과거 제목은 force push 금지라 남음. **종결(10/24 겸이 결재, req-data-00e8a89a):** Google News 수집 유지 + 현행 제목 비공개 처리 그대로 — 피어 G3·R4 는 오너 유지 결정으로 닫음(약관 위험은 오너가 인지·수용, 원문 판단은 위 [규정-A] 그대로). 다시 열 조건: 제목 공개로 바꾸거나 Google 측 삭제 요청이 오면.
  - NYT RSS — nytimes.com/rss "Terms & Conditions": 뉴스 리더 개인 이용 또는 비상업 블로그 일부로 허용, 게시 시 형식·출처 표기 요구 `[규정-A]` → 비상업 개인 대시보드 + 매체명·링크 표기로 유지.
  - NPR — Terms of Use 'Content Feeds': 개인 사이트·앱에서 표시·발췌·링크 허용, 피드 전체 재배포 금지·출처 표기 `[규정-A]` → 유지(제목·매체·링크만, 축당 일부).
  - BBC·Guardian·Al Jazeera·Yonhap·gCaptain·OilPrice·야후 — RSS 전용 조항 원문 못 찾음(Guardian ToS 는 RSS 를 '네트워크 접근 경로'로만 언급, BBC 피드 안내 페이지는 리더 사용법만) `[확인 필요: 각 매체 RSS 재게시 조항, 2026-10-31, 데이터]` → 보수적으로 제목·매체·시각·링크만, 본문·요약·이미지 없음, 축당 5·매체당 2 상한, 출처명 항상 표기.
- **축 단위 stale(G1)·사건 중복(G2)** (10/24): 축 검색 실패 → 그 축은 이전 파일 값 유지 + `stale{why,since,kept}`(연속 실패면 since 최초 유지), 화면 앰버 표시. 같은 사건 = 같은 링크 대상 또는 제목 단어 자카드 ≥0.4 또는 짧은 쪽 60%·5단어 겹침(10/23 산출물 대조: 같은 사건 0.45~1.0, 다른 사건 ≤0.31). 검색 호출 간격 1초 + 재시도 3·10초 — 10/23 23:03·10/24 00:33 두 번 다 6번째 검색(taiwan)만 503, 단독 호출 200 `[자체연구-B: 2회]`. 남은 것: 'Oleshky 휴전'처럼 단어가 거의 안 겹치는 같은 사건은 못 잡음(00:34 ruukr 5칸 중 2칸).
- **흔한 오해**: "키워드 매칭 헤드라인 = 축 상태 변화" → 아니다. 제목만 매칭(관세는 상대국·품목 동반 필요 — 첫 실행에 미 국내 정치 기사 섞임), 원문 미대조. 축 상태·해석은 매크로 데스크 손 갱신(geopolitics.json)만이 판단. `[경험]`

## 소스 목록 — 종목 한 줄 설명 (2026-10-24, 겸이 "각 티커에서 이 회사가 뭐 하는 회사인지 한 줄")
- **산출물**: reports/company_oneliner.json(화면용 line·industry·src) + reports/company_oneliner_ev.json(근거 첫 문장 ≤200자, 원문 전문 저장 안 함). 생성 screener/oneliner.py, 상세 생성 때 증분(detail.py, 야후 60개/회). 화면 = 종목 상세 머리 종목명 아래(getOneliners).
- **쓰는 것**: 야후 quoteSummary assetProfile(sector·industry·longBusinessSummary) — `yfinance Ticker.info` 는 401(Invalid Crumb), fc.yahoo.com 쿠키 + getcrumb 직접 호출은 됨. **UA 는 짧은 'Mozilla/5.0'** — 긴 크롬 UA·curl_cffi 는 getcrumb 429. 연속 1,500회쯤 뒤 getcrumb 'Too Many Requests'(평문) → 10~20분 쉬면 풀림. `[자체연구-B: 2026-10-24 실조회]`
- **한국어 한 줄은 데이터 에이전트가 근거를 읽고 쓴다**(src='yahoo+agent', 30~45자, 홍보·수치·전망 금지 — oneliner.check_line). ETF 는 상세 json etf.base 로 기계 생성(KR) / 손으로(US 67개, src='etf+agent').
- **못 쓴 것**: KRX KIND 상장법인목록(업종·주요제품) — 이 컨테이너 403(Akamai), Actions 에서는 미확인(코드는 시도 후 실패 시 야후로). DART company.json(업종코드) — 키(DART_API_KEY)는 Actions 에만. 야후 프로필 없는 신규 상장·소형주는 '설명 대기'.
- **흔한 오해**: "야후 industry = 한국 업종 분류" → 아니다. 야후 영문 분류(예: 삼성전자 'Consumer Electronics')는 공식 섹터가 아님 — 공식 섹터는 WICS(universe/kr_wics.csv). 화면은 한글 업종만 덧붙인다. `[경험]`

## 소스 목록 — KRX OPEN API (2026-10-24, req-data-7d1a8334)
- **서비스 목록 원문**(openapi.krx.co.kr OPPINFO004, 10/24 실조회, 제공 기간 2010~): 파생 6종 = 선물 일별매매정보 (주식선물外)·주식선물(유가)·주식선물(코스닥, 2015-08-03~)·옵션 일별매매정보 (주식옵션外)·주식옵션(유가)·주식옵션(코스닥, 2017-06-26~) / 지수 = 파생상품지수 시세정보 / 채권 = 국채전문유통시장 일별매매정보. API 별로 이용 신청·승인이 따로. `[규정-A: 서비스 목록 원문]`
- **탐침**: `scripts/probe_deriv_sources.py krx_openapi` (deriv_hist.yml task=probe days=krx_openapi commit=false) — 엔드포인트 drv/{fut,eqsfu_stk,eqkfu_ksq,opt,eqsop,eqkop}_bydd_trd·idx/drvprod_dd_trd·bon/kts_bydd_trd·대조군 sto/stk_bydd_trd. 응답: 틀린 키 = HTTP 401 `respMsg=Unauthorized Key`(샌드박스에서 직접 확인 — 접속은 됨).
- **10/24 결과**: Actions 로그에 `KRX_API_KEY:` 빈 값(등록된 시크릿은 *** 로 찍힘) → **시크릿 미등록**, 엔드포인트 호출 전 종료. 'KRX_API_KEY 이미 있음'은 워크플로가 이름만 참조한 것(KRX_BACKEND 기본 pykrx 라 안 쓰여서 드러나지 않음). 겸이 할 일 = 보드 user-krx-openapi-key.
- **흔한 오해**: "워크플로 yml 에 secrets.X 가 있으면 시크릿이 있다" → 아니다. 미등록 시크릿은 빈 문자열로 조용히 들어간다. 확인은 실행 로그 env 블록(*** vs 빈 칸)으로. `[경험]`

## 복기
- **2026-10-17 'YTD 누적 버그' 판정** — 틀림: 10/16 14:47 MU ni 5.2→13.8→28.2→37.7 모양만 보고 P0 "파서 결함"으로 올렸고, 15:25 수정 때 넣은 모양 가드(CUM_RATIO 1.8)가 SNDK revenue 3.0→6.0→9.0 을 같은 누적 버그로 '검증전' 처리했다. → 왜: MU 는 실제 누적치 누수(맞음)였지만 SNDK 는 분사 직후 정상 성장이었고, 두 경우를 모양으로는 구분할 수 없다는 걸 원문(8-K) 대조(23:43) 전까지 인정하지 않았다. → 다음부터: 파서 버그 의심은 (1) start/end 기간(일수)으로 누적 여부를 **구조적으로** 판정하고, (2) 모양 휴리스틱은 플래그만, 확정·해제는 fin_verified.json 원문 대조로만 한다. 같은 날 MU '매출 0행'도 모양이 아니라 코드 경로(첫 태그 break)로 먼저 확인했다.

## 출처
- 액티브 ETF 상관 0.7·상폐: 머니투데이 https://www.mt.co.kr/stock/2026/09/07/2026090716590337148 · 파이낸셜뉴스 https://www.fnnews.com/news/202608181844572118 · 더벨 https://www.thebell.co.kr/front/newsview.asp?key=202606152317415920106146 (검색 요약 확인, 원문 샌드박스 차단)
- FASB ASC 606 / us-gaap 2018 taxonomy(옛 매출 요소 deprecated) `[규정]` · screener/sec.py FLOW/INSTANT 매핑 · 액티브 ETF 명단 screener/etf.py KR_ACTIVE

## 10년차 기준 (2026-10-23 교육)
- 체크리스트: ① 적재마다 품질 차원(정확·완전·일관·적시·유효·유일) 점검 결과를 manifest 에 남긴다 `[교과서-B: DAMA-DMBOK 2판 품질 장, 원문 미열람]` [확인 필요: 차원 목록 원문 대조(교육), 2026-10-30] ② point-in-time: 발표일 기준 저장·정정 이력 보존(룩어헤드·생존편향 차단) `[교과서: 백테스트 표준 관행]` ③ 새 소스는 독립 소스 1개와 표본 대조 후 승격(reconciliation) `[현업 관행]`
- 격차: 밀린 요청 19건(전 데스크 최다, rounds/_requests.json open+promoted)·보드 P0/P1 17건(ops/board.json) — 처리량이 병목, 복기는 10/17 이후 없음.
- 드릴: data/hist/_manifest.json 에서 069500 은 4099행, 091230 은 4093행 — 둘 다 2010-01-04~2026-10-16. 다음 행동은? **답:** 기간이 같으니 6영업일 결측. 069500 날짜 집합과 차집합으로 날짜 특정 → pykrx 로 거래정지인지 야후 누락인지 대조 → 누락이면 manifest 에 결측 표기, ffill·0 으로 메우지 않는다.
