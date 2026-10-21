"""이벤트 드리븐 연구(reports/studies/2026-10-21_event_driven.md) 원자료 수집 — Actions 전용(컨테이너는 야후·FRED·연준·BLS 차단).

.github/workflows/event_driven_data.yml 이 실행 → data/study/event/* 를 study-data/event-driven-<run_id> 브랜치에만 올린다(main 미변경).

산출물
  idx.csv           지수·변동성·금리·유가 일봉(야후 auto_adjust=False): SPY QQQ ^VIX ^VIX9D ^VIX1D ^TNX CL=F ^KS200 ^KS11 069500.KS
                    열: sym,date,open,high,low,close,adj
  fred.csv          FRED DGS10(미 10년 %)·DCOILWTICO(WTI $) — fredgraph.csv(키 불필요)
  earn_dates.csv    yfinance get_earnings_dates(limit=100): yf,ts(현지시각 포함),eps_est,eps_rep,surprise_pct
                    대상 = universe/us_index.csv(S&P500∪NDX, 2026 구성 — 생존편향) + 국장 시총 상위 30
  stk.parquet       위 종목 일봉(야후 auto_adjust=True: 배당·분할 조정) yf,date,open,high,low,close,volume
  html/*.htm        연준 FOMC 일정(fomccalendars + fomchistorical2010~2020) · BLS 발표 아카이브(cpi·empsit) 원문
  chains.csv        현재 옵션 체인 스냅숏(SPY·QQQ·향후 3주 실적 대형주): sym,spot,expiry,type,strike,bid,ask,last,iv,oi,vol,asof
  next_earn.csv     위 대형주 다음 실적일(yfinance calendar)
금액·보유 없음(공개 시세·일정만).
"""
from __future__ import annotations

import io
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

OUT = Path("data/study/event")
START = "2009-10-01"
IDX = ["SPY", "QQQ", "^VIX", "^VIX9D", "^VIX1D", "^TNX", "CL=F", "^KS200", "^KS11", "069500.KS"]
FRED = ["DGS10", "DCOILWTICO"]
CHAIN = ["SPY", "QQQ", "META", "LRCX", "TSLA", "WDC", "STX", "MSFT", "GOOGL", "KLAC", "AMZN", "SNDK", "INTC",
         "AAPL", "AMD", "QCOM", "GEV", "VRT", "ETN", "ARM", "NVDA", "AMAT"]
UA = {"User-Agent": "Mozilla/5.0 (research; market-screener) noreply@anthropic.com"}
BROWSER = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
           "Accept-Language": "en-US,en;q=0.9", "Accept": "text/html,application/xhtml+xml"}


def _flat(df: pd.DataFrame) -> pd.DataFrame:
    if hasattr(df.columns, "levels"):
        df.columns = [c[0] for c in df.columns]
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    return df


def idx() -> None:
    import yfinance as yf
    rows = []
    for s in IDX:
        try:
            df = yf.download(s, start=START, interval="1d", auto_adjust=False, progress=False)
        except Exception as e:  # noqa: BLE001
            print(f"::warning::{s} 실패 {e}")
            continue
        if df is None or not len(df):
            print(f"::warning::{s} 데이터 없음")
            continue
        df = _flat(df)
        d = pd.DataFrame({"sym": s, "date": df.index.date, "open": df["Open"].values, "high": df["High"].values,
                          "low": df["Low"].values, "close": df["Close"].values, "adj": df["Adj Close"].values})
        rows.append(d)
        print(f"idx {s}: {len(d)} {d.date.min()}~{d.date.max()}")
    pd.concat(rows).to_csv(OUT / "idx.csv", index=False)


def fred() -> None:
    out = None
    for sid in FRED:
        try:
            r = requests.get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}", timeout=60, headers=UA)
            r.raise_for_status()
            df = pd.read_csv(io.StringIO(r.text))
            df.columns = ["date", sid]
            out = df if out is None else out.merge(df, on="date", how="outer")
            print(f"fred {sid}: {len(df)}")
        except Exception as e:  # noqa: BLE001
            print(f"::warning::FRED {sid} 실패 {e}")
    if out is not None:
        out.to_csv(OUT / "fred.csv", index=False)


def universe() -> list[str]:
    us = pd.read_csv("universe/us_index.csv")["yf"].astype(str).tolist()
    kr = pd.read_csv("universe/kr.csv", dtype=str)
    kr["mcap"] = pd.to_numeric(kr["mcap"], errors="coerce")
    kr = kr.sort_values("mcap", ascending=False).head(30)["yf"].tolist()
    return sorted(set(us)) + kr


