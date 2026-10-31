#!/usr/bin/env python3
"""추세 규칙 검증(2026-10-31) — 사전등록 reports/studies/2026-10-31_trend_rule.md §0 (커밋 d685885f4).

(§0-보정 EW 업종) S1 업종 12-1 상위 1/3 · S2 업종 52주 고점 근접 · S3 S1+절대 필터(현금) · D1 업종 하락추세 거르기 ·
D2 종목 하락추세 거르기 · C1 코어 5자산 절대 필터 vs 고정. 21거래일 비중첩 격자, t+1 종가 진입.

  python3 scripts/study_trend_rule.py   → reports/studies/2026-10-31_trend_rule.json
"""
from __future__ import annotations

import glob
import json
import math
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports/studies/2026-10-31_trend_rule.json"
H = 21
LB = 252
SKIP = 21
IS_END = "2019-12-31"
OOS_START = "2020-01-01"
M = 6
ALPHA = 0.05 / M
T_CRIT = 2.39
COST_RT_SECTOR = 0.0025
COST_OW_CORE = 0.0010
# §0-보정: KRX: 업종 계열 결함(코스피·코스닥 같은 이름 섞임 추정) → EW:<업종> 합성지수, 비반도체 23개
SECTORS = ["IT 서비스", "건설", "금속", "금융", "기계·장비", "기타금융", "기타제조", "보험", "비금속", "섬유·의류",
           "오락·문화", "운송·창고", "운송장비·부품", "유통", "음식료·담배", "의료·정밀기기", "일반서비스", "전기·가스",
           "제약", "종이·목재", "증권", "통신", "화학"]
PREFIX = "EW:"
N_TOPIC = 207
# 1차(§0 원정의, KRX: 계열) OOS 결과 — 데이터 결함으로 무효·인용 금지, 기록만
VOID_RUN1 = {"S1": {"OOS_mean": 0.13492, "t": 0.84}, "S2": {"OOS_mean": -0.41011, "t": -2.72},
             "S3": {"OOS_mean": -0.40201, "t": -3.27}, "D1": {"OOS_mean": -0.30803, "t": -1.08},
             "why": "KRX: 업종 일간 |수익|>20% 연 1,100~1,300건(예 비금속 +5,280%/일) — 수익 단위가 비율 수십 배로 깨짐"}


def ncdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def summ(s: pd.Series) -> dict:
    s = s.dropna()
    n = len(s)
    if n < 2:
        return {"n": n}
    m, sd = s.mean(), s.std(ddof=1)
    t = m / (sd / math.sqrt(n)) if sd > 0 else float("nan")
    return {"n": n, "mean": round(m, 5), "median": round(float(s.median()), 5), "t": round(t, 2),
            "p_one": round(1 - ncdf(t), 5), "hit": round(float((s > 0).mean()), 3)}


def split(s: pd.Series) -> dict:
    s = s.dropna()
    return {"ALL": summ(s), "IS": summ(s[s.index <= IS_END]), "OOS": summ(s[s.index >= OOS_START]),
            "Y2022": summ(s[(s.index >= "2022-01-01") & (s.index <= "2022-12-31")])}


def grade(r: dict, cap: str | None = None) -> str:
    o, i, y = r["OOS"], r["IS"], r["Y2022"]
    if o.get("n", 0) < 30:
        return "검증전"
    om, ot = o["mean"], o["t"]
    if om > 0 and ot >= T_CRIT and i.get("mean", -1) > 0:
        g = "A" if (i["t"] >= T_CRIT and y.get("mean", -1) > 0) else "B"
        if cap == "B" and g == "A":
            g = "B"
    elif om > 0 and ot >= 1.645:
        g = "C"
    elif om < 0 and ot <= -1.645:
        g = "C(역방향)"
    else:
        g = "F"
    return g


