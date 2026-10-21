"""scripts/study_laor_ib.py — 무한매수 규칙 엔진이 규칙표(별%·쿼터·소진)대로 움직이는지 손으로 푼 경로로 확인."""
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd

spec = importlib.util.spec_from_file_location("study_laor_ib", Path(__file__).resolve().parent.parent / "scripts/study_laor_ib.py")
lib = importlib.util.module_from_spec(spec)
sys.modules["study_laor_ib"] = lib   # dataclass 가 모듈 이름으로 자기 모듈을 찾는다
spec.loader.exec_module(lib)


def _path(closes, highs=None, fx=1000.0):
    idx = pd.bdate_range("2020-01-01", periods=len(closes))
    c = np.asarray(closes, float)
    h = c if highs is None else np.asarray(highs, float)
    return pd.DataFrame({"close": c, "high": h, "fx": fx, "is_syn": False}, index=idx)


def test_star_pct_table():
    assert lib.star_pct(lib.RULES["V4.0_20"], 15, 4) == 15 - 1.5 * 4      # TQQQ 20분할
    assert lib.star_pct(lib.RULES["V4.0_40"], 15, 4) == 15 - 0.75 * 4     # TQQQ 40분할
    assert lib.star_pct(lib.RULES["V4.0_20"], 20, 4) == 20 - 2 * 4        # SOXL 20분할
    assert lib.star_pct(lib.RULES["V4.0_40"], 20, 4) == 20 - 4            # SOXL 40분할
    assert lib.star_pct(lib.RULES["V2.2_40"], 15, 4) == 10 - 4 / 2        # V2.2
    assert lib.star_pct(lib.RULES["V4.0_20"], 15, 10) == 0                # 반환점 T=N/2 에서 별% 0


def test_quarter_sell_cuts_T_by_quarter():
    p = lib.Pos(cash=0.5, seed=1.0, qty=10.0, avg=1.0, T=4.0)
    # 별% = 15−6 = 9% → 별지점 1.09. 종가 1.10 ≥ 1.09 → 쿼터 LOC 체결, 고가 1.10 < 목표 1.15 → 지정가 미체결
    lib.step(p, lib.RULES["V4.0_20"], 15.0, 1.0, 1.10, 1.10, 1.0, 0.0)
    assert abs(p.qty - 7.5) < 1e-9 and abs(p.T - 3.0) < 1e-9
    assert abs(p.cash - (0.5 + 2.5 * 1.10)) < 1e-9


def test_target_limit_fills_at_order_price_and_ends_cycle():
    p = lib.Pos(cash=0.5, seed=1.0, qty=10.0, avg=1.0, T=4.0)
    res = lib.step(p, lib.RULES["V4.0_20"], 15.0, 1.0, 1.12, 1.20, 1.0, 0.0)   # 고가 1.20 ≥ 1.15, 종가 1.12 ≥ 1.09
    assert res == "end" and p.qty == 0
    assert abs(p.cash - (0.5 + 7.5 * 1.15 + 2.5 * 1.12)) < 1e-9


def test_front_half_two_loc_buys():
    p = lib.Pos(cash=0.9, seed=1.0, qty=0.1, avg=1.0, T=1.0)
    lib.step(p, lib.RULES["V4.0_20"], 15.0, 1.0, 0.99, 0.99, 1.0, 0.0)   # 종가 ≤ 평단 → 평단·별 둘 다 체결
    unit = 0.9 / 19
    assert abs(p.T - 2.0) < 1e-9 and abs(p.cash - (0.9 - unit)) < 1e-9


def test_rising_market_cycles_profit_no_exhaust():
    path = _path(100 * 1.01 ** np.arange(400), 100 * 1.01 ** np.arange(400) * 1.005)
    for rn in lib.RULES:
        res = lib.run_strategy(path, "TQQQ", rn)
        assert len(res["cycles"]) >= 3
        assert all(c["ret"] > 0 for c in res["cycles"])
        assert sum(c["rev"] + c["qstop"] for c in res["cycles"]) == 0


def test_falling_market_triggers_exhaust_modes():
    path = _path(100 * 0.99 ** np.arange(120))
    r4 = lib.run_strategy(path, "TQQQ", "V4.0_20")
    r3 = lib.run_strategy(path, "TQQQ", "V3.0_20")
    assert r4["open"]["rev"] >= 1 and r4["open"]["qstop"] == 0       # V4.0: 리버스모드
    assert r3["open"]["qstop"] >= 1 and r3["open"]["rev"] == 0       # V3.0: 쿼터손절
    assert r4["open"]["ret"] < 0 and r4["open"]["rev_pnl"] < 0


def test_flat_market_compound_only_costs():
    path = _path(np.full(60, 100.0))
    out = lib.compound(path, "TQQQ", "V4.0_20")
    assert -0.01 < out["min_vs_start"] <= 0 and out["mult_usd"] <= 1.0


def test_xirr_one_year_10pct():
    d = np.array(["2021-01-01", "2022-01-01"], dtype="datetime64[D]")
    assert abs(lib.xirr(d, np.array([-1.0, 1.1])) - 0.1) < 2e-3
