"""QLD 매일 적립 백테스트 — 검증 데스크 독립 재현 (원 코드 study_qld_dca.py 미열람, 보고서 명세만 사용).

    python3 scripts/replicate_qld_dca.py data/study/qld_dca_px.csv [--out reports/studies/replication_qld_dca.json]

명세(2026-10-21_qld_daily_dca.md §1·§6·§7)에서 읽은 것:
- 매 미국 거래일 종가에 1만원, 같은 날 환율. 환전 편도 0.25%, 매수·매도 수수료 0.1%, 소수점 매수.
- 실 ETF 구간은 Adj Close(배당 재투자·보수 반영). 이전은 합성:
  QLD = 2×NDX총수익 − (T-bill+spread)·일수/360 − 0.95%/yr,  QQQ = NDX+0.7% − 0.20%,  SPY = GSPC+3.0% − 0.09%.
- spread 는 2006-06-21~2015-12-31 실 QLD와 누적수익이 같아지도록 보정(재현도 독립 보정).
- 환율 KRW=X → DEXKOUS → 직전값.
독립 선택(명세에 없음, 민감도로 확인): 배당·보수는 달력일/365, 금리는 전일 값(t−1)으로 (t−1,t] 구간 이자.
"""
from __future__ import annotations

import argparse
import json
from datetime import date

import numpy as np
import pandas as pd

A = dict(daily=10_000.0, fx_spread=0.0025, fee_buy=0.001, fee_sell=0.001,
         qld_er=0.0095, qqq_er=0.002, spy_er=0.0009, ndx_div=0.007, spx_div=0.03,
         calib=("2006-06-21", "2015-12-31"))


def load(path: str) -> pd.DataFrame:
    d = pd.read_csv(path, parse_dates=["date"]).set_index("date").sort_index()
    return d


def fx_series(d: pd.DataFrame, idx: pd.DatetimeIndex, mode: str = "yahoo_first") -> pd.Series:
    y, f = d["KRW=X_close"], d["dbn_DEXKOUS"]
    if mode == "fed_only":
        s = f
    else:
        s = y.where(y.notna(), f)
    return s.ffill().reindex(idx, method="ffill")


def daily_returns(d: pd.DataFrame, spread: float, rate_lag: int = 1, a: dict = A) -> pd.DataFrame:
    """미국 거래일(^NDX 있는 날) 단위 USD 총수익 — 실 Adj 우선, 없으면 합성."""
    g = d[d["^NDX_close"].notna()]
    idx = g.index
    dt = pd.Series(idx, index=idx).diff().dt.days
    rate = d["^IRX_close"].ffill().reindex(idx, method="ffill") / 100.0
    rate = rate.shift(rate_lag) if rate_lag else rate
    ndx = g["^NDX_close"].pct_change()
    spx = d["^GSPC_close"].reindex(idx).pct_change()
    ndx_tr = ndx + a["ndx_div"] * dt / 365
    syn = {
        "QLD": 2 * ndx_tr - (rate + spread) * dt / 360 - a["qld_er"] * dt / 365,
        "QQQ": ndx_tr - a["qqq_er"] * dt / 365,
        "SPY": spx + a["spx_div"] * dt / 365 - a["spy_er"] * dt / 365,
    }
    out, is_syn = {}, {}
    for k in syn:
        real = d[f"{k}_adj"].reindex(idx).pct_change(fill_method=None)
        use = real.notna()
        out[k] = real.where(use, syn[k])
        is_syn[k] = ~use
    r = pd.DataFrame(out).iloc[1:]
    r.attrs["syn"] = pd.DataFrame(is_syn).iloc[1:]
    r.attrs["syn_raw"] = syn
    return r


