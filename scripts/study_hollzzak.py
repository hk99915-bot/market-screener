#!/usr/bin/env python3
"""'홀짝홀홀' 검정 — 폭락 뒤 숏커버 반등은 한 번만 오는가 (퀀트 데스크).

사전 등록: reports/studies/hollzzak_preregistration.md (결과 계산 전 커밋 0a32f3de). 정의를 바꾸지 않는다.
  python3 scripts/study_hollzzak.py   → reports/studies/hollzzak.json (+ 표준출력 요약)
데이터: data/hist/kr_index_daily.parquet · kr_etf_daily(122630) · data/deriv/daily.csv(spot_frgn)
        · screener.prices.load_kr(hist_from=2010) · data/short_hist.parquet · data/flows/names.json
영향 범위: 연구 전용 — 워크플로·탭·알림·규칙은 이 파일을 import 하지 않는다. 롤백 = 이 파일과 hollzzak.* 삭제.
"""
from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "reports" / "studies" / "hollzzak.json"

M = 7
ALPHA = 0.05 / M
B = 10_000
SEED = 20261021
W = 5            # 첫/재 판정 창
W3 = 3           # 폭락 뒤 양봉 창
EPI_GAP = 10
SPLITS = {"design": ("2010-01-01", "2019-12-31"), "valid": ("2020-01-01", "2025-12-31"),
          "holdout": ("2026-01-01", "2026-12-31"), "pooled": ("2010-01-01", "2025-12-31")}
MIN_IDX, MIN_EPI = 10, 5
MIN_STK, MIN_STK_DATES = 30, 10
COST = 0.0005


# ---------- 통계 도구 (scipy 없음) ----------
def _lpmf_binom(k, n, p):
    return math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1) + k * math.log(p) + (n - k) * math.log1p(-p)


def binom_p(k: int, n: int, p0: float, greater: bool) -> float:
    if n == 0:
        return float("nan")
    ks = range(k, n + 1) if greater else range(0, k + 1)
    return float(min(1.0, sum(math.exp(_lpmf_binom(i, n, p0)) for i in ks)))


def fisher_less(a: int, n1: int, c: int, n2: int) -> float:
    """H: 집단1(a/n1) 비율 < 집단2(c/n2). P(X ≤ a), X~초기하(총 N, 성공 K, 뽑기 n1)."""
    N, K = n1 + n2, a + c
    if n1 == 0 or n2 == 0:
        return float("nan")
    lc = lambda n, k: math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)  # noqa: E731
    den = lc(N, n1)
    lo = max(0, n1 - (N - K))
    return float(min(1.0, sum(math.exp(lc(K, x) + lc(N - K, n1 - x) - den) for x in range(lo, a + 1))))


def cluster_boot(df: pd.DataFrame, stat, groups: list[str], seed: int = SEED, b: int = B) -> np.ndarray:
    """군집(cluster) 단위 재표집. df: [cluster, group, val]. stat(sums dict, counts dict) → 배열(b,)."""
    cl = pd.Index(df["cluster"].unique())
    C = len(cl)
    if C == 0:
        return np.array([])
    idx = cl.get_indexer(df["cluster"])
    S, Nn = {}, {}
    for g in groups:
        m = (df["group"] == g).to_numpy()
        S[g] = np.bincount(idx[m], weights=df["val"].to_numpy()[m], minlength=C)
        Nn[g] = np.bincount(idx[m], minlength=C).astype(float)
    rng = np.random.default_rng(seed)
    out = []
    for start in range(0, b, 1000):
        k = min(1000, b - start)
        Wt = rng.multinomial(C, np.full(C, 1.0 / C), size=k).astype(float)
        out.append(stat({g: Wt @ S[g] for g in groups}, {g: Wt @ Nn[g] for g in groups}))
    return np.concatenate(out)


def _ratio(s, n):
    with np.errstate(invalid="ignore", divide="ignore"):
        return s / n


def ci(a: np.ndarray) -> list:
    a = a[np.isfinite(a)]
    return [round(float(np.percentile(a, 2.5)), 5), round(float(np.percentile(a, 97.5)), 5)] if len(a) else [None, None]


