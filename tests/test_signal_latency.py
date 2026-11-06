"""screener/latency.py — 신호 슬롯→계산→커밋 지연 (11/6 ⚡ 급락 신호 실측 재현)."""
from datetime import datetime
from zoneinfo import ZoneInfo

from screener import latency

KST = ZoneInfo("Asia/Seoul")


def test_crash_1106_measured_within_sla():
    sent = {"2026-11-05:crash": "2026-11-05 15:10", "2026-11-06:crash": "2026-11-06 15:09",
            "2026-11-06:stop1": "2026-11-06 16:47"}
    c = {"2026-11-06:crash": datetime(2026, 11, 6, 15, 9, 34, tzinfo=KST)}   # 99251d1e5 커밋 시각
    rows = latency.measure(sent, "2026-11-06", c)
    assert [r["key"] for r in rows] == ["2026-11-06:crash", "2026-11-06:stop1"]   # 어제 키 제외
    r = rows[0]
    assert r["slot_lag_s"] == 240 and r["commit_lag_s"] == 34 and r["margin_s"] == 660 and r["ok"]
    s = rows[1]   # 슬롯 모르는 종류 → 커밋 지연만(없으면 None), 위반 아님
    assert s["slot"] is None and s["slot_lag_s"] is None and s["commit_lag_s"] is None and s["ok"]


def test_breach_late_dispatch_and_thin_margin():
    rows = latency.measure({"2026-11-06:crash": "2026-11-06 15:14"}, "2026-11-06")
    assert rows[0]["breach"] == ["slot_lag_s", "margin_s"] and not rows[0]["ok"]


def test_run_keeps_prev_commit_on_shallow_clone(tmp_path):
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "alerts_state.json").write_text('{"sent": {"2026-11-06:crash": "2026-11-06 15:09"}}')
    prev = [{"key": "2026-11-06:crash", "committed": "2026-11-06 15:09:34"}]
    o = latency.run(tmp_path, datetime(2026, 11, 6, 20, 10, tzinfo=KST), prev)   # git 저장소 아님 → 이전 값 보존
    assert o["rows"][0]["commit_lag_s"] == 34 and o["sla"]["slot_lag_s"] == 300
