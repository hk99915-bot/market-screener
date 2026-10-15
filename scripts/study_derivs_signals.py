"""파생·수급 신호 검증 — reports/studies/derivs_signals.md §0 사전 등록 그대로.

python scripts/study_derivs_signals.py  → reports/studies/derivs_signals.json (+ 표준출력 요약)
데이터: data/deriv/daily.csv (screener/deriv_hist.py)
"""
from __future__ import annotations

import json
import math
import sys
from datetime import datetime
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CSV = ROOT / "data" / "deriv" / "daily.csv"
OUT = ROOT / "reports" / "studies" / "derivs_signals.json"
M = 10                      # 주 검정 수 (H8 제외)
ALPHA_B = 0.05 / M          # Bonferroni 단측 0.005
MIN_DAYS = 60               # 그룹별 IS 최소 일수
MIN_EVENTS = 30
N = NormalDist()


def p_one(t: float, direction: int) -> float:
    """단측 p (direction=+1 이면 t>0 이 예상 방향). 표본이 충분히 커서 정규 근사."""
    if t is None or not np.isfinite(t):
        return float("nan")
    return 1 - N.cdf(t * direction)


def welch(a: np.ndarray, b: np.ndarray):
    a, b = a[np.isfinite(a)], b[np.isfinite(b)]
    if len(a) < 2 or len(b) < 2:
        return float("nan"), float("nan")
    d = a.mean() - b.mean()
    se = math.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b))
    return d, (d / se if se > 0 else float("nan"))


def ols_nw(y: np.ndarray, X: np.ndarray, lag: int):
    """OLS + Newey-West(Bartlett) 표준오차. X 에 상수 포함. 반환: (계수, t)"""
    ok = np.isfinite(y) & np.all(np.isfinite(X), axis=1)
    y, X = y[ok], X[ok]
    n, k = X.shape
    if n <= k + 2 or np.linalg.matrix_rank(X) < k:      # 부분 표본에 신호가 한쪽뿐이면 추정 불가
        return np.full(k, np.nan), np.full(k, np.nan), n
    XtX_inv = np.linalg.inv(X.T @ X)
    b = XtX_inv @ X.T @ y
    u = y - X @ b
    Xu = X * u[:, None]
    S = Xu.T @ Xu
    for L in range(1, lag + 1):
        w = 1 - L / (lag + 1)
        G = Xu[L:].T @ Xu[:-L]
        S += w * (G + G.T)
    V = XtX_inv @ S @ XtX_inv
    se = np.sqrt(np.diag(V))
    return b, b / se, n


def load() -> pd.DataFrame:
    df = pd.read_csv(CSV, dtype={"fut_name": str, "opt_front": str, "night_src": str})
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    df = df[df["kospi_close"].notna()].reset_index(drop=True)
    c = df["kospi_close"]
    lc = np.log(c)
    for h in (1, 5, 20):
        df[f"r{h}"] = lc.shift(-h) - lc
    df["r0"] = lc - lc.shift(1)
    df["gap_next"] = df["kospi_open"].shift(-1) / c - 1
    df["gap"] = df["kospi_open"] / c.shift(1) - 1
    df["rv20"] = df["r0"].rolling(20).std() * math.sqrt(252)
    return df


def split(dates: pd.Series):
    ds = dates.sort_values()
    if len(ds) == 0:
        return None
    return ds.iloc[int(len(ds) * 0.7)] if len(ds) > 10 else ds.iloc[-1]


def grade(p_is, p_oos, p_all, d_is, d_oos, d_all, direction, enough_is, enough_oos):
    if not enough_is:
        return "검증전"
    if np.isfinite(p_is) and p_is < ALPHA_B:
        if enough_oos and np.isfinite(p_oos) and p_oos < 0.05:
            return "A"
        return "B"
    if np.isfinite(p_all) and p_all < 0.10 and d_all * direction > 0:
        return "C"
    return "F"


