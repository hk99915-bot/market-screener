"""screener.portfolios — 체결 시점 분리(월말 신호 → 다음 거래일 체결), 네트워크 없이 합성 가격표."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from screener import portfolios as pf


def _raw(seed=0, start="2009-01-01", end="2013-06-20"):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(start, end)
    cols = {}
    for j, c in enumerate(pf.TICKERS):
        base = 1100.0 if c == "USDKRW" else 20.0 if c == "VIX" else 100.0
        cols[c] = base * np.exp(np.cumsum(rng.normal(0.0003, 0.01, len(idx))))
    raw = pd.DataFrame(cols, index=idx)
    raw.loc[raw.index[::17], "K200"] = np.nan      # 한국 휴장일(미국은 거래) 흉내
    return raw


def test_exec_prices_next_trading_day_per_asset():
    idx = pd.to_datetime(["2026-01-29", "2026-01-30", "2026-02-02", "2026-02-03", "2026-02-27", "2026-03-02"])
    raw = pd.DataFrame({"SPY": [1, 2, 3, 4, 5, 6], "K200": [10, 20, np.nan, 40, 50, 60]}, index=idx, dtype=float)
    labels = pd.to_datetime(["2026-01-31", "2026-02-28", "2026-03-31"])
    ex = pf.exec_prices(raw, raw.ffill(), labels)
    assert ex["SPY"].tolist() == [3, 6, 6]           # 1월 신호 → 2/2 종가, 3월(진행 중) → 최신
    assert ex["K200"].tolist() == [40, 60, 60]       # 2/2 한국 휴장 → 2/3 종가


def test_run_reports_lagged_and_same_close(tmp_path, monkeypatch):
    monkeypatch.setattr(pf, "REPORT_DIR", tmp_path)
    out = pf.run(start_bt="2010-06-01", raw=_raw())
    assert out["exec"].startswith("월말 종가 신호")
    by = {s["name"]: s for s in out["strategies"]}
    for nm in ("60/40", "듀얼 모멘텀", "섹터 모멘텀 롱숏"):
        assert by[nm]["stats"] and by[nm]["stats_same_close"]
        assert by[nm]["stats"]["months"] == by[nm]["stats_same_close"]["months"]
    assert "stats_same_close" not in by["롱 스트래들"]
    assert (tmp_path / "portfolios.json").exists()


def test_lagged_return_uses_next_day_execution_prices(tmp_path, monkeypatch):
    """60/40 첫 구간 수익률 = 다음 거래일 체결가(원화) 기준 가중 수익률 − 첫 매수 비용(회전율 1 × COST)."""
    raw = _raw(seed=1)
    monkeypatch.setattr(pf, "REPORT_DIR", tmp_path)
    out = pf.run(start_bt="2010-06-01", raw=raw)
    kp = pf._krw(raw.ffill())
    me = kp.resample("ME").last()
    ex = pf.exec_prices(raw, kp, me.index)
    m0, m1 = [m for m in me.index if m >= pd.Timestamp("2010-06-01")][:2]
    w = {"SPY": .30, "QQQ": .15, "K200": .15, "IEF": .40}
    want = sum(wt * (ex.loc[m1, a] / ex.loc[m0, a] - 1) for a, wt in w.items()) - pf.COST
    s = {x["name"]: x for x in out["strategies"]}["60/40"]
    assert s["curve"][0][1] == pytest.approx(1 + want, abs=1e-4)
    same = sum(wt * (me.loc[m1, a] / me.loc[m0, a] - 1) for a, wt in w.items()) - pf.COST
    assert abs(want - same) > 1e-6                    # 체결 시점이 실제로 바뀜
