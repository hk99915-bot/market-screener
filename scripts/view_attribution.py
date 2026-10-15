#!/usr/bin/env python3
"""관점(렌즈) 사후 귀속 — 채점이 끝난 판단 기록(reports/decisions.json)에서
렌즈가 강세(bull)/약세(bear)였을 때 실제 결과가 그 방향이었는지 렌즈별 적중률을 센다 → reports/views_attrib.json

- 렌즈 상태: 판단에 붙은 pb_view.lenses (PB 판단 기록 시점) 우선, 없으면 reports/views_hist.json 의 같은 날짜 상태(출처 'hist').
- 결과: 그 판단 항목에서 실제 진입한 참가자들(현금 제외) 수익률의 평균 = 그 시점에 걸린 시장 방향.
  진입한 참가자가 하나도 없으면 결과 없음 → 제외.
- 표본이 작을 때(n < 20)는 적중률을 판단 근거로 쓰지 않는다 (views/README.md 승격 규칙).

사용: python scripts/view_attribution.py
"""
import json
import statistics as st
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REP = ROOT / "reports"
MIN_N = 20


def _j(p, d):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return d


def main() -> dict:
    dec = _j(REP / "decisions.json", {"items": []})
    hist = (_j(REP / "views_hist.json", {"days": {}}) or {}).get("days", {})
    per, used = {}, []
    for it in dec.get("items", []):
        r = it.get("result") or {}
        if not r or r.get("void"):
            continue
        rets = [r[w]["ret"] for w, p in (it.get("picks") or {}).items()
                if w in r and isinstance(r[w], dict) and not p.get("cash") and r[w].get("ret") is not None]
        if not rets:
            continue
        out = st.mean(rets)
        pv = it.get("pb_view") or {}
        if pv.get("lenses"):
            lz, src = {k: (v.get("s"), v.get("b")) for k, v in pv["lenses"].items()}, "snapshot"
        elif it.get("date") in hist:
            lz, src = {k: tuple(v) for k, v in hist[it["date"]].get("states", {}).items()}, "hist"
        else:
            continue
        used.append({"id": it["id"], "date": it.get("date"), "outcome": round(out, 4), "src": src})
        for lid, (state, bias) in lz.items():
            if bias not in ("bull", "bear"):
                continue
            p = per.setdefault(lid, {"bull": {"n": 0, "hit": 0, "outs": []}, "bear": {"n": 0, "hit": 0, "outs": []}})[bias]
            p["n"] += 1
            p["hit"] += int(out > 0 if bias == "bull" else out < 0)
            p["outs"].append(out)
    lenses = {}
    for lid, v in per.items():
        lenses[lid] = {}
        for b, p in v.items():
            if p["n"]:
                lenses[lid][b] = {"n": p["n"], "hit": round(p["hit"] / p["n"], 3), "avg_outcome": round(st.mean(p["outs"]), 4),
                                  "usable": p["n"] >= MIN_N}
    o = {"asof": datetime.now().strftime("%Y-%m-%d %H:%M"), "n_decisions": len(used), "min_n": MIN_N,
         "note": f"표본 {MIN_N}건 미만 렌즈는 적중률을 판단 근거로 쓰지 않음. 결과 = 그 판단에서 실제 진입한 쪽 수익률 평균(시장 방향 대용).",
         "lenses": lenses, "decisions": used[-50:]}
    (REP / "views_attrib.json").write_text(json.dumps(o, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"귀속: 판단 {len(used)}건, 렌즈 {len(lenses)}개 → reports/views_attrib.json")
    return o


if __name__ == "__main__":
    main()
