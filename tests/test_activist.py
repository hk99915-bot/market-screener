"""screener/activist.py — 네트워크 없이 픽스처로 (DART 목록·원문, EDGAR master.idx, 13D 원문, 가격)."""
from datetime import date

import polars as pl

from screener import activist as A

ROSTER = A.load_roster()


def _dart(rows):
    return pl.DataFrame([{"rcept_no": r[0], "date": date(2026, 10, 1), "code": r[1], "name": r[2], "corp_cls": "Y",
                          "title": r[3], "filer": r[4], "rm": "", "category": "지분 5%", "flag": ""} for r in rows])


def test_roster_shape():
    assert len(ROSTER["KR"]) >= 5 and len(ROSTER["US"]) >= 5
    for e in ROSTER["KR"] + ROSTER["US"]:
        assert e["id"] and e["aliases"] and "verified" in e and e.get("evidence")
    # CIK 는 확인된 것만 숫자 — 나머지는 null
    assert {e["id"] for e in ROSTER["US"] if e.get("cik")} == {"pershing", "trian", "starboard"}


def test_match_normalizes_names():
    kr = ROSTER["KR"]
    assert A.match("얼라인파트너스자산운용(주)", kr)["id"] == "align"
    assert A.match("주식회사 케이씨지아이", kr)["id"] == "kcgi"
    assert A.match("삼성물산", kr) is None
    us = ROSTER["US"]
    assert A.match("Starboard Value LP", us)["id"] == "starboard"
    assert A.match("anything", us, cik=1336528)["id"] == "pershing"
    assert A.match("THIRD POINT REINSURANCE LTD", us) is None   # 발행사와 혼동 금지


def test_parse_purpose():
    assert A.parse_purpose("<TD>보유목적</TD><TD>경영권 영향</TD>") == "경영참가"
    assert A.parse_purpose("보 유 목 적 : 단순투자") == "단순투자"
    assert A.parse_purpose("보유목적 일반투자 (경영권 영향 목적 아님)") == "일반투자"
    assert A.parse_purpose("보유목적 없음") is None


def test_kr_events_classification():
    df = _dart([
        ("1", "000001", "가회사", "주식등의대량보유상황보고서(일반)", "얼라인파트너스자산운용"),   # 명단+일반 → campaign(서식 추정)
        ("2", "000002", "나회사", "주식등의대량보유상황보고서(약식)", "트러스톤자산운용"),         # 명단+약식 → holding
        ("3", "000003", "다회사", "주식등의대량보유상황보고서(일반)", "홍길동"),                   # 명단 밖 일반 → 개수만
        ("4", "000004", "라회사", "주식등의대량보유상황보고서(일반)", "어떤투자조합"),             # 명단 밖 + 원문 경영참가 → campaign
        ("5", "000005", "마회사", "주식등의대량보유상황보고서(일반)", "차파트너스자산운용"),       # 명단 + 원문 단순투자 → holding
    ])
    ev, other = A.kr_events(df, ROSTER["KR"], purposes={"4": "경영참가", "5": "단순투자"}, stakes={"1": 5.03})
    k = {x["id"]: x for x in ev}
    assert k["KR-1"]["kind"] == "campaign" and k["KR-1"]["stake_pct"] == 5.03 and k["KR-1"]["purpose"] is None
    assert k["KR-2"]["kind"] == "holding"
    assert "KR-3" not in k and other == 1
    assert k["KR-4"]["kind"] == "campaign" and k["KR-4"]["roster_id"] is None
    assert k["KR-5"]["kind"] == "holding"


MASTER = """Description:           Daily Index of EDGAR Dissemination Feed by Company Name
CIK|Company Name|Form Type|Date Filed|Filename
--------------------------------------------------------------------------------
1517137|Starboard Value LP|SCHEDULE 13D|20261015|edgar/data/1517137/0000921895-26-000001.txt
723125|MICRON TECHNOLOGY INC|SCHEDULE 13D|20261015|edgar/data/723125/0000921895-26-000001.txt
99999|ELLIOTT INVESTMENT MANAGEMENT L.P.|SC 13D/A|20261015|edgar/data/99999/0000902664-26-000002.txt
92380|SOUTHWEST AIRLINES CO|SC 13D/A|20261015|edgar/data/92380/0000902664-26-000002.txt
11111|PASSIVE FUND|SC 13G|20261015|edgar/data/11111/0000000000-26-000003.txt
22222|Random Holder LLC|SCHEDULE 13D|20261015|edgar/data/22222/0000000000-26-000004.txt
33333|SOME ISSUER|SCHEDULE 13D|20261015|edgar/data/33333/0000000000-26-000004.txt
"""


