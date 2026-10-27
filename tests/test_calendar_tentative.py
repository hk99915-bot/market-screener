"""calendar_ev 날짜 미정(TENTATIVE) 일정 — 가짜 날짜 금지 (req-dev-dbd49e21 → 묶음 C ③)."""
from datetime import date

from screener import calendar_ev as C


def test_tentative_has_no_date_and_never_enters_events():
    rows = C.tentative(date(2026, 10, 27))
    assert rows and all(r["tentative"] and "date" not in r for r in rows)
    assert any("잠재성장률" in r["name"] for r in rows)
    names = {n for _, n, _, _ in C.MACRO}
    assert not names & {n for n, _, _, _ in C.TENTATIVE}          # MACRO 에 가짜 날짜로 중복 등록 안 됨
    assert all(len(by) in (4, 7) for _, by, _, _ in C.TENTATIVE)    # 기한 = 'YYYY' 또는 'YYYY-MM'


def test_tentative_label_and_overdue():
    r = {x["name"]: x for x in C.tentative(date(2027, 1, 5))}
    w = r["한은 잠재성장률 워킹페이퍼 공개"]
    assert w["overdue"] and w["label"] == "날짜 미정 (2026년 12월 중)"
    assert not C.tentative(date(2026, 10, 27))[0]["overdue"]


def test_upcoming_ignores_tentative(tmp_path, monkeypatch):
    import json
    fp = tmp_path / "calendar.json"
    fp.write_text(json.dumps({"events": [], "tentative": C.tentative(date(2026, 10, 27))}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(C, "OUT", fp)
    assert C.upcoming(60) == []