def two_group(df, mask_col, ycol, direction, lag, hid, lens, name, note=""):
    d = df[[ "date", ycol, mask_col]].dropna()
    if len(d) == 0:
        return {"id": hid, "lens_id": lens, "name": name, "grade": "검증전", "n": 0, "note": "데이터 없음. " + note}
    cut = split(d["date"])
    res = {}
    for part, sub in (("is", d[d["date"] < cut]), ("oos", d[d["date"] >= cut]), ("all", d)):
        y = sub[ycol].to_numpy(float)
        x = sub[mask_col].astype(float).to_numpy()
        n1, n0 = int(x.sum()), int(len(x) - x.sum())
        if lag == 0:
            diff, t = welch(y[x == 1], y[x == 0])
        else:
            b, tt, _ = ols_nw(y, np.column_stack([np.ones(len(x)), x]), lag)
            diff, t = b[1], tt[1]
        res[part] = {"n": len(sub), "n1": n1, "n0": n0, "diff": diff, "t": t, "p": p_one(t, direction),
                     "from": str(sub["date"].min().date()) if len(sub) else None, "to": str(sub["date"].max().date()) if len(sub) else None}
    enough_is = res["is"]["n1"] >= MIN_DAYS and res["is"]["n0"] >= MIN_DAYS
    enough_oos = res["oos"]["n1"] >= 20 and res["oos"]["n0"] >= 20
    g = grade(res["is"]["p"], res["oos"]["p"], res["all"]["p"], res["is"]["diff"], res["oos"]["diff"], res["all"]["diff"], direction, enough_is, enough_oos)
    return {"id": hid, "lens_id": lens, "name": name, "grade": g, "n": res["all"]["n"], "n_signal": res["all"]["n1"],
            "effect": _r(res["all"]["diff"]), "effect_unit": f"{ycol} 평균 차이(로그수익률)", "effect_is": _r(res["is"]["diff"]),
            "effect_oos": _r(res["oos"]["diff"]), "t_is": _r(res["is"]["t"], 2), "p_is": _r(res["is"]["p"], 4),
            "t_oos": _r(res["oos"]["t"], 2), "p_oos": _r(res["oos"]["p"], 4), "t_all": _r(res["all"]["t"], 2), "p_all": _r(res["all"]["p"], 4),
            "period": f"{res['all']['from']} ~ {res['all']['to']}", "is_until": str(cut.date()), "direction": "+" if direction > 0 else "−",
            "note": note}


def _r(x, k=5):
    try:
        return None if x is None or not np.isfinite(x) else round(float(x), k)
    except TypeError:
        return None


