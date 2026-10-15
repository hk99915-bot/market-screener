"""급락 후 '실행 대본'(committee._exec_plan) 신호 검증 스터디.

질문: 코스피 급락일 뒤, 대본의 신호(저점 지지·5일 고점 회복·약세 경로 손절·시초가 금지)가
단순 대안(다음날 시가/급락일 종가 매수)보다 결과를 개선하나?

사용법:  python scripts/study_playbook_signals.py
출력:    reports/studies/playbook_signals.json, reports/studies/playbook_signals.md

데이터 (네트워크 불필요):
  - 프록시 지수: data/hist/kr_*.parquet (2010~2025) + data/kr_prices.parquet (2025-09~) 의 .KS 종목,
    전일까지 60일 평균 거래대금 가중 (시총 데이터가 없어 거래대금 가중으로 대체; 가격은 비수정주가라
    가격제한폭 초과 일간수익률(액면분할·병합 등)은 제외).
  - 실제 코스피: reports/macro_series.json KOSPI (2024-09-19~, 일봉 OHLC) — 프록시 검증 + 이 구간은 실제 지수로 대체(스플라이스).
  - 외국인 수급 일별 이력은 저장된 것이 없어(신호1) 검증 불가.
"""
from __future__ import annotations

import glob
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT_J = ROOT / "reports/studies/playbook_signals.json"
OUT_M = ROOT / "reports/studies/playbook_signals.md"
SEED = 20261015
NBOOT = 5000
HORIZONS = (20, 60)
SIG2_WAIT = 10      # 신호2 대기 최대 거래일
BRK_WAIT = 20       # 5일 고점 돌파 대기 최대 거래일
CLUSTER_GAP = 10    # 직전 이벤트와 10거래일 이내면 같은 클러스터
REAL_FROM = "2024-09-19"


# ───────────────────────── 1. 지수 시리즈 ─────────────────────────
def _limit(d: pd.Series) -> pd.Series:
    """일간 가격제한폭 (2015-06-15부터 ±30%, 이전 ±15%) + 여유 1%p."""
    return np.where(d >= pd.Timestamp("2015-06-15"), 0.31, 0.16)


def build_proxy() -> pd.DataFrame:
    fs = sorted(glob.glob(str(ROOT / "data/hist/kr_*.parquet")))
    h = pd.concat([pd.read_parquet(f) for f in fs], ignore_index=True)
    k = pd.read_parquet(ROOT / "data/kr_prices.parquet")
    h["date"] = pd.to_datetime(h["date"])
    k["date"] = pd.to_datetime(k["date"])
    k = k[k["date"] > h["date"].max()]
    d = pd.concat([h, k], ignore_index=True)
    d = d[d["yf"].str.endswith(".KS")].drop_duplicates(["yf", "date"]).sort_values(["yf", "date"])
    d = d[(d["close"] > 0) & (d["volume"] >= 0)]
    # 시장 거래일 캘린더: 해당일 종목 수가 충분한 날
    cnt = d.groupby("date").size()
    cal = cnt[cnt >= 0.5 * cnt.rolling(20, min_periods=1).median()].index.sort_values()
    pos = pd.Series(np.arange(len(cal)), index=cal)
    d = d[d["date"].isin(cal)].copy()
    d["k"] = d["date"].map(pos)
    g = d.groupby("yf", sort=False)
    d["pc"] = g["close"].shift(1)
    d["pk"] = g["k"].shift(1)
    tv = d["close"] * d["volume"]
    d["tv60"] = tv.groupby(d["yf"]).transform(lambda s: s.rolling(60, min_periods=20).mean().shift(1))
    ok = (d["pk"] == d["k"] - 1) & d["tv60"].gt(0) & d["pc"].gt(0)
    d = d[ok].copy()
    lim = _limit(d["date"])
    o = d["open"].where(d["open"] > 0, d["close"])
    lo = d["low"].where(d["low"] > 0, np.minimum(o, d["close"]))
    hi = d["high"].where(d["high"] > 0, np.maximum(o, d["close"]))
    for c, s in (("rc", d["close"]), ("ro", o), ("rl", lo), ("rh", hi)):
        d[c] = s / d["pc"] - 1
    bad = (d[["rc", "ro", "rl", "rh"]].abs().max(axis=1) > lim)
    d = d[~bad]
    d["w"] = d["tv60"] / d.groupby("date")["tv60"].transform("sum")
    agg = d.groupby("date").apply(lambda x: pd.Series({c: float((x[c] * x["w"]).sum()) for c in ("rc", "ro", "rl", "rh")} | {"n": len(x)}),
                                  include_groups=False)
    agg = agg[agg["n"] >= 100]
    lvl = (1 + agg["rc"]).cumprod() * 1000.0
    prev = lvl.shift(1).fillna(1000.0)
    px = pd.DataFrame({"open": prev * (1 + agg["ro"]), "high": prev * (1 + agg["rh"]),
                       "low": prev * (1 + agg["rl"]), "close": lvl, "n": agg["n"]})
    # 저가·고가 일관성
    px["low"] = px[["low", "open", "close"]].min(axis=1)
    px["high"] = px[["high", "open", "close"]].max(axis=1)
    return px


