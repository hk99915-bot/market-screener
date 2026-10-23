"""부동산 트래킹(screener/realestate.py) — 부동산 데스크 10/23. 네트워크 없음(가짜 R-ONE·ECOS·RSS)."""
import json
from datetime import date, datetime, timezone

from screener import realestate as re_

NOW = datetime(2026, 10, 23, 13, 0, tzinfo=timezone.utc)

TABLES = {"SttsApiTbl": [{"head": [{"list_total_count": 4}, {"RESULT": {"CODE": "INFO-000"}}]}, {"row": [
    {"STATBL_ID": "M1", "DTACYCLE_CD": "MM", "STATBL_NM": "(월) 매매가격지수_아파트"},
    {"STATBL_ID": "W0", "DTACYCLE_CD": "WK", "STATBL_NM": "(주) 매매가격지수(계절조정)_아파트"},
    {"STATBL_ID": "W1", "DTACYCLE_CD": "WK", "STATBL_NM": "(주) 매매가격지수_아파트"},
    {"STATBL_ID": "W2", "DTACYCLE_CD": "WK", "STATBL_NM": "(주) 전세가격지수_아파트"},
]}]}


def _data(rows, total=None):
    return {"SttsApiTblData": [{"head": [{"list_total_count": total if total is not None else len(rows)}, {"RESULT": {"CODE": "INFO-000"}}]},
                               {"row": rows}]}


def _row(cls_id, full, week, val):
    return {"CLS_ID": cls_id, "CLS_NM": full.split(">")[-1], "CLS_FULLNM": full, "ITM_NM": "지수", "WRTTIME_IDTFR_ID": week, "DTA_VAL": val}


REGS = {1: "서울", 2: "서울>강남지역>동남권>강남구", 3: "서울>강북지역>동북권>노원구", 4: "경기>경부1권", 5: "부산"}
WEEKS = [f"2026{w:02d}" for w in range(1, 60)][:56]


def fake_json(url, params):
    if "SttsApiTbl.do" in url:
        return TABLES
    if "SttsApiTblData" in url:
        if params.get("CLS_ID") is None:
            return _data([_row(c, n, WEEKS[-1], 100.0) for c, n in REGS.items()], total=len(REGS) * len(WEEKS))
        c = params["CLS_ID"]
        # 강남 하락 추세, 노원 상승 추세, 나머지 평탄
        slope = {2: -0.1, 3: 0.2}.get(c, 0.0)
        return _data([_row(c, REGS[c], w, 100 + slope * i) for i, w in enumerate(WEEKS)])
    if "ecos" in url:
        if "722Y001" in url:
            return {"StatisticSearch": {"row": [{"TIME": f"2026{m:02d}", "DATA_VALUE": v} for m, v in [(6, "2.5"), (7, "2.75"), (8, "3"), (9, "3")]]}}
        if "151Y005" in url:
            return {"StatisticSearch": {"row": [{"TIME": "202607", "DATA_VALUE": "781727.6"}, {"TIME": "202608", "DATA_VALUE": "786089"}]}}
        return {"RESULT": {"CODE": "INFO-200", "MESSAGE": "해당하는 데이터가 없습니다."}}
    raise AssertionError(url)


RSS = """<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>서울 아파트값 89주 연속 상승…강남3구 하락 - 머니투데이</title><link>https://n.example/1</link>
<pubDate>Thu, 22 Oct 2026 05:00:00 GMT</pubDate><source url="https://mt.co.kr">머니투데이</source></item>
<item><title>3기 신도시 용적률 높여 3.8만 가구 더</title><link>https://n.example/2</link><pubDate>Thu, 22 Oct 2026 06:00:00 GMT</pubDate></item>
<item><title>수원 삼성, 홈경기 승리</title><link>https://n.example/3</link><pubDate>Thu, 22 Oct 2026 06:00:00 GMT</pubDate></item>
<item><title>재건축 조합원 지위 양도 제한 완화 검토</title><link>https://n.example/4</link><pubDate>Fri, 23 Oct 2026 01:00:00 GMT</pubDate></item>
</channel></rss>"""


def test_find_weekly_tables_skips_seasonal_and_monthly():
    _, rows = re_.rone_rows(TABLES, "SttsApiTbl")
    assert re_.find_weekly_tables(rows) == {"sale": "W1", "jeonse": "W2"}


def test_rone_error_and_empty():
    assert re_.rone_rows({"RESULT": {"CODE": "INFO-200", "MESSAGE": "없음"}}, "SttsApiTblData") == (0, [])
    try:
        re_.rone_rows({"RESULT": {"CODE": "ERROR-300", "MESSAGE": "필수 값"}}, "SttsApiTblData")
        assert False
    except ValueError as e:
        assert "ERROR-300" in str(e)


