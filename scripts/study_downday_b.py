#!/usr/bin/env python3
"""하락일 대응 B — H2(급락일 종가 매수 대상 비교) · H3(월 적립 타이밍).

  python3 scripts/study_downday_b.py       # → reports/studies/2026-11-05_downday_b.json

사전등록: docs/desk_kb/rounds/2026-11-05/prereg_downday_b.md (커밋 88a1b780d, 결과 계산 전). 결과를 본 뒤 정의를 바꾸지 않는다.
영향 범위: 연구 산출물만(다른 코드가 읽지 않음). 롤백: json 삭제.
"""
from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from study_crash_close_intraday import down, grade1, sps, t1  # noqa: E402  (t검정·등급 규약 재사용)

HIST = ROOT / "data" / "hist"
OUT = ROOT / "reports" / "studies" / "2026-11-05_downday_b.json"
KST = timezone(timedelta(hours=9))
IS_END = "2021-12-31"
SAMPLE_END = "2025-12-30"  # 개별 종목 자료 끝
COST_KR = 0.0045
HORIZONS = (5, 10, 20)
THRESH = (-0.03, -0.05)
CLUSTER_GAP = 20
M_H2, M_H3 = 18, 4
EX_NAMES = ("005930.KS", "000660.KS")
LOW_ETFS = ("091170", "091180", "117700")
WEIGHTS = {"SPX": 0.40, "NDX": 0.15, "K200": 0.15, "KTB3": 0.20, "GOLD": 0.10}
DOWN_THR = 0.015


# ---------- 공통 ----------
def cluster(idx, gap=CLUSTER_GAP):
    """직전 후보와 gap 거래일 이내면 군집의 첫날만 남긴다(후보 기준 연쇄)."""
    keep, prev = [], None
    for i in idx:
        if prev is None or i - prev > gap:
            keep.append(i)
        prev = i
    return keep


def bh_flags(ps, q=0.10):
    """Benjamini-Hochberg: 정렬 p_(k) <= q*k/m 인 최대 k 까지 통과."""
    m = len(ps)
    order = sorted(range(m), key=lambda i: ps[i])
    kmax = 0
    for rank, i in enumerate(order, 1):
        if ps[i] <= q * rank / m:
            kmax = rank
    ok = [False] * m
    for rank, i in enumerate(order, 1):
        ok[i] = rank <= kmax
    return ok


def nw_mean(y, lag):
    """평균의 Newey-West(Bartlett) z, 단측 p."""
    a = np.asarray(y, float)
    n = len(a)
    if n < 3:
        return {"n": n}
    mu = a.mean()
    e = a - mu
    s = float(e @ e) / n
    for k in range(1, min(lag, n - 1) + 1):
        s += 2 * (1 - k / (lag + 1)) * float(e[k:] @ e[:-k]) / n
    se = math.sqrt(max(s, 1e-18) / n)
    z = mu / se
    return {"n": n, "mean": round(float(mu), 5), "median": round(float(np.median(a)), 5), "win": round(float((a > 0).mean()), 3),
            "t": round(float(z), 2), "p_gt": round(float(sps.norm.sf(z)), 4), "p_lt": round(float(sps.norm.sf(-z)), 4)}


def cap_explore(g):
    return "C(탐색상한)" if g in ("A", "B") else g


def split_stats(xs, dates, alpha, test=t1):
    """전체·IS·OOS 통계와 등급(날짜 문자열 기준 분할)."""
    xs = np.asarray(xs, float)
    ds = np.asarray(dates)
    is_m = ds <= IS_END
    a, s, o = test(xs), test(xs[is_m]), test(xs[~is_m])
    return a, s, o, grade1(a, s, o, alpha) if a.get("n", 0) >= 2 else "검증전"


# ---------- H2 ----------
def load_kospi():
    d = pd.read_parquet(HIST / "kr_index_daily.parquet")
    d = d[d.symbol == "KOSPI"].sort_values("date")
    s = pd.Series(d.close.values.astype(float), index=pd.to_datetime(d.date))
    return s


