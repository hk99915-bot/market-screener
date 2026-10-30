"""타점 대결 '나' 게이트 — 겸이 10/23 결재 ① 계획 칸 강제 ② 당일 쿨다운 (screener/pick_gate.py · duel.apply_issue). 네트워크 없음."""
import json

import pytest

from screener import decisions, duel, pick_gate, ticket

D = "2026-10-26"                 # 월 — 게이트 적용일(PICK_GATE_FROM) 이후
AT = f"{D}T05:00:00Z"            # 14:00 KST
PLAN = " 손절 -2% 목표 +3% 근거: 급락 뒤 반등 확인"   # R:R 1.5 (경계 통과)


@pytest.fixture
def dec(tmp_path, monkeypatch):
    p = tmp_path / "decisions.json"
    monkeypatch.setattr(decisions, "OUT", p)
    monkeypatch.setattr(ticket, "COOLDOWN_FILE", tmp_path / "cooldown.json")
    monkeypatch.delenv("COOLDOWN_LAST_AT", raising=False)
    monkeypatch.setattr(pick_gate, "ref_price", lambda c, d: 10000.0)          # 기준가(최근 종가) 고정
    monkeypatch.setattr(decisions, "_score_pick", lambda p, d: None)            # 직전 판 실시간 채점 없음
    import screener.pb as pb
    monkeypatch.setattr(pb, "semi_code", lambda mk, code: code in ("091160", "000660"))
    return p


def _picks(p, iid=f"{D}-entry"):
    return next(x for x in json.loads(p.read_text(encoding="utf-8"))["items"] if x["id"] == iid)["picks"]


def _seed(p, items):
    p.write_text(json.dumps({"items": items}, ensure_ascii=False), encoding="utf-8")


# ── ① 계획 칸 ────────────────────────────────────────────
def test_full_plan_stays_me(dec):
    msg = duel.apply_issue(f"pick {D}", "069500 1000000 시가" + PLAN, AT)
    pk = _picks(dec)
    me = pk["나"]
    assert "나🔥" not in pk and me["ticker"] == "069500" and me["notional"] == 1_000_000 and me["exit"] == "next_open"
    assert me["plan"]["rr"] == 1.5 and me["plan"]["why"] == "급락 뒤 반등 확인" and "reclass" not in me
    assert "계획: 손절 −2.0% · 목표 +3.0% · R:R 1:1.50" in msg


def test_rr_boundary(dec):
    duel.apply_issue(f"pick {D}", "069500 시가 손절 -2% 목표 +2.98% 근거: x", AT)   # 1.49
    pk = _picks(dec)
    assert pk["나"] == {"pending": True}
    assert pk["나🔥"]["reclass"] == "R:R 1:1.49 < 1:1.5" and pk["나🔥"]["basis"] == "감"


@pytest.mark.parametrize("plan,miss", [("", "손절·목표·근거"), (" 손절 -2% 목표 +4%", "근거"), (" 목표 +4% 근거: x", "손절"),
                                       (" 손절 -2% 근거: x", "목표")])
def test_missing_plan_goes_bold(dec, plan, miss):
    msg = duel.apply_issue(f"pick {D}", "069500 500000 시가" + plan, AT)
    b = _picks(dec)["나🔥"]
    assert b["reclass"].startswith(f"계획 칸 비어 있음({miss})")
    assert b["notional"] == 1_000_000 and b["unlock_evidence"] is False and b["basis"] == "감"
    assert "'나🔥'(감)로 분류" in msg and b["reclass"] in msg


def test_price_plan_uses_ref_and_lines(dec):
    duel.apply_issue(f"pick {D}", "069500 시가\n손절가 9,800\n1차 목표 10,400\n근거: 20일선 지지", AT)   # (10400−10000)/(10000−9800)=2
    me = _picks(dec)["나"]
    assert me["plan"]["rr"] == 2.0 and me["plan"]["ref"] == 10000.0 and me["plan"]["stop"] == 9800


def test_cash_exempt(dec):
    assert "기록 완료" in duel.apply_issue(f"pick {D}", "현금", AT)
    assert _picks(dec)["나"]["cash"] is True and "나🔥" not in _picks(dec)


