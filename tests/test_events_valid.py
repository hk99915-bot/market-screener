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
