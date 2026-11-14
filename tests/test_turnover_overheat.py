"""거래대금 과열 페널티(가설 ①) — 순수 계산 모듈·연구 스크립트 회귀 (네트워크·저장소 데이터 불필요)."""
import importlib.util
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from screener import turnover_filter as tf  # noqa: E402

spec = importlib.util.spec_from_file_location("sto", ROOT / "scripts" / "study_turnover_overheat.py")
sto = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sto)


def test_rolling_and_prior_mean_alignment():
    x = np.arange(1.0, 11.0)                     # 1..10
    assert np.isnan(tf.rolling_mean(x, 3)[1])
    assert tf.rolling_mean(x, 3)[2] == 2.0       # (1+2+3)/3
    assert tf.rolling_mean(x, 3)[-1] == 9.0      # (8+9+10)/3
    # prior_mean(3, skip=1)[5] = x[2..4] 평균 = 3,4,5 → 4
    pm = tf.prior_mean(x, 3, 1)
    assert np.isnan(pm[2]) and pm[5] == 4.0
    # 창 안에 결측이 있으면 NaN
    y = x.copy(); y[8] = np.nan
    assert np.isnan(tf.rolling_mean(y, 3)[9])


def test_intensity_is_ratio_of_recent_to_prior():
    tv = np.array([100.0] * 25 + [300.0] * 5)     # 25일 평소 + 5일 3배
    r = tf.intensity(tv, 5, 20)
    # t=29: 최근 5일 평균 300 / 직전 20일(t−24~t−5, 모두 100) = 3.0
    assert abs(r[29] - 3.0) < 1e-9
    assert np.isnan(r[23]) and r[24] == 1.0       # t=24 부터 직전 20일 기준선이 생긴다


def test_intensity_has_no_lookahead():
    """미래 값을 바꿔도 과거 시점의 과열 배수는 그대로여야 한다(전방 누수 없음)."""
    rng = np.random.default_rng(11)
    tv = 1e9 * np.exp(rng.normal(0, 0.3, 80))
    a = tf.intensity(tv, 5, 20)
    tv2 = tv.copy(); tv2[60:] *= 10
    b = tf.intensity(tv2, 5, 20)
    assert np.allclose(a[:60], b[:60], equal_nan=True) and not np.allclose(a[60:], b[60:])


def test_split_adjustment_removes_jump():
    close = np.array([100_000.0, 100_500, 101_000, 101_000 / 50, 101_500 / 50, 102_000 / 50])
    open_ = np.array([100_000.0, 100_400, 100_900, 101_000 / 50, 101_400 / 50, 101_900 / 50])
    vol = np.array([10.0, 11, 12, 13, 14, 15])
    adj = tf.adjust_series(open_, open_, open_, close, vol)
    assert adj["events"] == 1
    assert not tf.bad_days(adj["open"], adj["close"]).any()      # 조정 뒤에는 오류일이 아니다
    assert tf.bad_days(open_, close)[3]                          # 조정 전에는 −98% 점프 = 오류일
    assert adj["close"][0] < close[0]                            # 과거 가격은 분할비만큼 내려간다
    assert adj["volume"][0] > vol[0]                             # 가격 배수의 역수로 거래량은 커진다(50:1 → ×50)


def test_split_factor_direction():
    fac, idx = tf.split_factors(np.array([1000.0, 1000.0, 50.0]), np.array([1000.0, 1000.0, 50.0]))
    assert list(idx) == [2] and abs(fac[0] - 0.05) < 1e-12 and fac[2] == 1.0


def test_classify_groups():
    lab = tf.classify(np.array([2.5, 1.5, 1.0, 1.2, 2.0, np.nan]))
    assert list(lab) == [1, 0, -1, -1, 1, 9]


def test_forward_open_return_entry_and_bounds():
    o = np.array([100.0, 110.0, 120.0, 130.0, 140.0])
    c = np.array([105.0, 115.0, 125.0, 135.0, 145.0])
    f = tf.forward_open_return(o, c, 2)
    assert abs(f[0] - (125.0 / 110.0 - 1)) < 1e-12      # t+1 시가 진입 → t+2 종가
    assert np.isnan(f[3]) and np.isnan(f[4])            # 창이 모자란 끝은 NaN
    assert abs(f[1] - (135.0 / 120.0 - 1)) < 1e-12