def test_button_body_without_plan_is_bold_and_cancels_previous_me(dec):
    duel.apply_issue(f"pick {D}", "069500 1000000 시가" + PLAN, AT)
    msg = duel.apply_issue(f"pick {D}", "069500 1000000 시가", f"{D}T05:10:00Z")   # 텔레그램 버튼 본문
    pk = _picks(dec)
    assert pk["나"] == {"pending": True} and pk["나🔥"]["submitted"] == "14:10"
    assert "앞서 낸 '나'(14:00 제출)는 취소" in msg


def test_before_gate_date_unchanged(dec):
    d0 = "2026-10-22"
    duel.apply_issue(f"pick {d0}", "122630 1000000 시가", f"{d0}T05:00:00Z")
    assert _picks(dec, f"{d0}-entry")["나"]["ticker"] == "122630"


def test_telegram_text_one_line_keeps_plan():
    is_ = duel.parse_pick_text("pick 069500 시가 손절 -2% 목표 +3% 근거 반등 확인", D, D)
    assert is_["body"] == "069500 시가 손절 -2% 목표 +3% 근거 반등 확인"
    head, tail = pick_gate.split_head(is_["body"])
    assert head == "069500 시가" and pick_gate.parse_plan(tail)["why"] == "반등 확인"


def test_why_in_middle_and_keyword_inside_reason():
    pl = pick_gate.parse_plan("근거 목표가 상향 뉴스 손절 -2% 목표 +4%")
    assert pl == {"why": "목표가 상향 뉴스", "stop_pct": -0.02, "target_pct": 0.04}


# ── ② 당일 쿨다운 ────────────────────────────────────────
def test_cooldown_real_sell_blocks_leverage_allows_plain(dec, tmp_path):
    (tmp_path / "cooldown.json").write_text(json.dumps({"events": [{"at": f"{D} 10:31", "what": "실계좌 매도"}]}, ensure_ascii=False), encoding="utf-8")
    duel.apply_issue(f"pick {D}", "122630 1000000 시가" + PLAN, AT)
    b = _picks(dec)["나🔥"]
    assert "쿨다운: 10/26 실계좌 매도 10:31 뒤" in b["reclass"] and "레버리지·인버스 +2배" in b["reclass"]
    msg = duel.apply_issue(f"pick {D}", "069500 1000000 시가" + PLAN, f"{D}T05:20:00Z")
    me = _picks(dec)["나"]
    assert me["ticker"] == "069500" and "'나' 인정" in me["cooldown"] and "⏳ 쿨다운" in msg


def test_cooldown_blocks_semi(dec, tmp_path):
    (tmp_path / "cooldown.json").write_text(json.dumps({"events": [{"at": f"{D} 09:10", "what": "포상"}]}, ensure_ascii=False), encoding="utf-8")
    duel.apply_issue(f"pick {D}", "091160 1000000 시가" + PLAN, AT)
    assert _picks(dec)["나🔥"]["reclass"].endswith("(반도체)")


def test_event_after_submission_or_other_day_ignored(dec, tmp_path):
    (tmp_path / "cooldown.json").write_text(json.dumps({"events": [{"at": f"{D} 14:30", "what": "포상"}, {"at": "2026-10-23 14:31", "what": "실계좌 매도"}]},
                                                       ensure_ascii=False), encoding="utf-8")
    duel.apply_issue(f"pick {D}", "122630 1000000 시가" + PLAN, AT)
    assert _picks(dec)["나"]["ticker"] == "122630"


def _loss_item(iid, date, detail, ret=-0.02, market=None):
    it = {"id": iid, "date": date, "kind": "entry", "title": "t",
          "picks": {"나": {"ticker": "122630", "notional": 1e6, "entry": "close", "exit": "next_open", "submitted": "14:00"}, "PB": {"cash": True}},
          "result": {"나": {"ret": ret, "pnl": ret * 1e6, "detail": detail}, "PB": {"ret": 0.0, "pnl": 0, "detail": "현금 유지"}}}
    if market:
        it["market"] = market
    return it


