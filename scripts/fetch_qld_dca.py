"""QLD 적립 백테스트(reports/studies/2026-10-21_qld_daily_dca.md) 원자료 수집 — Actions 전용(컨테이너는 야후·FRED 차단).

.github/workflows/qld_dca_data.yml 이 실행 → data/study/qld_dca_px.csv 를 study-data/qld-dca 브랜치에 올린다.
열: date, <심볼>_close, <심볼>_adj (야후 auto_adjust=False 의 Close·Adj Close), fred_DEXKOUS(원/달러, 정오 NY),
fred_DTB3(3개월 T-bill 할인율 %). 결측은 빈칸. 금액·보유 없음(지수·환율·금리만).
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import pandas as pd
import requests

YF = ["QLD", "QQQ", "SPY", "^NDX", "^GSPC", "KRW=X", "^IRX"]
FRED = ["DEXKOUS", "DTB3"]
OUT = Path("data/study/qld_dca_px.csv")


def yf_one(sym: str) -> pd.DataFrame:
    import yfinance as yf
    df = yf.download(sym, start="1980-01-01", interval="1d", auto_adjust=False, progress=False)
    if df is None or not len(df):
        print(f"::warning::{sym} 데이터 없음")
        return pd.DataFrame()
    if hasattr(df.columns, "levels"):
        df.columns = [c[0] for c in df.columns]
    df = df[["Close", "Adj Close"]].rename(columns={"Close": f"{sym}_close", "Adj Close": f"{sym}_adj"})
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    return df


def fred_one(sid: str) -> pd.DataFrame:
    r = requests.get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}", timeout=60,
                     headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    df.columns = ["date", f"fred_{sid}"]
    df["date"] = pd.to_datetime(df["date"])
    df[f"fred_{sid}"] = pd.to_numeric(df[f"fred_{sid}"], errors="coerce")
    return df.set_index("date")


def stooq_fx() -> pd.DataFrame:
    """FRED 실패 대비 1: Stooq usdkrw 일봉 종가."""
    r = requests.get("https://stooq.com/q/d/l/?s=usdkrw&i=d", timeout=60, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    df["date"] = pd.to_datetime(df["Date"])
    return df.set_index("date")[["Close"]].rename(columns={"Close": "stooq_USDKRW"})


def dbn_fx() -> pd.DataFrame:
    """FRED 실패 대비 2: DBnomics 의 Fed H.10 원/달러(정오 NY, FRED DEXKOUS 와 같은 원천)."""
    r = requests.get("https://api.db.nomics.world/v22/series/FED/H10/RXI_N.B.KO?observations=1&format=json", timeout=90)
    r.raise_for_status()
    doc = r.json()["series"]["docs"][0]
    df = pd.DataFrame({"date": pd.to_datetime(doc["period"]), "dbn_DEXKOUS": pd.to_numeric(doc["value"], errors="coerce")})
    return df.set_index("date")


def main() -> int:
    parts = [yf_one(s) for s in YF]
    for s in FRED:
        for _ in range(3):
            try:
                parts.append(fred_one(s))
                break
            except Exception as e:  # noqa: BLE001 — 실패는 로그로 남기고 계속
                print(f"::warning::FRED {s} 실패: {e}")
    for name, fn in (("stooq", stooq_fx), ("dbnomics", dbn_fx)):
        try:
            parts.append(fn())
        except Exception as e:  # noqa: BLE001
            print(f"::warning::{name} 환율 실패: {e}")
    df = pd.concat([p for p in parts if len(p)], axis=1).sort_index()
    df.index.name = "date"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.round(6).to_csv(OUT)
    for c in df.columns:
        s = df[c].dropna()
        print(f"{c}: {len(s)}행 {s.index.min().date() if len(s) else '-'}~{s.index.max().date() if len(s) else '-'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