def main() -> None:
    df = load()
    S = []
    # H1 선물 외국인
    df["fut_frgn_buy"] = np.where(df["fut_frgn"].notna(), (df["fut_frgn"] > 0).astype(float), np.nan)
    S.append(two_group(df, "fut_frgn_buy", "r1", +1, 0, "H1", "fut_foreign_flow", "외국인 선물 순매수 → 다음날",
                       "네이버 당일값을 2026-10-16부터 적재 — 과거 조회 소스 없음"))
    # H2 현물 외국인
    df["spot_frgn_buy"] = np.where(df["spot_frgn"].notna(), (df["spot_frgn"] > 0).astype(float), np.nan)
    S.append(two_group(df, "spot_frgn_buy", "r1", +1, 0, "H2", "foreign_flow", "외국인 현물 순매수 → 다음날"))
    # H3 외국인 매도→매수 전환 (3일 연속 순매도 후 순매수)
    f = df["spot_frgn"]
    turn = (f > 0) & (f.shift(1) < 0) & (f.shift(2) < 0) & (f.shift(3) < 0)
    ev = df.loc[turn & df["r5"].notna(), ["date", "r5"]]
    base = df["r5"].dropna()
    if len(ev):
        cut = split(df.loc[df["spot_frgn"].notna(), "date"])
        out = {}
        for part, e, b in (("is", ev[ev["date"] < cut], df[(df["date"] < cut)]["r5"].dropna()),
                           ("oos", ev[ev["date"] >= cut], df[(df["date"] >= cut)]["r5"].dropna()), ("all", ev, base)):
            x = e["r5"].to_numpy(float)
            mu = b.mean()
            t = (x.mean() - mu) / (x.std(ddof=1) / math.sqrt(len(x))) if len(x) > 2 else float("nan")
            out[part] = {"n": len(x), "diff": x.mean() - mu if len(x) else float("nan"), "t": t, "p": p_one(t, +1)}
        g = grade(out["is"]["p"], out["oos"]["p"], out["all"]["p"], out["is"]["diff"], out["oos"]["diff"], out["all"]["diff"], +1,
                  out["is"]["n"] >= MIN_EVENTS, out["oos"]["n"] >= 10)
        S.append({"id": "H3", "lens_id": "foreign_flow", "name": "외국인 현물 3일 순매도 후 순매수 전환 → 5일", "grade": g,
                  "n": out["all"]["n"], "effect": _r(out["all"]["diff"]), "effect_unit": "r5 − 무조건 r5 (로그)",
                  "effect_is": _r(out["is"]["diff"]), "effect_oos": _r(out["oos"]["diff"]), "t_is": _r(out["is"]["t"], 2), "p_is": _r(out["is"]["p"], 4),
                  "t_oos": _r(out["oos"]["t"], 2), "p_oos": _r(out["oos"]["p"], 4), "t_all": _r(out["all"]["t"], 2), "p_all": _r(out["all"]["p"], 4),
                  "period": f"{ev['date'].min().date()} ~ {ev['date'].max().date()}", "is_until": str(cut.date()), "direction": "+",
                  "note": "사건 간 5일 겹침은 보정 안 함(사건이 최소 4일 간격이라 겹침 작음)"})
    # H4 베이시스 음수
    df["basis_neg"] = np.where(df["basis_pct"].notna(), (df["basis_pct"] < 0).astype(float), np.nan)
    S.append(two_group(df, "basis_neg", "r5", +1, 4, "H4", "fut_basis", "베이시스 음수(백워데이션) → 5일"))
    # H5·H6 PCR 분위 (과거 250일, 최소 60일)
    pcr = df["pcr_oi"]
    pct = pcr.rolling(250, min_periods=60).apply(lambda w: (w[:-1] < w[-1]).mean() if len(w) > 1 else np.nan, raw=True)
    df["pcr_hi"] = np.where(pct.notna(), (pct >= 0.8).astype(float), np.nan)
    df["pcr_lo"] = np.where(pct.notna(), (pct <= 0.2).astype(float), np.nan)
    S.append(two_group(df, "pcr_hi", "r5", +1, 4, "H5-r5", "options_pcr", "풋콜(OI) 상위 20% → 5일 (역발상)"))
    S.append(two_group(df, "pcr_hi", "r20", +1, 19, "H5-r20", "options_pcr", "풋콜(OI) 상위 20% → 20일 (역발상)"))
    S.append(two_group(df, "pcr_lo", "r5", -1, 4, "H6-r5", "options_pcr", "풋콜(OI) 하위 20% → 5일 (낮음)"))
    S.append(two_group(df, "pcr_lo", "r20", -1, 19, "H6-r20", "options_pcr", "풋콜(OI) 하위 20% → 20일 (낮음)"))
    # H7 감마 하위 1/3 vs 상위 1/3 → |r1|
    g = df["gex_bn"]
    q1, q2 = g.quantile(1 / 3), g.quantile(2 / 3)
    df["gex_low"] = np.where(g.notna() & ((g <= q1) | (g >= q2)), (g <= q1).astype(float), np.nan)
    df["abs_r1"] = df["r1"].abs()
    h7 = two_group(df, "gex_low", "abs_r1", +1, 0, "H7", "options_gamma", "감마 하위 1/3 vs 상위 1/3 → 다음날 |수익률| (흔들림)")
    # H7b 통제 회귀
    d7 = df[["abs_r1", "gex_bn", "r0", "rv20"]].dropna()
    if len(d7) > 30:
        x = (d7["gex_bn"] <= q1).astype(float).to_numpy()
        b, t, n7 = ols_nw(d7["abs_r1"].to_numpy(float), np.column_stack([np.ones(len(d7)), x, d7["r0"].abs().to_numpy(float), d7["rv20"].to_numpy(float)]), 0)
        h7["control"] = {"coef_gex_low": _r(b[1]), "t": _r(t[1], 2), "p": _r(p_one(t[1], +1), 4), "n": int(n7),
                         "note": "|r_t|·20일 실현변동성 통제 후 감마 하위 1/3 더미"}
        if h7["grade"] in ("A", "B") and not (np.isfinite(t[1]) and p_one(t[1], +1) < 0.05):
            h7["note"] = (h7.get("note") or "") + " 통제 후 사라짐 → 감마 고유 정보 아님(변동성 군집의 재표현)"
            h7["grade_raw"] = h7["grade"]
            h7["grade"] = "C"
    S.append(h7)
    # H8 야간선물 → 다음 시가 갭
    S.append(night_test(df))
    # H9 비차익 상위 20%
    nb = df["prog_nonarb"]
    df["nonarb_top"] = np.where(nb.notna(), (nb >= nb.quantile(0.8)).astype(float), np.nan)
    S.append(two_group(df, "nonarb_top", "r1", +1, 0, "H9", "cand.program_nonarb", "프로그램 비차익 순매수 상위 20% → 다음날"))

    # 검증전 사유 보강 (옵션 보드 열은 2026-10-15 쉼표 버그 수정 전 백필 → 콜 행사가 ≥1,000 누락)
    for s in S:
        if s["id"] in ("H5-r5", "H5-r20", "H6-r5", "H6-r20", "H7"):
            s["note"] = ((s.get("note") or "") + " 옵션 보드 열(pcr_oi·gex_bn) 89일뿐이고, 코스피200 ≥ 1,000 구간은 행사가 쉼표 버그(dc0aacb9) 수정 전 "
                         "백필이라 콜 쪽이 빠져 PCR 과대·감마 음수 쏠림 — 재백필(--redo) 전엔 표본이 차도 쓰면 안 됨.").strip()
        if s["id"] == "H4":
            s["note"] = ("basis_pct 89일(2026-06~). basis_theo(2010~)는 금리·배당으로 계산한 이론 베이시스라 '공포·헤지 과잉' 대용 불가. "
                         "값은 서술 통계로만.")
        if s["id"] == "H9":
            s["note"] = "prog_nonarb 89일(2026-06~). 상위 20% = 18일 → 최소 표본 미달. 값은 서술 통계로만."

    post = {"H2_detail": h2_detail(df), "H3_cost": h3_cost(S), "IV_VOL": iv_vol(df), "SIGNAL1_CRASH": signal1_crash(df)}
    cover = {c: {"from": str(df.loc[df[c].notna(), "date"].min().date()), "to": str(df.loc[df[c].notna(), "date"].max().date()),
                 "n": int(df[c].notna().sum())} if df[c].notna().any() else {"n": 0}
             for c in pd.read_csv(CSV, nrows=0).columns if c != "date"}
    out = {"registered": "2026-10-16", "computed": datetime.now().strftime("%Y-%m-%d %H:%M"), "m": M, "alpha_bonf": ALPHA_B,
           "grades_doc": "A=IS Bonferroni+OOS · B=IS Bonferroni(OOS 미확인) · C=방향만(p<0.10) · F=효과 없음/반대 · 검증전=표본 미달",
           "post_hoc_doc": "post 절은 사전 등록 밖(사후). Bonferroni 묶음(m=10)에 넣지 않고, 등급은 views 규칙대로 최대 C(F는 가능).",
           "sanity": sanity(df), "coverage": cover, "signals": S, "post": post}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    for s in S:
        print(f"{s['id']:7s} {s['grade']:4s} n={s.get('n')} eff={s.get('effect')} t_is={s.get('t_is')} p_is={s.get('p_is')} "
              f"t_oos={s.get('t_oos')} p_oos={s.get('p_oos')} p_all={s.get('p_all')} {s.get('period', '')} {s.get('name')}")
        if s.get("control"):
            print("        control", s["control"])
        if s.get("detail"):
            print("        detail", s["detail"])
    print("coverage", json.dumps(cover, ensure_ascii=False))
    print("sanity", json.dumps(out["sanity"], ensure_ascii=False))
    for k, v in post.items():
        print("POST", k, json.dumps(v, ensure_ascii=False))


