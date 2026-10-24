# 무료 공공 데이터 신청 체크리스트 (데이터 데스크, 2026-10-24)

겸이 10/24: "공공데이터 같은 거 더 필요할 거 있으면 다 정리해줘, 어차피 공짜인데 더 탄탄하게 구현하자".
작성 근거: `docs/data_go_kr_apis.md`(승인 7건·V2 엔드포인트), `docs/desk_kb/*.md` 의 '키 필요·미확인' 줄, `screener/realestate.py` SOURCES, `.github/workflows/*.yml` 의 `secrets.*`, 요청 장부 `docs/desk_kb/rounds/_requests.json`(데이터 앞 open/promoted).
링크 확인: data.go.kr 상세 페이지는 2026-10-24 실조회로 제목을 확인한 것만 URL 로 적음. 확인 못 한 건 **검색어**로 적음. 호출 한도는 각 신청 화면 표기가 최종 — 여기 '미확인'은 원문을 못 본 것.

## 0. 규칙 (키 다루기)

- **키 값은 채팅·텔레그램·커밋·로그에 쓰지 않는다.** 발급받으면 바로 GitHub Secrets 에만 넣는다:
  https://github.com/hk99915-bot/market-screener/settings/secrets/actions/new → Name 에 아래 '시크릿 이름' 그대로, Secret 에 키 값.
- **data.go.kr 은 키가 하나다.** 이미 등록된 `DATA_GO_KR_KEY`(일반 인증키 Decoding)가 계정의 모든 활용신청에 공통 — **새 API 는 '활용신청' 버튼만 누르면 되고 새 시크릿 등록 불필요.** (아래 표 'DATA_GO_KR_KEY 재사용' 표시)
- 등록 확인은 데이터가 Actions 실행 로그 env 블록으로 한다(등록 = `***`, 미등록 = 빈 칸 — data KB 흔한 오해 'secrets.X 가 yml 에 있으면 있다'). 겸이가 따로 확인할 필요 없음.
- 모든 항목 개인정보 없음: 시장·통계·공시·거래 집계(실거래가는 동·지번 일부·층·면적·금액, 거래 당사자 정보 없음). 우리 쪽에서도 보유·금액은 공개 저장소에 안 올림(비율만).

## 1. 이미 있는 것 — 중복 신청 말 것

| 시크릿 / 소스 | 상태 | 근거 |
|---|---|---|
| `DATA_GO_KR_KEY` | **있음** (10/24 등록) | 승인 7건: 금융위 주식시세·시장지수(주가·채권·파생지수)·채권시세·파생상품(옵션·주식선물), 국토부 아파트 매매 실거래 상세·아파트 전월세, 주택금융공사 전세자금대출 금리 — `docs/data_go_kr_apis.md` |
| `DART_API_KEY` (OpenDART) | **있음** (Actions 에만) | data KB 종목 한 줄 설명 절, 워크플로 3곳 사용 |
| `KRX_ID`·`KRX_PW` | **있음** | pykrx 로그인용(Actions 로그 `***`). OPEN API 키와는 별개 |
| `SEC_USER_AGENT` | **있음** | SEC EDGAR(키 아님, UA 만) |
| FRED `fredgraph.csv` | 키 불필요 | data KB 원자재 절 — 지금 그대로 씀 |
| `KRX_API_KEY` | **미등록** (yml 이름만 있음) | 보드 `user-krx-openapi-key` — 아래 P0-3 |
| `ECOS_API_KEY` | **미등록** (지금 공개 sample 키 1회 10행) | realestate.py SAMPLE_KEY_NOTE, 보드 `user-realestate-keys-1023` |
| `REB_API_KEY` | **미등록** (무키 = 샘플 5행) | realestate.py fetch_rone, 같은 보드 항목 |

## 2. 데스크별 데이터 공백 (요약)

