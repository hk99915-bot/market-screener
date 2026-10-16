"""ticket.apply_ticket_issue — 주문표 파싱·규칙 검사(손익비·레버리지·개장 30분·추격 절반)·공개 금액 규칙."""
import json

import pytest

from screener import decisions, ticket

D = "2026-10-16"
OK_AT = f"{D}T05:00:00Z"      # 14:00 KST
OPEN_AT = f"{D}T00:15:00Z"    # 09:15 KST
BODY = "매수가 10,000\n손절가 9,500\n목표가 11,500\n근거: 20일선 되돌림 지지\n보유 5일\n"


@pytest.fixture
def env(tmp_path, monkeypatch):
    """결정 파일·상세 데이터·이벤트를 임시 폴더로 — 네트워크·실제 저장소 데이터 없이 검사."""
    rep = tmp_path / "reports"
    (rep / "detail" / "KR").mkdir(parents=True)
    (rep / "detail" / "US").mkdir(parents=True)
    (rep / "detail" / "KR" / "000001.json").write_text(json.dumps({"name": "테스트전자", "close": 10000, "stats": {"rsi14": 45, "ret1": 0.01}}), encoding="utf-8")
    (rep / "detail" / "KR" / "000002.json").write_text(json.dumps({"name": "급등주", "close": 10500, "stats": {"rsi14": 55, "ret1": 0.07}}), encoding="utf-8")
    (rep / "detail" / "KR" / "122630.json").write_text(json.dumps({"name": "KODEX 레버리지", "close": 10000, "stats": {}}), encoding="utf-8")
    (rep / "events.json").write_text(json.dumps({"events": []}), encoding="utf-8")
    (rep / "calendar.json").write_text(json.dumps({"events": []}), encoding="utf-8")
    monkeypatch.setattr(ticket, "REPORT_DIR", rep)
    monkeypatch.setattr(decisions, "OUT", rep / "decisions.json")
    monkeypatch.delenv("SAT_BOOK_KRW", raising=False)
    monkeypatch.delenv("RISK_PCT", raising=False)
    monkeypatch.delenv("MY_RULES", raising=False)
    return rep


def _item(rep, code):
    return next(x for x in json.loads((rep / "decisions.json").read_text(encoding="utf-8"))["items"] if x["id"] == f"{D}-ticket-{code}")


def test_parse_ok_and_record(env):
    msg = ticket.apply_ticket_issue("ticket 000001", BODY + "금액 800000", OK_AT)
    it = _item(env, "000001")
    assert "✅ 통과" in msg and "| 손익비 | 1:3.0 |" in msg
    assert it["kind"] == "ticket" and it["entry"] == 10000 and it["stop"] == 9500 and it["target"] == 11500
    assert it["rr"] == 3.0 and it["horizon_days"] == 5 and it["why"] == "20일선 되돌림 지지"
    assert it["stop_eff"] == 9500 and it["qty_max"] == 15          # 3,000,000 × 0.25% = 7,500 ÷ 500
    assert it["notional"] == 800000 and it["picks"] == {} and it["submitted"].endswith("14:00")


def test_big_amount_stored_as_pct_only(env):
    ticket.apply_ticket_issue("ticket 000001", BODY + "금액 1,500,000", OK_AT)
    it = _item(env, "000001")
    assert "notional" not in it and it["notional_pct"] == 50.0
    assert "3000000" not in json.dumps(it) and "1500000" not in json.dumps(it)


def test_rr_below_2_rejected(env):
    msg = ticket.apply_ticket_issue("ticket 000001", "매수가 10000\n손절가 9500\n목표가 10800\n근거: 감\n보유 3일", OK_AT)
    assert "⛔ 거부" in msg and "손익비 1:1.6" in msg
    assert _item(env, "000001")["verdict"].startswith("⛔")


def test_hard_stop_8pct_is_effective_stop(env):
    ticket.apply_ticket_issue("ticket 000001", "매수가 10000\n손절가 8500\n목표가 13500\n근거: 바닥\n보유 10일", OK_AT)
    it = _item(env, "000001")
    assert it["stop_eff"] == 9200 and it["qty_max"] == 9          # 7,500 ÷ 800


def test_leverage_rejected(env):
    msg = ticket.apply_ticket_issue("ticket 122630", BODY, OK_AT)
    assert "⛔ 거부" in msg and "레버리지" in msg


def test_open_30min_rejected(env):
    msg = ticket.apply_ticket_issue("ticket 000001", BODY, OPEN_AT)
    assert "⛔ 거부" in msg and "09:00–09:30" in msg


def test_chase_half_size(env):
    msg = ticket.apply_ticket_issue("ticket 000002", "매수가 10500\n손절가 10000\n목표가 11600\n근거: 돌파\n보유 5일", OK_AT)
    it = _item(env, "000002")
    assert "⚠️ 절반 사이징" in msg and it["half"] and it["qty_max"] == 7   # 15 → 절반


def test_halt_event_today_rejected(env):
    (env / "events.json").write_text(json.dumps({"events": [{"date": D, "time": "12:57", "market": "KOSDAQ", "type": "매수 사이드카"}]}), encoding="utf-8")
    assert "사이드카" in ticket.apply_ticket_issue("ticket 000001", BODY, OK_AT)


def test_missing_field_message(env):
    msg = ticket.apply_ticket_issue("ticket 000001", "매수가 10000\n손절가 9500", OK_AT)
    assert "빠진 항목" in msg and "목표가" in msg
