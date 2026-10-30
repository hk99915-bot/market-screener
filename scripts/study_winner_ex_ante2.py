#!/usr/bin/env python3
"""req-quant-ec93e2cb H1 2차 검정 — H1-4(수급)·H1-6(목표가 상향). 사전등록 §1 그대로(문턱·격자·분할 불변, 결과 전 정의 고정).

H1-4: (외국인+기관합계) 20일 순매수 ÷ 시총(t0) 횡단면 상위 20%. data/flows 2022-01-03~, IS<2025-01 / OOS>=2025-01, 하락 구간 = 2022.
H1-6: 직전 20거래일(t0 포함) 안 같은 증권사·종목 목표가 상향(직전 목표가 대비 +) 1건 이상. data/research.parquet 2024-10-30~, IS<2025-10 / OOS>=2025-10.
H1-5(공시 영업이익 YoY): data/fin/full.parquet 에 접수일(rcept) 컬럼이 없어 '접수일 기준' 시점 원칙을 지킬 수 없음 → 미실행(검증전).
격자는 H1 1차와 동일(2011-01 첫 거래일부터 20거래일마다)에서 해당 데이터 기간만 취한다. 오염 구간(t0>=2026-07-01) 제외.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from screener.prices import load_kr  # noqa: E402
from study_winner_ex_ante import COST, H, LAST_T0, STEP, nw_t, p_one  # noqa: E402

OUT = ROOT / "reports" / "studies" / "2026-10-30_winner_ex_ante2.raw.json"
CFG = {"H1-4": ("2022-02-01", "2025-01-01", (2022,)), "H1-6": ("2024-12-01", "2025-10-01", ())}


def main() -> None:
    d = load_kr(hist_from=2010).with_columns(pl.col("yf").str.slice(0, 6).alias("code"))
    d = d.filter(pl.col("code").str.contains(r"^\d{5}0$"))
    dates = sorted(d["date"].unique().to_list())
    di = {x: i for i, x in enumerate(dates)}
    syms = sorted(d["yf"].unique().to_list())
    si = {s: i for i, s in enumerate(syms)}
    c2s = {}
    for s in syms:
        c2s.setdefault(s[:6], si[s])
    T, S = len(dates), len(syms)
    ii = d["date"].replace_strict(di, return_dtype=pl.Int32).to_numpy()
    jj = d["yf"].replace_strict(si, return_dtype=pl.Int32).to_numpy()

    def mat(col):
        a = np.full((T, S), np.nan, dtype=np.float32)
        a[ii, jj] = d[col].to_numpy().astype(np.float32)
        return a

    close, vol = mat("close"), mat("volume")
    val = close * vol
    cf = pl.DataFrame(close).fill_nan(None).with_columns(pl.all().forward_fill()).to_numpy().astype(np.float32)
    nbars = np.cumsum(~np.isnan(close), axis=0)

    # H1-4 수급: fi(백만원), mcap(억원)
    fl = pl.concat([pl.read_parquet(p) for p in sorted((ROOT / "data" / "flows").glob("kr_inv_*.parquet"))])
    fl = fl.filter(pl.col("code").is_in(list(c2s)) & pl.col("date").is_in(list(di)))
    fi_m = np.full((T, S), np.nan, dtype=np.float32)
    mc_m = np.full((T, S), np.nan, dtype=np.float32)
    ti = fl["date"].replace_strict(di, return_dtype=pl.Int32).to_numpy()
    sj = fl["code"].replace_strict(c2s, return_dtype=pl.Int32).to_numpy()
    fi_m[ti, sj] = (fl["f"] + fl["i"]).to_numpy().astype(np.float32)
    mc_m[ti, sj] = fl["mcap"].to_numpy().astype(np.float32)

    # H1-6 목표가 상향 이벤트(일자 x 종목 카운트)
    rs = pl.read_parquet(ROOT / "data" / "research.parquet").filter(pl.col("target").is_not_null() & (pl.col("target") > 0) & pl.col("code").is_in(list(c2s)))
    rs = rs.select("date", "code", "broker", "target").unique().sort("date")
    rs = rs.with_columns(pl.col("target").shift(1).over(["code", "broker"]).alias("prev"))
    up = rs.filter(pl.col("prev").is_not_null() & (pl.col("target") > pl.col("prev")))
    # 거래일 인덱스에 매핑(비거래일 접수는 다음 거래일로 — 당일 장 마감 후 공개로 취급)
    dnp = np.array(dates, dtype="datetime64[D]")
    up_i = np.searchsorted(dnp, up["date"].to_numpy().astype("datetime64[D]"), side="left")
    upm = np.zeros((T, S), np.float32)
    for k, c in zip(up_i, up["code"].to_list()):
        if k < T:
            upm[k, c2s[c]] += 1

    t0s = [i for i, x in enumerate(dates) if "2011-01-01" <= str(x) <= LAST_T0][::STEP]
    t0s = [i for i in t0s if i + H < T]
    rows = {"H1-4": [], "H1-6": []}
    for i in t0s:
        dstr = str(dates[i])
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
        for name in rows:
            start, split, _ = CFG[name]
            if dstr < start:
                continue
            if name == "H1-4":
                w = fi_m[i - 19:i + 1, idx]
                have = (~np.isnan(w)).sum(axis=0)
                ratio = np.where(have >= 15, np.nansum(w, axis=0) / (mc_m[i, idx] * 100.0), np.nan)
                valid = ~np.isnan(ratio) & np.isfinite(ratio)
                if valid.sum() < 200:
                    continue
                F = valid & (ratio >= np.nanpercentile(ratio[valid], 80))
            else:
                F = upm[i - 19:i + 1, idx].sum(axis=0) >= 1
            nf = int(F.sum())
            if nf == 0:
                continue
            rows[name].append({"date": dstr, "split": "IS" if dstr < split else "OOS", "nF": nf, "k": k,
                               "n_up": int((F & y_up).sum()), "n_lo": int((F & y_lo).sum()),
                               "ex_mean": float(r60[F].mean() - r60.mean() - COST), "ex_med": float(np.median(r60[F]) - np.median(r60) - COST)})
    res = {}
    for name, rr_all in rows.items():
        out = {}
        for tag, sel in (("전체", lambda r: True), ("IS", lambda r: r["split"] == "IS"), ("OOS", lambda r: r["split"] == "OOS"),
                         ("하락연도", lambda r: int(r["date"][:4]) in CFG[name][2])):
            rr = [r for r in rr_all if sel(r)]
            if not rr:
                continue
            u = np.array([r["n_up"] / r["nF"] - 0.05 for r in rr]); lo = np.array([r["n_lo"] / r["nF"] - 0.05 for r in rr])
            mu, _, t = nw_t(u); _, _, tl = nw_t(lo)
            nF = sum(r["nF"] for r in rr); nu = sum(r["n_up"] for r in rr); nl = sum(r["n_lo"] for r in rr); kk = sum(r["k"] for r in rr)
            out[tag] = {"dates": len(rr), "events_F": nF, "precision_up": nu / nF, "precision_lo": nl / nF, "lift_up": nu / nF / 0.05,
                        "lift_lo": nl / nF / 0.05, "recall_up": nu / kk, "nw_t": t, "p_one": p_one(t), "nw_t_lo": tl,
                        "ex_mean_after_cost": float(np.mean([r["ex_mean"] for r in rr])), "ex_med_after_cost": float(np.mean([r["ex_med"] for r in rr]))}
        res[name] = out
    meta = {name: {"dates": len(v), "first": v[0]["date"] if v else None, "last": v[-1]["date"] if v else None} for name, v in rows.items()}
    meta["research_up_events"] = int(len(up))
    json.dump({"meta": meta, "results": res}, open(OUT, "w"), ensure_ascii=False, indent=1)
    print(json.dumps({"meta": meta, "results": res}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