def test_prev_trading_day_kr_loss_triggers(dec):
    _seed(dec, [_loss_item("2026-10-23-entry", "2026-10-23", "2026-10-23 종가 66,770 → 2026-10-26 시가 64,005", -0.0419)])
    msg = duel.apply_issue(f"pick {D}", "122630 1000000 시가" + PLAN, AT)
    b = _picks(dec)["나🔥"]
    assert "국장 10/23 '나' 손실 −4.2% 확정(10/26 09:00) 뒤" in b["reclass"]
    assert b["reclass"] in msg


def test_prev_day_gain_no_cooldown(dec):
    _seed(dec, [_loss_item("2026-10-23-entry", "2026-10-23", "2026-10-23 종가 1 → 2026-10-26 시가 2", 0.01)])
    duel.apply_issue(f"pick {D}", "122630 1000000 시가" + PLAN, AT)
    assert _picks(dec)["나"]["ticker"] == "122630"


def test_same_day_us_loss_triggers_kr(dec):
    _seed(dec, [_loss_item("2026-10-23-entry-us", "2026-10-23", "2026-10-23 시가 48.64 → 2026-10-23 종가 47.13", -0.0315, "US")])
    # 10/23 16:00 ET = 10/24 05:00 KST → 10/24 KST 날짜의 손실 (10/26 국장엔 해당 없음)
    duel.apply_issue(f"pick {D}", "122630 1000000 시가" + PLAN, AT)
    assert _picks(dec)["나"]["ticker"] == "122630"
    us = "2026-10-26"   # 미장 10/26 세션, 10/26 22:00 KST 제출 — 그날 09:00 국장 손실 확정 뒤
    _seed(dec, [_loss_item("2026-10-23-entry", "2026-10-23", "2026-10-23 종가 66,770 → 2026-10-26 시가 64,005")])
    msg = duel.apply_issue(f"pick-us {us}", "SOXL 1000000" + PLAN, f"{us}T13:00:00Z")
    b = _picks(dec, f"{us}-entry-us")["나🔥"]
    assert "국장 10/23 '나' 손실" in b["reclass"] and "+3배" in b["reclass"] and "미장" in msg
    assert b["unlock_evidence"] is False


def test_reclassified_battle_still_scored(dec, monkeypatch):
    it = {"id": "2026-10-20-entry", "date": "2026-10-20", "kind": "entry", "title": "t",   # 지난 날짜(채점 대상)
          "picks": {"나": {"pending": True}, "PB": {"cash": True},
                    "나🔥": {"ticker": "122630", "notional": 1e6, "entry": "close", "exit": "next_open", "reclass": "계획 칸 비어 있음(근거)", "basis": "감"}}}
    _seed(dec, [it])
    monkeypatch.setattr(decisions, "_score_pick", lambda p, d: {"ret": 0.0, "pnl": 0.0, "detail": "현금 유지"} if p.get("cash") else {"ret": 0.01, "pnl": 10000, "detail": "x"})
    import screener.battle_scoreboard as bs
    monkeypatch.setattr(bs, "build", lambda: None)
    decisions.score()
    d = json.loads(dec.read_text(encoding="utf-8"))
    r = d["items"][0]["result"]
    assert "void" not in r and r["나🔥"]["ret"] == 0.01 and d["tally"]["나🔥"]["by_basis"]["감"]["n"] == 1


