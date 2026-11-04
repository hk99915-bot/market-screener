#!/usr/bin/env python3
"""급락일 종가 매수(①) · 장중 5분류(②) · B1 구간 재확인(③) — 사전등록 reports/studies/2026-11-04_crash_close_intraday.md §0.

  python3 scripts/study_crash_close_intraday.py         # → reports/studies/2026-11-04_crash_close_intraday.json
  python3 scripts/study_crash_close_intraday.py --skip3  # ③(무거운 엔진) 생략

결과를 본 뒤 기준을 바꾸지 않는다(정의는 §0 커밋 1172c607d). 영향 범위: 연구 산출물만(다른 코드가 읽지 않음). 롤백: json 삭제.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SRC = ROOT / "data" / "deriv" / "daily.csv"
OUT = ROOT / "reports" / "studies" / "2026-11-04_crash_close_intraday.json"
KST = timezone(timedelta(hours=9))
IS_END = "2019-12-31"
COST, COST_HI = 0.0005, 0.0010
EXCL = {"2026-10-30", "2026-11-03"}
HOR = ("X0", "X1", "X2", "X5")
M1, M2, M3 = 4, 10, 2


def _betacf(a, b, x):
    tiny = 1e-300
    qab, qap, qam = a + b, a + 1, a - 1
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 300):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        dl = d * c
        h *= dl
        if abs(dl - 1.0) < 1e-12:
            break
    return h


def _betainc(a, b, x):
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    bt = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x))
    if x < (a + 1) / (a + b + 2):
        return bt * _betacf(a, b, x) / a
    return 1 - bt * _betacf(b, a, 1 - x) / b


class sps:  # scipy 미설치 환경용 최소 대체(검산: t(df=∞)→정규, 이항 합)
    class t:
        @staticmethod
        def cdf(t, df):
            x = df / (df + t * t)
            tail = 0.5 * _betainc(df / 2, 0.5, x)
            return 1 - tail if t > 0 else tail

        @staticmethod
        def sf(t, df):
            return sps.t.cdf(-t, df)

    class norm:
        @staticmethod
        def sf(z):
            return 0.5 * math.erfc(z / math.sqrt(2))

    class binom:
        @staticmethod
        def sf(k, n, p):  # P(X > k)
            return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k + 1, n + 1))


def load():
    rows = []
    with open(SRC, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                x = {"d": r["date"], "o": float(r["kospi_open"]), "c": float(r["kospi_close"])}
            except (TypeError, ValueError):
                continue
            for k in ("fut_open", "fut_close"):
                try:
                    x[k] = float(r[k])
                except (TypeError, ValueError):
                    x[k] = None
            rows.append(x)
    return rows


def t1(xs):
    """단측 H1 mean>0 t검정 → (n, mean, median, win, worst, t, p_gt, p_lt)."""
    a = np.asarray(xs, float)
    n = len(a)
    if n < 2:
        return {"n": n}
    mu, sd = a.mean(), a.std(ddof=1)
    t = mu / (sd / math.sqrt(n)) if sd > 0 else 0.0
    return {"n": n, "mean": round(float(mu), 5), "median": round(float(np.median(a)), 5), "win": round(float((a > 0).mean()), 3),
            "worst": round(float(a.min()), 5), "t": round(float(t), 2),
            "p_gt": round(float(sps.t.sf(t, n - 1)), 4), "p_lt": round(float(sps.t.cdf(t, n - 1)), 4)}


def grade1(all_, is_, oos, alpha):
    if all_.get("n", 0) < 8:
        return "검증전"
    if all_["p_gt"] < alpha:
        if is_.get("n", 0) >= 8 and oos.get("n", 0) >= 8 and is_["mean"] > 0 and oos["mean"] > 0 and is_["p_gt"] < 0.10 and oos["p_gt"] < 0.10:
            return "A"
        return "B"
    if all_["mean"] > 0 and all_["p_gt"] < 0.10:
        return "C"
    if all_["mean"] < 0 and all_["p_lt"] < 0.10:
        return "C(역방향)"
    return "F"


def down(g):
    return {"A": "B", "B": "C"}.get(g, g)


def study1(rows):
    n = len(rows)
    ev = []
    for i in range(1, n - 0):
        r = rows[i]["c"] / rows[i - 1]["c"] - 1
        if -0.05 <= r <= -0.03 and rows[i]["d"] not in EXCL:
            ev.append(i)
    # 비중첩: 직전 후보와 5거래일 이내면 군집 → 첫날만
    keep, prev = [], None
    for i in ev:
        if prev is None or i - prev > 5:
            keep.append(i)
        prev = i

    def rets(i, h, cost):
        e = rows[i]["c"]
        j = {"X0": (i + 1, "o"), "X1": (i + 1, "c"), "X2": (i + 2, "c"), "X5": (i + 5, "c")}[h]
        if j[0] >= n:
            return None
        return rows[j[0]][j[1]] / e - 1 - cost

    def uncond(h, cost):
        v = [rets(i, h, cost) for i in range(1, n)]
        return [x for x in v if x is not None]

    out = {"events_all": len(ev), "events_nonoverlap": len(keep), "dates_nonoverlap": [rows[i]["d"] for i in keep], "h": {}}
    alpha = 0.05 / M1
    for h in HOR:
        def sel(idx, cost=COST, cond=lambda d: True):
            return [x for i in idx if cond(rows[i]["d"]) for x in [rets(i, h, cost)] if x is not None]
        a, s, o = t1(sel(keep)), t1(sel(keep, cond=lambda d: d <= IS_END)), t1(sel(keep, cond=lambda d: d > IS_END))
        g = grade1(a, s, o, alpha)
        ex2020 = t1(sel(keep, cond=lambda d: not d.startswith("2020")))
        ex2026 = t1(sel(keep, cond=lambda d: not d.startswith("2026")))
        flip = any(x.get("mean", 0) * a.get("mean", 0) < 0 for x in (ex2020, ex2026))
        g_final = down(g) if flip else g
        ub = float(np.mean(uncond(h, COST)))
        res = {"all": a, "is": s, "oos": o, "ex2020": ex2020, "ex2026": ex2026, "grade_raw": g, "flip_by_robust": flip, "grade": g_final,
               "all_events_overlap": t1(sel(ev)), "cost10bp": t1(sel(keep, COST_HI)), "no_cost": t1(sel(keep, 0.0)),
               "uncond_mean_net": round(ub, 5), "excess_vs_uncond": round(a.get("mean", 0) - ub, 5) if a.get("mean") is not None else None}
        # K200F 실가격 구간(보조)
        fv = []
        for i in keep:
            if rows[i]["fut_close"] and i + 1 < n and rows[i + 1]["fut_open"]:
                j = {"X0": (i + 1, "fut_open"), "X1": (i + 1, "fut_close"), "X2": (i + 2, "fut_close"), "X5": (i + 5, "fut_close")}[h]
                if j[0] < n and rows[j[0]][j[1]]:
                    fv.append(rows[j[0]][j[1]] / rows[i]["fut_close"] - 1 - COST)
        res["k200f_actual"] = t1(fv) if len(fv) > 1 else {"n": len(fv)}
        out["h"][h] = res
    return out


def hac_diff(y, x, lag):
    """y = a + b x + e, b 의 Newey-West(Bartlett) 양측 z."""
    n = len(y)
    X = np.column_stack([np.ones(n), x])
    XtXi = np.linalg.inv(X.T @ X)
    beta = XtXi @ X.T @ y
    e = y - X @ beta
    Xe = X * e[:, None]
    S = Xe.T @ Xe
    for L in range(1, lag + 1):
        w = 1 - L / (lag + 1)
        G = Xe[L:].T @ Xe[:-L]
        S += w * (G + G.T)
    V = XtXi @ S @ XtXi
    se = math.sqrt(V[1, 1])
    z = beta[1] / se if se > 0 else 0.0
    return float(beta[1]), float(z), float(2 * sps.norm.sf(abs(z)))


def study2():
    import hf_intraday_pattern as hp
    tab = hp.table(hp.load())
    kinds = ("전강후약", "전약후강", "강세 지속", "약세 지속", "혼조")
    alpha = 0.05 / M2
    out = {"alpha": alpha, "cells": {}, "explore_vs_honjo": {}}
    for key, lag in (("next_ret", 1), ("ret5", 4)):
        for k in kinds:
            cell = {}
            for nm, f in (("all", lambda d: True), ("is", lambda d: d <= IS_END), ("oos", lambda d: d > IS_END)):
                xs = [x for x in tab if key in x and f(x["d"])]
                y = np.array([x[key] for x in xs])
                d = np.array([1.0 if x["type"] == k else 0.0 for x in xs])
                if d.sum() < 5:
                    cell[nm] = {"n_k": int(d.sum())}
                    continue
                b, z, p = hac_diff(y, d, lag)
                cell[nm] = {"n_k": int(d.sum()), "n": len(y), "diff": round(b, 5), "mean_k": round(float(y[d == 1].mean()), 5), "z": round(z, 2), "p": round(p, 4)}
            a, s, o = cell["all"], cell["is"], cell["oos"]
            if "p" not in a:
                g = "검증전"
            elif a["p"] < alpha:
                same = "p" in s and "p" in o and np.sign(s["diff"]) == np.sign(o["diff"])
                g = "A" if same and s["p"] < 0.10 and o["p"] < 0.10 else "B"
                if "p" in s and "p" in o and np.sign(s["diff"]) != np.sign(o["diff"]):
                    g = "C"  # 사전 규칙: IS·OOS 반대부호면 최대 C
            elif a["p"] < 0.10:
                g = "C"
            else:
                g = "F"
            cell["grade"] = g
            out["cells"][f"{k}|{key}"] = cell
    # 탐색: k − 혼조 (m 밖, 상한 C)
    for key in ("next_ret", "ret5"):
        for k in kinds[:4]:
            xs = [x for x in tab if key in x and x["type"] in (k, "혼조")]
            y = np.array([x[key] for x in xs])
            d = np.array([1.0 if x["type"] == k else 0.0 for x in xs])
            b, z, p = hac_diff(y, d, 1 if key == "next_ret" else 4)
            out["explore_vs_honjo"][f"{k}|{key}"] = {"diff": round(b, 5), "p": round(p, 4), "grade_cap": "C"}
    ng = [x for x in tab if "next_gap" in x]
    out["n_days"] = len(tab)
    return out


def net_dates(E, market, st, split_unused=None):
    O, Hh, L, Cw, cost, ok, _ = st.to_r(E, "struct", market)
    res, k1, hit2 = st.scale_out(O, Hh, L, Cw, 1.5, 3.0)
    return res - cost, E["date"][ok]


def study3():
    import study_alpha_sources as sa
    import study_tradeplan as st
    kb, krs, khi = sa.hyp_price("KR", 10, False)
    r = {}
    sig = sa.run_cell(khi, "KR", "2020-01-01")
    base = sa.run_cell(kb, "KR", "2020-01-01")
    r["repro"] = {"train_abs": sig["train"]["ev_r"], "test_abs": sig["test"]["ev_r"],
                  "train_ex": sa.excess(sig["train"], base["train"])["ex"], "test_ex": sa.excess(sig["test"], base["test"])["ex"],
                  "orig": {"train_abs": -0.032, "test_abs": 0.083, "train_ex": 0.043, "test_ex": 0.098}}
    r["repro"]["ok"] = all(abs(r["repro"][a] - r["repro"]["orig"][a]) <= 0.003 for a in ("train_abs", "test_abs", "train_ex", "test_ex"))
    ns, ds = net_dates(khi, "KR", st)
    nb, db = net_dates(kb, "KR", st)
    yrs = {}
    for y in range(2010, 2026):
        ms = (ds >= np.datetime64(f"{y}-01-01")) & (ds < np.datetime64(f"{y + 1}-01-01"))
        mb = (db >= np.datetime64(f"{y}-01-01")) & (db < np.datetime64(f"{y + 1}-01-01"))
        if ms.sum() and mb.sum():
            yrs[y] = {"n_sig": int(ms.sum()), "abs": round(float(ns[ms].mean()), 4), "base": round(float(nb[mb].mean()), 4),
                      "excess": round(float(ns[ms].mean() - nb[mb].mean()), 4)}
    r["by_year"] = yrs
    ex = np.array([v["excess"] for v in yrs.values()])
    npos, ny = int((ex > 0).sum()), len(ex)
    r["H3a"] = {"pos_years": npos, "years": ny, "p": round(float(sps.binom.sf(npos - 1, ny, 0.5)), 4)}
    ex2 = np.array([v["excess"] for y, v in yrs.items() if y not in (2020, 2021)])
    tt = float(ex2.mean() / (ex2.std(ddof=1) / math.sqrt(len(ex2)))) if len(ex2) > 1 else 0.0
    r["H3b"] = {"mean_excess_ex2020_21": round(float(ex2.mean()), 4), "years": len(ex2), "t": round(tt, 2), "p": round(float(sps.t.sf(tt, len(ex2) - 1)), 4),
                "excess_2020_21_only": round(float(np.mean([yrs[y]["excess"] for y in (2020, 2021) if y in yrs])), 4)}
    a_ok, b_ok = r["H3a"]["p"] < 0.025, r["H3b"]["p"] < 0.025
    r["verdict"] = ("B 유지(체제 비의존)" if a_ok and b_ok else "C 상한(체제 의존/부분 통과)")
    r["verdict_raw"] = {"H3a_pass": a_ok, "H3b_pass": b_ok}
    r["abs_pos_years"] = int(sum(v["abs"] > 0 for v in yrs.values()))
    return r


def other_sources():
    """기존 연구 json 에서 등급 A/B(통과) 셀을 목록으로만 옮긴다(새 검정 아님)."""
    found = []
    for name in ("2026-10-21_alpha_sources", "2026-10-21_hf_desk_signals", "2026-10-21_hf_classics", "2026-10-21_hf_ls_vol"):
        p = ROOT / "reports" / "studies" / f"{name}.json"
        if not p.exists():
            continue
        d = json.loads(p.read_text(encoding="utf-8"))

        def walk(o, path):
            if isinstance(o, dict):
                g = o.get("grade")
                if isinstance(g, str) and g[:1] in ("A", "B") and "(역" not in g:
                    found.append({"study": name, "path": path, "grade": g, "desc": str(o.get("desc") or o.get("name") or "")[:60]})
                for k, v in o.items():
                    walk(v, f"{path}/{k}")
            elif isinstance(o, list):
                for i, v in enumerate(o):
                    walk(v, f"{path}[{i}]")
        walk(d, "")
    return found


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip3", action="store_true")
    a = ap.parse_args(argv)
    rows = load()
    out = {"v": 1, "asof": str(datetime.now(KST).date()), "generated_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M KST"),
           "study": "2026-11-04_crash_close_intraday", "prereg": "reports/studies/2026-11-04_crash_close_intraday.md §0 (커밋 1172c607d)",
           "m": M1 + M2 + M3, "m_by": {"1": M1, "2": M2, "3": M3}, "alpha_bonf": {"1": 0.05 / M1, "2": 0.05 / M2, "3": 0.05 / M3},
           "is_end": IS_END, "cost": {"round_trip": COST, "sens": COST_HI, "note": "[가정] K200F 왕복"}, "topic": "crash_entry",
           "data_end": rows[-1]["d"]}
    out["prereg"] = {"commit": "1172c607d", "m": M1 + M2 + M3, "alpha_bonf": round(0.05 / (M1 + M2 + M3), 5), "is_end": IS_END,
                     "cost": COST, "sub": {"1": {"m": M1, "alpha": 0.05 / M1}, "2": {"m": M2, "alpha": 0.05 / M2}, "3": {"m": M3, "alpha": 0.05 / M3}},
                     "note": "등급은 소연구별 m 의 α 로 판정(사전등록). 전체 m=16 의 α 0.00313 을 써도 통과 건수는 0(① ②)이라 등급 불변; ③ H3a·H3b p 0.0021·0.0051 중 H3b 는 0.00313 미달"}
    out["survivorship"] = "① ② 지수 데이터라 생존편향 해당 없음 · ③ B1 은 2010~2025 현재 상장·유동 필터 종목(원 연구와 동일 유니버스, 상폐 종목 누락 가능 → 절대 E[R] 낙관)"
    out["dsr"] = "비해당 — ① 은 F(채택 대상 아님), ② 기술 차이 검정, ③ 은 기존 소스 재확인(DSR 미계산, 연도 단위 t 만)"
    out["s1"] = study1(rows)
    out["s2"] = study2()
    if not a.skip3:
        out["s3"] = study3()
    out["s3_other_sources_listed"] = other_sources()
    out["grades"] = {f"1_{h}": out["s1"]["h"][h]["grade"] for h in HOR} | {f"2_{k}": v["grade"] for k, v in out["s2"]["cells"].items()}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("wrote", OUT)
    return out


if __name__ == "__main__":
    main()
