"""합성 데이터: semis_cap 재현 시뮬레이터의 CAP40M·BAND 동작과 Newey-West 확인."""
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import replicate_semis_cap as rs  # noqa: E402


def _dates(n):
    d, out = date(2015, 1, 1), []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def test_cap_and_band_trigger():
    n = 60
    dates = _dates(n)
    rsx = [0.0] + [0.02] * (n - 1)      # 반도체만 매일 +2% → 비중 상승
    rr = [0.0] * n
    reb = [True] * n                     # 매일 반등일
    bear = [False] * n
    bh = rs.simulate("BH", 0, n - 1, dates, rsx, rr, bear, reb)
    cap = rs.simulate("CAP40M", 0, n - 1, dates, rsx, rr, bear, reb)
    band = rs.simulate("BAND", 0, n - 1, dates, rsx, rr, bear, reb)
    assert bh["sells"] == 0 and bh["w_max"] > 0.6
    assert cap["sells"] >= 2 and cap["w_max"] < bh["w_max"]
    assert band["sells"] >= 1 and band["buys"] == 0
    assert cap["ret"] < bh["ret"]


def test_newey_west_constant_shift():
    r = rs.nw_test([0.01, 0.02] * 30)
    assert abs(r["mean"] - 0.015) < 1e-12 and r["p"] < 0.001