| 데스크 | 공백 | 막힌 이유 | 해결 항목 |
|---|---|---|---|
| 부동산 | R-ONE 주간 지수·구별 숫자 '미확인', 실거래가 지수 | REB_API_KEY 없음 | P0-2 |
| 부동산·가계 | 아파트 밖(빌라·오피스텔) 전월세 — 독립 시 주거비 기준선 없음 | 미신청 | P0-4·5 |
| 부동산·가계 | 청약 일정·경쟁률(세대분리 뒤 청약 판단) | 미신청 | P0-6, P1 |
| 매크로·개발 | MACRO '기준금리' 칸 '데이터 없음'(req-data-2964da3f), 주담대 금리 sample 10행 | ECOS 개인키 없음 | P0-1 |
| 채권·매크로 | 국고 3·10년 일별 백필 2021~22(req-data-a555e088)·국고 3년 일봉(req-data-5046a78b)·출처별 3~4bp 차(req-data-1fd3dc04) | ECOS 개인키·KRX 국채 API 없음 | P0-1, P0-3 |
| 파생·HF·퀀트 | 코스피200 선물·옵션 일별 이력(2010~), VKOSPI 이력 0(req-data-4e390b32), 주식옵션 | KRX_API_KEY 미등록·서비스 미신청 | P0-3 (+ 이미 있는 금융위 파생 V2 로 T+1 누적) |
| 매크로 | 정제마진·재고(EIA)·중국 PMI·비료 가격 | EIA 키 없음, 나머지 무키 소스 미연결 | P1 |
| 애널·매크로 | 반도체 수출(관세청) | 미신청 | P1 |
| 퀀트 | KR 상장·폐지 마스터(생존편향) | 미신청 | P1 (금융위 KRX상장종목정보) |
| HF | 미장 옵션 체인·공매도 잔고·추정치 이력 | **무료 공공 API 없음** — 이 목록 범위 밖(유료·브로커) | — |

## 3. P0 — 지금 신청 (7개, 이 순서로)

- [ ] **P0-1 한국은행 ECOS 개인 인증키** → 시크릿 `ECOS_API_KEY`
  - 신청: https://ecos.bok.or.kr/api/#/AuthKeyApply (회원가입 → 인증키 신청, 즉시 발급 — 심의 없음으로 알고 있음 `[확인 필요]`)
  - 한도: 공지 원문 미확인(1회 요청 행 수 제한 있음 — 키 받으면 실측)
  - 쓰는 데스크: 매크로(기준금리 722Y001·금통위), 부동산(주담대 121Y006·주택대출 151Y005 — 코드 이미 있음), 채권(시장금리 일별 국고 3·10년 → 백필·출처 대조)
  - data.go.kr 키 재사용: **아니오**(별도 사이트)
- [ ] **P0-2 한국부동산원 R-ONE 오픈API 인증키** → 시크릿 `REB_API_KEY`
  - 신청: https://www.reb.or.kr/r-one/portal/openapi/openApiIntroPage.do (R-ONE 회원가입 → 인증키 신청) · 승인 방식·한도 미확인
  - 쓰는 데스크: 부동산(주간 매매·전세 지수 권역·구별, 공동주택 실거래가격지수 월) — 코드 이미 있음, 키만 들어오면 '키 필요' → 1차 값
  - data.go.kr 키 재사용: **아니오**
- [ ] **P0-3 KRX 정보데이터시스템 OPEN API** → 시크릿 `KRX_API_KEY`
  - 신청: https://openapi.krx.co.kr → 회원가입 → 인증키 신청 → **서비스별 이용 신청 따로**: 선물 일별매매정보(주식선물外) · 옵션 일별매매정보(주식옵션外) · 주식옵션(유가) · 파생상품지수 시세정보 · 국채전문유통시장 일별매매정보. 승인 = 신청 후 심의(서비스별)
  - 한도: 미확인(승인 화면 확인)
  - 쓰는 데스크: 파생·HF·퀀트(옵션 이력 2010~, VKOSPI), 채권(국고 일별)
  - 보드 `user-krx-openapi-key` 와 같은 일 — 여기서 하면 그 항목도 같이 끝남
- [ ] **P0-4 국토부 오피스텔 전월세 실거래가** — **DATA_GO_KR_KEY 재사용**(활용신청만)
  - 신청: https://www.data.go.kr/data/15126475/openapi.do · 자동승인(개발계정) · 한도는 승인 화면(기존 승인 건은 1만/일)
  - 쓰는 데스크: 가계·부동산(독립 시 월세·보증금 기준선, 양천·직장 근처)
