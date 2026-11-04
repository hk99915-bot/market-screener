"""TradingView 작성자 HDJ1 ICT·SMC 계열 스크립트 + Athena Boom° 일봉 Classic 사전등록 백테스트.

사전등록 문언은 docs/desk_kb/rounds/2026-11-05/quant_ict_hdj1.md §0 과 아래 RULES 가 같다(결과 보기 전 고정).
python3 scripts/study_ict_hdj1.py  → reports/studies/2026-11-05_ict_hdj1.json + docs/.../quant_ict_rules.json + 표준출력 표
데이터(일봉): SPX/NASDAQ = data/hist/us_*.parquet ^GSPC·^IXIC (~2025-12-31) + reports/macro_series.json 이후분,
KOSPI = data/deriv/daily.csv kospi_* (2010~). 체결: 신호 다음 날 시가. 손절 2×ATR14, 최대 10거래일, 왕복 비용 KR 0.45%·US 0.2%.
"""
from __future__ import annotations

import glob
import json
import math
import sys
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "reports" / "studies" / "2026-11-05_ict_hdj1.json"
RULES_OUT = ROOT / "docs" / "desk_kb" / "rounds" / "2026-11-05" / "quant_ict_rules.json"
IS_END = pd.Timestamp("2021-12-31")  # 사전등록: IS ≤ 2021-12-31 < OOS
ATR_N, STOP_ATR, HOLD = 14, 2.0, 10
COST = {"SPX": 0.002, "NASDAQ": 0.002, "KOSPI": 0.0045}
N_MIN_OOS = 30
ALPHA = 0.05
NRM = NormalDist()

RULES = {
    "R1_TurtleSoup": "Raschke 1995: 당일 저가가 직전 20일 최저가(L20, t-20..t-1)를 하회하고 L20 형성일이 ≥4봉 전이며 종가>L20 → 롱. 숏은 대칭(20일 고가).",
    "R2_CRT_PO3": "전일(C1) 저가를 하회 스윕했으나 종가는 C1 저가 위·C1 고가 아래(범위 안 복귀) → 롱. 한쪽만 스윕한 날만. 숏은 대칭.",
    "R3_SMT": "A지수 저가가 직전 20일 저가 갱신 & 상관지수 B 저가는 직전 20일 저가 미갱신 → 롱(고점 다이버전스는 숏). 쌍 SPX↔NASDAQ.",
    "R4_OTE": "fractal(3/3) 최근 확정 스윙 저점→고점 레그(≥3×ATR): 되돌림 62%에 닿고(저가≤고점−0.62R) 종가가 79% 선 위(≥고점−0.79R), 고점 후 ≤20봉, 레그당 1회 → 롱. 숏 대칭.",
    "R5_OrderBlock": "변위봉(양봉 몸통≥1.5×ATR14(t-1) & 종가>전일 고가) 직전 5봉 내 마지막 음봉을 OB로 두고, 이후 ≤10봉 내 첫 재진입(저가≤OB 고가 & 종가≥OB 저가) → 롱. OB 저가 종가 이탈 시 폐기. 숏 대칭.",
    "R6_CISD": "t-1까지 연속 음봉 런(길이≥2, 도지 건너뜀)의 첫 봉 시가(CISD 수준)를 t 종가가 엄격히 상향 돌파 → 롱. 숏 대칭.",
    "R7_BoS": "fractal(3/3) 최근 확정 스윙 고점을 종가가 처음 상향 돌파(Break of Structure) → 롱(추세 추종). 스윙 저점 하향 돌파 → 숏.",
    "R8_FVG_Retest": "3봉 갭 FVG(저가[t]>고가[t-2], 갭≥0.5×ATR) 형성 후 ≤10봉 내 첫 재진입(저가≤갭 상단 & 종가≥갭 하단) → 롱. 갭 하단 종가 이탈 시 폐기. 숏 대칭.",
    "R9_Boom_Daily": "Boom° Classic 일봉: C2=전일 저가 스윕 후 범위 안 종가 복귀 확정봉 b(양쪽 스윕이면 봉 색 방향); C3~C5=b+1..b+3 안에서 전일 저가 스윕일 s 이후 CISD(마지막 음봉 런 첫 봉 시가를 종가가 엄격히 상향) 확정 → 롱, 시퀀스당 1회, 새 C2 나오면 리셋. 숏 대칭. (LTF CISD 동반 유효조건은 일봉에 없어 생략)",
}
MARKETS = {"R3_SMT": ["SPX", "NASDAQ"]}
ALL_M = ["SPX", "NASDAQ", "KOSPI"]


