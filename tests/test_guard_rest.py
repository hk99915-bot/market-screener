"""guard-rest (보드, 10/17): live.json·dashboard_state.json 에 asof 단조 가드 + 계약. 장중 시각은 분 단위·KST 로 비교."""
import json
from datetime import datetime, timedelta

import pytest

from screener import dashboard, guard, live
from screener.guard import KST


@pytest.fixture
def rep(tmp_path, monkeypatch):
    r = tmp_path / "reports"
    r.mkdir()
    monkeypatch.setattr(guard, "_report_dir", lambda: r)
    monkeypatch.delenv("SCREENER_ALLOW_REGRESS", raising=False)
    return r


def _fr(rep):
    return json.loads((rep / "freshness.json").read_text(encoding="utf-8"))


# ── 비교 규칙 ──
def test_not_older_minute_and_timezone():
    assert guard.not_older("2026-10-17 09:47", "2026-10-17 09:52")            # 같은 날 늦은 시각 = 정상 장중 갱신
    assert guard.not_older("2026-10-17 09:47", "2026-10-17 09:47:30")         # 같은 분
    assert not guard.not_older("2026-10-17 10:05", "2026-10-17 09:50")        # 같은 날 이른 시각 = 역행
    # 일 단위 버그 재현: UTC 표기 23:55Z(=KST 08:55)는 앞 10자로 읽으면 '10-16' → 하루 전으로 오판해 막혔다
    assert guard.day("2026-10-16T23:55:00Z") < guard.day("2026-10-17 08:50")
    assert guard.not_older("2026-10-17 08:50", "2026-10-16T23:55:00Z")       # KST 로 바꾸면 5분 뒤 → 허용
    assert guard.not_older("2026-10-17 08:50", "2026-10-17T08:55:00+09:00")
    assert not guard.not_older("2026-10-17 08:50", "2026-10-16T23:40:00Z")   # KST 08:40 → 역행
    assert guard.not_older("2026-10-17 15:30", "2026-10-17")                  # 한쪽 날짜만 → 일 단위(같은 날 허용)
    assert not guard.not_older("2026-10-17", "2026-10-16 23:59")


# ── live.json ──
def _offline_live(monkeypatch, rep):
    monkeypatch.setattr(live, "REPORT_DIR", rep)
    monkeypatch.setattr(live, "kr_indices", lambda: {"KOSPI": {"last": 5600.0, "chg": 0.01, "src": "test"}})
    monkeypatch.setattr(live, "yahoo", lambda keys: {"SPX": {"last": 6000.0, "chg": -0.01, "src": "test"}})

    def _no_net(*a, **k):
        raise OSError("offline")
    monkeypatch.setattr("requests.get", _no_net)


def test_live_intraday_update_passes(rep, monkeypatch):
    _offline_live(monkeypatch, rep)
    before = (datetime.now(KST) - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M")
    (rep / "live.json").write_text(json.dumps({"asof": before, "updated_at": before[5:] + " KST", "items": []}), encoding="utf-8")
    out = live.snapshot()
    d = json.loads((rep / "live.json").read_text(encoding="utf-8"))
    assert d["asof"] == out["asof"] > before and [x["key"] for x in d["items"]] == ["KOSPI", "SPX"]
    assert not (rep / "freshness.json").exists()                                   # 차단 기록 없음


def test_live_regress_blocked(rep, monkeypatch):
    _offline_live(monkeypatch, rep)
    later = (datetime.now(KST) + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M")   # 다른 러너가 이미 더 늦은 스냅샷을 씀
    (rep / "live.json").write_text(json.dumps({"asof": later, "updated_at": "x", "items": [{"key": "KEEP"}]}), encoding="utf-8")
    live.snapshot()
    assert json.loads((rep / "live.json").read_text(encoding="utf-8"))["items"] == [{"key": "KEEP"}]
    rb = _fr(rep)["regress_blocked"][-1]
    assert rb["path"].endswith("live.json") and rb["existing"] == later and len(rb["new"]) == 16   # 분 단위 라벨


def test_live_legacy_file_without_asof_is_overwritten(rep, monkeypatch):
    _offline_live(monkeypatch, rep)
    (rep / "live.json").write_text(json.dumps({"updated_at": "10-17 09:47 KST", "items": []}), encoding="utf-8")   # 10/17 이전 형식
    live.snapshot()
    assert "asof" in json.loads((rep / "live.json").read_text(encoding="utf-8"))


# ── dashboard_state.json ──
@pytest.fixture
def st(rep, monkeypatch):
    f = rep / "dashboard_state.json"
    monkeypatch.setattr(dashboard, "STATE", f)
    monkeypatch.setattr(dashboard, "REPORT_DIR", rep)
    return f


def _st(f):
    return json.loads(f.read_text(encoding="utf-8"))


def test_state_piece_regress_blocked_others_written(st, rep):
    assert dashboard.put_state("telegram_US", "16일 요약", asof="2026-10-16")
    assert dashboard.put_state("telegram_US", "15일 재실행", asof="2026-10-15") is False   # 10/17 detail_us 역행 류
    assert _st(st)["telegram_US"]["value"] == "16일 요약"
    rb = _fr(rep)["regress_blocked"][-1]
    assert rb["path"].endswith("dashboard_state.json#telegram_US") and rb["existing"] == "2026-10-16" and rb["new"] == "2026-10-15"
    assert dashboard.put_state("macro_US", [1], asof="2026-10-15")                        # 다른 조각은 영향 없음
    assert dashboard.put_state("telegram_US", "17일", asof="2026-10-17") and _st(st)["telegram_US"]["asof"] == "2026-10-17"


def test_state_intraday_pieces_never_blocked_by_day_granularity(st):
    assert dashboard.put_state("intraday_snapshot", {"v": 1}, asof="2026-10-17 10:30")
    assert dashboard.put_state("intraday_snapshot", {"v": 2}, asof="2026-10-17 13:35")   # 같은 날 늦은 시각
    assert dashboard.put_state("intraday_snapshot", {"v": 3}, asof="2026-10-17")         # 날짜만 = 같은 날 허용
    assert dashboard.put_state("intraday_snapshot", {"v": 4}, asof="2026-10-17T05:40:00Z")   # KST 14:40
    assert dashboard.put_state("intraday_kr", "asof 없는 조각")                            # asof 없음 → 항상 씀
    assert dashboard.put_state("intraday_kr", "두 번째")
    assert _st(st)["intraday_snapshot"]["value"] == {"v": 4} and _st(st)["intraday_kr"]["value"] == "두 번째"
    assert dashboard.put_state("intraday_snapshot", {"v": 5}, asof="2026-10-17 14:10") is False   # 14:40 뒤 14:10 = 역행


def test_state_broken_piece_and_bypass(st, rep, monkeypatch):
    st.write_text(json.dumps({"broken": "문자열 조각"}), encoding="utf-8")                  # 기존 조각이 깨져도
    assert dashboard.put_state("close_KR", "ok", asof="2026-10-16")                          # 새 조각은 씀
    monkeypatch.setenv("SCREENER_ALLOW_REGRESS", "1")
    assert dashboard.put_state("close_KR", "백필", asof="2026-10-01")
