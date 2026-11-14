"""가설 ① VRP 반등 필터 — 사전등록 백테스트 (연구 전용, 매매 지시 아님).

python3 scripts/study_vrp_rebound_filter.py     → reports/studies/2026-11-14_vrp_rebound_filter.json

## §0 사전등록 (결과 보기 전에 이 파일을 커밋한다)
- 주제: 반등 진입 — crash_entry (현재 시도 N 100, 주제 α 0.0005 · 이 연구 m=2 추가, kb:quant#30)
- 데이터: `data/deriv/daily.csv` (코스피 일봉 + rep_iv 대표 내재변동성, 2010-01-04~)
- 지표: IV = rep_iv(연율 %), RV20 = 20거래일 로그수익률 표준편차 × √252
        VRP(분산) = (IV/100)² − (RV20/100)²   /  VRP(변동성) = IV − RV20
- 사건(반등 구간): 20일 고점 대비 낙폭 ≤ −5% 인 상태에서 당일 수익률 > 0 (반등 신호일)
- 진입: 사건일 종가. 성과: 이후 5거래일 수익률(종가→종가)
- 가설 m=2, α=0.05/2=0.025 (단측)
  H1: VRP > 0 그룹의 5일 수익률 평균이 VRP ≤ 0 그룹보다 크다        (Welch 단측)
  H2: VRP > 0 그룹의 5일 승률이 50%보다 크다                         (단측 t)
- 분할: IS ≤ 2019-12-31 / OOS ≥ 2020-01-01
- 등급: scripts/study_rule_audit.grade() 와 같은 규칙 —
        A=Bonferroni 통과 + IS·OOS 같은 방향 · B=Bonferroni 통과, 하위 구간 방향 불일치
        C=방향만(보정 전 p<0.10) · F=현행과 구별 안 됨 · 검증전=표본 부족
- 탐색(등급 대상 아님, `exploratory`): 단일 급락일(−2%) 사건, 깊은 조정(−7%) 사건,
        VRP 변동성형(IV−RV), 지평 10일. **결과를 본 뒤 주 가설을 바꾸지 않는다.**
"""
from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from screener import vrp_filter as vf  # noqa: E402

CSV = ROOT / "data" / "deriv" / "daily.csv"
OUT = ROOT / "reports" / "studies" / "2026-11-14_vrp_rebound_filter.json"

M = 2
ALPHA = 0.05 / M
IS_END = "2019-12-31"
HORIZON = 5
DROP_DD = -0.05


def grade(p, subs: dict[str, float | None], n: int, alpha: float = ALPHA) -> tuple[str, str]:
    """등급 규칙 — scripts/study_rule_audit.grade() 와 동일한 문턱(여기선 표본 n 만 추가 확인)."""
    if p is None or n < 10:
        return "검증전", f"표본 {n}"
    if p < alpha:
        if all(s is None or np.sign(s) >= 0 for s in subs.values()):
            return "A", f"Bonferroni 유의(p={p:.4f}) + IS·OOS 같은 방향"
        return "B", f"Bonferroni 유의(p={p:.4f}), 하위 구간 방향 불일치"
    if p < 0.10:
        return "C", f"방향만(p={p:.3f}, Bonferroni α={alpha:.4f} 미달)"
    return "F", f"현행과 구별 안 됨(p={p:.2f})"


def _slice(series: pd.Series, dates: pd.Series, lo: str | None, hi: str | None) -> pd.Series:
    m = pd.Series(True, index=series.index)
    if lo:
        m &= dates >= lo
    if hi:
        m &= dates <= hi
    return series[m]


