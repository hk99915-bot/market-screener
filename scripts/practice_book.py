#!/usr/bin/env python3
"""겸이 연습 장부(모의) — 한 줄 매매("○○ 사고 싶다, X 밑이면 팔고 Y 오면 판다")를 기록하고 채점한다 (겸이 10/22, HF 개미 교실).

  python3 scripts/practice_book.py add --code 000660 --stop <손절가> --target <목표가> [--line "<원문>"]   # 원문은 저장 안 함(아래)
  python3 scripts/practice_book.py mark     # 체결(다음 시가)·손절·목표·20거래일 시간 정리
  python3 scripts/practice_book.py show     # 성적표(건수·적중·평균 R·손익비)

상태 reports/practice_book.json — 금액 없음(가격·R·%만). 모의 전용, 실계좌 주문 아님.
겸이 원문 문장(--line)은 공개 저장소에 쓰지 않는다(11/4 결재 req-dev-c396adfc) — 공개본엔 src_ref(= 기록 id, pb-private 의 원문 키)만 남고,
원문은 PB 가 pb-private 에 직접 적는다. save()/load() 가 원문 필드(FORBIDDEN_KEYS)를 항상 걷어낸다 — tests/test_practice_book.py.
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
RULES = ["손절가를 매수 전에 안 적으면 안 산다 — 겸이 1호 규칙(10/23, −20% 손실 38번의 원인)",
         "추세추종 v2(11/4): +2R 종가 도달 → 손절을 진입가(본전)로, +3R 종가 → 1/3 익절, 나머지는 20일 저점 트레일"]
BE_R, PART_R, PART_FRAC = 2.0, 3.0, 1 / 3
FORBIDDEN_KEYS = ("line",)               # 공개 장부에 쓰면 안 되는 필드(겸이 원문)
COST = {"KR": 0.0045, "US": 0.002}      # 왕복 비용(세금·수수료·슬리피지) — hf_book 국장 주식·미장 주식과 같은 가정


def load() -> dict:
    return json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {"v": 1, "note": "겸이 연습 장부 — 모의, 금액 없음", "open": [], "closed": []}


def scrub(b: dict) -> int:
    """원문 필드를 걷어내고 src_ref(기록 id)를 채운다. 걷어낸 필드 수를 돌려준다(값은 다루지 않음)."""
    n = 0
    for k in ("open", "closed", "voided"):
        for p in b.get(k, []):
            n += sum(1 for f in FORBIDDEN_KEYS if p.pop(f, None) is not None)
            p.setdefault("src_ref", p.get("id"))
    seen: dict = {}
    for s in b.get("skips", []):
        n += sum(1 for f in FORBIDDEN_KEYS if s.pop(f, None) is not None)
        base = f"skip:{s.get('d')}:{s.get('market')}:{s.get('code')}"
        seen[base] = seen.get(base, 0) + 1
        s.setdefault("src_ref", f"{base}:{seen[base]}")
    return n


def save(b: dict):
    scrub(b)
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
         "name": H.detail_name(market, code) or code, "stop": stop, "target": target,
         "created": now.strftime("%Y-%m-%d %H:%M"), "status": "대기", "days": 0,
         **({"trail": "low20_weekly", "stop0": stop, "v2": True} if trail else {})}
    lv = H.live_kr_stock(code) if (market == "KR" and open_now) else None
    if lv:
        p.update(entry=lv[1], entry_d=now.strftime("%Y-%m-%d"), status="보유", entry_how="장중가(heatmap_KR)")
        if not stop < lv[1] < (target if target is not None else float("inf")):
            raise SystemExit(f"지금가 {lv[1]:,.0f} 가 손절~목표 사이가 아님")
    p["src_ref"] = p["id"]                                    # 원문(line)은 저장하지 않는다 — 인자는 호환용, PB 가 pb-private 에 적음
    b["open"].append(p)
    return p


def skip(b: dict, code: str, line: str, market: str = "KR", now: datetime | None = None) -> dict:
    """'안 산다'도 결정 — 그때 가격을 적어두고 나중에 '안 산 게 맞았나'(그 뒤 수익률)를 본다."""
    now = now or datetime.now(KST)
    last = H.stock_last(code) if market == "KR" else H.us_stock_last(code)
    if not last:
        raise SystemExit(f"{code} 가격 없음")
    s = {"code": code, "market": market, "name": last[2] or code, "d": now.strftime("%Y-%m-%d"), "px": float(last[1])}
    b.setdefault("skips", []).append(s)
    scrub(b)
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
        stop, wk, part = p.get("stop0", p["stop"]), None, None
        r1 = p["entry"] - p.get("stop0", p["stop"])
        fl = p.get("floor")                                       # 수동 손절 바닥 {"px","d"} — 그 날짜 이후 봉부터
        for x in after:
            if p.get("trail"):                                    # 주 첫 봉에서 손절 = max(손절, 직전 20봉 저점)
                w = date.fromisoformat(x["t"][:10]).isocalendar()[:2]
                if wk is not None and w != wk:
                    i = bars.index(x)
                    lows = [float(y["l"]) for y in bars[max(0, i - 20):i] if y.get("l")]
                    if lows:
                        stop = max(stop, min(lows))
                wk = w
            if fl and x["t"][:10] >= fl["d"]:
                stop = max(stop, float(fl["px"]))
            o, c = float(x["o"]), float(x["c"])
            if x["t"][:10] > p["entry_d"] and o <= stop:
                why, px, d = "손절(갭 — 시가 체결)", o, x["t"][:10]
            elif c <= stop:
                why, px, d = "손절" if stop <= p.get("stop0", stop) else "추세 이탈(올린 손절)", c, x["t"][:10]
            elif p.get("target") is not None and c >= p["target"]:
                why, px, d = "목표", c, x["t"][:10]
            if why:
                break
            if p.get("v2"):                                       # 종가 기준 — 다음 봉부터 적용
                if c >= p["entry"] + BE_R * r1:
                    stop = max(stop, p["entry"])
                if part is None and c >= p["entry"] + PART_R * r1:
                    part = {"px": c, "d": x["t"][:10], "frac": PART_FRAC}
        if fl and not why:
            stop = max(stop, float(fl["px"]))                     # 아직 그 날짜 봉이 없어도 다음 봉부터 적용될 손절로 표시
        p["stop"] = stop
        if part:
            p["partial"] = part
        p["days"] = len(after)
        if not why and not p.get("trail") and p["days"] >= HOLD:
            why, px, d = "20거래일 시간 정리", float(after[-1]["c"]), after[-1]["t"][:10]
        if why:
            f = part["frac"] if part else 0.0
            r = f * _r(p, part["px"]) + (1 - f) * _r(p, px) if part else _r(p, px)
            ret = (f * part["px"] + (1 - f) * px) / p["entry"] - 1 - COST[p["market"]] if part else px / p["entry"] - 1 - COST[p["market"]]
            p.update(exit=px, exit_d=d, exit_why=why + (f" · 1/3 익절 {part['px']:,.0f}({part['d']})" if part else ""), r=round(r, 3), ret=round(ret, 4), status="청산")
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
        tg = ("목표 없음(추세추종 — 손절 매주 20일 저점으로 올림" + (" · +2R 본전·+3R 1/3 익절" if p.get("v2") else "") + ")") if p.get("trail") else f"목표 {p['target']:,.0f}"
        if p.get("partial"):
            tg += f" · 1/3 익절됨 {p['partial']['px']:,.0f}({p['partial']['d']})"
        ls.append(f"- {p['name']} {ent} · 손절 {p['stop']:,.{2 if p['stop'] < 1000 else 0}f} · {tg}{cur} — 원문 {p.get('src_ref') or p.get('id')}")
    for p in cl[-5:]:
        ls.append(f"- 청산 {p['name']} {p['r']:+.2f}R ({p['ret'] * 100:+.1f}%, {p['exit_why']}, {p['exit_d']})")
    for s in b.get("skips", [])[-5:]:
        last = H.stock_last(s["code"]) if s["market"] == "KR" else H.us_stock_last(s["code"])
        since = f" → 지금 {last[1] / s['px'] - 1:+.1%}" if last else ""
        ls.append(f"- 안 산다 {s['name']} {s['px']:,.0f}({s['d']}){since} — 원문 {s.get('src_ref', '-')}")
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
    a.add_argument("--line", default="", help="원문 — 저장하지 않음(공개 저장소). PB 가 pb-private 에 적는다")
    k = sp.add_parser("skip", help="'안 산다' 결정 기록 — 그 뒤 수익률로 채점")
    k.add_argument("--code", required=True)
    k.add_argument("--market", default="KR")
    k.add_argument("--line", default="", help="원문 — 저장하지 않음(공개 저장소)")
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
