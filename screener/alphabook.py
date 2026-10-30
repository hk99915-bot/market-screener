"""알파북(모의) — HF 데스크 상시 운용 북. 가상 1단위(NAV 1.0 시작), 실계좌 근거 아님.

비유: 사냥꾼 장부. 검증 통과한 덫(알파 소스)에 걸린 놈만 쏘고(trade plan 필수), 덫이 없으면 총을 내려놓고(현금) 덫을 찾는다.
용어: 알파 = 벤치마크(KR 069500·US SPY) 대비 초과수익. IR(정보비율) = 일별 초과수익 평균 ÷ 표준편차 × √252.

규칙(docs/desk_kb/hf.md, 보드 hf-alphabook, 10/21 겸이 "피도 눈물도 없게")
- 모든 진입 = screener/tradeplan.py plan 필수. 소스는 reports/studies/2026-10-21_alpha_sources.json 통과(B)만,
  소스 OOS 기대값 ≤ 기준선이면 진입 금지. 통과 소스 0 → 현금 + '탐색 중'(억지 진입 금지).
- 장이 나빠도 0으로 쉬지 않는다: 총노출·1회 리스크를 시장 필터 배수로 줄이되 바닥 FLOOR(0.25). 이벤트 당일(필터 보류)만 신규 0.
- 진입 = 결정 다음 봉 시가, 진입 구간 밖이면 미진입 만료(추격 금지).
- 스탑: 봉 저가가 스탑에 닿으면 **다음 봉 시가 즉시 청산(예외 없음)**. 1차 목표 50% 익절 → 스탑 본전, 2차 목표 나머지(컨빅션 C 이하면 1차 전량).
- 시간 손절: 보유 HOLD 거래일째 종가 전량 청산. 체결 비용 보수적: 편도 = (tradeplan 왕복 비용 + 추가 미끄러짐) ÷ 2.

순수 함수: new_book·regime_scale·gate·size·order·step_day·stats·hf_block·say_line·scan_52w (파일·네트워크 없음).
파일 읽기·쓰기: update(o, market, today) — committee.build/build_us 가 tradeplan.attach 뒤 호출. 상태 reports/alphabook.json.
영향 범위: 운용회의 KR·US 산출물에 `hf` 블록, 텔레그램 운용회의 1~2줄, DAILY › 운용회의 화면 HF 카드. 워크플로 변경 없음.
롤백: committee.py 의 alphabook 호출(try 블록 2개)·telegram 꼬리 제거 — hf 키는 선택이라 소비자 호환. reports/alphabook.json 삭제 = 북 초기화.
"""
from __future__ import annotations

import json
import logging
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger(__name__)
KST = timezone(timedelta(hours=9))

START_NAV = 1.0
RISK_BASE = 0.005            # 1회 리스크(북 NAV 대비) — FRM #16 1% 규칙의 절반(모의 1단계 0.25% 와 실계좌 3단계 1% 사이)
GROSS_MAX = 1.0              # 총노출 상한(레버리지 없음)
FLOOR = 0.25                 # 나쁜 장에도 남기는 최소 배수(0 으로 쉬지 않음) — 이벤트 당일 보류만 예외
WEIGHT_CAP = 0.15            # 단일 종목 상한(tradeplan.WEIGHT_CAP 과 같음)
MAX_POS = 8
MAX_NEW = 2                  # 회의당 신규 제안 상한(시장별)
HOLD = 20
COST_RT = {"KR": 0.0025, "US": 0.0010}       # tradeplan.COST 와 같음
SLIP_RT = {"KR": 0.0020, "US": 0.0010}       # 보수적 추가 미끄러짐(왕복)
BENCH = {"KR": "069500", "US": "SPY"}
SRC_FILE = "reports/studies/2026-10-21_alpha_sources.json"
SRC_MARKET = {"B1": "KR", "A1": "KR", "C1": "KR", "D1": "KR", "A2": "US", "B2": "US", "D2": "US", "E": "US"}
HI52_TH = 0.95
LIQ = {"KR": (1e9, 1000.0), "US": (2e7, 5.0)}


def side_cost(market: str) -> float:
    return (COST_RT[market] + SLIP_RT[market]) / 2


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


# ───────────── 북 상태 ─────────────

def new_book(market: str, start: str) -> dict:
    return {"market": market, "start": start, "last_bar": None, "cash": START_NAV, "positions": [], "pending": [],
            "fills": [], "closed": [], "nav": [], "bench": BENCH[market]}


def nav_of(book: dict, px: dict | None = None) -> float:
    px = px or {}
    return book["cash"] + sum(p["qty"] * px.get(p["code"], p.get("mark", p["entry"])) for p in book["positions"])


def gross_of(book: dict, px: dict | None = None) -> float:
    nav = nav_of(book, px)
    px = px or {}
    return (sum(p["qty"] * px.get(p["code"], p.get("mark", p["entry"])) for p in book["positions"]) / nav) if nav > 0 else 0.0


# ───────────── 크기 (FRM 한도 안) ─────────────

