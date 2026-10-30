"""toss_md 신선도: 창 밖에서 장 전(04:10) publish 를 '오늘 장중분'으로 통과시키지 않는다 (10/30 데이터 라운드)."""
from datetime import datetime
from zoneinfo import ZoneInfo

from screener import toss_live

KST = ZoneInfo("Asia/Seoul")
IT = {"window": "09:30-15:40", "max_age_min": 30}


def test_premarket_publish_is_late_after_close():
    now = datetime(2026, 10, 30, 20, 54, tzinfo=KST)   # 금, 장 마감 뒤
    r = toss_live.check_late("2026-10-30T04:10:14+09:00", now, IT)
    assert r is not None and r[0] == "2026-10-30 장중 publish"


def test_intraday_publish_ok_after_close():
    now = datetime(2026, 10, 30, 20, 54, tzinfo=KST)
    assert toss_live.check_late("2026-10-30T15:35:00+09:00", now, IT) is None


def test_before_window_expects_previous_session():
    now = datetime(2026, 10, 30, 8, 0, tzinfo=KST)     # 창 시작 전 → 기대 = 전 거래일(10/29) 장중
    assert toss_live.check_late("2026-10-29T15:30:00+09:00", now, IT) is None
    assert toss_live.check_late("2026-10-29T08:00:00+09:00", now, IT) is not None
