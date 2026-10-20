"""10/20 dev: battle-scoreboard · signal-tracking · us-entry-ideas · light-calibration (네트워크 없음)."""
import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

from screener import battle_scoreboard as B
from screener import fwd_perf as F
from screener import idea_tracking as IT
from screener import signal_tracking as S
from screener import us_committee as U

KST = ZoneInfo("Asia/Seoul")


def bars(closes, start=1, opens=None):
    return [{"date": f"2026-09-{start + i:02d}", "open": (opens or closes)[i], "high": c, "low": c, "close": c} for i, c in enumerate(closes)]


# ── fwd_perf ──
def test_fwd_and_pending():
    b = bars([100, 101, 102, 103, 104, 110])
    assert abs(F.fwd(b, "2026-09-01", 5)["ret"] - 0.10) < 1e-9
    assert F.fwd(b, "2026-09-02", 5) is None            # 기간 미경과 = None (0 아님)
    assert F.fwd(b, "2026-08-31", 1) is None            # 신호일 이전 봉 없음


def test_market_median_and_excess():
    uni = {f"c{i}": bars([100, 100 + i]) for i in range(31)}   # 수익 0%..30% → 중앙 15%
    med = F.MarketMedian(uni)
    assert abs(med("2026-09-01", "2026-09-02") - 0.15) < 1e-9
    fx = F.fwd_excess(bars([100, 120]), "2026-09-01", med, horizons=(1, 5))
    assert abs(fx["h1"]["ex"] - 0.05) < 1e-6 and fx["h5"] is None
    assert F.MarketMedian({"a": bars([1, 2])})("2026-09-01", "2026-09-02") is None   # 표본 부족 → None


def test_summarize_counts_only_scored():
    rows = [{"fwd": {"h5": {"ex": 0.02}}}, {"fwd": {"h5": {"ex": -0.01}}}, {"fwd": {"h5": None}}]
    s = F.summarize(rows, horizons=(5, 20))
    assert s["h5"]["n"] == 2 and s["h5"]["hit"] == 0.5 and s["h20"] is None


# ── battle_scoreboard ──
def _it(picks, result=None, mk="KR", d="2026-09-01"):
    return {"id": "x", "date": d, "market": mk, "picks": picks, **({"result": result} if result else {})}


def test_battle_pending_and_missing_price_are_unrated():
    bench = {"KR": bars([100, 101, 102])}
    r = B._row(_it({"나": {"pending": True}}), "나", {"pending": True}, {}, bench, "2026-09-10")
    assert r["status"] == "미제출" and r["ret"] is None
    p = {"ticker": "999999", "name": "없는 종목", "entry": "close", "exit": "next_open", "notional": 1000000}
    r = B._row(_it({"나": p}), "나", p, {}, bench, "2026-09-10")
    assert r["status"] == "미평가" and r["ret"] is None and "notional" not in r


def test_battle_open_mark_and_bench_same_window():
    p = {"ticker": "A", "entry": "close", "exit": "d5_close"}
    px = {"A": bars([100, 110, 121])}
    bench = {"KR": bars([100, 100, 105])}
    r = B._row(_it({"PB": p}), "PB", p, px, bench, "2026-09-10")
    assert r["status"] == "보유 중" and abs(r["ret"] - (0.21 - B.COST)) < 1e-4
    assert abs(r["bench"] - (0.05 - B.COST)) < 1e-4 and abs(r["ex"] - 0.16) < 1e-4


def test_battle_confirmed_uses_exit_open_for_bench():
    p = {"ticker": "A", "entry": "close", "exit": "next_open"}
    res = {"PB": {"ret": 0.02, "detail": "2026-09-01 종가 100 → 2026-09-02 시가 102"}, "winner": "PB"}
    bench = {"KR": bars([100, 110], opens=[100, 101])}
    r = B._row(_it({"PB": p}, res), "PB", p, {}, bench, "2026-09-10")
    assert r["status"] == "확정" and r["win"] and abs(r["bench"] - (0.01 - B.COST)) < 1e-6


