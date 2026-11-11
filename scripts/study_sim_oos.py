#!/usr/bin/env python3
"""추세 시뮬 표본외 검증 (보드 sim-oos) — 사전등록 reports/studies/2026-11-12_sim_oos.md §0 (퀀트).

  python3 scripts/study_sim_oos.py           # reports/studies/2026-11-12_sim_oos.json
  python3 scripts/study_sim_oos.py --quick   # KR 일부 종목 점검(파일 안 씀)

규칙은 screener/detail.py _simulate·_fresh·_fresh_exp 그대로(이평 롱·PSAR 롱, 종가 체결, 왕복 0.25%).
H1·H2 = 월 포트폴리오(전략 − 같은 종목 보유), H3·H4 = 새로 켜짐 이벤트(t+1 시가→t+21 종가 − 비용 − 같은 업종 EW),
H5 = 지난 250일 시뮬 성적 상위 1/3 − 하위 1/3 의 다음 달 전략 초과. 표본 단위 = 달, NW(3) t, m = 10, α/m = 0.005.
영향 범위: 연구 파일만(워크플로·화면 없음).
"""
from __future__ import annotations

import argparse
import bisect
import json
import math
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from screener import detail, prices  # noqa: E402
from screener.indicators import psar_np  # noqa: E402

KST = timezone(timedelta(hours=9))
STUDY = "2026-11-12_sim_oos"
OUT = ROOT / "reports" / "studies" / f"{STUDY}.json"
M = 10
ALPHA = 0.05 / M
COST = detail.COST
H, H5D = 21, 5
GAP = 20
WIN = 250
LIQ = {"KR": (1e9, 1000.0), "US": (2e7, 5.0)}
IS_END, OOS_START = "2019-12", "2020-01"
BAD = 0.40
N_TOPIC = 217
STRATS = ("ma", "psar")


# ---------------- 데이터 ----------------
def load(market: str, years) -> pl.DataFrame:
    fs = [ROOT / "data" / "hist" / f"{market.lower()}_{y}.parquet" for y in years]
    df = pl.concat([pl.read_parquet(f, columns=["yf", "date", "open", "high", "low", "close", "volume"]) for f in fs if f.exists()],
                   how="vertical_relaxed")
    df = df.filter(pl.col("close").is_not_null() & (pl.col("close") > 0)).unique(["yf", "date"]).sort("yf", "date")
    if market == "KR":
        df = prices.adjust(df)
    return df


def sectors(market: str) -> dict[str, str]:
    if market == "KR":
        s = pd.read_csv(ROOT / "universe" / "kr_sector.csv", dtype=str)
        return dict(zip(s["code"].str.zfill(6), s["sector"]))
    s = pd.read_csv(ROOT / "universe" / "us_sector.csv", dtype=str)
    return dict(zip(s["yf"], s["sector"]))


def sym_key(market: str, yf: str) -> str:
    return yf[:6] if market == "KR" else yf


# ---------------- 규칙 ----------------
def signals(c, h, l):
    s = pd.Series(c)
    s20, s50 = s.rolling(20).mean().to_numpy(), s.rolling(50).mean().to_numpy()
    ps = psar_np(h, l, c)
    with np.errstate(invalid="ignore"):
        ma = ((c > s50) & (s20 > s50)).astype(np.int8)            # NaN 비교 = False → 0
        sar = np.where(np.isnan(ps), 0, (c > ps)).astype(np.int8)  # NaN = 0 중립(§0)
        ma_ls = np.where((c > s50) & (s20 > s50), 1, np.where((c < s50) & (s20 < s50), -1, 0)).astype(np.int8)
        sar_ls = np.where(np.isnan(ps), 0, np.where(c > ps, 1, -1)).astype(np.int8)
    return {"ma": ma, "psar": sar, "ma_ls": ma_ls, "psar_ls": sar_ls}, s20, s50, ps


