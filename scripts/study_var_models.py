#!/usr/bin/env python3
"""VaR 변동성 모델 비교 — EWMA·GARCH(1,1)·GJR-GARCH 1일 VaR99·ES97.5 초과일 백테스트 (퀀트, req-quant-67015597).

사전등록: docs/valuation_notes/2026-11-10_var_models_prereg.md (결과 전 커밋 f5936b5b4). 이 파일의 상수는 그 문서 §1 그대로다 —
결과를 본 뒤 바꾸지 않는다(바꾸면 새 id 로 재등록, kb:quant#1).

  python3 scripts/data_store.py pull --groups all        # data/hist/*_daily.parquet (릴리스 자산)
  python3 scripts/study_var_models.py                    # reports/studies/2026-11-10_var_models.{json,md}
  python3 scripts/study_var_models.py --no-write         # 계산만(요약 출력)

연구 카드 — 규칙·엔진 변경 아님. 워크플로·탭·알림은 이 파일을 import 하지 않는다. 롤백 = 이 파일·산출 2개·테스트 삭제.
외부 패키지 없이 numpy·scipy 로 MLE 를 직접 구현(재현성). `arch` 가 깔려 있으면 tests 가 모수를 대조한다.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import optimize, signal, special, stats

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "studies" / "2026-11-10_var_models"
PREREG = "docs/valuation_notes/2026-11-10_var_models_prereg.md"

# ── 사전등록 §1 상수 ────────────────────────────────────────────────────────────
START, END = "2010-01-04", "2026-11-06"
IS_END = "2019-12-31"
LAM = 0.94
HS_DAYS = 250
EST_WIN, REFIT = 1000, 21
Z99, Z975, K_ES975 = 2.326, 1.960, 2.338
NW_LAG = 5
M = 4
ALPHA_BONF = 0.05 / M
SEED, N_BOOT = 20261110, 10000
PORT_W = {"S&P500": 0.40, "NDX": 0.15, "K200": 0.15, "KTB": 0.20, "Gold": 0.10}   # screener/defs.py ISA_TARGET (C안)
CRASH = {"2020-03": ("2020-02-20", "2020-04-30"), "2022": ("2022-01-03", "2022-12-30"),
         "2024-08": ("2024-08-01", "2024-08-30"), "2026-11초": ("2026-11-02", "2026-11-06")}
SERIES = ["PORT", "KOSPI", "KOSPI200", "SP500", "NASDAQ"]
MODELS = ["HS250", "EWMA", "ENGINE", "GARCH_N", "GJR_N", "SIG60", "GARCH_T", "GJR_T"]
HYP = {"H1": ("GARCH_N", "EWMA"), "H2": ("GJR_N", "EWMA"), "H3": ("GJR_N", "GARCH_N"), "H4": ("GJR_N", "ENGINE")}


# ── 데이터 ────────────────────────────────────────────────────────────────────
def _px(df: pd.DataFrame, sym: str, col: str) -> pd.Series:
    d = df[df.symbol == sym].sort_values("date")
    s = pd.Series(d[col].astype("float64").values, index=pd.to_datetime(d.date.astype(str)), name=sym)
    return s[(s.index >= START) & (s.index <= END)]


def load_series(root: Path = ROOT) -> dict[str, pd.Series]:
    """계열 5개의 일간 단순수익률."""
    k = pd.read_parquet(root / "data/hist/kr_index_daily.parquet")
    u = pd.read_parquet(root / "data/hist/us_daily.parquet")
    e = pd.read_parquet(root / "data/hist/kr_etf_daily.parquet")
    out = {"KOSPI": _px(k, "KOSPI", "close").pct_change().dropna(),
           "KOSPI200": _px(k, "KOSPI200", "close").pct_change().dropna(),
           "SP500": _px(u, "^GSPC", "close").pct_change().dropna(),
           "NASDAQ": _px(u, "^IXIC", "close").pct_change().dropna()}
    out["PORT"] = port_returns(_px(e, "069500", "adj_close"), _px(e, "114260", "adj_close"),
                               _px(u, "SPY", "adj_close"), _px(u, "QQQ", "adj_close"), _px(u, "GLD", "adj_close"),
                               _px(u, "KRW=X", "close"))
    return out


def lag_to(cal: pd.DatetimeIndex, s: pd.Series) -> pd.Series:
    """한국 t일 값 = t일보다 '앞선' 가장 최근 날짜의 값(같은 날 불가)."""
    a = pd.merge_asof(pd.DataFrame({"date": cal}), s.rename("v").rename_axis("date").reset_index(),
                      on="date", allow_exact_matches=False)
    return pd.Series(a.v.values, index=cal)


def port_returns(k200, ktb, spy, qqq, gld, fx) -> pd.Series:
    cal = k200.index.intersection(ktb.index)
    fxl = lag_to(cal, fx)
    legs = pd.DataFrame({"K200": k200.reindex(cal), "KTB": ktb.reindex(cal),
                         "S&P500": lag_to(cal, spy) * fxl, "NDX": lag_to(cal, qqq) * fxl, "Gold": lag_to(cal, gld) * fxl})
    r = legs.pct_change().dropna()
    return sum(PORT_W[c] * r[c] for c in PORT_W).rename("PORT")


# ── 분산 모형 ──────────────────────────────────────────────────────────────────
def garch_filter(r: np.ndarray, omega: float, alpha: float, gamma: float, beta: float, s0: float) -> np.ndarray:
    """σ²[0]=s0, σ²[t] = ω + (α + γ·1[r[t−1]<0])·r[t−1]² + β·σ²[t−1]. 길이 len(r)+1 (마지막 = 다음 날 예측)."""
    x = np.empty(len(r) + 1)
    x[0] = s0
    x[1:] = omega + (alpha + gamma * (r < 0)) * r * r
    return signal.lfilter([1.0], [1.0, -beta], x)


def _nll(theta, r, s0, gjr, tdist):
    omega, alpha, beta = theta[0], theta[1], theta[2]
    gamma = theta[3] if gjr else 0.0
    s2 = garch_filter(r, omega, alpha, gamma, beta, s0)[:-1]
    if np.any(s2 <= 0) or not np.all(np.isfinite(s2)):
        return 1e12
    if tdist:
        nu = theta[-1]
        c = special.gammaln((nu + 1) / 2) - special.gammaln(nu / 2) - 0.5 * math.log(math.pi * (nu - 2))
        ll = c - 0.5 * np.log(s2) - (nu + 1) / 2 * np.log1p(r * r / (s2 * (nu - 2)))
    else:
        ll = -0.5 * (math.log(2 * math.pi) + np.log(s2) + r * r / s2)
    return -float(ll.sum())


def fit_garch(r: np.ndarray, gjr: bool = False, tdist: bool = False, warm=None):
    """MLE (SLSQP, 고정 시작값 + 직전 모수). r 은 % 단위 권장. 반환 (theta dict, 수렴 여부)."""
    v = float(np.var(r))
    starts = [[v * 0.05, 0.03 if gjr else 0.08, 0.90] + ([0.08] if gjr else []) + ([8.0] if tdist else []),
              [v * 0.10, 0.05, 0.80] + ([0.10] if gjr else []) + ([6.0] if tdist else [])]
    if warm is not None:
        starts.insert(0, list(warm))
    bounds = [(1e-8 * max(v, 1e-12), 10 * v), (0.0, 0.6), (0.0, 0.9995)] + ([(-0.3, 0.9)] if gjr else []) + ([(2.05, 200.0)] if tdist else [])
    cons = [{"type": "ineq", "fun": (lambda t: 0.999 - t[1] - t[2] - (0.5 * t[3] if gjr else 0.0))}]
    if gjr:
        cons.append({"type": "ineq", "fun": lambda t: t[1] + t[3]})
    best = None
    for s in starts:
        try:
            res = optimize.minimize(_nll, s, args=(r, v, gjr, tdist), method="SLSQP", bounds=bounds, constraints=cons,
                                    options={"maxiter": 300, "ftol": 1e-9})
        except Exception:   # noqa: BLE001 — 수렴 실패는 호출부가 직전 모수 유지
            continue
        ok = bool(res.success) and np.isfinite(res.fun) and res.fun < 1e11 and all(c["fun"](res.x) >= -1e-6 for c in cons)
        if ok and (best is None or res.fun < best.fun - 1e-6):
            best = res
    if best is None:
        return None, False
    return np.array(best.x), True


def t_consts(nu: float) -> tuple[float, float, float]:
    """표준화(분산 1) Student-t 의 (VaR99, VaR97.5, ES97.5) 배수."""
    sc = math.sqrt((nu - 2) / nu)
    q99, q975 = stats.t.ppf(0.99, nu), stats.t.ppf(0.975, nu)
    es = stats.t.pdf(q975, nu) / 0.025 * (nu + q975 * q975) / (nu - 1)
    return q99 * sc, q975 * sc, es * sc


def rolling_garch(r: np.ndarray, gjr: bool, tdist: bool) -> dict:
    """1000일 창·21일마다 재추정. 반환: sigma[t](t일 예측 σ, 소수), 배수 3종[t], 모수 기록, 실패 수."""
    n = len(r)
    rp = r * 100.0
    sig = np.full(n, np.nan)
    k99, k975, kes = (np.full(n, np.nan) for _ in range(3))
    theta, fails, hist = None, 0, []
    for t0 in range(EST_WIN, n, REFIT):
        w = rp[t0 - EST_WIN:t0]
        th, ok = fit_garch(w, gjr, tdist, warm=theta)
        if ok:
            theta = th
        else:
            fails += 1
        if theta is None:
            continue
        hist.append(theta.copy())
        t1 = min(t0 + REFIT, n)
        seg = rp[t0 - EST_WIN:t1]
        s2 = garch_filter(seg, theta[0], theta[1], theta[3] if gjr else 0.0, theta[2], float(np.var(w)))
        sig[t0:t1] = np.sqrt(s2[EST_WIN:EST_WIN + (t1 - t0)]) / 100.0
        c = t_consts(theta[-1]) if tdist else (Z99, Z975, K_ES975)
        k99[t0:t1], k975[t0:t1], kes[t0:t1] = c
    H = np.array(hist) if hist else np.zeros((0, 3))
    med = {}
    if len(H):
        med = {"alpha": float(np.median(H[:, 1])), "beta": float(np.median(H[:, 2]))}
        if gjr:
            med["gamma"] = float(np.median(H[:, 3]))
        med["persistence"] = float(np.median(H[:, 1] + H[:, 2] + (0.5 * H[:, 3] if gjr else 0)))
        if tdist:
            med["nu"] = float(np.median(H[:, -1]))
    return {"sigma": sig, "k99": k99, "k975": k975, "kes": kes, "fails": fails, "refits": len(hist), "params_median": med}


def ewma_sigma(r: np.ndarray) -> np.ndarray:
    """σ²_t = λσ²_{t−1} + (1−λ)r²_{t−1}, 초기값 = 첫 250일 표본분산(t=250 부터 유효)."""
    n = len(r)
    s2 = np.full(n, np.nan)
    if n <= HS_DAYS:
        return s2
    s2[HS_DAYS] = float(np.var(r[:HS_DAYS], ddof=1))
    for t in range(HS_DAYS + 1, n):
        s2[t] = LAM * s2[t - 1] + (1 - LAM) * r[t - 1] ** 2
    return np.sqrt(s2)


def hist_sim(r: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """역사적 250일: VaR99 = 최악 3번째, VaR97.5 = 최악 7번째, ES97.5 = 최악 6개 평균."""
    n = len(r)
    v99, v975, es = (np.full(n, np.nan) for _ in range(3))
    k99, k975, kes = math.ceil(0.01 * HS_DAYS), math.ceil(0.025 * HS_DAYS), int(0.025 * HS_DAYS)
    for t in range(HS_DAYS, n):
        w = np.sort(r[t - HS_DAYS:t])
        v99[t], v975[t], es[t] = -w[k99 - 1], -w[k975 - 1], -w[:kes].mean()
    return v99, v975, es


def forecasts(r: np.ndarray) -> tuple[dict, dict]:
    """모형별 {var99, var975, es975} 배열(손실 양수)과 메타."""
    f, meta = {}, {}
    h99, h975, hes = hist_sim(r)
    f["HS250"] = {"var99": h99, "var975": h975, "es975": hes}
    ew = ewma_sigma(r)
    f["EWMA"] = {"var99": Z99 * ew, "var975": Z975 * ew, "es975": K_ES975 * ew}
    f["ENGINE"] = {k: np.fmax(f["HS250"][k], f["EWMA"][k]) for k in ("var99", "var975", "es975")}
    s60 = pd.Series(r).rolling(60).std(ddof=1).shift(1).values
    f["SIG60"] = {"var99": Z99 * s60, "var975": Z975 * s60, "es975": K_ES975 * s60}
    for name, gjr, td in (("GARCH_N", False, False), ("GJR_N", True, False), ("GARCH_T", False, True), ("GJR_T", True, True)):
        g = rolling_garch(r, gjr, td)
        f[name] = {"var99": g["k99"] * g["sigma"], "var975": g["k975"] * g["sigma"], "es975": g["kes"] * g["sigma"]}
        meta[name] = {"fails": g["fails"], "refits": g["refits"], "params_median": {k: round(v, 4) for k, v in g["params_median"].items()}}
    return f, meta


# ── 검정 ──────────────────────────────────────────────────────────────────────
def _xlogy(a, b):
    return float(special.xlogy(a, b))


def kupiec(x: int, n: int, p: float) -> tuple[float, float]:
    """POF 우도비 (χ²1). 반환 (LR, p값)."""
    if n == 0:
        return float("nan"), float("nan")
    ph = x / n
    lr = -2 * (_xlogy(n - x, 1 - p) + _xlogy(x, p) - _xlogy(n - x, 1 - ph) - _xlogy(x, ph))
    return lr, float(stats.chi2.sf(lr, 1))


def christoffersen(hit: np.ndarray) -> tuple[float, float]:
    """독립성 우도비 (χ²1): 초과 다음 날 초과 확률이 평소와 같은가."""
    h = hit.astype(int)
    a, b = h[:-1], h[1:]
    n00, n01 = int(((a == 0) & (b == 0)).sum()), int(((a == 0) & (b == 1)).sum())
    n10, n11 = int(((a == 1) & (b == 0)).sum()), int(((a == 1) & (b == 1)).sum())
    if n01 + n11 == 0 or n00 + n01 == 0 or n10 + n11 == 0:
        return float("nan"), float("nan")
    p01, p11, pp = n01 / (n00 + n01), n11 / (n10 + n11), (n01 + n11) / (n00 + n01 + n10 + n11)
    l0 = _xlogy(n00 + n10, 1 - pp) + _xlogy(n01 + n11, pp)
    l1 = _xlogy(n00, 1 - p01) + _xlogy(n01, p01) + _xlogy(n10, 1 - p11) + _xlogy(n11, p11)
    lr = max(-2 * (l0 - l1), 0.0)
    return lr, float(stats.chi2.sf(lr, 1))


def tick_loss(L: np.ndarray, var: np.ndarray, q: float = 0.99) -> np.ndarray:
    """분위수 손실: 초과하면 초과분×q, 아니면 남는 폭×(1−q)."""
    return (L - var) * (q - (L <= var))


def dm_test(d: np.ndarray, lag: int = NW_LAG) -> tuple[float, float, float]:
    """Diebold–Mariano: mean(d)/NW 표준오차, 양측 정규 p. 반환 (mean, t, p)."""
    d = np.asarray(d, float)
    n = len(d)
    if n < 10:
        return float("nan"), float("nan"), float("nan")
    m = d.mean()
    e = d - m
    lrv = float(e @ e) / n
    for k in range(1, lag + 1):
        lrv += 2 * (1 - k / (lag + 1)) * float(e[k:] @ e[:-k]) / n
    se = math.sqrt(max(lrv, 0) / n)
    if se == 0:
        return m, float("nan"), float("nan")
    t = m / se
    return m, t, float(2 * stats.norm.sf(abs(t)))


def mcneil_frey(L: np.ndarray, var975: np.ndarray, es: np.ndarray, rng) -> dict:
    """VaR97.5 초과일의 (L−ES)/σ 평균 = 0 (단측: >0 = ES 과소). σ 대용 = ES/2.338(정규 모형에선 σ 와 같음)."""
    ex = L > var975
    n = int(ex.sum())
    if n < 5:
        return {"n": n, "ratio": None, "mean_resid": None, "p": None}
    z = (L[ex] - es[ex]) / (es[ex] / K_ES975)
    t0 = z.mean() / (z.std(ddof=1) / math.sqrt(n))
    zc = z - z.mean()
    b = zc[rng.integers(0, n, size=(N_BOOT, n))]
    sd = b.std(axis=1, ddof=1)
    tb = np.where(sd > 0, b.mean(axis=1) / (sd / math.sqrt(n)), 0.0)
    return {"n": n, "ratio": round(float(L[ex].mean() / es[ex].mean()), 3), "mean_resid": round(float(z.mean()), 3),
            "p": round(float((tb >= t0).mean()), 4)}


def traffic(exc: int) -> str:
    return "적" if exc >= 10 else ("황" if exc >= 5 else "녹")


def basel_windows(hit: np.ndarray) -> dict:
    """250일 이동 창 초과 수 → 녹·황·적 비율과 마지막 창."""
    if len(hit) < 250:
        return {"windows": 0}
    c = np.convolve(hit.astype(int), np.ones(250, dtype=int), mode="valid")
    n = len(c)
    return {"windows": n, "green": round(float((c <= 4).mean()), 4), "yellow": round(float(((c >= 5) & (c <= 9)).mean()), 4),
            "red": round(float((c >= 10).mean()), 4), "max": int(c.max()), "last": int(c[-1]), "last_light": traffic(int(c[-1])),
            "zero_share": round(float((c == 0).mean()), 4)}


def evaluate(L: np.ndarray, f: dict, rng) -> dict:
    """한 구간·한 모형: 초과일·진단·신호등·손실."""
    n = len(L)
    h99, h975 = L > f["var99"], L > f["var975"]
    x99, x975 = int(h99.sum()), int(h975.sum())
    lr, p = kupiec(x99, n, 0.01)
    li, pi = christoffersen(h99)
    cc = (lr + li) if li == li else float("nan")
    _, p975 = kupiec(x975, n, 0.025)
    r = lambda v, k=4: (None if v != v else round(float(v), k))   # noqa: E731
    return {"n": n, "exc99": x99, "exp99": round(0.01 * n, 1), "rate99": r(x99 / n if n else float("nan"), 5),
            "kupiec_p": r(p), "christ_p": r(pi), "cc_p": r(float(stats.chi2.sf(cc, 2)) if cc == cc else float("nan")),
            "exc975": x975, "exp975": round(0.025 * n, 1), "kupiec975_p": r(p975),
            "tick99_bp": r(float(tick_loss(L, f["var99"]).mean()) * 1e4), "mean_var99_pct": r(float(f["var99"].mean()) * 100, 3),
            "basel": basel_windows(h99), "es": mcneil_frey(L, f["var975"], f["es975"], rng)}


def crash_table(dates: pd.DatetimeIndex, L: np.ndarray, var: np.ndarray) -> dict:
    out = {}
    for name, (a, b) in CRASH.items():
        m = np.asarray((dates >= a) & (dates <= b))
        n = int(m.sum())
        if n == 0:
            out[name] = {"n": 0}
            continue
        Lm, Vm = L[m], var[m]
        ex = Lm > Vm
        idx = np.flatnonzero(m)
        jump = None
        if ex.any():
            j = idx[np.flatnonzero(ex)[0]]
            if j + 1 < len(var):
                jump = round(float(var[j + 1] / var[j] - 1), 3)
        out[name] = {"n": n, "exc": int(ex.sum()), "exp": round(0.01 * n, 2), "max_ratio": round(float((Lm / Vm).max()), 2),
                     "mean_excess_pp": round(float((Lm[ex] - Vm[ex]).mean() * 100), 2) if ex.any() else 0.0,
                     "sum_excess_pp": round(float(np.maximum(Lm - Vm, 0).sum() * 100), 2), "next_day_var_jump": jump,
                     "mean_var_pct": round(float(Vm.mean() * 100), 2), "worst_loss_pct": round(float(Lm.max() * 100), 2)}
    return out


def grade(oos: tuple, is_: tuple, n_oos: int, idx_same: int | None) -> str:
    """사전등록 §2. oos/is_ = (mean d, t, p)."""
    m, _, p = oos
    if n_oos < 1000:
        return "검증전"
    if m < 0 and p < ALPHA_BONF:
        if is_[0] < 0 and idx_same is not None and idx_same >= 3:
            return "A"
        return "B"
    if m < 0 and p < 0.10:
        return "C"
    if m > 0 and p < 0.10:
        return "C(역방향)"
    return "F"


def holm(ps: dict[str, float], alpha: float = 0.05) -> dict[str, bool]:
    out, m, stop = {}, len(ps), False
    for i, (k, p) in enumerate(sorted(ps.items(), key=lambda kv: kv[1])):
        ok = (not stop) and p < alpha / (m - i)
        stop = stop or not ok
        out[k] = ok
    return out


# ── 실행 ──────────────────────────────────────────────────────────────────────
def run(series: dict[str, pd.Series]) -> dict:
    rng = np.random.default_rng(SEED)
    res = {"series": {}, "meta": {}}
    dm = {h: {} for h in HYP}
    dm_extra = {}
    for s in SERIES:
        rs = series[s]
        r, dates = rs.values.astype(float), rs.index
        f, meta = forecasts(r)
        L = -r
        first = EST_WIN
        is_m = np.zeros(len(r), bool)
        is_m[first:] = np.asarray(dates[first:] <= IS_END)
        oos_m = np.asarray(dates > IS_END)
        out = {"n_ret": len(r), "first_forecast": str(dates[first].date()), "last": str(dates[-1].date()),
               "oos_n": int(oos_m.sum()), "is_n": int(is_m.sum()), "models": {}, "crash": {}, "yearly_exc99": {}}
        for mname in MODELS:
            fm = f[mname]
            out["models"][mname] = {seg: evaluate(L[m], {k: v[m] for k, v in fm.items()}, rng) for seg, m in (("is", is_m), ("oos", oos_m))}
            out["crash"][mname] = crash_table(dates, L, fm["var99"])
            hit = pd.Series((L > fm["var99"])[first:], index=dates[first:])
            out["yearly_exc99"][mname] = {str(y): int(v) for y, v in hit.groupby(hit.index.year).sum().items()}
        for h, (cand, base) in list(HYP.items()) + [("X_GARCH_vs_ENGINE", ("GARCH_N", "ENGINE")), ("X_GARCH_T_vs_ENGINE", ("GARCH_T", "ENGINE")),
                                                      ("X_GJR_T_vs_ENGINE", ("GJR_T", "ENGINE")), ("X_GJR_T_vs_GJR_N", ("GJR_T", "GJR_N")),
                                                      ("X_ENGINE_vs_EWMA", ("ENGINE", "EWMA"))]:
            d = tick_loss(L, f[cand]["var99"]) - tick_loss(L, f[base]["var99"])
            rec = {"oos": dm_test(d[oos_m]), "is": dm_test(d[is_m])}
            (dm[h] if h in HYP else dm_extra.setdefault(h, {}))[s] = rec
        res["series"][s] = out
        res["meta"][s] = meta
    # 가설 등급 (PORT OOS, 지수 4개 방향)
    hyps, ps = {}, {}
    for h, (cand, base) in HYP.items():
        po = dm[h]["PORT"]
        same = sum(1 for s in SERIES[1:] if dm[h][s]["oos"][0] < 0)
        g = grade(po["oos"], po["is"], res["series"]["PORT"]["oos_n"], same)
        ps[h] = po["oos"][2]
        hyps[h] = {"cand": cand, "base": base, "grade": g,
                   "oos_mean_d_bp": round(po["oos"][0] * 1e4, 4), "oos_t": round(po["oos"][1], 2), "oos_p": round(po["oos"][2], 4),
                   "is_mean_d_bp": round(po["is"][0] * 1e4, 4), "is_t": round(po["is"][1], 2), "is_p": round(po["is"][2], 4),
                   "index_same_sign": same,
                   "by_series_oos": {s: {"mean_d_bp": round(dm[h][s]["oos"][0] * 1e4, 4), "t": round(dm[h][s]["oos"][1], 2),
                                         "p": round(dm[h][s]["oos"][2], 4)} for s in SERIES}}
    hl = holm(ps)
    for h in hyps:
        hyps[h]["holm_pass"] = bool(hl[h])
    res["hypotheses"] = hyps
    res["exploratory_dm"] = {h: {s: {"oos_mean_d_bp": round(v["oos"][0] * 1e4, 4), "oos_t": round(v["oos"][1], 2), "oos_p": round(v["oos"][2], 4),
                                     "is_mean_d_bp": round(v["is"][0] * 1e4, 4)} for s, v in d.items()} for h, d in dm_extra.items()}
    res["adoption"] = adoption(res)
    return res


def adoption(res: dict) -> dict:
    """사전등록 §3 채택선 — PORT OOS."""
    P = res["series"]["PORT"]
    eng = P["models"]["ENGINE"]["oos"]
    eng_crash = sum(v.get("sum_excess_pp", 0) for v in P["crash"]["ENGINE"].values())
    out = {"engine": {"kupiec_p": eng["kupiec_p"], "christ_p": eng["christ_p"], "red_share": eng["basel"].get("red"),
                      "crash_sum_excess_pp": round(eng_crash, 2), "exc99": eng["exc99"], "exp99": eng["exp99"]}}
    for cand, h in (("GJR_N", "H4"), ("GARCH_N", None)):
        o = P["models"][cand]["oos"]
        cs = round(sum(v.get("sum_excess_pp", 0) for v in P["crash"][cand].values()), 2)
        g = res["hypotheses"][h]["grade"] if h else "m 밖(상한 C)"
        c1 = bool(h) and g in ("A", "B")
        c2 = (o["kupiec_p"] or 0) >= 0.05 and (o["christ_p"] is None or o["christ_p"] >= 0.05)
        c3 = o["basel"].get("red", 1) <= eng["basel"].get("red", 0)
        c4 = cs <= round(eng_crash, 2)
        verdict = "교체 제안" if (c1 and c2 and c3 and c4) else ("교체 근거 부족 · 계기판 병기 후보" if (c2 and c3 and c4) else "현행 유지")
        out[cand] = {"c1_tick_grade_B_plus": c1, "grade_vs_engine": g, "c2_kupiec_christ": bool(c2), "kupiec_p": o["kupiec_p"],
                     "christ_p": o["christ_p"], "christ_note": "초과 연속 0회면 계산 불가(None) — 연속 없음 = 독립성 위반 증거 없음으로 처리",
                     "c3_red_share_le_engine": bool(c3), "red_share": o["basel"].get("red"),
                     "c4_crash_excess_le_engine": bool(c4), "crash_sum_excess_pp": cs, "verdict": verdict}
    out["verdict"] = "교체 제안" if any(out[c]["verdict"] == "교체 제안" for c in ("GJR_N",)) else "현행 유지"
    return out


def build_json(res: dict) -> dict:
    return {"id": "2026-11-10_var_models", "generated": "2026-11-10", "asof": END, "desk": "quant",
            "request": ["req-quant-67015597", "req-frm-1906c9d1"],
            "prereg": {"doc": PREREG, "commit": "f5936b5b4", "m": M, "alpha_bonf": ALPHA_BONF, "is_end": IS_END, "oos_start": "2020-01-01",
                       "est_window": EST_WIN, "refit_days": REFIT, "ewma_lambda": LAM, "hs_days": HS_DAYS, "nw_lag": NW_LAG, "seed": SEED,
                       "cost": "해당 없음(매매 없는 리스크 측정 연구)",
                       "survivorship": "지수·현재 상장 ETF 만 사용 — 상장폐지 상품 없음(영향 작음)",
                       "dsr_pbo": "해당 없음(수익 전략 아님 — 샤프 선택 편향 대상 아님)",
                       "exploratory": 2, "port_weights": PORT_W},
            "grades": {h: v["grade"] for h, v in res["hypotheses"].items()},
            **res}


# ── 보고서 ────────────────────────────────────────────────────────────────────
NAMES = {"HS250": "역사적 250일", "EWMA": "EWMA λ0.94", "ENGINE": "현 엔진(둘 중 큰 값)", "GARCH_N": "GARCH(1,1) 정규",
         "GJR_N": "GJR-GARCH 정규", "SIG60": "60일 σ(공개 계기판)", "GARCH_T": "GARCH-t(보조)", "GJR_T": "GJR-t(보조)"}


def _f(v, nd=2, pct=False):
    if v is None:
        return "–"
    return f"{v * 100:.{nd}f}%" if pct else f"{v:.{nd}f}"


def model_table(S: dict, seg: str) -> list[str]:
    out = ["| 모형 | 초과일(99%) | 기대 | 초과율 | Kupiec p | 독립성 p | 평균 VaR99 | tick 손실(bp) | 250일 창 녹/황/적 | 창 최대 | 초과일(97.5%) | 기대 | ES 비율 | ES p |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for m in MODELS:
        o = S["models"][m][seg]
        b, e = o["basel"], o["es"]
        bw = f"{b['green'] * 100:.0f}/{b['yellow'] * 100:.0f}/{b['red'] * 100:.0f}%" if b.get("windows") else "–"
        out.append(f"| {NAMES[m]} | {o['exc99']} | {o['exp99']} | {_f(o['rate99'], 2, True)} | {_f(o['kupiec_p'], 3)} | {_f(o['christ_p'], 3)} | "
                   f"{o['mean_var99_pct']:.2f}% | {o['tick99_bp']:.3f} | {bw} | {b.get('max', '–')} | {o['exc975']} | {o['exp975']} | {_f(e['ratio'])} | {_f(e['p'], 3)} |")
    return out


def build_md(j: dict) -> str:
    P = j["series"]["PORT"]
    H, A = j["hypotheses"], j["adoption"]
    eng, ew, ga, gj = (P["models"][m]["oos"] for m in ("ENGINE", "EWMA", "GARCH_N", "GJR_N"))
    cs = {m: round(sum(v.get("sum_excess_pp", 0) for v in P["crash"][m].values()), 2) for m in MODELS}
    cx = {m: sum(v.get("exc", 0) for v in P["crash"][m].values()) for m in MODELS}
    L = []
    L += ["# VaR 변동성 모델 비교 — EWMA·GARCH(1,1)·GJR-GARCH 초과일 백테스트 (2026-11-10, 퀀트)", "",
          f"등급: H1 {H['H1']['grade']} · H2 {H['H2']['grade']} · H3 {H['H3']['grade']} · H4 {H['H4']['grade']} (무엇 대비는 §2 표) · 신뢰도 중 · "
          "**연구 카드 — 규칙·엔진 변경 아님**(엔진 교체는 결재 사항) · 비율·지수 대용만 · 매매 지시 아님.",
          f"요청 req-quant-67015597(FRM 짝 req-frm-1906c9d1) · 사전등록 `{PREREG}`(결과 전 커밋 f5936b5b4) · 기준 {j['asof']} · "
          "코드 `scripts/study_var_models.py` · 원자료 `reports/studies/2026-11-10_var_models.json`.", "",
          "## 요약 (What · So What · Now What)", "", "**What**",
          f"- 코어 대용 포트(PORT) 2020-01~2026-11 {eng['n']}거래일에서 99% VaR 를 넘은 날: 현 엔진 {eng['exc99']}일 · EWMA {ew['exc99']}일 · "
          f"GARCH {ga['exc99']}일 · GJR {gj['exc99']}일 (기대 {eng['exp99']}일).",
          f"- 급락 구간 4곳에서 VaR 를 넘어선 손실의 합: 현 엔진 {cs['ENGINE']}%p · EWMA {cs['EWMA']}%p · GARCH {cs['GARCH_N']}%p · GJR {cs['GJR_N']}%p.",
          f"- 사전등록 판정(tick 손실, 문턱 p < {ALPHA_BONF}): GJR vs 현 엔진 p {H['H4']['oos_p']}({H['H4']['grade']}) · GJR vs EWMA p {H['H2']['oos_p']}({H['H2']['grade']}) · "
          f"GARCH vs EWMA p {H['H1']['oos_p']}({H['H1']['grade']}) · GJR vs GARCH p {H['H3']['oos_p']}({H['H3']['grade']}).",
          "", "**So What**",
          f"- 채택선(사전등록 §3) 판정 = **{A['verdict']}**. GJR: {A['GJR_N']['verdict']} · GARCH: {A['GARCH_N']['verdict']}.",
          "- 뒤집는 조건: 비공개 저장소 실제 북 수익률로 같은 절차를 돌렸을 때 GJR 이 현 엔진 대비 tick 손실 B 이상이고 §3 의 2~4 를 모두 넘으면 재상정.",
          "- 반대 근거: PORT 는 채권·금이 30% 섞인 대용이라 반도체 비중이 큰 실제 북보다 꼬리가 얇다 — 지수 단독 표(§5)가 실제 북에 더 가까울 수 있다.",
          "", "**Now What**",
          "- 퀀트: 이 결과를 FRM 에 넘김(해석·엔진 정합은 FRM 몫). 엔진 코드는 건드리지 않음.",
          "- FRM: 아래 'FRM 한 줄' 확인 뒤 req-frm-1906c9d1 회신. 실제 북 재실행 여부는 FRM 판단.",
          "", "**원본**", "- reports/studies/2026-11-10_var_models.json", "- scripts/study_var_models.py", f"- {PREREG}", "", "---", "",
          "## 0. 용어 풀이 (처음 보는 사람용)",
          "- **VaR99(1일)**: '100거래일 중 99일은 하루 손실이 이 값 안'이라는 선. 250일에 2.5번쯤 넘는 게 정상이다.",
          "- **ES97.5**: 최악 2.5% 날들의 평균 손실. VaR 를 넘은 날 '얼마나 깊게' 넘는지 본다.",
          "- **초과일**: 실제 손실이 전날 계산한 VaR 를 넘은 날. 너무 많으면 모형이 위험을 작게 본 것, 0에 가까우면 너무 크게 본 것.",
          "- **EWMA**: 최근 날에 가중을 더 주는 변동성 평균(어제 6%, 그 전은 94%씩 줄어듦). 급락 뒤 빨리 오르지만 평소 수준으로 돌아가는 힘이 없다.",
          "- **GARCH(1,1)**: EWMA 에 '장기 평균으로 돌아가는 힘'을 더한 모형. 모수를 과거 1000일로 추정한다.",
          "- **GJR-GARCH**: GARCH 에 '하락한 날은 변동성이 더 뛴다'(비대칭)를 더한 모형.",
          "- **Kupiec 검정**: 초과일 수가 기대와 맞는지. p 가 0.05 미만이면 '안 맞는다'. **독립성(Christoffersen)**: 초과일이 연달아 몰리는지.",
          "- **바젤 신호등**: 250일 창 초과 0~4회 녹, 5~9회 황, 10회 이상 적.",
          "- **tick 손실**: VaR 를 넘으면 넘은 폭에 큰 벌점(×0.99), 안 넘으면 남는 폭에 작은 벌점(×0.01). 과소도 과대도 깎는 종합 점수 — 작을수록 좋다.",
          "- **IS/OOS**: 2014~2019 는 방향 확인용(IS), 2020~2026 이 판정 구간(OOS).", "",
          "## 1. 설계 (사전등록 그대로)",
          f"- 표본 {START}~{END} · 계열 5개(PORT·KOSPI·KOSPI200·S&P500·나스닥) · 전부 1일 앞 예측(t일 VaR 는 t−1일까지 자료).",
          f"- PORT = S&P500 40 · NDX 15 · K200 15 · 국고3년 20 · 금 10(코어 C안 비율, `screener/defs.py` 30행) 매일 재조정. 미국 다리는 전날 미국 종가×환율.",
          f"- GARCH·GJR: 직전 {EST_WIN}일로 {REFIT}일마다 재추정, 정규 분포. 수렴 실패 {sum(j['meta'][s][m]['fails'] for s in SERIES for m in ('GARCH_N', 'GJR_N'))}회"
          f"(재추정 {sum(j['meta'][s][m]['refits'] for s in SERIES for m in ('GARCH_N', 'GJR_N'))}회 중).",
          f"- 가설 m = {M}, Bonferroni α = {ALPHA_BONF}. 시도 일지 주제 var_model N = 4 + 보조 2.",
          f"- PORT 첫 예측 {P['first_forecast']} · IS {P['is_n']}일 · OOS {P['oos_n']}일.", "",
          "## 2. 가설 판정 (PORT · OOS · tick 손실 차이 = 후보 − 기준, 음수면 후보가 나음)", "",
          "| 가설 | 후보 vs 기준 | OOS 차이(bp/일) | t | p | IS 차이(bp/일) | 지수 4개 중 같은 부호 | α/m | Holm | 등급 |", "|---|---|---|---|---|---|---|---|---|---|"]
    for h, v in H.items():
        L.append(f"| {h} | {NAMES[v['cand']]} vs {NAMES[v['base']]} | {v['oos_mean_d_bp']:+.4f} | {v['oos_t']:+.2f} | {v['oos_p']:.4f} | {v['is_mean_d_bp']:+.4f} | "
                 f"{v['index_same_sign']}/4 | {ALPHA_BONF} | {'통과' if v['holm_pass'] else '미통과'} | **{v['grade']}** |")
    L += ["", "결론 줄:"]
    for h, v in H.items():
        L.append(f"- {h} {NAMES[v['cand']]} < {NAMES[v['base']]} · 효과 {v['oos_mean_d_bp']:+.4f}bp/일 · p(IS {v['is_p']}/OOS {v['oos_p']}) · α/m {ALPHA_BONF} · α(N) {ALPHA_BONF} · "
                 f"등급 {v['grade']} · 신뢰도 중 · 뒤집는 조건: 실제 북 재실행에서 부호 반대")
    L += ["", "## 3. PORT 모형별 성적", "", "### 3-1. OOS (2020-01 ~ 2026-11, 판정 구간)", ""] + model_table(P, "oos")
    L += ["", "### 3-2. IS (2014 ~ 2019, 방향 확인용)", ""] + model_table(P, "is")
    L += ["", "- 'ES 비율' = VaR97.5 를 넘은 날의 실제 손실 평균 ÷ 그날 ES 예측 평균(1 보다 크면 ES 과소). 'ES p' = McNeil–Frey 단측 부트스트랩(작으면 과소).",
          "- 독립성 p 가 '–' 면 초과일이 한 번도 연달아 나오지 않아 계산 불가(몰림 증거 없음).", "",
          "## 4. 급락 구간 (PORT · VaR99)", "",
          "| 구간 | 모형 | 거래일 | 초과일 | 기대 | 최악 하루 손실 | 최대 손실/VaR 배수 | 초과분 평균(%p) | 초과분 합(%p) | 첫 초과 다음 날 VaR 변화 |", "|---|---|---|---|---|---|---|---|---|---|"]
    for c in CRASH:
        for m in ("ENGINE", "EWMA", "HS250", "GARCH_N", "GJR_N", "GJR_T"):
            v = P["crash"][m][c]
            if not v.get("n"):
                continue
            jmp = "–" if v["next_day_var_jump"] is None else f"{v['next_day_var_jump'] * 100:+.0f}%"
            L.append(f"| {c} | {NAMES[m]} | {v['n']} | {v['exc']} | {v['exp']} | {v['worst_loss_pct']:.2f}% | {v['max_ratio']:.2f} | {v['mean_excess_pp']:.2f} | {v['sum_excess_pp']:.2f} | {jmp} |")
    L += ["", "급락 구간 4곳 합산(과소평가 폭):", "", "| 모형 | 초과일 합 | 초과분 합(%p) |", "|---|---|---|"]
    for m in MODELS:
        L.append(f"| {NAMES[m]} | {cx[m]} | {cs[m]} |")
    L += ["", "- 구간별 초과일은 한 자릿수라 서술용이다(사전등록 §5).", "",
          "## 5. 지수별 OOS (같은 표, 보조)", ""]
    for s in SERIES[1:]:
        L += [f"### {s} (OOS {j['series'][s]['oos_n']}일)", ""] + model_table(j["series"][s], "oos") + [""]
    L += ["지수별 tick 손실 차이(OOS, bp/일 · 괄호 p):", "", "| 가설 | " + " | ".join(SERIES) + " |", "|---|" + "---|" * len(SERIES)]
    for h, v in H.items():
        L.append(f"| {h} | " + " | ".join(f"{v['by_series_oos'][s]['mean_d_bp']:+.4f} ({v['by_series_oos'][s]['p']:.3f})" for s in SERIES) + " |")
    L += ["", "## 6. 채택선 판정 (사전등록 §3 · PORT OOS)", "",
          "| 조건 | 현 엔진 | GJR 정규 | GARCH 정규 |", "|---|---|---|---|",
          f"| ① 엔진 대비 tick 손실 B 이상 | – | {A['GJR_N']['grade_vs_engine']} → {'충족' if A['GJR_N']['c1_tick_grade_B_plus'] else '미충족'} | {A['GARCH_N']['grade_vs_engine']} → 미충족 |",
          f"| ② Kupiec p ≥ 0.05 · 독립성 p ≥ 0.05 | {_f(A['engine']['kupiec_p'], 3)} · {_f(A['engine']['christ_p'], 3)} | {_f(A['GJR_N']['kupiec_p'], 3)} · {_f(A['GJR_N']['christ_p'], 3)} → {'충족' if A['GJR_N']['c2_kupiec_christ'] else '미충족'} | "
          f"{_f(A['GARCH_N']['kupiec_p'], 3)} · {_f(A['GARCH_N']['christ_p'], 3)} → {'충족' if A['GARCH_N']['c2_kupiec_christ'] else '미충족'} |",
          f"| ③ 250일 창 '적' 비율 ≤ 엔진 | {_f(A['engine']['red_share'], 1, True)} | {_f(A['GJR_N']['red_share'], 1, True)} → {'충족' if A['GJR_N']['c3_red_share_le_engine'] else '미충족'} | "
          f"{_f(A['GARCH_N']['red_share'], 1, True)} → {'충족' if A['GARCH_N']['c3_red_share_le_engine'] else '미충족'} |",
          f"| ④ 급락 4구간 초과분 합 ≤ 엔진 | {A['engine']['crash_sum_excess_pp']}%p | {A['GJR_N']['crash_sum_excess_pp']}%p → {'충족' if A['GJR_N']['c4_crash_excess_le_engine'] else '미충족'} | "
          f"{A['GARCH_N']['crash_sum_excess_pp']}%p → {'충족' if A['GARCH_N']['c4_crash_excess_le_engine'] else '미충족'} |",
          f"| 판정 | – | **{A['GJR_N']['verdict']}** | **{A['GARCH_N']['verdict']}** |", "",
          "## 7. 보조 (사후 해석 상한 C — 등급에 안 씀)", "",
          "tick 손실 차이(PORT OOS, bp/일):", "", "| 비교 | 차이 | t | p |", "|---|---|---|---|"]
    xn = {"X_GARCH_vs_ENGINE": "GARCH 정규 vs 현 엔진", "X_GARCH_T_vs_ENGINE": "GARCH-t vs 현 엔진", "X_GJR_T_vs_ENGINE": "GJR-t vs 현 엔진",
          "X_GJR_T_vs_GJR_N": "GJR-t vs GJR 정규", "X_ENGINE_vs_EWMA": "현 엔진 vs EWMA"}
    for h, d in j["exploratory_dm"].items():
        v = d["PORT"]
        L.append(f"| {xn[h]} | {v['oos_mean_d_bp']:+.4f} | {v['oos_t']:+.2f} | {v['oos_p']:.4f} |")
    L += ["", "추정 모수 중앙값(재추정 전체):", "", "| 계열 | 모형 | α | γ(비대칭) | β | 지속성 | ν(t 자유도) |", "|---|---|---|---|---|---|---|"]
    for s in SERIES:
        for m in ("GARCH_N", "GJR_N", "GJR_T"):
            pm = j["meta"][s][m]["params_median"]
            L.append(f"| {s} | {NAMES[m]} | {_f(pm.get('alpha'), 3)} | {_f(pm.get('gamma'), 3)} | {_f(pm.get('beta'), 3)} | {_f(pm.get('persistence'), 3)} | {_f(pm.get('nu'), 1)} |")
    L += ["", "PORT 연도별 VaR99 초과일:", "", "| 모형 | " + " | ".join(P["yearly_exc99"]["ENGINE"].keys()) + " |", "|---|" + "---|" * len(P["yearly_exc99"]["ENGINE"])]
    for m in MODELS:
        L.append(f"| {NAMES[m]} | " + " | ".join(str(v) for v in P["yearly_exc99"][m].values()) + " |")
    L += ["", "__INTERP__", ""]
    return "\n".join(L)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-write", action="store_true")
    a = ap.parse_args()
    res = run(load_series())
    j = build_json(res)
    if a.no_write:
        print(json.dumps({"grades": j["grades"], "adoption": j["adoption"]}, ensure_ascii=False, indent=1))
        return
    OUT.with_suffix(".json").write_text(json.dumps(j, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    interp = OUT.parent / "2026-11-10_var_models_interp.md"   # 사람이 쓴 해석·한계 절(있으면 끼움)
    md = build_md(j).replace("__INTERP__", interp.read_text(encoding="utf-8").strip() if interp.exists() else "")
    OUT.with_suffix(".md").write_text(md.rstrip() + "\n", encoding="utf-8")
    print("wrote", OUT.with_suffix(".json"), OUT.with_suffix(".md"))
    print(json.dumps({"grades": j["grades"], "adoption": j["adoption"]}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
