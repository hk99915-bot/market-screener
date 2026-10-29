#!/usr/bin/env python3
"""req-quant-ec93e2cb H1 첫 검정 — 60일 상위 5% 종목의 출발 시점 특징 P(상위5%|특징).

사전등록: docs/desk_kb/rounds/2026-10-29/quant_prereg_ec93e2cb.md §1 (결과 전 커밋). 이 스크립트는 H1-1·H1-2·H1-3·H1-7 만 실행
(가격·거래량만 필요). H1-4~6(수급·공시·리포트)는 이번 라운드 미실행. 문턱·격자·분할은 §1 그대로 — 결과를 보고 바꾸지 않는다.
  python3 scripts/study_winner_ex_ante.py   # 원자료를 reports/studies/2026-10-29_winner_ex_ante.raw.json 에 씀(최종 json 은 prereg·grades 를 덧붙여 수동 병합)
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from screener.prices import load_kr  # noqa: E402

OUT = ROOT / "reports" / "studies" / "2026-10-29_winner_ex_ante.json"
H = 60          # 보유(거래일)
STEP = 20       # 격자
M, ALPHA = 7, 0.05
SPLIT = "2020-01-01"
LAST_T0 = "2026-06-30"   # 최근 60일 오염 구간(t0>=2026-07-01) 제외
DOWN_YEARS = (2011, 2018, 2022)
COST = 0.0025


def nw_t(x: np.ndarray, lag: int = 2) -> tuple[float, float, float]:
    """평균, NW(Bartlett) t. 반환 (mean, se, t)."""
    x = x[~np.isnan(x)]
    n = len(x)
    if n < 3:
        return float("nan"), float("nan"), float("nan")
    mu = x.mean()
    e = x - mu
    v = (e @ e) / n
    for k in range(1, lag + 1):
        v += 2 * (1 - k / (lag + 1)) * (e[k:] @ e[:-k]) / n
    se = math.sqrt(max(v, 1e-18) / n)
    return float(mu), se, float(mu / se)


def p_one(t: float) -> float:
    return 0.5 * math.erfc(t / math.sqrt(2))   # 단측 p (정규 근사)


def main() -> None:
    d = load_kr(hist_from=2010)
    d = d.with_columns(pl.col("yf").str.slice(0, 6).alias("code"))
    # 보통주: 6자리 숫자·끝자리 0 (우선주 5/7/9/K, 신형 영문코드 ETF/ETN 등 제외) [가정: ETF·스팩은 이름 정보 없어 코드로만 거름]
    d = d.filter(pl.col("code").str.contains(r"^\d{5}0$"))
    dates = sorted(d["date"].unique().to_list())
    di = {x: i for i, x in enumerate(dates)}
    syms = sorted(d["yf"].unique().to_list())
    si = {s: i for i, s in enumerate(syms)}
    T, S = len(dates), len(syms)
    ii = d["date"].replace_strict(di, return_dtype=pl.Int32).to_numpy()
    jj = d["yf"].replace_strict(si, return_dtype=pl.Int32).to_numpy()

    def mat(col: str) -> np.ndarray:
        a = np.full((T, S), np.nan, dtype=np.float32)
        a[ii, jj] = d[col].to_numpy().astype(np.float32)
        return a

    close, high, vol = mat("close"), mat("high"), mat("volume")
    val = close * vol
    # 상폐: 마지막 종가로 청산(앞방향 채움) — 거래정지 구간도 같은 처리
    cf = pl.DataFrame(close).fill_nan(None).with_columns(pl.all().forward_fill()).to_numpy()
    cf = cf.astype(np.float32)
    ret1 = np.full_like(cf, np.nan)
    ret1[1:] = cf[1:] / cf[:-1] - 1
    nbars = np.cumsum(~np.isnan(close), axis=0)

    sector = {}
    try:
        for row in pl.read_csv(ROOT / "universe" / "kr_sector.csv", schema_overrides={"code": pl.String}).iter_rows():
            sector[row[0]] = row[1]
    except Exception:
        pass
    sec_of = np.array([sector.get(s[:6], "미분류") for s in syms])

    t0s = [i for i, x in enumerate(dates) if str(x) >= "2011-01-01" and str(x) <= LAST_T0]
    t0s = t0s[::STEP]
    t0s = [i for i in t0s if i + H < T]

    feats = ["H1-1", "H1-2", "H1-3"]
    rows = []   # 날짜별 집계
    sec_counts = {}   # (split, sector) -> [n, y]
    for i in t0s:
        px = cf[i]
        adv = np.nanmean(val[i - 19:i + 1], axis=0)
        elig = (~np.isnan(close[i])) & (adv >= 1e9) & (px >= 1000) & (nbars[i] >= 260)
        idx = np.where(elig)[0]
        if len(idx) < 200:
            continue
        r60 = cf[i + H, idx] / px[idx] - 1
        ok = ~np.isnan(r60)
        idx, r60 = idx[ok], r60[ok]
        n = len(idx)
        k = int(round(0.05 * n))
        order = np.argsort(r60)
        y_up = np.zeros(n, bool); y_up[order[-k:]] = True
        y_lo = np.zeros(n, bool); y_lo[order[:k]] = True
        f = {}
        hi250 = np.nanmax(high[i - 249:i + 1, idx], axis=0)
        f["H1-1"] = (px[idx] / hi250 - 1) <= -0.40
        sd = np.nanstd(ret1[i - 59:i + 1, idx], axis=0)
        f["H1-2"] = sd >= np.nanpercentile(sd, 80)
        v5 = np.nanmean(val[i - 4:i + 1, idx], axis=0)
        v60 = np.nanmean(val[i - 64:i - 4, idx], axis=0)
        f["H1-3"] = (v5 / np.where(v60 > 0, v60, np.nan)) >= 2
        split = "IS" if str(dates[i]) < SPLIT else "OOS"
        rec = {"date": str(dates[i]), "split": split, "n": n, "mean_r": float(r60.mean())}
        for name in feats:
            F = f[name]
            nf = int(F.sum())
            rec[name] = {
                "nF": nf,
                "n_up": int((F & y_up).sum()), "n_lo": int((F & y_lo).sum()), "k": k,
                "ex_mean": float(r60[F].mean() - r60.mean() - COST) if nf else None,
                "ex_med": float(np.median(r60[F]) - np.median(r60) - COST) if nf else None,
            }
        for s_, yv in zip(sec_of[idx], y_up):
            c = sec_counts.setdefault((split, s_), [0, 0]); c[0] += 1; c[1] += int(yv)
        rows.append(rec)

    res = {}
    for name in feats:
        out = {}
        for tag, sel in (("전체", lambda r: True), ("IS", lambda r: r["split"] == "IS"), ("OOS", lambda r: r["split"] == "OOS"),
                         ("하락연도", lambda r: int(r["date"][:4]) in DOWN_YEARS)):
            rr = [r for r in rows if sel(r) and r[name]["nF"] > 0]
            if not rr:
                continue
            up = np.array([r[name]["n_up"] / r[name]["nF"] - 0.05 for r in rr])
            lo = np.array([r[name]["n_lo"] / r[name]["nF"] - 0.05 for r in rr])
            mu, se, t = nw_t(up)
            mul, sel_, tl = nw_t(lo)
            nF = sum(r[name]["nF"] for r in rr)
            nu = sum(r[name]["n_up"] for r in rr)
            nl = sum(r[name]["n_lo"] for r in rr)
            kk = sum(r[name]["k"] for r in rr)
            exm = [r[name]["ex_mean"] for r in rr if r[name]["ex_mean"] is not None]
            exd = [r[name]["ex_med"] for r in rr if r[name]["ex_med"] is not None]
            out[tag] = {
                "dates": len(rr), "events_F": nF,
                "precision_up": nu / nF, "precision_lo": nl / nF,
                "lift_up": nu / nF / 0.05, "lift_lo": nl / nF / 0.05,
                "recall_up": nu / kk,
                "diff_mean": mu, "nw_t": t, "p_one": p_one(t),
                "diff_lo_mean": mul, "nw_t_lo": tl,
                "ex_mean_after_cost": float(np.mean(exm)), "ex_med_after_cost": float(np.mean(exd)),
            }
        res[name] = out

    # H1-7 업종 (사후 분류, 상한 C): 업종별 P(상위5%) 동일성 카이제곱 — 겹침으로 p 과대 유의 가능, 서술용
    h17 = {}
    for sp in ("IS", "OOS"):
        cells = {s_: v for (a, s_), v in sec_counts.items() if a == sp and v[0] >= 500}
        N = sum(v[0] for v in cells.values()); Yt = sum(v[1] for v in cells.values())
        p0 = Yt / N
        chi = sum((v[1] - v[0] * p0) ** 2 / (v[0] * p0 * (1 - p0)) for v in cells.values())
        top = sorted(((v[1] / v[0] / p0, s_, v[0]) for s_, v in cells.items()), reverse=True)
        h17[sp] = {"sectors": len(cells), "chi2": chi, "df": len(cells) - 1,
                   "top3_lift": [(s_, round(l, 2), n) for l, s_, n in top[:3]],
                   "bottom3_lift": [(s_, round(l, 2), n) for l, s_, n in top[-3:]]}
    res["H1-7"] = h17
    meta = {"t0_dates": len(rows), "first_t0": rows[0]["date"], "last_t0": rows[-1]["date"],
            "avg_eligible": float(np.mean([r["n"] for r in rows])), "symbols_total": S}
    json.dump({"meta": meta, "results": res}, open(OUT.with_suffix(".raw.json"), "w"), ensure_ascii=False, indent=1)
    print(json.dumps({"meta": meta, "results": res}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
