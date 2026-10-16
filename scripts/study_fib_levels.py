"""하방 피보나치 지지 효과 검증 — reports/studies/fib_levels.md §0 사전 등록 그대로.

python scripts/study_fib_levels.py  → reports/studies/fib_levels.json (+ 표준출력 요약)
데이터: data/hist/kr_*.parquet (상폐 포함) + data/kr_prices.parquet, 레짐은 코스피(프록시+실제 스플라이스).
레벨은 apps-script/Index.html fibDown 과 같은 로직을 사건일 전날까지의 120봉으로 계산(미래참조 없음).
"""
from __future__ import annotations

import glob
import json
import math
import sys
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
OUT = ROOT / "reports" / "studies" / "fib_levels.json"
RATIOS = np.array([0.236, 0.382, 0.5, 0.618, 0.786, 1.0, 1.272, 1.618])
W, TOPN, BAND, DEDUP, FWD = 120, 150, 0.005, 10, 12
START, IS_END = pd.Timestamp("2019-01-02"), pd.Timestamp("2023-12-31")
M = 4
ALPHA_B = 0.05 / M
SEED = 20261016
N = NormalDist()


def load() -> pd.DataFrame:
    fs = [f for f in sorted(glob.glob(str(ROOT / "data/hist/kr_[0-9]*.parquet"))) if int(f[-12:-8]) >= 2017]
    h = pd.concat([pd.read_parquet(f) for f in fs], ignore_index=True)
    k = pd.read_parquet(ROOT / "data/kr_prices.parquet")
    for x in (h, k):
        x["date"] = pd.to_datetime(x["date"])
    d = pd.concat([h[h["date"] < k["date"].min()], k], ignore_index=True)
    d = d[(d["close"] > 0) & d["yf"].str.endswith((".KS", ".KQ"))].drop_duplicates(["yf", "date"], keep="last")
    d = d.sort_values(["yf", "date"]).reset_index(drop=True)
    o = d["open"].where(d["open"] > 0, d["close"])
    d["low"] = d["low"].where(d["low"] > 0, np.minimum(o, d["close"]))
    d["high"] = d["high"].where(d["high"] > 0, np.maximum(o, d["close"]))
    g = d.groupby("yf", sort=False)
    r = d["close"] / g["close"].shift(1) - 1
    lim = np.where(d["date"] >= pd.Timestamp("2015-06-15"), 0.31, 0.16)
    d["bad"] = (r.abs() > lim).astype(np.int32)
    tv = d["close"] * d["volume"].fillna(0)
    d["tv60"] = tv.groupby(d["yf"]).transform(lambda s: s.rolling(60, min_periods=40).mean().shift(1))
    d["rk"] = d.groupby("date")["tv60"].rank(ascending=False, method="first")
    return d


def regime() -> pd.Series:
    """코스피 200일선 아래 여부(전날 종가 기준) — 프록시(~2024-09-18) + 실제 코스피 스플라이스."""
    from study_playbook_signals import REAL_FROM, build_proxy, load_real
    px, real = build_proxy()["close"], load_real()["close"]
    s0 = pd.Timestamp(REAL_FROM)
    k = px[px.index <= s0].iloc[-1] / real[real.index >= s0].iloc[0]
    s = pd.concat([px[px.index < s0], real[real.index >= s0] * k]).sort_index()
    return (s < s.rolling(200).mean()).shift(1).rename("bear")


def fib_window(lo: np.ndarray, hi: np.ndarray):
    il = int(np.argmin(lo))
    L = lo[il]
    H = hi[il + 1:].max() if il + 1 < len(hi) else -np.inf
    if not H > L:
        H = hi[:il].max() if il > 0 else -np.inf
    return (L, H) if H > L else None


def pick3(H, R, ratios, c):
    v = H - R * ratios
    ok = (v < c) & (v > 0)
    idx = np.where(ok)[0]
    idx = idx[np.argsort(-v[idx])][:3]
    return v[idx], ratios[idx]


