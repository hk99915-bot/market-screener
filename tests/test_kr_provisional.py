"""macro_series KR 지수 16:20 전 '잠정' 표시 (req-dev-082223e8 → 묶음 C ①)."""
from datetime import datetime
from zoneinfo import ZoneInfo

from screener.main import kr_provisional

KST = ZoneInfo("Asia/Seoul")
SER = {"KOSPI": [["2026-10-21", 1, 1, 1, 1, 0], ["2026-10-22", 1, 1, 1, 5539.94, 0]],
       "KOSDAQ": [["2026-10-22", 1, 1, 1, 1, 0]], "SPX": [["2026-10-22", 1, 1, 1, 1, 0]]}


def test_before_1620_today_bar_is_provisional():
    assert kr_provisional(SER, datetime(2026, 10, 22, 15, 55, tzinfo=KST)) == {"KOSPI": "2026-10-22", "KOSDAQ": "2026-10-22"}


def test_after_1620_or_old_bar_is_confirmed():
    assert kr_provisional(SER, datetime(2026, 10, 22, 16, 20, tzinfo=KST)) == {}
    assert kr_provisional(SER, datetime(2026, 10, 23, 8, 50, tzinfo=KST)) == {}     # 어제 봉은 16:20 실행에서 확정
    assert kr_provisional({}, datetime(2026, 10, 22, 15, 0, tzinfo=KST)) == {}
