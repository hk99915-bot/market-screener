"""미장 운용회의 매수후보·회피 규칙의 '가격 조건' 부분만 사후 검정 (연구 전용, 매매 지시 아님).

규칙(screener/us_committee.py): 매수후보 = drv ≥ 0.4 AND 20일수익 ≤ −3% / 회피 = drv ≤ −0.2 AND 20일수익 ≥ +5%.
drv(이익추정 요약)의 과거 이력은 저장소에 없다(data/fin/us_quarterly.parquet 는 보고 실적, 추정 이력 아님) → drv 부분은 검정 불가, 가격 조건만 본다.
사전등록(이 파일 커밋이 결과 json 보다 먼저): 가설 m=2, α=0.05/2=0.025(단측), 분할 IS ≤2019-12-31 / OOS 2020~.
  HA: r20 ≤ −3% 종목의 향후 4거래일 초과수익(= 종목수익 − 그날 유니버스 동일가중 평균) > 0   (매수후보 가격 조건)
  HB: r20 ≥ +5% 종목의 향후 4거래일 초과수익 < 0                                          (회피 가격 조건)
  추출: 4거래일마다 1날짜(비중첩) → 날짜별 그룹 평균 초과수익 시계열 → 평균·t(단측).
등급 규약: A=Bonferroni 통과+OOS 같은 방향 · B=Bonferroni 통과 · C=보정 전 p<0.10 · F=효과 없음/반대 · 검증전.
한계: 유니버스는 data/hist/us_*.parquet 의 현재 상장 223종목(2010~2025) — 생존편향, S&P500 1999~ 구성종목 이력 아님.
"""
from __future__ import annotations

import glob
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "reports/studies/2026-10-23_us_r20_reversal.json"
H, LO, HI, SPLIT = 4, -0.03, 0.05, "2019-12-31"


def p_one(t: float, sign: int) -> float:
    """단측 정규 근사 p. sign=+1: 평균>0 가설, −1: 평균<0 가설."""
    z = t * sign
    return 0.5 * math.erfc(z / math.sqrt(2))


def group_series(px: pd.DataFrame, h: int = H) -> dict:
    """px: index=date, columns=symbol 종가. 반환: 날짜별 r20·향후 h일 초과수익으로 만든 그룹 평균 시계열."""
    r20 = px / px.shift(20) - 1
    fwd = px.shift(-h) / px - 1
    exc = fwd.sub(fwd.mean(axis=1), axis=0)
    idx = px.index[20:-h:h]                                    # 비중첩
    r20, exc = r20.loc[idx], exc.loc[idx]
    a = exc.where(r20 <= LO).mean(axis=1, skipna=True)         # 해당 종목 없는 날은 NaN
    b = exc.where(r20 >= HI).mean(axis=1, skipna=True)
    na = (r20 <= LO).sum(axis=1)
    nb = (r20 >= HI).sum(axis=1)
    return {"A": a.dropna(), "B": b.dropna(), "nA": float(na.sum()), "nB": float(nb.sum())}


def summarize(s: pd.Series, sign: int) -> dict:
    n = len(s)
    if n < 3:
        return {"n_dates": n}
    m, sd = float(s.mean()), float(s.std(ddof=1))
    t = m / (sd / math.sqrt(n)) if sd > 0 else 0.0
    return {"n_dates": n, "mean": m, "t": t, "p_one": p_one(t, sign), "win": float((s * sign > 0).mean())}


def run(files: list[str]) -> dict:
    d = pd.concat([pd.read_parquet(f, columns=["yf", "date", "close"]) for f in files])
    d["date"] = pd.to_datetime(d["date"])
    px = d.pivot_table(index="date", columns="yf", values="close").sort_index()
    px = px.loc[:, px.notna().mean() > 0.8]                      # 거의 전 기간 있는 종목만
    g = group_series(px)
    out = {"study": "us_r20_reversal", "date": "2026-10-23", "m": 2, "alpha_bonf": 0.025, "h": H, "lo": LO, "hi": HI, "split": SPLIT,
           "universe": {"symbols": int(px.shape[1]), "first": str(px.index[0].date()), "last": str(px.index[-1].date()),
                        "note": "현재 상장 종목 → 생존편향. S&P500 1999~ 구성종목 이력 아님"},
           "events": {"A_stock_days": g["nA"], "B_stock_days": g["nB"]}, "H": {}}
    for k, name, sign in (("A", "HA 매수후보 가격조건 r20≤−3%", +1), ("B", "HB 회피 가격조건 r20≥+5%", -1)):
        s = g[k]
        isx, oos = s[s.index <= SPLIT], s[s.index > SPLIT]
        r = {"name": name, "all": summarize(s, sign), "IS": summarize(isx, sign), "OOS": summarize(oos, sign)}
        p, om = r["all"].get("p_one", 1), r["OOS"].get("mean", 0) * sign
        same = r["IS"].get("mean", 0) * sign > 0 and om > 0
        r["grade"] = "A" if p < 0.025 and same else "B" if p < 0.025 else "C" if p < 0.10 else "F"
        out["H"][k] = r
    return out


def main() -> int:
    files = sorted(glob.glob(str(ROOT / "data/hist/us_*.parquet")))
    res = run(files)
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1))
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