def perf(r: pd.Series, per_year: float) -> dict:
    r = r.dropna()
    if len(r) < 2:
        return {}
    w = (1 + r).cumprod()
    yrs = len(r) / per_year
    cagr = w.iloc[-1] ** (1 / yrs) - 1
    vol = r.std(ddof=1) * math.sqrt(per_year)
    mdd = float((w / w.cummax() - 1).min())
    return {"cagr": round(cagr, 4), "vol": round(vol, 4), "sharpe": round(r.mean() * per_year / vol, 2) if vol else None,
            "mdd": round(mdd, 4)}


def dsr(sr_ann: float, n_obs: int, per_year: float, n_trials: int, skew=0.0, kurt=3.0) -> float | None:
    """Bailey & López de Prado 2014 근사. 시도 간 샤프 분산 = 1/n_obs(귀무) 가정."""
    if sr_ann is None or n_obs < 10:
        return None
    sr = sr_ann / math.sqrt(per_year)
    var_sr = 1 / n_obs
    g = 0.5772156649
    from statistics import NormalDist
    nd = NormalDist()
    e_max = math.sqrt(var_sr) * ((1 - g) * nd.inv_cdf(1 - 1 / n_trials) + g * nd.inv_cdf(1 - 1 / (n_trials * math.e)))
    den = math.sqrt(max(1e-12, 1 - skew * sr + (kurt - 1) / 4 * sr ** 2))
    z = (sr - e_max) * math.sqrt(n_obs - 1) / den
    return round(nd.cdf(z), 3)


# ---------------- 업종 ----------------
def sector_panel() -> pd.DataFrame:
    d = pd.read_parquet(ROOT / "data/hist/kr_sector_daily.parquet")
    d = d[d.symbol.isin([PREFIX + s for s in SECTORS])]
    p = d.pivot(index="date", columns="symbol", values="close").sort_index()
    p.index = pd.to_datetime(p.index)
    return p.ffill()


def sector_tests(p: pd.DataFrame) -> tuple[dict, dict]:
    idx = p.index
    grid = list(range(LB, len(idx) - H - 1, H))
    sma200 = p.rolling(200).mean()
    hi252 = p.rolling(LB).max().shift(1)
    rows = []
    prev_w = {k: None for k in ("S1", "S2", "S3", "BM")}
    for gi in grid:
        t = idx[gi]
        e, x = gi + 1, gi + 1 + H
        fwd = p.iloc[x] / p.iloc[e] - 1
        mom = p.iloc[gi - SKIP] / p.iloc[gi - LB] - 1
        r12 = p.iloc[gi] / p.iloc[gi - LB] - 1
        up200 = p.iloc[gi] > sma200.iloc[gi]
        near = p.iloc[gi] / hi252.iloc[gi] >= 0.95
        valid = fwd.dropna().index.intersection(mom.dropna().index)
        if len(valid) < 15:
            continue
        k = len(valid) // 3
        top = mom[valid].sort_values(ascending=False).index[:k]
        bm_w = pd.Series(1 / len(valid), index=valid)
        w1 = pd.Series(1 / k, index=top)
        keep = [s for s in top if r12[s] > 0 and up200[s]]
        w3 = pd.Series(1 / k, index=keep) if keep else pd.Series(dtype=float)
        nr = near[valid][near[valid]].index
        w2 = pd.Series(1 / len(nr), index=nr) if len(nr) else None

        def ret_cost(w, key):
            if w is None:
                prev_w[key] = None
                return np.nan
            r = float((w * fwd.reindex(w.index)).sum())
            pw = prev_w[key]
            allk = w.index.union(pw.index) if pw is not None else w.index
            # 직전 보유가 21일 동안 표류한 비중은 무시(근사): 목표 비중 차의 합 = 회전
            to = float((w.reindex(allk, fill_value=0) - (pw.reindex(allk, fill_value=0) if pw is not None else 0)).abs().sum())
            if pw is None:
                to = float(w.sum())
            prev_w[key] = w
            return r - to * COST_RT_SECTOR / 2, to

        bm = ret_cost(bm_w, "BM")
        s1 = ret_cost(w1, "S1")
        s2 = ret_cost(w2, "S2")
        s3 = ret_cost(w3 if len(w3) else pd.Series(dtype=float), "S3")
        dn = valid[(p.iloc[gi][valid] < sma200.iloc[gi][valid]).values & (r12[valid] < 0).values]
        ok = valid.difference(dn)
        d1 = float(fwd[ok].mean() - fwd[dn].mean()) if len(dn) and len(ok) else np.nan
        rows.append({"date": t, "bm": bm[0], "s1": s1[0], "s1_to": s1[1], "s2": s2 if not isinstance(s2, tuple) else s2[0],
                     "s2_n": len(nr), "s3": s3[0], "s3_to": s3[1], "s3_inv": float(w3.sum()) if len(w3) else 0.0,
                     "d1": d1, "n_down": len(dn), "n_valid": len(valid), "bm_raw": float(fwd[valid].mean())})
    df = pd.DataFrame(rows).set_index("date")
    df.index = df.index.strftime("%Y-%m-%d")
    res = {}
    for key in ("s1", "s2", "s3"):
        ex = df[key] - df["bm"]
        res[key.upper()] = {"effect": split(ex), "perf_strat": perf(df[key], 12), "perf_bm": perf(df["bm"], 12)}
    res["S1"]["turnover_per_year"] = round(df.s1_to.mean() * 12, 2)
    res["S3"]["turnover_per_year"] = round(df.s3_to.mean() * 12, 2)
    res["S3"]["avg_invested"] = round(df.s3_inv.mean(), 3)
    res["S2"]["grid_with_signal"] = int(df.s2.notna().sum())
    res["D1"] = {"effect": split(df["d1"]), "avg_down_share": round((df.n_down / df.n_valid).mean(), 3)}
    for k in ("S1", "S2", "S3"):
        key = k.lower()
        res[k]["crash_2020_02_03"] = {d: round(float(df.loc[d, key] - df.loc[d, "bm"]), 4)
                                     for d in df.index if "2020-01-15" <= d <= "2020-03-31"}
    return res, {"grid_n": len(df), "first": df.index[0], "last": df.index[-1]}