def load_etf(cal):
    e = pd.read_parquet(HIST / "kr_etf_daily.parquet")
    px = e.pivot(index="date", columns="symbol", values="adj_close")
    px.index = pd.to_datetime(px.index)
    return px.reindex(cal).ffill(limit=3).astype(float)


def load_stocks(cal):
    parts = []
    for y in range(2010, 2026):
        p = HIST / f"kr_{y}.parquet"
        h = pd.read_parquet(p, columns=["yf", "date", "close", "volume"])
        parts.append(h[h.yf.str.endswith(".KS")])
    h = pd.concat(parts)
    h["date"] = pd.to_datetime(h.date)
    h = h.drop_duplicates(["yf", "date"])
    c = h.pivot(index="date", columns="yf", values="close").reindex(cal).astype("float32")
    v = h.pivot(index="date", columns="yf", values="volume").reindex(cal).astype("float32")
    return c, v


def exsemi_forward(c, v, hs):
    """t 마다 상위 200(직전 60일 평균 거래대금, t 전일까지) − 삼성전자·SK하이닉스 동일가중 h일 순수익(비용 전)."""
    val = (c * v).rolling(60, min_periods=40).mean().shift(1)
    ranks = val.rank(axis=1, ascending=False, method="first")
    mask = (ranks <= 200) & c.notna()
    for nm in EX_NAMES:
        if nm in mask.columns:
            mask[nm] = False
    bad = (c.pct_change(fill_method=None).abs() > 0.40).astype("float32")
    out = {}
    for h in hs:
        fwd = c.shift(-h) / c - 1
        fb = bad.rolling(h).sum().shift(-h)
        ok = mask & fwd.notna() & (fb == 0)
        out[h] = fwd.where(ok).mean(axis=1, skipna=True).where(ok.sum(axis=1) >= 100)
    return out, mask.sum(axis=1)


def etf_forward(px, cols, hs):
    out = {}
    for h in hs:
        f = px[list(cols)].shift(-h) / px[list(cols)] - 1
        out[h] = f.mean(axis=1, skipna=False)
    return out


def h2_targets(cal):
    px = load_etf(cal)
    c, v = load_stocks(cal)
    ex, n_univ = exsemi_forward(c, v, HORIZONS)
    tg = {"K200": etf_forward(px, ["069500"], HORIZONS), "EXSEMI_EW": ex, "LOWSEMI_ETF": etf_forward(px, LOW_ETFS, HORIZONS)}
    comp = {s: etf_forward(px, [s], HORIZONS) for s in LOW_ETFS}
    return tg, comp, n_univ


def net_excess(series, idx_events, dates, h_mask_is):
    """이벤트 순 초과 = 이벤트 h일 수익 − 같은 분할 모든 날 평균 − 비용. (이벤트 인덱스, 값, 날짜 문자열)."""
    vals = series.values
    ds = np.asarray([d.strftime("%Y-%m-%d") for d in series.index])
    base_all = np.nanmean(vals[(ds <= SAMPLE_END) & np.isfinite(vals)])
    base_is = np.nanmean(vals[(ds <= IS_END) & np.isfinite(vals)])
    base_oos = np.nanmean(vals[(ds > IS_END) & (ds <= SAMPLE_END) & np.isfinite(vals)])
    rows = []
    for i in idx_events:
        x = vals[i]
        if not np.isfinite(x):
            continue
        b = base_is if ds[i] <= IS_END else base_oos
        rows.append((i, float(x), float(x - b - COST_KR), ds[i]))
    return rows, {"all": float(base_all), "is": float(base_is), "oos": float(base_oos)}


