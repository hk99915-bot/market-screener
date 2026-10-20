"""재발방지대책(10/17 오너 지시) 테스트 — asof 가드·거래일 기대일·신선도 계약·조용한 대체 stale·역행 재현."""
import json
import sys
import types
from datetime import date, datetime
from pathlib import Path

import polars as pl
import pytest

from screener import freshness, guard, tradecal
from screener.tradecal import KST


@pytest.fixture
def rep(tmp_path, monkeypatch):
    """reports/ 를 임시 폴더로 (guard 의 freshness.json 기록 위치 포함)."""
    r = tmp_path / "reports"
    r.mkdir()
    monkeypatch.setattr(guard, "_report_dir", lambda: r)
    monkeypatch.delenv("SCREENER_ALLOW_REGRESS", raising=False)
    return r


def _fr(rep):
    return json.loads((rep / "freshness.json").read_text(encoding="utf-8"))


# ── B. asof 단조 가드 ──
def test_guard_blocks_regress_and_records(rep):
    p = rep / "x_summary.json"   # 계약 없는 경로 — 역행만 검사
    p.write_text(json.dumps({"asof": "2026-10-16", "n": 1}), encoding="utf-8")
    assert guard.write_json(p, {"asof": "2026-10-15", "n": 2}) is False
    assert json.loads(p.read_text())["n"] == 1                       # 기존 그대로
    rb = _fr(rep)["regress_blocked"]
    assert rb[-1]["existing"] == "2026-10-16" and rb[-1]["new"] == "2026-10-15"


def test_guard_same_day_and_newer_allowed(rep):
    p = rep / "x_board.json"
    p.write_text(json.dumps({"asof": "2026-10-16 15:50", "date": "2026-10-16", "v": 1}), encoding="utf-8")
    assert guard.write_json(p, {"asof": "2026-10-16 19:44", "date": "2026-10-16", "v": 2}, key="date")
    assert guard.write_json(p, {"asof": "2026-10-17 01:00", "date": "2026-10-17", "v": 3}, key="date")
    assert json.loads(p.read_text())["v"] == 3
    # key=date: asof(실행 시각)가 새로워도 데이터일이 과거면 차단
    assert guard.write_json(p, {"asof": "2026-10-18 09:00", "date": "2026-10-16", "v": 4}, key="date") is False


def test_guard_new_file_and_text(rep):
    p = rep / "latest_US.md"
    assert guard.write_text(p, "# US 스크리너 — 2026-10-16 [CONFIRMED]\n", asof="2026-10-16")
    assert guard.write_text(p, "# US 스크리너 — 2026-10-15 [CONFIRMED]\n", asof="2026-10-15") is False
    assert "2026-10-16" in p.read_text()
    assert guard.write_text(p, "# US 스크리너 — 2026-10-16 [CONFIRMED]\n생성 2026-10-17 09:47\n")   # asof 생략 = 머리 날짜


def test_guard_env_override(rep, monkeypatch):
    p = rep / "x.json"
    p.write_text(json.dumps({"asof": "2026-10-16"}))
    monkeypatch.setenv("SCREENER_ALLOW_REGRESS", "1")
    assert guard.write_json(p, {"asof": "2026-10-01"})


def test_detail_build_skips_when_regress(rep, monkeypatch):
    from screener import detail
    monkeypatch.setattr(detail, "REPORT_DIR", rep)
    d = rep / "detail" / "US"
    d.mkdir(parents=True)
    (d / "_index.json").write_text(json.dumps({"asof": "2026-10-16", "symbols": ["AAPL"]}))
    (d / "AAPL.json").write_text(json.dumps({"asof": "2026-10-16"}))
    last = pl.DataFrame({"symbol": ["AAPL"], "date": [date(2026, 10, 15)]})
    assert detail.build("US", last, last, None, [], "", {}) is None
    assert json.loads((d / "AAPL.json").read_text())["asof"] == "2026-10-16"   # 폴더 안 지워짐
    assert _fr(rep)["regress_blocked"][-1]["new"] == "2026-10-15"


