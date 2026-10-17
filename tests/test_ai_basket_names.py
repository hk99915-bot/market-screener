from screener import bonds


def test_basket_keeps_name_not_obs_count():
    px = {t: {f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}": 10 + i * 0.01 for i in range(300)} for t in bonds.AI_BASKET}
    o = bonds.ai_credit(px)
    assert o["basket"] and all(isinstance(r["n"], str) for r in o["basket"])
    assert all(r["obs"] == 300 for r in o["basket"])


def test_us_watch_reads_csv():
    from screener import universe
    w = universe.us_watch()
    assert {"CIFR", "IREN", "APLD"} <= w
