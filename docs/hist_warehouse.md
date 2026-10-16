# 연구용 시세 창고 (data/hist/*_daily.parquet)

연구 스크립트가 ETF·지수 대신 종목 합성 프록시를 쓰던 문제를 없애기 위한 저장소 내 시세 창고.
빌드는 `scripts/build_hist.py`, 갱신은 `.github/workflows/hist.yml`(매주 토 20:00 UTC + 수동), 읽기는 `screener.hist`.
연구 코드는 **네트워크를 쓰지 않고** 이 파일만 읽는다.

## 파일

| 파일 | 내용 | 심볼 예 |
|---|---|---|
| `kr_etf_daily.parquet` | 국내 ETF (`screener.etf.KR_MUST` + 연구용 몇 개) | `069500`, `122630`, `252670`, `114800`, `091160`, `139260`, `229200`, `233740` |
| `kr_index_daily.parquet` | 국내 지수, 시가 포함 OHLC | `KOSPI`, `KOSPI200`, `KOSDAQ` |
| `kr_sector_daily.parquet` | KRX 공식 업종지수 `KRX:<이름>` + `universe/kr_sector.csv` 동일가중 합성 `EW:<업종>`, `EW:KOSPI`, `EW:KOSDAQ` | `KRX:전기전자`, `EW:전기·전자` |
| `us_daily.parquet` | 미국 지수·광역/섹터 ETF·반도체 체인·메가캡 (`build_hist.US_SYMBOLS`) | `SPY`, `QQQ`, `SOXX`, `MU`, `SNDK`, `PSI`, `^GSPC`, `^SOX` |
| `_manifest.json` | 파일·심볼별 first/last/rows/source, 전체 바이트 | |

기존 `kr_YYYY.parquet` / `us_YYYY.parquet`(종목 전체, 상폐 포함)은 그대로 두고 `screener.lab.load_kr` / `screener.backfill.load_hist` 가 계속 담당한다.

## 스키마 (long)

`date(Date) symbol(str) open high low close adj_close(Float32) volume(Float64) src(str)`

- `src`=`yfinance`(auto_adjust): `close == adj_close`, 배당·분할 반영.
- `src`=`pykrx`(KRX): `close` 원주가, `adj_close` 는 전일 종가→시가 ±45% 갭 규칙으로 분할 보정 (lab 과 같은 규칙).
- `src`=`deriv_csv` / `macro_series` / `chains_json`: 저장소 안의 기존 자료를 이어 붙인 것 (일부는 종가만, open·volume null 가능).
- `src`=`ew_composite`: 종목 일간수익 동일가중 체인, 2010-01-04 = 1000, volume null. 종목 조건: 전일 종가 ≥ 1,000원, |일간수익| ≤ 32%, 업종당 5종목 이상.
- 같은 (symbol, date) 가 여러 출처에 있으면 `pykrx > yfinance = hist_parquet = ew_composite > deriv_csv = macro_series > chains_json`.

## 읽기

```python
from screener.hist import load, wide, coverage, symbols

px = load("069500", start="2015-01-01")                      # long, (symbol, date) 정렬. '069500.KS' 도 됨
px = load(["069500", "122630", "SPY", "KOSPI"], start="2020-01-01", end="2025-12-31")   # 파일은 자동으로 찾음
w  = wide(["069500", "SPY"], field="adj_close")               # date × symbol 피벗
coverage(["069500", "SPY"])                                  # 심볼별 first/last/rows (파일을 직접 셈)
symbols()                                                    # 매니페스트: 심볼 → {file, first, last, rows, source}
```

- 파일이 없거나 심볼이 없으면 **빈 프레임**(스키마 유지)을 돌려준다 — 연구 스크립트는 `len(px)==0` 이면 "창고에 없음"으로 적고 프록시로 떨어지면 된다.
- 지수 별칭: `^KS11→KOSPI`, `^KS200→KOSPI200`, `^KQ11→KOSDAQ`.
- 테스트·오프라인 검증은 `root=` 인자 또는 `HIST_DIR` 환경변수로 다른 폴더를 가리킬 수 있다 (`tests/test_hist.py`).

## 빌드·갱신

```
python scripts/build_hist.py --offline   # 저장소 안 자료만 병합 (컨테이너에서 가능)
python scripts/build_hist.py --network   # yfinance + pykrx 로 2010~ 증분 백필 (Actions 러너)
```

- 멱등·증분: 심볼별 마지막 날짜 −14일부터만 다시 받고, 결과가 기존 파일과 같으면 다시 쓰지 않는다.
- 어느 출처가 실패해도 나머지는 진행 (ETF 는 yfinance 에 없으면 pykrx 로 폴백).
- 크기 예산 25 MB (float32 + zstd). 넘으면 경고 — `US_SYMBOLS` 를 줄인다.
- 수동 실행: `gh api -X POST repos/hk99915-bot/market-screener/actions/workflows/hist.yml/dispatches -f ref=main`

## 연구에서 바꿀 곳

- `scripts/study_semis_cap.py`: 삼성전자·하이닉스 50/50 대용치 → `load(["091160", "139260", "069500"])`.
- `screener/study.py` (급락 후 레버리지 ETF 매매): `_dl("122630.KS")` 네트워크 호출 → `load("122630")`.
- `scripts/study_playbook_signals.py`, `study_fib_levels.py`, `study_rule_audit.py`: 코스피 프록시(종목 합성) → `load("KOSPI")` (2010~ OHLC, 시가 포함) 또는 `load("EW:KOSPI")`.
- `screener/portfolios.py` K200 (`069500.KS`): `load("069500")`.
