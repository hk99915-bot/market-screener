"""규칙 집행 갭 6건 (감사 2026-10-17 rules_vs_code #12·#17·#24·#25·#26 + 화면 정합성 중-1·중-2·중-4·경-10).
① 재협상 사유 10자·관련 주문표만 ⛔ ② 하드 바닥(평단 −30%) 감시 ③ 시크릿 부재 health ④ VaR 초과 → 반도체 BUY ⛔ ⑤ ISA #15 ⑥ 화면 용어·비율만 보기."""
import json
import re
from datetime import date, datetime
from pathlib import Path

import pytest

from screener import alerts, defs, event_watch, freshness, renego, ticket

ROOT = Path(__file__).resolve().parents[1]
AT = "2026-10-19T02:00:00Z"      # 월 11:00 KST
BODY = "매수가 10,000\n손절가 9,500\n목표가 11,500\n근거: 눌림 지지 확인\n보유 5일\n"
NOSEMI = {"semi": False, "below_backstop": False, "var_over": False}
SEMI = {"semi": True, "below_backstop": False, "var_over": False}


@pytest.fixture
def env(tmp_path, monkeypatch):
    rep = tmp_path / "reports"
    (rep / "detail" / "KR").mkdir(parents=True)
    (rep / "events.json").write_text(json.dumps({"events": []}), encoding="utf-8")
    (rep / "calendar.json").write_text(json.dumps({"events": []}), encoding="utf-8")
    monkeypatch.setattr(ticket, "REPORT_DIR", rep)
    monkeypatch.setattr(ticket, "COOLDOWN_FILE", tmp_path / "cooldown.json")
    monkeypatch.setattr(ticket, "ISA_FILE", tmp_path / "isa_buys.json")
    monkeypatch.setattr(renego, "FILE", tmp_path / "renego.json")
    monkeypatch.delenv(ticket.COOLDOWN_ENV, raising=False)
    for n in ("MY_RULES", "MY_HOLDINGS"):
        monkeypatch.delenv(n, raising=False)
    renego.add("POS_BACKSTOP", date(2026, 10, 17))
    renego.add("POS_BACKSTOP", date(2026, 10, 17))
    return tmp_path


# ① 재협상 ----------------------------------------------------------------------------------------
def test_reason_needs_10_chars():
    assert not renego.reason_ok("ㅇ") and not renego.reason_ok("   짧은 사유   ")
    assert renego.reason_ok("반등일 확인 전 손절은 과매도 구간이라")
    tk = ticket.parse_ticket("ticket 000001", BODY + "재협상사유: ㅇ")
    assert tk["renego_reason"] is False and tk["renego_short"] is True


def test_backstop_renego_only_for_related_tickets(env):
    tk = ticket.parse_ticket("ticket 000001", BODY)
    assert not any("재협상" in r for r in ticket.evaluate(tk, AT, ctx=NOSEMI)["reasons"])    # 무관한 주문표: ⛔ 없음
    ev = ticket.evaluate(tk, AT, ctx=SEMI)
    assert ev["verdict"].startswith("⛔") and any("재협상 2회째" in r and "POS_BACKSTOP(백스톱)" in r for r in ev["reasons"])
    ev = ticket.evaluate(tk, AT, ctx={**NOSEMI, "below_backstop": True})
    assert ev["verdict"].startswith("⛔")                                                    # −20% 아래 보유 종목도 관련
    short = ticket.parse_ticket("ticket 000001", BODY + "재협상사유: ㅇ")
    assert any("10자 미만" in r for r in ticket.evaluate(short, AT, ctx=SEMI)["reasons"])
    ok = ticket.parse_ticket("ticket 000001", BODY + "재협상사유: 반등일 확인 전 손절은 과매도 구간이라")
    ev = ticket.evaluate(ok, AT, ctx=SEMI)
    assert ev["verdict"].startswith("✅") and ev["renego"]["reason_given"] is True


def test_unscoped_rule_still_applies_to_all(env):
    renego.add("MIN_RR", date(2026, 10, 18))
    renego.add("MIN_RR", date(2026, 10, 18))
    ev = ticket.evaluate(ticket.parse_ticket("ticket 000001", BODY), AT, ctx=NOSEMI)
    assert ev["verdict"].startswith("⛔") and ev["renego"]["rules"] == ["MIN_RR"]


# ② 하드 바닥 -------------------------------------------------------------------------------------
CTX = {"floors": {"005930": {"mk": "KR", "name": "삼성전자", "avg": 100000.0, "floor": 70000.0},
                  "000660": {"mk": "KR", "name": "SK하이닉스", "avg": 1500000.0, "floor": 1050000.0},
                  "MU": {"mk": "US", "name": "Micron", "avg": 100.0, "floor": 70.0}}}


