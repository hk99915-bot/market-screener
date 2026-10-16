"""screener.valuation_daily — 합성 SEC/DART 분기 프레임으로 PER·분해·결측 처리 검사 (네트워크 없음)."""
import math

import polars as pl
import pytest

from screener import valuation_daily as vd


def _q(n: int, ni: float = 100.0, rev: float = 1000.0, op: float = 150.0, eq: float = 2000.0, **extra) -> list[dict]:
    rows = []
    for i in range(n):
        rows.append({"period": f"2025Q{i % 4 + 1}", "revenue": rev * (1 + 0.1 * i), "op": op, "ni": ni, "cfo": ni * 1.2,
                     "capex": 20.0, "da": 30.0, "assets": 5000.0, "liab": 1000.0, "equity": eq, "cash": 1500.0, **extra})
    return rows


def test_per_pbr_ttm_basic():
    m = vd.metrics(_q(8), shares=100.0, price=80.0)
    assert m["verified"] and m["n_quarters"] == 8
    assert m["eps_ttm"] == pytest.approx(4.0)          # 4분기 × 100 / 100주
    assert m["per"] == pytest.approx(20.0)
    assert m["bps"] == pytest.approx(20.0) and m["pbr"] == pytest.approx(4.0)
    assert m["roe"] == pytest.approx(400 / 2000)
    assert m["earn_yield"] == pytest.approx(0.05)
    assert m["rev_yoy"] == pytest.approx(1000 * 1.7 / (1000 * 1.3) - 1)
    assert m["ocf_ni"] == pytest.approx(1.2)
    assert m["net_cash_proxy_ratio"] == pytest.approx((1500 - 1000) / 8000)
    assert m["ev_ebitda"] == pytest.approx((8000 + 1000 - 1500) / (600 + 120))
    assert m["flags"] == []


def test_ni_owner_preferred_over_ni():
    m = vd.metrics(_q(4, ni_owner=50.0), shares=100.0, price=10.0)
    assert m["eps_ttm"] == pytest.approx(2.0)          # 지배주주 순이익 50×4/100


def test_short_history_is_unverified_and_annualized():
    m = vd.metrics(_q(2), shares=100.0, price=80.0)
    assert not m["verified"]
    assert m["eps_ttm"] == pytest.approx(4.0)          # 2분기 × 2 연환산
    assert any("검증전" in f for f in m["flags"])
    assert m["rev_yoy"] is None                        # 5분기 미만이면 YoY 없음


def test_missing_data_handled():
    m = vd.metrics([], shares=None, price=None)
    assert m["n_quarters"] == 0 and not m["verified"] and "재무 데이터 없음" in m["flags"]
    q = _q(4)
    for r in q:
        r["revenue"] = None
        r["da"] = None
    m = vd.metrics(q, shares=100.0, price=80.0)
    assert m["per"] == pytest.approx(20.0)
    assert m["rev_yoy"] is None and m["ev_ebitda"] is None
    assert m["op_margin_4q"] == [None] * 4
    assert any("매출" in f for f in m["flags"]) and any("EV/EBITDA" in f for f in m["flags"])
    m = vd.metrics(_q(4), shares=None, price=80.0)      # 주식 수 없음 → 주당 지표 없음, 예외 없음
    assert m["per"] is None and m["pbr"] is None and m["roe"] is not None


def test_loss_gives_no_per():
    m = vd.metrics(_q(4, ni=-10.0), shares=100.0, price=80.0)
    assert m["loss"] and m["per"] is None and m["earn_yield"] is None
    assert any("적자" in f for f in m["flags"])


def test_decomposition_adds_up():
    d = vd.decompose(price_now=120.0, price_prev=100.0, eps_now=6.0, eps_prev=5.0)
    assert d["d_price"] == pytest.approx(math.log(1.2))
    assert d["d_eps"] == pytest.approx(math.log(1.2))
    assert d["d_multiple"] == pytest.approx(0.0, abs=1e-12)   # PER 20 → 20: 전부 EPS
    d = vd.decompose(110.0, 100.0, 5.0, 5.0)
    assert d["d_multiple"] == pytest.approx(d["d_price"]) and d["d_eps"] == 0
    assert d["d_price"] == pytest.approx(d["d_multiple"] + d["d_eps"])


def test_decomposition_missing():
    assert vd.decompose(None, 100.0, 5.0, 5.0)["d_price"] is None
    d = vd.decompose(110.0, 100.0, -1.0, 5.0)
    assert d["d_price"] is not None and d["d_multiple"] is None and "적자" in d["note"]


