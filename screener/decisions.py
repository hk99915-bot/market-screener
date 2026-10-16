"""판단 성적표 — '나' vs 'PB' 의 결정을 기록하고, 실제 가격으로 채점.

reports/decisions.json:
  {"items": [{id, date, title, note,
              "picks": {"나": {"ticker", "name", "notional", "entry": "close", "exit": "next_open"} | {"cash": true},
                        "PB": {...}},
              "result": {...채점 후}}]}
entry "close" = 결정일 종가, exit "next_open" = 다음 거래일 시가 / "next_close" / "d5_close"(5거래일 뒤 종가)
               / "trail"(추세 끌고가기: 종가 20일선 이탈 또는 −8% 손절 시 그날 종가, 최대 60거래일)
entry "open"  = 결정일(세션일) 시가 — 미장 대결. exit "same_close" = 같은 날 종가,
               "d5_close" = 진입일 포함 5번째 세션 종가 (진입일 + 4거래일 뒤 종가; 시가 진입은 진입일 자체가 1세션이므로)
채점: KR = data/kr_prices.parquet(KRX 확정 종가) + 없는 날만 야후(.KS/.KQ), US = 야후 — 결정일 다음 거래일 데이터가 생기면 손익(%·원) 계산, 승자 표시.
item["market"] = "KR"(기본) | "US" — tally_by_market 에 시장별 누적 전적.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from .config import REPORT_DIR

log = logging.getLogger(__name__)
OUT = REPORT_DIR / "decisions.json"
ET = ZoneInfo("America/New_York")


def _us_session_done(date: str) -> bool:
    """미장 세션(date)의 종가가 확정됐는가 — 뉴욕 16:30 이후."""
    n = datetime.now(ET)
    return str(n.date()) > date or (str(n.date()) == date and n.hour * 60 + n.minute >= 16 * 60 + 30)


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
    if str(ticker).isdigit():
        return _bars_kr(str(ticker), start)
    return _bars_yf(ticker, start)


def _bars_yf(t: str, start: str) -> list[dict]:
    import yfinance as yf
    df = yf.download(t, start=start, interval="1d", auto_adjust=False, progress=False)
    if df is None or not len(df):
        return []
    if hasattr(df.columns, "levels"):
        df.columns = [c[0] for c in df.columns]
    return [{"d": str(i.date()), "o": float(r["Open"]), "c": float(r["Close"])} for i, r in df.iterrows() if r["Close"] > 0]


_KR_REFRESHED = False


def _bars_kr(code: str, start: str) -> list[dict]:
    """KR 일봉 = 스크리너와 같은 소스: data/kr_prices.parquet (KRX 확정 종가, 잠정일은 정규장 종가로 교정).
    파켓에 아직 없는 날(오늘 장중 시가 등)만 야후(.KS/.KQ, KRX 정규장 시세)로 채움.
    오늘(KST) 봉은 15:45 전이면 종가를 None 으로 — 장중 현재가로 채점하지 않음."""
    global _KR_REFRESHED
    from .data_krx import KST, PARQUET, refresh_recent
    if not _KR_REFRESHED:   # 실행당 1회: 커밋된 파켓의 잠정 종가를 KRX 확정치로 교정
        _KR_REFRESHED = True
        try:
            refresh_recent()
        except Exception as e:  # noqa: BLE001
            log.warning("KR 일봉 교정 실패 — 저장된 시세로 채점: %s", e)
    bars: dict[str, dict] = {}
    suf = ".KS"
    try:
        import polars as pl
        px = pl.read_parquet(PARQUET).filter(pl.col("yf").str.starts_with(code + ".") & (pl.col("date") >= pl.lit(start).str.to_date()))
        if len(px):
            suf = px["yf"][0][len(code):]
        for r in px.iter_rows(named=True):
            if r["close"] > 0:
                bars[str(r["date"])] = {"d": str(r["date"]), "o": float(r["open"]), "c": float(r["close"])}
    except Exception as e:  # noqa: BLE001
        log.warning("KR 일봉 파켓 읽기 실패 %s: %s", code, e)
    try:
        yb = _bars_yf(code + suf, start)
        if not yb and suf == ".KS" and not bars:
            yb = _bars_yf(code + ".KQ", start)
        for b in yb:
            bars.setdefault(b["d"], b)
    except Exception as e:  # noqa: BLE001
        log.warning("KR 야후 일봉 실패 %s: %s", code, e)
    n = datetime.now(KST)
    today = str(n.date())
    if today in bars and n.hour * 60 + n.minute < 15 * 60 + 45:
        bars[today] = {**bars[today], "c": None}
    return [bars[k] for k in sorted(bars)]


def _score_pick(p: dict, date: str) -> dict | None:
    if p.get("cash"):
        return {"ret": 0.0, "pnl": 0.0, "detail": p.get("label") or "현금 유지"}
    bars = _bars(p["ticker"], date)
    if not str(p["ticker"]).isdigit():   # 미국 종목: 진행 중인 세션 봉(잠정)은 쓰지 않음
        today = str(datetime.now(ET).date())
        if not _us_session_done(today):
            bars = [b for b in bars if b["d"] < today]
    if p.get("entry") == "open":
        return _score_open(p, date, bars)
    day = next((b for b in bars if b["d"] == date), None)
    after = [b for b in bars if b["d"] > date]
    if not day or not after or day["c"] is None:
        return None
    buy = day["c"]
    ex = p.get("exit", "next_open")
    if ex == "next_open":
        sell, when = after[0]["o"], after[0]["d"] + " 시가"
    elif ex == "next_close":
        sell, when = after[0]["c"], after[0]["d"] + " 종가"
    elif ex == "trail":   # 추세 끌고가기 (규정 [5]): 종가 20일선 이탈(20일선 위를 한 번 회복한 뒤) 또는 진입가 −8% 이하 → 그날 종가 청산, 최대 60거래일
        from datetime import date as _date, timedelta as _td
        hist = [b for b in _bars(p["ticker"], str(_date.fromisoformat(date) - _td(days=45))) if b["d"] <= date and b["c"]]
        closes = [b["c"] for b in hist]
        sell = when = None
        armed = bool(len(closes) >= 20 and buy >= sum(closes[-20:]) / 20)   # 20일선 아래에서 진입하면 20일선을 회복한 뒤부터 이탈 청산 적용 (그 전엔 −8% 손절만)
        for i, b in enumerate(after[:60]):
            if b["c"] is None:
                return None
            closes.append(b["c"])
            sma = sum(closes[-20:]) / 20 if len(closes) >= 20 else None
            if sma and b["c"] >= sma:
                armed = True
            why = "−8% 손절" if b["c"] <= buy * 0.92 else "20일선 이탈" if armed and sma and b["c"] < sma else "60거래일 만기" if i == 59 else None
            if why:
                sell, when = b["c"], f"{b['d']} 종가 ({why})"
                break
        if sell is None:
            return None   # 아직 보유 중
    else:
        if len(after) < 5:
            return None
        sell, when = after[4]["c"], after[4]["d"] + " 종가"
    if sell is None:
        return None
    cost = 0.0005
    r = sell / buy - 1 - cost
    return {"ret": round(r, 4), "pnl": round(r * (p.get("notional") or 0)), "buy": round(buy, 2), "sell": round(sell, 2),
            "detail": f"{date} 종가 {buy:,.0f} → {when} {sell:,.0f}"}


def _score_open(p: dict, date: str, bars: list[dict]) -> dict | None:
    """시가 진입: 결정일 시가 매수 → same_close(당일 종가) / d5_close(진입일 포함 5번째 세션 종가)."""
    seq = [b for b in bars if b["d"] >= date]
    if not seq:
        return None
    if seq[0]["d"] != date:   # 결정일에 봉이 없는데 이후 봉은 있음 = 휴장일
        return {"ret": 0.0, "pnl": 0.0, "detail": f"{date} 휴장 — 거래 없음", "holiday": True}
    buy = seq[0]["o"]
    if p.get("exit", "same_close") == "d5_close":
        if len(seq) < 5:
            return None
        sell, when = seq[4]["c"], seq[4]["d"] + " 종가"
    else:
        sell, when = seq[0]["c"], seq[0]["d"] + " 종가"
    if sell is None:
        return None
    cost = 0.0005
    r = sell / buy - 1 - cost
    return {"ret": round(r, 4), "pnl": round(r * (p.get("notional") or 0)), "buy": round(buy, 2), "sell": round(sell, 2),
            "detail": f"{date} 시가 {buy:,.2f} → {when} {sell:,.2f}"}


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
        if it.get("market") == "US" and not _us_session_done(it["date"]):
            continue   # 미장 세션 종가 확정 전
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
        if ok and any(v.get("holiday") for v in res.values()):
            it["result"] = {"void": "휴장일 — 채점 제외", "scored_at": datetime.now().strftime("%Y-%m-%d %H:%M")}
            continue
        if ok and res:
            best = max(res.items(), key=lambda kv: kv[1]["pnl"])
            tie = len({v["pnl"] for v in res.values()}) == 1
            it["result"] = {**res, "winner": None if tie else best[0], "scored_at": datetime.now().strftime("%Y-%m-%d %H:%M")}
            n += 1
    # 누적 전적
    tally, by_mk = {}, {"KR": {}, "US": {}}
    for it in d["items"]:
        r = it.get("result")
        if not r or r.get("void"):
            continue
        mk = by_mk.setdefault(it.get("market") or "KR", {})
        for who in [w for w in it["picks"] if w in r]:
            rw = r.get(who, {})
            for tb in (tally, mk):
                t = tb.setdefault(who, {"win": 0, "n": 0, "pnl": 0, "rets": []})
                t["n"] += 1
                t["pnl"] += rw.get("pnl", 0)
                if r.get("winner") == who:
                    t["win"] += 1
                if not it["picks"][who].get("cash") and rw.get("ret") is not None:
                    t.setdefault("rets", []).append(rw["ret"])
    # 실력 지표: 승률(수익 낸 비율)·평균 수익/손실·손익비·기대값 (현금 판단은 제외, 진입한 판만)
    for tb in [tally, *by_mk.values()]:
        for t in tb.values():
            rs = t.pop("rets", [])
            w = [x for x in rs if x > 0]
            l = [x for x in rs if x <= 0]
            t["trades"] = len(rs)
            t["hit"] = round(len(w) / len(rs), 3) if rs else None
            t["avg_win"] = round(sum(w) / len(w), 4) if w else None
            t["avg_loss"] = round(sum(l) / len(l), 4) if l else None
            t["payoff"] = round(t["avg_win"] / abs(t["avg_loss"]), 2) if w and l and t["avg_loss"] else None
            t["ev"] = round(sum(rs) / len(rs), 4) if rs else None
    d["tally"] = tally
    d["tally_by_market"] = by_mk
    OUT.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    log.info("판단 성적표 채점 %d건", n)
    return n
