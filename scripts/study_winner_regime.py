#!/usr/bin/env python3
"""req-quant-ec93e2cb/32e05b61/77018bfa — 사전등록 개정3(§6, 커밋 13788920e) 실행: bond_regime_v1 층화(H1-1~4 x BA/BC/BB, m12) + 정리매매 제외 민감도(H1-1~3).
문턱·격자·분할·층 정의는 §1·§6 그대로. 결과를 보고 바꾸지 않는다. 출력 reports/studies/2026-11-03_bond_regime_strata.json
"""
from __future__ import annotations
import json, math, sys
from pathlib import Path
import numpy as np, pandas as pd, polars as pl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
from screener.prices import load_kr  # noqa: E402
from study_winner_ex_ante import COST, H, LAST_T0, STEP, nw_t, p_one  # noqa: E402
from study_bond_regime import grid_labels  # noqa: E402

OUT = ROOT / "reports" / "studies" / "2026-11-03_bond_regime_strata.json"
M_FAM, ALPHA = 12, 0.05
SPLIT = {"H1-1": "2020-01-01", "H1-2": "2020-01-01", "H1-3": "2020-01-01", "H1-4": "2025-01-01"}
H14_START = "2022-02-01"
LAST_LAB = "2025-12-31"
B, SEED = 10000, 20261029


def records(excl_settle: bool) -> tuple[dict, list]:
    d = load_kr(hist_from=2010).with_columns(pl.col("yf").str.slice(0, 6).alias("code"))
    d = d.filter(pl.col("code").str.contains(r"^\d{5}0$"))
    dates = sorted(d["date"].unique().to_list())
    di = {x: i for i, x in enumerate(dates)}
    syms = sorted(d["yf"].unique().to_list()); si = {s: i for i, s in enumerate(syms)}
    c2s = {}
    for s in syms:
        c2s.setdefault(s[:6], si[s])
    T, S = len(dates), len(syms)
    ii = d["date"].replace_strict(di, return_dtype=pl.Int32).to_numpy()
    jj = d["yf"].replace_strict(si, return_dtype=pl.Int32).to_numpy()

    def mat(col):
        a = np.full((T, S), np.nan, dtype=np.float32); a[ii, jj] = d[col].to_numpy().astype(np.float32); return a
    close, high, vol = mat("close"), mat("high"), mat("volume")
    ndel = 0
    if excl_settle:
        for j in range(S):
            nz = np.where(~np.isnan(close[:, j]))[0]
            if len(nz) and nz[-1] < T - 1 - 5:
                ndel += 1
                cut = nz[-7:] if len(nz) > 7 else nz
                close[cut, j] = np.nan; high[cut, j] = np.nan; vol[cut, j] = np.nan
    val = close * vol
    cf = pl.DataFrame(close).fill_nan(None).with_columns(pl.all().forward_fill()).to_numpy().astype(np.float32)
    ret1 = np.full_like(cf, np.nan); ret1[1:] = cf[1:] / cf[:-1] - 1
    nbars = np.cumsum(~np.isnan(close), axis=0)
    fl = pl.concat([pl.read_parquet(p) for p in sorted((ROOT / "data" / "flows").glob("kr_inv_*.parquet"))])
    fl = fl.filter(pl.col("code").is_in(list(c2s)) & pl.col("date").is_in(list(di)))
    fi_m = np.full((T, S), np.nan, dtype=np.float32); mc_m = np.full((T, S), np.nan, dtype=np.float32)
    ti = fl["date"].replace_strict(di, return_dtype=pl.Int32).to_numpy(); sj = fl["code"].replace_strict(c2s, return_dtype=pl.Int32).to_numpy()
    fi_m[ti, sj] = (fl["f"] + fl["i"]).to_numpy().astype(np.float32); mc_m[ti, sj] = fl["mcap"].to_numpy().astype(np.float32)

    t0s = [i for i, x in enumerate(dates) if "2011-01-01" <= str(x) <= LAST_T0][::STEP]
    t0s = [i for i in t0s if i + H < T]
    recs = {k: [] for k in SPLIT}
    for i in t0s:
        dstr = str(dates[i]); px = cf[i]
        adv = np.nanmean(val[i - 19:i + 1], axis=0)
        elig = (~np.isnan(close[i])) & (adv >= 1e9) & (px >= 1000) & (nbars[i] >= 260)
        idx = np.where(elig)[0]
        if len(idx) < 200: continue
        r60 = cf[i + H, idx] / px[idx] - 1; ok = ~np.isnan(r60); idx, r60 = idx[ok], r60[ok]
        n = len(idx); k = int(round(0.05 * n)); order = np.argsort(r60)
        yu = np.zeros(n, bool); yu[order[-k:]] = True
        yl = np.zeros(n, bool); yl[order[:k]] = True
        f = {}
        hi250 = np.nanmax(high[i - 249:i + 1, idx], axis=0); f["H1-1"] = (px[idx] / hi250 - 1) <= -0.40
        sd = np.nanstd(ret1[i - 59:i + 1, idx], axis=0); f["H1-2"] = sd >= np.nanpercentile(sd, 80)
        v5 = np.nanmean(val[i - 4:i + 1, idx], axis=0); v60 = np.nanmean(val[i - 64:i - 4, idx], axis=0)
        f["H1-3"] = (v5 / np.where(v60 > 0, v60, np.nan)) >= 2
        if dstr >= H14_START:
            w = fi_m[i - 19:i + 1, idx]; have = (~np.isnan(w)).sum(axis=0)
            ratio = np.where(have >= 15, np.nansum(w, axis=0) / (mc_m[i, idx] * 100.0), np.nan)
            valid = ~np.isnan(ratio) & np.isfinite(ratio)
            if valid.sum() >= 200: f["H1-4"] = valid & (ratio >= np.nanpercentile(ratio[valid], 80))
        for name, F in f.items():
            nf = int(F.sum())
            if nf == 0: continue
            recs[name].append({"date": dstr, "nF": nf, "k": k, "n_up": int((F & yu).sum()), "n_lo": int((F & yl).sum()),
                               "ex": float(r60[F].mean() - r60.mean() - COST)})
    return recs, [ndel]