def scan(d: pd.DataFrame) -> pd.DataFrame:
    rng = np.random.default_rng(SEED)
    fibs = RATIOS
    rows = []
    last_date = d["date"].max()
    for yf, g in d.groupby("yf", sort=False):
        if len(g) < W + FWD + 2:
            continue
        dt = g["date"].to_numpy()
        lo, hi, cl = g["low"].to_numpy(), g["high"].to_numpy(), g["close"].to_numpy()
        cb = np.concatenate([[0], np.cumsum(g["bad"].to_numpy())])
        inu = (g["rk"].to_numpy() <= TOPN)
        last = {"fib": -10**9, "ctl": -10**9}
        for i in range(W, len(g) - FWD):
            if not inu[i] or dt[i] < START:
                continue
            if cb[i + FWD + 1] - cb[i - W + 1] > 0:      # 레벨 창·사후 창에 분할/권리락 의심
                continue
            fw = fib_window(lo[i - W:i], hi[i - W:i])
            if fw is None:
                continue
            L, H = fw
            R, c = H - L, cl[i - 1]
            u = rng.uniform(0.1, 1.7, 40)
            u = u[np.min(np.abs(u[:, None] - fibs[None, :]), axis=1) > 0.03][:8]
            for grp, rr in (("fib", fibs), ("ctl", u)):
                if i - last[grp] <= DEDUP:
                    continue
                lv, rs = pick3(H, R, rr, c)
                hit = (c > lv * (1 + BAND)) & (lo[i] <= lv * (1 + BAND)) & (hi[i] >= lv * (1 - BAND))
                if not hit.any():
                    continue
                j = int(np.argmax(hit))
                v = lv[j]
                last[grp] = i
                brk = cl[i] < v * (1 - BAND) and cl[i + 1] < v * (1 - BAND)
                rows.append((yf, dt[i], grp, float(rs[j]), cl[i + 5] / cl[i] - 1,
                             cl[i + 10] / cl[i] - 1, cl[i + 5] > v, cl[i + 10] > v, brk,
                             cl[i + 11] / cl[i + 1] - 1 if brk else np.nan))
    ev = pd.DataFrame(rows, columns=["yf", "date", "grp", "ratio", "r5", "r10", "up5", "up10", "brk", "rb10"])
    return ev[ev["date"] <= last_date]


def mtest(a: pd.DataFrame, b: pd.DataFrame, col: str, direction: int) -> dict:
    a, b = a[a[col].notna()], b[b[col].notna()]
    ma = a.groupby(a["date"].dt.to_period("M"))[col].agg(["mean", "size"])
    mb = b.groupby(b["date"].dt.to_period("M"))[col].agg(["mean", "size"])
    j = ma.join(mb, lsuffix="_a", rsuffix="_b", how="inner")
    j = j[(j["size_a"] >= 3) & (j["size_b"] >= 3)]
    dd = (j["mean_a"] - j["mean_b"]).to_numpy()
    k = len(dd)
    t = dd.mean() / (dd.std(ddof=1) / math.sqrt(k)) if k >= 3 and dd.std(ddof=1) > 0 else float("nan")
    p = 1 - N.cdf(t * direction) if np.isfinite(t) else float("nan")
    # 참고: 사건 단위 Welch
    x, y = a[col].to_numpy(), b[col].to_numpy()
    ew = (x.mean() - y.mean()) / math.sqrt(x.var(ddof=1) / len(x) + y.var(ddof=1) / len(y)) if len(x) > 2 and len(y) > 2 else float("nan")
    return {"n_a": int(len(a)), "n_b": int(len(b)), "mean_a": round(float(a[col].mean()), 5), "mean_b": round(float(b[col].mean()), 5),
            "diff": round(float(a[col].mean() - b[col].mean()), 5), "months": k,
            "mdiff": round(float(dd.mean()), 5) if k else None, "t": round(float(t), 2) if np.isfinite(t) else None,
            "p": round(float(p), 4) if np.isfinite(p) else None, "event_welch_t": round(float(ew), 2) if np.isfinite(ew) else None}


