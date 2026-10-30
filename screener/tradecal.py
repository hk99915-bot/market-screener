"""거래일 달력 (KR·US) — '지금 기대되는 최신 확정 봉 날짜' 계산.

2026-10-17 사고(토 09:46 KST 수동 detail_us 가 US 기준일을 10/16→10/15 로 역행)의 1차 원인은
"지금이면 어느 날짜 봉이 있어야 하는가"를 코드가 몰랐다는 것. 이 모듈이 그 기준을 한 곳에 둔다.

휴장일 표: KRX(한국거래소)·NYSE 공지 기준 2026~2027. [확인 필요: 2027 KR 음력 휴일·대체공휴일을 KRX 연말 공지와 대조, 2026-12-31 까지]
표 범위 밖 날짜는 주말만 휴장으로 본다(freshness 가 표 만료 45일 전부터 경고).
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
ET = ZoneInfo("America/New_York")
TZ = {"KR": KST, "US": ET}

HOLIDAYS: dict[str, frozenset[str]] = {
    "KR": frozenset({
        # 2026: 신정 · 설(2/16~18) · 삼일절 대체(3/2) · 근로자의날(KRX 휴장) · 어린이날 · 부처님오신날 대체(5/25)
        #       · 지방선거(6/3) · 광복절 대체(8/17) · 추석(9/24~25) · 개천절 대체(10/5) · 한글날 · 성탄절 · 연말 휴장
        "2026-01-01", "2026-02-16", "2026-02-17", "2026-02-18", "2026-03-02", "2026-05-01", "2026-05-05",
        "2026-05-25", "2026-06-03", "2026-08-17", "2026-09-24", "2026-09-25", "2026-10-05", "2026-10-09",
        "2026-12-25", "2026-12-31",
        # 2027: 신정 · 설(2/5, 2/8 대체) · 삼일절 · 어린이날 · 부처님오신날 · 광복절 대체 · 추석(9/14~16)
        #       · 개천절 대체(10/4) · 한글날 대체(10/11) · 성탄절 대체(12/27) · 연말 휴장
        "2027-01-01", "2027-02-05", "2027-02-08", "2027-03-01", "2027-05-05", "2027-05-13", "2027-08-16",
        "2027-09-14", "2027-09-15", "2027-09-16", "2027-10-04", "2027-10-11", "2027-12-27", "2027-12-31",
    }),
    "US": frozenset({
        "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25", "2026-06-19", "2026-07-03",
        "2026-09-07", "2026-11-26", "2026-12-25",
        "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31", "2027-06-18", "2027-07-05",
        "2027-09-06", "2027-11-25", "2027-12-24",
    }),
}
# 정규장 시간(현지): 마감 확정치가 나오는 기준
SESSION = {"KR": (time(9, 0), time(15, 30)), "US": (time(9, 30), time(16, 0))}


def covered_until(market: str) -> date:
    """휴장일 표가 다루는 마지막 해의 12/31."""
    return date(max(int(d[:4]) for d in HOLIDAYS[market]), 12, 31)


def is_session(market: str, d: date) -> bool:
    return d.weekday() < 5 and d.isoformat() not in HOLIDAYS[market]


def prev_session(market: str, d: date) -> date:
    """d 보다 엄격히 앞선 마지막 거래일."""
    x = d - timedelta(days=1)
    while not is_session(market, x):
        x -= timedelta(days=1)
    return x


def session_on_or_before(market: str, d: date) -> date:
    return d if is_session(market, d) else prev_session(market, d)


def expected_session(market: str, now: datetime, ready: str | None = None, tz: str | None = None,
                     day_offset: int = 0, grace_min: int = 0) -> date:
    """`now` 시점에 이미 나와 있어야 하는 최신 거래일.

    거래일 d 의 데이터는 (d + day_offset일) 의 `ready` 시각(tz 기준) + grace_min 에 준비된다고 본다.
    기본 ready = 그 시장 정규장 마감 + 30분(현지). 예) US, now=2026-10-17 09:46 KST(=10/16 20:46 ET) → 2026-10-16.
    """
    zone = ZoneInfo(tz) if tz else TZ[market]
    if ready is None:
        c = SESSION[market][1]
        rt = (datetime.combine(date(2000, 1, 1), c) + timedelta(minutes=30)).time()
        zone = TZ[market]
    else:
        hh, mm = ready.split(":")
        rt = time(int(hh), int(mm))
    if now.tzinfo is None:
        now = now.replace(tzinfo=KST)
    d = session_on_or_before(market, now.astimezone(TZ[market]).date() + timedelta(days=1))
    for _ in range(30):
        ready_at = datetime.combine(d + timedelta(days=day_offset), rt, tzinfo=zone) + timedelta(minutes=grace_min)
        if ready_at <= now:
            return d
        d = prev_session(market, d)
    return d


def in_session(market: str, now: datetime) -> bool:
    loc = now.astimezone(TZ[market])
    o, c = SESSION[market]
    return is_session(market, loc.date()) and o <= loc.time() < c


def us_open_kst(d) -> datetime:
    """미 정규장 개장(09:30 ET)의 KST 시각 — 서머타임(3월 둘째 일~11월 첫째 일)은 America/New_York 이 계산.
    2026-10-30 확인: 여름 22:30, 겨울(11/1 뒤) 23:30. KST 22:30 하드코딩 금지 — 이 함수를 쓴다(req-dev-cbd568fc)."""
    if isinstance(d, str):
        d = date.fromisoformat(d[:10])
    return datetime.combine(d, SESSION["US"][0], tzinfo=ET).astimezone(KST)


def us_open_hhmm(d) -> str:
    """us_open_kst 의 'HH:MM' (문자열 비교용)."""
    return us_open_kst(d).strftime("%H:%M")
