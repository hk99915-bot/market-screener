"""네이버(Npay 증권) 리서치 목록 API 파서 — 픽스처는 Actions 가 실제로 받은 응답(content 만 500자로 자름)."""
import json
from datetime import date
from pathlib import Path

import pytest

from screener import naver_research_api as nra
from screener import research, research_views as rv

FX = Path(__file__).parent / "fixtures"


def load(t):
    return json.loads((FX / f"naver_api_{t}_20261021.json").read_text(encoding="utf-8"))


def test_company_items_have_all_fields():
    rows = [nra.parse_item("company", it) for it in load("company")["items"]]
    assert len(rows) == 5 and all(rows)
    r = rows[0]
    assert r["code"] == "012450" and r["name"] == "한화에어로스페이스" and r["broker"] == "DS투자증권"
    assert r["opinion"] == "매수" and r["target"] == 1650000.0 and r["date"] == date(2026, 10, 20)
    assert r["title"] == "3Q에 대한 걱정 대신 4Q에 걸어볼 기대"
    assert r["link"] == "https://stock.naver.com/research/company/96882"
    assert 0 < len(r["summary"]) <= 500 and "<" not in r["summary"]


@pytest.mark.parametrize("t", ["industry", "market", "invest", "economy", "debenture"])
def test_views_items_parse(t):
    rows = [nra.parse_item(t, it) for it in load(t)["items"]]
    assert len(rows) == 5 and all(r and r["broker"] and r["title"] and r["summary"] for r in rows)
    assert all(r["link"].startswith(f"https://stock.naver.com/research/{'daily' if t == 'market' else t}/") for r in rows)


def test_industry_sector_and_analyst():
    r = nra.parse_item("industry", load("industry")["items"][0])
    assert r["sector"] == "자동차" and r["analyst"] == "김광식,최보영"


def test_summary_strips_html_and_clips():
    assert nra.summary("<p><strong>A</strong></p><p>&nbsp;B<br>C</p>") == "A B C"
    assert len(nra.summary("가" * 900)) == 500


def _pager(pages, one_based):
    calls = []

    def get(url):
        calls.append(url)
        i = int(url.split("index=")[1]) if "index=" in url else (1 if one_based else 0)
        k = i - (1 if one_based else 0)
        return pages[k] if k < len(pages) else {"hasNext": False, "items": []}
    return get, calls


def _page(nids, d, more=True):
    return {"hasNext": more, "totalCount": "9", "items": [
        {"nid": str(n), "title": f"t{n}", "brokerName": "B", "writeDate": d, "content": "<p>x</p>"} for n in nids]}


@pytest.mark.parametrize("one_based", [True, False])
def test_fetch_pages_until_older_regardless_of_index_base(one_based):
    pages = [_page([9, 8, 7], "2026-10-20"), _page([6, 5, 4], "2026-10-19"), _page([3, 2], "2026-10-10")]
    get, calls = _pager(pages, one_based)
    rows, diag = nra.fetch("market", date(2026, 10, 15), size=3, get=get, pause=0)
    assert [r["nid"] for r in rows] == ["9", "8", "7", "6", "5", "4"]
    assert diag["status"] == "ok" and diag["index_base"] == (1 if one_based else 0)


def test_research_fetch_naver_maps_rows(monkeypatch):
    monkeypatch.setattr(nra, "_get_json", lambda url: load("company") if "index" not in url else {"items": []})
    rows = research.fetch_naver(date(2026, 10, 20))
    assert len(rows) == 5 and rows[0]["source"] == "네이버" and rows[0]["target"] == 1650000.0
    assert research.NAVER_LAST["status"] == "ok"


def test_views_fetch_naver_records_keep_summary(monkeypatch):
    monkeypatch.setattr(nra, "_get_json", lambda url: load("industry") if "index" not in url else {"items": []})
    rows, st = rv.fetch_naver("industry", date(2026, 10, 20))
    assert st["status"] == "ok" and st["n"] == 5 and st["label"] == "산업분석"
    rec = rv.to_record(rows[0], "t")
    assert rec["summary"] and len(rec["summary"]) <= 500 and rec["source"] == "네이버"
