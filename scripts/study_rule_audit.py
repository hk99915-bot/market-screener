"""'비싼 대기·확인 조건' 전수 점검 — reports/studies/rule_audit.md §0 사전 등록 그대로.

python scripts/study_rule_audit.py  → reports/studies/rule_audit.json (+ 표준출력 요약)
데이터: data/deriv/daily.csv (코스피 2010~), data/hist + data/kr_prices.parquet (종목, 상폐 포함, screener.lab.load_kr)
T1 손절 폭 · T2 트레일 기준선 · T3 부분익절 · T4 반등일 매도 대기 · T5 하락장 노출 상한 · T6 추격 절반 사이징
"""
from __future__ import annotations

import json
import math
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from screener.lab import load_kr, BAD, MIN_TV  # noqa: E402
from study_entry_signals import t_cdf  # noqa: E402

CSV = ROOT / "data" / "deriv" / "daily.csv"
OUT = ROOT / "reports" / "studies" / "rule_audit.json"

COST = 0.0025          # 왕복
IS_END = "2018-12-31"
M = 18
ALPHA = 0.05 / M
TOPN = 100
MIN_PX = 1000
HOLD = 60              # T1~T3 최대 보유 / 코호트 간격
GAP6 = 20              # T6 보유·코호트 간격


# ───────────────────────── 통계 ─────────────────────────
def ttest(d) -> dict:
    d = np.asarray([x for x in d if x is not None and np.isfinite(x)], float)
    n = len(d)
    if n < 3:
        return {"n": n, "mean": float(d.mean()) if n else None, "t": None, "p": None}
    sd = d.std(ddof=1)
    t = d.mean() / (sd / math.sqrt(n)) if sd > 0 else float("nan")
    p = 2 * (1 - t_cdf(abs(t), n - 1)) if np.isfinite(t) else None
    return {"n": n, "mean": float(d.mean()), "t": float(t), "p": float(p) if p is not None else None}


def compare(d: np.ndarray, dates: np.ndarray, bear: np.ndarray | None) -> dict:
    out = {"all": ttest(d), "is": ttest(d[dates <= IS_END]), "oos": ttest(d[dates > IS_END])}
    if bear is not None:
        out["bear"] = ttest(d[bear])
    return out


def grade(c: dict) -> tuple[str, str]:
    a = c["all"]
    p, m = a["p"], a["mean"]
    if p is None:
        return "검증전", f"표본 {a['n']}"
    if p < ALPHA:
        subs = [c[k]["mean"] for k in ("is", "oos", "bear") if k in c and c[k]["mean"] is not None]
        if all(np.sign(x) == np.sign(m) for x in subs):
            return "A", f"Bonferroni 유의(p={p:.4f}) + IS·OOS{'·하락장' if 'bear' in c else ''} 같은 방향"
        return "B", f"Bonferroni 유의(p={p:.4f}), 하위 구간 방향 불일치"
    if p < 0.10:
        return "C", f"방향만(p={p:.3f}, Bonferroni α={ALPHA:.4f} 미달)"
    return "F", f"현행과 구별 안 됨(p={p:.2f})"


def mdd(rets) -> float:
    eq = np.cumprod(1 + np.asarray(rets, float))
    return float((eq / np.maximum.accumulate(eq) - 1).min())


def trade_stats(r: np.ndarray, hold: np.ndarray | None = None) -> dict:
    r = r[np.isfinite(r)]
    w, l = r[r > 0], r[r <= 0]
    out = {"n": int(len(r)), "avg": float(r.mean()), "med": float(np.median(r)), "win": float((r > 0).mean()),
           "pl": float(w.mean() / abs(l.mean())) if len(w) and len(l) and l.mean() < 0 else None, "worst": float(r.min())}
    if hold is not None:
        out["hold"] = float(hold.mean())
        out["r_per20"] = float(r.mean() / hold.mean() * 20)
        out["turns_yr"] = float(250 / hold.mean())     # 같은 자본을 몇 번 돌리나 (회전율 근사)
    return out


# ───────────────────────── 데이터 ─────────────────────────
def load_index() -> pd.DataFrame:
    df = pd.read_csv(CSV, usecols=["date", "kospi_close"]).dropna().reset_index(drop=True)
    c = df.kospi_close
    df["ret1"] = c.pct_change()
    df["sma20"] = c.rolling(20).mean()
    df["sma200"] = c.rolling(200).mean()
    return df