- [ ] **P0-5 국토부 연립다세대 전월세 실거래가** — **DATA_GO_KR_KEY 재사용**
  - 신청: https://www.data.go.kr/data/15126473/openapi.do · 자동승인 · 한도 승인 화면
  - 쓰는 데스크: 가계·부동산(빌라 전월세 기준선·전세가율 — 전세 위험 점검)
- [ ] **P0-6 한국부동산원 청약홈 분양정보 조회** — **DATA_GO_KR_KEY 재사용**
  - 신청: https://www.data.go.kr/data/15098547/openapi.do · 자동승인 여부 신청 화면 확인 · 한도 승인 화면
  - 쓰는 데스크: 가계·부동산(세대분리 뒤 청약 일정·공급 위치·분양가)
- [ ] **P0-7 국토부 단독/다가구 전월세 실거래가** — **DATA_GO_KR_KEY 재사용**
  - 신청: https://www.data.go.kr/data/15126472/openapi.do · 자동승인 · 한도 승인 화면
  - 쓰는 데스크: 가계·부동산(다가구 원룸 월세 — 오피스텔·빌라와 같이 봐야 독립 주거비 표본이 참)

P0-4~7 은 data.go.kr 로그인 한 번에 '활용신청' 4번이면 끝(시크릿 추가 없음). P0-1~3 은 사이트 3곳 가입 + 시크릿 3개.

## 4. P1 — 다음 (구현 여력 생기면, 대부분 DATA_GO_KR_KEY 재사용)

| 이름 | 기관 | 신청 | 승인 | 데스크·용도 | 시크릿 |
|---|---|---|---|---|---|
| 청약홈 청약접수 경쟁률·특별공급 신청현황 | 한국부동산원 | https://www.data.go.kr/data/15098905/openapi.do | 신청 화면 확인 | 가계·부동산(경쟁률·특공 수요) | DATA_GO_KR_KEY |
| 연립다세대 매매 실거래가 | 국토부 | https://www.data.go.kr/data/15126467/openapi.do | 자동 | 부동산(빌라 매매·전세가율 분자) | DATA_GO_KR_KEY |
| 오피스텔 매매 실거래가 | 국토부 | https://www.data.go.kr/data/15126464/openapi.do | 자동 | 부동산(오피스텔 전세가율) | DATA_GO_KR_KEY |
| 건축HUB 건축물대장정보 | 국토부 | https://www.data.go.kr/data/15134735/openapi.do | 신청 화면 확인 | 부동산(단지 연식·세대수·위반건축물 — 빌라 점검) | DATA_GO_KR_KEY |
| 공동주택 단지 목록제공 | 국토부 | https://www.data.go.kr/data/15057332/openapi.do | 자동 | 부동산(단지 코드 마스터 — 실거래 단지명 매칭) | DATA_GO_KR_KEY |
| KRX상장종목정보 | 금융위 | https://www.data.go.kr/data/15094775/openapi.do | 자동 | 퀀트·데이터(KR 상장·폐지 마스터 — 생존편향 축소) | DATA_GO_KR_KEY |
| 주식배당정보 | 금융위 | https://www.data.go.kr/data/15043284/openapi.do | 자동 | 애널·배분(배당 이력 DART 대조) | DATA_GO_KR_KEY |
| 기업 재무정보 | 금융위 | https://www.data.go.kr/data/15043459/openapi.do | 자동 | 데이터·검증(DART 재무 독립 대조 — 하이닉스 Q2 단독분기 의심 건) | DATA_GO_KR_KEY |
| 품목별 국가별 수출입실적(GW) | 관세청 | https://www.data.go.kr/data/15100475/openapi.do | 신청 화면 확인 | 매크로·애널(반도체 HS 8542 수출 — 월) | DATA_GO_KR_KEY |
| LH 분양임대공고 | LH | 검색어: `한국토지주택공사_분양임대공고문 조회` | 미확인 | 가계(행복주택·청년 임대 공고) | DATA_GO_KR_KEY |
| 통계청 KOSIS 공유서비스 | 통계청 | https://kosis.kr/openapi/index/index.jsp | 즉시(로 알고 있음 `[확인 필요]`) | 매크로·가계(세부 CPI·가구·인구이동) | `KOSIS_API_KEY` |
| EIA Open Data | 미 에너지정보청 | https://www.eia.gov/opendata/register.php | 즉시(이메일) | 매크로(원유·휘발유 재고·정제 가동률 — KB 'EIA 키 필요') | `EIA_API_KEY` |
| SGIS 통계지리정보 | 통계청 | https://sgis.kostat.go.kr/developer/ (개발지원센터) | 신청 후 승인 | 부동산(구·동 경계·인구 — 지도 구현 쪽이 필요하다고 할 때만) | `SGIS_CONSUMER_KEY`·`SGIS_CONSUMER_SECRET` |
| 서울 열린데이터광장 | 서울시 | 검색어: `서울 열린데이터광장 인증키 신청` | 즉시(로 알고 있음) | 부동산(서울 부동산 실거래·전월세 — 국토부 대조) | `SEOUL_API_KEY` |

