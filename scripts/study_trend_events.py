#!/usr/bin/env python3
"""새 추세 진입 전략군(hi52·gcv·sqz) 단면 이벤트 연구 — 사전등록 docs/valuation_notes/2026-10-24_trend_events_prereg.md (퀀트).

  python3 scripts/study_trend_events.py          # reports/studies/2026-10-24_trend_events.json
  python3 scripts/study_trend_events.py --quick  # 2016~ 점검(파일 안 씀)

정의는 사전등록 §1 그대로(= screener/trend_discovery.py 상수). 이벤트 = 상태 0→1, t+1 시가 → t+21 종가, 비용 0.25%,
초과 = 같은 t 유동 종목 중앙값 대비, 표본 단위 = 달. m = 6, Bonferroni 단측 t ≥ 2.39. 영향 범위: 연구 파일만(워크플로·화면 없음).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
KST = timezone(timedelta(hours=9))
STUDY = "2026-10-24_trend_events"
OUT = ROOT / "reports" / "studies" / f"{STUDY}.json"
STRATS = ("hi52", "gcv", "sqz")
M = 6
T_BONF = 2.39
T_C = 1.645
COST = 0.0025
H, H2 = 20, 60
GAP = 20
LIQ = {"KR": (1e9, 1000.0), "US": (2e7, 5.0)}
SPLIT = "2020-01-01"


def load(market: str, years) -> pl.DataFrame:
    fs = [ROOT / "data" / "hist" / f"{market.lower()}_{y}.parquet" for y in years]
    df = pl.concat([pl.read_parquet(f, columns=["yf", "date", "open", "high", "low", "close", "volume"]) for f in fs if f.exists()],
                   how="vertical_relaxed")
    df = df.filter(pl.col("close").is_not_null() & (pl.col("close") > 0)).unique(["yf", "date"]).sort("yf", "date")
    mv, mp = LIQ[market]
    c, o = pl.col("close"), pl.col("open")
    df = df.with_columns(
        (c * pl.col("volume")).rolling_mean(20).over("yf").alias("val20"),
        (c / c.shift(1).over("yf") - 1).abs().alias("absr"),
        (c.shift(-(H + 1)).over("yf") / o.shift(-1).over("yf") - 1).alias("f20"),
        (c.shift(-(H2 + 1)).over("yf") / o.shift(-1).over("yf") - 1).alias("f60"),
    )
    df = df.with_columns(
        ((pl.col("val20") >= mv) & (c >= mp) & pl.col("open").shift(-1).over("yf").is_not_null()
         & (pl.col("open").shift(-1).over("yf") > 0)).fill_null(False).alias("liq"),
        (pl.col("absr") > 0.4).cast(pl.Int8).shift(-(H + 1)).over("yf").rolling_max(252 + H + 2).over("yf").fill_null(1).alias("bad"),
    )
    med = (df.filter(pl.col("liq")).group_by("date")
             .agg(pl.col("f20").median().alias("m20"), pl.col("f60").median().alias("m60"), pl.len().alias("n_uni")))
    return df.join(med, on="date", how="left")


def states(c, h, v) -> dict[str, np.ndarray]:
    """사전등록 §1 상태 열 → 0→1 전환일 bool."""
    s = pd.Series(c)
    s20, s50 = s.rolling(20).mean().to_numpy(), s.rolling(50).mean().to_numpy()
    hi252 = s.shift(1).rolling(252).max().to_numpy()
    vs = pd.Series(v)
    v5, v50 = vs.rolling(5).mean().to_numpy(), vs.rolling(50).mean().to_numpy()
    bw = (4 * s.rolling(20).std(ddof=0) / s.rolling(20).mean())
    thr = bw.shift(1).rolling(250, min_periods=120).quantile(0.2, interpolation="lower").to_numpy()
    bwmin5 = bw.shift(1).rolling(5, min_periods=1).min().to_numpy()
    hi20 = pd.Series(h).shift(1).rolling(20).max().to_numpy()
    n = len(c)
    ev = {k: np.zeros(n, bool) for k in STRATS}
    st = {k: 0 for k in STRATS}
    for i in range(1, n):
        if np.isnan(s50[i]):
            continue
        # hi52
        if st["hi52"]:
            st["hi52"] = 0 if c[i] < s50[i] else 1
        elif not np.isnan(hi252[i]) and c[i] > hi252[i]:
            st["hi52"] = 1
            ev["hi52"][i] = True
        # gcv
        if st["gcv"]:
            st["gcv"] = 0 if s20[i] < s50[i] else 1
        elif (not np.isnan(s50[i - 1]) and s20[i] > s50[i] and s20[i - 1] <= s50[i - 1]
              and v50[i] > 0 and v5[i] >= 1.2 * v50[i]):
            st["gcv"] = 1
            ev["gcv"][i] = True
        # sqz
        if st["sqz"]:
            st["sqz"] = 0 if c[i] < s20[i] else 1
        elif not np.isnan(thr[i]) and not np.isnan(hi20[i]) and bwmin5[i] <= thr[i] and c[i] > hi20[i]:
            st["sqz"] = 1
            ev["sqz"][i] = True
    return ev


def events(df: pl.DataFrame) -> pl.DataFrame:
    rows = []
    for part in df.partition_by("yf", maintain_order=True):
        c = part["close"].to_numpy().astype(float)
        if len(c) < 120:
            continue
        h = part["high"].fill_null(part["close"]).to_numpy().astype(float)
        v = part["volume"].fill_null(0).to_numpy().astype(float)
        ev = states(c, h, v)
        v20 = pd.Series(v).rolling(20).mean().to_numpy()
        c20 = pd.Series(c).rolling(20).max().to_numpy()
        chase = (v >= 3 * v20) & (c >= c20)   # HF S4/S6 정의(사후 서술용 꼬리표 — 등급에 안 씀)
        liq, bad = part["liq"].to_numpy(), part["bad"].to_numpy()
        f20, m20, f60, m60 = (part[k].to_numpy() for k in ("f20", "m20", "f60", "m60"))
        dates = part["date"].to_list()
        sym = part["yf"][0]
        for k in STRATS:
            last = -10 ** 9
            for i in np.flatnonzero(ev[k]):
                if i - last < GAP:
                    continue
                if not liq[i] or bad[i] or f20[i] is None or np.isnan(f20[i]) or m20[i] is None or np.isnan(m20[i]):
                    continue
                last = i
                ex60 = None if (f60[i] is None or np.isnan(f60[i]) or m60[i] is None or np.isnan(m60[i])) else float(f60[i] - COST - m60[i])
                rows.append({"strat": k, "yf": sym, "date": dates[i], "ex": float(f20[i] - COST - m20[i]), "ex60": ex60,
                             "chase": bool(chase[i])})
    return pl.DataFrame(rows, schema={"strat": pl.Utf8, "yf": pl.Utf8, "date": pl.Date, "ex": pl.Float64, "ex60": pl.Float64,
                                     "chase": pl.Boolean})


def mstats(e: pl.DataFrame, col: str = "ex") -> dict:
    e = e.filter(pl.col(col).is_not_null())
    if not len(e):
        return {"n": 0, "months": 0}
    mo = e.group_by(pl.col("date").dt.strftime("%Y-%m").alias("m")).agg(pl.col(col).mean().alias("x")).sort("m")
    x = mo["x"].to_numpy()
    k = len(x)
    mu = float(x.mean())
    sd = float(x.std(ddof=1)) if k > 1 else float("nan")
    t = mu / (sd / math.sqrt(k)) if k > 1 and sd > 0 else None
    return {"n": len(e), "months": k, "mean_m": round(mu, 5), "t": None if t is None else round(t, 2),
            "mean_ev": round(float(e[col].mean()), 5), "median_ev": round(float(e[col].median()), 5),
            "hit": round(float((e[col] > 0).mean()), 3)}


def grade(is_, oos, y22) -> str:
    if oos.get("months", 0) < 30 or oos.get("n", 0) < 100:
        return "검증전"
    mo, to = oos.get("mean_m"), oos.get("t") or 0
    b = mo > 0 and to >= T_BONF and (is_.get("mean_m") or 0) > 0
    if b and (is_.get("t") or 0) >= T_BONF and (y22.get("mean_m") or -1) > 0:
        return "A"
    if b:
        return "B"
    if mo > 0 and to >= T_C:
        return "C"
    if mo < 0 and to <= -T_C:
        return "C(역방향)"
    return "F"


def run(market: str, years) -> dict:
    df = load(market, years)
    E = events(df)
    out = {"symbols": df["yf"].n_unique(), "first": str(df["date"].min()), "last": str(df["date"].max()),
           "uni_median_n": int(df.filter(pl.col("n_uni").is_not_null())["n_uni"].median() or 0), "cells": {}}
    sp = datetime.fromisoformat(SPLIT).date()
    for k in STRATS:
        e = E.filter(pl.col("strat") == k)
        is_, oos = mstats(e.filter(pl.col("date") < sp)), mstats(e.filter(pl.col("date") >= sp))
        y22 = mstats(e.filter(pl.col("date").dt.year() == 2022))
        by_year = {str(y): mstats(e.filter(pl.col("date").dt.year() == y)).get("mean_m")
                   for y in sorted(set(e["date"].dt.year().to_list()))}
        out["cells"][k] = {"is": is_, "oos": oos, "y2022": y22, "grade": grade(is_, oos, y22),
                           "h60": {"is": mstats(e.filter(pl.col("date") < sp), "ex60"), "oos": mstats(e.filter(pl.col("date") >= sp), "ex60")},
                           "by_year_mean_m": by_year,
                           # 사후 서술(사전등록 밖): HF S4/S6 추격 패턴과 겹치는 이벤트 vs 나머지 — 일일 레이어 '추격 주의' 제외 근거 점검용
                           "chase_split_oos": {"chase": mstats(e.filter((pl.col("date") >= sp) & pl.col("chase"))),
                                               "rest": mstats(e.filter((pl.col("date") >= sp) & ~pl.col("chase")))}}
    return out


def holm(cells: dict) -> dict:
    """OOS t → 단측 p(정규 근사) Holm 단계 내림 통과 여부(병기)."""
    ps = sorted(((0.5 * math.erfc((c["oos"].get("t") or -9) / math.sqrt(2)), key) for key, c in cells.items()))
    out, alive = {}, True
    for i, (p, key) in enumerate(ps):
        thr = 0.05 / (len(ps) - i)
        alive = alive and p < thr
        out[key] = {"p": round(p, 5), "thr": round(thr, 5), "pass": alive}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    a = ap.parse_args(argv)
    years = range(2016, 2026) if a.quick else range(2010, 2026)
    res = {mk: run(mk, years) for mk in ("KR", "US")}
    flat = {f"{k}_{mk}": res[mk]["cells"][k] for mk in res for k in STRATS}
    out = {"study": STUDY, "prereg": "docs/valuation_notes/2026-10-24_trend_events_prereg.md", "m": M, "alpha": round(0.05 / M, 4),
           "t_bonf": T_BONF, "split": SPLIT, "cost": COST, "hold": H,
           "run_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M KST"), "markets": res,
           "grades": {key: c["grade"] for key, c in flat.items()}, "holm": holm(flat),
           "not_for_orders": True,
           "note": "B 이상이어도 sim_signals 정식 편입은 다음 결재. 생존편향(현재 구성, US 303종목)·OOS 2023~2025 사전 노출 겹침(부분 사후)."}
    if not a.quick:
        OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"grades": out["grades"], **{key: {"is": (c["is"].get("mean_m"), c["is"].get("t"), c["is"].get("n")),
                                                         "oos": (c["oos"].get("mean_m"), c["oos"].get("t"), c["oos"].get("n"), c["oos"].get("months"))}
                                                   for key, c in flat.items()}}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