def regime_scale(filt: dict | None) -> dict:
    """시장 단위 필터(tradeplan.macro_filter, 종목 무관) → 총노출 상한·1회 리스크 배수. 보류(이벤트 당일)만 신규 0."""
    f = filt or {}
    if f.get("state") == "보류":
        return {"gross_cap": GROSS_MAX * FLOOR, "risk_mult": 0.0, "new_ok": False, "why": "이벤트 당일/필터 보류 — 신규 0, 보유는 규칙대로"}
    m = f.get("mult") if _num(f.get("mult")) else 1.0
    k = max(FLOOR, min(1.0, m))
    why = "정상" if k >= 0.999 else f"필터 ×{m:.2f} → 총노출 상한 {GROSS_MAX*k*100:.0f}%·1회 리스크 ×{k:.2f}(바닥 {FLOOR})"
    return {"gross_cap": round(GROSS_MAX * k, 3), "risk_mult": round(k, 3), "new_ok": True, "why": why, "reasons": f.get("reasons") or []}


def gate(plan: dict | None, src: dict | None) -> list[str]:
    """진입 금지 사유 목록(빈 목록 = 진입 가능). 계획 필수·보류 사유·소스 통과·기대값 > 기준선."""
    why = []
    if not isinstance(plan, dict) or not (plan.get("stop") or {}).get("px"):
        return ["trade plan 없음 — 진입 금지"]
    hard = [w for w in (plan.get("why_not") or []) if not str(w).startswith(("보정 E[R]", "확률·기대값", "E[R]"))]
    if plan.get("verdict") == "보류":
        why += hard or ["계획 보류"]
    if not src or not src.get("pass"):
        why.append(f"소스 {(src or {}).get('key', '?')} 미통과({(src or {}).get('grade', '없음')})")
    ev, base = (src or {}).get("ev_r"), (src or {}).get("base_ev_r")
    if not _num(ev) or not _num(base) or ev <= base:
        why.append(f"기대값 {ev if _num(ev) else '없음'} ≤ 기준선 {base if _num(base) else '없음'}")
    return why


def size(plan: dict, nav: float, gross_now: float, scale: dict) -> dict:
    """비중 = 1회 리스크(RISK_BASE × 컨빅션 배수 × 시장 배수) ÷ 손절폭, 상한 15%·남은 총노출."""
    sp = plan["stop"]["pct"]
    conv = (plan.get("conviction") or {}).get("mult")
    conv = conv if _num(conv) else 0.5
    risk = RISK_BASE * conv * scale["risk_mult"]
    room = max(0.0, scale["gross_cap"] - gross_now)
    w = min(risk / sp if sp > 0 else 0.0, WEIGHT_CAP, room)
    return {"risk_pct": round(risk, 5), "weight": round(w, 4), "room": round(room, 4),
            "formula": f"{RISK_BASE*100:.1f}% × 컨빅션 {conv} × 시장 {scale['risk_mult']} ÷ 손절폭 {sp*100:.1f}% (상한 15%·남은 노출 {room*100:.0f}%)"}


def order(plan: dict, src: dict, sz: dict, created: str, after: str | None = None) -> dict:
    """after = 이 날짜 '다음' 봉 시가에만 체결(결정 시점에 이미 열린 장의 시가로 소급 체결 금지)."""
    return {"code": plan["code"], "name": plan.get("name"), "src": src["key"], "created": created, "after": after or created,
            "lo": plan["entry"]["lo"], "hi": plan["entry"]["hi"], "stop": plan["stop"]["px"], "t1": plan["t1"]["px"], "t2": plan["t2"]["px"],
            "hold_t2": bool(plan["t2"].get("hold")), "weight": sz["weight"], "risk_pct": sz["risk_pct"], "hold": (plan.get("time_stop") or {}).get("days", HOLD),
            "line": plan.get("line"), "ev_r": src.get("ev_r"), "base_ev_r": src.get("base_ev_r")}


# ───────────── 하루 처리 ─────────────

def _fill(book, kind, p, px, frac, d, why):
    m = book["market"]
    c = side_cost(m)
    q = p["qty0"] * frac if kind != "buy" else p["qty"]
    if kind == "buy":
        book["cash"] -= q * px * (1 + c)
    else:
        q = min(q, p["qty"])
        book["cash"] += q * px * (1 - c)
        p["qty"] -= q
        p["realized_r"] = p.get("realized_r", 0.0) + frac * ((px * (1 - c) - p["entry"] * (1 + c)) / p["r_unit"])
    book["fills"].append({"d": d, "code": p["code"], "name": p.get("name"), "kind": kind, "px": round(px, 4), "frac": round(frac, 3), "why": why})


def _close_pos(book, p, d, why):
    book["positions"].remove(p)
    book["closed"].append({"code": p["code"], "name": p.get("name"), "src": p.get("src"), "entry_d": p["entry_d"], "exit_d": d,
                           "r": round(p.get("realized_r", 0.0), 3), "why": why, "days": p["days"]})


