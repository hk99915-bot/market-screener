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
from .tradecal import us_open_hhmm

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

# 확정판(D1, 10/21 CIO 진단 cio_top3_review_2026-10-21 §4): 회의는 하루 7~8번 재생성되므로 '첫 판'이 아니라
# 진입 판정 전 마지막 판을 기록한다. KR = 장 마감 뒤(asof ≥ 15:45 KST) 판만 캡처, 같은 날 뒤 판이 나오면 그 판으로 교체
# (다음 거래일 시가 전이라 미래 참조 없음). US = KST 22:30(미장 개장) 전 판은 마지막 판으로 교체, 22:30 이후 판은
# 그날 행이 없을 때만 캡처. 날짜가 바뀌거나(KR) 22:30 이 지나면(US) 원래 조건은 덮어쓰지 않는다 = '확정판 기준' 불변.
KR_FINAL_FROM = "15:45"
US_OPEN_KST = "22:30"   # 여름(EDT) 기준 설명용 — 판정은 us_open_hhmm(날짜)(겨울 23:30, 서머타임 대응 10/30)
SCHEMA = ("행 키: id · date · ticker(종목코드 — code 키는 없음, 원본 안에서는 original.s) · market(없으면 KR) · name · "
          "proposed_at(기록한 확정판 asof) · captured_at · original(확정판 원본, 불변) · state(채점) · note(사후 주석, 원본 아님)")


def capture(book, meeting, now, market="KR"):
    """그날 확정판 TOP3 를 기록. 확정 시점 이후 원래 조건은 덮어쓰지 않는다(위 주석)."""
    day = str(meeting.get("date", ""))
    asof = str(meeting.get("asof", ""))
    if day != now.strftime("%Y-%m-%d") or asof[:10] != day:
        return
    hm = asof[11:16]
    rows = book.setdefault("rows", [])
    mine = [r for r in rows if r["date"] == day and _mk(r) == market]
    if market == "US":
        replace = hm < us_open_hhmm(day)
    else:
        if hm < KR_FINAL_FROM:
            return   # 장중 판은 기록하지 않음(evaluate 만)
        replace = True
    if mine and not replace:
        return
    if mine and any(r.get("state", {}).get("entry_date") or r.get("state", {}).get("price_date") for r in mine):
        return   # 이미 가격 판정이 시작된 행은 절대 교체 안 함(방어)
    top = [i for i in (meeting.get("ideas_top") or {}).get("items", [])[:3] if str(i.get("s", ""))]
    if mine and [r["ticker"] for r in mine] == [str(i["s"]) for i in top] and \
            all(r["original"] == i for r, i in zip(mine, top)):
        return
    if mine:
        book["rows"] = rows = [r for r in rows if r not in mine]
    for idea in top:
        code = str(idea.get("s", ""))
        if any(r["date"] == day and _mk(r) == market and r["ticker"] == code for r in rows):
            continue
        row = {"id": ("US:" if market == "US" else "") + day + ":" + code, "date": day, "ticker": code,
               "name": idea.get("n", code), "proposed_at": asof,
               "captured_at": now.strftime("%Y-%m-%d %H:%M KST"),
               "original": copy.deepcopy(idea), "state": {"status": "waiting"}}
        if mine:
            row["replaced"] = "같은 날 앞선 판(" + ", ".join(sorted({r["proposed_at"] for r in mine})) + ") → 확정판으로 교체"
        if market == "US":
            row.update(market="US", ref=idea.get("ref"))
        rows.append(row)

# ── TOP3 v2 규칙 (스위치 screener/config.CIO_TOP3_V2, 기본 OFF). 국장·미장 운용회의가 공용으로 쓴다. ──
SELF_REF = ("exec_plan", "committee_ideas")   # 운용회의 자기 산출물 원천 — 합산하면 어제 고른 종목이 오늘 다시 상위 고정(D4)
VALID = {"entry_days": 1, "hold_max": 20}     # P1 유효기간: 진입 1거래일, 보유 최대 20거래일


