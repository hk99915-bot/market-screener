"""야간선물 갭 · 시초 갭 괴리 가드 — 순수 계산·검증 모듈 (연구 전용, 매매 지시 아님).

무엇: 야간 세션(18:00~06:00)이 만든 방향과 본장 시초가가 만든 방향이 **어긋날 때**
      시초 추격 진입을 보류하는 조건식. 기존 실계좌 룰·알림은 건드리지 않는다(계산만).

입력 (`data/deriv/daily.csv`, 2025-09-01~ / 야간 세션은 2025-06 KRX 자체 야간시장 이후)
  night_vwap     : 당일 06:00 에 끝난 야간 세션 코스피200 선물 VWAP (trdDd=D 는 D−1 18:00~D 06:00)
  night_vol      : 같은 세션 거래량(계약)
  prev_fut_close : 전일 최근월 선물 종가 · fut_open : 당일 선물 시초가
  prev_close     : 전일 코스피 종가 · open : 당일 시초가

정의 (모두 비율)
  야간 갭      = night_vwap / prev_fut_close − 1     ← 야간 세션이 만든 방향
  시초 갭(선물) = fut_open / prev_fut_close − 1
  괴리         = 시초 갭 − 야간 갭
                 음수 = 시초가 야간 상승을 **반납**하고 열림 / 양수 = 시초가 야간 움직임을 **초과**
  갭 반납일     = 종가 < 전일 종가
  시초 추격 손익 = 종가 / 시초가 − 1   ← '시초에 사서 종가에 판' 결과(실제 추격 진입의 손익)

주의
- night_vwap 은 상품군 합계(10종목) 값이라 최근월 선물 종가와 완전히 같은 계약이 아니다(프록시).
- 선물·현물 베이시스가 하루 사이 ±0.5% 움직이면 갭 자체에 섞인다 → 부호·괴리 판정에만 쓴다.
- '본장 초반 수급·체결강도' 는 저장소에 분봉·초반 수급 이력이 없다(검증 불가). 아래 guard() 는
  그 입력을 선택 인자로 열어 두되, 없으면 갭·시초 갭 두 다리로만 판정한다(`early_flow=None`).
- 등급·판정은 연구 스크립트(`scripts/study_night_gap_guard.py`)가 매긴다. 여기는 계산기다.
"""
from __future__ import annotations

import math

import numpy as np

# 사전등록 기본 문턱 (스크립트가 인자로 바꿀 수 있다 — 바꾸면 새 가설 id)
MIN_NIGHT_GAP = 0.005      # 야간 갭 +0.5% 이상을 '야간 상승'으로 본다
DIV_BACK = -0.003          # 괴리 −0.3%p 이하 = 시초가 야간 상승을 반납
DIV_OVER = 0.015           # 괴리 +1.5%p 이상 = 시초가 야간 움직임을 초과(오버슈트)


def night_gap(night_vwap, prev_close):
    """야간 세션 갭(비율). 결측이면 nan."""
    try:
        a, b = float(night_vwap), float(prev_close)
    except (TypeError, ValueError):
        return float("nan")
    if not (a > 0 and b > 0) or math.isnan(a) or math.isnan(b):
        return float("nan")
    return a / b - 1.0


def open_gap(open_px, prev_close):
    """시초 갭(비율)."""
    return night_gap(open_px, prev_close)   # 같은 식 — 이름만 다르게 읽힌다


def divergence(open_gap_value: float, night_gap_value: float) -> float:
    """괴리 = 시초 갭 − 야간 갭. 음수면 시초가 야간 상승을 반납했다는 뜻."""
    if open_gap_value is None or night_gap_value is None:
        return float("nan")
    a, b = float(open_gap_value), float(night_gap_value)
    if math.isnan(a) or math.isnan(b):
        return float("nan")
    return a - b


