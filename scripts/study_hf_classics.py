#!/usr/bin/env python3
"""HF 3차 알파 소스 — 고전 전략 5종. 사전등록 reports/studies/2026-10-21_hf_classics.md §0.

  python3 scripts/study_hf_classics.py    # reports/studies/2026-10-21_hf_classics.json

T1 시계열 모멘텀(롱 보유 대비) · Q1 BAB 베타중립 롱숏 · C1 월말·월초 · O1 오버나이트 · V3 롱 감마(사후 착안, C 상한).
엔진·통계는 scripts/study_hf_ls_vol.py 재사용. 영향 범위: 연구 산출물만(알파북 미연결).
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

STUDY = "2026-10-21_hf_classics"


def deriv():
    d = pl.read_csv(ROOT / "data" / "deriv" / "daily.csv", infer_schema_length=5000)
    d = d.select("date", "k200_close", "kospi_open", "kospi_close", "rep_iv").drop_nulls()
    return (np.array(d["date"].to_list(), dtype="datetime64[D]"), d["k200_close"].to_numpy().astype(float),
            d["kospi_open"].to_numpy().astype(float), d["kospi_close"].to_numpy().astype(float), d["rep_iv"].to_numpy().astype(float))


def t1_rows(dt, k):
    lr = np.r_[np.nan, np.diff(np.log(k))]
    rows, prev = [], 0.0
    for t in range(252, len(k) - 21, 21):
        rv60 = (252 * np.mean(lr[t - 59:t + 1] ** 2)) ** 0.5
        size = min(2.0, 0.15 / rv60) if rv60 > 0 else 0.0
        sgn = 1.0 if k[t] / k[t - 252] - 1 > 0 else -1.0
        r = k[t + 21] / k[t] - 1
        pos = sgn * size
        rows.append((dt[t], float(pos * r - size * r - h.FUT_RT * abs(pos - prev))))
        prev = pos
    return rows


def c1_rows(dt, k):
    ym = dt.astype("datetime64[M]")
    r = np.r_[np.nan, k[1:] / k[:-1] - 1]
    rows = []
    months = np.unique(ym)
    for m in months[1:-1]:
        ii = np.where(ym == m)[0]
        nx = np.where(ym == m + np.timedelta64(1, "M"))[0]
        if len(ii) < 10 or len(nx) < 3:
            continue
        last = ii[-1]
        a, b = last - 1, nx[2]          # 마지막 거래일 직전 종가 → 다음 달 3번째 거래일 종가
        tom = k[b] / k[a] - 1
        rest = np.setdiff1d(ii, [last])[3:]   # 이달 첫 3거래일(전월 TOM 일부)·마지막 날 제외
        base = np.nanmean(r[rest]) * 4 if len(rest) else 0.0
        rows.append((dt[last], float(tom - base - h.FUT_RT)))
    return rows


def o1_rows(dt, o, c):
    rows = []
    for t in range(1, len(c)):
        on = o[t] / c[t - 1] - 1
        cc = c[t] / c[t - 1] - 1
        rows.append((dt[t], float(on - cc / 2 - h.FUT_RT)))
    return rows


def v3_rows(dt, k, iv):
    lr = np.r_[np.nan, np.diff(np.log(k))]
    rows = []
    for t in range(21, len(k) - 21, 21):
        rv = (252 * np.mean(lr[t + 1:t + 22] ** 2)) ** 0.5 * 100
        rv20 = (252 * np.mean(lr[t - 19:t + 1] ** 2)) ** 0.5 * 100
        if not iv[t] < rv20:
            rows.append((dt[t], 0.0))
            continue
        rows.append((dt[t], float((rv ** 2 - iv[t] ** 2) / (2 * iv[t]) - h.VOL_COST)))
    return rows


def q1_rows():
    df = h.st.load_hist("KR", range(2010, 2026))
    dates, W = h.wide(df)
    C = h.ffill(W["close"])
    raw = W["close"]
    R = C / np.r_[np.full((1, C.shape[1]), np.nan), C[:-1]] - 1
    liq = (h.roll_mean(raw * W["volume"], 20) >= 1e9) & (raw >= 1000) & ~np.isnan(raw)
    dv = pl.read_csv(ROOT / "data" / "deriv" / "daily.csv", infer_schema_length=5000).select("date", "k200_close").drop_nulls()
    km = dict(zip(dv["date"].to_list(), dv["k200_close"].to_list()))
    ic = h.ffill(np.array([km.get(str(d)[:10], np.nan) for d in dates], float)[:, None])[:, 0]
    ir = np.r_[np.nan, ic[1:] / ic[:-1] - 1]

    def beta(idx, t):
        bk = np.nanmean(R[t - 59:t + 1][:, idx], axis=1)
        ix = ir[t - 59:t + 1]
        ok = ~np.isnan(bk) & ~np.isnan(ix)
        b = float(np.cov(bk[ok], ix[ok])[0, 1] / np.var(ix[ok], ddof=1)) if ok.sum() > 20 else 1.0
        return max(b, 1 / 3)

    rows, wl_old, ws_old = [], {}, {}
    hold = 21
    for t in range(260, len(dates) - hold, hold):
        vol = np.nanstd(R[t - 59:t + 1], axis=0)
        m = liq[t] & (np.sum(~np.isnan(R[t - 59:t + 1]), axis=0) >= 50)
        ii = np.where(m)[0]
        if len(ii) < 50:
            rows.append((dates[t], 0.0))
            continue
        o = ii[np.argsort(vol[ii])]
        q = len(o) // 10
        L, S = o[:q], o[-q:]
        bl, bs = beta(L, t), beta(S, t)
        rl = np.nanmean(C[t + hold, L] / C[t, L] - 1)
        ri = ic[t + hold] / ic[t] - 1
        wl = {int(x): (1 / bl) / len(L) for x in L}
        cost = h.SIDE * h.turnover(wl, wl_old)
        if h.banned(dates[t]):
            r = rl / bl - ri - h.FUT_RT
            ws = {}
        else:
            rs = np.nanmean(C[t + hold, S] / C[t, S] - 1)
            ws = {int(x): (1 / bs) / len(S) for x in S}
            r = rl / bl - rs / bs - h.BORROW * hold / 252 / bs
            cost += h.SIDE * h.turnover(ws, ws_old)
        rows.append((dates[t], float(r - cost)))
        wl_old, ws_old = wl, ws
    return rows


def main():
    dt, k, o, c, iv = deriv()
    spec = [("T1", "시계열 모멘텀 − 같은 크기 롱 보유(21일)", t1_rows(dt, k), 21),
            ("Q1", "저변동성 BAB 베타중립 롱숏(21일)", q1_rows(), 21),
            ("C1", "월말·월초 4일 − 나머지 날 평균×4", c1_rows(dt, k), 21),
            ("O1", "오버나이트 − 종가수익/2", o1_rows(dt, o, c), 1),
            ("V3", "롱 감마 IV<RV20 (사후 착안, C 상한)", v3_rows(dt, k, iv), 21)]
    cells = {}
    for key, desc, rows, hd in spec:
        cl = {"key": key, "desc": desc, "hold": hd, "unit": "변동성 %p" if key == "V3" else "수익률(소수)", **h.stats(rows, hd)}
        g = h.grade(cl)
        if key == "V3" and g == "B":
            g = "C(방향만)"
            cl["note"] = "사후 착안 — 등급 상한 C, 옵션 호가 이력 전 알파북 반영 불가(§0)"
        cl["grade"] = g
        cells[key] = cl
        print(key, g, "train", cl["train"], "\n   test", cl["test"], "covid", cl["covid_2020_03"])
    out = {"v": 1, "asof": datetime.now(h.KST).strftime("%Y-%m-%d"), "generated_at": datetime.now(h.KST).strftime("%Y-%m-%d %H:%M KST"),
           "study": STUDY, "prereg": f"reports/studies/{STUDY}.md §0", "m": 5, "t_bonf": h.T_BONF, "split": str(h.SPLIT),
           "cells": cells, "pass": [kk for kk, x in cells.items() if x["grade"] == "B"]}
    (ROOT / "reports" / "studies" / f"{STUDY}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
