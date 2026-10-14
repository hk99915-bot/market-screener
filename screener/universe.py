"""유니버스 구성.

KR: pykrx → FinanceDataReader → universe/kr.csv (폴백 순서). 성공 시 CSV 갱신.
US: nasdaqtrader 심볼 디렉터리 → universe/us.csv 폴백.
반환: Polars DataFrame [symbol, yf, name, market, mcap(nullable)]
"""
from __future__ import annotations

import io
import logging
from datetime import date

import polars as pl
import requests

from .config import UNIVERSE_DIR

log = logging.getLogger(__name__)
UA = {"User-Agent": "Mozilla/5.0"}


def _save(df: pl.DataFrame, name: str) -> None:
    UNIVERSE_DIR.mkdir(exist_ok=True)
    df.write_csv(UNIVERSE_DIR / f"{name}.csv")


def _load(name: str) -> pl.DataFrame | None:
    p = UNIVERSE_DIR / f"{name}.csv"
    if not p.exists():
        return None
    df = pl.read_csv(p, schema_overrides={"symbol": pl.Utf8})
    log.warning("유니버스 폴백: %s (%d종목, 수정 %s)", p.name, len(df),
                date.fromtimestamp(p.stat().st_mtime))
    return df


# ───────────────────────── KR ─────────────────────────

def _kr_pykrx() -> pl.DataFrame:
    from datetime import timedelta
    from pykrx import stock  # type: ignore
    frames = []
    for mkt, suffix in (("KOSPI", ".KS"), ("KOSDAQ", ".KQ")):
        cap = None
        for back in range(8):  # 장 시작 전·휴장일이면 직전 영업일로
            d = (date.today() - timedelta(days=back)).strftime("%Y%m%d")
            cap = stock.get_market_cap(d, market=mkt)
            if cap is not None and not cap.empty and cap["시가총액"].sum() > 0:
                break
        if cap is None or cap.empty:
            raise RuntimeError(f"pykrx {mkt} 시총 비어 있음")
        names = {t: stock.get_market_ticker_name(t) for t in cap.index}
        frames.append(pl.DataFrame({
            "symbol": list(cap.index), "yf": [t + suffix for t in cap.index],
            "name": [names[t] for t in cap.index], "market": mkt,
            "mcap": cap["시가총액"].astype(float).tolist(),
        }))
    return pl.concat(frames)


def _kr_fdr() -> pl.DataFrame:
    import FinanceDataReader as fdr  # type: ignore
    df = fdr.StockListing("KRX")
    df = df[df["Market"].isin(["KOSPI", "KOSDAQ"])]
    return pl.DataFrame({
        "symbol": df["Code"].astype(str).tolist(),
        "yf": [c + (".KS" if m == "KOSPI" else ".KQ") for c, m in zip(df["Code"], df["Market"])],
        "name": df["Name"].tolist(), "market": df["Market"].tolist(),
        "mcap": df["Marcap"].astype(float).tolist() if "Marcap" in df else [None] * len(df),
    })


def kr_universe() -> pl.DataFrame:
    for fn in (_kr_pykrx, _kr_fdr):
        try:
            df = fn()
            # 우선주/스팩/ETF류 제거: 이름 기반 간단 필터
            df = df.filter(~pl.col("name").str.contains(r"스팩|SPAC|ETN|ETF|리츠|\d호$|우$|우B$|우C$"))
            _save(df, "kr")
            log.info("KR 유니버스 %s: %d종목", fn.__name__, len(df))
            return df
        except Exception as e:  # noqa: BLE001
            log.warning("KR 유니버스 %s 실패: %s", fn.__name__, e)
    df = _load("kr")
    if df is None:
        raise RuntimeError("KR 유니버스를 가져올 수 없고 폴백 CSV도 없음")
    return df


# ───────────────────────── US ─────────────────────────

def _us_nasdaqtrader() -> pl.DataFrame:
    base = "https://www.nasdaqtrader.com/dynamic/SymDir/"
    rows = []
    for fn in ("nasdaqlisted.txt", "otherlisted.txt"):
        r = requests.get(base + fn, headers=UA, timeout=30)
        r.raise_for_status()
        txt = r.text.strip().split("\n")
        txt = [l for l in txt if not l.startswith("File Creation Time")]
        df = pl.read_csv(io.StringIO("\n".join(txt)), separator="|", infer_schema_length=0)
        if fn == "nasdaqlisted.txt":
            df = df.filter((pl.col("ETF") == "N") & (pl.col("Test Issue") == "N"))
            sym, name, mkt = "Symbol", "Security Name", pl.lit("NASDAQ")
        else:
            df = df.filter((pl.col("ETF") == "N") & (pl.col("Test Issue") == "N"))
            sym, name = "ACT Symbol", "Security Name"
            mkt = pl.when(pl.col("Exchange") == "N").then(pl.lit("NYSE")) \
                    .when(pl.col("Exchange") == "A").then(pl.lit("AMEX")).otherwise(pl.lit("OTHER"))
        rows.append(df.select(
            pl.col(sym).alias("symbol"), pl.col(name).alias("name"), mkt.alias("market")))
    df = pl.concat(rows)
    # 워런트/우선주/유닛 등 제외 (심볼에 $ . ^ 포함, 이름에 Warrant/Preferred/Unit/Right)
    df = df.filter(
        ~pl.col("symbol").str.contains(r"[\$\.\^]")
        & ~pl.col("name").str.contains(r"(?i)warrant|preferred|\bunit\b|\bright\b|depositary|notes due|debenture")
        & (pl.col("market") != "OTHER")
    ).with_columns(
        pl.col("symbol").str.replace("-", "-").alias("yf"),  # yfinance 도 BRK-B 형식 사용
        pl.lit(None, dtype=pl.Float64).alias("mcap"),
    ).select("symbol", "yf", "name", "market", "mcap")
    return df


