"""cashflow_rebal 검산 — 드릴 allocation-d1(kb:allocation#7·#8 예) 숫자 재현."""
import importlib.util
from pathlib import Path

_p = Path(__file__).with_name("cashflow_rebal.py")
_s = importlib.util.spec_from_file_location("cashflow_rebal", _p)
cr = importlib.util.module_from_spec(_s)
_s.loader.exec_module(cr)


def test_drill_d1():
    r = cr.allocate({"주식": 60, "채권": 40}, {"주식": 70, "채권": 30}, 10)
    assert abs(r["short"]["주식"]) < 1e-9 and abs(r["short"]["채권"] - 14) < 1e-9
    assert abs(r["alloc"]["채권"] - 10) < 1e-9 and r["wait"] < 1e-9
    assert round(r["post"]["주식"] * 100, 1) == 63.6
    assert cr.band_flags(r["post"], r["tw"], 0.05) == {}
    assert "주식" in cr.band_flags(r["pre"], r["tw"], 0.05)


def test_alloc_sums_and_no_sell():
    r = cr.allocate({"A": 40, "B": 15, "C": 15, "D": 20, "E": 10}, {"A": 45, "B": 18, "C": 10, "D": 18, "E": 9}, 7)
    assert abs(sum(r["alloc"].values()) - 7) < 1e-9
    assert all(v >= 0 for v in r["alloc"].values())
    assert abs(sum(r["post"].values()) - 1) < 1e-9


def test_first_only_leaves_wait():
    r = cr.allocate({"S": 70, "D": 30}, {"S": 72, "D": 28}, 10, first=["D"])
    assert abs(r["alloc"]["D"] - 5) < 1e-9 and abs(r["wait"] - 5) < 1e-9 and r["alloc"]["S"] == 0


def test_default_target_loads():
    t, b = cr.default_target()
    assert abs(sum(t.values()) - 1) < 1e-9 and 0 < b < 0.2
