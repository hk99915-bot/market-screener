"""결재 #14 (10/17 14:09): 모의 레버리지 ETF 보유 상한 1일(리셋 비용 라벨) · 매도/포상 후 30분 쿨다운(새 모의 베팅 거부, 남은 분) ·
나🔥 해금 근거 제외 라벨. 새 제출부터만 — 기존 기록은 건드리지 않는다."""
import json
from datetime import datetime

import pytest

from screener import decisions, defs, duel, ticket

D = "2026-10-20"
OK_AT = f"{D}T05:00:00Z"   # 14:00 KST
KST = duel.KST


@pytest.fixture
def dec_file(tmp_path, monkeypatch):
    p = tmp_path / "decisions.json"
    monkeypatch.setattr(decisions, "OUT", p)
    monkeypatch.setattr(ticket, "COOLDOWN_FILE", tmp_path / "cooldown.json")
    monkeypatch.delenv("COOLDOWN_LAST_AT", raising=False)
    return p


def _me(p, iid=f"{D}-entry", slot="나"):
    return next(x for x in json.loads(p.read_text(encoding="utf-8"))["items"] if x["id"] == iid)["picks"][slot]


def test_lev_list_in_defs():
    for k in ("SOXL", "TQQQ", "252670", "122630"):
        assert k in defs.MOCK_LEV_ETFS
    assert duel.lev_factor("252670") == -2 and duel.lev_factor("SOXL", market="US") == 3 and defs.MOCK_LEV_HOLD_DAYS == 1


def test_lev_cap_kr_us_and_plain():
    p = duel.lev_cap({"ticker": "252670", "name": "곱버스", "exit": "trail", "notional": 1e6}, "KR")
    assert p["exit"] == "next_close" and "−2" not in p["lev_cap"] and "-2배" in p["lev_cap"] and p["lev_drag"].startswith("리셋 비용")
    assert duel.lev_cap({"ticker": "122630", "exit": "next_open"}, "KR")["exit"] == "next_open"           # 1일 이내 청산은 그대로, 라벨만
    assert duel.lev_cap({"ticker": "SOXL", "exit": "d5_close"}, "US")["exit"] == "same_close"
    plain = {"ticker": "069500", "exit": "d5_close"}
    assert duel.lev_cap(plain, "KR") == plain and duel.lev_cap({"cash": True}) == {"cash": True}


def test_us_pick_capped(dec_file):
    msg = duel.apply_issue(f"pick-us {D}", "TQQQ 1000000 5일", f"{D}T05:00:00Z")
    me = _me(dec_file, f"{D}-entry-us")
    assert me["exit"] == "same_close" and "lev_cap" in me and "⏱" in msg


def test_cooldown_after_sell_blocks_bet_with_countdown(dec_file):
    decisions.OUT.write_text(json.dumps({"items": [{"id": f"{D}-exit-000660", "date": D, "kind": "exit", "title": "매도 타점 대결 · SK하이닉스",
                                                    "picks": {"나": {"cash": True, "label": "매도", "submitted": "13:45"}}}]}), encoding="utf-8")
    msg = duel.apply_issue(f"pick {D}", "069500 1000000", OK_AT)            # 14:00 = 매도 15분 뒤
    assert msg.startswith("⏳ 쿨다운") and "16분 남음" in msg and "14:15 이후" in msg
    assert duel.apply_issue(f"pick {D}", "현금", OK_AT).startswith("기록 완료")   # 현금은 베팅 아님 → 받음
    assert duel.apply_issue(f"pick {D}", "069500 1000000", f"{D}T05:16:00Z").startswith("기록 완료")   # 14:16 = 해제


def test_cooldown_after_reward_file(dec_file, tmp_path):
    (tmp_path / "cooldown.json").write_text(json.dumps({"events": [{"at": f"{D} 13:50", "what": "포상"}]}), encoding="utf-8")
    msg = duel.apply_issue(f"pick🔥 {D}", "122630 1000000 종가\n근거: x", OK_AT)
    assert msg.startswith("⏳ 쿨다운") and "포상" in msg
    assert duel.mock_cooldown(datetime(2026, 10, 20, 14, 21, tzinfo=KST)) is None


def test_ticket_verdict_does_not_block_mock_bet(dec_file):
    decisions.OUT.write_text(json.dumps({"items": [{"id": f"{D}-ticket-x", "date": D, "kind": "ticket", "submitted": f"{D} 13:55", "code": "x", "verdict": "✅"}]}), encoding="utf-8")
    assert duel.mock_cooldown(datetime(2026, 10, 20, 14, 0, tzinfo=KST)) is None


def test_bold_pick_marked_not_unlock_evidence(dec_file):
    duel.apply_issue(f"pick🔥 {D}", "069500 1000000 종가\n근거: y", OK_AT)
    assert _me(dec_file, slot="나🔥")["unlock_evidence"] is False


def test_no_retroactive_change(dec_file):
    old = {"items": [{"id": "2026-10-10-entry", "date": "2026-10-10", "kind": "entry", "title": "t",
                      "picks": {"나": {"ticker": "122630", "exit": "d5_close", "notional": 1e6}, "PB": {"cash": True}}}]}
    decisions.OUT.write_text(json.dumps(old), encoding="utf-8")
    duel.apply_issue(f"pick {D}", "122630 1000000 5일", OK_AT)
    items = json.loads(decisions.OUT.read_text(encoding="utf-8"))["items"]
    assert items[0]["picks"]["나"] == old["items"][0]["picks"]["나"]
