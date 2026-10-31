#!/usr/bin/env python3
"""현금흐름 리밸런싱 배정 + 밴드 판정 — 자산배분 스킬 시범(2026-10-31). 식은 kb:allocation#7·#8 그대로, 비율만(금액 입력 없음).

  python3 .claude/skills/alloc-desk/scripts/cashflow_rebal.py --cur "S&P500=42,NDX=17,K200=12,KTB=19,Gold=10" --c 5
  python3 .claude/skills/alloc-desk/scripts/cashflow_rebal.py --cur ... --c 5 --first KTB,Gold     # B안형: 지정 칸 부족분만 먼저, 나머지 '대기'
  python3 .claude/skills/alloc-desk/scripts/cashflow_rebal.py --target "주식=60,채권=40" --cur "주식=70,채권=30" --c 10   # 드릴 allocation-d1 검산

입력: --cur 현재 코어 비중(합으로 정규화 = V 를 100 으로 본 상대값), --c 신규 납입(같은 단위, V=100 대비), --target 생략 시 screener/defs.py ISA_TARGET(C안), --band 생략 시 ISA_BAND.
식: 부족분_i = max(0, w*_i × (V + C) − V_i) → C 를 부족분 비율로 배정(Σ부족분 ≥ C 항상 성립). 매도 0.
판정: |w_i − w*_i| > 밴드 → 이탈(배정 전·후 둘 다). 매매 지시가 아니라 산수 검산이다 — 집행은 결재 비율·규칙대로.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]


def parse_w(s: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for part in s.split(","):
        if not part.strip():
            continue
        k, v = part.split("=")
        out[k.strip()] = float(v)
    return out


def default_target() -> tuple[dict[str, float], float]:
    sys.path.insert(0, str(ROOT))
    from screener.defs import ISA_BAND, ISA_TARGET  # noqa: E402
    return dict(ISA_TARGET), float(ISA_BAND)


def allocate(target: dict[str, float], cur: dict[str, float], c: float, first: list[str] | None = None) -> dict:
    """target 합=1(정규화), cur 상대값(합=V 로 정규화해 100), c = V(=100) 대비 납입. 반환: 배정·사후 비중·대기."""
    tsum = sum(target.values())
    tw = {k: v / tsum for k, v in target.items()}
    keys = list(tw) + [k for k in cur if k not in tw]
    csum = sum(cur.values())
    V = 100.0
    vi = {k: cur.get(k, 0.0) / csum * V for k in keys}
    short = {k: max(0.0, tw.get(k, 0.0) * (V + c) - vi[k]) for k in keys}
    pool = [k for k in keys if (first is None or k in first)]
    s_pool = sum(short[k] for k in pool)
    if first is None:
        alloc = {k: (c * short[k] / s_pool if s_pool > 0 else 0.0) for k in keys}
    else:  # 지정 칸 부족분까지만 채우고 남는 납입은 대기(현금)
        use = min(c, s_pool)
        alloc = {k: (use * short[k] / s_pool if (k in pool and s_pool > 0) else 0.0) for k in keys}
    wait = c - sum(alloc.values())
    tot = V + c
    post = {k: (vi[k] + alloc[k]) / (tot - wait) for k in keys}
    pre = {k: vi[k] / V for k in keys}
    return {"tw": tw, "pre": pre, "short": short, "alloc": alloc, "wait": wait, "post": post, "c": c}


def band_flags(w: dict[str, float], tw: dict[str, float], band: float) -> dict[str, float]:
    return {k: w[k] - tw.get(k, 0.0) for k in w if abs(w[k] - tw.get(k, 0.0)) > band + 1e-12}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cur", required=True)
    ap.add_argument("--c", type=float, required=True, help="신규 납입, 현재 코어(=100) 대비")
    ap.add_argument("--target")
    ap.add_argument("--band", type=float)
    ap.add_argument("--first", help="쉼표 목록: 이 칸 부족분만 먼저 배정, 나머지 대기(B안형)")
    a = ap.parse_args(argv)
    if a.target:
        target, band = parse_w(a.target), (a.band if a.band is not None else 0.05)
    else:
        target, band = default_target()
        band = a.band if a.band is not None else band
    band = band / 100 if band > 1 else band
    r = allocate(target, parse_w(a.cur), a.c, a.first.split(",") if a.first else None)
    print(f"식: 부족분_i = max(0, w*_i×(V+C) − V_i), V=100, C={a.c:g} (kb:allocation#7) · 밴드 ±{band*100:.0f}%p (#8)")
    print("칸 | 목표 | 현재 | 부족분 | 납입 배정 % | 사후")
    for k in r["post"]:
        share = r["alloc"][k] / a.c * 100 if a.c else 0.0
        print(f"{k} | {r['tw'].get(k,0)*100:.1f}% | {r['pre'][k]*100:.1f}% | {r['short'][k]:.2f} | {share:.1f}% | {r['post'][k]*100:.1f}%")
    if r["wait"] > 1e-9:
        print(f"대기(예수금): 납입의 {r['wait']/a.c*100:.1f}% — 사후 비중은 대기분 제외 기준")
    for lab, w in (("배정 전", r["pre"]), ("배정 후", r["post"])):
        f = band_flags(w, r["tw"], band)
        print(f"{lab}: " + ("밴드 안 — 매도 없이 끝" if not f else "밴드 이탈 " + " · ".join(f"{k} {d*100:+.1f}%p" for k, d in f.items())))
    print("매도 0 (현금흐름 방식). 산수 검산이며 매매 지시 아님.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
