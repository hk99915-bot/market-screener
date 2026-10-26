"""컨센 결측 → 전분기 대용·표기 (req-analyst-16fe6a15) — 네트워크 없이."""
from screener import earnings_cal as E


def test_fill_proxy_marks_basis():
    rows = [{"sym": "AAA", "eps_avg": 1.2}, {"sym": "BBB", "eps_avg": None}, {"sym": "CCC", "eps_avg": None}]
    px = {"BBB": {"eps": 0.55, "period": "2026Q2"}}
    n = E.fill_proxy(rows, proxy=lambda s: px.get(s))
    a, b, c = rows
    assert n == 1
    assert a["eps_basis"] == E.BASIS_CONS and "eps_proxy" not in a
    assert b["eps_basis"] == E.BASIS_PROXY and b["eps_proxy"] == 0.55 and b["eps_proxy_period"] == "2026Q2"
    assert c["eps_basis"] == E.BASIS_NONE and "eps_proxy" not in c


def test_build_counts_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(E, "OUT", tmp_path / "earnings_cal.json")
    fake = {"AAA": {"sym": "AAA", "date": "2099-01-01", "eps_avg": 1.0, "eps_n": 3, "rev_avg": None, "err": None},
            "BBB": {"sym": "BBB", "date": "2099-01-02", "eps_avg": None, "eps_n": None, "rev_avg": None, "err": "EPS 컨센 없음"}}
    o = E.build(["AAA", "BBB"], fetch=lambda t: dict(fake[t]), proxy=lambda s: {"eps": 0.3, "period": "2026Q3"})
    assert o["n_cons_missing"] == 1 and o["n_proxy"] == 1
    assert {r["sym"]: r["eps_basis"] for r in o["rows"]} == {"AAA": E.BASIS_CONS, "BBB": E.BASIS_PROXY}
