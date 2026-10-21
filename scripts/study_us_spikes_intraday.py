#!/usr/bin/env python3
"""미국 잡주 폭등 장중 분봉 단타 사건연구 (퀀트, 2026-10-21) — 사전등록 reports/studies/2026-10-21_us_spikes_intraday.md §0.

  python3 scripts/study_us_spikes_intraday.py --data <intraday_dir> --daily <daily_dir>
    <intraday_dir> = study-data/us-spikes-intraday-<run_id> 의 data/study/spikes_intraday
    <daily_dir>    = study-data/us-spikes-39537550959 의 data/study/spikes (일봉 사건 P1 정의·SEC 주식 수)

출력  reports/studies/2026-10-21_us_spikes_intraday.json — md §1~ 은 이 json 을 보고 사람이 적는다.
영향  연구 전용. 어떤 워크플로·탭·알림도 이 json 을 읽지 않는다. 일봉 연구 코드는 import 만(수정 없음).
체결  신호 = 봉 종가 판정 → 다음 봉 시가 진입. 스탑 = min(스탑, 시가)×(1−0.5%) · 목표 = 고가 ≥ 목표×1.0025 · 같은 봉 둘 다 → 스탑.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import study_us_spikes as daily  # noqa: E402  (정의 재사용, 수정 금지 파일)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "studies" / "2026-10-21_us_spikes_intraday.json"
M = 16
ALPHA = 0.05
TRIG, TRIG_VOL = 0.30, 1.0
COMM = 0.001                 # 편도 수수료 [가정]
SPREAD = 0.02                # 왕복 스프레드+슬리피지 [가정, 1차]
SHORT_X = 0.005              # 숏 로케이트/차입 건당 [가정]
STOP_SLIP = 0.005
TP_THRU = 0.0025
STRATS = ["ORB5", "ORB15", "VWAPR", "VWAPL", "FPB", "FADE", "HALT_L", "HALT_S"]
SHORTS = {"VWAPL", "FADE", "HALT_S"}
TP_GRID = [0.05, 0.10, 0.15, 0.20, 0.30, 0.40, None]
SL_GRID = [0.03, 0.05, 0.08, 0.12, 0.20, "rule"]
RTH_FIRST, RTH_LAST = "09:30", "15:55"


def rt_cost(side: str, spread: float = SPREAD) -> float:
    return spread + 2 * COMM + (SHORT_X if side == "S" else 0.0)


# ───────── 세션 ─────────
class Sess:
    """정규장 5분봉 한 세션. 배열 o,h,l,c,v · hm('HH:MM') · vwap(누적)."""

    def __init__(self, df: pd.DataFrame):
        df = df.sort_values("ts")
        hm = df["ts"].dt.strftime("%H:%M").to_numpy()
        r = (hm >= RTH_FIRST) & (hm <= RTH_LAST)
        self.pre = df[hm < RTH_FIRST]
        d = df[r]
        self.ts = d["ts"].to_numpy()
        self.hm = hm[r]
        self.o, self.h, self.l, self.c, self.v = (d[k].to_numpy(float) for k in "ohlcv")
        tp = (self.h + self.l + self.c) / 3
        cv = np.cumsum(self.v)
        with np.errstate(invalid="ignore", divide="ignore"):
            self.vwap = np.where(cv > 0, np.cumsum(tp * self.v) / cv, self.c)
        self.n = len(self.c)


def first_idx(hm: np.ndarray, at: str) -> int | None:
    k = np.flatnonzero(hm >= at)
    return int(k[0]) if len(k) else None


def signal(S: Sess, strat: str, k0: int, halt: dict | None = None):
    """(신호 봉 index, 전략 손절가, 방향) 또는 None. 신호 봉은 index ≥ k0 (T0 이후 종가)만."""
    if S.n < 3 or S.hm[0] != RTH_FIRST:
        return None
    o, h, l, c = S.o, S.h, S.l, S.c
    if strat in ("ORB5", "ORB15"):
        w = 1 if strat == "ORB5" else 3
        if S.n <= w or S.hm[w - 1] > ("09:30" if w == 1 else "09:40"):
            return None
        orh, orl = h[:w].max(), l[:w].min()
        for i in range(max(k0, w), S.n - 1):
            if c[i] > orh:
                return i, orl, "L"
        return None
    if strat == "VWAPR":
        dip = None
        for i in range(k0, S.n - 1):
            if dip is None and c[i] < S.vwap[i]:
                dip = i
            elif dip is not None and c[i] > S.vwap[i]:
                return i, l[dip:i + 1].min(), "L"
        return None
    if strat == "VWAPL":
        for i in range(max(k0, 1), S.n - 1):
            if c[i - 1] >= S.vwap[i - 1] and c[i] < S.vwap[i]:
                return i, h[:i + 1].max(), "S"
        return None
    if strat == "FPB":
        pb = None
        for i in range(max(k0, 1), S.n - 1):
            hod = h[:i + 1].max()
            if pb is None and l[i] <= hod * 0.90:
                pb = i
            elif pb is not None and c[i] > h[i - 1]:
                return i, l[pb:i + 1].min(), "L"
        return None
    if strat == "FADE":
        for i in range(k0, S.n - 1):
            hod = h[:i + 1].max()
            if c[i] <= hod * 0.85:
                return i, hod, "S"
        return None
    if strat in ("HALT_L", "HALT_S") and halt is not None:
        r = halt["r"]
        if r < k0 or r >= S.n - 1:
            return None
        if strat == "HALT_L":
            return r, l[r], "L"
        return r, max(h[r], h[:r + 1].max()), "S"
    return None


def simulate(S: Sess, i_sig: int, side: str, stop_px: float | None, tp_pct: float | None,
             sl_pct: float | None) -> dict | None:
    """신호 봉 i_sig 다음 봉 시가 진입 → 브래킷(목표·스탑) → 15:55 봉 종가 청산. 수익은 비용 전(gross)."""
    e = i_sig + 1
    if e >= S.n:
        return None
    px = S.o[e]
    if not np.isfinite(px) or px <= 0:
        return None
    sgn = 1 if side == "L" else -1
    stop = px * (1 - sgn * sl_pct) if sl_pct is not None else stop_px
    tp = px * (1 + sgn * tp_pct) if tp_pct is not None else None
    for j in range(e, S.n):
        oj, hj, lj = S.o[j], S.h[j], S.l[j]
        if side == "L":
            if stop is not None and (oj <= stop or lj <= stop):
                x, why = min(stop, oj) * (1 - STOP_SLIP), "stop"
            elif tp is not None and j > e and oj >= tp:
                x, why = oj, "tp"
            elif tp is not None and hj >= tp * (1 + TP_THRU):
                x, why = tp, "tp"
            else:
                continue
        else:
            if stop is not None and (oj >= stop or hj >= stop):
                x, why = max(stop, oj) * (1 + STOP_SLIP), "stop"
            elif tp is not None and j > e and oj <= tp:
                x, why = oj, "tp"
            elif tp is not None and lj <= tp * (1 - TP_THRU):
                x, why = tp, "tp"
            else:
                continue
        return {"e": e, "entry": px, "exit": x, "why": why, "gross": sgn * (x / px - 1), "bars": j - e + 1}
    x = S.c[S.n - 1]
    return {"e": e, "entry": px, "exit": x, "why": "eod", "gross": sgn * (x / px - 1), "bars": S.n - e}


def range_proxy(S: Sess, e: int) -> float:
    a = max(0, e - 6)
    seg = (S.h[a:e] - S.l[a:e]) / S.c[a:e]
    return float(np.nanmedian(seg) * 0.5) if len(seg) else float("nan")


# ───────── 정지 ─────────
def find_halt(S: Sess, hrows: pd.DataFrame | None, k0: int) -> tuple[dict | None, str]:
    """T0 이후 첫 '상승' 정지의 재개 봉 index r. RSS(LUDP) 우선(hrows 가 None 이 아니면 RSS 수집 성공 — 빈 표 = 정지 없음),
    RSS 수집 자체가 실패(None)면 정규장 봉 공백 ≥10분 대리."""
    tmin = pd.to_datetime(S.ts)
    if hrows is not None:
        for hr in hrows.sort_values("halt_time").itertuples():
            if hr.reason != "LUDP" or not isinstance(hr.halt_time, str) or not isinstance(hr.resume_trade, str):
                continue
            ht, rt = hr.halt_time[:5], hr.resume_trade[:5]
            hb = np.flatnonzero(S.hm <= ht)
            if not len(hb):
                continue
            hi = int(hb[-1])
            if hi < k0 or hi < 3 or S.c[hi] <= S.c[hi - 3]:
                continue
            rb = np.flatnonzero(S.hm >= f"{rt[:3]}{int(rt[3:5]) // 5 * 5:02d}")
            if not len(rb):
                continue
            return {"r": int(rb[0]), "src": "rss"}, "rss"
        return None, "rss"
    gaps = np.diff(tmin.values).astype("timedelta64[m]").astype(int)
    for g in np.flatnonzero(gaps >= 10):
        hi = int(g)
        if hi >= k0 and hi >= 3 and S.c[hi] > S.c[hi - 3]:
            return {"r": hi + 1, "src": "gap"}, "gap"
    return None, "gap"


# ───────── 모집단 ─────────
def mcap_map(daily_dir: Path, keys: pd.DataFrame) -> pd.Series:
    try:
        st = json.loads((daily_dir / "sec_tickers.json").read_text(encoding="utf-8"))
        t2c = {v["ticker"].upper().replace(".", "-"): int(v["cik_str"]) for v in st.values()}
        Sh = pd.read_csv(daily_dir / "sec_shares.csv").dropna()
        Sh["cik"] = Sh["cik"].astype(int)
        Sh["end"] = pd.to_datetime(Sh["end"])
    except FileNotFoundError:
        return pd.Series(np.nan, index=keys.index)
    X = keys.copy()
    X["cik"] = X["yf"].str.upper().map(t2c)
    X["dt"] = pd.to_datetime(X["d0"])
    Y = X.dropna(subset=["cik"]).copy()
    Y["cik"] = Y["cik"].astype(int)
    Y = Y.reset_index().sort_values("dt")
    J = pd.merge_asof(Y, Sh.sort_values("end"), left_on="dt", right_on="end", by="cik", direction="backward",
                      tolerance=pd.Timedelta(days=450)).set_index("index")
    return J["val"].reindex(keys.index)


def cooldown(df: pd.DataFrame, col: str = "d0") -> pd.DataFrame:
    keep = []
    for _, g in df.sort_values(col).groupby("yf"):
        last = None
        for i, d in zip(g.index, g[col]):
            if last is None or np.busday_count(last, d) > daily.COOL:
                keep.append(i)
                last = d
    return df.loc[sorted(keep)]


def build(data: Path, ddir: Path) -> dict:
    C = pd.read_csv(data / "cand_daily.csv", keep_default_na=False, na_values=[""])
    B = pd.read_parquet(data / "bars5.parquet")
    B["ts"] = pd.to_datetime(B["ts"])
    B["day"] = B["ts"].dt.strftime("%Y-%m-%d")
    try:
        H = pd.read_csv(data / "halts.csv", dtype=str)
    except (FileNotFoundError, pd.errors.EmptyDataError):
        H = pd.DataFrame(columns=["yf", "date", "reason", "halt_time", "resume_quote", "resume_trade"])
    groups = {k: g for k, g in B.groupby(["yf", "day"])}
    first_day = B["day"].min() if len(B) else None
    last_day = B["day"].max() if len(B) else None
    C["raw_m1"] = C["pc"] * C["raw_f_m1"]
    C["shares"] = mcap_map(ddir, C[["yf", "d0"]])
    C["mcap"] = C["shares"] * C["raw_m1"]
    base = C[C.raw_m1.between(daily.PX_LO, daily.PX_HI) & (C.n_hist >= daily.MIN_HIST)
             & ((C.mcap < daily.MCAP_HI) | C.mcap.isna())]
    base = base[base.d0 >= first_day] if first_day else base
    # P0: 실시간 트리거
    p0 = []
    for r in base.itertuples():
        g = groups.get((r.yf, r.d0))
        if g is None:
            continue
        S = Sess(g)
        if S.n < 3 or S.hm[0] != RTH_FIRST:
            continue
        cv = np.cumsum(S.v)
        ok = np.flatnonzero((S.c >= r.pc * (1 + TRIG)) & (cv >= TRIG_VOL * r.vol20) & (S.hm <= "15:45"))
        if len(ok):
            p0.append({"yf": r.yf, "d0": r.d0, "k0": int(ok[0]), "t0": S.hm[ok[0]], "pc": r.pc, "vol20": r.vol20})
    P0 = cooldown(pd.DataFrame(p0)) if p0 else pd.DataFrame(columns=["yf", "d0", "k0"])
    # P1: 일봉 정의 사건의 D+1
    L = daily.load(ddir)
    s = daily.select(L["W"])
    s["d0"] = pd.to_datetime(s["d0"]).dt.strftime("%Y-%m-%d")
    nxt = C.set_index(["yf", "d0"])["d1"].to_dict()
    p1 = []
    for r in s[s.d0 >= (first_day or "9999")].itertuples():
        d1 = nxt.get((r.yf, r.d0))
        if isinstance(d1, str) and d1 and d1 <= last_day and (r.yf, d1) in groups:
            p1.append({"yf": r.yf, "d0": r.d0, "d1": d1, "ret0": r.ret0, "k0": 0})
    P1 = pd.DataFrame(p1)
    return {"C": C, "base": base, "P0": P0, "P1": P1, "groups": groups, "H": H, "E": s,
            "window": [first_day, last_day]}


def run_trades(ctx: dict, pop: str, strat: str, tp, sl) -> pd.DataFrame:
    P = ctx["P0"] if pop == "P0" else ctx["P1"]
    day_col = "d0" if pop == "P0" else "d1"
    rows = []
    for r in P.itertuples():
        day = getattr(r, day_col)
        S = Sess(ctx["groups"][(r.yf, day)])
        halt = None
        if strat.startswith("HALT"):
            hr = ctx["H"][(ctx["H"].yf == r.yf) & (ctx["H"].date == day)] if len(ctx["H"]) else None
            halt, _ = find_halt(S, hr, r.k0)
            if halt is None:
                continue
        sg = signal(S, strat, r.k0, halt)
        if sg is None:
            continue
        i, stop_px, side = sg
        t = simulate(S, i, side, stop_px if sl == "rule" else None, tp, None if sl == "rule" else sl)
        if t is None:
            continue
        t.update({"yf": r.yf, "day": day, "side": side, "sig": S.hm[i], "proxy": range_proxy(S, t["e"])})
        t["net"] = t["gross"] - rt_cost(side)
        rows.append(t)
    return pd.DataFrame(rows)


def stats(T: pd.DataFrame, col: str = "net") -> dict:
    if not len(T):
        return {"n": 0}
    d = daily.describe(T[col])
    g = T.groupby("day")[col].mean().sort_index()
    t = daily.nw_t(g.to_numpy())
    d.update({"days": int(len(g)), "t": round(t, 3) if np.isfinite(t) else None,
              "p": round(daily.p_one(t), 5) if np.isfinite(t) else None})
    if d.get("avg_win") is not None and d.get("avg_loss"):
        d["payoff"] = round(-d["avg_win"] / d["avg_loss"], 3)
    return d


def grade(st: dict) -> str:
    if st.get("n", 0) < 30:
        return "검증전"
    p = st.get("p")
    if p is not None and p < 0.10 and st["median"] > 0:
        return "C(가설-강)" if p < ALPHA / M else "C"
    return "F"


def bracket(ctx: dict, pop: str, strat: str) -> dict:
    cells = {}
    days = None
    for a, tp in enumerate(TP_GRID):
        for b, sl in enumerate(SL_GRID):
            T = run_trades(ctx, pop, strat, tp, sl)
            cells[(a, b)] = T
            if days is None and len(T):
                days = sorted(T["day"].unique())
    if not days or len(days) < 6:
        return {"n_days": len(days or []), "note": "표본 부족"}
    cut = days[int(len(days) * 2 / 3)]
    tr = {k: (T[T.day < cut]["net"] if len(T) else pd.Series(dtype=float)) for k, T in cells.items()}
    mean = {k: (x.mean() if len(x) >= 10 else np.nan) for k, x in tr.items()}
    score = {}
    for (a, b) in cells:
        nb = [mean[(a + i, b + j)] for i in (-1, 0, 1) for j in (-1, 0, 1)
              if (a + i, b + j) in mean and np.isfinite(mean[(a + i, b + j)])]
        score[(a, b)] = np.mean(nb) if np.isfinite(mean[(a, b)]) and nb else np.nan
    ok = {k: v for k, v in score.items() if np.isfinite(v)}
    if not ok:
        return {"n_days": len(days), "note": "학습 n<10"}
    best = max(ok, key=ok.get)
    peak = max((k for k in mean if np.isfinite(mean[k])), key=lambda k: mean[k])
    T = cells[best]
    surf = [[None if not np.isfinite(mean[(a, b)]) else round(float(mean[(a, b)]), 4) for b in range(len(SL_GRID))]
            for a in range(len(TP_GRID))]
    lab = lambda k: {"tp": TP_GRID[k[0]], "sl": SL_GRID[k[1]]}
    return {"cut": cut, "train_days": sum(d < cut for d in days), "test_days": sum(d >= cut for d in days),
            "pick": lab(best), "pick_train_mean": round(float(mean[best]), 4), "pick_plateau": round(float(ok[best]), 4),
            "peak": lab(peak), "peak_train_mean": round(float(mean[peak]), 4),
            "test": stats(T[T.day >= cut]) if len(T) else {"n": 0},
            "peak_test": stats(cells[peak][cells[peak].day >= cut]) if len(cells[peak]) else {"n": 0},
            "train_surface": surf}


def descriptives(ctx: dict) -> dict:
    out = {}
    E, groups = ctx["E"], ctx["groups"]
    w0 = ctx["window"][0] or "9999"
    pre_hi, pre_vs, gap_pre, cdiff = [], [], [], []
    for r in E[E.d0 >= w0].itertuples():
        g = groups.get((r.yf, r.d0))
        if g is None:
            continue
        S = Sess(g)
        if S.n < 3:
            continue
        if len(S.pre):
            pre_hi.append(float(S.pre["h"].max() > S.h.max()))
            pre_vs.append(float(S.pre["v"].sum() / max(S.v.sum() + S.pre["v"].sum(), 1)))
            gap_pre.append(float(S.pre["h"].max() / r.cm1 - 1 >= 0.30))
        else:
            pre_hi.append(0.0)
        if S.hm[-1] == RTH_LAST:
            cdiff.append(abs(S.c[-1] / r.c0 - 1))
    out["E_daily_D0_with_bars"] = len(pre_hi)
    out["premarket_high_above_RTH_high"] = round(float(np.mean(pre_hi)), 3) if pre_hi else None
    out["premarket_volume_share_median"] = round(float(np.median(pre_vs)), 3) if pre_vs else None
    out["premarket_touch30"] = round(float(np.mean(gap_pre)), 3) if gap_pre else None
    out["daily_close_vs_5m_last_close_absdiff_median"] = round(float(np.median(cdiff)), 4) if cdiff else None
    P0, P1 = ctx["P0"], ctx["P1"]
    ek = set(zip(E.yf, E.d0))
    out["P0_n"] = int(len(P0))
    out["P0_in_E_daily"] = int(sum((a, b) in ek for a, b in zip(P0.yf, P0.d0))) if len(P0) else 0
    out["P0_trigger_time_hist"] = P0["t0"].str[:2].value_counts().sort_index().to_dict() if len(P0) else {}
    out["P1_n"] = int(len(P1))
    out["E_daily_in_window"] = int((E.d0 >= w0).sum())
    out["candidate_days"] = int(len(ctx["C"]))
    out["base_after_filters"] = int(len(ctx["base"]))
    out["halts_rows"] = int(len(ctx["H"]))
    return out


def baselines(ctx: dict) -> dict:
    res = {}
    for name, pop, side in (("P0_trigger_long_eod", "P0", "L"), ("P1_open_long_eod", "P1", "L"),
                            ("P1_open_short_eod", "P1", "S")):
        P = ctx[pop]
        col = "d0" if pop == "P0" else "d1"
        rows = []
        for r in P.itertuples():
            S = Sess(ctx["groups"][(r.yf, getattr(r, col))])
            i = r.k0 if pop == "P0" else -1
            t = simulate(S, i, side, None, None, None)
            if t:
                t.update({"day": getattr(r, col), "net": t["gross"] - rt_cost(side)})
                rows.append(t)
        res[name] = stats(pd.DataFrame(rows))
    return res


def run(data: Path, ddir: Path) -> dict:
    ctx = build(data, ddir)
    hyps, sens, brk = [], {}, {}
    for pop in ("P0", "P1"):
        for st in STRATS:
            T = run_trades(ctx, pop, st, None, "rule")
            s = stats(T)
            hid = f"{pop}_{st}"
            row = {"id": hid, "pop": pop, "strat": st, **s, "grade": grade(s)}
            if len(T):
                row["exit_mix"] = T["why"].value_counts().to_dict()
                row["gross_mean"] = round(float(T["gross"].mean()), 4)
                row["proxy_rt_spread_median"] = round(float(T["proxy"].median()), 4)
                side = T["side"].iloc[0]
                sens[hid] = {f"spread{int(sp * 100)}": round(float((T["gross"] - rt_cost(side, sp)).mean()), 4)
                             for sp in (0.01, 0.02, 0.04)}
                sens[hid]["proxy"] = round(float((T["gross"] - T["proxy"] - rt_cost(side, 0.0)).mean()), 4)
                sens[hid]["fx"] = round(float((T["gross"] - rt_cost(side) - 0.002).mean()), 4)
                sens[hid]["worst_trades"] = T.nsmallest(3, "net")[["yf", "day", "net"]].round(4).to_dict("records")
            hyps.append(row)
            brk[hid] = bracket(ctx, pop, st)
    return {"generated": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"), "window": ctx["window"],
            "prereg": {"m": M, "alpha": ALPHA, "bonf": ALPHA / M, "cost_long_rt": rt_cost("L"), "cost_short_rt": rt_cost("S"),
                       "grid_cells": len(TP_GRID) * len(SL_GRID), "grid_trials": len(TP_GRID) * len(SL_GRID) * M},
            "desc": descriptives(ctx), "baselines": baselines(ctx), "hypotheses": hyps, "sensitivity": sens,
            "bracket": brk, "m": M}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--daily", required=True)
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()
    res = run(Path(a.data), Path(a.daily))
    Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    for h in res["hypotheses"]:
        print(h["id"], h.get("n"), h.get("mean"), h.get("median"), h.get("win"), h.get("p"), h["grade"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
