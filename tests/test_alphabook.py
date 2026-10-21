"""알파북(screener/alphabook.py) — 진입 게이트·스탑 다음 봉 시가 청산·분할·시간 손절·NAV·운용회의 4줄·말투 금지어."""
import json
from datetime import datetime

from screener import alphabook as A


def _plan(code="X", c=100.0, stop=95.0, verdict="채택(모의)", why=None, conv=0.75, hold_t2=True):
    return {"code": code, "name": "테스트", "market": "KR", "verdict": verdict, "why_not": why or [],
            "entry": {"lo": c - 1, "hi": c + 1}, "stop": {"px": stop, "pct": (c - stop) / c},
            "t1": {"px": c + 1.5 * (c - stop)}, "t2": {"px": c + 3 * (c - stop), "hold": hold_t2},
            "conviction": {"mult": conv}, "time_stop": {"days": 20}, "line": "계획"}


SRC = {"key": "B1", "pass": True, "grade": "B", "ev_r": 0.083, "base_ev_r": -0.015}
SCALE = A.regime_scale({"state": "정상", "mult": 1.0})


def _book_with(plan, after="2026-10-01"):
    b = A.new_book("KR", "2026-10-01")
    sz = A.size(plan, 1.0, 0.0, SCALE)
    b["pending"].append(A.order(plan, SRC, sz, "2026-10-01", after))
    return b, sz


def test_gate_requires_plan_and_edge():
    assert A.gate(None, SRC) == ["trade plan 없음 — 진입 금지"]
    assert A.gate(_plan(), SRC) == []
    assert any("기대값" in w for w in A.gate(_plan(), {**SRC, "ev_r": -0.02}))      # 기대값 ≤ 기준선
    assert any("미통과" in w for w in A.gate(_plan(), {**SRC, "pass": False, "grade": "F"}))
    assert A.gate(_plan(verdict="보류", why=["손절폭 16.7% > 15%"]), SRC) == ["손절폭 16.7% > 15%"]


def test_regime_scale_never_zero_except_event_day():
    s = A.regime_scale({"state": "축소", "mult": 0.1})
    assert s["risk_mult"] == A.FLOOR and s["new_ok"]
    assert A.regime_scale({"state": "보류", "mult": 0.0})["new_ok"] is False
    sz = A.size(_plan(), 1.0, 0.0, A.regime_scale({"state": "축소", "mult": 0.5}))
    assert abs(sz["risk_pct"] - A.RISK_BASE * 0.75 * 0.5) < 1e-5 and sz["weight"] <= A.WEIGHT_CAP


def test_stop_touch_exits_next_bar_open_no_exception():
    b, _ = _book_with(_plan())
    A.step_day(b, "2026-10-02", {"X": {"o": 100.0, "h": 101, "l": 94.0, "c": 96}}, 1000)   # 진입 + 같은 봉 스탑 닿음
    assert b["positions"][0]["exit_next"]
    A.step_day(b, "2026-10-05", {"X": {"o": 97.0, "h": 120, "l": 96, "c": 119}}, 1000)    # 다음 봉 시가 청산(반등해도 예외 없음)
    assert not b["positions"] and b["closed"][0]["why"].startswith("스탑")
    sell = [f for f in b["fills"] if f["kind"] == "sell"][0]
    assert sell["px"] == 97.0
    assert b["closed"][0]["r"] < -0.5


def test_pending_outside_zone_expires_and_no_same_day_fill():
    b, _ = _book_with(_plan(), after="2026-10-02")
    A.step_day(b, "2026-10-02", {"X": {"o": 100.0, "h": 101, "l": 99, "c": 100}}, 1000)   # after 당일 = 체결 안 함
    assert b["pending"] and not b["positions"]
    A.step_day(b, "2026-10-05", {"X": {"o": 105.0, "h": 106, "l": 104, "c": 105}}, 1000)  # 구간 밖 → 만료
    assert not b["pending"] and not b["positions"] and b["fills"][-1]["kind"] == "expire"


def test_scale_out_breakeven_and_time_stop():
    b, _ = _book_with(_plan())
    A.step_day(b, "2026-10-02", {"X": {"o": 100.0, "h": 101, "l": 99, "c": 100}}, 1000)
    A.step_day(b, "2026-10-05", {"X": {"o": 101.0, "h": 108, "l": 100.5, "c": 107}}, 1000)  # 1차(107.5) 50%
    p = b["positions"][0]
    assert p["t1_done"] and p["stop"] == p["entry"] and abs(p["qty"] / p["qty0"] - 0.5) < 1e-9
    for i in range(18):
        A.step_day(b, f"2026-10-{6+i:02d}", {"X": {"o": 107.0, "h": 108, "l": 106, "c": 107}}, 1000)
    assert not b["positions"] and b["closed"][0]["why"] == "시간 손절"
    assert b["closed"][0]["r"] > 0


def test_conviction_c_exits_all_at_t1():
    b, _ = _book_with(_plan(hold_t2=False))
    A.step_day(b, "2026-10-02", {"X": {"o": 100.0, "h": 101, "l": 99, "c": 100}}, 1000)
    A.step_day(b, "2026-10-05", {"X": {"o": 101.0, "h": 108, "l": 100.5, "c": 107}}, 1000)
    assert not b["positions"] and b["closed"][0]["why"] == "1차 목표 전량"


def test_nav_excess_and_ir_threshold():
    b = A.new_book("US", "2026-10-01")
    A.step_day(b, "2026-10-01", {}, 100.0)
    A.step_day(b, "2026-10-02", {}, 101.0)
    s = A.stats(b)
    assert s["nav"] == 1.0 and abs(s["today_excess"] + 0.01) < 1e-9 and s["ir"] is None and "20" in s["ir_note"]