def strat_ret(r: np.ndarray, pos: np.ndarray) -> np.ndarray:
    """_sim_one 과 같은 일간 수익: i일 = (1 − cost/2·|pos[i−1]−pos[i−2]|)·(1 + pos[i−1]·r[i]) − 1."""
    p1 = np.concatenate([[0], pos[:-1]]).astype(float)
    p2 = np.concatenate([[0, 0], pos[:-2]]).astype(float)
    out = (1 - COST / 2 * np.abs(p1 - p2)) * (1 + p1 * r) - 1
    out[0] = 0.0
    return out


def trades(pos: np.ndarray):
    """전체 이력 롱 거래 (진입 idx, 청산 idx) — 진입 = pos 0→1 인 날 종가, 청산 = 1→0 인 날 종가."""
    d = np.diff(pos.astype(np.int8), prepend=0)
    ent = np.flatnonzero(d == 1)
    ex = np.flatnonzero(d == -1)
    out = []
    j = 0
    for e in ent:
        while j < len(ex) and ex[j] <= e:
            j += 1
        if j < len(ex):
            out.append((int(e), int(ex[j])))
    return out


def window_rets(c, tr_list, exits, ws, t):
    """창 [ws, t] 에서 _sim_one 이 청산했을 거래: 청산 x ∈ (ws, t−1], 진입가 = c[max(e, ws)]. (총수익, 순수익) 목록."""
    lo = bisect.bisect_right(exits, ws)
    hi = bisect.bisect_right(exits, t - 1)
    gross, net = [], []
    for e, x in tr_list[lo:hi]:
        g = c[x] / c[max(e, ws)] - 1
        gross.append(g)
        net.append(round(g - COST, 4))
    return gross, net