def step_day(book: dict, d: str, bars: dict, bench_close: float | None) -> dict:
    """하루(d) 일봉 처리. bars = {code: {o,h,l,c}}. 순서: ①전날 스탑 닿은 것 시가 청산 ②대기 주문 시가 체결/만료
    ③보유 봉 판정(스탑 닿음 → 다음 봉 시가 예약 · 같은 봉 목표는 무시(보수) · 1차 50%+본전 · 2차 · 시간 손절 종가) ④NAV."""
    m = book["market"]
    for p in list(book["positions"]):
        b = bars.get(p["code"])
        if p.get("exit_next") and b and _num(b.get("o")):
            _fill(book, "sell", p, b["o"], p["qty"] / p["qty0"], d, p["exit_next"])
            _close_pos(book, p, d, p["exit_next"])
    for o in list(book["pending"]):
        b = bars.get(o["code"])
        if o.get("after", o["created"]) >= d or not b or not _num(b.get("o")):
            continue
        book["pending"].remove(o)
        if not (o["lo"] <= b["o"] <= o["hi"]):
            book["fills"].append({"d": d, "code": o["code"], "name": o.get("name"), "kind": "expire", "px": b["o"], "frac": 0,
                                  "why": f"시가 {b['o']:,.2f} 진입 구간 {o['lo']:,.2f}~{o['hi']:,.2f} 밖 — 미진입 만료(추격 금지)"})
            continue
        nav = nav_of(book)
        e = b["o"]
        w = o["weight"]
        if _num(o.get("risk_pct")) and o["risk_pct"] > 0 and e > o["stop"]:
            # 체결가로 크기 재조정(축소만): 실현 리스크 = 비중 × (체결가−스탑)/체결가 ≤ 주문 리스크. 상향은 안 함(주문 때 남은 노출 기준).
            w = min(w, o["risk_pct"] / ((e - o["stop"]) / e))
        qty = w * nav / e
        if qty <= 0 or o["stop"] >= e:
            continue
        p = {"code": o["code"], "name": o.get("name"), "src": o["src"], "entry_d": d, "entry": e, "qty": qty, "qty0": qty,
             "stop": o["stop"], "stop0": o["stop"], "r_unit": e - o["stop"], "t1": o["t1"], "t2": o["t2"], "hold_t2": o["hold_t2"],
             "hold": o.get("hold", HOLD), "days": 0, "t1_done": False, "mark": e}
        book["positions"].append(p)
        _fill(book, "buy", p, e, 1.0, d, f"{o['src']} 시가 진입" + (f" · 체결가 재조정 {o['weight']*100:.2f}%→{w*100:.2f}%" if w < o["weight"] - 1e-9 else ""))
    for p in list(book["positions"]):
        b = bars.get(p["code"])
        if not b or not all(_num(b.get(k)) for k in "ohlc"):
            continue
        p["days"] += 1
        p["mark"] = b["c"]
        if b["l"] <= p["stop"]:
            p["exit_next"] = "스탑 닿음 → 다음 봉 시가 청산" if not p["t1_done"] else "본전 스탑 닿음 → 다음 봉 시가 청산"
            continue
        if not p["t1_done"] and b["h"] >= p["t1"]:
            frac = 0.5 if p["hold_t2"] else 1.0
            _fill(book, "sell", p, p["t1"], frac, d, "1차 목표" + (" 50% 익절 · 스탑 본전" if frac < 1 else " 전량(컨빅션 C 이하)"))
            if frac >= 1:
                _close_pos(book, p, d, "1차 목표 전량")
                continue
            p["t1_done"], p["stop"] = True, p["entry"]
        if p["t1_done"] and b["h"] >= p["t2"] and p in book["positions"]:
            _fill(book, "sell", p, p["t2"], p["qty"] / p["qty0"], d, "2차 목표")
            _close_pos(book, p, d, "2차 목표")
            continue
        if p["days"] >= p["hold"]:
            _fill(book, "sell", p, b["c"], p["qty"] / p["qty0"], d, f"시간 손절 {p['hold']}일 종가")
            _close_pos(book, p, d, "시간 손절")
    nav = nav_of(book)
    prev = book["nav"][-1] if book["nav"] else {"nav": START_NAV, "bench": None}
    ret = nav / prev["nav"] - 1 if prev["nav"] else 0.0
    bret = (bench_close / prev["bench"] - 1) if _num(bench_close) and _num(prev.get("bench")) else 0.0
    row = {"d": d, "nav": round(nav, 6), "bench": bench_close, "ret": round(ret, 6), "bench_ret": round(bret, 6),
           "excess": round(ret - bret, 6), "gross": round(gross_of(book), 4), "n_pos": len(book["positions"])}
    book["nav"].append(row)
    book["last_bar"] = d
    return row


