#!/usr/bin/env python3
"""월 PGR/PLR 집계표 — 행동 스킬 시범(2026-10-31). kb:behavior#2(정의)·#11(월 1회 양식, 건수만)을 그대로 계산한다.

  python3 .claude/skills/behavior-desk/scripts/pgr_plr.py --row 2026-11 4 6 1 9 [규칙매도n]
  python3 .claude/skills/behavior-desk/scripts/pgr_plr.py --csv <비공개 경로>/pgr_counts.csv

CSV 열: month,gain_real,gain_hold,loss_real,loss_hold[,rule_sell]  (건수 정수만 — 금액·종목 열이 있으면 거부)
규칙(#11): PGR = 이익실현 ÷ (이익실현+이익보유) · PLR = 손실실현 ÷ (손실실현+손실보유)
          PGR/PLR ≥ 1.5 = '처분효과 의심' · 월 합계 10건 미만이면 같은 분기 달끼리 합산해 판정(분기 행).
판정은 진단 꼬리표일 뿐 등급이 아니다 — n<20 은 '검증전'을 붙인다(okr_behavior 해석상 유의). 매매 지시 문구 없음.
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

COLS = ("gain_real", "gain_hold", "loss_real", "loss_hold")
OPTIONAL = ("rule_sell",)
SUSPECT = 1.5      # kb:behavior#11 (판정은 judge 의 정수식 = 3/2)
MIN_MONTH_N = 10   # kb:behavior#11 — 미만이면 분기 합산
MIN_N = 20         # okr_behavior 해석상 유의 — n<20 검증전


def ratio(a: int, b: int) -> float | None:
    return a / (a + b) if a + b else None


def judge(row: dict) -> dict:
    gr, gh, lr, lh = (int(row[c]) for c in COLS)
    if min(gr, gh, lr, lh) < 0:
        raise ValueError(f"음수 건수: {row}")
    pgr, plr = ratio(gr, gh), ratio(lr, lh)
    n = gr + gh + lr + lh
    rr = (pgr / plr) if (pgr is not None and plr) else None
    if pgr is None or plr is None:
        verdict = "판정 불가(이익 또는 손실 쪽 0건)"
    elif plr == 0:
        verdict = "처분효과 의심(PLR 0 — 손실 실현 0건)" if pgr > 0 else "판정 불가(실현 0건)"
    else:
        # 경계(=1.5) 포함 — 부동소수 오차 없이 정수로: gr·(lr+lh) ≥ 1.5·lr·(gr+gh) ⇔ 2·gr·(lr+lh) ≥ 3·lr·(gr+gh)
        verdict = "처분효과 의심" if 2 * gr * (lr + lh) >= 3 * lr * (gr + gh) else "의심 아님"
    tag = "" if n >= MIN_N else f" · 검증전(n {n}<{MIN_N})"
    return {**row, "n": n, "pgr": pgr, "plr": plr, "ratio": rr, "verdict": verdict + tag}


def quarter(month: str) -> str:
    y, m = month.split("-")[:2]
    return f"{y}-Q{(int(m) - 1) // 3 + 1}"


def table(rows: list[dict]) -> list[dict]:
    """월 행 + (10건 미만 달이 있는 분기) 분기 합산 행."""
    out, small = [], {}
    for r in rows:
        j = judge(r)
        if j["n"] < MIN_MONTH_N:
            j["verdict"] = f"월 {j['n']}건<{MIN_MONTH_N} → 분기 합산 판정"
            small.setdefault(quarter(r["month"]), []).append(r)
        out.append(j)
    for q, rs in small.items():
        same_q = [r for r in rows if quarter(r["month"]) == q]
        agg = {"month": q + "(합산)", **{c: sum(int(r[c]) for r in same_q) for c in COLS}}
        if all(c in r for r in same_q for c in OPTIONAL):
            agg["rule_sell"] = sum(int(r["rule_sell"]) for r in same_q)
        out.append(judge(agg))
    return out


def fmt(x: float | None, pct: bool = True) -> str:
    if x is None:
        return "—"
    return f"{x * 100:.1f}%" if pct else f"{x:.2f}"


def render(rows: list[dict]) -> str:
    head = "| 월 | 이익실현 n | 이익보유 n | 손실실현 n | 손실보유 n | PGR | PLR | PGR/PLR | 규칙 매도 n | 판정 |"
    lines = [head, "|" + "---|" * 10]
    for r in rows:
        lines.append(f"| {r['month']} | {r['gain_real']} | {r['gain_hold']} | {r['loss_real']} | {r['loss_hold']} | "
                     f"{fmt(r['pgr'])} | {fmt(r['plr'])} | {fmt(r['ratio'], False)} | {r.get('rule_sell', '—')} | {r['verdict']} |")
    return "\n".join(lines)


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        rd = csv.DictReader(f)
        extra = set(rd.fieldnames or []) - set(COLS) - set(OPTIONAL) - {"month"}
        if extra:
            raise ValueError(f"허용 밖 열(금액·종목 금지, 건수만): {sorted(extra)}")
        return [r for r in rd if r.get("month")]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--row", nargs="+", metavar="V", help="month gain_real gain_hold loss_real loss_hold [rule_sell]")
    g.add_argument("--csv", type=Path)
    a = ap.parse_args(argv)
    try:
        if a.row:
            if len(a.row) not in (5, 6):
                ap.error("--row 는 month + 건수 4개 [+ 규칙매도]")
            rows = [dict(zip(("month",) + COLS + OPTIONAL, a.row))]
        else:
            rows = read_csv(a.csv)
        print(render(table(rows)))
    except (ValueError, KeyError) as e:
        print(f"거부: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
