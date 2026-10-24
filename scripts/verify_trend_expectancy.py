#!/usr/bin/env python3
"""trend_expectancy 사전등록 §3 검증(10/24) — docs/valuation_notes/2026-10-17_trend_expectancy_prereg.md §6 에 덧붙일 숫자.

  python3 scripts/verify_trend_expectancy.py   → reports/studies/trend_expectancy_verify.json

§3-1 재현: 현재 detail 파일로 연구 스크립트(run_market) 재실행 → 같은 기준일 sim_signals_{KR,US}.json exp 통과 집합과 비교
§3-2 과잉 통과: git 이력의 sim_signals (기준일 10/17~10/23, 기준일별 마지막 판) exp (통과, m) 합 → 이항 p (귀무 0.05)
§3-3 서술: 10/16 통과(US IEX) vs 같은 날 (a)·(b) 충족 비통과, 10/16 종가 → 5거래일 뒤 종가 (detail 유니버스 중앙값 대비). 검정 아님.
§3-4 뒤집는 조건: 재현 불일치 · 통과의 70%+ 한 업종.
"""
from __future__ import annotations

import json
import math
import statistics as st
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import study_trend_expectancy as S  # noqa: E402
from screener import detail as D  # noqa: E402

OUT = ROOT / "reports" / "studies" / "trend_expectancy_verify.json"
WIN = ("2026-10-17", "2026-10-23")


def binom_tail(k, n, p=0.05):
    return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k, n + 1)) if n else None


def repro() -> dict:
    out = {}
    for mk in ("KR", "US"):
        r = S.run_market(mk)
        ss = json.loads((ROOT / "reports" / f"sim_signals_{mk}.json").read_text(encoding="utf-8"))
        a = {(x["s"], x["strategy"]) for x in r["exp"]["rows"]}
        b = {(x["s"], x["strategy"]) for x in (ss.get("exp") or {}).get("rows") or []}
        out[mk] = {"study_asof": r["asof"], "pipeline_asof": ss.get("asof"), "study_pass": sorted(map(list, a)),
                   "pipeline_pass": sorted(map(list, b)), "same": a == b, "m_study": r["exp"]["n_eligible"],
                   "m_pipeline": (ss.get("exp") or {}).get("n_eligible"), "repro_rate": r["repro"]["rate"],
                   "pass_by_theme": r["pass_by_theme"]}
    return out


def history() -> dict:
    out = {}
    for mk in ("KR", "US"):
        f = f"reports/sim_signals_{mk}.json"
        hs = subprocess.run(["git", "-C", str(ROOT), "log", "--format=%h", "--", f], capture_output=True, text=True).stdout.split()
        by = {}
        for h in hs:   # 최신 → 과거: 기준일별 첫(=마지막) 판만
            try:
                d = json.loads(subprocess.run(["git", "-C", str(ROOT), "show", f"{h}:{f}"], capture_output=True, text=True).stdout)
            except Exception:  # noqa: BLE001
                continue
            a = str(d.get("asof") or "")[:10]
            if WIN[0] <= a <= WIN[1] and a not in by and d.get("exp"):
                by[a] = {"commit": h, "k": d["exp"].get("n_pass") or 0, "m": d["exp"].get("n_eligible") or 0,
                         "wilson_pass": d.get("n_pass") or 0, "rows": [r["s"] for r in d["exp"].get("rows") or []]}
        out[mk] = dict(sorted(by.items()))
    k = sum(v["k"] for mk in out.values() for v in mk.values())
    m = sum(v["m"] for mk in out.values() for v in mk.values())
    w = sum(v["wilson_pass"] for mk in out.values() for v in mk.values())
    return {"by_market": out, "k": k, "m": m, "expected": round(0.05 * m, 2), "binom_p": None if not m else round(binom_tail(k, m), 4),
            "wilson_pass_total": w,
            "note": "같은 종목·전략이 연속 기준일에 다시 세일 수 있어 m 은 독립 검정 수가 아님(낙관적)."}


def descriptive() -> dict:
    """10/16 기준 상태를 현재 chart 를 10/16 까지 자른 것으로 재구성."""
    d0 = "2026-10-16"
    dd = ROOT / "reports" / "detail" / "US"
    rows, uni = [], []
    for f in sorted(dd.glob("*.json")):
        if f.name.startswith("_"):
            continue
        ch = json.loads(f.read_text(encoding="utf-8")).get("chart") or []
        t = [b.get("t") for b in ch]
        if d0 not in t:
            continue
        i = t.index(d0)
        if i + 5 >= len(ch) or not ch[i + 5].get("c") or not ch[i].get("c"):
            continue
        r5 = ch[i + 5]["c"] / ch[i]["c"] - 1
        uni.append(r5)
        sim, dates = S.rebuild(ch[: i + 1])
        if not sim:
            continue
        for k in D.FRESH_STRATS:
            r = sim[k]["long"]
            if r["pos"] == 1 and str(r["entry_date"]) in set(sim["last2"]) and len(r["rets"]) >= D.EXP_MIN_TRADES:
                rows.append({"s": f.stem, "strategy": k, "pass": D.exp_lb(r["rets"])[2] > 0, "r5": r5})
    med = st.median(uni) if uni else 0
    p = [x["r5"] - med for x in rows if x["pass"]]
    q = [x["r5"] - med for x in rows if not x["pass"]]
    return {"date": d0, "to": "5거래일 뒤 종가", "universe_n": len(uni), "universe_median": round(med, 4),
            "pass": {"n": len(p), "syms": [x["s"] for x in rows if x["pass"]], "mean_ex": round(st.mean(p), 4) if p else None},
            "nonpass": {"n": len(q), "mean_ex": round(st.mean(q), 4) if q else None, "median_ex": round(st.median(q), 4) if q else None},
            "note": "서술만 — n 이 작아 등급을 올리지 않음(사전등록 §3-3). 10/16 상태는 현재 chart 를 10/16 까지 잘라 재구성(250봉 창 시작이 며칠 다를 수 있음)."}


def main() -> None:
    rp, hi, ds = repro(), history(), descriptive()
    flip_repro = not all(v["same"] for v in rp.values())
    passes = [s for mk in hi["by_market"].values() for v in mk.values() for s in v["rows"]]
    rec = ("E 로 대체 추천" if (hi["binom_p"] is not None and hi["binom_p"] < 0.05 and hi["wilson_pass_total"] == 0)
           else "병기 유지, C")
    out = {"prereg": "docs/valuation_notes/2026-10-17_trend_expectancy_prereg.md §3", "repro": rp, "history": hi, "descriptive": ds,
           "flip": {"repro_mismatch": flip_repro, "n_pass_window": len(passes),
                    "theme_70": "통과 0~1건이라 판정 불가" if len(passes) < 3 else None},
           "recommendation": rec if not flip_repro else "표시 중단 추천(재현 불일치)"}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1)[:4000])


if __name__ == "__main__":
    main()