# ── 거래일 기대일 ──
@pytest.mark.parametrize("market,now,exp", [
    ("KR", datetime(2026, 10, 16, 15, 0, tzinfo=KST), date(2026, 10, 15)),    # 평일 장중 → 전일
    ("KR", datetime(2026, 10, 16, 16, 5, tzinfo=KST), date(2026, 10, 16)),    # 장후 → 당일
    ("KR", datetime(2026, 10, 18, 12, 0, tzinfo=KST), date(2026, 10, 16)),    # 일요일 → 금
    ("KR", datetime(2026, 10, 5, 18, 0, tzinfo=KST), date(2026, 10, 2)),      # 개천절 대체휴일(월) → 금
    ("KR", datetime(2026, 10, 9, 20, 0, tzinfo=KST), date(2026, 10, 8)),      # 한글날(금)
    ("US", datetime(2026, 10, 17, 9, 46, tzinfo=KST), date(2026, 10, 16)),    # 토 09:46 KST = 금 20:46 ET → 금
    ("US", datetime(2026, 10, 16, 9, 46, tzinfo=KST), date(2026, 10, 15)),    # 금 아침 KST → 미 목요일
    ("US", datetime(2026, 10, 16, 4, 0, tzinfo=KST), date(2026, 10, 14)),     # 미 장중(목 15:00 ET) → 수
    ("US", datetime(2026, 11, 27, 9, 0, tzinfo=KST), date(2026, 11, 25)),     # 추수감사절(11/26) 다음 아침 → 11/25
])
def test_expected_session(market, now, exp):
    assert tradecal.expected_session(market, now) == exp


def test_expected_session_contract_form():
    # 계약: US 'd 다음날 07:30 KST' — 토 07:00 이면 아직 목요일분이 최신
    assert tradecal.expected_session("US", datetime(2026, 10, 17, 7, 0, tzinfo=KST), "07:30", "Asia/Seoul", 1) == date(2026, 10, 15)
    assert tradecal.expected_session("US", datetime(2026, 10, 17, 7, 31, tzinfo=KST), "07:30", "Asia/Seoul", 1) == date(2026, 10, 16)


# ── A. 10/17 토요일 detail_us 역행 재현 (가짜 now) ──
SAT = datetime(2026, 10, 17, 9, 46, tzinfo=KST)


def test_saturday_us_regress_is_refused():
    from screener.main import asof_decision
    # 9ea9efbd: Yahoo 응답 523종목 전부 마지막 봉 10/15, 게시본 10/16 → 예전 코드는 그대로 덮어씀. 이제 'regress' = 쓰지 않음
    assert asof_decision("US", date(2026, 10, 15), SAT, "2026-10-16") == "regress"
    assert asof_decision("US", date(2026, 10, 15), SAT, "2026-10-15") == "stale"     # 기대일 10/16 미달 → [STALE]
    assert asof_decision("US", date(2026, 10, 16), SAT, "2026-10-16") == "ok"
    assert asof_decision("US", date(2026, 10, 16), SAT, None) == "ok"


def _px(last_day: int) -> pl.DataFrame:
    rows = [{"yf": s, "date": date(2026, 10, d), "close": 1.0} for s in ("AAPL", "MSFT") for d in range(13, last_day + 1)]
    return pl.DataFrame(rows)


def test_fetch_with_retry_waits_for_expected_bar():
    from screener.main import fetch_with_retry
    calls = []
    seq = [_px(15), _px(16)]
    px, asof = fetch_with_retry(lambda: calls.append(1) or seq[len(calls) - 1], "US", SAT, tries=3, sleep_s=0)
    assert asof == date(2026, 10, 16) and len(calls) == 2


def test_fetch_with_retry_gives_up_and_returns_last():
    from screener.main import fetch_with_retry
    px, asof = fetch_with_retry(lambda: _px(15), "US", SAT, tries=2, sleep_s=0)
    assert asof == date(2026, 10, 15)


