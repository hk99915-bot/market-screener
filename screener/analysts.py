"""애널리스트(증권사×작성자)별 성향·적중률 → reports/analysts.json

리포트 발간일 이후 첫 거래일 종가를 기준으로:
- 발간 시 여력: 목표가 / 기준가 − 1  (낙관 성향 측정)
- 60영업일 초과수익: 종목 수익률 − 시장(전종목 중앙값) 수익률  (매수 의견 적중 측정)
- 목표가 도달률: 250영업일 안에 고가가 목표가에 닿았는가 (기간이 덜 지난 리포트는 제외)
표본이 적으면(기본 8건 미만) 수치를 싣되 '표본 부족'으로 표시한다.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import polars as pl

from .config import REPORT_DIR
from .research import _norm_broker, load_store, opinion_rank

log = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")


def _prices(since) -> pl.DataFrame:
    from .prices import load_kr   # 분할·병합 조정 (60일 초과수익·250일 고점이 기업행위로 왜곡되지 않게)
    px = load_kr(hist_from=since.year - 1)
    if not len(px):
        return pl.DataFrame()
    px = px.select("yf", "date", "high", "close")
    return px.with_columns(pl.col("yf").str.slice(0, 6).alias("code")).sort("code", "date")


def perf(store: pl.DataFrame, px: pl.DataFrame) -> pl.DataFrame:
    p = px.with_columns((pl.col("close") / pl.col("close").shift(1).over("code") - 1).alias("r"))
    mkt = (p.group_by("date").agg(pl.col("r").median().alias("mr")).sort("date")
             .with_columns((1 + pl.col("mr").fill_null(0)).cum_prod().alias("mkt")))
    p = (p.join(mkt.select("date", "mkt"), on="date", how="left")
          .with_columns(
              pl.col("close").shift(-60).over("code").alias("c60"),
              pl.col("mkt").shift(-60).over("code").alias("m60"),
              pl.col("high").reverse().rolling_max(250, min_samples=250).reverse().shift(-1).over("code").alias("hmax250"),
          ))
    rep = (store.filter(pl.col("target").is_not_null() & pl.col("code").is_not_null())
                .select("key", "date", "code", "broker", "analyst", "opinion", "target").sort("date"))
    j = rep.join_asof(p.select("code", "date", "close", "mkt", "c60", "m60", "hmax250").rename({"date": "pdate"}).sort("pdate"),
                      left_on="date", right_on="pdate", by="code", strategy="forward", tolerance="5d")
    return j.with_columns(
        (pl.col("target") / pl.col("close") - 1).alias("upside"),
        ((pl.col("c60") / pl.col("close")) - (pl.col("m60") / pl.col("mkt"))).alias("exc60"),
        pl.when(pl.col("hmax250").is_not_null()).then(pl.col("hmax250") >= pl.col("target")).otherwise(None).alias("tp_hit"),
        pl.col("opinion").map_elements(opinion_rank, return_dtype=pl.Int8).alias("op"),
        pl.col("broker").map_elements(_norm_broker, return_dtype=pl.Utf8).alias("b"),
    )


def build(min_n: int = 8) -> int:
    store = load_store()
    if store.is_empty() or store["analyst"].null_count() == len(store):
        log.info("애널리스트 정보 없음 — 건너뜀")
        return 0
    since = store["date"].min()
    px = _prices(since)
    if px.is_empty():
        return 0
    x = perf(store.filter(pl.col("analyst").is_not_null() & (pl.col("analyst") != "")), px)
    x = x.with_columns(pl.col("upside").clip(-0.9, 3.0))   # 액면분할 등 이상치 완화
    mkt_up = x["upside"].median()
    g = (x.group_by("b", "analyst").agg(
            pl.len().alias("n"),
            pl.col("code").n_unique().alias("stocks"),
            pl.col("upside").median().alias("upside_med"),
            (pl.col("op") == 2).mean().alias("buy_share"),
            pl.col("exc60").filter(pl.col("op") == 2).mean().alias("exc60_buy"),
            (pl.col("exc60").filter(pl.col("op") == 2) > 0).mean().alias("hit60_buy"),
            pl.col("exc60").filter(pl.col("op") == 2).count().alias("n60"),
            pl.col("tp_hit").cast(pl.Float64).mean().alias("tp_hit"),
            pl.col("tp_hit").count().alias("n_tp"),
            pl.col("date").max().alias("last"),
            pl.col("code").mode().first().alias("top_code"),
        ))
    out = {}
    for r in g.to_dicts():
        style = []
        if r["upside_med"] is not None and mkt_up is not None:
            if r["upside_med"] > mkt_up + 0.10:
                style.append("낙관 성향(목표가 높게)")
            elif r["upside_med"] < mkt_up - 0.08:
                style.append("보수적 목표가")
        if r["buy_share"] is not None and r["buy_share"] < 0.7 and r["n"] >= min_n:
            style.append("중립·매도 의견도 내는 편")
        if r["n60"] >= min_n and r["hit60_buy"] is not None:
            if r["hit60_buy"] >= 0.6:
                style.append("매수 적중률 높음")
            elif r["hit60_buy"] <= 0.4:
                style.append("매수 적중률 낮음")
        rd = lambda v, k=3: None if v is None else round(float(v), k)  # noqa: E731
        out[f"{r['b']}|{r['analyst']}"] = {
            "broker": r["b"], "analyst": r["analyst"], "n": r["n"], "stocks": r["stocks"],
            "upside_med": rd(r["upside_med"]), "buy_share": rd(r["buy_share"]),
            "exc60_buy": rd(r["exc60_buy"]), "hit60_buy": rd(r["hit60_buy"]), "n60": r["n60"],
            "tp_hit": rd(r["tp_hit"]), "n_tp": r["n_tp"], "last": str(r["last"]),
            "style": style, "thin": r["n60"] < min_n,
        }
    meta = {"asof": datetime.now(KST).strftime("%Y-%m-%d %H:%M KST"), "from": str(since),
            "market_upside_med": None if mkt_up is None else round(float(mkt_up), 3), "min_n": min_n,
            "note": "60영업일 초과수익 = 종목 − 전종목 중앙값. 목표가 도달 = 250영업일 내 고가 기준. 과거 성과이며 미래를 보장하지 않음."}
    (REPORT_DIR / "analysts.json").write_text(json.dumps({"meta": meta, "analysts": out}, ensure_ascii=False), encoding="utf-8")
    log.info("애널리스트 %d명 (기간 %s~)", len(out), since)
    return len(out)
