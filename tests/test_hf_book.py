"""HF 재량 북(scripts/hf_book.py) — 체크리스트·기대값·컨빅션 크기·헤지 순 리스크·S4 추격 금지·북 손실 한도·보정."""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import hf_book as H  # noqa: E402

D = {"date": "2026-10-21", "k200": 900.0, "fut": 900.0, "iv": 0.4}
U = {"date": "2026-10-20", "spx": 7700.0, "ndx": 26400.0, "iv": 0.18, "usdkrw": 1325.0}
CK = dict(fund="f", narrative="n", positioning="p", macro="m", scenarios="s", hedge="h", kill="k", catalyst="2026-10-28",
          p_win=0.6, p_src="유사 사례 n=40")


def _a(**kw):
    base = dict(kind="fut", side="롱", code=None, name=None, stop=880.0, t1=940.0, t2=None, strike=None, expiry=None,
                hold=None, risk=None, conv="mid", hedge_of=None, why="t", src="t", **CK)
    base.update(kw)
    return SimpleNamespace(**base)


def _b():
    return {"open": [], "closed": [], "nav": [], "limits": {}}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr(H, "deriv_last", lambda: dict(D))
    monkeypatch.setattr(H, "us_last", lambda: dict(U))
    monkeypatch.setattr(H, "daily_vol", lambda kind, code, n=20: 0.01)
    monkeypatch.setattr(H, "beta_of", lambda kind, code, n=60: 1.0)
    monkeypatch.setattr(H, "bars", lambda market, code: [])


def test_bs_parity_and_delta():
    import math
    c, p = H.bs("call", 900, 900, 0.1, 0.4), H.bs("put", 900, 900, 0.1, 0.4)
    assert abs((c - p) - (900 - 900 * math.exp(-H.RATE * 0.1))) < 1e-6
    assert abs(H.bs_delta("call", 900, 900, 0.1, 0.4) - H.bs_delta("put", 900, 900, 0.1, 0.4) - 1) < 1e-9


def test_checklist_required():
    with pytest.raises(SystemExit, match="체크리스트"):
        H.add(_b(), _a(kill=None))
    with pytest.raises(SystemExit, match="체크리스트"):
        H.add(_b(), _a(p_src=""))


def test_rr_breakeven_and_ev_gate():
    p = H.add(_b(), _a())                       # 900 → 손절 880(20) · 1차 940(40) = R:R 2.0
    assert p["plan"]["rr"] == 2.0 and p["plan"]["p_be"] == round(1 / 3, 3) and p["plan"]["ev_r"] == round(0.6 * 2 - 0.4, 3)
    with pytest.raises(SystemExit, match="기대값"):
        H.add(_b(), _a(p_win=0.3))              # 0.3×2 − 0.7 < 0
    with pytest.raises(SystemExit, match="1차 목표"):
        H.add(_b(), _a(t1=None))
    with pytest.raises(SystemExit, match="손절"):
        H.add(_b(), _a(stop=910.0))


def test_conviction_sizing_and_subjective_low():
    hi = H.add(_b(), _a(conv="high", stop=850.0, t1=1000.0))
    assert abs(hi["risk"] - 0.004) < 1e-4
    sub = H.add(_b(), _a(conv="high", p_src="주관", stop=850.0, t1=1000.0))
    assert sub["conv"] == "low" and abs(sub["risk"] - 0.0015) < 1e-4


def test_vol_factor():
    assert H.vol_factor(0.04) == 0.5 and H.vol_factor(0.01) == 1.0 and H.vol_factor(None) == 1.0


def test_option_sell_banned_and_total_risk_cap():
    b = _b()
    with pytest.raises(SystemExit):
        H.add(b, _a(kind="put", side="숏", strike=850.0, expiry="2026-11-12"))
    for _ in range(5):                         # 0.4% × 5 = 2.0%
        H.add(b, _a(kind="put", strike=850.0, expiry="2026-11-12", conv="high"))
    assert H.open_risk(b) <= H.RISK_ALL + 1e-9
    with pytest.raises(SystemExit, match="한도"):
        H.add(b, _a(kind="put", strike=850.0, expiry="2026-11-12"))


def test_hedge_leg_counts_zero_and_capped():
    b = _b()
    par = H.add(b, _a(kind="es", stop=7550.0, t1=8000.0))
    before = H.open_risk(b)
    hg = H.add(b, _a(kind="nq", side="숏", stop=27000.0, t1=25000.0, hedge_of=par["id"]))
    assert H.open_risk(b) == pytest.approx(before) and hg["weight"] <= 1.5 * par["weight"] + 1e-9
    with pytest.raises(SystemExit, match="헤지 대상"):
        H.add(b, _a(kind="nq", side="숏", stop=27000.0, t1=25000.0, hedge_of="없는-id"))


