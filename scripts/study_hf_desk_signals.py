#!/usr/bin/env python3
"""HF 4차 — 현업 데스크 시그널 6종. 사전등록 reports/studies/2026-10-21_hf_desk_signals.md §0.

  python3 scripts/study_hf_desk_signals.py    # reports/studies/2026-10-21_hf_desk_signals.json

지수: S1 외국인 수급 추종 · S2 개인 쏠림 역추세 · S3 공포 매수(VKOSPI +50%).
종목: S4 KR 거래량 터진 돌파 · S5 KR 장대 반전 · S6 US 거래량 터진 돌파.
영향 범위: 연구 산출물만(알파북·재량 북 미연결).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import study_hf_ls_vol as h  # noqa: E402

STUDY = "2026-10-21_hf_desk_signals"
T_BONF, T_C = 2.39, 1.645
FUT = 0.0002
COST = {"KR": 0.0025, "US": 0.0010}
LIQ = {"KR": (1e9, 1000), "US": (2e7, 5)}


def grade(c):
    t, tr = c["test"], c["train"]
    if (t.get("n") or 0) < 30 or t.get("t") is None:
        return "검증전"
    if t["mean"] > 0 and t["t"] >= T_BONF and (tr.get("mean") or 0) > 0:
        return "B"
    if t["mean"] > 0 and t["t"] >= T_C:
        return "C(방향만)"
    return "F"


def one(x):
    x = np.asarray(x, float)
    if len(x) < 2:
        return {"n": int(len(x))}
    m, sd = x.mean(), x.std(ddof=1)
    return {"n": int(len(x)), "mean": round(float(m), 5), "t": round(float(m / (sd / len(x) ** 0.5)), 2) if sd > 0 else None,
            "hit": round(float((x > 0).mean()), 3), "worst": round(float(x.min()), 4)}


def index_cell(dt, k, sig, h, side):
    """비중첩 사건 → 초과 수익(같은 구간 무조건 h일 평균 차감)."""
    n = len(k)
    fwd = np.full(n, np.nan)
    fwd[:n - h] = k[h:] / k[:n - h] - 1
    tr = dt < np.datetime64("2020-01-01")
    base = {True: np.nanmean(fwd[tr]), False: np.nanmean(fwd[~tr])}
    ev, i = [], 0
    while i < n - h:
        if sig[i]:
            r = fwd[i]
            b = base[bool(tr[i])]
            ev.append((dt[i], side * (r - b) - FUT))
            i += h
        else:
            i += 1
    out = {"train": one([v for d, v in ev if d < np.datetime64("2020-01-01")]),
           "test": one([v for d, v in ev if d >= np.datetime64("2020-01-01")])}
    return out


def roll_rank_top(x, w=250, q=0.9):
    out = np.zeros(len(x), bool)
    for i in range(w, len(x)):
        win = x[i - w:i]
        win = win[~np.isnan(win)]
        if len(win) > 100 and not np.isnan(x[i]):
            out[i] = x[i] >= np.quantile(win, q)
    return out


def index_signals():
    d = pl.read_csv(ROOT / "data" / "deriv" / "daily.csv", infer_schema_length=5000)
    d = d.select("date", "k200_close", "spot_frgn", "spot_indiv", "rep_iv").drop_nulls(["date", "k200_close"])
    dt = np.array(d["date"].to_list(), dtype="datetime64[D]")
    k = d["k200_close"].to_numpy().astype(float)
    f = d["spot_frgn"].fill_null(0).to_numpy().astype(float)
    ind = d["spot_indiv"].fill_null(0).to_numpy().astype(float)
    iv = d["rep_iv"].to_numpy().astype(float)
    f5 = np.convolve(f, np.ones(5), "full")[:len(f)]
    i5 = np.convolve(ind, np.ones(5), "full")[:len(ind)]
    s1 = roll_rank_top(f5)
    s2 = roll_rank_top(i5)
    iv20 = np.r_[np.full(20, np.nan), iv[:-20]]
    s3 = np.nan_to_num(iv / iv20 - 1) >= 0.5
    return {"S1": ("외국인 5일 순매수 상위10% → K200 롱 5일", index_cell(dt, k, s1, 5, 1)),
            "S2": ("개인 5일 순매수 상위10% → K200 숏 5일", index_cell(dt, k, s2, 5, -1)),
            "S3": ("VKOSPI 20일 +50% → K200 롱 20일", index_cell(dt, k, s3, 20, 1))}


def wide4(df):
    dates = np.array(sorted(df["date"].unique().to_list()), dtype="datetime64[D]")
    syms = sorted(df["sym"].unique().to_list())
    di = {str(d)[:10]: i for i, d in enumerate(dates)}
    si = {s: i for i, s in enumerate(syms)}
    r = np.array([di[str(x)[:10]] for x in df["date"].to_list()])
    c = np.array([si[s] for s in df["sym"].to_list()])
    W = {}
    for key in ("open", "close", "volume"):
        a = np.full((len(dates), len(syms)), np.nan)
        a[r, c] = df[key].to_numpy().astype(float)
        W[key] = a
    return dates, W


def stock_cell(market, kind, hold):
    df = h.st.load_hist(market, range(2010, 2026))
    dates, W = wide4(df)
    O, C, V = W["open"], W["close"], W["volume"]
    mv, mp = LIQ[market]
    val = h.roll_mean(C * V, 20)
    liq = (val >= mv) & (C >= mp) & ~np.isnan(C)
    n = len(dates)
    pc = np.r_[np.full((1, C.shape[1]), np.nan), C[:-1]]
    if kind == "breakout":
        v20 = np.full_like(V, np.nan)
        v20[20:] = h.roll_mean(V, 20)[19:-1]          # 직전 20일 평균(당일 제외)
        hi20 = np.full_like(C, np.nan)
        from numpy.lib.stride_tricks import sliding_window_view
        hi20[19:] = sliding_window_view(np.nan_to_num(C, nan=-np.inf), 20, axis=0).max(axis=-1)
        sig = liq & (V >= 3 * v20) & (C >= hi20)
    else:
        sig = liq & (O <= pc * 0.95) & (C >= pc)
    rows = []
    for t in range(21, n - hold - 1):
        ii = np.where(sig[t])[0]
        if not len(ii):
            continue
        ent = O[t + 1]
        ex = C[t + hold]
        u = liq[t] & ~np.isnan(ent) & ~np.isnan(ex) & (ent > 0)
        if u.sum() < 30:
            continue
        uni = np.nanmean(ex[u] / ent[u] - 1)
        ok = ii[~np.isnan(ent[ii]) & ~np.isnan(ex[ii]) & (ent[ii] > 0)]
        if not len(ok):
            continue
        r = np.nanmean(ex[ok] / ent[ok] - 1) - uni - COST[market]
        rows.append((dates[t], float(r), len(ok)))
    mon = {}
    for d, r, _ in rows:
        mon.setdefault(str(d)[:7], []).append(r)
    ms = sorted(mon)
    split = "2020-01"
    tr = [np.mean(mon[m]) for m in ms if m < split]
    te = [np.mean(mon[m]) for m in ms if m >= split]
    return {"train": one(tr), "test": one(te), "events": int(sum(x[2] for x in rows)), "days": len(rows)}


def main():
    cells = {}
    for key, (desc, c) in index_signals().items():
        cells[key] = {"key": key, "desc": desc, "unit": "건당 초과(소수)", **c}
    for key, desc, mk, kind, hold in (("S4", "KR 거래량 3배 + 20일 최고 종가 돌파 → 10일", "KR", "breakout", 10),
                                      ("S5", "KR 시가 −5% 갭 후 전일 종가 회복 → 5일", "KR", "reversal", 5),
                                      ("S6", "US 거래량 3배 + 20일 최고 종가 돌파 → 10일", "US", "breakout", 10)):
        cells[key] = {"key": key, "desc": desc, "unit": "월 평균 초과(소수)", **stock_cell(mk, kind, hold)}
    for k, c in cells.items():
        c["grade"] = grade(c)
        print(k, c["grade"], c["desc"], "\n   train", c["train"], "\n   test ", c["test"], c.get("events", ""))
    out = {"v": 1, "asof": datetime.now(h.KST).strftime("%Y-%m-%d"), "generated_at": datetime.now(h.KST).strftime("%Y-%m-%d %H:%M KST"),
           "study": STUDY, "prereg": f"reports/studies/{STUDY}.md §0", "m": 6, "t_bonf": T_BONF, "split": "2020-01-01",
           "cells": cells, "pass": [k for k, c in cells.items() if c["grade"] == "B"]}
    (ROOT / "reports" / "studies" / f"{STUDY}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