def load_all() -> dict[str, pd.DataFrame]:
    h = pd.concat([pd.read_parquet(f) for f in sorted(glob.glob(str(ROOT / "data/hist/us_20*.parquet")))])
    mac = json.load(open(ROOT / "reports" / "macro_series.json"))["series"]
    out = {}
    for name, yf in (("SPX", "^GSPC"), ("NASDAQ", "^IXIC")):
        x = h[h.yf == yf][["date", "open", "high", "low", "close"]].copy()
        x["date"] = pd.to_datetime(x["date"])
        m = pd.DataFrame(mac[name], columns=["date", "open", "high", "low", "close", "v"]).drop(columns="v")
        m["date"] = pd.to_datetime(m["date"])
        ov = x.merge(m, on="date", suffixes=("", "_m"))
        rel = float(((ov["close"] / ov["close_m"]) - 1).abs().max()) if len(ov) else float("nan")
        assert rel < 1e-3, f"{name} hist/macro 종가 불일치 {rel}"
        out[name] = pd.concat([x, m[m.date > x.date.max()]]).drop_duplicates("date").sort_values("date").reset_index(drop=True)
    k = pd.read_csv(ROOT / "data/deriv/daily.csv", usecols=["date", "kospi_open", "kospi_high", "kospi_low", "kospi_close"])
    k.columns = ["date", "open", "high", "low", "close"]
    k["date"] = pd.to_datetime(k["date"])
    out["KOSPI"] = k.sort_values("date").reset_index(drop=True)
    for v in out.values():
        assert (v[["open", "high", "low", "close"]] > 0).all().all()
    return out


def prep(df: pd.DataFrame) -> dict:
    o, h, l, c = (df[x].to_numpy(float) for x in ("open", "high", "low", "close"))
    pc = np.r_[np.nan, c[:-1]]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    atr = pd.Series(tr).rolling(ATR_N).mean().to_numpy()
    return dict(o=o, h=h, l=l, c=c, atr=atr, d=df["date"].to_numpy(), n=len(df))


def fractals(P, k=3):
    """확정 시점(i+k)에 알려지는 fractal 스윙: dict conf_idx -> [(kind, idx, price)]."""
    h, l, n = P["h"], P["l"], P["n"]
    ev = {}
    for i in range(k, n - k):
        if h[i] > h[i - k:i].max() and h[i] > h[i + 1:i + k + 1].max():
            ev.setdefault(i + k, []).append(("H", i, h[i]))
        if l[i] < l[i - k:i].min() and l[i] < l[i + 1:i + k + 1].min():
            ev.setdefault(i + k, []).append(("L", i, l[i]))
    return ev


def run_start(o, c, i, down=True):
    """i 에서 거슬러 올라가며 연속 음봉(down=False 면 양봉) 런의 첫 봉 인덱스와 길이. 도지는 건너뜀."""
    j, first, cnt = i, None, 0
    while j >= 0:
        if (c[j] < o[j]) if down else (c[j] > o[j]):
            first, cnt = j, cnt + 1
        elif c[j] == o[j]:
            pass
        else:
            break
        j -= 1
    return first, cnt


def last_run_start(o, c, i, down=True, back=5):
    """i 이하에서 가장 가까운 (음|양)봉을 찾아(최대 back 봉) 그 런의 첫 봉 시가를 돌려준다."""
    for j in range(i, max(i - back - 1, -1), -1):
        if (c[j] < o[j]) if down else (c[j] > o[j]):
            f, cnt = run_start(o, c, j, down)
            return f
    return None


def sig_R1(P):
    h, l, c, n = P["h"], P["l"], P["c"], P["n"]
    out = []
    for t in range(21, n):
        w = l[t - 20:t]
        j = int(np.argmin(w))
        if l[t] < w[j] and c[t] > w[j] and (20 - j) >= 4:
            out.append((t, 1))
        w = h[t - 20:t]
        j = int(np.argmax(w))
        if h[t] > w[j] and c[t] < w[j] and (20 - j) >= 4:
            out.append((t, -1))
    return out


