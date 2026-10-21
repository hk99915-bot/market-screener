"""replicate_us_spikes — 합성 창으로 롱·숏·손절·쿨다운·NW 검정 산식 확인 (검증 데스크)."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import replicate_us_spikes as R  # noqa: E402


def _win(closes, opens=None, highs=None, d0="2020-01-02", yf="AAA", dates=None):
    """k=-1..20 한 창을 wide 형태 1행으로."""
    row = {"yf": yf, "d0": d0, "vol20": 100.0, "n_hist": 100}
    for i, k in enumerate(R.K):
        c = closes[i]
        o = opens[i] if opens else c
        h = highs[i] if highs else max(o, c)
        row.update({f"close_{k}": c, f"open_{k}": o, f"high_{k}": h, f"low_{k}": min(o, c),
                    f"volume_{k}": 1000.0 if k == 0 else 100.0, f"raw_f_{k}": 1.0,
                    f"date_{k}": (dates[i] if dates else f"2020-02-{i + 1:02d}")})
    return row


def test_long_and_short_basic():
    closes = [10, 15] + [12] * 20            # C−1 10, C0 15 (+50%), 이후 12
    w = pd.DataFrame([_win(closes)])
    assert abs(R.long_ret(w, 1).iloc[0] - (12 / 15 - 1 - 0.01)) < 1e-12
    s = R.short_ret(w, 5, b=1.0).iloc[0]
    assert abs(s - (0.0 - 0.01 - 5 / 252)) < 1e-12       # 시가 12 → 종가 12


def test_short_loss_can_exceed_100pct():
    closes = [10, 15, 12, 20, 30, 40, 48] + [48] * 15
    w = pd.DataFrame([_win(closes)])
    s = R.short_ret(w, 5, b=0.0, cost=0.0).iloc[0]
    assert abs(s - (-(48 / 12 - 1))) < 1e-12              # −300%
    capped = R.short_ret(w, 5, b=0.0, cost=0.0, cap_loss=-1.0).iloc[0]
    assert capped == -1.0


def test_stop_intraday_and_gap():
    closes = [10, 15, 12, 12, 12, 12, 12] + [12] * 15
    highs = [10, 15, 12, 16, 12, 12, 12] + [12] * 15       # D+2 고가 16 ≥ 12×1.3=15.6 → 15.6 환매
    w = pd.DataFrame([_win(closes, highs=highs)])
    s = R.short_ret(w, 5, b=0.0, cost=0.0, stop=0.3).iloc[0]
    assert abs(s - (-(15.6 / 12 - 1))) < 1e-12
    opens = [10, 15, 12, 20, 12, 12, 12] + [12] * 15       # D+2 시가 20 갭 → 시가 환매
    w2 = pd.DataFrame([_win(closes, opens=opens, highs=[max(a, b) for a, b in zip(opens, highs)])])
    s2 = R.short_ret(w2, 5, b=0.0, cost=0.0, stop=0.3).iloc[0]
    assert abs(s2 - (-(20 / 12 - 1))) < 1e-12


def test_cooldown_blocks_events_inside_window():
    dates = [f"2020-03-{i + 1:02d}" for i in range(22)]
    a = _win([10, 15] + [12] * 20, d0=dates[1], dates=dates)
    b = _win([10, 15] + [12] * 20, d0=dates[10], dates=[f"2020-04-{i + 1:02d}" for i in range(22)])
    w = pd.DataFrame([a, b])
    keep = R.cooldown(w, 20)
    assert keep.tolist() == [True, False]


def test_nw_positive_series():
    rng = np.random.default_rng(0)
    d0 = pd.Series(pd.date_range("2015-01-01", periods=600, freq="7D").strftime("%Y-%m-%d"))
    x = pd.Series(0.05 + rng.normal(0, 0.1, 600))
    t = R.nw_test(x, d0)
    assert t["t"] > 5 and t["p"] < 1e-6
