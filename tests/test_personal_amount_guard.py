"""개인 금액 가드 (10/25 PB 공개 장부 누출 사고 재발 방지, 감사 req-dev-d026b1af) — ask.py·msgr 피드·prepush·slop_audit.
테스트 문자열의 금액은 조각으로 이어 붙인다(이 파일 자체가 pre-push 금액 검사에 걸리지 않게)."""
import importlib.util
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))
import ask  # noqa: E402
import msgr_feed  # noqa: E402
import slop_audit as sa  # noqa: E402
from screener.redact import personal_amount_hits  # noqa: E402

spec = importlib.util.spec_from_file_location("prepush_check", ROOT / "scripts" / "prepush_check.py")
pc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pc)

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 26, 12, 0, tzinfo=KST)
N1 = "5" + ",000" + "만원"          # 쉼표+단위
N2 = "1" + "2,345" + ",678원"
N3 = "3" + "억"
N4 = "30" + "0만"


@pytest.mark.parametrize("t", [
    f"연봉 {N1} 기준으로 역산", f"내 순자산 {N3} 중 증권 밖", f"부모님 용돈 월 {N4} 지원", f"보유 계좌 {N2}",
    f"청약 월 {N4} 납입", f"월급 {'2' + '50'}M 정도",
])
def test_detects_personal_amounts(t):
    assert personal_amount_hits(t), t


@pytest.mark.parametrize("t", [
    "보유 비중 12.5% 로 줄이자", "순자산 대비 월 적립 비율 3%", f"예시: 연봉이 {N1} 이라고 가정하면 비율은",
    f"가상 예시 — 순자산 {N3} 시나리오", f"순자산 목표 {N3} (겸이 10/24 예외)", f"ETF 1주 25,475원(10/23 종가) 적립 잔차",
    "모의 계좌 고정 사이즈 100" + "만원", "삼성전자 영업이익 6" + "조원 보유 대비", "short_hist ##,###행 잔고".replace("##", "12"),
    "DART 일 2" + "만 콜 한도, 공매도 잔고 백필", "비공개 저장소 ops/agreements.md 참조", "코스피 2,650 지수 보유 비중",
])
def test_allows_ratio_example_and_public_numbers(t):
    assert not personal_amount_hits(t), t


def test_ask_rejects_without_echoing_value():
    L = {"requests": []}
    with pytest.raises(ValueError) as e:
        ask.add(L, "pb", "dev", f"연봉 {N1} 반영해줘", None, NOW)
    assert "5" not in str(e.value).replace("5", "", 0) or N1 not in str(e.value)
    assert N1 not in str(e.value)
    L, r = ask.add(L, "pb", "dev", "연봉 대비 월 저축 비율 20% 로 계산", None, NOW)
    with pytest.raises(ValueError):
        ask.reply(L, r["id"], "dev", f"순자산 {N3} 라서", True, NOW)
    with pytest.raises(ValueError):
        ask.reply(L, r["id"], "dev", f"월급 {N4} 날아감", True, NOW)
    ask.reply(L, r["id"], "dev", "월급 많이 물렸다 ㅠㅠ", True, NOW)   # 숫자 없는 자조는 통과 (사담 --chat 은 10/28 pb-private 로 통합)


def test_msgr_feed_masks_leak_in_ledger(tmp_path):
    led = {"requests": [{"id": "req-dev-aaaaaaaa", "from": "pb", "to": "dev", "text": f"내 연봉 {N1}", "opened": "2026-10-25",
                         "opened_at": "2026-10-25T10:00+09:00", "status": "open",
                         "replies": [{"by": "dev", "at": "2026-10-25T11:00+09:00", "text": "연봉 비율만 쓸게", "voc": True}]}],
           "chat": [{"by": "dev", "at": "2026-10-25T12:00+09:00", "text": f"순자산 {N3} 얘기 금지"}]}
    feed = msgr_feed.build(led, tmp_path, NOW)
    s = json.dumps(feed, ensure_ascii=False)
    assert N1 not in s and N3 not in s and feed["masked"] == 1 and "chat" not in feed   # 사담은 10/28 부터 공개 피드에 안 실음
    assert feed["items"][0]["replies"][0]["text"] == "연봉 비율만 쓸게"


def test_prepush_amount_hits_added_only_and_moved_lines_ignored():
    leak = f'"text": "연봉 {N1} 역산"'
    added = {"a.json": [leak, "순자산 대비 비율 3%"], "b.md": ["보유 12.5%"]}
    assert pc.amount_hits(added) == {"a.json": 1}
    # 지워진 줄에 같은 맥락이 있으면(피드 통째 재생성) 새 누출이 아님
    assert pc.amount_hits({"f.md": [leak + " 새 항목"]}, {"f.md": [leak]}) == {}
    assert pc.amount_hits({"f.md": [leak, leak]}, {"f.md": [leak]}) == {"f.md": 1}


def test_prepush_amount_check_reports_files_not_values(monkeypatch, capsys):
    monkeypatch.setattr(pc, "diff_lines", lambda b, h="HEAD": ({"x.json": [f"연봉 {N1}"]}, {}))
    assert pc.amount_check(None) is False
    out = capsys.readouterr().out
    assert "x.json: 1곳" in out and N1 not in out
    monkeypatch.setattr(pc, "diff_lines", lambda b, h="HEAD": ({}, {}))
    assert pc.amount_check(None) is True


def test_slop_audit_scans_request_ledger_and_feed(tmp_path):
    for rel in ("docs/desk_kb/rounds/_requests.json", "reports/msgr_feed.md"):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{}", encoding="utf-8")
    got = {str(p.relative_to(tmp_path)) for p in sa.collect_paths(tmp_path, None)}
    assert {"docs/desk_kb/rounds/_requests.json", "reports/msgr_feed.md"} <= got
