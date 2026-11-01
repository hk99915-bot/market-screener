#!/usr/bin/env python3
"""변동성 매도·보험 전략 빠른 모의 3종(커버드콜 · 숏 스트랭글 vs 아이언 콘도르 · 칼라) — 파생 데스크 2026-11-01.
**모의·교육용, 실계좌 불가.** 사전등록: docs/desk_kb/rounds/2026-11-01/derivs_strategy_map.md §0.

  python3 scripts/study_vol_strategies.py [--print]

가격·사이클·IV·비용은 scripts/study_gamma_scalp.py 와 같은 정의(BS r=q=0, IV=rep_iv, 월물 둘째 목요일, 반호가 max(1틱,1.5%)).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import study_gamma_scalp as g  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "studies" / "2026-11-01_vol_strategies.json"
M = 4
ALPHA = 0.05 / M

# (권리, 머니니스, 수량: +매수/−매도)
LEGS = {
    "CC": [("C", 1.02, -1)],
    "SS": [("P", 0.95, -1), ("C", 1.05, -1)],
    "IC": [("P", 0.95, -1), ("C", 1.05, -1), ("P", 0.90, +1), ("C", 1.10, +1)],
    "COL": [("P", 0.95, +1), ("C", 1.05, -1)],
}
HOLDS_INDEX = {"CC": True, "COL": True, "SS": False, "IC": False}
SKEW_ADJ = {("P", 0.95): 3.0, ("P", 0.90): 5.0, ("C", 1.02): -1.0, ("C", 1.05): -1.0, ("C", 1.10): -2.0}


def bs(right: str, s: float, k: float, t: float, vol: float) -> float:
    p, _, _ = g.bs_put(s, k, t, vol)
    return p + s - k if right == "C" else p      # 패리티(r=q=0)


def cycle(d: pd.DataFrame, i0: int, i1: int, strat: str, cost_mult: float, skew: bool) -> dict:
    s0, s1 = d.k200_close[i0], d.k200_close[i1]
    t = (d.date[i1] - d.date[i0]).days / 365.0
    iv = d.rep_iv[i0]
    opt_pnl = cost = prem_net = 0.0
    for right, mny, q in LEGS[strat]:
        k = round(s0 * mny / g.GRID) * g.GRID
        vol = (iv + (SKEW_ADJ.get((right, mny), 0.0) if skew else 0.0)) / 100
        p = bs(right, s0, k, t, vol)
        pay = max(s1 - k, 0.0) if right == "C" else max(k - s1, 0.0)
        opt_pnl += q * (pay - p)
        prem_net += -q * p
        cost += max(g.tick(p), p * g.OPT_HALF_SPREAD) * cost_mult
    idx = (s1 - s0) if HOLDS_INDEX[strat] else 0.0
    return {"entry": d.date[i0].strftime("%Y-%m-%d"), "expiry": d.date[i1].strftime("%Y-%m-%d"),
            "iv": round(iv, 2), "k200_ret_pct": round((s1 / s0 - 1) * 100, 4),
            "prem_net_pct": round(prem_net / s0 * 100, 4),
            "pnl_pct": round((idx + opt_pnl - cost) / s0 * 100, 4), "cost_pct": round(cost / s0 * 100, 4)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--print", action="store_true")
    a = ap.parse_args()
    d = g.load()
    ex = g.expiries(d)
    pairs = list(zip(ex[:-1], ex[1:]))
    runs = {}
    for s in LEGS:
        for cm in (0.0, 1.0, 2.0):
            runs[f"{s}_x{cm:g}"] = pd.DataFrame([cycle(d, i0, i1, s, cm, False) for i0, i1 in pairs])
        runs[f"{s}_skew"] = pd.DataFrame([cycle(d, i0, i1, s, 1.0, True) for i0, i1 in pairs])
    base = runs["SS_x1"]
    entry = pd.to_datetime(base.entry)
    is_m = (entry <= g.IS_END).to_numpy()
    k200 = base.k200_ret_pct.to_numpy()

    def series(key: str, excess: bool) -> np.ndarray:
        x = runs[key].pnl_pct.to_numpy()
        return x - k200 if excess else x

    hyp = {"H1_CC_minus_K200": ("CC", True), "H2_SS": ("SS", False), "H3_IC": ("IC", False),
           "H4_COL_minus_K200": ("COL", True)}
    H, grades, reverse = {}, {}, {}
    for h, (s, ex_) in hyp.items():
        x = series(f"{s}_x1", ex_)
        all_, is_, oos = g.summ(x), g.summ(x[is_m]), g.summ(x[~is_m])
        x2 = g.summ(series(f"{s}_x2", ex_))
        H[h] = {"all": all_, "is": is_, "oos": oos, "cost_x0": g.summ(series(f"{s}_x0", ex_)), "cost_x2": x2,
                "skew_adj": g.summ(series(f"{s}_skew", ex_)), "dsr": g.dsr(x, 7)}
        grades[h] = g.grade(all_["p_one_sided"], all_["n"], is_["mean"], oos["mean"], x2["mean"])
        if all_["t_nw1"] is not None:
            reverse[h] = "역방향 p " + str(round(g.ncdf(all_["t_nw1"]), 5))

    # 절대 수준 서술(전략 자체 손익 분포)
    levels = {s: g.summ(runs[f"{s}_x1"].pnl_pct.to_numpy()) for s in LEGS}
    levels["K200"] = g.summ(k200)
    for s in ("CC", "COL"):
        levels[s + "_skew"] = g.summ(runs[f"{s}_skew"].pnl_pct.to_numpy())
    # 상승 포착(K200 상승 사이클에서 CC·COL 이 가져간 비율), 하락 완충
    up, dn = k200 > 0, k200 < 0
    capture = {s: {"up_capture": round(float(runs[f"{s}_x1"].pnl_pct[up].sum() / k200[up].sum()), 3),
                   "down_capture": round(float(runs[f"{s}_x1"].pnl_pct[dn].sum() / k200[dn].sum()), 3)}
               for s in ("CC", "COL")}
    # 국면
    regimes = {}
    for nm, (a0, a1) in g.REGIMES.items():
        msk = ((entry >= a0) & (entry <= a1)).to_numpy()
        r = {"n": int(msk.sum()), "K200_sum": round(float(k200[msk].sum()), 3)}
        for s in LEGS:
            r[s + "_sum"] = round(float(runs[f"{s}_x1"].pnl_pct[msk].sum()), 3)
            r[s + "_worst"] = round(float(runs[f"{s}_x1"].pnl_pct[msk].min()), 3)
        r["loo"] = {h: g.summ(series(f"{s}_x1", ex_)[~msk])["mean"] for h, (s, ex_) in hyp.items()}
        r["loo_t"] = {h: g.summ(series(f"{s}_x1", ex_)[~msk])["t_nw1"] for h, (s, ex_) in hyp.items()}
        regimes[nm] = r
    # 꼬리 비교 SS vs IC
    ss, ic = runs["SS_x1"].pnl_pct.to_numpy(), runs["IC_x1"].pnl_pct.to_numpy()
    worst5 = runs["SS_x1"].assign(IC=ic).nsmallest(5, "pnl_pct")[["entry", "iv", "k200_ret_pct", "pnl_pct", "IC"]]
    tail = {"SS_worst5": worst5.round(3).to_dict("records"),
            "share_of_total_loss_top5_SS": round(float(-worst5.pnl_pct.sum() / max(1e-9, -ss[ss < 0].sum())), 3),
            "SS_prem_mean_pct": round(float(runs["SS_x1"].prem_net_pct.mean()), 3),
            "IC_prem_mean_pct": round(float(runs["IC_x1"].prem_net_pct.mean()), 3),
            "CC_prem_mean_pct": round(float(runs["CC_x1"].prem_net_pct.mean()), 3),
            "COL_prem_mean_pct": round(float(runs["COL_x1"].prem_net_pct.mean()), 3)}
    yearly = pd.DataFrame({"year": entry.dt.year, "K200": k200, **{s: runs[f"{s}_x1"].pnl_pct for s in LEGS}}) \
        .groupby("year").sum().round(2).reset_index().to_dict("records")

    out = {
        "study": "2026-11-01_vol_strategies", "generated": "2026-11-01", "asof": d.date.iloc[-1].strftime("%Y-%m-%d"),
        "label": "모의·교육용, 실계좌 불가(옵션 화이트리스트 밖·공매도 2027-04-15까지 금지). 매매 지시 아님.",
        "m": M,
        "prereg": {"doc": "docs/desk_kb/rounds/2026-11-01/derivs_strategy_map.md §0", "m": M, "alpha_bonf": round(ALPHA, 5),
                   "is_end": g.IS_END, "oos_start": "2020-01-01",
                   "legs": {k: [list(x) for x in v] for k, v in LEGS.items()},
                   "cost": {"opt_half_spread": "다리마다 max(1틱, 프리미엄×1.5%)", "index_hold": 0, "sens": [0, 1, 2]},
                   "skew_sens": {f"{k[0]}{k[1]}": v for k, v in SKEW_ADJ.items()},
                   "pricing": "BS r=q=0 단일 IV(rep_iv), 만기 보유·현금정산",
                   "grade_rule": "gamma_scalp 와 동일 · 상한 B",
                   "topic_N_note": "vol_premium 태그 N 3(이전) + m 4 = 7 → α(N) 0.0071 · hf_ls_vol 포함 9 → 0.0056"},
        "survivorship": "해당 없음(지수 단일 기초) — 모형 편향: 스큐 미반영(민감도 skew_adj 로 서술)",
        "grades": grades, "reverse_direction": reverse, "hypotheses_detail": H,
        "levels": levels, "capture": capture, "regimes": regimes, "tail": tail, "yearly": yearly,
        "limits": ["BS·단일 IV(스큐 민감도만)", "rep_iv 대용", "OTM 반호가 1.5% 가정(실제 더 넓을 수 있음)",
                   "가격지수(배당 제외)", "증거금·강제청산 미반영(SS)", "만기 보유만(조기 청산·롤 관리 없음)"],
    }
    if a.print:
        print(json.dumps({"grades": grades, "reverse": reverse, "capture": capture, "tail": tail}, ensure_ascii=False, indent=1))
        for h, v in H.items():
            print(h, {k: (vv if k == "dsr" else {x: vv.get(x) for x in ("n", "mean", "median", "t_nw1", "p_one_sided", "win")}) for k, vv in v.items()})
        for s, v in levels.items():
            print("level", s, v)
        for k, v in regimes.items():
            print(k, v)
        print(pd.DataFrame(yearly).to_string())
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