# ── 소급 점검(10/24 결재 appr-pick-gate-start: 10/23 19:00 제출분부터, 표시만) ──
def test_audit_flags_bypass_only_after_start(dec):
    items = [
        {"id": "2026-10-23-entry", "date": "2026-10-23", "kind": "entry",
         "picks": {"나": {"ticker": "122630", "name": "KODEX 레버리지", "submitted": "15:02"}}},                 # 적용 전 → 대상 아님
        {"id": "2026-10-23-entry-us", "date": "2026-10-23", "kind": "entry", "market": "US",
         "picks": {"나": {"ticker": "SOXX", "name": "SOXX", "submitted": "21:17"}}},                           # 계획 없이 '나' → 위반
        {"id": f"{D}-entry", "date": D, "kind": "entry",
         "picks": {"나": {"ticker": "069500", "submitted": "14:00", "plan": {"stop_pct": -0.02, "target_pct": 0.03, "why": "x", "rr": 1.5}},
                   "나🔥": {"ticker": "122630", "submitted": "13:00", "reclass": "계획 칸 비어 있음(근거)"}}},
        {"id": "2026-10-27-entry", "date": "2026-10-27", "kind": "entry", "picks": {"나": {"cash": True, "submitted": "10:00"}}},
    ]
    rows = {(r["id"], r["slot"]): r for r in pick_gate.audit(items, events=[], semi_fn=lambda m, c: False)}
    assert ("2026-10-23-entry", "나") not in rows
    v = rows[("2026-10-23-entry-us", "나")]
    assert v["status"] == "위반" and "계획 칸 비어 있음" in v["reasons"][0]
    assert rows[(f"{D}-entry", "나")]["status"] == "통과" and rows[(f"{D}-entry", "나🔥")]["status"] == "재분류"
    assert rows[("2026-10-27-entry", "나")]["status"] == "현금"


def test_audit_apply_marks_without_moving(dec):
    import scripts.pick_gate_audit as pga
    _seed(dec, [{"id": "2026-10-23-entry-us", "date": "2026-10-23", "kind": "entry", "market": "US",
                 "picks": {"나": {"ticker": "SOXX", "name": "SOXX", "submitted": "21:17"}}}])
    pga.main(["--apply"])
    pk = _picks(dec, "2026-10-23-entry-us")
    assert "나🔥" not in pk and pk["나"]["ticker"] == "SOXX" and "게이트 위반" in pk["나"]["gate_audit"]


# ── 결재 10/29 ①: R:R 기준가 = 체결 기준가, 본문 매수가는 참고(±0.5% 넘으면 경고) ──
def _classify(plan_text, ref=10000.0):
    from datetime import datetime
    t = datetime(2026, 10, 30, 14, 0, tzinfo=pick_gate.KST)
    item = {"id": "2026-10-30-entry", "date": "2026-10-30", "kind": "entry", "market": "KR"}
    pick = {"ticker": "122630", "notional": 1e6, "entry": "close", "exit": "next_open"}
    return pick_gate.classify(pick, plan_text, t, item, [], ref_fn=lambda c, d: ref, events=[])


def test_entry_in_body_does_not_set_rr_base():
    # 매수가 9800 을 적어 R:R 을 4 로 부풀려도 체결 기준가(10000) 기준 0.67 → '나🔥'
    slot, pick, why = _classify("손절 9700 목표 10200 매수가 9800 근거: 반등")
    assert slot == "나🔥" and any("R:R" in w for w in why)
    assert pick["plan"]["rr"] == 0.67 and pick["plan"]["ref"] == 10000.0 and pick["plan"]["entry"] == 9800
    assert "9,800" in pick["plan"]["warn"] and "±0.5%" in pick["plan"]["warn"]


def test_entry_within_half_percent_no_warn_and_ref_used():
    slot, pick, why = _classify("손절 9800 목표 10300 매수가 10040 근거: 반등")   # +0.4%
    assert slot == "나" and not why and "warn" not in pick["plan"]
    assert pick["plan"]["rr"] == 1.5      # (10300-10000)/(10000-9800), 매수가 10040 이면 1.55
    assert pick_gate.entry_warn({"entry": 10051}, 10000.0) and not pick_gate.entry_warn({"entry": 10050}, 10000.0)


def test_entry_only_without_ref_is_not_used_for_rr():
    slot, pick, why = pick_gate.classify(
        {"ticker": "X", "notional": 1}, "손절 9700 목표 10200 매수가 9800 근거: 반등",
        __import__("datetime").datetime(2026, 10, 30, 14, 0, tzinfo=pick_gate.KST),
        {"id": "i", "date": "2026-10-30", "kind": "entry"}, [], ref_fn=lambda c, d: None, events=[])
    assert slot == "나🔥" and any("R:R 계산 불가" in w for w in why)