def evaluate(df: pd.DataFrame, *, dd_max: float | None, drop: float | None, rebound_day: bool,
             mode: str = "variance", horizon: int = HORIZON, band: float = 0.0) -> dict:
    """사건 집합 → VRP 그룹 비교. 등급은 여기서 매기지 않는다(grade 는 호출부).

    band: |VRP| ≤ band 인 사건은 '부호 판정 불가(동점)'로 제외 — IV≈RV 경계의 부호 민감도를 보는 용도.
    """
    px = df["kospi_close"].to_numpy(dtype=float)
    iv = df["rep_iv"].to_numpy(dtype=float)
    rv = vf.realized_vol(px)
    vrp = vf.vrp_variance(iv, rv) if mode == "variance" else vf.vrp_volatility(iv, rv)
    fwd = vf.forward_return(px, horizon)
    mask = vf.event_mask(px, drop=drop, dd_max=dd_max, rebound_day=rebound_day)
    dates = df["date"].dt.strftime("%Y-%m-%d")
    rows = pd.DataFrame({"date": dates, "vrp": vrp, "fwd": fwd})[mask].dropna()
    if band > 0:
        rows = rows[rows["vrp"].abs() > band]
    hi = rows[rows.vrp > 0]
    lo = rows[rows.vrp <= 0]
    w = vf.welch(hi["fwd"], lo["fwd"])
    w_is = vf.welch(_slice(hi["fwd"], hi["date"], None, IS_END), _slice(lo["fwd"], lo["date"], None, IS_END))
    w_oos = vf.welch(_slice(hi["fwd"], hi["date"], "2020-01-01", None), _slice(lo["fwd"], lo["date"], "2020-01-01", None))
    # H2 — VRP>0 그룹 승률 > 50% (지시자 평균의 단측 t)
    ind = (hi["fwd"] > 0).astype(float).to_numpy() - 0.5
    n2 = ind.size
    if n2 >= 3 and np.std(ind, ddof=1) > 0:
        t2 = float(np.mean(ind) / (np.std(ind, ddof=1) / math.sqrt(n2)))
        p2 = vf.p_one_sided(t2, +1)
    else:
        t2, p2 = None, None
    return {
        "events": int(len(rows)),
        "groups": {"vrp_pos": vf.group_stats(hi["fwd"]), "vrp_nonpos": vf.group_stats(lo["fwd"])},
        "all": vf.group_stats(rows["fwd"]),
        "H1": {"welch": w, "is": w_is, "oos": w_oos},
        "H2": {"win": float((hi["fwd"] > 0).mean()) if len(hi) else None, "t": t2, "p_one": p2,
               "baseline_win": float((rows["fwd"] > 0).mean()) if len(rows) else None},
        "median": {"iv": float(np.nanmedian(iv)) if np.isfinite(iv).any() else None,
                   "rv20_at_events": float(np.nanmedian(rv[df.index[mask]])) if mask.any() else None},
    }


def summarize(name: str, res: dict) -> dict:
    """등급 부여 + 사람이 읽는 요약 1건."""
    h1 = res["H1"]
    w = h1["welch"]
    p = w.get("p_one")
    subs = {"is": (h1["is"].get("diff")), "oos": (h1["oos"].get("diff"))}
    g, why = grade(p, subs, res["events"])
    return {"id": name, "grade": g, "why": why,
            "n": res["events"], "n_pos": w.get("n_a"), "n_nonpos": w.get("n_b"),
            "mean_pos": w.get("mean_a"), "mean_nonpos": w.get("mean_b"), "diff": w.get("diff"),
            "p_one": p, "t": w.get("t"),
            "is": {"n_pos": h1["is"].get("n_a"), "n_nonpos": h1["is"].get("n_b"),
                   "mean_pos": h1["is"].get("mean_a"), "mean_nonpos": h1["is"].get("mean_b"),
                   "diff": h1["is"].get("diff"), "p_one": h1["is"].get("p_one")},
            "oos": {"n_pos": h1["oos"].get("n_a"), "n_nonpos": h1["oos"].get("n_b"),
                    "mean_pos": h1["oos"].get("mean_a"), "mean_nonpos": h1["oos"].get("mean_b"),
                    "diff": h1["oos"].get("diff"), "p_one": h1["oos"].get("p_one")},
            "H2_win": res["H2"]["win"], "H2_p_one": res["H2"]["p_one"],
            "H2_baseline_win": res["H2"]["baseline_win"],
            "false_rate_pos": res["groups"]["vrp_pos"].get("false_rate"),
            "false_rate_nonpos": res["groups"]["vrp_nonpos"].get("false_rate"),
            "payoff_pos": res["groups"]["vrp_pos"].get("payoff"),
            "payoff_nonpos": res["groups"]["vrp_nonpos"].get("payoff")}