def test_battle_tally_simple_sum_and_hit():
    rows = [{"status": "확정", "ret": 0.1, "ticker": "A", "win": True, "ex": 0.05},
            {"status": "확정", "ret": -0.05, "ticker": "B", "win": False, "ex": None},
            {"status": "확정", "ret": 0.0, "ticker": None, "win": False},
            {"status": "보유 중", "ret": 0.5, "ticker": "C"}]
    t = B._tally(rows)
    assert t["n"] == 3 and t["win"] == 1 and t["trades"] == 2 and t["hit"] == 0.5
    assert abs(t["cum_ret"] - 0.05) < 1e-9 and t["open"] == 1 and t["n_ex"] == 1


def test_scoreboard_file_has_no_amounts():
    from pathlib import Path
    p = Path(__file__).resolve().parents[1] / "reports" / "battle_scoreboard.json"
    if p.exists():
        t = p.read_text(encoding="utf-8")
        assert '"notional"' not in t and '"pnl"' not in t


# ── signal_tracking ──
def test_signal_extract_and_repeat_rule():
    acc = {"asof": "2026-09-01", "status": "ok", "top": {"accum": [{"code": "000001", "name": "a"}], "distrib": [{"code": "000002"}]}}
    sig = S.extract("accum", acc)
    assert {(x["tag"], x["side"]) for x in sig} == {("accum", 1), ("distrib", -1)}
    book = {}
    assert S.merge(book, sig, "live") == 2
    later = json.loads(json.dumps(acc).replace("2026-09-01", "2026-09-10"))
    assert S.merge(book, S.extract("accum", later), "live") == 0      # 20일 안 재등장 = 계속
    much = json.loads(json.dumps(acc).replace("2026-09-01", "2026-10-15"))
    assert S.merge(book, S.extract("accum", much), "live") == 2
    assert S.extract("accum", {"status": "fail"}) == []


def test_signal_bear_flip_in_summary():
    evs = [{"side": -1, "fwd": {"h5": {"ex": -0.03}}}, {"side": 1, "fwd": {"h5": {"ex": 0.01}}}]
    s = S._summ(evs)
    assert s["h5"]["hit"] == 1.0 and abs(s["h5"]["avg_ex"] - 0.02) < 1e-9


def test_signal_sources_listed_with_untracked_reasons():
    assert all(s.get("why") for s in S.SOURCES if not s["tracked"])
    assert any(s["src"] == "ideas_top" and not s["tracked"] for s in S.SOURCES)   # idea_tracking 과 중복 안 함


# ── 신호등 보정 ──
def test_high_event_rule():
    assert U.high_event({"type": "매크로", "name": "FOMC 금리 결정"})
    assert U.high_event({"type": "매크로", "name": "미 CPI(9월)"}) and U.high_event({"type": "매크로", "name": "미 고용보고서(9월)"})
    assert not U.high_event({"type": "매크로", "name": "미 주택착공·건축허가"})
    assert not U.high_event({"type": "실적", "name": "Netflix 실적", "ticker": "NFLX"}, {"AAPL"})
    assert U.high_event({"type": "실적", "name": "Apple 실적", "ticker": "AAPL"}, {"AAPL"})


def test_light_yellow_half_band():
    clock = [{"kind": "가격", "what": "a", "dist": -0.02}, {"kind": "이벤트", "what": "주택착공", "hi": False}]
    near, hi = U.light_yellow(clock, 0.03)
    assert near == [] and hi == []                          # 예전 규칙이면 🟡(범위 3% 안 + 이벤트)
    near, _ = U.light_yellow([{"kind": "가격", "what": "b", "dist": 0.01}], 0.03)
    assert near == ["b"]


def test_us_bottom_line_green_on_minor_event():
    k = {"vix": 20, "last": 100.0, "low20": 90.0, "hi5": 110.0, "hi52": 120.0}
    cal = [{"date": "2026-10-20", "type": "매크로", "name": "미 주택착공", "imp": 3}]
    bl = U.bottom_line_us({"scenarios": [{"name": "기본 — x", "prob": .5}]}, k, None, cal, date(2026, 10, 20),
                          {"red": "r", "yellow": "y", "green": "g"}, "f")
    assert bl["light"] == "green" and bl["label"] == "g"
    cal[0]["name"] = "FOMC 금리 결정"
    bl = U.bottom_line_us({"scenarios": [{"name": "기본 — x", "prob": .5}]}, k, None, cal, date(2026, 10, 20),
                          {"red": "r", "yellow": "y", "green": "g"}, "f")
    assert bl["light"] == "yellow"


