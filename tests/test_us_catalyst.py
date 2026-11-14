"""미장 촉매 판정 (screener/us_catalyst.py) — 18건 전부 '대기 — 촉매 없음' 이던 구조 결손의 회귀 검사.

배경: 촉매 정의가 calendar.json 실적 이벤트(US_EARN 30종목)뿐이라 후보 풀 626종목의 대부분이 촉매 0 으로
미진입했다(docs/desk_kb/rounds/2026-11-01/quant_signal_review.md §4). 여기서 고정하는 것:
① 실적 14일 창 경계, 중복, 지난 일정 제외 ② EPS 30일 상향 문턱, 상하향 엇갈림, 리비전 폭, 낡은 스냅숏
③ 촉매가 있어도 확신, 게이트, 추세 조건은 그대로(촉매만으로 '실행 후보'가 되지 않음) ④ 촉매는 점수, 순위를 바꾸지 않음.
"""
from datetime import date

from screener import defs
from screener import us_committee as U
from screener import us_catalyst as C

TODAY = date(2026, 11, 14)


def _eps(chg0=None, chg1=None, up=None, dn=None):
    e = {}
    if chg0 is not None:
        e["0y"] = {"cur": 1.0, "chg30": chg0, "chg90": 0.0}
    if chg1 is not None:
        e["+1y"] = {"cur": 1.1, "chg30": chg1, "chg90": 0.0}
    rec = {"eps": e}
    if up is not None:
        rec["rev_up30"], rec["rev_dn30"] = up, dn
    return rec


# ── ① 실적 예정일 창 ──
def test_earnings_window_edges_and_flags():
    cal = [{"type": "실적", "ticker": "AAA", "date": "2026-11-14", "confirmed": True},          # 오늘 = 포함
           {"type": "실적", "ticker": "AAA", "date": "2026-11-28"},                            # +14 = 포함
           {"type": "실적", "ticker": "AAA", "date": "2026-11-29"},                            # +15 = 제외
           {"type": "실적", "ticker": "AAA", "date": "2026-11-13"},                            # 지난 일정 = 제외
           {"type": "매크로", "ticker": "AAA", "date": "2026-11-18"},                          # 실적 아님 = 제외
           {"type": "실적", "ticker": "BBB", "date": "2026-11-18"}]                            # 다른 종목 = 제외
    got = C.earnings("AAA", TODAY, cal)
    assert [c["date"] for c in got] == ["2026-11-14", "2026-11-28"]
    assert got[0]["what"] == "실적 발표 (회사 확정)" and got[1]["what"] == "실적 발표 (예정일 추정)"
    assert all(c["k"] == "us_earn" and c["src"] == "calendar.json" for c in got)
    assert C.earnings("AAA", TODAY, cal, []) == C.earnings("AAA", TODAY, cal)   # 창 상수 = defs
    assert defs.US_EARN_DAYS == 14


def test_earnings_cal_json_dedupes_and_skips_past():
    cal = [{"type": "실적", "ticker": "AAA", "date": "2026-11-20"}]
    ecal = [{"sym": "AAA", "date": "2026-11-20", "past": False},        # calendar 와 같은 날 → 중복 제거
            {"sym": "AAA", "date": "2026-11-25", "past": False},        # 추가 1건
            {"sym": "AAA", "date": "2026-11-10", "past": True},         # 지난 발표일 = 제외
            {"sym": "ZZZ", "date": "2026-11-25", "past": False}]
    got = C.earnings("AAA", TODAY, cal, ecal)
    assert [c["date"] for c in got] == ["2026-11-20", "2026-11-25"]
    assert got[1]["src"] == "earnings_cal.json" and got[1]["what"] == "실적 예정 (야후 추정일)"


