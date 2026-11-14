"""변동성 타게팅 + GEX 감마 국면 — 비중(노출) 조절 계산·백테스트 모듈 (연구 전용, 매매 지시 아님).

무엇: 지수(K200) 노출 비중만 0~100% 사이에서 조절하는 두 겹의 규칙을 계산한다.
      ① 변동성 타게팅 — 최근 실현변동성이 목표보다 높으면 비중을 줄이고 낮으면 늘린다
      ② GEX 감마 국면 — 딜러 숏감마 구간(`gex_bn < 0`)이면 비중 상한을 한 번 더 깎는다
      기존 실계좌 룰은 건드리지 않는다(호출하는 쪽이 판단). 이 모듈은 계산기다.

정의 (연율 %, 예: 15.0 = 연 15%)
  RV20 = 최근 20거래일 일간 로그수익률 표본표준편차 × √252  (`screener.vrp_filter.realized_vol` 재사용)
  w_vt = clip(target_vol / RV20, 0, max_w)                  ← 목표 변동성 ÷ 현재 변동성
  w    = w_vt × gex_mult(gex_bn)                            ← gex_mult = 0.6 if gex_bn < 0 else 1.0

실행 시점 (전방 누수 0)
  t일 종가까지의 정보로 w(t)를 정하고, 그 비중을 **t+1일** 종가-종가 수익률에 적용한다
  (`backtest(lag=1)`). 체결 가정은 t일 종가 동시호가 [가정: 슬리피지는 비용 bp에 포함].
  하루 더 늦춘 `lag=2`(t+1일 종가 체결)도 계산할 수 있다 — 실행 시점 민감도용.

비용·회전율
  편도 비용 = |w(t) − w(t−1)| × cost_bp/10,000. 노트레이드 밴드(band) 안의 변화는 무시한다
  (밴드 = |목표 − 보유| 가 band 이하이면 리밸런싱 스킵). 밴드로도 회전율이 남으면 비용이 성과를 갉는다.

주의
- RV20 은 t일 종가까지로만 계산한다(전방 정보 없음). gex_bn 은 t일 종가 시점 값.
- gex_bn 부호는 미국식 관례(딜러 콜 롱·풋 숏) 가정 — 한국 매매주체 구성이 다르면 부호가 뒤집힌다
  (docs/desk_kb/derivs.md). 그래서 부호 반전 민감도를 스크립트에서 함께 계산한다.
- 여기서는 현금 이자를 0으로 두는 것이 기본(보수적). cash_rate 로 바꿔 볼 수 있다.
- 등급·판정은 연구 스크립트(`scripts/study_gex_vol_target.py`)가 매긴다.

영향 범위  연구 전용 계산 모듈 — 어떤 워크플로·탭·알림도 import 하지 않는다(grep gex_vol_target).
롤백      git revert <도입 커밋> (파일 5개: 모듈·스크립트·테스트·보고서 2개, 연구 파이프라인·trial_log 2행).
테스트    tests/test_gex_vol_target.py (순수 함수·누수 없음·비용·밴드·부트스트랩).
"""
from __future__ import annotations

import math

import numpy as np

from screener.vrp_filter import realized_vol

TRADING_DAYS = 252


# ── 신호: 목표 비중 ──────────────────────────────────────────────────
def vol_target_weight(rv_pct, target_vol: float = 13.0, max_w: float = 1.0, min_w: float = 0.0):
    """RV20(%) → 변동성 타게팅 비중 = clip(target/RV, min_w, max_w). RV 결측·0 이하는 min_w."""
    rv = np.asarray(rv_pct, dtype=float)
    w = np.full(rv.shape, float(min_w))
    ok = np.isfinite(rv) & (rv > 0)
    w[ok] = np.clip(float(target_vol) / rv[ok], float(min_w), float(max_w))
    return w


