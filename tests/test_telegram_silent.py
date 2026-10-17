"""결재 #9 '⛔만 소리' — send_telegram 의 disable_notification 기본값·호출부 분류 (네트워크 없음: requests.post 를 가짜로 바꿔 payload 만 본다)."""
from datetime import date

import pytest

from screener import alerts, rebound, report


class _Resp:
    status_code = 200
    text = "ok"


@pytest.fixture
def posted(monkeypatch):
    """CFG 에 가짜 토큰·채팅ID 를 넣고 requests.post 가 받은 data 들을 모은다."""
    calls: list[dict] = []
    monkeypatch.setattr(report.CFG, "telegram_token", "123456789:" + "A" * 35)
    monkeypatch.setattr(report.CFG, "telegram_chat", "-100123")
    monkeypatch.setattr(report.requests, "post", lambda url, data, timeout: calls.append(data) or _Resp())
    return calls


def test_default_is_silent(posted):
    report.send_telegram("📐 점도표")
    assert posted and posted[0]["disable_notification"] == "true"
    assert posted[0]["text"].startswith("📐 점도표")


def test_explicit_loud(posted):
    report.send_telegram("⛔ 손절선", disable_notification=False)
    assert posted[0]["disable_notification"] == "false"


def test_long_text_keeps_flag_on_every_chunk(posted):
    report.send_telegram("\n".join("x" * 100 for _ in range(80)), disable_notification=False)
    assert len(posted) >= 2 and {c["disable_notification"] for c in posted} == {"false"}


def test_loud_marks():
    assert report.loud("⛔ <b>손절선 2일 연속 이탈</b>")
    assert report.loud("⚡ <b>급락일 종가 매수 신호</b>")
    assert not report.loud("⚠️ 손절선 1일 이탈 — 내일 종가 확인")
    assert not report.loud("📏 규정 알림 · 기한 D-2")


def _capture(monkeypatch):
    sent: list[tuple[str, bool]] = []
    monkeypatch.setattr(report, "send_telegram", lambda text, *, disable_notification=True: sent.append((text, disable_notification)))
    return sent


def test_rules_alert_loud_only_with_stop_mark(monkeypatch):
    sent = _capture(monkeypatch)
    monkeypatch.setattr(alerts, "_state", lambda: {})
    monkeypatch.setattr(alerts, "_save", lambda st: None)
    monkeypatch.setattr(alerts, "build", lambda at_close, today: [("dl2", "📅 기한 D-2"), ("stop1", "⚠️ 손절선 1일 이탈")])
    alerts.run(send=True)
    assert sent[-1][1] is True                      # ⚠️·D-n 만 → 무음
    monkeypatch.setattr(alerts, "build", lambda at_close, today: [("stop2", "⛔ 손절선 2일 연속 이탈 — 즉시 집행")])
    alerts.run(send=True)
    assert sent[-1][1] is False                     # ⛔ 포함 → 소리


def test_crash_signal_is_loud(monkeypatch):
    sent = _capture(monkeypatch)
    monkeypatch.setattr(alerts, "_state", lambda: {})
    monkeypatch.setattr(alerts, "_save", lambda st: None)
    out = alerts.crash_check({"chg": -0.05, "last": 5000.0}, send=True, today=date(2026, 10, 17))
    assert out["fired"] and sent[-1][0].startswith("⚡") and sent[-1][1] is False


def test_rebound_1425_is_loud(monkeypatch, tmp_path):
    sent = _capture(monkeypatch)
    monkeypatch.setattr(rebound, "OUT", tmp_path / "rebound.json")
    monkeypatch.setattr(rebound, "judge", lambda q=None: {"date": "2026-10-17", "time": "14:25", "last": 5030.0, "prev": 5000.0,
                                                           "thr": 5025.0, "chg": 0.006, "ok": True})
    monkeypatch.setattr(alerts, "run", lambda send=True, at_close=True: [])
    rebound.run(send=True)
    assert sent and "반등일 ✅" in sent[0][0] and sent[0][1] is False