# ── ② EPS 추정 상향 촉매 ──
def test_eps_up_threshold_breadth_and_mixed():
    ok, _ = C.eps_up("X", _eps(0.158, 0.073, 11, 0), "2026-11-14 07:01", TODAY)
    assert ok and ok["k"] == "us_eps_up" and ok["date"] == "2026-11-14" and "+15.8%" in ok["what"]
    assert "상향 11/하향 0" in ok["what"]
    # 한 기간만 있어도 문턱을 넘으면 인정(내년 컨센 없음)
    assert C.eps_up("X", _eps(None, 0.05, None, None), "2026-11-14", TODAY)[0] is not None
    # 문턱 미달
    one, why = C.eps_up("X", _eps(0.004, 0.001, 2, 0), "2026-11-14", TODAY)
    assert one is None and "문턱" in why
    # 올해 +3.6% 인데 내년 −7.6% → 엇갈림
    one, why = C.eps_up("X", _eps(0.036, -0.076, 6, 4), "2026-11-14", TODAY)
    assert one is None and "엇갈림" in why
    # 폭은 넘지만 상향 리비전 수가 하향 이하
    one, why = C.eps_up("X", _eps(0.05, 0.05, 3, 3), "2026-11-14", TODAY)
    assert one is None and "상향 3" in why


def test_eps_up_missing_and_stale_snapshot():
    assert C.eps_up("X", None, "2026-11-14", TODAY) == (None, "EPS 추정 자료 없음")
    assert C.eps_up("X", {"eps": {}}, "2026-11-14", TODAY)[0] is None
    one, why = C.eps_up("X", _eps(0.2, 0.2, 9, 0), "2026-11-01 07:01", TODAY)   # 13일 전 = 낡음
    assert one is None and "낡음" in why
    assert C.eps_up("X", _eps(0.2, 0.2, 9, 0), "2026-11-14", TODAY)[0] is not None
    assert C.eps_up("X", _eps(0.2, 0.2, 9, 0), None, TODAY)[0] is None            # 기준일 없음
    assert defs.US_EPS_UP_30 == 0.02 and defs.US_EPS_MAX_AGE_DAYS == 7


def test_evaluate_reports_why_when_empty():
    src = {"eps": {"AAA": _eps(0.001, 0.001, 1, 1)}, "eps_asof": "2026-11-14 07:01",
           "earn_cal": [], "cal_asof": "2026-11-14 03:37"}
    r = C.evaluate("AAA", TODAY, [], src)
    assert r["catalysts"] == []
    assert r["check"].startswith("실적 14일 안 없음(캘린더 2026-11-14)") and "EPS 30일 상향" in r["check"]
    assert "us_eps 2026-11-14" in r["check"]                       # 기준일 명시(노후 판정 근거)
    src["eps"]["AAA"] = _eps(0.10, 0.10, 8, 1)
    r2 = C.evaluate("AAA", TODAY, [{"type": "실적", "ticker": "AAA", "date": "2026-11-18"}], src)
    assert [c["k"] for c in r2["catalysts"]] == ["us_eps_up", "us_earn"]   # 날짜 순(관측 11-14 → 예정 11-18)
    assert r2["catalysts"][0]["date"] == "2026-11-14" and r2["catalysts"][1]["date"] == "2026-11-18"


def test_load_sources_reads_committed_reports():
    src = C.load_sources()
    assert isinstance(src["eps"], dict) and src["eps_asof"]
    assert "HAS" in src["eps"] or "XOM" in src["eps"]      # 18건 제안 종목이 실제로 들어 있다


# ── ③④ 아이디어 편입: 자격만 열고 나머지 조건은 그대로 ──
def _rb(c):
    return {"close": 100.0, "atr_pct": 0.02, "stop": 95.0, "stop_pct": 0.05, "target": 110.0, "skip": False}


def _run(peers, ch, gate="pass", cat_src=None, cal=None, acc=None, book=None):
    return U.ideas_top_us({}, peers, acc or {"status": "ok", "grades": {}}, cal or [], TODAY, _rb,
                          lambda c: ch.get(c, []), gate, "레짐 상승", cat_src=cat_src, book=book or {})


