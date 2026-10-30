#!/usr/bin/env python3
"""req-quant-ec93e2cb H2 — 외국인·기관 동반 순매수 k일째(k=1,2,3) 다음날 종가 진입 20거래일 초과수익.

사전등록 docs/desk_kb/rounds/2026-10-29/quant_prereg_ec93e2cb.md §2 그대로: 당일 시총 상위 100(point-in-time), 직전일 동반 순매수 아님에서 시작,
같은 종목·같은 k 20거래일 안 재발 제외, 초과 = 종목 20일 수익 − 같은 날 상위100 평균, 비용 왕복 0.25%, IS<2025-01-01/OOS>=, 하락 = 2022,
월 군집 SE. 가격 = load_kr 보정 종가. KOSPI 대비 병기는 미실행.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from screener.prices import load_kr  # noqa: E402

COST, HOLD, SPLIT = 0.0025, 20, "2025-01-01"


def cl_t(e: np.ndarray, g: np.ndarray) -> tuple[float, float, int]:
    n = len(e); mu = e.mean(); u = e - mu
    ug = np.array([u[g == k].sum() for k in np.unique(g)])
    se = math.sqrt((ug ** 2).sum()) / n * (len(ug) / max(len(ug) - 1, 1)) ** 0.5
    return float(mu), (float(mu / se) if se > 0 else float("nan")), len(ug)


def p1(t: float) -> float:
    return 0.5 * math.erfc(t / math.sqrt(2))


def main() -> None:
    px = load_kr(hist_from=2021).with_columns(pl.col("yf").str.slice(0, 6).alias("code")).select("date", "code", "close")
    px = px.group_by(["date", "code"]).agg(pl.col("close").last())
    fl = pl.concat([pl.read_parquet(p) for p in sorted((ROOT / "data" / "flows").glob("kr_inv_*.parquet"))]).select("date", "code", "mcap", "f", "i")
    dates = sorted(fl["date"].unique().to_list()); di = {x: k for k, x in enumerate(dates)}
    codes = sorted(set(fl["code"].to_list())); ci = {c: k for k, c in enumerate(codes)}
    T, S = len(dates), len(codes)
    def mat(df, col, dcol="date"):
        df = df.filter(pl.col(dcol).is_in(list(di)) & pl.col("code").is_in(list(ci)))
        a = np.full((T, S), np.nan, dtype=np.float64)
        a[df[dcol].replace_strict(di, return_dtype=pl.Int32).to_numpy(), df["code"].replace_strict(ci, return_dtype=pl.Int32).to_numpy()] = df[col].to_numpy().astype(float)
        return a
    cl = mat(px, "close"); mc = mat(fl, "mcap"); f = mat(fl, "f"); i_ = mat(fl, "i")
    cl = pl.DataFrame(cl).fill_nan(None).with_columns(pl.all().forward_fill()).to_numpy()   # 정지·상폐: 마지막 종가 유지
    both = (f > 0) & (i_ > 0)
    top = np.zeros((T, S), bool)
    for t in range(T):
        m = np.where(np.isnan(mc[t]), -1, mc[t]); top[t, np.argsort(-m)[:100]] = True
    ev = {1: [], 2: [], 3: []}
    last = {}
    for t in range(1, T - HOLD - 1):
        e0 = t + 1; e1 = e0 + HOLD
        # 같은 날 상위100 평균 20일 수익(진입 다음날 종가 → +20)
        r = cl[e1] / cl[e0] - 1
        bench = np.nanmean(np.where(top[t], r, np.nan))
        for s in np.where(top[t] & both[t])[0]:
            k = 1 if not both[t - 1, s] else (2 if t >= 2 and not both[t - 2, s] else (3 if t >= 3 and not both[t - 3, s] else 0))
            if k == 0 or np.isnan(r[s]) or np.isnan(bench):
                continue
            if t - last.get((s, k), -99) <= HOLD:
                continue
            last[(s, k)] = t
            ev[k].append((str(dates[t]), r[s] - bench - COST, r[s] - bench))
    out = {}
    for k, rows in ev.items():
        o = {}
        for tag, sel in (("전체", lambda d: True), ("IS", lambda d: d < SPLIT), ("OOS", lambda d: d >= SPLIT), ("하락2022", lambda d: d[:4] == "2022")):
            rr = [x for x in rows if sel(x[0])]
            if len(rr) < 3:
                continue
            e = np.array([x[1] for x in rr]); g = np.array([x[0][:7] for x in rr])
            mu, t, ng = cl_t(e, g)
            o[tag] = {"events": len(rr), "months": ng, "mean_excess_after_cost": mu, "median_excess_after_cost": float(np.median(e)), "cluster_t": t, "p_one": p1(t)}
        out[f"k={k}"] = o
    # H2-4: (k=3) − (k=1) 월별 평균 차의 paired t (양측)
    def bym(rows):
        d = {}
        for dt, ex, _ in rows: d.setdefault(dt[:7], []).append(ex)
        return {m: np.mean(v) for m, v in d.items()}
    a, b = bym(ev[3]), bym(ev[1]); ms = sorted(set(a) & set(b))
    dd = np.array([a[m] - b[m] for m in ms])
    sd = dd.std(ddof=1); t4 = float(dd.mean() / (sd / math.sqrt(len(dd))))
    out["H2-4"] = {"months": len(ms), "mean_diff_k3_minus_k1": float(dd.mean()), "t": t4, "p_two": math.erfc(abs(t4) / math.sqrt(2))}
    out["meta"] = {"dates": T, "first": str(dates[0]), "last": str(dates[-1])}
    json.dump(out, open(ROOT / "reports" / "studies" / "2026-10-30_flow_streak_entry.raw.json", "w"), ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