def load_stocks():
    o = pl.col
    df = load_kr().sort("yf", "date")
    pc = o("c").shift(1).over("yf")
    df = df.with_columns(
        (o("c") / pc - 1).alias("r1"), (o("o") / pc - 1).alias("gap"),
        (pl.max_horizontal(o("h"), pc) - pl.min_horizontal(o("l"), pc)).alias("tr"),
        (o("c") - pc).alias("dc"),
        o("tv").rolling_mean(20).over("yf").alias("tv20"),
    )
    df = df.with_columns(
        ((o("r1").abs() > BAD) | (o("gap").abs() > BAD) | ((o("c") / o("o") - 1).abs() > BAD)).fill_null(False).cast(pl.Int32).alias("bad"),
        o("tr").rolling_mean(14).over("yf").alias("atr"),
        o("dc").clip(lower_bound=0).ewm_mean(alpha=1 / 14, adjust=False).over("yf").alias("ag"),
        (-o("dc")).clip(lower_bound=0).ewm_mean(alpha=1 / 14, adjust=False).over("yf").alias("al"),
        o("l").rolling_min(20).over("yf").alias("low20"),
    )
    df = df.with_columns(
        (100 - 100 / (1 + o("ag") / o("al"))).alias("rsi"),
        o("bad").rolling_sum(5, min_samples=1).over("yf").alias("bad5"),
        ((o("rc") >= MIN_PX) & (o("tv20") >= MIN_TV)).fill_null(False).alias("liq"),
        o("date").cum_count().over("yf").alias("age"),
    )
    return df


def picks(df: pl.DataFrame, dates: list) -> pl.DataFrame:
    o = pl.col
    return (df.filter(o("date").is_in(dates) & o("liq") & (o("bad5") == 0) & (o("age") >= 60) & o("atr").is_not_null())
              .with_columns(o("tv20").rank("ordinal", descending=True).over("date").alias("rk"))
              .filter(o("rk") <= TOPN)
              .select("yf", "date", "c", "atr", "low20", "rsi", "r1"))


class Wide:
    """선택된 종목만 날짜 × 종목 행렬로."""
    def __init__(self, df: pl.DataFrame, yfs: list[str], cal: list):
        sub = df.filter(pl.col("yf").is_in(yfs)).select("yf", "date", "o", "c", "bad").to_pandas()
        self.cal = pd.Index(pd.to_datetime(cal))
        sub["date"] = pd.to_datetime(sub["date"])
        piv = lambda col: sub.pivot(index="date", columns="yf", values=col).reindex(self.cal)
        c = piv("c")
        raw = c.to_numpy()
        ok = ~np.isnan(raw)
        li = len(raw) - 1 - np.argmax(ok[::-1], axis=0)          # 종목별 마지막 거래일 인덱스
        cf = c.ffill().to_numpy()
        cf[np.arange(len(raw))[:, None] > li[None, :]] = np.nan
        self.c = cf
        self.o = piv("o").to_numpy()
        self.traded = ok
        self.bad = piv("bad").fillna(0).to_numpy()
        self.col = {y: i for i, y in enumerate(c.columns)}
        self.lastidx = {y: int(li[i]) for i, y in enumerate(c.columns)}
        self.gmax = len(self.cal) - 1


# ───────────────────────── T1·T2·T3: 청산 규칙 ─────────────────────────
def exit_ma(W: Wide, j: int, t: int, E: float, stop: float | None, ma: int | None, chand: float | None, atr: float):
    """t = 신호일(진입 t+1 시가 E). 반환 (총수익, 보유일, 청산 이유) 또는 None(제외)."""
    e = t + 1
    last = W.lastidx[W.colname[j]]
    end = e + HOLD - 1
    if end > W.gmax and last >= W.gmax:
        return None                       # 미완성
    end = min(end, last)
    if end < e or W.bad[e:end + 1, j].any():
        return None
    hist = W.c[max(0, t - 60):t + 1, j]
    hist = hist[np.isfinite(hist)]
    closes = list(hist)
    armed = True
    if ma:
        if len(closes) < ma:
            return None
        armed = E >= np.mean(closes[-ma:])
    hi = -np.inf
    for i in range(e, end + 1):
        c = W.c[i, j]
        closes.append(c)
        hi = max(hi, c)
        if stop is not None and c <= stop:
            return c / E - 1, i - e + 1, "stop"
        if ma:
            sma = np.mean(closes[-ma:])
            if c >= sma and not armed:
                armed = True
            elif armed and c < sma:
                return c / E - 1, i - e + 1, "trail"
        if chand is not None and c <= hi - chand * atr:
            return c / E - 1, i - e + 1, "trail"
    return W.c[end, j] / E - 1, end - e + 1, ("delist" if last < e + HOLD - 1 else "time")


