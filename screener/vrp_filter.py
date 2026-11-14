"""VRP(분산 리스크 프리미엄) 반등 필터 — 순수 계산·검증 모듈 (연구 전용, 매매 지시 아님).

무엇: 급락 뒤 반등 구간에서 '급락폭·고IV'만 보지 않고 **내재변동성과 실현변동성의 부호**로
      두 국면을 갈라 본다 — 공포 과잉(VRP > 0) vs 실제 변동성 폭발(VRP ≤ 0).
      기존 실계좌 룰은 건드리지 않는다(호출하는 쪽이 판단). 이 모듈은 계산만 한다.

정의 (연율 %, 예: IV 42.3 = 연 42.3%)
  IV    = 대표 내재변동성 — `data/deriv/daily.csv` 의 rep_iv (KRX 대표 IV, 2010~)
  RV20  = 최근 20거래일 일간 로그수익률 표준편차 × √252
  VRP(분산형) = (IV/100)² − (RV20/100)²   ← 무차원(연율 분산). Carr–Wu(2009) 의 IV²−RV²
  VRP(변동성형) = IV − RV20                ← 단위 변동성 %p. 현업 표기 'IV−RV'

부호 해석 (가설의 핵심)
  VRP > 0  → 내재가 실현보다 비싸다 = 공포 프리미엄이 남아 있다('공포 과잉' 쪽)
  VRP ≤ 0  → 실현이 내재를 추월 = 이미 실제 변동성이 폭발한 국면('공포 과잉' 아님)

주의
- IV 는 **당일 종가 시점** 값, RV20 은 t−19~t 종가로만 계산한다(전방 정보 없음). 진입은 t 종가 가정.
- 지수 하나(KOSPI)의 대표 IV 라 개별 종목·개별 옵션에 그대로 옮기지 않는다.
- 등급·판정은 연구 스크립트(`scripts/study_vrp_rebound_filter.py`)가 매긴다. 여기는 계산기다.
"""
from __future__ import annotations

import math

import numpy as np

TRADING_DAYS = 252


# ── 기본 계산 ────────────────────────────────────────────────────────
def realized_vol(closes, window: int = 20, ann: int = TRADING_DAYS) -> np.ndarray:
    """종가 배열 → 연율 실현변동성 %(앞 window 칸은 NaN). 표본표준편차(ddof=1)·로그수익률."""
    px = np.asarray(closes, dtype=float)
    n = px.size
    out = np.full(n, np.nan)
    if n < window + 1:
        return out
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.diff(np.log(px))
    for i in range(window, n):
        w = r[i - window:i]
        out[i] = float(np.std(w, ddof=1)) * math.sqrt(ann) * 100.0
    return out


def vrp_variance(iv_pct, rv_pct):
    """IV²−RV² (무차원 연율 분산). 어느 한쪽이 없으면 nan."""
    iv = np.asarray(iv_pct, dtype=float) / 100.0
    rv = np.asarray(rv_pct, dtype=float) / 100.0
    with np.errstate(invalid="ignore"):
        return iv ** 2 - rv ** 2


def vrp_volatility(iv_pct, rv_pct):
    """IV−RV (변동성 %p) — 현업 표기 'IV−RV'. 부호 판정은 분산형과 대체로 같지만 크기 해석이 다르다."""
    return np.asarray(iv_pct, dtype=float) - np.asarray(rv_pct, dtype=float)


def regime(vrp, band: float = 0.0) -> str:
    """부호 → 국면 이름. band 만큼 0 근처를 '중립'으로 둘 수 있다(기본 0 = 부호 그대로)."""
    if vrp is None or (isinstance(vrp, float) and math.isnan(vrp)):
        return "unknown"
    if vrp > band:
        return "fear_excess"        # 공포 과잉 — 내재가 실현보다 비싸다
    if vrp < -band:
        return "realized_breakout"  # 실현변동성 폭발 — 내재가 실현보다 싸다
    return "neutral"


# ── 반등 진입 관문 ──────────────────────────────────────────────────
def rebound_gate(iv_pct: float, rv_pct: float, *, mode: str = "variance", band: float = 0.0) -> dict:
    """반등 구간 진입 관문 1건 판정.

    반환 dict: {ok, vrp, side, regime, reason}
      ok  = True  → 공포 과잉(VRP > band) … 가설이 '진입 허용'으로 보는 쪽
      ok  = False → 실현변동성 폭발(VRP ≤ band) … 가설이 '보류'로 보는 쪽
    mode: "variance"(IV²−RV², 기본) | "volatility"(IV−RV)
    """
    if iv_pct is None or rv_pct is None:
        return {"ok": False, "vrp": None, "side": "unknown", "regime": "unknown", "reason": "IV·RV 결측"}
    v = float(vrp_variance(iv_pct, rv_pct) if mode == "variance" else vrp_volatility(iv_pct, rv_pct))
    if math.isnan(v):
        return {"ok": False, "vrp": None, "side": "unknown", "regime": "unknown", "reason": "계산 불가(NaN)"}
    reg = regime(v, band)
    ok = reg == "fear_excess"
    side = "공포 과잉(내재 > 실현)" if ok else "실현변동성 폭발(내재 ≤ 실현)"
    unit = "분산" if mode == "variance" else "vol %p"
    return {"ok": ok, "vrp": round(v, 6), "side": side, "regime": reg,
            "reason": f"VRP {unit} {v:+.4f} — {side}", "mode": mode}


