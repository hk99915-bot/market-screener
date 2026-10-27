"""점도표 '기울기만' 점 검수 — 200일선 부호 → p_up = 0.5 ± 1/12 의 근거 (req-quant-41a36cce).

python scripts/study_dotplot_tilt.py → reports/studies/dotplot_tilt.json

사전 등록(결과 전, 2026-10-28 퀀트):
- 질문: screener/dotplot.py TILT_P = 1/12 — 200일선 위면 p_up 0.583, 아래면 0.417 — 가 과거 분포와 맞나(보정·calibration).
- 데이터(저장본): KOSPI = data/deriv/daily.csv kospi_close 2010~2026-10 · SPX = data/hist ^GSPC 2010~2025 +
  reports/macro_series.json SPX(2026 이어붙임) · SEMI_KR = 삼성·하이닉스 50/50 일간 리밸런싱(screener.lab.load_kr).
- 신호: 종가 vs 200일 단순이동평균 부호(당일 종가로 판정, 그 종가부터 h 거래일 뒤 수익). h = 5, 20(점도표 horizon).
- 지표: P(상승 | 위)·P(상승 | 아래), 겹침 보정 표준오차 = √(p(1−p)/(n/h)). Brier: 기울기 p(0.5±1/12) vs 0.5(무정보) vs 전체 상승률(기저율).
- m = 6 (3 자산 × 2 horizon) — 판정 단위는 '위−아래 상승률 차'. Bonferroni α = 0.0083, 등급은 kb:quant#4.
- 판정(사전): ① 위−아래 차 ≥ 1/6(=0.167, 현행 가정 그대로)이면 '1/12 지지' · 0 < 차 < 1/6 이면 '방향은 맞으나 과대' ·
  ≤0 이면 '근거 없음'. ② Brier(기울기) < Brier(0.5) 이면 '점수상 손해 없음'. IS ≤2019 / OOS 2020~ 부호 일치 확인.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "reports" / "studies" / "dotplot_tilt.json"
TILT = 1 / 12
M = 6
ALPHA = 0.05 / M


def _ncdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def series() -> dict[str, pd.Series]:
    out = {}
    k = pd.read_csv(ROOT / "data" / "deriv" / "daily.csv", usecols=["date", "kospi_close"]).dropna()
    out["KOSPI"] = pd.Series(k["kospi_close"].values, index=pd.to_datetime(k["date"])).sort_index()
    import glob
    us = pl.concat([pl.read_parquet(f).filter(pl.col("yf") == "^GSPC") for f in sorted(glob.glob(str(ROOT / "data/hist/us_20*.parquet")))],
                   how="diagonal_relaxed")
    spx = pd.Series(us["close"].to_numpy(), index=pd.to_datetime(us["date"].to_list())).sort_index()
    ms = json.load(open(ROOT / "reports" / "macro_series.json", encoding="utf-8"))["series"].get("SPX") or []
    extra = pd.Series({pd.Timestamp(r[0]): float(r[4]) for r in ms})
    extra = extra[extra.index > spx.index.max()]
    out["SPX"] = pd.concat([spx, extra]).sort_index()
    try:
        from screener.lab import load_kr
        st = load_kr().filter(pl.col("yf").is_in(["005930.KS", "000660.KS"])).select("yf", "date", "c").to_pandas()
        px = st.pivot(index="date", columns="yf", values="c").sort_index()
        px.index = pd.to_datetime(px.index)
        r = px.pct_change().mean(axis=1).fillna(0)
        out["SEMI_KR"] = (1 + r).cumprod()
    except Exception as e:  # noqa: BLE001 — 저장본 없으면 기록하고 건너뜀
        print("SEMI_KR 데이터 없음:", e)
    return out


def cell(s: pd.Series, h: int, mask: pd.Series | None = None) -> dict:
    sma = s.rolling(200).mean()
    fwd = s.shift(-h) / s - 1
    df = pd.DataFrame({"above": s > sma, "y": fwd > 0, "ok": sma.notna() & fwd.notna()})
    if mask is not None:
        df = df[mask.reindex(df.index).fillna(False)]
    df = df[df["ok"]]
    res = {}
    for name, g in (("above", df[df["above"]]), ("below", df[~df["above"]])):
        n = len(g); p = float(g["y"].mean()) if n else float("nan")
        res[name] = {"n": n, "n_eff": round(n / h, 1), "p_up": p}
    a, b = res["above"], res["below"]
    d = a["p_up"] - b["p_up"]
    se = math.sqrt(a["p_up"] * (1 - a["p_up"]) / max(a["n_eff"], 1) + b["p_up"] * (1 - b["p_up"]) / max(b["n_eff"], 1))
    z = d / se if se > 0 else float("nan")
    base = float(df["y"].mean())
    y = df["y"].astype(float).values
    pt = np.where(df["above"].values, 0.5 + TILT, 0.5 - TILT)
    pe = np.where(df["above"].values, a["p_up"], b["p_up"])
    return {**res, "diff": d, "se": se, "z": z, "p": 2 * (1 - _ncdf(abs(z))), "base_up": base,
            "brier_tilt": float(((pt - y) ** 2).mean()), "brier_half": float(((0.5 - y) ** 2).mean()),
            "brier_base": float(((base - y) ** 2).mean()), "brier_cond": float(((pe - y) ** 2).mean()),
            "share_above": float(df["above"].mean())}


def verdict(c: dict) -> str:
    if c["diff"] <= 0:
        return "근거 없음"
    return "1/12 지지" if c["diff"] >= 2 * TILT else "방향은 맞으나 과대"


def grade(c: dict, is_: dict, oos: dict) -> str:
    if c["p"] < ALPHA:
        return "A" if np.sign(is_["diff"]) == np.sign(oos["diff"]) == np.sign(c["diff"]) else "B"
    if c["p"] < 0.10:
        return "C"
    return "F"


def main() -> None:
    out = {"study": "dotplot_tilt", "req": "req-quant-41a36cce", "tilt": TILT, "m": M, "alpha": ALPHA, "cells": {}}
    for a, s in series().items():
        for h in (5, 20):
            c = cell(s, h)
            is_ = cell(s, h, pd.Series(s.index <= pd.Timestamp("2019-12-31"), index=s.index))
            oos = cell(s, h, pd.Series(s.index > pd.Timestamp("2019-12-31"), index=s.index))
            out["cells"][f"{a}_{h}d"] = {"all": c, "is": is_, "oos": oos, "verdict": verdict(c), "grade": grade(c, is_, oos),
                                        "range": [str(s.index[0].date()), str(s.index[-1].date())]}
            print(f"{a:8s} {h:2d}d 위 {c['above']['p_up']:.3f}(n_eff {c['above']['n_eff']}) 아래 {c['below']['p_up']:.3f}"
                  f"(n_eff {c['below']['n_eff']}) 차 {c['diff']:+.3f} p {c['p']:.3f} IS {is_['diff']:+.3f} OOS {oos['diff']:+.3f} "
                  f"Brier 기울기 {c['brier_tilt']:.4f} 0.5 {c['brier_half']:.4f} 기저 {c['brier_base']:.4f} → {verdict(c)} {out['cells'][f'{a}_{h}d']['grade']}")
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
