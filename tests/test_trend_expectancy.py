"""기대값 하한 규칙 (사전등록 docs/valuation_notes/2026-10-17_trend_expectancy_prereg.md) — 수식·필터·집계."""
from screener import detail as D


def test_exp_lb_formula():
    m, sd, lb = D.exp_lb([0.1, -0.02] * 4)                   # n 8, t(7) 1.895
    assert round(m, 4) == 0.04 and round(sd, 4) == 0.0641
    assert round(lb, 4) == round(0.04 - 1.895 * sd / 8 ** 0.5, 4) and lb < 0
    assert D.exp_lb([0.05]) is None
    assert D.t95(35) == D.T95[30] and D.t95(7) == 1.895      # 표에 없는 자유도 → 작은 자유도(보수적)


def test_sim_one_rets_net_of_cost():
    c = [100, 101, 110, 108, 100, 99]
    r = D._sim_one(c, [1, 1, 0, 0, 0, 0], list(range(6)))   # 0일 결정 → 0일 종가 진입, 2일 결정 0 → 2일 종가 청산
    assert r["trades"] == 1 and r["rets"] == [round(110 / 100 - 1 - D.COST, 4)]


def _sim(rets, pos=1, entry="d9"):
    return {"bh": 0.1, "last2": ["d8", "d9"], "ma": {"long": {"pos": pos, "entry_date": entry, "rets": rets, "ret": 0.2}}, "psar": {"long": {}}}


def test_fresh_exp_filters():
    good = [0.06, -0.02, 0.05, 0.04, -0.01, 0.07, 0.03, 0.05]   # 승률 75% · 평균 +3.4% · 하한 > 0
    assert [x["strategy"] for x in D._fresh_exp(_sim(good), ["d8", "d9"])] == ["ma"]
    assert D._fresh_exp(_sim(good[:7]), ["d8", "d9"]) == []                 # 거래 < 8
    assert D._fresh_exp(_sim(good, entry="d1"), ["d8", "d9"]) == []         # 새로 켜짐 아님
    assert D._fresh_exp(_sim([0.1, -0.08] * 4), ["d8", "d9"]) == []         # 평균 +1% 지만 하한 < 0
    # 추세형: 승률 33% (Wilson 탈락) 이어도 기대값 하한 통과 가능 — 평균 +6%, 하한 = 0.06 − 1.796·0.1034/√12 ≈ +0.6%
    trend = [0.2] * 4 + [-0.01] * 8
    f = D._fresh_exp(_sim(trend), ["d8", "d9"])
    assert f and f[0]["win"] == 0.333 and f[0]["grade"] == "C·참고" and 0 < f[0]["exp_lb"] < 0.01
    assert D.wilson_lo(4, 12) < D.FRESH_WILSON_MIN


def test_exp_block_counts_and_binom():
    good = [0.06, -0.02, 0.05, 0.04, -0.01, 0.07, 0.03, 0.05]
    stocks = {}
    for i in range(20):
        s = _sim(good if i == 0 else [0.01, -0.01] * 4)
        s["fresh_exp"] = D._fresh_exp(s, ["d8", "d9"])
        stocks[f"S{i}"] = {"name": f"n{i}", "sim": s}
    b = D.exp_block(stocks)
    assert b["n_eligible"] == 20 and b["n_pass"] == 1 and b["expected_chance"] == 1.0
    assert abs(b["binom_p"] - (1 - 0.95 ** 20)) < 1e-3 and "우연과 구분 안 됨" in b["grade"]
