"""10/21 겸이 '왜 홈에 closed kr이 자꾸 뜨고, 늦은 데이터 오류가 자꾸 나는지' — 화면 장 상태 + 신선도 오탐 정리."""
import json
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from screener import freshness, tradecal

ROOT = Path(__file__).resolve().parents[1]
KST = freshness.KST


@pytest.mark.skipif(not shutil.which("node"), reason="node unavailable")
def test_session_phase_js():
    r = subprocess.run(["node", str(Path(__file__).with_suffix(".cjs"))], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_ui_holiday_table_matches_tradecal():
    html = (ROOT / "apps-script" / "Index.html").read_text(encoding="utf-8")
    for mk in ("KR", "US"):
        m = re.search(mk + r":'([\d\- ]+)'\.split", html)
        assert m, mk
        assert set(m.group(1).split()) == set(tradecal.HOLIDAYS[mk]), f"{mk} 휴장표: Index.html HOL 을 tradecal.HOLIDAYS 와 맞출 것"


def test_since_suppresses_pre_contract_expectation(monkeypatch):
    # 10/21 00:34 toss_md 계약 추가 → 00:38 '10/20 장중 publish' 늦음(첫 publish 00:48) 오탐
    from screener import toss_live
    monkeypatch.setattr(toss_live, "read_value", lambda url, key: (None, "원격 파일 없음/읽기 실패"))
    it = {"id": "toss_md", "path": "toss-live:live.json", "kind": "toss_md", "market": "KR", "window": "09:30-15:40", "max_age_min": 30}
    now = datetime(2026, 10, 21, 0, 38, tzinfo=KST)
    assert freshness.check_item(it, now) is not None
    assert freshness.check_item({**it, "since": "2026-10-21"}, now) is None
    # 계약 이후 날짜를 요구하면 그대로 늦음
    assert freshness.check_item({**it, "since": "2026-10-21"}, datetime(2026, 10, 22, 0, 38, tzinfo=KST)) is not None


def test_contract_toss_md_has_since():
    items = freshness.load_contract()
    assert next(i for i in items if i["id"] == "toss_md").get("since") == "2026-10-21"


def test_stale_resolved_and_known_note(tmp_path):
    (tmp_path / "reports").mkdir()
    (tmp_path / "ops").mkdir()
    (tmp_path / "reports" / "macro_series.json").write_text(json.dumps({"asof": "2026-10-21", "series": {}}), encoding="utf-8")
    (tmp_path / "reports" / "us.json").write_text(json.dumps({"asof": "2026-10-19"}), encoding="utf-8")
    stale = [{"at": "2026-10-19 09:02", "path": "reports/macro_series.json", "what": "KOSPI", "want": "2026-10-19", "got": "2026-10-16"},
             {"at": "2026-10-21 10:12", "path": "reports/us.json", "what": "US 시세 기준일", "want": "2026-10-20", "got": "2026-10-19"}]
    (tmp_path / "reports" / "freshness.json").write_text(json.dumps({"stale": stale}), encoding="utf-8")
    (tmp_path / "ops" / "freshness_known.json").write_text(json.dumps({"items": [
        {"ids": ["us"], "expected": "2026-10-20", "cause": "원천 지연", "owner": "개발", "action": "보충"}]}), encoding="utf-8")
    items = [{"id": "us", "path": "reports/us.json", "key": "asof", "kind": "session", "market": "US", "ready": "07:30",
              "tz": "Asia/Seoul", "day_offset": 1, "grace_min": 0}]
    o = freshness.check(datetime(2026, 10, 21, 10, 30, tzinfo=KST), tmp_path, items, write=False)
    assert [x["path"] for x in o["stale"]] == ["reports/us.json"]          # 해소된 macro_series 항목은 빠짐
    assert o["late"] and o["late"][0]["note"].startswith("원인: 원천 지연 · 담당: 개발 · 조치 중: 보충")
    assert o["stale_today"][0]["note"] == o["late"][0]["note"]


def test_calendar_asof_is_kst():
    # 러너 UTC → 09:00 KST 전 asof 가 전날로 찍혀 calendar '늦음' 오탐(10/19·10/20 10:21~15:09)
    code = [ln for ln in (ROOT / "screener" / "calendar_ev.py").read_text(encoding="utf-8").splitlines() if not ln.strip().startswith(('"""', "#"))]
    assert not [ln for ln in code if "datetime.now()" in ln or "date.today()" in ln]
