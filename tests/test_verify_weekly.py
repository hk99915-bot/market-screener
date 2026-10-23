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
