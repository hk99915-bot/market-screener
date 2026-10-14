"""시세 수집 (yfinance) → Parquet 캐시.

정규장 일봉만 사용 (기획 원칙: 시간외/프리·애프터는 기술지표에 섞지 않음).
yfinance 일봉은 정규장 OHLCV이므로 조건 충족. 배당/분할 조정은 auto_adjust=True.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

import polars as pl

from .config import CFG, DATA_DIR

log = logging.getLogger(__name__)


def fetch_prices(yf_symbols: list[str], market: str, lookback_days: int | None = None) -> pl.DataFrame:
    """long 포맷 [yf, date, open, high, low, close, volume] 반환."""
    import pandas as pd
    import yfinance as yf

    lookback_days = lookback_days or CFG.lookback_days
    start = (date.today() - timedelta(days=lookback_days)).isoformat()
    frames: list[pl.DataFrame] = []
    bs = CFG.batch_size
    for i in range(0, len(yf_symbols), bs):
        chunk = yf_symbols[i:i + bs]
        try:
            raw = yf.download(chunk, start=start, auto_adjust=True, group_by="ticker",
                              threads=CFG.threads, progress=False, timeout=60)
        except Exception as e:  # noqa: BLE001
            log.warning("배치 %d 실패: %s", i // bs, e)
            continue
        if raw is None or raw.empty:
            continue
        if len(chunk) == 1:  # 단일 티커면 컬럼이 1단계
            raw = pd.concat({chunk[0]: raw}, axis=1)
        for sym in chunk:
            if sym not in raw.columns.get_level_values(0):
                continue
            d = raw[sym].dropna(subset=["Close"])
            if d.empty:
                continue
            frames.append(pl.DataFrame({
                "yf": sym,
                "date": [x.date() for x in pd.to_datetime(d.index)],
                "open": d["Open"].astype(float).values, "high": d["High"].astype(float).values,
                "low": d["Low"].astype(float).values, "close": d["Close"].astype(float).values,
                "volume": d["Volume"].fillna(0).astype(float).values,
            }))
        log.info("%s 시세 배치 %d/%d", market, i // bs + 1, (len(yf_symbols) + bs - 1) // bs)
    if not frames:
        raise RuntimeError(f"{market} 시세 수집 결과 없음")
    df = pl.concat(frames).with_columns(pl.col("date").cast(pl.Date)).sort("yf", "date")
    DATA_DIR.mkdir(exist_ok=True)
    df.write_parquet(DATA_DIR / f"{market.lower()}_prices.parquet")
    return df


def load_cached(market: str) -> pl.DataFrame | None:
    p = DATA_DIR / f"{market.lower()}_prices.parquet"
    return pl.read_parquet(p) if p.exists() else None


def fetch_macro() -> pl.DataFrame:
    """매크로 컨텍스트 시계열 (long). 실패해도 전체 파이프라인은 계속."""
    try:
        df = fetch_prices(list(CFG.macro.values()), "MACRO", lookback_days=200)
        inv = {v: k for k, v in CFG.macro.items()}
        return df.with_columns(pl.col("yf").replace_strict(inv, default=pl.col("yf")).alias("key"))
    except Exception as e:  # noqa: BLE001
        log.warning("매크로 수집 실패: %s", e)
        return pl.DataFrame(schema={"key": pl.Utf8, "date": pl.Date, "close": pl.Float64})