def run(csv: Path = CSV) -> dict:
    df = pd.read_csv(csv, parse_dates=["date"]).sort_values("date").reset_index(drop=True)
    df = df[["date", "kospi_close", "rep_iv"]].dropna(subset=["kospi_close"])
    main = evaluate(df, dd_max=DROP_DD, drop=None, rebound_day=True)
    exp = {
        "crash_day_-2pct": summarize("crash_day_-2pct", evaluate(df, dd_max=None, drop=-0.02, rebound_day=False)),
        "deep_dd_-7pct": summarize("deep_dd_-7pct", evaluate(df, dd_max=-0.07, drop=None, rebound_day=False)),
        "vol_spread_mode": summarize("vol_spread_mode", evaluate(df, dd_max=DROP_DD, drop=None, rebound_day=True, mode="volatility")),
        "horizon_10": summarize("horizon_10", evaluate(df, dd_max=DROP_DD, drop=None, rebound_day=True, horizon=10)),
        "tie_band_0.002": summarize("tie_band_0.002", evaluate(df, dd_max=DROP_DD, drop=None, rebound_day=True, band=0.002)),
        "tie_band_0.005": summarize("tie_band_0.005", evaluate(df, dd_max=DROP_DD, drop=None, rebound_day=True, band=0.005)),
    }
    return {
        "generated": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "id": "vrp_rebound_filter",
        "title": "VRP(IV²−RV20²) 반등 필터 — 공포 과잉 vs 실현변동성 폭발",
        "prereg": {"m": M, "alpha_bonf": round(ALPHA, 5), "is_end": IS_END, "horizon": HORIZON,
                   "event": {"dd_max": DROP_DD, "drop": None, "rebound_day": True},
                   "iv": "rep_iv", "rv": "RV20(20d, √252)", "mode": "variance",
                   "data": "data/deriv/daily.csv", "rows": int(len(df)),
                   "range": [str(df["date"].iloc[0].date()), str(df["date"].iloc[-1].date())]},
        "main": summarize("main_dd5_rebound", main),
        "exploratory": exp,
        "grades": {"H1": None, "H2": None},
        "meta": {"run_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")},
    }


def main(argv=None) -> int:
    out = run()
    h1g = out["main"]["grade"]
    h2p = out["main"]["H2_p_one"]
    out["grades"] = {"H1": h1g,
                     "H2": ("검증전" if h2p is None else ("A" if h2p < ALPHA else "C" if h2p < 0.10 else "F"))}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    m = out["main"]
    print(f"[{out['id']}] 사건 {m['n']}건 (VRP>0 {m['n_pos']} / ≤0 {m['n_nonpos']}) 5일 평균 "
          f"{m['mean_pos']:+.4f} vs {m['mean_nonpos']:+.4f} (차 {m['diff']:+.4f}, 단측 p {m['p_one']:.3f}) → H1 {h1g}")
    print(f"  IS  {m['is']['mean_pos']:+.4f} vs {m['is']['mean_nonpos']:+.4f} p {m['is']['p_one']} | "
          f"OOS {m['oos']['mean_pos']:+.4f} vs {m['oos']['mean_nonpos']:+.4f} p {m['oos']['p_one']}")
    print(f"  승률 {m['H2_win']} vs 기준 {m['H2_baseline_win']} (p {m['H2_p_one']})  오탐률 {m['false_rate_pos']} vs {m['false_rate_nonpos']}")
    print(f"→ {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