# ---------------- 종목 ----------------
def stock_test() -> tuple[dict, dict]:
    sec = pd.read_csv(ROOT / "universe/kr_sector.csv", dtype=str)
    semi = set(sec[sec.sector.str.contains("전기", na=False) & sec.sector.str.contains("전자", na=False)].code)
    fr = []
    for f in sorted(glob.glob(str(ROOT / "data/hist/kr_20*.parquet"))):
        d = pd.read_parquet(f, columns=["yf", "date", "close", "volume"])
        fr.append(d)
    d = pd.concat(fr)
    d["code"] = d.yf.str[:6]
    d = d[~d.code.isin(semi)]
    c = d.pivot_table(index="date", columns="code", values="close").sort_index()
    v = d.pivot_table(index="date", columns="code", values="volume").sort_index()
    c.index = pd.to_datetime(c.index)
    v = v.reindex(c.index)
    val = (c * v).rolling(20, min_periods=15).mean()
    sma = c.rolling(200, min_periods=200).mean()
    idx = c.index
    rows = []
    for gi in range(LB, len(idx) - H - 1, H):
        e, x = gi + 1, gi + 1 + H
        px = c.iloc[gi]
        liq = (val.iloc[gi] >= 1e9) & (px >= 1000)
        r12 = px / c.iloc[gi - LB] - 1
        fwd = c.iloc[x] / c.iloc[e] - 1
        ok = liq & r12.notna() & sma.iloc[gi].notna() & c.iloc[e].notna()
        fwd = fwd.where(ok)
        # 상폐 등으로 x 일 종가 없으면 마지막 종가까지(정리매매 포함)
        last = c.iloc[e:x + 1].ffill().iloc[-1]
        fwd = (last / c.iloc[e] - 1).where(ok)
        dn = ok & (px < sma.iloc[gi]) & (r12 < 0)
        up = ok & ~dn
        if dn.sum() < 20 or up.sum() < 20:
            continue
        rows.append({"date": idx[gi].strftime("%Y-%m-%d"), "d2": float(fwd[up].mean() - fwd[dn].mean()),
                     "d2_med": float(fwd[up].median() - fwd[dn].median()), "n_dn": int(dn.sum()), "n_up": int(up.sum())})
    df = pd.DataFrame(rows).set_index("date")
    return {"effect": split(df.d2), "effect_median_diff": split(df.d2_med),
            "avg_n_down": round(df.n_dn.mean(), 1), "avg_n_up": round(df.n_up.mean(), 1)}, \
        {"grid_n": len(df), "first": df.index[0], "last": df.index[-1], "semi_codes_excluded": len(semi)}


