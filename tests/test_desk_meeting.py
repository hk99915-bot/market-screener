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


def test_should_send_dedup_same_date():
    o = {"date": "2026-11-09"}
    assert dm.should_send(o, set(), today="2026-11-09", today_only=True)[0]
    ok, why = dm.should_send(o, {"2026-11-09"}, today="2026-11-09", today_only=True)
    assert not ok and "재발송 금지" in why
    assert dm.should_send(o, {"2026-11-09"}, force=True)[0]


def test_should_send_push_today_only():
    o = {"date": "2026-11-06"}
    assert not dm.should_send(o, set(), today="2026-11-09", today_only=True)[0]
    assert dm.should_send(o, set(), today="2026-11-09", today_only=False)[0]   # 수동 dispatch 는 지난 회의도 허용
    assert not dm.should_send({"date": ""}, set())[0]


def test_marker_skip_and_alerts_off_no_mark(monkeypatch, tmp_path):
    """같은 date 마커가 있으면 발송 단계까지 가지 않음 · ALERTS_OFF 로 생략된 날은 마커를 남기지 않음."""
    o = dm.load()
    m = tmp_path / "sent.txt"
    monkeypatch.setenv("ALERTS_OFF", "1")
    assert dm.main(["--marker", str(m)]) == 0
    assert not m.exists()
    m.write_text(o["date"] + "\n", encoding="utf-8")
    called = []
    monkeypatch.setattr("screener.report.send_telegram", lambda t: called.append(t))
    assert dm.main(["--marker", str(m)]) == 0 and called == []
    assert dm.sent_dates(m) == {o["date"]}


def test_marker_written_after_send(monkeypatch, tmp_path):
    o = dm.load()
    m = tmp_path / "s" / "sent.txt"
    monkeypatch.delenv("ALERTS_OFF", raising=False)
    called = []
    monkeypatch.setattr("screener.report.send_telegram", lambda t: called.append(t))
    assert dm.main(["--marker", str(m)]) == 0 and len(called) == 1
    assert dm.sent_dates(m) == {o["date"]}
    assert dm.main(["--marker", str(m)]) == 0 and len(called) == 1   # 두 번째 실행은 건너뜀


def test_workflow_push_trigger_on_view_json():
    from pathlib import Path
    import yaml
    wf = yaml.safe_load((Path(__file__).resolve().parents[1] / ".github/workflows/desk_meeting_tg.yml").read_text(encoding="utf-8"))
    on = wf.get("on") or wf.get(True)
    assert "reports/views/desk_meeting.json" in on["push"]["paths"]
    assert "workflow_dispatch" in on
    run = " ".join(s.get("run", "") for s in wf["jobs"]["send"]["steps"])
    assert "--marker" in run and "--today-only" in run
