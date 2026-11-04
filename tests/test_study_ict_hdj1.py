"""study_ict_hdj1 — 신호·체결 로직 합성 데이터 검사."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import study_ict_hdj1 as s  # noqa: E402


def mk(o, h, l, c):
    df = pd.DataFrame(dict(date=pd.bdate_range("2020-01-01", periods=len(o)), open=o, high=h, low=l, close=c))
    return s.prep(df)


def test_turtle_soup_long_and_trade_stop():
    n = 40
    o = np.full(n, 100.0); h = o + 1; l = o - 1; c = o.copy()
    l[10] = 90.0  # 20일 저가 형성(≥4봉 전)
    l[30] = 89.0; c[30] = 91.0  # 90 하회 후 복귀 → 롱 신호(t=30)
    P = mk(o, h, l, c)
    assert (30, 1) in s.sig_R1(P)
    x = s.trade(P, 30, 1, 0.0)
    assert x and x[0] == 31


def test_trade_gap_through_stop_fills_at_open():
    n = 30
    o = np.full(n, 100.0); h = o + 1; l = o - 1; c = o.copy()
    P = mk(o, h, l, c)
    P["o"][22] = 80.0  # 보유 중 갭다운 — 롱 손절(100−2×ATR≈96)을 시가가 넘음 → 시가 체결
    x = s.trade(P, 20, 1, 0.0)
    assert x[1] == 22 and x[2] < -1.0


def test_crt_requires_close_inside_range():
    o = np.array([10, 10, 10.0]); h = np.array([12, 12, 11.5]); l = np.array([8, 8, 7.0]); c = np.array([10, 10, 9.0])
    P = mk(o, h, l, c)
    assert s.crt_dir(P, 2) == 1  # 전일 저가 8 하회 후 종가 9 는 범위 안
    c2 = c.copy(); c2[2] = 7.5
    assert s.crt_dir(mk(o, h, l, c2), 2) == 0


def test_cisd_run_level():
    o = np.array([10, 9, 8, 7, 6.0]); c = np.array([9, 8, 7, 6, 10.0])  # 4연속 음봉 후 종가 10 > 첫 봉 시가 10? 엄격 초과 아님
    P = mk(o, o + 1, o - 1, c)
    assert (4, 1) not in s.sig_R6(P)
    c[4] = 10.5
    assert (4, 1) in s.sig_R6(mk(o, o + 1, o - 1, c))