def exit_partial(W: Wide, j: int, t: int, E: float, S: float, atr: float, mode: str):
    e = t + 1
    last = W.lastidx[W.colname[j]]
    end = e + HOLD - 1
    if end > W.gmax and last >= W.gmax:
        return None
    end = min(end, last)
    if end < e or W.bad[e:end + 1, j].any():
        return None
    R = E - S
    pos, real, hi = 1.0, 0.0, -np.inf
    took = 0
    for i in range(e, end + 1):
        c = W.c[i, j]
        hi = max(hi, c)
        if c <= S:
            return real + pos * (c / E - 1), i - e + 1
        if mode == "target2R":
            if c >= E + 2 * R:
                return c / E - 1, i - e + 1
            continue
        if mode == "cur":
            while took < 2 and c >= E + (took + 1) * R:
                real += (1 / 3) * (c / E - 1); pos -= 1 / 3; took += 1
        if c <= hi - 3 * atr:
            return real + pos * (c / E - 1), i - e + 1
    return real + pos * (W.c[end, j] / E - 1), end - e + 1


T1 = {"cur": ("현행 −8% + 20일선", dict(stop=0.92, ma=20)), "s5": ("손절 −5%", dict(stop=0.95, ma=20)),
      "s12": ("손절 −12%", dict(stop=0.88, ma=20)), "satr": ("손절 2×ATR", dict(stop="atr2", ma=20)), "snone": ("손절 없음", dict(stop=None, ma=20))}
T2 = {"m10": ("10일선 트레일", dict(stop=0.92, ma=10)), "m50": ("50일선 트레일", dict(stop=0.92, ma=50)),
      "chand": ("최고가−3×ATR 트레일", dict(stop=0.92, ma=None, chand=3.0)), "tnone": ("트레일 없음(−8%·60일)", dict(stop=0.92, ma=None))}
T3 = {"cur": "현행 1R·2R 1/3 + 3ATR 트레일", "nopart": "부분익절 없음(전량 3ATR 트레일)", "target2R": "+2R 전량 목표"}
ACT = {"s5": "강화", "s12": "완화", "satr": "변경(변동성 비례)", "snone": "삭제", "m10": "강화", "m50": "완화", "chand": "변경(ATR 트레일)",
       "tnone": "삭제", "nopart": "삭제", "target2R": "변경(2R 전량)", "imm": "삭제(즉시 매도)", "th0": "완화", "th1": "강화",
       "c0": "강화(전량 현금)", "c70": "완화", "c100": "삭제", "full": "삭제(전액)", "ban": "강화(금지)"}


def run_exits(df: pl.DataFrame, cal: list, idx: pd.DataFrame):
    cdates = cal[60::HOLD]
    P = picks(df, cdates).to_pandas()
    W = Wide(df, sorted(P.yf.unique()), cal)
    W.colname = {i: y for y, i in W.col.items()}
    calpos = {d: i for i, d in enumerate(pd.to_datetime(cal))}
    P["date"] = pd.to_datetime(P["date"])
    bear_map = idx.set_index(pd.to_datetime(idx.date))
    rows = []
    for r in P.itertuples():
        t = calpos[r.date]; j = W.col[r.yf]
        if t + 1 > W.gmax or not W.traded[t + 1, j] or not np.isfinite(W.o[t + 1, j]):
            continue
        E = W.o[t + 1, j]
        rec = {"date": r.date.strftime("%Y-%m-%d"), "yf": r.yf}
        ok = True
        for code, (_, kw) in {**T1, **T2}.items():
            st = kw.get("stop")
            stop = None if st is None else (E - 2 * r.atr if st == "atr2" else E * st)
            res = exit_ma(W, j, t, E, stop, kw.get("ma"), kw.get("chand"), r.atr)
            if res is None:
                ok = False; break
            rec[code] = res[0] - COST; rec[code + "_h"] = res[1]; rec[code + "_x"] = res[2]
        if not ok:
            continue
        S = min(max(r.low20, r.c - 2 * r.atr), r.c - r.atr)
        if (r.c - S) / r.c <= 0.15 and E > S:
            for code in T3:
                res = exit_partial(W, j, t, E, S, r.atr, code)
                rec["p_" + code] = None if res is None else res[0] - COST
                rec["p_" + code + "_h"] = None if res is None else res[1]
        rows.append(rec)
    T = pd.DataFrame(rows)
    b = bear_map.reindex(pd.to_datetime(T.date.unique()), method="ffill")
    bear = {d.strftime("%Y-%m-%d"): bool(x.kospi_close < x.sma200) if np.isfinite(x.sma200) else None for d, x in b.iterrows()}
    return T, W, bear


