"""검증 데스크 독립 재현: rule_audit T4(반등일 매도 대기)·T5(하락장 노출 상한).

명세 = reports/studies/rule_audit.md §0-3 + reports/studies/replication_rule_audit.md §0(해석·허용오차).
원 코드(scripts/study_rule_audit.py)는 열지 않았다(kb:verify#8). 원값은 rule_audit.json 결과만 읽어 대조.

  python3 scripts/replicate_rule_audit.py            # 기본 창(~2026-10-15) + 민감도, json 저장
  python3 scripts/replicate_rule_audit.py --no-write # 출력만
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DAILY = ROOT / "data/deriv/daily.csv"
ORIG = ROOT / "reports/studies/rule_audit.json"
OUT = ROOT / "reports/studies/replication_rule_audit.json"
END_ORIG = "2026-10-15"
IS_END = "2018-12-31"
ALPHA = 0.05 / 18
COST_ONE_WAY = 0.00125


# ---------- 공통 ----------
def ttest(x) -> dict:
    """양측 1표본 t (ddof=1). p 는 t 분포(scipy 있으면) 아니면 정규 근사."""
    x = np.asarray([v for v in x if v is not None and not np.isnan(v)], float)
    n = len(x)
    if n < 2:
        return {"n": n, "mean": float(x.mean()) if n else float("nan"), "t": float("nan"), "p": float("nan")}
    m, sd = x.mean(), x.std(ddof=1)
    t = m / (sd / math.sqrt(n)) if sd > 0 else float("nan")
    try:
        from scipy import stats
        p = float(2 * stats.t.sf(abs(t), n - 1))
    except Exception:  # pragma: no cover
        p = math.erfc(abs(t) / math.sqrt(2))
    return {"n": n, "mean": float(m), "t": float(t), "p": p}


def grade(parts: dict, keys=("all", "is", "oos", "bear")) -> str:
    """원 §0-2 등급 규칙: A p<α & 부호 일치, B p<α, C p<0.10, F 그 외."""
    p = parts["all"]["p"]
    signs = {np.sign(parts[k]["mean"]) for k in keys if k in parts and parts[k]["n"] > 0}
    if p < ALPHA and len(signs) == 1:
        return "A"
    if p < ALPHA:
        return "B"
    if p < 0.10:
        return "C"
    return "F"


def load(end: str | None = END_ORIG) -> pd.DataFrame:
    df = pd.read_csv(DAILY, usecols=["date", "kospi_close"]).dropna()
    df = df.sort_values("date").reset_index(drop=True)
    if end:
        df = df[df["date"] <= end].reset_index(drop=True)
    return df


def sma(c: np.ndarray, w: int) -> np.ndarray:
    out = np.full(len(c), np.nan)
    cs = np.cumsum(np.insert(c, 0, 0.0))
    out[w - 1:] = (cs[w:] - cs[:-w]) / w
    return out


# ---------- T4 ----------
T4_VARIANTS = {"cur": 0.005, "imm": None, "th0": 0.0, "th1": 0.010}


def t4_events(dates, c, need: int = 10) -> list[int]:
    m20 = sma(c, 20)
    ev, last = [], -10**9
    for i in range(1, len(c)):
        if np.isnan(m20[i]) or np.isnan(m20[i - 1]):
            continue
        if c[i] < m20[i] and c[i - 1] > m20[i - 1] and i - last > 20:
            if i + need < len(c):
                ev.append(i)
            last = i  # 간격은 채택(=조건 충족) 이벤트 기준
    return ev


def t4_sale(c, i0, th):
    if th is None:
        return i0
    for k in range(1, 11):
        j = i0 + k
        if c[j] / c[j - 1] - 1 >= th:
            return j
    return i0 + 10


def simulate_t4(df: pd.DataFrame, need: int = 10, d_mode: str = "t0") -> dict:
    """need: 이벤트 완성 조건(t0+need 종가 존재). d_mode: 't0' = (대안−현행)/t0 종가(§0 기본),
    'cur' = 대안/현행 − 1(사후 — 원 숫자 모사용)."""
    dates, c = df["date"].to_numpy(), df["kospi_close"].to_numpy(float)
    m200 = sma(c, 200)
    ev = t4_events(dates, c, need)
    rows = []
    for i0 in ev:
        r = {"t0": str(dates[i0]), "is": dates[i0] <= IS_END,
             "bear": bool(not np.isnan(m200[i0]) and c[i0] < m200[i0])}
        for v, th in T4_VARIANTS.items():
            j = t4_sale(c, i0, th)
            r[v] = {"sale": c[j] / c[i0] - 1, "wait": j - i0,
                    "after5": c[j + 5] / c[j] - 1 if j + 5 < len(c) else np.nan,
                    "after20": c[j + 20] / c[j] - 1 if j + 20 < len(c) else np.nan}
        rows.append(r)
    summary = {}
    for v in T4_VARIANTS:
        s = np.array([r[v]["sale"] for r in rows])
        summary[v] = {"sale_vs_t0": float(s.mean()), "sale_med": float(np.median(s)),
                      "better_than_t0": float((s > 0).mean()),
                      "wait": float(np.mean([r[v]["wait"] for r in rows])),
                      "after5": float(np.nanmean([r[v]["after5"] for r in rows])),
                      "after20": float(np.nanmean([r[v]["after20"] for r in rows]))}
    cmp = {}
    for v in ("imm", "th0", "th1"):
        if d_mode == "cur":
            d = lambda sub: [(1 + r[v]["sale"]) / (1 + r["cur"]["sale"]) - 1 for r in rows if sub(r)]
        else:
            d = lambda sub: [r[v]["sale"] - r["cur"]["sale"] for r in rows if sub(r)]
        cmp[v] = {"all": ttest(d(lambda r: True)), "is": ttest(d(lambda r: r["is"])),
                  "oos": ttest(d(lambda r: not r["is"])), "bear": ttest(d(lambda r: r["bear"]))}
        cmp[v]["grade"] = grade(cmp[v])
    return {"n_events": len(rows), "n_is": sum(r["is"] for r in rows),
            "n_bear": sum(r["bear"] for r in rows), "summary": summary, "cmp": cmp,
            "dates": [r["t0"] for r in rows]}


# ---------- T5 ----------
T5_CAPS = {"cur": 0.5, "c0": 0.0, "c70": 0.7, "c100": 1.0}


def t5_path(c: np.ndarray, cap: float):
    """신호일 인덱스 199.. → 수익일 200.. 의 (노출, 순수익)."""
    m200 = sma(c, 200)
    start = 199
    sig_bear = c[start:-1] < m200[start:-1]          # 신호일 t
    e = np.where(sig_bear, cap, 1.0)                  # t+1 노출
    r = c[start + 1:] / c[start:-1] - 1
    prev = np.concatenate([[e[0]], e[:-1]])
    net = e * r - np.abs(e - prev) * COST_ONE_WAY
    return e, net, sig_bear


def t5_stats(e, net) -> dict:
    n = len(net)
    eq = np.cumprod(1 + net)
    vol = net.std(ddof=1) * math.sqrt(252)
    return {"cagr": float(eq[-1] ** (252 / n) - 1), "vol": float(vol),
            "sharpe": float(net.mean() * 252 / vol),
            "mdd": float((eq / np.maximum.accumulate(eq) - 1).min()),
            "turnover_yr": float(np.abs(np.diff(e)).sum() / (n / 252)),
            "avg_exposure": float(e.mean())}


def simulate_t5(df: pd.DataFrame, pad: bool = False, partial: bool = False) -> dict:
    """pad: 신호 첫날(수익 0)을 일수에 포함, partial: 마지막 불완전 블록 포함 — 둘 다 사후(원 숫자 모사용)."""
    dates, c = df["date"].to_numpy(), df["kospi_close"].to_numpy(float)
    paths = {k: t5_path(c, cap) for k, cap in T5_CAPS.items()}
    if pad:
        paths = {k: (np.concatenate([[p[0][0]], p[0]]), np.concatenate([[0.0], p[1]]),
                     np.concatenate([[p[2][0]], p[2]])) for k, p in paths.items()}
    ret_dates = dates[200 - int(pad):]
    n = len(ret_dates)
    nb = -(-n // 21) if partial else n // 21
    blk = {k: np.array([np.prod(1 + p[1][b * 21:(b + 1) * 21]) - 1 for b in range(nb)]) for k, p in paths.items()}
    bstart = np.array([ret_dates[b * 21] for b in range(nb)])
    sig = paths["cur"][2]
    bbear = np.array([sig[b * 21:(b + 1) * 21].mean() > 0.5 for b in range(nb)])
    isb = bstart <= IS_END
    cmp, bear_blocks = {}, {}
    for k in ("c0", "c70", "c100"):
        d = blk[k] - blk["cur"]
        cmp[k] = {"all": ttest(d), "is": ttest(d[isb]), "oos": ttest(d[~isb])}
        cmp[k]["grade"] = grade(cmp[k], keys=("all", "is", "oos"))
        bear_blocks[k] = ttest(d[bbear])
    return {"from": str(dates[199]), "first_ret": str(ret_dates[0]), "days": n, "blocks": nb,
            "blocks_is": int(isb.sum()), "bear_share": float(sig.mean()),
            "summary": {k: t5_stats(p[0], p[1]) for k, p in paths.items()},
            "cmp": cmp, "bear_blocks": bear_blocks}


# ---------- 대조 ----------
def _tol_mean(o):
    return max(0.0001, 0.5 * abs(o["mean"] / o["t"])) if o.get("t") else 0.0001


def compare(orig: dict, rep: dict) -> list[dict]:
    rows = []

    def add(item, o, r, tol, unit=""):
        rows.append({"item": item, "orig": o, "rep": r, "tol": tol,
                     "ok": bool(abs(r - o) <= tol + 1e-12), "unit": unit})

    o4, r4 = orig["T4"], rep["T4"]
    for k in ("n_events", "n_is", "n_bear"):
        add(f"T4 {k}", o4[k], r4[k], 2, "건")
    for v in ("cur", "imm", "th0", "th1"):
        os_, rs = o4["summary"][v], r4["summary"][v]
        add(f"T4 {v} 매도가/t0", os_["sale_vs_t0"], rs["sale_vs_t0"], 0.0009)
        if v != "imm":
            p, n = os_["better_than_t0"], o4["n_events"]
            add(f"T4 {v} t0보다 비싸게", p, rs["better_than_t0"], max(0.005, 0.5 * math.sqrt(p * (1 - p) / n)))
            add(f"T4 {v} 대기일", os_["wait"], rs["wait"], 0.2, "일")
        add(f"T4 {v} 매도 후 5일", os_["after5"], rs["after5"], 0.0009)
        add(f"T4 {v} 매도 후 20일", os_["after20"], rs["after20"], 0.0009)
    for v in ("imm", "th0", "th1"):
        for sub in ("all", "is", "oos", "bear"):
            o = o4["cmp"][v][sub]
            add(f"T4 d {v} {sub}", o["mean"], r4["cmp"][v][sub]["mean"], _tol_mean(o))
    o5, r5 = orig["T5"], rep["T5"]
    add("T5 일수", o5["days"], r5["days"], 2, "일")
    add("T5 블록 수", o5["cmp"]["c0"]["all"]["n"], r5["blocks"], 2, "개")
    tol5 = {"cagr": 0.002, "vol": 0.002, "sharpe": 0.02, "mdd": 0.01, "avg_exposure": 0.005}
    for v in T5_CAPS:
        for k, t in tol5.items():
            add(f"T5 {v} {k}", o5["summary"][v][k], r5["summary"][v][k], t)
        ot = o5["summary"][v]["turnover_yr"]
        add(f"T5 {v} turnover_yr", ot, r5["summary"][v]["turnover_yr"], max(0.05 * ot, 0.01), "회/년")
    for v in ("c0", "c70", "c100"):
        for sub in ("all", "is", "oos"):
            o = o5["cmp"][v][sub]
            add(f"T5 d {v} {sub}", o["mean"], r5["cmp"][v][sub]["mean"], _tol_mean(o))
    return rows


def grades_cmp(orig: dict, rep: dict) -> list[dict]:
    out = []
    for t, vs in (("T4", ("imm", "th0", "th1")), ("T5", ("c0", "c70", "c100"))):
        for v in vs:
            og = orig["grades"].get(f"{t}/{v}", {}).get("grade")
            rc = rep[t]["cmp"][v]
            out.append({"test": f"{t}/{v}", "orig_grade": og, "rep_grade": rc["grade"],
                        "orig_p": orig["grades"].get(f"{t}/{v}", {}).get("p"), "rep_p": rc["all"]["p"],
                        "same": og == rc["grade"]})
    return out


def run(end=END_ORIG, posthoc: bool = False) -> dict:
    """posthoc=False: §0 사전 고정 정의. True: 결과 본 뒤 찾은 원 정의 후보(t0+30 완성·대안/현행 비율·
    신호 첫날 포함·불완전 블록 포함) — 원인 확인용, 판정 기준 아님."""
    df = load(end)
    t4 = simulate_t4(df, need=30, d_mode="cur") if posthoc else simulate_t4(df)
    t5 = simulate_t5(df, pad=True, partial=True) if posthoc else simulate_t5(df)
    return {"T4": t4, "T5": t5, "window": [str(df["date"].iloc[0]), str(df["date"].iloc[-1])]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-write", action="store_true")
    a = ap.parse_args()
    orig = json.loads(ORIG.read_text())
    orig_r = {"T4": orig["results"]["T4"], "T5": orig["results"]["T5"], "grades": orig["grades"]}
    rep = run(END_ORIG)
    full = run(None)
    ph = run(END_ORIG, posthoc=True)
    ph_full = run(None, posthoc=True)
    ph_rows = compare(orig_r, ph)
    rows = compare(orig_r, rep)
    g = grades_cmp(orig_r, rep)
    g_full = grades_cmp(orig_r, full)
    for r in rows:
        print(f"{'OK ' if r['ok'] else 'XX '} {r['item']:<28} 원 {r['orig']:+.5f} 재현 {r['rep']:+.5f} 허용 {r['tol']:.5f}")
    for x in g:
        print("등급", x)
    print("민감도(~최신)", [(x["test"], x["rep_grade"], round(x["rep_p"], 4)) for x in g_full])
    res = {"generated_by": "scripts/replicate_rule_audit.py", "orig": "reports/studies/rule_audit.json",
           "window": rep["window"], "rows": rows, "grades": g,
           "n_ok": sum(r["ok"] for r in rows), "n_rows": len(rows),
           "rep": {"T4": {k: v for k, v in rep["T4"].items()}, "T5": rep["T5"]},
           "sensitivity_full": {"window": full["window"], "grades": g_full,
                                "T4_n": full["T4"]["n_events"], "T5_days": full["T5"]["days"]}}
    res["posthoc"] = {"note": "결과 본 뒤 원인 확인용(판정 기준 아님)", "n_ok": sum(r["ok"] for r in ph_rows),
                      "max_abs_diff_cmp": max(abs(r["rep"] - r["orig"]) for r in ph_rows if " d " in r["item"]),
                      "grades": grades_cmp(orig_r, ph), "grades_full": grades_cmp(orig_r, ph_full),
                      "T4_n": ph["T4"]["n_events"], "T5_days": ph["T5"]["days"], "T5_blocks": ph["T5"]["blocks"]}
    print(f"{res['n_ok']}/{res['n_rows']} 허용오차 안 · 사후 모사 {res['posthoc']['n_ok']}/{len(ph_rows)}, "
          f"cmp 최대 차 {res['posthoc']['max_abs_diff_cmp']:.2e}")
    print("사후 모사 ~최신", [(x["test"], x["rep_grade"], round(x["rep_p"], 4)) for x in res["posthoc"]["grades_full"]])
    if not a.no_write:
        OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float))
    return res


if __name__ == "__main__":
    main()
