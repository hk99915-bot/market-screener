"""사이버보안 커버리지(10/22 겸이 요청) — ETF·관찰 종목·체인이 목록에 들어갔는지."""
from screener import drivers, etf, universe


def test_cyber_tickers_in_lists():
    assert {"BUG", "CIBR", "HACK"} <= set(etf.US_LIST)
    assert {"ZS", "NET", "OKTA", "S", "CYBR", "CHKP", "QLYS", "TENB", "RPD", "VRNS"} <= universe.us_watch()
    ch = drivers.CHAINS["cybersecurity"]
    assert ch["name"] == "사이버보안" and "053800" in ch["codes"]
    assert all(len(p) == 4 for p in ch["proxies"])
    assert drivers.chain_of("053800", None) == "cybersecurity"
    assert {"ZS", "OKTA", "CHKP"} <= drivers.US_CYBER