def load_real() -> pd.DataFrame:
    ms = json.loads((ROOT / "reports/macro_series.json").read_text(encoding="utf-8"))["series"]["KOSPI"]
    r = pd.DataFrame([x[:5] for x in ms if len(x) >= 6], columns=["date", "open", "high", "low", "close"])
    r["date"] = pd.to_datetime(r["date"])
    return r.set_index("date").astype(float)


def validate(px: pd.DataFrame, real: pd.DataFrame) -> dict:
    j = px.join(real, rsuffix="_k", how="inner")
    rp, rk = j["close"].pct_change(), j["close_k"].pct_change()
    m = rp.notna() & rk.notna()
    cl_p = (j["close"] / j["low"] - 1)
    cl_k = (j["close_k"] / j["low_k"] - 1)
    gap_p = j["open"] / j["close"].shift(1) - 1
    gap_k = j["open_k"] / j["close_k"].shift(1) - 1
    crash_p = set(j.index[rp <= -0.03])
    crash_k = set(j.index[rk <= -0.03])
    beta = float(np.polyfit(rk[m], rp[m], 1)[0])
    return {"overlap": [str(j.index.min().date()), str(j.index.max().date())], "n_days": int(m.sum()),
            "ret_corr": round(float(rp[m].corr(rk[m])), 3), "beta_proxy_on_kospi": round(beta, 3),
            "vol_ratio": round(float(rp[m].std() / rk[m].std()), 3),
            "close_above_low_med": {"proxy": round(float(cl_p.median()), 4), "kospi": round(float(cl_k.median()), 4)},
            "open_gap_corr": round(float(gap_p.corr(gap_k)), 3),
            "crash_days_-3%": {"kospi": len(crash_k), "proxy": len(crash_p), "both": len(crash_p & crash_k)}}


def calibrate(px: pd.DataFrame, real: pd.DataFrame, val: dict) -> pd.DataFrame:
    """종목 저가의 가중평균은 지수 장중 저가보다 깊다(종목마다 저점 시각이 다름) → 겹치는 구간에서
    실제 코스피 대비 비율로 보정. 저가: (1−L/C) × k_low (중앙값 비율). 시가 갭: × k_gap (원점 OLS 기울기)."""
    j = px.join(real, rsuffix="_k", how="inner")
    xp, xk = 1 - j["low"] / j["close"], 1 - j["low_k"] / j["close_k"]
    m = xp > 0.002
    k_low = float((xk[m] / xp[m]).median())
    gp = (j["open"] / j["close"].shift(1) - 1).dropna()
    gk = (j["open_k"] / j["close_k"].shift(1) - 1).reindex(gp.index)
    k_gap = float((gp * gk).sum() / (gp * gp).sum())
    q = px.copy()
    pc = q["close"].shift(1)
    q["low"] = q["close"] * (1 - k_low * (1 - px["low"] / px["close"]))
    q["open"] = (pc * (1 + k_gap * (px["open"] / pc - 1))).fillna(px["open"])
    q["low"] = q[["low", "open", "close"]].min(axis=1)
    q["high"] = q[["high", "open", "close"]].max(axis=1)
    val["calibration"] = {"k_low": round(k_low, 3), "k_gap": round(k_gap, 3),
                          "note": "프록시 저가거리·시가갭을 실제 코스피(2024-09~) 대비 비율로 축소. 종가 수익률은 무보정."}
    return q