def _peers(*codes):
    drv = {"AAA": 0.5, "BBB": 0.45, "LOW": 0.15}
    return [{"s": c, "n": c, "g": "IT", "drv": drv.get(c, 0.5)} for c in codes]


def test_eps_catalyst_unlocks_entry_but_not_score():
    ch = {c: [{"t": "2026-11-13", "c": 100, "s50": 90}] for c in ("AAA", "BBB")}
    src = {"eps": {"AAA": _eps(0.158, 0.073, 11, 0)}, "eps_asof": "2026-11-14 07:01", "earn_cal": []}
    o = _run(_peers("AAA", "BBB"), ch, cat_src=src)
    it = {x["s"]: x for x in o["items"] + o["candidates"]}
    assert it["AAA"]["status"] == "실행 후보" and it["AAA"]["catalyst"][0]["k"] == "us_eps_up"
    assert it["BBB"]["status"] == "대기 — 촉매 없음" and it["BBB"]["catalyst_note"] == "없음"
    assert "EPS 추정 자료 없음" in it["BBB"]["catalyst_check"]   # 왜 촉매가 없는지 화면에 남는다
    base = _run(_peers("AAA", "BBB"), ch, cat_src={"eps": {}, "eps_asof": None, "earn_cal": []})
    bi = {x["s"]: x for x in base["items"] + base["candidates"]}
    assert it["AAA"]["score"] == bi["AAA"]["score"]           # 촉매는 점수를 바꾸지 않는다
    assert [x["s"] for x in o["items"] + o["candidates"]] == [x["s"] for x in base["items"] + base["candidates"]]   # 순위도 그대로
    assert o["exec_zero"] is None and base["exec_zero"].startswith("오늘 US 실행 0")


def test_catalyst_does_not_bypass_conviction_gate_or_trend():
    ch = {c: [{"t": "2026-11-13", "c": 100, "s50": 90}] for c in ("AAA", "LOW")}
    acc = {"status": "ok", "grades": {"S3": "F"}, "hits": [{"symbol": "LOW", "signals": ["S3"], "date": "2026-11-12"}]}
    src = {"eps": {"AAA": _eps(0.15, 0.10, 9, 0), "LOW": _eps(0.15, 0.10, 9, 0)},
           "eps_asof": "2026-11-14 07:01", "earn_cal": []}
    o = _run(_peers("AAA", "LOW"), ch, gate="fail", cat_src=src, acc=acc)
    st = {x["s"]: x["status"] for x in o["items"] + o["candidates"]}
    assert st["AAA"] == "대기 — 진입 게이트 불통과"            # 촉매 O, 게이트 X → 대기
    assert st["LOW"] == "대기 — 확신 낮음"                     # 촉매 O, 확신 낮음 → 대기
    ch["AAA"][0]["s50"] = 110                                  # 50일선 아래면 동의 원천이 상쇄돼 후보에서 빠진다
    o2 = _run(_peers("AAA", "LOW"), ch, cat_src=src, acc=acc)
    assert "AAA" not in {x["s"] for x in o2["items"] + o2["candidates"]}


def test_earnings_calendar_catalyst_reaches_entry():
    ch = {"AAA": [{"t": "2026-11-13", "c": 100, "s50": 90}]}
    src = {"eps": {}, "eps_asof": None, "earn_cal": [{"sym": "AAA", "date": "2026-11-18", "past": False}]}
    it = {x["s"]: x for x in _run(_peers("AAA"), ch, cat_src=src)["items"]}
    assert it["AAA"]["status"] == "실행 후보" and it["AAA"]["catalyst"][0]["src"] == "earnings_cal.json"


def test_far_earnings_still_wait():
    ch = {"AAA": [{"t": "2026-11-13", "c": 100, "s50": 90}]}
    cal = [{"type": "실적", "ticker": "AAA", "date": "2026-12-20"}]
    it = {x["s"]: x for x in _run(_peers("AAA"), ch, cal=cal, cat_src={"eps": {}, "earn_cal": []})["items"]}
    assert it["AAA"]["status"] == "대기 — 촉매 없음"