def gex_regime(gex_bn) -> str:
    """딜러 감마 국면 이름. gex_bn < 0 → 'short_gamma'(딜러 숏감마), > 0 → 'long_gamma'."""
    if gex_bn is None:
        return "unknown"
    g = float(gex_bn)
    if not math.isfinite(g):
        return "unknown"
    return "short_gamma" if g < 0 else "long_gamma"


def gex_mult(gex_bn, scale: float = 0.6) -> float:
    """숏감마 구간이면 scale, 그 밖(롱감마·결측)은 1.0. 결측을 1.0 로 두는 이유: 모르는 날은 규칙 미적용."""
    return float(scale) if gex_regime(gex_bn) == "short_gamma" else 1.0


def target_weight(rv_pct, gex_bn=None, *, target_vol: float = 13.0, max_w: float = 1.0,
                  scale: float = 0.6, invert_gex: bool = False):
    """두 겹 규칙 합성 → t일 목표 비중. invert_gex=True 는 부호 가정 반전 민감도(gex>0 이 숏감마)."""
    w = vol_target_weight(rv_pct, target_vol=target_vol, max_w=max_w)
    g = np.asarray(gex_bn, dtype=float) if gex_bn is not None else np.full(w.shape, np.nan)
    short = np.isfinite(g) & ((g > 0) if invert_gex else (g < 0))
    w = np.where(short, w * float(scale), w)
    return w


def regime_flip(gex_bn) -> np.ndarray:
    """t일 국면이 t−1일과 달라진 날(부호 전환). 밴드를 무시하고 리밸런싱할 날 표시."""
    g = np.asarray(gex_bn, dtype=float)
    sign = np.sign(np.where(np.isfinite(g), g, np.nan))
    flip = np.zeros(g.shape, dtype=bool)
    prev = np.nan
    for i, s in enumerate(sign):
        if np.isfinite(s):
            flip[i] = bool(np.isfinite(prev) and s != prev)
            prev = s
    return flip


def apply_band(w_target: float, w_held: float, band: float, force: bool = False) -> float:
    """노트레이드 밴드 — 목표와 보유의 차가 band 이하이면 보유 유지, force 면 밴드 무시."""
    if not np.isfinite(w_target):
        return float(w_held)
    if force or abs(float(w_target) - float(w_held)) > float(band):
        return float(w_target)
    return float(w_held)


# ── 백테스트 엔진 ────────────────────────────────────────────────────
def backtest(asset_ret, w_target, *, cost_bp: float = 10.0, band: float = 0.10,
             cash_rate: float = 0.0, force=None, lag: int = 1) -> dict:
    """일간 순수익률 계산. w_target[i] = i일 종가에 정한 목표 비중, lag=1 → i+1일 수익에 적용.

    반환 {ret, held, trade, cost}: ret = 일간 순수익률(첫 lag칸 NaN), held = 그날 실제 보유 비중,
         trade = 그날 회전(|Δw|), cost = 비용 차감분(|Δw|×cost_bp/1e4).
    """
    r = np.asarray(asset_ret, dtype=float)
    tgt = np.asarray(w_target, dtype=float)
    n = r.size
    cash_d = (1.0 + float(cash_rate)) ** (1.0 / TRADING_DAYS) - 1.0
    held = np.zeros(n)
    ret = np.full(n, np.nan)
    trade = np.zeros(n)
    prev = 0.0
    for i in range(n):
        j = i - int(lag)
        want = tgt[j] if j >= 0 else 0.0
        force_i = bool(force[j]) if (force is not None and j >= 0) else False
        w = apply_band(want, prev, band, force_i)
        trade[i] = abs(w - prev)
        if np.isfinite(r[i]):
            ret[i] = w * r[i] + (1.0 - w) * cash_d - trade[i] * float(cost_bp) / 10_000.0
        held[i] = w
        prev = w
    return {"ret": ret, "held": held, "trade": trade, "cost": trade * float(cost_bp) / 10_000.0}


