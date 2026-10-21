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
    print(df.tail(3).to_string())


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


def full() -> None:
    """실제 파이프라인 경로(data.fetch_prices, 배치 150·threads 8·400일)로 유니버스 전체 → 종목별 마지막 날짜 분포 + 원시 NaN 점검."""
    import collections
    import sys

    import pandas as pd
    import yfinance as yf
    sys.path.insert(0, ".")
    from screener import data
    from screener.config import CFG
    syms = [x.strip() for x in open("universe/us_index.csv", encoding="utf-8").read().split()[1:] if x.strip()]
    px = data.fetch_prices(syms, "DIAG")
    last = px.group_by("yf").agg(__import__("polars").col("date").max())
    dist = collections.Counter(str(d) for d in last["date"].to_list())
    print("FULL fetch_prices 종목", len(syms), "수신", last.height, "마지막날 분포", dict(dist))
    lag = sorted(last.filter(last["date"] < max(last["date"]))["yf"].to_list())
    print("마지막날 뒤처진 종목 수", len(lag), "예", lag[:15])
    # 원시: 첫 배치 그대로 받아 마지막 2일 Close NaN 개수
    start = (date.today() - timedelta(days=CFG.lookback_days)).isoformat()
    raw = yf.download(syms[:CFG.batch_size], start=start, auto_adjust=True, group_by="ticker",
                      threads=CFG.threads, progress=False, timeout=60)
    idx = pd.to_datetime(raw.index)
    print("원시 배치1 인덱스 마지막 3", [str(x.date()) for x in idx[-3:]])
    for d in idx[-2:]:
        row = raw.loc[d]
        closes = row.xs("Close", level=1) if hasattr(row.index, "levels") else row
        print("  ", d.date(), "Close NaN", int(closes.isna().sum()), "/", len(closes))


if __name__ == "__main__":
    if os.environ.get("FULL") == "1":
        full()
    else:
        main()