# ── ⑤ 같은 종목 중복 진입 방지 (리스크, 피어리뷰 합동 점검 2026-11-14 ①) ──
def _book(code, day, status="실행 후보", market="US", entry=None):
    st = {"status": "waiting"} if entry is None else {"status": "open", "entry_date": entry}
    return {"rows": [{"id": f"{market}:{day}:{code}", "date": day, "ticker": code, "market": market,
                      "original": {"s": code, "status": status}, "state": st}]}


def test_recent_entries_counts_only_prior_executed_rows():
    from screener import idea_tracking as IT
    b = {"rows": [
        {"date": "2026-11-13", "ticker": "AAA", "market": "US", "original": {"status": "실행 후보"}, "state": {}},
        {"date": "2026-11-05", "ticker": "BBB", "market": "US", "original": {"status": "대기 — 촉매 없음"}, "state": {}},
        {"date": "2026-11-10", "ticker": "CCC", "market": "US", "original": {"status": "대기 — 확신 낮음"},
         "state": {"entry_date": "2026-11-11"}},                                    # 실제 진입 = 센다
        {"date": "2026-10-01", "ticker": "DDD", "market": "US", "original": {"status": "실행 후보"}, "state": {}},
        {"date": "2026-11-13", "ticker": "EEE", "market": "KR", "original": {"status": "실행 후보"}, "state": {}},
        {"date": "2026-11-14", "ticker": "FFF", "market": "US", "original": {"status": "실행 후보"}, "state": {}}]}  # 오늘 = 제외
    got = IT.recent_entries(b, "US", TODAY, defs.US_REPROPOSE_DAYS)
    assert got == {"AAA": "2026-11-13", "CCC": "2026-11-10"}


def test_cooldown_blocks_repeat_entry_within_window():
    ch = {"AAA": [{"t": "2026-11-13", "c": 100, "s50": 90}]}
    src = {"eps": {"AAA": _eps(0.15, 0.10, 9, 0)}, "eps_asof": "2026-11-14 07:01", "earn_cal": []}
    fresh = {x["s"]: x for x in _run(_peers("AAA"), ch, cat_src=src)["items"]}
    assert fresh["AAA"]["status"] == "실행 후보"
    near = {x["s"]: x for x in _run(_peers("AAA"), ch, cat_src=src, book=_book("AAA", "2026-11-13"))["items"]}
    assert near["AAA"]["status"].startswith("대기 — 중복 제안(11-13 실행")
    # 창(10일) 밖이면 다시 후보, 대기였던 제안은 중복이 아니다
    old = {x["s"]: x for x in _run(_peers("AAA"), ch, cat_src=src, book=_book("AAA", "2026-11-01"))["items"]}
    assert old["AAA"]["status"] == "실행 후보"
    wait = {x["s"]: x for x in _run(_peers("AAA"), ch, cat_src=src,
                                    book=_book("AAA", "2026-11-13", status="대기 — 촉매 없음"))["items"]}
    assert wait["AAA"]["status"] == "실행 후보"
    assert defs.US_REPROPOSE_DAYS == 10


# ── ⑥ 계획 판정 게이트: 촉매만으로 모의 체결되지 않는다 (합동 점검 ②) ──
def test_plan_gate_demotes_low_expected_return():
    def row(status, verdict, ev, base):
        return {"s": "AAA", "status": status, "plan": {"verdict": verdict, "ev_r": ev,
                                                       "prob": {"base_ev_r": base}, "why_not": ["무조건 기준선 이하"]}}
    it = {"items": [row("실행 후보", "관찰(모의)", 0.0999, 0.1203),
                    row("실행 후보", "채택(모의)", 0.21, 0.1203),
                    row("대기 — 촉매 없음", "관찰(모의)", 0.09, 0.12)]}
    n = U.apply_plan_gate(it)
    assert n == 1                                        # 채택, 이미 대기인 행은 그대로
    low, ok, wait = it["items"]
    assert low["status"] == "대기 — 계획 관찰(모의): E[R] +0.10 ≤ 기준선 +0.12"
    assert low["plan_gate"]["verdict"] == "관찰(모의)" and "채택" in low["plan_gate"]["rule"]
    assert ok["status"] == "실행 후보"
    assert wait["status"] == "대기 — 촉매 없음"


