"""장중 오늘 봉 오버레이(screener/intraday_last.py) + KR 히트맵 토스 우선(10/24 겸이 "1y 차트도 장중 업뎃·라이브는 토스 기준").
계약(필드·관측 근사·거래일 바뀌면 리셋·역행 금지)과 토스→네이버 순서·출처 집계."""
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from screener import heatmap as HU
from screener import heatmap_kr as H
from screener import intraday_last as I

KST = ZoneInfo("Asia/Seoul")
D = "2026-10-21"


def test_observed_ohlc_accumulates_and_resets_on_new_day():
    b1 = I.merge(None, [{"s": "005930", "close": 70000, "r1": 0.01}], "KR", D, "LIVE", "2026-10-21 09:05 KST")
    q = b1["q"]["005930"]
    assert q[:4] == [70000, 70000, 70000, 70000] and q[7] == "n" and q[8] == 0 and q[9:] == [None, None, None]   # 근사면 갭 없음(추정 금지)
    b2 = I.merge(b1, [{"s": "005930", "close": 71500, "r1": 0.03, "src": "toss"}], "KR", D, "LIVE", "2026-10-21 09:10 KST")
    b3 = I.merge(b2, [{"s": "005930", "close": 69000, "r1": -0.005}], "KR", D, "LIVE", "2026-10-21 09:15 KST")
    assert b3["q"]["005930"][:4] == [70000, 71500, 69000, 69000] and b2["q"]["005930"][7] == "t"
    nd = I.merge(b3, [{"s": "005930", "close": 69500, "r1": 0.007}], "KR", "2026-10-22", "LIVE", "2026-10-22 09:05 KST")
    assert nd["q"]["005930"][:3] == [69500, 69500, 69500]                 # 거래일 바뀌면 새로 시작


@pytest.mark.parametrize("o,h,l,c,pc,want", [
    (101.8, 103, 101.5, 102, 100, (0.018, "U", 0)),     # 갭상 +1.8%, 저가 101.5 > 전일 100 → 안 메움
    (101.8, 103, 99.9, 100.5, 100, (0.018, "U", 1)),    # 저가 ≤ 전일 종가 → 메움
    (98.8, 100.0, 97, 98, 100, (-0.012, "D", 1)),       # 갭하 −1.2%, 고가 ≥ 전일 → 메움
    (98.8, 99.5, 97, 98, 100, (-0.012, "D", 0)),
    (100.3, 101, 99, 100, 100, (0.003, "0", None)),     # ±0.5% 안 = 보합, 메움 판정 없음
])
def test_gap_kind_and_fill(o, h, l, c, pc, want):
    b = I.merge(None, [{"s": "X", "close": c, "r1": c / pc - 1, "o": o, "h": h, "l": l, "v": 1234, "pc": pc}], "US", D, "LIVE", "x")
    q = b["q"]["X"]
    assert q[4] == 1234 and q[5] == pc and q[8] == 1
    assert q[9] == pytest.approx(want[0], abs=1e-4) and q[10] == want[1] and q[11] == want[2]


def test_bar_rows_use_daily_ohlc_and_skip_bad():
    b = I.merge(None, [{"s": "AAPL", "close": 101.234567, "r1": 0.012, "o": 100, "h": 102, "l": 99.5, "src": "yahoo"},
                       {"s": "BAD", "close": None, "r1": 0.1}], "US", D, "LIVE", "x")
    q = b["q"]["AAPL"]
    assert q[:4] == [100, 102, 99.5, 101.2346] and q[7] == "y" and q[8] == 1 and b["n"] == 1 and b["exact"] == 1
    assert q[5] == pytest.approx(101.234567 / 1.012, abs=1e-3) and q[10] == "0"   # 전일 종가 없으면 r1 로 복원(100.03) → 시가 100 = 보합


