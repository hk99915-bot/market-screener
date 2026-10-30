#!/usr/bin/env python3
"""겸이 연습 장부(모의) — 한 줄 매매("○○ 사고 싶다, X 밑이면 팔고 Y 오면 판다")를 기록하고 채점한다 (겸이 10/22, HF 개미 교실).

  python3 scripts/practice_book.py add --code 000660 --stop 1120000 --target 1360000 --line "하이닉스 사고 싶다 112만원 밑이면 팔고 136만원 오면 판다"
  python3 scripts/practice_book.py mark     # 체결(다음 시가)·손절·목표·20거래일 시간 정리
  python3 scripts/practice_book.py show     # 성적표(건수·적중·평균 R·손익비)

상태 reports/practice_book.json — 금액 없음(가격·R·%만). 모의 전용, 실계좌 주문 아님.
R·수익률은 왕복 비용 차감(국장 0.45%·미장 0.2%) 뒤 숫자.
체결: 장 마감 뒤 등록 → 다음 거래일 시가(차트 o), 장중 등록 → 그 시각 장중가(heatmap_KR). 손절·목표 = 종가 기준, 갭으로 넘으면 시가 체결.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import hf_book as H  # noqa: E402
sys.path.insert(0, str(ROOT))
from screener.tradecal import us_open_hhmm  # noqa: E402

STATE = ROOT / "reports" / "practice_book.json"
KST = timezone(timedelta(hours=9))
HOLD = 20
RULES = ["손절가를 매수 전에 안 적으면 안 산다 — 겸이 1호 규칙(10/23, −20% 손실 38번의 원인)"]
COST = {"KR": 0.0045, "US": 0.002}      # 왕복 비용(세금·수수료·슬리피지) — hf_book 국장 주식·미장 주식과 같은 가정


def load() -> dict:
    return json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {"v": 1, "note": "겸이 연습 장부 — 모의, 금액 없음", "open": [], "closed": []}


def save(b: dict):
    b["asof"] = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    STATE.write_text(json.dumps(b, ensure_ascii=False, indent=1), encoding="utf-8")


def add(b: dict, code: str, stop: float, target: float | None, line: str, market: str = "KR", now: datetime | None = None,
        trail: bool = False) -> dict:
    """trail=True — 추세추종: 목표 없음·20거래일 시간 정리 없음, 손절을 매주 첫 봉에 '직전 20일 저점'으로 올림(내리지 않음)."""
    now = now or datetime.now(KST)
    if target is None and not trail:
        raise SystemExit("목표가 없으면 --trail(추세추종) 이어야 해")
    if target is not None and not stop < target:
        raise SystemExit("손절은 목표보다 낮아야 해(롱)")
    open_now = now.weekday() < 5 and (9 * 60) <= now.hour * 60 + now.minute < (15 * 60 + 20)
    p = {"id": f"{now:%Y%m%d}-{len(b['open']) + len(b['closed']) + 1}", "code": code, "market": market,
         "name": H.detail_name(market, code) or code, "line": line, "stop": stop, "target": target,
         "created": now.strftime("%Y-%m-%d %H:%M"), "status": "대기", "days": 0, **({"trail": "low20_weekly", "stop0": stop} if trail else {})}
    lv = H.live_kr_stock(code) if (market == "KR" and open_now) else None
    if lv:
        p.update(entry=lv[1], entry_d=now.strftime("%Y-%m-%d"), status="보유", entry_how="장중가(heatmap_KR)")
        if not stop < lv[1] < (target if target is not None else float("inf")):
            raise SystemExit(f"지금가 {lv[1]:,.0f} 가 손절~목표 사이가 아님")
    b["open"].append(p)
    return p


def skip(b: dict, code: str, line: str, market: str = "KR", now: datetime | None = None) -> dict:
    """'안 산다'도 결정 — 그때 가격을 적어두고 나중에 '안 산 게 맞았나'(그 뒤 수익률)를 본다."""
    now = now or datetime.now(KST)
    last = H.stock_last(code) if market == "KR" else H.us_stock_last(code)
    if not last:
        raise SystemExit(f"{code} 가격 없음")
    s = {"code": code, "market": market, "name": last[2] or code, "line": line, "d": now.strftime("%Y-%m-%d"), "px": float(last[1])}
    b.setdefault("skips", []).append(s)
    return s


def _r(p, px):
    """비용 차감 R — 왕복 비용(진입가 × COST)을 1R(진입 − 첫 손절)로 나눠 뺀다. 추세추종은 손절이 올라가도 1R 은 첫 손절 기준."""
    return (px - p["entry"] - COST[p["market"]] * p["entry"]) / (p["entry"] - p.get("stop0", p["stop"]))


def mark(b: dict) -> list[dict]:
    out, keep = [], []
    for p in b["open"]:
        bars = H.bars(p["market"], p["code"])
        if p["status"] == "대기":
            cd, ct = p["created"][:10], p["created"][11:16]
            same_ok = p["market"] == "US" and ct < us_open_hhmm(cd)   # 미장: 같은 KST 날짜 봉 = 그날 개장 세션(여름 22:30·겨울 23:30 KST, ET 로 계산)
            nb = [x for x in bars if (x["t"][:10] > cd or (same_ok and x["t"][:10] == cd)) and x.get("o")]
            if not nb:
                keep.append(p)
                continue
            p.update(entry=float(nb[0]["o"]), entry_d=nb[0]["t"][:10], status="보유", entry_how="다음 시가")
        after = [x for x in bars if x["t"][:10] >= p["entry_d"]]
        why, px, d = None, None, None
        stop, wk = p.get("stop0", p["stop"]), None
        for x in after:
            if p.get("trail"):                                    # 주 첫 봉에서 손절 = max(손절, 직전 20봉 저점)
                w = date.fromisoformat(x["t"][:10]).isocalendar()[:2]
                if wk is not None and w != wk:
                    i = bars.index(x)
                    lows = [float(y["l"]) for y in bars[max(0, i - 20):i] if y.get("l")]
                    if lows:
                        stop = max(stop, min(lows))
                wk = w
            o, c = float(x["o"]), float(x["c"])
            if x["t"][:10] > p["entry_d"] and o <= stop:
                why, px, d = "손절(갭 — 시가 체결)", o, x["t"][:10]
            elif c <= stop:
                why, px, d = "손절" if stop <= p.get("stop0", stop) else "추세 이탈(올린 손절)", c, x["t"][:10]
            elif p.get("target") is not None and c >= p["target"]:
                why, px, d = "목표", c, x["t"][:10]
            if why:
                break
        p["stop"] = stop
        p["days"] = len(after)
        if not why and not p.get("trail") and p["days"] >= HOLD:
            why, px, d = "20거래일 시간 정리", float(after[-1]["c"]), after[-1]["t"][:10]
        if why:
            p.update(exit=px, exit_d=d, exit_why=why, r=round(_r(p, px), 3), ret=round(px / p["entry"] - 1 - COST[p["market"]], 4), status="청산")
            b["closed"].append(p)
            out.append(p)
        else:
            if after:
                p["last"] = float(after[-1]["c"])
            keep.append(p)
    b["open"] = keep
    return out


def show(b: dict) -> list[str]:
    cl = b["closed"]
    ls = [f"규칙 {i}. {r}" for i, r in enumerate(RULES, 1)]
    ls.append(f"연습 장부: 보유·대기 {len(b['open'])} · 청산 {len(cl)} / 목표 20건 (R = 비용 차감: 국장 {COST['KR']:.2%}·미장 {COST['US']:.1%} 왕복)")
    if cl:
        rs = [x["r"] for x in cl]
        w = [r for r in rs if r > 0]
        lo = [r for r in rs if r <= 0]
        slug = (sum(w) / len(w)) / abs(sum(lo) / len(lo)) if w and lo and sum(lo) else None
        ls.append(f"적중 {len(w)}/{len(rs)} · 평균 {sum(rs) / len(rs):+.2f}R" + (f" · 손익비 {slug:.2f}" if slug else ""))
    for p in b["open"]:
        cur = f" · 현재 {p['last']:,.0f} ({_r(p, p['last']):+.2f}R)" if p.get("last") and p.get("entry") else ""
        ent = f"진입 {p['entry']:,.0f}({p['entry_d']})" if p.get("entry") else "다음 시가 체결 대기"
        tg = "목표 없음(추세추종 — 손절 매주 20일 저점으로 올림)" if p.get("trail") else f"목표 {p['target']:,.0f}"
        ls.append(f"- {p['name']} {ent} · 손절 {p['stop']:,.{2 if p['stop'] < 1000 else 0}f} · {tg}{cur} — \"{p['line']}\"")
    for p in cl[-5:]:
        ls.append(f"- 청산 {p['name']} {p['r']:+.2f}R ({p['ret'] * 100:+.1f}%, {p['exit_why']}, {p['exit_d']})")
    for s in b.get("skips", [])[-5:]:
        last = H.stock_last(s["code"]) if s["market"] == "KR" else H.us_stock_last(s["code"])
        since = f" → 지금 {last[1] / s['px'] - 1:+.1%}" if last else ""
        ls.append(f"- 안 산다 {s['name']} {s['px']:,.0f}({s['d']}){since} — \"{s['line']}\"")
    return ls


def main(argv=None):
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    a = sp.add_parser("add")
    a.add_argument("--code", required=True)
    a.add_argument("--market", default="KR")
    a.add_argument("--stop", type=float, required=True)
    a.add_argument("--target", type=float)
    a.add_argument("--trail", action="store_true", help="추세추종: 목표 없음, 손절을 매주 직전 20일 저점으로 올림")
    a.add_argument("--line", required=True)
    k = sp.add_parser("skip", help="'안 산다' 결정 기록 — 그 뒤 수익률로 채점")
    k.add_argument("--code", required=True)
    k.add_argument("--market", default="KR")
    k.add_argument("--line", required=True)
    sp.add_parser("mark")
    sp.add_parser("show")
    x = ap.parse_args(argv)
    b = load()
    if x.cmd == "add":
        add(b, x.code, x.stop, x.target, x.line, x.market, trail=x.trail)
        save(b)
    elif x.cmd == "skip":
        skip(b, x.code, x.line, x.market)
        save(b)
    elif x.cmd == "mark":
        for p in mark(b):
            print(f"청산 {p['name']} {p['r']:+.2f}R — {p['exit_why']}")
        save(b)
    print("\n".join(show(b)))


if __name__ == "__main__":
    main()