# ---------------- 종목별 계산 ----------------
def per_stock(market: str, df: pl.DataFrame, secmap: dict, quick: bool = False):
    mv, mp = LIQ[market]
    mrows, frows, evrows, rep = [], [], [], []
    parts = df.partition_by("yf", maintain_order=True)
    if quick:
        parts = parts[::15]
    rng = random.Random(20261112)
    for part in parts:
        n = len(part)
        if n < WIN + 60:
            continue
        sym = part["yf"][0]
        sec = secmap.get(sym_key(market, sym))
        c = part["close"].to_numpy().astype(float)
        o = part["open"].fill_null(part["close"]).to_numpy().astype(float)
        o = np.where(o > 0, o, c)
        h = part["high"].fill_null(part["close"]).to_numpy().astype(float)
        l = part["low"].fill_null(part["close"]).to_numpy().astype(float)
        v = part["volume"].fill_null(0).to_numpy().astype(float)
        dates = part["date"].to_numpy()
        dlist = part["date"].to_list()
        sig, s20, s50, ps = signals(c, h, l)
        r = np.concatenate([[0.0], c[1:] / c[:-1] - 1])
        bad = np.abs(r) > BAD
        val20 = pd.Series(c * v).rolling(20).mean().to_numpy()
        liq = (val20 >= mv) & (c >= mp)
        sr = {k: strat_ret(r, sig[k]) for k in sig}
        months = pd.DatetimeIndex(dates).to_period("M")
        mcodes = months.asi8
        # --- 월 포트폴리오 (H1·H2·H5·서술)
        lr_bh = np.log1p(r)
        cum = {k: np.concatenate([[0.0], np.cumsum(np.log1p(sr[k]))]) for k in ("ma", "psar")}
        cbh = np.concatenate([[0.0], np.cumsum(lr_bh)])
        bcum = np.concatenate([[0], np.cumsum(bad)])
        bounds = np.flatnonzero(np.diff(mcodes, prepend=mcodes[0] - 1) != 0)   # 각 달 첫 idx
        for bi, s0 in enumerate(bounds):
            if s0 == 0:
                continue
            e0 = bounds[bi + 1] if bi + 1 < len(bounds) else n
            j = s0 - 1                       # 전월 마지막 거래일
            if not liq[j] or bcum[e0] - bcum[s0] > 0 or e0 - s0 < 10:
                continue
            row = {"yf": sym, "m": str(months[s0]), "sec": sec,
                   "bh": math.expm1(cbh[e0] - cbh[s0])}
            for k in sig:
                row[k] = float(np.prod(1 + sr[k][s0:e0]) - 1)
            if j >= WIN and bcum[j + 1] - bcum[j + 1 - WIN] == 0:
                b250 = math.expm1(cbh[j + 1] - cbh[j + 1 - WIN])
                row["score"] = 0.5 * sum(math.expm1(cum[k][j + 1] - cum[k][j + 1 - WIN]) - b250 for k in ("ma", "psar"))
            mrows.append(row)
        # --- 전진 수익 패널 (업종 기준선) + 이벤트
        idx = np.arange(n)
        ok = (idx >= 1) & (idx < n - H - 1)
        f21 = np.full(n, np.nan)
        f5 = np.full(n, np.nan)
        f21[: n - H - 1] = c[H + 1:] / o[1: n - H] - 1
        f5[: n - H5D - 1] = c[H5D + 1:] / o[1: n - H5D] - 1
        ii = np.arange(n)
        badf = bcum[np.minimum(ii + H + 2, n)] - bcum[np.minimum(ii + 1, n)] > 0
        valid = ok & liq & ~badf & ~np.isnan(f21)
        if sec is not None:
            vi = np.flatnonzero(valid)
            frows.append(pl.DataFrame({"date": dates[vi], "sec": [sec] * len(vi), "f21": f21[vi], "f5": f5[vi]}))
        for k in STRATS:
            pos = sig[k]
            tl = trades(pos)
            exits = [x for _, x in tl]
            ent = np.flatnonzero(np.diff(pos.astype(np.int8), prepend=0) == 1)
            last = {"all": -10 ** 9, "exp": -10 ** 9, "wil": -10 ** 9}
            for t in ent:
                if t < WIN + 49 or not valid[t] or sec is None:
                    continue
                ws = t - WIN + 1
                gross, net = window_rets(c, tl, exits, ws, t)
                nt = len(net)
                flags = {"all": True,
                         "exp": nt >= detail.EXP_MIN_TRADES and detail.exp_lb(net)[2] > detail.EXP_LB_MIN,
                         "wil": nt >= detail.FRESH_MIN_TRADES and (detail.wilson_lo(sum(g > 0 for g in gross), nt) or 0) > detail.FRESH_WILSON_MIN}
                for typ, f in flags.items():
                    if f and t - last[typ] >= GAP:
                        last[typ] = t
                        evrows.append({"typ": typ, "strat": k, "yf": sym, "date": dlist[t], "sec": sec,
                                       "f21": float(f21[t]), "f5": float(f5[t]), "nt": nt})
                if len(rep) < 20 and nt >= 3 and rng.random() < 0.002:
                    rep.append((part[ws: t + 1], k, nt, net, sum(g > 0 for g in gross), s20[ws:t + 1], s50[ws:t + 1], ps[ws:t + 1]))
    M_ = pl.DataFrame(mrows, infer_schema_length=None)
    F_ = pl.concat(frows) if frows else pl.DataFrame()
    E_ = pl.DataFrame(evrows, infer_schema_length=None)
    return M_, F_, E_, rep


def replicate(rep) -> dict:
    """창 시뮬 복제 점검: 같은 창을 detail._simulate 에 넣어 거래 수·rets·wins 일치."""
    ok, bad = 0, []
    for part, k, nt, net, wins, s20, s50, ps in rep:
        g = pl.DataFrame({"date": part["date"], "close": part["close"].cast(pl.Float64),
                          "sma20": s20, "sma50": s50, "psar": [None if np.isnan(x) else float(x) for x in ps]})
        sim = detail._simulate(g, days=WIN)
        rr = sim[k]["long"]
        if rr["trades"] == nt and rr["rets"] == net and rr["wins"] == wins:
            ok += 1
        else:
            bad.append({"yf": part["yf"][0], "date": str(part["date"][-1]), "strat": k, "mine": [nt, wins], "detail": [rr["trades"], rr["wins"]]})
    return {"n": len(rep), "match": ok, "mismatch": bad[:5]}