def stats(book: dict) -> dict:
    nv = book["nav"]
    ex = [r["excess"] for r in nv[1:]] if len(nv) > 1 else []
    cum = (nv[-1]["nav"] / START_NAV - 1) if nv else 0.0
    b0 = next((r["bench"] for r in nv if _num(r.get("bench"))), None)
    bcum = (nv[-1]["bench"] / b0 - 1) if nv and b0 and _num(nv[-1].get("bench")) else None
    ir = None
    if len(ex) >= 20:
        mu = sum(ex) / len(ex)
        sd = (sum((x - mu) ** 2 for x in ex) / (len(ex) - 1)) ** 0.5
        ir = round(mu / sd * math.sqrt(252), 2) if sd > 0 else None
    cl = book["closed"]
    return {"nav": round(nv[-1]["nav"], 6) if nv else START_NAV, "cum": round(cum, 5), "bench_cum": round(bcum, 5) if bcum is not None else None,
            "excess_cum": round(cum - bcum, 5) if bcum is not None else None, "today_excess": nv[-1]["excess"] if nv else 0.0,
            "ir": ir, "ir_note": None if ir is not None else f"표본 {len(ex)}일 < 20 — IR 미산출",
            "n_closed": len(cl), "hit": round(sum(1 for c in cl if c["r"] > 0) / len(cl), 3) if cl else None,
            "avg_r": round(sum(c["r"] for c in cl) / len(cl), 3) if cl else None,
            "n_pos": len(book["positions"]), "gross": nv[-1]["gross"] if nv else 0.0, "n_days": len(nv)}


# ───────────── 신호 (B1 52주 고점 근접) ─────────────

def scan_52w(bars_by_code: dict, market: str = "KR", th: float = HI52_TH) -> list[dict]:
    """{code: [bars]} → 마지막 봉 기준 C/250일 고가 ≥ th 이고 유동성 통과한 종목(근접도·거래대금 순)."""
    mv, mp = LIQ[market]
    out = []
    for code, b in bars_by_code.items():
        b = [x for x in b if _num(x.get("c")) and _num(x.get("h"))]
        if len(b) < 250:
            continue
        c = b[-1]["c"]
        hi = max(x["h"] for x in b[-250:])
        val20 = sum(x["c"] * (x.get("v") or 0) for x in b[-20:]) / 20
        if c < mp or val20 < mv or hi <= 0:
            continue
        r = c / hi
        if r >= th:
            out.append({"code": code, "prox": round(r, 4), "val20": val20, "asof": b[-1].get("t")})
    return sorted(out, key=lambda x: (-x["prox"], -x["val20"]))


S4_VOL = 3.0                 # 2026-10-21_hf_desk_signals S4: 거래량 ≥ 20일 평균 × 3 + 종가 = 20일 최고 종가 → 10일 −1.3~−1.7%(t −7.4/−6.2, F)


def chase_s4(b: list[dict]) -> bool:
    """마지막 봉이 S4(거래량 터진 돌파 추격) 정의에 걸리면 True — B1 이어도 신규 롱 제외(10/23 HF 고도화)."""
    b = [x for x in b if _num(x.get("c"))]
    if len(b) < 21:
        return False
    v = [x.get("v") or 0 for x in b]
    v20 = sum(v[-21:-1]) / 20
    return v20 > 0 and v[-1] >= S4_VOL * v20 and b[-1]["c"] >= max(x["c"] for x in b[-20:])


# ───────────── 운용회의 개입 문장 (규칙 문장, LLM 아님) ─────────────

BANNED = ("병신", "장애인같", "틀딱", "한남", "김치녀", "짱깨", "쪽바리", "흑형", "급식충", "맘충", "홍어", "똥남아", "게이같", "정신병자", "애자")


def clean(s: str) -> str:
    """욕은 시장·포지션·자기 실수에만 — 혐오·차별 표현이 섞이면 그 문장을 버린다(빈 문자열)."""
    t = s.replace(" ", "")
    return "" if any(w in t for w in BANNED) else s


def entry_why(x: dict, market: str, srcs: dict | None = None, today: date | None = None) -> dict | None:
    """제안 1건의 진입 근거(기술·기대값·리스크·뒤집힘 + 펀더·내러티브·센티) — screener/entry_why.py. 실패는 None(문장 생략)."""
    try:
        from . import entry_why as EW
        g = ((srcs or {}).get(x.get("src")) or {}).get("grade")
        return EW.build(x, market, grade=g, today=today)
    except Exception as e:  # noqa: BLE001
        log.warning("알파북 진입 근거 실패(%s): %s", x.get("code"), e)
        return None


def say_line(st: dict, prop: list[dict], last_loss: dict | None, n_pass: int, src: dict | None, why: dict | None = None) -> str:
    """말투 줄(터미널·텔레그램 = 공개 보고서 → 욕 없음, 냉정한 톤만 · 10/21 겸이 지정). 우선순위: 직전 손절 → 제안 → 통과 소스 0 → 대기.
    제안 = 캐치프레이즈 대신 진입 근거 문장(10/24 겸이 "왜 진입하는지로") — why(entry_why) 없으면 order dict 숫자만으로."""
    if last_loss:
        s = f"{last_loss.get('name') or last_loss['code']} 손절({last_loss['r']:+.2f}R). 규칙대로 잘랐다. 다음."
    elif prop:
        x = prop[0]
        if why:
            s = why["tech"] + ". " + why["risk"] + "."
        else:
            s = (f"{x.get('name') or x['code']} = {x.get('src')} 통과 소스 신호"
                 + (f", 소스 OOS E[R] {x['ev_r']:+.3f}R vs 기준선 {x['base_ev_r']:+.3f}R" if _num(x.get("ev_r")) and _num(x.get("base_ev_r")) else "")
                 + f". 손절 {x['stop']:,.2f} 닿으면 다음 봉 시가 청산.")
    elif n_pass == 0:
        ev, base = (src or {}).get("ev_r"), (src or {}).get("base_ev_r")
        s = ("이 장에서 롱 타령은 근거 없다 — " + (f"기대값 {ev:+.2f}R, 기준선 {base:+.2f}R 밑. " if _num(ev) and _num(base) else "통과한 소스가 하나도 없어. ")
             + "현금 들고 사냥감 찾는 중.")
    else:
        s = ""          # 대기 상태는 말투 줄 생략(10/23 겸이 — 숫자 줄로 충분)
    return clean(s)


