"""파생 한눈에 인사이트 (screener/derivs.py insight) — 합성 데이터."""
from datetime import date, timedelta

from screener.derivs import insight


def _rows(n=60, pcr=1.4, gex=-500.0, iv=0.40):
    d0 = date(2026, 7, 1)
    return [{"date": str(d0 + timedelta(days=i)), "pcr_oi": str(pcr + (i % 10) / 100), "gex_bn": str(gex),
             "basis": str(1.0 + (i % 5)), "atm_iv": str(iv + (i % 10) / 100), "rep_iv": str(20 + i % 30),
             "basis_theo": "2.0", "fut_frgn": ""} for i in range(n)]


def _o(**kw):
    o = {"date": "2026-08-29", "spot": 850.0, "pcr_oi": 1.29, "atm_iv": 0.48, "rv20": 0.47, "gex_bn": -1100.0,
         "expiry": "2026-09-10", "dte": 12, "front": "202609", "fut": {"basis": 2.27}}
    o.update(kw)
    return o


def test_cards_and_rough_day():
    I = insight(_o(), _rows(), {"options_pcr": "검증전", "options_gamma": "검증전"}, today=date(2026, 8, 29))
    ks = [c["k"] for c in I["cards"]]
    assert ks == ["vol", "fear", "basis", "frgn", "expiry"]
    vol = I["cards"][0]
    assert vol["light"] == "red" and "감마 음수" in vol["easy"] and "최근 60거래일" in vol["where"] and vol["grade"] == "검증전"
    fear = I["cards"][1]
    assert "경계 약함" in fear["easy"]                 # 절대 1.29 라도 과거(1.40~1.49) 대비 낮음을 말한다
    assert "변동성 확대 국면" in I["one_line"] and "풋 포지션" not in I["one_line"]
    assert "레버리지" in I["so_what"] and "방향" in I["so_what"]
    assert I["cards"][3]["status"] == "데이터 없음"    # 외국인 선물 없음은 숨기지 않고 표시
    assert not I["stale"]


def test_missing_and_stale():
    o = _o(pcr_oi=None, atm_iv=None, gex_bn=None, fut={}, expiry=None, stale={"want": "2026-09-01", "got": "2026-08-29"})
    I = insight(o, [], {}, today=date(2026, 9, 1))
    assert I["stale"] and I["one_line"].startswith("[지연")
    assert all(c["light"] == "gray" for c in I["cards"] if c["k"] != "frgn")
    assert {c["status"] for c in I["cards"]} == {"데이터 없음"}
    assert "레버리지" not in I["so_what"]


def test_basis_vs_theo_intraday():
    """10/21 PB 요청: 장중엔 전일 확정 이론값 대비 괴리로 판단, 부호만 보고 '정상' 표기 금지."""
    rows = _rows()
    last = rows[-1]["date"]                                   # 마지막 확정일, basis_theo 2.0
    o = _o(date="2026-08-30", asof="2026-08-30 11:41", fut={"basis": 0.5})
    b = [c for c in insight(o, rows, {}, today=date(2026, 8, 30))["cards"] if c["k"] == "basis"][0]
    assert "장중 값(11:41)" in b["easy"] and "-1.50p" in b["easy"] and "저평가" in b["easy"] and last[5:] in b["easy"]
    assert b["light"] == "amber"                              # 양수(+0.5)여도 이론 대비 −1.5p 면 경계
    o2 = _o(date=last, asof=last + " 18:10", fut={"basis": 2.3})
    b2 = [c for c in insight(o2, rows, {}, today=date.fromisoformat(last))["cards"] if c["k"] == "basis"][0]
    assert "장중" not in b2["easy"] and "이론값 근처" in b2["easy"] and b2["light"] == "green"
    b3 = [c for c in insight(_o(fut={"basis": 2.0}), [], {}, today=date(2026, 8, 29))["cards"] if c["k"] == "basis"][0]
    assert "이론값 없음" in b3["easy"]