def grade(is_, oos, full, direction) -> str:
    if is_["n_a"] < 300 or is_["months"] < 24:
        return "검증전"
    same = lambda r: r["mdiff"] is not None and r["mdiff"] * direction > 0
    if is_["p"] is not None and is_["p"] < ALPHA_B and same(is_):
        return "A" if (oos["p"] is not None and oos["p"] < 0.05 and same(oos)) else "B"
    if full["p"] is not None and full["p"] < 0.10 and same(full):
        return "C"
    return "F"


HYP = {  # id: (처리군 필터, 대조군 필터, 열, 방향)
    "H1a_FIB_TOUCH_5": (lambda e: e[e.grp == "fib"], lambda e: e[e.grp == "ctl"], "r5", +1),
    "H1b_FIB_TOUCH_10": (lambda e: e[e.grp == "fib"], lambda e: e[e.grp == "ctl"], "r10", +1),
    "H2_FIB_BREAK_10": (lambda e: e[(e.grp == "fib") & e.brk], lambda e: e[(e.grp == "ctl") & e.brk], "rb10", -1),
    "H3_FIB_GOLDEN_10": (lambda e: e[(e.grp == "fib") & e.ratio.isin([0.618, 1.0])],
                         lambda e: e[(e.grp == "fib") & ~e.ratio.isin([0.618, 1.0])], "r10", +1),
}


def main():
    d = load()
    ev = scan(d)
    bear = regime()
    ev["bear"] = ev["date"].map(bear).fillna(False).astype(bool)
    parts = {"IS": ev[ev.date <= IS_END], "OOS": ev[ev.date > IS_END], "ALL": ev}
    res = {}
    for hid, (fa, fb, col, dr) in HYP.items():
        r = {k: mtest(fa(x), fb(x), col, dr) for k, x in parts.items()}
        r["bear_ALL"] = mtest(fa(ev[ev.bear]), fb(ev[ev.bear]), col, dr)
        r["bull_ALL"] = mtest(fa(ev[~ev.bear]), fb(ev[~ev.bear]), col, dr)
        r["grade"] = grade(r["IS"], r["OOS"], r["ALL"], dr)
        res[hid] = r
    f = ev[ev.grp == "fib"]
    by_ratio = (f.groupby("ratio").agg(n=("r10", "size"), r5=("r5", "mean"), r10=("r10", "mean"), up5=("up5", "mean"), up10=("up10", "mean"))
                .round(4).reset_index().to_dict("records"))
    desc = {g: {"n": int(len(x)), "r5": round(float(x.r5.mean()), 4), "r10": round(float(x.r10.mean()), 4),
                "bounce5": round(float(x.up5.mean()), 3), "bounce10": round(float(x.up10.mean()), 3),
                "break_rate": round(float(x.brk.mean()), 3)} for g, x in ev.groupby("grp")}
    lens = max((res["H1a_FIB_TOUCH_5"]["grade"], res["H1b_FIB_TOUCH_10"]["grade"]), key=lambda g: -["A", "B", "C", "F", "검증전"].index(g))
    out = {"asof": str(d["date"].max().date()), "period": [str(ev.date.min().date()), str(ev.date.max().date())],
           "universe": f"일별 전일 60일 평균 거래대금 상위 {TOPN} (.KS+.KQ)", "m": M, "alpha_bonferroni": ALPHA_B,
           "bear_share": round(float(ev.bear.mean()), 3), "desc": desc, "by_ratio": by_ratio, "tests": res, "lens_grade": lens}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: {kk: (v[kk] if kk == "grade" else {x: v[kk][x] for x in ("n_a", "n_b", "mdiff", "t", "p", "months")})
                          for kk in ("IS", "OOS", "ALL", "bear_ALL", "bull_ALL", "grade")} for k, v in res.items()}, ensure_ascii=False, indent=1))
    print("desc", desc)
    print("by_ratio", by_ratio)
    print("lens_grade", lens)


if __name__ == "__main__":
    main()
