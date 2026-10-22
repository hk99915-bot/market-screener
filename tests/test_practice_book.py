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
