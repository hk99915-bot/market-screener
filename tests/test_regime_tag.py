from screener import regime_tag as rt


def test_classify_thresholds():
    up = [100 + i * 0.1 for i in range(250)]
    assert rt.classify(up)["l"] == "상승"
    corr = up + [up[-1] * 0.85]
    assert rt.classify(corr)["l"] == "조정"
    bear = up + [up[-1] * 0.75]
    r = rt.classify(bear)
    assert r["l"] == "하락" and r["dd"] <= -0.2
    assert rt.classify([1.0] * 10) is None


def test_below_ma200_is_correction_even_near_high():
    c = [100.0] * 150 + [130.0] * 40 + [80.0] * 5 + [125.0] * 5   # 고점 −3.8%, 200일선(약 108)… 위 → 상승
    assert rt.classify(c)["l"] == "상승"
    c2 = [150.0] * 195 + [140.0] * 5 + [141.0]   # 고점 −6%·200일선 아래
    assert rt.classify(c2)["l"] == "조정"


def test_tag_items_uses_last_trading_day_on_or_before():
    dates = [f"2026-01-{d:02d}" for d in range(1, 31)]
    closes = [100.0 + i for i in range(30)]
    items = [{"date": "2026-01-31", "code": "000001"}, {"date": "2025-12-01", "code": "000001"}]
    n = rt.tag_items(items, (dates, closes), {"000001": (dates, closes)})
    assert n == 1 and items[0]["rg_k"]["l"] == "상승" and items[1].get("rg_k") is None