# ───────────────────────── 사후(post-hoc) · 보강 — 사전 등록 밖 ─────────────────────────
COST_RT = 0.0025     # lab.py 와 같은 왕복 비용(보수적: 지수 ETF·선물은 훨씬 작다)
COST_RT_LOW = 0.0005
NBOOT = 5000
CLUSTER_GAP = 10


def sanity(df: pd.DataFrame) -> dict:
    r = df["r0"]
    flow_sum = (df["spot_frgn"] + df["spot_inst"] + df["spot_indiv"] + df["spot_corp"]).abs()
    big = df.loc[r.abs() > 0.08, ["date", "r0"]]
    return {
        "rows": int(len(df)), "dup_dates": int(df["date"].duplicated().sum()),
        "max_calendar_gap_days": int(df["date"].diff().dt.days.max()),
        "ohlc_violations": int(((df["kospi_high"] < df[["kospi_open", "kospi_close"]].max(axis=1) - 1e-6) |
                                (df["kospi_low"] > df[["kospi_open", "kospi_close"]].min(axis=1) + 1e-6)).sum()),
        "open_eq_prev_close_share": _r(float((df["gap"].abs() < 1e-9).mean()), 4),
        "flow_4way_sum_abs_median": _r(float(flow_sum.median()), 2),
        "abs_r_gt_8pct_days": [f"{d.date()} {x:+.3f}" for d, x in zip(big["date"], big["r0"])],
        "share_2026_of_abs_r_gt_8pct": _r(float((big["date"].dt.year == 2026).mean()), 2),
        "frgn_abs_median_2010_2025_vs_2026": [_r(float(df.loc[df["date"].dt.year < 2026, "spot_frgn"].abs().median()), 0),
                                               _r(float(df.loc[df["date"].dt.year == 2026, "spot_frgn"].abs().median()), 0)],
        "rep_iv_median_2010_2025_vs_2026": [_r(float(df.loc[df["date"].dt.year < 2026, "rep_iv"].median()), 1),
                                             _r(float(df.loc[df["date"].dt.year == 2026, "rep_iv"].median()), 1)],
        "option_board_bug": "call_wall 은 k200 < 1,000 인 11일만 존재, put_wall=1.0 인 날 4일, max_pain·night_close 전부 비어 있음",
    }


