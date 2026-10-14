"""장기 히스토리 백필 (백테스트용) → data/hist/{kr,us}_{YYYY}.parquet

KR: KRX 날짜별 전종목 시세 (상장폐지 종목 포함 → 생존편향 없음). 연도별 파일, 원주가(수정 전).
    로드 시 load_hist('KR') 가 전 기간을 합쳐 기업행위 보정.
US: yfinance, 현재 거래대금 상위 N 종목의 전체 이력 (생존편향 있음 — 상폐 종목 빠짐).

시간 예산(기본 300분)을 넘기면 스스로 멈추고, 다음 실행에서 이어서 받는다.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import date, timedelta

import polars as pl

from .config import DATA_DIR, UNIVERSE_DIR

log = logging.getLogger("backfill")
HIST = DATA_DIR / "hist"


def _done_marker(market: str, year: int):
    return HIST / f"{market.lower()}_{year}.parquet"


def backfill_kr(start_year: int, budget_s: float, t0: float) -> bool:
    """True = 전부 완료."""
    from .data_krx import _fetch_day
    HIST.mkdir(parents=True, exist_ok=True)
    this_year = date.today().year
    for y in range(start_year, this_year):  # 올해는 일일 파이프라인(kr_prices.parquet)이 담당
        out = _done_marker("KR", y)
        if out.exists():
            continue
        part = HIST / f"kr_{y}.partial.parquet"
        have = pl.read_parquet(part) if part.exists() else None
        done_days = set(have["date"].unique().to_list()) if have is not None else set()
        frames = [have] if have is not None else []
        d = date(y, 1, 1)
        fails = 0
        while d.year == y:
            if d.weekday() < 5 and d not in done_days:
                if time.time() - t0 > budget_s:
                    if frames:
                        pl.concat(frames).write_parquet(part)
                    log.info("시간 예산 소진 — %s 까지 저장, 다음 실행에서 이어감", d)
                    return False
                try:
                    df = _fetch_day(d)
                    if len(df):
                        frames.append(df)
                    fails = 0
                except Exception as e:  # noqa: BLE001
                    fails += 1
                    log.warning("KR %s 실패: %s", d, e)
                    if fails >= 8:
                        if frames:
                            pl.concat(frames).write_parquet(part)
                        raise RuntimeError("KRX 연속 실패 — 중단 (진행분 저장됨)") from e
                    time.sleep(5)
            d += timedelta(days=1)
            if d.month != (d - timedelta(days=1)).month and frames:  # 월마다 중간 저장
                pl.concat(frames).write_parquet(part)
                log.info("KR %d-%02d 저장", y, (d - timedelta(days=1)).month)
        df = pl.concat(frames).unique(["yf", "date"]).sort("yf", "date")
        df.write_parquet(out, compression="zstd")
        part.unlink(missing_ok=True)
        log.info("KR %d 완료: %d행", y, len(df))
    return True


def backfill_us(start_year: int, budget_s: float, t0: float) -> bool:
    import pandas as pd
    import yfinance as yf
    HIST.mkdir(parents=True, exist_ok=True)
    marker = HIST / "us_done.txt"
    if marker.exists():
        return True
    top = UNIVERSE_DIR / "us_top.csv"
    if not top.exists():
        log.warning("universe/us_top.csv 없음 — US 일일 실행 후 다시 시도")
        return False
    syms = pl.read_csv(top)["yf"].to_list() + ["SPY", "QQQ", "IWM", "^GSPC", "^IXIC", "^VIX", "^TNX"]
    frames = []
    for i in range(0, len(syms), 100):
        if time.time() - t0 > budget_s:
            return False
        chunk = syms[i:i + 100]
        try:
            raw = yf.download(chunk, start=f"{start_year}-01-01", end=f"{date.today().year}-01-01", auto_adjust=True,
                              group_by="ticker", threads=True, progress=False, timeout=120)
        except Exception as e:  # noqa: BLE001
            log.warning("US 배치 %d 실패: %s", i // 100, e)
            continue
        if len(chunk) == 1:
            raw = pd.concat({chunk[0]: raw}, axis=1)
        for s in chunk:
            if s not in raw.columns.get_level_values(0):
                continue
            d = raw[s].dropna(subset=["Close"])
            if d.empty:
                continue
            frames.append(pl.DataFrame({
                "yf": s, "date": [x.date() for x in pd.to_datetime(d.index)],
                "open": d["Open"].astype(float).values, "high": d["High"].astype(float).values,
                "low": d["Low"].astype(float).values, "close": d["Close"].astype(float).values,
                "volume": d["Volume"].fillna(0).astype(float).values}))
        log.info("US 배치 %d/%d", i // 100 + 1, (len(syms) + 99) // 100)
    if not frames:
        return False
    df = pl.concat(frames).with_columns(pl.col("date").cast(pl.Date))
    for (y,), g in df.with_columns(pl.col("date").dt.year().alias("_y")).group_by("_y"):
        g.drop("_y").sort("yf", "date").write_parquet(HIST / f"us_{y}.parquet", compression="zstd")
    marker.write_text(date.today().isoformat())
    log.info("US 완료: %d행, %d종목", len(df), df["yf"].n_unique())
    return True


def load_hist(market: str) -> pl.DataFrame:
    """전 기간 시세 (장기 히스토리 + 올해 일일 데이터). KR 은 기업행위 보정 적용."""
    files = sorted(HIST.glob(f"{market.lower()}_[0-9][0-9][0-9][0-9].parquet"))
    parts = [pl.read_parquet(f) for f in files]
    cur = DATA_DIR / f"{market.lower()}_prices.parquet"
    if cur.exists():
        parts.append(pl.read_parquet(cur))
    df = pl.concat(parts, how="vertical_relaxed").unique(["yf", "date"], keep="last").sort("yf", "date")
    if market == "KR":
        from .data_krx import adjust_splits
        df = adjust_splits(df)
    return df


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", choices=["KR", "US", "ALL"], default="ALL")
    ap.add_argument("--start", type=int, default=int(os.environ.get("BACKFILL_START", "2010")))
    ap.add_argument("--budget-min", type=float, default=300)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", stream=sys.stderr)
    t0, budget = time.time(), a.budget_min * 60
    done = True
    if a.market in ("US", "ALL"):
        done &= backfill_us(max(a.start, 2005), budget, t0)
    if a.market in ("KR", "ALL"):
        done &= backfill_kr(a.start, budget, t0)
    print("BACKFILL", "COMPLETE" if done else "PARTIAL")


if __name__ == "__main__":
    main()