def test_group_prices_regions_and_average():
    rows = [_row(2, REGS[2], w, 100 - 0.1 * i) for i, w in enumerate(WEEKS)] + [_row(3, REGS[3], w, 100 + 0.2 * i) for i, w in enumerate(WEEKS)]
    g = {x["id"]: x for x in re_.group_prices(re_.series_by_region(rows))}
    core = g["core"]
    assert core["n_ok"] == 1 and core["chg1w"] < 0 and core["members"][1]["status"] == "미확인"   # 서초 없음 → 미확인, 평균은 있는 것만
    assert g["lower"]["chg1w"] > 0 and g["lower"]["pos52"] == 1.0
    st = re_.idx_stats([("a", 100.0), ("b", 101.0)])
    assert st["chg1w"] == 1.0 and st["chg4w"] is None


def test_ecos_parse_and_rate_row():
    s = re_.parse_ecos({"StatisticSearch": {"row": [{"TIME": "202608", "DATA_VALUE": "786089"}, {"TIME": "202607", "DATA_VALUE": "781727.6"}]}})
    assert s[0][0] == "202607"
    r = re_.rate_row("HOUSING_LOAN", "주택관련대출", "조원", "", s, date(2026, 10, 23))
    assert r["last"] == 786.09 and r["chg1m"] == 4.36 and r["month"] == "2026-08" and r["status"] == "ok"
    old = re_.rate_row("X", "x", "%", "", [("202501", 3.0)], date(2026, 10, 23))
    assert old["status"] == "미확인"
    assert re_.parse_ecos({"RESULT": {"CODE": "INFO-200"}}) == []


def test_news_cue_filter():
    assert re_.match_news("수원 삼성, 홈경기 승리") == []          # 지역명만 있고 부동산 단서 없음
    assert "redev" in re_.match_news("재건축 조합원 지위 양도 제한 완화 검토")
    assert set(re_.match_news("서울 아파트값 89주 연속 상승…강남3구 하락")) >= {"market", "core"}


def test_build_without_key_marks_prices_key_needed(tmp_path, monkeypatch):
    monkeypatch.setattr(re_, "OUT", tmp_path / "realestate.json")
    reits = {"329200.KS": [(f"2026-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}", 4000 + i) for i in range(260)]}
    out = re_.build(fetch_json=fake_json, fetch_text=lambda u: RSS, fetch_prices=lambda s: reits, now=NOW, env={})
    assert out["prices"]["status"] == "키 필요"
    base = next(r for r in out["rates"] if r["key"] == "BOK_BASE")
    assert base["last"] == 3.0 and base["chg1m"] == 0.0
    assert next(r for r in out["rates"] if r["key"] == "MORT_RATE")["status"] == "미확인"
    news = {a["id"]: a["items"] for a in out["news"]}
    assert news["newtown"] and news["redev"] and not any("홈경기" in i["title"] for v in news.values() for i in v)
    from screener import contracts
    assert contracts.check("reports/realestate.json", out) == []
    assert json.loads((tmp_path / "realestate.json").read_text(encoding="utf-8"))["asof"] == "2026-10-23"
    assert {u["key"] for u in out["unavailable"]} >= {"MOLIT_RTMS", "KB_WEEKLY"}


def test_build_with_key_fills_regions(tmp_path, monkeypatch):
    monkeypatch.setattr(re_, "OUT", tmp_path / "realestate.json")
    out = re_.build(fetch_json=fake_json, fetch_text=lambda u: RSS, fetch_prices=lambda s: {}, now=NOW, env={"REB_API_KEY": "k"})
    p = out["prices"]
    assert p["status"] == "ok" and p["tables"] == {"sale": "W1", "jeonse": "W2"}
    g = {x["id"]: x for x in p["sale"]}
    assert g["core"]["chg1w"] < 0 < g["lower"]["chg1w"] and g["gg_south"]["n_ok"] == 1 and g["seoul"]["chg1w"] == 0.0


def test_build_all_fail_keeps_previous(tmp_path, monkeypatch):
    monkeypatch.setattr(re_, "OUT", tmp_path / "realestate.json")
    calls = []
    monkeypatch.setattr("screener.guard.record_stale", lambda *a: calls.append(a))

    def boom(*a, **k):
        raise RuntimeError("offline")
    assert re_.build(fetch_json=boom, fetch_text=boom, fetch_prices=boom, now=NOW, env={"REB_API_KEY": "k"}) is None
    assert not (tmp_path / "realestate.json").exists() and calls
