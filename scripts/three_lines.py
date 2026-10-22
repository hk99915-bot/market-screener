#!/usr/bin/env python3
"""진입 전 세 줄 도우미 — 종목 코드만 넣으면 숫자 칸(손절·목표·손익비·손익분기 승률·경고)을 채우고,
'왜 지금'과 '버릴 조건'은 데이터에서 뽑은 후보 중에서 고르게 한다 (겸이 10/22 "세 줄 쓰는 걸 잘 못하겠어요").

  python3 scripts/three_lines.py 000660          # 국장
  python3 scripts/three_lines.py BUG --market US  # 미장

데이터: reports/detail/{KR,US}/<코드>.json 차트·flow_note, reports/calendar.json, reports/live.json(코스피 등락).
손절 = max(20일 저점, 종가 − 2×ATR14) — 위원회 trade plan 과 같은 규칙. 목표 = 1.5R(그리고 20일 고점·50일선 참고).
모의 연습용. 매수 지시 아님.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(p):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def atr14(ch):
    tr = []
    for i in range(1, len(ch)):
        h, l, pc = float(ch[i]["h"]), float(ch[i]["l"]), float(ch[i - 1]["c"])
        tr.append(max(h, pc) - min(l, pc))
    return sum(tr[-14:]) / min(14, len(tr)) if tr else None


def build(code: str, market: str = "KR", root: Path = ROOT, today: date | None = None) -> dict:
    d = _load(root / "reports" / "detail" / market / f"{code}.json")
    if not d or not d.get("chart"):
        return {"error": f"데이터 없음: reports/detail/{market}/{code}.json — 세 줄 못 씀 = 안 산다"}
    ch = [b for b in d["chart"] if b.get("c") and b.get("h") and b.get("l")]
    c = float(ch[-1]["c"])
    atr = atr14(ch)
    low20 = min(float(b["l"]) for b in ch[-20:])
    hi20 = max(float(b["h"]) for b in ch[-20:])
    stop = max(low20, c - 2 * atr) if atr else low20
    if c - stop < atr:                                  # 최소 1×ATR
        stop = c - atr
    r = c - stop
    t1 = c + 1.5 * r
    s50 = ch[-1].get("s50")
    s200 = ch[-1].get("s200")
    v = [float(b.get("v") or 0) for b in ch]
    v20 = sum(v[-21:-1]) / 20 if len(v) > 21 else 0
    vr = v[-1] / v20 if v20 else 0
    hi250 = max(float(b["c"]) for b in ch[-250:])
    ret1 = c / float(ch[-2]["c"]) - 1
    ret20 = c / float(ch[-21]["c"]) - 1 if len(ch) > 21 else 0
    warn = []
    if vr >= 3 and c >= max(float(b["c"]) for b in ch[-20:]):
        warn.append("⛔ 거래량 3배 + 20일 신고가 = 추격(10일 −1.3~−1.7%, 검증 F) — 오늘 롱 금지")
    elif vr >= 2 and ret1 > 0:
        warn.append("⚠️ 거래량 급증 상승일 — 추격 주의, 눌림 확인 뒤")
    if c / hi250 >= 0.95 and market == "US":
        warn.append("⚠️ 미장 52주 고점 근처 — 추격 진입 초과 −0.073R(검증 F)")
    if (r / c) > 0.15:
        warn.append("⚠️ 손절폭 15% 초과 — 너무 흔들리는 종목, 크기를 아주 작게 아니면 패스")
    today = today or date.today()
    cal = (_load(root / "reports" / "calendar.json") or {}).get("events") or []
    earn = next((e["date"] for e in cal if e.get("ticker") == code and e.get("type") == "실적" and e["date"] >= today.isoformat()), None)
    if earn and (date.fromisoformat(earn) - today).days <= 5:
        warn.append(f"⚠️ 실적 {earn} — 5일 안, 갭이 손절을 뚫을 수 있음")
    why = []
    lv = _load(root / "reports" / "live.json") or {}
    kospi = next((x for x in lv.get("items", []) if x.get("key") == "KOSPI"), {})
    if market == "KR" and kospi.get("chg") is not None and abs(kospi["chg"]) >= 0.03:
        why.append(f"코스피 오늘 {kospi['chg'] * 100:+.1f}% — 큰 날 다음 날 반대(네 모의 패턴: 지수 1배 ETF 에만 해당, 개별 종목 근거 아님)")
    fn = d.get("flow_note") or ""
    if "동반 매도" in fn:
        warn.append(f"⚠️ 수급 이탈 중 — {fn}")
    if "동반 매수" in fn:
        why.append(f"수급: {fn}")
    if s200 and c >= float(s200) and min(float(b["c"]) for b in ch[-5:]) >= float(s200) * 0.98:
        why.append(f"200일선 {float(s200):,.0f} 지지 중")
    if c / hi250 >= 0.95 and market == "KR":
        why.append("국장 52주 고점 근처(B1 — 검증 통과 신호)")
    if earn:
        why.append(f"촉매: 실적 {earn}")
    kill = [f"종가가 손절 {stop:,.0f} 아래", "외국인·기관 5일 동반 순매도로 전환", f"20거래일 안에 목표 {t1:,.0f} 못 가면 정리"]
    if earn:
        kill.append(f"실적({earn})이 컨센서스 하회")
    rr = 1.5
    return {"code": code, "name": d.get("name") or code, "market": market, "close": c, "asof": ch[-1]["t"][:10],
            "stop": round(stop, 2), "stop_pct": round(r / c, 4), "t1": round(t1, 2), "rr": rr, "p_be": round(1 / (1 + rr), 3),
            "ref": {"20일 고점": hi20, "50일선": s50, "200일선": s200, "52주 고점 대비": round(c / hi250, 3), "20일 수익": round(ret20, 4)},
            "flow": fn, "why_options": why, "kill_options": kill, "warn": warn}


def render(o: dict) -> str:
    if o.get("error"):
        return o["error"]
    L = [f"■ {o['name']} ({o['code']}, {o['market']}) — 기준 {o['asof']} 종가 {o['close']:,.2f}"]
    L += o["warn"] or ["경고 없음"]
    L.append("")
    L.append("1) 티커 + 왜 지금 — 아래 중 하나 이상 고르고, 못 고르면 안 산다:")
    L += [f"   [{i + 1}] {w}" for i, w in enumerate(o["why_options"])] or ["   (데이터에서 뽑힌 이유 없음 → 오늘은 안 사는 날)"]
    L.append(f"2) 손절 {o['stop']:,.2f} (−{o['stop_pct'] * 100:.1f}%) · 목표 {o['t1']:,.2f} (1.5R) · 손익비 {o['rr']} → {o['p_be'] * 100:.0f}% 넘게 맞혀야 본전")
    L.append("   참고: " + " · ".join(f"{k} {v:,.2f}" if isinstance(v, (int, float)) and v is not None and k not in ('52주 고점 대비', '20일 수익') else f"{k} {v}" for k, v in o["ref"].items()))
    L.append("3) 버릴 조건 — 하나 이상 골라 적어두고, 나오면 묻지 말고 판다:")
    L += [f"   [{chr(97 + i)}] {k}" for i, k in enumerate(o["kill_options"])]
    L.append("")
    L.append("→ 세 줄 예시: '" + o["code"] + " — " + (o["why_options"][0] if o["why_options"] else "이유 없음") + f" / 손절 {o['stop']:,.0f}·목표 {o['t1']:,.0f} / " + o["kill_options"][0] + "'")
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("code")
    ap.add_argument("--market", default=None)
    a = ap.parse_args(argv)
    mk = a.market or ("KR" if a.code.isdigit() else "US")
    print(render(build(a.code, mk)))


if __name__ == "__main__":
    sys.exit(main())