def _welch_block(sub, col, y):
    a = sub.loc[sub[col] == 1, y].to_numpy(float)
    b = sub.loc[sub[col] == 0, y].to_numpy(float)
    d, t = welch(a, b)
    return {"n1": int(len(a)), "n0": int(len(b)), "diff": _r(d), "t": _r(t, 2)}


def h2_detail(df: pd.DataFrame) -> dict:
    """H2 보강: 시대별, 동시점(같은 날) 차이, 비용 차감 타이밍 전략."""
    d = df[df["spot_frgn"].notna()].copy()
    eras = {"2010-2020": d["date"].dt.year <= 2020, "2021-2025": d["date"].dt.year.between(2021, 2025), "2026": d["date"].dt.year == 2026}
    out = {"by_era_r1": {k: _welch_block(d[m], "spot_frgn_buy", "r1") for k, m in eras.items()},
           "same_day_r0": _welch_block(d, "spot_frgn_buy", "r0"),
           "note": "same_day_r0 = 같은 날 수익률 차이 — 외국인 순매수는 '그날' 오른 날과 겹친다(설명), 다음날 예측은 별개."}
    # 타이밍 전략: t 외국인 순매수면 t 종가 매수 → t+1 종가 보유, 아니면 현금. 전환마다 편도 비용.
    s = d[["date", "spot_frgn_buy", "r1"]].dropna()
    on = s["spot_frgn_buy"].to_numpy(float)
    sw = np.abs(np.diff(np.r_[0.0, on]))
    gross = on * s["r1"].to_numpy(float)
    res = {}
    for nm, c in (("cost_0.25%", COST_RT), ("cost_0.05%", COST_RT_LOW)):
        net = gross - sw * c / 2
        res[nm] = {"ann_ret_strategy": _r(float(net.mean() * 252), 4), "ann_ret_buyhold": _r(float(s["r1"].mean() * 252), 4),
                   "time_in_market": _r(float(on.mean()), 3), "switches_per_year": _r(float(sw.sum() / len(on) * 252), 1)}
    out["timing_strategy"] = res
    return out


def h3_cost(S: list) -> dict:
    h3 = next((s for s in S if s["id"] == "H3"), None)
    if not h3 or h3.get("effect") is None:
        return {}
    return {"effect_gross": h3["effect"], "effect_net_0.25%": _r(h3["effect"] - COST_RT), "effect_net_0.05%": _r(h3["effect"] - COST_RT_LOW),
            "note": "사건마다 5일 보유 1회 왕복. 총효과부터 음수라 비용 차감은 확인용."}


def iv_vol(df: pd.DataFrame) -> dict:
    """사후 IV_VOL: 대표 내재변동성(rep_iv, 2010~) 상위 1/3 vs 하위 1/3 → 다음날 |r1|. H7(감마)의 대용.
    H7 과 같은 틀(분위 1/3·Welch·통제 회귀). 방향은 보지 않는다."""
    d = df[["date", "rep_iv", "r1", "r0", "rv20"]].dropna().copy()
    d["abs_r1"] = d["r1"].abs()
    q1, q2 = d["rep_iv"].quantile(1 / 3), d["rep_iv"].quantile(2 / 3)
    d["iv_hi"] = np.where((d["rep_iv"] >= q2) | (d["rep_iv"] <= q1), (d["rep_iv"] >= q2).astype(float), np.nan)
    base = two_group(d, "iv_hi", "abs_r1", +1, 0, "IV_VOL", "options_gamma", "사후: 대표 내재변동성 상위 1/3 vs 하위 1/3 → 다음날 |수익률|")
    cut = split(d["date"])
    ctrl = {}
    for part, sub in (("is", d[d["date"] < cut]), ("oos", d[d["date"] >= cut]), ("all", d)):
        X = np.column_stack([np.ones(len(sub)), sub["rep_iv"].to_numpy(float) / 100 / math.sqrt(252),
                             sub["r0"].abs().to_numpy(float), sub["rv20"].to_numpy(float) / math.sqrt(252)])
        b, t, n = ols_nw(sub["abs_r1"].to_numpy(float), X, 5)
        ctrl[part] = {"n": int(n), "coef_iv_daily": _r(b[1], 3), "t_iv": _r(t[1], 2), "coef_rv20_daily": _r(b[3], 3), "t_rv20": _r(t[3], 2),
                      "coef_abs_r0": _r(b[2], 3), "t_abs_r0": _r(t[2], 2)}
    # 등급: 사후 → 최대 C. IS·OOS 모두 통제 후 IV t>2 면 C, 아니면 F.
    ok = all((ctrl[p]["t_iv"] or 0) > 2 for p in ("is", "oos"))
    base.update({"grade_raw": base["grade"], "grade": "C" if (base["grade"] in ("A", "B", "C") and ok) else "F",
                 "control_nw5": ctrl, "q_low_high": [_r(q1, 1), _r(q2, 1)],
                 "ratio_abs_r1_hi_over_lo": _r(float(d.loc[d["iv_hi"] == 1, "abs_r1"].mean() / d.loc[d["iv_hi"] == 0, "abs_r1"].mean()), 2),
                 "note": "사후(사전 등록 H7 은 gex_bn 기준인데 감마 이력이 89일·버그 구간이라 대체). 사후라 등급 상한 C. "
                         "IV 는 시장이 매긴 '내일 흔들림 가격'이라 예측력이 있는 게 당연 — 렌즈 가치는 '실현변동성(rv20) 통제 후에도 남나'."})
    return base


