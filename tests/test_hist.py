"""screener.hist 로더 — 작은 합성 parquet 로 네트워크 없이 검사 (심볼 정규화, 기간 필터, 피벗, 빈 결과, 매니페스트 라우팅)."""
import json
from datetime import date, timedelta

import polars as pl
import pytest

from screener import hist


def _mk(symbol: str, n: int, base: float, src: str) -> pl.DataFrame:
    d0 = date(2024, 1, 1)
    dates = [d0 + timedelta(days=i) for i in range(n)]
    return pl.DataFrame({"date": dates, "symbol": symbol, "open": [base + i for i in range(n)], "high": [base + i + 1 for i in range(n)],
                         "low": [base + i - 1 for i in range(n)], "close": [base + i for i in range(n)],
                         "adj_close": [base + i for i in range(n)], "volume": [100.0] * n, "src": src}
                        ).select(*[pl.col(c).cast(t) for c, t in hist.SCHEMA.items()])


@pytest.fixture
def root(tmp_path):
    pl.concat([_mk("069500", 10, 30000, "yfinance"), _mk("122630", 10, 20000, "yfinance")]).write_parquet(tmp_path / "kr_etf_daily.parquet")
    _mk("KOSPI", 10, 2500, "pykrx").write_parquet(tmp_path / "kr_index_daily.parquet")
    _mk("SPY", 10, 500, "yfinance").write_parquet(tmp_path / "us_daily.parquet")
    man = {"files": {"kr_etf_daily": {"symbols": {"069500": {"first": "2024-01-01", "last": "2024-01-10", "rows": 10, "source": "yfinance"},
                                                   "122630": {"first": "2024-01-01", "last": "2024-01-10", "rows": 10, "source": "yfinance"}}},
                     "kr_index_daily": {"symbols": {"KOSPI": {"first": "2024-01-01", "last": "2024-01-10", "rows": 10, "source": "pykrx"}}},
                     "us_daily": {"symbols": {"SPY": {"first": "2024-01-01", "last": "2024-01-10", "rows": 10, "source": "yfinance"}}}}}
    (tmp_path / "_manifest.json").write_text(json.dumps(man), encoding="utf-8")
    return tmp_path


def test_norm_symbol():
    assert hist.norm_symbol("069500.KS") == "069500"
    assert hist.norm_symbol("^KS11") == "KOSPI"
    assert hist.norm_symbol("SPY") == "SPY"


def test_load_single_and_range(root):
    df = hist.load("069500.KS", start="2024-01-03", end="2024-01-05", root=root)
    assert df["symbol"].unique().to_list() == ["069500"]
    assert df["date"].to_list() == [date(2024, 1, 3), date(2024, 1, 4), date(2024, 1, 5)]
    assert list(df.columns) == list(hist.SCHEMA)
    assert df.schema["close"] == pl.Float32


def test_load_many_across_files(root):
    df = hist.load(["069500", "SPY", "KOSPI"], root=root)
    assert sorted(df["symbol"].unique().to_list()) == ["069500", "KOSPI", "SPY"]
    assert len(df) == 30
    assert df.sort("symbol", "date").equals(df)


def test_wide_pivot(root):
    w = hist.wide(["069500", "122630"], field="adj_close", root=root)
    assert w.columns == ["date", "069500", "122630"]
    assert len(w) == 10
    assert float(w["069500"][0]) == 30000.0


def test_missing_is_empty(root, tmp_path):
    assert hist.load("000000", root=root).shape == (0, len(hist.SCHEMA))
    assert hist.load("SPY", root=tmp_path / "nowhere").shape == (0, len(hist.SCHEMA))
    assert hist.wide("000000", root=root).columns == ["date"]


def test_symbols_and_coverage(root):
    s = hist.symbols(root=root)
    assert s["SPY"]["file"] == "us_daily" and s["069500"]["last"] == "2024-01-10"
    cov = hist.coverage(["SPY", "KOSPI"], root=root)
    assert cov["rows"].to_list() == [10, 10]
