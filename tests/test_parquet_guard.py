import pytest

from screener import parquet_guard as g
from screener import prices
from scripts import data_store


def test_group_name_matches_data_store():
    assert g.GROUP in data_store.GROUPS
    assert g.PULL_CMD == "python scripts/data_store.py pull --groups hist_year"


def test_missing_hist_year_fails_with_pull_hint(tmp_path):
    with pytest.raises(g.HistYearMissing) as e:
        g.require_hist_year(tmp_path / "hist", "kr")
    assert g.PULL_CMD in str(e.value)


def test_load_kr_hist_from_fails_loudly_without_files(tmp_path):
    prices._load_cached.cache_clear()
    with pytest.raises(FileNotFoundError, match="pull --groups hist_year"):
        prices.load_kr(hist_from=2010, path=tmp_path / "kr_prices.parquet")


def test_present_files_pass(tmp_path):
    (tmp_path / "kr_2020.parquet").write_bytes(b"")
    (tmp_path / "kr_index_daily.parquet").write_bytes(b"")
    assert [p.rsplit("/", 1)[1] for p in g.require_hist_year(tmp_path)] == ["kr_2020.parquet"]
