"""study_profit_lock 시뮬레이터 구조 검사 — 합성 가격(저장본 불필요)."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from study_profit_lock import SEMIS, metrics, simulate  # noqa: E402


def _df(n=60):
    d = pd.bdate_range("2023-01-02", periods=n)
    up = np.cumprod(np.r_[1.0, np.full(n - 1, 1.02)])           # 반도체 매일 +2%
    k = np.cumprod(np.r_[1.0, np.where(np.arange(n - 1) % 2 == 0, 1.006, 0.996)])  # 이틀에 한 번 반등일
    df = pd.DataFrame({SEMIS[0]: 50000 * up, SEMIS[1]: 100000 * up, "k200_close": 300 * k,
                       "kospi_close": 2000 * k}, index=d)
    df["rebound"] = df["kospi_close"].pct_change().fillna(0) >= 0.005
    df["week_end"] = np.r_[(d[1:].isocalendar().week.values != d[:-1].isocalendar().week.values), True]
    df["month_end"] = np.r_[d[1:].month != d[:-1].month, True]
    return df


def test_bh_no_trades_and_weight_drifts_up():
    r = simulate(_df(), "BH")
    assert r["trades"] == [] and r["w"].iloc[-1] > 0.4


def test_rule_trims_only_on_rebound_days_to_cap():
    df = _df()
    r = simulate(df, "R", cap=0.25)
    assert r["trades"]
    for t in r["trades"]:
        assert df.loc[t["date"], "rebound"]
    assert r["w"].max() < 0.30          # 반등일 사이 하루치 상승만 넘침
    m = metrics(r)
    assert m["trims"] == len(r["trades"]) and m["mdd"] <= 0


def test_integer_shares_are_whole_and_coarse_size_trades_less():
    df = _df()
    small = simulate(df, "R", cap=0.25, size=20)
    big = simulate(df, "R", cap=0.25, size=1000)
    for t in small["trades"] + big["trades"]:
        assert all(isinstance(x, int) for x in t["shares"])
    assert len(small["trades"]) <= len(big["trades"])
