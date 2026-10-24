import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("tr", Path(__file__).resolve().parents[1] / "scripts" / "team_run.py")
tr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tr)


def test_add_dedupes_same_day_owner_task():
    t = {"runs": [{"date": "2026-10-17", "owner": "개발", "task": "x", "tokens": 1}]}
    tr.add(t, {"date": "2026-10-17", "owner": "개발", "task": "x", "tokens": 2})
    tr.add(t, {"date": "2026-10-17", "owner": "PM", "task": "x", "tokens": 3})
    assert [r["tokens"] for r in t["runs"]] == [2, 3]


def test_add_normalizes_owner_key():
    t = {"runs": []}
    tr.add(t, {"date": "2026-10-21", "owner": "dev", "task": "x", "tokens": 1})
    tr.add(t, {"date": "2026-10-21", "owner": "개발", "task": "x", "tokens": 2})
    tr.add(t, {"date": "2026-10-21", "owner": "hf", "task": "y", "tokens": 3})
    assert [(r["owner"], r["tokens"]) for r in t["runs"]] == [("개발", 2), ("HF", 3)]


def test_normalize_existing_rows():
    t = {"runs": [{"owner": "analyst"}, {"owner": "애널"}, {"owner": "FRM"}, {"owner": "PB(메인)"}]}
    assert tr.normalize(t) == 2
    assert [r["owner"] for r in t["runs"]] == ["애널", "애널", "리스크", "PB(메인)"]
