# Market Screener (KR + US) — v1 장마감 스크리너

LLM·유료 API 없이 돌아가는 결정론적 스크리너. GitHub Actions 무료 러너에서 매일 실행되고,
결과는 Markdown(`reports/`)으로 저장되며 요약은 텔레그램으로 전송된다.

## 구조

```
screener/
  config.py      # 필터 기준·매크로 심볼·시크릿
  universe.py    # KR: pykrx → FDR → universe/kr.csv 폴백 / US: nasdaqtrader → universe/us.csv
  data.py        # US: yfinance 일봉 → data/us_prices.parquet
  data_krx.py    # KR: KRX 공식 전종목 일별시세 (pykrx 또는 KRX Open API) 증분 → data/kr_prices.parquet (커밋)
  indicators.py  # SMA/EMA·MACD·RSI·Stoch·CCI·DMI/ADX·ATR·PSAR·일목·52주 (Polars)
  scoring.py     # Trend / Momentum / Reversal Risk (0~100, 버킷 상한) + 분류
  context.py     # 시장 폭·이상 신호·매크로 레짐 (점수 미합산)
  report.py      # Markdown·텔레그램·(선택)구글시트
  main.py        # 엔트리
reports/
  latest_KR.md latest_US.md   # 최신
  daily/  signals/  anomalies/  breadth_history.jsonl
universe/ kr.csv us.csv       # 유니버스 폴백 (자동 갱신·커밋)
```

## 점수 체계

| 축 | 구성 | 상한 |
|---|---|---|
| Trend | 장기추세(SMA200 위·50>200·200 기울기) 30 · 전술추세(SMA20 위·20>50·구름 위) 30 · 추세강도(ADX, +DI>-DI일 때만) 20 · 구조(PSAR 아래·52주 고점 10%내) 20 | 100 |
| Momentum | MACD(시그널 위·0 위·히스토 3봉 상승) 40 · RSI 20 · Stoch 20 · CCI 20 | 100 |
| Reversal Risk | RSI>75·Stoch>85·CCI>200·20일선 이격(ATR)·5일 급등·거래량 폭증 | 100 |

분류: `TREND_LONG`(T≥65,M≥55) · `TREND_OVEREXTENDED`(+Risk≥60) · `PULLBACK_IN_UPTREND`(T≥60,M≤40)
· `COUNTERTREND_BOUNCE`(T≤40,M≥60) · `TREND_SHORT`(T≤35,M≤45) · `NEUTRAL`

상태 태그: 장중 실행이면 `[LIVE]`, 마감 후면 `[CONFIRMED]`.

## 설정

GitHub 저장소 → Settings → Secrets and variables → Actions:

| 시크릿 | 필수 | 설명 |
|---|---|---|
| `TELEGRAM_TOKEN` | O | BotFather 토큰 (Apps Script와 같은 봇 사용 가능) |
| `TELEGRAM_CHAT_ID` | O | 받을 채팅 ID |
| `KRX_ID` / `KRX_PW` | O | KRX 정보데이터시스템(data.krx.co.kr) 회원 아이디·비밀번호. pykrx 가 로그인해야 시세 조회 가능 |
| `GSHEET_ID` | X | 결과를 넣을 구글시트 ID (URL의 `/d/` 뒤) |
| `GCP_SA_JSON` | X | 서비스계정 JSON 전체 내용. 시트를 서비스계정 이메일에 편집자로 공유해야 함 |

Actions 탭 → `market-screener` → Run workflow 로 수동 실행 가능.

## 로컬 실행

```bash
pip install -r requirements.txt
python -m screener.main --market KR --no-send      # 전송 없이
python tests/make_synthetic.py KR 120               # 네트워크 없이 파이프라인 점검용 합성 데이터
python -m screener.main --market KR --prices data/kr_prices.parquet --no-send
```

## 알려진 제약 (v1)

