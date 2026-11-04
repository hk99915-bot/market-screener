#!/usr/bin/env python3
"""코스피 장중 패턴 트래킹 — 전강후약·전약후강 등 (겸이 11/4 "장중 변동도 앞으로 트래킹").

  python3 scripts/hf_intraday_pattern.py                 # 최근 10일 분류 + 패턴별 다음날 통계 → reports/hf_intraday_pattern.json
  python3 scripts/hf_intraday_pattern.py --today O H L C  # 오늘 OHLC(장중 잠정)를 직접 넣어 분류

분류(시가 갭 = 시가/전일 종가 −1, 몸통 = 종가/시가 −1, 문턱 ±0.5%):
  전강후약 = 갭 ≥ +0.5% & 몸통 ≤ −0.5% · 전약후강 = 갭 ≤ −0.5% & 몸통 ≥ +0.5%
  강세 지속 = 갭·몸통 모두 ≥ +0.5% · 약세 지속 = 둘 다 ≤ −0.5% · 그 외 혼조
통계는 기술(記述)용 — 사전등록·검정 전(검증전). 매매 신호로 쓰지 않는다. 입력 data/deriv/daily.csv(2010~).
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "deriv" / "daily.csv"
OUT = ROOT / "reports" / "hf_intraday_pattern.json"
KST = timezone(timedelta(hours=9))
THR = 0.005
SPLIT = "2020-01-01"


def load(path: Path = SRC) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                rows.append({"d": r["date"], "o": float(r["kospi_open"]), "h": float(r["kospi_high"]),
                             "l": float(r["kospi_low"]), "c": float(r["kospi_close"])})
            except (TypeError, ValueError):
                continue
    return rows


def classify(prev_c: float, o: float, h: float, l: float, c: float) -> dict:
    gap, body = o / prev_c - 1, c / o - 1
    if gap >= THR and body <= -THR:
        k = "전강후약"
    elif gap <= -THR and body >= THR:
        k = "전약후강"
    elif gap >= THR and body >= THR:
        k = "강세 지속"
    elif gap <= -THR and body <= -THR:
        k = "약세 지속"
    else:
        k = "혼조"
    pos = (c - l) / (h - l) if h > l else 0.5
    return {"type": k, "gap": round(gap, 4), "body": round(body, 4), "ret": round(c / prev_c - 1, 4),
            "range": round((h - l) / prev_c, 4), "close_pos": round(pos, 2)}


def table(rows: list[dict]) -> list[dict]:
    out = []
    for i in range(1, len(rows)):
        p, r = rows[i - 1], rows[i]
        x = {"d": r["d"], **classify(p["c"], r["o"], r["h"], r["l"], r["c"])}
        if i + 1 < len(rows):
            n = rows[i + 1]
            x["next_gap"] = n["o"] / r["c"] - 1
            x["next_ret"] = n["c"] / r["c"] - 1
        if i + 5 < len(rows):
            x["ret5"] = rows[i + 5]["c"] / r["c"] - 1
        out.append(x)
    return out


def stats(tab: list[dict]) -> dict:
    res = {}
    for part, cond in (("IS(~2019)", lambda d: d < SPLIT), ("OOS(2020~)", lambda d: d >= SPLIT)):
        for k in ("전강후약", "전약후강", "강세 지속", "약세 지속", "혼조"):
            xs = [x for x in tab if x["type"] == k and cond(x["d"]) and "next_ret" in x]
            if not xs:
                continue
            m = lambda key: round(sum(x[key] for x in xs if key in x) / max(1, sum(1 for x in xs if key in x)), 4)  # noqa: E731
            res.setdefault(k, {})[part] = {"n": len(xs), "next_gap": m("next_gap"), "next_ret": m("next_ret"),
                                           "ret5": m("ret5"), "up_next": round(sum(x["next_ret"] > 0 for x in xs) / len(xs), 2)}
    return res


def build(today: tuple[float, float, float, float] | None = None, path: Path = SRC) -> dict:
    rows = load(path)
    tab = table(rows)
    o = {"v": 1, "generated_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M KST"), "src": "data/deriv/daily.csv",
         "status": "검증전 — 기술 통계, 매매 신호 아님", "thr": THR, "recent": [{k: x[k] for k in ("d", "type", "gap", "body", "ret", "range", "close_pos")} for x in tab[-10:]],
         "stats": stats(tab)}
    if today:
        o["today"] = {"d": datetime.now(KST).strftime("%Y-%m-%d"), "provisional": True, **classify(rows[-1]["c"], *today)}
    return o


def lines(o: dict) -> list[str]:
    ls = []
    if o.get("today"):
        t = o["today"]
        ls.append(f"오늘(잠정) {t['type']} · 갭 {t['gap']:+.2%} · 몸통 {t['body']:+.2%} · 하루 {t['ret']:+.2%} · 장중폭 {t['range']:.2%} · 종가 위치 {t['close_pos']:.0%}")
    for x in o["recent"][-5:]:
        ls.append(f"{x['d']} {x['type']} · 갭 {x['gap']:+.2%} · 몸통 {x['body']:+.2%} · 하루 {x['ret']:+.2%} · 장중폭 {x['range']:.2%}")
    for k, v in o["stats"].items():
        s = v.get("OOS(2020~)")
        if s:
            ls.append(f"[{k}] 2020~ n={s['n']} · 다음날 시가 {s['next_gap']:+.2%} · 다음날 {s['next_ret']:+.2%}(상승 {s['up_next']:.0%}) · 5일 {s['ret5']:+.2%}")
    ls.append(o["status"])
    return ls


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--today", nargs=4, type=float, metavar=("O", "H", "L", "C"))
    x = ap.parse_args(argv)
    o = build(tuple(x.today) if x.today else None)
    OUT.write_text(json.dumps(o, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n".join(lines(o)))


if __name__ == "__main__":
    main()