def guard(night_gap_value: float, open_gap_value: float, *, min_night: float = MIN_NIGHT_GAP,
          div_back: float = DIV_BACK, div_over: float = DIV_OVER, early_flow: float | None = None) -> dict:
    """시초 추격 진입 가드 1건 판정.

    반환 dict: {hold, reason, kind, night_gap, open_gap, div}
      hold=True  → 시초 추격 진입 **보류**
      kind: "back"  = 야간 상승을 시초가 반납(괴리 ≤ div_back)
            "over"  = 야간 움직임을 시초가 초과(괴리 ≥ div_over)
            "flow"  = 본장 초반 수급이 갭과 반대 부호(early_flow 부호 사용)
            "none"  = 괴리 없음 → 진입 허용
    """
    d = divergence(open_gap_value, night_gap_value)
    base = {"hold": False, "reason": "괴리 없음 — 갭 방향과 시초가 일치", "kind": "none",
            "night_gap": None if night_gap_value is None else round(float(night_gap_value), 6),
            "open_gap": None if open_gap_value is None else round(float(open_gap_value), 6),
            "div": None if math.isnan(d) else round(d, 6)}
    if math.isnan(d):
        base["reason"] = "야간 갭 또는 시초 갭 결측 — 판정 불가"
        return base
    ng = float(night_gap_value)
    if ng >= min_night and d <= div_back:
        base.update(hold=True, kind="back",
                    reason=f"야간 {ng*100:+.2f}% 상승을 시초가 반납({d*100:+.2f}%p) — 추격 근거 약화")
    elif ng <= min_night and d >= div_over:
        base.update(hold=True, kind="over",
                    reason=f"야간 {ng*100:+.2f}% 대비 시초 {d*100:+.2f}%p 초과 갭업 — 시초 오버슈트")
    if early_flow is not None and ng > 0 and float(early_flow) < 0:
        base.update(hold=True, kind="flow",
                    reason=f"야간 {ng*100:+.2f}% 상승인데 본장 초반 수급 순매도 — 괴리")
    return base


# ── 집계 (백테스트 공용) ────────────────────────────────────────────
def give_back(close, prev_close) -> bool | None:
    """갭 반납일인가 — 종가 < 전일 종가."""
    try:
        return float(close) < float(prev_close)
    except (TypeError, ValueError):
        return None


def open_to_close(close, open_px) -> float:
    """시초 추격 손익(종가/시초가 − 1)."""
    try:
        a, b = float(close), float(open_px)
    except (TypeError, ValueError):
        return float("nan")
    if not (a > 0 and b > 0):
        return float("nan")
    return a / b - 1.0


def fisher_two_by_two(a: list, b: list) -> dict:
    """2×2 빈도표 Fisher 정확검정(양측). a·b 는 0/1 리스트. 반환 {odds, p, table}."""
    a1 = int(sum(1 for x in a if x))
    a0 = int(len(a) - a1)
    b1 = int(sum(1 for x in b if x))
    b0 = int(len(b) - b1)
    table = [[a1, a0], [b1, b0]]
    n1, n2 = a1 + a0, b1 + b0
    row1 = a1 + b1
    return {"odds": (a1 * b0 / (a0 * b1)) if a0 and b1 else None, "p": _fisher_p(a1, a0, b1, b0),
            "table": table, "rate_a": a1 / n1 if n1 else None, "rate_b": b1 / n2 if n2 else None,
            "n_a": n1, "n_b": n2, "row1": row1}


def _fisher_p(a1: int, a0: int, b1: int, b0: int) -> float:
    """2×2 Fisher 정확검정 양측 p (초기하분포, 표준 라이브러리만)."""
    n = a1 + a0 + b1 + b0
    if n == 0:
        return float("nan")
    row1, col1 = a1 + b1, a1 + a0

    def prob(x: int) -> float:
        return (math.comb(row1, x) * math.comb(n - row1, col1 - x)) / math.comb(n, col1)

    lo = max(0, col1 - (n - row1))
    hi = min(row1, col1)
    obs = prob(a1)
    return float(min(1.0, sum(prob(x) for x in range(lo, hi + 1) if prob(x) <= obs + 1e-12)))