def p_le0(a: np.ndarray) -> float:
    a = a[np.isfinite(a)]
    return float((a <= 0).mean()) if len(a) else float("nan")


def r4(x):
    return None if x is None or (isinstance(x, float) and not math.isfinite(x)) else round(float(x), 5)


def in_split(d: pd.Series, s: str) -> pd.Series:
    a, z = SPLITS[s]
    return (d >= pd.Timestamp(a)) & (d <= pd.Timestamp(z))


# ---------- 지수 ----------
def load_index() -> pd.DataFrame:
    ix = pd.read_parquet(ROOT / "data/hist/kr_index_daily.parquet")
    ix["date"] = pd.to_datetime(ix["date"])
    k = ix[ix.symbol == "KOSPI"].set_index("date").sort_index()
    k2 = ix[ix.symbol == "KOSPI200"].set_index("date").sort_index()
    d = pd.DataFrame({"close": k["close"].astype(float)})
    d["r"] = d["close"].pct_change()
    d["rn"] = d["r"].shift(-1)
    k2c = k2["close"].astype(float)
    d["k200_hi"] = (k2["high"].astype(float) / k2c.shift(1) - 1).reindex(d.index)
    dv = pd.read_csv(ROOT / "data/deriv/daily.csv", usecols=["date", "spot_frgn"], parse_dates=["date"]).set_index("date")
    d["frgn"] = dv["spot_frgn"].reindex(d.index)
    return d.reset_index()


def classify(d: pd.DataFrame, thr: float, w: int = W) -> pd.DataFrame:
    d = d.copy()
    c = (d["r"] <= thr).fillna(False)
    d["crash"] = c
    prior = c.shift(1, fill_value=False).astype(int).rolling(w, min_periods=1).max().astype(bool)
    reb = c & (d["rn"] > 0)
    prior_reb = reb.shift(1, fill_value=False).astype(int).rolling(w, min_periods=1).max().astype(bool)
    d["first"] = c & ~prior
    d["re"] = c & prior_reb
    d["consec"] = c & prior & ~prior_reb
    prior3 = c.shift(1, fill_value=False).astype(int).rolling(W3, min_periods=1).max().astype(bool)
    d["big_up"] = prior3 & (d["r"] >= 0.03)
    d["side_px"] = prior3 & (d["k200_hi"] >= 0.04)
    d["side_px5"] = prior3 & (d["k200_hi"] >= 0.05)
    # 에피소드: 폭락일 간격 ≤ EPI_GAP 거래일
    pos = np.where(c.to_numpy())[0]
    ep = np.full(len(d), -1)
    eid, last = -1, -10**9
    for p in pos:
        if p - last > EPI_GAP:
            eid += 1
        ep[p] = eid
        last = p
    # 비폭락일은 직전 폭락일의 에피소드(H3 사건용), 없으면 -1
    s = pd.Series(ep).replace(-1, np.nan).ffill()
    d["episode"] = s.fillna(-1).astype(int).to_numpy()
    return d


