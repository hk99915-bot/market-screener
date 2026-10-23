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
    words = "alpha bravo charlie delta echo foxtrot golf hotel india".split()   # 서로 다른 사건(G2 사건 중복 제거에 안 걸리게)
    many = [{"title": f"Hormuz {words[i]} {words[i]}xx tanker", "src": "A" if i < 4 else f"S{i}", "when": NOW, "link": ""} for i in range(9)]
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


# ── 10/24 피어 G1·G2·G3 (docs/peer_reviews/2026-10-24_commodities_geo.md) ──
def _r(title, src, link, via="검색", h=0):
    from datetime import timedelta
    return {"title": title, "src": src, "link": link, "when": NOW - timedelta(hours=h), "via": via}


def test_g2_same_event_one_slot_real_titles():
    """10/23 산출물에서 5칸 중 3칸을 한 사건이 차지한 축 3개(rare_earth·chips·ruukr) → 사건당 1칸."""
    rows = [
        _r("TSMC Seeks Equipment Alternatives to Cut China Rare Earth Reliance", "Seoul Economic Daily", "https://news.google.com/rss/articles/a1", h=1),
        _r("\"TSMC Seeks Alternative Parts to Reduce Dependence on Chinese Rare Earths\"", "news.sbs.co.kr", "https://news.google.com/rss/articles/a2", h=2),
        _r("China rare earth curbs push TSMC to seek alternatives", "IDNFinancials", "https://news.google.com/rss/articles/a3", h=3),
        _r("Myanmar Rare Earth Exports Surge Amid Illusion of Regime Control", "The Irrawaddy", "https://news.google.com/rss/articles/a4", h=4),
        _r("US export curbs accelerate China's chip ambitions, says Nvidia CEO", "ET", "https://news.google.com/rss/articles/b1", h=1),
        _r("Jensen Huang says US export curbs accelerate China chip progress", "NewsBytes", "https://news.google.com/rss/articles/b2", h=2),
        _r("Nvidia CEO Jensen Huang says US export curbs have accelerated China's chip ambitions: CNBC", "CNBC TV18", "https://news.google.com/rss/articles/b3", h=3),
        _r("Nvidia B300 chips reportedly surface on China Telecom-linked network, raising export-control questions", "digitimes", "https://news.google.com/rss/articles/b4", h=4),
        _r("White House says Melania Trump 'secured a ceasefire' in Ukraine's Oleshky", "Al Jazeera", "https://www.aljazeera.com/news/x", via="직접", h=1),
        _r("Melania Trump secures Oleshky ceasefire between Russia, Ukraine, White House says", "Reuters", "https://news.google.com/rss/articles/c2", h=2),
        _r("Russia drops cluster bombs on Ukraine as Kyiv consolidates front line", "Al Jazeera", "https://www.aljazeera.com/news/y", via="직접", h=3),
    ]
    res = gn.assign(rows, ["rare_earth", "chips", "ruukr"], NOW)
    assert len(res["rare_earth"]) == 2 and len(res["chips"]) == 2 and len(res["ruukr"]) == 2
    # 다른 사건(유사도 ≤0.31)은 안 합친다
    assert not gn.same_event(_r("Brent Hits 114 dollars as Houthi Attacks Threaten Saudi Energy Infrastructure", "OilPrice", "https://oilprice.com/a"),
                             _r("Brent crude hits more than five-month high on Houthi-Saudi attacks, UAE oil spill", "Reuters", "https://news.google.com/x"))
    # 긴 라이브 블로그 제목 vs 짧은 속보 제목(자카드 0.375) — 짧은 쪽 60%·5단어 겹침으로 같은 사건 (10/24 00:33 실행)
    assert gn.same_event(_r("Melania Trump has helped broker ceasefire in Russian-occupied Ukrainian town, says White House – Europe live", "The Guardian", "https://g/1"),
                         _r("White House says Melania Trump brokers truce for Ukraine city 'on brink of disaster'", "BBC World", "https://b/1"))
    # 같은 링크 대상(쿼리·www 차이)은 제목이 달라도 같은 사건
    assert gn.same_event(_r("A", "x", "https://www.bbc.com/news/123?at=rss"), _r("Totally different", "y", "http://bbc.com/news/123/"))