def cohort_cmp(T: pd.DataFrame, cur: str, alt: str, bear: dict) -> dict:
    g = T.dropna(subset=[cur, alt]).groupby("date")[[cur, alt]].mean()
    d = (g[alt] - g[cur]).to_numpy()
    dates = g.index.to_numpy()
    bm = np.array([bear.get(x) is True for x in dates])
    return compare(d, dates, bm)


def exit_summary(T: pd.DataFrame, code: str) -> dict:
    sub = T.dropna(subset=[code])
    s = trade_stats(sub[code].to_numpy(), sub[code + "_h"].to_numpy(float))
    co = sub.groupby("date")[code].mean()
    s["cohort_avg"] = float(co.mean())
    s["mdd_chain"] = mdd(co.to_numpy())
    if code + "_x" in sub:
        s["exit_mix"] = {k: round(float(v), 3) for k, v in sub[code + "_x"].value_counts(normalize=True).items()}
    return s


# ───────────────────────── T4: 반등일 매도 대기 ─────────────────────────
TH = {"cur": 0.005, "imm": None, "th0": 0.0, "th1": 0.01}
T4N = {"cur": "현행 반등일(+0.5%) 대기", "imm": "즉시 매도", "th0": "반등일 +0.0%", "th1": "반등일 +1.0%"}


def sale_idx(r1: np.ndarray, t0: int, th) -> int:
    if th is None:
        return t0
    for s in range(t0 + 1, t0 + 11):
        if r1[s] >= th:
            return s
    return t0 + 10


def run_t4(idx: pd.DataFrame) -> dict:
    c, r1, s20 = idx.kospi_close.values, idx.ret1.values, idx.sma20.values
    ev, last = [], -10**9
    for t in range(21, len(c) - 31):
        if c[t] < s20[t] and c[t - 1] >= s20[t - 1] and t - last > 20:
            ev.append(t); last = t
    dates = idx.date.values[ev]
    bear = np.array([c[t] < idx.sma200.values[t] if np.isfinite(idx.sma200.values[t]) else False for t in ev])
    per = {}
    for k, th in TH.items():
        S = np.array([sale_idx(r1, t, th) for t in ev])
        px = c[S] / c[ev] - 1
        per[k] = {"px": px, "S": S, "f5": c[S + 5] / c[S] - 1, "f20": c[S + 20] / c[S] - 1, "wait": S - np.array(ev)}
    summ = {k: {"sale_vs_t0": float(v["px"].mean()), "sale_med": float(np.median(v["px"])), "better_than_t0": float((v["px"] > 0).mean()),
                "wait": float(v["wait"].mean()), "after5": float(v["f5"].mean()), "after20": float(v["f20"].mean())} for k, v in per.items()}
    cmp_ = {}
    for k in ("imm", "th0", "th1"):
        d = (1 + per[k]["px"]) / (1 + per["cur"]["px"]) - 1
        cmp_[k] = compare(d, dates, bear)
    return {"n_events": len(ev), "n_is": int((dates <= IS_END).sum()), "n_bear": int(bear.sum()), "summary": summ, "cmp": cmp_}