def test_floor_hits_ratio_only_and_touch_stricter():
    q = {"005930": {"last": 71000, "low": 69500, "name": "삼성전자"}, "000660": {"last": 1100000, "low": 1100000, "name": "SK하이닉스"}}
    hits = alerts.floor_hits(CTX, {"touch": {"000660": 1170000.0}}, q.get, "KR")
    assert [h[0] for h in hits] == ["005930"]                       # 000660 은 더 엄격한 touch 1,170,000 이 담당
    line = hits[0][2]
    assert "하드 바닥" in line and defs.SEMI_HARD_FLOOR_STATE in line and "−30%" in line
    assert "70,000" not in line and "100,000" not in line and "69,500" not in line   # 평단·가격 미노출
    assert alerts.floor_hits(CTX, {}, {"005930": {"last": 80000, "low": 75000}}.get, "KR") == []
    assert alerts.floor_hits(None, {}, q.get, "KR") == []


def test_event_watch_floor_daily_hashed():
    st = {"sent": {}}
    evs = event_watch.floor_events(CTX, {}, {"MU": {"last": 69.0, "low": 68.0}}, st, "2026-10-19", "US")
    assert len(evs) == 1 and evs[0]["key"].startswith("floor:") and "MU" not in evs[0]["key"]
    st["sent"][evs[0]["key"]] = "x"
    assert event_watch.floor_events(CTX, {}, {"MU": {"last": 69.0, "low": 68.0}}, st, "2026-10-19", "US") == []
    assert alerts.kind(evs[0]["key"]) not in alerts.RING_KINDS     # 사전등록 — 소리 표 밖


# ③ 시크릿 부재 -----------------------------------------------------------------------------------
def test_secret_health_warns_and_clears(tmp_path, monkeypatch, caplog):
    fp = tmp_path / "freshness.json"
    fp.write_text(json.dumps({"late": [], "stale": []}), encoding="utf-8")
    monkeypatch.delenv("MY_RULES", raising=False)
    monkeypatch.setenv("MY_HOLDINGS", "x")
    with caplog.at_level("WARNING"):
        assert alerts.secret_health("test", path=fp, intended={}) == ["MY_RULES"]
    assert "알림 비활성: MY_RULES 없음" in caplog.text
    h = json.loads(fp.read_text(encoding="utf-8"))["health"]
    assert [x["what"] for x in h] == ["알림 비활성: MY_RULES 없음"] and "x" not in json.dumps(h).replace("fix", "")
    monkeypatch.setenv("MY_RULES", "000660 1170000 touch")
    assert alerts.secret_health("test", path=fp, intended={}) == []
    assert json.loads(fp.read_text(encoding="utf-8"))["health"] == []


def test_secret_intended_off_is_info_not_alarm(tmp_path, monkeypatch, caplog):
    """10/21 겸이 결정: MY_RULES·MY_HOLDINGS 안 만든다 → 배지 경보(health)가 아니라 health_info. 예전 경보 줄은 옮겨진다."""
    fp = tmp_path / "freshness.json"
    fp.write_text(json.dumps({"health": [{"id": "secret:MY_RULES", "what": "알림 비활성: MY_RULES 없음", "since": "2026-10-19 09:02"}]}), encoding="utf-8")
    monkeypatch.delenv("MY_RULES", raising=False)
    monkeypatch.delenv("MY_HOLDINGS", raising=False)
    with caplog.at_level("INFO"):
        assert alerts.secret_health("test", path=fp) == ["MY_RULES", "MY_HOLDINGS"]
    assert "⛔" not in caplog.text
    o = json.loads(fp.read_text(encoding="utf-8"))
    assert o["health"] == [] and [h["id"] for h in o["health_info"]] == ["secret:MY_RULES", "secret:MY_HOLDINGS"]
    assert o["health_info"][0]["since"] == "2026-10-19 09:02" and "10/21 결정" in o["health_info"][0]["what"]
    assert set(alerts.INTENDED_OFF) == {"MY_RULES", "MY_HOLDINGS"}


def test_freshness_check_keeps_health(tmp_path):
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "freshness.json").write_text(json.dumps({"health": [{"id": "secret:MY_RULES", "what": "알림 비활성: MY_RULES 없음"}]}), encoding="utf-8")
    o = freshness.check(datetime(2026, 10, 19, 11, 0, tzinfo=alerts.KST), root=tmp_path, items=[])
    assert o["health"][0]["what"] == "알림 비활성: MY_RULES 없음"


def test_badge_shows_health():
    idx = (ROOT / "apps-script" / "Index.html").read_text(encoding="utf-8")
    assert "FR.health" in idx and "H.map(h=>h.what)" in idx


