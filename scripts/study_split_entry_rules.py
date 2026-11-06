#!/usr/bin/env python3
"""split_entry_rules (사전등록 reports/studies/2026-11-06_split_entry_rules.md §0 그대로). 정의 변경 금지 — 바꾸려면 새 id."""
from __future__ import annotations
import glob, json, math, sys
from datetime import date
import numpy as np, polars as pl

COST = 0.0015; H = 40; IS_END = (2019, 10); OOS_START = (2020, 3); OOS_END = (2025, 10)
ALPHA = 0.05 / 6


def load():
    df = pl.concat([pl.read_parquet(f) for f in sorted(glob.glob("data/hist/kr_20*.parquet"))], how="diagonal")
    df = df.filter(pl.col("yf").str.ends_with(".KS") | pl.col("yf").str.ends_with(".KQ")).unique(["yf", "date"]).sort("yf", "date")
    return df


def first_days(df):
    ds = sorted(df["date"].unique().to_list()); seen = {}
    for d in ds: seen.setdefault((d.year, d.month), d)
    return seen


def bar_exit(o, h, l, j, stop, target):
    if o[j] <= stop: return o[j]
    if l[j] <= stop: return stop
    if o[j] >= target: return o[j]
    if h[j] >= target: return target
    return None


def sim_b(o, h, l, c, i, P0, A, k, tsN=None):
    """B0/TS/ST: 풀 1 단위, 손절 P0-kA, 목표 P0+2kA. 반환 R, 종류."""
    stop, tgt = P0 - k * A, P0 + 2 * k * A
    for n in range(1, H + 1):
        j = i + n; x = bar_exit(o, h, l, j, stop, tgt)
        if x is not None: return (x - P0 - COST * (P0 + x)) / (k * A), "stop" if x <= stop else "tgt"
        if tsN and n == tsN and c[j] < P0 + A: return (c[j] - P0 - COST * (P0 + c[j])) / (k * A), "time"
    x = c[i + H]; return (x - P0 - COST * (P0 + x)) / (k * A), "end"


def sim_sp(o, h, l, c, i, P0, A):
    stop, tgt = P0 - 2 * A, P0 + 4 * A; added = False; Pa = None; cnt = 0
    for n in range(1, H + 1):
        j = i + n; x = bar_exit(o, h, l, j, stop, tgt)
        if x is None and n == H: x = c[j]
        if x is not None:
            if added: pnl = (x - P0) / 3 + (2 / 3) * (x - Pa) - COST * ((P0 + x) / 3 + (2 / 3) * (Pa + x))
            else: pnl = (x - P0) / 3 - COST * (P0 + x) / 3
            return pnl / (2 * A), added
        if not added:
            cnt = cnt + 1 if c[j] > P0 + A else 0
            if cnt >= 2 and n <= H - 1:
                added = True; Pa = c[j]; stop = max(stop, P0 + (2 / 3) * (Pa - P0) - 2 * A)


def nw_t(x, lag=2):
    x = np.asarray(x); n = len(x); m = x.mean(); e = x - m
    v = e @ e / n
    for L in range(1, lag + 1): v += 2 * (1 - L / (lag + 1)) * (e[L:] @ e[:-L]) / n
    se = math.sqrt(v / n); t = m / se if se > 0 else 0.0
    return m, se, t, math.erfc(abs(t) / math.sqrt(2))


def summ(ds, months):
    out = {}
    def seg(name, sel):
        v = [d for d, mo in zip(ds, months) if sel(mo)]
        if len(v) < 5: return {"n": len(v)}
        m, se, t, p = nw_t(v); return {"n": len(v), "mean": round(m, 4), "median": round(float(np.median(v)), 4), "se": round(se, 4), "t": round(t, 2), "p": round(p, 5)}
    out["all"] = seg("all", lambda mo: True)
    out["IS"] = seg("IS", lambda mo: mo <= IS_END)
    out["OOS"] = seg("OOS", lambda mo: mo >= OOS_START)
    out["ex2020"] = seg("ex2020", lambda mo: mo[0] != 2020)
    return out


