import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

spec = importlib.util.spec_from_file_location("sl", Path(__file__).resolve().parent.parent / "scripts/study_us_long_sort.py")
sl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sl)


def _rows(spec):
    return {s: {"s": s, "drv": d, "r20": r, "r1": 0.0} for s, d, r in spec}


def test_pick_rules_split_by_price():
    rows = _rows([("UP", 0.9, 0.05), ("DN", 0.9, -0.10), ("WEAK", 0.2, -0.10), ("FLAT", 0.5, -0.01)])
    assert sl.pick(rows, "c") == ["DN"]           # 현행: drv≥0.4 & r20≤−3%
    assert sl.pick(rows, "a") == ["UP"]           # 가격 확인: drv≥0.4 & r20>0
    prev = _rows([("UP", 0.9, 0), ("DN", 0.7, 0), ("WEAK", 0.1, 0), ("FLAT", 0.5, 0)])
    assert sl.pick(rows, "b", prev) == ["DN", "WEAK"]   # Δdrv>0 큰 순 (DN +0.2 > WEAK +0.1)
    assert sl.pick(rows, "b", None) == []


def test_diff_series_planted_momentum():
    """20일 상승 종목이 계속 오르도록 심으면 (a)−(c) 차 > 0, 날짜는 h일 간격 비중첩."""
    rng = np.random.default_rng(1)
    n, k = 600, 40
    drift = np.where(np.arange(k) < k // 2, 0.002, -0.002)
    r = rng.normal(0, 0.01, (n, k)) + drift
    px = pd.DataFrame(100 * np.cumprod(1 + r, axis=0), index=pd.bdate_range("2015-01-01", periods=n), columns=[f"S{i}" for i in range(k)])
    s = sl.diff_series(px, 5)
    assert len(s) > 50 and s.mean() > 0
    assert (np.diff(s.index.values.astype("datetime64[D]").astype(int)) >= 5).all()


def test_grade_labels():
    assert sl.grade({"p_one": 0.01}, {"mean": 0.1}, {"mean": 0.1}) == "B"
    assert sl.grade({"p_one": 0.01}, {"mean": 0.1}, {"mean": -0.1}).startswith("B(")
    assert sl.grade({"p_one": 0.07}, {}, {}) == "C"
    assert sl.grade({"p_one": 0.95}, {}, {}) == "C(역방향)"
    assert sl.grade({"p_one": 0.5}, {}, {}) == "F"