# ---------------- 코어 ----------------
def core_test() -> tuple[dict, dict]:
    import yfinance as yf
    fx = yf.download("KRW=X", start="2009-01-01", end="2026-01-01", progress=False, auto_adjust=False)["Close"]
    if isinstance(fx, pd.DataFrame):
        fx = fx.iloc[:, 0]
    fx.index = pd.to_datetime(fx.index).tz_localize(None)
    us = pd.concat(pd.read_parquet(f, columns=["yf", "date", "close"]) for f in sorted(glob.glob(str(ROOT / "data/hist/us_20*.parquet"))))
    us = us[us.yf.isin(["SPY", "QQQ", "GLD"])].pivot_table(index="date", columns="yf", values="close")
    us.index = pd.to_datetime(us.index)
    et = pd.read_parquet(ROOT / "data/hist/kr_etf_daily.parquet")
    et = et[et.symbol.isin(["069500", "114260"])].pivot(index="date", columns="symbol", values="adj_close")
    et.index = pd.to_datetime(et.index)
    cal = et.index[et.index <= "2025-12-31"]
    fxa = fx.reindex(fx.index.union(cal)).ffill().reindex(cal)
    usa = us.reindex(us.index.union(cal)).ffill().reindex(cal)
    px = pd.DataFrame({"K200": et["069500"].reindex(cal), "KTB3": et["114260"].reindex(cal),
                       "SPX": usa.SPY * fxa, "NDX": usa.QQQ * fxa, "GOLD": usa.GLD * fxa}).ffill().dropna()
    sma = px.rolling(200).mean()
    idx = px.index
    rows = []
    pw_f = None
    pw_x = None
    on_hist = []
    for gi in range(LB, len(idx) - H - 1, H):
        e, x = gi + 1, gi + 1 + H
        fwd = px.iloc[x] / px.iloc[e] - 1
        r12 = px.iloc[gi] / px.iloc[gi - LB] - 1
        on = (r12 > 0) & (px.iloc[gi] > sma.iloc[gi])
        wx = pd.Series(0.2, index=px.columns)
        wf = wx.where(on, 0.0)
        cx = 0.0 if pw_x is None else float((wx - pw_x).abs().sum()) * COST_OW_CORE
        cf = float((wf - (pw_f if pw_f is not None else wx)).abs().sum()) * COST_OW_CORE
        if pw_f is None:
            cf = float((wf - wx).abs().sum()) * COST_OW_CORE
        rx = float((wx * fwd).sum()) - cx
        rf = float((wf * fwd).sum()) - cf
        pw_x, pw_f = wx, wf
        on_hist.append(on.to_dict())
        rows.append({"date": idx[gi].strftime("%Y-%m-%d"), "fixed": rx, "filt": rf, "invested": float(wf.sum())})
    df = pd.DataFrame(rows).set_index("date")
    eff = df.filt - df.fixed
    onf = pd.DataFrame(on_hist)
    res = {"effect": split(eff), "perf_fixed": perf(df.fixed, 12), "perf_filter": perf(df.filt, 12),
           "perf_fixed_OOS": perf(df.fixed[df.index >= OOS_START], 12), "perf_filter_OOS": perf(df.filt[df.index >= OOS_START], 12),
           "avg_invested": round(df.invested.mean(), 3), "on_share_by_asset": {k: round(float(onf[k].mean()), 3) for k in onf},
           "y2022": {"fixed": round(float((1 + df.fixed[(df.index >= "2022-01-01") & (df.index <= "2022-12-31")]).prod() - 1), 4),
                     "filter": round(float((1 + df.filt[(df.index >= "2022-01-01") & (df.index <= "2022-12-31")]).prod() - 1), 4)},
           "y2020_q1": {"fixed": round(float((1 + df.fixed[(df.index >= "2020-01-15") & (df.index <= "2020-03-31")]).prod() - 1), 4),
                        "filter": round(float((1 + df.filt[(df.index >= "2020-01-15") & (df.index <= "2020-03-31")]).prod() - 1), 4)}}
    return res, {"grid_n": len(df), "first": df.index[0], "last": df.index[-1], "assets": list(px.columns),
                 "fx": "yahoo KRW=X (실행 시 내려받음)", "us_dividends": "미포함(SPY·QQQ·GLD 종가)"}


