#!/usr/bin/env python3
"""VaR·ES 계기판 + 초과일 백테스트 신호등 + 스트레스 비중 산술 — 리스크(FRM) 스킬 시범(2026-10-31).

KB 공식만 쓴다(새 규칙 없음): 파라메트릭 VaR99 = 2.326σ · ES97.5 = 2.338σ (kb:frm#4) · 역사적 VaR99 = 250일 1% 분위,
ES97.5 = 최악 2.5% 평균 (#5) · 초과일 = '손실 > 전날 VaR99', 250일 기대 2.5회, 0–4 녹 / 5–9 황 / 10+ 적, 0회도 과대 의심 (#6)
· σ 창 20/60/250 + 역사적 VaR 병기 (복기 #1, #22: 60일 기본·20일 참고) · 허용 비중 = 한도 ÷ 충격 (#10) · 회복 필요 수익 (#1).

  python3 .claude/skills/frm-desk/scripts/var_backtest.py --csv <파일.csv> [--col ret] [--pct]   # 일간 수익률 열
  python3 .claude/skills/frm-desk/scripts/var_backtest.py --csv <파일.csv> --col close --price    # 종가 열 → 수익률
  python3 .claude/skills/frm-desk/scripts/var_backtest.py --ticker <yf코드>                      # data/kr_prices.parquet(공개 시세)
  python3 .claude/skills/frm-desk/scripts/var_backtest.py --stress --limit 15 --shock 50          # #10 허용 비중만

개인 북 수익률은 비공개 저장소(pb-private risk/frm.py)에서만 돌린다 — 공개 저장소엔 결과 비율만.
정규 가정·창 길이는 보고 줄에 같이 찍는다. 출력은 계기판(한도 아님, #7) — 판정 문장은 데스크가 쓴다.
"""
from __future__ import annotations

import argparse
import csv
import math
import statistics
import sys
from pathlib import Path

Z99 = 2.326     # kb:frm#4
K_ES975 = 2.338  # kb:frm#4 (정규)
ROOT = Path(__file__).resolve().parents[4]


def sigma(r: list[float]) -> float:
    return statistics.stdev(r) if len(r) > 1 else float("nan")


def param_var_es(r: list[float], window: int) -> tuple[float, float, int]:
    """최근 window일 σ 로 (VaR99, ES97.5, 실제 n). 손실을 양수로."""
    w = r[-window:]
    s = sigma(w)
    return Z99 * s, K_ES975 * s, len(w)


def hist_var_es(r: list[float], window: int = 250) -> tuple[float, float, int]:
    """역사적 VaR99 = 손실 1% 분위(최악 ceil(1%·n)번째, 250일 → 3번째), ES97.5 = 최악 floor(2.5%·n)개 평균(250일 → 6일, #5)."""
    w = sorted(r[-window:])
    n = len(w)
    if n == 0:
        return float("nan"), float("nan"), 0
    k_var = max(1, math.ceil(0.01 * n))
    k_es = max(1, int(0.025 * n))
    return -w[k_var - 1], -sum(w[:k_es]) / k_es, n


def traffic_light(exc: int) -> str:
    """Basel 신호등 (#6, 250일 기준 칸 그대로)."""
    if exc >= 10:
        return "적(모형 폐기)"
    if exc >= 5:
        return "황(의심)"
    if exc == 0:
        return "녹(정상) · 0회 = VaR 과대 의심(#6)"
    return "녹(정상)"


def backtest(r: list[float], sigma_window: int = 60, days: int = 250) -> dict:
    """직전 days일 각 날 t: 손실 −r_t > 전날까지 sigma_window일 파라메트릭 VaR99 면 초과 (#6)."""
    start = max(sigma_window, len(r) - days)
    exc_idx = []
    for t in range(start, len(r)):
        var_t = Z99 * sigma(r[t - sigma_window:t])
        if -r[t] > var_t:
            exc_idx.append(t)
    n = len(r) - start
    # 몰림 참고: 60일 안 최대 초과 수(판정 문턱은 KB 에 없음 — 숫자만 보여 준다)
    dense = max((sum(1 for j in exc_idx if i <= j < i + 60) for i in exc_idx), default=0)
    return {"n": n, "exc": len(exc_idx), "expected": 0.01 * n, "idx": exc_idx,
            "max_in_60d": dense, "light": traffic_light(len(exc_idx)) if n >= 250 else f"표본 {n}일 < 250 — 신호등 칸 미적용"}


def stress_cap(limit_pct: float, shock_pct: float) -> float:
    """허용 비중(%) = 한도 ÷ 충격 (#10). 예: 15 ÷ 50 → 30%."""
    return 100.0 * abs(limit_pct) / abs(shock_pct)


