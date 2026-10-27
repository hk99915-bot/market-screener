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

    st = f.run(get=get, env={"DATA_GO_KR_KEY": "SECRETX9"}, days=2, today=date(2026, 10, 27), ours=lambda d: {"005930": 70000.0})
    assert st["status"] == "ok" and st["match_rate"] == 1.0
    assert "SECRETX9" not in (tmp_path / "o.json").read_text()
