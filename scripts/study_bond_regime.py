#!/usr/bin/env python3
"""bond_regime_v1 (kb:bonds#25) 라벨 계산·분포 보고. 임계는 bonds.md #25 그대로(2026-11-02 고정) — 변경 금지, 변경은 새 id.
입력 data/hist/us_2010~2025.parquet 의 ^TNX·HYG·IEF 종가. 라벨은 격자 t0 기준 t0-1 종가까지만 사용.
  A: ^TNX 20거래일 차 >= +0.20 급등 / <= -0.20 급락 / 중립 · B: t0-1 값의 직전 756거래일(최소 250) 백분위 상위 1/3 고·하위 1/3 저·중
  C: HYG/IEF 20거래일 변화 <= -1.0% 약화.  격자 = KR 거래일 2011-01 첫날부터 20거래일마다.
"""
from __future__ import annotations
import json, sys
from pathlib import Path
import numpy as np, pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def load_us() -> pd.DataFrame:
    d = pd.concat(pd.read_parquet(ROOT / "data" / "hist" / f"us_{y}.parquet", columns=["yf", "date", "close"]) for y in range(2010, 2026))
    d = d[d.yf.isin(["^TNX", "HYG", "IEF"])]
    p = d.pivot(index="date", columns="yf", values="close").sort_index()
    p.index = pd.to_datetime(p.index)
    return p


def daily_labels() -> pd.DataFrame:
    """미국 거래일 기준 일별 라벨(해당 일 종가까지). 격자에서는 t0 직전 미국 거래일 값을 쓴다."""
    p = load_us()
    t = p["^TNX"]
    dA = t - t.shift(20)
    A = np.where(dA >= 0.20, "급등", np.where(dA <= -0.20, "급락", "중립"))
    pct = t.rolling(756, min_periods=250).apply(lambda w: (w[:-1] < w[-1]).mean() if False else (w < w[-1]).mean(), raw=True)
    B = np.where(pct.isna(), "NA", np.where(pct >= 2 / 3, "고", np.where(pct <= 1 / 3, "저", "중")))
    ratio = p["HYG"] / p["IEF"]
    chg = ratio / ratio.shift(20) - 1
    C = np.where(chg.isna(), "NA", np.where(chg <= -0.01, "약화", "비약화"))
    A = np.where(dA.isna(), "NA", A)
    return pd.DataFrame({"tnx": t, "dA": dA, "A": A, "pctB": pct, "B": B, "chgC": chg, "C": C}, index=p.index)


def grid_dates() -> list[pd.Timestamp]:
    import polars as pl
    from screener.prices import load_kr
    ds = sorted(load_kr(hist_from=2010).select("date").unique()["date"].to_list())
    ds = [pd.Timestamp(x) for x in ds]
    i0 = next(i for i, x in enumerate(ds) if x >= pd.Timestamp("2011-01-01"))
    return ds[i0::20]


def grid_labels(last_t0: str = "2025-12-31") -> pd.DataFrame:
    lab = daily_labels()
    rows = []
    for t0 in grid_dates():
        if t0 > pd.Timestamp(last_t0):
            break
        prev = lab.index[lab.index < t0]          # t0-1 = t0 이전 마지막 미국 거래일(시차 보수적)
        if len(prev) == 0:
            continue
        r = lab.loc[prev[-1]]
        rows.append({"t0": t0, "A": r.A, "B": r.B, "C": r.C})
    return pd.DataFrame(rows).set_index("t0")


def runs(s: pd.Series) -> dict:
    out = {}
    for v in s.unique():
        m = (s == v).astype(int).values
        out[v] = int(((m[1:] == 1) & (m[:-1] == 0)).sum() + (m[0] == 1))
    return out


def main() -> None:
    lab = daily_labels()
    lab = lab[lab.index >= "2011-01-01"]
    res = {"daily": {}, "grid": {}}
    for ax in "ABC":
        s = lab[ax]; s = s[s != "NA"]
        res["daily"][ax] = {"days": s.value_counts().to_dict(), "transitions": int((s != s.shift()).sum() - 1), "runs": runs(s)}
    g = grid_labels()
    g = g[g.index >= "2011-01-01"]
    res["grid_n"] = len(g)
    for ax in "ABC":
        s = g[ax]
        res["grid"][ax] = {"n": s.value_counts().to_dict(), "IS": s[s.index < "2020-01-01"].value_counts().to_dict(),
                           "OOS": s[s.index >= "2020-01-01"].value_counts().to_dict(), "runs": runs(s), "transitions": int((s != s.shift()).sum() - 1)}

    def phi(a, b):
        x, y = a.values.astype(float), b.values.astype(float)
        return float(np.corrcoef(x, y)[0, 1])
    res["phi_grid"] = {"급등~약화": phi(g.A == "급등", g.C == "약화"), "급락~약화": phi(g.A == "급락", g.C == "약화"),
                       "고~약화": phi(g.B == "고", g.C == "약화"), "급등~고": phi(g.A == "급등", g.B == "고")}
    res["cross_AC"] = pd.crosstab(g.A, g.C).to_dict()
    res["phi_daily"] = {"급락~약화": phi(lab.A == "급락", lab.C == "약화"), "급등~약화": phi(lab.A == "급등", lab.C == "약화")}
    res["unique_grid_labels_by_year"] = {str(y): g[g.index.year == y][["A", "C"]].apply(lambda c: c.value_counts().to_dict()).to_dict() for y in (2020, 2022)}
    print(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    g.to_csv(ROOT / "reports" / "studies" / "2026-11-03_bond_regime_v1_grid.csv")


if __name__ == "__main__":
    main()
