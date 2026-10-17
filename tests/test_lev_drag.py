"""duel.lev_drag — 레버리지 ETF 일일 리셋 비용(변동성 끌림) 계산 + 결정 기록·주문표에 자동 표기 (결재 #14 ① 코드 근거)."""
import json

import pytest

from screener import decisions, duel, ticket

D = "2026-10-16"
OK_AT = f"{D}T05:00:00Z"   # 14:00 KST


def test_round_trip_3x_matches_hand_calc():
    # 지수 +3% → −3%: 지수 0.9991 (−0.09%), 3배 '기대' −0.27%, 3배 일일 복리 1.09×0.91 = 0.9919 (−0.81%)
    x = duel.lev_drag([0.03, -0.03], 3)
    assert x["index"] == pytest.approx(-0.0009, abs=1e-6)
    assert x["naive"] == pytest.approx(-0.0027, abs=1e-6)
    assert x["etf"] == pytest.approx(-0.0081, abs=1e-6)
    assert x["drag"] == pytest.approx(-0.0054, abs=1e-6)


def test_drag_grows_with_days_and_swing_and_is_zero_for_trend():
    d2 = duel.lev_drag([0.03, -0.03], 3)["drag"]
    d10 = duel.lev_drag([0.03, -0.03] * 5, 3)["drag"]
    d_big = duel.lev_drag([0.06, -0.06], 3)["drag"]
    assert d10 < d2 < 0 and d_big < d2
    # 한 방향 추세에선 일일 복리가 L배 기대보다 오히려 유리 (끌림 양수)
    assert duel.lev_drag([0.02, 0.02, 0.02], 3)["drag"] > 0
    # 레버리지 1배는 끌림 0
    assert duel.lev_drag([0.05, -0.04, 0.02], 1)["drag"] == pytest.approx(0, abs=1e-12)


def test_inverse_also_drags():
    x = duel.lev_drag([0.03, -0.03], -2)
    assert x["etf"] == pytest.approx(0.94 * 1.06 - 1, abs=1e-9) and x["drag"] < 0


def test_lev_factor_tables():
    assert duel.lev_factor("122630") == 2 and duel.lev_factor("252670") == -2 and duel.lev_factor("114800") == -1
    assert duel.lev_factor("069500") == 0 and duel.lev_factor("SPY", "", "US") == 0
    assert duel.lev_factor("SOXL", "", "US") == 3 and duel.lev_factor("SQQQ", "", "US") == -3 and duel.lev_factor("QLD", "", "US") == 2
    assert duel.lev_factor("XXXX", "Direxion Daily Semis Bear 3x Shares", "US") == -3


def test_note_text_and_even_days():
    n = duel.lev_drag_note("SOXL", 3, 5)     # 5일 → 4일 왕복
    assert "4일 보유" in n and "±3%" in n and "끌림" in n
    assert duel.lev_note_for_pick({"cash": True}) is None
    assert duel.lev_note_for_pick({"ticker": "069500", "name": "KODEX 200", "exit": "next_open"}) is None
    assert "KODEX 레버리지 +2배" in duel.lev_note_for_pick({"ticker": "122630", "name": "KODEX 레버리지", "exit": "d5_close"})


@pytest.fixture
def dec_file(tmp_path, monkeypatch):
    p = tmp_path / "decisions.json"
    monkeypatch.setattr(decisions, "OUT", p)
    return p


def test_pick_records_lev_drag(dec_file):
    msg = duel.apply_issue(f"pick {D}", "122630 1000000 5일", OK_AT)
    me = next(x for x in json.loads(dec_file.read_text(encoding="utf-8"))["items"] if x["id"] == f"{D}-entry")["picks"]["나"]
    assert "끌림" in me["lev_drag"] and "4일 보유" in me["lev_drag"] and "⚠" in msg
    duel.apply_issue(f"pick {D}", "069500 1000000", OK_AT)
    me = next(x for x in json.loads(dec_file.read_text(encoding="utf-8"))["items"] if x["id"] == f"{D}-entry")["picks"]["나"]
    assert "lev_drag" not in me


def test_ticket_notes_lev_drag(monkeypatch, tmp_path):
    monkeypatch.setattr(ticket, "REPORT_DIR", tmp_path)   # detail 없음 → 이름은 NAMES 표
    tk = {"code": "122630", "market": "KR", "entry": 100.0, "stop": 95.0, "target": 120.0, "why": "t", "horizon_days": 6}
    ev = ticket.evaluate(tk, f"{D}T02:00:00Z")
    assert any("레버리지·인버스 금지" in r for r in ev["reasons"])
    assert any("6일 보유" in r and "끌림" in r for r in ev["reasons"])