## 5. P2 — 필요 생기면

- 분양권 전매 실거래가(국토부) — 검색어 `국토교통부_아파트 분양권전매 실거래가` · DATA_GO_KR_KEY · 부동산(입주 전 시세)
- 공동주택 관리비 / 공동주택 기본정보(K-apt) — 검색어 `공동주택 관리비 정보`·`공동주택 기본 정보제공 서비스` · DATA_GO_KR_KEY · 가계(관리비 포함 주거비)
- 금융위 채권기본정보 — https://www.data.go.kr/data/15059592/openapi.do · DATA_GO_KR_KEY · 채권(발행·만기 마스터)
- 경기데이터드림 — 검색어 `경기데이터드림 인증키` · `GG_API_KEY` · 부동산(경기남부 보조)
- FRED API 키 — 검색어 `FRED API key request` · `FRED_API_KEY` · 지금 fredgraph.csv 로 충분, 메타·발표일(vintage) 필요할 때만
- USDA NASS QuickStats — 검색어 `NASS Quick Stats API key` · `USDA_API_KEY` · 매크로(곡물 — 비료·곡물 조건 채점, 우선 World Bank Pink Sheet 무키로)
- 기상청 단기·중기예보 — 검색어 `기상청_단기예보 조회서비스` · DATA_GO_KR_KEY · 원자재 연관 약함
- 국가교통 TAGO — 검색어 `국토교통부_(TAGO)` · DATA_GO_KR_KEY · 지금 쓰는 데스크 없음
- 산업부·조달청 원자재 가격 — 검색어 `조달청 비축물자 가격`·`원자재 가격 정보` · 야후 대용+FRED 월간으로 이미 대조됨, 국내 고시가 필요할 때만

키 없이 되는 것(신청 불필요, 구현 때 바로): World Bank Pink Sheet(비료·원자재 월간 xlsx), FRED fredgraph.csv, SEC EDGAR, 중국 NBS PMI(웹 발표 — 약관 확인 필요).

## 6. 겸이 할 일 순서

1. data.go.kr 로그인 → P0-4·5·6·7 '활용신청' 4번(사유 예: "개인 비상업 투자·주거 연구용 대시보드"). 시크릿 추가 없음.
2. ECOS 가입·인증키 → Secrets `ECOS_API_KEY`.
3. R-ONE 가입·인증키 → Secrets `REB_API_KEY`.
4. KRX OPEN API 가입·인증키 + 서비스 5종 이용 신청 → Secrets `KRX_API_KEY`.
5. 끝나면 `ask 데이터 키 등록 끝(ECOS·REB·KRX·data.go.kr 4건)` 한 줄. 데이터가 Actions 로그로 등록 여부 확인 후 탐침.
6. P1 은 데이터가 구현 착수할 때 다시 한 줄로 요청함 — 지금 미리 안 해도 됨.

※ 부동산 키 3종 결재 보드 `user-realestate-keys-1023`(보류 11/30)와 겹친다 — 위 2·3 을 하면 그 결재도 '진행'으로 바뀌는 것. 보류 유지면 2·3 만 빼고 하면 됨.

## 7. 승인 뒤 구현 (지금 안 함)

요청 장부 데이터 앞 1건(10/27 화 11시 이후 착수, 마감 11/07): 탐침 `scripts/probe_deriv_sources.py` 에 새 항목 추가 → 200 확인 → 수집기·저장(point-in-time) → 독립 소스 1개 대조 후 승격. 부동산 화면 연결은 부동산 담당 인스턴스와 겹치지 않게 산출물(json)까지만.