def run_t4_stock(T: pd.DataFrame, W: Wide, cal: list) -> dict:
    """민감도: T1 현행 거래 중 20일선 이탈 청산 → 종목 자신의 반등일 대기."""
    calpos = {d: i for i, d in enumerate(pd.to_datetime(cal))}
    rows = []
    for r in T[T.cur_x == "trail"].itertuples():
        j = W.col[r.yf]
        t0 = calpos[pd.Timestamp(r.date)] + r.cur_h       # 신호일 t + 보유일 = 청산일 인덱스
        if t0 + 10 > min(W.gmax, W.lastidx[r.yf]) or W.bad[t0:t0 + 11, j].any():
            continue
        cc = W.c[:, j]
        r1 = np.full(len(cc), np.nan); r1[1:] = cc[1:] / cc[:-1] - 1
        rec = {"date": cal[t0]}
        for k, th in TH.items():
            rec[k] = cc[sale_idx(r1, t0, th)] / cc[t0] - 1
        rows.append(rec)
    X = pd.DataFrame(rows)
    X["date"] = X.date.astype(str)
    g = X.groupby("date").mean()
    out = {"n_exits": len(X), "n_dates": len(g), "sale_vs_exit": {k: float(X[k].mean()) for k in TH}}
    out["cmp"] = {k: ttest(((1 + g[k]) / (1 + g["cur"]) - 1).to_numpy()) for k in ("imm", "th0", "th1")}
    return out


# ───────────────────────── T5: 하락장 노출 상한 ─────────────────────────
CAPS = {"cur": 0.5, "c0": 0.0, "c70": 0.7, "c100": 1.0}
T5N = {"cur": "현행 50%", "c0": "0% (전량 현금)", "c70": "70%", "c100": "제한 없음(100%)"}


def run_t5(idx: pd.DataFrame) -> dict:
    d = idx.dropna(subset=["sma200"]).reset_index(drop=True)
    r = d.ret1.values
    bearp = (d.kospi_close < d.sma200).shift(1, fill_value=False).values      # t−1 종가 판정 → t일 노출
    ser, summ = {}, {}
    for k, cap in CAPS.items():
        w = np.where(bearp, cap, 1.0)
        dw = np.abs(np.diff(np.r_[1.0, w]))
        net = w * r - dw * COST / 2
        net[0] = w[0] * r[0]
        ser[k] = net
        yrs = len(net) / 250
        eq = np.cumprod(1 + net)
        summ[k] = {"cagr": float(eq[-1] ** (1 / yrs) - 1), "vol": float(net.std() * math.sqrt(250)),
                   "sharpe": float(net.mean() / net.std() * math.sqrt(250)), "mdd": mdd(net), "turnover_yr": float(dw.sum() / yrs),
                   "avg_exposure": float(w.mean())}
    blocks = np.arange(len(r)) // 21
    bd = pd.Series(d.date.values).groupby(blocks).first().values
    agg = {k: pd.Series(np.log1p(v)).groupby(blocks).sum().pipe(np.expm1).values for k, v in ser.items()}
    cmp_ = {k: compare(agg[k] - agg["cur"], bd, None) for k in ("c0", "c70", "c100")}
    # 하락장 판정 블록만 (보조)
    inb = pd.Series(bearp).groupby(blocks).mean().values > 0.5
    sub = {k: ttest((agg[k] - agg["cur"])[inb]) for k in ("c0", "c70", "c100")}
    return {"from": d.date.iloc[0], "days": len(r), "bear_share": float(bearp.mean()), "summary": summ, "cmp": cmp_, "bear_blocks": sub}


# ───────────────────────── T6: 추격 절반 사이징 ─────────────────────────
W6 = {"cur": 0.5, "full": 1.0, "ban": 0.0}
T6N = {"cur": "현행 추격 절반", "full": "전액", "ban": "추격 금지"}


