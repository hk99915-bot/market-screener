#!/usr/bin/env python3
"""HF 5차 — BAB 재검. 사전등록 reports/studies/2026-10-23_hf_bab_recheck.md §0.

  python3 scripts/study_hf_bab_recheck.py    # reports/studies/2026-10-23_hf_bab_recheck.json

Q1b 배율 상한 1.5 · Q1L 롱 다리만(지수 헤지) · Q1A 알파북 B1 저변동 − 고변동.
엔진·통계는 scripts/study_hf_ls_vol.py, 정의는 scripts/study_hf_classics.py q1_rows 와 같고 §0 이 정한 곳만 다르다.
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

STUDY = "2026-10-23_hf_bab_recheck"
FLOOR = 2 / 3          # 베타 바닥 → 다리 배율 ≤ 1.5 (3차 Q1 은 1/3)
HI52 = 0.95            # alphabook.HI52_TH
HOLD = 21


def load():
    df = h.st.load_hist("KR", range(2010, 2026))
    dates, W = h.wide(df)
    C = h.ffill(W["close"])
    raw = W["close"]
    R = C / np.r_[np.full((1, C.shape[1]), np.nan), C[:-1]] - 1
    liq = (h.roll_mean(raw * W["volume"], 20) >= 1e9) & (raw >= 1000) & ~np.isnan(raw)
    dv = pl.read_csv(ROOT / "data" / "deriv" / "daily.csv", infer_schema_length=5000).select("date", "k200_close").drop_nulls()
    km = dict(zip(dv["date"].to_list(), dv["k200_close"].to_list()))
    ic = h.ffill(np.array([km.get(str(d)[:10], np.nan) for d in dates], float)[:, None])[:, 0]
    return dates, C, W["high"], R, liq, ic


def run():
    dates, C, H, R, liq, ic = load()
    ir = np.r_[np.nan, ic[1:] / ic[:-1] - 1]

    def beta(idx, t):
        bk = np.nanmean(R[t - 59:t + 1][:, idx], axis=1)
        ix = ir[t - 59:t + 1]
        ok = ~np.isnan(bk) & ~np.isnan(ix)
        b = float(np.cov(bk[ok], ix[ok])[0, 1] / np.var(ix[ok], ddof=1)) if ok.sum() > 20 else 1.0
        return max(b, FLOOR)

    q1b, q1l, q1a = [], [], []
    wl_old, ws_old, wll_old = {}, {}, {}
    for t in range(260, len(dates) - HOLD, HOLD):
        vol = np.nanstd(R[t - 59:t + 1], axis=0)
        m = liq[t] & (np.sum(~np.isnan(R[t - 59:t + 1]), axis=0) >= 50)
        ii = np.where(m)[0]
        d = dates[t]
        if len(ii) < 50:
            q1b.append((d, 0.0)), q1l.append((d, 0.0)), q1a.append((d, 0.0))
            continue
        o = ii[np.argsort(vol[ii])]
        q = len(o) // 10
        L, S = o[:q], o[-q:]
        bl, bs = beta(L, t), beta(S, t)
        rl = np.nanmean(C[t + HOLD, L] / C[t, L] - 1)
        ri = ic[t + HOLD] / ic[t] - 1
        wl = {int(x): (1 / bl) / len(L) for x in L}
        # Q1L — 롱 다리 ÷ 베타 − 지수
        q1l.append((d, float(rl / bl - ri - h.FUT_RT - h.SIDE * h.turnover(wl, wll_old))))
        wll_old = wl
        # Q1b — 3차 Q1 과 같고 베타 바닥만 2/3
        cost = h.SIDE * h.turnover(wl, wl_old)
        if h.banned(d):
            r = rl / bl - ri - h.FUT_RT
            ws = {}
        else:
            rs = np.nanmean(C[t + HOLD, S] / C[t, S] - 1)
            ws = {int(x): (1 / bs) / len(S) for x in S}
            r = rl / bl - rs / bs - h.BORROW * HOLD / 252 / bs
            cost += h.SIDE * h.turnover(ws, ws_old)
        q1b.append((d, float(r - cost)))
        wl_old, ws_old = wl, ws
        # Q1A — B1 집합 안 저변동 절반 − 고변동 절반, 다음 20거래일
        hi = np.nanmax(H[max(0, t - 249):t + 1], axis=0)
        with np.errstate(invalid="ignore", divide="ignore"):
            prox = C[t] / hi
        b1 = ii[(prox[ii] >= HI52)]
        if len(b1) < 10:
            q1a.append((d, 0.0))
            continue
        ob = b1[np.argsort(vol[b1])]
        half = len(ob) // 2
        fwd = C[t + 20, :] / C[t, :] - 1
        q1a.append((d, float(np.nanmean(fwd[ob[:half]]) - np.nanmean(fwd[ob[-half:]]))))
    return {"Q1b": q1b, "Q1L": q1l, "Q1A": q1a}


def main():
    rows = run()
    desc = {"Q1b": "BAB 베타중립 롱숏, 다리 배율 ≤ 1.5(21일)", "Q1L": "저변동 하위 10% 롱 ÷ 베타 − 코스피200(21일)",
            "Q1A": "알파북 B1 집합 저변동 절반 − 고변동 절반(20일)"}
    cells = {}
    for k, rs in rows.items():
        cl = {"key": k, "desc": desc[k], "hold": HOLD, "unit": "수익률(소수)", **h.stats(rs, HOLD)}
        nz = [r for _, r in rs if r != 0.0]
        cl["worst_period"] = round(min(nz), 4) if nz else None
        cl["n_zero"] = len(rs) - len(nz)
        cl["grade"] = h.grade(cl)
        cells[k] = cl
        print(k, cl["grade"], "train", cl["train"], "\n   test", cl["test"], "worst", cl["worst_period"], "zero", cl["n_zero"])
    out = {"v": 1, "asof": datetime.now(h.KST).strftime("%Y-%m-%d"), "generated_at": datetime.now(h.KST).strftime("%Y-%m-%d %H:%M KST"),
           "study": STUDY, "prereg": f"reports/studies/{STUDY}.md §0", "m": 3, "t_bonf": h.T_BONF, "split": str(h.SPLIT),
           "cells": cells, "pass": [kk for kk, x in cells.items() if x["grade"] == "B"]}
    (ROOT / "reports" / "studies" / f"{STUDY}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
