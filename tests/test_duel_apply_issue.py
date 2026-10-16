"""duel.apply_issue — 'pick' / 'pick🔥' 이슈 파싱 (슬롯·청산 방식·근거/감 분리·마감 시각)."""
import json

import pytest

from screener import decisions, duel

D = "2026-10-16"
OK_AT = f"{D}T05:00:00Z"      # 14:00 KST
LATE_AT = f"{D}T07:00:00Z"    # 16:00 KST (15:30 마감 이후)


@pytest.fixture
def dec_file(tmp_path, monkeypatch):
    p = tmp_path / "decisions.json"
    monkeypatch.setattr(decisions, "OUT", p)
    return p


def _item(p):
    data = json.loads(p.read_text(encoding="utf-8"))
    return next(x for x in data["items"] if x["id"] == f"{D}-entry")


def test_pick_basic_next_open(dec_file):
    msg = duel.apply_issue(f"pick {D}", "069500 500000 시가", OK_AT)
    me = _item(dec_file)["picks"]["나"]
    assert msg.startswith("기록 완료")
    assert me["ticker"] == "069500" and me["name"] == "KODEX 200"
    assert me["notional"] == 500000 and me["entry"] == "close" and me["exit"] == "next_open"
    assert me["submitted"] == "14:00"


def test_pick_trail_and_cash(dec_file):
    duel.apply_issue(f"pick {D}", "122630 1000000 추세 끌고가기", OK_AT)
    assert _item(dec_file)["picks"]["나"]["exit"] == "trail"
    duel.apply_issue(f"pick {D}", "현금", OK_AT)
    assert _item(dec_file)["picks"]["나"] == {"cash": True, "submitted": "14:00"}


def test_pick_bold_with_reason_is_judgement(dec_file):
    msg = duel.apply_issue(f"pick🔥 {D}", "122630 500000 종가\n근거: 반도체 수급 반전", OK_AT)
    it = _item(dec_file)
    b = it["picks"]["나🔥"]
    assert "나🔥" in msg
    assert b["exit"] == "next_close"
    assert b["why"] == "반도체 수급 반전" and b["basis"] == "판단"
    assert b["notional"] == 1_000_000          # 공격 픽은 금액 고정
    assert it["picks"]["나"] == {"pending": True}   # '나' 칸은 건드리지 않음


def test_pick_bold_without_reason_is_gut(dec_file):
    duel.apply_issue(f"pick-bold {D}", "069500", OK_AT)
    b = _item(dec_file)["picks"]["나🔥"]
    assert b["why"] == "감" and b["basis"] == "감"


def test_late_or_bad_submission_rejected(dec_file):
    assert "반영하지 않았어" in duel.apply_issue(f"pick {D}", "069500", LATE_AT)
    assert "날짜" in duel.apply_issue("pick", "069500", OK_AT)
    assert "첫 줄" in duel.apply_issue(f"pick {D}", "???", OK_AT)
    assert not dec_file.exists()   # 거절된 제출은 파일을 만들지 않음
