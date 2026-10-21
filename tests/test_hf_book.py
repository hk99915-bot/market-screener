"""HF 재량 북(scripts/hf_book.py) — 한도·손절 필수·옵션 매도 금지·BS 근사."""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import hf_book as H  # noqa: E402

D = {"date": "2026-10-21", "k200": 900.0, "fut": 900.0, "iv": 0.4}


def _a(**kw):
    base = dict(kind="fut", side="롱", code=None, name=None, stop=880.0, t1=940.0, t2=None, strike=None, expiry=None,
                hold=None, risk=H.RISK_1, why="t", src="t")
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.fixture(autouse=True)
def _deriv(monkeypatch):
    monkeypatch.setattr(H, "deriv_last", lambda: dict(D))


def test_bs_parity():
    c, p = H.bs("call", 900, 900, 0.1, 0.4), H.bs("put", 900, 900, 0.1, 0.4)
    assert abs((c - p) - (900 - 900 * __import__("math").exp(-H.RATE * 0.1))) < 1e-6


def test_fut_needs_stop_and_sizes_by_risk():
    b = {"open": [], "closed": []}
    with pytest.raises(SystemExit):
        H.add(b, _a(stop=None))
    with pytest.raises(SystemExit):
        H.add(b, _a(stop=910.0))          # 롱인데 손절이 위
    p = H.add(b, _a())
    assert abs(p["risk"] - H.RISK_1) < 1e-4 and p["weight"] <= 0.15


def test_option_sell_banned_and_risk_cap():
    b = {"open": [], "closed": []}
    with pytest.raises(SystemExit):
        H.add(b, _a(kind="put", side="숏", strike=850.0, expiry="2026-11-12"))
    for _ in range(4):
        H.add(b, _a(kind="put", strike=850.0, expiry="2026-11-12"))
    assert H.open_risk(b) <= H.RISK_ALL + 1e-9
    with pytest.raises(SystemExit):
        H.add(b, _a(kind="put", strike=850.0, expiry="2026-11-12"))


def test_stop_closes():
    b = {"open": [], "closed": []}
    H.add(b, _a())
    D["fut"] = 870.0
    try:
        out = H.mark(b)
    finally:
        D["fut"] = 900.0
    assert out and out[0]["exit_why"].startswith("손절") and out[0]["r"] < -1


def test_us_es_and_spx_put(monkeypatch):
    U = {"date": "2026-10-20", "spx": 7700.0, "ndx": 26400.0, "iv": 0.18, "usdkrw": 1325.0}
    monkeypatch.setattr(H, "us_last", lambda: dict(U))
    b = {"open": [], "closed": []}
    p = H.add(b, _a(kind="es", stop=7550.0, t1=7950.0))
    assert p["market"] == "US" and p["entry"] == 7700.0 and "계약" in H.qty(p)
    o = H.add(b, _a(kind="spx_put", strike=7300.0, expiry="2026-11-20", stop=None))
    assert 0 < o["entry"] < 7700 and o["stop"] is None
    with pytest.raises(SystemExit):
        H.add(b, _a(kind="spx_call", side="숏", strike=8000.0, expiry="2026-11-20"))
    assert H.open_risk(b) <= H.RISK_ALL + 1e-9


def test_days_count_trading_days_not_marks():
    b = {"open": [], "closed": []}
    H.add(b, _a())
    for _ in range(3):
        H.mark(b)
    assert b["open"][0]["days"] == 0          # 같은 거래일에 회의 3번 → 0일
    D["date"] = "2026-10-22"
    try:
        H.mark(b)
        H.mark(b)
    finally:
        D["date"] = "2026-10-21"
    assert b["open"][0]["days"] == 1
