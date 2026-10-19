from screener.daily import quote_label


def test_preopen_is_not_final():
    for status in ("PREOPEN", "HALT", "", None):
        text = quote_label({"items": [{"key": "KOSPI", "status": status}], "asof": "2026-10-19 08:50"})
        assert "확정" not in text
        assert "상태 미확인" in text


def test_previous_close_keeps_trade_date():
    text = quote_label({"items": [{"key": "KOSPI", "status": "CLOSE"}],
                        "trade_date": "2026-10-16", "asof": "2026-10-19 08:50"})
    assert "거래일 2026-10-16" in text
    assert "수집 2026-10-19 08:50" in text


def test_open_preserves_snapshot_time():
    text = quote_label({"items": [{"key": "KOSPI", "status": "OPEN"}], "asof": "2026-10-19 09:30"})
    assert text == "장중 · 시세 2026-10-19 09:30"
