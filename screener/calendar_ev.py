"""실적·이벤트 캘린더 → reports/calendar.json

- 미국 매크로: FOMC·CPI·고용·PCE·GDP (공식 일정 기준 수기 입력, 출처: fedratecalc.com 2026-09 확인 / 연준·BLS·BEA 일정)
- 국내 파생 만기: 매월 둘째 목요일 (3·6·9·12월은 동시만기)
- 실적 발표일: 야후 calendar (미국 빅테크·반도체, 국내 시총 상위) — 예정일은 회사 공시 전 추정치일 수 있음
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta

from .config import REPORT_DIR

log = logging.getLogger(__name__)
OUT = REPORT_DIR / "calendar.json"
MACRO = [   # (날짜 KST 기준, 이름, 메모, 중요도)  — 미국 발표는 한국 시간 다음날 새벽/밤
    ("2026-10-28", "FOMC 금리 결정", "10/28 14:00 ET → 한국 10/29 03:00", 3),
    ("2026-10-29", "미 PCE·GDP(3Q 속보)", "08:30 ET → 한국 21:30", 2),
    ("2026-11-06", "미 고용보고서(10월)", "08:30 ET → 한국 22:30", 2),
    ("2026-11-10", "미 CPI(10월)", "08:30 ET → 한국 22:30", 3),
    ("2026-11-25", "미 PCE·GDP(3Q 잠정)", "08:30 ET → 한국 22:30", 1),
    ("2026-12-04", "미 고용보고서(11월)", "08:30 ET → 한국 22:30", 2),
    ("2026-12-09", "FOMC 금리 결정", "12/9 14:00 ET → 한국 12/10 04:00", 3),
    ("2026-12-10", "미 CPI(11월)", "08:30 ET → 한국 22:30", 3),
    ("2026-12-23", "미 PCE·GDP(3Q 확정)", "08:30 ET → 한국 22:30", 1),
]
US_EARN = ["MSFT", "GOOGL", "AMZN", "META", "AAPL", "NVDA", "AVGO", "AMD", "MU", "SNDK", "TSM", "ASML", "AMAT", "LRCX", "KLAC",
           "TSLA", "INTC", "QCOM", "ORCL", "CRM", "NFLX", "WDC", "STX", "DELL", "SMCI", "ARM", "MRVL", "GEV", "VRT", "ETN"]
KR_EARN = ["005930", "000660", "009150", "373220", "207940", "005380", "000270", "068270", "035420", "035720", "105560", "055550",
           "012450", "042660", "329180", "009540", "267260", "034020", "006400", "051910", "066570", "011070", "402340", "028260"]
CAPEX = {"MSFT", "GOOGL", "AMZN", "META", "ORCL"}   # 빅테크 설비투자 가이던스 — 메모리 매도 규칙과 연결
CHIP = {"NVDA", "MU", "SNDK", "AVGO", "AMD", "TSM", "ASML", "AMAT", "LRCX", "KLAC", "000660", "005930", "WDC", "STX", "ARM", "MRVL"}


def _second_thursday(y: int, m: int) -> date:
    d = date(y, m, 1)
    while d.weekday() != 3:
        d += timedelta(days=1)
    return d + timedelta(days=7)


def _earn_dates(tickers: list[str], suffix: str = "") -> dict[str, str]:
    from concurrent.futures import ThreadPoolExecutor

    import yfinance as yf

    def one(t):
        try:
            cal = yf.Ticker(t + suffix).calendar
            ds = (cal or {}).get("Earnings Date") if isinstance(cal, dict) else None
            if ds:
                d = ds[0] if isinstance(ds, list) else ds
                return t, str(d)[:10]
        except Exception:  # noqa: BLE001
            pass
        return t, None
    with ThreadPoolExecutor(max_workers=8) as ex:
        return {t: d for t, d in ex.map(one, tickers) if d}


def build(days: int = 75) -> dict:
    today = date.today()
    end = today + timedelta(days=days)
    ev = []
    for d, n, note, imp in MACRO:
        if today <= date.fromisoformat(d) <= end:
            ev.append({"date": d, "type": "매크로", "name": n, "note": note, "imp": imp})
    for k in range(0, 4):
        y, m = (today.year + (today.month - 1 + k) // 12), ((today.month - 1 + k) % 12) + 1
        d = _second_thursday(y, m)
        if today <= d <= end:
            dual = m in (3, 6, 9, 12)
            ev.append({"date": str(d), "type": "만기", "name": "국내 " + ("선물·옵션 동시만기" if dual else "옵션 만기"),
                       "note": "장 막판 프로그램 물량 출렁임", "imp": 2 if dual else 1})
    names = {}
    for mk in ("KR", "US"):
        p = REPORT_DIR / "detail" / mk / "_index.json"
        if p.exists():
            names.update((json.loads(p.read_text(encoding="utf-8")).get("names") or {}))
    try:
        us = _earn_dates(US_EARN)
    except Exception as e:  # noqa: BLE001
        log.warning("미장 실적일 실패: %s", e)
        us = {}
    try:
        kr = _earn_dates(KR_EARN, ".KS")
    except Exception as e:  # noqa: BLE001
        log.warning("국장 실적일 실패: %s", e)
        kr = {}
    for t, d in {**us, **kr}.items():
        try:
            dd = date.fromisoformat(d)
        except ValueError:
            continue
        if not (today - timedelta(days=1) <= dd <= end):
            continue
        tags = []
        if t in CAPEX:
            tags.append("설비투자 가이던스 — 메모리 매도 규칙 체크")
        if t in CHIP:
            tags.append("반도체")
        nm = str(names.get(t, t))
        for cut in (" - Common Stock", ", Inc.", " Inc.", " Corporation", " Corp."):
            nm = nm.split(cut)[0]
        ev.append({"date": d, "type": "실적", "name": f"{nm} 실적", "ticker": t, "market": "KR" if t.isdigit() else "US",
                   "note": " · ".join(tags) + (" · 미국 장후 발표가 많음 → 한국 다음날 반영" if not t.isdigit() else ""),
                   "imp": 3 if t in CAPEX or t in ("NVDA", "MU", "000660", "005930") else 2 if t in CHIP else 1})
    ev.sort(key=lambda e: (e["date"], -e["imp"]))
    out = {"asof": datetime.now().strftime("%Y-%m-%d %H:%M"), "events": ev,
           "note": "실적일은 야후 기준 예정일(회사 확정 전 추정 포함). 매크로 일정은 연준·BLS·BEA 공식 일정 기준."}
    OUT.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    log.info("캘린더 %d건", len(ev))
    return out


def upcoming(n_days: int = 2) -> list[dict]:
    try:
        ev = json.loads(OUT.read_text(encoding="utf-8")).get("events", [])
    except Exception:  # noqa: BLE001
        return []
    t = date.today()
    return [e for e in ev if t <= date.fromisoformat(e["date"]) <= t + timedelta(days=n_days)]
