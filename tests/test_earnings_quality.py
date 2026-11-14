"""영업이익·순이익 괴리 필터(DART) — 순수 계산 모듈·연구 스크립트 회귀 (네트워크·저장소 데이터 불필요)."""
import importlib.util
import math
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from screener import earnings_quality as eq  # noqa: E402

spec = importlib.util.spec_from_file_location("soni", ROOT / "scripts" / "study_op_ni_divergence.py")
soni = importlib.util.module_from_spec(spec)
spec.loader.exec_module(soni)


def test_report_due_statutory_deadlines():
    assert eq.report_due(2021, 1) == date(2021, 5, 15)      # 1분기: 3/31 +45일
    assert eq.report_due(2021, 2) == date(2021, 8, 14)      # 반기: 6/30 +45일
    assert eq.report_due(2021, 3) == date(2021, 11, 14)     # 3분기: 9/30 +45일
    assert eq.report_due(2021, 4) == date(2022, 3, 31)      # 사업보고서: 12/31 +90일
    assert eq.report_due(2024, 4) == date(2025, 3, 31)      # 윤년 다음 해도 3/31
    assert eq.report_due(2021, 1) < eq.report_due(2021, 2) < eq.report_due(2021, 4)


def test_prev_period_is_same_quarter_last_year():
    assert eq.prev_period(2022, 1) == (2021, 1)
    assert eq.prev_period(2021, 4) == (2020, 4)
    assert eq.prev_period(2020, 2, back=1) == (2020, 1)


def test_standalone_quarter_prefers_period_value_and_detects_cumulative():
    # 1분기·2분기: amount 는 이미 3개월 값. 누적값과 일치하면 그대로 쓴다
    assert eq.standalone_quarter(1, 100.0, 100.0, None) == (100.0, "amount")
    assert eq.standalone_quarter(2, 120.0, 220.0, 100.0) == (120.0, "amount")
    # amount 에 누적값이 들어온 회사: 5% 넘게 어긋나면 누적 차분을 쓴다
    assert eq.standalone_quarter(2, 220.0, 220.0, 100.0) == (120.0, "cum_diff")
    # 4분기: 사업보고서 amount 는 연간 → 3분기 누적을 빼야 단독값
    assert eq.standalone_quarter(4, 400.0, None, 300.0) == (100.0, "annual_minus_cum3")
    assert eq.standalone_quarter(4, 400.0, None, None) == (None, "missing")
    assert eq.standalone_quarter(3, None, 300.0, 100.0) == (200.0, "cum_diff")


def test_snapshot_margins_and_nonop():
    s = eq.snapshot(1000.0, 100.0, 60.0, 80.0)
    assert abs(s["m_op"] - 0.10) < 1e-12 and abs(s["m_ni"] - 0.06) < 1e-12
    assert s["nonop"] == -20.0                       # 세전 80 − 영업 100 = 영업외 −20
    assert abs(s["m_nonop"] + 0.02) < 1e-12
    assert eq.snapshot(0.0, 10.0, 5.0, 6.0)["m_op"] is None      # 매출 0 → 이익률 없음
    assert eq.snapshot(-5.0, 10.0, 5.0, 6.0)["m_op"] is None     # 음수 매출도 없음
    assert eq.margin(None, 100.0) is None


def test_divergence_event_requires_business_up_and_ni_down():
    prev = eq.snapshot(1000.0, 80.0, 70.0, 90.0)      # 영업이익률 8%, 순이익률 7%
    now = eq.snapshot(1000.0, 100.0, 10.0, 12.0)      # 영업이익률 10%(개선), 순이익률 1%(급락)
    d = eq.divergence(now, prev)
    assert d["is_event"] is True
    assert d["d_op"] > 0 and d["d_ni"] < -0.02
    # 순이익이 영업이익과 같이 늘면 사건이 아니다
    assert eq.divergence(eq.snapshot(1000.0, 100.0, 90.0, 100.0), prev)["is_event"] is False
    # 영업이익률이 떨어졌으면(본업 둔화) 사건이 아니다 — 이 필터는 '본업 견조'를 전제로 한다
    assert eq.divergence(eq.snapshot(1000.0, 70.0, 20.0, 30.0), prev)["is_event"] is False
    # 본업 적자면 비교 자체가 성립하지 않는다
    assert eq.divergence(eq.snapshot(1000.0, -10.0, -50.0, -40.0), prev)["is_event"] is False
    assert eq.divergence({"m_op": None}, prev)["is_event"] is False


def test_warning_flag_uses_nonop_loss_share():
    prev = eq.snapshot(1000.0, 100.0, 60.0, 90.0)      # 영업외 −10
    now = eq.snapshot(1000.0, 100.0, -20.0, -40.0)     # 영업외 −140 = 영업이익의 1.4배
    w = eq.warning(now, prev)
    assert w["warn"] is True and abs(w["share"] - 1.4) < 1e-9
    assert w["d_nonop"] < -0.03
    small = eq.warning(eq.snapshot(1000.0, 100.0, 70.0, 75.0), prev)   # 영업외 −25 = 0.25배
    assert small["warn"] is False and abs(small["share"] - 0.25) < 1e-9
    assert eq.warning(eq.snapshot(1000.0, -10.0, -50.0, -60.0), prev)["share"] is None


