"""req-data-710a7fab / b0e557b0: 야후가 분할을 부분 소급 조정(SOXX) 또는 미조정(ITA)으로 내려준 시계열의 불연속을 잡는다.
합성 데이터 검증 — 실수집 확인은 Actions 몫."""
from datetime import date, timedelta

import polars as pl

from screener.prices import adjust_integer_splits, detect_integer_splits, snap_split_ratio


def _df(sym, closes, opens=None, vols=None):
    d0 = date(2026, 10, 26)
    rows = []
    for i, c in enumerate(closes):
        o = opens[i] if opens else c
        rows.append({"yf": sym, "date": d0 + timedelta(days=i), "open": float(o), "high": float(max(o, c)) * 1.01, "low": min(o, c) * 0.99,
                     "close": float(c), "volume": (vols[i] if vols else 1000.0)})
    return pl.DataFrame(rows)


def test_snap():
    assert snap_split_ratio(0.318) == 1 / 3
    assert snap_split_ratio(3.03) == 3.0
    assert snap_split_ratio(0.854) is None
    assert snap_split_ratio(0.56) is None      # 2:1 허용오차 2% — 실적 급락과 구분


def test_unadjusted_3to1_split_adjusts_history():   # ITA 형: 11/5 만 분할 후
    df = _df("ITA", [210, 214, 216, 212, 68], opens=[209, 212, 215, 215, 70.4], vols=[100, 100, 100, 100, 250])
    out = adjust_integer_splits(df)
    c = out["close"].to_list()
    assert abs(c[3] - 212 / 3) < 1e-9 and c[4] == 68
    assert abs(out["volume"].to_list()[0] - 300) < 1e-9
    assert max(abs(c[i] / c[i - 1] - 1) for i in range(1, 5)) < 0.1


def test_partially_adjusted_mixed_series():   # SOXX 형: ~10/30 은 ÷3 조정, 11/2~11/4 원가, 11/5 분할 후
    cl = [170.0, 157.0, 453.0, 465.0, 450.0, 132.0]
    op = [171.0, 159.0, 476.0, 466.0, 458.0, 143.0]
    out = adjust_integer_splits(_df("SOXX", cl, op))
    c = out["close"].to_list()
    assert abs(c[0] - 170.0) < 1e-6 and abs(c[1] - 157.0) < 1e-6      # 앞쪽 조정분은 유지(×3×1/3)
    assert abs(c[2] - 151.0) < 1e-6 and abs(c[4] - 150.0) < 1e-6      # 원가 구간만 ÷3
    assert c[5] == 132.0
    assert max(abs(c[i] / c[i - 1] - 1) for i in range(1, 6)) < 0.15


def test_real_crash_and_leveraged_etf_untouched():
    df = pl.concat([_df("SOXL", [66.68, 40.87], opens=[70, 56.95]),         # 3x 레버리지 실제 급락
                    _df("AAA", [100, 48], opens=[100, 49])])                 # -52% 실적 급락(2:1 근처지만 오차 밖)
    assert len(detect_integer_splits(df)) == 0
    assert adjust_integer_splits(df).equals(df)


def test_indices_futures_skipped():
    df = pl.concat([_df("^VIX", [15, 31], opens=[15, 30]), _df("CL=F", [60, 30], opens=[60, 30])])
    assert len(detect_integer_splits(df)) == 0
