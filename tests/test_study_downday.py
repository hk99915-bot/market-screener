"""study_downday 단위 검증 — 합성 데이터로 정의(이벤트·세 안 체결가·등급·BH) 확인."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import study_downday as sd  # noqa: E402


def test_grade_and_bh():
    a = {"n": 30, "mean": 0.01, "p_gt": 0.001, "p_lt": 0.999}
    ok = {"n": 10, "mean": 0.01, "p_gt": 0.05, "p_lt": 0.95}
    assert sd.grade(a, ok, ok, 0.0167) == "A"
    assert sd.grade(a, ok, {"n": 10, "mean": -0.01, "p_gt": 0.9, "p_lt": 0.1}, 0.0167) == "B"
    assert sd.grade({"n": 5, "mean": 1, "p_gt": 0, "p_lt": 1}, ok, ok, 0.0167) == "검증전"
    assert sd.grade({"n": 30, "mean": -0.01, "p_gt": 0.95, "p_lt": 0.04}, ok, ok, 0.0167) == "C(역방향)"
    assert sd.bh([0.001, 0.2, 0.04]) == [True, False, True]


def test_h4_three_exits_synthetic():
    # 코스피: 130일 평탄 → t(−3%) → t+1 −0.1% → t+2 +1% (반등일) → 이후 평탄
    n = 160
    idx = pd.bdate_range("2015-01-01", periods=n)
    k = np.full(n, 100.0)
    t = 130
    k[t] = 97.0
    k[t + 1] = 96.9
    k[t + 2] = 97.9
    k[t + 3:] = 97.9
    K = pd.Series(k, index=idx)
    # 종목: 평탄 100 → t 에서 75(−25%, 고점 대비 신규 진입) → t+2 80 → t+10 90
    c = np.full(n, 100.0)
    c[t] = 75.0
    c[t + 1] = 74.0
    c[t + 2] = 80.0
    c[t + 3:t + 10] = 82.0
    c[t + 10:] = 90.0
    C = pd.DataFrame({"X.KS": c}, index=idx)
    V = pd.DataFrame({"X.KS": np.full(n, 1e6)}, index=idx)
    ev = sd.h4_events(C, V, K)
    assert len(ev) == 1
    r = ev.iloc[0]
    assert abs(r["A"] - 1) < 1e-12
    assert abs(r["B"] - 80 / 75) < 1e-9 and r["wait"] == 2 and not r["same"]
    assert abs(r["C"] - 90 / 75) < 1e-9
    st = sd.h4_stats(ev)
    assert st["events"] == 1


def test_h1_events_gap_and_krw():
    idx = pd.bdate_range("2012-01-02", periods=60)
    spx = np.full(60, 100.0)
    spx[10] = 97.0   # −3%
    spx[12] = 94.0   # 같은 군집(20일 이내) → 제외
    spx[40] = 91.0   # 새 군집
    fx = np.full(60, 1000.0)
    fx[15:] = 1100.0
    df = pd.DataFrame({"spx": spx, "fx": fx}, index=idx)
    d, r, keep = sd.h1_events(df, -0.02)
    assert [d.index[i].date().isoformat() for i in keep][0] == idx[10].date().isoformat()
    assert len(keep) == 2
    assert abs(sd.krw_ret(d, 10, 5) - (spx[15] / spx[10] * 1.1 - 1)) < 1e-12
