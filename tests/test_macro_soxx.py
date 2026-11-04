"""req-data_eng-1cd9cbd1 (겸이 11/4 「SOXX로 트래킹햇」): macro_series 에 반도체 SOX(^SOX)·SOXX(ETF) 일봉 OHLCV 추가.
키·네트워크 없이 합성 시세로 write_macro_series 가 두 시리즈를 SPX·NASDAQ 와 같은 dohlcv 행 형식으로 쓰는지 확인한다.
실수집(야후 실제 응답·행 수·날짜 범위)은 Actions 몫."""
import json
from datetime import date, timedelta

import polars as pl
import pytest

from screener import config, data, guard, main
from screener.config import CFG


def _synth(symbols, days=30):
    rows = []
    d0 = date(2026, 9, 1)
    for i, s in enumerate(symbols):
        for j in range(days):
            c = 100.0 + i + j
            rows.append({"yf": s, "date": d0 + timedelta(days=j), "open": c - 1, "high": c + 2, "low": c - 2, "close": c, "volume": 1000 * (j + 1)})
    return pl.DataFrame(rows)


def test_config_has_sox_and_soxx():
    assert CFG.macro["SOX"] == "^SOX"
    assert CFG.macro["SOXX"] == "SOXX"
    # 기존 키·심볼은 그대로
    assert CFG.macro["SPX"] == "^GSPC" and CFG.macro["NASDAQ"] == "^IXIC"


@pytest.fixture
def rep(tmp_path, monkeypatch):
    r = tmp_path / "reports"
    r.mkdir()
    monkeypatch.setattr(guard, "_report_dir", lambda: r)
    monkeypatch.setattr(config, "REPORT_DIR", r)
    from screener import commodities, geo_news, live, macroview   # 실제 reports/ 를 덮어쓰지 않게 후속 빌더는 막는다
    monkeypatch.setattr(live, "snapshot", lambda *a, **k: {"items": []})
    for mod in (macroview, commodities, geo_news):
        monkeypatch.setattr(mod, "build", lambda *a, **k: None)
    monkeypatch.setattr(data, "fetch_prices", lambda syms, *a, **k: _synth(list(syms)))
    return r


def test_write_macro_series_includes_sox_soxx(rep):
    main.write_macro_series()
    d = json.loads((rep / "macro_series.json").read_text(encoding="utf-8"))
    ser = d["series"]
    for k in ("SPX", "NASDAQ", "SOX", "SOXX"):
        assert len(ser[k]) == 30
        row = ser[k][-1]
        assert len(row) == 6 and isinstance(row[0], str)   # [날짜, o, h, l, c, v]
        assert row[2] >= max(row[1], row[4]) and row[3] <= min(row[1], row[4])
    assert ser["SOX"][0][0] == ser["SPX"][0][0]
    assert d["asof_by"]["SOXX"] == d["asof_by"]["SOX"] == "2026-09-30"
