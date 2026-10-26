"""ticket.apply_ticket_issue — 주문표 파싱·규칙 검사(손익비·레버리지·개장 30분·추격 절반·매도/판정 후 30분 쿨다운)·공개 금액 규칙."""
import json

import pytest

from screener import decisions, renego, ticket

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
    monkeypatch.setattr(renego, "FILE", tmp_path / "renego.json")   # 실제 ops/renego.json 에 기록이 생겨도 이 테스트는 영향 없음
    monkeypatch.delenv("SAT_BOOK_KRW", raising=False)
    monkeypatch.delenv("RISK_PCT", raising=False)
    monkeypatch.delenv("MY_RULES", raising=False)
    monkeypatch.delenv(ticket.COOLDOWN_ENV, raising=False)
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


# ── 결재 #14 ③ 매도·판정·포상 후 30분 쿨다운 (근거: 10/16 보상 직후 레버리지 충동, kb:behavior#22) ──
def _write_items(rep, items):
    (rep / "decisions.json").write_text(json.dumps({"items": items}, ensure_ascii=False), encoding="utf-8")


def _exit_sell(code, hhmm):
    return {"id": f"{D}-exit-{code}", "date": D, "kind": "exit", "name": "팔린주", "title": "매도 타점 대결 · 팔린주",
            "picks": {"나": {"cash": True, "label": "매도", "submitted": hhmm}, "PB": {"cash": True}}, "basis": {"at": f"{D} {hhmm}"}}


def test_cooldown_after_sell_rejected(env):
    _write_items(env, [_exit_sell("000003", "13:45")])          # 13:45 매도 → 14:00 제출은 15분 뒤
    msg = ticket.apply_ticket_issue("ticket 000001", BODY, OK_AT)
    assert "⛔ 거부" in msg and "30분 쿨다운" in msg and "매도" in msg and "결재 #14" in msg
    assert _item(env, "000001")["verdict"].startswith("⛔")


def test_cooldown_expired_passes(env):
    _write_items(env, [_exit_sell("000003", "13:29")])          # 31분 전 매도 → 통과
    assert "✅ 통과" in ticket.apply_ticket_issue("ticket 000001", BODY, OK_AT)


def test_cooldown_after_previous_ticket_verdict(env):
    ticket.apply_ticket_issue("ticket 000001", BODY, OK_AT)                      # 14:00 판정
    msg = ticket.apply_ticket_issue("ticket 000002", "매수가 10500\n손절가 10000\n목표가 11600\n근거: 돌파\n보유 5일", f"{D}T05:10:00Z")  # 14:10
    assert "⛔ 거부" in msg and "주문표 판정" in msg
    # 거부된 판정도 판정 — 재협상(반복 제출)마다 30분이 다시 간다: 14:31 은 14:10 +21분 → 거부, 15:02 는 14:31 +31분 → 통과
    assert "⛔ 거부" in ticket.apply_ticket_issue("ticket 000001", BODY, f"{D}T05:31:00Z")
    assert "✅ 통과" in ticket.apply_ticket_issue("ticket 000001", BODY, f"{D}T06:02:00Z")


def test_cooldown_env_manual_time(env, monkeypatch):
    monkeypatch.setenv(ticket.COOLDOWN_ENV, f"{D} 13:50")        # 포상·장외 매도 수동 기록(KST)
    msg = ticket.apply_ticket_issue("ticket 000001", BODY, OK_AT)
    assert "⛔ 거부" in msg and "수동 기록" in msg
    _write_items(env, [])                                         # 방금 기록된 판정 제거
    monkeypatch.setenv(ticket.COOLDOWN_ENV, f"{D}T04:00:00Z")     # ISO 13:00 KST → 60분 전 → 통과
    assert "✅ 통과" in ticket.apply_ticket_issue("ticket 000001", BODY, OK_AT)


def test_cooldown_ignores_future_and_hold(env):
    _write_items(env, [_exit_sell("000003", "14:20"),            # 제출(14:00) 이후의 매도는 무시
                       {"id": f"{D}-exit-000004", "date": D, "kind": "exit", "name": "보유주",
                        "picks": {"나": {"ticker": "000004", "notional": 1}, "PB": {"cash": True}}, "basis": {"at": f"{D} 13:50"}}])  # 보유 판단은 매도 아님
    assert "✅ 통과" in ticket.apply_ticket_issue("ticket 000001", BODY, OK_AT)


# ── 헤지 전용 1배 인버스 예외 (겸이 10/26 18:5x 결재, 비공개 rules.txt [2] 예외 줄) ──
def _detail_kr(rep, code, name):
    (rep / "detail" / "KR" / f"{code}.json").write_text(json.dumps({"name": name, "close": 10000, "stats": {}}), encoding="utf-8")


def test_k200_inverse1_hedge_exception_not_rejected(env):
    _detail_kr(env, "114800", "KODEX 인버스")
    msg = ticket.apply_ticket_issue("ticket 114800", BODY, OK_AT)
    it = _item(env, "114800")
    assert "⛔" not in msg and "🟡 헤지 예외 — 조건 확인 필요" in msg and "조건(비공개 rules.txt [2]" in msg
    assert it["verdict"] == "🟡 헤지 예외 — 조건 확인 필요"
    assert not any("금지 (~" in r for r in it["reasons"])


def test_hedge_exception_other_rules_still_apply(env):
    _detail_kr(env, "114800", "KODEX 인버스")
    msg = ticket.apply_ticket_issue("ticket 114800", "매수가 10000\n손절가 9500\n목표가 10800\n근거: 헤지\n보유 5일", OK_AT)
    assert "⛔ 거부" in msg and "손익비" in msg


@pytest.mark.parametrize("code,name", [("252670", "KODEX 200선물인버스2X"), ("251340", "KODEX 코스닥150선물인버스"),
                                       ("122630", "KODEX 레버리지")])
def test_non_hedge_inverse_or_leverage_still_rejected(env, code, name):
    _detail_kr(env, code, name)
    msg = ticket.apply_ticket_issue(f"ticket {code}", BODY, OK_AT)
    assert "⛔ 거부" in msg and "레버리지·인버스 금지" in msg


def test_is_hedge_inverse1_scope():
    assert ticket.is_hedge_inverse1("123310", "TIGER 인버스", "KR")
    assert ticket.is_hedge_inverse1("999999", "ACE 코스피200선물인버스", "KR")
    assert not ticket.is_hedge_inverse1("252670", "KODEX 200선물인버스2X", "KR")
    assert not ticket.is_hedge_inverse1("SH", "ProShares Short S&P500", "US")
