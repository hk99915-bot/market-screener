"""변동성 타게팅 × GEX 국면(연구 2026-11-14) — 순수 계산 모듈·스터디 스크립트 회귀 (네트워크·저장소 데이터 불필요)."""
import importlib.util
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from screener import gex_vol_target as gv  # noqa: E402

spec = importlib.util.spec_from_file_location("sgvt", ROOT / "scripts" / "study_gex_vol_target.py")
sgvt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sgvt)


def test_vol_target_weight_clip_and_missing():
    w = gv.vol_target_weight(np.array([13.0, 26.0, 6.5, np.nan, 0.0]), target_vol=13.0, max_w=1.0)
    assert abs(w[0] - 1.0) < 1e-12          # 목표와 같으면 100%
    assert abs(w[1] - 0.5) < 1e-12          # 변동성 2배 → 절반
    assert abs(w[2] - 1.0) < 1e-12          # 낮은 변동성도 상한 1.0 (무레버리지)
    assert w[3] == 0.0 and w[4] == 0.0      # 결측·0 은 비중 0 (모르는 날은 시장 밖)
    up = gv.vol_target_weight(np.array([26.0]), target_vol=13.0, max_w=1.5)
    assert abs(up[0] - 0.5) < 1e-12         # max_w 는 상한만 올린다(비중은 target/RV 그대로)


def test_gex_regime_and_multiplier():
    assert gv.gex_regime(-100.0) == "short_gamma" and gv.gex_regime(100.0) == "long_gamma"
    assert gv.gex_regime(None) == "unknown" and gv.gex_regime(float("nan")) == "unknown"
    assert gv.gex_mult(-1.0) == 0.6 and gv.gex_mult(1.0) == 1.0 and gv.gex_mult(float("nan")) == 1.0
    assert gv.gex_mult(-1.0, scale=0.5) == 0.5


def test_target_weight_two_layers_and_invert():
    rv = np.array([26.0, 26.0, 26.0, np.nan])
    gex = np.array([-10.0, 10.0, np.nan, -10.0])
    w = gv.target_weight(rv, gex, target_vol=13.0, max_w=1.0, scale=0.6)
    assert abs(w[0] - 0.5 * 0.6) < 1e-12   # 숏감마 → 0.6배
    assert abs(w[1] - 0.5) < 1e-12         # 롱감마 → 그대로
    assert abs(w[2] - 0.5) < 1e-12         # gex 결측 → 규칙 미적용
    assert w[3] == 0.0
    inv = gv.target_weight(rv, gex, target_vol=13.0, max_w=1.0, scale=0.6, invert_gex=True)
    assert abs(inv[0] - 0.5) < 1e-12 and abs(inv[1] - 0.5 * 0.6) < 1e-12


def test_regime_flip_marks_sign_change_only():
    g = np.array([np.nan, -5.0, -7.0, 3.0, np.nan, 2.0, -1.0])
    f = gv.regime_flip(g)
    assert list(f) == [False, False, False, True, False, False, True]


def test_apply_band_skips_small_moves():
    assert gv.apply_band(0.65, 0.60, 0.10) == 0.60       # 5%p 차 → 무거래
    assert gv.apply_band(0.75, 0.60, 0.10) == 0.75       # 15%p 차 → 거래
    assert gv.apply_band(0.65, 0.60, 0.10, force=True) == 0.65
    assert gv.apply_band(float("nan"), 0.40, 0.10) == 0.40


def test_backtest_lag_costs_and_no_lookahead():
    r = np.array([0.10, 0.10, -0.10, -0.10])
    tgt = np.array([1.0, 1.0, 1.0, 1.0])
    bt = gv.backtest(r, tgt, cost_bp=0.0, band=0.0, lag=1)
    assert bt["ret"][0] == 0.0                   # 0일차는 아직 포지션이 없다(현금 0수익, 비용 0)
    assert abs(bt["ret"][1] - 0.10) < 1e-12       # 1일 수익 = 0일차 목표 비중
    assert bt["held"][1] == 1.0 and bt["held"][0] == 0.0
    # 비용: 첫 진입 |1−0| = 1회전 → 10bp
    c = gv.backtest(r, tgt, cost_bp=10.0, band=0.0, lag=1)
    assert abs(c["ret"][1] - (0.10 - 0.001)) < 1e-12
    assert abs(c["cost"][1] - 0.001) < 1e-12 and c["cost"][2] == 0.0     # 유지 중에는 비용 없음
    # 전방 누수 없음: 뒤쪽 수익률을 바꿔도 앞쪽 성과는 그대로
    r2 = r.copy()
    r2[3] = 0.5
    bt2 = gv.backtest(r2, tgt, cost_bp=0.0, band=0.0, lag=1)
    assert all(abs(x - y) < 1e-12 for x, y in zip(bt["ret"][:3], bt2["ret"][:3]))   # 끝의 두 칸만 달라진다
    assert abs(bt["ret"][3] - (-0.10)) < 1e-12 and abs(bt2["ret"][3] - 0.5) < 1e-12