def hf_block(market: str, st: dict, prop: list[dict], no_prop_why: str | None, cio: str | None, srcs: dict,
             last_loss: dict | None, scale: dict) -> dict:
    """hf.md '운용회의 개입 형식' 4줄 + 말투 줄 + 텔레그램 1~2줄. 숫자 줄엔 욕 없음."""
    pas = [k for k, c in srcs.items() if c.get("pass") and SRC_MARKET.get(k) == market]
    exs = st.get("today_excess")
    l1 = (f"알파북 현재({market}): 포지션 {st['n_pos']}개 · 총노출 {st['gross']*100:.0f}% · 오늘 초과 {exs*100:+.2f}%p"
          + (f" · 누적 {st['cum']*100:+.2f}% (벤치 {st['bench_cum']*100:+.2f}%, 초과 {st['excess_cum']*100:+.2f}%p)" if st.get("bench_cum") is not None else "")
          + (f" · IR {st['ir']:+.2f}" if st.get("ir") is not None else f" · {st.get('ir_note')}"))
    if prop:
        x = prop[0]
        l2 = (f"이번 제안: {x.get('name') or x['code']} 롱({x['src']}) — {x.get('line') or ''} · 알파북 크기 {x['weight']*100:.1f}%(리스크 {x['risk_pct']*100:.2f}%)"
              + (f" 외 {len(prop)-1}건" if len(prop) > 1 else "") + f" · 소스 OOS E[R] {x['ev_r']:+.3f}R > 기준선 {x['base_ev_r']:+.3f}R")
    else:
        l2 = "이번 제안: 없음 — " + (no_prop_why or "사유 미상")
    risk_on = bool(prop) or st["n_pos"] > 0
    cio_s = cio or "판정 없음"
    if any(w in cio_s for w in ("관망", "방어", "지켜", "보류", "축소")) and risk_on:
        l3 = f"이견: CIO 판정 '{cio_s}' = 베타(시장 방향) 얘기 — 알파북은 통과 소스({', '.join(pas)}) 초과 기대값으로 크기 줄여 들어간다 (시장 배수 {scale['risk_mult']}, {SRC_FILE})"
    elif any(w in cio_s for w in ("매수", "공격", "확대", "강세")) and not pas:
        l3 = f"이견: CIO 판정 '{cio_s}'(롱)에 반대 — {market} 알파 소스 전부 기준선 이하({', '.join(k for k in srcs if SRC_MARKET.get(k) == market)} 미통과, {SRC_FILE})"
    else:
        l3 = f"이견: 없음 — CIO 판정 '{cio_s}', 알파북 노출 {st['gross']*100:.0f}% 방향 같음"
    l4 = (f"틀린 것: {last_loss.get('name') or last_loss['code']} {last_loss['why']} {last_loss['r']:+.2f}R ({last_loss['exit_d']})" if last_loss
          else "틀린 것: 아직 없음 — 청산 0건(첫 손절은 이 줄 첫머리에 박는다)")
    why = entry_why(prop[0], market, srcs) if prop else None
    say = say_line(st, prop, last_loss, len(pas), _first_src(srcs, market), why)
    if prop:
        x = prop[0]
        px = (lambda v: f"{v:,.0f}") if market == "KR" else (lambda v: f"{v:,.2f}")
        tp = (f"제안 {x.get('name') or x['code']} 롱 {px(x['lo'])}~{px(x['hi'])} · 손절 {px(x['stop'])} · 1차 {px(x['t1'])} · 2차 {px(x['t2'])}"
              f" · 크기 {x['weight']*100:.1f}%" + (f" 외 {len(prop)-1}" if len(prop) > 1 else ""))
    else:
        tp = "제안 없음 — " + (no_prop_why or "")[:80]
    tg = [f"🦈 <b>[HF 알파북 {market}]</b> 포지션 {st['n_pos']} · 노출 {st['gross']*100:.0f}% · 오늘 초과 {exs*100:+.2f}%p · {tp}"]
    if why:
        tg += ["  └ " + clean(x) for x in why["tg"] if clean(x)]
    elif say:
        tg.append("  └ " + say)
    lines = [l1, l2, l3, l4] + [clean(x) for x in (why or {}).get("long", []) if clean(x)]   # 4줄 형식 + 진입 근거 펼침
    return {"v": 1, "lines": lines, "say": say, "tg": tg, "mock": True, "why": why,
            "note": "알파북 = 가상 1단위 모의(실계좌 근거 아님). 규칙 문장(LLM 아님) — screener/alphabook.py"}


