"""급락 뒤 진입 신호 검증 — reports/studies/entry_signals.md §0 사전 등록 그대로.

python scripts/study_entry_signals.py  → reports/studies/entry_signals.json (+ 표준출력 요약)
데이터: data/deriv/daily.csv (코스피 종가 + 외국인 현물 순매수, 2010~)
"""
from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CSV = ROOT / "data" / "deriv" / "daily.csv"
OUT = ROOT / "reports" / "studies" / "entry_signals.json"

GAP = 20            # 이벤트 비중첩 거래일
WIN = 20            # 신호 탐색창 t0+1..t0+WIN
EXIT = 40           # 공통 청산 t0+EXIT
HS = (5, 10, 20)
FAKE = -0.05
IS_END = "2018-12-31"
TESTED = ["A", "B", "B2", "C", "E", "F"]
M = len(TESTED)
ALPHA_B = 0.05 / M
MIN_N = 8
SIGNAL_TYPES = ["B", "B2", "C", "E", "A"]
ORDER = ["D", "D0", "A", "B", "B2", "C", "E", "F"]
NAMES = {"D": "대조군: 5일 고점 + 외국인 2일", "D0": "5일 고점만", "A": "단계 진입 1/3·1/3·1/3",
         "B": "저점 +3%", "B2": "저점 +3% + 외국인 1일", "C": "20일선 회복", "E": "5일선 회복", "F": "급락일 종가"}


def t_cdf(t: float, df: int) -> float:
    """스튜던트 t 누적분포 (정규화 불완전 베타, 연분수)."""
    if not np.isfinite(t):
        return float("nan")
    x = df / (df + t * t)
    a, b = df / 2, 0.5

    def betacf(a, b, x):
        qab, qap, qam = a + b, a + 1, a - 1
        c, d = 1.0, 1 - qab * x / qap
        d = 1 / (d if abs(d) > 1e-30 else 1e-30)
        h = d
        for m in range(1, 200):
            m2 = 2 * m
            aa = m * (b - m) * x / ((a + m2 - 1) * (a + m2))
            d = 1 + aa * d; d = 1 / (d if abs(d) > 1e-30 else 1e-30)
            c = 1 + aa / c if abs(c) > 1e-30 else 1 + aa / 1e-30
            h *= d * c
            aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
            d = 1 + aa * d; d = 1 / (d if abs(d) > 1e-30 else 1e-30)
            c = 1 + aa / c if abs(c) > 1e-30 else 1 + aa / 1e-30
            de = d * c
            h *= de
            if abs(de - 1) < 1e-12:
                break
        return h

    lbeta = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    bt = math.exp(a * math.log(x) + b * math.log(1 - x) - lbeta)
    ib = bt * betacf(a, b, x) / a if x < (a + 1) / (a + b + 2) else 1 - bt * betacf(b, a, 1 - x) / b
    return 1 - 0.5 * ib if t > 0 else 0.5 * ib


def paired(d: np.ndarray) -> dict:
    d = d[np.isfinite(d)]
    n = len(d)
    if n < 2:
        return {"n": n, "mean": float(d.mean()) if n else None, "t": None, "p": None}
    sd = d.std(ddof=1)
    t = d.mean() / (sd / math.sqrt(n)) if sd > 0 else float("nan")
    return {"n": n, "mean": float(d.mean()), "t": float(t), "p": float(1 - t_cdf(t, n - 1)) if np.isfinite(t) else None}


def load() -> pd.DataFrame:
    df = pd.read_csv(CSV, usecols=["date", "kospi_close", "spot_frgn"]).dropna(subset=["kospi_close"]).reset_index(drop=True)
    c = df.kospi_close
    df["ret1"] = c.pct_change()
    df["dd20"] = c / c.rolling(21, min_periods=1).max() - 1
    df["sma5"] = c.rolling(5).mean()
    df["sma20"] = c.rolling(20).mean()
    df["sma200"] = c.rolling(200).mean()
    df["hi5"] = c.rolling(5).max()
    return df


def events(df: pd.DataFrame, cond: pd.Series) -> list[int]:
    out, last = [], -10**9
    for i in np.flatnonzero(cond.values):
        if i - last > GAP and i + EXIT < len(df):
            out.append(int(i)); last = i
        elif i - last > GAP:          # 청산일이 데이터 끝을 넘음 → 분석 제외하지만 중첩 기준엔 반영
            last = i
    return out


def first_fire(df, t0, rule) -> int | None:
    c, f = df.kospi_close.values, df.spot_frgn.values
    for s in range(t0 + 1, t0 + WIN + 1):
        lo = c[t0:s + 1].min()
        ok = {
            "D0": c[s] >= df.hi5.values[s],
            "D": c[s] >= df.hi5.values[s] and f[s - 1] > 0 and f[s] > 0,
            "B": c[s] >= lo * 1.03,
            "B2": c[s] >= lo * 1.03 and f[s] > 0,
            "C": c[s] > df.sma20.values[s],
            "E": c[s] > df.sma5.values[s],
        }[rule]
        if ok:
            return s
    return None