def run_t6(df: pl.DataFrame, cal: list, idx: pd.DataFrame) -> dict:
    cdates = cal[60::GAP6]
    P = picks(df, cdates).to_pandas()
    W = Wide(df, sorted(P.yf.unique()), cal)
    calpos = {d: i for i, d in enumerate(pd.to_datetime(cal))}
    P["date"] = pd.to_datetime(P["date"])
    rows = []
    for r in P.itertuples():
        t = calpos[r.date]; j = W.col[r.yf]; e = t + 1
        if e > W.gmax or not np.isfinite(W.o[e, j]):
            continue
        last = W.lastidx[r.yf]; end = t + GAP6
        if end > W.gmax and last >= W.gmax:
            continue
        end = min(end, last)
        if end < e or W.bad[e:end + 1, j].any():
            continue
        E = W.o[e, j]
        rows.append({"date": r.date.strftime("%Y-%m-%d"), "chase": bool((r.rsi > 70) or (r.r1 >= 0.05)),
                     "ret": W.c[end, j] / E - 1 - COST, "mae": float(np.nanmin(W.c[e:end + 1, j]) / E - 1)})
    X = pd.DataFrame(rows)
    co = {}
    for k, w in W6.items():
        X["w"] = np.where(X.chase, w, 1.0)
        co[k] = X.assign(wr=X.w * X.ret).groupby("date").apply(lambda g: g.wr.sum() / len(g), include_groups=False)
    dates = co["cur"].index.to_numpy()
    b = idx.set_index(pd.to_datetime(idx.date)).reindex(pd.to_datetime(dates), method="ffill")
    bear = (b.kospi_close < b.sma200).to_numpy()
    summ = {k: {"cohort_avg": float(v.mean()), "sharpe": float(v.mean() / v.std() * math.sqrt(250 / GAP6)), "mdd_chain": mdd(v.to_numpy()),
                "win": float((v > 0).mean())} for k, v in co.items()}
    cmp_ = {k: compare((co[k] - co["cur"]).to_numpy(), dates, bear) for k in ("full", "ban")}
    ch, nc = X[X.chase], X[~X.chase]
    g = X.groupby(["date", "chase"]).ret.mean().unstack().dropna()
    side = {"chase": trade_stats(ch.ret.to_numpy()) | {"mae": float(ch.mae.mean())},
            "nochase": trade_stats(nc.ret.to_numpy()) | {"mae": float(nc.mae.mean())},
            "share": float(X.chase.mean()), "paired_chase_minus_no": compare((g[True] - g[False]).to_numpy(), g.index.to_numpy(),
                                                                              np.array([bool(x) for x in pd.Series(bear, index=dates).reindex(g.index)]))}
    return {"n_trades": len(X), "n_cohorts": len(dates), "summary": summ, "cmp": cmp_, "sides": side}


