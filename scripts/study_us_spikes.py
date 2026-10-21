#!/usr/bin/env python3
"""미국 소형주 하루 급등 뒤 롱 편승 vs 숏 사건연구 (퀀트, 2026-10-21) — 사전등록 reports/studies/2026-10-21_us_smallcap_spikes.md §0.

  python3 scripts/study_us_spikes.py --data <dir>     # <dir> = study-data/us-spikes-<run_id> 브랜치의 data/study/spikes

입력  events.parquet·meta.csv·elig_days.csv·bench.csv·sec_shares.csv·sec_tickers.json·form25.csv·borrow.csv·halts.csv
      (scripts/fetch_us_spikes.py 산출, Actions 전용 수집 — 원자료는 main 에 없다)
출력  reports/studies/2026-10-21_us_smallcap_spikes.json — md §1~ 은 이 json 을 보고 사람이 적는다.
영향  연구 전용. 어떤 워크플로·탭·알림도 이 json 을 읽지 않는다.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "studies" / "2026-10-21_us_smallcap_spikes.json"
IS_END = "2019-12-31"
M = 6
ALPHA = 0.05
COST = 0.01           # 왕복 [가정]
B1 = 0.50             # 1차 차입 수수료(연)
STOP1 = 0.30
COOL = 20
PX_LO, PX_HI, MCAP_HI, VM, MIN_HIST = 1.0, 20.0, 2e9, 5.0, 60
TIERS = {"T30": 0.30, "T50": 0.50, "T100": 1.00}
SPAC = r"Acquisition|SPAC|Merger Corp|Capital Corp\.? [IVX]+"
ADR = r"American Depositary|American Depository|\bADS\b|ADR"


# ───────── 검정 ─────────
def nw_t(x: np.ndarray, lag: int = 1) -> float:
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 3:
        return float("nan")
    e = x - x.mean()
    s = (e @ e) / n
    for L in range(1, lag + 1):
        s += 2 * (1 - L / (lag + 1)) * (e[L:] @ e[:-L]) / n
    return float(x.mean() / math.sqrt(s / n)) if s > 0 else float("nan")


def p_one(t: float) -> float:
    return float(0.5 * math.erfc(t / math.sqrt(2))) if np.isfinite(t) else float("nan")


def monthly_test(d0: pd.Series, r: pd.Series) -> dict:
    ok = r.notna()
    g = r[ok].groupby(d0[ok].str[:7]).mean()
    t = nw_t(g.to_numpy())
    return {"months": int(len(g)), "t": round(t, 3) if np.isfinite(t) else None, "p": round(p_one(t), 5) if np.isfinite(t) else None}


def describe(r: pd.Series) -> dict:
    x = r.dropna().to_numpy()
    if not len(x):
        return {"n": 0}
    q = np.percentile(x, [1, 5, 25, 50, 75, 95, 99])
    return {"n": int(len(x)), "mean": round(float(x.mean()), 4), "median": round(float(q[3]), 4),
            "win": round(float((x > 0).mean()), 4), "p01": round(float(q[0]), 4), "p05": round(float(q[1]), 4),
            "p25": round(float(q[2]), 4), "p75": round(float(q[4]), 4), "p95": round(float(q[5]), 4),
            "p99": round(float(q[6]), 4), "min": round(float(x.min()), 4), "max": round(float(x.max()), 4),
            "avg_win": round(float(x[x > 0].mean()), 4) if (x > 0).any() else None,
            "avg_loss": round(float(x[x <= 0].mean()), 4) if (x <= 0).any() else None}


# ───────── 사건 표 ─────────
def wide(E: pd.DataFrame) -> pd.DataFrame:
    E = E[(E.k >= -1) & (E.k <= 20)]
    W = E.pivot_table(index=["yf", "d0"], columns="k", values=["open", "high", "low", "close"], aggfunc="first")
    W.columns = [f"{a[0]}{b}" for a, b in [(c[0][0], c[1]) for c in W.columns]]
    first = E[E.k == 0].set_index(["yf", "d0"])[["volume", "vol20", "n_hist"]]
    rf = E[E.k == -1].set_index(["yf", "d0"])["raw_f"].rename("raw_f_m1")
    return W.join(first).join(rf).reset_index()


def short_ret(W: pd.DataFrame, h: int, stop: float | None, b: float) -> pd.Series:
    o1 = W["o1"].to_numpy()
    exit_px = np.full(len(W), np.nan)
    exit_k = np.full(len(W), np.nan)
    done = np.zeros(len(W), bool)
    for k in range(1, h + 1):
        ok_, hk, ck = W[f"o{k}"].to_numpy(), W[f"h{k}"].to_numpy(), W[f"c{k}"].to_numpy()
        if stop is not None:
            thr = o1 * (1 + stop)
            gap = (~done) & (k > 1) & (ok_ >= thr)
            exit_px[gap], exit_k[gap] = ok_[gap], k
            done |= gap
            hit = (~done) & (hk >= thr)
            exit_px[hit], exit_k[hit] = thr[hit], k
            done |= hit
        if k == h:
            rest = ~done
            exit_px[rest], exit_k[rest] = ck[rest], k
    r = -(exit_px / o1 - 1) - COST - b * exit_k / 252
    r[~np.isfinite(W[f"c{h}"].to_numpy()) & ~done] = np.nan
    return pd.Series(r, index=W.index)


def load(d: Path) -> dict:
    E = pd.read_parquet(d / "events.parquet")
    meta = pd.read_csv(d / "meta.csv", keep_default_na=False)
    W = wide(E)
    W = W.rename(columns={f"{a}-1": f"{a}m1" for a in "ohlc"})
    W["ret0"] = W["c0"] / W["cm1"] - 1
    W["vm"] = W["volume"] / W["vol20"]
    W["raw_m1"] = W["cm1"] * W["raw_f_m1"]
    W["gap_share"] = np.log(W["o0"] / W["cm1"]) / np.log(W["c0"] / W["cm1"])
    W = W.merge(meta[["yf", "name", "market", "last"]], on="yf", how="left")
    W["spac"] = W["name"].astype(str).str.contains(SPAC, case=False, regex=True)
    W["adr"] = W["name"].astype(str).str.contains(ADR, case=False, regex=True)
    # 시총: SEC shares 스냅숏(D0 이전 최근, 450일 이내) × D−1 원가격
    W["mcap"] = np.nan
    try:
        st = json.loads((d / "sec_tickers.json").read_text(encoding="utf-8"))
        t2c = {v["ticker"].upper().replace(".", "-"): int(v["cik_str"]) for v in st.values()}
        S = pd.read_csv(d / "sec_shares.csv").dropna()
        S["cik"] = S["cik"].astype(int)
        S["end"] = pd.to_datetime(S["end"])
        W["cik"] = W["yf"].str.upper().map(t2c)
        X = W[["yf", "d0", "cik"]].dropna().copy()
        X["cik"] = X["cik"].astype(int)
        X["dt"] = pd.to_datetime(X["d0"])
        X = X.sort_values("dt")
        S = S.sort_values("end")
        J = pd.merge_asof(X, S, left_on="dt", right_on="end", by="cik", direction="backward",
                          tolerance=pd.Timedelta(days=450))
        sh = J.set_index(["yf", "d0"])["val"]
        W["shares"] = pd.Series(list(zip(W.yf, W.d0))).map(sh.to_dict()).to_numpy()
        W["mcap"] = W["shares"] * W["raw_m1"]
    except FileNotFoundError as e:
        print(f"시총 없음: {e}")
    return {"W": W, "meta": meta, "dir": d}


def select(W: pd.DataFrame, thr: float = 0.30, mcap_known: bool = False) -> pd.DataFrame:
    s = W[(W.ret0 >= thr) & (W.vm >= VM) & W.raw_m1.between(PX_LO, PX_HI) & (W.n_hist >= MIN_HIST)]
    s = s[(s.mcap < MCAP_HI) | (s.mcap.isna() & (not mcap_known))]
    # 쿨다운: 같은 종목 직전 채택 사건과 20영업일 이내면 버림
    keep = []
    for yf, g in s.sort_values("d0").groupby("yf"):
        last = None
        for i, d0 in zip(g.index, g.d0):
            if last is None or np.busday_count(last, d0) > COOL:
                keep.append(i)
                last = d0
    return s.loc[sorted(keep)].sort_values(["d0", "yf"]).reset_index(drop=True)


def add_returns(s: pd.DataFrame) -> pd.DataFrame:
    s = s.copy()
    s["L1"] = s.c1 / s.c0 - 1 - COST
    s["L5"] = s.c5 / s.c0 - 1 - COST
    s["L1_gross"] = s.c1 / s.c0 - 1
    s["L5_gross"] = s.c5 / s.c0 - 1
    s["L5_o1"] = s.c5 / s.o1 - 1 - COST
    s["gapD1"] = s.o1 / s.c0 - 1
    s["S5_gross"] = -(s.c5 / s.o1 - 1)
    s["S20_gross"] = -(s.c20 / s.o1 - 1)
    s["S5"] = short_ret(s, 5, None, B1)
    s["S20"] = short_ret(s, 20, None, B1)
    s["S5_stop30"] = short_ret(s, 5, STOP1, B1)
    s["S5_b100"] = short_ret(s, 5, None, 1.0)
    hi = s[[f"h{k}" for k in range(1, 21)]].max(axis=1)
    s["max_up20"] = hi / s.o1 - 1
    s["IS"] = s.d0 <= IS_END
    return s


def grade(is_p, oos_mean, oos_p, n_is) -> str:
    if n_is < 100:
        return "검증전"
    if is_p is not None and is_p < ALPHA / M:
        g = "A" if (oos_mean is not None and oos_mean > 0 and oos_p is not None and oos_p < 0.10) else "B"
        return "B" if g == "A" else g  # 상한 B (§0: 생존편향·숏 실행 가능성 미검증)
    if is_p is not None and is_p < 0.10:
        return "C"
    return "F"


def hyp_table(s: pd.DataFrame, s100: pd.DataFrame) -> list[dict]:
    H = [("H1", "롱 L1 (D0 종가→D+1 종가, 비용 1%)", s, "L1"),
         ("H2", "롱 L5 (D0 종가→D+5 종가, 비용 1%)", s, "L5"),
         ("H3", "숏 S5 손절 없음 (D+1 시가→D+5, b=50%)", s, "S5"),
         ("H4", "숏 S20 손절 없음 (D+1 시가→D+20, b=50%)", s, "S20"),
         ("H5", "숏 S5 손절 +30% (b=50%)", s, "S5_stop30"),
         ("H6", "T100 숏 S5 손절 없음 (b=100%)", s100, "S5_b100")]
    rows = []
    for hid, lab, df, col in H:
        a, i, o = df, df[df.IS], df[~df.IS]
        ti, to = monthly_test(i.d0, i[col]), monthly_test(o.d0, o[col])
        di, do = describe(i[col]), describe(o[col])
        rows.append({"id": hid, "label": lab, "col": col, "all": describe(a[col]), "is": di, "oos": do,
                     "is_test": ti, "oos_test": to, "all_test": monthly_test(a.d0, a[col]),
                     "grade": grade(ti["p"], do.get("mean"), to["p"], di["n"])})
    return rows


def sens(s: pd.DataFrame) -> dict:
    out = {}
    for b in (0.0, 0.2, 0.5, 1.0, 3.0):
        for stop in (None, 0.15, 0.30, 0.50, 1.00):
            for h in (5, 20):
                r = short_ret(s, h, stop, b)
                out[f"S{h}_stop{'none' if stop is None else int(stop * 100)}_b{int(b * 100)}"] = {
                    "mean": round(float(r.mean()), 4), "median": round(float(r.median()), 4),
                    "win": round(float((r > 0).mean()), 4), "n": int(r.notna().sum())}
    return out


def no_borrow(s: pd.DataFrame, col: str = "S5") -> dict:
    r = s[col].dropna().sort_values(ascending=False)
    out = {}
    for k in (0, 10, 25, 50):
        x = r.iloc[int(len(r) * k / 100):]
        out[f"drop_best_{k}pct"] = {"mean": round(float(x.mean()), 4), "median": round(float(x.median()), 4), "n": int(len(x))}
    return out


def by_year(s: pd.DataFrame, elig: pd.DataFrame | None) -> list[dict]:
    rows = []
    for y, g in s.groupby(s.d0.str[:4]):
        e = None
        if elig is not None:
            m = elig[elig.year == int(y)]
            e = int(m.elig_days.iloc[0]) if len(m) else None
        rows.append({"year": y, "n": int(len(g)), "elig_days": e,
                     "rate_per_10k": round(len(g) / e * 1e4, 2) if e else None,
                     "L5_mean": round(float(g.L5.mean()), 4), "L5_median": round(float(g.L5.median()), 4),
                     "S5_mean": round(float(g.S5.mean()), 4), "S20_mean": round(float(g.S20.mean()), 4),
                     "S20_median": round(float(g.S20.median()), 4)})
    return rows


def surv(s: pd.DataFrame, d: Path, meta: pd.DataFrame) -> dict:
    out = {}
    try:
        f = pd.read_csv(d / "form25.csv")
        f["n"] = f.get("25", 0) + f.get("25-NSE", 0)
        yr = f.groupby("year")["n"].sum()
        out["form25_by_year"] = {int(k): int(v) for k, v in yr.items()}
        alive = {}
        mf = pd.to_datetime(meta["first"], errors="coerce")
        for y in range(2012, 2027):
            S_y = int((mf <= pd.Timestamp(f"{y}-12-31")).sum())
            D_y = int(yr[yr.index >= y].sum())
            alive[y] = {"survivors_listed": S_y, "form25_since": D_y,
                        "phi_upper": round(D_y / (S_y + D_y), 3) if S_y + D_y else None}
        out["phi_by_year"] = alive
        w = sum(alive[int(y)]["phi_upper"] * n for y, n in s.d0.str[:4].value_counts().items() if int(y) in alive)
        phi = w / len(s)
        out["phi_event_weighted"] = round(phi, 3)
        # 대리 집단: 사건 뒤 순(純) 역분할을 한 종목(raw_f_m1<1) = 상장 유지 기준 미달로 버틴 '반쯤 죽은 생존자'.
        # 상장폐지돼 빠진 사건은 이 집단과 같거나 더 나쁘다고 [가정] → 보정 = (1−φ)·관측 + φ·대리집단.
        # 대리 표시는 사후 정보(미래 역분할)라 신호로 못 쓴다 — 편향 크기 추정 전용.
        sc = {}
        dis = s.raw_f_m1 < 1
        out["distress_proxy_share"] = round(float(dis.mean()), 3)
        cols = ("L1", "L5", "S5", "S20")
        for nm, g, dg in (("T30", s, dis), ("T100", s[s.ret0 >= 1.0], dis[s.ret0 >= 1.0])):
            obs = {c: float(g[c].mean()) for c in cols}
            prox = {c: float(g[dg][c].mean()) for c in cols}
            out[f"distress_{nm}"] = {"n": int(dg.sum()), **{c: round(prox[c], 4) for c in cols},
                                    "healthy": {c: round(float(g[~dg][c].mean()), 4) for c in cols}}
            for ph in (0.2, 0.4, 0.6):
                sc[f"{nm}_phi{ph:.1f}"] = {c: round((1 - ph) * obs[c] + ph * prox[c], 4) for c in cols}
        out["scenarios"] = sc
    except FileNotFoundError as e:
        out["error"] = f"데이터 없음({e})"
    return out


def borrow_halts(s: pd.DataFrame, d: Path) -> dict:
    out = {}
    try:
        B = pd.read_csv(d / "borrow.csv")
        if len(B):
            B = B.dropna(subset=["fee"]).sort_values("date")
            X = s[["yf", "d0", "S5_gross"]].copy()
            X["dt"] = pd.to_datetime(X.d0)
            B["dt"] = pd.to_datetime(B.date)
            J = pd.merge_asof(X.sort_values("dt"), B.sort_values("dt"), on="dt", by="yf", direction="backward",
                              tolerance=pd.Timedelta(days=5)).dropna(subset=["fee"])
            fee = J["fee"].astype(float) / 100
            avail = pd.to_numeric(J["available"], errors="coerce")
            r = J["S5_gross"] - COST - fee * 5 / 252
            out["borrow"] = {"matched_events": int(len(J)), "fee_median": round(float(fee.median()), 4),
                             "fee_p75": round(float(fee.quantile(.75)), 4), "fee_p95": round(float(fee.quantile(.95)), 4),
                             "fee_ge_100pct": round(float((fee >= 1).mean()), 4),
                             "avail_zero_share": round(float((avail <= 0).mean()), 4),
                             "S5_real_fee_mean": round(float(r.mean()), 4),
                             "S5_real_fee_mean_avail_only": round(float(r[avail > 0].mean()), 4) if (avail > 0).any() else None,
                             "S5_real_fee_median": round(float(r.median()), 4)}
        else:
            out["borrow"] = {"error": "데이터 없음(iborrowdesk 수집 0행)"}
    except FileNotFoundError:
        out["borrow"] = {"error": "데이터 없음(파일 없음)"}
    try:
        Hh = pd.read_csv(d / "halts.csv")
        base = s[s.d0 >= "2023-01-01"]
        if len(Hh) and len(base):
            hs = set(zip(Hh.yf, Hh.date))
            bd = pd.bdate_range("2023-01-01", "2026-12-31")
            nxt = {x.strftime("%Y-%m-%d"): bd[i + 1].strftime("%Y-%m-%d") for i, x in enumerate(bd[:-1])}
            h0 = base.apply(lambda r: (r.yf, r.d0) in hs, axis=1)
            h1 = base.apply(lambda r: (r.yf, nxt.get(r.d0)) in hs, axis=1)
            out["halts"] = {"events_2023+": int(len(base)), "halt_d0": round(float(h0.mean()), 4),
                            "halt_d1": round(float(h1.mean()), 4), "reasons": Hh.reason.value_counts().head(8).to_dict()}
        else:
            out["halts"] = {"error": f"데이터 없음(정지 행 {len(Hh)}, 2023+ 사건 {len(base)})"}
    except FileNotFoundError:
        out["halts"] = {"error": "데이터 없음(파일 없음)"}
    return out


def explore(s: pd.DataFrame) -> list[dict]:
    """탐색(등록 밖, 등급 상한 C): 조건별 S5·L5. 시그널 후보 탐색용."""
    rows = []
    conds = {
        "갭형(gap_share≥0.5)": s.gap_share >= 0.5,
        "장중형(gap_share<0.5)": s.gap_share < 0.5,
        "원가격<$3": s.raw_m1 < 3,
        "원가격 $3~20": s.raw_m1 >= 3,
        "T50": s.ret0 >= 0.5,
        "T100": s.ret0 >= 1.0,
        "D+1 시가 갭다운(o1<c0)": s.gapD1 < 0,
        "D+1 시가 갭업(o1≥c0)": s.gapD1 >= 0,
        "SPAC": s.spac,
        "시총 미상": s.mcap.isna(),
        "시총<$300M": s.mcap < 3e8,
        "T100·갭형": (s.ret0 >= 1.0) & (s.gap_share >= 0.5),
        "T100·장중형": (s.ret0 >= 1.0) & (s.gap_share < 0.5),
        "D+1 갭업≥10%": s.gapD1 >= 0.10,
    }
    for lab, m in conds.items():
        g = s[m]
        if len(g) < 30:
            rows.append({"cond": lab, "n": int(len(g))})
            continue
        rows.append({"cond": lab, "n": int(len(g)),
                     **{f"{c}_{k}": describe(g[c])[k] for c in ("L1", "L5", "S5", "S5_stop30", "S20") for k in ("mean", "median", "win")},
                     "S5_test_all": monthly_test(g.d0, g.S5), "S20_test_all": monthly_test(g.d0, g.S20),
                     "S5_is_mean": round(float(g[g.IS].S5.mean()), 4) if g.IS.any() else None,
                     "S5_oos_mean": round(float(g[~g.IS].S5.mean()), 4) if (~g.IS).any() else None,
                     "S20_is_mean": round(float(g[g.IS].S20.mean()), 4) if g.IS.any() else None,
                     "S20_oos_mean": round(float(g[~g.IS].S20.mean()), 4) if (~g.IS).any() else None,
                     "S5_p05": describe(g.S5)["p05"], "S5_min": describe(g.S5)["min"]})
    return rows


def bench(s: pd.DataFrame, d: Path) -> dict:
    try:
        b = pd.read_csv(d / "bench.csv")
    except FileNotFoundError:
        return {"error": "데이터 없음"}
    iw = b[b.symbol == "IWM"].set_index("date")
    dates = list(iw.index)
    pos = {x: i for i, x in enumerate(dates)}
    l5, s5 = [], []
    for d0 in s.d0:
        i = pos.get(d0)
        if i is None or i + 5 >= len(dates):
            continue
        l5.append(iw.close.iloc[i + 5] / iw.close.iloc[i] - 1)
        s5.append(-(iw.close.iloc[i + 5] / iw.open.iloc[i + 1] - 1))
    return {"IWM_L5_mean": round(float(np.mean(l5)), 4) if l5 else None,
            "IWM_short_S5_mean": round(float(np.mean(s5)), 4) if s5 else None, "n": len(l5)}


def dq_flags(s: pd.DataFrame, E: pd.DataFrame | None = None) -> pd.DataFrame:
    """자료 품질(등록 밖 민감도): 거래 정체(D+1~D+5 종가 고유값 ≤2) · 20일 거래량 0 · 창 안 분할."""
    s = s.copy()
    s["dq_stale"] = s[[f"c{k}" for k in range(1, 6)]].nunique(axis=1) <= 2
    s["dq_vol0"] = ~np.isfinite(s.vm) | (s.vol20 <= 0)
    s["dq_split"] = False
    if E is not None:
        sw = E.groupby(["yf", "d0"]).raw_f.nunique()
        s["dq_split"] = (pd.Series(list(zip(s.yf, s.d0))).map(sw.to_dict()) > 1).to_numpy()
    s["dq_bad"] = s.dq_stale | s.dq_vol0 | s.dq_split
    return s


def run(d: Path) -> dict:
    L = load(d)
    W, meta = L["W"], L["meta"]
    s = add_returns(select(W))
    try:
        s = dq_flags(s, pd.read_parquet(d / "events.parquet", columns=["yf", "d0", "raw_f"]))
    except Exception:  # noqa: BLE001 — 합성 테스트 등
        s = dq_flags(s)
    s100 = s[s.ret0 >= 1.0]
    try:
        elig = pd.read_csv(d / "elig_days.csv")
    except FileNotFoundError:
        elig = None
    known = add_returns(select(W, mcap_known=True))
    tiers = {}
    for t, thr in TIERS.items():
        g = s[s.ret0 >= thr]
        tiers[t] = {"n": int(len(g)), "n_is": int(g.IS.sum()), "n_oos": int((~g.IS).sum()),
                    "gap_type_share": round(float((g.gap_share >= 0.5).mean()), 3) if len(g) else None,
                    **{c: describe(g[c]) for c in ("L1", "L5", "L1_gross", "L5_gross", "L5_o1", "S5", "S5_gross", "S20", "S20_gross", "S5_stop30")},
                    "squeeze_up100_20d": round(float((g.max_up20 >= 1).mean()), 4) if len(g) else None,
                    "squeeze_up300_20d": round(float((g.max_up20 >= 3).mean()), 4) if len(g) else None}
    funnel = {"후보창(느슨: +25%·3배·$0.5)": int(len(W)),
              "+30%": int((W.ret0 >= .3).sum()),
              "+30%·거래량5배": int(((W.ret0 >= .3) & (W.vm >= VM)).sum()),
              "+가격 $1~20(원가격)": int(((W.ret0 >= .3) & (W.vm >= VM) & W.raw_m1.between(PX_LO, PX_HI)).sum()),
              "+이력60일·시총<$2B/미상·쿨다운20": int(len(s)),
              "시총 확인분만": int(len(known))}
    adj_bias = int(((W.ret0 >= .3) & (W.vm >= VM) & (W.cm1 >= PX_LO) & (W.cm1 <= PX_HI)).sum())
    res = {
        "study": "us_smallcap_spikes", "date": "2026-10-21", "m": M, "alpha_bonf": round(ALPHA / M, 5),
        "params": {"cost_roundtrip": COST, "borrow_primary": B1, "stop_primary": STOP1, "cool": COOL,
                   "px": [PX_LO, PX_HI], "mcap_hi": MCAP_HI, "vol_mult": VM, "min_hist": MIN_HIST, "is_end": IS_END},
        "data": {"tickers_with_data": int(len(meta)), "rev_split_tickers": int((pd.to_numeric(meta.get("rev_splits"), errors="coerce") > 0).sum()),
                 "first_event": s.d0.min(), "last_event": s.d0.max(),
                 "last_bar": str(meta["last"].max()), "mcap_known_share": round(float(s.mcap.notna().mean()), 3),
                 "spac_share": round(float(s.spac.mean()), 3), "adr_share": round(float(s.adr.mean()), 3),
                 "same_filter_on_adjusted_price_n": adj_bias},
        "funnel": funnel, "tiers": tiers, "hypotheses": hyp_table(s, s100),
        "mcap_known_only": {c: describe(known[c]) for c in ("L1", "L5", "S5", "S20")},
        "sens_short": sens(s), "no_borrow": no_borrow(s), "no_borrow_S20": no_borrow(s, "S20"),
        "sens_short_T100": sens(s100), "no_borrow_T100": no_borrow(s100, "S5_b100"),
        "dq": {"stale": int(s.dq_stale.sum()), "vol0": int(s.dq_vol0.sum()), "split_in_window": int(s.dq_split.sum()),
               "clean_T30": {c: describe(s[~s.dq_bad][c]) for c in ("L1", "L5", "S5", "S20")},
               "clean_T100": {c: describe(s100[~s100.dq_bad][c]) for c in ("L5", "S5_b100", "S20")},
               "clean_T100_test": monthly_test(s100[~s100.dq_bad].d0, s100[~s100.dq_bad].S5_b100)},
        "by_year": by_year(s, elig), "by_year_T100": by_year(s100, None), "survivorship": surv(s, d, meta), "real_costs": borrow_halts(s, d),
        "bench": bench(s, d), "explore": explore(s),
        "grades_doc": "A=IS Bonferroni+OOS 같은 부호(p<0.10) · B=IS 통과 · C=IS p<0.10 · F=그 외 · 검증전=IS<100. 상한 B(생존편향·숏 실행 가능성). explore 는 등록 밖 → 상한 C",
    }
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()
    res = run(Path(a.data))
    Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    for h in res["hypotheses"]:
        print(h["id"], h["grade"], h["all"].get("n"), h["all"].get("mean"), h["all"].get("median"), h["is_test"], h["oos"].get("mean"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