def test_status_accepts_fake_now():
    from screener.main import _status
    assert _status("America/New_York", False, SAT) == "CONFIRMED"
    assert _status("Asia/Seoul", False, datetime(2026, 10, 16, 10, 0, tzinfo=KST)) == "LIVE"


# ── C. 신선도 계약 ──
def _root(tmp_path, files: dict, items: list[dict]) -> Path:
    (tmp_path / "ops").mkdir(exist_ok=True)
    (tmp_path / "reports").mkdir(exist_ok=True)
    (tmp_path / "ops" / "freshness.json").write_text(json.dumps({"items": items}), encoding="utf-8")
    for k, v in files.items():
        p = tmp_path / k
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(v if isinstance(v, str) else json.dumps(v), encoding="utf-8")
    return tmp_path


DERIVS = {"id": "derivs", "path": "reports/derivs.json", "key": "date", "kind": "session", "market": "KR",
          "ready": "19:10", "tz": "Asia/Seoul", "day_offset": 0, "grace_min": 40, "mode": "briefing reports",
          "fix": "gh workflow run briefing.yml -f mode=derivs"}


def test_freshness_derivs_late_after_deadline(tmp_path):
    r = _root(tmp_path, {"reports/derivs.json": {"date": "2026-10-15"}}, [DERIVS])
    o = freshness.check(datetime(2026, 10, 16, 20, 0, tzinfo=KST), r, last_commit=None)
    assert [(x["id"], x["expected"], x["actual"]) for x in o["late"]] == [("derivs", "2026-10-16", "2026-10-15")]
    assert json.loads((r / "reports" / "freshness.json").read_text())["late"][0]["fix"].endswith("mode=derivs")
    o2 = freshness.check(datetime(2026, 10, 16, 18, 0, tzinfo=KST), r)    # 마감 전: 10/15 면 정상
    assert o2["late"] == []


def test_freshness_md_and_missing(tmp_path):
    it = {"id": "latest_us", "path": "reports/latest_US.md", "key": None, "kind": "session", "market": "US",
          "ready": "07:30", "tz": "Asia/Seoul", "day_offset": 1, "grace_min": 30}
    r = _root(tmp_path, {"reports/latest_US.md": "# US 스크리너 — 2026-10-15 [CONFIRMED]\n"}, [it, {**it, "id": "nofile", "path": "reports/none.json", "key": "asof"}])
    o = freshness.check(SAT, r)
    assert {x["id"]: x["actual"] for x in o["late"]} == {"latest_us": "2026-10-15", "nofile": "파일 없음"}


def test_freshness_intraday(tmp_path):
    it = {"id": "live_kr", "path": "reports/live.json", "key": "updated_at", "kind": "intraday", "market": "KR", "max_age_min": 120}
    r = _root(tmp_path, {"reports/live.json": {"updated_at": "10-16 09:05 KST"}}, [it])
    assert freshness.check(datetime(2026, 10, 16, 10, 0, tzinfo=KST), r)["late"] == []      # 개장 2시간 전엔 판정 안 함
    assert len(freshness.check(datetime(2026, 10, 16, 11, 30, tzinfo=KST), r)["late"]) == 1
    assert freshness.check(datetime(2026, 10, 16, 18, 0, tzinfo=KST), r)["late"] == []      # 장외


def test_freshness_team(tmp_path):
    it = {"id": "team", "path": "ops/team.json", "key": "updated", "kind": "team", "ready": "00:07", "tz": "Asia/Seoul", "grace_min": 30}
    r = _root(tmp_path, {"ops/team.json": {"updated": "2026-10-17T10:47+09:00"}}, [it])
    c = datetime(2026, 10, 17, 11, 0, tzinfo=KST)
    assert freshness.check(datetime(2026, 10, 17, 11, 20, tzinfo=KST), r, last_commit=c)["late"] == []   # 30분 안
    assert len(freshness.check(datetime(2026, 10, 17, 11, 31, tzinfo=KST), r, last_commit=c)["late"]) == 1
    r2 = _root(tmp_path, {"ops/team.json": {"updated": "2026-10-16T23:47+09:00"}}, [it])
    assert len(freshness.check(datetime(2026, 10, 17, 0, 40, tzinfo=KST), r2, last_commit=datetime(2026, 10, 16, 20, 0, tzinfo=KST))["late"]) == 1


