"""scripts/prepush_check.py — push 전 검사 훅 (10/20 '푸시 금지' 무시 사고 재발 방지)."""
import importlib.util
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("prepush_check", ROOT / "scripts" / "prepush_check.py")
pc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pc)


def test_core_change_runs_all():
    assert pc.tests_for(["screener/defs.py"]) is None


def test_test_file_itself_selected():
    assert pc.tests_for(["tests/test_prepush_check.py"]) == ["tests/test_prepush_check.py"]


def test_module_maps_to_its_tests():
    sel = pc.tests_for(["screener/research_views.py"])
    assert sel and "tests/test_research_views.py" in sel
    assert all(s.startswith("tests/test_") for s in sel)


def test_docs_only_selects_nothing():
    assert pc.tests_for(["docs/desk_kb/LOOP.md", "ops/board.json"]) == []


def test_any_failure_blocks(monkeypatch):
    calls = []
    monkeypatch.setattr(pc, "run", lambda name, cmd: calls.append(name) or name != "check_functions")
    monkeypatch.setattr(pc, "changed_files", lambda b, h="HEAD": [])
    assert pc.main([]) == 1
    assert "check_functions" in calls and "check_rules_terms" in calls   # 실패해도 나머지 검사 결과는 보여 준다


def test_all_pass(monkeypatch):
    monkeypatch.setattr(pc, "run", lambda name, cmd: True)
    monkeypatch.setattr(pc, "changed_files", lambda b, h="HEAD": ["README.md"])
    assert pc.main([]) == 0


def test_hook_branch_delete_is_noop(monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO(f"(delete) {pc.ZERO} refs/heads/x {'a' * 40}\n"))
    monkeypatch.setattr(pc, "main", lambda a=None: 1)
    assert pc.hook_main() == 0


def test_hook_file_calls_checker():
    h = (ROOT / ".githooks" / "pre-push").read_text(encoding="utf-8")
    assert "prepush_check.py" in h and "--hook" in h


def test_core_bare_true_blocks(monkeypatch):
    monkeypatch.setattr(pc, "git", lambda *a: "true" if a[:2] == ("config", "--get") else "")
    monkeypatch.setattr(pc, "run", lambda name, cmd: True)
    assert pc.main([]) == 1
