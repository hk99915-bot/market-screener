import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

spec = importlib.util.spec_from_file_location("sr", Path(__file__).resolve().parent.parent / "scripts/study_us_r20_reversal.py")
sr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sr)


def test_p_one_sign():
    assert sr.p_one(2.0, +1) < 0.03 and sr.p_one(2.0, -1) > 0.97


def test_group_series_reversal_planted():
    """20일 하락 종목이 다음 4일 오르도록 심으면 그룹 A 초과수익 > 0, 구조(비중첩 날짜)도 확인."""
    rng = np.random.default_rng(0)
    idx = pd.bdate_range("2015-01-01", periods=400)
    px = pd.DataFrame(100 * np.cumprod(1 + rng.normal(0, 0.01, (400, 30)), axis=0), index=idx, columns=[f"S{i}" for i in range(30)])
    g = sr.group_series(px)
    assert len(g["A"]) > 20 and g["nA"] > 0 and g["nB"] > 0
    assert (np.diff(g["A"].index.values.astype("datetime64[D]").astype(int)) >= 4).all()
    s = sr.summarize(pd.Series([0.01, 0.02, 0.015, 0.012, 0.018]), +1)
    assert s["mean"] > 0 and s["p_one"] < 0.01 and s["win"] == 1.0