def crt_dir(P, t):
    h, l, c, o = P["h"], P["l"], P["c"], P["o"]
    lo, hi = l[t] < l[t - 1], h[t] > h[t - 1]
    if not (l[t - 1] < c[t] < h[t - 1]):
        return 0
    if lo and hi:
        return 1 if c[t] > o[t] else (-1 if c[t] < o[t] else 0)
    if lo:
        return 1
    if hi:
        return -1
    return 0


def sig_R2(P):
    out = []
    for t in range(1, P["n"]):
        if (P["l"][t] < P["l"][t - 1]) == (P["h"][t] > P["h"][t - 1]):
            continue  # 한쪽만 스윕한 날만
        d = crt_dir(P, t)
        if d:
            out.append((t, d))
    return out


def sig_R3(P, Q):
    l, h, ql, qh, n = P["l"], P["h"], Q["l"], Q["h"], P["n"]
    out = []
    for t in range(21, n):
        if l[t] < l[t - 20:t].min() and ql[t] >= ql[t - 20:t].min():
            out.append((t, 1))
        if h[t] > h[t - 20:t].max() and qh[t] <= qh[t - 20:t].max():
            out.append((t, -1))
    return out


def sig_R4(P):
    h, l, c, atr, n = P["h"], P["l"], P["c"], P["atr"], P["n"]
    ev = fractals(P)
    lastH = lastL = None
    used = set()
    out = []
    for t in range(n):
        for kind, i, px in ev.get(t, []):
            if kind == "H":
                lastH = (i, px)
            else:
                lastL = (i, px)
        if lastH is None or lastL is None or np.isnan(atr[t]):
            continue
        (ih, H), (il, L) = lastH, lastL
        R = abs(H - L)
        if il < ih and R >= 3 * atr[t] and t - ih <= 20 and t > ih and ("U", ih, il) not in used:
            if c[t] < L:
                used.add(("U", ih, il))
            elif l[t] <= H - 0.62 * R and c[t] >= H - 0.79 * R:
                used.add(("U", ih, il))
                out.append((t, 1))
        elif ih < il and R >= 3 * atr[t] and t - il <= 20 and t > il and ("D", ih, il) not in used:
            if c[t] > H:
                used.add(("D", ih, il))
            elif h[t] >= L + 0.62 * R and c[t] <= L + 0.79 * R:
                used.add(("D", ih, il))
                out.append((t, -1))
    return out


def _zone_retest(P, births):
    """births: {t: [(dir, zlo, zhi)]}. 이후 ≤10봉 내 첫 재진입을 신호로."""
    h, l, c, n = P["h"], P["l"], P["c"], P["n"]
    out, pend = [], []
    for t in range(n):
        keep = []
        for d, zlo, zhi, born in pend:
            if t - born > 10:
                continue
            if d == 1:
                if c[t] < zlo:
                    continue
                if l[t] <= zhi and c[t] >= zlo:
                    out.append((t, 1))
                    continue
            else:
                if c[t] > zhi:
                    continue
                if h[t] >= zlo and c[t] <= zhi:
                    out.append((t, -1))
                    continue
            keep.append((d, zlo, zhi, born))
        pend = keep
        for d, zlo, zhi in births.get(t, []):
            pend.append((d, zlo, zhi, t))
    return out


def sig_R5(P):
    o, h, l, c, atr, n = P["o"], P["h"], P["l"], P["c"], P["atr"], P["n"]
    births = {}
    for t in range(6, n):
        a = atr[t - 1]
        if np.isnan(a):
            continue
        if c[t] - o[t] >= 1.5 * a and c[t] > h[t - 1]:
            for j in range(t - 1, t - 6, -1):
                if c[j] < o[j]:
                    births.setdefault(t, []).append((1, l[j], h[j]))
                    break
        if o[t] - c[t] >= 1.5 * a and c[t] < l[t - 1]:
            for j in range(t - 1, t - 6, -1):
                if c[j] > o[j]:
                    births.setdefault(t, []).append((-1, l[j], h[j]))
                    break
    return _zone_retest(P, births)


def sig_R6(P):
    o, c, n = P["o"], P["c"], P["n"]
    out = []
    for t in range(3, n):
        f, cnt = run_start(o, c, t - 1, True)
        if f is not None and cnt >= 2 and c[t] > o[f]:
            out.append((t, 1))
        f, cnt = run_start(o, c, t - 1, False)
        if f is not None and cnt >= 2 and c[t] < o[f]:
            out.append((t, -1))
    return out