def summ(rr):
    if not rr: return None
    nF = sum(r["nF"] for r in rr); nu = sum(r["n_up"] for r in rr); nl = sum(r["n_lo"] for r in rr)
    x = np.array([r["n_up"] / r["nF"] - 0.05 for r in rr]); _, _, t = nw_t(x)
    return {"dates": len(rr), "events_F": nF, "prec_up": nu / nF, "lift_up": nu / nF / 0.05, "lift_lo": nl / nF / 0.05,
            "nw_t": t, "p_one": p_one(t), "ex_after_cost": float(np.mean([r["ex"] for r in rr]))}


def hac_diff(x: np.ndarray, s: np.ndarray, lag: int = 2):
    n = len(x); X = np.column_stack([np.ones(n), s]); XtXi = np.linalg.inv(X.T @ X)
    b = XtXi @ X.T @ x; u = x - X @ b; Xu = X * u[:, None]
    S0 = Xu.T @ Xu
    for l in range(1, lag + 1):
        G = Xu[l:].T @ Xu[:-l]; S0 += (1 - l / (lag + 1)) * (G + G.T)
    V = XtXi @ S0 @ XtXi; se = math.sqrt(V[1, 1]); t = b[1] / se
    return float(b[1]), se, float(t), 2 * 0.5 * math.erfc(abs(t) / math.sqrt(2))


def runs_of(labels: list[int]) -> list[tuple[int, int, int]]:
    out = []; st = 0
    for i in range(1, len(labels) + 1):
        if i == len(labels) or labels[i] != labels[st]:
            out.append((labels[st], st, i)); st = i
    return out


def strat(rr, lab: pd.DataFrame, axis: str, on: str, name: str, rng) -> dict:
    rr = [r for r in rr if r["date"] <= LAST_LAB and pd.Timestamp(r["date"]) in lab.index]
    if len(rr) < 6: return {"status": "검증전(날짜 부족)", "dates": len(rr)}
    s = np.array([1.0 if lab.loc[pd.Timestamp(r["date"]), axis] == on else 0.0 for r in rr])
    x = np.array([r["n_up"] / r["nF"] - 0.05 for r in rr]); sp = SPLIT[name]
    isn = np.array([r["date"] < sp for r in rr])
    cnt = {f"{a}_{b}": int(((s == sv) & (isn == iv)).sum()) for a, sv in (("on", 1), ("off", 0)) for b, iv in (("IS", True), ("OOS", False))}
    # 에피소드: 전체 격자 라벨 런(on 층, 길이>=2)
    full = [1 if v == on else 0 for v in lab[axis].tolist()]
    ep_on = [(a, b) for v, a, b in runs_of(full) if v == 1 and b - a >= 2]
    nF_on = sum(r["nF"] for r, sv in zip(rr, s) if sv == 1)
    short = min(cnt.values()) < 12 or nF_on < 100 or len(ep_on) < 3
    res = {"counts": cnt, "episodes_on_ge2": len(ep_on), "events_F_on": nF_on}
    def desc(sel):
        q = [r for r, sv in zip(rr, s) if sv == sel]; return summ(q)
    res["on"], res["off"] = desc(1), desc(0)
    if s.sum() < 3 or (1 - s).sum() < 3: res["status"] = "검증전(층 날짜 부족)"; return res
    diff, se, t, p_nw = hac_diff(x, s)
    # 에피소드 블록 부트스트랩: 격자 라벨 런(길이 무관)을 블록으로, 층 안에서 복원추출
    dates = [r["date"] for r in rr]; pos = {pd.Timestamp(d): i for i, d in enumerate(lab.index)}
    blocks = {1: [], 0: []}
    for v, a, b in runs_of(full):
        idxs = [j for j, d in enumerate(dates) if a <= pos[pd.Timestamp(d)] < b]
        if idxs: blocks[v].append((float(x[idxs].sum()), len(idxs)))
    bd = np.empty(B)
    arr = {v: np.array(blocks[v]) for v in (0, 1)}
    for v in (0, 1):
        if len(arr[v]) == 0: res["status"] = "검증전(블록 없음)"; return res
    for bi in range(B):
        m = {}
        for v in (0, 1):
            a = arr[v][rng.integers(0, len(arr[v]), len(arr[v]))]; m[v] = a[:, 0].sum() / a[:, 1].sum()
        bd[bi] = m[1] - m[0]
    p_bt = float(min(1.0, 2 * min((bd <= 0).mean(), (bd >= 0).mean())))
    # 에피소드 하나 제외 부호
    flips = 0
    for a, b in ep_on:
        keep = np.array([not (a <= pos[pd.Timestamp(d)] < b) for d in dates])
        if keep.sum() > 3 and s[keep].sum() > 0 and (s[keep] == 0).sum() > 0:
            d2 = x[keep][s[keep] == 1].mean() - x[keep][s[keep] == 0].mean()
            flips += int(np.sign(d2) != np.sign(diff))
    # IS/OOS 부호
    sg = {}
    for tag, sel in (("IS", isn), ("OOS", ~isn)):
        if (s[sel] == 1).sum() >= 2 and (s[sel] == 0).sum() >= 2:
            sg[tag] = float(x[sel][s[sel] == 1].mean() - x[sel][s[sel] == 0].mean())
    res.update({"diff_pp": diff * 100, "se_pp": se * 100, "t": t, "p_nw": p_nw, "p_boot": p_bt, "p_max": max(p_nw, p_bt),
                "sign_IS_OOS_pp": {k: v * 100 for k, v in sg.items()}, "episode_drop_flips": flips})
    pm = res["p_max"]; same = len(sg) == 2 and np.sign(sg["IS"]) == np.sign(sg["OOS"]) == np.sign(diff)
    if short: g = "검증전"
    elif pm < ALPHA / M_FAM: g = "A" if (same and flips == 0) else "B"
    elif pm < 0.10: g = "C"
    else: g = "F"
    res["grade_raw"] = g
    return res


