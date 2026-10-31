#!/usr/bin/env python3
"""곡선 기간별 라벨 — 채권 스킬 시범(2026-10-31). kb:bonds#13 + 복기 10/31(rounds/2026-10-31/bonds_curve.md).

  python3 .claude/skills/bonds-desk/scripts/curve_label.py                 # reports/bonds.json
  python3 .claude/skills/bonds-desk/scripts/curve_label.py --json path.json

규칙: 라벨엔 기간(d1/w1/m1/y1)을 반드시 붙이고, '국면' 은 m1 한 줄만 판정한다.
  스프레드 변화 Δ = 장기 다리 − 단기 다리(bp). |Δ| < 10 → 두 다리 같은 부호·평균 |≥10| 이면 '불/베어 평행', 아니면 '판정 보류(10bp 미만)'.
  |Δ| ≥ 10 → 두 다리 부호 반대면 '트위스트 스티프/플랫', 아니면 베어(금리↑)/불(금리↓) × 스티프/플랫.
  다리 값이 없거나 두 다리 기준일이 다르면 '미확인(사유)'. 판정만 — 등급 검증전, 매매 신호 아님.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
PERIODS = ("d1", "w1", "m1", "y1")
PAIRS = {"us": (("2Y", "10Y"), ("2Y", "30Y"), ("10Y", "30Y")), "kr": (("3Y", "10Y"), ("3Y", "30Y"))}
MAIN = {"us": ("2Y", "10Y"), "kr": ("3Y", "10Y")}
TH = 10.0


def classify(short: float | None, long: float | None, th: float = TH) -> str:
    if short is None or long is None:
        return "미확인(다리 값 없음)"
    d = long - short
    if abs(d) < th:
        if short * long > 0 and abs(short + long) / 2 >= th:
            return "불 평행" if short < 0 else "베어 평행"
        return f"판정 보류({th:.0f}bp 미만)"
    side = "스티프" if d > 0 else "플랫"
    if short * long < 0:
        return f"트위스트 {side}"
    up = (long if d > 0 else short) > 0          # 더 크게 움직인 다리의 방향
    return ("베어 " if up else "불 ") + ("스티프닝" if d > 0 else "플래트닝")


def rows(o: dict, mkt: str) -> list[dict]:
    chg = (o.get(mkt) or {}).get("chg") or {}
    out = []
    for a, b in PAIRS[mkt]:
        la, lb = chg.get(a) or {}, chg.get(b) or {}
        stale = la.get("date") != lb.get("date")
        for p in PERIODS:
            s, l = la.get(p), lb.get(p)
            lab = "미확인(다리 기준일 다름)" if stale and la and lb else classify(s, l)
            out.append({"mkt": mkt, "pair": f"{a}-{b}", "period": p, "short": s, "long": l,
                        "spread_chg": None if s is None or l is None else round(l - s, 1),
                        "date": la.get("date") or lb.get("date"), "label": lab})
    return out


def regime(rs: list[dict], mkt: str) -> dict | None:
    a, b = MAIN[mkt]
    return next((r for r in rs if r["pair"] == f"{a}-{b}" and r["period"] == "m1"), None)


def fmt(x):
    return "—" if x is None else f"{x:+.0f}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=str(ROOT / "reports" / "bonds.json"))
    a = ap.parse_args(argv)
    try:
        o = json.loads(Path(a.json).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"데이터 없음({a.json}: {e})")
        return 1
    for mkt, name in (("us", "미 국채"), ("kr", "국고")):
        rs = rows(o, mkt)
        if not rs or all(r["short"] is None for r in rs):
            print(f"## {name} — 데이터 없음(chg 블록 비어 있음)")
            continue
        print(f"## {name} (기준 {rs[0]['date']}, 출처 {a.json}, bp)")
        for r in rs:
            print(f"- [{r['period']}] {r['pair']}: {fmt(r['short'])} / {fmt(r['long'])} · Δ {fmt(r['spread_chg'])} → {r['label']}")
        g = regime(rs, mkt)
        if g:
            print(f"국면(m1, {g['pair']}): {g['label']} (검증전) — d1·w1 라벨은 국면 아님")
    return 0


if __name__ == "__main__":
    sys.exit(main())
