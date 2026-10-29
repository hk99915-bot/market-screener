from screener.live import fut_item


def test_fut_delayed_drops_basis():
    f = {"closePrice": "964.1", "fluctuationsRatio": "1.93", "delayTime": 20, "localTradedAt": "2026-10-29T09:48:00+09:00", "marketStatus": "OPEN"}
    it = fut_item(f, 964.1, 944.3)
    assert it["delay"] == 1200 and it["basis"] is None and it["spot"] == 944.3
    assert abs(it["chg"] - 0.0193) < 1e-9 and "지연" in it["note"]


def test_fut_realtime_keeps_basis():
    it = fut_item({"closePrice": "920.85", "fluctuationsRatio": "-2.6", "delayTime": 0}, 920.85, 919.0)
    assert it["basis"] == 1.85 and "delay" not in it


def test_fut_bad_delay_safe():
    it = fut_item({"closePrice": "1", "fluctuationsRatio": "0.5", "delayTime": "abc"}, 1.0, 1.0)
    assert it["basis"] == 0.0 and "delay" not in it