def idx_tests(d: pd.DataFrame, split: str) -> dict:
    x = d[in_split(d["date"], split) & d["rn"].notna()]
    base_up = float((x["rn"] > 0).mean())
    base_mean = float(x["rn"].mean())
    out = {"base": {"n": len(x), "up": r4(base_up), "mean": r4(base_mean)}}

    def desc(m):
        e = x[m]
        return {"n": int(len(e)), "episodes": int(e["episode"].nunique()), "up": r4((e["rn"] > 0).mean()) if len(e) else None,
                "mean": r4(e["rn"].mean()) if len(e) else None, "median": r4(e["rn"].median()) if len(e) else None,
                "worst": r4(e["rn"].min()) if len(e) else None,
                "epi_up": r4(e.groupby("episode")["rn"].apply(lambda v: (v > 0).mean()).mean()) if len(e) else None}
    for g in ("first", "re", "consec", "big_up", "side_px", "side_px5"):
        out[g] = desc(x[g])
    f, r_ = x[x["first"]], x[x["re"]]
    # H1
    k, n = int((f["rn"] > 0).sum()), len(f)
    pe = binom_p(k, n, base_up, True)
    bd = pd.DataFrame({"cluster": f["episode"], "group": "a", "val": (f["rn"] > 0).astype(float)})
    bs = cluster_boot(bd, lambda S, N: _ratio(S["a"], N["a"]) - base_up, ["a"]) if n else np.array([])
    out["H1"] = {"effect": r4(k / n - base_up) if n else None, "p_exact": r4(pe), "p_boot": r4(p_le0(bs)), "ci": ci(bs),
                 "p": r4(max(pe, p_le0(bs))) if n else None, "n": n, "episodes": int(f["episode"].nunique())}
    # H2: re < first
    a, n1, c, n2 = int((r_["rn"] > 0).sum()), len(r_), k, n
    pe = fisher_less(a, n1, c, n2)
    u = pd.concat([pd.DataFrame({"cluster": r_["episode"], "group": "re", "val": (r_["rn"] > 0).astype(float)}),
                   pd.DataFrame({"cluster": f["episode"], "group": "first", "val": (f["rn"] > 0).astype(float)})])
    bs = cluster_boot(u, lambda S, N: _ratio(S["first"], N["first"]) - _ratio(S["re"], N["re"]), ["re", "first"]) if n1 and n2 else np.array([])
    out["H2"] = {"effect": r4(a / n1 - c / n2) if n1 and n2 else None, "p_exact": r4(pe), "p_boot": r4(p_le0(bs)), "ci": ci(-bs) if len(bs) else [None, None],
                 "p": r4(max(pe, p_le0(bs))) if n1 and n2 else None, "n": n1, "n_first": n2,
                 "episodes": int(r_["episode"].nunique())}
    # H3a/H3b: mean < 0
    for h, g in (("H3a", "big_up"), ("H3b", "side_px")):
        e = x[x[g]]
        if len(e):
            bd = pd.DataFrame({"cluster": e["episode"], "group": "a", "val": e["rn"]})
            bs = cluster_boot(bd, lambda S, N: -_ratio(S["a"], N["a"]), ["a"])
            pb = p_le0(bs)
            pu = binom_p(int((e["rn"] > 0).sum()), len(e), base_up, False)
            out[h] = {"effect": r4(e["rn"].mean()), "p_boot": r4(pb), "p_up_binom": r4(pu), "ci": ci(-bs), "p": r4(pb),
                      "n": int(len(e)), "episodes": int(e["episode"].nunique()), "up": r4((e["rn"] > 0).mean())}
        else:
            out[h] = {"effect": None, "p": None, "n": 0, "episodes": 0}
    return out


def leverage(d: pd.DataFrame) -> dict:
    e = pd.read_parquet(ROOT / "data/hist/kr_etf_daily.parquet")
    e = e[e.symbol == "122630"].copy()
    e["date"] = pd.to_datetime(e["date"])
    e = e.set_index("date").sort_index()
    e["no"] = e["open"].shift(-1)
    e["nc"] = e["close"].shift(-1)
    j = d.set_index("date").join(e[["close", "no", "nc"]].rename(columns={"close": "lc"}), how="inner")
    j["ro"] = j["no"] / j["lc"] - 1 - COST
    j["rc"] = j["nc"] / j["lc"] - 1 - COST
    out = {}
    for s in ("design", "valid", "holdout", "pooled"):
        x = j[in_split(j.index.to_series(), s)]
        out[s] = {}
        for g in ("first", "re", "big_up"):
            y = x[x[g]]
            out[s][g] = {}
            for col, lab in (("ro", "next_open"), ("rc", "next_close")):
                v = y[col].dropna()
                out[s][g][lab] = {"n": int(len(v)), "win": r4((v > 0).mean()) if len(v) else None, "mean": r4(v.mean()) if len(v) else None,
                                  "median": r4(v.median()) if len(v) else None, "p05": r4(v.quantile(0.05)) if len(v) else None,
                                  "worst": r4(v.min()) if len(v) else None}
    return out