def sig_R7(P):
    c, n = P["c"], P["n"]
    ev = fractals(P)
    lastH = lastL = None
    brokeH = brokeL = True
    out = []
    for t in range(n):
        for kind, i, px in ev.get(t, []):
            if kind == "H":
                lastH, brokeH = (i, px), False
            else:
                lastL, brokeL = (i, px), False
        if lastH and not brokeH and c[t] > lastH[1]:
            brokeH = True
            out.append((t, 1))
        if lastL and not brokeL and c[t] < lastL[1]:
            brokeL = True
            out.append((t, -1))
    return out


def sig_R8(P):
    h, l, atr, n = P["h"], P["l"], P["atr"], P["n"]
    births = {}
    for t in range(2, n):
        a = atr[t]
        if np.isnan(a):
            continue
        if l[t] > h[t - 2] and l[t] - h[t - 2] >= 0.5 * a:
            births.setdefault(t, []).append((1, h[t - 2], l[t]))
        if h[t] < l[t - 2] and l[t - 2] - h[t] >= 0.5 * a:
            births.setdefault(t, []).append((-1, h[t], l[t - 2]))
    return _zone_retest(P, births)


def sig_R9(P):
    o, h, l, c, n = P["o"], P["h"], P["l"], P["c"], P["n"]
    out = []
    bias, b, swept, done = 0, None, False, False
    for t in range(2, n):
        d = crt_dir(P, t) if (l[t] < l[t - 1] or h[t] > h[t - 1]) else 0
        if d:  # 새 C2 확정 → 시퀀스 (재)시작
            bias, b, swept, done = d, t, False, False
            continue
        if bias == 0 or done or t - b > 3:
            continue
        if bias == 1:
            swept = swept or l[t] < l[t - 1]
            if swept:
                f = last_run_start(o, c, t, True)
                if f is not None and c[t] > o[f]:
                    out.append((t, 1))
                    done = True
        else:
            swept = swept or h[t] > h[t - 1]
            if swept:
                f = last_run_start(o, c, t, False)
                if f is not None and c[t] < o[f]:
                    out.append((t, -1))
                    done = True
    return out


def trade(P, t, d, cost):
    """신호일 t 종가 후 t+1 시가 진입. 반환 (entry_idx, exit_idx, R_net) 또는 None."""
    n, o, h, l, c, atr = P["n"], P["o"], P["h"], P["l"], P["c"], P["atr"]
    e = t + 1
    if e >= n or np.isnan(atr[t]):
        return None
    ep, risk = o[e], STOP_ATR * atr[t]
    stop = ep - d * risk
    last = min(e + HOLD - 1, n - 1)
    xp, xi = c[last], last
    for j in range(e, last + 1):
        if j > e and ((d == 1 and o[j] <= stop) or (d == -1 and o[j] >= stop)):  # 보유 중 시가 갭이 손절을 넘으면 시가 체결
            xp, xi = o[j], j
            break
        if (d == 1 and l[j] <= stop) or (d == -1 and h[j] >= stop):
            xp, xi = stop, j
            break
    return e, xi, d * (xp - ep) / risk - cost * ep / risk


def bench(P, cost):
    """무작위(매일) 진입 벤치: 방향별 모든 진입일 평균 R (같은 손절·보유·비용), 기간 IS/OOS 별."""
    res = {}
    dates = pd.to_datetime(P["d"])
    for d in (1, -1):
        rs = {"IS": [], "OOS": []}
        for t in range(ATR_N, P["n"] - 1):
            x = trade(P, t, d, cost)
            if x:
                rs["IS" if dates[x[0]] <= IS_END else "OOS"].append(x[2])
        res[d] = {k: float(np.mean(v)) for k, v in rs.items()}
    return res


def run_rule(P, sigs, cost, bm):
    dates = pd.to_datetime(P["d"])
    ss = sorted(set(sigs))
    sset = set(ss)
    busy, rows = -1, []
    for t, d in ss:
        if (t, -d) in sset or t + 1 <= busy:  # 같은 날 양방향 신호 제외·포지션 중 중복 금지
            continue
        x = trade(P, t, d, cost)
        if not x:
            continue
        e, xi, r = x
        busy = xi
        per = "IS" if dates[e] <= IS_END else "OOS"
        rows.append((per, d, r, r - bm[d][per]))
    return rows


