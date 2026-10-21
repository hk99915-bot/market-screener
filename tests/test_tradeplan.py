"""매매 계획 표준(screener/tradeplan.py) + 보정 경로 판정(scripts/study_tradeplan.py) 테스트."""
import copy
import importlib.util
import json
import math
import random
from datetime import date
from pathlib import Path

import numpy as np
import pytest

from screener import tradeplan as T

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("study_tradeplan", ROOT / "scripts" / "study_tradeplan.py")
S = importlib.util.module_from_spec(spec)
spec.loader.exec_module(S)


def bars(n=120, start=100.0, drift=0.001, vol=0.02, seed=1):
    rnd = random.Random(seed)
    out, c = [], start
    for i in range(n):
        o = c
        c = max(1.0, c * (1 + drift + rnd.gauss(0, vol)))
        h, l_ = max(o, c) * (1 + abs(rnd.gauss(0, vol / 2))), min(o, c) * (1 - abs(rnd.gauss(0, vol / 2)))
        out.append({"t": f"2026-01-{i:03d}", "o": o, "h": h, "l": l_, "c": c, "v": 1000})
    return out


# ── 보정 경로 판정: 벡터판 = 단순 스칼라판 ──

def _scalar_first(o, h, l_, c, r):
    for j in range(len(o)):
        if o[j] <= -1:
            return o[j], 1
        if l_[j] <= -1:
            return -1.0, 1
        if o[j] >= r:
            return o[j], 0
        if h[j] >= r:
            return r, 0
    return c[-1], 2


def test_first_touch_matches_scalar():
    rng = np.random.default_rng(7)
    N, H = 300, 20
    c = np.cumsum(rng.normal(0, 0.4, (N, H)), 1)
    o = np.c_[np.zeros(N), c[:, :-1]] + rng.normal(0, 0.1, (N, H))
    o[:, 0] = 0
    h = np.maximum(o, c) + np.abs(rng.normal(0, 0.3, (N, H)))
    l_ = np.minimum(o, c) - np.abs(rng.normal(0, 0.3, (N, H)))
    res, kind = S.first_touch(o, h, l_, c, 1.5)
    for i in range(N):
        v, k = _scalar_first(o[i], h[i], l_[i], c[i], 1.5)
        assert k == kind[i] and math.isclose(v, res[i], rel_tol=1e-6, abs_tol=1e-6)


def test_scale_out_stop_first_and_breakeven():
    # 1일째 1차(1R) 도달 → 2일째 본전 이탈: 0.5×1 + 0.5×0 = 0.5
    O = np.array([[0, 0.5, 0.2]], float); Hh = np.array([[0.3, 1.2, 0.3]]); L = np.array([[-0.2, 0.4, -0.1]]); C = np.array([[0.1, 1.0, 0.0]])
    res, k1, hit2 = S.scale_out(O, Hh, L, C, 1.0, 3.0)
    assert k1[0] == 0 and not hit2[0] and math.isclose(res[0], 0.5)
    # 같은 날 손절·목표 둘 다 → 손절(보수)
    res, k1, _ = S.scale_out(np.array([[0.0]]), np.array([[2.0]]), np.array([[-1.5]]), np.array([[0.0]]), 1.0, 3.0)
    assert k1[0] == 1 and res[0] == -1.0
    # 갭 하락은 시가 체결(−1R 보다 나쁨)
    res, k, = S.first_touch(np.array([[0.0, -1.6]]), np.array([[0.2, -1.5]]), np.array([[-0.2, -1.8]]), np.array([[0.1, -1.7]]), 2.0)
    assert k[0] == 1 and math.isclose(res[0], -1.6)


# ── 계획 본체 ──

def test_build_plan_invariants():
    p = T.build_plan(bars(), market="KR", calib=None)
    assert p is not None
    e, st, t1, t2 = p["entry"], p["stop"], p["t1"], p["t2"]
    assert st["px"] < e["lo"] <= e["ref"] <= e["hi"] < t1["px"] <= t2["px"]
    R = p["close"] - st["px"]
    assert math.isclose(p["rr1"], round((t1["px"] - p["close"]) / R, 2))
    assert 1.0 <= st["atr_mult"] <= 2.0
    assert p["prob"]["grade"] == "검증전" and p["verdict"] in ("관찰(모의)", "보류")
    assert p["size"]["mock"] and p["size"]["weight"] <= T.WEIGHT_CAP
    for k in ("entry", "stop", "t1", "t2", "rr1", "rr2", "prob", "ev_r", "scale_out", "time_stop", "filter", "conviction", "size", "verdict", "owners", "line"):
        assert k in p
    assert T.build_plan(bars(10)) is None


def test_t2_uses_valuation_analyst_median_and_cap():
    b = bars(drift=0.0)
    c = b[-1]["c"]
    det = {"valuation": {"models": {"a": {"value": c * 1.3, "group": "current"}, "b": {"value": c * 1.5, "group": "current"}}},
           "research": {"consensus_tp": c * 9}}
    p = T.build_plan(b, det=det)
    assert p["rr2"] <= T.R2_CAP + 1e-9 and "애널 목표가" in p["t2"]["basis"]


def test_conviction_bands_and_size():
    ax = {a: {"v": 0.9, "why": []} for a in T.AXES}
    cv = T.conviction(ax)
    assert cv["grade"] == "A" and cv["mult"] == 1.0 and cv["hold_t2"]
    cv = T.conviction({a: {"v": -0.8, "why": []} for a in T.AXES})
    assert cv["grade"] == "D" and cv["mult"] == 0.0
    cv = T.conviction({"tech": {"v": 1.0, "why": []}, "fund": {"v": None, "why": []}})
    assert cv["grade"] == "C"   # 가용 축 1개 → 상한 C
    assert T.conviction({})["grade"] == "D"


