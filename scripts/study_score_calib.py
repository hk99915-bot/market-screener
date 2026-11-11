#!/usr/bin/env python3
"""score-calib 1단계 — 스크리너 점수 분포·구간별 이후 초과수익 (사전등록 reports/studies/2026-11-12_score_calib.md §0, 커밋 40cd49bc0).

  python3 scripts/study_score_calib.py            # reports/studies/2026-11-12_score_calib.json 생성
  python3 scripts/study_score_calib.py --market KR

정의는 §0 그대로 — 바꾸면 새 id 로 재등록. 점수 코드는 screener/scoring.py·indicators.py 를 import 만 한다(수정 없음).
영향 범위: 연구 전용(워크플로·화면·알림 import 없음). 롤백 = 이 파일·json·md 결과절 revert.
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import polars as pl
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from screener import indicators, scoring  # noqa: E402
from screener.prices import adjust  # noqa: E402

OUT = ROOT / "reports" / "studies" / "2026-11-12_score_calib.json"
HS = (5, 20, 60)
M = 18
ALPHA = 0.05 / M
IS_END = date(2019, 12, 31)
OOS_START = date(2020, 1, 1)
START = date(2011, 1, 3)
STEP = 5
ERR = 0.40
MIN_N = 10
NW_LAG = 3
FILT = {"KR": (1000.0, 1_000_000_000.0), "US": (3.0, 5_000_000.0)}
EDGES = [0, 20, 40, 60, 80]
SCORES = {"T": "trend_score", "M": "momentum_score", "R": "reversal_risk"}
SIGN = {"T": 1, "M": 1, "R": -1}        # 가설 방향: T·M 상단−하단 > 0, R 상단−하단 < 0
NAN_DROPPED: dict[str, int] = {}
KEEP = ["yf", "date", "close", "dollar_vol20", "sma200", "trend_score", "momentum_score", "reversal_risk", "class"]


def load(market: str) -> pl.DataFrame:
    files = sorted(glob.glob(str(ROOT / "data" / "hist" / f"{market.lower()}_20[0-9][0-9].parquet")))
    keep = ["yf", "date", "open", "high", "low", "close", "volume"]
    df = (pl.concat([pl.read_parquet(f).select(keep) for f in files], how="vertical_relaxed")
            .with_columns(pl.col("date").cast(pl.Date), *[pl.col(c).cast(pl.Float64) for c in keep[2:]])
            .unique(["yf", "date"], keep="last").sort("yf", "date"))
    if market == "KR":
        df = adjust(df)   # px-adjust-unify 공통 조정 (load_kr(hist_from=2010) 와 같은 함수)
    return df.filter((pl.col("close") > 0) & pl.col("close").is_not_null())


def build(market: str, batch: int = 300) -> pl.DataFrame:
    px = load(market)
    cal = px.group_by("date").len().filter(pl.col("len") >= 50).sort("date")["date"]
    cal = cal.filter(cal >= START)
    fdates = cal[::STEP]
    syms = px["yf"].unique().sort().to_list()
    parts = []
    for i in range(0, len(syms), batch):
        sub = px.filter(pl.col("yf").is_in(syms[i:i + batch]))
        full = scoring.score(indicators.add_indicators(sub))
        c = pl.col("close")
        absr = (c / c.shift(1).over("yf") - 1).abs()
        full = full.with_columns(absr.alias("_absr"))
        ex = []
        for h in HS:
            ex += [(c.shift(-(1 + h)).over("yf") / c.shift(-1).over("yf") - 1).alias(f"r{h}"),
                   pl.col("_absr").reverse().rolling_max(h).reverse().shift(-2).over("yf").alias(f"mx{h}")]
        full = full.with_columns(ex)
        parts.append(full.filter(pl.col("date").is_in(fdates.implode())).select(KEEP + [f"r{h}" for h in HS] + [f"mx{h}" for h in HS]))
        print(f"  {market} batch {i // batch + 1}/{math.ceil(len(syms) / batch)}", file=sys.stderr)
    d = pl.concat(parts)
    mp, mdv = FILT[market]
    d = d.filter((pl.col("close") >= mp) & (pl.col("dollar_vol20") >= mdv) & pl.col("sma200").is_not_null())
    # 실행 중 수정(정의 변경 아님): 점수 NaN(ADX 0/0 → trend_score NaN) 행은 어느 구간에도 속하지 않음 → 제외·건수 기록.
    # 첫 실행에서 bin_expr 이 NaN 을 B5 로 보냈던 구현 오류(US 179행) 때문. scoring.py 자체의 NaN 은 별도 보드 항목.
    nan = pl.any_horizontal([pl.col(c).is_nan() for c in SCORES.values()])
    NAN_DROPPED[market] = int(d.filter(nan).height)
    return d.filter(~nan)


def bin_expr(col: str) -> pl.Expr:
    x = pl.col(col)
    return (pl.when(x < 20).then(1).when(x < 40).then(2).when(x < 60).then(3).when(x < 80).then(4).otherwise(5)).alias(f"b_{col}")


def nw_t(x: np.ndarray, lag: int = NW_LAG) -> tuple[float, float]:
    """평균, Newey-West(Bartlett) t."""
    n = len(x)
    mu = float(np.mean(x))
    e = x - mu
    s = float(e @ e) / n
    for k in range(1, min(lag, n - 1) + 1):
        s += 2 * (1 - k / (lag + 1)) * float(e[k:] @ e[:-k]) / n
    se = math.sqrt(s / n) if s > 0 else float("nan")
    return mu, mu / se if se and se == se else float("nan")


def test(monthly: pl.DataFrame, sign: int) -> dict:
    """monthly: [ym(date), s]. 단측(가설 방향) p."""
    def one(sub):
        x = sub["s"].to_numpy()
        n = len(x)
        if n < 3:
            return {"n_months": n}
        mu, t = nw_t(x)
        p = float(stats.t.sf(sign * t, n - 1))
        prev = float(stats.t.sf(-sign * t, n - 1))
        st = float(np.std(x, ddof=1) / math.sqrt(n))
        return {"n_months": n, "mean": mu, "median": float(np.median(x)), "t_nw": t, "t_simple": mu / st if st else None,
                "p": p, "p_rev": prev, "hit": float(np.mean(sign * x > 0))}
    ym = pl.col("ym")
    return {"all": one(monthly), "is": one(monthly.filter(ym <= IS_END)), "oos": one(monthly.filter(ym >= OOS_START)),
            "y2022": one(monthly.filter(ym.dt.year() == 2022)),
            "oos_ex2020": one(monthly.filter((ym >= OOS_START) & (ym.dt.year() != 2020)))}


def grade(r: dict, sign: int, market: str) -> str:
    o, i, y = r["oos"], r["is"], r["y2022"]
    if o.get("n_months", 0) < 30 or "mean" not in o:
        return "검증전"
    right = sign * o["mean"] > 0
    g = "F"
    if right and o["p"] < ALPHA and sign * i.get("mean", 0) > 0:
        g = "B"
        if i.get("p", 1) < ALPHA and sign * y.get("mean", 0) > 0 and market != "US":
            g = "A"
    elif right and o["p"] < 0.05:
        g = "C"
    elif (not right) and o["p_rev"] < 0.05:
        g = "C(역방향)"
    return g


def dist(d: pl.DataFrame) -> dict:
    out = {}
    for k, col in SCORES.items():
        x = d[col]
        q = x.quantile
        b = d.select(bin_expr(col))[f"b_{col}"].value_counts().sort(f"b_{col}")
        yr = (d.group_by(pl.col("date").dt.year().alias("y")).agg((pl.col(col) >= 100).mean().alias("cap100"),
                                                                  (pl.col(col) >= 90).mean().alias("ge90"),
                                                                  pl.col(col).mean().alias("mean")).sort("y"))
        out[k] = {"col": col, "n": len(x), "mean": float(x.mean()), "p05": q(0.05), "p25": q(0.25), "p50": q(0.5), "p75": q(0.75),
                  "p95": q(0.95), "zero": float((x <= 0).mean()), "ge90": float((x >= 90).mean()), "cap100": float((x >= 100).mean()),
                  "bins": {f"B{r[0]}": r[1] / len(x) for r in b.iter_rows()},
                  "by_year": {str(r["y"]): {"mean": round(r["mean"], 2), "ge90": round(r["ge90"], 4), "cap100": round(r["cap100"], 4)}
                              for r in yr.iter_rows(named=True)}}
    cls = d["class"].value_counts()
    out["class"] = {r[0]: r[1] / len(d) for r in cls.iter_rows()}
    return out


def analyze(market: str, d: pl.DataFrame) -> dict:
    res = {"nan_score_rows_dropped": NAN_DROPPED.get(market, 0), "n_rows": len(d), "n_dates": d["date"].n_unique(), "n_syms": d["yf"].n_unique(),
           "first": str(d["date"].min()), "last": str(d["date"].max()), "dist": dist(d), "tests": {}, "bins": {}, "class_h20": {}, "nonoverlap_h20": {}}
    d = d.with_columns([bin_expr(c) for c in SCORES.values()])
    for h in HS:
        dh = (d.filter(pl.col(f"r{h}").is_not_null() & (pl.col(f"mx{h}").is_null() | (pl.col(f"mx{h}") <= ERR)))
               .with_columns((pl.col(f"r{h}") - pl.col(f"r{h}").mean().over("date")).alias("x")))
        for k, col in SCORES.items():
            b = pl.col(f"b_{col}")
            top = b >= 4 if k == "R" else b == 5
            g = (dh.group_by("date").agg(pl.col("x").filter(top).mean().alias("hi"), top.sum().alias("nh"),
                                         pl.col("x").filter(b == 1).mean().alias("lo"), (b == 1).sum().alias("nl"))
                   .filter((pl.col("nh") >= MIN_N) & (pl.col("nl") >= MIN_N))
                   .with_columns((pl.col("hi") - pl.col("lo")).alias("s"), pl.col("date").dt.truncate("1mo").alias("ym")))
            mo = g.group_by("ym").agg(pl.col("s").mean()).sort("ym")
            r = test(mo, SIGN[k])
            r["n_dates"] = len(g)
            r["mean_n_top"] = float(g["nh"].mean()) if len(g) else None
            r["mean_n_bottom"] = float(g["nl"].mean()) if len(g) else None
            hid = f"{k}{h}_{market}"
            r["grade"] = grade(r, SIGN[k], market)
            res["tests"][hid] = r
            # 구간 전부(OOS, 형성일 평균 → 전체 평균)
            oo = dh.filter(pl.col("date") >= OOS_START)
            bb = (oo.group_by(["date", f"b_{col}"]).agg(pl.col("x").mean()).group_by(f"b_{col}")
                    .agg(pl.col("x").mean().alias("mean"), pl.len().alias("dates")).sort(f"b_{col}"))
            pool = oo.group_by(f"b_{col}").agg(pl.col("x").mean().alias("m"), pl.len().alias("n")).sort(f"b_{col}")
            pm = {f"B{r_[0]}": (r_[1], r_[2]) for r_ in pool.iter_rows()}
            bi = {f"B{r_[0]}": {"mean": r_[1], "dates": r_[2], "pooled_mean": pm[f"B{r_[0]}"][0], "pooled_n": pm[f"B{r_[0]}"][1]}
                  for r_ in bb.iter_rows()}
            if bb.height >= 3:
                rho = stats.spearmanr(bb[f"b_{col}"].to_numpy(), bb["mean"].to_numpy())[0]
            else:
                rho = None
            res["bins"][hid] = {"oos": bi, "spearman_bin_vs_mean": None if rho is None else float(rho)}
            if h == 20:   # 비중첩: 4번째 형성일마다(20거래일 간격)
                dts = g.sort("date")["date"][::4]
                gn = g.filter(pl.col("date").is_in(dts.implode()))
                res["nonoverlap_h20"][hid] = {"n": len(gn), "mean": float(gn["s"].mean()) if len(gn) else None,
                                               "oos_n": gn.filter(pl.col("date") >= OOS_START).height,
                                               "oos_mean": gn.filter(pl.col("date") >= OOS_START)["s"].mean()}
        if h == 20:
            cl = (dh.filter(pl.col("date") >= OOS_START).group_by(["date", "class"]).agg(pl.col("x").mean())
                    .group_by("class").agg(pl.col("x").mean().alias("mean"), pl.len().alias("dates")).sort("class"))
            res["class_h20"] = {r[0]: {"mean": r[1], "dates": r[2]} for r in cl.iter_rows()}
    return res


def holm(tests: dict) -> dict:
    ps = sorted(((v["oos"].get("p", 1.0), k) for k, v in tests.items()), key=lambda z: z[0])
    out, stop = {}, False
    for i, (p, k) in enumerate(ps):
        ok = (not stop) and p < 0.05 / (len(ps) - i)
        stop = stop or not ok
        out[k] = bool(ok)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", choices=["KR", "US"], nargs="*", default=["KR", "US"])
    a = ap.parse_args(argv)
    out = {"study": "2026-11-12_score_calib", "board": "score-calib",
           "prereg": {"file": "reports/studies/2026-11-12_score_calib.md", "commit": "40cd49bc0", "m": M, "alpha_bonf": ALPHA,
                      "is_end": str(IS_END), "oos_start": str(OOS_START), "step_days": STEP, "horizons": list(HS),
                      "entry": "t+1 종가", "bench": "같은 형성일 적격 종목 동일가중 평균", "bins": "B1[0,20) B2[20,40) B3[40,60) B4[60,80) B5[80,100]; R 상단=[60,100]",
                      "cost": "미반영(점수 보정 — 매매 전략 아님)", "nw_lag": NW_LAG, "err_cut_abs_daily": ERR, "min_n_per_bin": MIN_N,
                      "filters": {"KR": "종가≥1000원·20일 거래대금≥10억원·SMA200", "US": "종가≥$3·≥$5M·SMA200"}},
           "survivorship": {"KR": "data/hist 상폐 포함(시총 필터 미적용)", "US": "현재 상세 유니버스 666종목 — 생존편향, 현재 구성 후향분석 · 등급 상한 B"},
           "dsr": "해당 없음 — 전략 선택이 아니라 사전 고정 18셀 검정(§0-5)",
           "code": {"scoring": "screener/scoring.py@aaa5e0d89", "indicators": "screener/indicators.py@aaa5e0d89"},
           "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "markets": {}, "grades": {}}
    if OUT.exists():
        old = json.loads(OUT.read_text(encoding="utf-8"))
        out["markets"] = old.get("markets", {})
    for mk in a.market:
        print(f"[{mk}] 계산", file=sys.stderr)
        out["markets"][mk] = analyze(mk, build(mk))
    tests = {k: v for mk in out["markets"].values() for k, v in mk["tests"].items()}
    out["grades"] = {k: v["grade"] for k, v in sorted(tests.items())}
    out["holm_oos"] = holm(tests)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float) + "\n", encoding="utf-8")
    print(json.dumps(out["grades"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
