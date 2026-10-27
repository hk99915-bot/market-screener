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


def test_chase_s4_excluded():
    base = [{"t": f"d{i}", "c": 100.0, "v": 1000} for i in range(25)]
    assert not A.chase_s4(base)
    assert A.chase_s4(base + [{"t": "x", "c": 110.0, "v": 3000}])           # 3배 + 20일 최고 종가
    assert not A.chase_s4(base + [{"t": "x", "c": 110.0, "v": 2900}])       # 거래량 미달
    assert not A.chase_s4(base + [{"t": "x", "c": 99.0, "v": 5000}])        # 신고가 아님


def _block(prop=None, loss=None, cio="관망", srcs=None):
    st = {"n_pos": 1, "gross": 0.12, "today_excess": 0.0031, "cum": 0.01, "bench_cum": 0.005, "excess_cum": 0.005, "ir": None, "ir_note": "표본 3일 < 20 — IR 미산출"}
    srcs = srcs if srcs is not None else {"B1": {"pass": True, "grade": "B", "test": {"ev_r": 0.083}, "base_test": {"ev_r": -0.015}}}
    return A.hf_block("KR", st, prop or [], None if prop else "B1 신호 0건 — 대기", cio, srcs, loss, SCALE)


def test_hf_block_four_lines_format():
    pr = A.order(_plan(), SRC, A.size(_plan(), 1.0, 0.0, SCALE), "2026-10-21")
    b = _block([pr])
    assert len(b["lines"]) >= 4                                  # 4줄 형식 + 진입 근거 펼침(10/24)
    assert [x.split(":")[0] for x in b["lines"][:4]] == ["알파북 현재(KR)", "이번 제안", "이견", "틀린 것"]
    assert any(x.startswith("근거 펀더") for x in b["lines"][4:])
    assert "R" in b["lines"][1] and "크기" in b["lines"][1]
    assert b["lines"][2].startswith("이견: CIO 판정 '관망'")
    assert 2 <= len(b["tg"]) <= 5 and "52주 고점 밀어붙이는" not in b["say"]
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
    p.write_text(json.dumps({"open": [{"side": "롱", "kind": "fut", "name": "코스피200 선물", "entry": 893.05, "last": 910.1, "r_unit": 17.05, "weight": 0.065},
                                      {"side": "롱", "kind": "put", "name": "코스피200 풋 847.5 (2026-11-12)", "entry": 20.84, "last": 10.42, "r_unit": 20.84}],
                             "closed": [{"r": -1.02}]}, ensure_ascii=False))
    ln = A.disc_line(p)
    assert ln.strip().startswith(A.DISC_PREFIX)
    assert "지수 선물 상승 쪽 +1.00R(+1.9%)" in ln and "지수 하락 보험 하락 쪽" in ln and "청산 1건 평균 -1.02R" in ln
    # PB 문구 규칙: 계약 수·행사가·주문형/명령형·욕 없음
    for w in A.DISC_BANNED + ("847.5", "59", "젠장", "개소리", "빌어먹을", "제기랄"):
        assert w not in ln, w


def test_fill_resizes_down_to_order_risk():
    """체결가가 기준가보다 위(스탑에서 멀어짐)면 비중을 줄여 실현 리스크 ≤ 주문 리스크. 아래 체결이어도 상향 안 함 (10/23 KT&G 0.218% vs 0.187%)."""
    b, sz = _book_with(_plan(stop=95.0))
    A.step_day(b, "2026-10-02", {"X": {"o": 101.0, "h": 102, "l": 100, "c": 101}}, 1000)
    p = b["positions"][0]
    real = p["qty"] * (p["entry"] - p["stop"])
    assert real <= sz["risk_pct"] + 1e-9 and "체결가 재조정" in b["fills"][-1]["why"]
    b2, sz2 = _book_with(_plan(stop=95.0))
    A.step_day(b2, "2026-10-02", {"X": {"o": 99.0, "h": 100, "l": 98, "c": 99}}, 1000)
    p2 = b2["positions"][0]
    assert abs(p2["qty"] * 99.0 - sz2["weight"]) < 1e-9 and "재조정" not in b2["fills"][-1]["why"]



# ── 진입 근거 문장(10/24 겸이 "왜 진입하는지로" · "펀더 내러 센티 다 드러나게") ──
def _ew_root(tmp_path, det=None, accum=None, research=None, trend=None):
    import json as _json
    (tmp_path / "reports" / "detail" / "KR").mkdir(parents=True)
    (tmp_path / "docs" / "valuation_notes").mkdir(parents=True)
    if det is not None:
        (tmp_path / "reports" / "detail" / "KR" / "000001.json").write_text(_json.dumps(det, ensure_ascii=False))
    for nm, v in (("accum.json", accum), ("research.json", research), ("trend_discovery_KR.json", trend)):
        if v is not None:
            (tmp_path / "reports" / nm).write_text(_json.dumps(v, ensure_ascii=False))
    return tmp_path