def frgn_desc(d: pd.DataFrame) -> dict:
    x = d[d["date"] <= pd.Timestamp("2026-12-31")]
    out = {}
    for g in ("first", "re"):
        y = x[x[g] & x["frgn"].notna()]
        out[g] = {"n": int(len(y)), "frgn_sell_share": r4((y["frgn"] < 0).mean()) if len(y) else None}
    return out


# ---------- 개별 종목 ----------
NAME_EX = re.compile(r"스팩|SPAC|ETN|ETF|리츠|\d호$")


def load_stocks(ix: pd.DataFrame) -> pl.DataFrame:
    from screener.prices import load_kr
    df = load_kr(hist_from=2010)
    names = json.loads((ROOT / "data/flows/names.json").read_text())
    bad = [c for c, n in names.items() if NAME_EX.search(str(n))]
    df = (df.with_columns(pl.col("yf").str.slice(0, 6).alias("code"), pl.col("yf").str.slice(7).alias("mk"))
            .filter((pl.col("code").str.slice(5, 1) == "0") & ~pl.col("code").is_in(bad) & pl.col("mk").is_in(["KS", "KQ"]))
            .sort("yf", "date"))
    df = df.with_columns(pc=pl.col("close").shift(1).over("yf"))
    df = df.with_columns(r=pl.col("close") / pl.col("pc") - 1, tv=pl.col("close") * pl.col("volume"))
    df = df.with_columns(
        sig=pl.col("r").rolling_std(60, min_samples=40).shift(1).over("yf"),
        tv20=pl.col("tv").rolling_mean(20, min_samples=15).shift(1).over("yf"),
    )
    df = df.with_columns(ok=(pl.col("pc") >= 1000) & (pl.col("tv20") >= 1e9) & (pl.col("volume") > 0)
                         & (pl.col("r").abs() <= 0.31) & pl.col("sig").is_not_null())
    df = df.with_columns(rn=pl.col("r").shift(-1).over("yf"), okn=pl.col("ok").shift(-1).over("yf"),
                         vn=pl.col("volume").shift(-1).over("yf"))
    df = df.with_columns(rn=pl.when((pl.col("rn").abs() <= 0.31) & (pl.col("vn") > 0)).then(pl.col("rn")).otherwise(None))
    # 시장 지수
    ixr = []
    for sym, mk in (("KOSPI", "KS"), ("KOSDAQ", "KQ")):
        k = ix[ix.symbol == sym].sort_values("date").copy()
        k["mr"] = k["close"].astype(float).pct_change()
        k["mrn"] = k["mr"].shift(-1)
        k["mk"] = mk
        ixr.append(k[["date", "mk", "mr", "mrn"]])
    m = pl.from_pandas(pd.concat(ixr)).with_columns(pl.col("date").cast(pl.Date))
    df = df.join(m, on=["date", "mk"], how="left").with_columns(e=pl.col("rn") - pl.col("mrn"))
    ok = pl.col("ok")
    crash = ok & (pl.col("r") <= -2.5 * pl.col("sig")) & (pl.col("r") <= -0.05)
    c10 = ok & (pl.col("r") <= -0.10)
    df = df.with_columns(crash=crash.fill_null(False), c10=c10.fill_null(False))
    for c, pre in (("crash", ""), ("c10", "t10_")):
        reb = pl.col(c) & (pl.col("rn") > 0).fill_null(False)
        df = df.with_columns(
            _pr=pl.col(c).cast(pl.Int8).shift(1).rolling_max(W, min_samples=1).over("yf").fill_null(0),
            _prb=reb.cast(pl.Int8).shift(1).rolling_max(W, min_samples=1).over("yf").fill_null(0),
            _p3=pl.col(c).cast(pl.Int8).shift(1).rolling_max(W3, min_samples=1).over("yf").fill_null(0),
        ).with_columns(**{
            pre + "first": pl.col(c) & (pl.col("_pr") == 0),
            pre + "re": pl.col(c) & (pl.col("_prb") == 1),
        })
        if c == "crash":
            df = df.with_columns(big_up=(ok & (pl.col("_p3") == 1) & (pl.col("r") >= 2 * pl.col("sig")) & (pl.col("r") >= 0.05)).fill_null(False))
    return df.drop("_pr", "_prb", "_p3")


