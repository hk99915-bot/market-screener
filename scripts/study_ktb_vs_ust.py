#!/usr/bin/env python3
"""퀀트 연구: ISA 채권 20% 슬리브 — 국고채 vs 미국채(환노출 UH·환헤지 H), 원화 기준 월간 (2026-10-17).
사전등록: reports/studies/trial_log.json (study=ktb_vs_ust, m=11) — 계산 전 커밋 0c05bc57.
프록시(외부망 차단으로 야후·FRED 불가):
  USDKRW  = 달러선물 ETF(138230 ~2016-12, 261240 2017~) 일수익 − 미 정책금리/252, 2024-09-17 현물(macro_series)로 수준 보정
  UST-UH  = IEF(USD, 분배 재투자) × USDKRW      UST-H = IEF − (미 정책금리 − 한 기준금리)/12   TLT-UH 서술만
  KTB10   = 148070 (KOSEF 국고채10년)  KTB3 = 114260 (KODEX 국고채3년, 서술만)
  금리    = 연준 목표 중간값·한은 기준금리 하드코딩(2026년 이후 동결 가정 — 미확인)
실행: python3 scripts/study_ktb_vs_ust.py  → reports/studies/ktb_vs_ust.json
"""
from __future__ import annotations
import json, math, sys
from pathlib import Path
import numpy as np, pandas as pd
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from screener.portfolios import _stats  # noqa: E402

FED = [("2009-12", .00125), ("2015-12", .00375), ("2016-12", .00625), ("2017-03", .00875), ("2017-06", .01125),
       ("2017-12", .01375), ("2018-03", .01625), ("2018-06", .01875), ("2018-09", .02125), ("2018-12", .02375),
       ("2019-08", .02125), ("2019-09", .01875), ("2019-11", .01625), ("2020-03", .00125), ("2022-03", .00375),
       ("2022-05", .00875), ("2022-06", .01625), ("2022-07", .02375), ("2022-09", .03125), ("2022-11", .03875),
       ("2022-12", .04375), ("2023-02", .04625), ("2023-03", .04875), ("2023-05", .05125), ("2023-07", .05375),
       ("2024-09", .04875), ("2024-11", .04625), ("2024-12", .04375), ("2025-09", .04125), ("2025-10", .03875),
       ("2025-12", .03625)]
BOK = [("2009-12", .02), ("2010-07", .0225), ("2010-11", .025), ("2011-01", .0275), ("2011-03", .03), ("2011-06", .0325),
       ("2012-07", .03), ("2012-10", .0275), ("2013-05", .025), ("2014-08", .0225), ("2014-10", .02), ("2015-03", .0175),
       ("2015-06", .015), ("2016-06", .0125), ("2017-11", .015), ("2018-11", .0175), ("2019-07", .015), ("2019-10", .0125),
       ("2020-03", .0075), ("2020-05", .005), ("2021-08", .0075), ("2021-11", .01), ("2022-01", .0125), ("2022-04", .015),
       ("2022-05", .0175), ("2022-07", .0225), ("2022-08", .025), ("2022-10", .03), ("2022-11", .0325), ("2023-01", .035),
       ("2024-10", .0325), ("2024-11", .03), ("2025-02", .0275), ("2025-05", .025)]
HIKE = [("2017-11", "2018-11"), ("2021-08", "2023-01")]
START, END = "2011-11", "2026-09"
IS_END = "2018-12"
COST = 0.001
SEED, B, BLK = 20261017, 5000, 6


def step(sched, idx):
    s = pd.Series({pd.Period(k, "M"): v for k, v in sched})
    return pd.Series([s[s.index <= p].iloc[-1] for p in idx], index=idx)


def load():
    kr = pd.read_parquet(ROOT / "data/hist/kr_etf_daily.parquet")
    kr = kr.pivot(index="date", columns="symbol", values="adj_close")
    ki = pd.read_parquet(ROOT / "data/hist/kr_index_daily.parquet").pivot(index="date", columns="symbol", values="close")
    us = pd.read_parquet(ROOT / "data/hist/us_daily.parquet")
    us = us.pivot(index="date", columns="symbol", values="adj_close")[["IEF", "TLT", "SPY", "QQQ", "GLD"]]
    for d in (kr, ki, us):
        d.index = pd.to_datetime(d.index)
    days = ki["KOSPI"].dropna().index
    # USDKRW 복원
    fed_d = step(FED, days.to_period("M")).values / 252
    r1 = kr["138230"].reindex(days).ffill().pct_change()
    r2 = kr["261240"].reindex(days).ffill().pct_change()
    etf = r1.where(days < "2017-01-01", r2)
    fxr = (etf.fillna(0) - fed_d)
    fx = (1 + fxr).cumprod()
    ms = json.load(open(ROOT / "reports/macro_series.json"))["series"]["USDKRW"]
    spot = pd.Series({pd.Timestamp(r[0]): r[4] for r in ms})
    fx = fx * spot.iloc[0] / fx.asof(spot.index[0])
    val = pd.DataFrame(index=days)
    val["FX"] = fx
    val["KOSPI"] = ki["KOSPI"].reindex(days)
    for s in ("148070", "114260", "069500", "305080"):
        val[s] = kr[s].reindex(days)
    usd = us.reindex(days.union(us.index)).ffill().reindex(days)  # 한국 거래일 기준 최근 미국 종가
    for c in usd.columns:
        val[c + "_usd"] = usd[c]
        val[c + "_krw"] = usd[c] * fx
    val = val.ffill()
    return val, spot, fx


