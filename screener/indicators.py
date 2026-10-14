"""기술지표 — Polars 벡터 연산 (종목별 group_by over 'yf').

입력: long DataFrame [yf, date, open, high, low, close, volume] (yf·date 정렬 가정)
출력: 같은 행 수 + 지표 컬럼. 마지막 행(종목별 최신)만 스코어링에 사용.
Wilder 평활(RSI/ATR/DMI)은 ewm_mean(alpha=1/n) 로 근사. PSAR는 numpy 루프.
"""
from __future__ import annotations

import numpy as np
import polars as pl


def _over(e: pl.Expr) -> pl.Expr:
    return e.over("yf")


def _wilder(e: pl.Expr, n: int) -> pl.Expr:
    return _over(e.ewm_mean(alpha=1 / n, adjust=False, min_samples=n))


def psar_np(high: np.ndarray, low: np.ndarray, close: np.ndarray,
            af0: float = 0.02, af_max: float = 0.2) -> np.ndarray:
    n = len(close)
    out = np.full(n, np.nan)
    if n < 3:
        return out
    up = close[1] >= close[0]
    sar = low[0] if up else high[0]
    ep = high[0] if up else low[0]
    af = af0
    for i in range(1, n):
        sar = sar + af * (ep - sar)
        if up:
            sar = min(sar, low[i - 1], low[i - 2] if i >= 2 else low[i - 1])
            if low[i] < sar:
                up, sar, ep, af = False, ep, low[i], af0
            elif high[i] > ep:
                ep, af = high[i], min(af + af0, af_max)
        else:
            sar = max(sar, high[i - 1], high[i - 2] if i >= 2 else high[i - 1])
            if high[i] > sar:
                up, sar, ep, af = True, ep, high[i], af0
            elif low[i] < ep:
                ep, af = low[i], min(af + af0, af_max)
        out[i] = sar
    return out


