from screener import rate_series as r

CSV = "observation_date,DFII10\n2026-10-20,2.77\n2026-10-21,.\n2026-10-22,2.64\n"


def test_parse_fred_skips_holiday():
    assert r.parse_fred_csv(CSV) == [("2026-10-20", 2.77), ("2026-10-22", 2.64)]


def test_merge_ok_and_failure_keeps_series():
    hist = {"rows": [{"date": "2026-10-22", "kr_3Y": 3.84}, {"date": "2026-10-23", "kr_3Y": 3.803}, {"date": "2026-10-24"}]}
    ser = {"TIPS10Y": [["old", 1, 1, 1, 1, 0]]}
    st = r.merge_into(ser, hist, fred=lambda: (_ for _ in ()).throw(TimeoutError("x")))
    assert ser["KR3Y"][-1] == ["2026-10-23", 3.803, 3.803, 3.803, 3.803, 0]
    assert st["KR3Y"].startswith("ok 2일") and st["TIPS10Y"].startswith("실패")
    assert ser["TIPS10Y"] == [["old", 1, 1, 1, 1, 0]]
    r.merge_into(ser, hist, fred=lambda: r.parse_fred_csv(CSV))
    assert ser["TIPS10Y"][-1][4] == 2.64
