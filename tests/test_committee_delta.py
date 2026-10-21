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


def test_mock_gate_b1(monkeypatch):
    """B1(10/21): 위성 해금 전 + 판정 관망 + TOP3 실행 후보 → 🔴 대신 🟡 '모의 추적 후보 n개'. 해금 + 매수 쪽이면 원래대로."""
    from screener import config
    ideas = {"items": [{"s": "A", "status": "실행 후보"}, {"s": "B", "status": "실행 후보"}, {"s": "C", "status": "대기"}]}
    bl = {"light": "green", "label": committee.LIGHTS["green"], "stance": "관망", "lines": ["a", "b", "c"]}
    monkeypatch.setattr(config, "SATELLITE_LIVE", False)
    g = committee._mock_gate(bl, ideas)
    assert g["light"] == "yellow" and g["label"] == "🟡 모의 추적 후보 2개(실계좌 위성 해금 전)" and "모의 추적만" in g["lines"][2]
    assert committee._mock_gate(bl, {"items": []}) is bl
    monkeypatch.setattr(config, "SATELLITE_LIVE", True)
    assert committee._mock_gate({**bl, "stance": "분할 매수"}, ideas)["light"] == "green"
    assert "판정 관망" in committee._mock_gate(bl, ideas)["label"]
    assert committee._live_buy("분할 매수") and not committee._live_buy("관망")