def test_conservative_cost_exceeds_tradeplan_cost():
    from screener import tradeplan
    for m in ("KR", "US"):
        assert A.side_cost(m) * 2 > tradeplan.COST[m]


def test_scan_52w():
    bars = [{"t": f"d{i}", "o": 10000, "h": 10000 + i, "l": 9900, "c": 10000 + i, "v": 1e6} for i in range(260)]
    hits = A.scan_52w({"A": bars, "B": bars[:100]}, "KR")
    assert [h["code"] for h in hits] == ["A"]


def _block(prop=None, loss=None, cio="관망", srcs=None):
    st = {"n_pos": 1, "gross": 0.12, "today_excess": 0.0031, "cum": 0.01, "bench_cum": 0.005, "excess_cum": 0.005, "ir": None, "ir_note": "표본 3일 < 20 — IR 미산출"}
    srcs = srcs if srcs is not None else {"B1": {"pass": True, "grade": "B", "test": {"ev_r": 0.083}, "base_test": {"ev_r": -0.015}}}
    return A.hf_block("KR", st, prop or [], None if prop else "B1 신호 0건 — 대기", cio, srcs, loss, SCALE)


def test_hf_block_four_lines_format():
    pr = A.order(_plan(), SRC, A.size(_plan(), 1.0, 0.0, SCALE), "2026-10-21")
    b = _block([pr])
    assert len(b["lines"]) == 4
    assert [x.split(":")[0] for x in b["lines"]] == ["알파북 현재(KR)", "이번 제안", "이견", "틀린 것"]
    assert "R" in b["lines"][1] and "크기" in b["lines"][1]
    assert b["lines"][2].startswith("이견: CIO 판정 '관망'")
    assert 1 <= len(b["tg"]) <= 2
    loss = {"code": "X", "name": "테스트", "r": -1.03, "why": "스탑 닿음 → 다음 봉 시가 청산", "exit_d": "2026-10-20"}
    b2 = _block(None, loss)
    assert b2["lines"][3].startswith("틀린 것: 테스트") and b2["say"].startswith("테스트 손절")
    b3 = _block(None, None, "지켜보기", {"A1": {"pass": False, "grade": "F", "test": {"ev_r": 0.098}, "base_test": {"ev_r": 0.12}}})
    assert "근거 없다" in b3["say"] and "+0.10R" in b3["say"]


def test_tone_banned_words():
    """터미널·텔레그램(공개 보고서)엔 욕 0 · 혐오·차별 표현 0 (10/21 겸이 지정)."""
    PROFANE = ("젠장", "개소리", "빌어먹을", "제기랄")
    loss = {"code": "X", "name": "테스트", "r": -1.0, "why": "스탑", "exit_d": "2026-10-20"}
    pr = A.order(_plan(), SRC, A.size(_plan(), 1.0, 0.0, SCALE), "2026-10-21")
    for blk in (_block([pr]), _block(None, loss), _block(), _block(None, None, "매수", {})):
        txt = json.dumps(blk, ensure_ascii=False).replace(" ", "")
        assert not any(w in txt for w in A.BANNED)
        assert not any(w in txt for w in PROFANE)
    assert A.clean("젠장 병신 같은 장") == ""
    assert A.clean("젠장, 손절 맞았어") == "젠장, 손절 맞았어"


def test_after_rule_no_backfill_of_passed_open():
    kst = A.KST
    assert A._after("KR", datetime(2026, 10, 21, 11, 35, tzinfo=kst), "2026-10-20") == "2026-10-21"
    assert A._after("KR", datetime(2026, 10, 21, 8, 50, tzinfo=kst), "2026-10-20") == "2026-10-20"
    assert A._after("US", datetime(2026, 10, 21, 14, 15, tzinfo=kst), "2026-10-20") == "2026-10-20"


def test_update_cash_when_no_passing_source(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "load_sources", lambda: {"A2": {"pass": False, "grade": "F", "test": {"ev_r": 0.098}, "base_test": {"ev_r": 0.12}}})
    monkeypatch.setattr(A, "_bars", lambda code, m: [{"t": "2026-10-19", "o": 1, "h": 1, "l": 1, "c": 100.0}, {"t": "2026-10-20", "o": 1, "h": 1, "l": 1, "c": 101.0}])
    o = {"bottom_line": {"label": "🟡 지켜보기"}}
    blk = A.update(o, "US", datetime(2026, 10, 21, 14, 15, tzinfo=A.KST), tmp_path / "ab.json")
    assert blk["state"] == "탐색 중(현금)" and not blk["proposals"]
    assert "통과 소스 0" in blk["lines"][1]
    S = json.loads((tmp_path / "ab.json").read_text(encoding="utf-8"))
    assert S["books"]["US"]["cash"] == 1.0 and S["mock"] is True


def test_disc_line(tmp_path):
    p = tmp_path / "d.json"
    assert A.disc_line(p) is None
    p.write_text(json.dumps({"open": [{"side": "롱", "name": "코스피200 선물", "entry": 893.05, "last": 910.1, "r_unit": 17.05}],
                             "closed": [{"r": -1.02}]}, ensure_ascii=False))
    ln = A.disc_line(p)
    assert "롱 코스피200 선물 893.05→910.10(+1.00R)" in ln and "청산 1건 평균 -1.02R" in ln
    assert not any(w in ln for w in ("젠장", "개소리", "빌어먹을", "제기랄"))
