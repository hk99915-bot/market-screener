"""HF 바스켓 엔진(scripts/hf_basket.py) — 분위 구성·베타 배율 상한·손익·바스켓 손절·시간 청산·재량 북 합산."""
import sys
from pathlib import Path

from datetime import datetime

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import hf_basket as B  # noqa: E402
import hf_book as H  # noqa: E402

N = 40
AFTER = datetime(2026, 10, 23, 15, 25, tzinfo=H.KST)
VOLS = {f"{i:06d}": 0.005 + i * 0.001 for i in range(N)}      # 000000 = 최저 변동, 000039 = 최고
PX = {c: 10000.0 for c in VOLS}
D = {"date": "2026-10-23", "k200": 840.0, "fut": 840.0, "iv": 0.5}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for c in PX:
        PX[c] = 10000.0
    D["date"] = "2026-10-23"
    monkeypatch.setattr(B, "universe", lambda top_n=B.TOP_N: [(c, f"N{c}") for c in VOLS])
    monkeypatch.setattr(B, "vol60", lambda c: VOLS[c])
    monkeypatch.setattr(H, "beta_of", lambda kind, code, n=60: 0.5 if VOLS.get(code, 1) < 0.01 else 1.3)
    monkeypatch.setattr(H, "stock_last", lambda c: (D["date"], PX[c], f"N{c}"))
    monkeypatch.setattr(H, "adv_krw", lambda kind, c: 1e13)
    monkeypatch.setattr(H, "deriv_last", lambda: dict(D))
    monkeypatch.setattr(H, "bars", lambda m, c: [])


def _b():
    return {"open": [], "closed": [], "nav": [], "limits": {}}


def test_build_deciles_and_beta_floor():
    k = B.build(_b(), risk=0.004)
    lo = [l for l in k["legs"] if l["side"] == "롱"]
    sh = [l for l in k["legs"] if l["side"] == "숏"]
    assert {l["code"] for l in lo} == {"000000", "000001", "000002", "000003"} and {l["code"] for l in sh} == {"000036", "000037", "000038", "000039"}
    assert k["beta"]["롱"] == pytest.approx(2 / 3, abs=1e-3)            # 0.5 → 바닥 2/3 (배율 ≤ 1.5)
    g = 0.004 / B.UNIT_STOP
    assert sum(l["w"] for l in lo) == pytest.approx(g * 1.5, rel=1e-4) and sum(l["w"] for l in sh) == pytest.approx(g / 1.3, rel=1e-4)


def test_held_codes_excluded():
    b = _b()
    b["open"].append({"code": "000039", "risk": 0.001})
    k = B.build(b)
    assert "000039" not in {l["code"] for l in k["legs"]}


def test_open_counts_risk_and_cost():
    b = _b()
    x = B.open_basket(b, risk=0.004, now=AFTER)
    assert H.open_risk(b) == pytest.approx(0.004) and x["pnl"] == pytest.approx(-B.SIDE_COST * x["gross"], abs=2e-6)
    with pytest.raises(SystemExit, match="열린 바스켓"):
        B.open_basket(b, now=AFTER)


def test_pnl_sign_and_stop():
    b = _b()
    B.open_basket(b, risk=0.004, now=AFTER)
    for c in ("000036", "000037", "000038", "000039"):
        PX[c] = 9000.0                                                  # 숏 다리 −10% → 이익
    assert B.mark(b) == [] and b["baskets"]["open"][0]["pnl"] > 0
    for c in ("000036", "000037", "000038", "000039"):
        PX[c] = 14000.0                                                 # 숏 다리 +40% → 손실 > 예산
    out = B.mark(b)
    assert out and out[0]["exit_why"].startswith("바스켓 손절") and out[0]["r"] < -1 and not b["baskets"]["open"]


def test_time_exit_after_21_trading_days():
    b = _b()
    B.open_basket(b, now=AFTER)
    for i in range(B.HOLD):
        D["date"] = f"2026-11-{i + 1:02d}"
        out = B.mark(b)
    assert out and out[0]["exit_why"].startswith("21거래일") and b["baskets"]["closed"][0]["days"] == B.HOLD


def test_book_mark_and_show_include_basket():
    b = _b()
    B.open_basket(b, now=AFTER)
    H.mark(b)
    assert any("바스켓 BK-" in x for x in H.show(b)) and "pnl" in b["limits"]


def test_intraday_entry_blocked():
    with pytest.raises(SystemExit, match="15:00 이후"):
        B.open_basket(_b(), now=datetime(2026, 10, 23, 12, 10, tzinfo=H.KST))