def test_macro_filter_rules():
    assert T.macro_filter({"regime": "하락장"})["mult"] == 0.5
    assert T.macro_filter({"events": [{"d": 0, "what": "FOMC"}]})["state"] == "보류"
    assert T.macro_filter({}, earn_days=1)["state"] == "보류"
    f = T.macro_filter({}, earn_days=10)
    assert f["state"] == "정상" and "어닝 D-10" in f["flags"]
    det = {"drivers": {"macro": {"rows": [{"factor": "US10Y", "name": "미 10년 금리", "beta": -0.3, "t": -3.0}]}}}
    sh = [{"name": "금리 급등", "factors": ("US10Y",), "dir": 1}]
    f = T.macro_filter({"shocks": sh}, det)
    assert f["t2_haircut"] == 0.5 and f["state"] == "축소"
    det["drivers"]["macro"]["rows"][0]["t"] = -1.0   # 유의하지 않으면 무시
    assert T.macro_filter({"shocks": sh}, det)["state"] == "정상"
    p = T.build_plan(bars(), ctx={"shocks": sh}, det={"drivers": {"macro": {"rows": [{"factor": "US10Y", "name": "x", "beta": -0.3, "t": -3}]}}})
    assert "매크로 감액" in p["t2"]["basis"]


def test_calib_lookup_nearest_cell_and_grade():
    cal = {"asof": "x", "groups": {"kr_trend": {"grid": {"struct": {
        "scale": {"1.5/3.0": {"test": {"p_t1": .3, "p_s": .5, "p_t2": .1, "ev_r": .05, "t": 2.5, "n": 999, "n_dates": 100}},
                  "1.0/2.0": {"test": {"ev_r": -.1, "t": -3, "n_dates": 100}}},
        "single": {"1.5": {"test": {"p_time": .2, "stop_exit_r": -1.02}}}}}},
        "kr_base": {"grid": {"struct": {"scale": {"1.5/3.0": {"test": {"ev_r": .08}}}}}}}}
    q = T.calib_lookup(cal, "kr_trend", 1.6, 3.2)
    assert q["cell"] == "struct 1.5/3.0" and q["grade"] == "C" and q["base_ev_r"] == .08
    assert T.calib_lookup(cal, "kr_trend", 1.0, 2.0)["grade"] == "F"
    assert T.calib_lookup(None, "kr_trend", 1.5, 3)["grade"] == "검증전"


# ── '계획 없는 매수/편입 문구 금지' (10/21 겸이 상시 규칙) ──

def test_affirmative_buy_detection():
    assert T.affirmative_buy("급락일 종가 1차 매수 — 15:20 동시호가")
    assert not T.affirmative_buy("하지 말 일: 모의 후보 추격 매수")
    assert not T.affirmative_buy("반도체 신규 매수 금지")
    assert T.affirmative_buy("현금 분할 매수 2차 집행")


def test_guard_rewrites_buy_without_plan():
    o = {"stance": {"plan": "급락일 종가 1차 매수.", "exec": {"steps": [{"when": "2차", "do": "추격 매수 금지"}], "cands": []}},
         "bottom_line": {"lines": ["할 일: 현금 분할 매수"]}, "ideas_top": {"items": []}}
    ch = T.guard_buy_text(o)
    assert len(ch) == 2 and "계획 없음" in o["stance"]["plan"] and o["stance"]["exec"]["steps"][0]["do"] == "추격 매수 금지"
    assert not any(T.affirmative_buy(p[k]) for p, k in T._texts(o))


def test_guard_keeps_text_when_plan_exists():
    p = T.build_plan(bars())
    o = {"stance": {"plan": "급락일 종가 1차 매수"}, "ideas_top": {"items": [{"s": "x", "plan": p}]}}
    assert T.guard_buy_text(o) == [] and o["stance"]["plan"] == "급락일 종가 1차 매수"


@pytest.mark.parametrize("fn,mk", [("committee.json", "KR"), ("committee_us.json", "US")])
def test_attach_on_real_committee(fn, mk):
    f = ROOT / "reports" / fn
    if not f.exists():
        pytest.skip("committee 산출물 없음")
    o = json.loads(f.read_text(encoding="utf-8"))
    s = T.attach(copy.deepcopy(o), mk, date(2026, 10, 21))
    o2 = copy.deepcopy(o)
    T.attach(o2, mk, date(2026, 10, 21))
    it = o2.get("ideas_top") or {}
    for x in (it.get("items") or []) + (it.get("candidates") or []):
        assert "plan" in x or "plan_error" in x
    todo = [L for L in (o2.get("bottom_line") or {}).get("lines", []) if "할 일" in L]
    assert all("계획" in L for L in todo)
    assert s["mock"] is True
    # 계획을 모두 지운 판에서 가드 → 긍정 매수 문구 0
    for x in (it.get("items") or []) + (((o2.get("stance") or {}).get("exec") or {}).get("cands") or []):
        x.pop("plan", None)
    T.guard_buy_text(o2)
    assert not any(T.affirmative_buy(str(p[k])) for p, k in T._texts(o2))


def test_committee_wires_tradeplan():
    src = (ROOT / "screener" / "committee.py").read_text(encoding="utf-8")
    assert src.count("tradeplan.attach(out,") == 2   # KR·US 둘 다
    assert "duel_plan" in (ROOT / "screener" / "duel.py").read_text(encoding="utf-8")
