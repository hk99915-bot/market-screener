"""HF 재량 북(scripts/hf_book.py) — 체크리스트·기대값·컨빅션 크기·헤지 순 리스크·S4 추격 금지·북 손실 한도·보정."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import hf_book as H  # noqa: E402

OTHER_BOOKS = H.other_books          # autouse 픽스처가 빈 목록으로 바꾸기 전 원본

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
    monkeypatch.setattr(H, "other_books", lambda market, today: [])


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
    monkeypatch.setattr(H, "live_kr_stock", lambda code: None)   # live.json 실값이 섞이면 가격 가정이 깨진다
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
    monkeypatch.setattr(H, "live_kr_stock", lambda code: None)   # live.json 실값이 섞이면 가격 가정이 깨진다
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



_US_LAST, _US_STOCK_LAST = H.us_last, H.us_stock_last      # autouse 픽스처가 us_last 를 바꾸기 전 원본


def test_us_live_overlay(tmp_path, monkeypatch):
    import json as _j
    (tmp_path / "reports").mkdir()
    ser = {k: [["2026-10-22", 0, 0, 0, v, 0]] for k, v in (("SPX", 7663.0), ("NASDAQ", 26009.0), ("VIX", 19.0), ("USDKRW", 1325.0))}
    (tmp_path / "reports" / "macro_series.json").write_text(_j.dumps({"series": ser}))
    (tmp_path / "reports" / "live.json").write_text(_j.dumps({"asof": "2026-10-23 23:06", "items": [
        {"key": "SPX", "last": 7628.3, "date": "2026-10-23"}, {"key": "NASDAQ", "last": 25994.0, "date": "2026-10-23"}]}))
    (tmp_path / "reports" / "heatmap_US.json").write_text(_j.dumps({"rows": [{"s": "NVDA", "close": 211.95, "date": "2026-10-23"}]}))
    monkeypatch.setattr(H, "ROOT", tmp_path)
    u = _US_LAST()
    assert u["date"] == "2026-10-23" and u["spx"] == 7628.3 and u["iv"] == 0.19          # VIX 는 live 에 없으면 일봉 값
    monkeypatch.setattr(H, "bars", lambda m, c: [{"t": "2026-10-22", "c": 212.21}])
    assert _US_STOCK_LAST("NVDA") == ("2026-10-23", 211.95)


def test_spread_payoff_bounds():
    import hf_spread as SP
    assert SP.payoff_range("put", 900, 850) == (0.0, 50.0)          # 베어 풋 데빗
    assert SP.payoff_range("put", 850, 900) == (-50.0, 0.0)         # 불 풋 크레딧
    assert SP.payoff_range("call", 900, 950) == (0.0, 50.0)
    with pytest.raises(SystemExit):
        SP.plan(H.bs, "put", 900, 900, 900, 0.1, 0.4)


def test_spread_debit_and_credit_sizing():
    b = _b()
    deb = H.add(b, _a(kind="spread", und="K200", right="put", strike=900.0, strike2=850.0, expiry="2026-11-12",
                      stop=None, t1=None, p_win=0.6))
    sp = deb["spread"]
    assert sp["type"] == "데빗" and deb["r_unit"] == pytest.approx(sp["max_loss"], rel=1e-4)
    assert deb["risk"] == pytest.approx(H.CONV["mid"]) and deb["contracts"] > 0                     # 최대손실 = 리스크 예산
    with pytest.raises(SystemExit, match="기대값"):                                                  # 크레딧 = 손익비 낮음 → 승률 80% 로는 안 들어감
        H.add(b, _a(kind="spread", und="K200", right="put", strike=800.0, strike2=860.0, expiry="2026-11-12",
                    stop=None, t1=None, p_win=0.8))
    cr = H.add(b, _a(kind="spread", und="K200", right="put", strike=800.0, strike2=860.0, expiry="2026-11-12",
                     stop=None, t1=None, p_win=0.95))
    assert cr["spread"]["type"] == "크레딧" and cr["entry"] < 0 and cr["r_unit"] > 0
    assert H.r_of(cr, cr["entry"]) < 0                                                              # 진입 즉시 비용만큼 음수
    with pytest.raises(SystemExit, match="스프레드"):
        H.add(b, _a(kind="spread", side="숏", und="K200", right="put", strike=900.0, strike2=850.0, expiry="2026-11-12"))


def test_spread_take_profit_and_expiry():
    b = _b()
    p = H.add(b, _a(kind="spread", und="K200", right="put", strike=900.0, strike2=850.0, expiry="2026-11-12",
                    stop=None, t1=None, p_win=0.6))
    D["k200"] = 820.0                                             # 크게 하락 → 스프레드 가치 ↑ → 50% 익절
    try:
        out = H.mark(b)
    finally:
        D["k200"] = 900.0
    assert out and out[0]["exit_why"].startswith("최대이익 50%") and out[0]["r"] > 0
    b2 = _b()
    H.add(b2, _a(kind="spread", und="K200", right="call", strike=920.0, strike2=960.0, expiry="2026-10-30",
                 stop=None, t1=None, p_win=0.6))
    D["date"] = "2026-10-30"
    try:
        out = H.mark(b2)
    finally:
        D["date"] = "2026-10-21"
    assert out and out[0]["exit_why"].startswith("만기") and out[0]["r"] < -0.9                      # 900 < 920 → 0 정산 ≈ −1R


# ── 북 독립성(10/24 결재 appr-hf-independence) ──
AB_LONG = [{"book": "알파북", "code": "033780", "name": "KT&G", "dir": 1}, {"book": "PB🔥", "code": "102110", "name": "TIGER 200", "dir": 1}]


def _stock_env(monkeypatch):
    bars = [{"t": f"2026-10-{i + 1:02d}", "o": 100, "h": 101, "l": 99, "c": 100.0, "v": 1e9} for i in range(20)]
    monkeypatch.setattr(H, "bars", lambda market, code: bars)
    monkeypatch.setattr(H, "live_kr_stock", lambda code: None)   # live.json 실값이 섞이면 가격 가정이 깨진다


def test_indep_same_code_rejected_and_logged(monkeypatch):
    _stock_env(monkeypatch)
    monkeypatch.setattr(H, "other_books", lambda market, today: AB_LONG)
    b = _b()
    with pytest.raises(H.IndepReject, match="①같은 종목"):
        H.add(b, _a(kind="stock", code="033780", stop=80.0, t1=130.0, indep="data/deriv/daily.csv 외국인 선물 순매수"))
    r = b["rejected"][-1]
    assert r["rule"] == "①같은 종목" and r["code"] == "033780" and not b["open"]
    p = H.add(b, _a(kind="stock", side="숏", code="033780", stop=120.0, t1=70.0))   # 반대 방향은 겹침 아님 — ③ 없이 통과
    assert not p.get("consensus")


def test_indep_net_beta_cap(monkeypatch):
    monkeypatch.setattr(H, "other_books", lambda market, today: AB_LONG)
    b = _b()
    with pytest.raises(H.IndepReject, match="②순베타"):       # K200F 롱 손절 2.2% → 비중 ≈11% → 순베타 손실 1.1% ≫ 리스크 0.25%의 절반
        H.add(b, _a(indep="data/deriv/daily.csv 베이시스"))
    assert b["rejected"][-1]["rule"] == "②순베타"
    _stock_env(monkeypatch)                                     # 종목 롱 손절 −25%: 순베타 손실 = β1×w×10% = 리스크 × 0.4 ≤ 절반
    p = H.add(b, _a(kind="stock", code="000001", stop=75.0, t1=140.0, indep="data/deriv/daily.csv 외국인 선물 순매수"))
    assert p["consensus"] and p["independence"]["beta_loss"] <= p["independence"]["half_risk"]


def test_indep_requires_unshared_data(monkeypatch):
    _stock_env(monkeypatch)
    monkeypatch.setattr(H, "other_books", lambda market, today: AB_LONG)
    for bad in (None, "", "reports/committee.json lenses", "느낌상 좋다", "reports/없는파일.json"):
        b = _b()
        with pytest.raises(H.IndepReject, match="③독립 데이터"):
            H.add(b, _a(kind="stock", code="000001", stop=75.0, t1=140.0, indep=bad))
        assert b["rejected"][-1]["rule"] == "③독립 데이터"


def test_indep_hedge_leg_and_other_market_exempt(monkeypatch):
    b = _b()
    par = H.add(b, _a(kind="fut", side="숏", stop=920.0, t1=860.0))          # 숏은 롱 두 북과 반대 — 겹침 아님
    monkeypatch.setattr(H, "other_books", lambda market, today: AB_LONG if market == "KR" else [])
    hg = H.add(b, _a(kind="fut", stop=880.0, t1=940.0, hedge_of=par["id"]))  # 헤지 다리 면제
    us = H.add(b, _a(kind="es", stop=7550.0, t1=8000.0))                    # 미장엔 다른 북 노출 없음
    assert not hg.get("consensus") and not us.get("consensus")


def test_direction_of_options_and_spreads():
    assert H.direction({"kind": "put", "side": "롱"}) == -1 and H.direction({"kind": "spx_call", "side": "롱"}) == 1
    assert H.direction({"kind": "spread", "side": "롱", "k_long": 900, "k_short": 950}) == 1     # 불 콜(데빗)
    assert H.direction({"kind": "spread", "side": "롱", "k_long": 900, "k_short": 850}) == -1    # 베어 풋(데빗)


def test_other_books_reads_alphabook_and_pb(tmp_path, monkeypatch):
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "alphabook.json").write_text(json.dumps({"books": {"KR": {"positions": [{"code": "033780", "name": "KT&G"}],
                                                                                  "pending": [{"code": "012030", "name": "DB"}]}}}))
    (tmp_path / "reports" / "decisions.json").write_text(json.dumps({"items": [
        {"kind": "entry", "date": "2026-10-24", "picks": {"PB🔥": {"ticker": "252670", "name": "KODEX 200선물인버스2X"}, "PB": {"cash": True}}},
        {"kind": "entry", "date": "2026-10-23", "picks": {"PB🔥": {"ticker": "102110", "name": "TIGER 200"}}}]}, ensure_ascii=False))
    monkeypatch.setattr(H, "ROOT", tmp_path)
    o = OTHER_BOOKS("KR", "2026-10-24")
    assert {(x["book"], x["code"], x["dir"]) for x in o} == {("알파북", "033780", 1), ("알파북", "012030", 1), ("PB🔥", "252670", -1)}


# ── 페어 진입(10/24 겸이 "롱이랑 헤지를 한 번에", req-hf-a1a96e88) ──
def test_pair_auto_passes_net_beta_and_links(monkeypatch):
    monkeypatch.setattr(H, "other_books", lambda market, today: AB_LONG)
    b = _b()
    with pytest.raises(H.IndepReject, match="--beta-hedge auto"):          # 안내 문구
        H.add(b, _a(indep="data/deriv/daily.csv 베이시스"))
    p = H.add(b, _a(indep="data/deriv/daily.csv 베이시스", beta_hedge="auto"))
    h = b["open"][-1]
    assert [x["id"] for x in b["open"]] == [p["id"], h["id"]] and p["pair_hedge"] == h["id"]
    assert h["pair"] and h["hedge_of"] == [p["id"]] and h["kind"] == "fut" and h["side"] == "숏"
    assert p["independence"]["beta_loss"] <= p["independence"]["half_risk"] + 1e-9
    assert H.open_risk(b) == pytest.approx(p["risk"])                     # 헤지 다리 = 순 리스크 0
    # auto = 최소 크기: 한도 바로 위로만(헤지 명목 ≤ 부모 비중)
    assert h["weight"] <= p["weight"] and h["weight"] * H.INDEP_SHOCK >= p["weight"] * H.INDEP_SHOCK - p["risk"] * H.INDEP_FRAC - 1e-6


def test_pair_ratio_and_us_es(monkeypatch):
    b = _b()
    p = H.add(b, _a(beta_hedge="0.5"))
    assert b["open"][-1]["weight"] == pytest.approx(0.5 * p["weight"], abs=1e-5)
    u = H.add(b, _a(kind="us_stock", code="LRCX", stop=200.0, t1=300.0, beta_hedge="1"))
    assert b["open"][-1]["kind"] == "es" and b["open"][-1]["hedge_of"] == [u["id"]] and b["open"][-1]["market"] == "US"


def test_pair_atomic(monkeypatch):
    monkeypatch.setattr(H, "other_books", lambda market, today: AB_LONG)
    b = _b()
    with pytest.raises(H.IndepReject, match="③독립 데이터"):              # 헤지는 맞췄지만 ③ 실패 → 둘 다 미기록
        H.add(b, _a(beta_hedge="auto", indep=None))
    assert b["open"] == []
    with pytest.raises(SystemExit, match="비율"):
        H.add(b, _a(beta_hedge="2"))
    with pytest.raises(SystemExit, match="기대값"):                         # 부모 검증 실패 → 헤지도 없음
        H.add(b, _a(beta_hedge="1", p_win=0.2))
    assert b["open"] == []


def test_pair_closes_with_parent():
    b = _b()
    p = H.add(b, _a(beta_hedge="1"))
    D["fut"] = 870.0                                                        # 부모 손절 880 아래
    try:
        out = H.mark(b)
    finally:
        D["fut"] = 900.0
    assert b["open"] == [] and {x["id"] for x in out} == {p["id"], p["pair_hedge"]}
    hc = next(x for x in b["closed"] if x.get("pair"))
    assert hc["exit_why"].startswith("페어 헤지") and hc["r"] > 0           # 숏 헤지는 하락에 이익
    b2 = _b()
    H.add(b2, _a(beta_hedge="1"))
    H.mark(b2)                                                              # 부모 살아 있으면 헤지도 유지(자체 손절 없음)
    assert len(b2["open"]) == 2
    b2["open"] = [x for x in b2["open"] if x.get("pair")]                    # close-now 와 같은 경로
    assert len(H.close_orphan_pairs(b2)) == 1 and b2["open"] == []
    b3 = _b()
    H.add(b3, _a(beta_hedge="1"))
    assert any("페어 헤지 — 부모 청산 때 같이" in x for x in H.show(b3))


def test_close_part_halves_size():
    b = _b()
    p = H.add(b, _a(kind="es", side="숏", stop=7850.0, t1=7450.0))
    w, r = p["weight"], p["risk"]
    q = H.close_part(b, p["id"], 0.5, 7650.0, "2026-10-21", "FOMC 전 절반")
    assert q["weight"] == pytest.approx(w / 2, rel=1e-4) and b["open"][0]["risk"] == pytest.approx(r / 2, rel=1e-4)
    assert b["closed"][-1]["id"] == p["id"] + "-p1" and b["closed"][-1]["r"] > 0       # 숏 7700 → 7650 이익
    with pytest.raises(SystemExit):
        H.close_part(b, p["id"], 1.0, 7650.0, "2026-10-21", "x")