def monthly(val):
    """월말 신호 → 다음 거래일 종가 체결: 라벨 m 의 수익 = (m 다음 첫 거래일) → (m+1 다음 첫 거래일)."""
    days = val.index
    labels = pd.period_range("2011-01", END, freq="M")
    ex = []
    for p in labels:
        i = days.searchsorted(p.end_time.normalize(), side="right")
        ex.append(days[i])
    px = val.loc[ex]; px.index = labels
    r = px.pct_change().shift(-1).dropna(how="all")  # 라벨 m = 다음 달 보유 수익 → 라벨을 보유월로 이동
    r.index = r.index + 1
    return r.loc[START:END]


def build(val):
    r = monthly(val)
    idx = r.index
    fed, bok = step(FED, idx), step(BOK, idx)
    A = pd.DataFrame(index=idx)
    A["KTB10"] = r["148070"]; A["KTB3"] = r["114260"]
    A["UST-UH"] = r["IEF_krw"]; A["UST-H"] = r["IEF_usd"] - (fed - bok) / 12
    A["TLT-UH"] = r["TLT_krw"]
    A["KOSPI"] = r["KOSPI"]; A["SP_KRW"] = r["SPY_krw"]; A["NDX_KRW"] = r["QQQ_krw"]
    A["K200"] = r["069500"]; A["GOLD_KRW"] = r["GLD_krw"]; A["FX"] = r["FX"]; A["T305080"] = r["305080"]
    return A, fed, bok


def port(A, bond, cost=COST):
    w = {"SP_KRW": .40, "NDX_KRW": .10, "K200": .15, bond: .20, "GOLD_KRW": .15}
    out, cur = [], dict(w)
    for t in A.index:
        rr = sum(cur[k] * A.at[t, k] for k in w)
        grown = {k: cur[k] * (1 + A.at[t, k]) for k in w}
        tot = sum(grown.values())
        drift = {k: v / tot for k, v in grown.items()}
        turn = sum(abs(drift[k] - w[k]) for k in w) / 2
        out.append(rr - turn * cost)
        cur = dict(w)
    return pd.Series(out, index=A.index)


def _betacf(a, b, x):
    qab, qap, qam = a + b, a + 1, a - 1
    c, d = 1.0, 1 - qab * x / qap
    d = 1 / (d if abs(d) > 1e-30 else 1e-30); h = d
    for m in range(1, 300):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1 + aa * d; d = 1 / (d if abs(d) > 1e-30 else 1e-30)
        c = 1 + aa / c if abs(1 + aa / c) > 1e-30 else 1e-30
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1 + aa * d; d = 1 / (d if abs(d) > 1e-30 else 1e-30)
        c = 1 + aa / c if abs(1 + aa / c) > 1e-30 else 1e-30
        de = d * c; h *= de
        if abs(de - 1) < 1e-12:
            break
    return h


def _betai(a, b, x):
    """정규화 불완전 베타 I_x(a,b) — t분포 양측 p = I_{df/(df+t²)}(df/2, 1/2) (scipy 없음)."""
    if x <= 0 or x >= 1:
        return 0.0 if x <= 0 else 1.0
    lb = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x)
    if x < (a + 1) / (a + b + 2):
        return math.exp(lb) * _betacf(a, b, x) / a
    return 1 - math.exp(lb) * _betacf(b, a, 1 - x) / b


def tstat(x, side):
    x = np.asarray(x, float); x = x[~np.isnan(x)]
    if len(x) < 3:
        return float("nan"), len(x)
    df = len(x) - 1
    t = x.mean() / (x.std(ddof=1) / math.sqrt(len(x)))
    p2 = _betai(df / 2, 0.5, df / (df + t * t))
    if side == "two":
        return float(p2), len(x)
    p = p2 / 2 if (t > 0) == (side == ">") else 1 - p2 / 2
    return float(p), len(x)