def stk_tests(st: pl.DataFrame, split: str, variant: str = "excess") -> dict:
    a, z = SPLITS[split]
    x = st.filter((pl.col("date") >= pl.lit(a).str.to_date()) & (pl.col("date") <= pl.lit(z).str.to_date()) & pl.col("ok")
                  & pl.col("e").is_not_null())
    if variant == "ex_mkt_crash":
        x = x.filter(pl.col("mr") > -0.02)
    val = "rn" if variant == "raw" else "e"
    base_up = float((x[val] > 0).mean())
    out = {"base": {"n": x.height, "up": r4(base_up), "mean": r4(x[val].mean())}}
    pre = "t10_" if variant == "t10" else ""
    g_first, g_re = pre + "first", pre + "re"

    def ev(g):
        e = x.filter(pl.col(g)).select("date", "yf", val).to_pandas()
        e["cluster"] = e["date"]
        return e
    f, r_, bu = ev(g_first), ev(g_re), ev("big_up")
    for nm, e in (("first", f), ("re", r_), ("big_up", bu)):
        out[nm] = {"n": int(len(e)), "dates": int(e["date"].nunique()), "up": r4((e[val] > 0).mean()) if len(e) else None,
                   "mean": r4(e[val].mean()) if len(e) else None, "median": r4(e[val].median()) if len(e) else None}
    k, n = int((f[val] > 0).sum()), len(f)
    pe = binom_p(k, n, base_up, True)
    bs = cluster_boot(pd.DataFrame({"cluster": f["cluster"], "group": "a", "val": (f[val] > 0).astype(float)}),
                      lambda S, N: _ratio(S["a"], N["a"]) - base_up, ["a"]) if n else np.array([])
    out["H4a"] = {"effect": r4(k / n - base_up) if n else None, "p_exact": r4(pe), "p_boot": r4(p_le0(bs)), "ci": ci(bs),
                  "p": r4(max(pe, p_le0(bs))) if n else None, "n": n, "dates": int(f["date"].nunique())}
    a_, n1 = int((r_[val] > 0).sum()), len(r_)
    pe = fisher_less(a_, n1, k, n)
    u = pd.concat([pd.DataFrame({"cluster": r_["cluster"], "group": "re", "val": (r_[val] > 0).astype(float)}),
                   pd.DataFrame({"cluster": f["cluster"], "group": "first", "val": (f[val] > 0).astype(float)})])
    bs = cluster_boot(u, lambda S, N: _ratio(S["first"], N["first"]) - _ratio(S["re"], N["re"]), ["re", "first"]) if n1 and n else np.array([])
    out["H4b"] = {"effect": r4(a_ / n1 - k / n) if n1 and n else None, "p_exact": r4(pe), "p_boot": r4(p_le0(bs)),
                  "ci": ci(-bs) if len(bs) else [None, None], "p": r4(max(pe, p_le0(bs))) if n1 and n else None,
                  "n": n1, "dates": int(r_["date"].nunique())}
    if len(bu):
        bs = cluster_boot(pd.DataFrame({"cluster": bu["cluster"], "group": "a", "val": bu[val]}), lambda S, N: -_ratio(S["a"], N["a"]), ["a"])
        out["H4c"] = {"effect": r4(bu[val].mean()), "p_boot": r4(p_le0(bs)), "ci": ci(-bs), "p": r4(p_le0(bs)),
                      "n": int(len(bu)), "dates": int(bu["date"].nunique()), "up": r4((bu[val] > 0).mean())}
    else:
        out["H4c"] = {"effect": None, "p": None, "n": 0, "dates": 0}
    return out


