"""scripts/study_laor_ib_qld.py — QLD 3안 파라미터 매핑·고가 근사·기존 엔진 불변 확인."""
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("study_laor_ib_qld", ROOT / "scripts/study_laor_ib_qld.py")
mod = importlib.util.module_from_spec(spec)
sys.modules["study_laor_ib_qld"] = mod
spec.loader.exec_module(mod)
L = mod.L


def test_plans_map_to_star_table():
    a, b, c = (mod._key(p) for p in mod.PLANS)
    assert L.star_pct(L.RULES["V4.0_20"], L.BASE[a], 4) == 10 - 1.0 * 4      # A: 10 − T
    assert L.star_pct(L.RULES["V4.0_20"], L.BASE[b], 4) == 15 - 1.5 * 4      # B: TQQQ 그대로
    assert L.star_pct(L.RULES["V2.2_40"], L.BASE[c], 4) == 10 - 4 / 2        # C: V2.2


def test_existing_engine_constants_untouched():
    assert L.BASE["TQQQ"] == 15.0 and L.BASE["SOXL"] == 20.0
    assert set(L.RULES) == {"V4.0_20", "V4.0_40", "V3.0_20", "V2.2_40"}


def test_plan_a_target_is_plus_10pct():
    k = mod._key(list(mod.PLANS)[0])
    p = L.Pos(cash=0.5, seed=1.0, qty=10.0, avg=1.0, T=4.0)
    # A: 별% 10−4 = 6% → 별지점 1.06, 목표 1.10. 고가 1.11 → ¾ 지정가 1.10 체결, 종가 1.07 ≥ 1.06 → ¼ LOC → 종료
    assert L.step(p, L.RULES["V4.0_20"], L.BASE[k], 1.0, 1.07, 1.11, 1.0, 0.0) == "end"
    assert abs(p.cash - (0.5 + 7.5 * 1.10 + 2.5 * 1.07)) < 1e-9


def test_prevT_no_same_day_half_rejudge():
    """T=10.5(후반) 에서 쿼터 매도로 T→7.9(전반)가 돼도, 그날 매수는 직전 T 기준 후반 규칙(별지점 LOC만)이어야 한다."""
    rule = L.RULES["V4.0_20"]
    mk = lambda: L.Pos(cash=0.5, seed=1.0, qty=10.0, avg=1.0, T=10.5)
    # 별% = 15 − 1.5×10.5 = −0.75% → 별지점 0.9925. 종가 0.995 ≥ 별지점 → 쿼터 매도, 종가 ≤ 평단 1.0
    p_fix, p_orig = mk(), mk()
    mod.step_prevT(p_fix, rule, 15.0, 1.0, 0.995, 0.995, 1.0, 0.0)
    mod._ORIG_STEP(p_orig, rule, 15.0, 1.0, 0.995, 0.995, 1.0, 0.0)
    assert abs(p_fix.T - 10.5 * 0.75) < 1e-9          # 후반: 종가 > 별지점−0.01% 라 매수 없음
    assert abs(p_orig.T - p_fix.T) < 1e-9              # 10/23 엔진 본체가 T0 로 고쳐져(검증 요청) 원 엔진도 같은 날 재판정 안 함
    assert L.step is mod._ORIG_STEP                    # 컨텍스트 밖에서는 원 엔진 그대로


def test_build_qld_path_high_proxy():
    idx = pd.bdate_range("2010-01-01", periods=4)
    dq = pd.DataFrame({"QLD_adj": [100, 102, 101, 103.0], "QQQ_adj": [50, 50.5, 50.25, 51.0], "SPY_adj": [1, 1, 1, 1.0],
                       "^NDX_close": [1000, 1010, 1005, 1020.0], "^GSPC_close": [1, 1, 1, 1.0], "^IRX_close": [0, 0, 0, 0.0],
                       "KRW=X_close": [1100.0] * 4}, index=idx)
    dl = pd.DataFrame({"^NDX_close": [1000, 1010, 1005, 1020.0], "^NDX_high": [1001, 1030, 1012, 1020.0]}, index=idx)
    path, meta = mod.build_qld_path(dq, dl)
    assert meta["real_first"] == str(idx[1].date())
    # 둘째 날: 고가 = 100 × (1 + 2 × (1030/1000 − 1)) = 106 (종가 102 위)
    assert np.isclose(path["high"].iloc[0], 100 * (1 + 2 * 0.03))
    assert (path["high"] >= path["close"] - 1e-12).all()
