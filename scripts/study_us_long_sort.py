"""미장 운용회의 매수후보 정렬 3안 비교 — (a) 가격 확인 r20>0 (b) Δdrv 정렬 (c) 현행 drv≥0.4+r20≤−3% (연구 전용, 매매 지시 아님).

요청: req-quant-d242da52(pb, "7일 연속 DELL·HOOD") + req-quant-4abdbeaf(겸이, 가격 조건 검정) 잔여분.
사전등록(이 파일 커밋이 결과 json 보다 먼저, 2026-10-23 21:35 KST):
 Part 1 — 장기 가격 절반 (data/hist/us_*.parquet 2010~2025, 현재 상장 종목 → 생존편향, drv 없음):
   H1: r20>0 그룹 − r20≤−3% 그룹 의 향후 5거래일 초과수익(유니버스 동일가중 평균 대비) 차 > 0
   H2: 같은 차의 향후 20거래일 버전 > 0
   비중첩(h일 간격) 날짜별 차 시계열 → 평균·t·단측 p. m=2, α=0.05/2=0.025. IS ≤2019-12-31 / OOS 2020~.
   등급: A=Bonferroni 통과+IS·OOS 같은 방향 / B=Bonferroni 통과 / C=p<0.10 / F=효과 없음·반대.
   상한 B(생존편향·drv 미포함·비용 미반영). 'C(역방향)'은 단측 반대쪽 p<0.10 일 때 별도 표기.
 Part 2 — 실제 drv 스냅숏 (reports/peers_US.json git 이력, 거래일 10/14~10/22 7개, 종목 ~520):
   기술 통계만 — 정렬 3안 상위 10 의 (i) 날짜 간 겹침 (ii) drv 일간 변화 분포·포화(|drv|≥0.9) 비율
   (iii) 다음 1~5일 초과수익. 사전 최소 표본(독립 5일 창 ≥20)에 한참 못 미침 → 등급 '검증전' 고정(결과와 무관).
"""
from __future__ import annotations

import glob
import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "reports/studies/2026-10-23_us_long_sort.json"
SPLIT, LO, ALPHA = "2019-12-31", -0.03, 0.025
TOP = 10


def p_one(t: float, sign: int = 1) -> float:
    return 0.5 * math.erfc(t * sign / math.sqrt(2))


def summarize(s: pd.Series) -> dict:
    n = len(s)
    if n < 3:
        return {"n_dates": n}
    m, sd = float(s.mean()), float(s.std(ddof=1))
    t = m / (sd / math.sqrt(n)) if sd > 0 else 0.0
    return {"n_dates": n, "mean": m, "t": t, "p_one": p_one(t, +1), "win": float((s > 0).mean())}


def diff_series(px: pd.DataFrame, h: int) -> pd.Series:
    """날짜별 [r20>0 그룹 평균 초과수익] − [r20≤−3% 그룹 평균 초과수익], h일 간격 비중첩."""
    r20 = px / px.shift(20) - 1
    fwd = px.shift(-h) / px - 1
    exc = fwd.sub(fwd.mean(axis=1), axis=0)
    idx = px.index[20:-h:h]
    r20, exc = r20.loc[idx], exc.loc[idx]
    a = exc.where(r20 > 0).mean(axis=1)
    c = exc.where(r20 <= LO).mean(axis=1)
    return (a - c).dropna()


def grade(all_: dict, is_: dict, oos: dict) -> str:
    p = all_.get("p_one", 1.0)
    if p < ALPHA:
        same = (is_.get("mean", 0) > 0) and (oos.get("mean", 0) > 0)
        return "B" if same else "B(하위구간 불일치)"   # 상한 B — 생존편향·drv 미포함
    if p < 0.10:
        return "C"
    if 1 - p < 0.10:
        return "C(역방향)"
    return "F"


def part1(files: list[str]) -> dict:
    d = pd.concat([pd.read_parquet(f, columns=["yf", "date", "close"]) for f in files])
    d["date"] = pd.to_datetime(d["date"])
    px = d.pivot_table(index="date", columns="yf", values="close").sort_index()
    px = px.loc[:, px.notna().mean() > 0.8]
    out = {"universe": {"symbols": int(px.shape[1]), "first": str(px.index[0].date()), "last": str(px.index[-1].date())}, "H": {}}
    for k, h in (("H1", 5), ("H2", 20)):
        s = diff_series(px, h)
        a, i, o = summarize(s), summarize(s[s.index <= SPLIT]), summarize(s[s.index > SPLIT])
        out["H"][k] = {"name": f"(a) r20>0 − (c) r20≤−3%, 향후 {h}일 초과수익 차", "h": h, "all": a, "IS": i, "OOS": o,
                       "grade": grade(a, i, o)}
    return out


# ───────────── Part 2: 실제 drv 스냅숏 ─────────────
def snapshots(path: str = "reports/peers_US.json") -> dict[str, dict]:
    """git 이력의 peers_US.json → {asof 날짜: {종목: row}} (같은 날 여러 판이면 가장 늦은 커밋)."""
    hs = subprocess.run(["git", "-C", str(ROOT), "log", "--format=%h", "--", path], capture_output=True, text=True).stdout.split()
    snap: dict[str, dict] = {}
    for h in hs:                                   # 최신 커밋부터 → 날짜별 첫 판 = 가장 늦은 판
        try:
            d = json.loads(subprocess.run(["git", "-C", str(ROOT), "show", f"{h}:{path}"], capture_output=True, text=True).stdout)
        except Exception:  # noqa: BLE001
            continue
        a = str(d.get("asof", ""))[:10]
        if len(a) == 10 and a[4] == "-" and a not in snap:
            snap[a] = {r["s"]: r for r in d.get("rows", []) if r.get("s")}
    return dict(sorted(snap.items()))


