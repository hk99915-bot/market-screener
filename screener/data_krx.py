"""KR 시세 — KRX 공식 데이터 (yfinance 대체).

백엔드 (환경변수 KRX_BACKEND, 기본 pykrx)
  pykrx   : data.krx.co.kr 스크래핑. 날짜별 전종목 OHLCV → 하루 2콜(KOSPI/KOSDAQ). 키 불필요.
  openapi : KRX Open API (openapi.krx.co.kr). KRX_API_KEY 필요. 엔드포인트는 KRX_OPENAPI_STK/KSQ 로 지정.

방식: data/kr_prices.parquet 를 증분 갱신 (마지막 저장일 다음 영업일부터 오늘까지만 호출).
      최초 백필(약 400 영업일 ≈ 800콜)은 국내 IP(내 PC)에서 한 번 돌리고 Parquet 를 커밋하는 걸 권장.
수정주가: KRX 전종목 일별 시세는 '당일 실제 가격'이라 액면분할·병합 시 과거와 단절됨.
      전일 종가 대비 시가가 ±45% 를 넘는 날(상하한 30% 밖)을 기업행위로 보고, 그 이전 구간을 비율로 조정.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import date, timedelta

import polars as pl

from .config import DATA_DIR

log = logging.getLogger(__name__)
PARQUET = DATA_DIR / "kr_prices.parquet"
SCHEMA = {"yf": pl.Utf8, "date": pl.Date, "open": pl.Float64, "high": pl.Float64,
          "low": pl.Float64, "close": pl.Float64, "volume": pl.Float64}


# ───────────── 백엔드 ─────────────

def _pykrx_day(d: date) -> pl.DataFrame:
    from pykrx import stock  # type: ignore
    frames = []
    for mkt, suf in (("KOSPI", ".KS"), ("KOSDAQ", ".KQ")):
        df = stock.get_market_ohlcv_by_ticker(d.strftime("%Y%m%d"), market=mkt)
        if df is None or df.empty:
            continue
        df = df[df["거래량"] > 0]  # 휴장일·거래정지 제외
        frames.append(pl.DataFrame({
            "yf": [t + suf for t in df.index], "date": d,
            "open": df["시가"].astype(float).values, "high": df["고가"].astype(float).values,
            "low": df["저가"].astype(float).values, "close": df["종가"].astype(float).values,
            "volume": df["거래량"].astype(float).values,
        }))
        time.sleep(0.3)  # KRX 차단 방지
    return pl.concat(frames) if frames else pl.DataFrame(schema=SCHEMA)


def _openapi_day(d: date) -> pl.DataFrame:
    """KRX Open API. 응답 필드명은 계정 문서 기준으로 아래 매핑만 손보면 됨."""
    import requests
    key = os.environ["KRX_API_KEY"]
    eps = {".KS": os.environ.get("KRX_OPENAPI_STK", "https://data-dbg.krx.co.kr/svc/apis/sto/stk_bydd_trd"),
           ".KQ": os.environ.get("KRX_OPENAPI_KSQ", "https://data-dbg.krx.co.kr/svc/apis/sto/ksq_bydd_trd")}
    fmap = {"code": "ISU_CD", "open": "TDD_OPNPRC", "high": "TDD_HGPRC", "low": "TDD_LWPRC",
            "close": "TDD_CLSPRC", "volume": "ACC_TRDVOL"}
    frames = []
    for suf, url in eps.items():
        r = requests.get(url, headers={"AUTH_KEY": key}, params={"basDd": d.strftime("%Y%m%d")}, timeout=30)
        r.raise_for_status()
        rows = r.json().get("OutBlock_1", [])
        num = lambda v: float(str(v).replace(",", "") or 0)  # noqa: E731
        rows = [x for x in rows if num(x.get(fmap["volume"], 0)) > 0]
        if rows:
            frames.append(pl.DataFrame({
                "yf": [x[fmap["code"]] + suf for x in rows], "date": d,
                **{k: [num(x[fmap[k]]) for x in rows] for k in ("open", "high", "low", "close", "volume")},
            }))
    return pl.concat(frames) if frames else pl.DataFrame(schema=SCHEMA)


def _fetch_day(d: date) -> pl.DataFrame:
    be = os.environ.get("KRX_BACKEND", "pykrx")
    return _openapi_day(d) if be == "openapi" else _pykrx_day(d)


# ───────────── 증분 갱신 ─────────────

def update(lookback_days: int = 400, max_calls: int = 450) -> pl.DataFrame:
    DATA_DIR.mkdir(exist_ok=True)
    hist = pl.read_parquet(PARQUET) if PARQUET.exists() else pl.DataFrame(schema=SCHEMA)
    start = (hist["date"].max() + timedelta(days=1)) if len(hist) else date.today() - timedelta(days=lookback_days)
    days = [start + timedelta(i) for i in range((date.today() - start).days + 1)]
    days = [d for d in days if d.weekday() < 5][-max_calls:]
    new, fails = [], 0
    for d in days:
        try:
            df = _fetch_day(d)
            if len(df):
                new.append(df)
            log.info("KRX %s: %d행", d, len(df))
        except Exception as e:  # noqa: BLE001
            fails += 1
            log.warning("KRX %s 실패: %s", d, e)
            if fails >= 5:
                raise RuntimeError("KRX 연속 실패 — IP 차단 또는 사이트 변경 가능성") from e
    if new:
        hist = pl.concat([hist, pl.concat(new)]).unique(subset=["yf", "date"], keep="last")
    if not len(hist):
        raise RuntimeError("KRX 시세 없음")
    hist = hist.sort("yf", "date")
    hist.write_parquet(PARQUET)
    return hist


# ───────────── 기업행위 조정 ─────────────

def adjust_splits(df: pl.DataFrame, threshold: float = 0.45) -> pl.DataFrame:
    """전일 종가→당일 시가 비율이 ±45% 를 넘으면 그 이전 구간을 비율로 보정 (가격은 나누고 거래량은 곱함)."""
    df = df.sort("yf", "date").with_columns(
        (pl.col("open") / pl.col("close").shift(1).over("yf")).alias("_r"))
    ev = df.filter((pl.col("_r") > 1 + threshold) | (pl.col("_r") < 1 - threshold)).select("yf", "date", "_r")
    if not len(ev):
        return df.drop("_r")
    log.info("기업행위 추정 %d건 → 과거 구간 조정", len(ev))
    # 각 이벤트 이전 구간에 누적 비율 적용
    df = df.with_columns(pl.lit(1.0).alias("_f"))
    for r in ev.to_dicts():
        df = df.with_columns(
            pl.when((pl.col("yf") == r["yf"]) & (pl.col("date") < r["date"]))
              .then(pl.col("_f") * r["_r"]).otherwise(pl.col("_f")).alias("_f"))
    return df.with_columns(
        *[(pl.col(c) * pl.col("_f")).alias(c) for c in ("open", "high", "low", "close")],
        (pl.col("volume") / pl.col("_f")).alias("volume"),
    ).drop("_r", "_f")


def fetch_prices_krx() -> pl.DataFrame:
    return adjust_splits(update())
