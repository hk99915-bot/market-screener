#!/usr/bin/env python3
"""HF 바스켓 엔진 — 5차 Q1b(저변동 롱 / 고변동 숏, 다리 배율 ≤ 1.5, 21거래일) 를 재량 북 안에서 굴린다 (겸이 10/23 "바스켓 엔진 만들어조").

  python3 scripts/hf_basket.py open [--dry] [--risk 0.004]   # 바스켓 구성·진입(장중이면 heatmap 장중가)
  python3 scripts/hf_basket.py mark                          # 평가·바스켓 손절·21거래일 시간 청산 (hf_book mark 가 자동 호출)
  python3 scripts/hf_basket.py show
  python3 scripts/hf_basket.py close --why "..."             # 재량 전량 청산

상태 = reports/hf_discretion.json 의 "baskets" {open, closed}. hf_book 이 열린 리스크·손익·한도·show 에 합산한다.
근거 reports/studies/2026-10-23_hf_bab_recheck.md (Q1b OOS +3.20%/기간 t 3.28 B · 최악 1기간 −31.9%(학습)).
단일 종목 손절·목표 대신: 바스켓 손익 ≤ −리스크 예산이면 전량 청산, 아니면 21거래일 시간 청산. 가상·모의, 실계좌 주문 아님.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import hf_book as H  # noqa: E402

TOP_N = 100            # 코스피 시총 상위 — 대차 가능 대형주 근사(연구는 유동 전 종목, 여기만 다름)
DECILE = 0.10
BETA_FLOOR = 2 / 3     # 다리 배율 ≤ 1.5 (Q1b)
HOLD = 21
UNIT_STOP = 0.20       # 다리 단위(G) 대비 −20% = 바스켓 손절 — Q1b OOS 최악 1기간 −19% 근처
RISK_DEF = H.CONV["high"]                     # 검증 B 소스 → 높은 컨빅션 상한 0.40%
SIDE_COST = H.COST["stock"] / 2               # 한쪽 비용(재량 북 주식 왕복 0.45% 의 절반)
BORROW = 0.03                                 # 대차 연 3%
SRC = "reports/studies/2026-10-23_hf_bab_recheck.md Q1b"


def universe(top_n: int = TOP_N) -> list[tuple[str, str]]:
    rows = [r for r in csv.DictReader(open(ROOT / "universe" / "kr.csv", encoding="utf-8")) if r.get("market") == "KOSPI"]
    rows.sort(key=lambda r: -float(r.get("mcap") or 0))
    return [(r["symbol"], r["name"]) for r in rows[:top_n]]


def vol60(code: str) -> float | None:
    """60일 일간 수익률 표준편차(유동성 미달·데이터 부족이면 None) — 연구 Q1 정의."""
    bs_ = [x for x in H.bars("KR", code) if x.get("c")]
    if len(bs_) < 61:
        return None
    c = [float(x["c"]) for x in bs_]
    val20 = sum(float(x["c"]) * float(x.get("v") or 0) for x in bs_[-20:]) / 20
    if c[-1] < 1000 or val20 < 1e9:
        return None
    r = [c[i] / c[i - 1] - 1 for i in range(len(c) - 60, len(c))]
    m = sum(r) / 60
    return (sum((x - m) ** 2 for x in r) / 59) ** 0.5


def build(b: dict, risk: float = RISK_DEF, top_n: int = TOP_N) -> dict:
    """저변동 하위 10% 롱 ÷ β_L, 고변동 상위 10% 숏 ÷ β_S (β 바닥 2/3), 다리 단위 G = 리스크 ÷ 20%."""
    held = {p.get("code") for p in b["open"] if p.get("code")}
    cand = []
    for code, name in universe(top_n):
        if code in held:
            continue
        v = vol60(code)
        if v is not None:
            cand.append((v, code, name))
    cand.sort()
    n = int(len(cand) * DECILE)
    if n < 3:
        raise SystemExit(f"후보 {len(cand)}개 — 다리당 3종목 미만, 바스켓 안 만든다")
    lo, hi = cand[:n], cand[-n:]
    g = risk / UNIT_STOP
    legs = []
    betas = {}
    for side, grp in (("롱", lo), ("숏", hi)):
        bl = [H.beta_of("stock", c) for _, c, _ in grp]
        beta = max(BETA_FLOOR, sum(bl) / len(bl))
        betas[side] = round(beta, 3)
        for (v, c, nm), bi in zip(grp, bl):
            d, px, _ = H.stock_last(c)
            w = g / beta / len(grp)
            adv = H.adv_krw("stock", c)
            cut = adv and H.AUM * w > H.LIQ_FRAC * adv
            if cut:
                w = H.LIQ_FRAC * adv / H.AUM
            legs.append({"code": c, "name": nm, "side": side, "w": round(w, 6), "entry": px, "entry_d": d, "last": px,
                         "vol60": round(v * math.sqrt(252), 3), "beta": bi, **({"liq_cut": True} if cut else {})})
    gl = sum(x["w"] for x in legs if x["side"] == "롱")
    gs = sum(x["w"] for x in legs if x["side"] == "숏")
    return {"legs": legs, "g": round(g, 5), "risk": risk, "beta": betas, "gross": round(gl + gs, 5),
            "net_beta": round(sum(x["w"] * x["beta"] * (1 if x["side"] == "롱" else -1) for x in legs), 5)}


def open_basket(b: dict, risk: float = RISK_DEF, now: datetime | None = None) -> dict:
    bk = b.setdefault("baskets", {"open": [], "closed": []})
    if bk["open"]:
        raise SystemExit("열린 바스켓이 있음 — 21거래일 뒤 리밸런싱(중복 진입 금지)")
    lim = H.book_limits(b, H._today_kst())
    if lim.get("ban_new"):
        raise SystemExit(f"북 한도 — 신규 금지: {lim.get('why')}")
    if H.open_risk(b) + risk > H.RISK_ALL + 1e-12:
        raise SystemExit(f"열린 리스크 {H.open_risk(b) * 100:.2f}% + 바스켓 {risk * 100:.2f}% > 한도 {H.RISK_ALL * 100:.2f}%")
    x = build(b, risk)
    now = now or datetime.now(H.KST)
    x.update({"id": f"BK-{now:%Y%m%d}", "name": "바스켓 Q1b", "kind": "Q1b", "src": SRC, "created": now.strftime("%Y-%m-%d %H:%M"), "asof": H.deriv_last()["date"],
              "days": 0, "hold": HOLD, "stop": -risk, "cost_in": round(SIDE_COST * x["gross"], 6), "pnl": round(-SIDE_COST * x["gross"], 6)})
    bk["open"].append(x)
    return x


def basket_pnl(x: dict) -> float:
    """AUM 대비 손익 = Σ 부호 × 비중 × 수익률 − 진입 비용 − 숏 대차(보유 거래일)."""
    gross = sum((1 if l["side"] == "롱" else -1) * l["w"] * (l["last"] / l["entry"] - 1) for l in x["legs"])
    borrow = BORROW * x["days"] / 252 * sum(l["w"] for l in x["legs"] if l["side"] == "숏")
    return gross - x["cost_in"] - borrow


def _close(bk: dict, x: dict, d: str, why: str):
    x["pnl"] = round(basket_pnl(x) - SIDE_COST * sum(l["w"] * l["last"] / l["entry"] for l in x["legs"]), 6)
    x.update(exit_d=d, exit_why=why, r=round(x["pnl"] / x["risk"], 3))
    bk["open"] = [y for y in bk["open"] if y["id"] != x["id"]]
    bk["closed"].append(x)


def mark(b: dict) -> list[dict]:
    bk = b.get("baskets") or {}
    out = []
    md = H.deriv_last()["date"]
    for x in list(bk.get("open") or []):
        for l in x["legs"]:
            try:
                l["last"] = H.stock_last(l["code"])[1]
            except SystemExit:
                pass
        if md != x.get("mark_d", x["asof"]):
            x["days"] += 1
            x["mark_d"] = md
        x["pnl"] = round(basket_pnl(x), 6)
        why = ("바스켓 손절 — 손익 ≤ −리스크 예산" if x["pnl"] <= x["stop"] else
               "21거래일 시간 청산(리밸런싱)" if x["days"] >= x["hold"] else None)
        if why:
            _close(bk, x, md, why)
            out.append(x)
    return out


def close_all(b: dict, why: str) -> list[dict]:
    bk = b.get("baskets") or {}
    md = H.deriv_last()["date"]
    out = list(bk.get("open") or [])
    for x in out:
        _close(bk, x, md, "재량 청산 — " + why)
    return out


def lines(b: dict, detail: bool = False) -> list[str]:
    bk = b.get("baskets") or {}
    ls = []
    for x in bk.get("open") or []:
        lg = [l for l in x["legs"] if l["side"] == "롱"]
        sh = [l for l in x["legs"] if l["side"] == "숏"]
        def leg_ret(g):
            w = sum(l["w"] for l in g)
            return sum(l["w"] * (l["last"] / l["entry"] - 1) for l in g) / w if w else 0.0
        ls.append(f"- 바스켓 {x['id']} Q1b 저변동 롱 {len(lg)} {leg_ret(lg) * 100:+.1f}% / 고변동 숏 {len(sh)} {leg_ret(sh) * 100:+.1f}% · "
                  f"손익 {x['pnl'] * 100:+.3f}% ({x['pnl'] / x['risk']:+.2f}R) · 손절 {x['stop'] * 100:.2f}% · {x['days']}/{x['hold']}거래일 · "
                  f"총노출 {x['gross'] * 100:.2f}% · 순베타 {x['net_beta'] * 100:+.2f}% · 근거 {x['src']}")
        if detail:
            for l in x["legs"]:
                ls.append(f"    {l['side']} {l['name']}({l['code']}) {l['entry']:,.0f} → {l['last']:,.0f} · 비중 {l['w'] * 100:.3f}% · 변동성 {l['vol60']:.0%} · β {l['beta']}")
    cl = bk.get("closed") or []
    if cl:
        rs = [x["r"] for x in cl]
        ls.append(f"- 바스켓 청산 {len(cl)}건 · 평균 {sum(rs) / len(rs):+.2f}R · 적중 {sum(r > 0 for r in rs)}/{len(rs)} · 손익 {sum(x['pnl'] for x in cl) * 100:+.3f}%")
    return ls


def main(argv=None):
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    a = sp.add_parser("open")
    a.add_argument("--risk", type=float, default=RISK_DEF)
    a.add_argument("--dry", action="store_true")
    sp.add_parser("mark")
    sp.add_parser("show")
    c = sp.add_parser("close")
    c.add_argument("--why", required=True)
    x = ap.parse_args(argv)
    b = H.load()
    if x.cmd == "open":
        if x.dry:
            k = build(b, x.risk)
            print(json.dumps({kk: v for kk, v in k.items() if kk != "legs"}, ensure_ascii=False))
            for l in k["legs"]:
                print(f"  {l['side']} {l['name']}({l['code']}) {l['entry']:,.0f} 비중 {l['w'] * 100:.3f}% 변동성 {l['vol60']:.0%} β {l['beta']}")
            return
        open_basket(b, x.risk)
        H.save(b)
    elif x.cmd == "mark":
        for k in mark(b):
            print(f"청산 바스켓 {k['id']} {k['r']:+.2f}R — {k['exit_why']}")
        H.save(b)
    elif x.cmd == "close":
        close_all(b, x.why)
        H.save(b)
    print("\n".join(lines(b, detail=True)))


if __name__ == "__main__":
    main()
