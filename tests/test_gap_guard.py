"""야간선물 갭 가드(가설 ②) — 순수 계산 모듈·연구 스크립트 회귀 (네트워크·저장소 데이터 불필요)."""
import importlib.util
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from screener import gap_guard as gg  # noqa: E402

spec = importlib.util.spec_from_file_location("sng", ROOT / "scripts" / "study_night_gap_guard.py")
sng = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sng)


def test_gap_math():
    assert abs(gg.night_gap(101.0, 100.0) - 0.01) < 1e-12
    assert math.isnan(gg.night_gap(None, 100.0))
    assert math.isnan(gg.night_gap(0.0, 100.0))
    assert abs(gg.open_gap(99.0, 100.0) + 0.01) < 1e-12
    assert abs(gg.divergence(0.002, 0.012) + 0.010) < 1e-12
    assert math.isnan(gg.divergence(None, 0.01))


def test_guard_back_giveback_holds_chase():
    """야간 +1.5% 상승을 시초가 +0.2%로 반납 → 보류(back)."""
    g = gg.guard(0.015, 0.002)
    assert g["hold"] is True and g["kind"] == "back" and g["div"] == pytest.approx(-0.013)


def test_guard_confirmed_gap_allows():
    g = gg.guard(0.015, 0.014)
    assert g["hold"] is False and g["kind"] == "none"


def test_guard_open_overshoot_holds():
    """야간은 +0.1% 인데 시초가 +2.0% 갭업 → 시초 오버슈트로 보류(over)."""
    g = gg.guard(0.001, 0.021)
    assert g["hold"] is True and g["kind"] == "over"


def test_guard_early_flow_divergence():
    g = gg.guard(0.012, 0.013, early_flow=-1.0)     # 갭은 확인됐지만 초반 수급이 순매도
    assert g["hold"] is True and g["kind"] == "flow"


def test_guard_missing_inputs():
    g = gg.guard(float("nan"), 0.01)
    assert g["hold"] is False and "결측" in g["reason"]


def test_give_back_and_open_to_close():
    assert gg.give_back(95.0, 100.0) is True
    assert gg.give_back(101.0, 100.0) is False
    assert gg.give_back(None, 100.0) is None
    assert gg.open_to_close(99.0, 100.0) == pytest.approx(-0.01)
    assert math.isnan(gg.open_to_close(0.0, 100.0))


def test_fisher_exact_and_rates():
    a = [1] * 7 + [0] * 3
    b = [1] * 1 + [0] * 9
    r = gg.fisher_two_by_two(a, b)
    assert r["rate_a"] == pytest.approx(0.7) and r["rate_b"] == pytest.approx(0.1)
    assert r["p"] < 0.02 and r["table"] == [[7, 3], [1, 9]]
    same = gg.fisher_two_by_two(a, a)
    assert same["p"] == pytest.approx(1.0)


def _csv(tmp_path, n=120, seed=5):
    """야간 세션 n−1일 — 앞 60일은 '시초 확인'(시초 +1.2%·당일 +2%), 뒤는 '시초 반납'(시초 0%·당일 −1%)."""
    dc = np.where(np.arange(n) < 60, 0.020, -0.010)
    px = np.empty(n)
    px[0] = 300.0
    for i in range(1, n):                                 # 종가 수준 — 당일 수익률을 dc 로 고정
        px[i] = px[i - 1] * (1 + dc[i])
    prev = np.concatenate([[px[0]], px[:-1]])              # 전일 종가
    ng = np.full(n, 0.010)
    og = np.where(np.arange(n) < 60, 0.012, 0.000)
    df = pd.DataFrame({"date": pd.bdate_range("2026-01-01", periods=n).strftime("%Y-%m-%d"),
                       "night_vwap": prev * (1 + ng), "night_vol": 10000.0,
                       "fut_open": prev * (1 + og), "fut_close": px,
                       "kospi_open": prev * 5.5 * (1 + og), "kospi_close": px * 5.5})
    p = tmp_path / "daily.csv"
    df.to_csv(p, index=False)
    return p


def test_build_table_and_test_planted(tmp_path):
    df = pd.read_csv(_csv(tmp_path), parse_dates=["date"])
    d = sng.build_table(df)
    assert len(d) == len(df) - 1                       # 첫날(전일 없음)만 빠진다
    base = d[d["night_up"]]
    assert len(base) == len(df) - 1                    # 야간 갭은 전부 +1.0%
    hold = base[base["hold"]]
    go = base[~base["hold"]]
    assert len(hold) > 30 and len(go) > 20
    assert hold["give_back"].mean() > 0.95             # 반납 구간은 종가가 전일 아래
    assert go["give_back"].mean() < 0.05
    res = sng.test(d)
    assert res["give_back_hold"] > res["give_back_go"] and res["fisher_p"] < 0.01
    assert res["o2c_hold"] < res["o2c_go"]             # 시초→종가도 반납 구간이 낮게 심었다


def test_script_run_on_fixture(tmp_path):
    out = sng.run(_csv(tmp_path))
    assert out["id"] == "night_gap_guard" and out["prereg"]["m"] == 2
    assert out["grades"]["H1"] in {"A", "B", "C", "F", "검증전"}
    assert out["prereg"]["instruments"]
    assert isinstance(out["cases"], list)
    assert len(out["limits"]) >= 3