def _clusters(idx):
    cid, out, last = -1, [], None
    for i in idx:
        if last is None or i - last > CLUSTER_GAP:
            cid += 1
        out.append(cid)
        last = i
    return np.array(out)


def _boot(vals, cl, rng):
    u = np.unique(cl)
    groups = [vals[cl == g] for g in u]
    bs = np.empty(NBOOT)
    for k in range(NBOOT):
        pick = rng.integers(0, len(u), len(u))
        bs[k] = np.concatenate([groups[p] for p in pick]).mean()
    return [_r(float(np.percentile(bs, 2.5)), 4), _r(float(np.percentile(bs, 97.5)), 4)]


def signal1_crash(df: pd.DataFrame) -> dict:
    """사후 SIGNAL1: 실행 대본 신호① '외국인 순매수 전환'을 playbook_signals 의 급락 이벤트·비교 틀 그대로 검증.
    이벤트: 1일 ≤ −3% (−5%) & 종가 ÷ 최근 21개 종가 최고 − 1 ≤ −10%. 청산 T = t+H 종가 (H=20·60), 미진입 = 0%.
    B  = 급락일 종가 매수 (기준선, crash_day_close 렌즈)
    G1 = t+1..t+10 중 외국인 현물 순매수(>0) 첫날 종가 (committee _exec_plan 신호① '외국인 순매수 전환')
    G2 = t+1..t+20 중 외국인 현물 2일 연속 순매수 둘째 날 종가 (committee 강세 시나리오 트리거 '2일 연속 순매수 전환')
    차이는 같은 이벤트끼리 짝지은 G − B, 10거래일 클러스터 부트스트랩 95% CI."""
    rng = np.random.default_rng(20261016)
    c = df["kospi_close"].to_numpy(float)
    f = df["spot_frgn"].to_numpy(float)
    dates = df["date"]
    out = {"doc": signal1_crash.__doc__.strip().splitlines()[1:]}
    for thr in (-0.03, -0.05):
        ev = [i for i in range(21, len(c)) if c[i] / c[i - 1] - 1 <= thr and c[i] / c[i - 20:i + 1].max() - 1 <= -0.10]
        for H in (20, 60):
            rows = []
            for t in ev:
                T = t + H
                if T >= len(c):
                    continue
                g1 = next((d for d in range(t + 1, min(t + 10, T) + 1) if f[d] > 0), None)
                g2 = next((d for d in range(t + 2, min(t + 20, T) + 1) if f[d] > 0 and f[d - 1] > 0), None)
                rB = c[T] / c[t] - 1
                r1 = c[T] / c[g1] - 1 if g1 is not None else 0.0
                r2 = c[T] / c[g2] - 1 if g2 is not None else 0.0
                rows.append({"t": t, "date": str(dates[t].date()), "B": rB, "G1": r1, "G2": r2, "g1_lag": (g1 - t) if g1 else None,
                             "g2_lag": (g2 - t) if g2 else None, "frgn_crash_day_buy": bool(f[t] > 0),
                             "g1_prem": (c[g1] / c[t] - 1) if g1 else None, "g2_prem": (c[g2] / c[t] - 1) if g2 else None})
            if not rows:
                continue
            R = pd.DataFrame(rows)
            cl = _clusters(R["t"].tolist())
            res = {"n_events": len(R), "n_clusters": int(cl.max() + 1), "from": R["date"].iloc[0], "to": R["date"].iloc[-1]}
            for k in ("B", "G1", "G2"):
                v = R[k].to_numpy(float)
                res[k] = {"mean": _r(v.mean(), 4), "median": _r(float(np.median(v)), 4), "hit": _r(float((v > 0).mean()), 3),
                          "worst": _r(v.min(), 4), "ci": _boot(v, cl, rng)}
            for k, lag, prem in (("G1", "g1_lag", "g1_prem"), ("G2", "g2_lag", "g2_prem")):
                diff = (R[k] - R["B"]).to_numpy(float)
                filled = R[lag].notna()
                res[k].update({"filled": int(filled.sum()), "median_lag_days": _r(float(R.loc[filled, lag].median()), 1) if filled.any() else None,
                               "entry_prem_vs_crash_close": _r(float(R.loc[filled, prem].mean()), 4) if filled.any() else None,
                               "missed_B_mean": _r(float(R.loc[~filled, "B"].mean()), 4) if (~filled).any() else None,
                               "diff_vs_B": _r(float(diff.mean()), 4), "diff_ci": _boot(diff, cl, rng)})
            # 급락일 당일 외국인이 샀나 → B 수익 서술
            m = R["frgn_crash_day_buy"]
            res["B_by_crash_day_frgn"] = {"buy": {"n": int(m.sum()), "mean": _r(float(R.loc[m, "B"].mean()), 4) if m.any() else None},
                                          "sell": {"n": int((~m).sum()), "mean": _r(float(R.loc[~m, "B"].mean()), 4) if (~m).any() else None}}
            pre = R[R["date"] < "2026-01-01"]
            if len(pre) > 3:
                clp = _clusters(pre["t"].tolist())
                res["pre_2026"] = {"n": len(pre), "clusters": int(clp.max() + 1),
                                   **{f"{k}_diff_vs_B": _r(float((pre[k] - pre["B"]).mean()), 4) for k in ("G1", "G2")},
                                   **{f"{k}_diff_ci": _boot((pre[k] - pre["B"]).to_numpy(float), clp, rng) for k in ("G1", "G2")}}
            out[f"{int(thr * 100)}%_H{H}"] = res
    # 판정 (playbook 0-5 규칙 그대로 적용): H20·H60 모두 B 대비 평균 > 0 이고 한 CI 라도 0 위 → 개선. 반대면 악화.
    verdict = {}
    for k in ("G1", "G2"):
        a, b = out.get("-3%_H20", {}).get(k, {}), out.get("-3%_H60", {}).get(k, {})
        if not a or not b:
            continue
        da, db = a["diff_vs_B"], b["diff_vs_B"]
        if da > 0 and db > 0 and (a["diff_ci"][0] > 0 or b["diff_ci"][0] > 0):
            verdict[k] = "개선"
        elif da < 0 and db < 0 and (a["diff_ci"][1] < 0 or b["diff_ci"][1] < 0):
            verdict[k] = "악화"
        else:
            verdict[k] = "근거 불충분"
    out["verdict"] = verdict
    return out