def test_month_cluster_t():
    dates = [f"2015-{m:02d}-10" for m in range(1, 13)] * 3
    days = sorted(dates)
    d = np.array([0.01] * len(days))
    r = tf.month_cluster(d, np.array(days))
    assert r["n_months"] == 12 and r["mean"] > 0 and r["p_one"] is not None
    # 부호가 반대면 단측 p 가 커진다
    assert tf.month_cluster(-d, np.array(days))["p_one"] > 0.5


def test_welch_and_grade_rules():
    a = np.array([0.01, 0.02, 0.03, 0.04, 0.05])
    b = np.array([-0.03, -0.02, -0.01, 0.0, 0.01])
    w = tf.welch(a, b)
    assert w["n_a"] == 5 and w["diff"] > 0 and w["p_one"] < 0.05
    assert tf.welch(a[:2], b)["p_one"] is None
    assert tf.grade(0.001, {"is": 0.01, "oos": 0.01}, 100, 60)[0] == "A"
    assert tf.grade(0.001, {"is": 0.01, "oos": -0.01}, 100, 60)[0] == "B"
    assert tf.grade(0.05, {"is": 0.01, "oos": 0.01}, 100, 60)[0] == "C"
    assert tf.grade(0.5, {"is": 0.01, "oos": 0.01}, 100, 60)[0] == "F"
    assert tf.grade(0.001, {"is": 0.01, "oos": 0.01}, 10, 6)[0] == "검증전"


def _synth(quiet_better: bool = True, n_dates: int = 600, seed: int = 5) -> pd.DataFrame:
    """날짜별로 과열/조용 두 그룹을 만들어 비교 함수를 검사한다."""
    rng = np.random.default_rng(seed)
    rows = []
    days = pd.bdate_range("2015-01-02", periods=n_dates)
    for i, d in enumerate(days):
        for lab, ratio in (("hot", 3.0), ("quiet", 1.0)):
            for _ in range(4):
                base = rng.normal(0, 0.03)
                edge = (0.01 if lab == "quiet" else 0.0) if quiet_better else (0.0 if lab == "quiet" else 0.01)
                f5 = base + edge
                rows.append({"day": int(d.toordinal()), "date": d.strftime("%Y-%m-%d"),
                             "r5": 0.15, "r20": 0.25, "ratio": ratio, "ratio1": ratio,
                             "f5": f5, "f10": f5 * 1.5, "exc5": f5, "exc10": f5 * 1.5})
    return pd.DataFrame(rows)


def test_compare_detects_direction_and_schema():
    up = sto.compare(_synth(True), 5, hot=2.0, quiet=1.2, r5_min=0.10)
    assert up["n_hot"] > 0 and up["n_quiet"] > 0
    assert up["quiet"]["exc_mean"] > up["hot"]["exc_mean"]
    assert up["month"]["p_one"] < 0.05
    down = sto.compare(_synth(False), 5, hot=2.0, quiet=1.2, r5_min=0.10)
    assert down["month"]["p_one"] > 0.5
    s = sto.summarize("t", up)
    assert s["grade"] in {"A", "B", "C", "F", "검증전"} and s["n"] == up["n_events"]
    # 강세 문턱을 올리면 사건이 줄고, 중간 그룹은 대조에서 빠진다
    assert sto.compare(_synth(True), 5, hot=2.0, quiet=1.2, r5_min=0.20)["n_events"] == 0


def test_exploratory_grade_capped():
    s = sto.summarize("x", sto.compare(_synth(True), 5, hot=2.0, quiet=1.2, r5_min=0.10), cap="C")
    assert s["grade"] == "C" and "상한 C" in s["why"]


def test_future_bad_window_flags():
    bad = np.array([False, False, False, True, False, False, False])
    got = sto._future_any(bad, 2)
    assert list(got) == [False, True, True, True, False, False, False]   # t~t+2 안에 오류일이 있는가
