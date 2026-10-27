"""이익 잠금 백테스트 — 반도체 비중 상한 초과분을 반등일에 덜기 (profit_lock).

python scripts/study_profit_lock.py [--prices PATH]  → reports/studies/profit_lock.json (+ 표준출력 요약)

공개 저장소 — 비율만. 포트 규모는 '시작일 하이닉스 1주 가격의 N배'(비율 파라미터)로만 다룬다.
사전 등록(결과 전 커밋 b6e0e552): docs/desk_kb/rounds/2026-10-28/quant_profit_lock.md §0 — 그 절을 바꾸지 않는다.
요지: 반도체 = 삼성전자·SK하이닉스 주식(시작 가치 50/50, 사이 리밸런싱 없음), 나머지 = 코스피200 가격지수.
2023-01-02 종가 시작(반도체 25%) ~ 2026-10-27. 규칙 BH · R25 · R26 · R25W · CAP25M · R25_CASH · R25_INT(N=50/200/1000).
반등일 = 코스피 종가 ≥ 전일 +0.5%, 체결 = 반등일 종가. 비용: 주식 매도 0.25%, K200 매수 0.05%.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CSV = ROOT / "data" / "deriv" / "daily.csv"
DETAIL = ROOT / "reports" / "detail" / "KR"
OUT = ROOT / "reports" / "studies" / "profit_lock.json"

SEMIS = ["005930.KS", "000660.KS"]
START = "2023-01-02"
END = "2026-10-27"
CRASH = ("2026-06-22", "2026-07-30")      # FRM 공식 구간
SELL_COST = 0.0025
BUY_COST = 0.0005
REBOUND = 0.005
W0 = 0.25
SIZES = [50, 200, 1000]


# ───────────────────────── 데이터 ─────────────────────────
def load(prices: Path | None = None) -> pd.DataFrame:
    from screener.prices import PARQUET, load_kr
    p = Path(prices) if prices else PARQUET
    if not p.exists():   # worktree 에는 kr_prices.parquet 가 없음 → 메인 체크아웃 저장본
        alt = ROOT.parents[2] / "data" / "kr_prices.parquet" if ".claude" in ROOT.parts else None
        if alt is not None and alt.exists():
            p = alt
    st = (load_kr(hist_from=2022, path=p).filter(pl.col("yf").is_in(SEMIS))
          .select("yf", "date", "close").to_pandas())
    st["date"] = pd.to_datetime(st["date"])
    px = st.pivot(index="date", columns="yf", values="close").sort_index()
    # 저장본 마지막 날 이후는 상세 리포트 c1y 로 잇는다(겹치는 날은 일치 확인)
    for yf in SEMIS:
        c1y = json.load(open(DETAIL / f"{yf[:6]}.json", encoding="utf-8"))["c1y"]
        s = pd.Series({pd.Timestamp(d): float(c) for d, c in c1y})
        ov = s.index.intersection(px.index)
        if len(ov):
            diff = (s[ov] / px.loc[ov, yf] - 1).abs().max()
            if diff > 0.002:
                raise SystemExit(f"{yf} c1y 와 저장본 불일치 {diff:.4f}")
        new = s[s.index > px[yf].dropna().index.max()]
        for d, v in new.items():
            px.loc[d, yf] = v
    px = px.sort_index()
    idx = pd.read_csv(CSV, usecols=["date", "kospi_close", "k200_close"]).dropna()
    idx["date"] = pd.to_datetime(idx["date"])
    df = idx.set_index("date").sort_index()
    df = df.join(px, how="left")
    df[SEMIS] = df[SEMIS].ffill()
    df = df.loc[(df.index >= pd.Timestamp(START) - pd.Timedelta(days=10)) & (df.index <= pd.Timestamp(END))]
    df["rebound"] = (df["kospi_close"].pct_change() >= REBOUND).fillna(False)
    d = df.index
    df["week_end"] = np.r_[(d[1:].isocalendar().week.values != d[:-1].isocalendar().week.values)
                           | (d[1:].year != d[:-1].year), True]
    df["month_end"] = np.r_[d[1:].month != d[:-1].month, True]
    df = df.loc[df.index >= pd.Timestamp(START)]
    if df[SEMIS].isna().any().any():
        raise SystemExit("반도체 가격 결측")
    return df


# ───────────────────────── 시뮬레이션 ─────────────────────────
def simulate(df: pd.DataFrame, rule: str, *, cap: float = 0.25, i0: int = 0, size: int | None = None,
             to_cash: bool = False) -> dict:
    """i0 종가에 순자산 1.0(반도체 W0 = 삼성·하이닉스 가치 50/50) 시작. size 가 있으면 주식 수량 온주.
    rule: BH | R(매일 점검, 반등일 덜기) | RW(주말 점검, 반등일 덜기) | CAPM(월말 초과분 즉시 매도)."""
    P = df[SEMIS].values            # 0=삼성, 1=하이닉스 (컬럼 순서 SEMIS)
    K = df["k200_close"].values
    reb = df["rebound"].values; wend = df["week_end"].values; mend = df["month_end"].values
    dates = df.index
    nav0 = 1.0
    unit = nav0 / size if size else None            # 하이닉스 1주 = 시작 순자산 / size
    scale = (unit / P[i0, 1]) if size else 1.0       # 가격 → 순자산 단위 환산
    sh = np.array([W0 * 0.5 / (P[i0, 0] * scale), W0 * 0.5 / (P[i0, 1] * scale)])
    if size:
        sh = np.floor(sh)
    k_units = (nav0 - float(sh @ P[i0]) * scale) / K[i0]
    cash = 0.0
    pending = False
    nav, wts, trades = [], [], []
    for i in range(i0, len(df)):
        sv = float(sh @ P[i]) * scale
        tot = sv + k_units * K[i] + cash
        w = sv / tot
        if i > i0 and rule != "BH":
            if rule == "CAPM":
                go = mend[i] and w > cap
            else:
                if (rule == "R" or wend[i]) and w > cap:
                    pending = True
                go = pending and reb[i] and w > cap
                if pending and w <= cap:
                    pending = False
            if go:
                excess = sv - cap * tot
                vals = sh * P[i] * scale
                sell = excess * vals / sv                     # 종목별 가치 비중대로
                q = sell / (P[i] * scale)
                if size:
                    q = np.floor(q + 1e-9)
                if q.sum() > 0:
                    proceeds = float(q @ P[i]) * scale
                    sh = sh - q
                    net = proceeds * (1 - SELL_COST)
                    if to_cash:
                        cash += net
                    else:
                        k_units += net * (1 - BUY_COST) / K[i]
                    trades.append({"date": str(dates[i].date()), "w_before": round(w, 4),
                                   "sold_pct_nav": round(proceeds / tot, 4), "shares": [int(x) for x in q] if size else None})
                    pending = False
                    sv = float(sh @ P[i]) * scale
                    tot = sv + k_units * K[i] + cash
                    w = sv / tot
                # 온주 0주면 대기 유지(pending 그대로)
        nav.append(tot); wts.append(w)
    nav = pd.Series(nav, index=dates[i0:]); wts = pd.Series(wts, index=dates[i0:])
    return {"nav": nav, "w": wts, "trades": trades}


def metrics(r: dict) -> dict:
    nav, w = r["nav"], r["w"]
    n = len(nav)
    yrs = (nav.index[-1] - nav.index[0]).days / 365.25
    cum = nav.iloc[-1] / nav.iloc[0] - 1
    cagr = (nav.iloc[-1] / nav.iloc[0]) ** (1 / yrs) - 1 if yrs > 0 else float("nan")
    peak = nav.cummax(); dd = nav / peak - 1
    mdd = float(dd.min()); trough = dd.idxmin()
    peak_date = nav.loc[:trough].idxmax()
    # 최장 수중 기간(거래일)
    under = (dd < -1e-12).values
    longest, cur, ongoing = 0, 0, False
    for u in under:
        cur = cur + 1 if u else 0
        longest = max(longest, cur)
    ongoing = bool(under[-1]) and cur == longest
    rec = nav.loc[trough:]; hit = rec[rec >= nav.loc[peak_date]]
    a, b = pd.Timestamp(CRASH[0]), pd.Timestamp(CRASH[1])
    seg = nav.loc[a:b]
    crash = float(seg.iloc[-1] / seg.iloc[0] - 1) if len(seg) > 1 else None
    seg_dd = float((seg / seg.cummax() - 1).min()) if len(seg) > 1 else None
    crash_low = seg.min() if len(seg) else None
    pre = nav.loc[:a]
    since = float(nav.iloc[-1] / crash_low - 1) if crash_low else None
    reclaim = float((nav.iloc[-1] - crash_low) / (pre.max() - crash_low)) if crash_low and pre.max() > crash_low else None
    return {
        "cum": float(cum), "cagr": float(cagr), "mdd": mdd, "calmar": float(cagr / abs(mdd)) if mdd < 0 else None,
        "mdd_peak": str(peak_date.date()), "mdd_trough": str(trough.date()),
        "mdd_recovered": str(hit.index[0].date()) if len(hit) else None,
        "longest_underwater_days": int(longest), "underwater_ongoing": ongoing,
        "crash_ret": crash, "crash_window_dd": seg_dd,
        "w_crash_start": float(r["w"].loc[:a].iloc[-1]) if len(r["w"].loc[:a]) else None,
        "from_crash_low": since, "reclaim_of_prior_peak": reclaim,
        "trims": len(r["trades"]), "w_end": float(w.iloc[-1]), "w_max": float(w.max()), "w_mean": float(w.mean()),
        "n_days": n,
    }


def verdict(m: dict) -> dict:
    bh, r, cm = m["BH"], m["R25"], m["CAP25M"]
    p1 = (r["crash_ret"] - bh["crash_ret"]) >= 0.02
    p2 = (r["mdd"] - bh["mdd"]) >= 0.03 and r["longest_underwater_days"] <= bh["longest_underwater_days"]
    p3 = r["calmar"] is not None and bh["calmar"] is not None and r["calmar"] >= 0.9 * bh["calmar"]
    p4 = r["trims"] <= cm["trims"] and abs(r["crash_ret"] - cm["crash_ret"]) <= 0.005
    if p1 and p2 and p3:
        v = "유효(위험 통제 장치)"
    elif p1 and p2:
        v = "보호는 되나 비용 큼"
    elif not p1:
        v = "무효"
    else:
        v = "부분(P1만)"
    return {"P1": bool(p1), "P2": bool(p2), "P3": bool(p3), "P4": bool(p4), "verdict": v}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prices", default=None)
    a = ap.parse_args()
    df = load(a.prices)
    runs = {
        "BH": simulate(df, "BH"),
        "R25": simulate(df, "R", cap=0.25),
        "R26": simulate(df, "R", cap=0.26),
        "R25W": simulate(df, "RW", cap=0.25),
        "CAP25M": simulate(df, "CAPM", cap=0.25),
        "R25_CASH": simulate(df, "R", cap=0.25, to_cash=True),
    }
    for n in SIZES:
        runs[f"R25_INT{n}"] = simulate(df, "R", cap=0.25, size=n)
        runs[f"BH_INT{n}"] = simulate(df, "BH", size=n)
    m = {k: metrics(v) for k, v in runs.items()}
    v = verdict(m)
    # 강건성: 2023-01~2025-12 매월 첫 거래일 시작 36개 경로
    starts = [i for i in range(len(df)) if (i == 0 or df.index[i].month != df.index[i - 1].month)
              and df.index[i] <= pd.Timestamp("2025-12-31")]
    rob = []
    for i0 in starts:
        b = metrics(simulate(df, "BH", i0=i0)); r = metrics(simulate(df, "R", cap=0.25, i0=i0))
        rob.append({"start": str(df.index[i0].date()), "bh_mdd": b["mdd"], "r_mdd": r["mdd"], "bh_cum": b["cum"],
                    "r_cum": r["cum"], "bh_crash": b["crash_ret"], "r_crash": r["crash_ret"], "trims": r["trims"]})
    share = float(np.mean([x["r_mdd"] > x["bh_mdd"] for x in rob]))
    # 온주 무해 판정
    intg = {}
    for n in SIZES:
        q = m[f"R25_INT{n}"]; f = m["R25"]
        intg[n] = {"d_cum": q["cum"] - f["cum"], "d_mdd": q["mdd"] - f["mdd"], "d_crash": q["crash_ret"] - f["crash_ret"],
                   "harmless": all(abs(x) <= 0.005 for x in (q["cum"] - f["cum"], q["mdd"] - f["mdd"], q["crash_ret"] - f["crash_ret"])),
                   "trims": q["trims"], "hynix_share_of_nav_end": float(df[SEMIS[1]].iloc[-1] / df[SEMIS[1]].iloc[0] / n
                                                                        / runs[f"R25_INT{n}"]["nav"].iloc[-1])}
    # 구간 보조: 반도체 바스켓·코스피200 자체
    sem = (df[SEMIS] / df[SEMIS].iloc[0]).mean(axis=1)
    k2 = df["k200_close"] / df["k200_close"].iloc[0]
    a_, b_ = pd.Timestamp(CRASH[0]), pd.Timestamp(CRASH[1])
    ctx = {"semis_cum": float(sem.iloc[-1] - 1), "k200_cum": float(k2.iloc[-1] - 1),
           "semis_crash": float(sem.loc[b_] / sem.loc[a_] - 1), "k200_crash": float(k2.loc[b_] / k2.loc[a_] - 1),
           "semis_mdd": float((sem / sem.cummax() - 1).min()), "k200_mdd": float((k2 / k2.cummax() - 1).min()),
           "rebound_days": int(df["rebound"].sum()), "days": len(df),
           "first": str(df.index[0].date()), "last": str(df.index[-1].date())}
    out = {"study": "profit_lock", "prereg": "docs/desk_kb/rounds/2026-10-28/quant_profit_lock.md §0 (commit b6e0e552)",
           "params": {"start": START, "end": END, "w0": W0, "crash": CRASH, "sell_cost": SELL_COST, "buy_cost": BUY_COST,
                      "rebound": REBOUND, "sizes": SIZES, "m": 6},
           "context": ctx, "metrics": m, "verdict": v,
           "robust": {"n": len(rob), "share_r_mdd_better": share, "robust": share >= 0.75, "paths": rob},
           "integer": intg,
           "trades_R25": runs["R25"]["trades"], "trades_R25_INT200": runs["R25_INT200"]["trades"],
           "grade_cap": "C (단일 경로·검정 없음)"}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    print(json.dumps(ctx, ensure_ascii=False))
    cols = ["cum", "cagr", "mdd", "calmar", "longest_underwater_days", "underwater_ongoing", "crash_ret", "crash_window_dd",
            "w_crash_start", "reclaim_of_prior_peak", "trims", "w_end", "w_max", "mdd_peak", "mdd_trough", "mdd_recovered"]
    print(pd.DataFrame(m).T[cols].to_string())
    print(v); print("robust", share, len(rob)); print(json.dumps(intg, ensure_ascii=False, default=float))


if __name__ == "__main__":
    main()