# ───────────────────────── 2. 이벤트·전략 ─────────────────────────
def events(px: pd.DataFrame, thr: float) -> list[int]:
    c = px["close"].to_numpy()
    out = []
    for i in range(21, len(c)):
        r1 = c[i] / c[i - 1] - 1
        dd = c[i] / c[i - 20:i + 1].max() - 1   # committee: max(c[-21:])
        if r1 <= thr and dd <= -0.10:
            out.append(i)
    return out


def run_event(px: pd.DataFrame, t: int, H: int) -> dict:
    o, lo, c = (px[k].to_numpy() for k in ("open", "low", "close"))
    n = len(c)
    T = t + H
    if T >= n:
        return {}
    Lc = lo[t]
    hi5_fixed = c[t - 4:t + 1].max()
    # 약세 경로: 크래시 저점 아래 종가 2일 연속 → 두 번째 날 b
    b = None
    for d in range(t + 2, T + 1):
        if c[d - 1] < Lc and c[d] < Lc:
            b = d
            break
    # 신호2 (문자 그대로): t+1..t+10 중 첫 날 종가 ≥ 크래시 저점
    s2 = next((d for d in range(t + 1, min(t + SIG2_WAIT, T) + 1) if c[d] >= Lc), None)
    # 신호2-리테스트: 장중 저점이 크래시 저점 +1% 이내로 내려왔다가 종가는 그 위
    s2r = next((d for d in range(t + 1, min(t + SIG2_WAIT, T) + 1) if lo[d] <= Lc * 1.01 and c[d] >= Lc), None)
    # 5일 고점 돌파 — 고정 레벨(급락일 기준 직전 5일 종가 최고) / 이동 레벨(당일 포함 5일 종가 신고)
    brk = next((d for d in range(t + 1, min(t + BRK_WAIT, T) + 1) if c[d] >= hi5_fixed), None)
    brk_roll = next((d for d in range(t + 1, min(t + BRK_WAIT, T) + 1) if c[d] >= c[d - 4:d + 1].max() and c[d] > c[d - 1]), None)

    def leg(entry_day, price_kind="close"):
        """한 다리: (진입일, 진입가) → 무청산/청산 버전 결과."""
        if entry_day is None or entry_day > T:
            return None
        ep = o[entry_day] if price_kind == "open" else c[entry_day]
        path = c[entry_day:T + 1] if price_kind == "close" else c[entry_day:T + 1]
        raw_ret = c[T] / ep - 1
        mdd_raw = min(0.0, float(path.min() / ep - 1))
        # 컷: 진입 이후 처음 성립하는 2일 연속 이탈
        bb = None
        start = entry_day + 1 if price_kind == "close" else entry_day
        for d in range(max(start + 1, t + 2), T + 1):
            if d - 1 >= start and c[d - 1] < Lc and c[d] < Lc:
                bb = d
                break
        if bb is not None:
            cut_ret = c[bb] / ep - 1
            mdd_cut = min(0.0, float(c[entry_day:bb + 1].min() / ep - 1))
        else:
            cut_ret, mdd_cut = raw_ret, mdd_raw
        return {"d": entry_day, "ep": ep, "raw": raw_ret, "cut": cut_ret, "mdd_raw": mdd_raw, "mdd_cut": mdd_cut,
                "cut_fired": bb is not None}

    bh = c[T] / c[t] - 1
    legs = {"A_next_open": leg(t + 1, "open"), "B_crash_close": leg(t, "close"), "C_next_close": leg(t + 1, "close"),
            "D_sig2": leg(s2), "D2_sig2_retest": leg(s2r), "E_breakout5": leg(brk), "E2_breakout5_roll": leg(brk_roll)}
    res = {"t": t, "date": str(px.index[t].date()), "H": H, "bh_crash_close": bh, "bear_day": b,
           "lag": {"sig2": None if s2 is None else s2 - t, "sig2_retest": None if s2r is None else s2r - t,
                   "breakout5": None if brk is None else brk - t}}
    out = {}
    for name, L in legs.items():
        for mode in ("raw", "cut"):
            key = f"{name}|{mode}"
            if L is None or (mode == "cut" and b is not None and L["d"] > b):
                # 미진입 (또는 약세 경로 확정 후라 '신규 진입 중단')
                out[key] = {"ret": 0.0, "entered": False, "mdd": None, "missed_bh": bh, "entry_prem": None, "cut_fired": False}
            else:
                out[key] = {"ret": L[mode], "entered": True, "mdd": L["mdd_" + mode], "missed_bh": None,
                            "entry_prem": L["ep"] / c[t] - 1, "cut_fired": mode == "cut" and L["cut_fired"]}
    # 분할: 50% 신호2 + 50% 5일 고점 돌파 (못 채운 절반은 현금)
    for mode in ("raw", "cut"):
        a, z = out[f"D_sig2|{mode}"], out[f"E_breakout5|{mode}"]
        ent = a["entered"] or z["entered"]
        mdds = [x["mdd"] for x in (a, z) if x["entered"] and x["mdd"] is not None]
        out[f"F_tranche|{mode}"] = {"ret": 0.5 * a["ret"] + 0.5 * z["ret"], "entered": ent,
                                    "mdd": (min(mdds) if mdds else None), "missed_bh": None if ent else bh,
                                    "entry_prem": None, "cut_fired": a["cut_fired"] or z["cut_fired"],
                                    "half_filled": a["entered"] != z["entered"]}
    res["s"] = out
    return res


