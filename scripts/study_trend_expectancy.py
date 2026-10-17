#!/usr/bin/env python3
"""추세 시뮬레이션 '새로 켜짐' — 기대값 t 하한 규칙 (퀀트, 사전등록 docs/valuation_notes/2026-10-17_trend_expectancy_prereg.md).

  python3 scripts/study_trend_expectancy.py            # reports/studies/trend_expectancy.{json,md} 생성
  python3 scripts/study_trend_expectancy.py --prereg   # 결과 없이 사전등록 블록만 json 에 (결과 보기 전 커밋용)

입력  reports/detail/{KR,US}/*.json 의 chart(c·s20·s50·p) — 재구성 규칙은 사전등록 §2
계산  screener.detail 의 _sim_one·_fresh·_fresh_exp·exp_lb·boot_lb 를 그대로 호출(파이프라인과 같은 수식)
출력  reports/studies/trend_expectancy.json (m = 검정 수, 통과 목록, Wilson 비교, 재현율) · .md 요약
영향 범위  문서·운용회의 sim_fresh 'C·참고' 표 보조 원천(파이프라인 sim_signals_*.json 에 exp 블록이 생기기 전까지).
롤백  git revert — 다른 코드가 import 하지 않는다.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from math import comb
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from screener import detail as D  # noqa: E402

KST = timezone(timedelta(hours=9))
OUT_J = ROOT / "reports" / "studies" / "trend_expectancy.json"
OUT_M = ROOT / "reports" / "studies" / "trend_expectancy.md"
PREREG = {
    "registered": "2026-10-17", "doc": "docs/valuation_notes/2026-10-17_trend_expectancy_prereg.md",
    "rule": f"새로 켜짐 + 청산 거래 ≥ {D.EXP_MIN_TRADES} + 거래당 순수익 t 단측 95% 하한 > 0",
    "secondary": "부트스트랩 단측 95% 하한(B 2000, 시드 20261017) > 0 — 보고만",
    "compare": f"Wilson 규칙(거래 ≥ {D.FRESH_MIN_TRADES}, 승률 하한 > {D.FRESH_WILSON_MIN})",
    "grade_cap": "C", "order_ticket_evidence": False, "verify_due": "2026-10-24",
}


def rebuild(chart: list[dict], days: int = 250) -> tuple[dict, list]:
    """chart → detail._simulate 와 같은 구조의 sim (+fresh·fresh_exp)."""
    g = [r for r in chart if r.get("c") is not None and r.get("s20") is not None and r.get("s50") is not None][-days:]
    if len(g) < 60:
        return {}, []
    c, s20, s50 = [r["c"] for r in g], [r["s20"] for r in g], [r["s50"] for r in g]
    ps = [r.get("p") for r in g]
    dates = [r.get("t") or r.get("d") for r in g]
    ma = [1 if (c[i] > s50[i] and s20[i] > s50[i]) else 0 for i in range(len(c))]
    sar = [0 if ps[i] is None else (1 if c[i] > ps[i] else 0) for i in range(len(c))]
    sim = {"bh": round(c[-1] / c[0] - 1, 4), "last2": [str(dates[-2]), str(dates[-1])]}
    for name, sig in (("ma", ma), ("psar", sar)):
        sim[name] = {"long": D._sim_one(c, sig, dates)}
    sim["fresh"] = D._fresh(sim, dates)
    sim["fresh_exp"] = D._fresh_exp(sim, dates)
    return sim, dates


def run_market(mk: str) -> dict:
    d = ROOT / "reports" / "detail" / mk
    stocks, match, comp, asofs = {}, 0, 0, set()
    for f in sorted(d.glob("*.json")):
        if f.name.startswith("_"):
            continue
        j = json.loads(f.read_text(encoding="utf-8"))
        asofs.add(str(j.get("asof")))
        sim, _ = rebuild(j.get("chart") or [])
        if not sim:
            continue
        stocks[f.stem] = {"name": j.get("name"), "sim": sim}
        for k in D.FRESH_STRATS:   # 재현 점검: 청산 거래 수가 파일의 sim 과 같은가
            orig = ((j.get("sim") or {}).get(k) or {}).get("long") or {}
            if orig.get("trades") is not None:
                comp += 1
                match += int(orig["trades"] == sim[k]["long"]["trades"])
    ex = D.exp_block(stocks)
    boot_diff, wil = [], []
    for s, v in stocks.items():
        for f in v["sim"]["fresh"]:
            wil.append({"s": s, "n": v["name"], "strategy": f["strategy"], "wins": f["wins"], "trades": f["trades"], "wilson_lo": f["wilson_lo"]})
        for k in D.FRESH_STRATS:
            r = v["sim"][k]["long"]
            rets = r["rets"]
            if r["pos"] == 1 and str(r["entry_date"]) in set(v["sim"]["last2"]) and len(rets) >= D.EXP_MIN_TRADES:
                t_pass = D.exp_lb(rets)[2] > 0
                b_pass = D.boot_lb(rets) > 0
                if t_pass != b_pass:
                    boot_diff.append({"s": s, "strategy": k, "t_pass": t_pass, "boot_pass": b_pass})
    sectors = {}
    for r in ex["rows"]:
        th = (json.loads((d / f"{r['s']}.json").read_text(encoding="utf-8")).get("theme") or "기타")
        sectors[th] = sectors.get(th, 0) + 1
    return {"market": mk, "asof": sorted(asofs)[-1] if asofs else None, "n_scanned": len(stocks),
            "repro": {"compared": comp, "match": match, "rate": round(match / comp, 3) if comp else None},
            "exp": ex, "wilson": {"n_pass": len(wil), "rows": wil}, "boot_disagree": boot_diff, "pass_by_theme": sectors}


def render_md(o: dict) -> str:
    L = ["# 추세 '새로 켜짐' 기대값 하한 — 결과 (C·참고)", "",
         f"> 사전등록 {o['prereg']['doc']} · 생성 {o['generated']} KST · 원천 reports/detail/{{KR,US}}/*.json · 주문표 근거 불가.", "",
         "| 시장 | 기준일 | 스캔 | 재현율 | 검정 m | 통과 E | 우연 기대 | 이항 p | Wilson 통과 | 부트스트랩 불일치 |", "|---|---|---|---|---|---|---|---|---|---|"]
    for r in o["markets"]:
        e = r["exp"]
        L.append(f"| {r['market']} | {r['asof']} | {r['n_scanned']} | {r['repro']['rate']} | {e['n_eligible']} | {e['n_pass']} | "
                 f"{e['expected_chance']} | {e['binom_p']} | {r['wilson']['n_pass']} | {len(r['boot_disagree'])} |")
    for r in o["markets"]:
        if not r["exp"]["rows"]:
            continue
        L += ["", f"## {r['market']} 통과", "", "| 종목 | 전략 | 거래 | 기대값 | t 하한 | 승률 | 켜진 날 |", "|---|---|---|---|---|---|---|"]
        for x in r["exp"]["rows"]:
            L.append(f"| {x['n']} ({x['s']}) | {x['label']} | {x['trades']} | {x['exp']*100:+.2f}% | {x['exp_lb']*100:+.2f}% | {x['win']*100:.0f}% | {x['entry_date']} |")
    L.append("")
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prereg", action="store_true")
    a = ap.parse_args(argv)
    if a.prereg:
        OUT_J.write_text(json.dumps({"registered": "2026-10-17", "prereg": PREREG, "status": "registered (결과 없음)"},
                                    ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"wrote {OUT_J.relative_to(ROOT)} (prereg only)")
        return 0
    mk = [run_market(m) for m in ("KR", "US")]
    m_total = sum(r["exp"]["n_eligible"] for r in mk)
    out = {"registered": "2026-10-17", "generated": datetime.now(KST).strftime("%Y-%m-%d %H:%M"),
           "prereg": {**PREREG, "m": m_total}, "status": "result", "markets": mk,
           "grades": {f"E_{r['market']}": "C" if r["exp"]["n_pass"] else "F" for r in mk}}
    if any((r["repro"]["rate"] or 0) < 0.9 for r in mk):
        out["grades"] = {k: "검증전" for k in out["grades"]}
    OUT_J.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    OUT_M.write_text(render_md(out), encoding="utf-8")
    print(render_md(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
