"""부동산 트래킹(screener/realestate.py) — 부동산 데스크 10/23. 네트워크 없음(가짜 R-ONE·ECOS·RSS)."""
import json
import urllib.parse
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
    assert g["lower"]["chg1w"] > 0 and g["lower"]["pos52_avg"] == 1.0 and "pos52" not in g["lower"]
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


def test_news_lower_guro_boundary():
    # 피어 10/24 R3: '8336가구로' 의 '구로'가 하급지 축에 걸리던 버그
    assert "lower" not in re_.match_news("재건축·재개발로 2~3년 내 사라지는 집, ‘4만8249가구’… 용산구 8336가구로 ‘최다’")
    assert "lower" not in re_.match_news("조합원 요구로 재건축 일정 연기")
    assert "lower" in re_.match_news("구로구 아파트값 상승")
    assert "lower" in re_.match_news("구로동 재개발 단지 시공사 선정")
    assert "lower" in re_.match_news("금천·구로 아파트 거래 늘어")
    assert "lower" in re_.match_news("서울 구로 아파트 신고가")


def test_news_cue_excludes_industrial_complex():
    # 피어 10/24 경: CUE '단지'가 '산업단지'를 통과시키던 것
    assert re_.match_news("용인 반도체 산업단지 착공") == []
    assert re_.match_news("평택 산업 단지 조성") == []
    assert "gg_south" in re_.match_news("동탄 대단지 입주 시작")


def test_build_without_key_marks_prices_key_needed(tmp_path, monkeypatch):
    monkeypatch.setattr(re_, "OUT", tmp_path / "realestate.json")
    reits = {"329200.KS": [(f"2026-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}", 4000 + i) for i in range(260)]}
    out = re_.build(fetch_json=fake_json, fetch_text=lambda u: RSS, fetch_prices=lambda s: reits, now=NOW, env={})
    assert out["prices"]["status"] == "키 필요"
    base = next(r for r in out["rates"] if r["key"] == "BOK_BASE")
    assert base["last"] == 3.0 and base["chg1m"] == 0.0
    assert next(r for r in out["rates"] if r["key"] == "MORT_RATE")["status"] == "미확인"
    news = {a["id"]: a["items"] for a in out["news"]}
    assert news["newtown"] and news["redev"] and not any(i["link"] == "https://n.example/3" for v in news.values() for i in v)   # 홈경기 기사 제외
    # 10/24 피어 G3: Google News 경유 → 공개 산출물에 제목 비공개(매체·시각·링크만)
    assert all(i["title"] is None and i["title_withheld"] and i["time"] for v in news.values() for i in v)
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


def test_news_axis_failure_keeps_previous_and_marks_stale(tmp_path, monkeypatch):
    """10/24 req-realestate-c3d27b87: 축 검색 실패가 빈 칸으로 조용히 나가던 구멍 → 이전 값(7일 창 안) + stale, 최상위 stale_axes."""
    monkeypatch.setattr(re_, "OUT", tmp_path / "realestate.json")
    q = re_.NEWS_AXES["policy"][2]
    fail = lambda u: (_ for _ in ()).throw(RuntimeError("503 Server Error")) if urllib.parse.quote(q) in u else RSS  # noqa: E731
    prev = {"generated_at": "2026-10-23 06:52 KST", "news": [{"id": "policy", "name": "정책", "items": [
        {"title": "옛 제목 노출", "src": "뉴시스", "time": "2026-10-22 09:00", "link": "https://news.google.com/rss/articles/a"},
        {"title": None, "src": "MTN", "time": "2026-10-10 09:00", "link": "https://news.google.com/rss/articles/old"}]}]}
    (tmp_path / "realestate.json").write_text(json.dumps(prev), encoding="utf-8")
    out = re_.build(fetch_json=fake_json, fetch_text=fail, fetch_prices=lambda s: {}, now=NOW, env={})
    ax = {a["id"]: a for a in out["news"]}
    pol = ax["policy"]
    assert out["stale_axes"] == ["policy"] and "503" in pol["stale"]["why"] and pol["stale"]["since"] == "2026-10-23 06:52 KST"
    assert [i["link"] for i in pol["items"]] == ["https://news.google.com/rss/articles/a"] and pol["stale"]["kept"] == 1   # 7일 밖 제외
    assert pol["items"][0]["title"] is None and pol["items"][0]["title_withheld"]   # 이전 값에도 G3 재적용
    assert "stale" not in ax["newtown"] and ax["newtown"]["items"]
    from screener import contracts
    assert contracts.check("reports/realestate.json", out) == []
    out2 = re_.build(fetch_json=fake_json, fetch_text=fail, fetch_prices=lambda s: {}, now=NOW, env={})   # 연속 실패 → since 최초 유지
    assert next(a for a in out2["news"] if a["id"] == "policy")["stale"]["since"] == "2026-10-23 06:52 KST"


