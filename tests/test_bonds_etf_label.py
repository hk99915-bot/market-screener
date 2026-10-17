"""채권 ETF '만기 없음 · 금리 +100bp → 가격 −X%' 라벨 (결재 #15 ③) — 네트워크 없이 순수 로직만."""
from screener.bonds import dur_only, etf_rate_label, vehicles


def test_label_matches_duration_approx():
    lab = etf_rate_label(2.8, "KODEX 국고채3년")
    assert lab["maturity"].startswith("없음")
    assert "-2.8%" in lab["rate_line"] and "+100bp" in lab["rate_line"] and "만기 없음" in lab["rate_line"]
    # 한 줄 숫자 = dur_only 시나리오(+100bp)와 같은 근사
    assert dur_only(2.8, 3.85)["scen"]["100"] == -2.8


def test_label_without_duration_is_safe():
    lab = etf_rate_label(None)
    assert "없음" in lab["maturity"] and "계산 불가" in lab["rate_line"]


def _synthetic_o():
    v = lambda x: {"v": x}  # noqa: E731
    return {"us": {"chg": {"2Y": v(4.7), "7Y": v(5.0), "20Y": v(5.4)}},
            "kr": {"chg": {"3Y": v(3.85), "10Y": v(4.18), "20Y": v(4.21)}},
            "hedge_cost": 1.03,
            "etf": [{"s": "114260.KS", "n": "KODEX 국고채3년", "dur": 2.8, "y": 3.85, "role": "단기"},
                    {"s": "148070.KS", "n": "국고채10년 ETF (148070)", "dur": 8.0, "y": 4.18, "role": "장기"},
                    {"s": "SHY", "n": "미국채 1-3년 (SHY)", "dur": 1.9, "y": 4.7, "role": "단기"},
                    {"s": "IEF", "n": "미국채 7-10년 (IEF)", "dur": 7.5, "y": 5.0, "role": "중기"},
                    {"s": "TLT", "n": "미국채 20년+ (TLT)", "dur": 16.0, "y": 5.4, "role": "장기"},
                    {"s": "LQD", "n": "LQD", "dur": 8.5, "dy": 4.9, "role": "수익"},
                    {"s": "HYG", "n": "HYG", "dur": 3.5, "dy": 6.1, "role": "수익"}]}


def test_vehicles_etf_rows_have_no_maturity_and_rate_line():
    rows = {r["name"]: r for r in vehicles(_synthetic_o())}
    k3 = rows["KR 국고채 3년 ETF"]
    assert k3["maturity"].startswith("없음") and "-2.8%" in k3["rate_line"]
    assert rows["KR 국고채 10년 ETF"]["rate_line"].count("-8.0%") == 1
    # 개인투자용 국채는 만기가 있고 시가 평가가 없다 — ETF 라벨을 붙이면 안 된다
    p10 = rows["개인투자용 국채 10년"]
    assert p10["maturity"].startswith("있음") and p10["up100"] is None and "+100bp" not in p10["rate_line"]
    # 모든 행에 두 필드가 있다
    assert all("maturity" in r and "rate_line" in r for r in rows.values())
