import json

import polars as pl

from screener import us_eps_hist as h

SNAP = {"A": {"eps": {"0y": {"cur": 6.2, "chg30": 0.01, "chg90": 0.02}, "+1y": {"cur": 6.7, "chg30": -0.002, "chg90": None}}},
        "B": {"eps": {}}, "C": None}


def test_rows_skip_empty():
    r = h.rows_from_snapshot("2026-10-24 06:57", SNAP)
    assert {(x["ticker"], x["period"], x["date"]) for x in r} == {("A", "0y", "2026-10-24"), ("A", "+1y", "2026-10-24")}


def test_upsert_overwrites_same_day_and_appends(tmp_path):
    p = tmp_path / "h.parquet"
    h.upsert(h.rows_from_snapshot("2026-10-24 06:57", SNAP), p)
    s2 = {"A": {"eps": {"0y": {"cur": 9.9, "chg30": 0.0, "chg90": 0.0}}}}
    h.upsert(h.rows_from_snapshot("2026-10-24 18:00", s2), p)
    n = h.upsert(h.rows_from_snapshot("2026-10-25 06:57", SNAP), p)
    df = pl.read_parquet(p)
    assert n == df.height == 4
    assert df.filter((pl.col("date") == "2026-10-24") & (pl.col("period") == "0y"))["cur"].to_list() == [9.9]


def test_rebuild_from_archive(tmp_path):
    a = tmp_path / "arch"; a.mkdir()
    (a / "2026-10-17.json").write_text(json.dumps({"asof": "2026-10-18 00:07", "data": SNAP}))
    (a / "2026-10-19.json").write_text(json.dumps({"asof": "2026-10-20 06:56", "data": SNAP}))
    assert h.rebuild_from_archive(a, tmp_path / "o.parquet") == 4
