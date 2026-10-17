"""결재 #3 (10/17 14:09): 반도체 밴드 레짐 연동 35/40/40(+45 발동·30 하단) · 11월 말 35% 적립 글라이드 · 60일 VaR99 계기판 ·
삼성전기 포함/제외 병기. 가상 숫자만(금액은 테스트 전용), 출력은 비율만."""
from datetime import date

import pytest

from screener import defs, pb


def _up(n=260, start=100.0, step=0.002):
    return [start * (1 + step) ** i for i in range(n)]


def test_regime_three_states():
    assert pb.semi_regime(_up())["regime"] == "상승장"
    bear = _up(200) + [_up(200)[-1] * (0.99 ** i) for i in range(1, 41)]      # 고점 −33%
    assert pb.semi_regime(bear)["regime"] == "하락장"
    rec = bear + [bear[-1] * 1.15, bear[-1] * 1.17]                           # 20일선 위 2일 연속, 고점은 여전히 −20% 아래
    r = pb.semi_regime(rec)
    assert r["regime"] == "회복확인" and r["above20"] >= 2 and r["tag"] != "상승"
    assert pb.semi_regime([])["regime"] == "하락장"                            # 데이터 없음 → 가장 낮은 상한


def test_band_status_by_regime():
    assert defs.SEMI_REGIME_CAP == {"하락장": 0.35, "회복확인": 0.40, "상승장": 0.40}
    assert pb.band_status(0.38, "하락장")["status"] == "over" and "신규 매수 금지" in pb.band_status(0.38, "하락장")["tag"]
    assert pb.band_status(0.38, "회복확인")["status"] == "ok"
    assert pb.band_status(0.47, "상승장")["status"] == "trigger" and "40%로" in pb.band_status(0.47, "상승장")["tag"]
    assert pb.band_status(0.47, "하락장")["tag"].endswith("35%로")
    assert pb.band_status(0.25, "상승장")["status"] == "floor" and "재매수 허용" in pb.band_status(0.25, "상승장")["tag"]


def test_glide_path_with_monthly_isa():
    # 가상: 반도체 45, 분모 100, 월 적립 10 (11/1) → 11/30 = 45/110 = 40.9% · 35% 까지 추가 축소 (45 − 38.5)/100 = 6.5%p
    g = pb.glide_path(45.0, 100.0, 10.0, date(2026, 10, 17), "2026-11-30", day=1)
    assert g["n_contrib"] == 1 and g["points"][1]["d"] == "2026-11-01"
    assert g["points"][-1]["x"] == pytest.approx(45 / 110) and g["need"] == pytest.approx(0.065)
    assert g["points"][-1]["line"] == pytest.approx(0.35) and g["points"][0]["line"] == pytest.approx(0.45)
    # 적립만으로 도달
    assert pb.glide_path(30.0, 100.0, 10.0, date(2026, 10, 17))["need"] == 0.0
    # 적립 0
    assert pb.glide_path(45.0, 100.0, 0.0, date(2026, 10, 17))["points"][-1]["x"] == pytest.approx(0.45)


def test_var99_60d_and_limit():
    import math
    closes = [100.0]
    for i in range(60):
        closes.append(closes[-1] * (1.02 if i % 2 else 0.98))
    rows = [{"v": 50.0, "c61": closes}]
    v = pb.var99_window(rows, 100.0)
    sd = math.sqrt(sum((x - 0) ** 2 for x in [0.02, -0.02] * 30) / 59)    # 평균≈0
    assert v["n"] == 60 and v["var99"] == pytest.approx(defs.VAR99_Z * 50 * sd / 100, rel=0.02)
    assert pb.var_limit("하락장") == 0.015 and pb.var_limit("상승장") == 0.02
    assert pb.var99_window([{"v": 1.0, "c61": [1.0] * 5}], 100.0) is None


def test_isa_monthly_line_is_not_a_holding():
    assert pb.isa_monthly_in("ISA적립 300 25\n005930 1") == (300.0, 25)
    books = pb.parse_books("005930 1 100\nISA적립 300\n예적금 50\n")
    assert [h["key"] for h in books["sat"][0]] == ["005930"]


def test_evaluate_band_block_and_brief(tmp_path, monkeypatch):
    from tests.test_pb_stress import _fake_reports
    _fake_reports(tmp_path, monkeypatch)
    monkeypatch.setattr(pb, "semi_regime", lambda closes=None: {"regime": "하락장", "tag": "하락", "above20": 0, "n": 260, "src": "t"})
    txt = "005930 10\n009150 5\n현금 500\n## ISA\n069500 10\n현금 1000\nISA적립 400\n"   # 가상: 반도체 1000 · 삼성전기 500 · NAV 4000
    ev = pb.evaluate(txt)
    b = ev["band"]
    assert b["ex"]["x"] == pytest.approx(0.25) and b["incl"]["x"] == pytest.approx(0.375)
    assert b["ex"]["status"] == "floor" and b["incl"]["status"] == "over" and b["has_monthly"]
    monkeypatch.setenv("MY_HOLDINGS", txt)
    monkeypatch.delenv("MY_RULES", raising=False)
    out = pb.brief()
    assert "레짐 <b>하락장</b>" in out and "삼성전기 제외 25%" in out and "포함 38%" in out and "원" not in "".join(pb.band_lines(ev))
