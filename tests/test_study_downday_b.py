"""scripts/study_downday_b.py — 순수 함수 검증(합성 데이터, 저장소 밖 자료 불필요)."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import study_downday_b as sd  # noqa: E402


def test_cluster_chain_gap20():
    assert sd.cluster([5, 10, 30, 60, 90]) == [5, 60, 90]  # 5→10→30 은 직전 후보 20일 이내 연쇄로 한 군집, 60·90 은 각각 30 거리라 새 군집
    assert sd.cluster([5, 10, 25, 40]) == [5]  # 연쇄: 각 후보가 직전 후보와 15일 이내
    assert sd.cluster([]) == []


def test_cluster_exact_boundary():
    assert sd.cluster([0, 20]) == [0]      # 20일 이내 = 같은 군집
    assert sd.cluster([0, 21]) == [0, 21]  # 21일은 새 군집


def test_bh_flags():
    ok = sd.bh_flags([0.001, 0.009, 0.04, 0.5], q=0.10)
    assert ok == [True, True, True, False]
    assert sd.bh_flags([0.9, 0.8], q=0.10) == [False, False]


def test_nw_mean_one_sided():
    r = sd.nw_mean(np.full(30, 0.01) + np.linspace(-0.001, 0.001, 30), 2)
    assert r["p_gt"] < 0.001 and r["p_lt"] > 0.99
    neg = sd.nw_mean(-np.abs(np.random.default_rng(0).normal(0.01, 0.002, 40)), 3)
    assert neg["mean"] < 0 and neg["p_gt"] > 0.9


def test_month_arms_constant_price_no_difference():
    P = np.ones((10, 5)) * 100.0
    w = np.array(list(sd.WEIGHTS.values()))
    dvb, dvc, pb, pc, wait, opp = sd.month_arms(P, w, 0, 4, 9)
    assert dvb == 0 and dvc == 0 and pb == 0 and pc == 0 and wait == 4


def test_month_arms_waiting_into_rising_market_costs():
    P = np.vstack([np.full(5, 100.0), np.full(5, 100.0), np.full(5, 110.0), np.full(5, 121.0)])
    w = np.array(list(sd.WEIGHTS.values()))
    dvb, dvc, pb, pc, wait, opp = sd.month_arms(P, w, 0, 2, 3)  # B 는 110 에 삼 → 단가 +10%
    assert abs(pb - 0.10) < 1e-9
    assert dvb < 0 and dvc < 0 and abs(dvc - dvb / 2) < 1e-9  # C = 절반이라 손실도 절반
    assert 0 < pc < pb
    assert abs(dvb - (1 / 1.10 - 1) * 1.21) < 1e-9  # 1/110 단위 × 121 − 1/100 × 121 (무게합 1)


def test_month_arms_waiting_into_fall_gains():
    P = np.vstack([np.full(5, 100.0), np.full(5, 90.0), np.full(5, 100.0)])
    w = np.array(list(sd.WEIGHTS.values()))
    dvb, dvc, pb, pc, wait, opp = sd.month_arms(P, w, 0, 1, 2)
    assert pb < 0 and dvb > 0 and dvc > 0


def test_trigger_flags_sp_maps_to_next_kr_day_and_kospi_same_day():
    cal = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"])
    r_k = np.array([np.nan, -0.02, 0.0, 0.0])
    g = pd.Series([0.0, -0.02, 0.0], index=pd.to_datetime(["2024-01-02", "2024-01-04", "2024-01-05"]))
    f_either = sd.trigger_flags(cal, r_k, g, 0.015, "either")
    assert f_either.tolist() == [False, True, False, True]  # KOSPI 1/3 당일 · S&P 1/4(미국) → KR 1/5
    assert sd.trigger_flags(cal, r_k, g, 0.015, "kospi").tolist() == [False, True, False, False]
    assert sd.trigger_flags(cal, r_k, g, 0.015, "sp").tolist() == [False, False, False, True]


def test_month_blocks_starts_after_2010_11_and_splits_months():
    cal = pd.to_datetime(["2010-10-29", "2010-11-01", "2010-11-30", "2010-12-01", "2010-12-30"])
    assert sd.month_blocks(cal) == [(1, 2), (3, 4)]


def test_cell_stats_robust_flip_downgrades():
    rows = [(i, 0.0, 0.01, "2013-01-01") for i in range(10)] + [(99, 0.0, 0.5, "2020-03-01")]
    cs = sd.cell_stats(rows, 0.05 / 18)
    assert cs["net_excess"]["n"] == 11 and "grade" in cs
    rows2 = [(i, 0.0, -0.01, "2013-01-01") for i in range(10)] + [(99, 0.0, 0.5, "2020-03-01")]
    cs2 = sd.cell_stats(rows2, 0.05 / 18)
    assert cs2["grade"] in ("F", "C(역방향)", "C", "검증전", "B")


def test_cap_explore():
    assert sd.cap_explore("A") == "C(탐색상한)" and sd.cap_explore("F") == "F"
