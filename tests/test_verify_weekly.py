"""verify_weekly 순수 함수 — 합성 데이터(규약 v1, 2026-10-23)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import verify_weekly as vw  # noqa: E402

BARS = [{"t": "2026-10-20", "o": 100, "h": 101, "l": 99, "c": 100},
        {"t": "2026-10-21", "o": 101, "h": 102, "l": 94, "c": 95},
        {"t": "2026-10-22", "o": 93, "h": 96, "l": 92, "c": 95}]


def test_stop_breach_requires_next_open_exit():
    assert vw.stop_breaches(BARS, "2026-10-20", 95, "2026-10-22")[0]["ok"] is True
    bad = vw.stop_breaches(BARS, "2026-10-20", 95, None)[0]
    assert bad["ok"] is False and bad["need_exit"] == "2026-10-22"
    assert vw.stop_breaches(BARS, "2026-10-20", 90, None) == []


def test_entry_band_and_next_open():
    o = {"after": "2026-10-20", "lo": 100, "hi": 102}
    assert vw.entry_check(o, "2026-10-21", 101, BARS)["ok"]
    assert not vw.entry_check(o, "2026-10-21", 103, BARS)["in_band"]
    assert not vw.entry_check(o, "2026-10-22", 93, BARS)["next_open"]


def test_size_formula_and_fill_risk_warning():
    o = {"weight": 0.0388, "risk_pct": 0.00187, "stop": 184628.57,
         "formula": "0.5% × 컨빅션 0.75 × 시장 0.5 ÷ 손절폭 4.8% (상한 15%·남은 노출 50%)"}
    sc = vw.size_check(o, 195600.0)
    assert sc["formula_ok"] and sc["risk_warn"] and abs(sc["risk_real"] - 0.00218) < 1e-5


def test_stop_decision_needs_n():
    assert vw.stop_decision([-0.5] * 3)["verdict"].startswith("판정 보류")
    assert vw.stop_decision([-0.1] * 12)["verdict"] == "B1 진입 중단"
    assert vw.stop_decision([0.2] * 12)["verdict"] == "유지"


def test_wilson_ir_overlap():
    lo, hi = vw.wilson(16, 26)
    assert 0.42 < lo < 0.43 and 0.77 < hi < 0.78
    assert vw.ir([0.001] * 5) is None
    ov = vw.overlap({"d1": {"a": 1, "b": 1}, "d2": {"a": 1, "b": -1}, "d3": {"a": 1}})
    assert ov["a~b"] == {"days_both": 2, "same": 1, "ratio": 0.5}


# ── 규약 v2 (2026-10-24, req-verify-747e1bd3 · 1f20e800 · ed663038) ──

def _hf_fixture():
    parent = {"id": "2026-10-27-1", "kind": "stock", "side": "롱", "code": "000660", "market": "KR", "asof": "2026-10-27",
              "exit_d": "2026-10-28", "entry": 100, "stop": 95, "t1": 110, "exit_why": "손절", "r": -1.0, "risk": 0.002,
              "weight": 0.04, "plan": {"p_win": 0.5}, "consensus": True,
              "independence": {"books": ["PB🔥", "알파북"], "indep": "data/flows/000660.csv 외국인 순매수", "pair_hedge": "2026-10-27-2"}}
    pair = {"id": "2026-10-27-2", "kind": "fut", "side": "숏", "code": "K200F", "market": "KR", "asof": "2026-10-27",
            "exit_d": "2026-10-28", "entry": 850, "stop": None, "t1": None, "exit_why": "페어 헤지 — 부모 청산 연동",
            "r": 0.3, "risk": 0.004, "weight": 0.04, "pair": True, "hedge_of": ["2026-10-27-1"]}
    put = {"id": "2026-10-27-3", "kind": "put", "side": "롱", "code": "K200O", "market": "KR", "asof": "2026-10-27",
           "exit_d": "2026-10-28", "entry": 20.0, "r_unit": 20.0, "stop": None, "t1": 40.0, "exit_why": "만기 전 청산",
           "r": 0.5, "risk": 0.0025, "weight": 0.0025, "time_exit": "2026-11-05"}
    return {"closed": [parent, pair, put], "open": [], "nav": [{"pnl": -0.002 + 0.0012 + 0.00125}]}


def test_pair_leg_excluded_from_r_and_invalid_but_bundled(monkeypatch):
    monkeypatch.setattr(vw, "_fut", lambda: {"2026-10-27": 850.0, "2026-10-28": 830.0})
    monkeypatch.setattr(vw, "_chart", lambda m, c: [])
    monkeypatch.setattr(vw, "indep_linked", lambda p: True)
    ab = {"books": {"KR": {"fills": []}}}
    h = vw.score_hf(_hf_fixture(), ab, {"items": []}, "2026-10-28")
    assert h["pair_n"] == 1 and h["n"] == 2 and h["invalid_n"] == 0       # 페어 다리 plan 없음 ≠ 무효
    assert h["r_all"]["n"] == 2 and 0.3 not in [x["r"] for x in h["rows"] if not x["pair_of"]]
    par = next(x for x in h["rows"] if x["id"] == "2026-10-27-1")
    assert abs(par["pnl_bundle"] - (-0.002 + 0.0012)) < 1e-12              # 부모 + 페어 다리 손익
    assert h["pnl_ok"]                                                     # H1 합계엔 다리 손익 그대로
    c = h["consensus"]
    assert c["three_books"]["n_closed"] == 1 and c["two_books"]["n_closed"] == 0
    assert abs(c["three_books"]["pnl_bundle"] - (-0.0008)) < 1e-12
    assert c["non_consensus"]["n_closed"] == 1                             # 풋만(페어 다리 제외)
    assert c["linkage"]["verdict"].startswith("판정 보류")
    md = vw.render({"asof": "2026-10-28", "protocol": "v2", "alphabook": {}, "hf": h})
    assert "페어→2026-10-27-1" in md and "세 북 청산 1" in md


def test_bundle_orphan():
    b = vw.bundle_pnl([{"id": "a", "pnl": 1.0}, {"id": "h", "pnl": 0.5, "pair_of": "a"}, {"id": "x", "pnl": 0.2, "pair_of": "zz"}])
    assert b["a"] == 1.5 and b["_orphan"] == 0.2


def test_option_defined_risk_and_cautions():
    ok = vw.option_check({"kind": "put", "entry": 20.0, "r_unit": 20.0, "risk": 0.0025, "time_exit": "2026-11-05"})
    assert ok["defined_risk"] and ok["caution"] == ["논지 붕괴 수준", "IV 재평가"]
    assert not vw.option_check({"kind": "put", "entry": 20.0, "r_unit": 10.0, "risk": 0.0025})["defined_risk"]
    sp = vw.option_check({"kind": "spread", "spread": {"max_loss": 3.2}, "r_unit": 3.2, "risk": 0.002,
                          "check": {"time_exit": "x", "thesis_stop": 820, "iv_review": "FOMC 뒤"}})
    assert sp["defined_risk"] and sp["caution"] == []
    assert vw.option_check({"kind": "stock"}) == {"applies": False}


def test_consensus_days_and_missing_flags():
    days = {"d1": {"HF재량": 1, "알파북": 1, "PB🔥": 1}, "d2": {"HF재량": 1, "알파북": -1}, "2026-10-26": {"HF재량": 1, "알파북": 1}}
    assert vw.consensus_days(days) == {"days": 3, "ge2": 2, "all3": 1}
    e = [{"id": "a", "kind": "stock", "side": "롱", "asof": "2026-10-26"},
         {"id": "b", "kind": "stock", "side": "롱", "asof": "2026-10-26", "consensus": True},
         {"id": "c", "kind": "put", "side": "롱", "asof": "2026-10-26"},              # 풋 롱 = 숏 노출 → 겹침 아님
         {"id": "d", "kind": "fut", "side": "숏", "asof": "2026-10-26", "hedge_of": ["a"]}]
    assert vw.missing_flags(e, days) == ["a"]


def test_indep_linkage():
    p = {"asof": "2026-10-27", "code": "000660",
         "independence": {"indep": "reports/committee.json data/flows/000660.csv 외국인"}}
    assert vw.indep_paths(p["independence"]["indep"]) == ["data/flows/000660.csv"]   # 공유 입력 제외
    assert vw.indep_linked(p, reader=lambda path, d: ("date,000660,1", "2026-10-24"))
    assert not vw.indep_linked(p, reader=lambda path, d: ("date,005930,1", "2026-10-24"))   # 종목 없음 = 형식
    assert not vw.indep_linked(p, reader=lambda path, d: ("000660", "2026-10-01"))          # 낡은 판
    assert vw.linkage_verdict(3, 9).startswith("판정 보류")
    assert vw.linkage_verdict(4, 10) == "형식 칸" and vw.linkage_verdict(6, 10) == "경고" and vw.linkage_verdict(8, 10) == "실질"