# ───────────────────────── 실행 ─────────────────────────
def main():
    idx = load_index()
    df = load_stocks()
    cal = sorted(df["date"].unique().to_list())
    print("데이터 로드:", len(cal), "거래일", cal[0], "~", cal[-1], flush=True)

    T, W, bear = run_exits(df, cal, idx)
    res = {}
    # T1·T2
    for tid, alts in (("T1", T1), ("T2", T2)):
        codes = ["cur"] + [k for k in alts if k != "cur"]
        res[tid] = {"names": {"cur": T1["cur"][0], **{k: v[0] for k, v in alts.items()}},
                    "summary": {k: exit_summary(T, k) for k in codes},
                    "cmp": {k: cohort_cmp(T, "cur", k, bear) for k in codes if k != "cur"}}
    # T3
    T3d = T.rename(columns={f"p_{k}": k + "3" for k in T3} | {f"p_{k}_h": k + "3_h" for k in T3})
    res["T3"] = {"names": T3, "summary": {k: exit_summary(T3d, k + "3") for k in T3},
                 "cmp": {k: cohort_cmp(T3d, "cur3", k + "3", bear) for k in ("nopart", "target2R")}}
    res["exits_meta"] = {"n_trades": len(T), "n_cohorts": int(T.date.nunique()), "n_is_cohorts": int((T.date.unique() <= IS_END).sum()),
                         "n_bear_cohorts": int(sum(1 for d in T.date.unique() if bear.get(d))), "n_t3": int(T["p_cur"].notna().sum())}
    print("T1~T3 완료", res["exits_meta"], flush=True)
    res["T4"] = run_t4(idx) | {"names": T4N}
    res["T4"]["stock"] = run_t4_stock(T, W, cal)
    res["T5"] = run_t5(idx) | {"names": T5N}
    res["T6"] = run_t6(df, cal, idx) | {"names": T6N}

    # 등급 + 추천
    grades, recs = {}, {}
    for tid in ("T1", "T2", "T3", "T4", "T5", "T6"):
        best = None
        for k, c in res[tid]["cmp"].items():
            if tid == "T2" and k == "cur":
                continue
            g, why = grade(c)
            grades[f"{tid}/{k}"] = {"grade": g, "why": why, "mean": c["all"]["mean"], "p": c["all"]["p"], "action": ACT.get(k)}
            if c["all"]["mean"] is not None and c["all"]["mean"] > 0 and g in ("A", "B", "C"):
                if best is None or c["all"]["mean"] > res[tid]["cmp"][best]["all"]["mean"]:
                    best = k
        worse = [k for k, c in res[tid]["cmp"].items() if c["all"]["mean"] is not None and c["all"]["mean"] < 0 and grade(c)[0] in ("A", "B", "C")]
        if best:
            recs[tid] = {"pick": best, "action": ACT[best], "why": f"{best} 가 현행보다 + ({grades[f'{tid}/{best}']['grade']})"}
        elif len(worse) == len(res[tid]["cmp"]):
            recs[tid] = {"pick": "cur", "action": "현행 유지(근거 생김)", "why": "모든 대안이 현행보다 C 이상으로 나쁨"}
        else:
            recs[tid] = {"pick": "cur", "action": "현행 유지(근거 없음)", "why": "현행보다 나은 대안이 C 이상으로 나오지 않음"}
    out = {"generated": datetime.now().strftime("%Y-%m-%d %H:%M"), "prereg": "reports/studies/rule_audit.md §0",
           "data": {"index": f"data/deriv/daily.csv {idx.date.iloc[0]}~{idx.date.iloc[-1]}", "stocks": f"data/hist + kr_prices {cal[0]}~{cal[-1]}"},
           "params": {"cost_rt": COST, "is_end": IS_END, "m": M, "alpha_bonf": ALPHA, "topn": TOPN, "hold": HOLD, "gap6": GAP6},
           "grades": grades, "recommend": recs, "results": res}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o)) + "\n", encoding="utf-8")

    pct = lambda x, d=2: "—" if x is None else f"{x*100:+.{d}f}"
    for tid in ("T1", "T2", "T3"):
        print(f"\n## {tid}")
        for k, s in res[tid]["summary"].items():
            c = res[tid]["cmp"].get(k.replace("3", "") if tid == "T3" else k)
            print(f"{k:9s} n={s['n']} avg {pct(s['avg'])} med {pct(s['med'])} win {s['win']*100:.0f}% pl {s['pl'] and round(s['pl'],2)} hold {s['hold']:.1f} "
                  f"r/20d {pct(s['r_per20'])} mdd {pct(s['mdd_chain'],1)} exits {s.get('exit_mix')} "
                  + (f"| d {pct(c['all']['mean'])} p {c['all']['p']:.4f} IS {pct(c['is']['mean'])} OOS {pct(c['oos']['mean'])} bear {pct(c['bear']['mean'])}" if c else ""))
    print("\n## T4", res["T4"]["n_events"], res["T4"]["summary"])
    for k, c in res["T4"]["cmp"].items():
        print(k, pct(c["all"]["mean"]), round(c["all"]["p"], 4), "IS", pct(c["is"]["mean"]), "OOS", pct(c["oos"]["mean"]), "bear", pct(c["bear"]["mean"]))
    print("stock", json.dumps(res["T4"]["stock"], default=str)[:600])
    print("\n## T5", json.dumps(res["T5"]["summary"]))
    for k, c in res["T5"]["cmp"].items():
        print(k, pct(c["all"]["mean"]), c["all"]["p"], "IS", pct(c["is"]["mean"]), "OOS", pct(c["oos"]["mean"]))
    print("\n## T6", res["T6"]["n_trades"], json.dumps(res["T6"]["summary"]))
    for k, c in res["T6"]["cmp"].items():
        print(k, pct(c["all"]["mean"]), c["all"]["p"], "IS", pct(c["is"]["mean"]), "OOS", pct(c["oos"]["mean"]), "bear", pct(c["bear"]["mean"]))
    print("sides", json.dumps(res["T6"]["sides"], default=str)[:900])
    print("\n등급", {k: (v["grade"], pct(v["mean"]), v["p"] and round(v["p"], 4)) for k, v in grades.items()})
    print("추천", recs)


if __name__ == "__main__":
    main()
