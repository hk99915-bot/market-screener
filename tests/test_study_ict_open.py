import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import study_ict_open as S  # noqa: E402


def mk(o, h, l, c, dates=None):
    n = len(c)
    s = {"date": dates or [f"2025-01-{i + 1:02d}" for i in range(n)], "o": np.array(o, float), "h": np.array(h, float),
         "l": np.array(l, float), "c": np.array(c, float), "v": np.ones(n)}
    s["atr"] = np.full(n, 1.0)
    return s


def test_t_sf_known_values():
    assert abs(S.t_sf(0, 10) - 0.5) < 1e-6
    assert abs(S.t_sf(2.228, 10) - 0.025) < 1e-3
    assert abs(S.t_sf(-2.228, 10) - 0.975) < 1e-3


def test_simulate_stop_and_timeout():
    # 신호 t=0, 진입 t=1 시가 100, ATR 1 → 손절 98. 2일차 저가 97 → 손절 -1R (비용 0)
    s = mk([100, 100, 100, 100], [101, 101, 101, 101], [99, 99, 97, 99], [100, 100, 100, 100])
    r, j = S.simulate(s, 0, 1, 0.0)
    assert j == 2 and abs(r + 1.0) < 1e-9
    # 숏은 같은 봉에서 고가 101 < 손절 102 → 보유 만기까지 자료 부족이면 None
    assert S.simulate(s, 0, -1, 0.0) is None


def test_simulate_cost_in_R():
    n = S.HOLD + 2
    s = mk([100] * n, [100.5] * n, [99.5] * n, [100] * n)
    r, _ = S.simulate(s, 0, 1, 0.002)
    assert abs(r - (-0.002 * 100 / 2.0)) < 1e-9  # 비용 0.2% × 100 / 위험 2 = 0.1R


def test_daye_tuesday_sweep_long():
    # 2025-01-06 월, 01-07 화: 화요일 저가가 월 저가 하회 후 월 저가 위 마감 → 롱 신호(t=1)
    s = mk([10, 10], [11, 10.5], [9, 8.5], [10, 9.5], ["2025-01-06", "2025-01-07"])
    assert S.sig_daye(s) == [(1, 1)]
    s2 = mk([10, 10], [11, 11.5], [9, 8.5], [10, 9.5], ["2025-01-06", "2025-01-07"])  # 양쪽 스윕 → 제외
    assert S.sig_daye(s2) == []


def test_run_signals_no_overlap():
    n = 40
    s = mk([100] * n, [100.5] * n, [99.5] * n, [100] * n)
    out = S.run_signals(s, [(0, 1), (1, 1), (5, 1), (20, 1)], 0.0)
    assert [x[0] for x in out] == [0, 20]  # 보유(≤11일) 중 신호 2건 건너뜀
