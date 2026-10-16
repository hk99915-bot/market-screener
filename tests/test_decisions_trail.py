"""decisions._score_pick — 'trail' 청산: 20일선 이탈은 20일선 위에서 진입(또는 회복)했을 때만 무장, 그 전엔 −8% 손절만."""
from datetime import date, timedelta

import pytest

from screener import decisions

ENTRY = "2026-09-01"


def _days(n, start=ENTRY, back=0):
    d = date.fromisoformat(start) - timedelta(days=back)
    out = []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(str(d))
        d += timedelta(days=1)
    return out


def _fake_bars(closes_before: list[float], entry_close: float, closes_after: list[float]):
    """진입일 이전 25거래일 + 진입일 + 이후 봉을 만들고, _bars(ticker, start) 를 start 이후만 돌려주는 가짜로 교체."""
    pre = _days(25, back=40)
    pre = [d for d in pre if d < ENTRY][-len(closes_before):]
    post = [d for d in _days(len(closes_after) + 1) if d > ENTRY][: len(closes_after)]
    bars = [{"d": d, "o": c, "c": c} for d, c in zip(pre, closes_before)]
    bars.append({"d": ENTRY, "o": entry_close, "c": entry_close})
    bars += [{"d": d, "o": c, "c": c} for d, c in zip(post, closes_after)]

    def fake(ticker, start):
        return [b for b in bars if b["d"] >= start]

    return fake


@pytest.fixture
def pick():
    return {"ticker": "069500", "notional": 1_000_000, "entry": "close", "exit": "trail"}


def test_armed_at_entry_exits_on_sma_break(monkeypatch, pick):
    monkeypatch.setattr(decisions, "_bars", _fake_bars([100.0] * 25, 100.0, [101.0, 95.0, 90.0]))
    r = decisions._score_pick(pick, ENTRY)
    assert r is not None and "20일선 이탈" in r["detail"]
    assert r["sell"] == 95.0
    assert r["ret"] == round(95 / 100 - 1 - 0.0005, 4)


def test_not_armed_below_sma_only_stoploss(monkeypatch, pick):
    # 20일선(≈110) 아래에서 진입 → 이탈 청산 비무장: 97·95 는 보유 유지, 91(−9%) 에서 손절
    monkeypatch.setattr(decisions, "_bars", _fake_bars([110.0] * 25, 100.0, [97.0, 95.0]))
    assert decisions._score_pick(pick, ENTRY) is None   # 아직 보유 중
    monkeypatch.setattr(decisions, "_bars", _fake_bars([110.0] * 25, 100.0, [97.0, 95.0, 91.0]))
    r = decisions._score_pick(pick, ENTRY)
    assert r is not None and "−8% 손절" in r["detail"] and r["sell"] == 91.0


def test_arms_after_recovery_then_exits(monkeypatch, pick):
    # 아래서 진입 → 20일선 회복(무장) → 다시 이탈 → 그날 종가 청산
    pre = [100.0] * 25
    after = [99.0, 101.0, 98.0]   # 101 ≥ SMA(≈100) 로 무장, 98 < SMA 로 이탈
    monkeypatch.setattr(decisions, "_bars", _fake_bars(pre, 99.0, after))
    r = decisions._score_pick(pick, ENTRY)
    assert r is not None and "20일선 이탈" in r["detail"] and r["sell"] == 98.0


def test_cash_pick_scores_zero(pick):
    assert decisions._score_pick({"cash": True}, ENTRY) == {"ret": 0.0, "pnl": 0.0, "detail": "현금 유지"}
