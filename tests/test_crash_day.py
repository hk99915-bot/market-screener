"""급락일 종가 = 1차 신호 — 운용회의 판정·실행 대본·15:05 알림·PB 책임·성적표·점도표 (합성 입력, 네트워크 없음)."""
import json
import sys
from datetime import date
from pathlib import Path

from screener import alerts, committee, dotplot as dp, duel

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import scorecard_week as sw  # noqa: E402

GRADE = committee.crash_day_grade()


def _k(chg: float, low_chg: float | None = None, streak: int = 0) -> dict:
    prev = 5500.0
    last = prev * (1 + chg)
    low = prev * (1 + (low_chg if low_chg is not None else min(chg, 0) - 0.005))
    return {"last": last, "ret1": chg, "dd20": -0.1, "from_hi": -0.15, "low_today": low, "low20": prev * 0.90, "hi5": prev * 1.02,
            "src": "KRX 확정 종가 10-15", "sma20": prev * 1.01, "sma50": prev * 1.03, "prev_close": prev, "above20_streak": streak}


def _stance(k):
    scen, sb = committee._scenarios(k, {}, {})
    return committee._stance(k, scen, sb, {}, [], {})


def test_registry_grade_is_read_verbatim():
    reg = json.loads((Path(__file__).resolve().parents[1] / "views" / "registry.json").read_text(encoding="utf-8"))
    g = next(l["evidence"]["grade"] for l in reg["lenses"] if l["id"] == "crash_day_close")
    assert GRADE == g and GRADE in ("A", "B", "C", "F", "검증전")


def test_crash_flag_close_and_intraday_low():
    assert committee.crash_flag(_k(-0.052))["crash"] is True
    f = committee.crash_flag(_k(-0.03, low_chg=-0.051))   # 종가 −3% 라도 장중 −5% 면 급락일
    assert f["crash"] is True and f["near"] is True
    f = committee.crash_flag(_k(-0.042))
    assert f["crash"] is False and f["near"] is True
    assert committee.crash_flag(_k(-0.02))["crash"] is False
    assert committee.crash_flag({})["crash"] is False
    assert committee.crash_flag(_k(-0.06))["grade"] == GRADE


def test_stance_crash_day_buys_regardless_of_flows():
    st = _stance(_k(-0.052))
    assert st["stance"] == "분할 매수"
    assert st["crash_day"]["crash"] is True
    assert st["reasons"][0]["t"].startswith("급락일 종가") and f"등급 {GRADE}" in st["reasons"][0]["t"]
    assert "외국인" not in st["plan"] or "조건이 아님" in st["plan"]
    assert "15:20 동시호가" in st["plan"]
    # 20일 저점 아래(방어 조건)여도 급락일이면 1차 신호가 우선
    k = _k(-0.052)
    k["low20"] = k["last"] * 1.02
    assert _stance(k)["stance"] == "분할 매수"


def test_stance_small_drop_waits_and_recovery_is_sma20_two_days():
    st = _stance(_k(-0.02))
    assert st["stance"] == "관망"
    assert all("외국인 2일 연속 순매수 +" not in r["d"] for r in st["reasons"])
    assert any("20일선" in r["t"] or "20일선" in r["d"] for r in st["reasons"])
    assert _stance(_k(0.01, streak=2))["stance"] == "분할 매수"
    assert _stance(_k(0.01, streak=1))["stance"] == "관망"


def test_exec_plan_step1_text_and_signals():
    k = _k(-0.052)
    st = _stance(k)
    ex = committee._exec_plan(k, st, {}, [])
    s1 = ex["steps"][0]
    assert s1["when"].startswith("급락일 종가 1차 매수 — 15:20 동시호가") and f"등급 {GRADE}" in s1["when"] and "오늘 충족" in s1["when"]
    assert s1["do"] == "크기 = 해금 단계 리스크(1단계 0.25%) · 실계좌 신규는 해금 후(11/16), 그 전엔 모의 '나' 픽 + ISA 선매수(승인 시)"
    assert ex["primary"] == "crash_day_close" and ex["crash_day"]["crash"] is True
    assert ex["signals"][0]["ok"] is True and "1차 신호" in ex["signals"][0]["t"]
    assert any("+1% 위 마감 (C — 2차 참고)" in s["t"] for s in ex["signals"])   # 점도표 low_signal 정규식 호환
    assert not any("외국인" in s["t"] for s in ex["signals"])
    assert ex["dont"][0].startswith("레버리지")
    ex2 = committee._exec_plan(_k(-0.02), _stance(_k(-0.02)), {}, [])
    assert ex2["signals"][0]["ok"] is False and "오늘 미충족" in ex2["steps"][0]["when"]


def test_scenario_trigger_drops_foreign_condition():
    scen, _ = committee._scenarios(_k(-0.01), {}, {})
    assert "20일선" in scen[0]["trigger"] and "외국인 현물 2일" not in scen[0]["trigger"]