# ── 미장 진입 후보 ──
def _rb(c):
    return {"close": 100.0, "atr_pct": 0.02, "stop": 95.0, "stop_pct": 0.05, "target": 110.0, "skip": False}


def test_ideas_top_us_format_and_gate():
    peers = [{"s": t, "n": t + " Inc", "g": "IT", "drv": d} for t, d in (("AAA", 0.5), ("BBB", 0.45), ("CCC", -0.5))]
    acc = {"status": "ok", "grades": {"S3": "F"}, "hits": [{"symbol": "BBB", "signals": ["S3"], "date": "2026-10-19"}]}
    ch = {"AAA": [{"t": "2026-10-19", "c": 100, "s50": 90}], "BBB": [{"t": "2026-10-19", "c": 100, "s50": 95}], "CCC": [{"t": "2026-10-19", "c": 100, "s50": 95}]}
    cal = [{"type": "실적", "ticker": "AAA", "date": "2026-10-25", "name": "AAA 실적"}]
    o = U.ideas_top_us({}, peers, acc, cal, date(2026, 10, 20), _rb, lambda c: ch.get(c, []), "fail", "레짐 하락장")
    it = {x["s"]: x for x in o["items"] + o["candidates"]}
    assert set(it) == {"AAA", "BBB"} and "CCC" not in it
    for k in ("entry", "entry_max", "stop", "target", "payoff", "status", "kill", "sources", "ref"):
        assert k in it["AAA"]
    assert it["AAA"]["status"] == "대기 — 진입 게이트 불통과" and it["BBB"]["status"] == "대기 — 촉매 없음"
    ch["AAA"][0]["s50"] = 110   # 50일선 아래 → 동의 이익 신호 − 추세 반대 = 0 → 제외
    o3 = U.ideas_top_us({}, peers, acc, cal, date(2026, 10, 20), _rb, lambda c: ch.get(c, []), "pass", "")
    assert "AAA" not in {x["s"] for x in o3["items"] + o3["candidates"]}
    ch["AAA"][0]["s50"] = 90
    o2 = U.ideas_top_us({}, peers, acc, cal, date(2026, 10, 20), _rb, lambda c: ch.get(c, []), "pass", "")
    assert {x["s"]: x for x in o2["items"]}["AAA"]["status"] == "실행 후보"
    assert any(s["k"] == "us_accum" and s["w"] == 0 for s in it["BBB"]["sources"])   # F 등급 = 가중 0, 근거로는 표시


# ── idea_tracking US 편입 ──
def test_idea_tracking_us_capture_and_no_lookahead():
    now = datetime(2026, 10, 20, 22, 52, tzinfo=KST)
    m = {"date": "2026-10-20", "asof": "2026-10-20 22:52", "ideas_top": {"items": [
        {"s": "AAA", "n": "A", "side": "롱", "status": "실행 후보", "entry": 100, "entry_max": 102, "stop": 90, "target": 120, "ref": "2026-10-19"}]}}
    book = {"rows": [{"id": "2026-10-20:AAA", "date": "2026-10-20", "ticker": "AAA", "original": {}, "state": {}}]}   # KR 같은 티커
    IT.capture(book, m, now, "US")
    us = [r for r in book["rows"] if r.get("market") == "US"]
    assert len(us) == 1 and us[0]["id"] == "US:2026-10-20:AAA"
    bs = [dict(date="2026-10-20", open=101, high=125, low=99, close=110), dict(date="2026-10-21", open=101, high=105, low=99, close=103)]
    st = IT.evaluate(us[0], bs)
    assert st["entry_date"] == "2026-10-21"                  # 22:52 제안 → 이미 열린 10/20 세션은 건너뜀
    us[0]["proposed_at"] = "2026-10-21 06:55"
    assert IT.evaluate(us[0], bs)["entry_date"] == "2026-10-21"
