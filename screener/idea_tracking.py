"""TOP3 forward-only paper tracking, separate from legacy ideas attribution.

KR = 국장 운용회의 ideas_top (kr_prices). US = 미장 운용회의 ideas_top (detail/US chart, 10/20 us-entry-ideas):
row id 'US:<date>:<ticker>', market 'US'. 진입 = 제안 시점 이후 처음 열리는 미장 세션 시가 —
ref(제안 때 차트 마지막 세션) 다음 세션이고, 제안이 KST 22:30 이후면 그날 세션은 이미 열려 건너뜀(미래 참조 금지).
가격 공통 유틸 = screener/fwd_perf.py."""
from __future__ import annotations
import copy
import json
import math
from datetime import datetime
from zoneinfo import ZoneInfo
from .config import REPORT_DIR, DATA_DIR

KST = ZoneInfo("Asia/Seoul")
POLICY = ("모의 추적: 제안일 다음 첫 거래일 시가가 원래 진입 구간 안일 때만 진입. "
          "다음 시가가 구간 밖이면 미진입 만료. 대기 제안은 미진입. 종가가 손절선 미만이면 종가 손절. "
          "목표는 고가 도달 시 목표가(시가 갭 상승은 시가). 같은 날 목표·종가 손절 동시 충족은 판정 보류. "
          "20거래일 안 +1R 미도달 시 종가 시간 손절. 비용 0.05%, 실거래 아님.")
TERMINAL = {"target", "stop", "timeout", "expired", "ambiguous"}
def number(v):
    return isinstance(v, (int, float)) and math.isfinite(v) and v > 0

def _mk(r):
    return r.get("market") or "KR"

def capture(book, meeting, now, market="KR"):
    """First three top proposals per date (per market), never overwrite original conditions."""
    day = str(meeting.get("date", ""))
    if day != now.strftime("%Y-%m-%d") or str(meeting.get("asof", ""))[:10] != day:
        return
    rows = book.setdefault("rows", [])
    existing = {r["ticker"] for r in rows if r["date"] == day and _mk(r) == market}
    for idea in (meeting.get("ideas_top") or {}).get("items", [])[:3]:
        code = str(idea.get("s", ""))
        if code in existing or len(existing) >= 3:
            continue
        original = copy.deepcopy(idea)
        row = {"id": ("US:" if market == "US" else "") + day + ":" + code, "date": day, "ticker": code,
               "name": idea.get("n", code), "proposed_at": meeting["asof"],
               "captured_at": now.strftime("%Y-%m-%d %H:%M KST"),
               "original": original, "state": {"status": "waiting"}}
        if market == "US":
            row.update(market="US", ref=idea.get("ref"))
        rows.append(row)
        existing.add(code)

def evaluate(row, bars):
    p = row["original"]
    if not p.get("status"):
        return {"status": "review", "reason": "과거 제안의 실행 상태·진입 상한 미기록 — 소급 체결 금지"}
    if not str(p.get("status", "")).startswith("실행"):
        return {"status": "not_entered", "reason": p.get("status") or "당시 실행 상태 없음"}
    lo, hi, stop, target = (p.get(k) for k in ("entry", "entry_max", "stop", "target"))
    if p.get("side") != "롱" or not all(number(x) for x in (lo, hi, stop, target)) or not stop < lo <= hi < target:
        return {"status": "review", "reason": "가격 조건 또는 방향 검증 필요"}
    if _mk(row) == "US":   # 제안 이후 처음 '열리는' 세션: ref 다음, 제안이 그날 KST 22:30 이후면 그 세션 제외
        after, pa = row.get("ref") or "", str(row.get("proposed_at") or "")
        seq = sorted([b for b in bars if b["date"] > after and not (b["date"] < pa[:10] or (b["date"] == pa[:10] and pa[11:16] >= "22:30"))],
                     key=lambda b: b["date"])
    else:
        seq = sorted([b for b in bars if b["date"] > row["date"]], key=lambda b: b["date"])
    if not seq:
        return {"status": "waiting", "reason": "다음 거래일 확정 일봉 대기"}
    first = seq[0]
    if not number(first.get("open")):
        return {"status": "review", "reason": "진입일 시가 누락"}
    buy = first["open"]
    if not lo <= buy <= hi:
        return {"status": "expired", "price_date": first["date"], "reason": "다음 시가가 진입 구간 밖 — 미진입"}
    risk = buy - stop
    state = {"status": "open", "entry_date": first["date"], "entry_price": buy}
    hit1r = False
    for i, b in enumerate(seq):
        if not all(number(b.get(k)) for k in ("open", "high", "low", "close")):
            return {**state, "status": "review", "reason": "OHLC 누락 — 후속 채점 중지"}
        if not b["low"] <= min(b["open"], b["close"]) <= max(b["open"], b["close"]) <= b["high"]:
            return {**state, "status": "review", "reason": "OHLC 정합성 오류"}
        hit1r = hit1r or b["high"] >= buy + risk
        target_hit, stopped = b["high"] >= target, b["close"] < stop
        if target_hit and stopped:
            return {**state, "status": "ambiguous", "price_date": b["date"],
                    "reason": "목표·손절 동일 일봉 — 장중 순서 미검증, 승패 제외"}
        status, sell = "open", b["close"]
        if stopped:
            status = "stop"
        elif target_hit:
            status, sell = "target", max(target, b["open"])
        elif i + 1 >= 20 and not hit1r:
            status = "timeout"
        ret = sell / buy - 1 - 0.0005
        state.update(status=status, price_date=b["date"], mark_price=sell,
                     ret=round(ret, 6), r=round((sell-buy)/risk, 4), sessions=i+1, hit1r=hit1r)
        if status != "open":
            state["exit_date"] = b["date"]
            break
    return state

