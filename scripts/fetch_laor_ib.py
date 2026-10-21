"""라오어 무한매수 백테스트(reports/studies/2026-10-21_laor_infinite_buy.md) 원자료 수집 — Actions 전용(컨테이너는 야후 차단).

.github/workflows/laor_ib_data.yml 이 실행 → data/study/laor_ib_px.csv 를 study-data/laor-ib-<run> 브랜치에 올린다(main 미변경).
열: date, <심볼>_high, <심볼>_close, <심볼>_adj (야후 auto_adjust=False), dbn_DEXKOUS(Fed H.10 원/달러). 결측은 빈칸.
금액·보유 없음(지수·ETF 가격·환율·금리만). fetch_qld_dca.py 패턴 재사용.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_qld_dca import dbn_fx  # noqa: E402

YF = ["SOXL", "TQQQ", "QQQ", "SOXX", "^SOX", "^NDX", "^IRX", "KRW=X"]
OUT = Path("data/study/laor_ib_px.csv")


def yf_ohlc(sym: str) -> pd.DataFrame:
    import yfinance as yf
    df = yf.download(sym, start="1980-01-01", interval="1d", auto_adjust=False, progress=False)
    if df is None or not len(df):
        print(f"::warning::{sym} 데이터 없음")
        return pd.DataFrame()
    if hasattr(df.columns, "levels"):
        df.columns = [c[0] for c in df.columns]
    df = df[["High", "Close", "Adj Close"]].rename(columns={"High": f"{sym}_high", "Close": f"{sym}_close", "Adj Close": f"{sym}_adj"})
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    return df


def main() -> int:
    parts = [yf_ohlc(s) for s in YF]
    try:
        parts.append(dbn_fx())
    except Exception as e:  # noqa: BLE001 — 실패는 로그로 남기고 계속(야후 KRW=X 로 대체)
        print(f"::warning::dbnomics 환율 실패: {e}")
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
