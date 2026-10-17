"""결재 #9 (2026-10-17): 매크로 지표 문장은 '전월 대비'만 — 컨센서스가 없으므로 서프라이즈·예상 대비 표기 금지, 코스피−S&P 격차 병기.

문장은 calendar_ev.release_line 한 곳에서 만들고, committee._v2_macro 의 releases/note 가 그 규칙을 따르는지 검사한다 (네트워크 없음).
"""
from datetime import date

from screener import calendar_ev, committee

CPI = {"grp": "CPI", "label": "CPI 전년비", "period": "2026-09", "value": 4.023, "prev": 3.713, "how": "yoy", "seen": "2026-10-15"}
NFP = {"grp": "고용", "label": "비농업 고용", "period": "2026-09", "value": 29.0, "prev": 133.0, "how": "mom_k", "seen": "2026-10-15"}
UNR = {"grp": "고용", "label": "실업률", "period": "2026-09", "value": 4.2, "prev": 4.1, "how": "lvl", "seen": "2026-10-15"}
MV = {"rows": [{"key": "KOSPI", "chg20": -0.152}, {"key": "SPX", "chg20": 0.014}]}


def _no_banned(s: str) -> None:
    for w in calendar_ev.BANNED_WORDS:
        assert w not in s, f"금지어 '{w}' 포함: {s}"


def test_release_line_is_month_over_month_only():
    s = calendar_ev.release_line(CPI)
    assert s == "CPI 전년비 4.02% (전월 3.71% → +0.31%p)"
    assert calendar_ev.release_line(NFP) == "비농업 고용 +29천명 (전월 +133천명 → -104천명)"
    assert calendar_ev.release_line(UNR, period=True, seen=True) == "실업률 4.20% (전월 4.10% → +0.10%p) · 2026-09 기준 · 발표 확인 10-15"
    assert calendar_ev.release_line({**CPI, "prev": None}) == "CPI 전년비 4.02%"       # 직전치 없으면 비교 생략
    for x in (CPI, NFP, UNR):
        _no_banned(calendar_ev.release_line(x, period=True, seen=True))
        _no_banned(calendar_ev._fmt(x))                                          # 캘린더 이벤트 결과도 같은 함수


def test_committee_macro_releases_follow_rule_and_carry_kr_us_gap(monkeypatch):
    files = {"macro_releases.json": {"series": {"CPIAUCSL": CPI, "PAYEMS": NFP}}}
    monkeypatch.setattr(committee, "_j", lambda name, default=None: files.get(name, default))
    monkeypatch.setattr(committee, "_kst_today", lambda: date(2026, 10, 19))      # 월요일 08:50 장전
    monkeypatch.setattr(committee, "_regime", lambda mv: {})
    monkeypatch.setattr(committee, "_ai_credit_line", lambda: None)
    m = committee._v2_macro(MV, None)
    assert m["releases"] == ["CPI 전년비 4.02% (전월 3.71% → +0.31%p) · 2026-09 기준 · 발표 확인 10-15",
                             "비농업 고용 +29천명 (전월 +133천명 → -104천명) · 2026-09 기준 · 발표 확인 10-15"]
    assert m["gap"] == "코스피−S&P500 20일 격차 -16.6%p (코스피 -15.2% / S&P500 +1.4%) — 한국 고유 요인(반도체 쏠림·외국인) 쪽"
    assert m["gap"] in m["note"] and "전월" in m["note"]
    for s in m["releases"] + [m["note"], m["gap"]]:
        _no_banned(s)


def test_gap_absent_when_series_missing_and_sign_labels():
    assert committee._kr_us_gap({"rows": [{"key": "KOSPI", "chg20": 0.01}]}) is None
    assert committee._kr_us_gap(None) is None
    assert committee._kr_us_gap({"rows": [{"key": "KOSPI", "chg20": 0.10}, {"key": "SPX", "chg20": 0.01}]}).endswith("— 한국이 강함")
    g = committee._kr_us_gap({"rows": [{"key": "KOSPI", "chg20": 0.02}, {"key": "SPX", "chg20": 0.01}]})
    assert g == "코스피−S&P500 20일 격차 +1.0%p (코스피 +2.0% / S&P500 +1.0%)"
