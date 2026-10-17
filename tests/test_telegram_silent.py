"""결재 #9 (10/17 14:09 최종) 알림 등급 — 소리 5종(stop2·dl0·touch·halt·fresh 하루 1회)만, 나머지 무음.
원래: — send_telegram 의 disable_notification 기본값·호출부 분류 (네트워크 없음: requests.post 를 가짜로 바꿔 payload 만 본다)."""
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


def test_explicit_loud_is_overridden_when_all_silent(posted, monkeypatch):
    from screener import defs
    report.send_telegram("⛔ 손절선", disable_notification=False)
    assert posted[0]["disable_notification"] == ("true" if defs.TELEGRAM_ALL_SILENT else "false")


def test_explicit_loud_when_switch_off(posted, monkeypatch):
    from screener import defs
    monkeypatch.setattr(defs, "TELEGRAM_ALL_SILENT", False)
    report.send_telegram("⛔ 손절선", disable_notification=False)
    assert posted[0]["disable_notification"] == "false"


def test_long_text_keeps_flag_on_every_chunk(posted, monkeypatch):
    from screener import defs
    monkeypatch.setattr(defs, "TELEGRAM_ALL_SILENT", False)
    report.send_telegram("\n".join("x" * 100 for _ in range(80)), disable_notification=False)
    assert len(posted) >= 2 and {c["disable_notification"] for c in posted} == {"false"}


def test_ring_table_is_exactly_five():
    assert set(alerts.RING_KINDS) == {"stop2", "dl0", "touch", "halt", "fresh"}
    assert alerts.kind("2026-10-20:touch:000660") == "touch" and alerts.kind("stop2") == "stop2"
    assert alerts.ring(["dl1", "touch:000660"]) and not alerts.ring(["dl2", "dl1", "stop1", "band", "crash"])
    assert alerts.silent() is True
    assert not hasattr(report, "loud")      # 본문 이모지로 소리를 정하던 옛 방식 제거


def _capture(monkeypatch):
    sent: list[tuple[str, bool]] = []
    monkeypatch.setattr(report, "send_telegram", lambda text, *, disable_notification=True: sent.append((text, disable_notification)))
    return sent


def _run_rules(monkeypatch, items):
    sent = _capture(monkeypatch)
    monkeypatch.setattr(alerts, "_state", lambda: {})
    monkeypatch.setattr(alerts, "_save", lambda st: None)
    monkeypatch.setattr(alerts, "build", lambda at_close, today: items)
    alerts.run(send=True)
    return sent[-1][1]


@pytest.mark.parametrize("items,silent", [
    ([("dl2", "⏳ 기한 D-2"), ("stop1", "⚠️ 손절선 1일 이탈")], True),
    ([("dl1", "⏳ 기한 D-1")], True),
    ([("band", "📐 반도체 발동선 초과")], True),            # 밴드 초과는 무음 (#9 목록 밖)
    ([("stop2", "⛔ 손절선 2일 연속 이탈")], False),
    ([("dl0", "⏰ 규정 [12] 집행 기한 D-day")], False),      # D-day 는 ⛔ 표시가 없어도 소리
    ([("band", "📐"), ("touch:000660", "⛔ SK하이닉스 발동선 터치")], False),
])
def test_rules_alert_grading(monkeypatch, items, silent):
    assert _run_rules(monkeypatch, items) is silent


def test_deadline_dday_key():
    assert alerts.deadline_line(date(2026, 10, 22), "2026-10-22")[0] == "dl0"


def test_crash_signal_now_silent(monkeypatch):
    sent = _capture(monkeypatch)
    monkeypatch.setattr(alerts, "_state", lambda: {})
    monkeypatch.setattr(alerts, "_save", lambda st: None)
    out = alerts.crash_check({"chg": -0.05, "last": 5000.0}, send=True, today=date(2026, 10, 17))
    assert out["fired"] and sent[-1][0].startswith("⚡") and sent[-1][1] is True


def test_rebound_1425_now_silent(monkeypatch, tmp_path):
    sent = _capture(monkeypatch)
    monkeypatch.setattr(rebound, "OUT", tmp_path / "rebound.json")
    monkeypatch.setattr(rebound, "judge", lambda q=None: {"date": "2026-10-17", "time": "14:25", "last": 5030.0, "prev": 5000.0,
                                                           "thr": 5025.0, "chg": 0.006, "ok": True})
    monkeypatch.setattr(alerts, "run", lambda send=True, at_close=True: [])
    rebound.run(send=True)
    assert sent and "반등일 ✅" in sent[0][0] and sent[0][1] is True


def test_events_halt_rings_proximity_silent():
    from screener import events
    assert events.halt_keys([{"market": "KOSPI", "type": "사이드카", "title": "코스피 매도 사이드카 발동"}])
    assert events.halt_keys([{"market": "KOSPI", "type": "서킷브레이커 1단계"}])
    assert not events.halt_keys([{"market": "KOSPI", "type": "경보:서킷 1단계 기준(−8%) 도달"}])
    assert not events.halt_keys([{"market": "시장", "type": "거래 장애"}])
    assert alerts.silent(events.halt_keys([{"market": "KOSPI", "type": "경보:급락 −5% (사이드카 근처)"}]))


def test_pb_morning_and_duel_are_silent():
    import inspect
    from screener import duel, pb
    assert "disable_notification=True" in inspect.getsource(pb.send)
    assert "loud(" not in inspect.getsource(duel)