def cell_stats(rows, alpha, drop_years=()):
    """셀 통계 + 강건성(2020·2022 제외 부호 반전 시 한 단계 하향)."""
    xs = [r[2] for r in rows]
    ds = [r[3] for r in rows]
    a, s, o, g = split_stats(xs, ds, alpha)
    flips = {}
    for y in ("2020", "2022"):
        sub = [(x, d) for x, d in zip(xs, ds) if not d.startswith(y)]
        st = t1([x for x, _ in sub]) if len(sub) >= 2 else {}
        flips[y] = st.get("mean")
    flip = any(m is not None and a.get("mean") is not None and m * a["mean"] < 0 for m in flips.values())
    gross = [r[1] for r in rows]
    return {"net_excess": a, "is": s, "oos": o, "grade_raw": g, "grade": down(g) if flip else g, "flip_by_robust": flip,
            "ex_year_mean": {k: (round(v, 5) if v is not None else None) for k, v in flips.items()},
            "gross_mean": round(float(np.mean(gross)), 5) if gross else None,
            "gross_median": round(float(np.median(gross)), 5) if gross else None,
            "gross_win": round(float((np.asarray(gross) > 0).mean()), 3) if gross else None}


def run_h2():
    kospi = load_kospi()
    cal = kospi.index
    ret = kospi.pct_change()
    ds_str = np.asarray([d.strftime("%Y-%m-%d") for d in cal])
    tg, comp, n_univ = h2_targets(cal)
    alpha = 0.05 / M_H2
    out = {"alpha": alpha, "m": M_H2, "sample_end": SAMPLE_END, "events": {}, "cells": {}, "explore_pair": {}, "explore_components": {},
           "exsemi_universe_median_n": int(n_univ[n_univ > 0].median()), "baseline_mean": {}}
    pvals, keys = [], []
    for thr in THRESH:
        cand = [i for i in range(1, len(cal)) if ret.iloc[i] <= thr and ds_str[i] <= SAMPLE_END]
        keep = cluster(cand)
        out["events"][str(thr)] = {"candidates": len(cand), "nonoverlap": len(keep), "dates": [ds_str[i] for i in keep]}
        rows_by = {}
        for name, per_h in tg.items():
            for h in HORIZONS:
                rows, base = net_excess(per_h[h], keep, cal, None)
                rows_by[(name, h)] = rows
                out["baseline_mean"][f"{name}|{h}"] = {k: round(v, 5) for k, v in base.items()}
                cs = cell_stats(rows, alpha)
                key = f"{name}|h{h}|{int(thr * 100)}"
                out["cells"][key] = cs
                pvals.append(cs["net_excess"].get("p_gt", 1.0))
                keys.append(key)
        for name in ("EXSEMI_EW", "LOWSEMI_ETF"):
            for h in HORIZONS:
                a_rows = {r[0]: r for r in rows_by[(name, h)]}
                b_rows = {r[0]: r for r in rows_by[("K200", h)]}
                common = sorted(set(a_rows) & set(b_rows))
                diff = [(i, 0.0, a_rows[i][2] - b_rows[i][2], a_rows[i][3]) for i in common]
                cs = cell_stats(diff, alpha)
                cs["grade"] = cap_explore(cs["grade"])
                out["explore_pair"][f"{name}-K200|h{h}|{int(thr * 100)}"] = cs
        for s, per_h in comp.items():
            for h in HORIZONS:
                rows, _ = net_excess(per_h[h], keep, cal, None)
                cs = cell_stats(rows, alpha)
                cs["grade"] = cap_explore(cs["grade"])
                out["explore_components"][f"{s}|h{h}|{int(thr * 100)}"] = cs
    bh = bh_flags(pvals)
    for k, f in zip(keys, bh):
        out["cells"][k]["bonferroni_pass"] = bool(out["cells"][k]["net_excess"].get("p_gt", 1) < alpha)
        out["cells"][k]["bh_q10_pass"] = bool(f)
    return out