def main():
    p = sector_panel()
    sec, sec_meta = sector_tests(p)
    stk, stk_meta = stock_test()
    core, core_meta = core_test()
    hyp = {"S1": sec["S1"], "S2": sec["S2"], "S3": sec["S3"], "D1": sec["D1"], "D2": stk, "C1": core}
    grades = {k: grade(v["effect"], cap=None if k == "C1" else "B") for k, v in hyp.items()}
    for k in ("S1", "S3"):
        sr = hyp[k]["perf_strat"].get("sharpe")
        hyp[k]["dsr_strat"] = dsr(sr, hyp[k]["effect"]["ALL"]["n"], 12, N_TOPIC)
    hyp["C1"]["dsr_filter"] = dsr(core["perf_filter"].get("sharpe"), core["effect"]["ALL"]["n"], 12, N_TOPIC)
    out = {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "asof": "2026-10-31",
        "prereg": {"doc": "reports/studies/2026-10-31_trend_rule.md §0", "commit": "d685885f4", "m": M,
                   "alpha_bonf": round(ALPHA, 5), "t_crit_one_sided": T_CRIT, "is_end": IS_END, "oos_start": OOS_START,
                   "hold_days": H, "cost": {"sector_round_trip": COST_RT_SECTOR, "core_one_way": COST_OW_CORE,
                                            "filters_D1_D2": "없음(같은 날 두 집단 차)"},
                   "topic": "trend_sim", "topic_N_after": N_TOPIC, "alpha_N": round(0.05 / N_TOPIC, 5),
                   "sectors": SECTORS, "sector_source": "kr_sector_daily EW:<업종> (§0-보정 커밋 61705edfb)", "void_run1": VOID_RUN1,
                   "grade_cap": {"S1": "B", "S2": "B", "S3": "B", "D1": "B", "D2": "B"}},
        "survivorship": {"sector": "EW 합성 = 현재 분류 종목만(상폐 종목 분류 없으면 빠짐) → 위로 치우칠 수 있음, 업종 간 상대는 일부 상쇄", "D2": "상폐 포함 원천, 정리매매 봉 포함(하락 집단 꼬리↑ 가능)",
                         "core": "ETF·지수 — 작음"},
        "meta": {"sector": sec_meta, "stock": stk_meta, "core": core_meta},
        "results": hyp,
        "grades": grades,
        "dsr": {"S1": hyp["S1"]["dsr_strat"], "S3": hyp["S3"]["dsr_strat"], "C1_filter": hyp["C1"]["dsr_filter"],
                "note": "Bailey·López de Prado 2014 근사, 전략 자체 연 샤프 기준(초과 아님), 시도 N = 주제 N"},
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    for k, v in hyp.items():
        print(k, grades[k], json.dumps(v["effect"], ensure_ascii=False))


if __name__ == "__main__":
    main()