- KR 시세는 KRX 공식 전종목 일별시세를 날짜별로 받아 `data/kr_prices.parquet` 에 증분 저장하고 저장소에 커밋한다 (약 1M행, 15MB 내외).
  - 최초 실행 시 parquet 가 없으면 Actions 안에서 자동 백필한다(약 800콜, 5~10분). PC 불필요. 이후는 하루 2콜.
  - KRX 가 러너 IP를 차단해 백필이 실패하면: (a) `KRX_BACKEND=openapi` 로 전환하거나 (b) 국내 IP 에서 `python -m screener.main --market KR --no-send` 1회 실행 후 parquet 커밋.
  - KRX 가 GitHub 러너(해외 IP)를 차단하면 `KRX_BACKEND=openapi` + `KRX_API_KEY`(openapi.krx.co.kr 무료 발급)로 전환. 응답 필드명은 `data_krx._openapi_day` 의 매핑 확인.
  - KRX 일별시세는 수정주가가 아니다. 전일 종가 대비 시가 ±45% 초과를 기업행위로 보고 과거 구간을 자동 보정한다 (휴리스틱).
- US 는 전종목(약 6천)을 매일 받지 않는다. 주 1회 5일치만 받아 거래대금 상위 N(`US_TOP_N`, 기본 1500 ≈ S&P500 + 러셀1000 대부분 + 유동성 있는 중소형)을 `universe/us_top.csv` 에 캐시하고, 매일은 그 N 종목만 400일치를 받는다. 시총 필터 대신 거래대금 필터.
- US 마감 cron은 서머타임/표준시를 한 시각(21:40 UTC)으로 커버하므로, 표준시 기간엔 마감 40분 후, 서머타임 기간엔 1시간 40분 후 실행된다.
- GitHub Actions 스케줄은 혼잡 시 수십 분 지연될 수 있다.
- 이 저장소에 자동매매·포지션 규칙은 없다 (기획서 v1 스코프).

## 하루 흐름 (KST, 월~금)

| 시각 | 워크플로 | 내용 |
|---|---|---|
| 07/09/12/15/19 | briefing `reports` | 네이버·한경 신규 리포트 → 기술 태그·여력·손익비·목표가/의견 변경·몰림 |
| 08:10 | briefing `premarket_kr` | 밤사이 미장·섹터·매크로 → 국장 시사점, 밤사이 리포트, **오늘 관심종목**(`reports/watchlist_KR.json`) |
| 10:30 / 13:30 | briefing `intraday_kr` | 외국인·기관 잠정 수급(시장·종목 상위), 관심종목 수급 교차 |
| 16:20 | screener `KR` | 전종목 스크리너 + 해석 코멘트 + 리포트 결합 + **마감 코멘트**(지수·수급 확정·대형주) |
| 22:30 | briefing `premarket_us` | 선물·매크로, 오늘 국장 결과, 어제 US 스크리너 |
| 01:00 / 03:30 | briefing `intraday_us` | 지수·섹터 ETF 진행 중, 거래대금 상위 등락 |
| 06:40 | screener `US` | US 스크리너 + 섹터 tone + **내일 국장 시사점** |

리포트 저장소 `data/research.parquet`(커밋): `research.post_performance()` 로 발간 후 5/20/60일 초과수익, `broker_stats()` 로 증권사별 적중률 집계 가능 (데이터가 2~3개월 쌓인 뒤 의미 있음).

## 뉴스·이슈 레이어 (Context, 점수 미반영)

| 소스 | 시크릿 | 비고 |
|---|---|---|
| yfinance 종목 뉴스 | 없음 | 신호 상위 종목(최대 ~30개)만 최근 3일 헤드라인. US 풍부, KR 은 자주 비어 있음 |
| 텔레그램 채널 | `TG_API_ID` `TG_API_HASH` `TG_SESSION` `TG_CHANNELS` | my.telegram.org 에서 API 발급 → 로컬에서 1회 로그인해 StringSession 문자열 생성 → 시크릿 등록. 채널은 `@채널명,@채널명`. 종목명 문자열 매칭이라 오탐 있음 |
| fiscal.ai | `FISCAL_AI_KEY` | 어댑터 자리만 있음 (`news.fetch_fiscal_ai`). API 문서 확인 후 엔드포인트·필드 채워야 동작 |

StringSession 생성:
```python
from telethon.sync import TelegramClient
from telethon.sessions import StringSession
with TelegramClient(StringSession(), API_ID, API_HASH) as c:
    print(c.session.save())   # 이 문자열을 TG_SESSION 시크릿에
```
