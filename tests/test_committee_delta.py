"""committee._delta_line — 직전 운용회의 대비 변화 한 줄 (지수·시나리오 확률·판정·PCR·감마)."""
from screener import committee

PREV = {
    "date": "2026-10-15", "session": "장후", "asof": "2026-10-15T15:50:12",
    "head": ["코스피 3,000.00 (−1.2%) · 외국인 순매도"],
    "scenarios": [{"name": "강세 돌파", "prob": 0.30}, {"name": "기본 박스", "prob": 0.50}, {"name": "약세 이탈", "prob": 0.20}],
    "stance": {"stance": "중립"},
    "derivs": {"pcr_oi": 1.00, "gex_bn": 100.0},
}
SCEN = [{"name": "강세 돌파", "prob": 0.35}, {"name": "기본 박스", "prob": 0.505}, {"name": "약세 이탈", "prob": 0.145}]


def test_delta_line_reports_each_change(monkeypatch):
    monkeypatch.setattr(committee, "_prev_meeting", lambda session: PREV)
    s = committee._delta_line({"last": 3060.0}, SCEN, {"stance": "방어"}, {"pcr_oi": 1.05, "gex_bn": 200.0}, "장전")
    assert s.startswith("직전 회의(10-15 장후 15:50) 대비: ")
    assert "코스피 3,000→3,060 (+2.0%)" in s
    assert "강세 30→35%" in s and "약세 20→14%" in s
    assert "기본" not in s                      # 1%p 미만 변화는 생략
    assert "판정 중립→방어" in s
    assert "PCR 1.00→1.05" in s and "감마 100→200억" in s


def test_delta_line_stance_kept_and_missing_fields(monkeypatch):
    monkeypatch.setattr(committee, "_prev_meeting", lambda session: {**PREV, "head": [], "derivs": {}})
    s = committee._delta_line({}, [], {"stance": "중립"}, {"pcr_oi": 1.2}, "장후")
    assert s.endswith("판정 유지(중립)")
    assert "코스피" not in s and "PCR" not in s


def test_delta_line_none_without_previous(monkeypatch):
    monkeypatch.setattr(committee, "_prev_meeting", lambda session: None)
    assert committee._delta_line({"last": 1.0}, [], {"stance": "중립"}, {}, "장후") is None
