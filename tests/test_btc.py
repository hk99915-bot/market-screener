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


def test_committee_btc_line_splits_closed_and_live(tmp_path, monkeypatch):
    """운용회의 한 줄: 확정 UTC 일봉과 진행 중 봉을 날짜로 갈라 적고, 오래된 값·alert 는 처리(req-dev-54eba83d 5단계)."""
    import json
    from datetime import date
    from screener import committee
    base = {"ok": True, "closed_asof": "2026-10-22", "live_date": "2026-10-23", "close": 81312.0, "chg_1d_pct": -3.21,
            "live_px": 81619.0, "chg_live_pct": 0.38, "trend": "혼조", "atr14_pct": 2.54, "alert": False, "alert_pct": 5.0}
    (tmp_path / "btc.json").write_text(json.dumps(base), encoding="utf-8")
    monkeypatch.setattr(committee, "REPORT_DIR", tmp_path)
    monkeypatch.setattr(committee, "_kst_today", lambda: date(2026, 10, 23))
    s = committee._btc_line()
    assert "10-22 확정" in s and "진행 중 10-23" in s and "경보" not in s
    (tmp_path / "btc.json").write_text(json.dumps({**base, "alert": True}), encoding="utf-8")
    assert "±5% 변동 경보" in committee._btc_line()
    monkeypatch.setattr(committee, "_kst_today", lambda: date(2026, 11, 3))
    assert committee._btc_line() is None   # 5일 넘은 값은 쓰지 않음


def test_alert_sends_once_per_bar_and_direction(tmp_path):
    """req-dev-54eba83d ④: ±5% 무음 알림 — 같은 UTC 봉·같은 방향은 1회, 문구에 금액·보유 없음."""
    rows = _rows(last_day="2026-10-23")
    rows[-1][4] = rows[-2][4] * 0.94
    o = btc.build(rows, datetime(2026, 10, 23, 5, 0, tzinfo=timezone.utc))
    sent = []
    st = tmp_path / "s.json"
    assert btc.maybe_alert(o, st, sent.append) is True
    assert btc.maybe_alert(o, st, sent.append) is False            # 같은 봉 재실행 → 안 보냄
    assert len(sent) == 1 and sent[0].startswith("₿ 비트코인 -6.0%") and "무음" in sent[0] and "매매 신호 아님" in sent[0]
    rows[-1][4] = rows[-2][4] * 1.06                                # 같은 봉 반대 방향 → 1통 더
    assert btc.maybe_alert(btc.build(rows, datetime(2026, 10, 23, 6, 0, tzinfo=timezone.utc)), st, sent.append) is True
    rows[-1][4] = rows[-2][4] * 1.01
    assert btc.maybe_alert(btc.build(rows, datetime(2026, 10, 23, 7, 0, tzinfo=timezone.utc)), st, sent.append) is False
    assert len(sent) == 2