def test_news_axis_failure_without_previous_is_empty_stale(tmp_path, monkeypatch):
    monkeypatch.setattr(re_, "OUT", tmp_path / "realestate.json")
    q = re_.NEWS_AXES["redev"][2]
    fail = lambda u: (_ for _ in ()).throw(RuntimeError("timeout")) if urllib.parse.quote(q) in u else RSS  # noqa: E731
    out = re_.build(fetch_json=fake_json, fetch_text=fail, fetch_prices=lambda s: {}, now=NOW, env={})
    rd = next(a for a in out["news"] if a["id"] == "redev")
    assert rd["items"] == [] and rd["stale"] == {"why": "Google News 검색 실패(timeout) — 이전 값 유지", "since": None, "kept": 0}
    assert out["stale_axes"] == ["redev"]


def test_regions_block_stage_priority_and_geo():
    """지도 칸(10/24): R-ONE 1차 > 2차 스냅샷(검증전) > 미확인 — 숫자를 지어내지 않음 · 지오 자산은 출처·라이선스 포함."""
    prices = {"status": "ok", "sale_areas": {"강남구": {"status": "ok", "week": "202642", "chg1w": -0.3, "chg4w": -1.0, "pos52": 0.2}}}
    snap = {"_week": "W", "_src": "S", "강남구": {"sale_1w": 9.9}, "양천구": {"sale_1w": 0.16, "src": "세계일보"}, "마포구": {"why": "미보도"}}
    r = re_.build_regions(prices, {"양천구": [{"title": None, "src": "x"}]}, snap)
    a = {x["id"]: x for x in r["areas"]}
    assert len(a) == 46 and a["강남구"]["stage"] == "1차" and a["강남구"]["sale_1w"] == -0.3
    assert a["양천구"]["stage"].startswith("2차") and a["양천구"]["sale_1w"] == 0.16 and a["양천구"]["week"] == "W" and a["양천구"]["news"]
    assert a["마포구"]["stage"] == "미확인" and "sale_1w" not in a["마포구"] and a["마포구"]["why"] == "미보도"
    assert a["강남구"]["groups"] == ["core"] and r["n_valued"] == 2
    geo = r["geo"]
    assert geo and geo["source"]["license"] == "CC BY 3.0" and "geoBoundaries" in geo["source"]["attribution"]
    ids = {x["id"] for x in geo["areas"]}
    assert set(a) <= ids and all(x["d"].startswith("M") for x in geo["areas"])


def test_area_news_alias_and_title_withheld():
    items = [{"title": "목동 재건축 아파트 신고가", "src": "A", "when": NOW, "link": "l1"},
             {"title": "양천구 축제 개막", "src": "B", "when": NOW, "link": "l2"}]   # 부동산 단서 없음 → 제외
    out = re_.area_news(items, NOW)
    assert [x["link"] for x in out["양천구"]] == ["l1"] and out["양천구"][0]["title"] is None


# ── 국토부 RTMS 서울 25개 구 집계(데이터 10/24) — 가짜 XML, 네트워크 없음 ──
def _xml(items, total=None, code="000"):
    body = "".join("<item>" + "".join(f"<{k}>{v}</{k}>" for k, v in it.items()) + "</item>" for it in items)
    return (f"<response><header><resultCode>{code}</resultCode><resultMsg>OK</resultMsg></header><body><items>{body}</items>"
            f"<totalCount>{len(items) if total is None else total}</totalCount></body></response>").encode()


def _tr(amt, area, by="2005", cancel=""):
    return {"dealAmount": amt, "excluUseAr": area, "buildYear": by, "cdealType": cancel}


def test_rtms_months_excludes_current():
    assert re_.rtms_months(date(2026, 10, 24)) == ["202607", "202608", "202609"]
    assert re_.rtms_months(date(2026, 2, 3)) == ["202511", "202512", "202601"]


def test_parse_rtms_xml_and_error():
    items, total = re_.parse_rtms_xml(_xml([_tr("95,000", "59.9")], total=7))
    assert items[0]["dealAmount"] == "95,000" and total == 7
    try:
        re_.parse_rtms_xml(_xml([], code="30"))
        assert False, "오류 코드는 예외"
    except ValueError as e:
        assert "30" in str(e)


