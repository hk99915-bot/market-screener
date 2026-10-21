"""미장 마감 EOD 토스 보충 (보드 us-eod-toss, 10/21) — 수집기 파서·수집 + screener 마지막 날 보충. 네트워크 없음."""
from __future__ import annotations

import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

import polars as pl

from screener import data, guard
from screener import main as smain
from tools.toss_md import collect, publish

KST = ZoneInfo("Asia/Seoul")
# 실측 키 꼴(10/21 노트북 --shape): result.candles[{timestamp, openPrice, highPrice, lowPrice, closePrice, volume}], 값은 합성
CANDLES = {"result": {"candles": [
    {"timestamp": "2026-10-19T16:00:00-04:00", "openPrice": 10.0, "highPrice": 11.0, "lowPrice": 9.5, "closePrice": 10.5, "volume": 1000},
    {"timestamp": "2026-10-20T16:00:00-04:00", "openPrice": 10.5, "highPrice": 12.0, "lowPrice": 10.1, "closePrice": 11.8, "volume": 2500},
]}}


def test_eod_bar_parser_picks_et_day():
    assert collect.eod_bar(CANDLES, "2026-10-20") == [10.5, 12.0, 10.1, 11.8, 2500.0]
    assert collect.eod_bar(CANDLES, "2026-10-21") is None


class _Client:
    def __init__(self):
        self.calls = []

    def get(self, path, params):
        self.calls.append((path, dict(params)))
        if params["symbol"] == "ZZZ":
            return {"result": {"candles": CANDLES["result"]["candles"][:1]}}   # 당일 봉 없음 → missing
        return CANDLES


def test_collect_us_eod_after_close_once(tmp_path):
    now = datetime(2026, 10, 21, 6, 20, tzinfo=KST)   # = 10/20 17:20 ET (화 06:20 KST)
    c = _Client()
    ok, fail, err = collect.collect_us_eod(c, tmp_path, now, dry_run=True, symbols=["AAPL", "BRK-B", "ZZZ"])
    assert (ok, fail, err) == (3, 0, None)
    assert c.calls[1] == ("/api/v1/candles", {"symbol": "BRK.B", "interval": "1d", "count": 3})
    rec = json.loads((tmp_path / "us_eod" / "2026-10-20.json").read_text(encoding="utf-8"))
    assert rec["date"] == "2026-10-20" and rec["n"] == 2 and rec["missing"] == ["ZZZ"]
    assert rec["bars"]["BRK-B"] == [10.5, 12.0, 10.1, 11.8, 2500.0]
    assert rec["prev"]["BRK-B"] == ["2026-10-19", 10.0, 11.0, 9.5, 10.5, 1000.0]   # 검증 게이트용 전날 봉
    assert collect.collect_us_eod(c, tmp_path, now, dry_run=True, symbols=["AAPL"]) == (0, 0, None)   # 하루 1회
    pub = publish.build_us_eod(tmp_path, now)
    publish.assert_public(pub)
    assert pub["date"] == "2026-10-20" and pub["bars"]["AAPL"][3] == 11.8
    assert pub["prev"]["AAPL"] == ["2026-10-19", 10.0, 11.0, 9.5, 10.5, 1000] and "ZZZ" not in pub["prev"]


def test_collect_us_eod_skips_before_close(tmp_path):
    now = datetime(2026, 10, 21, 4, 0, tzinfo=KST)   # 10/20 15:00 ET — 장중
    assert collect.us_eod_day(now) is None
    assert collect.collect_us_eod(_Client(), tmp_path, now, dry_run=True, symbols=["AAPL"]) == (0, 0, None)


def _yahoo_px():
    rows = [("AAPL", date(2026, 10, 16)), ("AAPL", date(2026, 10, 19)), ("MSFT", date(2026, 10, 19)), ("NVDA", date(2026, 10, 19))]
    return pl.DataFrame({"yf": [r[0] for r in rows], "date": [r[1] for r in rows], "open": 1.0, "high": 1.0, "low": 1.0,
                         "close": 1.0, "volume": 1.0}).with_columns(pl.col("date").cast(pl.Date))


EOD = {"date": "2026-10-20", "bars": {"AAPL": [10.5, 12.0, 10.1, 11.8, 2500], "MSFT": [1, 2, 0.5, 1.5, 9]},
       "prev": {s: ["2026-10-19", 1.0, 1.0, 1.0, 1.0, 1] for s in ("AAPL", "MSFT", "NVDA")}}   # 전날 = 야후와 일치 → 게이트 통과
NOW = datetime(2026, 10, 21, 6, 52, tzinfo=KST)   # screen_us 슬롯 — 기대 거래일 10/20


def test_fill_last_day_from_toss(tmp_path, monkeypatch):
    monkeypatch.setattr(guard, "_report_dir", lambda: tmp_path)
    px, info = smain.us_toss_fill(_yahoo_px(), date(2026, 10, 19), NOW, load=lambda: EOD)
    assert info["filled"] == 2 and info["total"] == 3 and info["label"] == "src: 야후+토스 보충 66.7% (토스 검증 일치 100%)"
    last = px.group_by("yf").agg(pl.col("date").max())
    assert last["date"].mode()[0] == date(2026, 10, 20)   # 기준일 10/20 → STALE 아님
    assert px.filter((pl.col("yf") == "AAPL") & (pl.col("date") == date(2026, 10, 20)))["close"][0] == 11.8
    assert len(px.filter(pl.col("yf") == "AAPL")) == 3   # 이력(야후) 유지
    fr = json.loads((tmp_path / "freshness.json").read_text(encoding="utf-8"))
    assert fr["filled"][-1]["pct"] == 66.7 and fr["filled"][-1]["src"] == "yahoo+toss"


def test_fill_missing_or_wrong_date_keeps_stale():
    px0 = _yahoo_px()
    for eod in (None, {**EOD, "date": "2026-10-19"}):
        px, info = smain.us_toss_fill(px0, date(2026, 10, 19), NOW, load=lambda e=eod: e)
        assert info is None and px.equals(px0)
    px, info = smain.us_toss_fill(px0, date(2026, 10, 20), NOW, load=lambda: EOD)   # 야후가 이미 최신 → 손대지 않음
    assert info is None