def test_g2_g3_direct_version_replaces_search_version():
    rows = [_r("Melania Trump secures Oleshky ceasefire between Russia, Ukraine, White House says", "Reuters", "https://news.google.com/rss/articles/c2", h=1),
            _r("White House says Melania Trump 'secured a ceasefire' in Ukraine's Oleshky", "Al Jazeera", "https://www.aljazeera.com/news/x", via="직접", h=2)]
    got = gn.assign(rows, ["ruukr"], NOW)["ruukr"]
    assert [r["src"] for r in got] == ["Al Jazeera"]


def test_g3_google_items_published_without_title():
    p = gn.public_item(_r("Iran says 7 oil tankers damaged", "Reuters", "https://news.google.com/rss/articles/z"))
    assert p["title"] is None and "약관" in p["title_withheld"] and p["src"] == "Reuters" and p["time"] and p["link"]
    d = gn.public_item(_r("Iran says 7 oil tankers damaged", "BBC World", "https://www.bbc.com/news/1", via="직접"))
    assert d["title"] == "Iran says 7 oil tankers damaged" and "title_withheld" not in d
    old = gn.public_item({"title": "Old GN title", "src": "X", "time": "2026-10-23 10:00", "link": "https://news.google.com/rss/articles/q"})
    assert old["title"] is None and old["time"] == "2026-10-23 10:00"   # 옛 파일 항목(via 없음)도 링크로 판정


TW_RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
<item><title>Taiwan to Criminalize Unauthorized AI Chip Exports to China</title><link>https://news.google.com/rss/articles/tw</link>
<pubDate>Fri, 23 Oct 2026 10:00:00 GMT</pubDate><source url="https://techtimes.com">Tech Times</source></item>
<item><title>Iran says 7 oil tankers damaged in Strait of Hormuz</title><link>https://news.google.com/rss/articles/ir</link>
<pubDate>Fri, 23 Oct 2026 10:05:00 GMT</pubDate><source url="https://reuters.com">Reuters</source></item>
</channel></rss>"""


def _tw_fail(url):
    import urllib.parse
    if "news.google.com" in url and "Taiwan" in urllib.parse.unquote(url):
        raise RuntimeError("503 Server Error")
    return TW_RSS if "news.google.com" in url else RSS


def test_g1_axis_search_failure_keeps_previous_and_marks_stale(tmp_path, monkeypatch):
    """10/23 23:03: Google News taiwan 503 → 대만 AI칩 수출통제 기사(다른 축 검색에서 들어온 것)가 taiwan 축을 채움. 이제는 이전 값 + stale."""
    monkeypatch.setattr(gn, "OUT", tmp_path / "geo_news.json")
    prev = {"generated_at": "2026-10-23 16:20 KST", "axes": [
        {"id": "taiwan", "name": "대만", "items": [
            {"title": "PLA drills near Taiwan Strait", "src": "BBC World", "time": "2026-10-22 09:00", "link": "https://www.bbc.com/news/tw"},
            {"title": "GN title", "src": "Reuters", "time": "2026-10-22 08:00", "link": "https://news.google.com/rss/articles/old"},
            {"title": "too old", "src": "BBC World", "time": "2026-10-10 08:00", "link": "https://www.bbc.com/news/old"}]}]}
    (tmp_path / "geo_news.json").write_text(json.dumps(prev), encoding="utf-8")
    out = gn.build(fetch=_tw_fail, now=NOW)
    ax = {a["id"]: a for a in out["axes"]}
    tw = ax["taiwan"]
    assert tw["stale"]["since"] == "2026-10-23 16:20 KST" and "503" in tw["stale"]["why"] and out["stale_axes"] == ["taiwan"]
    assert [i["link"] for i in tw["items"]] == ["https://www.bbc.com/news/tw", "https://news.google.com/rss/articles/old"]
    assert tw["items"][1]["title"] is None   # 이전 값도 G3 규칙 재적용
    assert "stale" not in ax["hormuz"] and ax["hormuz"]["items"]
    assert all(i["title"] is None for i in ax["hormuz"]["items"] if "news.google.com" in i["link"])
    out2 = gn.build(fetch=_tw_fail, now=NOW)   # 다음 실행도 실패하면 since 는 최초 시각 유지
    assert next(a for a in out2["axes"] if a["id"] == "taiwan")["stale"]["since"] == "2026-10-23 16:20 KST"


def test_g1_no_previous_file_gives_empty_stale_axis(tmp_path, monkeypatch):
    monkeypatch.setattr(gn, "OUT", tmp_path / "geo_news.json")
    tw = next(a for a in gn.build(fetch=_tw_fail, now=NOW)["axes"] if a["id"] == "taiwan")
    assert tw["items"] == [] and tw["stale"]["since"] is None and tw["stale"]["kept"] == 0
