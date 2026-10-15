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
    if n <= k + 2:
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

    cover = {c: {"from": str(df.loc[df[c].notna(), "date"].min().date()), "to": str(df.loc[df[c].notna(), "date"].max().date()),
                 "n": int(df[c].notna().sum())} for c in ("kospi_close", "spot_frgn", "prog_nonarb", "fut_close", "pcr_oi", "gex_bn",
                                                          "night_close", "night_vwap", "fut_frgn", "basis_theo", "rep_iv") if c in df and df[c].notna().any()}
    out = {"registered": "2026-10-16", "computed": datetime.now().strftime("%Y-%m-%d %H:%M"), "m": M, "alpha_bonf": ALPHA_B,
           "grades_doc": "A=IS Bonferroni+OOS · B=IS Bonferroni(OOS 미확인) · C=방향만(p<0.10) · F=효과 없음/반대 · 검증전=표본 미달",
           "coverage": cover, "signals": S}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    for s in S:
        print(f"{s['id']:7s} {s['grade']:4s} n={s.get('n')} eff={s.get('effect')} t_is={s.get('t_is')} p_is={s.get('p_is')} "
              f"t_oos={s.get('t_oos')} p_oos={s.get('p_oos')} p_all={s.get('p_all')} {s.get('period', '')} {s.get('name')}")
        if s.get("control"):
            print("        control", s["control"])
        if s.get("detail"):
            print("        detail", s["detail"])
    print("coverage", json.dumps(cover, ensure_ascii=False))


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
    base = det["krx_vwap"] if det["krx_vwap"].get("n", 0) >= 10 else det["all"]
    return {"id": "H8", "lens_id": "night_futures", "name": "야간선물 등락 → 다음 정규장 시가 갭 (산수 확인)", "grade": g,
            "n": base.get("n"), "effect": base.get("r2"), "effect_unit": "R² (시가 갭 ~ 야간 등락)", "slope": base.get("slope"),
            "period": f"{base.get('from')} ~ {base.get('to')}", "detail": det,
            "note": "KRX 자체 야간은 종가 대신 세션 평균 체결가(VWAP) — 사전 등록의 '야간 종가'에서 벗어남. 매매 신호 아님, 시초가 예상 정보."}


if __name__ == "__main__":
    sys.exit(main())