def test_contract_file_is_valid():
    items = freshness.load_contract()
    ids = [i["id"] for i in items]
    assert len(ids) == len(set(ids)) >= 20
    assert "team" in ids and "detail_us" in ids and "derivs" in ids
    for i in items:
        assert i["kind"] in ("session", "intraday", "team", "toss_md") and i.get("fix") and i.get("mode")
        if i["kind"] == "session":
            assert i["market"] in ("KR", "US") and ":" in i["ready"]


def test_alert_once_per_day(tmp_path, monkeypatch):
    r = _root(tmp_path, {"reports/derivs.json": {"date": "2026-10-15"}}, [DERIVS])
    sent = []
    from screener import report
    monkeypatch.setattr(report, "send_telegram", lambda t, disable_notification=True: sent.append((t, disable_notification)))
    now = datetime(2026, 10, 16, 20, 10, tzinfo=KST)
    freshness.run(send=True, now=now, root=r)
    freshness.run(send=True, now=now, root=r)
    assert len(sent) == 1 and sent[0][1] is False and sent[0][0].startswith("⛔") and "mode=derivs" in sent[0][0]
    assert len(sent[0][0].splitlines()) <= 8
    freshness.run(send=True, now=datetime(2026, 10, 17, 8, 20, tzinfo=KST), root=r)    # 다음날 = 새 알림
    assert len(sent) == 2
    assert sent[1][1] is False                                                          # 다음날 = 다시 소리


def test_fresh_ring_once_per_item_per_day(tmp_path, monkeypatch):
    """결재 #9: 같은 항목이 같은 날 키만 바뀌어(기대일 변경) 다시 걸리면 알림은 가되 무음."""
    import json as _j
    r = _root(tmp_path, {"reports/derivs.json": {"date": "2026-10-15"}}, [DERIVS])
    sent = []
    from screener import report
    monkeypatch.setattr(report, "send_telegram", lambda t, disable_notification=True: sent.append((t, disable_notification)))
    now = datetime(2026, 10, 16, 20, 10, tzinfo=KST)
    freshness.run(send=True, now=now, root=r)
    sp = r / "reports" / freshness.STATE.name
    st = _j.loads(sp.read_text(encoding="utf-8"))
    assert st["rang"] == ["derivs"] or st["rang"]
    st["keys"] = []                                   # 같은 날, 새 키(다른 기대일)로 다시 걸린 상황
    sp.write_text(_j.dumps(st), encoding="utf-8")
    freshness.run(send=True, now=now, root=r)
    assert len(sent) == 2 and sent[0][1] is False and sent[1][1] is True
    assert freshness.item_of("late:derivs:2026-10-16") == "derivs"


# ── E. 조용한 대체 stale ──
def test_derivs_fallback_marks_stale(rep, monkeypatch):
    from screener import derivs
    monkeypatch.setattr(derivs, "OUT", rep / "derivs.json")
    monkeypatch.setattr(derivs, "HIST", rep / "derivs_hist.json")
    monkeypatch.setattr(derivs, "interpret", lambda c: [])
    monkeypatch.setitem(sys.modules, "pykrx", types.SimpleNamespace(stock=None))
    import time as _t
    monkeypatch.setattr(_t, "sleep", lambda s: None)

    class D(date):
        @classmethod
        def today(cls):
            return date(2026, 10, 16)
    monkeypatch.setattr(derivs, "date", D)
    seen = []

    def fake_read(d):
        seen.append(d)
        return None if d == date(2026, 10, 16) else {"date": str(d), "spot": 1.0}
    monkeypatch.setattr(derivs, "_read", fake_read)
    cur = derivs.build(backfill=0)
    assert seen.count(date(2026, 10, 16)) == 3                       # 목표일 3회 시도
    assert cur["stale"] == {"want": "2026-10-16", "got": "2026-10-15"}
    assert _fr(rep)["stale"][-1]["what"] == "옵션 보드"


