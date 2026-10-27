"""KRX 수집 실패 시 1회 자동 재시도 (10/27 16:20 Akamai 차단 → 수동 재실행 성공 사례, PB 10/27 확정 지시)."""
from datetime import date

import polars as pl

from screener import data_krx as K
from screener import universe as U

UNI = pl.DataFrame({"symbol": ["005930"], "yf": ["005930.KS"], "name": ["삼성전자"], "market": ["KOSPI"], "mcap": [1.0]})


def test_universe_retries_once_after_both_paths_fail(monkeypatch):
    calls, waits = [], []
    state = {"n": 0}

    def pyk():
        calls.append("pykrx")
        state["n"] += 1
        if state["n"] == 1:
            raise RuntimeError("403 Access Denied (Akamai)")
        return UNI

    def fdr():
        calls.append("fdr")
        raise RuntimeError("403")
    monkeypatch.setattr(U, "_kr_pykrx", pyk)
    monkeypatch.setattr(U, "_kr_fdr", fdr)
    monkeypatch.setattr(U, "_sleep", waits.append)
    monkeypatch.setattr(U, "_save", lambda df, k: None)
    df = U.kr_universe()
    assert len(df) == 1 and calls == ["pykrx", "fdr", "pykrx"] and waits == [U.KR_RETRY_WAIT]


def test_universe_falls_back_after_second_failure(monkeypatch):
    def bad():
        raise RuntimeError("403")
    monkeypatch.setattr(U, "_kr_pykrx", bad)
    monkeypatch.setattr(U, "_kr_fdr", bad)
    waits = []
    monkeypatch.setattr(U, "_sleep", waits.append)
    monkeypatch.setattr(U, "_load", lambda k: UNI)
    assert len(U.kr_universe()) == 1 and len(waits) == 1     # 재시도는 1회만, 그다음 폴백 CSV


def test_krx_day_retry_once(monkeypatch, tmp_path):
    monkeypatch.setattr(K, "PARQUET", tmp_path / "kr.parquet")
    monkeypatch.setattr(K, "DATA_DIR", tmp_path)
    waits, seen = [], {}
    monkeypatch.setattr(K.time, "sleep", waits.append)

    def day(d):
        seen[d] = seen.get(d, 0) + 1
        if seen[d] == 1:
            raise ConnectionError("Akamai reset")
        return pl.DataFrame({"yf": ["005930.KS"], "date": [d], "open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0], "volume": [1.0]},
                            schema=K.SCHEMA), False
    monkeypatch.setattr(K, "_fetch_day_flag", day)
    out = K.update(until=date(2026, 10, 27), lookback_days=1)
    assert len(out) == 2 and seen == {date(2026, 10, 26): 2, date(2026, 10, 27): 2}   # 이틀 모두 2차에 성공
    assert waits.count(K.DAY_RETRY_WAIT) == 2
