"""HF 스프레드 엔진 — 손실이 막힌 옵션 수직 스프레드(국장 코스피200·개별주식옵션, 미장 SPX·개별주) (겸이 10/23 "스프레드 엔진 만들고 국장·미장 개별종목 옵션 다").

scripts/hf_book.py 의 kind = "spread"(국장) · "us_spread"(미장) 가 쓰는 순수 함수 모음.
  - 한 다리 매수(k_long) + 한 다리 매도(k_short), 같은 권리·만기. 데빗(돈 내고 삼)·크레딧(돈 받고 팜) 둘 다 —
    최대손실이 행사가 폭으로 막혀 있어 '무방비 매도 금지'(2차 연구 V1 F)와 충돌하지 않는다.
  - 가격 = 블랙숄즈 근사. 지수 IV = VKOSPI(rep_iv)·VIX, 개별주 IV = 20일 실현변동성 × 1.1(호가 체인 없을 때의 근사 — req-data-eee6de46 들어오면 실제 호가로 교체).
  - R 단위 = 1단위(기초 1주·1pt)당 최대손실. 손익(R) = (현재 가치 − 진입 가치) ÷ 최대손실 − 비용(두 다리 프리미엄 × 2%).
  - 익절 = 최대이익의 50%(현업 관행) · 만기 = 내재가치 정산 · 손절 없음(최대손실 = 1R 로 이미 막힘).
검증전 — 옵션 호가 이력이 없어 스프레드 소스 검증 불가. 가상·모의, 실계좌 주문 아님.
"""
from __future__ import annotations

import math
from datetime import date

LEG_COST = 0.02          # 다리당 프리미엄 대비 왕복 호가 비용(단일 옵션 COST 와 같은 가정)
TAKE = 0.5               # 최대이익의 50% 에서 익절
STOCK_IV_MULT = 1.1      # 개별주 IV ≈ 20일 실현변동성 × 1.1 (체인 없을 때 근사)
MULT_KR_STOCK = 10       # 국장 개별주식옵션 승수(주)
MULT_US = 100            # 미장 옵션 승수(주·지수 $100)


def payoff_range(right: str, k_long: float, k_short: float) -> tuple[float, float]:
    """만기 손익(1단위) 범위 [lo, hi]. 풋: max(Kl−S,0) − max(Ks−S,0) / 콜: max(S−Kl,0) − max(S−Ks,0)."""
    w = (k_long - k_short) if right == "put" else (k_short - k_long)
    return (min(0.0, w), max(0.0, w))


def value(bs, right: str, s: float, k_long: float, k_short: float, t: float, iv: float) -> float:
    """스프레드 1단위 가치(롱 다리 − 숏 다리). t ≤ 0 이면 내재가치."""
    return bs(right, s, k_long, t, iv) - bs(right, s, k_short, t, iv)


def legs_premium(bs, right, s, k_long, k_short, t, iv) -> float:
    return bs(right, s, k_long, t, iv) + bs(right, s, k_short, t, iv)


def years(expiry: str, asof: str) -> float:
    return max((date.fromisoformat(expiry) - date.fromisoformat(asof)).days, 0) / 365


def plan(bs, right: str, s: float, k_long: float, k_short: float, t: float, iv: float) -> dict:
    """진입 가치·최대손실·최대이익·익절 가치·비용(1단위)."""
    if right not in ("put", "call") or k_long == k_short:
        raise SystemExit("스프레드 = 같은 권리(put/call)·다른 행사가 두 다리")
    if t <= 0:
        raise SystemExit("만기가 지났거나 오늘 — 스프레드 안 받아")
    v0 = value(bs, right, s, k_long, k_short, t, iv)
    lo, hi = payoff_range(right, k_long, k_short)
    max_loss, max_gain = v0 - lo, hi - v0
    if max_loss <= 0 or max_gain <= 0:
        raise SystemExit(f"가치 {v0:.2f} 가 만기 범위 [{lo:g}, {hi:g}] 밖 — 공짜 점심 없음(가격 근사 오류)")
    kind = "데빗" if v0 > 0 else "크레딧"
    return {"v0": v0, "max_loss": max_loss, "max_gain": max_gain, "t1": v0 + TAKE * max_gain, "type": kind,
            "cost_unit": LEG_COST * legs_premium(bs, right, s, k_long, k_short, t, iv), "rr_take": TAKE * max_gain / max_loss}


def delta(bs_delta, right, s, k_long, k_short, t, iv) -> float:
    if t <= 0:
        return 0.0
    return bs_delta(right, s, k_long, t, iv) - bs_delta(right, s, k_short, t, iv)


def stock_iv(daily_vol: float | None) -> float | None:
    return daily_vol * math.sqrt(252) * STOCK_IV_MULT if daily_vol else None
