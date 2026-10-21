#!/usr/bin/env python3
"""HF 2차 알파 소스 — 롱숏·베타헤지·변동성 매도 근사. 사전등록 reports/studies/2026-10-21_hf_ls_vol.md §0.

  python3 scripts/study_hf_ls_vol.py           # reports/studies/2026-10-21_hf_ls_vol.json
  python3 scripts/study_hf_ls_vol.py --quick   # 2016~ 만(결과 파일 안 씀)

L1 B1 베타헤지 롱숏 · L2 단기 반전 · L3 12-1 모멘텀 · V1 분산 매도 · V2 조건부 분산 매도, m = 5, t ≥ 2.33.
영향 범위: 연구 산출물만. 알파북(screener/alphabook.py)은 이 json 을 아직 읽지 않는다(통과 시 별도 작업).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import study_tradeplan as st  # noqa: E402

KST = timezone(timedelta(hours=9))
STUDY = "2026-10-21_hf_ls_vol"
SPLIT = np.datetime64("2020-01-01")
T_BONF, T_C = 2.33, 1.645
SIDE = 0.00125          # 왕복 0.25% 의 한쪽
FUT_RT = 0.0002
BORROW = 0.03
VOL_COST = 1.0          # 변동성 %p
BANS = [("2020-03-16", "2021-05-02"), ("2023-11-06", "2025-03-30")]


def wide(df: pl.DataFrame):
    dates = np.array(sorted(df["date"].unique().to_list()), dtype="datetime64[D]")
    syms = sorted(df["sym"].unique().to_list())
    di = {d: i for i, d in enumerate(dates.astype(str))}
    si = {s: i for i, s in enumerate(syms)}
    r = np.array([di[str(d)[:10]] for d in df["date"].to_list()])
    c = np.array([si[s] for s in df["sym"].to_list()])
    out = {}
    for k in ("close", "high", "volume"):
        a = np.full((len(dates), len(syms)), np.nan)
        a[r, c] = df[k].to_numpy().astype(float)
        out[k] = a
    return dates, out


def ffill(a):
    m = np.isnan(a)
    idx = np.where(~m, np.arange(a.shape[0])[:, None], 0)
    np.maximum.accumulate(idx, axis=0, out=idx)
    f = a[idx, np.arange(a.shape[1])]
    f[np.isnan(a) & (idx == 0)] = np.nan
    return f


def roll_mean(a, w):
    z = np.nan_to_num(a)
    cs = np.cumsum(z, axis=0)
    out = np.full_like(a, np.nan)
    out[w:] = (cs[w:] - cs[:-w]) / w
    return out


def roll_max(a, w):
    from numpy.lib.stride_tricks import sliding_window_view
    out = np.full_like(a, np.nan)
    v = sliding_window_view(np.nan_to_num(a, nan=-np.inf), w, axis=0)
    out[w - 1:] = v.max(axis=-1)
    return out


def banned(d) -> bool:
    s = str(d)[:10]
    return any(a <= s <= b for a, b in BANS)


def stats(rows, h):
    def one(x):
        x = np.array([v for _, v in x], float)
        if len(x) < 2:
            return {"n": int(len(x))}
        m, sd = x.mean(), x.std(ddof=1)
        cum = np.cumsum(x)
        return {"n": int(len(x)), "mean": round(float(m), 5), "t": round(float(m / (sd / len(x) ** 0.5)), 2) if sd > 0 else None,
                "sharpe": round(float(m / sd * (252 / h) ** 0.5), 2) if sd > 0 else None,
                "worst": round(float(x.min()), 4), "mdd": round(float((cum - np.maximum.accumulate(cum)).min()), 4),
                "hit": round(float((x > 0).mean()), 3)}
    tr = [r for r in rows if r[0] < SPLIT]
    te = [r for r in rows if r[0] >= SPLIT]
    covid = round(float(sum(v for d, v in rows if np.datetime64("2020-02-15") <= d <= np.datetime64("2020-03-31"))), 4)
    return {"train": one(tr), "test": one(te), "covid_2020_03": covid}


def grade(c):
    t, tr = c["test"], c["train"]
    if t.get("n", 0) < 30 or t.get("t") is None:
        return "검증전"
    if t["mean"] > 0 and t["t"] >= T_BONF and (tr.get("mean") or 0) > 0:
        return "B"
    if t["mean"] > 0 and t["t"] >= T_C:
        return "C(방향만)"
    return "F"


def turnover(w_new: dict, w_old: dict) -> float:
    ks = set(w_new) | set(w_old)
    return sum(abs(w_new.get(k, 0) - w_old.get(k, 0)) for k in ks)


def ls_book(dates, C, R, liq, idx_c, step, h, pick, hedge_long=False):
    """pick(t) → (long_idx, short_idx | None). 반환 [(date, 기간 수익)]."""
    rows, wl_old, ws_old = [], {}, {}
    n = len(dates)
    for t in range(260, n - h, step):
        L, S = pick(t)
        if L is None or len(L) < 5:
            rows.append((dates[t], 0.0))
            wl_old, ws_old = {}, {}
            continue
        rl = np.nanmean(C[t + h, L] / C[t, L] - 1)
        ri = idx_c[t + h] / idx_c[t] - 1
        wl = {int(k): 1 / len(L) for k in L}
        cost = SIDE * turnover(wl, wl_old)
        if hedge_long:
            win = R[t - 59:t + 1][:, L]
            bk = np.nanmean(win, axis=1)
            ix = idx_c[t - 59:t + 1] / idx_c[t - 60:t] - 1
            ok = ~np.isnan(bk) & ~np.isnan(ix)
            beta = float(np.cov(bk[ok], ix[ok])[0, 1] / np.var(ix[ok], ddof=1)) if ok.sum() > 20 else 1.0
            r = rl - beta * ri - FUT_RT
            ws = {}
        elif banned(dates[t]) or S is None or len(S) < 5:
            r = rl - ri - FUT_RT
            ws = {}
        else:
            rs = np.nanmean(C[t + h, S] / C[t, S] - 1)
            ws = {int(k): 1 / len(S) for k in S}
            r = rl - rs - BORROW * h / 252
            cost += SIDE * turnover(ws, ws_old)
        rows.append((dates[t], float(r - cost)))
        wl_old, ws_old = wl, ws
    return rows


def vol_rows(cond: bool):
    d = pl.read_csv(ROOT / "data" / "deriv" / "daily.csv", infer_schema_length=5000).select("date", "k200_close", "rep_iv").drop_nulls()
    dt = np.array(d["date"].to_list(), dtype="datetime64[D]")
    k = d["k200_close"].to_numpy().astype(float)
    iv = d["rep_iv"].to_numpy().astype(float)
    lr = np.r_[np.nan, np.diff(np.log(k))]
    rows = []
    for t in range(21, len(k) - 21, 21):
        rv = (252 * np.mean(lr[t + 1:t + 22] ** 2)) ** 0.5 * 100
        rv20 = (252 * np.mean(lr[t - 19:t + 1] ** 2)) ** 0.5 * 100
        if cond and not iv[t] > rv20:
            rows.append((dt[t], 0.0))
            continue
        rows.append((dt[t], float((iv[t] ** 2 - rv ** 2) / (2 * iv[t]) - VOL_COST)))
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    a = ap.parse_args(argv)
    years = range(2016 if a.quick else 2010, 2026)
    df = st.load_hist("KR", years)
    dates, W = wide(df)
    C = ffill(W["close"])
    raw = W["close"]
    R = C / np.r_[np.full((1, C.shape[1]), np.nan), C[:-1]] - 1
    val = roll_mean(raw * W["volume"], 20)
    liq = (val >= 1e9) & (raw >= 1000) & ~np.isnan(raw)
    hi250 = roll_max(W["high"], 250)
    dv = pl.read_csv(ROOT / "data" / "deriv" / "daily.csv", infer_schema_length=5000).select("date", "k200_close").drop_nulls()
    km = dict(zip(dv["date"].to_list(), dv["k200_close"].to_list()))
    idx_c = np.array([km.get(str(d)[:10], np.nan) for d in dates], float)
    idx_c = ffill(idx_c[:, None])[:, 0]

    def pick_b1(t):
        m = liq[t] & (raw[t] / hi250[t] >= 0.95)
        return np.where(m)[0], None

    def dec(score, t):
        m = liq[t] & ~np.isnan(score)
        ii = np.where(m)[0]
        if len(ii) < 50:
            return None, None
        o = ii[np.argsort(score[ii])]
        k = len(o) // 10
        return o[:k], o[-k:]

    def pick_rev(t):
        lo, hi = dec(C[t] / C[t - 5] - 1, t)
        return lo, hi

    def pick_mom(t):
        lo, hi = dec(C[t - 21] / C[t - 252] - 1, t)
        return hi, lo

    cells = {}
    spec = [("L1", "B1 베타헤지 롱숏(5일)", ls_book(dates, C, R, liq, idx_c, 5, 5, pick_b1, hedge_long=True), 5),
            ("L2", "단기 반전 롱숏(5일, 하위10% 롱/상위10% 숏)", ls_book(dates, C, R, liq, idx_c, 5, 5, pick_rev), 5),
            ("L3", "12-1 모멘텀 롱숏(21일)", ls_book(dates, C, R, liq, idx_c, 21, 21, pick_mom), 21),
            ("V1", "분산 매도 무조건(21일, 베가 단위 %p)", vol_rows(False), 21),
            ("V2", "분산 매도 IV>RV20 일 때만", vol_rows(True), 21)]
    for key, desc, rows, h in spec:
        c = {"key": key, "desc": desc, "hold": h, "unit": "변동성 %p" if key[0] == "V" else "수익률(소수)", **stats(rows, h)}
        c["grade"] = grade(c)
        if key[0] == "V" and c["grade"] == "B":
            c["note"] = "분산스왑 근사 — 알파북 반영은 실제 옵션 호가 이력 확보 뒤(§0)"
        cells[key] = c
        print(key, c["grade"], "train", c["train"], "\n   test", c["test"], "covid", c["covid_2020_03"])
    if a.quick:
        return
    out = {"v": 1, "asof": datetime.now(KST).strftime("%Y-%m-%d"), "generated_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M KST"),
           "study": STUDY, "prereg": f"reports/studies/{STUDY}.md §0", "m": 5, "t_bonf": T_BONF, "split": str(SPLIT),
           "cells": cells, "pass": [k for k, c in cells.items() if c["grade"] == "B"]}
    (ROOT / "reports" / "studies" / f"{STUDY}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
