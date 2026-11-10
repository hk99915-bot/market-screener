"""scripts/study_var_models.py — 검정·필터·MLE 단위 테스트 (연구 카드 req-quant-67015597). 데이터 파일 없이 돈다."""
import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import study_var_models as s  # noqa: E402


def _sim_gjr(n=3000, seed=1, om=0.02, al=0.03, ga=0.12, be=0.88):
    rng = np.random.default_rng(seed)
    r, s2 = np.zeros(n), 1.0
    for t in range(n):
        r[t] = math.sqrt(s2) * rng.standard_normal()
        s2 = om + (al + ga * (r[t] < 0)) * r[t] ** 2 + be * s2
    return r


def test_kupiec_exact_and_reject():
    lr, p = s.kupiec(10, 1000, 0.01)
    assert lr == pytest.approx(0, abs=1e-9) and p == pytest.approx(1.0)
    assert s.kupiec(30, 1000, 0.01)[1] < 0.001
    assert s.kupiec(0, 250, 0.01)[1] < 0.05   # 0회도 과대 의심


def test_christoffersen_cluster_vs_spread():
    spread = np.zeros(1000, int); spread[::100] = 1
    clus = np.zeros(1000, int); clus[100:110] = 1
    assert math.isnan(s.christoffersen(spread)[1]) or s.christoffersen(spread)[1] > 0.05
    assert s.christoffersen(clus)[1] < 0.001


def test_tick_loss_and_dm():
    L = np.array([0.03, 0.01]); v = np.array([0.02, 0.02])
    assert s.tick_loss(L, v) == pytest.approx([0.01 * 0.99, 0.01 * 0.01])
    rng = np.random.default_rng(0)
    m, t, p = s.dm_test(rng.standard_normal(2000) + 0.2)
    assert m > 0 and p < 0.001
    assert s.dm_test(rng.standard_normal(2000))[2] > 0.01


def test_garch_filter_matches_loop():
    r = _sim_gjr(200)
    out = s.garch_filter(r, 0.02, 0.03, 0.12, 0.88, 1.5)
    s2 = 1.5
    for t in range(200):
        assert out[t] == pytest.approx(s2)
        s2 = 0.02 + (0.03 + 0.12 * (r[t] < 0)) * r[t] ** 2 + 0.88 * s2
    assert out[200] == pytest.approx(s2)


def test_fit_recovers_gjr_params():
    th, ok = s.fit_garch(_sim_gjr(), gjr=True)
    assert ok and th[3] == pytest.approx(0.12, abs=0.05) and th[2] == pytest.approx(0.88, abs=0.04)


def test_fit_matches_arch_if_installed():
    arch = pytest.importorskip("arch")
    r = _sim_gjr()
    th, _ = s.fit_garch(r, gjr=True)
    ref = arch.arch_model(r, mean="Zero", vol="GARCH", p=1, o=1, q=1, rescale=False).fit(disp="off").params.values   # ω α γ β
    assert th[1] == pytest.approx(ref[1], abs=0.01) and th[3] == pytest.approx(ref[2], abs=0.01) and th[2] == pytest.approx(ref[3], abs=0.01)


def test_hist_and_ewma_use_only_past():
    r = np.random.default_rng(3).standard_normal(400) * 0.01
    v99, _, es = s.hist_sim(r)
    w = np.sort(r[50:300])
    assert v99[300] == pytest.approx(-w[2]) and es[300] == pytest.approx(-w[:6].mean())
    e1 = s.ewma_sigma(r)
    r2 = r.copy(); r2[350] = -0.5
    e2 = s.ewma_sigma(r2)
    assert e1[350] == e2[350] and e2[351] > e1[351]


def test_t_consts_and_grade_and_traffic():
    assert s.t_consts(1e6) == pytest.approx((2.326, 1.960, 2.338), abs=2e-3)
    assert s.t_consts(5)[0] > s.Z99
    assert s.grade((-1, -3, 0.003), (-1, -1, 0.3), 1500, 3) == "A"
    assert s.grade((-1, -3, 0.003), (1, 1, 0.3), 1500, 4) == "B"
    assert s.grade((-1, -1.8, 0.07), (-1, -1, 0.3), 1500, 4) == "C"
    assert s.grade((1, 1.8, 0.07), (-1, -1, 0.3), 1500, 4) == "C(역방향)"
    assert s.grade((-1, -0.5, 0.6), (-1, -1, 0.3), 1500, 4) == "F"
    assert s.grade((-1, -3, 0.003), (-1, -1, 0.3), 500, 4) == "검증전"
    assert [s.traffic(x) for x in (4, 5, 10)] == ["녹", "황", "적"]


def test_output_structure():
    f = ROOT / "reports/studies/2026-11-10_var_models.json"
    if not f.exists():
        pytest.skip("산출 없음")
    j = json.loads(f.read_text(encoding="utf-8"))
    assert j["prereg"]["m"] == 4 and j["prereg"]["alpha_bonf"] == 0.0125
    assert set(j["grades"]) == {"H1", "H2", "H3", "H4"}
    assert j["adoption"]["verdict"] in ("현행 유지", "교체 제안")
    assert abs(sum(j["prereg"]["port_weights"].values()) - 1) < 1e-9
