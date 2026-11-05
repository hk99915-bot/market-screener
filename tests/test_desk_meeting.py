"""데스크 운용회의 결론 → 텔레그램 3줄형 변환 + 뷰 JSON 형식."""
import json

from screener import desk_meeting as dm


def test_view_json_shape():
    o = dm.load()
    assert {"date", "asof", "inflection", "lines", "asks", "path"} <= set(o)
    assert len(o["lines"]) == 3 and o["path"].endswith("ops_meeting_kr.md")


def test_telegram_three_line_form():
    o = dm.load()
    t = dm.telegram_text(o, today=o["date"]).split("\n")
    assert t[1].startswith("① What: ") and t[2].startswith("② So What: ") and t[3].startswith("③ Now What: ")
    assert t[4] == "원본: " + o["path"]
    assert all(len(x) <= dm.MAX for x in t)
    assert not t[0].startswith("지난 회의")


def test_stale_label_and_clip():
    o = {"date": "2026-11-01", "asof": "x", "inflection": "가" * 200, "lines": ["a"], "asks": [], "path": "p"}
    t = dm.telegram_text(o, today="2026-11-05").split("\n")
    assert t[0].startswith("지난 회의(2026-11-01)")
    assert all(len(x) <= dm.MAX for x in t)


def test_send_respects_alerts_off(monkeypatch):
    monkeypatch.setenv("ALERTS_OFF", "1")
    assert dm.main([]) == 0