def us_universe() -> pl.DataFrame:
    try:
        df = _us_nasdaqtrader()
        _save(df, "us")
        log.info("US 유니버스 nasdaqtrader: %d종목", len(df))
        return df
    except Exception as e:  # noqa: BLE001
        log.warning("US 유니버스 실패: %s", e)
    df = _load("us")
    if df is None:
        raise RuntimeError("US 유니버스를 가져올 수 없고 폴백 CSV도 없음")
    return df


# ───────────────────────── US 유니버스 축소 (거래대금 상위 N) ─────────────────────────

def us_liquid_subset(full: pl.DataFrame, top_n: int | None = None, refresh_days: int = 7) -> pl.DataFrame:
    """전체 상장 종목 중 최근 5일 평균 거래대금 상위 N 만 남김. 순위표는 universe/us_top.csv 에 캐시하고
    refresh_days 마다 갱신 (갱신은 5일치 소량 다운로드라 2~3분)."""
    import os, time
    top_n = top_n or int(os.environ.get("US_TOP_N", "300"))
    p = UNIVERSE_DIR / "us_top.csv"
    if p.exists() and (time.time() - p.stat().st_mtime) < refresh_days * 86400:
        top = pl.read_csv(p)
        log.info("US 유동성 상위 캐시 사용: %d종목", len(top))
        return full.filter(pl.col("yf").is_in(top["yf"].implode()))
    from .data import fetch_prices
    px = fetch_prices(full["yf"].to_list(), "US_RANK", lookback_days=10)
    rank = (px.with_columns((pl.col("close") * pl.col("volume")).alias("dv"))
              .group_by("yf").agg(pl.col("dv").mean().alias("dv5"), pl.col("close").last().alias("px"))
              .filter(pl.col("px") >= 3).sort("dv5", descending=True).head(top_n))
    rank.write_csv(p)
    log.info("US 유동성 상위 %d 갱신 (최저 거래대금 $%.1fM)", len(rank), rank["dv5"].min() / 1e6)
    return full.filter(pl.col("yf").is_in(rank["yf"].implode()))


# ───────────────────────── US 지수 구성종목 (S&P 500 ∪ Nasdaq-100) ─────────────────────────

INDEX_SOURCES = {
    "SP500": ("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", "Symbol", 480),
    "NDX": ("https://en.wikipedia.org/wiki/Nasdaq-100", "Ticker", 95),
}


def _wiki_tickers(url: str, col: str, min_n: int) -> list[str]:
    import pandas as pd
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0 (market-screener)"}, timeout=30)
    r.raise_for_status()
    for t in pd.read_html(io.StringIO(r.text)):
        if col in t.columns:
            syms = [str(s).strip().replace(".", "-") for s in t[col].dropna()]
            if len(syms) >= min_n:
                return syms
    raise RuntimeError(f"{url}: '{col}' 열의 구성종목 표를 찾지 못함")


def us_index_members(refresh_days: int = 7) -> set[str]:
    """S&P 500 ∪ Nasdaq-100 구성종목 (yfinance 형식). 주 1회 갱신, 캐시는 universe/us_index.csv."""
    import time
    p = UNIVERSE_DIR / "us_index.csv"
    if p.exists() and (time.time() - p.stat().st_mtime) < refresh_days * 86400:
        return set(pl.read_csv(p)["yf"].to_list())
    syms: set[str] = set()
    for name, (url, col, min_n) in INDEX_SOURCES.items():
        got = _wiki_tickers(url, col, min_n)
        log.info("US %s 구성종목 %d개", name, len(got))
        syms |= set(got)
    pl.DataFrame({"yf": sorted(syms)}).write_csv(p)
    return syms


def us_index_universe(full: pl.DataFrame) -> pl.DataFrame | None:
    """지수 구성종목만 남긴 유니버스. 실패하면 None 을 돌려 호출부가 거래대금 상위 방식으로 폴백하게 함."""
    try:
        mem = us_index_members()
    except Exception as e:  # noqa: BLE001
        log.warning("US 지수 구성종목 실패, 거래대금 상위 방식으로 폴백: %s", e)
        return None
    base = full.filter(pl.col("yf").is_in(sorted(mem)))
    missing = sorted(mem - set(base["yf"].to_list()))   # nasdaqtrader 목록에 없는 종목(예: BRK-B 등)
    if missing:
        extra = pl.DataFrame({
            "symbol": missing, "yf": missing, "name": missing,
            "market": ["US"] * len(missing), "mcap": [None] * len(missing),
        }, schema={"symbol": pl.Utf8, "yf": pl.Utf8, "name": pl.Utf8,
                   "market": pl.Utf8, "mcap": pl.Float64})
        base = pl.concat([base, extra], how="vertical_relaxed")
    log.info("US 지수 유니버스 %d종목 (S&P500 ∪ NDX)", len(base))
    return base
