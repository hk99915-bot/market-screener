from datetime import date

from screener import fsc_close as f


def _js(items, total=None):
    return {"response": {"body": {"items": {"item": items}, "totalCount": total if total is not None else len(items)}}}


def test_compare_and_codes():
    fsc = f.fsc_closes([{"srtnCd": "A005930", "clpr": "70,000"}, {"srtnCd": "000660", "clpr": "200000"}, {"srtnCd": "BAD", "clpr": "1"}])
    assert fsc == {"005930": 70000.0, "000660": 200000.0}
    r = f.compare(fsc, {"005930": 70000.0, "000660": 199000.0, "035720": 5.0})
    assert (r["n_common"], r["n_match"], r["n_mismatch"]) == (2, 1, 1)


def test_run_no_key(tmp_path, monkeypatch):
    monkeypatch.setattr(f, "OUT", tmp_path / "o.json")
    assert f.run(env={})["status"] == "키 대기"


def test_run_with_fake_get(tmp_path, monkeypatch):
    monkeypatch.setattr(f, "OUT", tmp_path / "o.json")
    calls = []

    def get(p):
        calls.append(p["basDt"])
        return _js([{"srtnCd": "005930", "clpr": "70000"}]) if p["basDt"] == "20261026" else _js([])

    st = f.run(get=get, env={"DATA_GO_KR_KEY": "SECRETX9"}, days=2, today=date(2026, 10, 27), ours=lambda d: {"005930": 70000.0}, is_session=lambda d: d.weekday() < 5)
    assert st["status"].startswith("표본 부족") and st["match_rate_all"] == 1.0   # 공통 1종목 < 2,000 → 판정 보류
    assert "SECRETX9" not in (tmp_path / "o.json").read_text()


def test_single_A_prefix_only():
    assert f.fsc_closes([{"srtnCd": "AA00593", "clpr": "1"}, {"srtnCd": "AAB1234", "clpr": "2"}]) == {"A00593": 1.0, "AB1234": 2.0}


def test_mismatch_sorted_by_abs_diff():
    fsc = {"000001": 1000.0, "000002": 1000.0, "000003": 1000.0}
    r = f.compare(fsc, {"000001": 1010.0, "000002": 900.0, "000003": 1000.0})
    assert [m["code"] for m in r["mismatch"]] == ["000002", "000001"]


def test_retry_then_ok(tmp_path, monkeypatch):
    monkeypatch.setattr(f, "OUT", tmp_path / "o.json")
    n = {"c": 0}

    def get(p):
        n["c"] += 1
        if n["c"] == 1:
            raise TimeoutError("x")
        return _js([{"srtnCd": "005930", "clpr": "70000"}])

    st = f.run(get=get, env={"DATA_GO_KR_KEY": "K"}, days=1, today=date(2026, 10, 27), ours=lambda d: {"005930": 70000.0},
               sleep=lambda s: None, is_session=lambda d: True)
    assert st["days"][0]["status"].startswith("표본 부족") and n["c"] == 2


def test_holiday_skip_and_sample_rules(tmp_path, monkeypatch):
    monkeypatch.setattr(f, "OUT", tmp_path / "o.json")
    big = {f"{i:06d}": 1000.0 for i in range(2100)}
    seen = []

    def get(p):
        seen.append(p["basDt"])
        return _js([{"srtnCd": c, "clpr": str(v)} for c, v in big.items()], 2100)

    hol = {date(2026, 10, 26)}   # 공휴일 가정 → 조회·창 소진 없이 건너뜀
    st = f.run(get=get, env={"DATA_GO_KR_KEY": "K"}, days=5, today=date(2026, 10, 28), ours=lambda d: (dict(big), "kr_prices"),
               sleep=lambda s: None, is_session=lambda d: d.weekday() < 5 and d not in hol)
    assert "20261026" not in seen and len(seen) == 5
    assert st["status"] == "ok" and st["match_rate"] == 1.0 and st["verdict"] == "통과"


def test_partial_and_small_sample_excluded(tmp_path, monkeypatch):
    monkeypatch.setattr(f, "OUT", tmp_path / "o.json")
    sizes = {"20261027": 2100, "20261026": 2100, "20261023": 1500, "20261022": 2100}

    def get(p):
        n = sizes[p["basDt"]]
        return _js([{"srtnCd": f"{i:06d}", "clpr": "1000"} for i in range(n)], n)

    st = f.run(get=get, env={"DATA_GO_KR_KEY": "K"}, days=4, today=date(2026, 10, 28),
               ours=lambda d: {f"{i:06d}": 1000.0 for i in range(2100)}, sleep=lambda s: None, is_session=lambda d: d.weekday() < 5)
    stat = {x["date"]: x["status"] for x in st["days"]}
    assert stat["2026-10-23"].startswith("부분 적재")
    assert st["status"].startswith("표본 부족")   # 기준 충족 3일 < 5일 → 판정 보류
    assert "verdict" not in st