def expanding_mean(w_target, min_obs: int = 20) -> np.ndarray:
    """확장 평균 비중(동일 평균 노출 대조군) — t일에는 t−1일까지의 평균만 쓴다(전방 누수 없음)."""
    w = np.asarray(w_target, dtype=float)
    out = np.full(w.shape, np.nan)
    acc = 0.0
    cnt = 0
    for i, x in enumerate(w):
        if cnt >= min_obs:
            out[i] = acc / cnt
        if np.isfinite(x):
            acc += x
            cnt += 1
    return out


# ── 성과 지표 ────────────────────────────────────────────────────────
def perf_metrics(rets, periods: int = TRADING_DAYS) -> dict:
    """일간 순수익률 → CAGR·연변동성·샤프·MDD·Calmar·최종 배수. 무위험 0 가정."""
    r = np.asarray(rets, dtype=float)
    r = r[np.isfinite(r)]
    if r.size < 2:
        return {"n": int(r.size)}
    eq = np.cumprod(1.0 + r)
    years = r.size / periods
    total = float(eq[-1])
    cagr = total ** (1.0 / years) - 1.0 if total > 0 else -1.0
    vol = float(np.std(r, ddof=1) * math.sqrt(periods))
    sharpe = float(np.mean(r) / np.std(r, ddof=1) * math.sqrt(periods)) if np.std(r, ddof=1) > 0 else None
    peak = np.maximum.accumulate(eq)
    mdd = float((eq / peak - 1.0).min())
    return {"n": int(r.size), "years": round(years, 2), "total_x": round(total, 4),
            "cagr": cagr, "vol": vol, "sharpe": sharpe, "mdd": mdd,
            "calmar": (cagr / abs(mdd)) if mdd < 0 else None}


def ann_turnover(trade, rets) -> float:
    """연 회전율(편도 합계) = Σ|Δw| ÷ 연수."""
    t = np.asarray(trade, dtype=float)
    n = int(np.isfinite(np.asarray(rets, dtype=float)).sum())
    return float(np.nansum(t) / (n / TRADING_DAYS)) if n else float("nan")


def block_bootstrap_sharpe_diff(a, b, *, block: int = 20, n_boot: int = 2000, seed: int = 7) -> dict:
    """두 수익률 계열의 샤프 차(a−b) 블록 부트스트랩 단측 p.

    겹침·자기상관을 무시하는 iid 부트스트랩은 p를 과소평가하므로 block일 묶음으로 재표집한다(kb:quant#10).
    반환 {diff, p_one, ci90, n_boot, block} — p_one = 재표집에서 차 ≤ 0 인 비율.
    """
    x = np.asarray(a, dtype=float)
    y = np.asarray(b, dtype=float)
    m = np.isfinite(x) & np.isfinite(y)
    x, y = x[m], y[m]
    n = x.size
    if n < block * 3:
        return {"diff": None, "p_one": None, "n": int(n)}
    sd_x, sd_y = np.std(x, ddof=1), np.std(y, ddof=1)
    obs = float(np.mean(x) / sd_x - np.mean(y) / sd_y) * math.sqrt(TRADING_DAYS)
    rng = np.random.default_rng(seed)
    n_blocks = int(math.ceil(n / block))
    draws = np.empty(n_boot)
    for k in range(n_boot):
        starts = rng.integers(0, n - block + 1, n_blocks)
        idx = (starts[:, None] + np.arange(block)[None, :]).ravel()[:n]
        bx, by = x[idx], y[idx]
        sx, sy = np.std(bx, ddof=1), np.std(by, ddof=1)
        draws[k] = (bx.mean() / sx - by.mean() / sy) * math.sqrt(TRADING_DAYS) if sx > 0 and sy > 0 else 0.0
    return {"diff": obs, "p_one": float((draws <= 0).mean()), "n_boot": int(n_boot), "block": int(block),
            "ci90": [float(np.quantile(draws, 0.05)), float(np.quantile(draws, 0.95))], "n": int(n)}