# ---------------- 통계 ----------------
def nw_t(x: np.ndarray, lag: int = 3) -> float | None:
    k = len(x)
    if k < 3:
        return None
    u = x - x.mean()
    g0 = (u @ u) / k
    s = g0
    for L in range(1, min(lag, k - 1) + 1):
        s += 2 * (1 - L / (lag + 1)) * (u[L:] @ u[:-L]) / k
    return float(x.mean() / math.sqrt(s / k)) if s > 0 else None


def series_stats(s: pl.DataFrame, col: str = "x") -> dict:
    """s = [m, x] 월 시계열."""
    s = s.filter(pl.col(col).is_not_null() & pl.col(col).is_not_nan()).sort("m")
    x = s[col].to_numpy()
    k = len(x)
    if k < 3:
        return {"months": k}
    mu, sd = float(x.mean()), float(x.std(ddof=1))
    t_nw = nw_t(x)
    t_s = mu / (sd / math.sqrt(k)) if sd > 0 else None
    p = float(stats.t.sf(t_nw, k - 1)) if t_nw is not None else None
    p_rev = float(stats.t.cdf(t_nw, k - 1)) if t_nw is not None else None
    return {"months": k, "mean_m": round(mu, 5), "median_m": round(float(np.median(x)), 5), "hit": round(float((x > 0).mean()), 3),
            "t_nw3": None if t_nw is None else round(t_nw, 2), "t_simple": None if t_s is None else round(t_s, 2),
            "p": None if p is None else round(p, 6), "p_rev": None if p_rev is None else round(p_rev, 6),
            "sharpe_ann": round(mu / sd * math.sqrt(12), 2) if sd > 0 else None}


def split(s: pl.DataFrame) -> dict:
    return {"is": series_stats(s.filter(pl.col("m") <= IS_END)),
            "oos": series_stats(s.filter(pl.col("m") >= OOS_START)),
            "y2022": series_stats(s.filter(pl.col("m").str.starts_with("2022"))),
            "oos_ex2020": series_stats(s.filter((pl.col("m") >= OOS_START) & ~pl.col("m").str.starts_with("2020"))),
            "covid_2020_02_03": round(float(s.filter(pl.col("m").is_in(["2020-02", "2020-03"]))["x"].sum()), 4) if len(s) else None,
            "by_year": {y: round(float(g["x"].mean()), 5) for (y,), g in s.with_columns(pl.col("m").str.slice(0, 4).alias("y"))
                        .sort("y").group_by("y", maintain_order=True)}}


def grade(c: dict, event_n: int | None = None, cap_b: bool = False) -> str:
    is_, oos, y22 = c["is"], c["oos"], c["y2022"]
    if oos.get("months", 0) < 30 or (event_n is not None and event_n < 100):
        return "검증전"
    mo, p, pr = oos.get("mean_m"), oos.get("p"), oos.get("p_rev")
    b = mo > 0 and p is not None and p < ALPHA and (is_.get("mean_m") or 0) > 0
    if b and (is_.get("p") or 1) < ALPHA and (y22.get("mean_m") or -1) > 0 and not cap_b:
        return "A"
    if b:
        return "B" + ("(상한)" if cap_b else "")
    if mo > 0 and p is not None and p < 0.05:
        return "C"
    if mo < 0 and pr is not None and pr < 0.05:
        return "C(역방향)"
    return "F"


def dsr(sr_ann, n_obs, n_trials=N_TOPIC, per_year=12):
    if sr_ann is None or n_obs < 10:
        return None
    from statistics import NormalDist
    nd = NormalDist()
    sr = sr_ann / math.sqrt(per_year)
    g = 0.5772156649
    e_max = math.sqrt(1 / n_obs) * ((1 - g) * nd.inv_cdf(1 - 1 / n_trials) + g * nd.inv_cdf(1 - 1 / (n_trials * math.e)))
    return round(nd.cdf((sr - e_max) * math.sqrt(n_obs - 1)), 3)


def wealth(s: pl.DataFrame, col: str) -> dict:
    x = s.sort("m")[col].to_numpy()
    if len(x) < 12:
        return {}
    w = np.cumprod(1 + x)
    return {"cagr": round(float(w[-1] ** (12 / len(x)) - 1), 4), "mdd": round(float((w / np.maximum.accumulate(w) - 1).min()), 4)}


