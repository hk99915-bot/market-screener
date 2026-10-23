"""운용회의 일정 한국 날짜 (req-dev-d624b9cc, 파생 10/24): 미국 이벤트 date 는 현지 날짜라
'FOMC 10-28 03:00' 처럼 KST 시각만 붙이면 하루 틀린다 → 메모 '한국 M/D' 날짜 사용. 시계(_v2_clock)도 같은 기준."""
from datetime import date

from screener import committee as c

FOMC = {"date": "2026-10-28", "type": "매크로", "name": "FOMC 금리 결정", "note": "10/28 14:00 ET → 한국 10/29 03:00", "imp": 3}


def test_kst_date_from_note():
    assert c._ev_kst_date(FOMC) == "2026-10-29"
    assert c._ev_kst_date({"date": "2026-10-23", "note": "한국 21:30"}) == "2026-10-23"
    assert c._ev_kst_date({"date": "2026-12-31", "note": "12/31 14:00 ET → 한국 1/1 04:00"}) == "2027-01-01"
    assert c._ev_kst_date({"date": "2026-11-12", "type": "만기"}) == "2026-11-12"


def test_clock_uses_kst_date():
    on_27 = c._v2_clock({}, {}, {}, [FOMC], date(2026, 10, 27), None)
    on_28 = c._v2_clock({}, {}, {}, [FOMC], date(2026, 10, 28), None)
    assert not [x for x in on_27 if x["kind"] == "이벤트"]          # 이틀 뒤 새벽 — 내일 아님
    assert [x["t"] for x in on_28 if x["kind"] == "이벤트"] == ["내일 03:00"]
