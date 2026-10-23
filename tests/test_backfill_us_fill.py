"""US 연도별 hist 증분 채우기(req-data-4e6e68fe) — 네트워크 없이 가짜 download."""
import json
import time
from datetime import date

import pandas as pd
import pytest
import polars as pl

from screener import backfill as bf


def _old(hist):
    pl.DataFrame({"yf": ["AAA", "AAA"], "date": [date(2024, 12, 30), date(2024, 12, 31)],
                  "open": [1.0, 1.0], "high": [1.0, 1.0], "low": [1.0, 1.0], "close": [1.0, 1.1],
                  "volume": [10.0, 10.0]}).with_columns(pl.col("date").cast(pl.Date)).write_parquet(hist / "us_2024.parquet")


def _fake(chunk):
    idx = pd.to_datetime(["2024-12-30", "2025-01-02"])
    cols = {}
    for s in chunk:
        if s == "NEW":  # 상장 전 — 빈 값
            continue
        for k in ("Open", "High", "Low", "Close", "Volume"):
            cols[(s, k)] = [2.0, 3.0]
    return pd.DataFrame(cols, index=idx)


def test_fill_adds_missing_only(tmp_path, monkeypatch):
    monkeypatch.setattr(bf, "HIST", tmp_path)
    monkeypatch.setattr(bf, "FILL_LOG", tmp_path / "us_fill.json")
    monkeypatch.setattr(bf, "_us_targets", lambda: ["AAA", "BBB", "NEW"])
    _old(tmp_path)
    asked = []
    done = bf.backfill_us_fill(2024, 1e9, time.time(), end_year=2026, pause_s=0,
                               download=lambda c: (asked.append(list(c)), _fake(c))[1])
    assert asked == [["BBB", "NEW"]]  # AAA 는 이미 있음
    assert done is True
    y24 = pl.read_parquet(tmp_path / "us_2024.parquet")
    y25 = pl.read_parquet(tmp_path / "us_2025.parquet")
    assert sorted(y24["yf"].unique().to_list()) == ["AAA", "BBB"]
    assert y24.filter(pl.col("yf") == "AAA")["close"].to_list() == pytest.approx([1.0, 1.1])  # 기존 행 보존
    assert y25.filter(pl.col("yf") == "BBB")["close"].to_list() == [3.0]
    st = json.loads((tmp_path / "us_fill.json").read_text())
    assert st["no_data"] == ["NEW"] and st["left"] == 0 and st["have"] == 2
    # 두 번째 실행: 받을 것 없음 → download 호출 없음
    asked.clear()
    assert bf.backfill_us_fill(2024, 1e9, time.time(), end_year=2026, pause_s=0,
                               download=lambda c: (asked.append(c), _fake(c))[1]) is True
    assert asked == []


def test_fill_budget_stops(tmp_path, monkeypatch):
    monkeypatch.setattr(bf, "HIST", tmp_path)
    monkeypatch.setattr(bf, "FILL_LOG", tmp_path / "us_fill.json")
    monkeypatch.setattr(bf, "_us_targets", lambda: ["BBB"])
    assert bf.backfill_us_fill(2024, -1, time.time(), end_year=2026, pause_s=0, download=_fake) is False
    assert json.loads((tmp_path / "us_fill.json").read_text())["left"] == 1
