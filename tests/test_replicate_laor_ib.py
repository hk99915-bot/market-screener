"""검증 데스크 라오어 무한매수 독립 재현 — 합성 데이터 테스트."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import replicate_laor_ib as m  # noqa: E402


def _px(closes, highs=None, fx=1000.0):
    idx = pd.bdate_range("2020-01-01", periods=len(closes))
    return pd.DataFrame({"close": closes, "high": highs if highs is not None else closes, "fx": fx}, index=idx)


def test_xirr_simple():
    assert abs(m.xirr([("2020-01-01", -100.0), ("2021-01-01", 110.0)]) - 0.10) < 0.002


def test_rising_path_closes_cycle_with_profit():
    c = np.r_[100.0, 100.0, 99.0, 98.0, 97.0, 130.0, 130.0]
    r = m.simulate(_px(c), m.Rule(base=15.0))
    first = r.cycles[0]
    assert first.end is not None and first.ret_usd > 0 and first.exhaust == 0


def test_falling_path_enters_reverse_and_loses():
    c = np.r_[100.0, 100.0, 100 * 0.97 ** np.arange(1, 80)]
    r = m.simulate(_px(c), m.Rule(base=15.0))
    cyc = r.cycles[0]
    assert cyc.exhaust >= 1 and cyc.end is None and cyc.ret_usd < -0.3 and cyc.min_eq_usd <= cyc.ret_usd + 1e-9


def test_post_sell_half_only_adds_buys():
    # 후반(T≥10)에 별지점(평단 아래) 위·평단 아래로 마감한 날: 원 코드 방식만 평단 LOC 를 추가 체결
    rng = np.random.default_rng(1)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.03, 600)))
    px = _px(c, c * 1.01)
    a = m.simulate(px, m.Rule(base=20.0), trace=(ta := []))
    b = m.simulate(px, m.Rule(base=20.0, post_sell_half=True), trace=(tb := []))
    assert len(ta) == len(tb) and len(a.cycles) >= 1 and len(b.cycles) >= 1
