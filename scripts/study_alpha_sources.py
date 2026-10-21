#!/usr/bin/env python3
"""알파 소스 교체 연구 — 사전등록 reports/studies/2026-10-21_alpha_sources.md §0 (HF, 보드 hf-alphabook).

  python3 scripts/study_alpha_sources.py            # reports/studies/2026-10-21_alpha_sources.json + md 결과 절
  python3 scripts/study_alpha_sources.py --quick    # 표본 축소 점검(결과 파일 안 씀)

엔진 = scripts/study_tradeplan.py (build_entries·to_r·scale_out·_stats) 그대로 — tradeplan 보정과 같은 청산 규칙(struct, 1.5/3.0, H20).
가설 A1·A2(업종 내 상대강도) · B1·B2(52주 고점 근접) · C1(외국인+기관 수급 지속) · D1(애널 목표가 상향), m = 6.
통과(B) = OOS 초과 E[R] > 0 · t ≥ 2.39 · 학습 초과 > 0 · OOS E[R] > 0. 알파북(screener/alphabook.py)은 통과 소스만 진입 후보로 쓴다.
영향 범위: 이 json 을 screener/alphabook.py 가 읽는다(소스 통과 여부·OOS 확률). 워크플로 변경 없음. 롤백: json 삭제 → 알파북 '탐색 중'.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import study_tradeplan as st  # noqa: E402

KST = timezone(timedelta(hours=9))
STOP, R1, R2 = "struct", 1.5, 3.0
M = 6
Z_BONF = 2.39       # 단측 α 0.05/6 = 0.0083
Z_C = 1.645
LIQ = {"KR": (1e9, 1000), "US": (2e7, 5)}
STUDY = "2026-10-21_alpha_sources"


def run_cell(E, market, split):
    """엔트리 → (학습, 검증) 통계 dict (struct·1.5/3.0 분할 청산, 비용 차감)."""
    if not len(E.get("C", [])):
        return {"train": {"n": 0}, "test": {"n": 0}}
    O, Hh, L, Cw, cost, ok, _ = st.to_r(E, STOP, market)
    res, k1, hit2 = st.scale_out(O, Hh, L, Cw, R1, R2)
    net = res - cost
    dates = E["date"][ok]
    tr = dates < np.datetime64(split)
    out = {}
    for nm, msk in (("train", tr), ("test", ~tr)):
        k = k1[msk]
        out[nm] = st._stats(net[msk], dates[msk], {
            "p_t1": round(float((k == 0).mean()), 3) if len(k) else None,
            "p_s": round(float((k == 1).mean()), 3) if len(k) else None,
            "p_t2": round(float(hit2[msk].mean()), 3) if len(k) else None})
    return out


def excess(sig, base):
    """신호 − 기준선 초과 E[R] 와 t (SE 합성)."""
    if not sig.get("n") or not base.get("n") or sig.get("se") is None or base.get("se") is None:
        return {"ex": None, "t": None}
    ex = sig["ev_r"] - base["ev_r"]
    se = (sig["se"] ** 2 + base["se"] ** 2) ** 0.5
    return {"ex": round(ex, 4), "t": round(ex / se, 2) if se > 0 else None}


def grade(cell: dict) -> str:
    t, b = cell["test"], cell["base_test"]
    if (t.get("n_dates") or 0) < 30:
        return "검증전"
    xo, xt = cell["ex_test"], cell["ex_train"]
    if xo["ex"] is None:
        return "검증전"
    if xo["ex"] > 0 and (xo["t"] or 0) >= Z_BONF and (xt["ex"] or 0) > 0 and (t.get("ev_r") or 0) > 0:
        return "B"
    if xo["ex"] > 0 and (xo["t"] or 0) >= Z_C:
        return "C(방향만)"
    return "F"


def _sub(E, mask):
    return {k: v[mask] for k, v in E.items()}


def flag_pick(df: pl.DataFrame, col: str, step: int):
    """df(sym·date 정렬)의 bool 열 → build_entries 용 pick(sym, dates, c): 격자(60+step 배수) ∩ 신호."""
    flags = {s: g[col].to_numpy() for (s,), g in df.group_by(["sym"], maintain_order=True)}

    def pick(sym, dates, c):
        f = flags.get(sym)
        if f is None:
            return []
        grid = np.arange(60, len(c) - st.H - 1, step)
        return grid[f[grid]] if len(grid) else []
    return pick


def grid_pick(step):
    return lambda sym, dates, c: np.arange(60, len(c) - st.H - 1, step)


def features(df: pl.DataFrame, sector: dict, min_val: float, min_px: float) -> pl.DataFrame:
    """60일 수익률·업종 내 백분위(유동 종목만)·52주 고점 근접."""
    df = df.with_columns(
        (pl.col("close") / pl.col("close").shift(60).over("sym") - 1).alias("r60"),
        (pl.col("close") * pl.col("volume")).rolling_mean(20).over("sym").alias("val20"),
        pl.col("high").rolling_max(250).over("sym").alias("hi250"),
        pl.col("sym").replace_strict(sector, default=None).alias("sec"),
    )
    liq = (pl.col("val20") >= min_val) & (pl.col("close") >= min_px) & pl.col("r60").is_not_null() & pl.col("sec").is_not_null()
    df = df.with_columns(liq.fill_null(False).alias("liq"))
    ranked = (df.filter(pl.col("liq"))
                .with_columns(pl.len().over(["date", "sec"]).alias("nsec"),
                              ((pl.col("r60").rank().over(["date", "sec"]) - 1) / (pl.len().over(["date", "sec"]) - 1)).alias("rs_pct"))
                .select("sym", "date", "nsec", "rs_pct"))
    df = df.join(ranked, on=["sym", "date"], how="left")
    return df.with_columns(
        ((pl.col("nsec") >= 5) & (pl.col("rs_pct") >= 0.8)).fill_null(False).alias("f_rs"),
        ((pl.col("close") / pl.col("hi250")) >= 0.95).fill_null(False).alias("f_hi"),
    ).sort("sym", "date")


def hyp_price(market, step, quick):
    years = range(2010, 2026) if not quick else range(2016, 2026)
    df = st.load_hist(market, years)
    if market == "KR":
        sec = pl.read_csv(ROOT / "universe" / "kr_sector.csv", schema_overrides={"code": pl.Utf8})
        sector = {f"{c}.KS": s for c, s in zip(sec["code"], sec["sector"])} | {f"{c}.KQ": s for c, s in zip(sec["code"], sec["sector"])}
    else:
        sec = pl.read_csv(ROOT / "universe" / "us_sector.csv")
        sector = dict(zip(sec["yf"], sec["sector"]))
    mv, mp = LIQ[market]
    df = features(df, sector, mv, mp)
    base = st.build_entries(df, market, grid_pick(step), None, mv, mp)
    rs = st.build_entries(df, market, flag_pick(df, "f_rs", step), None, mv, mp)
    hi = st.build_entries(df, market, flag_pick(df, "f_hi", step), None, mv, mp)
    return base, rs, hi


def kr_recent_prices() -> pl.DataFrame:
    h = st.load_hist("KR", [2024, 2025])
    from screener.prices import load_kr
    k = load_kr().rename({"yf": "sym"}).select("sym", "date", "open", "high", "low", "close", "volume")
    k = k.filter(pl.col("date") > h["date"].max())
    return pl.concat([h, k], how="vertical_relaxed").drop_nulls().filter(pl.col("open") > 0).unique(["sym", "date"]).sort("sym", "date")


def hyp_flows(px: pl.DataFrame, step: int):
    fs = sorted((ROOT / "data" / "flows").glob("kr_inv_*.parquet"))
    if not fs:
        return None, None, "데이터 없음(data/flows/kr_inv_*.parquet — data_store pull 필요)"
    f = pl.concat([pl.read_parquet(x).select("date", "code", "mcap", "f", "i") for x in fs], how="vertical_relaxed").sort("code", "date")
    f = f.with_columns((pl.col("f") + pl.col("i")).cast(pl.Float64).alias("fi"))
    f = f.with_columns(pl.col("fi").rolling_sum(20).over("code").alias("fi20"),
                       (pl.col("fi") > 0).cast(pl.Int32).rolling_sum(20).over("code").alias("pos20"))
    f = f.with_columns((pl.col("fi20") / pl.col("mcap").cast(pl.Float64)).alias("int20"))
    px = px.with_columns(pl.col("sym").str.slice(0, 6).alias("code"),
                         (pl.col("close") * pl.col("volume")).rolling_mean(20).over("sym").alias("val20"))
    px = px.join(f.select("code", "date", "int20", "pos20"), on=["code", "date"], how="left")
    ok = (pl.col("val20") >= LIQ["KR"][0]) & (pl.col("close") >= LIQ["KR"][1]) & pl.col("int20").is_not_null()
    px = px.with_columns(ok.fill_null(False).alias("liq"))
    rk = (px.filter(pl.col("liq")).with_columns(((pl.col("int20").rank().over("date") - 1) / (pl.len().over("date") - 1)).alias("pct"))
            .select("sym", "date", "pct"))
    px = px.join(rk, on=["sym", "date"], how="left").with_columns(
        ((pl.col("pct") >= 0.8) & (pl.col("pos20") >= 14)).fill_null(False).alias("f_flow"),
        pl.col("liq").alias("f_base")).sort("sym", "date")
    mv, mp = LIQ["KR"]
    base = st.build_entries(px, "KR", flag_pick(px, "f_base", step), None, mv, mp)
    sig = st.build_entries(px, "KR", flag_pick(px, "f_flow", step), None, mv, mp)
    return base, sig, None


def research_events(min_gap: int = 5) -> pl.DataFrame:
    r = pl.read_parquet(ROOT / "data" / "research.parquet").select("date", "code", "broker", "target").drop_nulls()
    r = r.filter(pl.col("target") > 0).sort("code", "broker", "date")
    r = r.with_columns(pl.col("target").shift(1).over(["code", "broker"]).alias("prev"))
    up = r.filter(pl.col("prev").is_not_null() & (pl.col("target") > pl.col("prev"))).select("code", "date").unique().sort("code", "date")
    # 같은 종목 5거래일(≈7일) 안 중복은 첫 건
    keep, last = [], {}
    for c, d in up.iter_rows():
        if c in last and (d - last[c]).days <= 7:
            continue
        keep.append((c, d))
        last[c] = d
    return pl.DataFrame(keep, schema=["code", "date"], orient="row")


def hyp_research(px: pl.DataFrame):
    ev = research_events()
    want = {}
    for c, d in ev.iter_rows():
        want.setdefault(c, set()).add(str(d))

    def pick(sym, dates, c):
        ds = want.get(sym[:6]) or set()
        return [i for i, d in enumerate(dates.astype("datetime64[D]").astype(str)) if d in ds]
    mv, mp = LIQ["KR"]
    sig = st.build_entries(px.filter(pl.col("sym").str.slice(0, 6).is_in(list(want))), "KR", pick, None, mv, mp)
    return sig, ev.height


def cell(key, desc, market, split, sig, base, extra=None):
    s, b = run_cell(sig, market, split), run_cell(base, market, split)
    c = {"key": key, "desc": desc, "market": market, "split": split,
         "train": s["train"], "test": s["test"], "base_train": b["train"], "base_test": b["test"],
         "ex_train": excess(s["train"], b["train"]), "ex_test": excess(s["test"], b["test"]), **(extra or {})}
    c["grade"] = grade(c)
    c["pass"] = c["grade"] == "B"
    print(key, c["grade"], "test", c["test"].get("ev_r"), "base", c["base_test"].get("ev_r"), "ex", c["ex_test"], flush=True)
    return c


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    a = ap.parse_args(argv)
    step = 40 if a.quick else 10
    cells = {}
    kb, krs, khi = hyp_price("KR", step, a.quick)
    cells["A1"] = cell("A1", "KR 업종 내 60일 상대강도 상위 20%", "KR", "2020-01-01", krs, kb, {"src": "kr_sector_rs"})
    cells["B1"] = cell("B1", "KR 52주 고점 근접(≥0.95)", "KR", "2020-01-01", khi, kb, {"src": "kr_52w_high"})
    del kb, krs, khi
    ub, urs, uhi = hyp_price("US", step, a.quick)
    cells["A2"] = cell("A2", "US 업종 내 60일 상대강도 상위 20%", "US", "2020-01-01", urs, ub, {"src": "us_sector_rs"})
    cells["B2"] = cell("B2", "US 52주 고점 근접(≥0.95)", "US", "2020-01-01", uhi, ub, {"src": "us_52w_high"})
    del ub, urs, uhi
    px = kr_recent_prices()
    fb, fs, err = hyp_flows(px, 5)
    if err:
        cells["C1"] = {"key": "C1", "desc": "KR 외국인+기관 수급 지속", "grade": "검증전", "pass": False, "error": err, "src": "kr_flow_persist"}
    else:
        cells["C1"] = cell("C1", "KR 외국인+기관 20일 중 14일+ 순매수·강도 상위 20%", "KR", "2025-09-01", fs, fb, {"src": "kr_flow_persist"})
    rb = st.build_entries(px.filter(pl.col("date") >= pl.date(2024, 10, 1)), "KR", grid_pick(5), None, *LIQ["KR"])
    rs, n_ev = hyp_research(px)
    cells["D1"] = cell("D1", "KR 애널 목표가 상향(같은 증권사 직전 대비)", "KR", "2025-10-01", rs, rb, {"src": "kr_tp_up", "n_events": n_ev})
    cells["D2"] = {"key": "D2", "desc": "US 이익 추정 상향(us_eps chg30)", "grade": "검증전", "pass": False, "src": "us_eps_rev",
                   "error": "데이터 없음 — reports/us_eps.json 스냅숏만(git 이력 4판, 2026-10-15~), 20일 선행 결과 불가", "m_excluded": True}
    cells["E"] = {"key": "E", "desc": "이벤트 드리븐(event_driven H8·H13)", "grade": "검증전", "pass": False, "src": "event_driven",
                  "error": "reports/studies/2026-10-21_event_driven.json 없음(§0 만) — 결과 나오면 같은 규칙 재검", "m_excluded": True}
    today = datetime.now(KST).date()
    out = {"v": 1, "asof": str(today), "generated_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M KST"), "study": STUDY,
           "prereg": f"reports/studies/{STUDY}.md §0", "m": M, "alpha_bonf": round(0.05 / M, 4), "z_bonf": Z_BONF,
           "engine": {"stop": STOP, "scale": f"{R1}/{R2}", "H": st.H, "cost": st.COST, "entry": "다음날 시가, 구간 C±0.5ATR"},
           "grade_rule": "B(통과) = OOS 초과>0·t≥2.39·학습 초과>0·OOS E[R]>0 / C(방향만) = OOS 초과>0·t≥1.645 / F / 검증전 = OOS 신호일<30",
           "cells": cells, "passed": [k for k, c in cells.items() if c.get("pass")], "quick": a.quick}
    if a.quick:
        print(json.dumps(out["passed"]))
        return out
    p = ROOT / "reports" / "studies" / f"{STUDY}.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("wrote", p)
    return out


if __name__ == "__main__":
    main()