# ④ VaR ------------------------------------------------------------------------------------------
def test_var_over_blocks_semi_buy_only(env):
    renego.FILE.write_text(json.dumps({"events": []}), encoding="utf-8")
    buy = ticket.parse_ticket("ticket 000001", BODY)
    ev = ticket.evaluate(buy, AT, ctx={**SEMI, "var_over": True})
    assert ev["verdict"].startswith("⛔") and any(defs.VAR_SEMI_BUY_BAN in r for r in ev["reasons"])
    assert defs.VAR_SEMI_BUY_BAN == "반도체 신규 매수 금지(결재 #3)"
    assert ticket.evaluate(buy, AT, ctx={**NOSEMI, "var_over": True})["verdict"].startswith("✅")
    sell = ticket.parse_ticket("ticket 000001", BODY + "구분: 매도")
    assert sell["side"] == "SELL"
    assert not any(defs.VAR_SEMI_BUY_BAN in r for r in ticket.evaluate(sell, AT, ctx={**SEMI, "var_over": True})["reasons"])
    ev = ticket.evaluate(buy, AT, ctx={**SEMI, "var_over": None})
    assert any("VaR 계기판 확인 불가" in r for r in ev["reasons"])                   # 시크릿 없음 = 조용한 통과 금지


# ⑤ ISA #15 --------------------------------------------------------------------------------------
ISA = "매수가 10,000\n근거: 월 적립\n계좌 ISA\n"


def test_isa_monthly_day_and_once(env):
    assert ticket.isa_monthly_day(date(2026, 11, 20)) == date(2026, 11, 2)       # 11/1 일요일 → 다음 거래일
    tk = ticket.parse_ticket("ticket 360750", ISA)
    assert tk["account"] == "ISA" and tk["stop"] is None
    ok = ticket.evaluate_isa(tk, "2026-11-02T01:00:00Z")
    assert ok["verdict"].startswith("✅") and ok["kind"] == "monthly"
    assert ticket.evaluate_isa(tk, "2026-11-03T01:00:00Z")["verdict"].startswith("⛔")
    ticket.isa_record("2026-11-02", "monthly")
    assert any("이미" in r for r in ticket.evaluate_isa(tk, "2026-11-02T03:00:00Z")["reasons"])


def test_isa_crash_cap_two_per_year(env):
    tk = ticket.parse_ticket("ticket 360750", ISA + "급락선매수\n")
    assert ticket.evaluate_isa(tk, AT, crash=False)["verdict"].startswith("⛔")          # 급락 신호 없으면 선매수 아님
    assert ticket.evaluate_isa(tk, AT, crash=True)["verdict"].startswith("✅")
    ticket.isa_record("2026-03-02", "crash")
    ticket.isa_record("2026-08-05", "crash")
    ev = ticket.evaluate_isa(tk, AT, crash=True)
    assert ev["verdict"].startswith("⛔") and any("연 2회 상한" in r for r in ev["reasons"])
    assert ticket.isa_counts(date(2027, 1, 5))["crash_year"] == 0
    saved = json.loads(ticket.ISA_FILE.read_text(encoding="utf-8"))["events"]
    assert all(set(e) == {"date", "kind"} for e in saved)                              # 공개 파일: 날짜·종류만


def test_isa_counter_file_public_schema():
    d = json.loads((ROOT / "ops" / "isa_buys.json").read_text(encoding="utf-8"))
    assert all(set(e) <= ticket.ISA_KEYS for e in d.get("events") or [])


# ⑥ 화면 -----------------------------------------------------------------------------------------
def test_tab_my_denominator_terms_and_privacy():
    t = (ROOT / "apps-script" / "tab_my.html").read_text(encoding="utf-8")
    m = re.search(r"const DENOM_TERMS=\{a:'([^']+)',b:'([^']+)',c:'([^']+)'\}", t)
    assert m and m.groups() == (defs.DENOM_TERMS["a"], defs.DENOM_TERMS["b"], defs.DENOM_TERMS["c"])
    assert "pct(stS/DEN,1)" in t and "stS/NAV" not in t                              # MY 스트레스 = (b)
    assert "분모: 순자산" not in t and "분모 D2" not in t
    assert "비율만 보기" in t and "mt_ratio_only" in t and "localStorage.getItem(MYRK)!=='0'" in t   # 기본 ON
    assert not re.search(r"\$\{K\([^()]*\)\}원", t)                                   # 원 금액은 KW() 경유(비율만 보기 시 숨김)


def test_tab_duel_lev_label_and_single_cooldown():
    t = (ROOT / "apps-script" / "tab_duel.html").read_text(encoding="utf-8")
    assert "레버리지 1일 상한(결재 #14)" in t and "levTag(it.pb_view.bold.why)" in t
    assert "RENEGO_REASON_MIN=10" in t and "renegoFor(" in t
    defs_n = sum(len(re.findall(r"\bconst COOLDOWN_MIN\s*=", p.read_text(encoding="utf-8"))) for p in (ROOT / "apps-script").glob("*.html"))
    assert defs_n == 1 and re.search(r"const COOLDOWN_MIN=(\d+)", t).group(1) == str(defs.COOLDOWN_MIN)
