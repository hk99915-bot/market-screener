from screener.commentary import stock_comment


def _row(**kw):
    return {"class": "COUNTERTREND_BOUNCE", "close": 10.0, "ret1": 0.0, "ret5": 0.0, "vol_ratio": 1.0, **kw}


def test_missing_high52_is_not_minus_100pct():
    txt = stock_comment(_row(from_high52=None), max_parts=5)
    assert "-100%" not in txt and "상장 6개월 미만" in txt


def test_real_drawdown_still_reported():
    assert "52주 고점 대비 -45%" in stock_comment(_row(from_high52=-0.45), max_parts=5)