def pick(rows: dict, rule: str, prev: dict | None = None) -> list[str]:
    R = [r for r in rows.values() if r.get("drv") is not None and r.get("r20") is not None]
    if rule == "c":
        L = [r for r in R if r["drv"] >= 0.4 and r["r20"] <= LO]
        L.sort(key=lambda r: (-r["drv"], r["s"]))
    elif rule == "a":
        L = [r for r in R if r["drv"] >= 0.4 and r["r20"] > 0]
        L.sort(key=lambda r: (-r["drv"], r["s"]))
    else:  # "b": Δdrv(첫 스냅숏 대비) 큰 순, Δ>0 만
        if not prev:
            return []
        L = [r for r in R if prev.get(r["s"], {}).get("drv") is not None and r["drv"] - prev[r["s"]]["drv"] > 0]
        L.sort(key=lambda r: (-(r["drv"] - prev[r["s"]]["drv"]), r["s"]))
    return [r["s"] for r in L[:TOP]]


def fwd_excess(snap: dict, dates: list[str], i: int, names: list[str], h: int) -> float | None:
    """dates[i] 종가 → dates[i+h] 종가, 이후 스냅숏의 r1 을 이어 붙인 수익 − 유니버스 평균."""
    if i + h >= len(dates) or not names:
        return None
    later = [snap[d] for d in dates[i + 1:i + h + 1]]
    common = set(snap[dates[i]])
    for s in later:
        common &= set(s)

    def cum(t: str) -> float | None:
        v = 1.0
        for s in later:
            r1 = s[t].get("r1")
            if r1 is None:
                return None
            v *= 1 + r1
        return v - 1
    u = [x for x in (cum(t) for t in common) if x is not None]
    g = [x for x in (cum(t) for t in names if t in common) if x is not None]
    return float(np.mean(g) - np.mean(u)) if u and g else None


def part2() -> dict:
    snap = snapshots()
    dates = list(snap)
    first = snap[dates[0]] if dates else {}
    lists = {k: {d: pick(snap[d], k, first if k == "b" and j >= 3 else None) for j, d in enumerate(dates)} for k in "acb"}
    over = {}
    for k, L in lists.items():
        ds = [d for d in dates if L[d]]
        j = [len(set(L[x]) & set(L[y])) / TOP for x, y in zip(ds, ds[1:])]
        cnt: dict[str, int] = {}
        for d in ds:
            for t in L[d]:
                cnt[t] = cnt.get(t, 0) + 1
        over[k] = {"n_dates": len(ds), "mean_overlap_next_day": round(float(np.mean(j)), 3) if j else None,
                   "always": sorted(t for t, c in cnt.items() if c == len(ds) and len(ds) > 1)}
    dd = []
    for x, y in zip(dates, dates[1:]):
        dd += [snap[y][t]["drv"] - snap[x][t]["drv"] for t in snap[x] if t in snap[y]
               and snap[x][t].get("drv") is not None and snap[y][t].get("drv") is not None]
    dd = np.abs(np.array(dd))
    last = snap[dates[-1]] if dates else {}
    dv = np.array([r["drv"] for r in last.values() if r.get("drv") is not None])
    span = [t for t in last if t in first and last[t].get("drv") is not None and first[t].get("drv") is not None]
    dspan = np.abs(np.array([last[t]["drv"] - first[t]["drv"] for t in span]))
    fwd = {k: {h: [v for v in (fwd_excess(snap, dates, i, lists[k][d], h) for i, d in enumerate(dates)) if v is not None]
               for h in (1, 3, 5)} for k in lists}
    fsum = {k: {f"h{h}": {"n": len(v), "mean": round(float(np.mean(v)), 4) if v else None} for h, v in x.items()} for k, x in fwd.items()}
    return {"dates": dates, "n_names_last": len(last), "lists": lists, "overlap": over,
            "drv_daily_abs_change": {"n": int(dd.size), "share_zero": round(float((dd < 0.005).mean()), 3) if dd.size else None,
                                     "p90": round(float(np.quantile(dd, 0.9)), 3) if dd.size else None},
            "drv_span_abs_change": {"from": dates[0] if dates else None, "to": dates[-1] if dates else None,
                                    "share_lt_0.05": round(float((dspan < 0.05).mean()), 3) if dspan.size else None},
            "drv_ge_0.4_share": round(float((dv >= 0.4).mean()), 3) if dv.size else None,
            "fwd_excess": fsum, "grade": "검증전",
            "why_grade": "거래일 7개·독립 5일 창 1개 — 사전 최소 표본(≥20) 미달. 결과와 무관하게 사전 고정"}


def main() -> int:
    files = sorted(glob.glob(str(ROOT / "data/hist/us_*.parquet")))
    res = {"study": "us_long_sort", "date": "2026-10-23", "m": 2, "alpha_bonf": ALPHA, "split": SPLIT,
           "requests": ["req-quant-d242da52", "req-quant-4abdbeaf"],
           "part1": part1(files), "part2": part2()}
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1))
    print(json.dumps({k: v for k, v in res.items() if k != "part2"} | {"part2": {k: v for k, v in res["part2"].items() if k != "lists"}},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
