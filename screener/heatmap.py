"""US heatmap quotes; separate from closing peer statistics. No AI or messages."""
from __future__ import annotations
import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import math
from .config import REPORT_DIR
from .json_safe import dumps

ET = ZoneInfo("America/New_York")
KST = ZoneInfo("Asia/Seoul")


def session_plan(now, once=False):
    import exchange_calendars as xc
    import pandas as pd
    cal = xc.get_calendar("XNYS")
    local = now.astimezone(ET)
    day = pd.Timestamp(local.date())
    if cal.is_session(day):
        opening = cal.session_open(day).to_pydatetime()
        closing = cal.session_close(day).to_pydatetime()
        if opening <= now <= closing + timedelta(minutes=30):
            return str(local.date()), "LIVE" if now < closing else "CLOSE"
        if not once:
            return None
        if now >= closing:
            return str(local.date()), "CLOSE"
    elif not once:
        return None
    prev = cal.date_to_session(day - pd.Timedelta(days=1), direction="previous")
    return str(prev.date()), "CLOSE"


def quote_rows(peers, frames, target):
    rows = []
    for peer in peers:
        symbol = peer["s"]
        g = frames.get(symbol)
        if g is None:
            continue
        c = g["Close"].dropna()
        c = c[[str(x.date()) <= target for x in c.index]]
        if len(c) < 2 or str(c.index[-1].date()) != target:
            continue
        last, prev = float(c.iloc[-1]), float(c.iloc[-2])
        if not (math.isfinite(last) and math.isfinite(prev) and last > 0 and prev > 0):
            continue
        rows.append({"s": symbol, "r1": last / prev - 1, "close": last, "date": target})
    return rows


def run(once=False):
    import yfinance as yf
    now = datetime.now(ET)
    plan = session_plan(now, once)
    if plan is None:
        print("US heatmap: outside trading window")
        return None
    target, status = plan
    peers = json.loads((REPORT_DIR / "peers_US.json").read_text(encoding="utf-8"))
    symbols = list(dict.fromkeys(r["s"] for r in peers["rows"]))
    frames = {}
    for i in range(0, len(symbols), 60):
        batch = symbols[i:i+60]
        data = yf.download(batch, period="1mo", auto_adjust=True, group_by="ticker",
                           progress=False, threads=4, timeout=20)
        for s in batch:
            try:
                frames[s] = data[s] if data.columns.nlevels > 1 else data
            except KeyError:
                pass
    rows = quote_rows(peers["rows"], frames, target)
    if not rows or len(rows) < len(symbols) * 0.8:
        raise RuntimeError(f"US heatmap coverage {len(rows)}/{len(symbols)}; previous snapshot retained")
    out = {"asof": now.astimezone(KST).strftime("%Y-%m-%d %H:%M KST"), "trade_date": target,
           "session": status, "source": "Yahoo Finance adjusted daily bars (may be delayed)",
           "base_asof": peers["asof"], "expected": len(symbols), "collected": len(rows), "rows": rows}
    p = REPORT_DIR / "heatmap_US.json"
    if p.exists() and json.loads(p.read_text(encoding="utf-8")).get("asof", "") > out["asof"]:
        raise RuntimeError("Refusing older US heatmap")
    p.write_text(dumps(out, ensure_ascii=False), encoding="utf-8")
    print(f"US heatmap {target} {status}: {len(rows)}/{len(symbols)}")
    return out


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--once", action="store_true", help="Collect latest regular-session data outside schedule")
    run(p.parse_args().once)
