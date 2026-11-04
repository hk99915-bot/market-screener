"""무료 트뷰 ICT/SMC 계열 지표 7종 중 일봉 규칙화 가능한 (a)군 검증 — docs/desk_kb/rounds/2026-11-05/quant_ict_open.md §0 사전등록 그대로.

python3 scripts/study_ict_open.py  → reports/studies/ict_open.json (+ 표준출력 요약)
데이터: reports/macro_series.json (dohlcv 일봉, 2024-10~). 미국 SPX·NASDAQ·RUT·SOXX(비용 0.2%), 한국 KOSPI·KOSDAQ(비용 0.45%).
신호는 t일 종가까지의 정보로만 계산 → t+1 시가 진입. 손절 2×ATR14(t)·최대 10거래일 보유. 비용은 왕복 합계를 R 로 환산해 차감.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "reports" / "studies" / "ict_open.json"
SERIES = {"SPX": 0.002, "NASDAQ": 0.002, "RUT": 0.002, "SOXX": 0.002, "KOSPI": 0.0045, "KOSDAQ": 0.0045}
WARM, HOLD, STOPK = 70, 10, 2.0
FVG_MIN, BPR_MIN, FVG_LIFE, SETUP_LIFE = 0.25, 0.10, 10, 20
PIV_N, SMC_LIFE, CH_W, CH_K, VP_W, VP_BINS, VP_K = 5, 15, 60, 2.0, 60, 30, 2.0
RULES = ["BPR", "IFVG", "SMC_BOS", "SMC_CHOCH", "DAYE_WEEKLY", "CHANNEL_REG", "VP_POC", "FORK_PROXY"]
M = len(RULES)
ALPHA_B = 0.05 / M
SEED = 20261105
BENCH_REPS = 2000
IS_FRAC = 0.70


# ---------- 통계 ----------
def t_sf(t: float, df: int) -> float:
    """Student-t 단측 p(T>=t) — scipy 없이 수치적분(Simpson)."""
    if df <= 0:
        return float("nan")
    c = math.exp(math.lgamma((df + 1) / 2) - math.lgamma(df / 2)) / math.sqrt(df * math.pi)
    f = lambda x: c * (1 + x * x / df) ** (-(df + 1) / 2)  # noqa: E731
    a, b, n = abs(t), 60.0, 4000
    h = (b - a) / n
    s = f(a) + f(b) + sum((4 if i % 2 else 2) * f(a + i * h) for i in range(1, n))
    tail = s * h / 3
    return tail if t >= 0 else 1 - tail


def tstat(x: np.ndarray):
    n = len(x)
    if n < 2:
        return float("nan"), float("nan")
    sd = x.std(ddof=1)
    if sd == 0:
        return float("nan"), float("nan")
    t = x.mean() / (sd / math.sqrt(n))
    return float(t), float(t_sf(t, n - 1))


# ---------- 데이터 ----------
def load() -> dict:
    d = json.loads((ROOT / "reports" / "macro_series.json").read_text(encoding="utf-8"))["series"]
    out = {}
    for k in SERIES:
        rows = [r for r in d[k] if r[1] and r[2] and r[3] and r[4] and r[2] >= r[3]]
        a = np.array([[r[1], r[2], r[3], r[4], r[5] or 0.0] for r in rows], dtype=float)
        out[k] = {"date": [r[0] for r in rows], "o": a[:, 0], "h": a[:, 1], "l": a[:, 2], "c": a[:, 3], "v": a[:, 4]}
        out[k]["atr"] = atr14(out[k])
    return out


def atr14(s: dict) -> np.ndarray:
    h, l, c = s["h"], s["l"], s["c"]
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    tr[0] = h[0] - l[0]
    a = np.full(len(c), np.nan)
    if len(c) < 15:
        return a
    a[13] = tr[:14].mean()
    for i in range(14, len(c)):
        a[i] = (a[i - 1] * 13 + tr[i]) / 14
    return a


# ---------- 거래 시뮬 ----------
def simulate(s: dict, t: int, d: int, cost: float):
    """t일 종가 신호 → t+1 시가 진입. (R, 청산 인덱스) 또는 None(미래 자료 부족)."""
    a = s["atr"][t]
    if not a or math.isnan(a) or t + 1 >= len(s["c"]):
        return None
    e = s["o"][t + 1]
    risk = STOPK * a
    stop = e - d * risk
    last = t + HOLD
    for j in range(t + 1, min(last, len(s["c"]) - 1) + 1):
        if d == 1:
            if j > t + 1 and s["o"][j] <= stop:
                x = s["o"][j]
                break
            if s["l"][j] <= stop:
                x = stop
                break
        else:
            if j > t + 1 and s["o"][j] >= stop:
                x = s["o"][j]
                break
            if s["h"][j] >= stop:
                x = stop
                break
        if j == last:
            x = s["c"][j]
            break
    else:
        return None
    r = d * (x - e) / risk - cost * e / risk
    return float(r), j


def run_signals(s: dict, sigs: list, cost: float):
    """sigs=[(t,d)] 시간순, 포지션 보유 중 신호 건너뜀. → [(t, d, R)]"""
    out, busy = [], -1
    for t, d in sorted(sigs):
        if t + 1 <= busy:
            continue
        r = simulate(s, t, d, cost)
        if r is None:
            continue
        out.append((t, d, r[0]))
        busy = r[1]
    return out


# ---------- 신호 정의 (사전등록 문언 §0-3) ----------
def sig_fvg(s: dict):
    """BPR(반대 FVG 두 개 겹침 구간 재진입) · IFVG(FVG 종가 이탈 후 반전 구간 재진입)."""
    h, l, c, at = s["h"], s["l"], s["c"], s["atr"]
    n = len(c)
    fvgs, bpr_p, ifvg_p, bpr, ifvg = [], [], [], [], []
    for t in range(2, n):
        if np.isnan(at[t]):
            continue
        # 대기 중 세트업 해소 (t 는 형성일 이후)
        for lst, out in ((bpr_p, bpr), (ifvg_p, ifvg)):
            for p in lst[:]:
                if t == p["t0"]:
                    continue
                if t - p["t0"] > SETUP_LIFE:
                    lst.remove(p)
                    continue
                if p["d"] == 1:
                    if c[t] < p["lo"]:
                        lst.remove(p)
                    elif l[t] <= p["hi"] and c[t] >= p["lo"]:
                        out.append((t, 1))
                        lst.remove(p)
                else:
                    if c[t] > p["hi"]:
                        lst.remove(p)
                    elif h[t] >= p["lo"] and c[t] <= p["hi"]:
                        out.append((t, -1))
                        lst.remove(p)
        # IFVG: 기존 FVG 종가 이탈
        for f in fvgs[:]:
            if t - f["t"] > FVG_LIFE:
                fvgs.remove(f)
            elif f["d"] == 1 and c[t] < f["lo"]:
                ifvg_p.append({"t0": t, "d": -1, "lo": f["lo"], "hi": f["hi"]})
                fvgs.remove(f)
            elif f["d"] == -1 and c[t] > f["hi"]:
                ifvg_p.append({"t0": t, "d": 1, "lo": f["lo"], "hi": f["hi"]})
                fvgs.remove(f)
        # 새 FVG (t-2 ~ t)
        new = None
        if l[t] > h[t - 2] and l[t] - h[t - 2] >= FVG_MIN * at[t]:
            new = {"t": t, "d": 1, "lo": h[t - 2], "hi": l[t]}
        elif h[t] < l[t - 2] and l[t - 2] - h[t] >= FVG_MIN * at[t]:
            new = {"t": t, "d": -1, "lo": h[t], "hi": l[t - 2]}
        if new:
            best = None
            for f in fvgs:
                if f["d"] == -new["d"] and t - f["t"] <= FVG_LIFE:
                    lo, hi = max(f["lo"], new["lo"]), min(f["hi"], new["hi"])
                    if hi - lo >= BPR_MIN * at[t] and (best is None or hi - lo > best["hi"] - best["lo"]):
                        best = {"t0": t, "d": new["d"], "lo": lo, "hi": hi}
            if best:
                bpr_p.append(best)
            fvgs.append(new)
    return bpr, ifvg


def pivots(s: dict, k: int, n=PIV_N):
    """k 번째 봉이 프랙탈 고/저점인가 (k+n 에 확정). → 'H'/'L'/None"""
    h, l = s["h"], s["l"]
    if k - n < 0 or k + n >= len(h):
        return None
    if h[k] >= h[k - n:k + n + 1].max() and h[k] > h[k - n:k].max():
        return "H"
    if l[k] <= l[k - n:k + n + 1].min() and l[k] < l[k - n:k].min():
        return "L"
    return None


def sig_smc(s: dict):
    """구조 돌파(BOS: 추세 방향 / CHoCH: 추세 반대) 후 돌파 레벨 되돌림(저가≤레벨, 종가>레벨) 신호."""
    h, l, c = s["h"], s["l"], s["c"]
    n = len(c)
    sh = sl = None
    sh_br = sl_br = False
    trend = 0
    pend, bos, choch = [], [], []
    for t in range(n):
        p = pivots(s, t - PIV_N)
        if p == "H":
            sh, sh_br = h[t - PIV_N], False
        elif p == "L":
            sl, sl_br = l[t - PIV_N], False
        for q in pend[:]:
            if t == q["t0"]:
                continue
            if t - q["t0"] > SMC_LIFE:
                pend.remove(q)
                continue
            if q["d"] == 1:
                if c[t] < q["lv"]:
                    pend.remove(q)
                elif l[t] <= q["lv"]:
                    (bos if q["k"] == "BOS" else choch).append((t, 1))
                    pend.remove(q)
            else:
                if c[t] > q["lv"]:
                    pend.remove(q)
                elif h[t] >= q["lv"]:
                    (bos if q["k"] == "BOS" else choch).append((t, -1))
                    pend.remove(q)
        if sh is not None and not sh_br and c[t] > sh:
            if trend != 0:
                pend.append({"t0": t, "d": 1, "lv": sh, "k": "BOS" if trend == 1 else "CHOCH"})
            trend, sh_br = 1, True
        elif sl is not None and not sl_br and c[t] < sl:
            if trend != 0:
                pend.append({"t0": t, "d": -1, "lv": sl, "k": "BOS" if trend == -1 else "CHOCH"})
            trend, sl_br = -1, True
    return bos, choch


def sig_daye(s: dict):
    """주간 분기: 월=Q1(범위), 화=Q2 조작. 화요일이 월 저가 하회 후 월 저가 위 마감 → 롱, 월 고가 상회 후 아래 마감 → 숏."""
    import datetime as dt
    out = []
    for t in range(1, len(s["c"])):
        d1 = dt.date.fromisoformat(s["date"][t])
        d0 = dt.date.fromisoformat(s["date"][t - 1])
        if d1.weekday() != 1 or (d1 - d0).days != 1 or d0.weekday() != 0:
            continue
        up, dn = s["h"][t] > s["h"][t - 1], s["l"][t] < s["l"][t - 1]
        if dn and not up and s["c"][t] > s["l"][t - 1]:
            out.append((t, 1))
        elif up and not dn and s["c"][t] < s["h"][t - 1]:
            out.append((t, -1))
    return out


def sig_channel(s: dict):
    """회귀 채널(60봉 종가 선형회귀 ±2σ): 하단 종가 이탈 다음날 종가 복귀 → 롱 / 상단 대칭 → 숏."""
    c = s["c"]
    n = len(c)
    lo, hi = np.full(n, np.nan), np.full(n, np.nan)
    x = np.arange(CH_W)
    for t in range(CH_W - 1, n):
        y = c[t - CH_W + 1:t + 1]
        b, a = np.polyfit(x, y, 1)
        fit = a + b * x
        sd = (y - fit).std(ddof=2)
        lo[t], hi[t] = fit[-1] - CH_K * sd, fit[-1] + CH_K * sd
    out = []
    for t in range(CH_W, n):
        if c[t - 1] < lo[t - 1] and c[t] >= lo[t]:
            out.append((t, 1))
        elif c[t - 1] > hi[t - 1] and c[t] <= hi[t]:
            out.append((t, -1))
    return out


def poc(s: dict, t: int):
    lo_, hi_ = s["l"][t - VP_W + 1:t + 1], s["h"][t - VP_W + 1:t + 1]
    v = s["v"][t - VP_W + 1:t + 1]
    a, b = lo_.min(), hi_.max()
    if b <= a:
        return None
    edges = np.linspace(a, b, VP_BINS + 1)
    prof = np.zeros(VP_BINS)
    for i in range(len(v)):
        m = (edges[1:] > lo_[i]) & (edges[:-1] < hi_[i])
        k = m.sum()
        if k:
            prof[m] += v[i] / k
    if prof.sum() == 0:
        return None
    j = int(prof.argmax())
    return (edges[j] + edges[j + 1]) / 2


def sig_vp(s: dict):
    """일봉 60일 거래량 가중 가격분포 POC 회귀: 종가가 POC 에서 ≥2×ATR14 떨어지면 POC 쪽으로."""
    out = []
    for t in range(VP_W, len(s["c"])):
        if np.isnan(s["atr"][t]):
            continue
        p = poc(s, t)
        if p is None:
            continue
        z = (p - s["c"][t]) / s["atr"][t]
        if z >= VP_K:
            out.append((t, 1))
        elif z <= -VP_K:
            out.append((t, -1))
    return out


def sig_fork(s: dict):
    """앤드류스 피치포크 자동 앵커 대리: 교대 프랙탈 A-B-C 확정일, 중앙선(A→B·C 중점)이 오르막이고 종가가 중앙선 아래면 롱, 내리막이고 위면 숏."""
    h, l, c = s["h"], s["l"], s["c"]
    piv, out = [], []
    for t in range(len(c)):
        k = t - PIV_N
        p = pivots(s, k)
        if p is None:
            continue
        pr = h[k] if p == "H" else l[k]
        if piv and piv[-1][0] == p:
            if (p == "H" and pr > piv[-1][2]) or (p == "L" and pr < piv[-1][2]):
                piv[-1] = (p, k, pr)
            continue
        piv.append((p, k, pr))
        if len(piv) < 3:
            continue
        (_, ia, pa), (_, ib, pb), (tc, ic, pc) = piv[-3:]
        mi, mp = (ib + ic) / 2, (pb + pc) / 2
        slope = (mp - pa) / (mi - ia)
        med = pa + slope * (t - ia)
        if tc == "L" and slope > 0 and pc > pa and c[t] < med:
            out.append((t, 1))
        elif tc == "H" and slope < 0 and pc < pa and c[t] > med:
            out.append((t, -1))
    return out


def all_signals(s: dict) -> dict:
    bpr, ifvg = sig_fvg(s)
    bos, choch = sig_smc(s)
    return {"BPR": bpr, "IFVG": ifvg, "SMC_BOS": bos, "SMC_CHOCH": choch, "DAYE_WEEKLY": sig_daye(s),
            "CHANNEL_REG": sig_channel(s), "VP_POC": sig_vp(s), "FORK_PROXY": sig_fork(s)}


# ---------- 집계 ----------
def pool_all(s: dict, cost: float):
    """무작위 진입 벤치용: 모든 (t, 방향) 독립 진입 R (중첩 허용)."""
    res = {1: {}, -1: {}}
    for t in range(WARM, len(s["c"]) - 1):
        for d in (1, -1):
            r = simulate(s, t, d, cost)
            if r is not None:
                res[d][t] = r[0]
    return res


def stats(rs: np.ndarray) -> dict:
    n = len(rs)
    if n == 0:
        return {"n": 0}
    t, p = tstat(rs)
    return {"n": n, "win": float((rs > 0).mean()), "meanR": float(rs.mean()), "t": t, "p1": p}


def grade(i: dict, o: dict, bench_p: float, excess: float) -> str:
    if o["n"] < 30 or i["n"] < 30:
        return "검증전"
    ok_b = excess > 0 and bench_p < 0.10
    if o["p1"] < ALPHA_B and i["p1"] < ALPHA_B and ok_b and i["meanR"] > 0:
        return "A"
    if o["p1"] < ALPHA_B and ok_b:
        return "B"
    if o["p1"] < 0.10 and o["meanR"] > 0 and ok_b and i["meanR"] > 0:
        return "C"
    if o["p1"] > 0.90 and o["t"] < -1.3:
        return "F(역방향 경향)"
    return "F"


def main() -> int:
    data = load()
    rng = np.random.default_rng(SEED)
    dates = data["SPX"]["date"]
    cut = dates[WARM + int((len(dates) - WARM) * IS_FRAC)]
    print(f"IS<= {cut}, 기간 {dates[WARM]}~{dates[-1]}, α_B={ALPHA_B:.5f} (M={M})")
    trades = {r: [] for r in RULES}  # (market, series, date, t, d, R)
    pools = {}
    for k, s in data.items():
        cost = SERIES[k]
        mk = "KR" if cost > 0.003 else "US"
        sg = all_signals(s)
        for r in RULES:
            for t, d, R in run_signals(s, [x for x in sg[r] if x[0] >= WARM], cost):
                trades[r].append((mk, k, s["date"][t], d, R))
        pools[k] = pool_all(s, cost)
    res = {}
    for r in RULES:
        res[r] = {}
        for part in ("IS", "OOS"):
            sel = [x for x in trades[r] if (x[2] <= cut) == (part == "IS")]
            rs = np.array([x[4] for x in sel])
            st = stats(rs)
            # 무작위 벤치: 같은 시리즈·방향 구성으로 같은 기간 전 일자에서 무작위 추출
            cnt = {}
            for x in sel:
                cnt[(x[1], x[3])] = cnt.get((x[1], x[3]), 0) + 1
            means = []
            if cnt:
                cand = {}
                for (k, d) in cnt:
                    dd = data[k]["date"]
                    cand[(k, d)] = np.array([v for t, v in pools[k][d].items() if (dd[t] <= cut) == (part == "IS")])
                for _ in range(BENCH_REPS):
                    tot = []
                    for (k, d), m in cnt.items():
                        pool = cand[(k, d)]
                        if len(pool):
                            tot.append(rng.choice(pool, size=m, replace=True))
                    means.append(np.concatenate(tot).mean())
                means = np.array(means)
                st["bench_mean"] = float(means.mean())
                st["bench_p"] = float((means >= st["meanR"]).mean())
                st["excess"] = st["meanR"] - st["bench_mean"]
            res[r][part] = st
            for mk in ("US", "KR"):
                sm = [x[4] for x in sel if x[0] == mk]
                res[r][f"{part}_{mk}"] = stats(np.array(sm))
            res[r][f"{part}_long"] = stats(np.array([x[4] for x in sel if x[3] == 1]))
            res[r][f"{part}_short"] = stats(np.array([x[4] for x in sel if x[3] == -1]))
        i, o = res[r]["IS"], res[r]["OOS"]
        res[r]["grade"] = grade(i, o, o.get("bench_p", 1.0), o.get("excess", -1.0)) if o["n"] else "검증전"
    out = {"cut_IS_end": cut, "M": M, "alpha_bonferroni": ALPHA_B, "seed": SEED, "bench_reps": BENCH_REPS,
           "range": [dates[WARM], dates[-1]], "rules": res}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    for r in RULES:
        for part in ("IS", "OOS"):
            x = res[r][part]
            if x["n"]:
                print(f"{r:12s} {part:3s} n={x['n']:3d} 승률={x['win']:.2f} 평균R={x['meanR']:+.3f} t={x['t']:+.2f} p1={x['p1']:.3f} 벤치={x.get('bench_mean', float('nan')):+.3f} 벤치p={x.get('bench_p', float('nan')):.3f}")
            else:
                print(f"{r:12s} {part:3s} n=0")
        print(f"   → 등급 {res[r]['grade']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