def grade(s, cap=None):
    a, i, o, x = s["all"], s["IS"], s["OOS"], s["ex2020"]
    if i.get("n", 0) < 60 or o.get("n", 0) < 60: return "검증전 (IS 또는 OOS 월 n<60)"
    sg = lambda r: np.sign(r["mean"])
    same = sg(i) == sg(o) == sg(a)
    side = "" if a["mean"] > 0 else "(역방향)"
    if a["p"] < ALPHA:
        g = "A" if (same and i["p"] < 0.05 and o["p"] < 0.05 and sg(x) == sg(a)) else "B"
        if cap == "B" and g == "A": g = "B"
        return g + side
    if a["p"] < 0.10 and same: return "C" + side
    return "F"


def main():
    df = load(); fd = first_days(df); fset = set(fd.values())
    res = {k: {"d": [], "mo": [], "ntr": 0} for k in ["H1", "H2", "H3", "H4", "H5", "H6"]}
    mix = {"stop": 0, "tgt": 0, "end": 0, "time": 0}; sp_add = [0, 0]; mkeys = sorted(fd)
    per = {mk: {k: [] for k in res} for mk in mkeys}; extra = {mk: [] for mk in mkeys}
    for sym, g in df.group_by("yf", maintain_order=True):
        dts = g["date"].to_list(); n = len(dts)
        o, h, l, c, v = (g[x].cast(pl.Float64).to_numpy() for x in ["open", "high", "low", "close", "volume"])
        if n < 120: continue
        pc = np.r_[np.nan, c[:-1]]; tr = np.maximum.reduce([h - l, np.abs(h - pc), np.abs(l - pc)])
        tv = c * v; idx = {d: i for i, d in enumerate(dts)}
        for mk, d0 in fd.items():
            if not (IS_END >= mk >= (2010, 1) or OOS_START <= mk <= OOS_END): continue
            i = idx.get(d0)
            if i is None or i < 61 or i + H >= n: continue
            if v[i] <= 0 or not np.isfinite(pc[i]): continue
            if np.median(tv[i - 60:i]) < 1e9: continue
            A = tr[i - 13:i + 1].mean(); P0 = c[i]
            if not (A > 0) or 2 * A / P0 > 0.15: continue
            if not (np.all(np.isfinite(o[i:i + H + 1])) and np.all(np.isfinite(c[i:i + H + 1]))): continue
            rb, kind = sim_b(o, h, l, c, i, P0, A, 2); mix[kind] += 1
            rsp, added = sim_sp(o, h, l, c, i, P0, A); sp_add[0] += added; sp_add[1] += 1
            per[mk]["H1"].append(rsp - rb); extra[mk].append(added)
            for key, N in (("H2", 5), ("H3", 10), ("H4", 20)):
                per[mk][key].append(sim_b(o, h, l, c, i, P0, A, 2, N)[0] - rb)
            for key, kk in (("H5", 1.5), ("H6", 3)):
                per[mk][key].append(sim_b(o, h, l, c, i, P0, A, kk)[0] - rb)
    out = {"asof": "2026-11-06", "prereg_doc": "reports/studies/2026-11-06_split_entry_rules.md", "results": {}, "grades": {}, "b0_exit_mix": mix, "sp_confirm_rate": round(sp_add[0] / max(sp_add[1], 1), 3), "trades": sp_add[1]}
    for k in res:
        ds, mo = [], []
        for mk in mkeys:
            if per[mk][k]: ds.append(float(np.mean(per[mk][k]))); mo.append(mk)
        out["results"][k] = summ(ds, mo)
        out["grades"][k] = grade(out["results"][k], "B" if k == "H1" else None)
    json.dump(out, open("/tmp/claude-0/-home-user-market-screener/66c17eb2-0017-5aaa-bb0a-500d7cd42cd4/scratchpad/split_res.json", "w"), ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
