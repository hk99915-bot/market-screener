"""us_spikes_intraday 체결 규칙 단위 테스트 — 미래정보 금지·스탑 우선·갭 체결 (사전등록 §0-3)."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import study_us_spikes_intraday as m  # noqa: E402


def sess(rows, start="2026-10-01 09:30"):
    ts = pd.date_range(start, periods=len(rows), freq="5min")
    df = pd.DataFrame(rows, columns=["o", "h", "l", "c", "v"])
    df["ts"] = ts
    return m.Sess(df)


def test_entry_is_next_bar_open_and_eod_exit():
    S = sess([(10, 11, 9, 10.5, 100), (10.6, 12, 10.4, 11.8, 100), (11.9, 12.5, 11.5, 12.0, 100)])
    t = m.simulate(S, 0, "L", None, None, None)
    assert t["entry"] == 10.6 and t["why"] == "eod" and t["exit"] == 12.0


def test_same_bar_tp_and_stop_takes_stop():
    S = sess([(10, 10, 10, 10, 100), (10, 10, 10, 10, 100), (10, 12, 9, 10, 100)])
    t = m.simulate(S, 0, "L", None, 0.10, 0.05)
    assert t["why"] == "stop"
    assert np.isclose(t["exit"], 9.5 * (1 - m.STOP_SLIP))


def test_stop_gap_fills_at_open_not_stop():
    S = sess([(10, 10, 10, 10, 100), (10, 10.2, 9.9, 10, 100), (8, 8.5, 7.5, 8, 100)])
    t = m.simulate(S, 0, "L", 9.5, None, None)
    assert t["why"] == "stop" and np.isclose(t["exit"], 8 * (1 - m.STOP_SLIP))


def test_tp_needs_trade_through():
    S = sess([(10, 10, 10, 10, 100), (10, 11.0, 9.9, 10.5, 100), (10.5, 11.02, 10.4, 10.6, 100)])
    t = m.simulate(S, 0, "L", None, 0.10, None)
    assert t["why"] == "eod"  # 11.02 < 11×1.0025=11.0275
    S2 = sess([(10, 10, 10, 10, 100), (10, 10.2, 9.9, 10.1, 100), (10.1, 11.1, 10.0, 10.6, 100)])
    assert m.simulate(S2, 0, "L", None, 0.10, None)["why"] == "tp"


def test_short_stop_and_sign():
    S = sess([(10, 10, 10, 10, 100), (10, 10.1, 9.0, 9.2, 100), (9.2, 9.3, 8.0, 8.0, 100)])
    t = m.simulate(S, 0, "S", 11.0, None, None)
    assert t["why"] == "eod" and np.isclose(t["gross"], 0.2)


def test_orb5_signal_uses_close_and_or_low_stop():
    S = sess([(10, 11, 9.5, 10.5, 100), (10.5, 11.5, 10.4, 10.9, 100), (10.9, 11.6, 10.8, 11.2, 100),
              (11.2, 11.3, 11.0, 11.1, 100)])
    i, stop, side = m.signal(S, "ORB5", 0)
    assert i == 2 and stop == 9.5 and side == "L"  # 봉1 고가 11.5 는 돌파지만 종가 10.9 ≤ 11 → 봉2에서 신호


def test_signal_respects_trigger_index():
    S = sess([(10, 13, 10, 12.9, 100), (12.9, 13, 10, 10.5, 100), (10.5, 11, 10, 10.6, 100), (10.6, 10.7, 10, 10.1, 100)])
    assert m.signal(S, "FADE", 0)[0] == 1
    assert m.signal(S, "FADE", 2)[0] == 2


def test_cost_model():
    assert np.isclose(m.rt_cost("L"), 0.022) and np.isclose(m.rt_cost("S"), 0.027)