def test_rate_sensitivity_formula():
    s = vd.rate_sensitivity(20.0, bp=25)
    # E/P 5% → 5.25% : PER 19.05 → −4.76%
    assert s["up"] == pytest.approx(1 / 0.0525 / 20 - 1)
    assert s["down"] == pytest.approx(1 / 0.0475 / 20 - 1)
    assert vd.rate_sensitivity(None)["up"] is None
    assert "ERP" in s["formula"]


def test_us_quarters_from_synthetic_sec_parquet(tmp_path, monkeypatch):
    """SEC long 형식 → 분기 dict, 결측 항목은 열 자체가 없어도 처리."""
    rows = []
    for i, end in enumerate(["2025-03-31", "2025-06-30", "2025-09-30", "2025-12-31", "2026-03-31"]):
        rows += [{"ticker": "ZZZ", "end": end, "item": "ni", "value": 100.0 + i},
                 {"ticker": "ZZZ", "end": end, "item": "op", "value": 150.0},
                 {"ticker": "ZZZ", "end": end, "item": "equity", "value": 2000.0}]
    rows.append({"ticker": "ZZZ", "end": "2025-12-31", "item": "shares", "value": 100.0})
    p = tmp_path / "us.parquet"
    pl.DataFrame(rows).write_parquet(p)
    from screener import sec
    monkeypatch.setattr(sec, "OUT", p)
    q, sh = vd.us_quarters("ZZZ")
    assert sh == 100.0 and len(q) == 5 and q[-1]["period"] == "2026Q1"
    m = vd.metrics(q, sh, price=50.0)
    assert m["verified"] and m["per"] == pytest.approx(50 / ((101 + 102 + 103 + 104) / 100))
    assert m["rev_yoy"] is None                         # revenue 열 없음
    assert vd.us_quarters("NONE") == ([], None)


def test_markdown_and_telegram_shape():
    o = {"asof": "2026-10-16", "generated_at": "x", "grade": "참고(검증전) — 매매 트리거 아님", "unit": "비율만",
         "rates": {"us10y": 5.1, "us10y_w1_bp": -12, "kr3y": 3.85, "kr3y_w1_bp": -13},
         "basket": {"n": 2, "n_verified": 1, "n_priced": 2, "median_per": 20.0, "median_pbr": 3.0,
                    "cheapest": [{"name": "A", "rate_adj": 0.02}], "richest": [{"name": "B", "rate_adj": -0.03}],
                    "decomp20": {"d_price": -0.03, "d_multiple": -0.05, "d_eps": 0.02, "n": 1, "basis": "t"},
                    "rate_sens": vd.rate_sensitivity(20.0)},
         "rows": [{"name": "A", "sym": "A", "mk": "KR", "verified": True, "per": 10.0, "pbr": 1.0, "rate_adj": 0.02, "n_quarters": 4,
                   "op_margin_4q": [0.1, 0.2], "rev_yoy": 0.1, "ocf_ni": 1.1, "decomp20": {}},
                  {"name": "B", "sym": "B", "mk": "US", "verified": False, "per": None, "pbr": None, "rate_adj": None, "n_quarters": 0,
                   "op_margin_4q": [], "decomp20": {}}],
         "etfs": [], "events": {"window_days": 14, "next": [{"date": "2026-10-28", "name": "FOMC"}], "tripwires": [{"date": "2026-10-29", "name": "삼성전자 실적", "note": ""}]}}
    md = vd.markdown(o)
    assert "| 종목 | PER/PBR | 이익추세 | 금리조정 매력 |" in md and "⚠검증전" in md and "재무 없음" in md
    tg = vd.telegram_text(o)
    assert len(tg.split("\n")) <= 8 and "매매 트리거 아님" in tg and "원" not in tg


def test_cumulative_smell_marks_unverified():
    q = _q(8)
    for i, v in enumerate([5.24, 13.785, 28.243, 60.0]):   # 매 분기 1.8배↑ 단조 증가 — 누적치 전형
        q[4 + i]["ni"] = v
    m = vd.metrics(q, shares=100.0, price=80.0)
    assert not m["verified"] and any("누적치 의심" in f for f in m["flags"])
    assert vd.cumulative_smell(_q(8)) is None
    assert vd.cumulative_smell(q[-4:]) == "ni"
