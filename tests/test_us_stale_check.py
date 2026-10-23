"""08:52 KST detail_us_retry 문지기 (req-dev-fc677ec8) — US 상세가 기대 거래일보다 과거일 때만 재시도."""
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from scripts import us_stale_check as u

KST = ZoneInfo("Asia/Seoul")


def _idx(tmp_path, asof):
    p = tmp_path / "_index.json"
    p.write_text(json.dumps({"asof": asof}), encoding="utf-8")
    return p


def test_stale_when_published_behind_expected(tmp_path):
    now = datetime(2026, 10, 22, 8, 52, tzinfo=KST)        # 목 08:52 → 기대 US 거래일 10/21
    stale, why = u.is_stale(now, _idx(tmp_path, "2026-10-20"))
    assert stale and "STALE" in why


def test_fresh_skips(tmp_path):
    now = datetime(2026, 10, 22, 8, 52, tzinfo=KST)
    stale, _ = u.is_stale(now, _idx(tmp_path, "2026-10-21"))
    assert not stale


def test_unreadable_index_retries(tmp_path):
    now = datetime(2026, 10, 22, 8, 52, tzinfo=KST)
    stale, _ = u.is_stale(now, tmp_path / "missing.json")
    assert stale


def test_workflow_wires_retry_slot():
    from pathlib import Path
    t = (Path(__file__).resolve().parents[1] / ".github/workflows/briefing.yml").read_text(encoding="utf-8")
    assert '"52 23 * * 1-5") MODE=detail_us_retry' in t and "scripts/us_stale_check.py" in t