def test_backtest_band_reduces_turnover():
    rng = np.random.default_rng(3)
    r = rng.normal(0, 0.01, 200)
    tgt = np.clip(0.7 + 0.05 * np.sin(np.arange(200) / 3.0), 0, 1)
    quiet = gv.backtest(r, tgt, band=0.0)
    band = gv.backtest(r, tgt, band=0.10)
    assert band["trade"].sum() < quiet["trade"].sum()
    assert quiet["trade"].sum() - band["trade"].sum() > 0.5


def test_expanding_mean_uses_prior_only():
    w = np.array([1.0, 0.5, 0.0, 0.5])
    out = gv.expanding_mean(w, min_obs=1)
    assert np.isnan(out[0])                       # 첫날은 과거가 없다
    assert abs(out[1] - 1.0) < 1e-12              # 1일차 = 0일차까지 평균
    assert abs(out[2] - 0.75) < 1e-12
    assert abs(out[3] - 0.5) < 1e-12


def test_perf_metrics_basics():
    flat = np.zeros(252)
    p = gv.perf_metrics(flat)
    assert p["cagr"] == 0.0 and p["mdd"] == 0.0 and p["vol"] == 0.0 and p["sharpe"] is None
    up = np.full(252, 0.001)
    p = gv.perf_metrics(up)
    assert abs(p["cagr"] - (1.001 ** 252 - 1)) < 1e-9 and p["mdd"] == 0.0
    down = np.array([0.1, -0.2, 0.05])
    p = gv.perf_metrics(down)
    assert p["mdd"] < -0.15


def test_block_bootstrap_identical_and_directional():
    rng = np.random.default_rng(11)
    a = rng.normal(0.0006, 0.008, 600)
    same = gv.block_bootstrap_sharpe_diff(a, a)
    assert abs(same["diff"]) < 1e-9 and same["p_one"] >= 0.95   # 같은 계열 → 차 0, p≈1
    b = rng.normal(-0.0006, 0.008, 600)
    pos = gv.block_bootstrap_sharpe_diff(a, b)
    assert pos["diff"] > 0 and pos["p_one"] < 0.05
    assert gv.block_bootstrap_sharpe_diff(a[:20], b[:20])["p_one"] is None   # 표본 부족은 None


def test_grade_rules_match_repo():
    assert sgvt.grade(0.001, {"is": 0.2, "oos": 0.1}, 3000, 1500)[0] == "A"
    assert sgvt.grade(0.001, {"is": 0.2, "oos": -0.1}, 3000, 1500)[0] == "B"
    assert sgvt.grade(0.05, {"is": 0.2, "oos": 0.1}, 3000, 1500)[0] == "C"
    assert sgvt.grade(0.5, {"is": 0.2, "oos": 0.1}, 3000, 1500)[0] == "F"
    assert sgvt.grade(0.001, {"is": 0.2, "oos": 0.1}, 3000, 200)[0] == "검증전"     # IS 표본 미달
    assert sgvt.grade(0.001, {"is": None, "oos": 0.1}, 300, 0)[0] == "검증전"       # IS 없는 검정(GEX 전용)


def _csv(tmp_path, n=2900, seed=5):
    rng = np.random.default_rng(seed)
    r = rng.normal(0.0003, 0.011, n)
    px = 300.0 * np.exp(np.cumsum(r))
    gex = np.full(n, np.nan)
    gex[n - 250:] = rng.normal(0, 500, 250)      # 마지막 250일만 GEX 가용(실제 데이터와 같은 모양)
    df = pd.DataFrame({"date": pd.bdate_range("2010-01-04", periods=n).strftime("%Y-%m-%d"),
                       "k200_close": px, "gex_bn": gex})
    p = tmp_path / "daily.csv"
    df.to_csv(p, index=False)
    return p


def test_script_run_on_fixture(tmp_path):
    out = sgvt.run(_csv(tmp_path))
    assert out["id"] == "gex_vol_target"
    assert out["prereg"]["m"] == 2 and out["prereg"]["alpha_bonf"] == 0.025
    assert out["prereg"]["target_vol"] == 13.0 and out["prereg"]["cost_bp_oneway"] == 10.0
    assert out["coverage"]["gex_days"] > 100 and out["coverage"]["oos_days"] > 100
    assert out["H1"]["grade"] in {"A", "B", "C", "F", "검증전"}
    assert out["H2"]["grade"] == "검증전"        # GEX 표본만으로는 IS 채점 불가(사전 규약)
    for k in ("vt_net", "vt_gross", "vt_yearly"):
        assert k in out["main"]
    for k in ("band_0", "weekly", "lag_2", "cost_15bp", "gex_scale_0.5"):
        assert k in out["exploratory"]
    m = out["main"]["vt_net"]
    assert 0.0 <= m["avg_w"] <= 1.0 + 1e-9       # 무레버리지
    assert m["cost_pct_yr"] >= 0.0