def recovery_needed(loss_pct: float) -> float:
    """손실 L 뒤 회복 필요 수익(%) = 1/(1−L) − 1 (#1)."""
    L = abs(loss_pct) / 100.0
    return 100.0 * (1 / (1 - L) - 1)


def load_returns(args) -> tuple[list[float], list[str], str]:
    if args.ticker:
        import pandas as pd  # 지연 import — 스트레스 산술만 쓸 땐 불필요
        d = pd.read_parquet(ROOT / "data" / "kr_prices.parquet")
        d = d[d.yf == args.ticker].sort_values("date")
        if d.empty:
            sys.exit(f"데이터 없음(data/kr_prices.parquet 에 {args.ticker} 없음)")
        px = d.close.astype(float).tolist()
        dates = d.date.astype(str).tolist()
        return [b / a - 1 for a, b in zip(px, px[1:])], dates[1:], f"data/kr_prices.parquet {args.ticker} 종가"
    with open(args.csv, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows or args.col not in rows[0]:
        sys.exit(f"데이터 없음({args.csv} 에 열 '{args.col}' 없음)")
    vals = [float(x[args.col]) for x in rows if x[args.col] not in ("", None)]
    dates = [x.get(args.date_col, str(i)) for i, x in enumerate(rows) if x[args.col] not in ("", None)]
    if args.price:
        return [b / a - 1 for a, b in zip(vals, vals[1:])], dates[1:], f"{args.csv}:{args.col} 가격"
    if args.pct:
        vals = [v / 100.0 for v in vals]
    return vals, dates, f"{args.csv}:{args.col} 수익률"


def report(r: list[float], dates: list[str], src: str) -> list[str]:
    asof = dates[-1] if dates else "?"
    out = [f"기준 {asof} · 출처 {src} · n {len(r)}일 · 1일·정규 가정(파라메트릭) · 계기판(한도 아님, kb:frm#7)"]
    for w in (20, 60, 250):
        if len(r) >= 2:
            v, e, n = param_var_es(r, w)
            tag = " (기본)" if w == 60 else (" (참고)" if w == 20 else "")
            out.append(f"- 파라메트릭 σ{w}{tag}: VaR99 {100*v:.2f}% · ES97.5 {100*e:.2f}% (σ {100*v/Z99:.2f}%, n {n})")
    hv, he, hn = hist_var_es(r, 250)
    pv, _, _ = param_var_es(r, 60)
    out.append(f"- 역사적({hn}일): VaR99 {100*hv:.2f}% · ES97.5 {100*he:.2f}% · 역사적÷파라메트릭σ60 = {hv/pv:.2f}배"
               " (격차 크면 꼬리 두꺼움, #5)")
    for w in (60, 20):
        if len(r) > w + 1:
            b = backtest(r, w)
            out.append(f"- 초과일 σ{w}: {b['exc']}회 / 기대 {b['expected']:.1f} (직전 {b['n']}일) → {b['light']}"
                       f" · 60일 안 최대 {b['max_in_60d']}회(몰림 참고)")
            if b["idx"]:
                out.append("  초과일: " + ", ".join(dates[i] for i in b["idx"][-12:]))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--csv")
    src.add_argument("--ticker")
    ap.add_argument("--col", default="ret")
    ap.add_argument("--date-col", default="date")
    ap.add_argument("--pct", action="store_true", help="열 값이 % 단위(1.2 = 1.2%)")
    ap.add_argument("--price", action="store_true", help="열 값이 가격 → 단순 수익률로 변환")
    ap.add_argument("--stress", action="store_true", help="#10 허용 비중만 출력")
    ap.add_argument("--limit", type=float, default=15.0, help="구속 한도 % (기본 15, 결재 #3)")
    ap.add_argument("--shock", type=float, help="시나리오 충격 % (예 50)")
    a = ap.parse_args(argv)
    if a.stress:
        if a.shock is None:
            ap.error("--stress 는 --shock 필요")
        print(f"허용 비중 = {a.limit:g} ÷ {a.shock:g} = {stress_cap(a.limit, a.shock):.1f}% (kb:frm#10, 단독 가정 — "
              f"다른 클래스가 같은 한도를 나눠 쓰면 더 작다) · 충격 −{abs(a.shock):g}% 회복 필요 +{recovery_needed(a.shock):.1f}% (#1)")
        return 0
    if not (a.csv or a.ticker):
        ap.error("--csv 또는 --ticker 필요 (또는 --stress)")
    r, dates, s = load_returns(a)
    if len(r) < 21:
        print(f"데이터 없음(표본 {len(r)}일 < 21)")
        return 1
    print("\n".join(report(r, dates, s)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