def calibrate_spread(d: pd.DataFrame, a: dict = A) -> float:
    """보정 구간에서 합성 QLD 누적수익 = 실 QLD 누적수익이 되는 spread(이분법)."""
    s, e = a["calib"]
    real = d["QLD_adj"].dropna()
    real = real[(real.index >= s) & (real.index <= e)]
    target = real.iloc[-1] / real.iloc[0]
    lo, hi = -0.05, 0.05
    for _ in range(60):
        mid = (lo + hi) / 2
        r = daily_returns(d, mid, a=a).attrs["syn_raw"]["QLD"]
        r = r[(r.index > real.index[0]) & (r.index <= real.index[-1])]
        if (1 + r).prod() > target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def levels(r: pd.DataFrame, first: pd.Timestamp) -> pd.DataFrame:
    lv = (1 + r).cumprod()
    head = pd.DataFrame({k: [1.0] for k in r.columns}, index=[first])
    return pd.concat([head, lv])


def xirr(dates: np.ndarray, cfs: np.ndarray) -> float:
    t = (dates - dates[0]).astype("timedelta64[D]").astype(float) / 365.0

    def npv(x):
        return float(np.sum(cfs / (1 + x) ** t))

    lo, hi = -0.99, 5.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if npv(mid) > 0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def simulate(px_usd: pd.Series, fx: pd.Series, start, end, a: dict = A, net_mark: bool = True) -> dict:
    """[start, end] 매 거래일 1만원 적립. px_usd·fx 는 같은 인덱스."""
    m = (px_usd.index >= pd.Timestamp(start)) & (px_usd.index <= pd.Timestamp(end))
    p, f = px_usd[m].values, fx[m].values
    dates = px_usd.index[m].values.astype("datetime64[D]")
    sh = a["daily"] / (f * (1 + a["fx_spread"])) * (1 - a["fee_buy"]) / p
    cum = np.cumsum(sh)
    haircut = (1 - a["fx_spread"]) * (1 - a["fee_sell"]) if net_mark else 1.0
    val = cum * p * f * haircut
    paid = a["daily"] * np.arange(1, len(p) + 1)
    final = cum[-1] * p[-1] * f[-1] * (1 - a["fx_spread"]) * (1 - a["fee_sell"])
    cfs = -np.full(len(p), a["daily"])
    cfs = np.append(cfs, final)
    dd = np.append(dates, dates[-1])
    rel = val / paid - 1
    peak = np.maximum.accumulate(val)
    i = int(np.argmin(rel))
    return {"days": int(len(p)), "start": str(dates[0]), "end": str(dates[-1]),
            "paid": float(paid[-1]), "final": float(final), "moic": float(final / paid[-1]),
            "irr": xirr(dd, cfs), "loss_vs_paid_min": float(rel[i]), "loss_date": str(dates[i]),
            "val_mdd": float(np.min(val / peak - 1))}


def asset_mdd(lv: pd.Series) -> dict:
    peak = lv.cummax()
    dd = lv / peak - 1
    t = dd.idxmin()
    pk = lv[:t].idxmax()
    after = lv[t:]
    rec = after[after >= lv[pk]]
    return {"mdd": float(dd.min()), "peak": str(pk.date()), "trough": str(t.date()),
            "recovered": str(rec.index[0].date()) if len(rec) else None}


def run(path: str, spread: float | None = None, rate_lag: int = 1, fx_mode: str = "yahoo_first",
        net_mark: bool = True) -> dict:
    d = load(path)
    sp = calibrate_spread(d) if spread is None else spread
    r = daily_returns(d, sp, rate_lag=rate_lag)
    first = d[d["^NDX_close"].notna()].index[0]
    lv = levels(r, first)
    fx = fx_series(d, lv.index, fx_mode)
    out = {"spread": sp, "real": {}, "y10": {}, "mdd_krw": {}, "mdd_usd": {}}
    for k in ["QLD", "QQQ", "SPY"]:
        out["real"][k] = simulate(lv[k], fx, "2006-06-21", "2026-10-20", net_mark=net_mark)
        out["mdd_krw"][k] = asset_mdd(lv[k] * fx)
        out["mdd_usd"][k] = asset_mdd(lv[k])
        out["y10"][k] = {y: simulate(lv[k], fx, f"{y}-01-01", f"{y + 9}-12-31", net_mark=net_mark)["irr"]
                         for y in range(1986, 2017)}
    out["full"] = {k: simulate(lv[k], fx, "1985-10-02", "2026-10-20", net_mark=net_mark) for k in ["QLD"]}
    return out


