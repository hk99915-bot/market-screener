"""캘린더 실적 결과 첨부·지난 실적 이어받기 (req-dev-4f89d244) — 네트워크 없이 가짜 수집기로."""
import json
from datetime import date

from screener import calendar_ev as C


def test_reaction_amc_and_bmo():
    cl = [("2026-10-20", 100.0), ("2026-10-21", 110.0), ("2026-10-22", 99.0)]
    r, d = C.reaction(cl, "2026-10-21", "amc")
    assert d == "2026-10-22" and abs(r - (99 / 110 - 1)) < 1e-9
    r, d = C.reaction(cl, "2026-10-21", "bmo")
    assert d == "2026-10-21" and abs(r - 0.10) < 1e-9
    assert C.reaction(cl, "2026-10-22", "amc") == (None, None)   # 다음 거래일 종가 전


def test_us_line_and_short():
    r = {"eps_act": 7.25, "eps_est": 6.70, "eps_sur": None, "rev_act": 51.2e9, "rev_est": 49.5e9, "react": -0.031, "react_day": "2026-10-22"}
    s = C.us_line(r)[0]
    assert "EPS 7.25 vs 컨센 6.70 (+8.2%)" in s and "매출 $51.2B vs 컨센 $49.5B (+3.4%)" in s and "주가 반응 -3.1% (10-22 종가)" in s
    assert C.short({"res": r}) == "EPS +8%·반응 -3.1%"
    assert "매출 실제 미반영" in C.us_line({"eps_act": 1.0, "eps_est": 1.0})[0]


def test_attach_earn_fills_past_and_snapshots_cons_and_fixes_date():
    ev = [{"date": "2026-10-21", "type": "실적", "ticker": "META", "market": "US", "name": "Meta 실적", "note": "", "imp": 3},
          {"date": "2026-10-28", "type": "실적", "ticker": "MSFT", "market": "US", "name": "Microsoft 실적", "note": "", "imp": 3},
          {"date": "2026-10-22", "type": "실적", "ticker": "000660", "market": "KR", "name": "SK하이닉스 실적",
           "note": "회사 확정 · 컨센 영업익 약 77조(FnGuide)", "imp": 3},
          {"date": "2026-10-01", "type": "실적", "ticker": "OLD", "market": "US", "name": "old", "note": "", "imp": 1}]
    us = lambda t, d0, cons: {"eps_act": 7.0, "eps_est": 6.5, "eps_sur": 0.077, "react": 0.02, "react_day": "2026-10-23", "date_fix": "2026-10-22"}  # noqa: E731
    kr = lambda c, d0: {"react": -0.01, "react_day": "2026-10-22", "dart": {"date": "2026-10-22", "title": "연결재무제표기준영업(잠정)실적(공정공시)", "rcept_no": "1", "link": "x"}}  # noqa: E731
    n = C.attach_earn(ev, date(2026, 10, 23), fetch_us=us, fetch_kr=kr, fetch_cons=lambda t: {"eps": 3.1, "rev": 7.7e10})
    assert n == 2
    meta, msft, hy, old = ev
    assert meta["date"] == "2026-10-22" and meta["date_orig"] == "2026-10-21" and "EPS 7.00" in meta["result"][0]
    assert msft["cons"]["rev"] == 7.7e10 and msft["cons"]["asof"] == "2026-10-23" and "result" not in msft
    assert "DART" in hy["result"][0] and "컨센 영업익 77조" in hy["result"][0] and "-1.0%" in hy["result"][0]
    assert "result" not in old   # 발표일+5일 넘으면 다시 안 찾음


def test_attach_earn_failure_is_visible_not_silent():
    ev = [{"date": "2026-10-22", "type": "실적", "ticker": "WDC", "market": "US", "name": "WD 실적", "note": "", "imp": 2}]
    C.attach_earn(ev, date(2026, 10, 23), fetch_us=lambda *a: {"err": "야후 earnings_dates 에 실제 EPS 없음"}, fetch_cons=lambda t: {})
    assert ev[0]["result"][0].startswith("데이터 없음(")


def test_drop_moved_keeps_reported_but_drops_rescheduled():
    ev = [{"date": "2026-10-21", "type": "실적", "ticker": "META"},
          {"date": "2026-10-21", "type": "실적", "ticker": "TSLA"}, {"date": "2026-10-29", "type": "실적", "ticker": "TSLA"},
          {"date": "2026-10-21", "type": "실적", "ticker": "LRCX", "res": {"eps_act": 1}}, {"date": "2026-10-29", "type": "실적", "ticker": "LRCX"}]
    out = C.drop_moved(ev)
    keys = [(e["ticker"], e["date"]) for e in out]
    assert ("META", "2026-10-21") in keys and ("TSLA", "2026-10-21") not in keys and ("LRCX", "2026-10-21") in keys


def test_build_carries_over_yesterday_event(tmp_path, monkeypatch):
    """10/22 사고 재현: 발표 다음날 야후가 다음 분기로 넘어가도 지난 실적이 캘린더에 남는다."""
    out = tmp_path / "calendar.json"
    out.write_text(json.dumps({"events": [{"date": "2026-10-21", "type": "실적", "ticker": "META", "market": "US", "name": "Meta 실적", "note": "", "imp": 3}]}), encoding="utf-8")
    monkeypatch.setattr(C, "OUT", out)
    monkeypatch.setattr(C, "REPORT_DIR", tmp_path)
    monkeypatch.setattr(C, "_today", lambda: date(2026, 10, 22))
    monkeypatch.setattr(C, "_earn_dates", lambda t, suffix="": {"META": "2027-01-28"} if not suffix else {})
    monkeypatch.setattr(C, "VERIFIED", {})
    monkeypatch.setattr(C, "releases", lambda: {})
    monkeypatch.setattr(C, "attach_earn", lambda ev, today: 0)
    import screener.policy_rates as _pr   # build() 가 부르는 정책금리 수집이 실제 reports/policy_rates.json 을 덮지 않게
    monkeypatch.setattr(_pr, "collect", lambda *a, **k: {})
    o = C.build()
    assert any(e.get("ticker") == "META" and e["date"] == "2026-10-21" for e in o["events"])


def test_capex_line_uses_calendar_dates():
    ev = [{"date": "2026-10-21", "type": "실적", "ticker": "META", "res": {"eps_act": 7, "eps_est": 6.5, "react": -0.03, "react_day": "2026-10-22"}},
          {"date": "2026-10-28", "type": "실적", "ticker": "MSFT", "confirmed": True}]
    s = C.capex_line(ev, date(2026, 10, 23))
    assert "10/21 메타 EPS +8%·반응 -3.0%" in s and "10/28 MSFT" in s and "(추정일)" not in s
