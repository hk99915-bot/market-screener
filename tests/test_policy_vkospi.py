"""정책금리(policy_rates)·VKOSPI 수집 — 네트워크 없음 (data 데스크 10/25)."""
import json
from datetime import date

from screener import policy_rates as pr
from screener import vkospi as vk


def test_us_summary_changes():
    obs = [("2026-09-15", 4.25), ("2026-09-16", 4.25), ("2026-09-17", 4.0), ("2026-09-18", 4.0)]
    s = pr.us_summary(obs)
    assert s["value"] == 4.0 and s["last_change"] == {"date": "2026-09-17", "bp": -25}
    assert pr.us_summary([]) is None


def test_policy_collect(tmp_path, monkeypatch):
    monkeypatch.setattr(pr, "OUT", tmp_path / "p.json")
    ecos = {"StatisticSearch": {"row": [{"TIME": "202608", "DATA_VALUE": "3.00"}, {"TIME": "202609", "DATA_VALUE": "3.25"}]}}
    out = pr.collect(fred=lambda sid: [("2026-10-01", 4.0), ("2026-10-02", 4.0)], fetch_json=lambda u: ecos, env={}, today=date(2026, 10, 25))
    assert out["us"]["upper"]["series"] == "DFEDTARU" and out["us"]["lower"]["value"] == 4.0
    assert out["kr"]["value"] == 3.25 and out["kr"]["chg1m_bp"] == 25 and "sample" in out["kr"]["key"]
    assert "미확인" in out["kr_meeting"]
    assert json.loads((tmp_path / "p.json").read_text())["kr"]["month"] == "2026-09"


def test_policy_fred_fail_keeps_old(tmp_path, monkeypatch):
    f = tmp_path / "p.json"
    monkeypatch.setattr(pr, "OUT", f)
    f.write_text(json.dumps({"us": {"upper": {"series": "DFEDTARU", "value": 4.0}}, "kr": {"value": 3.0}}))

    def boom(*a):
        raise RuntimeError("x")
    out = pr.collect(fred=boom, fetch_json=boom, env={}, today=date(2026, 10, 25))
    assert out["us"]["upper"]["value"] == 4.0 and "stale" in out["us"]["upper"]
    assert out["kr"]["value"] == 3.0 and "stale" in out["kr"]


def _patch(tmp_path, monkeypatch):
    monkeypatch.setattr(vk, "CSV", tmp_path / "v.csv")
    monkeypatch.setattr(vk, "STATUS", tmp_path / "v.json")


def test_vkospi_no_key(tmp_path, monkeypatch):
    _patch(tmp_path, monkeypatch)
    assert vk.run(env={}, today=date(2026, 10, 26))["status"] == "키 대기"


def test_vkospi_found_and_missing(tmp_path, monkeypatch):
    _patch(tmp_path, monkeypatch)
    body = lambda items: {"response": {"body": {"items": {"item": items}}}}  # noqa: E731
    get = lambda p: body([{"idxNm": "코스피 200 선물지수", "clpr": "1", "fltRt": "0"}, {"idxNm": "KOSPI200 VKOSPI", "clpr": "21.5", "fltRt": "-1.2"}])  # noqa: E731
    st = vk.run(get=get, env={"DATA_GO_KR_KEY": "k"}, days=2, today=date(2026, 10, 26))
    assert st["status"] == "ok" and st["rows"] == 2 and st["last_close"] == 21.5
    _patch(tmp_path, monkeypatch)
    monkeypatch.setattr(vk, "CSV", tmp_path / "none.csv")
    st = vk.run(get=lambda p: body([{"idxNm": "코스피 200 선물지수"}]), env={"DATA_GO_KR_KEY": "k"}, days=1, today=date(2026, 10, 26))
    assert st["status"] == "소스에 없음" and st["idxNm_sample"]


def test_policy_display_range_and_basis():
    d = pr.display({"us": {"lower": {"value": 3.75}, "upper": {"value": 4.0, "date": "2026-10-26"}},
                    "kr": {"value": 3.0, "month": "2026-09"}})
    assert d["us"] == "3.75–4.00%" and "2026-10-26" in d["us_basis"]
    assert d["kr"] == "3.00%" and "월말 2026-09" in d["kr_basis"]
    assert pr.display({}) == {}


def test_vkospi_rejects_price_index_and_purges(tmp_path, monkeypatch):
    """10/27 오매칭 재발 방지: 이름에 '변동성'이 들어간 가격형 지수(값 ~800)는 VKOSPI 가 아니다."""
    _patch(tmp_path, monkeypatch)
    vk.CSV.parent.mkdir(parents=True, exist_ok=True)
    vk.CSV.write_text("date,close,chg_pct\n2026-10-19,803.45,3.60\n2026-10-20,21.00,0.10\n", encoding="utf-8")
    body = lambda items: {"response": {"body": {"items": {"item": items}}}}  # noqa: E731
    get = lambda p: body([{"idxNm": "코스피 200 변동성지수", "clpr": "787.27", "fltRt": "0.07"},  # noqa: E731
                          {"idxNm": "코스피200 변동성타겟 지수", "clpr": "30", "fltRt": "0"}])
    st = vk.run(get=get, env={"DATA_GO_KR_KEY": "k"}, days=1, today=date(2026, 10, 27))
    assert st["purged"]["n"] == 1 and st["rows"] == 1 and st["last_close"] == 21.0
    assert st["status"] == "소스에 없음" and any("787.27" in x for x in st["rejected"])
    assert "license" in st


def test_vkospi_ambiguous_not_loaded(tmp_path, monkeypatch):
    _patch(tmp_path, monkeypatch)
    monkeypatch.setattr(vk, "CSV", tmp_path / "none.csv")
    body = lambda items: {"response": {"body": {"items": {"item": items}}}}  # noqa: E731
    get = lambda p: body([{"idxNm": "VKOSPI", "clpr": "20"}, {"idxNm": "코스피200 변동성지수", "clpr": "21"}])  # noqa: E731
    st = vk.run(get=get, env={"DATA_GO_KR_KEY": "k"}, days=1, today=date(2026, 10, 27))
    assert st["status"] == "후보 여러 개" and st["rows"] == 0