def test_summarize_gu_bands_cancel_jeonse():
    trades = [_tr("60,000", "59.8"), _tr("80,000", "59.9", "1995"), _tr("99,000", "59.9", cancel="O"),   # 취소 1건 제외
              _tr("100,000", "84.9"), _tr("120,000", "84.5"), _tr("140,000", "84.1"), _tr("160,000", "84.7", "1990"),
              _tr("50,000", "40.0")]                                                                        # 밴드 밖
    rents = [{"deposit": "65,000", "monthlyRent": "0", "excluUseAr": "84.9"}, {"deposit": "75,000", "monthlyRent": "", "excluUseAr": "84.0"},
             {"deposit": "10,000", "monthlyRent": "120", "excluUseAr": "84.0"}]                              # 월세 제외
    s = re_.summarize_gu(trades, rents)
    assert s["n"] == 7 and s["n_cancel"] == 1 and s["n_jeonse"] == 2
    assert s["p59"] == 7.0 and s["n59"] == 2 and s["entry"] == "중"
    assert s["p84"] == 13.0 and s["p84_q1"] == 12.0 and s["n84"] == 4
    assert s["j84"] == 7.0 and s["jeonse_ratio"] == 54
    assert s["pre1999"] == round(2 / 7 * 100)
    assert re_.entry_level(6.99) == "하" and re_.entry_level(12) == "상" and re_.entry_level(None) is None


def test_fetch_rtms_paginates():
    calls = []

    def get(url, params):
        calls.append(params["pageNo"])
        n = re_.RTMS_ROWS if params["pageNo"] == "1" else 3
        return _xml([_tr("1", "59")] * n, total=re_.RTMS_ROWS + 3)
    assert len(re_.fetch_rtms(get, re_.RTMS_TRADE, "11110", "202609", "K")) == re_.RTMS_ROWS + 3 and calls == ["1", "2"]


def test_seoul_trades_skip_failed_and_no_key_leak():
    key = "SECRET+KEY/=="

    def get(url, params):
        assert params["serviceKey"] == key
        if params["LAWD_CD"] == "11110":
            raise RuntimeError(f"boom https://apis.data.go.kr/x?serviceKey={key}&LAWD_CD=11110")
        if "Trade" in url:
            return _xml([_tr("65,000", "59.5"), _tr("130,000", "84.0")])
        return _xml([{"deposit": "70,000", "monthlyRent": "0", "excluUseAr": "84.0"}])
    out = re_.fetch_seoul_trades(get, key, date(2026, 10, 24))
    assert out["status"] == "부분" and out["n_ok"] == 24 and [f["id"] for f in out["failed"]] == ["종로구"]
    assert out["districts"]["강남구"]["entry"] == "하" and out["districts"]["강남구"]["jeonse_ratio"] == 54
    assert out["period"] == "202607~202609"
    dumped = json.dumps(out, ensure_ascii=False)
    assert key not in dumped and urllib.parse.quote(key, safe="") not in dumped and "serviceKey=***" in dumped


def test_seoul_trades_no_key_and_daily_reuse():
    assert re_.fetch_seoul_trades(lambda u, p: b"", None, date(2026, 10, 24))["status"] == "키 필요"
    prev = {"status": "ok", "asof": "2026-10-24", "districts": {"강남구": {"p59": 20}}}

    def boom(u, p):
        raise AssertionError("같은 날 재호출 금지")
    assert re_.fetch_seoul_trades(boom, "K", date(2026, 10, 24), prev)["reused"] is True
    kept = re_.fetch_seoul_trades(boom, None, date(2026, 10, 25), prev)
    assert kept["reused"] and kept["districts"]["강남구"]["p59"] == 20


# ── 드릴다운(10/26 겸이 "구 클릭→동, 동 클릭→단지") — 같은 원자료로 법정동·단지 집계, 구별 파일 ──
def _tx(amt, area, dong, apt, d, fl="5", by="2005", cancel=""):
    return {"dealAmount": amt, "excluUseAr": area, "umdNm": dong, "aptNm": apt, "dealYear": "2026", "dealMonth": d[:2], "dealDay": d[2:],
            "floor": fl, "buildYear": by, "cdealType": cancel}