def short_explore(st: pl.DataFrame, ix: pd.DataFrame) -> dict:
    sh = pl.read_parquet(ROOT / "data/short_hist.parquet").with_columns(
        pl.col("date").cast(pl.Utf8).str.to_date("%Y%m%d"))
    dates = sorted(sh["date"].unique().to_list())
    agg = sh.group_by("date").agg(vol_ratio_mean=pl.col("vol_ratio").mean(), bal_ratio_mean=pl.col("bal_ratio").mean()).sort("date")
    k = ix[ix.symbol == "KOSPI"].sort_values("date").copy()
    k["r"] = k["close"].astype(float).pct_change()
    k["date"] = pd.to_datetime(k["date"]).dt.date
    kr = dict(zip(k["date"], k["r"]))
    rows = [{"date": str(d), "kospi_r": r4(kr.get(d)), "vol_ratio_mean": r4(v), "bal_ratio_mean": r4(b)}
            for d, v, b in agg.iter_rows()]
    crash_days = [r["date"] for r in rows if r["kospi_r"] is not None and r["kospi_r"] <= -0.03]
    ev = (st.with_columns(code=pl.col("yf").str.slice(0, 6)).filter(pl.col("crash") & pl.col("e").is_not_null())
            .join(sh.select("date", "code", "vol_ratio"), on=["date", "code"], how="inner").to_pandas())
    ex = {"n": int(len(ev)), "dates": int(ev["date"].nunique()) if len(ev) else 0}
    if len(ev) >= 15:
        q1, q2 = ev["vol_ratio"].quantile([1 / 3, 2 / 3])
        for lab, m in (("low", ev["vol_ratio"] <= q1), ("high", ev["vol_ratio"] >= q2)):
            y = ev[m]
            ex[lab] = {"n": int(len(y)), "up": r4((y["e"] > 0).mean()), "mean_e": r4(y["e"].mean())}
        ex["cut"] = [r4(q1), r4(q2)]
    return {"window": [str(dates[0]), str(dates[-1])], "days": len(dates), "kospi_crash_days": crash_days,
            "daily": rows, "stock_explore": ex}


# ---------- 판정 ----------
def grade(h: str, res: dict, min_ok) -> dict:
    d, v, p, ho = (res[s].get(h, {}) for s in ("design", "valid", "pooled", "holdout"))
    def dirn(x):  # 가설 방향 부호: H1/H4a effect>0, H2/H4b effect<0, H3/H4c effect<0
        if x.get("effect") is None:
            return 0
        e = x["effect"]
        return int(np.sign(e if h in ("H1", "H4a") else -e))
    okd, okv, okp = min_ok(d), min_ok(v), min_ok(p)
    pd_, pv_, pp_ = d.get("p"), v.get("p"), p.get("p")
    if okd and okv and pd_ is not None and pd_ < ALPHA and dirn(v) > 0 and pv_ is not None and pv_ < 0.05:
        g, verdict = "A", "통과"
    elif okd and okv and dirn(d) * dirn(v) < 0:
        g, verdict = "F", "기각"
    elif not okp:
        g, verdict = "검증전", "보류"
    elif pp_ is not None and pp_ >= 0.10:
        g, verdict = "F", "기각"
    elif dirn(d) >= 0 and dirn(v) >= 0 and pp_ is not None and pp_ < ALPHA and okd and okv:
        g, verdict = "B", "보류"
    elif pp_ is not None and pp_ < 0.10:
        g, verdict = "C", "보류"
    else:
        g, verdict = "F", "기각"
    if not (okd and okv) and g in ("A", "B"):
        g = "C"
    # 역방향 표기: 풀링 효과가 반대이고 반대쪽 단측 p<0.10 (부트스트랩 CI로 근사: 1-p)
    rev = bool(p.get("effect") is not None and dirn(p) < 0 and pp_ is not None and pp_ > 0.90)
    hold = "같은 방향" if dirn(ho) > 0 else ("반대" if dirn(ho) < 0 else "사건 없음")
    return {"grade": g + ("(역방향 C)" if rev else ""), "verdict": verdict, "split_ok": {"design": okd, "valid": okv, "pooled": okp},
            "holdout": hold}


