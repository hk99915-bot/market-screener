"""새로 켜진 추세 신호 (screener/detail.py _fresh·sim_signals → committee.py sim_fresh). 오너 요청 10/17."""
import json
from datetime import date, timedelta

import polars as pl
import pytest

from screener import committee, detail


def _frame(cycle: int, n: int = 250, on_last: bool = True) -> pl.DataFrame:
    """합성 가격: 매일 +0.5% 상승(롱 거래는 전부 이김). PSAR 열로 cycle 일 켜짐/cycle 일 꺼짐을 반복,
    on_last 면 마지막 거래일에 '꺼짐→켜짐'. 이평 신호는 sma20==sma50 이라 항상 0(거래 없음)."""
    c = [100 * 1.005 ** i for i in range(n)]
    ps = []   # 마지막 날(i=n-1)이 켜짐 구간의 첫날이 되도록 위상을 맞춘다
    for i in range(n):
        k = (i - (n - 1)) % (2 * cycle)          # 0 = 마지막 날과 같은 위상(켜짐 첫날)
        lit = k < cycle if on_last else k >= cycle
        ps.append(c[i] * (0.9 if lit else 1.1))
    d0 = date(2025, 10, 1)
    return pl.DataFrame({"date": [d0 + timedelta(days=i) for i in range(n)], "close": c,
                         "sma20": c, "sma50": c, "psar": ps})


def test_wilson_lower_bound_reference_values():
    assert detail.wilson_lo(7, 8) == pytest.approx(0.529, abs=0.002)     # 과제 검산값 ≈0.53
    assert detail.wilson_lo(6, 6) == pytest.approx(0.610, abs=0.002)
    assert detail.wilson_lo(5, 6) < detail.FRESH_WILSON_MIN              # 6회면 전승만 통과
    assert detail.wilson_lo(0, 0) is None


def test_fresh_detected_when_turned_on_last_day():
    sim = detail._simulate(_frame(cycle=10))
    r = sim["psar"]["long"]
    assert r["pos"] == 1 and r["entry_date"] == sim["last2"][1]          # 마지막 거래일 종가에 켜짐
    assert r["trades"] >= detail.FRESH_MIN_TRADES and r["wins"] == r["trades"]
    f = sim["fresh"]
    assert [x["strategy"] for x in f] == ["psar"]                          # 이평은 거래 0 → 제외
    x = f[0]
    assert x["wilson_lo"] > detail.FRESH_WILSON_MIN
    assert set(x) >= {"strategy", "win", "trades", "wilson_lo", "ret", "bh", "entry_date"}
    assert x["bh"] == sim["bh"]


def test_not_fresh_when_switched_off_or_old_entry():
    assert detail._simulate(_frame(cycle=10, on_last=False))["fresh"] == []      # 마지막 날 꺼짐
    sim = detail._simulate(_frame(cycle=10))
    sim["psar"]["long"]["entry_date"] = sim["from"]                               # 오래전 진입
    assert detail._fresh(sim, [sim["from"], sim["last2"][0], sim["last2"][1]]) == []


def test_excluded_when_trades_below_min():
    sim = detail._simulate(_frame(cycle=40))                 # 250일 / 80일 주기 → 청산 거래 3회
    r = sim["psar"]["long"]
    assert r["pos"] == 1 and r["trades"] < detail.FRESH_MIN_TRADES and r["wins"] == r["trades"]
    assert sim["fresh"] == []


def test_sim_signals_aggregate_sorted_and_expected_chance():
    a = detail._simulate(_frame(cycle=10))
    b = detail._simulate(_frame(cycle=40))
    stocks = {"AAA": {"name": "에이", "sim": a}, "BBB": {"name": "비", "sim": b}, "CCC": {"name": "씨", "sim": {}}}
    ss = detail.sim_signals("KR", "2026-10-16", stocks)
    assert ss["n_scanned"] == 2 and ss["n_pass"] == 1 and ss["rows"][0]["s"] == "AAA"
    n = a["psar"]["long"]["trades"]
    assert ss["n_eligible"] == 1
    assert ss["expected_chance"] == pytest.approx(round(detail._pass_prob_null(n), 2))
    assert "참고(C)" in ss["grade"] and "2종목" in ss["grade"]
    assert detail._pass_prob_null(6) == pytest.approx(1 / 64)              # 6회 전승만 통과 → 0.5^6


def _write_signals(tmp_path, n_rows=8, asof="2026-10-16"):
    rows = [{"s": f"{i:06d}", "n": f"종목{i}", "strategy": "psar", "label": "PSAR 롱", "win": 0.9, "wins": 9, "trades": 10,
             "wilson_lo": 0.6 - i * 0.01, "ret": 0.2, "bh": 0.1, "entry_date": asof} for i in range(n_rows)]
    (tmp_path / "sim_signals_KR.json").write_text(json.dumps(
        {"asof": asof, "n_scanned": 1459, "n_pass": n_rows, "n_eligible": 120, "expected_chance": 2.3,
         "grade": "참고(C) — 테스트", "rows": rows}, ensure_ascii=False), encoding="utf-8")


def test_committee_block_and_telegram_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(committee, "REPORT_DIR", tmp_path)
    monkeypatch.setattr(committee, "_kst_today", lambda: date(2026, 10, 17))
    _write_signals(tmp_path)
    b = committee._sim_fresh("KR")
    assert len(b["items"]) == committee.SIM_FRESH_TOP == 5
    assert b["items"][0]["line"] == "종목0 · PSAR 롱 · 승률 9/10(하한 60%) · 1년 전략 +20% vs 보유 +10%"
    o = {"bottom_line": {"lines": ["a"], "label": "🟡"}, "session": "장후", "date": "2026-10-17", "sim_fresh": b}
    tg = committee.telegram_text(o).split("\n")
    i = next(k for k, x in enumerate(tg) if "새로 켜진 추세 신호 · 참고 C" in x)
    items = [x for x in tg[i + 1:] if x.startswith("  · ")]
    assert 1 <= len(items) <= committee.SIM_FRESH_TG == 3
    assert not any("사라" in x or "매수하" in x for x in tg)               # 매매 지시문 없음


def test_committee_block_omitted_with_log(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(committee, "REPORT_DIR", tmp_path)
    monkeypatch.setattr(committee, "_kst_today", lambda: date(2026, 10, 17))
    caplog.set_level("INFO", logger=committee.log.name)
    assert committee._sim_fresh("KR") is None                              # 파일 없음
    _write_signals(tmp_path, asof="2026-10-01")
    assert committee._sim_fresh("KR") is None                              # 오래된 집계
    assert sum("sim_fresh 생략" in r.getMessage() for r in caplog.records) == 2
    _write_signals(tmp_path, n_rows=0)
    b = committee._sim_fresh("KR")
    assert b["items"] == [] and committee._sim_fresh_lines({"sim_fresh": b}) == []   # 통과 0건 → 텔레그램 줄 없음
