"""events._valid — 뉴스로 잡은 서킷·사이드카는 제목에 '발동'이 있어야 실제 이벤트 (통계·해설 기사 오탐 제거)."""
import json

from screener import events


def test_news_circuit_requires_trigger_word():
    assert events._valid({"source": "뉴스", "type": "서킷브레이커", "title": "코스피 서킷브레이커 발동…매매 20분 중단"})
    assert not events._valid({"source": "뉴스", "type": "서킷브레이커", "title": "올해만 10번 멈췄다…서킷브레이커 역사"})
    assert not events._valid({"source": "뉴스", "type": "사이드카", "title": "사이드카란 무엇인가"})


def test_official_and_other_types_pass_through():
    assert events._valid({"source": "KRX", "type": "서킷브레이커", "title": "해설"})
    assert events._valid({"source": "뉴스", "type": "거래 장애", "title": "증권사 HTS 먹통"})
    assert events._valid({})


def test_load_filters_and_counts_dropped(tmp_path, monkeypatch):
    p = tmp_path / "events.json"
    p.write_text(json.dumps({"events": [
        {"source": "뉴스", "type": "사이드카", "title": "코스닥 매도 사이드카 발동"},
        {"source": "뉴스", "type": "사이드카", "title": "사이드카 올해 몇 번?"},
    ]}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(events, "OUT", p)
    st = events.load()
    assert len(st["events"]) == 1 and st["_dropped"] == 1
    monkeypatch.setattr(events, "OUT", tmp_path / "missing.json")
    assert events.load() == {"events": []}


def test_check_stamps_seen_and_sent(tmp_path, monkeypatch):
    """계측(req-maint-a38820c6): 새 이벤트에 seen_at(잡은 시각)·sent_at(텔레그램 성공 시각)이 남아 지연을 잴 수 있다."""
    from screener import report
    p = tmp_path / "events.json"
    monkeypatch.setattr(events, "OUT", p)
    today = events.datetime.now(events.KST).strftime("%Y%m%d")
    monkeypatch.setattr(events, "_news", lambda: [{"title": "[속보]코스피, 매수사이드카 발동", "dt": today + "1053", "link": "x"}])
    monkeypatch.setattr(events, "_not_yet_rung", lambda keys, today: keys)
    sent = []
    monkeypatch.setattr(report, "send_telegram", lambda text, **k: sent.append(text))
    new = events.check({}, send=True)
    assert len(new) == 1 and sent
    e = json.loads(p.read_text(encoding="utf-8"))["events"][0]
    assert e["time"] == "10:53" and len(e["seen_at"]) == 8 and len(e["sent_at"]) == 8


def test_check_no_sent_at_when_telegram_fails(tmp_path, monkeypatch):
    from screener import report
    p = tmp_path / "events.json"
    monkeypatch.setattr(events, "OUT", p)
    today = events.datetime.now(events.KST).strftime("%Y%m%d")
    monkeypatch.setattr(events, "_news", lambda: [{"title": "코스닥 매도 사이드카 발동", "dt": today + "1300", "link": "x"}])
    monkeypatch.setattr(events, "_not_yet_rung", lambda keys, today: keys)

    def boom(text, **k):
        raise RuntimeError("x")
    monkeypatch.setattr(report, "send_telegram", boom)
    events.check({}, send=True)
    e = json.loads(p.read_text(encoding="utf-8"))["events"][0]
    assert "seen_at" in e and "sent_at" not in e


def test_main_does_not_shadow_report_dir():
    """main() 안에서 REPORT_DIR 를 다시 import 하면 지역 변수가 돼 quotes 분기 live.json events_checked_at 쓰기가 매번 실패 (10/21~10/23)."""
    from screener import main as m
    assert "REPORT_DIR" not in m.main.__code__.co_varnames