def night_test(df: pd.DataFrame) -> dict:
    """H8: 야간 등락 → 다음 정규장 시가 갭. 두 시대를 따로 본다.
    - 유렉스 연계(보드의 '(야간)' 행): 행 D 의 귀속(D 저녁 세션인지 D-1 저녁 세션인지)을 상관으로 판정해 맞는 쪽을 쓴다.
    - KRX 자체 야간(2025-06-09~): 행 D = D-1 18:00~D 06:00, 가격은 VWAP(종가 아님) → 사전 등록 정의에서 벗어남(명시)."""
    det = {}
    rows = []
    e = df[df["night_close"].notna() & df["fut_close"].notna()].copy()
    if len(e) > 30:
        a = (e["night_close"] / e["fut_close"] - 1)                         # D 저녁 세션 가정 → D+1 갭
        corr_a = np.corrcoef(a, e["gap_next"].fillna(0))[0, 1] if e["gap_next"].notna().sum() > 30 else float("nan")
        prev_fc = df["fut_close"].shift(1).loc[e.index]
        b = (e["night_close"] / prev_fc - 1)                                # D-1 저녁 세션 가정 → D 갭
        corr_b = np.corrcoef(b.fillna(0), e["gap"].fillna(0))[0, 1]
        det["eurex_corr_same_day_session"] = _r(corr_a, 3)
        det["eurex_corr_prev_day_session"] = _r(corr_b, 3)
        if np.nan_to_num(corr_a) >= np.nan_to_num(corr_b):
            rows.append(pd.DataFrame({"date": e["date"], "x": a, "y": e["gap_next"], "era": "eurex"}))
        else:
            rows.append(pd.DataFrame({"date": e["date"], "x": b, "y": e["gap"], "era": "eurex"}))
    k = df[df["night_vwap"].notna()].copy()
    if len(k):
        prev_fc = df["fut_close"].shift(1).loc[k.index]
        rows.append(pd.DataFrame({"date": k["date"], "x": k["night_vwap"] / prev_fc - 1, "y": k["gap"], "era": "krx_vwap"}))
    if not rows:
        return {"id": "H8", "lens_id": "night_futures", "name": "야간선물 등락 → 다음 시가 갭", "grade": "검증전", "n": 0, "note": "야간 데이터 없음"}
    d = pd.concat(rows).dropna()
    d = d[(d["x"].abs() < 0.15) & (d["y"].abs() < 0.15)]

    def fit(sub):
        if len(sub) < 10:
            return {"n": len(sub)}
        X = np.column_stack([np.ones(len(sub)), sub["x"].to_numpy(float)])
        b, t, n = ols_nw(sub["y"].to_numpy(float), X, 0)
        yhat = X @ b
        r2 = 1 - ((sub["y"] - yhat) ** 2).sum() / ((sub["y"] - sub["y"].mean()) ** 2).sum()
        hit = float(((np.sign(sub["x"]) == np.sign(sub["y"])) | (sub["y"].abs() < 1e-4)).mean())
        return {"n": int(n), "slope": _r(b[1], 3), "intercept_bp": _r(b[0] * 1e4, 1), "t": _r(t[1], 1), "r2": _r(r2, 3),
                "sign_hit": _r(hit, 3), "mae_bp": _r(float((sub["y"] - yhat).abs().mean() * 1e4), 1),
                "mae_naive_bp": _r(float((sub["y"] - sub["x"]).abs().mean() * 1e4), 1),
                "from": str(sub["date"].min().date()), "to": str(sub["date"].max().date())}
    cut = split(d["date"])
    det.update({"all": fit(d), "is": fit(d[d["date"] < cut]), "oos": fit(d[d["date"] >= cut]),
                "eurex": fit(d[d["era"] == "eurex"]), "krx_vwap": fit(d[d["era"] == "krx_vwap"])})
    # 등급: 장전 한 줄이 실제로 쓰는 KRX VWAP 시대 기준. 표본 부족이면 유렉스 시대 결과는 참고로만.
    k8 = det["krx_vwap"]
    if k8.get("n", 0) < MIN_DAYS:
        g = "검증전"
    else:
        kk = d[d["era"] == "krx_vwap"]
        kc = split(kk["date"])
        ko = fit(kk[kk["date"] >= kc])
        det["krx_vwap_oos"] = ko
        g = "A" if (k8["r2"] or 0) >= 0.5 and (ko.get("r2") or 0) >= 0.4 else "C" if (k8["r2"] or 0) >= 0.2 else "F"
    # 보강: 귀속 확인(행 D 야간 → D 시가 vs D+1 시가), 선물 시가 갭(같은 상품) 대비, 큰 야간 움직임(|x|>1%) 적중률
    if len(k):
        xk = k["night_vwap"] / df["fut_close"].shift(1).loc[k.index] - 1
        fut_gap = df["fut_open"] / df["fut_close"].shift(1) - 1
        kk = pd.DataFrame({"x": xk, "gap": k["gap"], "gap_next": k["gap_next"], "fut_gap": fut_gap.loc[k.index]}).dropna()
        det["attribution_corr"] = {"row_D_vs_gap_D": _r(float(kk["x"].corr(kk["gap"])), 3),
                                   "row_D_vs_gap_D+1": _r(float(kk["x"].corr(kk["gap_next"])), 3)}
        fk = pd.DataFrame({"date": k["date"], "x": xk, "y": fut_gap.loc[k.index]}).dropna()
        det["vs_futures_open_gap"] = fit(fk)
        big = kk[kk["x"].abs() > 0.01]
        det["big_move_gt1pct"] = {"n": int(len(big)), "sign_hit": _r(float((np.sign(big["x"]) == np.sign(big["gap"])).mean()), 3) if len(big) else None}
        det["resid_sd_bp"] = _r(float((kk["gap"] - kk["x"]).std() * 1e4), 1)
        det["gap_sd_bp"] = _r(float(kk["gap"].std() * 1e4), 1)
    base = det["krx_vwap"] if det["krx_vwap"].get("n", 0) >= 10 else det["all"]
    return {"id": "H8", "lens_id": "night_futures", "name": "야간선물 등락 → 다음 정규장 시가 갭 (산수 확인)", "grade": g,
            "n": base.get("n"), "effect": base.get("r2"), "effect_unit": "R² (시가 갭 ~ 야간 등락)", "slope": base.get("slope"),
            "period": f"{base.get('from')} ~ {base.get('to')}", "detail": det,
            "note": "KRX 자체 야간은 종가 대신 세션 평균 체결가(VWAP) — 사전 등록의 '야간 종가'에서 벗어남. 매매 신호 아님, 시초가 예상 정보."}


if __name__ == "__main__":
    sys.exit(main())
