"""rep-rule-audit T4·T5 독립 재현 — 합성 데이터로 정의만 검사(원 코드·실데이터 불필요)."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import replicate_rule_audit as R  # noqa: E402


def _df(c):
    return pd.DataFrame({"date": pd.bdate_range("2011-01-03", periods=len(c)).strftime("%Y-%m-%d"),
                         "kospi_close": np.asarray(c, float)})


def test_t4_event_and_wait():
    # 30일 상승(90→100) → t0(30)에 94 로 20일선 하향 이탈 → +0.2%, +0.6% → 현행 2일째, th0 1일째, th1 만기
    a, b = 94 * 1.002, 94 * 1.002 * 1.006
    c = list(np.linspace(90, 100, 30)) + [94.0, a, b] + [b * 1.0001 ** k for k in range(1, 41)]
    t = R.simulate_t4(_df(c))
    assert t["n_events"] == 1
    s = t["summary"]
    assert s["imm"]["wait"] == 0 and s["th0"]["wait"] == 1 and s["cur"]["wait"] == 2 and s["th1"]["wait"] == 10
    assert abs(s["cur"]["sale_vs_t0"] - (b / 94 - 1)) < 1e-12
    d_imm = t["cmp"]["imm"]["all"]["mean"]
    assert abs(d_imm + (b / 94 - 1)) < 1e-12


def test_t4_event_spacing_and_completion():
    base = list(np.linspace(90, 100, 25))
    dip = [94.0] + [101.0] * 3  # 이탈 후 복귀 반복
    c = base + dip + [101.0] * 5 + dip + [101.0] * 30
    ev = R.t4_events(None, np.array(c))
    assert len(ev) == 1  # 두 번째 이탈은 간격 ≤ 20 → 제외
    assert R.t4_events(None, np.array(c[:30]), need=10) == []  # t0+10 없음 → 미완성 제외


def test_t5_exposure_cost_and_stats():
    c = np.r_[np.linspace(100, 200, 220), np.linspace(200, 120, 60)]
    e, net, bear = R.t5_path(c, 0.5)
    assert set(np.unique(e)) <= {0.5, 1.0} and e[0] == 1.0
    r = c[200:] / c[199:-1] - 1
    prev = np.r_[e[0], e[:-1]]
    assert np.allclose(net, e * r - np.abs(e - prev) * 0.00125)
    e1, net1, _ = R.t5_path(c, 1.0)
    assert np.allclose(net1, r) and R.t5_stats(e1, net1)["turnover_yr"] == 0.0
    t = R.simulate_t5(_df(c))
    assert t["blocks"] == len(net) // 21 and t["days"] == len(net)


def test_grade_rule():
    mk = lambda m, p: {"n": 10, "mean": m, "t": 1.0, "p": p}
    assert R.grade({"all": mk(-1, 0.001), "is": mk(-1, .1), "oos": mk(-1, .1)}) == "A"
    assert R.grade({"all": mk(-1, 0.001), "is": mk(1, .1), "oos": mk(-1, .1)}) == "B"
    assert R.grade({"all": mk(-1, 0.05)}) == "C"
    assert R.grade({"all": mk(-1, 0.2)}) == "F"
