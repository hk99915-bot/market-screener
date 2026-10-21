"""scripts/study_qld_dca.py — XIRR·적립 계산이 손으로 푼 값과 맞는지."""
import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

spec = importlib.util.spec_from_file_location("sq", Path(__file__).resolve().parent.parent / "scripts/study_qld_dca.py")
sq = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sq)


def test_xirr_one_year_10pct():
    d = np.array(["2020-01-01", "2021-01-01"], dtype="datetime64[D]")
    r = sq.xirr(d, np.array([-100.0, 110.0]))
    assert abs(r - 0.1) < 2e-3   # 366일(윤년)/365.25 → ≈0.0997


def _rets(r: float, n: int = 300, fx: float = 1000.0) -> pd.DataFrame:
    idx = pd.bdate_range("2020-01-01", periods=n)
    return pd.DataFrame({"QLD": r, "QQQ": r, "SPY": r, "fx": fx, "qld_is_syn": False,
                         "qqq_is_syn": False, "spy_is_syn": False}, index=idx)


def test_dca_flat_market_loses_only_costs():
    out = sq.dca(_rets(0.0), "QQQ", "2020-01-01")
    a = sq.ASSUME
    cost = (1 - a["fee_buy"]) * (1 - a["fee_sell"]) / (1 + a["fx_spread"]) ** 2
    assert out["paid"] == 300 * a["daily_krw"]
    assert abs(out["moic"] - cost) < 1e-3
    assert out["underwater_max_yrs"] > 1.0          # 비용만큼 늘 원금 아래
    assert out["irr"] < 0


def test_whole_shares_holds_cash_until_one_share():
    # 1주 1000달러, 하루 1만원/1000원 ≈ 9.9달러 → 약 100일에 1주
    out = sq.dca(_rets(0.0), "QQQ", "2020-01-01", whole_shares=1000.0)
    frac = sq.dca(_rets(0.0), "QQQ", "2020-01-01")
    assert abs(out["moic"] - frac["moic"]) < 0.01    # 시장 0%면 현금 보유도 손익 같음(수수료만 차이)


def test_lump_beats_dca_in_rising_market():
    r = _rets(0.001)
    d = sq.dca(r, "QQQ", "2020-01-01")
    lp = sq.lump(r, "QQQ", "2020-01-01", None, d["paid"])
    assert lp["moic"] > d["moic"]