ORIG = {"irr_QLD": 0.309, "irr_QQQ": 0.198, "irr_SPY": 0.150, "loss_QLD": -0.568,
        "mdd_QLD_krw": -0.986, "neg_QLD": 7, "neg_QQQ": 2, "neg_SPY": 1,
        "neg_years_QLD": [1993, 1995, 1996, 1997, 1998, 1999, 2000]}
TOL = {"irr": 0.003, "loss": 0.02, "mdd": 0.005, "neg": 0}


def compare(rep: dict, orig: dict = ORIG, tol: dict = TOL) -> list[dict]:
    rows = []
    for k in ["QLD", "QQQ", "SPY"]:
        v = rep["real"][k]["irr"]
        rows.append({"item": f"실구간 IRR {k}", "orig": orig[f"irr_{k}"], "rep": round(v, 4),
                     "ok": abs(v - orig[f"irr_{k}"]) <= tol["irr"] + 0.0005})
    v = rep["real"]["QLD"]["loss_vs_paid_min"]
    rows.append({"item": "실구간 QLD 원금 대비 최대손실", "orig": orig["loss_QLD"], "rep": round(v, 4),
                 "ok": abs(v - orig["loss_QLD"]) <= tol["loss"]})
    v = rep["mdd_krw"]["QLD"]["mdd"]
    rows.append({"item": "QLD 원화 MDD", "orig": orig["mdd_QLD_krw"], "rep": round(v, 4),
                 "ok": abs(v - orig["mdd_QLD_krw"]) <= tol["mdd"] + 0.0005})
    for k in ["QLD", "QQQ", "SPY"]:
        neg = sorted(y for y, x in rep["y10"][k].items() if x < 0)
        ok = len(neg) == orig[f"neg_{k}"]
        if k == "QLD":
            ok = ok and neg == orig["neg_years_QLD"]
        rows.append({"item": f"10년 적립 원금미달 {k}", "orig": orig[f"neg_{k}"], "rep": len(neg),
                     "years": neg, "ok": ok})
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--out")
    a = ap.parse_args()
    base = run(a.csv)
    rows = compare(base)
    sens = {}
    for name, kw in {"spread_0": {"spread": 0.0}, "rate_same_day": {"rate_lag": 0},
                     "fx_fed_only": {"fx_mode": "fed_only"}, "mark_gross": {"net_mark": False}}.items():
        s = run(a.csv, **kw)
        sens[name] = {"spread": s["spread"],
                      "irr": {k: round(s["real"][k]["irr"], 4) for k in s["real"]},
                      "loss_QLD": round(s["real"]["QLD"]["loss_vs_paid_min"], 4),
                      "mdd_QLD_krw": round(s["mdd_krw"]["QLD"]["mdd"], 4),
                      "neg": {k: sorted(y for y, x in s["y10"][k].items() if x < 0) for k in s["y10"]}}
    res = {"meta": {"asof": "2026-10-20", "generated": date.today().isoformat(), "m": 0,
                    "source": "study-data/qld-dca-39529898962 data/study/qld_dca_px.csv",
                    "spread_rep": round(base["spread"], 5), "tol": TOL},
           "m": 0, "asof": "2026-10-20",
           "rows": rows, "sensitivity": sens,
           "detail": {"real": base["real"], "mdd_krw": base["mdd_krw"], "mdd_usd": base["mdd_usd"],
                      "full_QLD": base["full"]["QLD"],
                      "y10": {k: {str(y): round(v, 4) for y, v in base["y10"][k].items()} for k in base["y10"]}},
           "replicated": sum(r["ok"] for r in rows), "of": len(rows)}
    txt = json.dumps(res, ensure_ascii=False, indent=1, default=str)
    if a.out:
        open(a.out, "w", encoding="utf-8").write(txt + "\n")
    print(txt)


if __name__ == "__main__":
    main()
