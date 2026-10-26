"""장중 이벤트 감시 (screener/event_watch.py) — 가짜 시세로: 각 이벤트 1회 · 오래된 시세 무시 · 소리/무음 표 · 전송 간격 (네트워크·실보유 없음)."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from screener import alerts, event_watch as ew, pb

KST = ZoneInfo("Asia/Seoul")
NY = ZoneInfo("America/New_York")
NOW = datetime(2026, 10, 20, 10, 0, 0, tzinfo=KST)   # 화요일 10:00


def q(last, chg, *, at=NOW, low=None, stop="TRADING", name=None):
    return {"last": last, "chg": chg, "low": low, "ts": at.isoformat(), "stop": stop, "name": name}


@pytest.fixture
def st(tmp_path, monkeypatch):
    monkeypatch.setenv("EVENT_STATE", str(tmp_path / "ev.json"))
    monkeypatch.setenv("MY_RULES", "000000 1000000 touch\n005930 200000\nMU 90")
    monkeypatch.setattr(ew, "_news_halt_today", lambda day: set())
    return ew.load_state()


def calm(at=NOW):
    return {"KOSPI": q(5500, -0.01, at=at), "KOSDAQ": q(900, -0.01, at=at), "FUT": q(800, -0.01, at=at)}


def sender():
    sent = []
    return sent, (lambda text, *, disable_notification=True: sent.append((text, disable_notification)))


def rules():
    import os
    return pb.rules(os.environ["MY_RULES"])


def test_touch_fires_once_ever_and_rings(st):
    stocks = {"000000": q(1_010_000, -0.03, low=990_000, name="TEST01")}
    evs = ew.kr_events(NOW, calm(), stocks, rules(), {}, st)
    assert [e["key"] for e in evs] == ["touch:000000"]
    out, send = sender()
    res = ew.dispatch(evs, st, NOW, send)
    assert res["ring"] is True and out[0][1] is False and "발동선 터치" in out[0][0]
    later = NOW + timedelta(days=3)                       # 다른 날에도 다시 안 울림 (평생 1회)
    stocks = {"000000": q(950_000, -0.05, at=later, low=940_000)}
    evs = ew.kr_events(later, calm(later), stocks, rules(), {}, st)
    assert not [e for e in evs if e["key"].startswith("touch:")]


def test_touch_skipped_if_rules_alert_already_sent(st):
    stocks = {"000000": q(990_000, -0.05)}
    evs = ew.kr_events(NOW, calm(), stocks, rules(), {}, st, {"2026-10-19:touch:000000": "x"})
    assert not [e for e in evs if e["key"].startswith("touch:")]


def test_stale_quotes_do_not_fire(st):
    old = NOW - timedelta(minutes=10)
    idx = {"KOSPI": q(5000, -0.09, at=old), "KOSDAQ": q(800, -0.06, at=old), "FUT": q(700, -0.07, at=old)}
    stocks = {"000000": q(900_000, -0.10, at=old), "005930": q(150_000, -0.10, at=old)}
    assert ew.kr_events(NOW, idx, stocks, rules(), {"005930": "x"}, st) == []
    no_ts = {"KOSPI": {"last": 5000, "chg": -0.09, "ts": None}}
    assert ew.kr_events(NOW, no_ts, {}, rules(), {}, st) == []
    assert not ew.fresh(q(1, 0, at=NOW + timedelta(minutes=5)), NOW, 180)   # 미래 시각도 거부


def test_crash_levels_once_per_day_and_silent(st):
    idx = calm(); idx["KOSPI"] = q(5280, -0.042)
    evs = ew.kr_events(NOW, idx, {}, rules(), {}, st)
    assert [e["key"] for e in evs] == ["kospi-4:2026-10-20"]
    out, send = sender()
    assert ew.dispatch(evs, st, NOW, send)["ring"] is False and out[0][1] is True
    t2 = NOW + timedelta(minutes=2)
    idx = calm(t2); idx["KOSPI"] = q(5270, -0.043, at=t2)
    assert ew.dispatch(ew.kr_events(t2, idx, {}, rules(), {}, st), st, t2, send)["sent"] == []   # 같은 날 −4% 재전송 없음
    idx["KOSPI"] = q(5200, -0.052, at=t2)
    evs = ew.kr_events(t2, idx, {}, rules(), {}, st)
    assert [e["key"] for e in evs] == ["kospi-5:2026-10-20"]
    assert ew.dispatch(evs, st, t2, send)["ring"] is False


def test_jump_straight_to_minus5_marks_minus4(st):
    idx = calm(); idx["KOSDAQ"] = q(850, -0.06)
    out, send = sender()
    ew.dispatch(ew.kr_events(NOW, idx, {}, rules(), {}, st), st, NOW, send)
    assert "kosdaq-4:2026-10-20" in st["sent"] and len(out) == 1


def test_halt_needs_one_minute_then_rings_once(st):
    idx = calm(); idx["KOSPI"] = q(5050, -0.085)
    evs = ew.kr_events(NOW, idx, {}, rules(), {}, st)
    assert not [e for e in evs if e["key"].startswith("halt:")]          # 첫 표본: 대기
    t2 = NOW + timedelta(seconds=65)
    idx = calm(t2); idx["KOSPI"] = q(5040, -0.087, at=t2)
    evs = ew.kr_events(t2, idx, {}, rules(), {}, st)
    halts = [e for e in evs if e["key"].startswith("halt:")]
    assert [e["key"] for e in halts] == ["halt:KOSPI:cb1:2026-10-20"]
    out, send = sender()
    assert ew.dispatch(evs, st, t2, send)["ring"] is True and out[0][1] is False
    assert ew.halted_today("KOSPI", "2026-10-20", st)
    t3 = t2 + timedelta(seconds=65)
    idx = calm(t3); idx["KOSPI"] = q(5030, -0.088, at=t3)
    assert not [e for e in ew.kr_events(t3, idx, {}, rules(), {}, st) if e["key"].startswith("halt:")]


def test_halt_resets_if_condition_breaks(st):
    idx = calm(); idx["FUT"] = q(760, -0.052)
    ew.kr_events(NOW, idx, {}, rules(), {}, st)
    t2 = NOW + timedelta(seconds=60)
    ew.kr_events(t2, calm(t2), {}, rules(), {}, st)                      # 회복 → 대기 해제
    t3 = t2 + timedelta(seconds=60)
    idx = calm(t3); idx["FUT"] = q(758, -0.053, at=t3)
    assert not [e for e in ew.kr_events(t3, idx, {}, rules(), {}, st) if e["key"].startswith("halt:")]


def test_no_cb1_after_1450(st):
    late = datetime(2026, 10, 20, 14, 55, tzinfo=KST)
    for t in (late, late + timedelta(seconds=70)):
        idx = calm(t); idx["KOSPI"] = q(5000, -0.09, at=t)
        evs = ew.kr_events(t, idx, {}, rules(), {}, st)
    assert not [e for e in evs if e["key"].startswith("halt:")]


def test_news_first_means_no_second_ring(st, monkeypatch):
    monkeypatch.setattr(ew, "_news_halt_today", lambda day: {"KOSPI"})
    for t in (NOW, NOW + timedelta(seconds=70)):
        idx = calm(t); idx["KOSPI"] = q(5000, -0.09, at=t)
        evs = ew.kr_events(t, idx, {}, rules(), {}, st)
    assert not [e for e in evs if e["key"].startswith("halt:")]


def test_holdings_stop_and_drop_silent_hashed(st):
    stocks = {"005930": q(198_000, -0.06, name="삼성전자")}
    evs = ew.kr_events(NOW, calm(), stocks, rules(), {"005930": "삼성전자"}, st)
    kinds = sorted(alerts.kind(e["key"]) for e in evs)
    assert kinds == ["hold5", "stopx"]
    assert all("005930" not in e["key"] for e in evs)                   # 공개 상태 파일엔 코드 해시만
    out, send = sender()
    assert ew.dispatch(evs, st, NOW, send)["ring"] is False and out[0][1] is True
    assert ew.kr_events(NOW, calm(), stocks, rules(), {"005930": "x"}, st) and \
        ew.dispatch(ew.kr_events(NOW, calm(), stocks, rules(), {"005930": "x"}, st), st, NOW + timedelta(minutes=2), send)["sent"] == []


def test_us_events_silent(st):
    t = datetime(2026, 10, 20, 11, 0, tzinfo=NY)
    quotes = {"^GSPC": q(6000, -0.031, at=t), "^NDX": q(20000, -0.02, at=t), "^VIX": q(25, 0.30, at=t),
              "MU": q(95, -0.04, at=t, low=89)}
    evs = ew.us_events(t, quotes, rules())
    assert sorted(alerts.kind(e["key"]) for e in evs) == ["spx-3", "usstop", "vix+25"]
    assert not alerts.ring([e["key"] for e in evs])
    stale = {k: {**v, "ts": (t - timedelta(minutes=20)).isoformat()} for k, v in quotes.items()}
    assert ew.us_events(t, stale, rules()) == []


def test_rate_limit_batches_and_defers(st):
    out, send = sender()
    ew.dispatch([ew._ev("kospi-4:2026-10-20", "a")], st, NOW, send)
    t2 = NOW + timedelta(seconds=30)
    res = ew.dispatch([ew._ev("kosdaq-4:2026-10-20", "b"), ew._ev("touch:000000", "c")], st, t2, send)
    assert res["sent"] == [] and len(out) == 1 and len(res["queued"]) == 2
    t3 = NOW + timedelta(seconds=61)
    res = ew.dispatch([], st, t3, send)
    assert len(out) == 2 and set(res["sent"]) == {"kosdaq-4:2026-10-20", "touch:000000"} and res["ring"] is True
    assert "b" in out[1][0] and "c" in out[1][0]


def test_ring_mapping_uses_table_only():
    assert set(alerts.RING_KINDS) == {"stop2", "dl0", "touch", "halt", "fresh"}
    for k in ("kospi-4:2026-10-20", "kosdaq-5:2026-10-20", "hold5:ab:2026-10-20", "stopx:ab:2026-10-20",
              "spx-3:2026-10-20", "ndx-3:2026-10-20", "vix+25:2026-10-20", "usstop:ab:2026-10-20"):
        assert alerts.silent([k]), k
    assert alerts.ring(["halt:KOSPI:cb1:2026-10-20"]) and alerts.ring(["touch:000000"])


def test_state_roundtrip_keeps_touch(st):
    st["sent"] = {"touch:000000": "2026-01-01 10:00", **{f"kospi-4:2026-01-{i:02d}": f"2026-01-{i:02d}" for i in range(1, 29)}}
    ew.save_state(st)
    again = ew.load_state()
    assert "touch:000000" in again["sent"] and again["queue"] == []


def test_run_outside_session_is_noop(st):
    sat = datetime(2026, 10, 17, 12, 0, tzinfo=KST)
    assert ew.run(now=sat, send=lambda *a, **k: pytest.fail("보내면 안 됨")) == {"skipped": True}


# ── 10/26 maint req-dev-d1b2e934: FUT 는 '20분 지연' 시세 — 지연만큼 신선도 허용 ──
def test_parse_naver_keeps_delay_and_fut_delayed_quote_is_fresh():
    j = {"closePrice": "850.00", "fluctuationsRatio": "-1.54", "compareToPreviousPrice": {"code": "5"},
         "localTradedAt": (NOW - timedelta(minutes=20)).isoformat(), "delayTime": 20, "stockName": "코스피 200 선물"}
    fq = ew.parse_naver(j)
    assert fq["delay"] == 1200
    assert ew.fresh(fq, NOW, ew.FRESH_KR_SEC)                          # 20분 지연 + 여유 3분 안
    old = dict(fq, ts=(NOW - timedelta(minutes=30)).isoformat())
    assert not ew.fresh(old, NOW, ew.FRESH_KR_SEC)                     # 지연보다 더 오래되면 여전히 보류
    spot = dict(fq, delay=0)
    assert not ew.fresh(spot, NOW, ew.FRESH_KR_SEC)                    # 실시간 시세는 기존대로 180초
    assert "20분 지연" in ew._dly(fq) and ew._dly(spot) == ""