def v2_on():
    from . import config
    return bool(getattr(config, "CIO_TOP3_V2", False))


def v2_score(weights):
    """weights = [(원천 키, 부호 있는 가중)]. 자기 참조 원천은 합산 대신 가장 큰 것 하나만(P2/D4)."""
    own = [w for k, w in weights if k in SELF_REF]
    return sum(w for k, w in weights if k not in SELF_REF) + (max(own) if own else 0.0)


def entry_floor(close, stop, atr_pct):
    """P3/D5 진입 하한 = max(손절 + 0.5R, 종가 − 0.5×ATR). R = 종가 − 손절. 상한(종가 + 0.5×ATR)은 그대로."""
    return max(stop + 0.5 * (close - stop), close * (1 - 0.5 * atr_pct))


def top3_ready(x):
    """P1 필수 5칸: 진입 구간(하한·상한)·손절·목표·유효기간·촉매(없으면 catalyst_note '없음' 명시)."""
    lo, hi, st, tg = (x.get(k) for k in ("entry", "entry_max", "stop", "target"))
    if not all(number(v) for v in (lo, hi, st, tg)) or not st < lo <= hi < tg:
        return False
    v = x.get("valid") or {}
    if not (v.get("entry_days") and v.get("hold_max")):
        return False
    cat = x.get("catalyst")
    return isinstance(cat, list) and (bool(cat) or x.get("catalyst_note") == "없음")


def pick_top3(rows, market="KR"):
    """P2: 순위대로 정렬된 후보에서 TOP3 = 실행 후보 먼저, 3개 미만일 때만 대기 최대 1개. 5칸 결손은 자격 없음(P1).
    실행 후보 0이면 사유 1줄 — 빈칸은 억지로 채우지 않는다. 반환 (items, candidates, exec_zero 사유|None)."""
    ready = [r for r in rows if top3_ready(r)]
    go = [r for r in ready if str(r.get("status", "")).startswith("실행")][:3]
    wait = [r for r in ready if not str(r.get("status", "")).startswith("실행")][:1] if len(go) < 3 else []
    pick = {id(r) for r in go + wait}
    items = [r for r in rows if id(r) in pick]
    cands = [r for r in rows if id(r) not in pick]
    note = None
    if not go:
        why = {}
        for r in ready:
            k = str(r.get("status", "")).replace("대기 — ", "")
            why[k] = why.get(k, 0) + 1
        bad = len(rows) - len(ready)
        note = (f"오늘 {market} 실행 0 — 후보 {len(rows)}개 중 " + (" · ".join(f"{k} {n}" for k, n in why.items()) or "자격 후보 없음")
                + (f" · 필수 5칸 결손 {bad}" if bad else ""))
    return items, cands, note


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
        seq = sorted([b for b in bars if b["date"] > after and not (b["date"] < pa[:10] or (b["date"] == pa[:10] and pa[11:16] >= us_open_hhmm(pa[:10])))],
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
        if row.get("note"):
            row["state"]["note"] = row["note"]
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
    errs = book.setdefault("errors", {})
    if error:
        errs[market] = {"at": now.strftime("%Y-%m-%d %H:%M"), "error": error}
    else:
        errs.pop(market, None)
    if not errs:
        book.pop("errors")
    book.update(asof=now.strftime("%Y-%m-%d %H:%M"), policy=POLICY, schema=SCHEMA, summary=summarize(book["rows"]),
                summary_by_market={m: summarize([r for r in book["rows"] if _mk(r) == m]) for m in ("KR", "US")})
    path.write_text(json.dumps(book, ensure_ascii=False, indent=1), encoding="utf-8")
    hist = REPORT_DIR / "idea_tracking"
    hist.mkdir(exist_ok=True)
    (hist / (str(now.date()) + ".json")).write_text(json.dumps(book, ensure_ascii=False, indent=1), encoding="utf-8")
    return book
