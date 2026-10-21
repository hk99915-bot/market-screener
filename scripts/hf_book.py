#!/usr/bin/env python3
"""HF 재량 북 — 회의 때 시그널 보고 그때그때 롱·숏·선물·옵션을 거는 모의 장부 (겸이 10/21 20시 "그때그때 시그널 보고 결정").

  python3 scripts/hf_book.py add --kind stock --side 숏 --code 005930 --stop 120000 --t1 95000 --why "..." --src reports/committee.json
  python3 scripts/hf_book.py add --kind put --strike 850 --expiry 2026-11-12 --why "..." --src reports/committee.json
  python3 scripts/hf_book.py mark      # 최신 종가로 평가 · 손절/목표/만기/시간 손절 청산
  python3 scripts/hf_book.py show      # 라운드 기록용 요약 줄

상태 reports/hf_discretion.json. 가상 1단위 모의 — 실계좌 주문 아님. 체계 북(screener/alphabook.py)과 따로 채점.
가격: 주식 = screener.prices.load_kr 종가, 선물 = data/deriv/daily.csv fut_close(없으면 k200_close),
옵션 = 코스피200 블랙숄즈(σ = atm_iv, 없으면 VKOSPI/100, r 2.5%) — 실제 호가 아님(근사 표기).
한도: 1건 리스크 0.25% · 열린 리스크 합 1.0% · 동시 6건. 옵션 매수는 프리미엄 전액 = 리스크.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
STATE = ROOT / "reports" / "hf_discretion.json"
KST = timezone(timedelta(hours=9))
RISK_1, RISK_ALL, MAX_OPEN = 0.0025, 0.01, 6
RATE = 0.025
COST = {"stock": 0.0045, "fut": 0.0004, "put": 0.02, "call": 0.02}   # 왕복(옵션은 프리미엄 대비 호가 폭 가정)
HOLD = {"stock": 20, "fut": 10}


def ncdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs(kind: str, s: float, k: float, t: float, sig: float, r: float = RATE) -> float:
    if t <= 0:
        return max(0.0, (s - k) if kind == "call" else (k - s))
    d1 = (math.log(s / k) + (r + sig * sig / 2) * t) / (sig * math.sqrt(t))
    d2 = d1 - sig * math.sqrt(t)
    if kind == "call":
        return s * ncdf(d1) - k * math.exp(-r * t) * ncdf(d2)
    return k * math.exp(-r * t) * ncdf(-d2) - s * ncdf(-d1)


def deriv_last() -> dict:
    import csv
    rows = list(csv.DictReader(open(ROOT / "data" / "deriv" / "daily.csv", encoding="utf-8")))
    last = rows[-1]
    f = lambda k: float(last[k]) if last.get(k) not in (None, "") else None  # noqa: E731
    iv = f("atm_iv") or ((f("rep_iv") or 0) / 100 or None)
    if iv is None:
        iv = next(float(r["rep_iv"]) / 100 for r in reversed(rows) if r.get("rep_iv"))
    return {"date": last["date"], "k200": f("k200_close"), "fut": f("fut_close") or f("k200_close"), "iv": iv}


def stock_last(code: str) -> tuple[str, float, str]:
    import polars as pl
    from screener.prices import load_kr
    df = load_kr().filter(pl.col("yf").str.starts_with(code)).sort("date")
    if not len(df):
        raise SystemExit(f"가격 없음: {code}")
    nm = code
    try:
        names = json.loads((ROOT / "data" / "flows" / "names.json").read_text())
        nm = names.get(code, code) if isinstance(names, dict) else code
    except Exception:
        pass
    return str(df["date"][-1])[:10], float(df["close"][-1]), nm


def price(p: dict, d: dict) -> float:
    if p["kind"] == "stock":
        return stock_last(p["code"])[1]
    if p["kind"] == "fut":
        return d["fut"]
    t = (date.fromisoformat(p["expiry"]) - date.fromisoformat(d["date"])).days / 365
    return bs(p["kind"], d["k200"], p["strike"], t, d["iv"])


def load() -> dict:
    return json.loads(STATE.read_text()) if STATE.exists() else {"v": 1, "note": "HF 재량 북 — 가상 1단위 모의, 실계좌 주문 아님. 옵션 가격 = BS 근사.", "open": [], "closed": []}


def save(b: dict):
    b["asof"] = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    STATE.write_text(json.dumps(b, ensure_ascii=False, indent=1))


def open_risk(b: dict) -> float:
    return sum(p["risk"] for p in b["open"])


def add(b: dict, a) -> dict:
    if len(b["open"]) >= MAX_OPEN:
        raise SystemExit(f"동시 {MAX_OPEN}건 한도 — 하나 자르고 와")
    risk = min(a.risk, RISK_1, RISK_ALL - open_risk(b))
    if risk <= 0:
        raise SystemExit("열린 리스크 합 1.0% 한도 꽉 참")
    d = deriv_last()
    sgn = 1 if a.side == "롱" else -1
    p = {"id": f"{d['date']}-{len(b['open']) + len(b['closed']) + 1}", "kind": a.kind, "side": a.side, "why": a.why, "src": a.src}
    if a.kind == "stock":
        dt, px, nm = stock_last(a.code)
        p.update(code=a.code, name=a.name or nm, asof=dt)
    elif a.kind == "fut":
        px = d["fut"]
        p.update(code="K200F", name="코스피200 선물", asof=d["date"])
    else:
        if a.side != "롱":
            raise SystemExit("옵션 매도는 금지 — 국장 VRP ≈ 0 (reports/studies/2026-10-21_hf_ls_vol.md V1)")
        p.update(code="K200O", name=f"코스피200 {'풋' if a.kind == 'put' else '콜'} {a.strike:g} ({a.expiry})",
                 strike=a.strike, expiry=a.expiry, asof=d["date"], iv=round(d["iv"], 4), spot=d["k200"])
        px = price(p, d)
    p["entry"] = round(px, 4)
    if a.kind in ("put", "call"):
        p.update(stop=None, t1=round(px * 2, 4), r_unit=px, weight=round(risk, 5), risk=round(risk, 5), hold=None)
    else:
        if a.stop is None or (a.stop - px) * sgn >= 0:
            raise SystemExit("손절가 없거나 방향이 틀림 — 손절 없는 계획은 안 받아")
        stop_pct = abs(px - a.stop) / px
        w = min(risk / stop_pct, 0.15)
        p.update(stop=a.stop, t1=a.t1, t2=a.t2, r_unit=abs(px - a.stop), weight=round(w, 4), risk=round(w * stop_pct, 5),
                 hold=a.hold or HOLD[a.kind], stop_pct=round(stop_pct, 4))
    p["days"] = 0
    p["last"] = p["entry"]
    b["open"].append(p)
    return p


def r_of(p: dict, px: float) -> float:
    sgn = 1 if p["side"] == "롱" else -1
    return (px - p["entry"]) * sgn / p["r_unit"] - COST[p["kind"]] * p["entry"] / p["r_unit"]


def mark(b: dict) -> list[dict]:
    d = deriv_last()
    out, keep = [], []
    for p in b["open"]:
        px = price(p, d)
        p["last"] = round(px, 4)
        p["days"] += 1
        sgn = 1 if p["side"] == "롱" else -1
        why = None
        if p["kind"] in ("put", "call"):
            if d["date"] >= p["expiry"]:
                why = "만기"
            elif px >= p["t1"]:
                why = "프리미엄 2배 — 절반 아니고 전량 익절(재량 북 단순화)"
        else:
            if (px - p["stop"]) * sgn <= 0:
                why = "손절 — 묻지도 따지지도 않음"
            elif p.get("t1") and (px - p["t1"]) * sgn >= 0:
                why = "1차 목표"
            elif p["days"] >= p["hold"]:
                why = "시간 손절"
        if why:
            p.update(exit=round(px, 4), exit_d=d["date"], exit_why=why, r=round(r_of(p, px), 3))
            b["closed"].append(p)
            out.append(p)
        else:
            keep.append(p)
    b["open"] = keep
    return out


def show(b: dict) -> list[str]:
    d = deriv_last()
    ls = [f"재량 북: 열린 {len(b['open'])}건 · 열린 리스크 {open_risk(b) * 100:.2f}% (한도 1.00%) · 청산 {len(b['closed'])}건"
          + (f" · 평균 {sum(x['r'] for x in b['closed']) / len(b['closed']):+.2f}R · 적중 {sum(x['r'] > 0 for x in b['closed'])}/{len(b['closed'])}" if b["closed"] else "")]
    for p in b["open"]:
        cur = r_of(p, p["last"])
        lv = f"손절 {p['stop']:,.2f} · 1차 {p['t1']:,.2f}" if p["stop"] is not None else f"최대손실 = 프리미엄 · 익절 {p['t1']:,.2f}"
        ls.append(f"- {p['side']} {p['name']} 진입 {p['entry']:,.2f} → {p['last']:,.2f} ({cur:+.2f}R) · {lv} · 크기 {p['weight'] * 100:.2f}% · 근거: {p['why']}")
    for p in b["closed"][-3:]:
        ls.append(f"- 청산 {p['side']} {p['name']} {p['r']:+.2f}R ({p['exit_why']}, {p['exit_d']})")
    ls.append(f"(가격 기준 {d['date']} · 옵션 = BS 근사 σ {d['iv']:.1%} · 모의)")
    return ls


def main(argv=None):
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    a1 = sp.add_parser("add")
    a1.add_argument("--kind", choices=["stock", "fut", "put", "call"], required=True)
    a1.add_argument("--side", choices=["롱", "숏"], default="롱")
    a1.add_argument("--code")
    a1.add_argument("--name")
    a1.add_argument("--stop", type=float)
    a1.add_argument("--t1", type=float)
    a1.add_argument("--t2", type=float)
    a1.add_argument("--strike", type=float)
    a1.add_argument("--expiry")
    a1.add_argument("--hold", type=int)
    a1.add_argument("--risk", type=float, default=RISK_1)
    a1.add_argument("--why", required=True)
    a1.add_argument("--src", required=True)
    sp.add_parser("mark")
    sp.add_parser("show")
    a = ap.parse_args(argv)
    b = load()
    if a.cmd == "add":
        p = add(b, a)
        save(b)
        print(json.dumps(p, ensure_ascii=False))
    elif a.cmd == "mark":
        for p in mark(b):
            print(f"청산 {p['name']} {p['r']:+.2f}R — {p['exit_why']}")
        save(b)
    print("\n".join(show(b)))


if __name__ == "__main__":
    main()
