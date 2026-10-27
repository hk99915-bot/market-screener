"""금융위 V2 일일 수집기 — 네트워크 없음 (data 데스크 10/27, req-data-784ffc43)."""
import json
from datetime import date

from screener import fsc_daily as fd


def _body(items, total=None, code="00"):
    return {"response": {"header": {"resultCode": code}, "body": {"items": {"item": items}, "totalCount": total if total is not None else len(items)}}}


def _patch(tmp_path, monkeypatch):
    monkeypatch.setattr(fd, "RAW", tmp_path / "fsc")
    monkeypatch.setattr(fd, "STATUS", tmp_path / "st.json")


def test_no_key(tmp_path, monkeypatch):
    _patch(tmp_path, monkeypatch)
    assert fd.run(env={}, today=date(2026, 10, 27))["status"] == "키 대기"


def test_paging_raw_saved_status_has_no_values(tmp_path, monkeypatch):
    _patch(tmp_path, monkeypatch)
    monkeypatch.setattr(fd, "PAGE", 2)
    data = [{"srtnCd": f"00{i:04d}", "clpr": str(1000 + i)} for i in range(5)]

    def factory(api):
        def get(p):
            k = int(p["pageNo"])
            return _body(data[(k - 1) * 2:k * 2], total=5)
        return get
    st = fd.run(get_factory=factory, env={"DATA_GO_KR_KEY": "k"}, days=1, today=date(2026, 10, 27), apis=["stock"])
    day = st["apis"]["stock"]["days"][0]
    assert day["status"] == "ok" and day["rows"] == 5 and day["basDt"] == "2026-10-26"
    assert len(fd.load_raw("stock", date(2026, 10, 26))) == 5
    pub = (tmp_path / "st.json").read_text(encoding="utf-8")
    assert "1004" not in pub and "license" in json.loads(pub)   # 공개 상태 파일엔 원값 없음
    # 두 번째 실행은 보유분 건너뜀
    st2 = fd.run(get_factory=lambda a: (lambda p: 1 / 0), env={"DATA_GO_KR_KEY": "k"}, days=1, today=date(2026, 10, 27), apis=["stock"])
    assert st2["apis"]["stock"]["days"][0]["status"] == "보유"


def test_error_and_empty_and_resultcode(tmp_path, monkeypatch):
    _patch(tmp_path, monkeypatch)
    assert fd.fetch_day("index", date(2026, 10, 26), "k", lambda p: _body([]))["status"] == "행 없음"
    assert fd.fetch_day("index", date(2026, 10, 26), "k", lambda p: _body([], code="30"))["status"] == "실패"
    r = fd.fetch_day("index", date(2026, 10, 26), "k", lambda p: (_ for _ in ()).throw(ValueError("serviceKey=SECRET")))
    assert r["status"] == "실패" and "SECRET" not in json.dumps(r)


def test_probe_range_and_summaries(tmp_path, monkeypatch):
    _patch(tmp_path, monkeypatch)
    out = fd.probe_range(get_factory=lambda a: (lambda p: _body([{"x": 1}], total=0 if p["basDt"] < "2020" else 7)),
                         env={"DATA_GO_KR_KEY": "k"}, apis=["option"])
    assert out["option"]["oldest_with_rows"] == "2020-01-02"
    d = date(2026, 10, 26)
    fd.save_raw("stock_future", d, [{"itmsNm": "삼성전자 F 202612", "opnint": "100", "trqu": "5"},
                                    {"itmsNm": "삼성전자 F 202703", "opnint": "20", "trqu": "1"},
                                    {"itmsNm": "SK하이닉스 F 202612", "opnint": "50", "trqu": "2"}])
    s = fd.summary_stock_futures(d)
    assert s[0]["base"] == "삼성전자" and s[0]["oi"] == 120 and s[1]["base"] == "SK하이닉스"
    fd.save_raw("option", d, [{"itmsNm": "코스피200 C 202611 900.0", "opnint": "100", "iptVlty": "40"},
                              {"itmsNm": "코스피200 P 202611 800.0", "opnint": "150", "iptVlty": "55"}])
    o = fd.summary_options(d)
    assert o["pcr_oi"] == 1.5 and o["n"] == 2