def stats(rows, per):
    sel = [x for x in rows if per == "ALL" or x[0] == per]
    r = np.array([x[2] for x in sel])
    ex = np.array([x[3] for x in sel])
    n = len(r)
    if n < 3:
        return dict(n=n, win=None, avgR=None, excess=None, t_ex=None, p1=None, t_R=None)
    se = r.std(ddof=1) / math.sqrt(n)
    t_ex = float(ex.mean() / se) if se > 0 else 0.0
    t_r = float(r.mean() / se) if se > 0 else 0.0
    return dict(n=n, win=float((r > 0).mean()), avgR=float(r.mean()), excess=float(ex.mean()),
                t_ex=t_ex, p1=float(1 - NRM.cdf(t_ex)), t_R=t_r)


def grade(isx, oos, pool, alpha_b):
    """사전등록 등급: 검증전(OOS n<30) · A(OOS 초과 p≤α/N & IS 초과>0 & OOS 평균R>0) · B(전체 p≤α/N & OOS 초과>0) · C(OOS p<0.10 & IS 초과>0) · F."""
    if oos["n"] < N_MIN_OOS or oos["p1"] is None:
        return "검증전"
    if oos["p1"] <= alpha_b and isx["excess"] is not None and isx["excess"] > 0 and oos["avgR"] > 0:
        return "A"
    if pool["p1"] is not None and pool["p1"] <= alpha_b and oos["excess"] > 0:
        return "B"
    if oos["p1"] < 0.10 and isx["excess"] is not None and isx["excess"] > 0:
        return "C"
    return "F"


def main() -> int:
    data = load_all()
    P = {k: prep(v) for k, v in data.items()}
    gen = {"R1_TurtleSoup": sig_R1, "R2_CRT_PO3": sig_R2, "R4_OTE": sig_R4, "R5_OrderBlock": sig_R5,
           "R6_CISD": sig_R6, "R7_BoS": sig_R7, "R8_FVG_Retest": sig_R8, "R9_Boom_Daily": sig_R9}
    hyps = [(r, m) for r in gen for m in ALL_M] + [("R3_SMT", m) for m in MARKETS["R3_SMT"]]
    N = len(hyps)
    alpha_b = ALPHA / N
    bms = {m: bench(P[m], COST[m]) for m in ALL_M}
    res = []
    for r, m in hyps:
        sg = sig_R3(P[m], P["NASDAQ" if m == "SPX" else "SPX"]) if r == "R3_SMT" else gen[r](P[m])
        rows = run_rule(P[m], sg, COST[m], bms[m])
        isx, oos, pool = stats(rows, "IS"), stats(rows, "OOS"), stats(rows, "ALL")
        longs = sum(1 for x in rows if x[1] == 1)
        res.append(dict(rule=r, market=m, n_long=longs, n_short=len(rows) - longs, IS=isx, OOS=oos, ALL=pool,
                        grade=grade(isx, oos, pool, alpha_b)))
    out = dict(
        asof="2026-11-04", n_hypotheses=N, alpha=ALPHA, alpha_bonf=alpha_b, is_end=str(IS_END.date()),
        cost=COST, atr_n=ATR_N, stop_atr=STOP_ATR, hold=HOLD, n_min_oos=N_MIN_OOS,
        data_range={m: [str(data[m].date.min().date()), str(data[m].date.max().date()), len(data[m])] for m in ALL_M},
        bench={m: {str(d): v for d, v in bms[m].items()} for m in ALL_M},
        results=res,
        prereg=dict(m=N, alpha_bonf=alpha_b, is_end=str(IS_END.date()), cost=COST),
        grades={f"{x['rule']}|{x['market']}": x["grade"] for x in res},
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    RULES_OUT.parent.mkdir(parents=True, exist_ok=True)
    RULES_OUT.write_text(json.dumps(dict(
        source="퀀트 데스크 scripts/study_ict_hdj1.py", n_hypotheses=N,
        rules=[dict(name=r, definition=RULES[r], markets=MARKETS.get(r, ALL_M)) for r in RULES]),
        ensure_ascii=False, indent=1))
    print(f"N={N} alpha_b={alpha_b:.5f}  bench={out['bench']}")
    for x in res:
        f = lambda s: "n=%d" % s["n"] if s["avgR"] is None else "n=%d 승%.0f%% R%+.3f 초과%+.3f t%+.2f" % (s["n"], 100 * s["win"], s["avgR"], s["excess"], s["t_ex"])
        print(f"{x['rule']:15s}{x['market']:7s} IS[{f(x['IS'])}] OOS[{f(x['OOS'])}] -> {x['grade']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
