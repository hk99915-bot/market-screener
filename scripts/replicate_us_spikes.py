"""us_smallcap_spikes 독립 재현 (검증 데스크, 2026-10-21).

명세 = reports/studies/2026-10-21_us_smallcap_spikes.md §0~§4 + replication_us_spikes.md §0.
원 코드(study_us_spikes.py·fetch_us_spikes.py) 미열람(kb:verify#8).

  python3 scripts/replicate_us_spikes.py --data <dir with events.parquet ...> [--out reports/studies/replication_us_spikes.json]
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

P = dict(r_min=0.30, vol_mult=5.0, px=(1.0, 20.0), min_hist=60, mcap_hi=2e9, mcap_age=450,
         cool=20, cost=0.01, is_end="2019-12-31")
K = list(range(-1, 21))


# ---------- 적재 ----------
def load(data: Path):
    ev = pd.read_parquet(data / "events.parquet")
    shares = pd.read_csv(data / "sec_shares.csv")
    tick = json.load(open(data / "sec_tickers.json"))
    t2c = {}
    for v in tick.values():
        t2c.setdefault(v["ticker"].upper().replace(".", "-"), int(v["cik_str"]))
    halts = pd.read_csv(data / "halts.csv")
    meta = pd.read_csv(data / "meta.csv")
    return ev, shares, t2c, halts, meta


def wide(ev: pd.DataFrame) -> pd.DataFrame:
    """(yf,d0) 한 행 · 열 = 필드_k."""
    key = ["yf", "d0"]
    piv = ev.pivot_table(index=key, columns="k", values=["open", "high", "low", "close", "volume", "raw_f"],
                         aggfunc="first")
    piv.columns = [f"{a}_{b}" for a, b in piv.columns]
    dates = ev.pivot_table(index=key, columns="k", values="date", aggfunc="first")
    dates.columns = [f"date_{b}" for b in dates.columns]
    st = ev.groupby(key)[["vol20", "n_hist"]].first()
    w = piv.join(dates).join(st).reset_index()
    for k in K:
        for f in ["open", "high", "low", "close", "volume", "raw_f", "date"]:
            c = f"{f}_{k}"
            if c not in w:
                w[c] = np.nan
    return w


def attach_mcap(w: pd.DataFrame, shares: pd.DataFrame, t2c: dict, age=P["mcap_age"]) -> pd.Series:
    sh = shares.dropna().copy()
    sh["end"] = pd.to_datetime(sh["end"])
    sh = sh.sort_values("end")
    by = {c: (g["end"].values, g["val"].values) for c, g in sh.groupby("cik")}
    out = np.full(len(w), np.nan)
    d0 = pd.to_datetime(w["d0"]).values
    for i, (t, d) in enumerate(zip(w["yf"], d0)):
        c = t2c.get(str(t).upper())
        if c is None or c not in by:
            continue
        ends, vals = by[c]
        j = np.searchsorted(ends, d, side="left") - 1      # end < D0
        if j < 0:
            continue
        if (d - ends[j]) / np.timedelta64(1, "D") > age:
            continue
        out[i] = vals[j]
    return pd.Series(out, index=w.index) * w["px_raw_m1"]


def features(w: pd.DataFrame) -> pd.DataFrame:
    w = w.copy()
    w["r0"] = w["close_0"] / w["close_-1"] - 1
    w["vr"] = w["volume_0"] / w["vol20"]
    w["px_raw_m1"] = w["close_-1"] * w["raw_f_-1"]
    w["gap_share"] = np.log(w["open_0"] / w["close_-1"]) / np.log(w["close_0"] / w["close_-1"])
    # 창 안(D+1~D+20) 하룻밤 ×3 이상·⅓ 이하 갭 = 미반영 분할 의심(야후 분할 누락)
    g = pd.concat([w[f"open_{k}"] / w[f"close_{k-1}"] for k in range(1, 21)], axis=1)
    w["split_suspect"] = ((g >= 3) | (g <= 1 / 3)).any(axis=1)
    return w


def cooldown(w: pd.DataFrame, cool=P["cool"]) -> pd.Series:
    """시간순으로 채택 사건 창(k=1..cool) 안의 D0 는 제외."""
    keep = pd.Series(False, index=w.index)
    for t, g in w.sort_values("d0").groupby("yf", sort=False):
        blocked = set()
        for i, r in g.iterrows():
            if r["d0"] in blocked:
                continue
            keep[i] = True
            blocked = {r[f"date_{k}"] for k in range(1, cool + 1) if isinstance(r[f"date_{k}"], str)}
    return keep


def select(w, use_raw=True, mcap_known_only=False, p=P):
    px = w["px_raw_m1"] if use_raw else w["close_-1"]
    m = (w["r0"] >= p["r_min"]) & (w["vr"] >= p["vol_mult"]) & px.between(*p["px"]) & (w["n_hist"] >= p["min_hist"])
    mc = (w["mcap"] < p["mcap_hi"]) if mcap_known_only else ((w["mcap"] < p["mcap_hi"]) | w["mcap"].isna())
    s = w[m & mc]
    return s[cooldown(s, p["cool"])]


# ---------- 수익 ----------
def long_ret(w, h, cost=P["cost"]):
    return w[f"close_{h}"] / w["close_0"] - 1 - cost


def short_ret(w, h, b=0.5, stop=None, cost=P["cost"], entry="open_1", cap_loss=None):
    """D+1 진입(기본 시가) → D+h 종가 환매. stop=x 이면 고가 ≥ 진입×(1+x) 에 환매(갭이면 시가)."""
    e = w[entry] if isinstance(entry, str) else entry
    exitp = w[f"close_{h}"].copy()
    if stop is not None:
        lvl = e * (1 + stop)
        done = pd.Series(False, index=w.index)
        for k in range(1, h + 1):
            o, hi = w[f"open_{k}"], w[f"high_{k}"]
            hit = (~done) & (hi >= lvl)
            px = lvl.copy()
            if k > 1:
                px = np.where(o >= lvl, o, lvl)
            exitp = exitp.where(~hit, px)
            done |= hit.fillna(False)
    r = -(exitp / e - 1)
    if cap_loss is not None:
        r = r.clip(lower=cap_loss)
    r = r - cost - b * h / 252
    return r.where(w[f"close_{h}"].notna())


def stats(x: pd.Series) -> dict:
    x = x.dropna()
    if len(x) == 0:
        return {"n": 0}
    q = x.quantile([0.01, 0.05, 0.5, 0.95, 0.99])
    return {"n": int(len(x)), "mean": round(float(x.mean()), 4), "median": round(float(q[0.5]), 4),
            "win": round(float((x > 0).mean()), 4), "sd": round(float(x.std()), 4),
            "p01": round(float(q[0.01]), 4), "p05": round(float(q[0.05]), 4),
            "min": round(float(x.min()), 4), "max": round(float(x.max()), 4)}


def nw_test(x: pd.Series, d0: pd.Series, lag=1) -> dict:
    """달력월 평균 → Newey-West(lag) t, 단측(평균>0) 정규 p."""
    s = pd.DataFrame({"x": x, "m": pd.to_datetime(d0).dt.to_period("M")}).dropna()
    if s.empty:
        return {"months": 0}
    y = s.groupby("m")["x"].mean().values
    n = len(y)
    mu = y.mean()
    e = y - mu
    g0 = (e @ e) / n
    v = g0
    for L in range(1, lag + 1):
        gl = (e[L:] @ e[:-L]) / n
        v += 2 * (1 - L / (lag + 1)) * gl
    se = math.sqrt(v / n) if v > 0 else float("nan")
    t = mu / se
    p = 0.5 * math.erfc(t / math.sqrt(2))
    return {"months": n, "mean_m": round(float(mu), 4), "t": round(t, 3), "p": float(f"{p:.3g}")}


def event_t(x: pd.Series) -> dict:
    x = x.dropna()
    t = x.mean() / (x.std() / math.sqrt(len(x)))
    return {"t": round(float(t), 3), "p": float(f"{0.5 * math.erfc(t / math.sqrt(2)):.3g}")}


def boot_p(x: pd.Series, d0: pd.Series, B=2000, seed=7) -> float:
    """달력월 블록 부트스트랩: 평균 ≤ 0 비율(단측)."""
    s = pd.DataFrame({"x": x, "m": pd.to_datetime(d0).dt.to_period("M")}).dropna()
    groups = [g.values for _, g in s.groupby("m")["x"]]
    sums = np.array([g.sum() for g in groups]); cnt = np.array([len(g) for g in groups])
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(groups), size=(B, len(groups)))
    mu = sums[idx].sum(1) / cnt[idx].sum(1)
    return float(f"{(mu <= 0).mean():.3g}")


def hyp(sel, col, is_end=P["is_end"]):
    x = sel[col]
    isx = sel["d0"] <= is_end
    return {"all": stats(x), "is": {**stats(x[isx]), **nw_test(x[isx], sel["d0"][isx])},
            "oos": {**stats(x[~isx]), **nw_test(x[~isx], sel["d0"][~isx])},
            "nw_all": nw_test(x, sel["d0"])}


def add_returns(s: pd.DataFrame) -> pd.DataFrame:
    s = s.copy()
    s["L1"] = long_ret(s, 1)
    s["L5"] = long_ret(s, 5)
    s["S5"] = short_ret(s, 5, b=0.5)
    s["S20"] = short_ret(s, 20, b=0.5)
    s["S5_st30"] = short_ret(s, 5, b=0.5, stop=0.3)
    s["S5_b100"] = short_ret(s, 5, b=1.0)
    s["S20_b100"] = short_ret(s, 20, b=1.0)
    return s


def trim(x: pd.Series, q):
    x = x.dropna()
    lo, hi = x.quantile(q), x.quantile(1 - q)
    return x[(x >= lo) & (x <= hi)]


def winsor(x: pd.Series, q):
    x = x.dropna()
    return x.clip(x.quantile(q), x.quantile(1 - q))


def compare(orig: dict, R: dict) -> list:
    """§0-2 허용오차로 원 vs 재현 9항목(+참고) 판정."""
    oh = {h["id"]: h for h in orig["hypotheses"]}
    rows = []

    def add(item, o, r, tol, unit):
        rows.append({"item": item, "orig": o, "rep": r, "diff": round(r - o, 4), "tol": round(tol, 4), "unit": unit,
                     "verdict": "일치" if abs(r - o) <= tol + 1e-12 else "불일치"})
    for t, o in [("T30", 5948), ("T50", 2393), ("T100", 710)]:
        add(f"사건 수 {t}", o, R["tiers"][t]["n"], max(2, 0.005 * o), "건")
    for hid, lab in [("H1", "롱 D0종가→D+1"), ("H6", "T100 숏 D+1시가→D+5 b100%")]:
        a, r = oh[hid]["all"], R["hypotheses"][hid]["all"]
        se = r["sd"] / math.sqrt(r["n"])
        add(f"{hid} {lab} 평균", a["mean"], r["mean"], max(0.0005, 0.5 * se), "비율")
        add(f"{hid} {lab} 중앙", a["median"], r["median"], max(0.0005, 0.5 * 1.2533 * se), "비율")
        p = a["win"]
        add(f"{hid} {lab} 승률", p, r["win"], max(0.005, 0.5 * math.sqrt(p * (1 - p) / r["n"])), "비율")
    for hid in ["H2", "H3", "H4", "H5"]:
        a, r = oh[hid]["all"], R["hypotheses"][hid]["all"]
        se = r["sd"] / math.sqrt(r["n"])
        add(f"(참고) {hid} 평균", a["mean"], r["mean"], max(0.0005, 0.5 * se), "비율")
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", default="reports/studies/replication_us_spikes.json")
    ap.add_argument("--orig", default="reports/studies/2026-10-21_us_smallcap_spikes.json")
    a = ap.parse_args(argv)
    data = Path(a.data)
    ev, shares, t2c, halts, meta = load(data)
    w = features(wide(ev))
    w["mcap"] = attach_mcap(w, shares, t2c)
    R = {"meta": {"study": "replication_us_spikes", "target": "2026-10-21_us_smallcap_spikes", "date": "2026-10-21",
                  "data_branch": "study-data/us-spikes-39537550959@ee662a62", "topic": "us_spike", "m": 0,
                  "original_code_read": False}}
    # 깔때기
    f = {}
    f["candidate_windows"] = len(w)
    m1 = w["r0"] >= 0.30; f["+30%"] = int(m1.sum())
    m2 = m1 & (w["vr"] >= 5); f["+30%·vol5"] = int(m2.sum())
    m3 = m2 & w["px_raw_m1"].between(1, 20); f["+px raw 1~20"] = int(m3.sum())
    sel = select(w); f["final"] = len(sel)
    f["final_adjusted_px"] = len(select(w, use_raw=False))
    f["final_mcap_known_only"] = len(select(w, mcap_known_only=True))
    # 쿨다운 대안: 거래량·가격·이력만 걸고 쿨다운 → 그 뒤 시총
    R["funnel"] = f
    sel = add_returns(sel)
    isx = sel["d0"] <= P["is_end"]
    R["tiers"] = {t: {"n": int((sel["r0"] >= th).sum()), "n_is": int(((sel["r0"] >= th) & isx).sum()),
                      "gap_share": round(float((sel.loc[sel["r0"] >= th, "gap_share"] >= 0.5).mean()), 3)}
                  for t, th in [("T30", 0.3), ("T50", 0.5), ("T100", 1.0)]}
    R["mcap_known_share"] = round(float(sel["mcap"].notna().mean()), 3)
    t100 = sel[sel["r0"] >= 1.0]
    R["hypotheses"] = {"H1": hyp(sel, "L1"), "H2": hyp(sel, "L5"), "H3": hyp(sel, "S5"), "H4": hyp(sel, "S20"),
                       "H5": hyp(sel, "S5_st30"), "H6": hyp(t100, "S5_b100")}
    for h, (df, c) in {"H3": (sel, "S5"), "H6": (t100, "S5_b100"), "H1": (sel, "L1")}.items():
        R["hypotheses"][h]["event_t"] = event_t(df[c])
        R["hypotheses"][h]["boot_p_all"] = boot_p(df[c], df["d0"])
        isd = df["d0"] <= P["is_end"]
        R["hypotheses"][h]["boot_p_is"] = boot_p(df.loc[isd, c], df.loc[isd, "d0"])
    R["sens_T100_b"] = {f"S{h}_b{int(b*100)}": stats(short_ret(t100, h, b=b))["mean"]
                        for h in (5, 20) for b in (0, 0.5, 1.0, 3.0)}
    R["sens_T30_b"] = {f"S{h}_b{int(b*100)}": stats(short_ret(sel, h, b=b))["mean"]
                       for h in (5, 20) for b in (0, 0.5, 1.0, 3.0)}

    # (1) 원가격 복원
    rf = ev.groupby(["yf", "d0"])["raw_f"].agg(["min", "max"])
    mt = meta.set_index("yf")
    rv = sel.merge(mt[["rev_splits", "splits"]], left_on="yf", right_index=True, how="left")
    R["check1_raw_price"] = {
        "raw_f_zero_rows": int((ev["raw_f"] == 0).sum()),
        "windows_raw_f_varies": int((rf["min"] != rf["max"]).sum()),
        "sel_raw_f_ne1": int((sel["raw_f_-1"] != 1).sum()),
        "sel_raw_f_lt1": int((sel["raw_f_-1"] < 1).sum()),
        "sel_raw_f_gt1": int((sel["raw_f_-1"] > 1).sum()),
        "sel_adj_px_m1_gt20": int((sel["close_-1"] > 20).sum()),
        "sel_adj_px_m1_gt1000": int((sel["close_-1"] > 1000).sum()),
        "sel_raw_f_lt1_but_meta_no_rev": int(((rv["raw_f_-1"] < 1) & (rv["rev_splits"].fillna(0) == 0)).sum()),
        "excluded_by_raw_but_in_adj": int(len(set(map(tuple, select(w, use_raw=False)[["yf", "d0"]].values))
                                           - set(map(tuple, sel[["yf", "d0"]].values)))),
    }
    # (2) D+1 시가 품질·거래 가능성
    o1, h1, l1, c1, v1 = (sel[f"{x}_1"] for x in ["open", "high", "low", "close", "volume"])
    bad_range = (o1 > h1 * 1.0001) | (o1 < l1 * 0.9999)
    v0 = v1 == 0
    jump = (o1 / sel["close_0"] > 3) | (o1 / sel["close_0"] < 1 / 3)
    hl = halts.copy(); hl["k"] = 1
    halt_set = set(zip(hl["yf"], hl["date"]))
    d1halt = pd.Series([(t, d) in halt_set for t, d in zip(sel["yf"], sel["date_1"])], index=sel.index)
    d0halt = pd.Series([(t, d) in halt_set for t, d in zip(sel["yf"], sel["date_0"])], index=sel.index)
    since23 = sel["d0"] >= "2023-01-01"
    typ = (h1 + l1 + c1) / 3
    c2 = {"open1_outside_HL": int(bad_range.sum()), "vol1_zero": int(v0.sum()),
          "open1_vs_close0_gt3x_or_lt_third": int(jump.sum()),
          "open1_eq_close0": int((o1 == sel["close_0"]).sum()),
          "events_2023+": int(since23.sum()), "halt_d0_2023+": round(float(d0halt[since23].mean()), 4),
          "halt_d1_2023+": round(float(d1halt[since23].mean()), 4)}
    t1 = sel["r0"] >= 1.0
    clean = ~(bad_range | v0 | jump)
    for nm, mask in {"T30": pd.Series(True, index=sel.index), "T100": t1}.items():
        b = 1.0 if nm == "T100" else 0.5
        c2[nm] = {
            "base_S5": stats(short_ret(sel[mask], 5, b=b))["mean"],
            "clean_open_S5": stats(short_ret(sel[mask & clean], 5, b=b))["mean"],
            "ex_halt_d1_2023+_S5": stats(short_ret(sel[mask & since23 & ~d1halt], 5, b=b))["mean"],
            "only_2023+_S5": stats(short_ret(sel[mask & since23], 5, b=b))["mean"],
            "entry_typical_D1_S5": stats(short_ret(sel[mask], 5, b=b, entry=typ[mask]))["mean"],
            "entry_close_D1_S5": stats(short_ret(sel[mask], 5, b=b, entry="close_1"))["mean"],
            "entry_close_D1_S5_median": stats(short_ret(sel[mask], 5, b=b, entry="close_1"))["median"],
        }
    R["check2_d1_open"] = c2
    # (3) 숏 손익 꼬리
    def worst(df, col, h, n=5):
        x = df.nsmallest(n, col)
        return [{"yf": r["yf"], "d0": r["d0"], "ret": round(float(r[col]), 4), "open1": round(float(r["open_1"]), 4),
                 f"close{h}": round(float(r[f"close_{h}"]), 4), "vol20": float(r["vol20"]),
                 "split_suspect": bool(r["split_suspect"])} for _, r in x.iterrows()]
    R["check3_short_tail"] = {
        "T30_S5_worst": worst(sel, "S5", 5), "T100_S5_worst": worst(t100, "S5_b100", 5),
        "T30_S20_worst": worst(sel, "S20", 20, 3),
        "T30_S5_loss_gt100": int((sel["S5"] < -1).sum()), "T100_S5_loss_gt100": int((t100["S5_b100"] < -1).sum()),
        "T30_S5_cap_-100": stats(short_ret(sel, 5, b=0.5, cap_loss=-1.0))["mean"],
        "T100_S5_cap_-100": stats(short_ret(t100, 5, b=1.0, cap_loss=-1.0))["mean"],
        "T100_S5_stop100": stats(short_ret(t100, 5, b=1.0, stop=1.0))["mean"],
    }
    # 자료 품질 민감도: vol20=0(거래량 필터 무의미) · 창 안 분할 의심 · 쿨다운 19
    dq = {"vol20_zero": int((sel["vol20"] == 0).sum()), "split_suspect": int(sel["split_suspect"].sum()),
          "split_suspect_T100": int(t100["split_suspect"].sum())}
    ok = (sel["vol20"] > 0) & ~sel["split_suspect"]
    t1 = sel["r0"] >= 1.0
    dq["clean_T30_S5"] = stats(sel.loc[ok, "S5"]); dq["clean_T30_S20"] = stats(sel.loc[ok, "S20"])
    dq["clean_T30_L1"] = stats(sel.loc[ok, "L1"])
    dq["clean_T100_S5_b100"] = stats(sel.loc[ok & t1, "S5_b100"])
    dq["clean_T100_S5_b100_nw"] = nw_test(sel.loc[ok & t1, "S5_b100"], sel.loc[ok & t1, "d0"])
    s19 = add_returns(select(w, p={**P, "cool": 19}))
    dq["cool19"] = {"n": len(s19), "T50": int((s19["r0"] >= .5).sum()), "T100": int((s19["r0"] >= 1).sum()),
                    "mcap_known_only": len(select(w, mcap_known_only=True, p={**P, "cool": 19})),
                    "L1": stats(s19["L1"]), "H6": stats(s19.loc[s19["r0"] >= 1, "S5_b100"])}
    R["data_quality"] = dq
    # (5) 생존편향 대리: raw_f(D0) < 1 = D0 이후 순 역분할(미래 정보)
    px_ = sel["raw_f_0"] < 1
    sv = {"proxy_share": round(float(px_.mean()), 3)}
    for nm, (df, col) in {"T30_L5": (sel, "L5"), "T30_S5": (sel, "S5"), "T30_S20": (sel, "S20"),
                          "T100_S5_b50": (sel[t1], None), "T100_S20_b50": (sel[t1], None)}.items():
        if col is None:
            h = 5 if "S5" in nm else 20
            x = short_ret(df, h, b=0.5)
        else:
            x = df[col]
        pr, rest = x[px_.loc[x.index]].mean(), x[~px_.loc[x.index]].mean()
        obs = x.mean()
        sv[nm] = {"obs": round(float(obs), 4), "proxy": round(float(pr), 4), "rest": round(float(rest), 4),
                  **{f"phi{f}": round(float((1 - f) * obs + f * pr), 4) for f in (0.2, 0.4, 0.6)}}
    tt = sel[t1]
    rest = tt[~px_.loc[tt.index]]
    sv["T100_S5_b100_rest"] = {**stats(rest["S5_b100"]), **nw_test(rest["S5_b100"], rest["d0"])}
    per = pd.cut(pd.to_datetime(tt["d0"]).dt.year, [2010, 2019, 2022, 2024, 2026], labels=["2011-19", "2020-22", "2023-24", "2025-26"])
    sv["T100_S5_b100_by_period"] = {str(k): {"n": int(len(g)), "mean": round(float(g.mean()), 4), "median": round(float(g.median()), 4)}
                                    for k, g in tt["S5_b100"].groupby(per, observed=True)}
    sv["proxy_share_by_year"] ={y: round(float(g.mean()), 3) for y, g in px_.groupby(sel["d0"].str[:4])}
    R["survivorship"] = sv
    # (6) 극단값
    c6 = {}
    for nm, x in {"L1": sel["L1"], "S5_T30": sel["S5"], "S20_T30": sel["S20"], "S5_T100_b100": t100["S5_b100"]}.items():
        c6[nm] = {"mean": stats(x)["mean"], "trim1": round(float(trim(x, 0.01).mean()), 4),
                  "trim5": round(float(trim(x, 0.05).mean()), 4), "winsor1": round(float(winsor(x, 0.01).mean()), 4),
                  "drop_top1_only": round(float(x.dropna()[x.dropna() <= x.quantile(0.99)].mean()), 4),
                  "drop_bottom1_only": round(float(x.dropna()[x.dropna() >= x.quantile(0.01)].mean()), 4)}
    R["check6_extremes"] = c6
    # (5) 생존편향 대리: 창 밖 미래 역분할 정보가 데이터에 없음 → 창 안(k 0..20) raw_f 변화로만 근사
    R["by_year"] = {str(y): {"n": int(len(g)), "S20_mean": round(float(g["S20"].mean()), 4),
                             "L5_mean": round(float(g["L5"].mean()), 4)}
                    for y, g in sel.groupby(sel["d0"].str[:4])}
    op = Path(a.orig)
    if op.exists():
        R["rows"] = compare(json.load(open(op)), R)
        core = [x for x in R["rows"] if not x["item"].startswith("(참고)")]
        R["verdict"] = {"core_match": f"{sum(x['verdict'] == '일치' for x in core)}/{len(core)}",
                        "all_match": f"{sum(x['verdict'] == '일치' for x in R['rows'])}/{len(R['rows'])}"}
    out = Path(a.out)
    out.write_text(json.dumps(R, ensure_ascii=False, indent=1, default=str))
    return R, sel


if __name__ == "__main__":
    main()
