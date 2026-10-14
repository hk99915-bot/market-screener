"""네트워크 없이 파이프라인 검증용 합성 시세 생성. 추세·횡보·급등 패턴을 섞음."""
import sys
from datetime import date, timedelta

import numpy as np
import polars as pl

rng = np.random.default_rng(7)
n_days, n_sym = 320, int(sys.argv[2]) if len(sys.argv) > 2 else 120
market = sys.argv[1] if len(sys.argv) > 1 else "KR"
dates = [d for d in (date.today() - timedelta(days=i) for i in range(460)) if d.weekday() < 5][:n_days][::-1]

frames, uni = [], []
for i in range(n_sym):
    kind = i % 4  # 0 상승추세 1 하락추세 2 횡보 3 급등
    drift = {0: 0.0015, 1: -0.0015, 2: 0.0, 3: 0.0005}[kind]
    vol = {0: 0.015, 1: 0.02, 2: 0.012, 3: 0.02}[kind]
    r = rng.normal(drift, vol, n_days)
    if kind == 3:
        r[-6:] += 0.035
    close = 50_000 * np.exp(np.cumsum(r)) if market == "KR" else 50 * np.exp(np.cumsum(r))
    hi = close * (1 + np.abs(rng.normal(0, 0.008, n_days)))
    lo = close * (1 - np.abs(rng.normal(0, 0.008, n_days)))
    op = np.r_[close[0], close[:-1]] * (1 + rng.normal(0, 0.004, n_days))
    v = rng.lognormal(12 if market == "KR" else 14, 0.4, n_days)
    if kind == 3:
        v[-1] *= 4
    sym = f"{100000 + i:06d}" if market == "KR" else f"SYM{i:03d}"
    yf = sym + (".KS" if market == "KR" else "")
    frames.append(pl.DataFrame({"yf": yf, "date": dates, "open": op, "high": hi, "low": lo, "close": close, "volume": v}))
    uni.append({"symbol": sym, "yf": yf, "name": f"{'종목' if market == 'KR' else 'Corp'}{i}", "market": "KOSPI" if market == "KR" else "NYSE", "mcap": 5e11})

px = pl.concat(frames).with_columns(pl.col("date").cast(pl.Date))
px.write_parquet(f"data/{market.lower()}_prices.parquet")
pl.DataFrame(uni).write_csv(f"universe/{market.lower()}.csv")
print(f"{market}: {n_sym}종목 × {n_days}일 생성")