def test_update_contract_and_no_regress(tmp_path):
    now = datetime(2026, 10, 21, 10, 0, tzinfo=KST)
    doc = I.update("KR", [{"s": "000660", "close": 200000, "r1": 0.02}], D, "LIVE", now, tmp_path)
    assert doc["schema"] == 2 and doc["fields"] == ["o", "h", "l", "c", "v", "pc", "r1", "src", "x", "gap", "gk", "gf"]
    assert doc["gap_band"] == 0.005 and doc["asof"] == "2026-10-21 10:00 KST"
    I.update("US", [{"s": "SPY", "close": 600, "r1": 0.001, "o": 599, "h": 601, "l": 598}], D, "LIVE",
             datetime(2026, 10, 21, 23, 0, tzinfo=KST), tmp_path)
    j = json.loads((tmp_path / I.NAME).read_text(encoding="utf-8"))
    assert set(j) >= {"KR", "US", "schema", "fields", "asof"} and j["asof"] == "2026-10-21 23:00 KST"
    assert I.update("KR", [{"s": "000660", "close": 1, "r1": 0}], D, "LIVE", datetime(2026, 10, 21, 9, 0, tzinfo=KST), tmp_path) is None
    assert json.loads((tmp_path / I.NAME).read_text(encoding="utf-8"))["KR"]["q"]["000660"][3] == 200000


def _toss(quotes, asof="2026-10-21T10:50:00+09:00"):
    return {"source": "toss", "kr_quotes": {c: {"last": p, "chg_pct": pct, "asof": asof} for c, (p, pct) in quotes.items()}}


def test_toss_quotes_fallback_rules():
    now = datetime(2026, 10, 21, 11, 0, tzinfo=KST)
    t = H.toss_quotes(_toss({"000001": (1000, 1.5), "000002": (0, 1), "000003": (500, 45)}), ["000001", "000002", "000003"], D, now)
    assert t == {"000001": {"r1": 0.015, "close": 1000.0, "t": "2026-10-21 10:50", "src": "toss"}}   # 0원·±31% 넘는 값 버림
    assert H.toss_quotes(_toss({"000001": (1000, 1.5)}, asof="2026-10-21T10:20:00+09:00"), ["000001"], D, now) == {}   # 40분 전 = 오래됨
    # 장 마감 뒤엔 토스 종목가 금지(NXT 통합가로 보임, req-dev-a4d03413)
    assert H.toss_quotes(_toss({"000001": (1000, 1.5)}, asof="2026-10-21T15:35:00+09:00"), ["000001"], D,
                         datetime(2026, 10, 21, 15, 40, tzinfo=KST)) == {}
    assert H.toss_quotes(None, ["000001"], D, now) == {}


def _poll(codes_ok):
    def get(url):
        if "polling" in url:
            return {"datas": [{"itemCode": c, "closePrice": "2,000", "fluctuationsRatio": "1.01", "compareToPreviousPrice": {"code": "2"},
                               "compareToPreviousClosePrice": "20", "openPrice": "1,990", "highPrice": "2,050", "lowPrice": "1,950",
                               "accumulatedTradingVolume": "12,345", "localTradedAt": "2026-10-21T10:55:00+09:00"}
                              for c in url.rsplit("/", 1)[1].split(",") if c in codes_ok]}
        return {"stocks": []}
    return get


def test_run_naver_first_toss_fallback_and_writes_intraday(tmp_path):
    codes = [f"{i:06d}" for i in range(1, 11)]
    (tmp_path / "peers_KR.json").write_text(json.dumps({"asof": "2026-10-20", "rows": [{"s": c} for c in codes]}), encoding="utf-8")
    toss = lambda: _toss({"000001": (1000, 1.5), "000010": (3000, -2.0)})   # noqa: E731 — 000001 은 네이버가 있으니 무시
    out = H.run(now=datetime(2026, 10, 21, 11, 0, tzinfo=KST), get=_poll(codes[:9]), root=tmp_path, toss=toss)
    assert out["src_n"] == {"naver": 9, "toss": 1} and out["source"].startswith("네이버") and out["source"].endswith("토스 폴백 1")
    j = json.loads((tmp_path / I.NAME).read_text(encoding="utf-8"))["KR"]
    n, t = j["q"]["000001"], j["q"]["000010"]
    assert j["src"] == {"naver": 9, "toss": 1} and j["exact"] == 9 and "provisional" not in j
    assert n[:6] == [1990, 2050, 1950, 2000, 12345, 1980] and n[7] == "n" and n[8] == 1          # 네이버 값(토스 1000 무시)
    assert n[9] == pytest.approx(1990 / 1980 - 1, abs=1e-5) and n[10] == "U" and n[11] == 1      # 갭상 +0.51%, 저가 1950 ≤ 1980 → 메움
    assert t[3] == 3000 and t[7] == "t" and t[8] == 0 and t[9:] == [None, None, None]           # 토스 폴백 = 시가 필드 없음 → 갭 없음