def test_derivs_skips_krx_holiday(rep, monkeypatch):
    from screener import derivs

    class D(date):
        @classmethod
        def today(cls):
            return date(2026, 10, 9)     # 한글날(금) — 목표일은 10/8, stale 아님
    monkeypatch.setattr(derivs, "date", D)
    monkeypatch.setattr(derivs, "OUT", rep / "derivs.json")
    monkeypatch.setattr(derivs, "HIST", rep / "derivs_hist.json")
    monkeypatch.setattr(derivs, "interpret", lambda c: [])
    monkeypatch.setitem(sys.modules, "pykrx", types.SimpleNamespace(stock=None))
    monkeypatch.setattr(derivs, "_read", lambda d: {"date": str(d), "spot": 1.0})
    cur = derivs.build(backfill=0)
    assert cur["date"] == "2026-10-08" and "stale" not in cur


def test_bonds_stale_helper(rep):
    from screener import bonds
    o = {"asof": "2026-10-16"}
    bonds._stale(o, "etf", "2026-10-15")
    assert o["stale"]["etf"] == {"want": "2026-10-16", "got": "2026-10-15"}
    assert _fr(rep)["stale"][-1]["path"] == "reports/bonds.json"


# ── F. 저장 단계 역행 검사 (rebase -X theirs 뒤) ──
def test_regress_git_restores_remote_version(tmp_path, monkeypatch):
    import subprocess
    from screener import regress_git
    g = lambda *a: subprocess.run(["git", "-C", str(tmp_path), *a], check=True, capture_output=True, text=True).stdout  # noqa: E731
    g("init", "-q", "-b", "main")
    g("config", "user.email", "t@t"); g("config", "user.name", "t")
    (tmp_path / "ops").mkdir(); (tmp_path / "reports" / "detail" / "US").mkdir(parents=True)
    (tmp_path / "ops" / "freshness.json").write_text(json.dumps({"items": [
        {"id": "detail_us", "path": "reports/detail/US/_index.json", "key": "asof", "kind": "session", "market": "US", "ready": "07:30"},
        {"id": "momentum_us", "path": "reports/momentum_US.json", "key": "asof", "kind": "session", "market": "US", "ready": "07:30"}]}))
    w = lambda p, o: (tmp_path / p).write_text(json.dumps(o))  # noqa: E731
    w("reports/detail/US/_index.json", {"asof": "2026-10-16"}); w("reports/detail/US/AAPL.json", {"asof": "2026-10-16"})
    w("reports/momentum_US.json", {"asof": "2026-10-16"})
    g("add", "-A"); g("commit", "-qm", "base 10/16"); g("tag", "base")
    w("reports/detail/US/_index.json", {"asof": "2026-10-15"}); w("reports/detail/US/AAPL.json", {"asof": "2026-10-15"})
    w("reports/detail/US/NEW.json", {"asof": "2026-10-15"}); w("reports/momentum_US.json", {"asof": "2026-10-15"})
    g("add", "-A"); g("commit", "-qm", "briefing: detail_us (stale)")
    monkeypatch.setattr(regress_git, "ROOT", tmp_path)
    monkeypatch.setattr(guard, "_report_dir", lambda: tmp_path / "reports")
    assert [p for p, *_ in regress_git.regressed("base")] == ["reports/detail/US/_index.json", "reports/momentum_US.json"]
    regress_git.main(["--base", "base"])
    assert g("diff", "--name-only", "base", "HEAD").split() == ["reports/freshness.json"]
    assert "NEW.json" not in g("ls-files")
    assert len(g("log", "--oneline").splitlines()) == 2               # amend (커밋 수 그대로)
