"""VRP 반등 필터(가설 ①) — 순수 계산 모듈·연구 스크립트 회귀 (네트워크·저장소 데이터 불필요)."""
import importlib.util
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from screener import vrp_filter as vf  # noqa: E402

spec = importlib.util.spec_from_file_location("svf", ROOT / "scripts" / "study_vrp_rebound_filter.py")
svf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(svf)


def test_realized_vol_constant_and_known():
    flat = 100 * np.exp(0.002 * np.arange(60))       # 일간 로그수익률 일정 → 변동성 ≈ 0
    rv = vf.realized_vol(flat, window=20)
    assert np.isnan(rv[19]) and abs(rv[-1]) < 1e-6
    rng = np.random.default_rng(7)
    r = rng.normal(0, 0.01, 200)
    px = 100 * np.exp(np.cumsum(r))
    rv = vf.realized_vol(px, window=20)
    manual = np.std(np.diff(np.log(px))[179:199], ddof=1) * math.sqrt(252) * 100
    assert abs(rv[-1] - manual) < 1e-9


def test_vrp_signs_and_regime():
    assert vf.vrp_variance(20.0, 15.0) > 0          # IV > RV → 공포 과잉
    assert vf.vrp_variance(15.0, 25.0) < 0          # 실현 폭발
    assert vf.vrp_volatility(20.0, 15.0) == 5.0
    assert vf.regime(0.01) == "fear_excess"
    assert vf.regime(-0.01) == "realized_breakout"
    assert vf.regime(0.0001, band=0.001) == "neutral"
    assert vf.regime(None) == "unknown"


def test_rebound_gate_both_sides():
    ok = vf.rebound_gate(40.0, 25.0)
    assert ok["ok"] is True and ok["regime"] == "fear_excess" and "분산" in ok["reason"]
    hold = vf.rebound_gate(20.0, 45.0)
    assert hold["ok"] is False and hold["regime"] == "realized_breakout"
    vol = vf.rebound_gate(40.0, 25.0, mode="volatility")
    assert vol["ok"] is True and abs(vol["vrp"] - 15.0) < 1e-9
    assert vf.rebound_gate(None, 20.0)["regime"] == "unknown"
    assert vf.rebound_gate(float("nan"), 20.0)["regime"] == "unknown"


def test_event_mask_no_lookahead():
    """−6% 고점 대비 조정 + 당일 반등만 사건 — 사건일 i 는 i 이하 정보로만 정해져야 한다."""
    px = np.array([100.0] * 25 + [94.0, 95.0, 96.0])
    m = vf.event_mask(px, drop=None, dd_max=-0.05, rebound_day=True)
    assert not m[24]                        # 아직 낙폭 −0% (고점 100)
    assert not m[25]                        # 급락일(당일 −6%)은 상승 조건 미충족
    assert m[26]                            # 전일 −6% 조정 + 당일 +1.06% 상승
    # 미래를 바꾸면 과거 사건 표시가 달라지지 않는다(전방 누수 없음)
    px2 = px.copy()
    px2[27] = 40.0
    m2 = vf.event_mask(px2, drop=None, dd_max=-0.05, rebound_day=True)
    assert list(m[:27]) == list(m2[:27])


def test_forward_return_alignment():
    px = np.array([100.0, 110.0, 121.0, 133.1])
    f = vf.forward_return(px, 2)
    assert abs(f[0] - 0.21) < 1e-9 and abs(f[1] - 0.21) < 1e-9 and np.isnan(f[-1])


def test_welch_and_group_stats():
    a = np.array([0.01, 0.02, 0.03, 0.04, 0.05])
    b = np.array([-0.03, -0.02, -0.01, 0.0, 0.01])
    w = vf.welch(a, b)
    assert w["n_a"] == 5 and w["diff"] > 0 and w["p_one"] < 0.05
    assert vf.welch(a[:2], b)["p_one"] is None        # 표본 부족은 None
    g = vf.group_stats(a)
    assert g["n"] == 5 and g["win"] == 1.0 and g["false_rate"] == 0.0
    assert vf.group_stats(np.array([]))["n"] == 0


def test_p_one_sided_direction():
    assert vf.p_one_sided(2.0, +1) < 0.03 < vf.p_one_sided(2.0, -1)


def test_grade_rules_match_repo():
    assert svf.grade(0.001, {"is": 0.01, "oos": 0.01}, 50)[0] == "A"
    assert svf.grade(0.001, {"is": 0.01, "oos": -0.01}, 50)[0] == "B"
    assert svf.grade(0.05, {"is": 0.01, "oos": 0.01}, 50)[0] == "C"
    assert svf.grade(0.5, {"is": 0.01, "oos": 0.01}, 50)[0] == "F"
    assert svf.grade(0.001, {"is": 0.01, "oos": 0.01}, 5)[0] == "검증전"


def _csv(tmp_path, n=400, seed=3):
    rng = np.random.default_rng(seed)
    r = rng.normal(0.0004, 0.012, n)
    px = 2000 * np.exp(np.cumsum(r))
    iv = 18.0 + 25.0 * np.abs(rng.normal(0, 1, n))      # IV 는 대략 18~45%
    df = pd.DataFrame({"date": pd.bdate_range("2015-01-01", periods=n).strftime("%Y-%m-%d"),
                       "kospi_close": px, "rep_iv": iv,
                       "fut_close": px * 0.155, "fut_open": px * 0.155,
                       "kospi_open": px, "night_vwap": px * 0.155})
    p = tmp_path / "daily.csv"
    df.to_csv(p, index=False)
    return p


def test_script_run_on_fixture(tmp_path):
    out = svf.run(_csv(tmp_path))
    assert out["prereg"]["m"] == 2 and out["prereg"]["alpha_bonf"] == 0.025
    assert out["id"] == "vrp_rebound_filter"
    assert set(out["grades"]) == {"H1", "H2"}
    assert out["main"]["grade"] in {"A", "B", "C", "F", "검증전"}
    assert "tie_band_0.002" in out["exploratory"]
    assert out["main"]["n"] == out["main"]["n_pos"] + out["main"]["n_nonpos"]