def tranches(df, t0, code) -> list[tuple[int | None, float]]:
    """[(진입 인덱스 또는 None=현금, 비중)]"""
    if code == "F":
        return [(t0, 1.0)]
    if code == "A":
        return [(t0, 1 / 3), (first_fire(df, t0, "E"), 1 / 3), (first_fire(df, t0, "C"), 1 / 3)]
    return [(first_fire(df, t0, code), 1.0)]


def measure(df, t0, code) -> dict:
    c = df.kospi_close.values
    tr = tranches(df, t0, code)
    filled = [(i, w) for i, w in tr if i is not None]
    wfill = sum(w for _, w in filled)
    # 공통 청산 (미진입 조각 0)
    r_common = sum(w * (c[t0 + EXIT] / c[i] - 1) for i, w in filled)
    trough, peak = c[t0:t0 + EXIT + 1].min(), c[t0:t0 + EXIT + 1].max()
    rec = {"t0": df.date.values[t0], "fired": bool(filled), "w_filled": wfill, "r_common": r_common,
           "bear": bool(c[t0] < df.sma200.values[t0]) if np.isfinite(df.sma200.values[t0]) else None}
    if not filled:
        return rec
    last = max(i for i, _ in filled)
    cost = sum(w * c[i] for i, w in filled) / wfill          # 가중 평균 진입가 (채운 조각 기준)
    rec.update({"entry": df.date.values[last], "wait": int(last - t0), "cost": cost,
                "prem_vs_f": cost / c[t0] - 1, "above_trough": cost / trough - 1,
                "used": max(0.0, (cost - trough) / (peak - trough)) if peak > trough else None})
    for h in HS:
        if last + h < len(c):
            # 수익은 자본 대비: 채운 조각 수익 × 비중 (현금 조각 0)
            rec[f"r{h}"] = wfill * (c[last + h] / cost - 1)
    if last + 20 < len(c):
        path = c[last + 1:last + 21]
        # 가짜 반등·최대낙폭은 마지막 조각 진입일 이후, 평균 진입가 기준
        rec["mdd20"] = float(path.min() / cost - 1)
        rec["fake"] = bool(rec["mdd20"] <= FAKE)
    return rec


def summarize(recs: list[dict]) -> dict:
    f = [r for r in recs if r["fired"]]
    out = {"events": len(recs), "fired": len(f)}
    if not f:
        return out
    for h in HS:
        x = np.array([r[f"r{h}"] for r in f if f"r{h}" in r])
        if len(x):
            win, loss = x[x > 0], x[x <= 0]
            out[f"r{h}"] = {"n": len(x), "avg": float(x.mean()), "med": float(np.median(x)), "win": float((x > 0).mean()),
                           "pl": float(win.mean() / abs(loss.mean())) if len(win) and len(loss) and loss.mean() < 0 else None,
                           "worst": float(x.min())}
    fk = [r["fake"] for r in f if "fake" in r]
    out["fake"] = float(np.mean(fk)) if fk else None
    out["mdd20"] = float(np.mean([r["mdd20"] for r in f if "mdd20" in r]))
    out["wait"] = float(np.mean([r["wait"] for r in f]))
    out["above_trough"] = float(np.mean([r["above_trough"] for r in f]))
    u = [r["used"] for r in f if r.get("used") is not None]
    out["used"] = float(np.mean(u)) if u else None
    out["prem_vs_f"] = float(np.mean([r["prem_vs_f"] for r in f]))
    rc = np.array([r["r_common"] for r in recs])
    out["r_common"] = {"avg": float(rc.mean()), "med": float(np.median(rc)), "win": float((rc > 0).mean())}
    return out


def diff_tests(per: dict, ref: str, sel) -> dict:
    out = {}
    for code in ORDER:
        if code == ref:
            continue
        d = np.array([a["r_common"] - b["r_common"] for a, b in zip(per[code], per[ref]) if sel(a)])
        out[code] = paired(d)
    return out


def run_set(df, idx) -> dict:
    per = {code: [measure(df, t0, code) for t0 in idx] for code in ORDER}
    is_ = lambda r: r["t0"] <= IS_END
    oos = lambda r: r["t0"] > IS_END
    bear = lambda r: r["bear"] is True
    res = {"n_events": len(idx), "dates": [df.date.values[i] for i in idx],
           "n_is": sum(1 for i in idx if df.date.values[i] <= IS_END),
           "n_bear": sum(1 for r in per["F"] if r["bear"]),
           "summary": {c: summarize(per[c]) for c in ORDER},
           "summary_oos": {c: summarize([r for r in per[c] if oos(r)]) for c in ORDER},
           "vs_D": {"all": diff_tests(per, "D", lambda r: True), "is": diff_tests(per, "D", is_),
                    "oos": diff_tests(per, "D", oos), "bear": diff_tests(per, "D", bear)},
           "vs_F": {"all": diff_tests(per, "F", lambda r: True), "oos": diff_tests(per, "F", oos)},
           "per_event": {c: per[c] for c in ORDER}}
    return res


