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


def test_checks_run_without_git_env(monkeypatch):
    """훅 환경의 GIT_DIR 등이 검사 하위 프로세스로 새면 tmp 저장소 git 명령이 실제 저장소를 바꾼다(10/21 core.bare)."""
    monkeypatch.setenv("GIT_DIR", "/nonexistent")
    monkeypatch.setenv("GIT_INDEX_FILE", "/nonexistent/index")
    env = pc.clean_env()
    assert not any(k.startswith("GIT_") for k in env) and "PATH" in env


# ── index.html 낡음 검사 (req-dev-7406791f) ──────────────────────────
def _fake_show(files: dict):
    return lambda rev, path: files.get(path)


def _built(index_src: str, tabs: dict) -> str:
    sys.path.insert(0, str(ROOT / "scripts"))
    import build_pages as bp
    return bp.build(bp.resolve_includes(index_src, lambda n: tabs[n]))


def test_pages_stale_detects_tab_change_without_rebuild():
    shell, tabs = "<!doctype html><title>MARKET TERMINAL</title><?!= include('tab_a') ?></html>", {"tab_a": "<div id=a>old</div>"}
    files = {"apps-script/Index.html": shell, "apps-script/tab_a.html": tabs["tab_a"], "index.html": _built(shell, tabs)}
    assert pc.pages_stale("H", _fake_show(files)) is False
    files["apps-script/tab_a.html"] = "<div id=a>new</div>"          # 10/29 사고: 탭만 고치고 재생성 안 함
    assert pc.pages_stale("H", _fake_show(files)) is True


def test_pages_stale_unknown_when_index_missing():
    assert pc.pages_stale("H", _fake_show({"apps-script/Index.html": "<!doctype html>"})) is None


def test_pages_check_skips_unrelated_push(monkeypatch):
    monkeypatch.setattr(pc, "changed_files", lambda b, h: ["screener/duel.py"])
    monkeypatch.setattr(pc, "pages_stale", lambda h: True)
    assert pc.pages_check(None) is True


def test_pages_check_blocks_stale(monkeypatch):
    monkeypatch.setattr(pc, "changed_files", lambda b, h: ["apps-script/tab_life.html"])
    monkeypatch.setattr(pc, "pages_stale", lambda h: True)
    assert pc.pages_check(None) is False


def test_current_head_index_is_fresh():
    assert pc.pages_stale("HEAD") in (False, None)
