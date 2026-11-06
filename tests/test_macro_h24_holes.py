"""데이터 11/6: close_kr(06:50Z) 야후 BTC-USD 응답이 전일 UTC 봉(11/05)만 빼고 와서 btc.json closed_asof 가 11/04 로 내려가 역행 차단
(11/4·11/6 반복). 24시간 자산의 중간 구멍은 이전 파일 행으로 메우고 stale 로 표시한다."""
from screener import btc, main


def _row(d, c):
    return [d, c, c + 1, c - 1, c, 1]


def test_fill_holes_inserts_only_missing_middle_rows():
    ser = {"BTC": [_row("2026-11-03", 1), _row("2026-11-04", 2), _row("2026-11-06", 9)]}
    prev = {"BTC": [_row("2026-11-03", 100), _row("2026-11-04", 200), _row("2026-11-05", 3), _row("2026-11-06", 300)]}
    got = main.fill_holes(ser, prev, "BTC")
    assert got == ["2026-11-05"]
    assert [r[0] for r in ser["BTC"]] == ["2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06"]
    assert [r[4] for r in ser["BTC"]] == [1, 2, 3, 9]          # 새 수집값은 덮지 않음


def test_fill_holes_no_prev_or_no_gap():
    ser = {"BTC": [_row("2026-11-05", 1), _row("2026-11-06", 2)]}
    assert main.fill_holes(ser, {}, "BTC") == []
    assert main.fill_holes(ser, {"BTC": [_row("2026-11-07", 5)]}, "BTC") == []   # 범위 밖(미래) 행은 안 넣음
    assert len(ser["BTC"]) == 2


def test_btc_closed_asof_not_regressed_after_fill():
    from datetime import datetime, timezone
    rows = [_row(f"2026-10-{d:02d}", 100 + d) for d in range(10, 32)] + [_row("2026-11-01", 140), _row("2026-11-02", 141),
                                                                         _row("2026-11-03", 142), _row("2026-11-04", 143),
                                                                         _row("2026-11-06", 145)]
    now = datetime(2026, 11, 6, 6, 50, tzinfo=timezone.utc)
    assert btc.build(rows, now)["closed_asof"] == "2026-11-04"    # 구멍 그대로면 역행
    ser = {"BTC": rows}
    main.fill_holes(ser, {"BTC": [_row("2026-11-05", 144)]}, "BTC")
    assert btc.build(ser["BTC"], now)["closed_asof"] == "2026-11-05"
