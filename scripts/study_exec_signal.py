"""실행 대본 1·2 신호 재검증 + 급락 뒤 비반도체 섹터 로테이션 — reports/studies/exec_signal.md §0 사전 등록 그대로.

python scripts/study_exec_signal.py  → reports/studies/exec_signal.json (+ 표준출력 요약)
데이터: data/deriv/daily.csv (코스피 OHLC + 외국인 현물, 2010~) · data/hist/kr_*.parquet + data/kr_prices.parquet · universe/kr_sector.csv
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts.study_rule_audit import t_cdf  # noqa: E402  (같은 t분포 구현 재사용)

CSV = ROOT / "data" / "deriv" / "daily.csv"
OUT = ROOT / "reports" / "studies" / "exec_signal.json"
HS = (5, 20, 60)
IS_END = "2019-12-31"
M1 = 15                     # H1: 5 신호 × 3 보유기간 (vs U)
ALPHA1 = 0.05 / M1
M3, M4 = 2, 2
MIN_N = 8
GAP = 20
EXCL_SECTORS = {"전기·전자"}
SEMI_CHAINS = ("semi_equip", "it_hw", "components")
SEMI_EXTRA = {"005930", "005935", "000660"}
CHECK = {"2020-03": "2020-03-19", "2022": None, "2024-08": "2024-08-05", "2026-03": "2026-03-09", "2026-10": "2026-10-13"}


# ───────────── 통계 ─────────────
def nw_diff(y: np.ndarray, x: np.ndarray, lag: int) -> dict:
    """y ~ a + b·x, Newey–West(lag) 표준오차. b = 신호일 평균 − 비신호일 평균."""
    ok = np.isfinite(y) & np.isfinite(x)
    y, x = y[ok], x[ok].astype(float)
    n = len(y)
    if n < 10 or x.sum() < 3 or (1 - x).sum() < 3:
        return {"n": int(n), "n1": int(x.sum()), "b": None, "t": None, "p": None}
    X = np.column_stack([np.ones(n), x])
    XtX_inv = np.linalg.inv(X.T @ X)
    beta = XtX_inv @ X.T @ y
    e = y - X @ beta
    S = (X * e[:, None]).T @ (X * e[:, None])
    for L in range(1, lag + 1):
        w = 1 - L / (lag + 1)
        G = (X[L:] * e[L:, None]).T @ (X[:-L] * e[:-L, None])
        S += w * (G + G.T)
    V = XtX_inv @ S @ XtX_inv
    se = math.sqrt(max(V[1, 1], 1e-18))
    t = beta[1] / se
    p = 2 * (1 - NormalDist().cdf(abs(t)))
    return {"n": int(n), "n1": int(x.sum()), "b": float(beta[1]), "t": float(t), "p": float(p)}


def welch(a: np.ndarray, b: np.ndarray) -> dict:
    a, b = a[np.isfinite(a)], b[np.isfinite(b)]
    if len(a) < 3 or len(b) < 3:
        return {"na": len(a), "nb": len(b), "d": None, "p": None}
    va, vb = a.var(ddof=1) / len(a), b.var(ddof=1) / len(b)
    t = (a.mean() - b.mean()) / math.sqrt(va + vb) if va + vb > 0 else float("nan")
    df = (va + vb) ** 2 / (va ** 2 / (len(a) - 1) + vb ** 2 / (len(b) - 1)) if va + vb > 0 else 1
    p = 2 * (1 - t_cdf(abs(t), int(df))) if np.isfinite(t) else None
    return {"na": int(len(a)), "nb": int(len(b)), "d": float(a.mean() - b.mean()), "t": float(t), "p": p}


def ttest1(d) -> dict:
    d = np.asarray([x for x in d if x is not None and np.isfinite(x)], float)
    n = len(d)
    if n < 3:
        return {"n": n, "mean": float(d.mean()) if n else None, "t": None, "p": None}
    sd = d.std(ddof=1)
    t = d.mean() / (sd / math.sqrt(n)) if sd > 0 else float("nan")
    return {"n": n, "mean": float(d.mean()), "t": float(t), "p": float(2 * (1 - t_cdf(abs(t), n - 1))) if np.isfinite(t) else None}


def ztest2(k1, n1, k2, n2) -> dict:
    if min(n1, n2) < 3:
        return {"p": None}
    p1, p2, pp = k1 / n1, k2 / n2, (k1 + k2) / (n1 + n2)
    se = math.sqrt(pp * (1 - pp) * (1 / n1 + 1 / n2))
    z = (p1 - p2) / se if se > 0 else float("nan")
    return {"p1": p1, "p2": p2, "z": float(z), "p": float(2 * (1 - NormalDist().cdf(abs(z)))) if np.isfinite(z) else None}


def grade(p, mean, subs, alpha, n) -> tuple[str, str]:
    if p is None or n < MIN_N:
        return "검증전", f"표본 {n}"
    if p < alpha:
        if all(np.sign(x) == np.sign(mean) for x in subs if x is not None):
            return "A", f"Bonferroni 유의(p={p:.4f}) + IS·OOS 같은 방향"
        return "B", f"Bonferroni 유의(p={p:.4f}), 하위 구간 방향 불일치"
    if p < 0.10:
        return "C", f"방향만(p={p:.3f}, Bonferroni α={alpha:.4f} 미달)"
    return "F", f"구별 안 됨(p={p:.2f})"


def desc(r: np.ndarray) -> dict:
    r = r[np.isfinite(r)]
    if not len(r):
        return {"n": 0}
    return {"n": int(len(r)), "mean": float(r.mean()), "median": float(np.median(r)), "win": float((r > 0).mean()), "worst": float(r.min())}


# ───────────── Part 1 ─────────────
def load_kospi() -> pd.DataFrame:
    d = pd.read_csv(CSV, usecols=["date", "kospi_low", "kospi_close", "spot_frgn"]).dropna(subset=["kospi_close"]).reset_index(drop=True)
    c, lo, f = d.kospi_close.values, d.kospi_low.values, d.spot_frgn.values
    d["ret1"] = d.kospi_close.pct_change()
    d["sma20"] = d.kospi_close.rolling(20).mean()
    d["sma200"] = d.kospi_close.rolling(200).mean()
    d["hi5"] = d.kospi_close.rolling(5).max()
    d["dd20"] = c / d.kospi_close.rolling(21).max() - 1
    d["bear"] = (d.kospi_close < d.sma200) | (d.dd20 <= -0.15)
    d["S1"] = f > 0
    d["S2"] = c >= lo
    d["S2p"] = c >= lo * 1.01
    d["S12"] = d.S1 & d.S2p
    fprev = np.r_[np.nan, f[:-1]]
    d["R"] = (f > 0) & (fprev > 0) & (c >= d.hi5.values)
    d["Rp"] = d.R & (c > d.sma20)
    d["F"] = d.ret1 <= -0.05
    for h in HS:
        d[f"r{h}"] = d.kospi_close.shift(-h) / d.kospi_close - 1
    return d


def part1(d: pd.DataFrame) -> dict:
    res = {"universe": {}, "h1": {}, "h2": {}, "h3": {}, "grades": {}}
    b = d[d.bear & d.sma200.notna()].copy()
    res["universe"] = {"days": int(len(d)), "bear_days": int(len(b)), "bear_share": float(len(b) / len(d)),
                       "fire_share_bear": {s: float(b[s].mean()) for s in ("S1", "S2", "S2p", "S12", "R", "Rp", "F")},
                       "fire_share_all": {s: float(d[s].mean()) for s in ("S1", "S2", "S2p", "S12", "R", "Rp", "F")}}
    for scope, df in (("bear", b), ("all", d)):
        out = {}
        for s in ("U", "S1", "S2", "S2p", "S12", "R", "Rp", "F"):
            row = {}
            sub = df if s == "U" else df[df[s]]
            for h in HS:
                r = sub[f"r{h}"].values
                row[f"r{h}"] = desc(r)
                if s not in ("U", "F"):
                    nw = nw_diff(df[f"r{h}"].values, df[s].values, h - 1)
                    isx = df.date <= IS_END
                    nw_is = nw_diff(df[f"r{h}"].values[isx.values], df[s].values[isx.values], h - 1)
                    nw_oos = nw_diff(df[f"r{h}"].values[~isx.values], df[s].values[~isx.values], h - 1)
                    row[f"vsU{h}"] = {**nw, "is": nw_is["b"], "n_is": nw_is["n1"], "oos": nw_oos["b"], "n_oos": nw_oos["n1"]}
                    row[f"vsF{h}"] = welch(r, df[df.F][f"r{h}"].values)
            out[s] = row
        res["h1"][scope] = out
    # 등급: 주 분석(하락장) vs U
    for s in ("S1", "S2p", "S12", "R", "Rp"):
        for h in HS:
            v = res["h1"]["bear"][s][f"vsU{h}"]
            g, why = grade(v["p"], v["b"], [v["is"], v["oos"]], ALPHA1, v["n1"])
            res["grades"][f"H1/{s}/r{h}"] = {"grade": g, "why": why, "diff": v["b"], "p": v["p"], "n": v["n1"]}
    # H2 빈도
    yrs = sorted(set(b.date.str[:4]))
    h2 = {}
    for s in ("S12", "R", "Rp"):
        fire = b[b[s]]
        per_year = {y: int((fire.date.str[:4] == y).sum()) for y in yrs}
        bear_days_year = {y: int((b.date.str[:4] == y).sum()) for y in yrs}
        idx = np.where(d[s].values)[0]
        gaps = np.diff(idx) if len(idx) > 1 else np.array([0])
        gi = int(gaps.argmax()) if len(idx) > 1 else 0
        checks = {}
        for lab, t0 in CHECK.items():
            if t0 is None:   # 2022: 그해 첫 하락장 날
                t0 = b[b.date.str.startswith("2022")].date.iloc[0] if (b.date.str.startswith("2022")).any() else None
            if t0 is None:
                continue
            i0 = int(d.index[d.date >= t0][0])
            nxt = [i for i in idx if i > i0]
            if nxt:
                i1 = nxt[0]
                checks[lab] = {"t0": d.date[i0], "first": d.date[i1], "wait": int(i1 - i0), "missed": float(d.kospi_close[i1] / d.kospi_close[i0] - 1),
                               "r20_from_fire": float(d.r20[i1]) if np.isfinite(d.r20[i1]) else None, "r20_from_t0": float(d.r20[i0]) if np.isfinite(d.r20[i0]) else None}
            else:
                checks[lab] = {"t0": d.date[i0], "first": None}
        h2[s] = {"per_year_bear": per_year, "bear_days_year": bear_days_year, "n_bear": int(len(fire)),
                 "max_gap_days_all": int(gaps.max()) if len(idx) > 1 else None,
                 "max_gap_span": [d.date[idx[gi]], d.date[idx[gi + 1]]] if len(idx) > 1 else None, "checks": checks}
    res["h2"] = h2
    # H3
    h3 = {}
    for s in ("S1", "S2p", "S12"):
        r = b[b[s]].r20.values
        r = r[np.isfinite(r)]
        h3[s] = {"n": int(len(r)), "win": float((r > 0).mean()), "mean": float(r.mean())}
    for other in ("S1", "S2p"):
        z = ztest2(round(h3["S12"]["win"] * h3["S12"]["n"]), h3["S12"]["n"], round(h3[other]["win"] * h3[other]["n"]), h3[other]["n"])
        h3[f"S12_vs_{other}"] = z
        res["grades"][f"H3/S12_vs_{other}"] = {"grade": grade(z.get("p"), (z.get("p1") or 0) - (z.get("p2") or 0), [], 0.05 / M3, h3["S12"]["n"])[0],
                                                "diff_win": (z.get("p1") or 0) - (z.get("p2") or 0), "p": z.get("p")}
    res["h3"] = h3
    return res


# ───────────── Part 2 ─────────────
def load_prices() -> pd.DataFrame:
    frames = []
    for f in sorted((ROOT / "data" / "hist").glob("kr_*.parquet")):
        frames.append(pq.read_table(f, columns=["yf", "date", "close"]).to_pandas())
    frames.append(pq.read_table(ROOT / "data" / "kr_prices.parquet", columns=["yf", "date", "close"]).to_pandas())
    p = pd.concat(frames, ignore_index=True).drop_duplicates(["yf", "date"], keep="last")
    p["code"] = p.yf.str[:6]
    p["date"] = p.date.astype(str).str[:10]
    px = p.pivot(index="date", columns="code", values="close").sort_index()
    return px


def semi_codes() -> set:
    from screener.drivers import CHAINS
    s = set(SEMI_EXTRA)
    for k in SEMI_CHAINS:
        s |= set(CHAINS.get(k, {}).get("codes", []))
    return s


def sector_index(px: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    sec = pd.read_csv(ROOT / "universe" / "kr_sector.csv", dtype=str).dropna()
    excl = semi_codes()
    sec = sec[~sec.sector.isin(EXCL_SECTORS) & ~sec.code.isin(excl)]
    ret = px.pct_change(fill_method=None)
    ret = ret.where(ret.abs() < 0.5)          # 분할·오류 튐 제거
    out, cnt = {}, {}
    for s, g in sec.groupby("sector"):
        cols = [c for c in g.code if c in ret.columns]
        if len(cols) < MIN_N:
            continue
        r = ret[cols]
        n = r.notna().sum(axis=1)
        m = r.mean(axis=1).where(n >= MIN_N)
        out[s] = m
        cnt[s] = n
    R = pd.DataFrame(out)
    idx = (1 + R.fillna(0)).cumprod().where(R.notna())
    return idx, {s: int(c.median()) for s, c in cnt.items()}


def part2(d: pd.DataFrame, px: pd.DataFrame) -> dict:
    idx, members = sector_index(px)
    idx = idx.ffill(limit=3)
    dates = list(idx.index)
    pos = {dt: i for i, dt in enumerate(dates)}
    k = d.set_index("date")
    kc = k.kospi_close.reindex(idx.index).ffill()
    dd20 = idx / idx.rolling(21).max() - 1
    fwd = {h: idx.shift(-h) / idx - 1 for h in (20, 60)}
    kfwd = {h: kc.shift(-h) / kc - 1 for h in (20, 60)}
    # 이벤트
    crash_all = [dt for dt in k.index[k.F] if dt in pos]
    reb_all = [dt for dt in k.index[(k.dd20 <= -0.15) & (k.ret1 >= 0.005)] if dt in pos]

    def nonoverlap(ds):
        out, last = [], -10 ** 9
        for dt in ds:
            if pos[dt] - last > GAP:
                out.append(dt)
                last = pos[dt]
        return out

    res = {"sectors": members, "n_sectors": len(members), "excluded": sorted(EXCL_SECTORS) + ["semi_equip·it_hw·components 체인", "삼성전자·SK하이닉스"], "events": {}, "tables": {}, "h4": {}, "grades": {}}
    for kind, allds in (("crash", crash_all), ("rebound", reb_all)):
        evs = nonoverlap(allds)
        evs = [dt for dt in evs if pos[dt] + 60 < len(dates)]
        res["events"][kind] = {"n_all_days": len(allds), "n_nonoverlap": len(evs), "dates": evs}
        for sub, ds in (("nonoverlap", evs), ("all_days", [dt for dt in allds if pos[dt] + 60 < len(dates)])):
            rows = {}
            for s in idx.columns:
                r20 = np.array([fwd[20].loc[dt, s] - kfwd[20].loc[dt] for dt in ds], float)
                r60 = np.array([fwd[60].loc[dt, s] - kfwd[60].loc[dt] for dt in ds], float)
                a60 = np.array([fwd[60].loc[dt, s] for dt in ds], float)
                a20 = np.array([fwd[20].loc[dt, s] for dt in ds], float)
                ok = np.isfinite(r60)
                if ok.sum() < 3:
                    continue
                sd = r60[ok].std(ddof=1)
                rows[s] = {"n": int(ok.sum()), "abs20": float(np.nanmean(a20)), "abs60": float(np.nanmean(a60)),
                           "ex20": float(np.nanmean(r20)), "ex60": float(r60[ok].mean()), "win60": float((r60[ok] > 0).mean()),
                           "sd60": float(sd), "ra60": float(r60[ok].mean() / sd) if sd > 0 else None, "worst60": float(r60[ok].min())}
            # (사후 보조, 등급 무관) 섹터 간 상대: 각 이벤트에서 포함 섹터 평균 대비 60일 초과
            ex_mat = np.array([[fwd[60].loc[dt, s] for s in idx.columns] for dt in ds], float)
            rel = ex_mat - np.nanmean(ex_mat, axis=1, keepdims=True)
            for j, s in enumerate(idx.columns):
                if s in rows:
                    rows[s]["rel60"] = float(np.nanmean(rel[:, j]))
            rows["KOSPI"] = {"n": len(ds), "abs20": float(np.nanmean([kfwd[20].loc[dt] for dt in ds])), "abs60": float(np.nanmean([kfwd[60].loc[dt] for dt in ds]))}
            res["tables"][f"{kind}/{sub}"] = rows
        # H4: 덜 빠진 상위 1/3 vs 많이 빠진 하위 1/3
        diffs = {20: [], 60: []}
        per = []
        for dt in evs:
            row = dd20.loc[dt].dropna()
            if len(row) < 6:
                continue
            q = len(row) // 3
            srt = row.sort_values()
            worst, best = list(srt.index[:q]), list(srt.index[-q:])
            rec = {"date": dt, "least": best, "most": worst}
            for h in (20, 60):
                fb = fwd[h].loc[dt, best].mean() - kfwd[h].loc[dt]
                fw = fwd[h].loc[dt, worst].mean() - kfwd[h].loc[dt]
                diffs[h].append(fb - fw)
                rec[f"least{h}"], rec[f"most{h}"] = float(fb), float(fw)
            per.append(rec)
        t60, t20 = ttest1(diffs[60]), ttest1(diffs[20])
        dates_ev = np.array([p["date"] for p in per], dtype=str)
        d60 = np.array(diffs[60], float)
        sub = {"is": ttest1(d60[dates_ev <= IS_END]), "oos": ttest1(d60[dates_ev > IS_END])}
        g, why = grade(t60["p"], t60["mean"], [sub["is"]["mean"], sub["oos"]["mean"]], 0.05 / M4, t60["n"])
        res["h4"][kind] = {"n": t60["n"], "diff60": t60, "diff20": t20, "is": sub["is"], "oos": sub["oos"],
                           "least_mean60": float(np.mean([p["least60"] for p in per])) if per else None,
                           "most_mean60": float(np.mean([p["most60"] for p in per])) if per else None,
                           "least_mean20": float(np.mean([p["least20"] for p in per])) if per else None,
                           "most_mean20": float(np.mean([p["most20"] for p in per])) if per else None, "per_event": per}
        res["grades"][f"H4/{kind}"] = {"grade": g, "why": why, "diff": t60["mean"], "p": t60["p"], "n": t60["n"]}
    # 상·하위 3 (급락 비중첩, n≥8)
    tb = {s: v for s, v in res["tables"]["crash/nonoverlap"].items() if s != "KOSPI" and v["n"] >= MIN_N and v.get("ra60") is not None}
    rank = sorted(tb.items(), key=lambda kv: kv[1]["ra60"], reverse=True)
    res["best3"] = [{"sector": s, **v} for s, v in rank[:3]]
    res["worst3"] = [{"sector": s, **v} for s, v in rank[-3:]]
    res["rank_all"] = [{"sector": s, "n": v["n"], "ex60": v["ex60"], "ra60": v["ra60"], "win60": v["win60"]} for s, v in rank]
    try:
        rot = json.loads((ROOT / "reports" / "committee.json").read_text(encoding="utf-8")).get("rotation") or {}
        res["committee_rotation_today"] = {k_: [(x.get("theme") or x.get("chain")) for x in rot.get(k_, [])] for k_ in ("lead", "lag", "overweight", "underweight")}
    except Exception:  # noqa: BLE001
        res["committee_rotation_today"] = {}
    return res


def main() -> None:
    d = load_kospi()
    p1 = part1(d)
    px = load_prices()
    p2 = part2(d, px)
    out = {"asof": d.date.iloc[-1], "prereg": "reports/studies/exec_signal.md §0 (커밋 4fb5c60d)", "params": {"is_end": IS_END, "m1": M1, "alpha1": ALPHA1, "m3": M3, "m4": M4, "min_n": MIN_N, "gap": GAP},
           "part1": p1, "part2": p2}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o)), encoding="utf-8")
    pct = lambda x: "—" if x is None else f"{x*100:+.1f}"  # noqa: E731
    print("하락장 날", p1["universe"]["bear_days"], "/", p1["universe"]["days"], "발동 비율(하락장)", {k: round(v, 3) for k, v in p1["universe"]["fire_share_bear"].items()})
    for s, row in p1["h1"]["bear"].items():
        print(s, " ".join(f"r{h} n{row[f'r{h}'].get('n')} {pct(row[f'r{h}'].get('mean'))} 승{(row[f'r{h}'].get('win') or 0)*100:.0f}%" for h in HS),
              " | vsU20", pct((row.get("vsU20") or {}).get("b")), "p", (row.get("vsU20") or {}).get("p"), "vsF20", pct((row.get("vsF20") or {}).get("d")), "p", (row.get("vsF20") or {}).get("p"))
    print("등급", {k: v["grade"] for k, v in p1["grades"].items()})
    print("H2", json.dumps({s: {"n_bear": v["n_bear"], "max_gap": v["max_gap_days_all"], "span": v["max_gap_span"], "checks": v["checks"]} for s, v in p1["h2"].items()}, ensure_ascii=False, default=str))
    print("H3", json.dumps(p1["h3"], ensure_ascii=False))
    print("섹터", p2["n_sectors"], p2["events"]["crash"], p2["events"]["rebound"]["n_nonoverlap"])
    print("H4", {k: (v["grade"], pct(v["diff"]), v["p"], v["n"]) for k, v in p2["grades"].items()})
    print("best3", [(x["sector"], x["n"], pct(x["ex60"]), round(x["ra60"], 2)) for x in p2["best3"]])
    print("worst3", [(x["sector"], x["n"], pct(x["ex60"]), round(x["ra60"], 2)) for x in p2["worst3"]])
    print("rotation today", p2["committee_rotation_today"])


if __name__ == "__main__":
    main()