# ───────────────────────── 3. 통계 ─────────────────────────
def clusters(idx: list[int]) -> list[int]:
    cid, out, last = -1, [], None
    for i in idx:
        if last is None or i - last > CLUSTER_GAP:
            cid += 1
        out.append(cid)
        last = i
    return out


def boot_ci(vals: np.ndarray, cl: np.ndarray, rng, stat=np.mean) -> list[float]:
    u = np.unique(cl)
    groups = [vals[cl == g] for g in u]
    bs = np.empty(NBOOT)
    for k in range(NBOOT):
        pick = rng.integers(0, len(u), len(u))
        bs[k] = stat(np.concatenate([groups[p] for p in pick]))
    return [round(float(np.percentile(bs, 2.5)), 4), round(float(np.percentile(bs, 97.5)), 4)]


def summarize(evs: list[dict], rng) -> dict:
    if not evs:
        return {}
    cl = np.array(clusters([e["t"] for e in evs]))
    keys = list(evs[0]["s"].keys())
    base = np.array([e["s"]["B_crash_close|raw"]["ret"] for e in evs])
    base_open = np.array([e["s"]["A_next_open|raw"]["ret"] for e in evs])
    rows = {}
    for k in keys:
        r = np.array([e["s"][k]["ret"] for e in evs])
        ent = np.array([e["s"][k]["entered"] for e in evs])
        mdd = [e["s"][k]["mdd"] for e in evs if e["s"][k]["mdd"] is not None]
        miss = [e["s"][k]["missed_bh"] for e in evs if e["s"][k]["missed_bh"] is not None]
        prem = [e["s"][k]["entry_prem"] for e in evs if e["s"][k]["entry_prem"] is not None]
        rows[k] = {
            "n": len(r), "entered": int(ent.sum()),
            "mean": round(float(r.mean()), 4), "mean_ci": boot_ci(r, cl, rng),
            "median": round(float(np.median(r)), 4),
            "hit": round(float((r > 0).mean()), 3),
            "hit_if_entered": round(float((r[ent] > 0).mean()), 3) if ent.any() else None,
            "mean_if_entered": round(float(r[ent].mean()), 4) if ent.any() else None,
            "worst": round(float(r.min()), 4),
            "p10": round(float(np.percentile(r, 10)), 4),
            "avg_mdd_after_entry": round(float(np.mean(mdd)), 4) if mdd else None,
            "entry_prem_vs_crash_close": round(float(np.mean(prem)), 4) if prem else None,
            "missed_n": len(miss), "missed_bh_mean": round(float(np.mean(miss)), 4) if miss else None,
            "opp_cost_per_event": round(float(np.sum([max(m, 0) for m in miss]) / len(r)), 4),
            "cut_fired": int(sum(e["s"][k]["cut_fired"] for e in evs)),
            "diff_vs_crash_close": round(float((r - base).mean()), 4), "diff_vs_crash_close_ci": boot_ci(r - base, cl, rng),
            "diff_vs_next_open": round(float((r - base_open).mean()), 4), "diff_vs_next_open_ci": boot_ci(r - base_open, cl, rng),
        }
    lag = {}
    for s in ("sig2", "sig2_retest", "breakout5"):
        v = [e["lag"][s] for e in evs if e["lag"][s] is not None]
        lag[s] = {"fired": len(v), "of": len(evs), "median_lag": float(np.median(v)) if v else None,
                  "lag1_share": round(float(np.mean([x == 1 for x in v])), 3) if v else None}
    return {"n_events": len(evs), "n_clusters": int(cl.max() + 1), "bear_path_n": int(sum(e["bear_day"] is not None for e in evs)),
            "signal_lags": lag, "strategies": rows}


