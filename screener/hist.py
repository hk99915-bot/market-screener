"""연구용 시세 창고 로더 — data/hist/*_daily.parquet (ETF·지수·업종·미국) 를 네트워크 없이 읽는다.

파일 (scripts/build_hist.py 가 만들고 .github/workflows/hist.yml 이 주 1회 갱신)
  kr_etf_daily.parquet     국내 ETF (심볼 = 6자리 코드, 예 "069500")
  kr_index_daily.parquet   국내 지수 (KOSPI, KOSPI200, KOSDAQ — 시가 포함 OHLC)
  kr_sector_daily.parquet  국내 업종 (KRX 공식 업종지수 "KRX:<이름>" + universe/kr_sector.csv 동일가중 합성 "EW:<업종>")
  us_daily.parquet         미국 ETF·종목·지수 (야후 티커: SPY, QQQ, SOXX, MU, ^GSPC …)
  _manifest.json           심볼별 첫·끝 날짜·행수·출처

스키마 (long): date(Date) symbol(str) open high low close adj_close(Float32) volume(Float64) src(str)
  - 야후(auto_adjust) 출처는 close == adj_close (배당·분할 반영). KRX/pykrx 출처는 close 가 원주가, adj_close 는 분할(±45% 갭) 보정치.
  - 합성 업종(EW:)은 지수화(2010-01-04 = 1000), volume 은 null.

사용
    from screener.hist import load, symbols, manifest
    px = load("069500", start="2015-01-01")                   # 한 심볼
    px = load(["069500", "122630", "SPY"], start="2020-01-01")  # 여러 심볼 (파일은 자동으로 찾음)
    w  = wide(["069500", "SPY"], field="adj_close")            # date × symbol 피벗
"""
from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

import polars as pl

from .config import DATA_DIR

HIST_DIR = Path(os.environ.get("HIST_DIR") or (DATA_DIR / "hist"))
FILES = ("kr_etf_daily", "kr_index_daily", "kr_sector_daily", "us_daily")
SCHEMA = {"date": pl.Date, "symbol": pl.Utf8, "open": pl.Float32, "high": pl.Float32, "low": pl.Float32,
          "close": pl.Float32, "adj_close": pl.Float32, "volume": pl.Float64, "src": pl.Utf8}
_ALIAS = {"^KS11": "KOSPI", "^KS200": "KOSPI200", "^KQ11": "KOSDAQ", "K200": "KOSPI200"}


def _d(x: str | date) -> date:
    return x if isinstance(x, date) else date.fromisoformat(str(x)[:10])


def empty() -> pl.DataFrame:
    return pl.DataFrame(schema=SCHEMA)


def norm_symbol(s: str) -> str:
    """'069500.KS' → '069500', '^KS11' → 'KOSPI'. 그 외는 그대로 (대소문자 유지)."""
    s = str(s).strip()
    if s in _ALIAS:
        return _ALIAS[s]
    if s.endswith((".KS", ".KQ")) and s[:-3].isdigit():
        return s[:-3]
    return s


def manifest(root: Path | None = None) -> dict:
    p = (root or HIST_DIR) / "_manifest.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def symbols(name: str | None = None, root: Path | None = None) -> dict[str, dict]:
    """심볼 → {file, first, last, rows, source}. name 을 주면 그 파일만."""
    out: dict[str, dict] = {}
    for fn, info in manifest(root).get("files", {}).items():
        if name and fn != name:
            continue
        for s, m in info.get("symbols", {}).items():
            out[s] = {"file": fn, **m}
    return out


def _files_for(syms: list[str] | None, root: Path, name: str | None) -> list[Path]:
    if name:
        return [root / f"{name}.parquet"]
    if syms:
        known = symbols(root=root)
        hits = {known[s]["file"] for s in syms if s in known}
        if hits and all(s in known for s in syms):
            return [root / f"{f}.parquet" for f in sorted(hits)]
    return [root / f"{f}.parquet" for f in FILES]


def load(symbol: str | list[str] | None = None, start: str | date | None = None, end: str | date | None = None,
         name: str | None = None, root: Path | None = None) -> pl.DataFrame:
    """long 프레임 반환 (date, symbol, open, high, low, close, adj_close, volume, src), (symbol, date) 정렬.
    symbol=None 이면 name 파일(또는 전부). 파일이 없으면 빈 프레임 — 네트워크 접근 없음."""
    root = Path(root) if root else HIST_DIR
    syms = None if symbol is None else [norm_symbol(s) for s in ([symbol] if isinstance(symbol, str) else symbol)]
    parts = []
    for f in _files_for(syms, root, name):
        if not f.exists():
            continue
        lf = pl.scan_parquet(f)
        if syms:
            lf = lf.filter(pl.col("symbol").is_in(syms))
        if start:
            lf = lf.filter(pl.col("date") >= _d(start))
        if end:
            lf = lf.filter(pl.col("date") <= _d(end))
        parts.append(lf)
    if not parts:
        return empty()
    df = pl.concat(parts, how="vertical_relaxed").collect()
    if not len(df):
        return empty()
    df = df.unique(["symbol", "date"], keep="last").sort("symbol", "date")
    return df.select(*[pl.col(c).cast(t) for c, t in SCHEMA.items()])


def wide(symbol: str | list[str], field: str = "adj_close", start=None, end=None, root: Path | None = None) -> pl.DataFrame:
    """date × symbol 피벗 (field 한 개). 비어 있으면 date 컬럼만 있는 빈 프레임."""
    df = load(symbol, start, end, root=root)
    if not len(df):
        return pl.DataFrame(schema={"date": pl.Date})
    return df.pivot(on="symbol", index="date", values=field, aggregate_function="last").sort("date")


def coverage(symbol: str | list[str], root: Path | None = None) -> pl.DataFrame:
    """심볼별 first/last/rows (파일을 직접 세서 매니페스트와 무관하게 확인)."""
    df = load(symbol, root=root)
    if not len(df):
        return pl.DataFrame(schema={"symbol": pl.Utf8, "first": pl.Date, "last": pl.Date, "rows": pl.UInt32})
    return df.group_by("symbol").agg(pl.col("date").min().alias("first"), pl.col("date").max().alias("last"),
                                     pl.len().alias("rows")).sort("symbol")
