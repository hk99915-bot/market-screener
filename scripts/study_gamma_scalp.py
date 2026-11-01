#!/usr/bin/env python3
"""롱 풋 + 델타헤지(감마 스칼핑) 모의 백테스트 — 파생 데스크 2026-11-01. **모의·교육용, 실계좌 불가.**

사전등록: docs/desk_kb/rounds/2026-11-01/derivs_gamma_scalp_bt.md §0 (계산 전 고정). 정의를 바꾸면 새 id 로 재등록.

  python3 scripts/study_gamma_scalp.py            # reports/studies/2026-11-01_gamma_scalp.json 생성
  python3 scripts/study_gamma_scalp.py --print    # 요약만 출력

입력  data/deriv/daily.csv (k200_close · rep_iv · kospi_open/close · atm_iv)
가격  Black-Scholes(r=q=0, 단일 IV=당일 rep_iv) — 실제 옵션 시계열 없음. 스큐·기간구조 미반영.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "deriv" / "daily.csv"
OUT = ROOT / "reports" / "studies" / "2026-11-01_gamma_scalp.json"

# ---- 사전등록 상수 (§0) ----
GRID = 2.5
OPT_HALF_SPREAD = 0.015       # 프리미엄 대비 반호가
HEDGE_BP = 2.0                # 헤지 거래 명목 대비 bp
COND_PCT = 0.30               # VRP 확장 백분위 ≤ 30%
COND_MIN_HIST = 250
IS_END = "2019-12-31"
M = 3
ALPHA = 0.05 / M
REGIMES = {
    "R1_2020-03": ("2020-02-13", "2020-04-09"),
    "R2_2022": ("2022-01-01", "2022-12-31"),
    "R3_2026-07~10": ("2026-06-11", "2026-12-31"),
}


def ncdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def npdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


def bs_put(s: float, k: float, t: float, vol: float) -> tuple[float, float, float]:
    """(가격, 델타, 감마) r=q=0. t<=0 이면 내재가치."""
    if t <= 0 or vol <= 0:
        return max(k - s, 0.0), (-1.0 if s < k else 0.0), 0.0
    sq = vol * math.sqrt(t)
    d1 = (math.log(s / k) + 0.5 * vol * vol * t) / sq
    d2 = d1 - sq
    price = k * ncdf(-d2) - s * ncdf(-d1)
    return price, ncdf(d1) - 1.0, npdf(d1) / (s * sq)


def tick(prem: float) -> float:
    return 0.01 if prem < 10 else 0.05


def load() -> pd.DataFrame:
    d = pd.read_csv(SRC, parse_dates=["date"])
    d = d[["date", "k200_close", "rep_iv", "kospi_open", "kospi_close", "atm_iv"]].dropna(
        subset=["k200_close", "rep_iv"]).reset_index(drop=True)
    d["lr"] = np.log(d.k200_close).diff()
    d["sig20"] = d.lr.rolling(20).std() * math.sqrt(252) * 100
    d["vrp"] = d.rep_iv - d.sig20
    # 확장 백분위(그날 포함 과거만, 최소 250개)
    v = d.vrp.to_numpy()
    pct = np.full(len(d), np.nan)
    hist: list[float] = []
    for i, x in enumerate(v):
        if np.isnan(x):
            continue
        hist.append(x)
        if len(hist) >= COND_MIN_HIST:
            pct[i] = float(np.mean(np.array(hist) <= x))
    d["vrp_pct"] = pct
    d["k200_open_px"] = d.k200_close * d.kospi_open / d.kospi_close   # 근사(D2 서술용)
    return d


def expiries(d: pd.DataFrame) -> list[int]:
    """매월 둘째 목요일(휴장이면 직전 거래일)의 행 인덱스."""
    dates = d.date
    out = []
    for (y, m), _ in d.groupby([dates.dt.year, dates.dt.month]):
        first = date(int(y), int(m), 1)
        off = (3 - first.weekday()) % 7
        th2 = pd.Timestamp(first + timedelta(days=off + 7))
        idx = d.index[dates <= th2]
        idx = [i for i in idx if dates[i].year == y and dates[i].month == m]
        if idx:
            out.append(idx[-1])
    return sorted(set(out))


def run_cycle(d: pd.DataFrame, i0: int, i1: int, mode: str, cost_mult: float) -> dict:
    """i0 진입(종가) → i1 만기(종가). mode: D1 매일 종가 · W1 5거래일마다 · D2 시가+종가 · NH 헤지 없음."""
    s0 = d.k200_close[i0]
    k = round(s0 / GRID) * GRID
    exp_date = d.date[i1]

    def T(i):
        return max((exp_date - d.date[i]).days, 0) / 365.0

    iv0 = d.rep_iv[i0] / 100
    prem, delta, _ = bs_put(s0, k, T(i0), iv0)
    opt_cost = max(tick(prem), prem * OPT_HALF_SPREAD) * cost_mult
    h = -delta if mode != "NH" else 0.0          # 보유 지수 단위(0~1, 매수)
    hedge_cost = abs(h) * s0 * HEDGE_BP / 1e4 * cost_mult
    hedge_pnl = 0.0
    n_trades = 1 if h else 0
    s_prev = s0
    mtm = [0.0]   # 사이클 내 일별 평가손익(명목 %, 비용 포함)
    for j, i in enumerate(range(i0 + 1, i1 + 1), start=1):
        iv = d.rep_iv[i] / 100
        if mode == "D2":
            so = d.k200_open_px[i]
            hedge_pnl += h * (so - s_prev)
            if i < i1:
                _, dlt, _ = bs_put(so, k, T(i) + 0.25 / 365, iv)  # 시가 시점 잔존 근사
                hn = -dlt
                hedge_cost += abs(hn - h) * so * HEDGE_BP / 1e4 * cost_mult
                n_trades += 1
                h = hn
            s_prev = so
        s = d.k200_close[i]
        hedge_pnl += h * (s - s_prev)
        s_prev = s
        if i == i1:
            hedge_cost += abs(h) * s * HEDGE_BP / 1e4 * cost_mult   # 만기 정리
            opt_val = max(k - s, 0.0)
        else:
            opt_val, dlt, _ = bs_put(s, k, T(i), iv)
            rebalance = mode in ("D1", "D2") or (mode == "W1" and j % 5 == 0)
            if rebalance:
                hn = -dlt
                hedge_cost += abs(hn - h) * s * HEDGE_BP / 1e4 * cost_mult
                n_trades += 1
                h = hn
        mtm.append((opt_val - prem + hedge_pnl - opt_cost - hedge_cost) / s0 * 100)
    lr = d.lr[i0 + 1:i1 + 1]
    real = float(np.sqrt(np.mean(lr ** 2) * 252) * 100)
    return {
        "entry": d.date[i0].strftime("%Y-%m-%d"), "expiry": exp_date.strftime("%Y-%m-%d"),
        "s0": round(s0, 2), "k": k, "iv_entry": round(iv0 * 100, 2), "real_vol": round(real, 2),
        "prem_pct": round(prem / s0 * 100, 4),
        "opt_pnl_pct": round((max(k - d.k200_close[i1], 0) - prem) / s0 * 100, 4),
        "hedge_pnl_pct": round(hedge_pnl / s0 * 100, 4),
        "cost_pct": round((opt_cost + hedge_cost) / s0 * 100, 4),
        "pnl_pct": round(mtm[-1], 4), "mtm": mtm, "n_hedge": n_trades,
        "vrp_pct": None if np.isnan(d.vrp_pct[i0]) else round(float(d.vrp_pct[i0]), 4),
        "vrp": None if np.isnan(d.vrp[i0]) else round(float(d.vrp[i0]), 2),
    }


def nw_t(x: np.ndarray, lag: int = 1) -> float:
    n = len(x)
    if n < 3:
        return float("nan")
    e = x - x.mean()
    g0 = np.dot(e, e) / n
    v = g0
    for l in range(1, lag + 1):
        g = np.dot(e[l:], e[:-l]) / n
        v += 2 * (1 - l / (lag + 1)) * g
    return float(x.mean() / math.sqrt(v / n)) if v > 0 else float("nan")


def summ(x: np.ndarray) -> dict:
    if len(x) == 0:
        return {"n": 0}
    t = nw_t(x)
    cum = np.cumsum(x)
    mdd = float(np.min(cum - np.maximum.accumulate(np.concatenate([[0], cum]))[1:])) if len(x) else 0
    q5 = float(np.quantile(x, 0.05))
    return {
        "n": int(len(x)), "mean": round(float(x.mean()), 4), "median": round(float(np.median(x)), 4),
        "sd": round(float(x.std(ddof=1)), 4) if len(x) > 1 else None,
        "ann_pct": round(float(x.mean()) * 12, 3), "win": round(float(np.mean(x > 0)), 3),
        "q05": round(q5, 4), "cvar05": round(float(x[x <= q5].mean()), 4),
        "worst": round(float(x.min()), 4), "best": round(float(x.max()), 4),
        "mdd_cum_pct": round(mdd, 3), "t_nw1": round(t, 3) if not math.isnan(t) else None,
        "p_one_sided": round(1 - ncdf(t), 5) if not math.isnan(t) else None,
        "sharpe_ann": round(float(x.mean() / x.std(ddof=1) * math.sqrt(12)), 3) if len(x) > 1 and x.std() > 0 else None,
    }


def grade(p, n, is_mean, oos_mean, mean_x2) -> str:
    if n < 30:
        return "검증전(n<30)"
    if p is not None and p < ALPHA:
        if is_mean > 0 and oos_mean > 0 and mean_x2 > 0:
            return "B(상한 B — A 조건 충족, BS 근사라 상한)"
        return "B"
    if p is not None and p < 0.10:
        return "C"
    return "F"


def dsr(x: np.ndarray, n_trials: int) -> dict:
    """Deflated Sharpe(Bailey & López de Prado 2014) — 사이클 단위 SR, 시도 수 n_trials 의 기대 최대 SR 차감."""
    n = len(x)
    sr = x.mean() / x.std(ddof=1)
    sk = float(((x - x.mean()) ** 3).mean() / x.std() ** 3)
    ku = float(((x - x.mean()) ** 4).mean() / x.std() ** 4)
    emc = 0.5772156649
    # 시도 간 SR 분산 모름 → 1/n 근사(귀무 SR 표준오차²)
    v = 1.0 / n
    z1 = _ninv(1 - 1 / n_trials)
    z2 = _ninv(1 - 1 / (n_trials * math.e))
    sr0 = math.sqrt(v) * ((1 - emc) * z1 + emc * z2)
    den = math.sqrt(max(1e-12, 1 - sk * sr + (ku - 1) / 4 * sr * sr))
    z = (sr - sr0) * math.sqrt(n - 1) / den
    return {"sr_cycle": round(float(sr), 4), "sr0": round(sr0, 4), "skew": round(sk, 3),
            "kurt": round(ku, 3), "n_trials": n_trials, "dsr": round(ncdf(z), 4)}


def _ninv(p: float) -> float:
    lo, hi = -10.0, 10.0
    for _ in range(100):
        mid = (lo + hi) / 2
        if ncdf(mid) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--print", action="store_true")
    a = ap.parse_args()
    d = load()
    ex = expiries(d)
    pairs = list(zip(ex[:-1], ex[1:]))
    res: dict = {}
    for mode in ("D1", "W1", "D2", "NH"):
        for cm in (0.0, 1.0, 2.0):
            if mode != "D1" and cm != 1.0:
                continue
            res[f"{mode}_x{cm:g}"] = [run_cycle(d, i0, i1, mode, cm) for i0, i1 in pairs]
    base = res["D1_x1"]
    df = pd.DataFrame([{k: v for k, v in c.items() if k != "mtm"} for c in base])
    df["entry_dt"] = pd.to_datetime(df.entry)
    x = df.pnl_pct.to_numpy()
    is_m = (df.entry_dt <= IS_END).to_numpy()
    sig = (df.vrp_pct <= COND_PCT).fillna(False).to_numpy() & df.vrp_pct.notna().to_numpy()
    defined = df.vrp_pct.notna().to_numpy()

    def ser(key, mask=None):
        z = pd.DataFrame([{k: v for k, v in c.items() if k != "mtm"} for c in res[key]]).pnl_pct.to_numpy()
        return z if mask is None else z[mask]

    # H1
    h1 = summ(x)
    h1_is, h1_oos = summ(x[is_m]), summ(x[~is_m])
    h1_x2 = summ(ser("D1_x2"))
    # H2
    h2 = summ(x[sig])
    h2_is, h2_oos = summ(x[sig & is_m]), summ(x[sig & ~is_m])
    h2_x2 = summ(ser("D1_x2", sig))
    # H3
    a_, b_ = x[sig], x[defined & ~sig]
    diff = a_.mean() - b_.mean()
    se = math.sqrt(a_.var(ddof=1) / len(a_) + b_.var(ddof=1) / len(b_))
    t3 = diff / se
    def h3_split(mask):
        aa, bb = x[sig & mask], x[defined & ~sig & mask]
        return round(float(aa.mean() - bb.mean()), 4) if len(aa) and len(bb) else None
    h3 = {"n_sig": int(len(a_)), "n_non": int(len(b_)), "diff": round(float(diff), 4),
          "t_welch": round(t3, 3), "p_one_sided": round(1 - ncdf(t3), 5),
          "is_diff": h3_split(is_m), "oos_diff": h3_split(~is_m)}
    x2 = ser("D1_x2")
    h3_x2 = float(x2[sig].mean() - x2[defined & ~sig].mean())

    grades = {
        "H1_always_D1": grade(h1["p_one_sided"], h1["n"], h1_is["mean"], h1_oos["mean"], h1_x2["mean"]),
        "H2_cond_vrp30": grade(h2["p_one_sided"], h2["n"], h2_is.get("mean", -1), h2_oos.get("mean", -1), h2_x2.get("mean", -1)),
        "H3_cond_minus_non": grade(h3["p_one_sided"], h3["n_sig"], h3["is_diff"] or -1, h3["oos_diff"] or -1, h3_x2),
    }
    # 역방향 서술
    reverse = {k: ("역방향 p " + str(round(ncdf(t), 5))) for k, t in
               (("H1", h1["t_nw1"]), ("H2", h2["t_nw1"]), ("H3", h3["t_welch"])) if t is not None}

    # 변형 요약
    variants = {k: summ(ser(k)) for k in res}
    variants_cond = {k: summ(ser(k, sig)) for k in ("D1_x1", "W1_x1", "D2_x1", "NH_x1")}

    # 국면
    regimes = {}
    for nm, (s, e) in REGIMES.items():
        msk = ((df.entry_dt >= s) & (df.entry_dt <= e)).to_numpy()
        sub = df[msk]
        regimes[nm] = {
            "cycles": sub[["entry", "expiry", "iv_entry", "real_vol", "opt_pnl_pct", "hedge_pnl_pct", "cost_pct", "pnl_pct", "vrp_pct"]].to_dict("records"),
            "sum_pct": round(float(sub.pnl_pct.sum()), 3), "mean_pct": round(float(sub.pnl_pct.mean()), 3),
            "cond_entered": int((sig & msk).sum()),
            "W1_sum": round(float(ser("W1_x1", msk).sum()), 3), "NH_sum": round(float(ser("NH_x1", msk).sum()), 3),
            "loo_H1": summ(x[~msk]), "loo_H2": summ(x[sig & ~msk]),
        }
    # 연도별
    df["year"] = df.entry_dt.dt.year
    yearly = df.groupby("year").agg(n=("pnl_pct", "size"), sum=("pnl_pct", "sum"), iv=("iv_entry", "mean"),
                                    real=("real_vol", "mean")).round(3).reset_index().to_dict("records")
    # 일별 평가 MDD(항상·D1, 사이클 이어붙임)
    path = [0.0]
    for c in base:
        last = path[-1]
        path.extend(last + v for v in c["mtm"][1:])
    path = np.array(path)
    daily_mdd = float(np.min(path - np.maximum.accumulate(path)))
    # 분해: 손익 vs (실현²−내재²)
    df["var_gap"] = (df.real_vol ** 2 - df.iv_entry ** 2) / 100
    corr = float(np.corrcoef(df.var_gap, df.pnl_pct)[0, 1])
    # IV 대용 점검
    raw = pd.read_csv(SRC, parse_dates=["date"])
    ov = raw.dropna(subset=["atm_iv", "rep_iv"])
    iv_check = {"n": int(len(ov)), "period": [ov.date.min().strftime("%Y-%m-%d"), ov.date.max().strftime("%Y-%m-%d")],
                "atm_minus_rep_mean_pp": round(float((ov.atm_iv * 100 - ov.rep_iv).mean()), 2),
                "atm_minus_rep_median_pp": round(float((ov.atm_iv * 100 - ov.rep_iv).median()), 2),
                "abs_mean_pp": round(float((ov.atm_iv * 100 - ov.rep_iv).abs().mean()), 2)}
    # 프리미엄 대비 손익 (참고)
    prem_ratio = round(float(df.pnl_pct.mean() / df.prem_pct.mean()), 3)

    out = {
        "study": "2026-11-01_gamma_scalp", "generated": "2026-11-01", "asof": d.date.iloc[-1].strftime("%Y-%m-%d"),
        "label": "모의·교육용, 실계좌 불가(옵션 화이트리스트 밖·공매도 2027-04-15까지 금지). 매매 지시 아님.",
        "m": M,
        "prereg": {
            "doc": "docs/desk_kb/rounds/2026-11-01/derivs_gamma_scalp_bt.md §0", "m": M, "alpha_bonf": round(ALPHA, 5),
            "is_end": IS_END, "oos_start": "2020-01-01",
            "cost": {"opt_half_spread": "max(1틱, 프리미엄×1.5%)", "hedge_bp": HEDGE_BP, "sens": [0, 1, 2]},
            "iv": "rep_iv(KRX 대표 IV, 2010~) — VKOSPI 7행뿐이라 대용 불가", "pricing": "BS r=q=0 단일 IV",
            "cond": f"VRP=rep_iv−σ20 확장 백분위 ≤ {COND_PCT}(최소 {COND_MIN_HIST}일)",
            "grade_rule": "A=p<α且IS·OOS+且비용×2 평균>0 · B=p<α · C=p<0.10 · F · 검증전 n<30 · 상한 B(BS 근사)",
            "topic_N_note": "vol_premium: hf_ls_vol V1·V2 2 + 선행 노트 서술 1 + m 3 ≈ 6 → α(N) 0.0083",
        },
        "survivorship": "해당 없음(지수 단일 기초) — 대신 모형 편향: 스큐 미반영·rep_iv≠ATM 1개월 IV",
        "grades": grades,
        "reverse_direction": reverse,
        "H1": {"all": h1, "is": h1_is, "oos": h1_oos, "cost_x0": variants["D1_x0"], "cost_x2": h1_x2},
        "H2": {"all": h2, "is": h2_is, "oos": h2_oos, "cost_x2": h2_x2},
        "H3": h3 | {"cost_x2_diff": round(h3_x2, 4)},
        "variants_always": variants, "variants_cond": variants_cond,
        "regimes": regimes, "yearly": yearly,
        "daily_mtm_mdd_pct": round(daily_mdd, 3),
        "pnl_vs_var_gap_corr": round(corr, 3),
        "pnl_over_premium": prem_ratio,
        "avg_premium_pct": round(float(df.prem_pct.mean()), 3),
        "avg_cost_pct": round(float(df.cost_pct.mean()), 4),
        "decomp_mean_pct": {"opt": round(float(df.opt_pnl_pct.mean()), 4), "hedge": round(float(df.hedge_pnl_pct.mean()), 4),
                            "cost": round(float(-df.cost_pct.mean()), 4)},
        "iv_proxy_check": iv_check,
        "dsr": {"H1": dsr(x, 6), "H2": dsr(x[sig], 6)},
        "latest": {k: v for k, v in base[-1].items() if k != "mtm"},
        "now_signal": {"date": d.date.iloc[-1].strftime("%Y-%m-%d"), "vrp": round(float(d.vrp.iloc[-1]), 2),
                       "vrp_pct": round(float(d.vrp_pct.iloc[-1]), 4)},
        "limits": ["BS 근사·스큐/기간구조 없음", "rep_iv 대용", "D2 는 KOSPI 시가 비율로 K200 시가 근사",
                   "r=q=0", "만기일 최종가=K200 종가", "헤지 2bp 가정"],
    }
    if a.print:
        print(json.dumps({k: out[k] for k in ("grades", "reverse_direction", "H3", "daily_mtm_mdd_pct", "pnl_vs_var_gap_corr",
                                              "decomp_mean_pct", "iv_proxy_check", "dsr", "now_signal", "avg_premium_pct")},
                         ensure_ascii=False, indent=1))
        for k in ("H1", "H2"):
            print(k, json.dumps(out[k], ensure_ascii=False))
        for k, v in out["variants_always"].items():
            print("always", k, v)
        for k, v in out["variants_cond"].items():
            print("cond", k, v)
        for k, v in regimes.items():
            print(k, {kk: vv for kk, vv in v.items() if kk not in ("cycles",)})
        print(pd.DataFrame(yearly).to_string())
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
