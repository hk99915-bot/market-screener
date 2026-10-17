"""재협상 카운터 (screener/renego.py) + 주문표 ⛔ '재협상 2회째' 사유 칸 (오너 승인 10/17 14:09)."""
import json
from datetime import date

import pytest

from screener import decisions, renego, ticket

D = "2026-10-16"
OK_AT = f"{D}T05:00:00Z"      # 14:00 KST
BODY = "매수가 10,000\n손절가 9,500\n목표가 11,500\n근거: 20일선 되돌림 지지\n보유 5일\n"
REASON = "새벽에 손익비 낮춰 달라고 또 물어봄, 이번엔 실적 발표 전이라는 이유 (비공개 글)"


@pytest.fixture
def rf(tmp_path, monkeypatch):
    f = tmp_path / "renego.json"
    monkeypatch.setattr(renego, "FILE", f)
    return f


@pytest.fixture
def env(tmp_path, rf, monkeypatch):
    rep = tmp_path / "reports"
    (rep / "detail" / "KR").mkdir(parents=True)
    (rep / "detail" / "KR" / "000001.json").write_text(json.dumps({"name": "테스트전자", "close": 10000, "stats": {"rsi14": 45, "ret1": 0.01}}), encoding="utf-8")
    (rep / "events.json").write_text(json.dumps({"events": []}), encoding="utf-8")
    (rep / "calendar.json").write_text(json.dumps({"events": []}), encoding="utf-8")
    monkeypatch.setattr(ticket, "REPORT_DIR", rep)
    monkeypatch.setattr(ticket, "COOLDOWN_FILE", tmp_path / "none.json")
    monkeypatch.setattr(decisions, "OUT", rep / "decisions.json")
    monkeypatch.delenv(ticket.COOLDOWN_ENV, raising=False)
    return rep


def test_add_counts_window_and_schema(rf):
    assert renego.add("MIN_RR", date(2026, 9, 1)) == {"rule": "MIN_RR", "date": "2026-09-01", "count": 1}
    assert renego.add("MIN_RR", date(2026, 10, 10))["count"] == 1          # 30일 밖 → 다시 1회째
    assert renego.active(date(2026, 10, 16)) == []
    assert renego.add("MIN_RR", date(2026, 10, 16))["count"] == 2
    renego.add("SEMI_CAP", date(2026, 10, 16))
    a = renego.active(date(2026, 10, 16))
    assert [x["rule"] for x in a] == ["MIN_RR"] and a[0]["count"] == 2 and a[0]["term"] == "주문표 R:R"
    assert renego.active(date(2026, 11, 20)) == []                          # 기간 지나면 해제
    d = json.loads(rf.read_text(encoding="utf-8"))
    assert all(set(e) == {"rule", "date", "count"} for e in d["events"])  # 공개 파일: id·날짜·횟수만


def test_invalid_rule_rejected(rf):
    with pytest.raises(ValueError):
        renego.add("손익비")
    with pytest.raises(ValueError):
        renego.add("NOT_A_RULE")
    rf.write_text(json.dumps({"events": [{"rule": "BOGUS", "date": "2026-10-16"}, {"rule": "BOGUS", "date": "2026-10-16"}]}), encoding="utf-8")
    assert renego.active(date(2026, 10, 16)) == []                          # 모르는 id 는 세지 않음


def test_ticket_blocked_without_reason(env, rf):
    renego.add("MIN_RR", date(2026, 10, 14))
    renego.add("MIN_RR", date(2026, 10, 16))
    msg = ticket.apply_ticket_issue("ticket 000001", BODY, OK_AT)
    assert "⛔ 거부" in msg and "재협상 2회째" in msg and "사유 칸 필수" in msg
    it = next(x for x in json.loads((env / "decisions.json").read_text(encoding="utf-8"))["items"] if x["kind"] == "ticket")
    assert it["verdict"].startswith("⛔") and it["renego"] == {"rules": ["MIN_RR"], "reason_given": False}


def test_ticket_with_reason_passes_and_reason_not_stored(env, rf):
    renego.add("COOLDOWN_MIN", date(2026, 10, 15))
    renego.add("COOLDOWN_MIN", date(2026, 10, 16))
    msg = ticket.apply_ticket_issue("ticket 000001", BODY + f"재협상사유: {REASON}\n", OK_AT)
    assert "✅ 통과" in msg and "⛔ 재협상 2회째" in msg and "사유 기재됨" in msg
    raw = (env / "decisions.json").read_text(encoding="utf-8")
    assert "실적 발표 전" not in raw and "비공개 글" not in raw and "실적 발표 전" not in msg   # 사유 글은 어디에도 안 남음
    it = next(x for x in json.loads(raw)["items"] if x["kind"] == "ticket")
    assert it["renego"]["reason_given"] is True


def test_ticket_unaffected_when_one_renegotiation(env, rf):
    renego.add("MIN_RR", date(2026, 10, 16))
    msg = ticket.apply_ticket_issue("ticket 000001", BODY, OK_AT)
    assert "✅ 통과" in msg and "재협상" not in msg


def test_repo_file_public_schema():
    d = json.loads(renego.FILE.read_text(encoding="utf-8"))
    for e in d.get("events") or []:
        assert set(e) <= renego.ALLOWED_KEYS and renego.valid_rule(e["rule"])