# ---------- H3 ----------
def load_h3_prices():
    k = load_kospi()
    cal = k.index[k.index >= "2010-10-18"]
    px = load_etf(cal)
    u = pd.read_parquet(HIST / "us_daily.parquet")
    us = u.pivot(index="date", columns="symbol", values="adj_close")
    us.index = pd.to_datetime(us.index)
    spy, fx, gspc = us["SPY"].dropna(), us["KRW=X"].dropna(), us["^GSPC"].dropna()
    pos_us = np.searchsorted(spy.index.values, cal.values, side="left") - 1
    pos_fx = np.searchsorted(fx.index.values, cal.values, side="left") - 1
    spx_krw = spy.values[pos_us] * fx.values[pos_fx]
    P = np.column_stack([spx_krw, px["133690"].values, px["069500"].values, px["114260"].values, px["132030"].values]).astype(float)
    r_k = k.pct_change().reindex(cal).values
    g_ret = gspc.pct_change()
    return cal, P, r_k, g_ret


def trigger_flags(cal, r_k, g_ret, thr, mode):
    kd = (r_k <= -thr) if mode in ("either", "kospi") else np.zeros(len(cal), bool)
    sd = np.zeros(len(cal), bool)
    if mode in ("either", "sp"):
        us_days = g_ret[g_ret <= -thr].index.values
        pos = np.searchsorted(cal.values, us_days, side="right")  # u 이후 첫 KR 거래일
        for p in pos:
            if p < len(cal):
                sd[p] = True
    return np.nan_to_num(kd.astype(float)).astype(bool) | sd


def month_blocks(cal):
    m = pd.Series(np.arange(len(cal)), index=cal).groupby([cal.year, cal.month])
    return [(int(g.iloc[0]), int(g.iloc[-1])) for _, g in m if g.index[0] >= pd.Timestamp("2010-11-01")]


def month_arms(P, w, i0, iB, iX):
    """한 달: (ΔV_B, ΔV_C, 단가지수_B, 단가지수_C, 대기일, 기회비용) — 비용은 안 사이 상쇄라 미반영."""
    p0, pb = P[i0], P[iB]
    uA, uB = w / p0, w / pb
    uC = 0.5 * uA + 0.5 * uB
    pr_b = float(np.sum(w * (pb / p0 - 1)))
    pr_c = float(np.sum(w * (1 / (0.5 + 0.5 * p0 / pb) - 1)))
    if iX is None:
        dvb = dvc = None
    else:
        dvb, dvc = float((uB - uA) @ P[iX]), float((uC - uA) @ P[iX])
    return dvb, dvc, pr_b, pr_c, iB - i0, pr_b


def run_h3_variant(cal, P, flags, last_complete):
    w = np.array(list(WEIGHTS.values()))
    cal_np = cal.values
    rows = []
    for i0, end in month_blocks(cal):
        if cal[end] > last_complete:
            continue
        hit = np.nonzero(flags[i0:end + 1])[0]
        iB = i0 + int(hit[0]) if len(hit) else end
        x = np.searchsorted(cal_np, np.datetime64(cal[i0] + timedelta(days=365), "ns"), side="left")
        iX = int(x) if x < len(cal) else None
        dvb, dvc, pb_, pc_, wait, opp = month_arms(P, w, i0, iB, iX)
        rows.append({"d": cal[i0].strftime("%Y-%m-%d"), "dvb": dvb, "dvc": dvc, "pb": pb_, "pc": pc_, "wait": wait, "opp": opp, "trig": bool(len(hit))})
    return rows


def h3_tests(rows, alpha, cap=False):
    spec = (("H3a", "dvb", 1, 11), ("H3b", "dvc", 1, 11), ("H3c", "pb", -1, 2), ("H3d", "pc", -1, 2))
    out = {}
    for name, key, sgn, lag in spec:
        sel = [r for r in rows if r[key] is not None]
        ys = [sgn * r[key] for r in sel]
        ds = [r["d"] for r in sel]
        a, s, o, g = split_stats(ys, ds, alpha, test=lambda z, lag=lag: nw_mean(z, lag))
        out[name] = {"series": key, "sign": "+ = 안이 A보다 낫다(ΔV 증가·단가 하락)", "all": a, "is": s, "oos": o, "grade": cap_explore(g) if cap else g}
    return out