def main() -> None:
    out = {"prereg": "docs/desk_kb/rounds/2026-10-29/quant_prereg_ec93e2cb.md §6 (13788920e)", "m": M_FAM, "alpha_bonf_two_sided": ALPHA / M_FAM, "B": B, "seed": SEED}
    base, _ = records(False); excl, nd = records(True)
    out["delisted_candidates_removed_last7"] = nd[0]
    out["sensitivity"] = {}
    for k in ("H1-1", "H1-2", "H1-3"):
        row = {}
        for tag, recs in (("base", base), ("excl", excl)):
            rr = recs[k]
            row[tag] = {"전체": summ(rr), "IS": summ([r for r in rr if r["date"] < SPLIT[k]]), "OOS": summ([r for r in rr if r["date"] >= SPLIT[k]])}
        out["sensitivity"][k] = row
    lab = grid_labels(LAST_LAB); lab = lab[lab.index >= "2011-01-01"]
    rng = np.random.default_rng(SEED)
    out["strata"] = {}
    for k in ("H1-1", "H1-2", "H1-3", "H1-4"):
        for ax, on, nm in (("A", "급등", "BA"), ("C", "약화", "BC"), ("B", "고", "BB")):
            out["strata"][f"{k}x{nm}"] = strat(base[k], lab, ax, on, k, rng)
    grades = {}
    for kk, v in out["strata"].items():
        grades[kk] = v.get("grade_raw") or v.get("status", "검증전")
        if kk.startswith("H1-1") and grades[kk] in ("A", "B"): grades[kk] = "C"   # 주 검정 F → 층 결과 최대 C (§5 규칙 ①)
        if kk.endswith("BB") and grades[kk] == "A": grades[kk] = "B"            # BB 시기 교란 상한 B (§6)
    out.update({"study": "winner_ex_ante_bond_regime_strata", "req": "req-quant-77018bfa/32e05b61/ec93e2cb", "asof": "2026-11-03",
                "prereg_doc": "docs/desk_kb/rounds/2026-10-29/quant_prereg_ec93e2cb.md", "script": "scripts/study_winner_regime.py",
                "prereg": {"m": M_FAM, "alpha": ALPHA, "alpha_bonf": ALPHA / M_FAM, "is_end": "2019-12-31", "oos_start": "2020-01-01", "cost": "왕복 0.25% 차감(초과수익 보조지표)", "horizon_days": 60, "grid_days": 20, "last_label_t0": LAST_LAB},
                "survivorship": "load_kr(hist_from=2010) 상폐 포함 보통주코드; 민감도에서 마지막 봉일이 데이터 끝보다 5거래일+ 앞선 종목의 마지막 7봉 제거(정리매매·장기 거래정지 구분 불가 [가정])",
                "grades": grades})
    json.dump(out, open(OUT, "w"), ensure_ascii=False, indent=1, default=str)
    print(json.dumps(out, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
