"""지정학 뉴스 자동 트래킹(screener/geo_news.py) — 데이터 10/23. 네트워크 없음(가짜 RSS 텍스트)."""
import json
from datetime import datetime, timezone

from screener import geo_news as gn

NOW = datetime(2026, 10, 23, 13, 0, tzinfo=timezone.utc)

RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
<item><title><![CDATA[Iran says 7 oil tankers damaged in Strait of Hormuz - Reuters]]></title><link>https://n.example/a</link>
<pubDate>Fri, 23 Oct 2026 10:05:00 GMT</pubDate><source url="https://reuters.com">Reuters</source></item>
<item><title>Iran says 7 oil tankers damaged in Strait of Hormuz</title><link>https://bbc.example/a</link>
<pubDate>Fri, 23 Oct 2026 09:00:00 GMT</pubDate></item>
<item><title>Houthi strikes threaten Red Sea shipping &amp; Suez traffic</title><link>https://x.example/b</link>
<pubDate>Thu, 22 Oct 2026 08:00:00 +0900</pubDate></item>
<item><title>Old story: North Korea fires missile</title><link>https://x.example/c</link>
<pubDate>Mon, 05 Oct 2026 08:00:00 GMT</pubDate></item>
<item><title>Local bakery wins prize</title><link>https://x.example/d</link><pubDate>Fri, 23 Oct 2026 08:00:00 GMT</pubDate></item>
</channel></rss>"""

ATOM = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><title>t</title>
<entry><title>China tightens rare earth export controls</title><link href="https://y.example/e"/><updated>2026-10-22T03:00:00Z</updated></entry>
</feed>"""


def test_parse_rss_strips_source_suffix_and_parses_dates():
    rows = gn.parse_feed(RSS, "BBC World")
    assert rows[0]["title"] == "Iran says 7 oil tankers damaged in Strait of Hormuz" and rows[0]["src"] == "Reuters"
    assert rows[1]["src"] == "BBC World"   # <source> 없으면 피드 이름
    assert rows[2]["title"] == "Houthi strikes threaten Red Sea shipping & Suez traffic"
    assert rows[2]["when"] == datetime(2026, 10, 21, 23, 0, tzinfo=timezone.utc)   # +0900 → UTC


def test_parse_atom_and_broken_xml_fallback():
    a = gn.parse_feed(ATOM, "Feed")
    assert a[0]["title"].startswith("China tightens") and a[0]["link"] == "https://y.example/e"
    broken = "<rss><channel><item><title>Taiwan Strait drills by PLA &nbsp; expand</title><pubDate>Fri, 23 Oct 2026 01:00:00 GMT</pubDate></item></channel>"
    b = gn.parse_feed(broken, "X")
    assert b and "Taiwan Strait" in b[0]["title"]


def test_match_axes_keywords():
    assert gn.match_axes("Iran says tankers damaged in Strait of Hormuz") == ["hormuz"]
    assert "chips" in gn.match_axes("Nvidia CEO says US export curbs accelerate China chip push")
    assert gn.match_axes("Trump, tariffs and health care: Takeaways") == []   # 관세 단독(국내 정치)은 제외
    assert gn.match_axes("US raises tariffs on Korean steel") == ["tariff"]
    assert gn.match_axes("Local bakery wins prize") == []


def test_assign_dedups_windows_and_caps():
    rows = gn.parse_feed(RSS, "BBC World") + gn.parse_feed(ATOM, "Feed")
    res = gn.assign(rows, ["hormuz", "redsea", "korea", "rare_earth"], NOW)
    assert len(res["hormuz"]) == 1 and res["hormuz"][0]["src"] == "Reuters"   # 같은 제목 두 번 → 먼저 온 것 하나
    assert len(res["redsea"]) == 1 and len(res["rare_earth"]) == 1
    assert res["korea"] == []   # 7일 지난 기사 제외
    many = [{"title": f"Hormuz tanker update {i}", "src": "A" if i < 4 else f"S{i}", "when": NOW, "link": ""} for i in range(9)]
    capped = gn.assign(many, ["hormuz"], NOW)["hormuz"]
    assert len(capped) == gn.PER_AXIS and sum(r["src"] == "A" for r in capped) == gn.PER_SRC


def test_build_writes_axes_and_feed_status(tmp_path, monkeypatch):
    monkeypatch.setattr(gn, "OUT", tmp_path / "geo_news.json")

    def fake(url):
        if "bbci" in url:
            raise RuntimeError("down")
        return RSS
    out = gn.build(fetch=fake, now=NOW)
    ids = [a["id"] for a in out["axes"]]
    assert {"hormuz", "redsea", "ruukr", "rare_earth", "chips", "taiwan", "korea", "tariff"} <= set(ids)
    h = next(a for a in out["axes"] if a["id"] == "hormuz")["items"]
    assert h and set(h[0]) == {"title", "src", "time", "link"} and h[0]["time"] == "2026-10-23 19:05"   # KST
    assert any(not f["ok"] for f in out["feeds"]) and any(f["ok"] for f in out["feeds"])
    assert "해석 아님" in out["label"]
    saved = json.loads((tmp_path / "geo_news.json").read_text(encoding="utf-8"))
    assert saved["axes"][0]["id"] == out["axes"][0]["id"]


def test_build_all_feeds_fail_keeps_previous(tmp_path, monkeypatch):
    monkeypatch.setattr(gn, "OUT", tmp_path / "geo_news.json")
    calls = []
    monkeypatch.setattr("screener.guard.record_stale", lambda *a: calls.append(a))

    def boom(url):
        raise RuntimeError("offline")
    assert gn.build(fetch=boom, now=NOW) is None
    assert not (tmp_path / "geo_news.json").exists() and calls