def test_crash_alert_text_and_dedupe(tmp_path, monkeypatch):
    monkeypatch.setattr(alerts, "STATE", tmp_path / "alerts_state.json")
    t = alerts.crash_text(-0.047, GRADE, date(2026, 10, 15), 5240.12)
    assert t.startswith(f"⚡ <b>급락일 종가 매수 신호</b> (등급 {GRADE}, 20일 +7.5%·승률 81%·n16) — 15:20 동시호가")
    assert "① 모의 pick 등록" in t and "② ISA 선매수(결재 #15 · 연 2회 상한" in t and "③ 위성 실계좌는 해금 후" in t
    assert "하지 말 일: 레버리지. 안 할 거면 사유를 기록." in t
    assert "069500%201000000%20%EC%A2%85%EA%B0%80" in t   # issue_url 선입력 '069500 1000000 종가'
    r = alerts.crash_check({"chg": -0.046, "last": 5240.0}, send=False, today=date(2026, 10, 15))
    assert r["fired"] is True and r["text"]
    assert alerts.crash_check({"chg": -0.02, "last": 5400.0}, send=False, today=date(2026, 10, 15))["fired"] is False
    # 전송(모의) 뒤 같은 날은 다시 안 울림
    import screener.alerts as A
    st = {"sent": {"2026-10-15:crash": "x"}}
    (tmp_path / "alerts_state.json").write_text(json.dumps(st), encoding="utf-8")
    assert A.crash_check({"chg": -0.06, "last": 5200.0}, send=False, today=date(2026, 10, 15))["fired"] is False


def test_duel_marks_crash_day_cash():
    it = {"id": "2026-10-15-entry", "date": "2026-10-15", "kind": "entry", "picks": {}, "pb_view": {"why": "관망", "lines": ["코스피 5,200 (−5.2%)"]}}
    duel.mark_crash_day(it, {"cash": True}, True)
    assert it["crash_day"] is True and it["pb_view"]["crash_day_cash"] is True
    assert it["pb_view"]["lines"][-1] == duel.CRASH_CASH_LINE
    duel.mark_crash_day(it, {"cash": True}, True)   # 중복 추가 안 함
    assert it["pb_view"]["lines"].count(duel.CRASH_CASH_LINE) == 1
    it2 = {"id": "x", "date": "2026-10-15", "picks": {}}
    duel.mark_crash_day(it2, {"ticker": "069500"}, True)
    assert it2["crash_day"] is True and it2["pb_view"]["crash_day_cash"] is False
    assert duel.is_crash_day("2026-10-15", cmt={"date": "2026-10-15", "crash_day": {"crash": True}}) is True
    assert duel.is_crash_day("2026-10-15", cmt={"date": "2026-10-14", "crash_day": {"crash": True}}, q={"chg": -0.01}) is False
    assert duel.is_crash_day("2026-10-15", cmt={}, q={"chg": -0.055}) is True


def test_scorecard_crash_day_pb_rate():
    items = [
        {"id": "a", "date": "2026-10-13", "kind": "entry", "crash_day": True, "picks": {"PB": {"cash": True}}, "pb_view": {"why": "관망"}},
        {"id": "b", "date": "2026-10-14", "kind": "entry", "crash_day": True, "picks": {"PB": {"ticker": "069500"}}, "pb_view": {}},
        {"id": "c", "date": "2026-10-15", "kind": "entry", "crash_day": True, "picks": {"PB": {"cash": True}}, "pb_view": {"why": "게이트 불통: 노출 한도", "gate_fail": True}},
        {"id": "d", "date": "2026-10-16", "kind": "entry", "crash_day": False, "picks": {"PB": {"cash": True}}},
        {"id": "e", "date": "2026-10-08", "kind": "entry", "crash_day": True, "picks": {"PB": {"cash": True}}},   # 지난주
    ]
    r = sw.crash_day_pb(items, date(2026, 10, 12), date(2026, 10, 18))
    assert (r["n"], r["acted"]) == (3, 2) and abs(r["rate"] - 2 / 3) < 1e-9
    assert sw.crash_day_pb([], date(2026, 10, 12), date(2026, 10, 18))["rate"] is None


def test_dotplot_quant_crash_day_flag():
    f = {"date": "2026-10-16", "px": {a: {"r1": -0.01, "vs200": 0.05, "to_low20": 0.1, "vol20": 0.3} for a in dp.ASSETS},
         "us10y": {"level": 4.5, "d5_bp": 0.0}, "macro_score": 0.0, "macro_label": "중립", "gex_bn": 100.0, "basis": 0.5, "pcr_oi": 1.0,
         "has_committee": True, "has_derivs": True, "has_macro": True, "scen_kr": {"bull": 0.3, "bear": 0.3}, "scen_us": {"bull": 0.3, "bear": 0.3},
         "pb_stance": "분할 매수", "low_signal_ok": False, "glide": False, "valuation": {a: None for a in dp.ASSETS}, "has_valuation": False,
         "picks": [], "has_decisions": True, "crash_day": True, "crash_grade": GRADE}
    st, conv, reason, tag = dp.rule_quant(f, "KOSPI")
    assert (st, conv) == ("매수", 2) and reason.startswith(f"급락일 종가(등급 {GRADE})")
    assert dp.rule_quant(f, "SEMI_KR")[0] == "중립"   # 플래그는 코스피 점에만
    f["crash_day"] = False
    assert dp.rule_quant(f, "KOSPI")[0] == "중립"
    feats = dp.derive_features({"committee": {"date": "2026-10-16", "crash_day": {"crash": True, "grade": GRADE}}}, today="2026-10-16")
    assert feats["crash_day"] is True and feats["crash_grade"] == GRADE