def boot_sharpe_diff(a, b, rng):
    a, b = np.asarray(a), np.asarray(b); n = len(a)
    sh = lambda x: x.mean() / x.std(ddof=1) * math.sqrt(12)
    obs = sh(a) - sh(b)
    diffs = np.empty(B)
    for k in range(B):
        st = rng.integers(0, n, size=n // BLK + 1)
        ii = np.concatenate([(np.arange(s, s + BLK) % n) for s in st])[:n]
        diffs[k] = sh(a[ii]) - sh(b[ii])
    p = 2 * min((diffs <= 0).mean(), (diffs >= 0).mean())
    return float(obs), float(min(p, 1.0)), [float(np.percentile(diffs, 5)), float(np.percentile(diffs, 95))]


def grade(p, alpha, n, is_sign, oos_sign, full_sign):
    if n < 8:
        return "검증전"
    if p < alpha:
        return "A" if (is_sign == oos_sign == full_sign) else "B"
    return "C" if p < 0.10 else "F"


def main():
    val, spot, fx = load()
    # FX 복원 검증
    s2 = spot.reindex(fx.index).dropna(); f2 = fx.reindex(s2.index)
    fx_check = {"overlap": f"{s2.index[0].date()}~{s2.index[-1].date()}", "end_err": round(float(f2.iloc[-1] / s2.iloc[-1] - 1), 4),
                "max_abs_err": round(float((f2 / s2 - 1).abs().max()), 4),
                "daily_ret_corr": round(float(f2.pct_change().corr(s2.pct_change())), 3)}
    A, fed, bok = build(val)
    bonds = ["KTB10", "KTB3", "UST-UH", "UST-H", "TLT-UH"]
    rng = np.random.default_rng(SEED)
    P = {b: port(A, b) for b in bonds}
    ex_bond = (A["SP_KRW"] * .40 + A["NDX_KRW"] * .10 + A["K200"] * .15 + A["GOLD_KRW"] * .15) / .80
    res = {"generated": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"), "prereg": "trial_log.json ktb_vs_ust (커밋 0c05bc57, 계산 전)",
           "period": f"{A.index[0]}~{A.index[-1]}", "months": len(A), "m": 11, "alpha_bonf": round(0.05 / 11, 5),
           "proxies": __doc__.split("프록시")[1].split("실행:")[0].strip(), "fx_check": fx_check}
    # 1. 자산 통계·상관
    st = {}
    for b in bonds + ["KOSPI", "SP_KRW", "FX"]:
        s = _stats(A[b].values)
        if b in bonds:
            s["corr_kospi"] = round(float(A[b].corr(A["KOSPI"])), 2)
            s["corr_sp_krw"] = round(float(A[b].corr(A["SP_KRW"])), 2)
            s["corr_isa_ex_bond"] = round(float(A[b].corr(ex_bond)), 2)
            s["corr_fx"] = round(float(A[b].corr(A["FX"])), 2)
        st[b] = s
    res["assets"] = st
    v = A["T305080"].dropna(); v = v[v.index >= pd.Period("2018-10", "M")]
    res["proxy_check_305080"] = {"months": len(v), "corr_vs_UST-UH": round(float(v.corr(A.loc[v.index, "UST-UH"])), 3),
                                 "cagr_305080": _stats(v.values).get("cagr"), "cagr_UST-UH_same": _stats(A.loc[v.index, "UST-UH"].values).get("cagr")}
    # 2. 위기
    crisis = A.index[A["KOSPI"] <= -0.05]
    res["crisis_months"] = [str(p) for p in crisis]
    ctab = A.loc[crisis, ["KOSPI", "SP_KRW", "FX"] + bonds].round(4)
    res["crisis_table"] = {str(k): v for k, v in ctab.T.to_dict().items()}
    res["crisis_mean"] = {b: round(float(A.loc[crisis, b].mean()), 4) for b in bonds}
    res["crisis_hit"] = {b: round(float((A.loc[crisis, b] > 0).mean()), 2) for b in bonds}
    yr = lambda s, y: float((1 + s[(s.index >= pd.Period(f"{y}-01", "M")) & (s.index <= pd.Period(f"{y}-12", "M"))]).prod() - 1)
    res["spot"] = {"2020-03": {b: round(float(A.at[pd.Period("2020-03", "M"), b]), 4) for b in bonds + ["KOSPI", "FX"]},
                   "2026-07": {b: round(float(A.at[pd.Period("2026-07", "M"), b]), 4) for b in bonds + ["KOSPI", "FX"]},
                   "2022": {b: round(yr(A[b], 2022), 4) for b in bonds + ["KOSPI", "SP_KRW", "FX"]}}
    res["portfolio"] = {b: {**_stats(P[b].values), "crisis_mean": round(float(P[b].loc[crisis].mean()), 4)} for b in bonds}
    # 3. 국면
    hike = pd.Series(False, index=A.index)
    for a, z in HIKE:
        hike |= (A.index >= pd.Period(a, "M")) & (A.index <= pd.Period(z, "M"))
    fxup_now = A["FX"] > 0
    fx6 = (1 + A["FX"]).rolling(6).apply(np.prod, raw=True).shift(1) - 1
    fxup_ex = fx6 > 0
    def cond(mask):
        return {b: {"mean_m": round(float(A.loc[mask, b].mean()), 4), "ann": round(float((1 + A.loc[mask, b].mean()) ** 12 - 1), 4),
                    "n": int(mask.sum())} for b in bonds}
    res["regimes"] = {"BOK_hike": cond(hike), "BOK_nonhike": cond(~hike), "FX_up_same_month(사후)": cond(fxup_now),
                      "FX_down_same_month(사후)": cond(~fxup_now), "FX6m_up_prior(사전)": cond(fxup_ex & fx6.notna()),
                      "FX6m_down_prior(사전)": cond(~fxup_ex & fx6.notna())}
    # 4. 검정
    isel = A.index <= pd.Period(IS_END, "M")
    al = 0.05 / 11
    H = []
    def add(hid, desc, x, side, idx_mask=None):
        x = x.dropna()
        p, n = tstat(x.values, side)
        sgn = lambda y: int(np.sign(y.mean())) if len(y) else 0
        xi, xo = x[x.index <= pd.Period(IS_END, "M")], x[x.index > pd.Period(IS_END, "M")]
        g = grade(p, al, n, sgn(xi), sgn(xo), sgn(x))
        H.append({"id": hid, "desc": desc, "mean_m": round(float(x.mean()), 4), "n": n, "p": round(p, 4),
                  "is_mean": round(float(xi.mean()), 4) if len(xi) else None, "n_is": len(xi),
                  "oos_mean": round(float(xo.mean()), 4) if len(xo) else None, "n_oos": len(xo), "grade": g})
    d = lambda a, b: A[a] - A[b]
    add("H1a", "KOSPI≤−5% 달 UST-UH−KTB10 >0", d("UST-UH", "KTB10").loc[crisis], ">")
    add("H1b", "KOSPI≤−5% 달 UST-H−KTB10 >0", d("UST-H", "KTB10").loc[crisis], ">")
    add("H1c", "KOSPI≤−5% 달 UST-UH−UST-H >0", d("UST-UH", "UST-H").loc[crisis], ">")
    for hid, a, b in (("H2a", "UST-UH", "KTB10"), ("H2b", "UST-H", "KTB10"), ("H2c", "UST-UH", "UST-H")):
        obs, p, ci = boot_sharpe_diff(P[a].values, P[b].values, rng)
        shi = lambda s: s.mean() / s.std(ddof=1) * math.sqrt(12)
        di = shi(P[a][isel]) - shi(P[b][isel]); do = shi(P[a][~isel]) - shi(P[b][~isel])
        g = grade(p, al, len(P[a]), int(np.sign(di)), int(np.sign(do)), int(np.sign(obs)))
        H.append({"id": hid, "desc": f"ISA믹스 샤프 {a}슬리브 − {b}슬리브 (양측, 블록부트스트랩)", "sharpe_diff": round(obs, 3),
                  "ci90": [round(c, 3) for c in ci], "p": round(p, 4), "is_diff": round(float(di), 3), "oos_diff": round(float(do), 3),
                  "n": len(P[a]), "grade": g})
    add("H3a", "BOK 인상기 KTB10−UST-UH <0", d("KTB10", "UST-UH")[hike], "<")
    add("H3b", "BOK 인상기 KTB10−UST-H <0", d("KTB10", "UST-H")[hike], "<")
    add("H4", "직전6개월 원화약세(사전) 다음달 UST-UH−KTB10 >0", d("UST-UH", "KTB10")[fxup_ex & fx6.notna()], ">")
    add("H5a", "전체 UST-UH−KTB10 (양측)", d("UST-UH", "KTB10"), "two")
    add("H5b", "전체 UST-H−KTB10 (양측)", d("UST-H", "KTB10"), "two")
    res["tests"] = H
    res["grade_rule"] = "rule_audit 규약: A=Bonferroni(0.05/11) 유의+IS(~2018)·OOS(2019~)·전체 같은 방향 / B=보정 유의 / C=p<0.10 / F / 검증전 n<8"
    out = ROOT / "reports/studies/ktb_vs_ust.json"
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1))
    print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
