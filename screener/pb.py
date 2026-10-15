"""개인 PB 아침 브리핑 — 보유 내역은 GitHub 비공개 시크릿 MY_HOLDINGS 에서만 읽는다 (저장소·로그에 남기지 않음).

MY_HOLDINGS 형식 (웹 MY 탭과 동일, 한 줄에 하나):
    005930 11 260864
    TIGER 200 IT 17 128855
    MU 1 857.5
    USD 2223.07
    현금 3164341
선택: MY_RULES — 줄마다 '종목코드 가격' (종가 2일 연속 이탈 시 경고), 'LOSS_LIMIT 0.12' (순자산 대비 손실 한도), 'SEMI_CAP 0.6'
"""
from __future__ import annotations

import json
import logging
import os
import re

from .config import REPORT_DIR

log = logging.getLogger(__name__)


def _num(x):
    try:
        return float(str(x).replace(",", ""))
    except ValueError:
        return None


def parse(txt: str) -> tuple[list[dict], float, float]:
    hs, krw, usd = [], 0.0, 0.0
    for ln in txt.splitlines():
        p = ln.strip().split()
        if not p:
            continue
        k = p[0].upper()
        if k in ("현금", "KRW", "CMA", "원화", "예수금", "RP") or k.startswith("CMA"):
            krw += _num(p[1]) or 0
            continue
        if k in ("USD", "달러", "미국달러"):
            usd += _num(p[1]) or 0
            continue
        nums = []
        i = len(p)
        while i > 1 and len(nums) < 2 and _num(p[i - 1]) is not None:
            nums.insert(0, _num(p[i - 1]))
            i -= 1
        hs.append({"key": " ".join(p[:i]), "qty": nums[0] if nums else 0, "avg": nums[1] if len(nums) > 1 else None})
    return hs, krw, usd


def _index() -> list[tuple[str, str, str]]:
    out = []
    for mk in ("KR", "US"):
        p = REPORT_DIR / "detail" / mk / "_index.json"
        if p.exists():
            j = json.loads(p.read_text(encoding="utf-8"))
            out += [(mk, s, str((j.get("names") or {}).get(s, s))) for s in j.get("symbols", [])]
    return out


def resolve(key: str, idx) -> tuple[str, str] | None:
    k = key.lower().strip()
    for mk, s, n in idx:
        if s.lower() == k or n.lower() == k:
            return mk, s
    if re.fullmatch(r"[a-z][a-z.\-]{0,5}|\d{6}", k):
        return None
    for mk, s, n in idx:
        if n.lower().startswith(k) or k.replace(" ", "") in n.lower().replace(" ", ""):
            return mk, s
    return None


