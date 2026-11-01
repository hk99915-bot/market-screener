"""board.py --due·--note (2026-11-01 PM 늦은 일 정리: 마감 재설정·근거 1줄을 JSON 직접 편집 없이)."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(tmp, *args):
    (tmp / "scripts").mkdir(); (tmp / "ops").mkdir()
    shutil.copy(ROOT / "scripts" / "board.py", tmp / "scripts" / "board.py")
    task = {"id": "x", "title": "t", "owner": "개발", "priority": "P2", "status": "대기",
            "started": None, "due": "2026-10-28", "files": [], "depends_on": [], "notes": "원래"}
    (tmp / "ops" / "board.json").write_text(json.dumps({"tasks": [task]}, ensure_ascii=False), encoding="utf-8")
    r = subprocess.run([sys.executable, str(tmp / "scripts" / "board.py"), *args], capture_output=True, text=True)
    return r, json.loads((tmp / "ops" / "board.json").read_text(encoding="utf-8"))["tasks"][0]


def test_due_and_note(tmp_path):
    r, t = _run(tmp_path, "--due", "x", "2026-11-10", "--note", "x", "11/01 PM: 근거")
    assert r.returncode == 0, r.stderr
    assert t["due"] == "2026-11-10" and t["notes"] == "원래 | 11/01 PM: 근거"


def test_due_clear_and_bad_format(tmp_path):
    r, t = _run(tmp_path, "--due", "x", "11/10")
    assert r.returncode == 1 and t["due"] == "2026-10-28"
    r2, t2 = _run(tmp_path / "b" if (tmp_path / "b").mkdir() is None else tmp_path, "--due", "x", "-")
    assert r2.returncode == 0 and t2["due"] is None


def test_unknown_id(tmp_path):
    r, _ = _run(tmp_path, "--note", "nope", "x")
    assert r.returncode == 1


def test_crowded_dues_warns_over_cap():
    sys.path.insert(0, str(ROOT / "scripts"))
    import board
    mk = lambda i, d, st="대기": {"id": f"t{i}", "status": st, "due": d}
    tasks = [mk(i, "2026-11-03") for i in range(6)] + [mk(9, "2026-11-04")] + [mk(10 + i, "2026-11-05", "완료") for i in range(7)]
    assert board.crowded_dues(tasks) == [("2026-11-03", 6)]
    assert board.crowded_dues(tasks, since="2026-11-04") == []
    assert board.crowded_dues(tasks[:5]) == []