def test_close_window_is_provisional(tmp_path):
    codes = ["000001"]
    (tmp_path / "peers_KR.json").write_text(json.dumps({"asof": "2026-10-20", "rows": [{"s": "000001"}]}), encoding="utf-8")
    out = H.run(now=datetime(2026, 10, 21, 15, 35, tzinfo=KST), get=_poll(codes), root=tmp_path, toss=lambda: None)
    assert out["session"] == "CLOSE" and out["provisional"] is True
    assert json.loads((tmp_path / I.NAME).read_text(encoding="utf-8"))["KR"]["provisional"] is True
    out = H.run(now=datetime(2026, 10, 21, 15, 46, tzinfo=KST), get=_poll(codes), root=tmp_path, toss=lambda: None)
    assert "provisional" not in out and "provisional" not in json.loads((tmp_path / I.NAME).read_text(encoding="utf-8"))["KR"]


def test_us_bar_rows_take_target_day_ohlc():
    idx = pd.to_datetime(["2026-10-20", "2026-10-21"])
    f = pd.DataFrame({"Open": [1, 10.0], "High": [1, 12.0], "Low": [1, 9.0], "Close": [1, 11.0]}, index=idx)
    r = HU.bar_rows([{"s": "X", "r1": 0.1, "close": 11.0}, {"s": "Y", "r1": 0, "close": 5}], {"X": f}, "2026-10-21")
    assert r[0]["o"] == 10.0 and r[0]["h"] == 12.0 and r[0]["l"] == 9.0 and r[0]["src"] == "yahoo" and "o" not in r[1]


def test_toss_index_overlay_blocked_after_close():
    """req-dev-a4d03413 ②: 장 마감 뒤 토스 지수로 KRX 종가 덮기 금지(10/22 5,539.94 사고). 장중엔 그대로 덮음."""
    from screener import toss_live as T
    doc = {"asof": "x", "indices": {"KOSPI": {"last": 5539.94, "asof": "2026-10-22T15:34:00+09:00", "prev_close": 5500}}}
    items = [{"key": "KOSPI", "last": 5533.7, "chg": 0.006, "src": "naver"}]
    out, blk = T.overlay([dict(x) for x in items], doc, datetime(2026, 10, 22, 15, 40, tzinfo=KST))
    assert out[0]["src"] == "naver" and out[0]["last"] == 5533.7 and "KRX 종가 우선" in blk["skipped"]["KOSPI"]
    doc["indices"]["KOSPI"]["asof"] = "2026-10-22T11:00:00+09:00"
    out, blk = T.overlay([dict(x) for x in items], doc, datetime(2026, 10, 22, 11, 5, tzinfo=KST))
    assert out[0]["src"] == "naver"                       # 10/24 겸이: 정규장도 네이버 1차
    out, blk = T.overlay([], doc, datetime(2026, 10, 22, 11, 5, tzinfo=KST))
    assert out[0]["src"] == "toss"                        # 네이버 실패(항목 없음) → 토스 폴백


def test_live_marks_provisional_window():
    import inspect
    from screener import live
    src = inspect.getsource(live.snapshot)
    assert '"15:30" <= now.strftime("%H:%M") < "15:45"' in src and 'x["provisional"] = True' in src