def earn_dates(tickers: list[str]) -> None:
    import yfinance as yf
    rows, fail = [], []
    for i, t in enumerate(tickers):
        df = None
        for k in range(3):
            try:
                df = yf.Ticker(t).get_earnings_dates(limit=100)
                break
            except Exception as e:  # noqa: BLE001
                err = str(e)
                time.sleep(2 + 3 * k)
        if df is None or not len(df):
            fail.append(t)
            continue
        df = df.reset_index()
        df.columns = [str(c) for c in df.columns]
        ts = df.columns[0]
        g = lambda name: df[name] if name in df.columns else None  # noqa: E731
        rows.append(pd.DataFrame({"yf": t, "ts": df[ts].astype(str), "eps_est": g("EPS Estimate"),
                                  "eps_rep": g("Reported EPS"), "surprise_pct": g("Surprise(%)")}))
        if i % 50 == 0:
            print(f"earn {i}/{len(tickers)} {t} rows={len(df)}")
        time.sleep(0.3)
    if rows:
        pd.concat(rows).to_csv(OUT / "earn_dates.csv", index=False)
    print(f"earn: ok {len(rows)} / fail {len(fail)} {fail[:40]}")
    if fail:
        print(f"::warning::실적일 실패 {len(fail)}종목: {' '.join(fail[:60])}")


def stk(tickers: list[str]) -> None:
    import yfinance as yf
    parts = []
    for i in range(0, len(tickers), 60):
        ch = tickers[i:i + 60]
        try:
            df = yf.download(ch, start=START, interval="1d", auto_adjust=True, progress=False, group_by="ticker", threads=True)
        except Exception as e:  # noqa: BLE001
            print(f"::warning::stk chunk {i} 실패 {e}")
            continue
        for t in ch:
            try:
                d = df[t].dropna(subset=["Close"])
            except Exception:  # noqa: BLE001
                continue
            if not len(d):
                continue
            d.index = pd.to_datetime(d.index).tz_localize(None).normalize()
            parts.append(pd.DataFrame({"yf": t, "date": d.index.date, "open": d["Open"].values, "high": d["High"].values,
                                       "low": d["Low"].values, "close": d["Close"].values, "volume": d["Volume"].values}))
        print(f"stk {i + len(ch)}/{len(tickers)}")
    out = pd.concat(parts)
    out["date"] = pd.to_datetime(out["date"])
    out.to_parquet(OUT / "stk.parquet", index=False)
    print(f"stk rows {len(out)} syms {out.yf.nunique()}")


def html() -> None:
    (OUT / "html").mkdir(exist_ok=True)
    urls = {"fomc_cur": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"}
    for y in range(2010, 2021):
        urls[f"fomc_{y}"] = f"https://www.federalreserve.gov/monetarypolicy/fomchistorical{y}.htm"
    urls["bls_cpi"] = "https://www.bls.gov/bls/news-release/cpi.htm"
    urls["bls_empsit"] = "https://www.bls.gov/bls/news-release/empsit.htm"
    for k, u in urls.items():
        ok = False
        for h in (BROWSER, UA):
            try:
                r = requests.get(u, timeout=60, headers=h)
                if r.status_code == 200 and len(r.text) > 2000:
                    (OUT / "html" / f"{k}.htm").write_text(r.text, encoding="utf-8")
                    ok = True
                    break
                print(f"html {k} status {r.status_code}")
            except Exception as e:  # noqa: BLE001
                print(f"html {k} 오류 {e}")
            time.sleep(1)
        print(f"html {k}: {'ok' if ok else '::warning::실패'}")


def chains() -> None:
    import yfinance as yf
    asof = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M")
    rows, nxt = [], []
    for s in CHAIN:
        try:
            tk = yf.Ticker(s)
            spot = float(tk.history(period="5d")["Close"].iloc[-1])
            try:
                cal = tk.calendar or {}
                ed = cal.get("Earnings Date") if isinstance(cal, dict) else None
                nxt.append({"sym": s, "earn": ";".join(str(x) for x in (ed or [])), "spot": spot})
            except Exception:  # noqa: BLE001
                pass
            for ex in list(tk.options)[:6]:
                oc = tk.option_chain(ex)
                for typ, df in (("C", oc.calls), ("P", oc.puts)):
                    lo, hi = spot * 0.75, spot * 1.25
                    d = df[(df.strike >= lo) & (df.strike <= hi)]
                    for _, r in d.iterrows():
                        rows.append({"sym": s, "spot": spot, "expiry": ex, "type": typ, "strike": r.strike, "bid": r.bid,
                                     "ask": r.ask, "last": r.lastPrice, "iv": r.impliedVolatility,
                                     "oi": r.openInterest, "vol": r.volume, "asof": asof})
            print(f"chain {s}: spot {spot:.2f} rows so far {len(rows)}")
        except Exception as e:  # noqa: BLE001
            print(f"::warning::체인 {s} 실패 {e}")
        time.sleep(0.5)
    pd.DataFrame(rows).to_csv(OUT / "chains.csv", index=False)
    pd.DataFrame(nxt).to_csv(OUT / "next_earn.csv", index=False)


def main() -> int:
    stage = sys.argv[1] if len(sys.argv) > 1 else "all"
    OUT.mkdir(parents=True, exist_ok=True)
    if stage in ("all", "idx"):
        idx(); fred(); html(); chains()
    if stage in ("all", "earn"):
        t = universe()
        stk(t)
        earn_dates(t)
    return 0


if __name__ == "__main__":
    sys.exit(main())