def main() -> dict:
    px = build_proxy()
    real = load_real()
    val = validate(px, real)
    px_raw = px.copy()
    px = calibrate(px, real, val)
    sp = pd.concat([px.loc[px.index < REAL_FROM, ["open", "high", "low", "close"]],
                    real.loc[real.index >= REAL_FROM]]).sort_index()
    # 스플라이스: 실제 지수 구간을 프록시 마지막 레벨에 맞춰 연결 (수익률만 쓰므로 레벨 무관하지만 이어지게)
    first_real = real.index[real.index >= REAL_FROM][0]
    # 첫 실제일 수익률이 이어지도록: 실제 전일 종가 비율로 스케일
    prev_real = real["close"].shift(1).loc[first_real]
    sc = px.loc[px.index < REAL_FROM, "close"].iloc[-1] / prev_real
    sp.loc[sp.index >= REAL_FROM] *= sc
    out = {"asof": str(sp.index.max().date()), "validation": val, "series": {}}
    rng = np.random.default_rng(SEED)
    for sname, ser in (("spliced", sp), ("proxy_only", px[["open", "high", "low", "close"]]),
                       ("proxy_uncalibrated", px_raw[["open", "high", "low", "close"]]), ("real_kospi_only", real)):
        out["series"][sname] = {"from": str(ser.index.min().date()), "to": str(ser.index.max().date())}
        for thr in (-0.03, -0.05):
            ev_idx = events(ser, thr)
            out["series"][sname][f"{int(thr*100)}%"] = {"event_dates": [str(ser.index[i].date()) for i in ev_idx]}
            for H in HORIZONS:
                evs = [x for x in (run_event(ser, i, H) for i in ev_idx) if x]
                summ = summarize(evs, rng)
                firsts = []
                cl = clusters([e["t"] for e in evs])
                seen = set()
                for e, c_ in zip(evs, cl):
                    if c_ not in seen:
                        seen.add(c_)
                        firsts.append(e)
                out["series"][sname][f"{int(thr*100)}%"][f"H{H}"] = {"all": summ, "first_in_cluster": summarize(firsts, rng),
                                                                      "per_event": [{"date": e["date"], "bh": round(e["bh_crash_close"], 4), "bear": e["bear_day"] is not None,
                                                                                     "lag": e["lag"]} for e in evs]}
    OUT_J.parent.mkdir(parents=True, exist_ok=True)
    OUT_J.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return out


if __name__ == "__main__":
    o = main()
    print(json.dumps(o["validation"], ensure_ascii=False, indent=1))