def _first_src(srcs: dict, market: str) -> dict | None:
    xs = [c for k, c in srcs.items() if SRC_MARKET.get(k) == market and _num((c.get("test") or {}).get("ev_r"))]
    if not xs:
        return None
    best = max(xs, key=lambda c: c["test"]["ev_r"] - (c.get("base_test") or {}).get("ev_r", 0))
    return {"ev_r": best["test"]["ev_r"], "base_ev_r": (best.get("base_test") or {}).get("ev_r")}


def src_info(srcs: dict, key: str) -> dict | None:
    c = srcs.get(key)
    if not c:
        return None
    t, b = c.get("test") or {}, c.get("base_test") or {}
    return {"key": key, "pass": bool(c.get("pass")), "grade": c.get("grade"), "ev_r": t.get("ev_r"), "base_ev_r": b.get("ev_r"),
            "p_t1": t.get("p_t1"), "p_stop": t.get("p_s"), "p_t2": t.get("p_t2"), "n": t.get("n"), "n_dates": t.get("n_dates"),
            "t": (c.get("ex_test") or {}).get("t")}


def apply_src_prob(plan: dict, si: dict) -> dict:
    """계획의 확률·기대값을 알파 소스 OOS 성적으로 교체(같은 엔진·같은 칸)하고 판정 재계산."""
    plan = dict(plan)
    plan["prob"] = {"group": f"alpha_{si['key']}", "cell": "struct 1.5/3.0", "grade": si["grade"], "p_t1": si["p_t1"], "p_stop": si["p_stop"],
                    "p_t2": si["p_t2"], "ev_r": si["ev_r"], "base_ev_r": si["base_ev_r"], "n": si["n"], "n_dates": si["n_dates"], "src": SRC_FILE}
    plan["ev_r"] = si["ev_r"]
    plan["ev_pct"] = si["ev_r"] * plan["stop"]["pct"] if _num(si.get("ev_r")) else None
    hard = [w for w in (plan.get("why_not") or []) if not str(w).startswith(("보정 E[R]", "확률·기대값", "E[R]"))]
    plan["why_not"] = hard
    plan["verdict"] = "보류" if hard else "채택(모의)"
    try:
        from .tradeplan import plan_line
        plan["line"] = plan_line(plan)
    except Exception:  # noqa: BLE001
        pass
    return plan


# ───────────── 파일 읽기·쓰기 (committee 에서 호출) ─────────────

def _root():
    from .config import REPORT_DIR
    return REPORT_DIR


def load_state(path: Path | None = None) -> dict:
    p = path or (_root() / "alphabook.json")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"v": 1, "books": {}}


def load_sources() -> dict:
    try:
        return json.loads((_root().parent / SRC_FILE).read_text(encoding="utf-8")).get("cells") or {}
    except Exception:  # noqa: BLE001
        return {}


def _bars(code: str, market: str) -> list[dict]:
    from .tradeplan import _detail, kr_bars_local
    b = (_detail(code, market).get("chart") or [])
    if not b and market == "KR":
        b = kr_bars_local(code)
    return [{"t": x.get("t") or x.get("d"), "o": x.get("o"), "h": x.get("h"), "l": x.get("l"), "c": x.get("c"), "v": x.get("v")} for x in b]


def _kr_universe_bars(n: int = 260) -> tuple[dict, dict]:
    import polars as pl
    from .prices import load_kr
    px = load_kr().sort("yf", "date")
    last = px["date"].max()
    px = px.filter(pl.col("date") >= last - timedelta(days=int(n * 1.6)))
    out = {}
    for (yf,), g in px.group_by(["yf"], maintain_order=True):
        out[yf[:6]] = [{"t": str(d), "o": o, "h": h, "l": l, "c": c, "v": v} for d, o, h, l, c, v in
                       zip(g["date"], g["open"], g["high"], g["low"], g["close"], g["volume"])]
    names = {}
    try:
        u = pl.read_csv(_root().parent / "universe" / "kr.csv", schema_overrides={"symbol": pl.Utf8})
        names = dict(zip(u["symbol"], u["name"]))
    except Exception:  # noqa: BLE001
        pass
    return out, names


def _cutoff(market: str, now: datetime) -> str:
    """완성된 봉만 처리: KR 은 16:00 KST 전이면 오늘 봉 제외. US 는 KST 낮 회의라 전날 봉까지 완성."""
    if market == "KR" and now.hour < 16:
        return str(now.date() - timedelta(days=1))
    return str(now.date())


def _after(market: str, now: datetime, last_bar: str | None) -> str:
    """체결 기준일: KR 은 09:00 KST 이후 결정이면 오늘 시가는 이미 지남 → 내일 시가. US 는 KST 22시 전이면 미 정규장 전 → 마지막 완성 봉 다음."""
    today = str(now.date())
    if market == "KR":
        return today if now.hour >= 9 else (last_bar or str(now.date() - timedelta(days=1)))
    from .tradecal import us_open_kst   # 개장 30분 전 = 여름 22:00·겨울 23:00 KST (ET 로 계산, 서머타임 대응)
    n = now if now.tzinfo else now.replace(tzinfo=KST)
    return (last_bar or str(now.date() - timedelta(days=1))) if n < us_open_kst(today) - timedelta(minutes=30) else today


