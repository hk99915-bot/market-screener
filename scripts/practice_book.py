#!/usr/bin/env python3
"""겸이 연습 장부(모의) — 한 줄 매매("○○ 사고 싶다, X 밑이면 팔고 Y 오면 판다")를 기록하고 채점한다 (겸이 10/22, HF 개미 교실).

  python3 scripts/practice_book.py add --code 000660 --stop 1120000 --target 1360000 --line "하이닉스 사고 싶다 112만원 밑이면 팔고 136만원 오면 판다"
  python3 scripts/practice_book.py mark     # 체결(다음 시가)·손절·목표·20거래일 시간 정리
  python3 scripts/practice_book.py show     # 성적표(건수·적중·평균 R·손익비)

상태 reports/practice_book.json — 금액 없음(가격·R·%만). 모의 전용, 실계좌 주문 아님.
체결: 장 마감 뒤 등록 → 다음 거래일 시가(차트 o), 장중 등록 → 그 시각 장중가(heatmap_KR). 손절·목표 = 종가 기준, 갭으로 넘으면 시가 체결.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import hf_book as H  # noqa: E402

STATE = ROOT / "reports" / "practice_book.json"
KST = timezone(timedelta(hours=9))
HOLD = 20


def load() -> dict:
    return json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {"v": 1, "note": "겸이 연습 장부 — 모의, 금액 없음", "open": [], "closed": []}


def save(b: dict):
    b["asof"] = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    STATE.write_text(json.dumps(b, ensure_ascii=False, indent=1), encoding="utf-8")


def add(b: dict, code: str, stop: float, target: float, line: str, market: str = "KR", now: datetime | None = None) -> dict:
    now = now or datetime.now(KST)
    if not stop < target:
        raise SystemExit("손절은 목표보다 낮아야 해(롱)")
    open_now = now.weekday() < 5 and (9 * 60) <= now.hour * 60 + now.minute < (15 * 60 + 20)
    p = {"id": f"{now:%Y%m%d}-{len(b['open']) + len(b['closed']) + 1}", "code": code, "market": market,
         "name": H.detail_name(market, code) or code, "line": line, "stop": stop, "target": target,
         "created": now.strftime("%Y-%m-%d %H:%M"), "status": "대기", "days": 0}
    lv = H.live_kr_stock(code) if (market == "KR" and open_now) else None
    if lv:
        p.update(entry=lv[1], entry_d=now.strftime("%Y-%m-%d"), status="보유", entry_how="장중가(heatmap_KR)")
        if not stop < lv[1] < target:
            raise SystemExit(f"지금가 {lv[1]:,.0f} 가 손절~목표 사이가 아님")
    b["open"].append(p)
    return p


def _r(p, px):
    return (px - p["entry"]) / (p["entry"] - p["stop"])


def mark(b: dict) -> list[dict]:
    out, keep = [], []
    for p in b["open"]:
        bars = H.bars(p["market"], p["code"])
        if p["status"] == "대기":
            cd, ct = p["created"][:10], p["created"][11:16]
            same_ok = p["market"] == "US" and ct < "22:30"          # 미장: 같은 KST 날짜 봉 = 그날 22:30 KST 개장 세션
            nb = [x for x in bars if (x["t"][:10] > cd or (same_ok and x["t"][:10] == cd)) and x.get("o")]
            if not nb:
                keep.append(p)
                continue
            p.update(entry=float(nb[0]["o"]), entry_d=nb[0]["t"][:10], status="보유", entry_how="다음 시가")
        after = [x for x in bars if x["t"][:10] >= p["entry_d"]]
        why, px, d = None, None, None
        for x in after:
            o, c = float(x["o"]), float(x["c"])
            if x["t"][:10] > p["entry_d"] and o <= p["stop"]:
                why, px, d = "손절(갭 — 시가 체결)", o, x["t"][:10]
            elif c <= p["stop"]:
                why, px, d = "손절", c, x["t"][:10]
            elif c >= p["target"]:
                why, px, d = "목표", c, x["t"][:10]
            if why:
                break
        p["days"] = len(after)
        if not why and p["days"] >= HOLD:
            why, px, d = "20거래일 시간 정리", float(after[-1]["c"]), after[-1]["t"][:10]
        if why:
            p.update(exit=px, exit_d=d, exit_why=why, r=round(_r(p, px), 3), ret=round(px / p["entry"] - 1, 4), status="청산")
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
    ls = [f"연습 장부: 보유·대기 {len(b['open'])} · 청산 {len(cl)} / 목표 20건"]
    if cl:
        rs = [x["r"] for x in cl]
        w = [r for r in rs if r > 0]
        lo = [r for r in rs if r <= 0]
        slug = (sum(w) / len(w)) / abs(sum(lo) / len(lo)) if w and lo and sum(lo) else None
        ls.append(f"적중 {len(w)}/{len(rs)} · 평균 {sum(rs) / len(rs):+.2f}R" + (f" · 손익비 {slug:.2f}" if slug else ""))
    for p in b["open"]:
        cur = f" · 현재 {p['last']:,.0f} ({_r(p, p['last']):+.2f}R)" if p.get("last") and p.get("entry") else ""
        ent = f"진입 {p['entry']:,.0f}({p['entry_d']})" if p.get("entry") else "다음 시가 체결 대기"
        ls.append(f"- {p['name']} {ent} · 손절 {p['stop']:,.0f} · 목표 {p['target']:,.0f}{cur} — \"{p['line']}\"")
    for p in cl[-5:]:
        ls.append(f"- 청산 {p['name']} {p['r']:+.2f}R ({p['ret'] * 100:+.1f}%, {p['exit_why']}, {p['exit_d']})")
    return ls


def main(argv=None):
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    a = sp.add_parser("add")
    a.add_argument("--code", required=True)
    a.add_argument("--market", default="KR")
    a.add_argument("--stop", type=float, required=True)
    a.add_argument("--target", type=float, required=True)
    a.add_argument("--line", required=True)
    sp.add_parser("mark")
    sp.add_parser("show")
    x = ap.parse_args(argv)
    b = load()
    if x.cmd == "add":
        add(b, x.code, x.stop, x.target, x.line, x.market)
        save(b)
    elif x.cmd == "mark":
        for p in mark(b):
            print(f"청산 {p['name']} {p['r']:+.2f}R — {p['exit_why']}")
        save(b)
    print("\n".join(show(b)))


if __name__ == "__main__":
    main()
