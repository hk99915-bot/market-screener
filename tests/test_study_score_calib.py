"""score-calib 1단계 연구 스크립트 — 구간 경계·등급 규칙·NW t (사전등록 reports/studies/2026-11-12_score_calib.md §0)."""
import importlib.util
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("ssc", ROOT / "scripts" / "study_score_calib.py")
ssc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ssc)


def test_bin_edges():
    d = pl.DataFrame({"trend_score": [0.0, 19.9, 20.0, 59.9, 60.0, 79.9, 80.0, 100.0]})
    b = d.select(ssc.bin_expr("trend_score"))["b_trend_score"].to_list()
    assert b == [1, 1, 2, 3, 4, 4, 5, 5]


def test_nw_t_matches_simple_when_lag0():
    x = np.array([0.01, -0.02, 0.03, 0.00, 0.015, -0.005])
    mu, t = ssc.nw_t(x, lag=0)
    t_simple = mu / (np.std(x, ddof=0) / np.sqrt(len(x)))
    assert abs(t - t_simple) < 1e-9


def _r(mean_oos, p_oos, mean_is, p_is=0.5, m22=0.0, n=72):
    return {"oos": {"n_months": n, "mean": mean_oos, "p": p_oos, "p_rev": 1 - p_oos},
            "is": {"n_months": 108, "mean": mean_is, "p": p_is}, "y2022": {"n_months": 12, "mean": m22}}


def test_grade_rules():
    a = ssc.ALPHA
    assert ssc.grade(_r(0.01, a / 2, 0.01, a / 2, 0.01), 1, "KR") == "A"
    assert ssc.grade(_r(0.01, a / 2, 0.01, a / 2, 0.01), 1, "US") == "B"     # US 상한 B(생존편향)
    assert ssc.grade(_r(0.01, a / 2, -0.01), 1, "KR") == "C"                  # IS 반대 → B 불가
    assert ssc.grade(_r(-0.01, a / 2, -0.01, a / 2, -0.01), -1, "KR") == "A"  # Reversal: 음수가 가설 방향
    assert ssc.grade(_r(-0.01, 0.99, 0.0), 1, "KR") == "C(역방향)"
    assert ssc.grade(_r(0.01, 0.2, 0.01), 1, "KR") == "F"
    assert ssc.grade(_r(0.01, a / 2, 0.01, n=20), 1, "KR") == "검증전"
