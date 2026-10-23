"""prepush CI 빨강 게이트 (감사 D2) — 빨강이면 [ci-fix] 수리 커밋만, 데이터·조회실패는 통과."""
from scripts import prepush_check as p

RED = {"conclusion": "failure", "sha": "abcd1234", "url": "u"}


def test_green_passes():
    assert p.ci_gate_decision({"conclusion": "success", "sha": "x"}, ["screener/a.py"], "dev: x")[0]


def test_red_blocks_code_push_without_tag():
    ok, why = p.ci_gate_decision(RED, ["screener/a.py"], "dev: 기능 추가")
    assert not ok and "[ci-fix]" in why


def test_red_allows_fix_commit_and_data_only():
    assert p.ci_gate_decision(RED, ["tests/test_a.py"], "dev: 수리 [ci-fix]")[0]
    assert p.ci_gate_decision(RED, ["reports/x.json", "ops/board.json"], "briefing: data")[0]


def test_lookup_failure_is_fail_open():
    assert p.ci_gate_decision(None, ["screener/a.py"], "x")[0]


def test_fetch_parses_and_swallows_errors():
    assert p.latest_tests_run("o/r", fetch=lambda u: {"workflow_runs": [{"conclusion": "failure", "head_sha": "abcdef123456", "html_url": "h"}]})["sha"] == "abcdef12"
    assert p.latest_tests_run("o/r", fetch=lambda u: (_ for _ in ()).throw(OSError("x"))) is None
    assert p.latest_tests_run("o/r", fetch=lambda u: {"workflow_runs": []}) is None
