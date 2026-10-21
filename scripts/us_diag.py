"""야후 US 일봉 마지막 날 진단 (req-data-75288029, 10/21). .github/workflows/us_diag.yml 이 Actions 에서 실행 — 로그만, 커밋 없음.

yfinance 호출 방식 3가지(start만 / start+end=내일 / Ticker.history period=5d) + 대체 소스(Stooq CSV, Nasdaq historical) 의
최근 5행을 찍어 마지막 날 행 유무·NaN 여부를 비교한다.
"""
from __future__ import annotations

import os
from datetime import date, timedelta

import requests

SYMS = [s.strip() for s in os.environ.get("SYMS", "AAPL,MSFT,NVDA,SPY").split(",") if s.strip()]
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"}


def show(tag, df):
    print(f"--- {tag}")
    if df is None or len(df) == 0:
        print("  (빈 결과)")
        return
    print(df.tail(5).to_string())


def main() -> None:
    import yfinance as yf
    print("yfinance", yf.__version__, "today(UTC runner)", date.today())
    start = (date.today() - timedelta(days=10)).isoformat()
    end = (date.today() + timedelta(days=1)).isoformat()
    try:
        raw = yf.download(SYMS, start=start, auto_adjust=True, group_by="ticker", progress=False, threads=True)
        for s in SYMS:
            show(f"A download start만 {s}", raw[s] if s in raw.columns.get_level_values(0) else None)
    except Exception as e:  # noqa: BLE001
        print("A 실패", e)
    try:
        raw = yf.download(SYMS, start=start, end=end, auto_adjust=True, group_by="ticker", progress=False, threads=True)
        for s in SYMS:
            show(f"B download start+end=내일 {s}", raw[s] if s in raw.columns.get_level_values(0) else None)
    except Exception as e:  # noqa: BLE001
        print("B 실패", e)
    try:
        raw = yf.download(SYMS, period="5d", auto_adjust=True, group_by="ticker", progress=False, threads=True)
        for s in SYMS:
            show(f"B2 download period=5d {s}", raw[s] if s in raw.columns.get_level_values(0) else None)
    except Exception as e:  # noqa: BLE001
        print("B2 실패", e)
    for s in SYMS:
        try:
            show(f"C Ticker.history period=5d {s}", yf.Ticker(s).history(period="5d", auto_adjust=True))
        except Exception as e:  # noqa: BLE001
            print("C 실패", s, e)
    for s in SYMS[:3]:
        try:
            r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{s}?range=5d&interval=1d", headers=UA, timeout=20)
            j = r.json()["chart"]["result"][0]
            q = j["indicators"]["quote"][0]
            print(f"--- D chart API raw {s} HTTP {r.status_code}")
            for t, c, v in zip(j.get("timestamp") or [], q.get("close") or [], q.get("volume") or []):
                print("  ", date.fromtimestamp(t), c, v)
            m = j.get("meta") or {}
            print("   meta regularMarketTime", m.get("regularMarketTime"), "price", m.get("regularMarketPrice"))
        except Exception as e:  # noqa: BLE001
            print("D 실패", s, type(e).__name__, e)
    for s in SYMS[:3]:
        try:
            r = requests.get(f"https://stooq.com/q/d/l/?s={s.lower().replace('-', '.')}.us&i=d", headers=UA, timeout=20)
            print(f"--- E Stooq {s} HTTP {r.status_code}")
            print("\n".join(r.text.strip().splitlines()[-4:]))
        except Exception as e:  # noqa: BLE001
            print("E 실패", s, type(e).__name__, e)
    for s in SYMS[:3]:
        try:
            r = requests.get(f"https://api.nasdaq.com/api/quote/{s}/historical?assetclass={'etf' if s == 'SPY' else 'stocks'}"
                             f"&fromdate={start}&todate={end}&limit=10", headers={**UA, "Accept": "application/json"}, timeout=20)
            rows = ((r.json().get("data") or {}).get("tradesTable") or {}).get("rows") or []
            print(f"--- F Nasdaq {s} HTTP {r.status_code}")
            for x in rows[:4]:
                print("  ", x)
        except Exception as e:  # noqa: BLE001
            print("F 실패", s, type(e).__name__, e)


if __name__ == "__main__":
    main()