def test_parse_master_and_us_events():
    rows = A.parse_master(MASTER)
    assert len(rows) == 6 and all(r["form"] != "SC 13G" for r in rows)
    assert rows[0]["date"] == "2026-10-15"
    ev = A.us_events(rows, ROSTER["US"], {723125: "MU", 92380: "LUV"})
    k = {x["id"]: x for x in ev}
    assert set(k) == {"US-0000921895-26-000001", "US-0000902664-26-000002"}   # 명단 밖 13D 는 제외
    s = k["US-0000921895-26-000001"]
    assert s["roster_id"] == "starboard" and s["symbol"] == "MU" and s["kind"] == "campaign"
    e = k["US-0000902664-26-000002"]
    assert e["roster_id"] == "elliott" and e["symbol"] == "LUV" and e["kind"] == "amend"


def test_parse_13d_pct():
    assert A.parse_13d_pct("<coverPageHeader/><percentOfClass>7.4</percentOfClass>") == 7.4
    legacy = "13 PERCENT OF CLASS REPRESENTED BY AMOUNT IN ROW (11)\n<br>   9.9%\n14 TYPE OF REPORTING PERSON"
    assert A.parse_13d_pct(legacy) == 9.9
    assert A.parse_13d_pct("nothing") is None


def test_post_returns_and_flags():
    px = pl.DataFrame({"sym": ["X"] * 5, "date": [date(2026, 9, 29), date(2026, 9, 30), date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 5)],
                       "close": [99.0, 100.0, 107.0, 110.0, 90.0]})
    r = A.post_returns(px, "X", "2026-10-01", horizons=(0, 1, 2, 5))
    assert r["base_date"] == "2026-09-30" and r["d0"] == 7.0 and r["d1"] == 10.0 and r["d2"] == -10.0 and r["d5"] is None
    assert A.post_returns(px, "Y", "2026-10-01") == {}
    ev = A.flag([{"symbol": "X", "kind": "campaign"}, {"symbol": "Z", "kind": "holding"}, {"symbol": None, "kind": "campaign"}], {"X", "Z"}, set())
    assert [x["event"] for x in ev] == [True, False, False]


def test_merge_keeps_old_enrichment_and_prunes():
    old = [{"id": "KR-1", "date": "2026-10-01", "purpose": "경영참가", "stake_pct": 6.1},
           {"id": "KR-0", "date": "2024-01-01", "purpose": None, "stake_pct": None}]
    new = [{"id": "KR-1", "date": "2026-10-01", "purpose": None, "stake_pct": None, "kind": "campaign"}]
    m = A.merge(old, new, date(2026, 10, 17))
    assert len(m) == 1 and m[0]["purpose"] == "경영참가" and m[0]["stake_pct"] == 6.1 and m[0]["kind"] == "campaign"


def test_run_offline(tmp_path, monkeypatch):
    """키·네트워크 없이 DART 저장분만으로 돌고, 텔레그램/네트워크를 부르지 않는다."""
    monkeypatch.delenv("DART_API_KEY", raising=False)
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    from screener import dart
    df = _dart([("9", "005930", "삼성전자", "주식등의대량보유상황보고서(일반)", "얼라인파트너스자산운용")])
    monkeypatch.setattr(dart, "load", lambda: df.with_columns(pl.lit(date.today()).alias("date")))
    monkeypatch.setattr(A, "_prices", lambda m: pl.DataFrame(schema={"sym": pl.Utf8, "date": pl.Date, "close": pl.Float64}))

    def boom(*a, **k):
        raise AssertionError("네트워크 호출 금지")
    monkeypatch.setattr(A.requests, "get", boom)
    out = tmp_path / "activist.json"
    rep = A.run(days=7, out=out)
    assert out.exists() and rep["grade"] == "검증전"
    assert rep["counts"]["campaign"] == 1 and rep["events"][0]["in_universe"] in (True, False)
    assert any("SEC_USER_AGENT" in n for n in rep["notes"])
