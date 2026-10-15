"""판단 성적표 — '나' vs 'PB' 의 결정을 기록하고, 실제 가격으로 채점.

reports/decisions.json:
  {"items": [{id, date, title, note,
              "picks": {"나": {"ticker", "name", "notional", "entry": "close", "exit": "next_open"} | {"cash": true},
                        "PB": {...}},
              "result": {...채점 후}}]}
entry "close" = 결정일 종가, exit "next_open" = 다음 거래일 시가 / "next_close" / "d5_close"
채점: 야후 일봉(.KS) — 결정일 다음 거래일 데이터가 생기면 손익(%·원) 계산, 승자 표시.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime

from .config import REPORT_DIR

log = logging.getLogger(__name__)
OUT = REPORT_DIR / "decisions.json"


def load() -> dict:
    try:
        return json.loads(OUT.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"items": []}


def add(item: dict) -> None:
    d = load()
    d["items"] = [x for x in d["items"] if x["id"] != item["id"]] + [item]
    OUT.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


def _bars(ticker: str, start: str) -> list[dict]:
    import yfinance as yf
    t = ticker if "." in ticker or not ticker.isdigit() else ticker + ".KS"
    df = yf.download(t, start=start, interval="1d", auto_adjust=False, progress=False)
    if df is None or not len(df):
        return []
    if hasattr(df.columns, "levels"):
        df.columns = [c[0] for c in df.columns]
    return [{"d": str(i.date()), "o": float(r["Open"]), "c": float(r["Close"])} for i, r in df.iterrows() if r["Close"] > 0]


def _score_pick(p: dict, date: str) -> dict | None:
    if p.get("cash"):
        return {"ret": 0.0, "pnl": 0.0, "detail": p.get("label") or "현금 유지"}
    bars = _bars(p["ticker"], date)
    day = next((b for b in bars if b["d"] == date), None)
    after = [b for b in bars if b["d"] > date]
    if not day or not after:
        return None
    buy = day["c"]
    ex = p.get("exit", "next_open")
    if ex == "next_open":
        sell, when = after[0]["o"], after[0]["d"] + " 시가"
    elif ex == "next_close":
        sell, when = after[0]["c"], after[0]["d"] + " 종가"
    else:
        if len(after) < 5:
            return None
        sell, when = after[4]["c"], after[4]["d"] + " 종가"
    cost = 0.0005
    r = sell / buy - 1 - cost
    return {"ret": round(r, 4), "pnl": round(r * (p.get("notional") or 0)), "buy": round(buy, 2), "sell": round(sell, 2),
            "detail": f"{date} 종가 {buy:,.0f} → {when} {sell:,.0f}"}


def score() -> int:
    d = load()
    n = 0
    for it in d["items"]:
        if it.get("result"):
            continue
        live = {w: p for w, p in it["picks"].items() if not p.get("pending")}
        if len(live) < len(it["picks"]):
            if it["date"] >= datetime.now().strftime("%Y-%m-%d"):
                continue   # 당일엔 제출을 더 기다림
            if "나" not in live or len(live) < 2:
                it["result"] = {"void": "나 미제출 — 채점 제외" if "나" not in live else "상대 판단 없음 — 채점 제외",
                                "scored_at": datetime.now().strftime("%Y-%m-%d %H:%M")}
                continue
        res = {}
        ok = True
        for who, p in live.items():
            try:
                s = _score_pick(p, it["date"])
            except Exception as e:  # noqa: BLE001
                log.warning("채점 실패 %s %s: %s", it["id"], who, e)
                s = None
            if s is None:
                ok = False
                break
            res[who] = s
        if ok and res:
            best = max(res.items(), key=lambda kv: kv[1]["pnl"])
            tie = len({v["pnl"] for v in res.values()}) == 1
            it["result"] = {**res, "winner": None if tie else best[0], "scored_at": datetime.now().strftime("%Y-%m-%d %H:%M")}
            n += 1
    # 누적 전적
    tally = {}
    for it in d["items"]:
        r = it.get("result")
        if not r or r.get("void"):
            continue
        for who in [w for w in it["picks"] if w in r]:
            t = tally.setdefault(who, {"win": 0, "n": 0, "pnl": 0})
            t["n"] += 1
            t["pnl"] += r.get(who, {}).get("pnl", 0)
            if r.get("winner") == who:
                t["win"] += 1
    d["tally"] = tally
    OUT.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    log.info("판단 성적표 채점 %d건", n)
    return n
