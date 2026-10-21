"""replicate_qld_dca — 합성 데이터로 적립·IRR·MDD 산식 확인 (검증 데스크)."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import replicate_qld_dca as R  # noqa: E402

NOCOST = dict(R.A, fx_spread=0.0, fee_buy=0.0, fee_sell=0.0)


def test_flat_price_irr_zero_and_no_loss():
    idx = pd.bdate_range("2020-01-01", periods=300)
    px, fx = pd.Series(100.0, index=idx), pd.Series(1300.0, index=idx)
    s = R.simulate(px, fx, idx[0], idx[-1], a=NOCOST)
    assert s["days"] == 300
    assert abs(s["irr"]) < 1e-6
    assert abs(s["loss_vs_paid_min"]) < 1e-9


def test_growing_price_irr_matches_growth():
    idx = pd.bdate_range("2020-01-01", "2022-12-31")
    t = (idx - idx[0]).days.values / 365.0
    px = pd.Series(100 * 1.10 ** t, index=idx)
    fx = pd.Series(1000.0, index=idx)
    s = R.simulate(px, fx, idx[0], idx[-1], a=NOCOST)
    assert abs(s["irr"] - 0.10) < 1e-3


def test_costs_lower_final():
    idx = pd.bdate_range("2020-01-01", periods=50)
    px, fx = pd.Series(100.0, index=idx), pd.Series(1300.0, index=idx)
    s = R.simulate(px, fx, idx[0], idx[-1])
    expect = (1 - 0.001) / (1 + 0.0025) * (1 - 0.0025) * (1 - 0.001)   # 매수(환전·수수료) → 매도(환전·수수료)
    assert abs(s["moic"] - expect) < 1e-9


def test_asset_mdd_dates():
    idx = pd.bdate_range("2020-01-01", periods=6)
    lv = pd.Series([1.0, 2.0, 1.0, 0.5, 1.5, 2.5], index=idx)
    m = R.asset_mdd(lv)
    assert abs(m["mdd"] + 0.75) < 1e-12
    assert m["peak"] == str(idx[1].date()) and m["trough"] == str(idx[3].date()) and m["recovered"] == str(idx[5].date())


def test_compare_flags():
    rep = {"real": {k: {"irr": v, "loss_vs_paid_min": -0.568} for k, v in
                    {"QLD": 0.309, "QQQ": 0.198, "SPY": 0.15}.items()},
           "mdd_krw": {"QLD": {"mdd": -0.986}},
           "y10": {"QLD": {y: (-0.01 if y in R.ORIG["neg_years_QLD"] else 0.1) for y in range(1986, 2017)},
                   "QQQ": {y: (-0.01 if y in (1997, 1999) else 0.1) for y in range(1986, 2017)},
                   "SPY": {y: (-0.01 if y == 1999 else 0.1) for y in range(1986, 2017)}}}
    assert all(r["ok"] for r in R.compare(rep))
    rep["y10"]["QLD"][1995] = 0.001
    assert not all(r["ok"] for r in R.compare(rep))