def update(o: dict, market: str = "KR", now: datetime | None = None, state_path: Path | None = None) -> dict:
    """committee 산출물 o 에 hf 블록 부착 + reports/alphabook.json 갱신. 실패는 o['hf']['error'] 로 남긴다."""
    now = now or datetime.now(KST)
    today = str(now.date())
    path = state_path or (_root() / "alphabook.json")
    S = load_state(path)
    srcs = load_sources()
    book = (S.get("books") or {}).get(market) or new_book(market, today)
    cut = _cutoff(market, now)
    # ① 지난 봉 처리 (벤치 날짜 기준)
    bench = [x for x in _bars(BENCH[market], market) if x["t"] and x["t"] <= cut]
    codes = {p["code"] for p in book["positions"]} | {x["code"] for x in book["pending"]}
    series = {c: {x["t"]: x for x in _bars(c, market)} for c in codes}
    for bb in bench:
        if book["last_bar"] and bb["t"] <= book["last_bar"]:
            continue
        if not book["last_bar"] and bb["t"] < (bench[-1]["t"] if bench else ""):
            continue   # 새 북: 마지막 완성 봉 하나로 NAV 기준점만
        step_day(book, bb["t"], {c: s.get(bb["t"]) for c, s in series.items() if s.get(bb["t"])}, bb["c"])
    st = stats(book)
    # ② 시장 배수
    try:
        from . import tradeplan
        ctx = tradeplan.market_ctx(o, market, now.date())
        scale = regime_scale(tradeplan.macro_filter(ctx, None, market, None))
    except Exception as e:  # noqa: BLE001
        tradeplan, ctx, scale = None, {}, regime_scale(None)
        log.warning("alphabook 시장 필터 실패: %s", e)
    # ③ 제안 (통과 소스만)
    pass_keys = [k for k, c in srcs.items() if c.get("pass") and SRC_MARKET.get(k) == market]
    prop, why_none, rejected = [], None, []
    if not srcs:
        why_none = f"알파 소스 연구 결과 없음({SRC_FILE}) — 탐색 중, 현금"
    elif not pass_keys:
        fs = [f"{k} {c.get('grade')}" for k, c in srcs.items() if SRC_MARKET.get(k) == market]
        why_none = f"{market} 통과 소스 0 ({', '.join(fs)}) — 기대값 ≤ 기준선, 현금 + 탐색 중(억지 진입 금지)"
    elif not scale["new_ok"]:
        why_none = scale["why"]
    elif len(book["positions"]) + len(book["pending"]) >= MAX_POS:
        why_none = f"포지션 상한 {MAX_POS}개 — 신규 없음"
    elif any(x["created"] == today for x in book["pending"]):
        prop = [x for x in book["pending"] if x["created"] == today]
    elif "B1" in pass_keys and market == "KR" and tradeplan is not None:
        si = src_info(srcs, "B1")
        try:
            ub, names = _kr_universe_bars()
            held = codes
            hits = [h for h in scan_52w(ub, "KR") if h["code"] not in held]
            cal = []
            try:
                cal = json.loads((_root() / "calendar.json").read_text(encoding="utf-8")).get("events") or []
            except Exception:  # noqa: BLE001
                pass
            calib = tradeplan.load_calib()
            nav, g = nav_of(book), gross_of(book)
            for h in hits[:40]:
                if len(prop) >= MAX_NEW:
                    break
                if chase_s4(ub.get(h["code"]) or []):
                    rejected.append({"code": h["code"], "name": names.get(h["code"]), "why": ["S4 추격(거래량 3배 + 20일 최고 종가 — 10일 −1.3~−1.7%, F)"]})
                    continue
                p = tradeplan.plan_for(h["code"], "KR", o, ctx, calib, cal, now.date(), [{"k": "hi52", "side": "agree", "label": "52주 고점 근접"}], names.get(h["code"]))
                if not p:
                    p = tradeplan.build_plan(ub.get(h["code"]) or [], market="KR", ctx=ctx, calib=calib, code=h["code"], name=names.get(h["code"]))
                if not p:
                    continue
                p = apply_src_prob(p, si)
                no = gate(p, si)
                if no:
                    rejected.append({"code": h["code"], "name": p.get("name"), "why": no[:2]})
                    continue
                sz = size(p, nav, g + sum(x["weight"] for x in prop), scale)
                if sz["weight"] <= 0.001:
                    rejected.append({"code": h["code"], "name": p.get("name"), "why": ["남은 총노출 없음"]})
                    break
                od = order(p, si, sz, today, _after(market, now, book["last_bar"]))
                od.update({"prox": h["prox"], "formula": sz["formula"]})
                prop.append(od)
            book["pending"] += prop
            if not prop:
                why_none = (f"B1 신호 {len(hits)}건 중 계획 게이트 통과 0 — " + "; ".join(f"{r['name'] or r['code']}: {r['why'][0]}" for r in rejected[:2])) if hits else "B1(52주 고점 근접) 신호 0건 — 대기"
        except Exception as e:  # noqa: BLE001
            why_none = f"신호 스캔 실패({type(e).__name__}: {e}) — 데이터 없음, 신규 0"
            log.warning("alphabook 스캔 실패: %s", e)
    else:
        why_none = f"통과 소스 {pass_keys} 의 실시간 신호 연결 전 — 신규 0"
    last_loss = next((c for c in reversed(book["closed"]) if c["r"] < 0), None)
    cio = ((o.get("stance") or {}).get("stance") if market == "KR" else None) or ((o.get("bottom_line") or {}).get("label") or "").lstrip("🟢🟡🔴⚪ ").strip() or None
    blk = hf_block(market, st, prop, why_none, cio, srcs, last_loss, scale)
    blk.update({"asof": today, "cut": cut, "stats": st, "scale": scale, "proposals": prop, "rejected": rejected[:5],
                "sources": {k: {"grade": c.get("grade"), "pass": bool(c.get("pass"))} for k, c in srcs.items() if SRC_MARKET.get(k) == market},
                "state": "운용" if st["n_pos"] else "진입 대기(다음 봉 시가)" if book["pending"] else ("탐색 중(현금)" if not pass_keys else "대기(현금)")})
    if market == "KR":
        dl = disc_line()
        if dl:
            blk["disc"] = dl
            blk["tg"] = list(blk["tg"]) + [dl]
    o["hf"] = blk
    S.setdefault("books", {})[market] = book
    S.update({"v": 1, "updated": now.strftime("%Y-%m-%d %H:%M KST"), "mock": True, "unit": "가상 1단위(NAV 1.0)",
              "rules": "screener/alphabook.py 머리말 · docs/desk_kb/hf.md", "sources_file": SRC_FILE})
    S.setdefault("summary", {})[market] = {"state": blk["state"], "stats": st, "lines": blk["lines"], "say": blk["say"], "asof": today}
    try:   # 보고 상단 형식 top(STANDARD 8절) — 블록·파일 둘 다 추가만
        from . import topline_from
        blk["top"] = topline_from.alphabook_block(blk, market)
        S["top"] = topline_from.alphabook(S)
    except Exception as e:  # noqa: BLE001
        blk["top_error"] = f"{type(e).__name__}: {e}"
    try:
        path.write_text(json.dumps(S, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        blk["error"] = f"상태 저장 실패: {e}"
    return blk


DISC_PREFIX = "🧪 HF 재량·모의(가상 1,000억) — 겸이 실계좌 해당 없음"
DISC_BANNED = ("매수하세요", "매도하세요", "사세요", "파세요", "사라", "팔아", "들어가", "계약", "행사가")


def disc_line(path: Path | None = None) -> str | None:
    """HF 재량 북(모의 — scripts/hf_book.py 장부) 텔레그램 1줄. PB 10/21 문구 규칙: 고정 접두, 결과만(방향·R·손익%),
    계약 수·행사가·주문형/명령형 표현 금지(그건 장부·화면에만). 평가는 회의 라운드의 mark 값 그대로."""
    try:
        b = json.loads((path or _root() / "hf_discretion.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    op, cl = b.get("open") or [], b.get("closed") or []
    if not op and not cl:
        return None
    parts = []
    for p in op[:3]:
        sgn = 1 if p.get("side") == "롱" else -1
        r = (p["last"] - p["entry"]) * sgn / p["r_unit"] if p.get("r_unit") else 0.0
        pct = (p["last"] / p["entry"] - 1) * sgn if p.get("entry") else 0.0
        what = {"fut": "지수 선물", "put": "지수 하락 보험", "call": "지수 상승 옵션", "es": "미 S&P 선물", "nq": "미 나스닥 선물",
                "spx_put": "미 S&P 하락 보험", "spx_call": "미 S&P 상승 옵션"}.get(p.get("kind"), p.get("name") or "")
        up = (sgn > 0) != (p.get("kind") in ("put", "spx_put"))      # 풋 보유 = 하락 쪽 노출
        parts.append(f"{what} {'상승' if up else '하락'} 쪽 {r:+.2f}R({pct * 100:+.1f}%)")
    tail = f" · 청산 {len(cl)}건 평균 {sum(c['r'] for c in cl) / len(cl):+.2f}R" if cl else ""
    ln = f"  {DISC_PREFIX}: " + (" · ".join(parts) if parts else "포지션 없음") + tail
    return None if any(w in ln for w in DISC_BANNED) else clean(ln)


def telegram_tail(o: dict) -> list[str]:
    hf = o.get("hf") or {}
    tg = list((hf.get("tg") or [])[:6])      # 머리 1 + 진입 근거 4 + 재량 1 (10/24)
    from . import config
    if getattr(config, "TOPLINE_TG", False) and hf.get("top") and tg:   # 3줄형 스위치(기본 꺼짐) — 머리 1줄만 교체
        from .topline import render_tg3
        return render_tg3(hf["top"]).split("\n") + tg[1:]
    return tg
