"""미 서머타임 종료(2026-11-01) 대응 — 미장 시각을 KST 하드코딩 대신 America/New_York 으로 판정 (req-dev-cbd568fc)."""
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from screener import alphabook as A
from screener import tradecal as T

ROOT = Path(__file__).resolve().parents[1]
LIVE = ROOT / ".github" / "workflows" / "live.yml"


def test_us_open_kst_follows_dst():
    assert T.us_open_hhmm("2026-10-30") == "22:30"   # 여름(EDT)
    assert T.us_open_hhmm("2026-11-02") == "23:30"   # 겨울(EST) 첫 월요일
    assert T.us_open_hhmm("2027-03-12") == "23:30"   # 서머타임 시작(3/14) 직전
    assert T.us_open_hhmm("2027-03-15") == "22:30"


def test_alphabook_after_uses_open_not_fixed_22():
    kst = A.KST
    # 여름: 22시 이후 = 오늘 봉 / 겨울: 22:30 에도 아직 개장 전(23:30) → 마지막 완성 봉 다음
    assert A._after("US", datetime(2026, 10, 30, 22, 10, tzinfo=kst), "2026-10-29") == "2026-10-30"
    assert A._after("US", datetime(2026, 11, 2, 22, 40, tzinfo=kst), "2026-10-30") == "2026-10-30"
    assert A._after("US", datetime(2026, 11, 2, 23, 10, tzinfo=kst), "2026-10-30") == "2026-11-02"


def _in_window_script():
    text = LIVE.read_text(encoding="utf-8")
    m = re.search(r"( *)in_window\(\) \{.*?\n\1\}", text, re.S)
    assert m, "live.yml in_window() 없음"
    return m.group(0)


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash 필요")
@pytest.mark.parametrize("utc, want", [
    ("2026-10-30T13:20", True),    # 여름 22:20 KST = 09:20 EDT
    ("2026-10-30T20:10", True),    # 여름 05:10 KST = 16:10 EDT
    ("2026-11-02T13:20", False),   # 겨울 22:20 KST = 08:20 EST — 개장 전
    ("2026-11-02T14:20", True),    # 겨울 23:20 KST = 09:20 EST
    ("2026-11-02T20:10", True),    # 겨울 05:10 KST = 15:10 EST (예전 창은 05:15 에 끝남)
    ("2026-11-02T21:10", True),    # 겨울 06:10 KST = 16:10 EST
    ("2026-11-02T21:30", False),   # 겨울 06:30 KST = 16:30 EST
    ("2026-11-02T00:30", True),    # 국장 09:30 KST (변함 없음)
    ("2026-11-02T08:00", False),   # 17:00 KST
])
def test_in_window_by_ny_time(utc, want):
    epoch = int(datetime.fromisoformat(utc).replace(tzinfo=timezone.utc).timestamp())
    script = f"date() {{ command date -d @{epoch} \"$@\"; }}\n{_in_window_script()}\nin_window && echo Y || echo N"
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True).stdout.strip()
    assert (out == "Y") is want


def test_live_cron_winter_slots():
    cfg = yaml.safe_load(LIVE.read_text(encoding="utf-8"))
    crons = [c["cron"] for c in (cfg.get("on") or cfg.get(True))["schedule"]]
    # 두 계절 시작 cron 상시(10/30 금 밤 = 여름 22:30 개장도 지켜야 함) — 어느 쪽이 도는지는 in_window(ET)가 고른다
    assert "20 14 * * 1-5" in crons and "20 13 * * 1-5" in crons   # 23:20 · 22:20 KST 루프 시작
    assert "7 14-20 * * 1-5" in crons                                  # 백업 05:07 KST 까지
    gas = (ROOT / "apps-script" / "Scheduler.gs").read_text(encoding="utf-8")
    assert "['23:20', 'live.yml'" in gas and "['22:20', 'live.yml'" not in gas