def grade(res: dict, code: str) -> tuple[str, str]:
    fired = res["summary"][code]["fired"]
    if fired < MIN_N:
        return "검증전", f"발동 {fired}건 < {MIN_N}"
    base = res["vs_D"]["is" if res["n_is"] >= MIN_N else "all"][code]
    p, m = base["p"], base["mean"]
    io = [res["vs_D"][k][code]["mean"] for k in ("is", "oos")]
    br = res["vs_D"]["bear"][code]["mean"]
    if p is not None and p < ALPHA_B and m > 0:
        if all(x is not None and x > 0 for x in io) and br is not None and br > 0:
            return "A", f"Bonferroni 유의(p={p:.4f}) + IS·OOS·하락장 모두 +"
        return "B", f"Bonferroni 유의(p={p:.4f}), IS/OOS/하락장 일부 미확인"
    if p is not None and p < 0.10 and m > 0:
        return "C", f"방향만(p={p:.3f}, Bonferroni 미달)"
    return "F", f"대조군 대비 개선 없음(평균 {m*100:+.1f}%p, p={p if p is None else round(p, 3)})"


def main():
    df = load()
    primary = events(df, (df.dd20 <= -0.15) | (df.ret1 <= -0.05))
    sens = events(df, (df.ret1 <= -0.03) & (df.dd20 <= -0.10))
    P, S = run_set(df, primary), run_set(df, sens)
    grades = {c: dict(zip(("grade", "why"), grade(P, c))) for c in TESTED}
    rank = {"A": 4, "B": 3, "C": 2, "F": 0, "검증전": 0}
    sig = sorted(SIGNAL_TYPES, key=lambda c: (rank[grades[c]["grade"]], P["vs_D"]["all"][c]["mean"] or -9), reverse=True)
    best = sig[0]
    if rank[grades[best]["grade"]] >= 2:
        rec = {"pick": best, "why": f"신호형 최고 등급 {grades[best]['grade']}"}
    elif rank[grades["F"]["grade"]] >= 2:
        rec = {"pick": "F", "why": "신호형 모두 C 미만 → 급락일 종가(기다리지 않기) 유지"}
    else:
        rec = {"pick": "D", "why": "후보 모두 C 미만 → 대조군 유지"}
    # 현재(마지막 날) 각 신호 상태 — 참고용
    out = {"generated": datetime.now().strftime("%Y-%m-%d %H:%M"), "data": {"file": "data/deriv/daily.csv", "from": df.date.iloc[0], "to": df.date.iloc[-1]},
           "prereg": "reports/studies/entry_signals.md §0", "params": {"gap": GAP, "win": WIN, "exit": EXIT, "fake": FAKE, "is_end": IS_END, "m": M, "alpha_bonf": ALPHA_B, "min_n": MIN_N},
           "names": NAMES, "grades": grades, "recommend": rec, "primary": P, "sensitivity": S}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o)) + "\n", encoding="utf-8")

    def pct(x, d=1):
        return "—" if x is None else f"{x*100:+.{d}f}"
    for lab, R in (("주(−15%/−5%)", P), ("민감도(−3%&−10%)", S)):
        print(f"\n## {lab}: 이벤트 {R['n_events']} (IS {R['n_is']}, 하락장 {R['n_bear']})")
        print("코드 | 발동 | 대기 | r20 평균 | 중앙 | 승률 | 손익비 | 최악 | 가짜 | 저점대비 | 소진율 | 공통청산 | vsD 전체(p) | vsD IS | vsD OOS | vsD 하락장 | vsF")
        for c in ORDER:
            s = R["summary"][c]; r = s.get("r20", {})
            vd = R["vs_D"]
            g = lambda k: (vd[k][c]["mean"] if c != "D" else None)
            pa = vd["all"][c]["p"] if c != "D" else None
            vf = R["vs_F"]["all"][c]["mean"] if c != "F" else None
            print(f"{c} | {s['fired']}/{s['events']} | {s.get('wait', 0):.1f} | {pct(r.get('avg'))} | {pct(r.get('med'))} | {r.get('win', 0)*100:.0f}% | "
                  f"{r.get('pl') and round(r['pl'], 2)} | {pct(r.get('worst'))} | {pct(s.get('fake'), 0)} | {pct(s.get('above_trough'))} | {pct(s.get('used'), 0)} | "
                  f"{pct(s['r_common']['avg'])} | {pct(g('all'))} ({pa if pa is None else round(pa, 4)}) | {pct(g('is'))} | {pct(g('oos'))} | {pct(g('bear'))} | {pct(vf)}")
    print("\n등급:", {c: v["grade"] for c, v in grades.items()}, "→ 추천", rec)


if __name__ == "__main__":
    main()
