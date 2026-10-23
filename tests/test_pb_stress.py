"""pb.evaluate 스트레스(결재 #3): 구속 시나리오 '2026-07 실측(06/22→07/30)' 손실률 — 비율만, 분모 선택(D2/D1/EQ). 네트워크 없음(가짜 detail JSON).
10/24 결재 appr-frm-agenda-a(req-frm-cb131a3e): SOXX 대리 −30% 가정 → 실측(semi −50 · elec −60 · 코어 바구니 실측) 교체."""
import json
import re
from pathlib import Path

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
    # 손실 = 1000×−0.50 + 500×−0.60 + 룩스루 500×−0.50 = −1050 (두 북)
    den, books = pb.stress_denominator("D2", nav=NAV, tot=TOT, tot_sat=TOT_SAT, cash_sat=CASH_SAT)
    assert (den, books) == (4000.0, ("sat", "isa"))
    assert pb.stress_loss(ROWS, den, "2026-07", books) == pytest.approx(-1050 / 4000)
    den, books = pb.stress_denominator("EQ", nav=NAV, tot=TOT, tot_sat=TOT_SAT, cash_sat=CASH_SAT)
    assert pb.stress_loss(ROWS, den, "2026-07", books) == pytest.approx(-1050 / 2500)
    # D1 = 위성 북만: 손실 −500 −300 = −800, 분모 = 위성 주식 1500 + 위성 현금 500 = 2000
    den, books = pb.stress_denominator("D1", nav=NAV, tot=TOT, tot_sat=TOT_SAT, cash_sat=CASH_SAT)
    assert books == ("sat",) and pb.stress_loss(ROWS, den, "2026-07", books) == pytest.approx(-800 / 2000)
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
    txt = "005930 10\n009150 5\n현금 500\n## ISA\n069500 10\n현금 1000\n"   # 가상: 반도체 1000 · 전기 500 · 지수 ETF 1000(코어 K200) · 현금 1500 → NAV 4000
    ev = pb.evaluate(txt)
    # 반도체 −500 + 전기 −300 + KODEX 200(코어 K200 실측 전체 −41%, 룩스루 이중 계산 없음) −410 = −1210
    assert ev["stress_denom"] == "D2" and ev["stress"]["2026-07"] == pytest.approx(-1210 / 4000)
    ev1 = pb.evaluate(txt, stress_denominator_code="D1")
    assert ev1["stress"]["2026-07"] == pytest.approx(-800 / 2000)
    monkeypatch.setenv("MY_HOLDINGS", txt)
    monkeypatch.delenv("MY_RULES", raising=False)
    b = pb.brief()
    st = [ln for ln in b.splitlines() if ln.startswith("• 스트레스 2026-07")]
    assert len(st) == 1 and ("-30.2%" in st[0] or "-30.3%" in st[0]) and "⛔" in st[0]
    assert "원" not in st[0]   # 비율만 — 금액 금지
    assert not [ln for ln in b.splitlines() if "참고:" in ln and "스트레스" in ln]   # 참고 줄 없음 — 실측이 구속으로 승격


def test_binding_scenario_is_measured_2026_07():
    """결재 appr-frm-agenda-a(10/24): 구속 시나리오 = 실측 06/22→07/30 (reports/studies/2026-10-23_frm_replay_2026-07.md §1, 비율만)."""
    assert [k for k, sc in pb.STRESS_SCENARIOS.items() if sc.get("binding", True)] == ["2026-07"]
    sc = pb.STRESS_SCENARIOS["2026-07"]
    assert (sc["semi"], sc["elec"], sc["look"]) == (-0.50, -0.60, -0.50)   # KODEX 반도체 −50.3 · 삼성전기 −60.5 (옛 −30/−24 대리 기각)
    assert sc["core"] == {"K200": -0.41, "S&P500": -0.08, "NDX": -0.16, "KTB": 0.0, "Gold": -0.04}
    from screener.defs import ISA_TARGET
    assert set(sc["core"]) == set(ISA_TARGET)   # 코어 바구니 전부에 충격이 있다 — 바구니 추가 시 여기서 깨져야 한다
    rows = ROWS + [{"book": "isa", "s": "069500", "name": "KODEX 200", "v": 1000.0, "semi": False, "elec": False, "look": 300.0, "isa": "K200"},
                   {"book": "isa", "s": "114260", "name": "KODEX 국고채3년", "v": 500.0, "semi": False, "elec": False, "look": 0.0, "isa": "KTB"}]
    # semi −500 + elec −300 + 룩스루 −250 + K200 1000×−0.41(룩스루 이중 계산 없음) + KTB 0 = −1460
    assert pb.stress_loss(rows, 5500.0, "2026-07") == pytest.approx(-1460 / 5500)
    ev = {"stress": {"2026-07": -0.20}, "stress_denom": "D2"}
    assert "⛔" in pb.stress_line(ev) and pb.stress_ref_lines(ev) == []


def test_verdict_flip_from_proxy_to_measured():
    """영향: 반도체 비중 35%(분모 D2, 가상)는 옛 대리(−30%)로 −10.5% ✅, 실측(−50%)으로 −17.5% ⛔.
    허용 반도체 비중 = 15 ÷ 50 = 30% (kb:frm#10; 옛 가정 15 ÷ 30 = 50%)."""
    rows = [{"book": "sat", "v": 350.0, "semi": True, "elec": False, "look": 0.0}]
    x = pb.stress_loss(rows, 1000.0, "2026-07")
    assert x == pytest.approx(-0.175) and "⛔" in pb.stress_line({"stress": {"2026-07": x}, "stress_denom": "D2"})
    assert 350.0 * -0.30 / 1000.0 > -pb.STRESS_LIMIT   # 옛 가정이었으면 통과 — 판정이 뒤집히는 구간
    edge = [{"book": "sat", "v": 300.0, "semi": True, "elec": False, "look": 0.0}]
    assert "✅" in pb.stress_line({"stress": {"2026-07": pb.stress_loss(edge, 1000.0)}, "stress_denom": "D2"})   # 30% = 경계(−15.0%) 통과


def test_my_tab_shocks_match_pb():
    """MY 탭(apps-script/tab_my.html) STRESS_0726 = pb.STRESS_SCENARIOS['2026-07'] — 화면·텔레그램 판정이 같은 숫자."""
    src = (Path(__file__).resolve().parents[1] / "apps-script" / "tab_my.html").read_text(encoding="utf-8")
    m = re.search(r"const STRESS_0726=\{semi:(-?[\d.]+),elec:(-?[\d.]+),look:(-?[\d.]+),core:\{([^}]*)\}\};", src)
    assert m, "tab_my.html 에 STRESS_0726 상수가 없다"
    sc = pb.STRESS_SCENARIOS["2026-07"]
    assert tuple(float(m.group(i)) for i in (1, 2, 3)) == (sc["semi"], sc["elec"], sc["look"])
    core = {k: float(v) for k, v in re.findall(r"'([^']+)':(-?[\d.]+)", m.group(4))}
    assert core == sc["core"]
    assert "-0.30:c.kind==='elec'?-0.24" not in src   # 옛 대리 충격 잔존 금지