def run(market: str, years, quick: bool = False) -> dict:
    df = load(market, years)
    secmap = sectors(market)
    Mo, F, E, rep = per_stock(market, df, secmap, quick)
    out = {"symbols": df["yf"].n_unique(), "first": str(df["date"].min()), "last": str(df["date"].max()),
           "stock_months": len(Mo), "replication": replicate(rep), "cells": {}, "describe": {}}
    Mo = Mo.filter(pl.col("m") >= "2011-01")
    cap = market == "US"
    # H1·H2
    for hid, k in (("H1", "ma"), ("H2", "psar")):
        ex = Mo.with_columns((pl.col(k) - pl.col("bh")).alias("x")).group_by("m").agg(pl.col("x").mean(), pl.len().alias("n"))
        c = split(ex)
        c["grade"] = grade(c, cap_b=cap)
        c["n_stock_months"] = int(ex["n"].sum())
        c["median_stocks_per_month"] = int(ex["n"].median())
        # 서술: 업종 대비, 롱숏, 연복리·MDD, 회전
        secbh = Mo.filter(pl.col("sec").is_not_null()).group_by("m", "sec").agg(pl.col("bh").mean().alias("sbh"))
        vs_sec = (Mo.filter(pl.col("sec").is_not_null()).join(secbh, on=["m", "sec"])
                  .with_columns((pl.col(k) - pl.col("sbh")).alias("x")).group_by("m").agg(pl.col("x").mean()))
        ls = Mo.with_columns((pl.col(k + "_ls") - pl.col("bh")).alias("x")).group_by("m").agg(pl.col("x").mean())
        port = Mo.group_by("m").agg(pl.col(k).mean().alias("s"), pl.col("bh").mean().alias("b")).filter(pl.col("m") >= OOS_START)
        # 종목수 보정: 종목별 OOS 월 초과 t > 1.645 비율
        per = (Mo.filter(pl.col("m") >= OOS_START).with_columns((pl.col(k) - pl.col("bh")).alias("x"))
               .group_by("yf").agg(pl.col("x").mean().alias("mu"), pl.col("x").std().alias("sd"), pl.len().alias("n"))
               .filter(pl.col("n") >= 24).with_columns((pl.col("mu") / (pl.col("sd") / pl.col("n").sqrt())).alias("t")))
        c["describe"] = {"vs_sector_oos": series_stats(vs_sec.filter(pl.col("m") >= OOS_START)),
                         "vs_sector_is": series_stats(vs_sec.filter(pl.col("m") <= IS_END)),
                         "long_short_minus_bh_oos": series_stats(ls.filter(pl.col("m") >= OOS_START)),
                         "oos_strategy_ew": wealth(port, "s"), "oos_bh_ew": wealth(port, "b"),
                         "per_stock_oos_t_gt_1645": {"stocks": len(per), "share": round(float((per["t"] > 1.645).mean()), 3) if len(per) else None,
                                                     "null_expect": 0.05,
                                                     "share_t_lt_m1645": round(float((per["t"] < -1.645).mean()), 3) if len(per) else None},
                         "dsr_oos": dsr(c["oos"].get("sharpe_ann"), c["oos"].get("months", 0))}
        out["cells"][hid] = c
    # H3·H4 (+ 서술: 조건 없는 새로 켜짐)
    Fs = F.group_by("date", "sec").agg(pl.col("f21").mean().alias("s21"), pl.col("f5").mean().alias("s5"))
    Ej = (E.join(Fs, on=["date", "sec"], how="left")
           .with_columns((pl.col("f21") - COST - pl.col("s21")).alias("x"), (pl.col("f5") - COST - pl.col("s5")).alias("x5"),
                         pl.col("date").cast(pl.Date).dt.strftime("%Y-%m").alias("m"))
           .filter(pl.col("m") >= "2011-01"))
    for hid, typ in (("H3", "exp"), ("H4", "wil"), ("all_fresh", "all")):
        e = Ej.filter(pl.col("typ") == typ)
        ser = e.group_by("m").agg(pl.col("x").mean())
        c = split(ser)
        n_oos = int(e.filter(pl.col("m") >= OOS_START).height)
        c["n_events"] = {"is": int(e.filter(pl.col("m") <= IS_END).height), "oos": n_oos}
        c["event_median_oos"] = round(float(e.filter(pl.col("m") >= OOS_START)["x"].median()), 5) if n_oos else None
        c["by_strat_oos"] = {k: series_stats(e.filter((pl.col("strat") == k) & (pl.col("m") >= OOS_START)).group_by("m").agg(pl.col("x").mean()))
                             for k in STRATS}
        c["h5d_oos"] = series_stats(e.filter(pl.col("m") >= OOS_START).group_by("m").agg(pl.col("x5").mean().alias("x")))
        if hid == "all_fresh":
            out["describe"]["all_fresh_vs_sector"] = c
        else:
            c["grade"] = grade(c, event_n=n_oos, cap_b=True)
            out["cells"][hid] = c
    # H5
    Ms = Mo.filter(pl.col("score").is_not_null()).with_columns(
        (0.5 * ((pl.col("ma") - pl.col("bh")) + (pl.col("psar") - pl.col("bh")))).alias("fx"))
    Ms = Ms.with_columns(((pl.col("score").rank("ordinal").over("m") - 1) * 3 // pl.len().over("m")).alias("q"))
    sp = (Ms.group_by("m", "q").agg(pl.col("fx").mean()).pivot(on="q", index="m", values="fx")
            .with_columns((pl.col("2") - pl.col("0")).alias("x")).select("m", "x"))
    c = split(sp)
    c["grade"] = grade(c, cap_b=cap)
    c["median_stocks_per_month"] = int(Ms.group_by("m").len()["len"].median())
    out["cells"]["H5"] = c
    return out


def holm(flat: dict) -> dict:
    ps = sorted(((c["oos"].get("p") if c["oos"].get("p") is not None else 1.0), k) for k, c in flat.items())
    out, alive = {}, True
    for i, (p, k) in enumerate(ps):
        thr = 0.05 / (len(ps) - i)
        alive = alive and p < thr
        out[k] = {"p": round(p, 6), "thr": round(thr, 5), "pass": alive}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    a = ap.parse_args(argv)
    years = range(2010, 2026)
    mkts = ("KR",) if a.quick else ("KR", "US")
    res = {mk: run(mk, years, a.quick) for mk in mkts}
    flat = {f"{h}_{mk}": res[mk]["cells"][h] for mk in res for h in ("H1", "H2", "H3", "H4", "H5")}
    out = {"study": STUDY, "prereg": {"file": f"reports/studies/{STUDY}.md", "commit": "8efdba174", "m": M, "alpha_bonf": ALPHA,
                                      "is_end": IS_END, "oos": f"{OOS_START}~2025-12", "cost": COST, "hold": H, "gap": GAP, "window": WIN,
                                      "test": "월 시계열 평균>0 단측, Newey-West(3) t, 스튜던트 t p",
                                      "topic_N": N_TOPIC, "alpha_N": round(0.05 / N_TOPIC, 5),
                                      "survivorship": "KR 상폐 포함(업종은 현재 분류 → H3·H4 B 상한) · US 현재 구성(전부 B 상한)",
                                      "dsr": "H1·H2 OOS 월 초과 샤프, 시도 N 217 (Bailey–LdP 2014 근사)"},
           "run_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M KST"), "markets": res,
           "grades": {k: c["grade"] for k, c in flat.items()}, "holm": holm(flat), "not_for_orders": True}
    if not a.quick:
        OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    brief = {k: {"g": c["grade"], "is": (c["is"].get("mean_m"), c["is"].get("t_nw3")), "oos": (c["oos"].get("mean_m"), c["oos"].get("t_nw3"), c["oos"].get("p"), c["oos"].get("months"))}
             for k, c in flat.items()}
    print(json.dumps({"brief": brief, "rep": {mk: res[mk]["replication"] for mk in res}}, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