def _ew_order():
    return {"code": "000001", "name": "테스트", "src": "B1", "lo": 99.0, "hi": 101.0, "stop": 86.2, "t1": 120.7, "t2": 141.4, "weight": 0.009,
            "risk_pct": 0.00125, "line": "진입 99~101 · 손절 86(−13.8%) · 1차 121(1.5R)", "ev_r": 0.0828, "base_ev_r": -0.0149, "prox": 0.95}


def test_entry_why_no_data_is_unverified(tmp_path):
    from datetime import date
    from screener import entry_why as EW
    w = EW.build(_ew_order(), "KR", grade="B", today=date(2026, 10, 24), root=_ew_root(tmp_path))
    assert all(a["v"] == "미확인" and a["score"] is None for a in w["axes"].values())
    assert "펀더 미확인" in w["tg"][2] and "내러 미확인" in w["tg"][2] and w["tg"][3] == "센티 미확인"
    assert not w["weak"] and "hi52" not in w["tech"]                 # 연구 파일 없으면 hi52 문구도 없음(지어내지 않음)
    assert "E[R] +0.083R" in w["risk"] and "−13.8%" in w["risk"] and "리스크 0.125%" in w["risk"] and "뒤집힘" in w["risk"]
    assert all(len(x) <= 90 for x in w["tg"])


def test_entry_why_axes_from_data_and_weak_flag(tmp_path):
    from datetime import date
    from screener import entry_why as EW
    det = {"close": 100.0, "theme": "AI·소프트웨어",
           "valuation": {"group_upside": {"current": -0.25}},
           "financials": {"quarters": [{"year": 2025, "q": 2, "op": 100.0, "period": "2025Q2"}, {"year": 2026, "q": 2, "op": 70.0, "period": "2026Q2"}]},
           "flows": [{"외국인": -1.0, "기관": -2.0} for _ in range(5)]}
    root = _ew_root(tmp_path, det=det, accum={"status": "ok", "top": {"accum": [{"code": "999999", "tags": ["accum"]}]}},
                    research={"items": [{"code": "000001", "date": "2026-10-20", "tone": "부정(하향)", "broker": "가증권"}]},
                    trend={"sectors": {"rows": [{"g": "AI·소프트웨어", "lift": 0.5, "p_upper": 0.9, "bonf_pass": False}]}})
    w = EW.build(_ew_order(), "KR", grade="B", today=date(2026, 10, 24), root=root)
    ax = w["axes"]
    assert ax["펀더"]["v"] == "−" and "적정가 −25.0%" in ax["펀더"]["why"] and "−30.0%" in ax["펀더"]["why"]
    assert ax["내러"]["v"] == "−" and "부정 1" in ax["내러"]["why"] and "0.50배" in ax["내러"]["why"]
    assert ax["센티"]["v"] == "−" and "매집 신호 없음" in ax["센티"]["why"]
    assert w["weak"] and w["tg"][3].endswith("근거 약함") and "[flows]" in w["tg"][3]
    assert "2,000" not in " ".join(w["long"])                           # 입력에 없는 값 안 나옴
    assert "뒤집힘 종가 < 100(250일 고점 95%)" in w["risk"]               # 100 / 0.95 × 0.95


def test_entry_why_stock_fut_oi(tmp_path):
    from datetime import date, timedelta
    from screener import entry_why as EW
    (tmp_path / "data" / "deriv").mkdir(parents=True)
    t0 = date.today()
    rows = ["date,code,oi,clpr"] + [f"{(t0 - timedelta(days=5 - i)).isoformat()},000001,{1000 + 40 * i},{100 + i}" for i in range(6)] \
        + [f"{(t0 - timedelta(days=5 - i)).isoformat()},000002,{1000 + 40 * i},{100 - i}" for i in range(6)]
    (tmp_path / EW.STOCK_FUT_OI).write_text("\n".join(rows) + "\n", encoding="utf-8")
    up, dn = EW.stock_fut_oi("000001", tmp_path), EW.stock_fut_oi("000002", tmp_path)
    assert up["s"] == 1 and "신규 롱" in up["txt"] and dn["s"] == -1 and "신규 숏" in dn["txt"]
    assert EW.stock_fut_oi("000003", tmp_path) is None                      # 행 없음 → 재료 빠짐
    ax = EW.senti_axis(None, "000001", "KR", tmp_path)
    assert ax["v"] == "+" and "stock_fut_oi" in ax["src"]
    assert EW.stock_fut_oi("000001", tmp_path / "none") is None             # 파일 없음 → 기존 동작 그대로


def test_say_line_fallback_without_why():
    s = A.say_line({}, [_ew_order()], None, 1, None)
    assert "B1" in s and "+0.083R" in s and "밀어붙이는" not in s