def summarize(rows):
    states = [r["state"] for r in rows]
    closed = [s for s in states if s["status"] in {"target", "stop", "timeout"}]
    no_entry = sum(s["status"] in {"not_entered", "expired"} for s in states)
    resolved = no_entry + sum(bool(s.get("entry_date")) for s in states)
    return {"proposals": len(rows), "closed": len(closed),
            "hit_rate": sum(s["ret"] > 0 for s in closed)/len(closed) if closed else None,
            "avg_return": sum(s["ret"] for s in closed)/len(closed) if closed else None,
            "no_entry_rate": no_entry/resolved if resolved else None,
            "no_entry": no_entry, "resolved": resolved}

def run(meeting, now=None, market="KR"):
    now = now or datetime.now(KST)
    path = REPORT_DIR / "idea_tracking.json"
    book = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"version": 1, "rows": []}
    if book.get("asof", "") > now.strftime("%Y-%m-%d %H:%M"):
        return book
    capture(book, meeting, now, market)
    by = {}
    error = None
    try:
        if market == "US":
            from .fwd_perf import us_bars
            by = us_bars({r["ticker"] for r in book["rows"] if _mk(r) == "US"})
        else:
            # Same adjusted KRX source as the screener. No refresh or network side effects.
            from .fwd_perf import kr_bars
            by = kr_bars(now, path=DATA_DIR / "kr_prices.parquet")
    except Exception as exc:
        error = type(exc).__name__ + ": price source unavailable"
    for row in book["rows"]:
        if _mk(row) != market:
            continue
        if row.get("source_review"):
            continue
        if row.get("state", {}).get("status") in TERMINAL:
            continue
        if error and str(row["original"].get("status", "")).startswith("실행"):
            row["state"] = {"status": "review", "reason": error}
        else:
            row["state"] = evaluate(row, by.get(row["ticker"], []))
        # Non-price kill criteria need the contemporaneous sources, never future hindsight.
        current = next((x for x in (meeting.get("ideas_top") or {}).get("items", []) +
                        (meeting.get("ideas_top") or {}).get("candidates", [])
                        if str(x.get("s")) == row["ticker"]), None)
        if row["state"].get("status") == "open":
            old_agree = {s["k"] for s in row["original"].get("sources", []) if s.get("side") == "agree"}
            reversed_sources = old_agree & {s["k"] for s in (current or {}).get("sources", []) if s.get("side") == "oppose"}
            row["state"]["source_check"] = ("원천 반대 전환 — 청산 검토 필요" if reversed_sources else
                                           "최신 원천 반대 전환 없음" if current else "최신 원천 확인 필요")
            if reversed_sources:
                row["source_review"] = now.strftime("%Y-%m-%d %H:%M")
                row["state"].update(status="review", reason="비가격 kill 조건 발동 — 실제 관측 시점 청산가 검증 필요")
    book.update(asof=now.strftime("%Y-%m-%d %H:%M"), policy=POLICY, summary=summarize(book["rows"]),
                summary_by_market={m: summarize([r for r in book["rows"] if _mk(r) == m]) for m in ("KR", "US")})
    path.write_text(json.dumps(book, ensure_ascii=False, indent=1), encoding="utf-8")
    hist = REPORT_DIR / "idea_tracking"
    hist.mkdir(exist_ok=True)
    (hist / (str(now.date()) + ".json")).write_text(json.dumps(book, ensure_ascii=False, indent=1), encoding="utf-8")
    return book
