"""pb.evaluate 스트레스(결재 #3): '2026-07 재현(반도체 −30%)' 손실률 — 비율만, 분모 선택(D2/D1/EQ). 네트워크 없음(가짜 detail JSON)."""
import json

import pytest

from screener import pb

# 가상 보유 (금액은 테스트 전용 가상 숫자): 위성 = 반도체 개별주 1,000 + 전기 500 + 현금 500 / ISA = 지수 ETF(반도체 룩스루 50%) 1,000 + 현금 1,000
ROWS = [
    {"book": "sat", "v": 1000.0, "semi": True, "elec": False, "look": 0.0},
    {"book": "sat", "v": 500.0, "semi": False, "elec": True, "look": 0.0},
    {"book": "isa", "v": 1000.0, "semi": False, "elec": False, "look": 500.0},
]
NAV, TOT, TOT_SAT, CASH_SAT = 4000.0, 2500.0, 1500.0, 500.0


def test_stress_loss_ratio_by_denominator():
    # 손실 = 1000×−0.30 + 500×−0.24 + 500×−0.30 = −570 (두 북)
    den, books = pb.stress_denominator("D2", nav=NAV, tot=TOT, tot_sat=TOT_SAT, cash_sat=CASH_SAT)
    assert (den, books) == (4000.0, ("sat", "isa"))
    assert pb.stress_loss(ROWS, den, "2026-07", books) == pytest.approx(-570 / 4000)
    den, books = pb.stress_denominator("EQ", nav=NAV, tot=TOT, tot_sat=TOT_SAT, cash_sat=CASH_SAT)
    assert pb.stress_loss(ROWS, den, "2026-07", books) == pytest.approx(-570 / 2500)
    # D1 = 위성 북만: 손실 −300 −120 = −420, 분모 = 위성 주식 1500 + 위성 현금 500 = 2000
    den, books = pb.stress_denominator("D1", nav=NAV, tot=TOT, tot_sat=TOT_SAT, cash_sat=CASH_SAT)
    assert books == ("sat",) and pb.stress_loss(ROWS, den, "2026-07", books) == pytest.approx(-420 / 2000)
    assert pb.stress_loss(ROWS, 0.0) == 0.0
    with pytest.raises(ValueError):
        pb.stress_denominator("D9", nav=NAV, tot=TOT, tot_sat=TOT_SAT, cash_sat=CASH_SAT)


def test_stress_line_ratio_only_and_limit():
    ev = {"stress": {"2026-07": -0.1425}, "stress_denom": "D2"}
    line = pb.stress_line(ev)
    assert "-14.2%" in line or "-14.3%" in line
    assert "✅" in line and "원" not in line and "한도 −15%" in line and "D2" in line
    ev["stress"]["2026-07"] = -0.151
    assert "⛔" in pb.stress_line(ev)


def _fake_reports(tmp_path, monkeypatch):
    for mk, s, name, chain, etf in [("KR", "005930", "삼성전자", "메모리 반도체", None),
                                    ("KR", "009150", "삼성전기", "IT 하드웨어 — 전자부품", None),
                                    ("KR", "069500", "KODEX 200", None, {"look": {"chains": {"메모리 반도체": 0.5}}})]:
        d = tmp_path / "detail" / mk
        d.mkdir(parents=True, exist_ok=True)
        idx = d / "_index.json"
        j = json.loads(idx.read_text()) if idx.exists() else {"symbols": [], "names": {}}
        j["symbols"].append(s)
        j["names"][s] = name
        idx.write_text(json.dumps(j))
        doc = {"name": name, "close": 100.0, "stats": {"ret1": 0.0}, "c1y": [], "drivers": {"chain": {"name": chain}} if chain else {}}
        if etf:
            doc["etf"] = etf
        (d / f"{s}.json").write_text(json.dumps(doc))
    monkeypatch.setattr(pb, "REPORT_DIR", tmp_path)


def test_evaluate_exposes_stress_ratio(tmp_path, monkeypatch):
    _fake_reports(tmp_path, monkeypatch)
    txt = "005930 10\n009150 5\n현금 500\n## ISA\n069500 10\n현금 1000\n"   # 가상: 반도체 1000 · 전기 500 · 지수 ETF 1000(룩스루 50%) · 현금 1500 → NAV 4000
    ev = pb.evaluate(txt)
    assert ev["stress_denom"] == "D2" and ev["stress"]["2026-07"] == pytest.approx(-570 / 4000)
    ev1 = pb.evaluate(txt, stress_denominator_code="D1")
    assert ev1["stress"]["2026-07"] == pytest.approx(-420 / 2000)
    monkeypatch.setenv("MY_HOLDINGS", txt)
    monkeypatch.delenv("MY_RULES", raising=False)
    b = pb.brief()
    st = [ln for ln in b.splitlines() if ln.startswith("• 스트레스 2026-07")]
    assert len(st) == 1 and ("-14.2%" in st[0] or "-14.3%" in st[0])
    assert "원" not in st[0]   # 비율만 — 금액 금지


def test_measured_reference_scenario_not_binding():
    """FRM 10/23: '2026-07m' 실측 재생은 참고(binding False) — 코어 ETF 는 실측 전체 손실, ⛔ 판정엔 안 씀."""
    sc = pb.STRESS_SCENARIOS["2026-07m"]
    assert sc["binding"] is False and pb.STRESS_SCENARIOS["2026-07"].get("binding", True)
    rows = ROWS + [{"book": "isa", "s": "069500", "name": "KODEX 200", "v": 1000.0, "semi": False, "elec": False, "look": 300.0, "isa": "K200"},
                   {"book": "isa", "s": "114260", "name": "KODEX 국고채3년", "v": 500.0, "semi": False, "elec": False, "look": 0.0, "isa": "KTB"}]
    # semi 1000×−0.50 + elec 500×−0.60 + 룩스루 500×−0.50 + K200 1000×−0.41(룩스루 이중 계산 없음) + KTB 0 = −1460
    assert pb.stress_loss(rows, 5500.0, "2026-07m") == pytest.approx(-1460 / 5500)
    # 기존 구속 시나리오는 그대로: 코어 ETF 는 룩스루만
    assert pb.stress_loss(rows, 5500.0, "2026-07") == pytest.approx((-300 - 120 - 150 - 90) / 5500)
    ev = {"stress": {"2026-07": -0.10, "2026-07m": -0.20}, "stress_denom": "D2"}
    assert "✅" in pb.stress_line(ev)              # 판정은 구속 시나리오만
    ref = pb.stress_ref_lines(ev)
    assert len(ref) == 1 and "-20.0%" in ref[0] and "⛔" not in ref[0] and "원" not in ref[0]