def add_indicators(df: pl.DataFrame) -> pl.DataFrame:
    c, h, l, v = pl.col("close"), pl.col("high"), pl.col("low"), pl.col("volume")
    prev_c = _over(c.shift(1))

    tr = pl.max_horizontal(h - l, (h - prev_c).abs(), (l - prev_c).abs())
    up_move = h - _over(h.shift(1))
    down_move = _over(l.shift(1)) - l
    plus_dm = pl.when((up_move > down_move) & (up_move > 0)).then(up_move).otherwise(0.0)
    minus_dm = pl.when((down_move > up_move) & (down_move > 0)).then(down_move).otherwise(0.0)

    delta = c - prev_c
    gain = pl.when(delta > 0).then(delta).otherwise(0.0)
    loss = pl.when(delta < 0).then(-delta).otherwise(0.0)

    df = df.with_columns(
        # 이동평균
        _over(c.rolling_mean(5)).alias("sma5"), _over(c.rolling_mean(20)).alias("sma20"),
        _over(c.rolling_mean(50)).alias("sma50"), _over(c.rolling_mean(200)).alias("sma200"),
        # 수익률
        (c / prev_c - 1).alias("ret1"),
        (c / _over(c.shift(5)) - 1).alias("ret5"),
        (c / _over(c.shift(20)) - 1).alias("ret20"),
        (c / _over(c.shift(60)) - 1).alias("ret60"),
        # 거래대금·거래량
        (c * v).alias("dollar_vol"),
        _over((c * v).rolling_mean(20)).alias("dollar_vol20"),
        _over(v.rolling_mean(20)).alias("vol20"),
        # 52주
        _over(h.rolling_max(250, min_samples=120)).alias("high52"),
        _over(l.rolling_min(250, min_samples=120)).alias("low52"),
        # ATR / DMI 원재료
        _wilder(tr, 14).alias("atr14"),
        _wilder(plus_dm, 14).alias("pdm14"), _wilder(minus_dm, 14).alias("mdm14"),
        # RSI 원재료
        _wilder(gain, 14).alias("ag14"), _wilder(loss, 14).alias("al14"),
        # MACD
        (_over(c.ewm_mean(span=12, adjust=False)) - _over(c.ewm_mean(span=26, adjust=False))).alias("macd"),
        # Stochastic 원재료
        _over(l.rolling_min(14)).alias("ll14"), _over(h.rolling_max(14)).alias("hh14"),
        # CCI
        ((h + l + c) / 3).alias("tp"),
        # 일목균형표
        ((_over(h.rolling_max(9)) + _over(l.rolling_min(9))) / 2).alias("tenkan"),
        ((_over(h.rolling_max(26)) + _over(l.rolling_min(26))) / 2).alias("kijun"),
        ((_over(h.rolling_max(52)) + _over(l.rolling_min(52))) / 2).alias("senkou_b_raw"),
        (c - _over(c.shift(26))).alias("_dummy"),
    )
    df = df.with_columns(
        _over(pl.col("macd").ewm_mean(span=9, adjust=False)).alias("macd_sig"),
        (100 * pl.col("pdm14") / pl.col("atr14")).alias("pdi"),
        (100 * pl.col("mdm14") / pl.col("atr14")).alias("mdi"),
        (100 - 100 / (1 + pl.col("ag14") / pl.col("al14"))).alias("rsi14"),
        (100 * (c - pl.col("ll14")) / (pl.col("hh14") - pl.col("ll14"))).alias("stoch_k_raw"),
        ((pl.col("tp") - _over(pl.col("tp").rolling_mean(20)))
         / (0.015 * _over((pl.col("tp") - pl.col("tp").rolling_mean(20)).abs().rolling_mean(20)))).alias("cci20"),
        # 선행스팬: 26일 전에 계산된 값이 오늘 구름. shift(26) 으로 '오늘 구름' 산출
        _over(((pl.col("tenkan") + pl.col("kijun")) / 2).shift(26)).alias("senkou_a"),
        _over(pl.col("senkou_b_raw").shift(26)).alias("senkou_b"),
        _over(pl.col("sma200").shift(20)).alias("sma200_prev20"),
        _over(pl.col("sma50").shift(10)).alias("sma50_prev10"),
    )
    df = df.with_columns(
        (pl.col("macd") - pl.col("macd_sig")).alias("macd_hist"),
        (100 * (pl.col("pdi") - pl.col("mdi")).abs() / (pl.col("pdi") + pl.col("mdi"))).alias("dx"),
        _over(pl.col("stoch_k_raw").rolling_mean(3)).alias("stoch_k"),
    ).with_columns(
        _wilder(pl.col("dx"), 14).alias("adx14"),
        _over(pl.col("stoch_k").rolling_mean(3)).alias("stoch_d"),
        _over(pl.col("macd_hist").shift(1)).alias("macd_hist_p1"),
        _over(pl.col("macd_hist").shift(2)).alias("macd_hist_p2"),
        pl.max_horizontal("senkou_a", "senkou_b").alias("cloud_top"),
        pl.min_horizontal("senkou_a", "senkou_b").alias("cloud_bot"),
    ).drop("_dummy", "senkou_b_raw", "tp", "ll14", "hh14", "ag14", "al14", "pdm14", "mdm14", "stoch_k_raw")

    # PSAR (numpy, 종목별)
    psar_parts = []
    for (sym,), g in df.group_by("yf", maintain_order=True):
        psar_parts.append(pl.DataFrame({
            "yf": sym, "date": g["date"],
            "psar": psar_np(g["high"].to_numpy(), g["low"].to_numpy(), g["close"].to_numpy()),
        }))
    df = df.join(pl.concat(psar_parts), on=["yf", "date"], how="left")
    return df


def latest(df: pl.DataFrame) -> pl.DataFrame:
    """종목별 최신 행."""
    return df.group_by("yf", maintain_order=True).tail(1)