def test_plan_gate_handles_holdout_and_missing_plan():
    it = {"items": [{"s": "AAA", "status": "실행 후보", "plan": {"verdict": "보류", "why_not": ["손절폭 16.0% > 15%"]}},
                    {"s": "BBB", "status": "실행 후보", "plan_error": "일봉 부족 — 계획 없음"}]}
    assert U.apply_plan_gate(it) == 2
    assert it["items"][0]["status"] == "대기 — 계획 보류: 손절폭 16.0% > 15%"
    assert it["items"][1]["status"].startswith("대기 — 계획 없음:") and "계획 없음" in it["items"][1]["status"]
    assert defs.US_PLAN_ADOPT is True


# ── ⑦ 과거 18건 소급 체결 금지 (합동 점검 ③, docs/idea_tracking.md) ──
def test_past_us_rows_are_not_retroactively_entered():
    """이미 기록된 '대기 — 촉매 없음' 18건은 촉매 배관을 넓혀도 미진입으로 남는다."""
    import json
    from pathlib import Path

    from screener import idea_tracking as IT

    book = json.loads((Path(__file__).resolve().parents[1] / "reports" / "idea_tracking.json").read_text(encoding="utf-8"))
    us = [r for r in book["rows"] if r.get("market") == "US"]
    assert len(us) >= 18
    assert {r["original"]["status"] for r in us} == {"대기 — 촉매 없음"}
    bars = [{"date": "2026-11-16", "open": 100, "high": 120, "low": 99, "close": 110}]
    assert {IT.evaluate(r, bars)["status"] for r in us} == {"not_entered"}
    # 촉매가 있어도 오늘 회의는 '오늘 행'만 추가되고 과거 행 original 은 불변(확정판 보존)
    now = __import__("datetime").datetime(2026, 11, 14, 23, 0, tzinfo=IT.KST)
    meeting = {"date": "2026-11-14", "asof": "2026-11-14 22:55", "ideas_top": {"items": [
        {"s": "HAS", "n": "Hasbro", "status": "실행 후보", "catalyst": [{"date": "2026-11-14", "what": "EPS 추정 상향"}],
         "entry": 100, "entry_max": 102, "stop": 90, "target": 120, "ref": "2026-11-13"}]}}
    before = {r["id"]: json.dumps(r["original"], sort_keys=True) for r in book["rows"]}
    IT.capture(book, meeting, now, "US")
    for r in book["rows"]:
        if r["id"] in before:
            assert json.dumps(r["original"], sort_keys=True) == before[r["id"]]   # 과거 원본 불변
    assert abs(len(book["rows"]) - len(before)) <= 1


def test_plan_gate_precedes_mock_bottom_line():
    """계획 게이트가 bottom_line 보다 먼저 돌아 'TOP3 실행 후보 n개' 문구가 부풀지 않는다(11/14 합동 점검 ②)."""
    from screener import committee as CM
    it = {"items": [{"s": "AAA", "n": "AAA", "status": "실행 후보",
                     "plan": {"verdict": "관찰(모의)", "ev_r": 0.0999, "prob": {"base_ev_r": 0.1203}}}]}
    bl = {"light": "green", "stance": "중립", "label": "🟢 유지", "lines": ["① What: x", "② So What: y", "③ Now 할 일: z"]}
    assert "모의 추적" in CM._mock_gate(dict(bl, lines=list(bl["lines"])), it)["label"]   # 게이트 전 = 후보 1개
    U.apply_plan_gate(it)
    assert CM._mock_gate(dict(bl, lines=list(bl["lines"])), it)["label"] == "🟢 유지"     # 게이트 뒤 = 후보 0
