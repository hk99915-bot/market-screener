"""비트코인 트래킹 1단계 — 기준일 분리(확정 UTC 봉 vs 진행 중 봉)·ATR·추세·±5% 알림 판정."""
from datetime import datetime, timezone

from screener import btc


def _rows(n=210, start=100.0, step=1.0, last_day="2026-10-22"):
    from datetime import date, timedelta
    d0 = date.fromisoformat(last_day) - timedelta(days=n - 1)
    out = []
    for i in range(n):
        c = start + step * i
        out.append([(d0 + timedelta(days=i)).isoformat(), c - 0.5, c + 2, c - 2, c, 1e9])
    return out


def test_asof_split_live_bar_excluded_from_indicators():
    rows = _rows(last_day="2026-10-23")                      # 마지막 행 = 오늘(UTC) 진행 중 봉
    now = datetime(2026, 10, 23, 5, 0, tzinfo=timezone.utc)
    o = btc.build(rows, now)
    assert o["closed_asof"] == "2026-10-22" and o["live_date"] == "2026-10-23"
    assert o["close"] == rows[-2][4] and o["live_px"] == rows[-1][4]
    assert o["trend"] == "상승" and o["atr14"] == 4.0


def test_weekend_no_live_when_last_bar_is_past():
    o = btc.build(_rows(last_day="2026-10-22"), datetime(2026, 10, 24, 1, 0, tzinfo=timezone.utc))
    assert o["live_date"] is None and o["closed_asof"] == "2026-10-22" and o["chg_live_pct"] is None


def test_alert_threshold_on_live_move():
    rows = _rows(last_day="2026-10-23")
    prev = rows[-2][4]
    rows[-1][4] = prev * 0.94                                 # -6% 진행 중
    o = btc.build(rows, datetime(2026, 10, 23, 5, 0, tzinfo=timezone.utc))
    assert o["alert"] and o["chg_live_pct"] <= -5
    rows[-1][4] = prev * 1.04
    assert not btc.build(rows, datetime(2026, 10, 23, 5, 0, tzinfo=timezone.utc))["alert"]


def test_too_few_bars_says_no_data():
    o = btc.build([["2026-10-22", 1, 2, 0.5, 1.5, 1]], datetime(2026, 10, 23, tzinfo=timezone.utc))
    assert o["ok"] is False and "데이터 없음" in o["why"]