def _detail(mk: str, s: str) -> dict | None:
    p = REPORT_DIR / "detail" / mk / f"{s}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def brief() -> str | None:
    txt = os.environ.get("MY_HOLDINGS", "").strip()
    if not txt:
        return None
    rules_txt = os.environ.get("MY_RULES", "")
    loss_limit, semi_cap, price_rules = 0.12, 0.60, {}
    for ln in rules_txt.splitlines():
        p = ln.split()
        if len(p) >= 2 and p[0].upper() == "LOSS_LIMIT":
            loss_limit = _num(p[1]) or loss_limit
        elif len(p) >= 2 and p[0].upper() == "SEMI_CAP":
            semi_cap = _num(p[1]) or semi_cap
        elif len(p) >= 2 and _num(p[1]):
            price_rules[p[0].upper()] = _num(p[1])
    hs, krw, usd = parse(txt)
    idx = _index()
    try:
        ms = json.loads((REPORT_DIR / "macro_series.json").read_text(encoding="utf-8"))["series"]["USDKRW"]
        fx = ms[-1][4] if len(ms[-1]) >= 6 else ms[-1][1]
    except Exception:  # noqa: BLE001
        fx = 1400.0
    rows, tot, cost, miss = [], 0.0, 0.0, []
    for h in hs:
        r = resolve(h["key"], idx)
        d = _detail(*r) if r else None
        if not d:
            miss.append(h["key"])
            continue
        mk, s = r
        f = fx if mk == "US" else 1.0
        v = d["close"] * h["qty"] * f
        c = h["avg"] * h["qty"] * f if h["avg"] else None
        dv = d.get("drivers") or {}
        look = ((d.get("etf") or {}).get("look") or {})
        chain = (dv.get("chain") or {}).get("name") or ("ETF" if d.get("etf") else (d.get("valuation") or {}).get("sector")) or mk
        st = d.get("stats") or {}
        c1y = d.get("c1y") or []
        rows.append({"mk": mk, "s": s, "name": re.sub(r",?\s+(Inc\.?|Corporation|Corp\.?)$", "", re.sub(r"\s*[-–]\s*(Common Stock|Ordinary).*$", "", d.get("name") or s)),
                     "v": v, "c": c, "r1": st.get("ret1"), "drv": dv.get("score") if not d.get("etf") else look.get("drv"),
                     "stop": ((d.get("scenarios") or {}).get("bear") or {}).get("stop"), "close": d["close"], "etf": bool(d.get("etf")),
                     "semi": bool(re.search(r"반도체|IT 하드웨어", chain)) or (d.get("etf") and sum(w for k, w in (look.get("chains") or {}).items() if re.search(r"반도체|IT 하드웨어", k)) > 0.5)
                     or s in ("MU", "SNDK", "NVDA", "AMD", "AVGO", "TSM", "SOXX", "SMH", "PSI", "SOXL"),
                     "last2": [x[1] for x in c1y[-2:]]})
        tot += v
        if c:
            cost += c
    cash = krw + usd * fx
    nav = tot + cash
    if not rows:
        return None
    semi = sum(r["v"] for r in rows if r["semi"])
    loss = cost - sum(r["v"] for r in rows if r["c"])
    room = loss_limit * nav - loss
    day = sum(r["v"] - r["v"] / (1 + r["r1"]) for r in rows if r["r1"] is not None)
    L = ["🧑‍💼 <b>PB 아침 점검</b>",
         f"순자산 <b>{nav:,.0f}원</b> · 주식 {tot/nav*100:.0f}% · 현금 {cash/nav*100:.0f}%",
         f"주식 손익 {(-loss)/cost*100 if cost else 0:+.1f}% ({-loss:+,.0f}원) · 최근일 {day:+,.0f}원"]
    L.append("")
    L.append("<b>규칙 점검</b>")
    L.append(f"• 손실 한도(순자산 −{loss_limit*100:.0f}%)까지 " + (f"<b>{room:,.0f}원</b> 남음 (주식 −{room/tot*100:.1f}% 추가 하락 여유)" if room > 0 else "<b>⛔ 한도 도달 — 메모리 절반 축소 실행</b>"))
    L.append(f"• 반도체 비중 순자산 {semi/nav*100:.0f}% (상한 {semi_cap*100:.0f}%)" + (" ⛔ 초과 — 추가 매수 금지" if semi / nav > semi_cap + 0.005 else " ✅"))
    for code, px in price_rules.items():
        r = next((x for x in rows if x["s"].upper() == code), None)
        if not r:
            continue
        below = [p for p in r["last2"] if p is not None and p < px]
        tag = "⛔ 2일 연속 이탈 — 실행" if len(below) == 2 else "⚠️ 1일 이탈" if len(below) == 1 else "✅"
        L.append(f"• {r['name']} 기준 {px:,.0f} · 최근 종가 {r['close']:,.0f} ({r['close']/px*100-100:+.1f}%) {tag}")
    L.append("")
    L.append("<b>보유</b>")
    for r in sorted(rows, key=lambda x: -x["v"]):
        drv = f" · 드라이버 {r['drv']:+.2f}" if r["drv"] is not None else ""
        pnl = f" · 손익 {(r['v']/r['c']-1)*100:+.1f}%" if r["c"] else ""
        L.append(f"• {r['name']}{' (ETF)' if r['etf'] else ''} {r['v']/nav*100:.0f}% · 1D {(r['r1'] or 0)*100:+.1f}%{pnl}{drv}")
    try:   # 보유 종목·규칙 관련 이벤트 7일 내
        from .calendar_ev import upcoming
        mine = {r["s"] for r in rows}
        up = [e for e in upcoming(7) if e.get("ticker") in mine or e.get("imp", 1) >= 3]
        if up:
            L.append("")
            L.append("<b>7일 내 이벤트</b>")
            L += [f"• {e['date'][5:]} {'📌 ' if e.get('ticker') in mine else ''}{e['name']}" + (f" — {e['note']}" if e.get("note") else "") for e in up[:8]]
    except Exception:  # noqa: BLE001
        pass
    try:
        ev = json.loads((REPORT_DIR / "events_stats.json").read_text(encoding="utf-8"))
        rec = [e for e in ev.get("events", [])[:5] if not e.get("type", "").startswith("경보")]
        if rec:
            L.append("")
            L.append("<b>최근 이벤트</b> " + " / ".join(f"{e['date'][5:]} {e['market']} {e['type']}" for e in rec[:3]))
    except Exception:  # noqa: BLE001
        pass
    try:
        mv = json.loads((REPORT_DIR / "macro_view.json").read_text(encoding="utf-8"))
        if mv.get("summary"):
            L.append("")
            L.append("<b>매크로</b> " + mv["summary"])
    except Exception:  # noqa: BLE001
        pass
    if miss:
        L.append("")
        L.append("인식 못 한 종목: " + ", ".join(miss))
    return "\n".join(L)


def send() -> bool:
    t = brief()
    if not t:
        log.info("PB: MY_HOLDINGS 없음 — 건너뜀")
        return False
    from .report import send_telegram
    send_telegram(t)
    log.info("PB 아침 점검 전송")   # 내용은 로그에 남기지 않음
    return True
