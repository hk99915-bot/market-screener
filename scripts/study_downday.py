#!/usr/bin/env python3
"""하락일 대응 H4(매도 타이밍)·H1(S&P 급락 다음 날 360750 대리) — 사전등록 docs/desk_kb/rounds/2026-11-05/prereg_downday.md (커밋 a48b31b15).

  python3 scripts/study_downday.py            # 야후 캐시(data/study/downday_px.csv) 없으면 받아서 → reports/studies/2026-11-05_downday.json
  python3 scripts/study_downday.py --refetch

정의는 결과를 본 뒤 바꾸지 않는다. 영향 범위: 연구 산출물만. 롤백: json·csv 삭제.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from study_crash_close_intraday import sps  # noqa: E402  (scipy 대체 t 분포)

HIST = ROOT / "data" / "hist"
DERIV = ROOT / "data" / "deriv" / "daily.csv"
PX = ROOT / "data" / "study" / "downday_px.csv"
OUT = ROOT / "reports" / "studies" / "2026-11-05_downday.json"
IS_END = "2021-12-31"
ALPHA_H4, ALPHA_H1 = 0.05 / 3, 0.05 / 6
M_H4, M_H1 = 3, 6
EXPLORE_H4, EXPLORE_H1 = 33, 3
HOLD = 10          # 2주 = 10거래일
REB = 0.005
LOOK = 120
COOL = 20
TOPN = 200
US_COST = 0.002


# ---------- 통계 ----------
def t1(xs):
    a = np.asarray([x for x in xs if x == x], float)
    n = len(a)
    if n < 2:
        return {"n": n}
    mu, sd = a.mean(), a.std(ddof=1)
    t = mu / (sd / math.sqrt(n)) if sd > 0 else 0.0
    return {"n": n, "mean": round(float(mu), 5), "median": round(float(np.median(a)), 5), "win": round(float((a > 0).mean()), 3),
            "worst": round(float(a.min()), 5), "t": round(float(t), 2), "p_gt": round(float(sps.t.sf(t, n - 1)), 4),
            "p_lt": round(float(sps.t.cdf(t, n - 1)), 4)}


def grade(allr, isr, oosr, alpha, minn=8):
    """사전등록 §0 등급. allr/isr/oosr = t1 dict(군집 단위)."""
    if allr.get("n", 0) < minn:
        return "검증전"
    m, p = allr["mean"], allr["p_gt"]
    if p < alpha and m > 0:
        ok = all(x.get("n", 0) >= 2 and x["mean"] > 0 and x["p_gt"] < 0.10 for x in (isr, oosr))
        return "A" if ok else "B"
    if m > 0 and p < 0.10:
        return "C"
    if m < 0 and allr["p_lt"] < 0.10:
        return "C(역방향)"
    return "F"


def bh(ps, q=0.10):
    """BH 통과 여부 리스트(입력 순서)."""
    idx = sorted(range(len(ps)), key=lambda i: ps[i])
    m = len(ps)
    k = 0
    for r, i in enumerate(idx, 1):
        if ps[i] <= q * r / m:
            k = r
    ok = [False] * m
    for r, i in enumerate(idx, 1):
        if r <= k:
            ok[i] = True
    return ok


# ---------- H4 ----------
def load_kospi():
    d = pd.read_csv(DERIV, usecols=["date", "kospi_close"]).dropna()
    d["date"] = pd.to_datetime(d["date"])
    d = d.set_index("date")["kospi_close"].sort_index()
    return d


def load_kr_panel():
    cl, vo = [], []
    for y in range(2010, 2026):
        f = HIST / f"kr_{y}.parquet"
        if not f.exists():
            continue
        df = pd.read_parquet(f, columns=["yf", "date", "close", "volume"])
        df["date"] = pd.to_datetime(df["date"])
        cl.append(df.pivot_table(index="date", columns="yf", values="close", aggfunc="last"))
        vo.append(df.pivot_table(index="date", columns="yf", values="volume", aggfunc="last"))
    C = pd.concat(cl).sort_index()
    V = pd.concat(vo).sort_index()
    C = C[~C.index.duplicated(keep="last")]
    V = V[~V.index.duplicated(keep="last")]
    return C, V


def h4_events(C, V, K, dd=0.20, dday=-0.02, reb=REB, need_dday=True):
    """이벤트별 (date, code, A, B, Cx, wait, same). 체결가 비율 = 가격/t 종가."""
    kr = K.reindex(C.index).pct_change()
    cal = C.index
    pos = {d: i for i, d in enumerate(cal)}
    val = (C * V).rolling(60, min_periods=40).mean().shift(1)
    hi = C.rolling(LOOK, min_periods=LOOK).max()
    below = (C <= (1 - dd) * hi)
    # 직전 COOL 거래일 안에 below 없음
    prior = below.shift(1).rolling(COOL, min_periods=1).max().fillna(0).astype(bool)
    ev = below & ~prior
    kr_arr = kr.values
    rows = []
    cvals = C.values
    for i, d in enumerate(cal):
        if i < LOOK or i + HOLD >= len(cal):
            continue
        if need_dday and not (kr_arr[i] <= dday):
            continue
        cand = ev.iloc[i]
        cand = cand[cand].index
        if len(cand) == 0:
            continue
        top = val.iloc[i].dropna().nlargest(TOPN).index.intersection(cand)
        # 반등일 위치
        s_idx = None
        for j in range(i + 1, i + HOLD + 1):
            if kr_arr[j] >= reb:
                s_idx = j
                break
        for code in top:
            c = C[code].values
            w = c[i:i + HOLD + 1]
            if np.isnan(w).any() or (np.abs(np.diff(w) / w[:-1]) > 0.40).any():
                continue
            a = 1.0
            cx = c[i + HOLD] / c[i]
            b = c[s_idx] / c[i] if s_idx else cx
            rows.append({"date": d, "code": code, "A": a, "B": b, "C": cx,
                         "wait": (s_idx - i) if s_idx else HOLD, "same": s_idx is None})
    return pd.DataFrame(rows)


def h4_stats(ev: pd.DataFrame):
    if ev.empty:
        return {"events": 0}
    ev = ev.copy()
    ev["BA"] = ev["B"] - ev["A"]
    ev["CA"] = ev["C"] - ev["A"]
    ev["BC"] = ev["B"] - ev["C"]
    ev["ym"] = ev["date"].dt.to_period("M")
    out = {"events": int(len(ev)), "dates": int(ev["date"].nunique()), "months": int(ev["ym"].nunique()),
           "B_same_as_C": round(float(ev["same"].mean()), 3), "wait_mean": round(float(ev["wait"].mean()), 2),
           "mean_ratio": {k: round(float(ev[k].mean() - 1), 5) for k in ("A", "B", "C")},
           "median_ratio": {k: round(float(ev[k].median() - 1), 5) for k in ("A", "B", "C")}}
    for k in ("BA", "CA", "BC"):
        g = ev.groupby("ym")[k].mean()
        gi = g[g.index <= pd.Period(IS_END, "M")]
        go = g[g.index > pd.Period(IS_END, "M")]
        res = {"all": t1(g.values), "IS": t1(gi.values), "OOS": t1(go.values)}
        # 국면 제외 (OOS): 2022, 2025-04 제외
        ex = g[~g.index.map(lambda p: p.year == 2022)]
        res["ex2022"] = t1(ex.values)
        res["event_level_mean"] = round(float(ev[k].mean()), 5)
        out[k] = res
    return out


def run_h4():
    K = load_kospi()
    C, V = load_kr_panel()
    res = {"registered": {}, "explore": {}}
    base = h4_events(C, V, K)
    st = h4_stats(base)
    names = {"BA": "H4a", "CA": "H4b", "BC": "H4c"}
    ps = [st[k]["all"]["p_gt"] for k in ("BA", "CA", "BC")]
    bhok = bh(ps)
    for n, k in enumerate(("BA", "CA", "BC")):
        r = st[k]
        r["grade"] = grade(r["all"], r["IS"], r["OOS"], ALPHA_H4)
        r["bonferroni_pass"] = bool(r["all"].get("p_gt", 1) < ALPHA_H4)
        r["bh_pass"] = bhok[n]
        res["registered"][names[k]] = r
    res["registered"]["meta"] = {k: st[k] for k in ("events", "dates", "months", "B_same_as_C", "wait_mean", "mean_ratio", "median_ratio")}
    # 탐색
    cells = {}
    for dd in (0.15, 0.20, 0.25):
        for dday in (-0.015, -0.02, -0.03):
            if dd == 0.20 and dday == -0.02:
                continue
            s = h4_stats(h4_events(C, V, K, dd=dd, dday=dday))
            cells[f"dd{int(dd*100)}_day{dday*100:g}"] = s
    cells["reb1.0"] = h4_stats(h4_events(C, V, K, reb=0.01))
    cells["no_dday_cond"] = h4_stats(h4_events(C, V, K, need_dday=False))
    res["explore"] = cells
    res["explore_index"] = h4_index(K)
    return res


def h4_index(K, dd=0.10, dday=-0.02):
    """코스피 지수 자체: 120일 고점 −10% 첫 진입 + 그날 −2% → 세 안(서술)."""
    s = K.copy()
    r = s.pct_change()
    hi = s.rolling(LOOK).max()
    below = s <= (1 - dd) * hi
    prior = below.shift(1).rolling(COOL, min_periods=1).max().fillna(0).astype(bool)
    ev = below & ~prior & (r <= dday)
    cal = s.index
    rows = []
    for d in cal[ev.values]:
        i = cal.get_loc(d)
        if i + HOLD >= len(cal):
            continue
        j = next((j for j in range(i + 1, i + HOLD + 1) if r.iloc[j] >= REB), None)
        c = s.values
        rows.append({"date": str(d.date()), "A": 0.0, "B": float(c[j] / c[i] - 1) if j else float(c[i + HOLD] / c[i] - 1), "C": float(c[i + HOLD] / c[i] - 1)})
    df = pd.DataFrame(rows)
    if df.empty:
        return {"n": 0}
    return {"n": int(len(df)), "mean_B_minus_A": round(float(df["B"].mean()), 5), "mean_C_minus_A": round(float(df["C"].mean()), 5),
            "mean_B_minus_C": round(float((df["B"] - df["C"]).mean()), 5), "dates": list(df["date"])}


# ---------- H1 ----------
def fetch_px(refetch=False):
    import urllib.request
    if PX.exists() and not refetch:
        return pd.read_csv(PX, parse_dates=["date"]).set_index("date")
    out = {}
    for sym, col in (("^GSPC", "spx"), ("KRW=X", "fx")):
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym.replace('^', '%5E').replace('=', '%3D')}?period1=946684800&period2=1793900000&interval=1d"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        j = json.loads(urllib.request.urlopen(req, timeout=60).read())["chart"]["result"][0]
        ts = j["timestamp"]
        cl = j["indicators"]["quote"][0]["close"]
        # 마지막 봉이 장중(미확정)일 수 있어 당일 값은 쓰지 않는다: 직전 종가는 rows[-2] 규약 → 마지막 행 제거
        s = pd.Series(cl, index=pd.to_datetime(ts, unit="s").normalize(), dtype=float).dropna()
        s = s[~s.index.duplicated(keep="last")]
        out[col] = s.iloc[:-1]
    df = pd.DataFrame(out).sort_index()
    df.index.name = "date"
    PX.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(PX)
    return df


def h1_events(df, th, gap=20):
    d = df.dropna(subset=["spx"]).copy()
    d = d[d.index >= "2010-01-01"]
    d["fx"] = d["fx"].ffill()
    r = d["spx"].pct_change()
    idx = np.where(r.values <= th)[0]
    keep, last = [], -999
    for i in idx:
        if i - last > gap:
            keep.append(i)
        last = i
    return d, r, keep


def krw_ret(d, i, h):
    if i + h >= len(d):
        return float("nan")
    return (d["spx"].iloc[i + h] / d["spx"].iloc[i]) * (d["fx"].iloc[i + h] / d["fx"].iloc[i]) - 1


def run_h1(df, ths=(-0.02, -0.03), hs=(5, 10, 20), explore=False):
    d = df.dropna(subset=["spx"])
    d = d[d.index >= "2010-01-01"].copy()
    d["fx"] = d["fx"].ffill()
    dates = d.index
    out = {}
    for th in ths:
        _, r, keep = h1_events(df, th)
        for h in hs:
            base_all = np.array([krw_ret(d, i, h) for i in range(len(d))])
            base_all_s = pd.Series(base_all, index=dates)
            ev = [(dates[i], krw_ret(d, i, h), krw_ret_local(d, i, h)) for i in keep]
            ev = [e for e in ev if e[1] == e[1]]
            bis = float(base_all_s[dates <= IS_END].mean())
            boo = float(base_all_s[dates > IS_END].mean())
            exc = [(dt, x - (bis if str(dt.date()) <= IS_END else boo), x, loc) for dt, x, loc in ev]
            a = t1([e[1] for e in exc])
            isr = t1([e[1] for e in exc if str(e[0].date()) <= IS_END])
            oor = t1([e[1] for e in exc if str(e[0].date()) > IS_END])
            net = t1([e[2] - US_COST for e in exc])
            res = {"th": th, "h": h, "events": len(exc), "excess_all": a, "excess_IS": isr, "excess_OOS": oor,
                   "vs_inaction_net_cost": net, "baseline_mean_IS": round(bis, 5), "baseline_mean_OOS": round(boo, 5),
                   "local_only_mean": round(float(np.mean([e[3] for e in exc])), 5) if exc else None,
                   "ex2020_2022_excess": t1([e[1] for e in exc if e[0].year not in (2020, 2022)]),
                   "event_dates": [str(e[0].date()) for e in exc]}
            if not explore:
                res["grade"] = grade(a, isr, oor, ALPHA_H1, minn=8)
                if res["grade"] in ("A",) and oor.get("n", 0) < 8:
                    res["grade"] = "B"
                res["bonferroni_pass"] = bool(a.get("p_gt", 1) < ALPHA_H1)
            else:
                g = grade(a, isr, oor, ALPHA_H1)
                res["grade"] = g if g in ("검증전", "F", "C", "C(역방향)") else "C"
            out[f"{int(th*1000)/10:g}%_h{h}"] = res
    if not explore:
        keys = list(out)
        ok = bh([out[k]["excess_all"].get("p_gt", 1) for k in keys])
        for k, o in zip(keys, ok):
            out[k]["bh_pass"] = o
    return out


def krw_ret_local(d, i, h):
    if i + h >= len(d):
        return float("nan")
    return d["spx"].iloc[i + h] / d["spx"].iloc[i] - 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refetch", action="store_true")
    ap.add_argument("--skip4", action="store_true")
    a = ap.parse_args()
    px = fetch_px(a.refetch)
    res = {"generated": "2026-11-05", "prereg": {"file": "docs/desk_kb/rounds/2026-11-05/prereg_downday.md", "commit": "a48b31b15",
                                                  "m": M_H4 + M_H1, "m_h4": M_H4, "m_h1": M_H1, "explore_h4": EXPLORE_H4, "explore_h1": EXPLORE_H1,
                                                  "alpha_h4": ALPHA_H4, "alpha_h1": ALPHA_H1, "topic": "downday_response"},
           "data_end": {"spx": str(px["spx"].dropna().index[-1].date()), "fx": str(px["fx"].dropna().index[-1].date())}}
    res["H1"] = run_h1(px)
    res["H1_explore"] = run_h1(px, ths=(-0.015,), explore=True)
    if not a.skip4:
        res["H4"] = run_h4()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
