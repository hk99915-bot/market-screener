"""Context 레이어 — 시장 폭(breadth), 이상 신호, 매크로 레짐.
점수에 합산하지 않고 리포트 옆에 붙이는 정보만 생성.
"""
from __future__ import annotations

import polars as pl


def breadth(last: pl.DataFrame, full: pl.DataFrame) -> dict:
    """last: 필터 후 최신행, full: 지표 포함 전체 시계열(동일 종목 집합)."""
    n = len(last)
    if n == 0:
        return {}
    c = pl.col("close")
    agg = last.select(
        (c > pl.col("sma20")).mean().alias("pct_above20"),
        (c > pl.col("sma50")).mean().alias("pct_above50"),
        (c > pl.col("sma200")).mean().alias("pct_above200"),
        (pl.col("ret1") > 0).sum().alias("adv"), (pl.col("ret1") < 0).sum().alias("dec"),
        (pl.col("high") >= pl.col("high52")).sum().alias("new_high52"),
        (pl.col("low") <= pl.col("low52")).sum().alias("new_low52"),
        pl.col("ret1").median().alias("median_ret1"),
        (pl.col("class") == "TREND_LONG").sum().alias("n_trend_long"),
        (pl.col("class") == "TREND_SHORT").sum().alias("n_trend_short"),
    ).to_dicts()[0]
    agg["n"] = n
    # 20일 전 대비 % above 200 변화 (브레드스 추세)
    last_date = last["date"].max()
    prev = (full.filter(pl.col("yf").is_in(last["yf"].implode()))
                .group_by("yf").agg(pl.all().sort_by("date").slice(-21, 1).first()))
    if len(prev):
        agg["pct_above200_20d_ago"] = float(prev.select((pl.col("close") > pl.col("sma200")).mean()).item() or 0)
    agg["date"] = str(last_date)
    return agg


def anomalies(last: pl.DataFrame, full: pl.DataFrame) -> pl.DataFrame:
    """거래량 ≥3× 20일 평균 또는 갭 ≥5%. gap 은 full 에서 계산."""
    gap = (full.with_columns((pl.col("open") / pl.col("close").shift(1).over("yf") - 1).alias("gap"))
               .group_by("yf").tail(1).select("yf", "gap"))
    x = last.join(gap, on="yf", how="left")
    return (x.filter((pl.col("vol_ratio") >= 3) | (pl.col("gap").abs() >= 0.05))
             .select("symbol", "name", "market", "close", "ret1", "gap", "vol_ratio", "class",
                     "trend_score", "momentum_score", "reversal_risk")
             .sort("vol_ratio", descending=True))


def macro_regime(macro: pl.DataFrame) -> list[dict]:
    """키별 현재값·1일·20일 변화·50일선 대비 → 간단 레짐 라벨."""
    out = []
    if macro.is_empty():
        return out
    for key, g in macro.group_by("key", maintain_order=True):
        g = g.sort("date")
        c = g["close"].to_numpy()
        if len(c) < 25:
            continue
        sma50 = c[-50:].mean() if len(c) >= 50 else c.mean()
        d = {
            "key": key[0] if isinstance(key, tuple) else key,
            "last": float(c[-1]), "chg1": float(c[-1] / c[-2] - 1), "chg20": float(c[-1] / c[-21] - 1),
            "vs_sma50": float(c[-1] / sma50 - 1),
        }
        d["regime"] = "상승" if d["vs_sma50"] > 0.02 else "하락" if d["vs_sma50"] < -0.02 else "중립"
        out.append(d)
    order = ["KOSPI", "KOSDAQ", "SPX", "NASDAQ", "RUT", "VIX", "US10Y", "DXY", "USDKRW", "USDJPY", "WTI", "GOLD", "BTC"]
    out.sort(key=lambda d: order.index(d["key"]) if d["key"] in order else 99)
    return out


def regime_summary(mr: list[dict]) -> str:
    """매크로 컨텍스트 한 줄 (규칙 기반). 점수와 무관한 설명문."""
    m = {d["key"]: d for d in mr}
    notes = []
    if "VIX" in m:
        v = m["VIX"]["last"]
        notes.append("변동성 고조" if v >= 25 else "변동성 상승" if v >= 20 else "변동성 안정")
    if "US10Y" in m:
        notes.append(f"미10년물 {m['US10Y']['regime']}")
    if "DXY" in m:
        notes.append(f"달러 {m['DXY']['regime']}")
    if "WTI" in m:
        notes.append(f"WTI {m['WTI']['regime']}")
    if "USDJPY" in m and abs(m["USDJPY"]["chg20"]) > 0.03:
        notes.append("엔화 " + ("약세 가속" if m["USDJPY"]["chg20"] > 0 else "강세 전환"))
    return " · ".join(notes)
