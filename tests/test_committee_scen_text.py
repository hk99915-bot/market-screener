"""운용회의 시나리오 문구 — 고정 날짜·금지 상품 템플릿 재발 방지 (req-dev-7e78b190)."""
from datetime import date

from screener import committee as C


def _kr(cal):
    k = {"dd20": -0.05, "ret1": -0.01, "low_today": 5200, "last": 5250, "sma20": 5500}
    scen, _ = C._scenarios(k, {}, {}, cal)
    return " ".join(s["action"] + s["trigger"] for s in scen)


def test_no_stale_template_kr():
    txt = _kr([])
    assert "10/21~29" not in txt and "인버스 25%" not in txt and "인버스 헷지 해제" not in txt
    assert "실계좌 금지" in txt and C._lev_ban_until() in txt   # 금지 기간(오늘 ≤ 기한)


def test_earn_span_from_calendar():
    cal = [{"date": "2026-11-12", "type": "실적", "market": "KR"}, {"date": "2026-11-20", "type": "실적", "market": "KR"},
           {"date": "2026-11-13", "type": "실적", "market": "US"}, {"date": "2027-01-20", "type": "실적", "market": "KR"}]
    assert C._earn_span(cal, date(2026, 11, 11), "KR") == "11/12~11/20 2건"
    assert C._earn_span(cal, date(2026, 11, 11), "US", tickers={"MSFT"}) == ""
    assert C._earn_span([], date(2026, 11, 11)) == ""


def test_hedge_clause_after_ban():
    assert "실계좌 금지" in C._hedge_clause(True)
    assert "25%" not in C._hedge_clause(False) and C._lev_banned(date(2027, 4, 16)) is False