# ── 사건 정의·집계 (백테스트 공용) ──────────────────────────────────
def drawdown(closes, window: int = 20) -> np.ndarray:
    """20일 고점 대비 낙폭(≤0). 0 이면 신고가."""
    px = np.asarray(closes, dtype=float)
    n = px.size
    out = np.full(n, np.nan)
    for i in range(window - 1, n):
        hi = np.nanmax(px[i - window + 1:i + 1])
        if hi > 0:
            out[i] = px[i] / hi - 1.0
    return out


def daily_return(closes) -> np.ndarray:
    px = np.asarray(closes, dtype=float)
    out = np.full(px.size, np.nan)
    out[1:] = px[1:] / px[:-1] - 1.0
    return out


def p_one_sided(t: float, sign: int = 1) -> float:
    """단측 정규 근사 p (repo 관행: scripts/study_us_r20_reversal.p_one 과 동일)."""
    return 0.5 * math.erfc(t * sign / math.sqrt(2))


def welch(a, b) -> dict:
    """두 표본 평균차 Welch t (a−b). 반환 {n_a, n_b, mean_a, mean_b, diff, t, p_one}."""
    a = np.asarray([x for x in np.asarray(a, dtype=float) if not math.isnan(x)])
    b = np.asarray([x for x in np.asarray(b, dtype=float) if not math.isnan(x)])
    na, nb = a.size, b.size
    if na < 3 or nb < 3:
        return {"n_a": na, "n_b": nb, "mean_a": float(np.mean(a)) if na else None,
                "mean_b": float(np.mean(b)) if nb else None, "diff": None, "t": None, "p_one": None}
    va, vb = a.var(ddof=1) / na, b.var(ddof=1) / nb
    se = math.sqrt(va + vb)
    diff = float(a.mean() - b.mean())
    t = diff / se if se > 0 else 0.0
    return {"n_a": na, "n_b": nb, "mean_a": float(a.mean()), "mean_b": float(b.mean()),
            "diff": diff, "t": t, "p_one": p_one_sided(t, +1)}


def group_stats(r) -> dict:
    """수익 배열 요약 — n·평균·승률·손익비(평균이익/평균손실)·오탐률(음수 비율)."""
    r = np.asarray([x for x in np.asarray(r, dtype=float) if not math.isnan(x)])
    if r.size == 0:
        return {"n": 0}
    win = r[r > 0]
    loss = r[r < 0]
    payoff = float(win.mean() / abs(loss.mean())) if win.size and loss.size and abs(loss.mean()) > 0 else None
    return {"n": int(r.size), "mean": float(r.mean()), "median": float(np.median(r)),
            "win": float((r > 0).mean()), "false_rate": float((r < 0).mean()), "payoff": payoff}


def event_mask(closes, *, drop: float | None = -0.02, dd_max: float | None = -0.05,
               rebound_day: bool = True, window: int = 20) -> np.ndarray:
    """반등 구간 사건 표시.

    drop      : 당일 수익률 상한(예: −0.02 = 그날 −2% 이상 급락). None 이면 조건 없음
    dd_max    : 20일 고점 대비 낙폭 상한(예: −0.05 = 고점 대비 5% 이상 조정). None 이면 조건 없음
    rebound_day: True 면 당일 상승(수익률 > 0) 도 요구 — '급락 뒤 첫 상승일'(반등 신호일)
    """
    px = np.asarray(closes, dtype=float)
    r = daily_return(px)
    m = np.ones(px.size, dtype=bool)
    if drop is not None:
        m &= r <= drop
    if dd_max is not None:
        m &= drawdown(px, window) <= dd_max
    if rebound_day:
        m &= r > 0
    m &= ~np.isnan(r)
    return m


def forward_return(closes, horizon: int = 5) -> np.ndarray:
    """t 종가 → t+horizon 종가 수익률(끝 horizon 칸 NaN)."""
    px = np.asarray(closes, dtype=float)
    out = np.full(px.size, np.nan)
    if px.size > horizon:
        out[:-horizon] = px[horizon:] / px[:-horizon] - 1.0
    return out
