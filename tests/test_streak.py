"""매수 후보 '연속 N일째'·신규 표시 (req-dev-42019d08) — 산식 불변, 표시만."""
from screener import streak

ROWS = [{"date": f"2026-10-{d}", "long": ["DELL", "HOOD"] + ([] if d == "20" else ["NET"])} for d in ("15", "16", "19", "20", "21", "22")]


def test_streak_counts_consecutive_meetings_including_today():
    st = streak.streaks(ROWS, "2026-10-23", ["DELL", "NET", "ECHO"])
    assert st == {"DELL": 7, "NET": 3, "ECHO": 1}   # NET 은 10/20 에 빠져 끊김


def test_mark_new_and_line_and_today_row_ignored():
    rows = ROWS + [{"date": "2026-10-23", "long": ["DELL"]}]   # 오늘 행이 이미 있어도 이중 계산 안 함
    items = [{"s": "DELL"}, {"s": "ECHO"}]
    z = streak.mark(items, rows, "2026-10-23")
    assert items[0]["streak"] == 7 and items[0]["new"] is False
    assert items[1]["streak"] == 1 and items[1]["new"] is True
    assert z["new"] == ["ECHO"] and "최장 DELL 7일째" in z["line"]
    assert streak.tag(items[0]) == "·7일째" and streak.tag(items[1]) == "🆕"


def test_all_repeat_says_no_new_info_and_first_meeting_has_no_new():
    z = streak.mark([{"s": "DELL"}, {"s": "HOOD"}], ROWS, "2026-10-23")
    assert z["new"] == [] and "새 정보 없음" in z["line"]
    first = [{"s": "DELL"}]
    z2 = streak.mark(first, [], "2026-10-15")
    assert first[0]["new"] is False and z2["line"] == ""
