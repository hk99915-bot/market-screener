#!/usr/bin/env python3
"""매매 계획(trade plan) 보정 — 스탑·목표 배수 격자별 선도달 확률·기대값(R), 학습/검증 분리 (퀀트·FRM, 10/21 겸이 지시).

  python3 scripts/study_tradeplan.py                  # reports/studies/<오늘>_tradeplan_calib.json
  python3 scripts/study_tradeplan.py --quick          # 표본 축소(테스트·점검용)

입력  data/hist/{kr,us}_YYYY.parquet (2010~2025 일봉, git) · data/kr_prices.parquet(릴리스 자산, 2025-09~)
      reports/signal_tracking/*.json (accum 매집 신호 이력, KR 2026-02~) · data/hist/kr_index_daily.parquet(레짐)
      data/flows/kr_inv_*.parquet (외국인·기관 순매수 — 센티먼트 축)
계산  신호일 i 종가 C·ATR14·20일 저점 → 손절 S = C − d·ATR (d = k 또는 구조적 clip((C−20일저점)/ATR, 1, 2)).
      진입 = 다음날 시가 E, 단 E 가 진입 구간 [C−0.5ATR, C+0.5ATR] 밖이면 미진입(idea_tracking 정책과 같음).
      R = E − S. 이후 H=20 거래일 일봉으로 1차 목표(E + r·R)·손절 선도달 판정. 같은 날 둘 다 닿으면 손절(보수).
      시가가 손절 아래로 갭 → 시가 청산(갭 미끄러짐 반영). 목표 위로 갭 → 시가 청산. H일까지 미도달 → H일째 종가(시간 손절).
      분할 청산: 1차에서 f=50% 익절 후 스탑을 본전(E)으로, 나머지는 2차 목표·본전·시간 손절 중 먼저.
      비용: 왕복 KR 0.25%·US 0.10% 를 R 단위로 차감. 표준오차 = 신호일 군집 강건(같은 날 신호는 상관).
등급  사전등록 없음 → 상한 C. 검증(OOS) E[R]>0·t≥2·학습과 같은 부호면 C, OOS E[R]≤0 이면 F, OOS 신호일 < 30 이면 검증전.
영향 범위  screener/tradeplan.py 가 이 json(최신 *_tradeplan_calib.json)의 lookup 으로 확률·기대값을 붙인다. 워크플로 변경 없음.
롤백  git revert — json 이 없으면 tradeplan 은 확률 '검증전(보정 없음)' 으로 동작.
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
KST = timezone(timedelta(hours=9))
H = 20
STOPS = ["atr1.0", "atr1.5", "atr2.0", "atr2.5", "atr3.0", "struct"]
TARGETS = [1.0, 1.5, 2.0, 2.5, 3.0]
SCALE = [(1.0, 2.0), (1.0, 3.0), (1.5, 3.0), (2.0, 4.0)]
FRAC = 0.5
COST = {"KR": 0.0025, "US": 0.0010}
MAX_STOP_PCT = 0.15


# ───────────── 경로 판정 (벡터) ─────────────

def first_touch(O, Hh, L, C, r):
    """O,Hh,L,C: (N,H) R 단위 경로((가격−E)/R). 손절 −1, 목표 +r. 반환 (R 결과, 종류 0=목표 1=손절 2=시간)."""
    n, h = O.shape
    sh = (O <= -1) | (L <= -1)
    th = (O >= r) | (Hh >= r)
    s_any, t_any = sh.any(1), th.any(1)
    s_day = np.where(s_any, sh.argmax(1), h)
    t_day = np.where(t_any, th.argmax(1), h)
    idx = np.arange(n)
    res = C[:, -1].copy()
    kind = np.full(n, 2)
    stop_first = s_any & (s_day <= t_day)
    tgt_first = t_any & (t_day < s_day)
    so = O[idx, np.minimum(s_day, h - 1)]
    res[stop_first] = np.where(so[stop_first] <= -1, so[stop_first], -1.0)
    to = O[idx, np.minimum(t_day, h - 1)]
    res[tgt_first] = np.where(to[tgt_first] >= r, to[tgt_first], r)
    kind[stop_first], kind[tgt_first] = 1, 0
    return res, kind


def scale_out(O, Hh, L, C, r1, r2, f=FRAC):
    """1차 r1 에서 f 익절 → 스탑 본전(0) → 나머지 r2·본전·시간. 반환 (R 결과, 종류1, 2차 도달 여부)."""
    v1, k1 = first_touch(O, Hh, L, C, r1)
    n, h = O.shape
    res = v1.copy()
    hit2 = np.zeros(n, bool)
    sel = np.where(k1 == 0)[0]
    if len(sel):
        th = (O[sel] >= r1) | (Hh[sel] >= r1)
        j1 = th.argmax(1)
        after = np.arange(h)[None, :] > j1[:, None]
        sh = after & ((O[sel] <= 0) | (L[sel] <= 0))
        t2 = after & ((O[sel] >= r2) | (Hh[sel] >= r2))
        s_any, t_any = sh.any(1), t2.any(1)
        s_day = np.where(s_any, sh.argmax(1), h)
        t_day = np.where(t_any, t2.argmax(1), h)
        ii = np.arange(len(sel))
        rest = C[sel, -1].copy()
        sf = s_any & (s_day <= t_day)
        tf = t_any & (t_day < s_day)
        so = O[sel][ii, np.minimum(s_day, h - 1)]
        to = O[sel][ii, np.minimum(t_day, h - 1)]
        rest[sf] = np.where(so[sf] <= 0, so[sf], 0.0)
        rest[tf] = np.where(to[tf] >= r2, to[tf], r2)
        res[sel] = f * v1[sel] + (1 - f) * rest
        hit2[sel] = tf
    return res, k1, hit2


# ───────────── 진입 표본 ─────────────

def _windows(o, h, l, c, i_idx, d_atr, atr, low20):
    """신호 인덱스 → 진입 경로. 반환 dict(O,H,L,C 는 아직 가격, E, S 계산 전 원자료)."""
    sw = np.lib.stride_tricks.sliding_window_view
    e = i_idx + 1
    return sw(o, H)[e], sw(h, H)[e], sw(l, H)[e], sw(c, H)[e]


def build_entries(df: pl.DataFrame, market: str, pick, step: int | None, min_val: float, min_px: float):
    """df: [sym,date,open,high,low,close,volume] 정렬. pick(sym, dates, arrays) → 신호 인덱스 배열(없으면 step 표본).
    반환 dict of arrays: sym, date, C, ATR, low20, O/H/L/Cw (N,H), feat(dict)."""
    out = {k: [] for k in ("sym", "date", "C", "ATR", "LOW20", "O", "Hh", "L", "Cw", "MA50", "R60", "HI250")}
    for (sym,), g in df.group_by(["sym"], maintain_order=True):
        o, h, l, c, v = (g[x].to_numpy().astype(float) for x in ("open", "high", "low", "close", "volume"))
        n = len(c)
        if n < 80:
            continue
        dates = g["date"].to_numpy()
        pc = np.r_[c[0], c[:-1]]
        tr = np.maximum(h, pc) - np.minimum(l, pc)
        atr = np.convolve(tr, np.ones(14) / 14, "full")[:n]
        low20 = pl.Series(l).rolling_min(20).to_numpy()
        ma50 = pl.Series(c).rolling_mean(50).to_numpy()
        val20 = pl.Series(c * v).rolling_mean(20).to_numpy()
        hi250 = pl.Series(h).rolling_max(250, min_samples=60).to_numpy()
        ret = np.abs(c / pc - 1)
        bad = pl.Series(ret > 0.4).cast(pl.Int8).rolling_max(H + 2).to_numpy()   # 미조정 분할·오류 구간 제외
        cand = pick(sym, dates, c) if pick else np.arange(60, n - H - 1, step)
        cand = np.asarray([i for i in cand if 60 <= i < n - H - 1])
        if not len(cand):
            continue
        ok = (c[cand] >= min_px) & (val20[cand] >= min_val) & np.isfinite(low20[cand]) & (atr[cand] > 0)
        ok &= np.nan_to_num(bad[np.minimum(cand + H + 1, n - 1)], nan=1) == 0
        cand = cand[ok]
        if not len(cand):
            continue
        O, Hh, L, Cw = _windows(o, h, l, c, cand, None, atr, low20)
        out["sym"].append(np.full(len(cand), sym))
        out["date"].append(dates[cand])
        for k, arr in (("C", c), ("ATR", atr), ("LOW20", low20), ("MA50", ma50), ("HI250", hi250)):
            out[k].append(arr[cand])
        out["R60"].append(c[cand] / c[cand - 60] - 1)
        for k, arr in (("O", O), ("Hh", Hh), ("L", L), ("Cw", Cw)):
            out[k].append(arr.astype(np.float32))
    return {k: (np.concatenate(v) if v else np.array([])) for k, v in out.items()}


def stop_dist(E, stop):
    if stop == "struct":
        return np.clip((E["C"] - E["LOW20"]) / E["ATR"], 1.0, 2.0)
    return np.full(len(E["C"]), float(stop[3:]))


def to_r(E, stop, market):
    """정규화: 진입 구간 필터·손절폭 15% 필터 후 R 단위 경로와 비용(R)."""
    d = stop_dist(E, stop)
    S = E["C"] - d * E["ATR"]
    ent = E["O"][:, 0].astype(float)
    inzone = np.abs(ent - E["C"]) <= 0.5 * E["ATR"]
    R = ent - S
    ok = inzone & (R > 0) & (R / ent <= MAX_STOP_PCT)
    Rr = R[ok][:, None]
    e = ent[ok][:, None]
    f = lambda A: ((A[ok] - e) / Rr).astype(np.float32)  # noqa: E731
    return f(E["O"]), f(E["Hh"]), f(E["L"]), f(E["Cw"]), COST[market] * e[:, 0] / Rr[:, 0], ok, inzone


def _stats(res, dates, extra=None):
    n = len(res)
    if n == 0:
        return {"n": 0}
    mu = float(np.mean(res))
    df = pl.DataFrame({"d": dates.astype("datetime64[D]").astype(str), "e": res - mu})
    m = df.group_by("d").agg(pl.col("e").sum())["e"].to_numpy()   # 날짜 군집 잔차 합
    nd = len(m)
    se = float(np.sqrt(np.sum(m ** 2) * nd / max(nd - 1, 1)) / n) if nd > 1 else None   # 군집 강건 SE
    o = {"n": n, "n_dates": nd, "ev_r": round(mu, 4), "se": round(se, 4) if se else None,
         "t": round(mu / se, 2) if se else None}
    if extra:
        o.update(extra)
    return o


def evaluate(E, market, split_date, stops=STOPS):
    """격자 전체 → {stop: {single: {r: {train,test}}, scale: {...}, gap: ...}}."""
    out = {}
    for st in stops:
        O, Hh, L, Cw, cost, ok, inzone = to_r(E, st, market)
        dates = E["date"][ok]
        tr = dates < np.datetime64(split_date)
        blk = {"n_signal": int(len(ok)), "no_entry_rate": round(float(1 - inzone.mean()), 3) if len(inzone) else None,
               "stop_cut_rate": round(float(1 - ok.sum() / max(inzone.sum(), 1)), 3), "single": {}, "scale": {}}
        for r in TARGETS:
            res, kind = first_touch(O, Hh, L, Cw, r)
            net = res - cost
            cell = {}
            for nm, msk in (("train", tr), ("test", ~tr)):
                k = kind[msk]
                stopx = res[msk][k == 1]
                cell[nm] = _stats(net[msk], dates[msk], {
                    "p_t": round(float((k == 0).mean()), 3) if len(k) else None,
                    "p_s": round(float((k == 1).mean()), 3) if len(k) else None,
                    "p_time": round(float((k == 2).mean()), 3) if len(k) else None,
                    "stop_exit_r": round(float(stopx.mean()), 3) if len(stopx) else None})
            blk["single"][str(r)] = cell
        for r1, r2 in SCALE:
            res, k1, hit2 = scale_out(O, Hh, L, Cw, r1, r2)
            net = res - cost
            cell = {}
            for nm, msk in (("train", tr), ("test", ~tr)):
                k = k1[msk]
                cell[nm] = _stats(net[msk], dates[msk], {
                    "p_t1": round(float((k == 0).mean()), 3) if len(k) else None,
                    "p_s": round(float((k == 1).mean()), 3) if len(k) else None,
                    "p_t2": round(float(hit2[msk].mean()), 3) if len(k) else None})
            blk["scale"][f"{r1}/{r2}"] = cell
        out[st] = blk
    return out


def recommend(grid):
    """학습 E[R] 를 격자 이웃 평균(평탄 영역)으로 매끈하게 → 최대 칸. ATR 손절 행 × 목표 열."""
    ks = [s for s in STOPS if s.startswith("atr")]
    M = np.array([[grid[s]["single"][str(r)]["train"].get("ev_r", np.nan) for r in TARGETS] for s in ks])
    Sm = np.full_like(M, np.nan)
    for i in range(M.shape[0]):
        for j in range(M.shape[1]):
            nb = [M[a, b] for a, b in ((i, j), (i - 1, j), (i + 1, j), (i, j - 1), (i, j + 1)) if 0 <= a < M.shape[0] and 0 <= b < M.shape[1]]
            Sm[i, j] = np.nanmean(nb)
    i, j = np.unravel_index(np.nanargmax(Sm), Sm.shape)
    flat = float(np.nanmax(M) - np.nanmin(M))
    return {"stop": ks[i], "r": TARGETS[j], "train_smooth": round(float(Sm[i, j]), 4), "train_range": round(flat, 4),
            "smooth_table": [[round(float(x), 4) for x in row] for row in Sm]}


def best_scale(grid, stop):
    sc = grid[stop]["scale"]
    k = max(sc, key=lambda x: sc[x]["train"].get("ev_r", -9))
    return k


def grade(cell_test):
    if not cell_test or cell_test.get("n_dates", 0) < 30:
        return "검증전"
    ev, t = cell_test.get("ev_r"), cell_test.get("t") or 0
    if ev is None or ev <= 0:
        return "F"
    return "C" if t >= 2 else "C(방향만)" if t >= 1.28 else "F"


# ───────────── 데이터 ─────────────

def load_hist(market: str, years) -> pl.DataFrame:
    fs = [ROOT / "data" / "hist" / f"{market.lower()}_{y}.parquet" for y in years]
    df = pl.concat([pl.read_parquet(f) for f in fs if f.exists()], how="vertical_relaxed")
    return (df.rename({"yf": "sym"}).select("sym", "date", "open", "high", "low", "close", "volume")
              .drop_nulls().filter(pl.col("open") > 0).unique(["sym", "date"]).sort("sym", "date"))


def regime_series(market: str) -> dict:
    """신호일 → 지수 200일선 위(1)/아래(0)."""
    if market == "KR":
        p = ROOT / "data" / "hist" / "kr_index_daily.parquet"
        if not p.exists():
            return {}
        d = pl.read_parquet(p).filter(pl.col("symbol") == "KOSPI").sort("date")
    else:
        p = ROOT / "data" / "hist" / "us_daily.parquet"
        if not p.exists():
            return {}
        d = pl.read_parquet(p).filter(pl.col("symbol") == "^GSPC").sort("date")
    d = d.with_columns(pl.col("close").rolling_mean(200).alias("ma200"))
    return {str(a): int(b > m) for a, b, m in zip(d["date"], d["close"], d["ma200"]) if m is not None}


def by_regime(E, market, stop, r, reg):
    O, Hh, L, Cw, cost, ok, _ = to_r(E, stop, market)
    res, _k = first_touch(O, Hh, L, Cw, r)
    net = res - cost
    ds = E["date"][ok].astype("datetime64[D]").astype(str)
    lab = np.array([reg.get(x, -1) for x in ds])
    return {nm: _stats(net[lab == v], E["date"][ok][lab == v]) for nm, v in (("bull_200d_above", 1), ("bear_200d_below", 0))}


def accum_entries(quick=False):
    from screener.prices import load_kr
    ev = []
    for f in sorted(glob.glob(str(ROOT / "reports" / "signal_tracking" / "*.json"))):
        ev += [e for e in json.load(open(f, encoding="utf-8")) if e.get("src") == "accum" and e.get("side") == 1]
    px = load_kr()
    px = px.with_columns(pl.col("yf").str.slice(0, 6).alias("sym")).select("sym", "date", "open", "high", "low", "close", "volume").sort("sym", "date")
    want = {}
    for e in ev:
        want.setdefault(e["code"], set()).add(e["date"])

    def pick(sym, dates, c):
        ds = want.get(sym) or set()
        return [i for i, d in enumerate(dates.astype("datetime64[D]").astype(str)) if d in ds]
    px = px.filter(pl.col("sym").is_in(list(want)))
    return build_entries(px, "KR", pick, None, 1e9, 1000), len(ev)


def axis_calib(E, market, stop, r1, r2, split_date, flows=None):
    """컨빅션 축 보정: 기술(50일선 괴리·60일 수익률·52주 고점 근접) · 센티먼트(외국인+기관 20일 순매수/시총, KR 2024~).
    지표 = 같은 날 횡단면 순위(0~1) ↔ 계획 결과 R 의 순위상관(IC, 날짜 평균) 학습/검증. 펀더·내러티브는 이력 없음(2026-10~) → 검증전."""
    O, Hh, L, Cw, cost, ok, _ = to_r(E, stop, market)
    res, _k1, _h = scale_out(O, Hh, L, Cw, r1, r2)
    net = res - cost
    dates = E["date"][ok].astype("datetime64[D]").astype(str)
    feats = {"tech_ma50": (E["C"] / E["MA50"] - 1)[ok], "tech_r60": E["R60"][ok], "tech_hi250": (E["C"] / E["HI250"] - 1)[ok]}
    if flows is not None:
        key = {f"{s}|{d}": v for s, d, v in zip(flows["code"], flows["date"].cast(pl.Utf8), flows["sent"])}
        syms = E["sym"][ok]
        feats["sent_flow20"] = np.array([key.get(f"{str(s)[:6]}|{d}", np.nan) for s, d in zip(syms, dates)], dtype=float)
    df = pl.DataFrame({"d": dates, "r": net, **{k: v.astype(float) for k, v in feats.items()}})
    out = {}
    for k in feats:
        sub = df.filter(pl.col(k).is_not_nan() & pl.col(k).is_not_null())
        sub = sub.with_columns(pl.col(k).rank().over("d").alias("rk"), pl.col("r").rank().over("d").alias("rr"),
                               pl.len().over("d").alias("nn")).filter(pl.col("nn") >= 10)
        ic = sub.group_by("d").agg(pl.corr("rk", "rr").alias("ic")).drop_nans().drop_nulls()
        q = sub.with_columns((pl.col("rk") / pl.col("nn")).alias("pct"))
        row = {}
        for nm, cond in (("train", pl.col("d") < split_date), ("test", pl.col("d") >= split_date)):
            x = ic.filter(cond)["ic"].to_numpy()
            qq = q.filter(cond)
            top = qq.filter(pl.col("pct") > 2 / 3)["r"].mean()
            bot = qq.filter(pl.col("pct") <= 1 / 3)["r"].mean()
            row[nm] = {"ic": round(float(x.mean()), 4) if len(x) else None,
                       "t": round(float(x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))), 2) if len(x) > 2 and x.std() > 0 else None,
                       "n_dates": int(len(x)), "top_minus_bottom_r": round(float(top - bot), 4) if top is not None and bot is not None else None}
        out[k] = row
    return out


def flows_sent():
    fs = sorted((ROOT / "data" / "flows").glob("kr_inv_*.parquet"))
    if not fs:
        return None
    f = pl.concat([pl.read_parquet(x) for x in fs], how="vertical_relaxed").sort("code", "date")
    f = f.with_columns(((pl.col("f") + pl.col("i")).cast(pl.Float64).rolling_sum(20).over("code") / 100.0
                        / pl.col("mcap").cast(pl.Float64)).alias("sent"))   # 백만원 ÷ 억원 → 비율(%)
    return f.select("code", "date", "sent").drop_nulls()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    today = datetime.now(KST).date()
    step = 40 if a.quick else 10
    res = {"v": 1, "asof": str(today), "generated_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M KST"),
           "method": {"H": H, "entry": "다음날 시가, 진입 구간 [C−0.5ATR, C+0.5ATR] 밖이면 미진입", "same_day": "손절 우선",
                      "gap": "갭 통과 시 시가 체결", "scale_frac": FRAC, "cost": COST, "max_stop_pct": MAX_STOP_PCT,
                      "se": "신호일 군집 강건 표준오차(같은 날 신호 상관 반영)", "stops": STOPS, "targets": TARGETS, "scale": [f"{x}/{y}" for x, y in SCALE]},
           "m": len(STOPS) * (len(TARGETS) + len(SCALE)),
           "grade_rule": "사전등록 없음 → 상한 C. OOS E[R]>0·t≥2 → C, t≥1.28 → C(방향만), E[R]≤0 → F, OOS 신호일<30 → 검증전",
           "groups": {}}
    kr_years, us_years = range(2010, 2026), range(2010, 2026)
    reg_kr, reg_us = regime_series("KR"), regime_series("US")
    fl = flows_sent()
    specs = []
    kr = load_hist("KR", kr_years)
    kr_tr = build_entries(kr, "KR", None, step, 1e9, 1000)
    specs.append(("kr_base", "KR", "KR 유동 종목 무조건 표본(10거래일 간격) — 신호 없는 기준선", kr_tr, "2020-01-01", reg_kr))
    m = kr_tr["C"] > kr_tr["MA50"]
    specs.append(("kr_trend", "KR", "KR 추세 동의(종가 > 50일선) 표본 — TOP3 '추세' 원천 대용", {k: v[m] for k, v in kr_tr.items()}, "2020-01-01", reg_kr))
    del kr
    us = load_hist("US", us_years)
    us_e = build_entries(us, "US", None, step, 2e7, 5)
    specs.append(("us_base", "US", "US 대형주(S&P 구성 246종목) 무조건 표본", us_e, "2020-01-01", reg_us))
    m = us_e["C"] > us_e["MA50"]
    specs.append(("us_trend", "US", "US 추세 동의(종가 > 50일선) — 미장 TOP3 us_trend 원천 대용", {k: v[m] for k, v in us_e.items()}, "2020-01-01", reg_us))
    del us
    try:
        acc, n_ev = accum_entries(a.quick)
        specs.append(("kr_accum", "KR", f"KR 매집 신호(signal_tracking accum 롱 {n_ev}건, 2026-02~)", acc, "2026-07-01", reg_kr))
    except Exception as e:  # noqa: BLE001
        res["groups"]["kr_accum"] = {"error": f"{type(e).__name__}: {e}"}
    for key, mk, desc, E, split, reg in specs:
        if not len(E.get("C", [])):
            res["groups"][key] = {"desc": desc, "error": "표본 없음"}
            continue
        g = evaluate(E, mk, split)
        rec = recommend(g)
        sk = best_scale(g, rec["stop"])
        r1, r2 = (float(x) for x in sk.split("/"))
        cell = g[rec["stop"]]["single"][str(rec["r"])]
        struct = g["struct"]["scale"][sk]
        blk = {"desc": desc, "market": mk, "split": split, "n_signal_days": int(len(set(E["date"].astype("datetime64[D]").astype(str)))),
               "grid": g, "recommend": {**rec, "scale": sk, "test": cell["test"], "grade": grade(cell["test"]),
                                         "scale_test": g[rec["stop"]]["scale"][sk]["test"], "scale_grade": grade(g[rec["stop"]]["scale"][sk]["test"]),
                                         "struct_scale_test": struct["test"], "struct_scale_grade": grade(struct["test"])},
               "by_regime": by_regime(E, mk, "struct", 2.0, reg)}
        if key in ("kr_trend", "kr_accum", "us_trend"):
            blk["axes"] = axis_calib(E, mk, "struct", r1, r2, split, fl if mk == "KR" and key != "kr_trend" else None)
        if key == "kr_trend" and fl is not None:   # 센티먼트는 2024~ 만 → 별도 분할(2025-07)
            sub = {k: v[E["date"] >= np.datetime64("2024-02-01")] for k, v in E.items()}
            blk["axes_sent"] = axis_calib(sub, mk, "struct", r1, r2, "2025-07-01", fl)
        res["groups"][key] = blk
        print(key, "n", len(E["C"]), "rec", rec["stop"], rec["r"], "test", cell["test"], "scale", sk, g[rec["stop"]]["scale"][sk]["test"], flush=True)
    out = Path(a.out) if a.out else ROOT / "reports" / "studies" / f"{today}_tradeplan_calib.json"
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("→", out)


if __name__ == "__main__":
    main()
