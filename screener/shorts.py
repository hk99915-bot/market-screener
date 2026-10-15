"""공매도 — KRX(pykrx) 공매도 잔고(T+2 공시)·공매도 거래 비중 → 종목별 숏 포지션 지표와 숏스퀴즈 후보.

data/short_hist.parquet: date, code, bal_ratio(잔고/상장주식, %), bal_amt(원), vol_ratio(당일 공매도 거래 비중, %)
종목별: 최신 잔고 비중, 5·20거래일 변화, 최근 5일 평균 거래 비중
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

import polars as pl

from .config import DATA_DIR

log = logging.getLogger(__name__)
P = DATA_DIR / "short_hist.parquet"
SCHEMA = {"date": pl.Utf8, "code": pl.Utf8, "bal_ratio": pl.Float64, "bal_amt": pl.Float64, "vol_ratio": pl.Float64}


def _day(ymd: str) -> pl.DataFrame | None:
    from pykrx import stock  # type: ignore
    parts = []
    for mk in ("KOSPI", "KOSDAQ"):
        try:
            b = stock.get_shorting_balance_by_ticker(ymd, market=mk)
        except Exception:  # noqa: BLE001
            b = None
        if b is None or not len(b) or float(b["공매도잔고"].sum()) == 0:
            continue
        try:
            v = stock.get_shorting_volume_by_ticker(ymd, market=mk)
        except Exception:  # noqa: BLE001
            v = None
        vr = {str(k): float(x) for k, x in (v["비중"].items() if v is not None and "비중" in v.columns else [])}
        for code, r in b.iterrows():
            parts.append({"date": ymd, "code": str(code), "bal_ratio": float(r.get("비중") or 0), "bal_amt": float(r.get("공매도금액") or 0),
                          "vol_ratio": vr.get(str(code))})
    return pl.DataFrame(parts, schema=SCHEMA) if parts else None


def update(days_back: int = 30) -> int:
    old = pl.read_parquet(P) if P.exists() else pl.DataFrame(schema=SCHEMA)
    have = set(old["date"].unique().to_list())
    new = []
    misses = 0
    for back in range(1, days_back + 1):
        d = date.today() - timedelta(days=back)
        if d.weekday() >= 5:
            continue
        ymd = d.strftime("%Y%m%d")
        if ymd in have:
            continue
        df = _day(ymd)
        if df is None:
            misses += 1
            if misses > 6 and not new and have:
                break
            continue
        new.append(df)
        if len(new) >= 25:
            break
    if new:
        out = pl.concat([old] + new, how="vertical_relaxed").unique(["date", "code"], keep="last").sort("date", "code")
        cut = (date.today() - timedelta(days=400)).strftime("%Y%m%d")
        out.filter(pl.col("date") >= cut).write_parquet(P)
    log.info("공매도 잔고 %d일 추가", len(new))
    return len(new)


def by_code() -> dict[str, dict]:
    if not P.exists():
        return {}
    df = pl.read_parquet(P).sort("code", "date")
    ds = sorted(df["date"].unique().to_list())
    if not ds:
        return {}
    last = ds[-1]
    d5 = ds[-6] if len(ds) >= 6 else ds[0]
    d20 = ds[-21] if len(ds) >= 21 else ds[0]
    piv = {d: dict(zip(g["code"].to_list(), g["bal_ratio"].to_list())) for (d,), g in df.filter(pl.col("date").is_in([last, d5, d20])).group_by("date")}
    vr = (df.filter(pl.col("date").is_in(ds[-5:])).group_by("code").agg(pl.col("vol_ratio").mean().alias("v5")))
    vr = dict(zip(vr["code"].to_list(), vr["v5"].to_list()))
    amt = dict(zip(df.filter(pl.col("date") == last)["code"].to_list(), df.filter(pl.col("date") == last)["bal_amt"].to_list()))
    out = {}
    for c, r in piv.get(last, {}).items():
        out[c] = {"asof": f"{last[:4]}-{last[4:6]}-{last[6:]}", "ratio": r, "amt": amt.get(c),
                  "chg5": (r - piv.get(d5, {}).get(c, r)) if r is not None else None,
                  "chg20": (r - piv.get(d20, {}).get(c, r)) if r is not None else None, "vol5": vr.get(c),
                  "hist": [[x["date"], x["bal_ratio"]] for x in df.filter(pl.col("code") == c).tail(60).select("date", "bal_ratio").to_dicts()]
                  if False else None}
    return out


def squeeze_candidates(shorts: dict, peers: list[dict], n: int = 10) -> list[dict]:
    """잔고 비중 상위 + 이익 드라이버 양호 + 최근 잔고 증가 — 반등 시 되사기(숏커버) 압력이 큰 종목."""
    rows = []
    for r in peers:
        s = shorts.get(r["s"])
        if not s or s.get("ratio") is None or (r.get("mc") or 0) < 3e11:
            continue
        if s["ratio"] >= 1.0 and (r.get("drv") or 0) >= 0.1:
            rows.append({"s": r["s"], "n": r["n"], "g": r["g"], "ratio": s["ratio"], "chg20": s.get("chg20"), "drv": r.get("drv"),
                         "r20": r.get("r20"), "amt": s.get("amt")})
    rows.sort(key=lambda x: -(x["ratio"] + max(x.get("chg20") or 0, 0) * 2))
    return rows[:n]
