"""겸이 연습 장부(scripts/practice_book.py) — 다음 시가 체결·손절·목표·성적표."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import practice_book as P  # noqa: E402

KST = timezone(timedelta(hours=9))
BARS = []


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    BARS.clear()
    BARS.append({"t": "2026-10-22", "o": 100, "h": 101, "l": 99, "c": 100})
    monkeypatch.setattr(P.H, "bars", lambda m, c: BARS)
    monkeypatch.setattr(P.H, "detail_name", lambda m, c: "테스트")
    monkeypatch.setattr(P.H, "live_kr_stock", lambda c: None)


def test_pending_fill_then_target():
    b = {"open": [], "closed": []}
    P.add(b, "X", 92, 112, "t", now=datetime(2026, 10, 22, 16, 30, tzinfo=KST))
    assert P.mark(b) == [] and b["open"][0]["status"] == "대기"
    BARS.append({"t": "2026-10-23", "o": 101, "h": 104, "l": 100, "c": 103})
    P.mark(b)
    assert b["open"][0]["entry"] == 101 and b["open"][0]["status"] == "보유"
    BARS.append({"t": "2026-10-24", "o": 105, "h": 114, "l": 104, "c": 113})
    out = P.mark(b)
    assert out and out[0]["exit_why"] == "목표" and out[0]["r"] > 1
    assert any("적중 1/1" in x for x in P.show(b))


def test_gap_stop():
    b = {"open": [], "closed": []}
    P.add(b, "X", 92, 112, "t", now=datetime(2026, 10, 22, 16, 30, tzinfo=KST))
    BARS.append({"t": "2026-10-23", "o": 100, "h": 101, "l": 99, "c": 100})
    P.mark(b)
    BARS.append({"t": "2026-10-24", "o": 88, "h": 90, "l": 87, "c": 89})
    out = P.mark(b)
    assert out[0]["exit_why"].startswith("손절(갭") and out[0]["exit"] == 88


def test_bad_levels():
    with pytest.raises(SystemExit):
        P.add({"open": [], "closed": []}, "X", 120, 110, "t")


def test_us_same_day_session_fills():
    b = {"open": [], "closed": []}
    P.add(b, "X", 92, 112, "t", market="US", now=datetime(2026, 10, 22, 16, 30, tzinfo=KST))
    P.mark(b)
    assert b["open"][0]["entry"] == 100 and b["open"][0]["entry_d"] == "2026-10-22"


def test_cost_deducted_from_r():
    p = {"entry": 100.0, "stop": 90.0, "market": "KR"}
    assert P._r(p, 110.0) == pytest.approx((10 - 0.45) / 10)
    assert P._r({**p, "market": "US"}, 90.0) == pytest.approx((-10 - 0.2) / 10)


def test_trend_trailing_stop_weekly():
    b = {"open": [], "closed": []}
    BARS.clear()
    d0 = datetime(2026, 10, 5)
    for i in range(30):                                                  # 6주, 매일 +1 상승
        t = (d0 + timedelta(days=i)).date()
        if t.weekday() >= 5:
            continue
        BARS.append({"t": t.isoformat(), "o": 100 + i, "h": 101 + i, "l": 99 + i, "c": 100 + i})
    with pytest.raises(SystemExit, match="trail"):
        P.add(b, "X", 90, None, "t", market="US", now=datetime(2026, 10, 4, 12, 0, tzinfo=KST))
    p = P.add(b, "X", 90, None, "t", market="US", now=datetime(2026, 10, 4, 12, 0, tzinfo=KST), trail=True)
    assert P.mark(b) == [] and p["stop"] > 90 and p["stop0"] == 90                 # 손절이 올라감, 1R 은 첫 손절 기준
    BARS.append({"t": "2026-11-09", "o": 120, "h": 120, "l": 100, "c": 101})       # 올린 손절 아래 마감
    out = P.mark(b)
    assert out and out[0]["exit_why"].startswith("추세 이탈") and out[0]["r"] > 0


def test_skip_logged_and_scored(monkeypatch):
    px = {"v": 100.0}
    monkeypatch.setattr(P.H, "stock_last", lambda c: ("2026-10-28", px["v"], "테스트"))
    b = {"open": [], "closed": []}
    P.skip(b, "055550", "안 산다 — 이틀 연속 시장보다 약함")
    px["v"] = 95.0
    assert b["skips"][0]["px"] == 100.0 and any("안 산다 테스트 100(" in x and "-5.0%" in x for x in P.show(b))