def test_returns_have_no_lookahead():
    px = np.array([100.0, 110.0, 121.0, 133.1, 146.41])
    fwd = eq.forward_return(px, horizon=2)
    assert np.isnan(fwd[-2:]).all() and abs(fwd[0] - 0.21) < 1e-9
    back = eq.window_return(px, window=2)
    assert np.isnan(back[:2]).all() and abs(back[2] - 0.21) < 1e-9
    # 미래를 바꿔도 과거의 후방 수익률은 그대로 (전방 누수 없음)
    px2 = px.copy()
    px2[3:] *= 3
    assert abs(eq.window_return(px2, 2)[2] - back[2]) < 1e-12


def test_stats_helpers():
    assert abs(eq.p_one_sided(0.0) - 0.5) < 1e-12
    assert eq.p_one_sided(1.96) < 0.025 < eq.p_one_sided(1.0)
    assert abs(eq.p_one_sided(-1.96, -1) - eq.p_one_sided(1.96)) < 1e-12
    a = np.array([0.10, 0.12, 0.14, 0.11, 0.13])
    b = np.array([-0.02, 0.00, 0.01, -0.01, 0.0])
    w = eq.welch(a, b)
    assert w["n_a"] == 5 and w["diff"] > 0.10 and w["p_one"] < 0.01
    assert eq.welch(a[:2], b)["diff"] is None            # n < 3 은 검정하지 않는다
    cl = eq.cluster_mean([0.1, 0.2, 0.05, 0.15], ["d1", "d1", "d2", "d2"])
    assert cl["dates"] == 2 and abs(cl["mean"] - 0.125) < 1e-12
    st = eq.group_stats([0.1, -0.05, 0.0])
    assert st["n"] == 3 and abs(st["win"] - 1 / 3) < 1e-12 and abs(st["false_rate"] - 1 / 3) < 1e-12


def test_grade_rule_matches_repo_thresholds():
    assert soni.grade(0.001, {"is": 0.01, "oos": 0.02}, 100)[0] == "A"
    assert soni.grade(0.001, {"is": -0.01, "oos": 0.02}, 100)[0] == "B"
    assert soni.grade(0.001, {"is": -0.01, "oos": -0.02}, 100, direction=-1)[0] == "A"
    assert soni.grade(0.001, {"is": -0.01, "oos": 0.02}, 100, direction=-1)[0] == "B"
    assert soni.grade(0.05, {"is": 0.01, "oos": 0.02}, 100)[0] == "C"
    assert soni.grade(0.42, {"is": 0.01, "oos": 0.02}, 100)[0] == "F"
    assert soni.grade(0.001, {"is": 0.01, "oos": 0.02}, 4)[0] == "검증전"
    assert soni.ALPHA == 0.025 and soni.M == 2


def test_test_flag_matches_same_day_controls():
    """같은 진입일의 비플래그 종목과만 비교하는지 — 다른 날짜 종목이 대조에 섞이면 안 된다."""
    rows = []
    rng = np.random.default_rng(3)
    for en in ("2024-05-16", "2024-08-15"):
        for i in range(40):
            rows.append({"code": f"{i:06d}", "year": 2024, "q": 1, "avail": pd.Timestamp(en),
                         "t": pd.Timestamp(en), "entry": pd.Timestamp(en), "r20": -0.10 if i < 10 else 0.0,
                         "turn20": 1e9, "m_op": 0.05, "d_op": 0.01, "d_ni": -0.05, "d_nonop": -0.01,
                         "nonop_share": 0.6, "h1": i == 0, "h2": False, "h1_dni3": False, "h1_dni1": False,
                         "h2_share1": False, "h2_dn5": False,
                         "raw5": rng.normal(0, 0.05), "exc5": rng.normal(0, 0.01),
                         "raw20": rng.normal(0, 0.05), "exc20": 0.03 if i == 0 else rng.normal(0, 0.01),
                         "raw60": rng.normal(0, 0.05), "exc60": rng.normal(0, 0.01)})
    df = pd.DataFrame(rows)
    r = soni.test_flag(df, "h1")
    assert r["n_ev"] == 2                        # 날짜 2개 × 사건 1개
    assert r["n_ctrl"] == 18                     # 같은 두 날짜에서 낙폭 조건도 통과한 비사건만(9×2)
    assert abs(r["mean_ev"] - 0.03) < 1e-12
    df2 = df.copy()
    df2.loc[df2["code"] == "000005", "d_ni"] = np.nan      # 분류 불가 행(낙폭 조건은 통과)
    assert soni.test_flag(df2, "h1")["n_ctrl"] == 16


def test_build_panel_quarterly_difference():
    """합성 DART 행 — 사업보고서(4분기)는 연간−3분기누적, 반기/3분기는 누적 차분으로 단독값이 된다."""
    rows = []
    spec_rows = {1: (100.0, 100.0), 2: (120.0, 220.0), 3: (130.0, 350.0)}
    for q, (amt, cum) in spec_rows.items():
        rows.append({"code": "000001", "year": 2024, "q": q, "key": "rev", "amount": amt, "add_amount": cum})
    rows.append({"code": "000001", "year": 2024, "q": 4, "key": "rev", "amount": 400.0, "add_amount": None})
    d = pd.DataFrame(rows)
    got = {}
    for q in (1, 2, 3, 4):
        prev_cum = None if q == 1 else {1: 100.0, 2: 220.0, 3: 350.0}[q - 1]
        row = d[(d.q == q)].iloc[0]
        got[q] = eq.standalone_quarter(q, row["amount"], row["add_amount"], prev_cum)[0]
    assert got == {1: 100.0, 2: 120.0, 3: 130.0, 4: 50.0}
