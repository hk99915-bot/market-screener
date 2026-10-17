"""감사 M3 (2026-10-17 refactor_audit): macro_series 최상위 asof = 전 시리즈 최대 날짜 → BTC(24시간)가 토요일로 끌어올려
KOSPI 갱신 실패를 신선도가 못 잡고, 16:20 손절선 점검은 log.info 로 조용히 빠졌다. 재현 + 수정 확인."""
import json
import logging
from datetime import date, datetime

import pytest

from screener import alerts, contracts, freshness, guard
from screener.tradecal import KST


def _row(d, c=5000.0):
    return [d, c, c, c, c, 0]


# 재현 픽스처: BTC 토요일(10/17) 갱신 · USDKRW 10/17 · KOSPI 는 10/15 에서 멈춤(10/16 금 갱신 실패)
SER = {"BTC": [_row("2026-10-16"), _row("2026-10-17")], "USDKRW": [_row("2026-10-17", 1400.0)],
       "KOSPI": [_row("2026-10-14"), _row("2026-10-15")], "SPX": [_row("2026-10-16")]}


@pytest.fixture
def rep(tmp_path, monkeypatch):
    r = tmp_path / "reports"
    r.mkdir()
    monkeypatch.setattr(guard, "_report_dir", lambda: r)
    monkeypatch.setattr(alerts, "REPORT_DIR", r)
    monkeypatch.delenv("SCREENER_ALLOW_REGRESS", raising=False)
    return r


def _item():
    return next(i for i in freshness.load_contract() if i["id"] == "macro_series")


def test_series_asof_separates_kospi():
    a = contracts.series_asof({"series": SER})
    assert a["asof_kr"] == "2026-10-15" and a["asof_by"]["BTC"] == "2026-10-17" and a["asof_by"]["SPX"] == "2026-10-16"
    assert contracts.series_asof({"series": {"KOSDAQ": [_row("2026-10-16")]}})["asof_kr"] == "2026-10-16"
    assert contracts.series_asof({"series": {}})["asof_kr"] is None


def test_write_json_stores_per_series_asof(rep):
    p = rep / "macro_series.json"
    assert guard.write_json(p, {"asof": "2026-10-17", "fmt": "dohlcv", "series": SER, "stale": {}})
    j = json.loads(p.read_text())
    assert j["asof"] == "2026-10-17" and j["asof_kr"] == "2026-10-15" and j["asof_by"]["BTC"] == "2026-10-17"


def test_freshness_flags_stale_kospi_despite_btc_saturday(rep):
    """BTC 토요일 갱신 · KOSPI 10/15 → 토 10:00 KST 기대일 10/16(금) → 늦음. 옛 키(asof)였다면 '정상'으로 지나감."""
    root = rep.parent
    guard.write_json(rep / "macro_series.json", {"asof": "2026-10-17", "fmt": "dohlcv", "series": SER, "stale": {}})
    sat = datetime(2026, 10, 17, 10, 0, tzinfo=KST)
    it = _item()
    assert it["key"] == "asof_kr"
    late = freshness.check_item(it, sat, root)
    assert late and late["expected"] == "2026-10-16" and late["actual"] == "2026-10-15"
    assert freshness.check_item({**it, "key": "asof"}, sat, root) is None      # 버그 재현: 최상위 asof 로는 못 잡음


def test_freshness_fallback_for_old_file_without_asof_kr(rep):
    root = rep.parent
    (rep / "macro_series.json").write_text(json.dumps({"asof": "2026-10-17", "fmt": "dohlcv", "series": SER}))
    late = freshness.check_item(_item(), datetime(2026, 10, 17, 10, 0, tzinfo=KST), root)
    assert late and late["actual"] == "2026-10-15"
    ok = {**SER, "KOSPI": SER["KOSPI"] + [_row("2026-10-16")]}
    (rep / "macro_series.json").write_text(json.dumps({"asof": "2026-10-17", "fmt": "dohlcv", "series": ok}))
    assert freshness.check_item(_item(), datetime(2026, 10, 19, 8, 20, tzinfo=KST), root) is None   # 월 08:20 — 금 종가면 정상


def test_guard_get_list_index():
    assert guard._get({"series": SER}, "series.KOSPI.-1.0") == "2026-10-15"
    assert guard._get({"series": SER}, "series.KOSPI.9.0") is None and guard._get({"a": [1]}, "a.x") is None


def _write(rep, ser):
    guard.write_json(rep / "macro_series.json", {"asof": "2026-10-19", "fmt": "dohlcv", "series": ser, "stale": {}})


def test_1620_stop_check_logs_and_records_when_kospi_stale(rep, monkeypatch, caplog):
    """월 10/19(거래일) 16:20: KOSPI 끝 행 10/16 → 경고 로그 + freshness stale 기록(조용한 건너뜀 금지)."""
    monkeypatch.setattr(alerts, "band_line", lambda: (None, None))
    monkeypatch.setattr(alerts, "touch_lines", lambda: [])
    _write(rep, {"KOSPI": [_row("2026-10-15", 5300.0), _row("2026-10-16", 5300.0)], "BTC": [_row("2026-10-19")]})
    with caplog.at_level(logging.WARNING, logger="screener.alerts"):
        alerts.build(at_close=True, today=date(2026, 10, 19))
    assert any("손절선 점검 못 함" in r.getMessage() for r in caplog.records)
    st = json.loads((rep / "freshness.json").read_text())["stale"]
    assert st[-1]["path"] == "reports/macro_series.json" and st[-1]["want"] == "2026-10-19" and st[-1]["got"] == "2026-10-16"


def test_1620_stop_check_runs_when_kospi_today_and_quiet_on_holiday(rep, monkeypatch, caplog):
    monkeypatch.setattr(alerts, "band_line", lambda: (None, None))
    monkeypatch.setattr(alerts, "touch_lines", lambda: [])
    monkeypatch.setenv("RULE_STOP_LEVEL", "5451")
    _write(rep, {"KOSPI": [_row("2026-10-16", 5400.0), _row("2026-10-19", 5400.0)]})
    out = alerts.build(at_close=True, today=date(2026, 10, 19))
    assert ("stop2" in [k for k, _ in out])                                    # 2일 연속 종가 < 5,451
    assert not (rep / "freshness.json").exists()
    with caplog.at_level(logging.WARNING, logger="screener.alerts"):
        alerts.build(at_close=True, today=date(2026, 10, 18))                  # 일요일 = KR 휴장 → 기록 없음
    assert not (rep / "freshness.json").exists() and not any("못 함" in r.getMessage() for r in caplog.records)


def test_touch_already_sent_by_event_watch_is_skipped(rep, monkeypatch, tmp_path):
    """코디네이터 요청(10/17): event_watch 가 장중에 보낸 touch:<코드> 를 14:25·16:20 규정 알림이 또 보내지 않는다."""
    ew = tmp_path / "event_state.json"
    ew.write_text(json.dumps({"sent": {"touch:000660": "2026-10-19 10:05"}}))
    monkeypatch.setenv("EVENT_STATE", str(ew))
    monkeypatch.setattr(alerts, "band_line", lambda: (None, None))
    monkeypatch.setattr(alerts, "touch_lines", lambda: [("touch:000660", "⛔ 하이닉스 터치"), ("touch:005930", "⛔ 삼성 터치")])
    keys = [k for k, _ in alerts.build(at_close=False, today=date(2026, 10, 19))]
    assert "touch:000660" not in keys and "touch:005930" in keys