def holm(ps: dict) -> dict:
    items = sorted((v, k) for k, v in ps.items() if v is not None)
    m, out, stop = len(items), {}, False
    for i, (p, k) in enumerate(items):
        thr = 0.05 / (m - i)
        ok = (not stop) and p < thr
        stop = stop or not ok
        out[k] = ok
    return out


def main():
    ix = pd.read_parquet(ROOT / "data/hist/kr_index_daily.parquet")
    ix["date"] = pd.to_datetime(ix["date"])
    d0 = load_index()
    res: dict = {"index": {}, "index_-5%": {}, "index_w10": {}, "stock": {}, "stock_raw": {}, "stock_ex_mkt": {}, "stock_t10": {}}
    d3 = classify(d0, -0.03)
    for s in SPLITS:
        res["index"][s] = idx_tests(d3, s)
        res["index_-5%"][s] = idx_tests(classify(d0, -0.05), s)
        res["index_w10"][s] = idx_tests(classify(d0, -0.03, 10), s)
    st = load_stocks(ix)
    for s in SPLITS:
        res["stock"][s] = stk_tests(st, s)
        res["stock_raw"][s] = stk_tests(st, s, "raw")
        res["stock_ex_mkt"][s] = stk_tests(st, s, "ex_mkt_crash")
        res["stock_t10"][s] = stk_tests(st, s, "t10")
    mi = lambda x: x.get("n", 0) >= MIN_IDX and x.get("episodes", 0) >= MIN_EPI  # noqa: E731
    ms = lambda x: x.get("n", 0) >= MIN_STK and x.get("dates", 0) >= MIN_STK_DATES  # noqa: E731
    verdicts = {h: grade(h, res["index"], mi) for h in ("H1", "H2", "H3a", "H3b")}
    verdicts.update({h: grade(h, res["stock"], ms) for h in ("H4a", "H4b", "H4c")})
    # Holm 은 설계 구간 최소 표본을 채운 가설만 (미달 가설의 p 는 등급에 쓰지 않음)
    pdes = {h: ((res["index"] if h[1] != "4" else res["stock"])["design"][h].get("p") if verdicts[h]["split_ok"]["design"] else None)
            for h in verdicts}
    out = {
        "study": "hollzzak", "asof": "2026-10-16 (지수·ETF) / 2026-10-20 (종목)", "prereg": "reports/studies/hollzzak_preregistration.md @ 0a32f3de",
        "m": M, "alpha_bonf": round(ALPHA, 5), "B": B, "seed": SEED, "splits": SPLITS,
        "params": {"crash": -0.03, "window": W, "post_window": W3, "big_up": 0.03, "sidecar_proxy": "K200 high/prev close >= +4% (대용)",
                   "stock_crash": "r<=-2.5σ60 & r<=-5%", "stock_big_up": "r>=+2σ60 & r>=+5%", "liq": "tv20>=1e9 KRW, prev close>=1000",
                   "cost_lev": COST, "episode_gap": EPI_GAP},
        "verdicts": verdicts, "grades": {h: v["grade"] for h, v in verdicts.items()}, "holm_design": holm(pdes), "results": res,
        "leverage_122630": leverage(d3), "frgn_on_crash": frgn_desc(d3), "short_mech": short_explore(st, ix),
        "sidecar_data": {"actual_history": "없음 — reports/events.json 은 2026-10 뉴스 16건뿐, KRX data/kind 는 이 환경 프록시 403",
                         "proxy": "K200 현물 장중고가 +4% (+5% 병기)",
                         "how_to_get": "KRX KIND 시장조치 공시('프로그램매매호가 효력정지') 검색 또는 KRX 정보데이터시스템 시장조치 통계 — GitHub Actions(네트워크 허용) 수집 스크립트 필요"},
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    for h, v in verdicts.items():
        src = res["index"] if h[1] != "4" else res["stock"]
        print(h, v, {s: (src[s][h].get("n"), src[s][h].get("effect"), src[s][h].get("p")) for s in SPLITS})


if __name__ == "__main__":
    main()