def test_s4_chase_ban(monkeypatch):
    bars = [{"t": f"2026-09-{i + 1:02d}", "o": 100, "h": 101, "l": 99, "c": 100.0, "v": 1000} for i in range(25)]
    bars.append({"t": "2026-10-21", "o": 100, "h": 112, "l": 100, "c": 110.0, "v": 5000})
    monkeypatch.setattr(H, "bars", lambda market, code: bars)
    assert H.s4_hit("000000") == "2026-10-21"
    with pytest.raises(SystemExit, match="추격 롱 금지"):
        H.add(_b(), _a(kind="stock", code="000000", stop=100.0, t1=130.0))
    p = H.add(_b(), _a(kind="stock", side="숏", code="000000", stop=120.0, t1=90.0))   # 숏은 허용
    assert p["side"] == "숏"


def test_liquidity_cut(monkeypatch):
    bars = [{"t": f"2026-10-{i + 1:02d}", "o": 100, "h": 101, "l": 99, "c": 100.0, "v": 10_000} for i in range(20)]
    monkeypatch.setattr(H, "bars", lambda market, code: bars)            # 하루 거래대금 100만원
    p = H.add(_b(), _a(kind="stock", code="000001", stop=95.0, t1=110.0))
    assert "liq_cut" in p["sizing"] and H.AUM * p["weight"] <= H.LIQ_FRAC * 1_000_000 + 1


def test_stop_close_attr_and_brier():
    b = _b()
    H.add(b, _a())
    D["fut"] = 870.0
    try:
        out = H.mark(b)
    finally:
        D["fut"] = 900.0
    c = out[0]
    assert c["exit_why"].startswith("손절") and c["r"] < -1 and c["plan"]["brier"] == pytest.approx(0.36)
    assert any("승률 보정" in x for x in H.perf_lines(b))


def test_days_count_trading_days_not_marks():
    b = _b()
    H.add(b, _a())
    for _ in range(3):
        H.mark(b)
    assert b["open"][0]["days"] == 0
    D["date"] = "2026-10-22"
    try:
        H.mark(b)
        H.mark(b)
    finally:
        D["date"] = "2026-10-21"
    assert b["open"][0]["days"] == 1


def test_book_drawdown_limits():
    b = _b()
    b["nav"] = [{"d": "2026-10-10", "pnl": 0.01}]
    b["closed"] = [{"r": -10.0, "risk": 0.0045}]            # 손익 −4.5% → 고점 +1% 대비 −5.5%
    lim = H.book_limits(b, "2026-10-22")
    assert lim["ban_new"] and lim.get("flat") and lim["halt_until"] == "2026-11-05"
    b2 = _b()
    b2["closed"] = [{"r": -3.5, "risk": 0.01}]               # −3.5%
    assert H.book_limits(b2, "2026-10-22")["ban_new"]
    with pytest.raises(SystemExit, match="신규 금지"):
        H.add(b2, _a())


def test_us_es_and_spx_put():
    b = _b()
    p = H.add(b, _a(kind="es", stop=7550.0, t1=7950.0))
    assert p["market"] == "US" and p["entry"] == 7700.0 and "계약" in H.qty(p)
    o = H.add(b, _a(kind="spx_put", strike=7300.0, expiry="2026-11-20", stop=None, t1=None))
    assert 0 < o["entry"] < 7700 and o["stop"] is None and o["plan"]["rr"] == 1.0
    with pytest.raises(SystemExit):
        H.add(b, _a(kind="spx_call", side="숏", strike=8000.0, expiry="2026-11-20"))


def test_exit_next_open(monkeypatch):
    bars = [{"t": "2026-10-20", "o": 100.0, "h": 101, "l": 99, "c": 100.0, "v": 1e9},
            {"t": "2026-10-21", "o": 100.0, "h": 101, "l": 99, "c": 100.0, "v": 1e9}]
    monkeypatch.setattr(H, "bars", lambda market, code: bars)
    b = _b()
    p = H.add(b, _a(kind="us_stock", code="XX", stop=80.0, t1=130.0))
    p["exit_next_open"] = {"after": "2026-10-21", "why": "t"}
    assert H.mark(b) == [] and b["open"]                       # 다음 봉 없음 → 대기
    bars.append({"t": "2026-10-22", "o": 95.0, "h": 96, "l": 90, "c": 92.0, "v": 1e9})
    out = H.mark(b)
    assert out and out[0]["exit"] == 95.0 and out[0]["exit_why"].startswith("사전 결정 시가 청산") and not b["open"]


def test_utilization_warning():
    b = _b()
    assert any("가동률" in x and "⚠️" in x for x in H.show(b))
    for _ in range(3):
        H.add(b, _a(kind="put", strike=850.0, expiry="2026-11-12", conv="high"))    # 1.2% / 2.0% = 60%
    assert not any("⚠️ 가동률" in x for x in H.show(b))
