"""screener.prices — KR 기업행위 조정 회귀 (분할·병합·정지/재개·분할 아닌 급락·정리매매·무상증자·시가만 튐)."""
from __future__ import annotations

from datetime import date, timedelta

import polars as pl

from screener import prices
from screener.data_krx import adjust_splits


def _bdays(n, start=date(2026, 3, 2)):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(1)
    return out


def _frame(rows_by_sym: dict[str, list[tuple]], days=None):
    """rows: (open, close) 목록. None 은 그날 거래 없음(정지). 마지막 날짜는 모든 종목 공통 최대일."""
    n = max(len(v) for v in rows_by_sym.values())
    days = days or _bdays(n)
    recs = []
    for s, rows in rows_by_sym.items():
        for d, oc in zip(days, rows):
            if oc is None:
                continue
            o, c = oc
            recs.append({"yf": s, "date": d, "open": float(o), "high": float(max(o, c)), "low": float(min(o, c)),
                         "close": float(c), "volume": 1000.0})
    return pl.DataFrame(recs)


def _rets(df, s):
    c = df.filter(pl.col("yf") == s).sort("date")["close"].to_list()
    return [round(b / a - 1, 4) for a, b in zip(c, c[1:])]


FLAT = [(100, 100)] * 12   # 기준 종목(데이터 마지막 날을 끝까지 채움)


def test_split_1_to_5_after_halt():
    rows = [(10000, 10000), (10000, 10100)] + [None] * 5 + [(2020, 2040), (2040, 2060)] + [(2060, 2060)] * 3
    df = _frame({"A.KS": rows, "Z.KS": FLAT})
    ev = prices.detect_events(df)
    assert ev.filter(pl.col("yf") == "A.KS").height == 1
    r = _rets(prices.adjust(df), "A.KS")
    assert all(abs(x) < 0.05 for x in r), r          # 분할일 -80% 가 사라짐
    assert abs(r[1] - (2040 / 2020 - 1)) < 1e-3      # 재개일 시가→종가 움직임은 남음


def test_reverse_split_5_to_1():
    rows = [(500, 500), (500, 505)] + [None] * 10 + [(2525, 2600)]
    df = _frame({"B.KQ": rows, "Z.KS": [(100, 100)] * 13})
    adj = prices.adjust(df)
    r = _rets(adj, "B.KQ")
    assert abs(r[-1] - (2600 / 2525 - 1)) < 1e-3     # +415% 가 아니라 +3%
    assert adj.filter(pl.col("yf") == "B.KQ")["close"][0] == 2500.0   # 과거가 5배로 올라감


def test_halt_resume_without_corporate_action_is_untouched():
    rows = [(1000, 1000)] + [None] * 8 + [(1200, 1250), (1250, 1240), (1240, 1240)]
    df = _frame({"C.KS": rows, "Z.KS": FLAT})
    assert prices.detect_events(df).filter(pl.col("yf") == "C.KS").height == 0
    assert _rets(prices.adjust(df), "C.KS") == _rets(df, "C.KS")


def test_limit_down_crash_is_not_a_split():
    rows = [(1000, 1000), (1000, 1000), (720, 701)] + [(701, 690)] * 9      # -29.9% 하한가
    df = _frame({"D.KS": rows, "Z.KS": FLAT})
    assert prices.detect_events(df).height == 0
    assert _rets(prices.adjust(df), "D.KS")[1] == round(701 / 1000 - 1, 4)


def test_open_only_spike_is_not_a_split():
    # 시가만 +63% (체결 오류·단일가 왜곡), 종가는 +19% — v1(시가 ±45%)은 기업행위로 잘못 봤다 (312610 2026-09-23 사례)
    rows = [(89, 89), (89, 89), (145, 106)] + [(106, 105)] * 9
    df = _frame({"E.KQ": rows, "Z.KS": FLAT})
    assert prices.detect_events(df).height == 0


def test_bonus_issue_1_to_0_5_detected():
    # 1:0.5 무상증자 권리락: 기준가 ×0.667 — v1(시가 <0.55) 은 놓쳤다 (303360 2026-10-13, DART 권리락 공시와 일치)
    rows = [(5900, 5900), (5900, 5900), (3933, 3950)] + [(3950, 3950)] * 9
    df = _frame({"F.KQ": rows, "Z.KS": FLAT})
    assert prices.detect_events(df).height == 1
    assert abs(_rets(prices.adjust(df), "F.KQ")[1]) < 0.01


def test_delisting_liquidation_crash_is_kept():
    # 정리매매(가격제한 없음): 시계열 끝 7행 안 급락 + 종목이 데이터 마지막 날 전에 끝남 → 실제 손실, 조정 금지
    rows = [(100, 100)] * 5 + [None] * 2 + [(40, 30), (30, 12), (12, 5)]
    df = _frame({"G.KQ": rows, "Z.KS": FLAT})
    assert prices.detect_events(df).height == 0
    assert _rets(prices.adjust(df), "G.KQ")[-3] == -0.7


def test_nonpositive_open_ignored():
    rows = [(1000, 1000), (0, 1000), (1000, 1010)] + [(1010, 1010)] * 9
    df = _frame({"H.KS": rows, "Z.KS": FLAT})
    assert prices.detect_events(df).height == 0


def test_adjust_splits_delegates_and_keeps_columns():
    rows = [(10000, 10000)] + [None] * 3 + [(2000, 2000)] + [(2000, 2000)] * 7
    df = _frame({"A.KS": rows, "Z.KS": FLAT})
    out = adjust_splits(df, threshold=0.45)
    assert out.columns == df.columns
    assert out.equals(prices.adjust(df))
    a = out.filter(pl.col("yf") == "A.KS")
    assert a["close"][0] == 2000.0 and a["volume"][0] == 5000.0   # 가격 ÷5, 거래량 ×5


def test_load_kr_raw_vs_adjusted(tmp_path):
    rows = [(10000, 10000)] + [None] * 3 + [(2000, 2000)] + [(2000, 2000)] * 7
    p = tmp_path / "kr_prices.parquet"
    _frame({"A.KS": rows, "Z.KS": FLAT}).write_parquet(p)
    raw = prices.load_kr(raw=True, path=p)
    adj = prices.load_kr(path=p)
    assert raw.filter(pl.col("yf") == "A.KS")["close"][0] == 10000.0
    assert adj.filter(pl.col("yf") == "A.KS")["close"][0] == 2000.0


def test_crosscheck_dart():
    ev = pl.DataFrame({"yf": ["303360.KQ", "017650.KQ"], "date": [date(2026, 10, 13)] * 2, "r": [0.64, 0.19], "rc": [0.65, 0.2]})
    dart = pl.DataFrame({"code": ["303360", "017650", "115180", "999999"], "date": [date(2026, 10, 12)] * 4,
                         "title": ["권리락 (무상증자)", "주권매매거래정지해제 (액면분할 주권 변경상장)", "권리락 (유상증자)",
                                   "주권매매거래정지해제 (액면병합 주권 변경상장)"]})
    r = prices.crosscheck_dart(ev, dart)
    assert r == {"disclosures": 3, "matched": 2, "missing": ["999999"]}
