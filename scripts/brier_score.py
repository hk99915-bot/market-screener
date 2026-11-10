#!/usr/bin/env python3
"""리서치 본부 확률 장부 Brier 채점 (퀀트, req-quant-9aace2dc · 합친 표 req-quant-c7ac6b25).

  python3 scripts/brier_score.py            # 채점 표 출력(파일 안 바꿈)
  python3 scripts/brier_score.py --write    # 만기 도래분 판정을 장부에 쓰고 reports/views/prob_scores.{json,md} 갱신
  python3 scripts/brier_score.py --asof 2026-11-12

장부  reports/views/prob_ledger.json (확률 발언) + reports/views/analyst_calls.json (애널 판정, prob=null → 적중률만)
시세  data/kr_prices.parquet (릴리스 자산 — 먼저 `python3 scripts/data_store.py pull --groups all`)
판정  auto.type=close_up: 기준일 종가 대비 horizon_days 거래일 뒤 종가가 높으면 outcome 1. 그날 시세가 아직 없으면 open 유지.
      auto 없는 건은 사람이 status·outcome 을 적는다(이 스크립트는 읽기만).
Brier = mean((prob − outcome)²). 기준 0.25 = 항상 50%. 기저율(base_rate)이 있는 건은 기저율 Brier 와 나란히.
영향 범위  문서·장부 전용 — 워크플로·탭·알림은 import 하지 않는다. 롤백 = 이 파일·장부·산출·테스트 삭제.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "reports/views/prob_ledger.json"
ANALYST = ROOT / "reports/views/analyst_calls.json"
PRICES = ROOT / "data/kr_prices.parquet"
OUT = ROOT / "reports/views/prob_scores"
BUCKETS = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0001)]


def load_closes(yfs: set[str], path: Path = PRICES) -> dict[str, list[tuple[str, float]]]:
    """{yf: [(날짜, 종가)…]} 날짜 오름차순. 파일이 없으면 빈 dict."""
    if not yfs or not path.exists():
        return {}
    import pandas as pd
    d = pd.read_parquet(path, columns=["yf", "date", "close"])
    d = d[d.yf.isin(yfs)].sort_values("date")
    return {k: [(str(a)[:10], float(b)) for a, b in zip(g.date, g.close)] for k, g in d.groupby("yf")}


def resolve(call: dict, closes: dict, asof: str | None = None) -> dict | None:
    """auto 판정. 만기 시세가 있으면 {outcome, status, resolved, resolved_note}, 없으면 None."""
    a = call.get("auto")
    if call.get("status") != "open" or not a or a.get("type") != "close_up":
        return None
    px = closes.get(a["yf"]) or []
    if asof:
        px = [p for p in px if p[0] <= asof]
    dates = [p[0] for p in px]
    if a["base_date"] not in dates:
        return None
    i = dates.index(a["base_date"]) + int(a["horizon_days"])
    if i >= len(px):
        return None
    base, end = px[dates.index(a["base_date"])][1], px[i][1]
    out = 1 if end > base else 0
    return {"outcome": out, "status": "hit" if out else "miss", "resolved": px[i][0],
            "resolved_note": f"{a['yf']} 종가 {a['base_date']} → {px[i][0]} 수익률 {(end / base - 1) * 100:+.1f}% (data/kr_prices.parquet)"}


def brier(pairs: list[tuple[float, int]]) -> float | None:
    return round(sum((p - o) ** 2 for p, o in pairs) / len(pairs), 4) if pairs else None


def score(calls: list[dict]) -> dict:
    """채점 요약. prob 있는 판정 건 → Brier·보정표, prob=null 판정 건 → 적중률."""
    done = [c for c in calls if c.get("status") in ("hit", "miss") and c.get("outcome") in (0, 1)]
    pr = [c for c in done if isinstance(c.get("prob"), (int, float))]
    bn = [c for c in done if c.get("prob") is None]
    pairs = [(float(c["prob"]), int(c["outcome"])) for c in pr]
    wb = [c for c in pr if isinstance(c.get("base_rate"), (int, float))]
    cal = []
    for lo, hi in BUCKETS:
        b = [(p, o) for p, o in pairs if lo <= p < hi]
        if b:
            cal.append({"bucket": f"{lo:.1f}~{min(hi, 1.0):.1f}", "n": len(b), "mean_prob": round(sum(p for p, _ in b) / len(b), 3),
                        "freq": round(sum(o for _, o in b) / len(b), 3)})
    by_desk: dict[str, dict] = {}
    for c in calls:
        d = by_desk.setdefault(c.get("desk", "?"), {"n": 0, "open": 0, "resolved": 0, "void": 0, "pairs": [], "hits": 0, "binary": 0})
        d["n"] += 1
        st = c.get("status")
        d["open"] += st == "open"
        d["void"] += st == "void"
        if c in done:
            d["resolved"] += 1
            if c in pr:
                d["pairs"].append((float(c["prob"]), int(c["outcome"])))
            else:
                d["binary"] += 1
                d["hits"] += c["status"] == "hit"
    for d in by_desk.values():
        d["brier"] = brier(d.pop("pairs"))
        d["hit_rate"] = round(d["hits"] / d["binary"], 3) if d["binary"] else None
    return {"n_calls": len(calls), "n_open": sum(c.get("status") == "open" for c in calls), "n_resolved": len(done),
            "n_prob_resolved": len(pr), "brier": brier(pairs), "brier_ref_50": 0.25 if pairs else None,
            "brier_base_rate": brier([(float(c["base_rate"]), int(c["outcome"])) for c in wb]),
            "brier_same_calls_as_base": brier([(float(c["prob"]), int(c["outcome"])) for c in wb]), "n_with_base_rate": len(wb),
            "calibration": cal, "binary_resolved": len(bn), "binary_hits": sum(c["status"] == "hit" for c in bn), "by_desk": by_desk,
            "next_due": min((c["horizon_end"] for c in calls if c.get("status") == "open" and c.get("horizon_end")), default=None)}


def build_md(calls: list[dict], s: dict, asof: str) -> str:
    L = ["# 리서치 본부 확률·판정 채점표", "", f"> `scripts/brier_score.py --write` 산출물 — 손으로 고치지 않는다. 기준 {asof} · 장부 `reports/views/prob_ledger.json` + `reports/views/analyst_calls.json`.",
         "> 읽는 법: **Brier** = (말한 확률 − 실제 0/1)² 의 평균. 0 이 완벽, **0.25 = 항상 50% 라고 말한 것과 같음**, 그보다 크면 동전보다 못함. 표본이 20건 아래면 등급 없이 숫자만 본다.", "",
         "## 요약",
         f"- 기록 {s['n_calls']}건 · 판정 끝 {s['n_resolved']}건 · 대기 {s['n_open']}건 · 다음 만기 {s['next_due'] or '–'}",
         f"- Brier {s['brier'] if s['brier'] is not None else '–'} (확률 있는 판정 {s['n_prob_resolved']}건, 기준 0.25)"
         + (f" · 기저율만 말했을 때 {s['brier_base_rate']} vs 우리 {s['brier_same_calls_as_base']} (같은 {s['n_with_base_rate']}건)" if s["n_with_base_rate"] else ""),
         f"- 확률 없는 판정(애널): {s['binary_hits']}/{s['binary_resolved']} 적중" if s["binary_resolved"] else "- 확률 없는 판정(애널): 판정 끝 0건",
         "", "## 데스크별", "", "| 데스크 | 기록 | 판정 끝 | 대기 | Brier | 적중률(확률 없는 건) |", "|---|---|---|---|---|---|"]
    for k, d in s["by_desk"].items():
        L.append(f"| {k} | {d['n']} | {d['resolved']} | {d['open']} | {d['brier'] if d['brier'] is not None else '–'} | {d['hit_rate'] if d['hit_rate'] is not None else '–'} |")
    L += ["", "## 보정표 (말한 확률 구간별 실제 빈도)", "", "| 구간 | 건수 | 평균 확률 | 실제 빈도 |", "|---|---|---|---|"]
    L += [f"| {c['bucket']} | {c['n']} | {c['mean_prob']} | {c['freq']} |" for c in s["calibration"]] or ["| – | 0 | – | – |"]
    L += ["", "## 전체 목록", "", "| id | 데스크 | 대상 | 발언 | 확률 | 기저율 | 만기 | 상태 | 결과 | (p−o)² | 근거 |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for c in sorted(calls, key=lambda c: (c.get("horizon_end") or "", c["id"])):
        p, o = c.get("prob"), c.get("outcome")
        sq = f"{(p - o) ** 2:.4f}" if isinstance(p, (int, float)) and o in (0, 1) else "–"
        L.append(f"| {c['id']} | {c.get('desk', '')} | {c.get('subject', '')} | {c.get('claim', '')[:60]} | {p if p is not None else '–'} | {c.get('base_rate') if c.get('base_rate') is not None else '–'} | "
                 f"{c.get('horizon_end', '')} | {c.get('status', '')} | {o if o is not None else '–'} | {sq} | {c.get('resolved_note', '') or ''} |")
    return "\n".join(L) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--asof", default=None)
    a = ap.parse_args()
    led = json.loads(LEDGER.read_text(encoding="utf-8"))
    closes = load_closes({c["auto"]["yf"] for c in led["calls"] if c.get("auto")})
    newly = []
    for c in led["calls"]:
        r = resolve(c, closes, a.asof)
        if r:
            c.update(r)
            newly.append(c["id"])
    calls = led["calls"] + (json.loads(ANALYST.read_text(encoding="utf-8"))["calls"] if ANALYST.exists() else [])
    asof = a.asof or max((px[-1][0] for px in closes.values()), default="시세 없음")
    s = score(calls)
    md = build_md(calls, s, asof)
    print(md)
    print(f"이번 실행에서 새로 판정: {newly or '없음'}" + ("" if closes else " · 시세 파일 없음 → data_store.py pull 먼저"))
    if a.write:
        if newly:
            led["updated"] = f"{asof} (brier_score.py)"
            LEDGER.write_text(json.dumps(led, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        OUT.with_suffix(".json").write_text(json.dumps({"asof": asof, "newly_resolved": newly, **s}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        OUT.with_suffix(".md").write_text(md, encoding="utf-8")


if __name__ == "__main__":
    main()
