"""홀짝홀홀 연구(scripts/study_hollzzak.py) — 통계 도구·첫/재 분류 규칙 (네트워크·데이터 없음)."""
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import study_hollzzak as hz  # noqa: E402


def test_binom_and_fisher_exact():
    assert math.isclose(hz.binom_p(10, 10, 0.5, True), 0.5 ** 10)          # 10/10 단측
    assert math.isclose(hz.binom_p(0, 10, 0.5, False), 0.5 ** 10)
    # 2x2 [[1,9],[9,1]]: 집단1 1/10 < 집단2 9/10, 손계산 초기하 P(X<=1) = (C(10,0)C(10,10)+C(10,1)C(10,9))/C(20,10)
    exp = (1 + 10 * 10) / math.comb(20, 10)
    assert math.isclose(hz.fisher_less(1, 10, 9, 10), exp)


def test_classify_first_re_and_bigup():
    # r: 폭락(−4%) → 반등(+2%) → 평이 → 재폭락(−4%) → +3.5% 양봉 → …
    r = [0.0, -0.04, 0.02, 0.0, -0.04, 0.035, 0.01, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, -0.04, -0.01]
    d = pd.DataFrame({"date": pd.date_range("2020-01-01", periods=len(r), freq="B"), "r": r})
    d["rn"] = d["r"].shift(-1)
    d["k200_hi"] = d["r"] + 0.01
    c = hz.classify(d, -0.03)
    assert c.loc[1, "first"] and not c.loc[1, "re"]           # 직전 5일 폭락 없음
    assert c.loc[4, "re"] and not c.loc[4, "first"]           # 1일 폭락 뒤 반등(+2%) 있었음
    assert c.loc[5, "big_up"] and c.loc[5, "side_px"]         # 3일 안 폭락 + 3.5% / 고가 +4.5%
    assert c.loc[13, "first"]                                 # 9거래일 뒤라 첫 폭락


def test_cluster_boot_shape_and_grade_rules():
    df = pd.DataFrame({"cluster": [1, 1, 2, 3], "group": "a", "val": [1.0, 0.0, 1.0, 1.0]})
    bs = hz.cluster_boot(df, lambda S, N: hz._ratio(S["a"], N["a"]), ["a"], b=500)
    assert bs.shape == (500,) and np.nanmin(bs) >= 0 and np.nanmax(bs) <= 1
    ok = lambda x: x.get("n", 0) >= 10  # noqa: E731
    res = {"design": {"H1": {"n": 20, "effect": 0.1, "p": 0.001}}, "valid": {"H1": {"n": 20, "effect": 0.1, "p": 0.01}},
           "pooled": {"H1": {"n": 40, "effect": 0.1, "p": 0.0005}}, "holdout": {"H1": {"n": 5, "effect": -0.1}}}
    assert hz.grade("H1", res, ok)["grade"] == "A"
    res["valid"]["H1"]["effect"] = -0.1                       # 설계↔검증 부호 반대 → F
    assert hz.grade("H1", res, ok)["grade"] == "F"


def test_repo_result_structure():
    p = ROOT / "reports" / "studies" / "hollzzak.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    assert d["m"] == 7 and set(d["grades"]) == {"H1", "H2", "H3a", "H3b", "H4a", "H4b", "H4c"}
    assert d["prereg"].endswith("0a32f3de")
