# data.go.kr API — 10/24 승인·탐침 결과 (겸이 활용신청 7건, 키 `DATA_GO_KR_KEY` = 일반 인증키 Decoding)

탐침: `scripts/probe_deriv_sources.py datagokr` (deriv_hist.yml task=probe days=datagokr, 읽기 전용) · run 40078360285 (10/24 17:32 KST) · 기준일 basDt=20261022.
**금융위 API 는 전부 `_V2` 서비스·오퍼레이션** (옛 `/service/...` 주소는 403). 금융위 = T+1(기준일 다음 영업일 갱신 — 정확한 시각 확인 필요), 실시간 아님.

| 데이터 | 엔드포인트 (apis.data.go.kr) | 10/22 행 수 | 핵심 필드 | 1차 활용 데스크 |
|---|---|---|---|---|
| 주식시세 | `/1160100/GetStockSecuritiesInfoService_V2/getStockPriceInfo_V2` | 2,868 | mkp·hipr·lopr·clpr·vs·fltRt·trqu·trPrc·lstgStCnt·mrktTotAmt·mrktCtg | 데이터·검증·퀀트 (KRX 확정 종가 대조·pykrx 예비) |
| 주가지수 | `/1160100/GetMarketIndexInfoService_V2/getStockMarketIndex_V2` | 171 | idxNm·idxCsf·clpr·fltRt·lsYrEdVsFltRt·lstgMrktTotAmt·epyItmsCnt | 데이터·매크로 (지수 확정 종가·잠정 대조) |
| 채권지수 | `/1160100/GetMarketIndexInfoService_V2/getBondMarketIndex_V2` | 3 | totBnfIdxClpr·ytm·durt·cnvt·nPrcIdx | 채권 |
| 파생상품지수 | `/1160100/GetMarketIndexInfoService_V2/getDerivationProductMarketIndex_V2` | 322 | idxNm·clpr·fltRt·trqu (코스피200 선물지수·변동성지수 등 — VKOSPI 포함 여부 확인) | 파생·HF |
| 채권시세 | `/1160100/GetBondSecuritiesInfoService_V2/getBondPriceInfo_V2` | 312 | mkp/hipr/lopr/clprBnfRt(수익률)·clprPrc·itmsCtg | 채권 (국고 3Y 출처별 3~4bp 차 req-data-1fd3dc04) |
| 옵션 | `/1160100/GetDerivativeProductInfoService_V2/getOptionsPriceInfo_V2` | 20,974 | **iptVlty(내재변동성)**·opnint(미결제)·nxtDdBsPrc·clpr·trqu·prdCtg | 파생·HF (스프레드 엔진 IV 실측화·스큐·풋콜 OI) |
| 주식선물 | `/1160100/GetDerivativeProductInfoService_V2/getStockFuturesPriceInfo_V2` | 3,678 | opnint·sptPrc(현물)·stmPrc·clpr | 파생·HF (포지셔닝) |
| 아파트 매매 실거래 상세 | `/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev` (LAWD_CD·DEAL_YMD) | 양천 9월 98 | aptNm·aptDong·floor·excluUseAr·dealAmount·deal Y/M/D·cdealType(해제)·dealingGbn | 부동산 (신트리 원자료·거래량) |
| 아파트 전월세 실거래 | `/1613000/RTMSDataSvcAptRent/getRTMSDataSvcAptRent` | 양천 9월 641 | deposit·monthlyRent·contractType(신규/갱신)·preDeposit | 부동산 (전세가율) |
| 주택금융공사 전세자금대출 금리 | 미확인 — 활용신청 상세의 요청주소 필요 | — | — | 부동산·교육 |

- 400 난 파생 후보(지수선물·지수옵션·상품/채권/통화선물·주식옵션 이름)는 오퍼레이션명 추정 실패 — 상세기능 목록으로 확인 필요. 코스피200 **선물** 일별은 아직 미확인(파생지수·옵션으로 일부 대체 가능성).
- 키 값은 로그·커밋·채팅에 남기지 않는다. 트래픽 각 1만/일.

## 10/27 진행 (req-data-23bdae79)
- ① 국토부 매매·전월세: screener/realestate.py 가 이미 연결(서울 25구 3개월, reports/realestate.json seoul_trades status ok · 25/25구, 10/27 갱신 — Actions 실행분). 신트리 단지 원자료 대조는 부동산 데스크.
- ② 금융위 주식시세 ↔ 우리 일봉 종가 대조: screener/fsc_close.py(→ reports/fsc_close_check.json), deriv_hist.yml 에 단계 추가(평일 16:40, 실패해도 계속). **실호출 검증 전** — 이 컨테이너엔 키가 없어 합성 테스트만(tests/test_fsc_close.py). 첫 Actions 실행 후 match_rate·불일치 목록 확인 필요. 비교 대상 kr_prices 가 Actions 에 없으면 status '대조 불가'로 남는다.
- ③ 401/Encoding 교체: 10/24 탐침에서 7건 모두 응답했으므로 해당 없음(Decoding 키 정상).

## 10/27 밤 — T+1 일일 수집기 (req-data-784ffc43 · req-data-1a3f3978 ①) + 게시 대조 (req-data-cb6315c2)
- `screener/fsc_daily.py`: 위 금융위 7종을 최근 3영업일 수집(쪽 1000행, 이미 받은 날 건너뜀). 원자료 = `data/fsc/<api>/<YYYYMMDD>.csv.gz`(gitignore, Actions 는 `actions/cache` 로만 유지, 수집 시각 `_fetched` 열 = point-in-time). 공개 = `reports/fsc_daily_status.json`(상태·행 수·기준일만, 값 없음). deriv_hist.yml 평일 실행에 단계 추가(실패해도 계속).
- 백필 범위: `deriv_hist.yml task=probe days=fsc_range` → 2010·2015·2018·2020·2022·2024 첫 영업일 totalCount 만 기록 **(미실행 — 다음 수동 실행)**.
- 로컬 요약(공개 안 함): `summary_stock_futures`(기초자산별 미결제 합 — 삼성전자·SK하이닉스 등), `summary_options`(코스피200 PCR OI·IV 중앙값). 행 이름 규칙(콜/풋 표기)은 실응답 확인 전 `[자체연구-C]`.
- **게시 대조(10/27):** 금융위 V2 원값이 공개 저장소·Pages 에 나간 곳 = `data/deriv/vkospi.csv`·`reports/vkospi.json`(6행) — 게다가 VKOSPI 가 아닌 가격형 지수(786~810, 같은 날 대표 IV 45~52)를 부분 이름 일치로 잡은 오적재라 제거하고 정확 일치·범위 가드(5~150) 추가. `reports/fsc_close_check.json` 불일치 목록은 금융위 원값 대신 차이율만. 국토부 RTMS 파생(reports/realestate.json·realestate_trades/)은 금융위가 아니고 이용허락범위 원문 미확인.
- 주택금융공사 전세자금대출 금리 엔드포인트: 여전히 미확인(이 컨테이너에서 data.go.kr 접속 차단 — 10/27 curl reset).
