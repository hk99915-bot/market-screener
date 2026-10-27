"""검증 데스크 — SOX 대 S&P500 단기 상대수익률 재계산·분위 재현 (req-verify-7829ae44).

질문: 10/12~10/23 SOX 상대수익률이 언론(10/23) '약 −13%, 20여 년 최악' vs PB 재계산 −9.6%(SOX −11.9% vs S&P −2.4%).
명세(사전 고정, §0): 상대수익률 = SOX 기간 수익률 − S&P500 기간 수익률(차, %p). 보조 = 비율 (1+r_sox)/(1+r_spx)−1.
  기간 수익률 = 종가(end)/종가(base) − 1. base 후보 3개(10/08·10/09·10/12 종가), end 10/23 종가.
  총수익 대조: S&P 는 ^SP500TR(배당 재투자). SOX 는 가격지수만(총수익 지수 미보유 — 9거래일 배당 영향 ≈ 연 1%×9/252 ≈ 0.04%p).
  분위: 2000-01-03 이후 모든 n거래일 롤링 창(겹침 포함)의 상대수익률 분포에서 해당 값보다 나쁜 창 비율.
  '에피소드' = 값 이하 창을 2n 영업일 간격으로 묶은 최악 1개(겹침 제거 근사).
데이터: yfinance ^SOX·^GSPC·^SP500TR 일봉 종가(auto_adjust 안 함). 원 코드·PB 계산 미열람(명세만).

  python scripts/replicate_sox_rel.py --csv <closes.csv>   # 열: Date,^GSPC,^SOX,^SP500TR
  python scripts/replicate_sox_rel.py                      # yfinance 직접 다운로드
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT_JSON = ROOT / "reports" / "studies" / "replication_sox_rel.json"
SOX, SPX, SPXTR = "^SOX", "^GSPC", "^SP500TR"
BASES = ("2026-10-08", "2026-10-09", "2026-10-12")
END = "2026-10-23"
CLAIMS = {"언론(10/23)": -0.13, "PB 재계산": -0.096}


def window(px: pd.DataFrame, base: str, end: str, a: str = SOX, b: str = SPX) -> dict:
    ra = px.loc[end, a] / px.loc[base, a] - 1
    rb = px.loc[end, b] / px.loc[base, b] - 1
    n = int(((px.index > pd.Timestamp(base)) & (px.index <= pd.Timestamp(end))).sum())
    return {"base": base, "end": end, "n_ret": n, "sox": round(ra, 4), "mkt": round(rb, 4),
            "diff": round(ra - rb, 4), "ratio": round((1 + ra) / (1 + rb) - 1, 4)}


def rolling_diff(px: pd.DataFrame, n: int, a: str = SOX, b: str = SPX) -> pd.Series:
    return ((px[a] / px[a].shift(n) - 1) - (px[b] / px[b].shift(n) - 1)).dropna()


def rank(series: pd.Series, v: float) -> dict:
    worse = int((series < v).sum())
    return {"n_windows": int(len(series)), "worse": worse, "pctile": round(100 * worse / len(series), 2)}


def episodes(series: pd.Series, v: float, n: int) -> list[tuple[str, float]]:
    ep: list[list] = []
    for t, x in series[series <= v].items():
        if ep and (t - ep[-1][0]).days <= 2 * n * 7 / 5:
            if x < ep[-1][1]:
                ep[-1] = [t, x]
        else:
            ep.append([t, x])
    return [(str(t.date()), round(float(x), 4)) for t, x in ep]


def run(px: pd.DataFrame) -> dict:
    px = px[px.index >= "2000-01-01"].dropna(subset=[SOX, SPX])
    out = {"data": {"from": str(px.index[0].date()), "to": str(px.index[-1].date()), "rows": int(len(px))},
           "windows": [], "ranks": []}
    for bse in BASES:
        w = window(px, bse, END)
        if SPXTR in px:
            w["diff_tr"] = window(px, bse, END, b=SPXTR)["diff"]
        out["windows"].append(w)
    for w in out["windows"]:
        s = rolling_diff(px, w["n_ret"])
        prior = s[(s <= w["diff"]) & (s.index < pd.Timestamp(w["base"]))]
        ep = [e for e in episodes(s, w["diff"], w["n_ret"]) if e[0] < w["base"]]
        out["ranks"].append({"base": w["base"], "n": w["n_ret"], "value": w["diff"], **rank(s, w["diff"]),
                             "last_as_bad": (str(prior.index[-1].date()), round(float(prior.iloc[-1]), 4)) if len(prior) else None,
                             "episodes_before": len(ep), "episodes_since_2003": [e for e in ep if e[0] >= "2003-01-01"]})
    return out


def load(csv: str | None) -> pd.DataFrame:
    if csv:
        return pd.read_csv(csv, index_col=0, parse_dates=True)
    import yfinance as yf
    d = yf.download([SOX, SPX, SPXTR], start="1999-12-01", auto_adjust=False, progress=False)
    return d["Close"]


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv")
    ap.add_argument("--no-write", action="store_true")
    a = ap.parse_args(argv)
    r = run(load(a.csv))
    r["claims"] = CLAIMS
    if not a.no_write:
        OUT_JSON.write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(r, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    sys.exit(main())