def h3_describe(rows):
    pb = np.array([r["pb"] for r in rows])
    trig = np.array([r["trig"] for r in rows])
    wait = np.array([r["wait"] for r in rows], float)
    return {"months": len(rows), "trigger_months_share": round(float(trig.mean()), 3), "no_trigger_month_end_share": round(float(1 - trig.mean()), 3),
            "mean_wait_days": round(float(wait.mean()), 2), "median_wait_days": float(np.median(wait)),
            "mean_forgone_return_B_vs_A": round(float(pb.mean()), 5), "median_forgone_B": round(float(np.median(pb)), 5),
            "mean_unit_price_idx_B": round(float(pb.mean()), 5), "mean_unit_price_idx_C": round(float(np.mean([r["pc"] for r in rows])), 5),
            "mean_dV_B": round(float(np.mean([r["dvb"] for r in rows if r["dvb"] is not None])), 5),
            "mean_dV_C": round(float(np.mean([r["dvc"] for r in rows if r["dvc"] is not None])), 5),
            "n_dV_months": int(sum(r["dvb"] is not None for r in rows)),
            "triggered_only": {"n": int(trig.sum()), "mean_forgone_B": round(float(pb[trig].mean()), 5) if trig.any() else None,
                               "mean_dV_B": round(float(np.mean([r["dvb"] for r in rows if r["trig"] and r["dvb"] is not None])), 5) if trig.any() else None},
            "no_trigger_only": {"n": int((~trig).sum()), "mean_forgone_B": round(float(pb[~trig].mean()), 5) if (~trig).any() else None}}


def run_h3():
    cal, P, r_k, g_ret = load_h3_prices()
    last = cal[-1]
    alpha = 0.05 / M_H3
    out = {"alpha": alpha, "m": M_H3, "weights": WEIGHTS, "first_month": "2010-11", "data_end": last.strftime("%Y-%m-%d"), "explore": {}}
    # 마지막 달이 월말 거래일로 끝나지 않으면(자료 끝 = 중간) 그 달은 미완성으로 제외
    last_complete = last if (last + timedelta(days=3)).month != last.month else pd.Timestamp(last.year, last.month, 1) - timedelta(days=1)
    main = run_h3_variant(cal, P, trigger_flags(cal, r_k, g_ret, DOWN_THR, "either"), last_complete)
    out["main"] = {"thr": DOWN_THR, "mode": "either", "describe": h3_describe(main), "tests": h3_tests(main, alpha)}
    out["main_months_is"] = sum(r["d"] <= IS_END for r in main)
    for thr, mode in ((0.010, "either"), (0.020, "either"), (DOWN_THR, "kospi"), (DOWN_THR, "sp")):
        rows = run_h3_variant(cal, P, trigger_flags(cal, r_k, g_ret, thr, mode), last_complete)
        out["explore"][f"thr{thr}|{mode}"] = {"describe": h3_describe(rows), "tests": h3_tests(rows, alpha, cap=True)}
    out["monthly_main"] = [{k: (round(v, 5) if isinstance(v, float) else v) for k, v in r.items()} for r in main]
    return out


def main():
    h2 = run_h2()
    h3 = run_h3()
    res = {"v": 1, "study": "2026-11-05_downday_b", "topic": "downday_response", "generated_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M KST"),
           "prereg": "docs/desk_kb/rounds/2026-11-05/prereg_downday_b.md (커밋 88a1b780d)", "m": M_H2 + M_H3, "m_by": {"H2": M_H2, "H3": M_H3},
           "explore_n": {"H2": 30, "H3": 16}, "n_total_this_file": M_H2 + M_H3 + 46, "n_with_line1": M_H2 + M_H3 + 46 + 45,
           "is_end": IS_END, "cost": {"kr_round_trip": COST_KR}, "H2": h2, "H3": h3}
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