def test_summarize_detail_dong_and_complex():
    trades = [_tx("100,000", "84.9", "역삼동", "가단지", "0910", "12"), _tx("120,000", "84.6", "역삼동", "가단지", "0915", "3"),
              _tx("60,000", "59.9", "역삼동", "가단지", "0801"), _tx("140,000", "84.1", "역삼동", "가단지", "0920", "7"),
              _tx("90,000", "59.5", "역삼동", "나단지", "0705", by="1992"), _tx("99,000", "84.0", "역삼동", "나단지", "0706", cancel="O"),
              _tx("70,000", "59.2", "개포동", "다단지", "0901")]
    rents = [{"deposit": "65,000", "monthlyRent": "0", "excluUseAr": "84.9", "umdNm": "역삼동", "aptNm": "가단지"},
             {"deposit": "10,000", "monthlyRent": "100", "excluUseAr": "84.9", "umdNm": "역삼동", "aptNm": "가단지"},
             {"deposit": "30,000", "monthlyRent": "0", "excluUseAr": "39.0", "umdNm": "개포동", "aptNm": "라단지", "buildYear": "1988"}]
    d = re_.summarize_detail(trades, rents)
    dongs = {x["name"]: x for x in d["dongs"]}
    assert [x["name"] for x in d["dongs"]] == ["역삼동", "개포동"]                # 거래 수 많은 순
    y = dongs["역삼동"]
    assert y["n"] == 5 and y["n_cancel"] == 1 and y["n_jeonse"] == 1 and y["med"] == 10.0
    assert y["p84"] == 12.0 and y["n84"] == 3 and y["p59"] == 7.5 and y["n_cx"] == 2
    assert dongs["개포동"]["n_jeonse"] == 1 and dongs["개포동"]["n_cx"] == 2       # 전세만 있는 단지도 셈
    cx = {(c["dong"], c["name"]): c for c in d["complexes"]}
    g = cx[("역삼동", "가단지")]
    assert g["n"] == 4 and g["n_jeonse"] == 1 and g["by"] == 2005 and g["last_d"] == "2026-09-20"
    assert [r["d"] for r in g["recent"]] == ["2026-09-20", "2026-09-15", "2026-09-10"] and g["recent"][0] == {"d": "2026-09-20", "fl": "7", "a": 84.1, "p": 14.0}
    a85 = next(a for a in g["areas"] if a["a"] == 85)
    assert g["areas"][0]["a"] in (84, 85) and sum(a["n"] for a in g["areas"]) == 4 and a85["last_d"] >= "2026-09-10"
    assert cx[("역삼동", "나단지")]["n"] == 1 and cx[("역삼동", "나단지")]["n_cancel"] == 1 and cx[("역삼동", "나단지")]["by"] == 1992
    assert cx[("개포동", "라단지")]["n"] == 0 and cx[("개포동", "라단지")]["by"] == 1988 and cx[("개포동", "라단지")]["recent"] == []


def test_seoul_trades_detail_out_and_files(tmp_path, monkeypatch):
    def get(url, params):
        if "Trade" in url:
            return _xml([_tx("65,000", "59.5", "역삼동", "가단지", "0910"), _tx("130,000", "84.0", "삼성동", "나단지", "0911")])
        return _xml([{"deposit": "70,000", "monthlyRent": "0", "excluUseAr": "84.0", "umdNm": "삼성동", "aptNm": "나단지"}])
    det: dict = {}
    out = re_.fetch_seoul_trades(get, "K", date(2026, 10, 26), detail_out=det)
    assert out["detail_dir"] == "reports/realestate_trades" and len(det) == 25
    g = out["districts"]["강남구"]
    assert g["detail"] == "reports/realestate_trades/11680.json" and g["n_dong"] == 2 and g["n_cx"] == 2
    assert {"p59", "n", "entry", "code"} <= set(g)                                    # 기존 칸 유지(하위 호환)
    monkeypatch.chdir(tmp_path)
    assert re_.write_details(out, {"11680": det["11680"]}, tmp_path) == 1
    doc = json.loads((tmp_path / "11680.json").read_text(encoding="utf-8"))
    assert doc["gu"] == "강남구" and doc["asof"] == "2026-10-26" and doc["label"].startswith("표시 전용") and len(doc["dongs"]) == 2
    # 같은 날 재사용: detail_dir 있는 값이면 재호출 안 함, 없는 옛 값이면 한 번 더 받음
    def boom(u, p):
        raise AssertionError("재호출 금지")
    assert re_.fetch_seoul_trades(boom, "K", date(2026, 10, 26), out, detail_out={})["reused"] is True
    old = {k: v for k, v in out.items() if k != "detail_dir"}
    again = re_.fetch_seoul_trades(get, "K", date(2026, 10, 26), old, detail_out={})
    assert not again.get("reused") and again["detail_dir"]
