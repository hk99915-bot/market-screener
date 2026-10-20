"""공공 리포트 트래커·Jiang 피드(screener/public_reports) + 리서치 종합 카드 — 합성 데이터, 네트워크 없음."""
from datetime import date

from screener import public_reports as pr
from screener import research_synthesis as rs

RSS = """<?xml version="1.0" encoding="UTF-8"?><rss><channel>
<item><title>Minutes of the Federal Open Market Committee, September 16-17, 2026</title><link>https://fed/m1</link>
<pubDate>Wed, 08 Oct 2026 18:00:00 GMT</pubDate><description>&lt;p&gt;The Federal Reserve released minutes&lt;/p&gt;</description></item>
<item><title>Federal Reserve Board announces enforcement action</title><link>https://fed/x</link><pubDate>Thu, 09 Oct 2026 18:00:00 GMT</pubDate></item>
</channel></rss>"""
ATOM = """<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom" xmlns:yt="http://www.youtube.com/xml/schemas/2015">
<entry><yt:videoId>abc</yt:videoId><title>Game Theory #12: Why Iran and Israel Go to War</title>
<link rel="alternate" href="https://www.youtube.com/watch?v=abc"/><published>2026-10-18T12:00:00+00:00</published></entry>
</feed>"""
HTML = """<ul><li><a href="/portal/view.do?id=1">2026년 9월 소비자동향조사 결과</a><span>2026.09.24</span></li>
<li><a href="/portal/view.do?id=2">금융안정보고서(2026년 6월)</a><span>2026-06-25</span></li><li><a href="/m">메뉴</a></li></ul>"""
BOK = next(s for s in pr.SOURCES if s["id"] == "bok_press")
FED = next(s for s in pr.SOURCES if s["id"] == "fed")


def test_parse_and_classify():
    rows = pr.classify(FED, pr.parse_feed(RSS))
    assert len(rows) == 1 and rows[0]["series"] == "FOMC 의사록" and rows[0]["date"] == date(2026, 10, 8)
    assert rows[0]["summary"] == "The Federal Reserve released minutes"
    h = pr.classify(BOK, pr.parse_html_list(HTML, "https://www.bok.or.kr/portal/list.do"))
    assert [r["series"] for r in h] == ["소비자동향조사(CSI)", "금융안정보고서"]
    assert h[0]["link"] == "https://www.bok.or.kr/portal/view.do?id=1" and h[1]["date"] == date(2026, 6, 25)


def test_fetch_manual_and_error():
    kofia = next(s for s in pr.SOURCES if s["id"] == "kofia")
    assert pr.fetch_source(kofia)[1]["status"] == "manual"

    def boom(u):
        raise OSError("blocked")
    rows, st = pr.fetch_source(FED, get=boom)
    assert rows == [] and st["status"] == "error" and "blocked" in st["reason"]
    rows, st = pr.fetch_source(FED, get=lambda u: RSS)
    assert st["status"] == "ok" and st["n"] == 2   # 피드 2개가 같은 응답 → 병합 단계에서 중복 제거


def test_merge_backfill_rule():
    t = date(2026, 10, 21)
    new = [{"title": "a", "date": date(2026, 10, 20), "series": "s"}, {"title": "b", "date": date(2026, 9, 1), "series": "s"}]
    items, added = pr.merge([], new, "fed", "Fed", "해외", "2026-10-21 03:30", t)
    assert added == 0 and all(i["collected_at"].startswith("backfill") for i in items)   # 첫 수집 = 전부 백필
    items, added = pr.merge(items, new + [{"title": "c", "date": date(2026, 10, 20), "series": "s"},
                                          {"title": "d", "date": date(2026, 9, 2), "series": "s"}], "fed", "Fed", "해외", "x", t)
    assert added == 1 and len(items) == 4 and items[-1]["collected_at"].startswith("backfill")   # 14일 지난 새 행 = 백필


def test_next_expected():
    ser = [("금융안정보고서", "", [6, 12]), ("국제수지", "", pr.M), ("이슈노트", "", None)]
    nx = {x["series"]: x["next"] for x in pr.next_expected(ser, {"국제수지": date(2026, 10, 8)}, date(2026, 10, 21))}
    assert nx == {"금융안정보고서": "2026-12", "국제수지": "2026-11"}


def test_jiang_feed_and_ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(pr, "JIANG", tmp_path / "jiang.json")
    monkeypatch.setattr(pr, "JIANG_PRED", tmp_path / "jiang_predictions.json")
    monkeypatch.setattr(pr, "VIEWS", tmp_path)
    page = '<meta itemprop="identifier"><script>{"externalId":"UC1234567890123456789012"}</script>'
    j = pr.run_jiang(get=lambda u: page if "@" in u else ATOM, now="n", today=date(2026, 10, 21))
    assert j["channel_id"] == "UC1234567890123456789012" and j["status"]["status"] == "ok"
    v = j["videos"][0]
    assert v["tags"] == ["중동", "전쟁", "게임이론"] and v["collected_at"].startswith("backfill")
    assert "참고 뷰" in j["grade"] and set(v) == {"date", "title", "link", "tags", "collected_at"}   # 전사·요약 없음
    assert pr.ensure_ledger() and not pr.ensure_ledger()
    import json
    led = json.loads((tmp_path / "jiang_predictions.json").read_text(encoding="utf-8"))
    assert led["predictions"] == [] and led["fields"]["verdict"].startswith("null")


def test_synthesis_cards():
    t = date(2026, 10, 21)
    pub = pr.build_output([{"key": "1", "src": "bok_press", "group": "한은", "inst": "한국은행", "series": "국제수지",
                            "title": "2026년 8월 국제수지(잠정)", "date": "2026-10-17", "link": "l", "collected_at": "x"}],
                          {"bok_press": {"status": "ok", "n": 1}}, t, "n")
    c = rs.public_card(pub, t)
    assert c["groups"][0]["n30"] == 1 and c["new7"][0]["series"] == "국제수지"
    assert any(x["series"] == "금융안정보고서" and x["next"] == "2026-12" for x in c["calendar"])
    assert c["sources"]["ok"] == 1 and c["sources"]["미실행"] == len(pr.SOURCES) - 1
    assert rs.public_card(None, t)["status"] == "없음" and rs.geo_card(None)["videos"] == []
