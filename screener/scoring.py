"""점수 체계 — 기획서 원칙 준수.

Trend Score (0~100) = 장기추세 30 + 전술추세 30 + 추세강도 20 + 구조 20
Momentum Score (0~100) = MACD 40 + 오실레이터 합성 60 (RSI 20 / Stoch 20 / CCI 20)
Reversal Risk (0~100) = 과열·이격·급등 신호 합산 (별도 축, 점수에 합산 금지)
뉴스·매크로·포지셔닝은 Context — 여기 들어오지 않음.
"""
from __future__ import annotations

import polars as pl


def _pts(cond: pl.Expr, p: float) -> pl.Expr:
    return pl.when(cond).then(pl.lit(float(p))).otherwise(0.0).fill_null(0.0)


def _clip(e: pl.Expr, lo: float, hi: float) -> pl.Expr:
    return e.clip(lo, hi).fill_null(lo)


def score(last: pl.DataFrame) -> pl.DataFrame:
    c = pl.col("close")

    # ── Trend ──
    long_trend = (
        _pts(c > pl.col("sma200"), 10)
        + _pts(pl.col("sma50") > pl.col("sma200"), 10)
        + _pts(pl.col("sma200") > pl.col("sma200_prev20"), 10)
    )
    tactical = (
        _pts(c > pl.col("sma20"), 10)
        + _pts(pl.col("sma20") > pl.col("sma50"), 10)
        + _pts(c > pl.col("cloud_top"), 10)
    )
    # 추세강도: ADX 0~50 → 0~20, 방향(+DI>-DI)일 때만. 역방향이면 0.
    strength = pl.when(pl.col("pdi") > pl.col("mdi")).then(_clip(pl.col("adx14"), 0, 50) / 50 * 20).otherwise(0.0).fill_null(0.0)
    structure = (
        _pts(c > pl.col("psar"), 10)
        + _pts(c >= pl.col("high52") * 0.90, 10)   # 52주 고점 10% 이내
    )
    trend = (long_trend + tactical + strength + structure).round(1)

    # ── Momentum ──
    macd = (
        _pts(pl.col("macd") > pl.col("macd_sig"), 15)
        + _pts(pl.col("macd") > 0, 10)
        + _pts((pl.col("macd_hist") > pl.col("macd_hist_p1")) & (pl.col("macd_hist_p1") > pl.col("macd_hist_p2")), 15)
    )
    rsi = pl.col("rsi14")
    rsi_pts = (
        pl.when(rsi.is_between(55, 70)).then(20.0)
        .when(rsi.is_between(50, 55)).then(12.0)
        .when(rsi > 70).then(10.0)         # 과열은 모멘텀 점수 일부 차감 (Reversal Risk에서 별도 반영)
        .when(rsi.is_between(45, 50)).then(5.0)
        .otherwise(0.0).fill_null(0.0)
    )
    stoch_pts = (
        _pts((pl.col("stoch_k") > pl.col("stoch_d")) & (pl.col("stoch_k") > 50), 12)
        + _pts(pl.col("stoch_k") > 20, 8)
    )
    cci = pl.col("cci20")
    cci_pts = pl.when(cci > 100).then(20.0).when(cci > 0).then(12.0).when(cci > -100).then(4.0).otherwise(0.0).fill_null(0.0)
    momentum = (macd + rsi_pts + stoch_pts + cci_pts).round(1)

    # ── Reversal Risk ──
    dist_atr = (c - pl.col("sma20")) / pl.col("atr14")
    rev = (
        _pts(rsi > 75, 25) + _pts(rsi.is_between(70, 75), 12)
        + _pts(pl.col("stoch_k") > 85, 15)
        + _pts(cci > 200, 15)
        + _pts(dist_atr > 2.5, 20) + _pts(dist_atr.is_between(1.5, 2.5), 10)
        + _pts(pl.col("ret5") > 0.12, 20) + _pts(pl.col("ret5").is_between(0.07, 0.12), 10)
        + _pts(pl.col("volume") > 3 * pl.col("vol20"), 5)
    )
    reversal = _clip(rev, 0, 100).round(1)

    out = last.with_columns(
        trend.alias("trend_score"), momentum.alias("momentum_score"), reversal.alias("reversal_risk"),
        dist_atr.round(2).alias("dist_sma20_atr"),
        (pl.col("volume") / pl.col("vol20")).round(2).alias("vol_ratio"),
        (c / pl.col("high52") - 1).alias("from_high52"),
        (pl.col("open") / pl.col("close").shift(1).over("yf") - 1).alias("_gap_unused"),
    ).drop("_gap_unused")

    # ── 분류 (Trend / Countertrend) ──
    t, m, r = pl.col("trend_score"), pl.col("momentum_score"), pl.col("reversal_risk")
    cls = (
        pl.when((t >= 65) & (m >= 55) & (r >= 60)).then(pl.lit("TREND_OVEREXTENDED"))
        .when((t >= 65) & (m >= 55)).then(pl.lit("TREND_LONG"))
        .when((t >= 60) & (m <= 40)).then(pl.lit("PULLBACK_IN_UPTREND"))
        .when((t <= 40) & (m >= 60)).then(pl.lit("COUNTERTREND_BOUNCE"))
        .when((t <= 35) & (m <= 45)).then(pl.lit("TREND_SHORT"))
        .otherwise(pl.lit("NEUTRAL"))
    )
    return out.with_columns(cls.alias("class"))


def apply_filters(last: pl.DataFrame, min_price: float, min_dollar_vol: float) -> pl.DataFrame:
    return last.filter(
        (pl.col("close") >= min_price)
        & (pl.col("dollar_vol20") >= min_dollar_vol)
        & pl.col("sma200").is_not_null()
    )
