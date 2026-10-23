"""운용회의 '회피' vs '매수 후보' 고정 기간 초과수익 비교 — req-quant-2ba2c1f0 (겸이 10/24 01시 '회피가 더 잘먹히네').

원천: reports/committee_us_hist.json(미장, ref = 마지막 미장 종가일) · reports/committee_hist.json(국장, date = 회의일 종가)
가격: reports/detail/{US,KR}/*.json chart 종가. 진입 = ref(국장 date) 종가, h = 1·3·5 거래일 뒤 종가.
초과 = 종목 수익 − 같은 창 detail 유니버스 중앙값. 날짜별 (회피 평균 − 매수 평균) 의 평균·naive t(날짜 = 표본 단위).
사후(결과를 보고 묻는 질문) → 등급 상한 C, 표본이 날짜 ≤ 6 이라 '검증전'. 비용 미반영. 매매 지시 아님.
실행: python3 scripts/study_avoid_vs_long.py  →  reports/studies/2026-10-24_avoid_vs_long.json
"""
from __future__ import annotations

import json
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "studies" / "2026-10-24_avoid_vs_long.json"
SRC = {"US": "reports/committee_us_hist.json", "KR": "reports/committee_hist.json"}


def closes(market: str) -> dict[str, dict[str, float]]:
    c = {}
    for f in (ROOT / "reports" / "detail" / market).glob("*.json"):
        if f.name.startswith("_"):
            continue
        ch = json.loads(f.read_text(encoding="utf-8")).get("chart") or []
        c[f.stem] = {b["t"]: b["c"] for b in ch if b.get("t") and b.get("c")}
    return c


def run(market: str) -> dict:
    C = closes(market)
    days = sorted({d for v in C.values() for d in v})
    hist = json.loads((ROOT / SRC[market]).read_text(encoding="utf-8"))["rows"]
    res = {}
    for h in (1, 3, 5):
        per, bydate = defaultdict(list), defaultdict(lambda: defaultdict(list))
        for r in hist:
            ref = r.get("ref") or r["date"]
            if ref not in days or days.index(ref) + h >= len(days):
                continue
            d1 = days[days.index(ref) + h]
            med = st.median(v[d1] / v[ref] - 1 for v in C.values() if ref in v and d1 in v)
            for side in ("long", "avoid"):
                for s in r.get(side) or []:
                    v = C.get(s)
                    if v and ref in v and d1 in v:
                        x = v[d1] / v[ref] - 1 - med
                        per[side].append(x)
                        bydate[ref][side].append(x)
        blk = {s: {"n": len(x), "mean": round(st.mean(x), 4), "median": round(st.median(x), 4),
                   "share_pos": round(sum(v > 0 for v in x) / len(x), 2)} for s, x in per.items() if x}
        diffs = {d: round(st.mean(g["avoid"]) - st.mean(g["long"]), 4) for d, g in sorted(bydate.items()) if g["avoid"] and g["long"]}
        if len(diffs) >= 2:
            xs = list(diffs.values())
            sd = st.stdev(xs)
            blk["avoid_minus_long"] = {"n_dates": len(xs), "mean": round(st.mean(xs), 4),
                                       "t_naive": round(st.mean(xs) / (sd / len(xs) ** 0.5), 2) if sd else None, "by_date": diffs}
        res[f"h{h}"] = blk
    return {"dates": [r.get("ref") or r["date"] for r in hist], "asof": days[-1] if days else None, "res": res}


def main() -> None:
    out = {"study": "2026-10-24_avoid_vs_long", "request": "req-quant-2ba2c1f0", "m_unregistered": 6,
           "grade": "검증전(독립 날짜 ≤ 6, 20거래일 추적 미완) · 사후 질문이라 상한 C",
           "method": "진입 = 회의 기준 종가, h 거래일 뒤 종가, 초과 = 종목 − detail 유니버스 중앙값. 날짜별 (회피 평균 − 매수 평균). 비용 미반영.",
           "markets": {m: run(m) for m in (sys.argv[1:] or ["US", "KR"])}}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({m: {h: v.get("avoid_minus_long") for h, v in r["res"].items()} for m, r in out["markets"].items()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
