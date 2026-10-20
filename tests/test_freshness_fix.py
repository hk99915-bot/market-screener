"""감사 M2 (2026-10-17 refactor_audit): ⛔ 신선도 알림의 복구 명령(ops/freshness.json fix)이 실제로 저장되는가.
결정 C 뒤 수동 dispatch 는 commit=auto(슬롯 밖이면 읽기 전용)·false 가 기본 → commit 입력이 있는 워크플로는 fix 에 `-f commit=true` 필수."""
import shlex
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from screener import freshness
from scripts import slot_guard

ROOT = Path(__file__).resolve().parents[1]


def _dispatch_inputs(wf: str) -> dict:
    d = yaml.safe_load((ROOT / ".github" / "workflows" / wf).read_text(encoding="utf-8"))
    on = d.get("on") or d.get(True) or {}
    return ((on.get("workflow_dispatch") or {}).get("inputs")) or {}


def _cmds():
    out = []
    for it in freshness.load_contract(ROOT / "ops" / "freshness.json"):
        fix = it.get("fix") or ""
        if fix.startswith("gh workflow run "):
            out.append((it["id"], fix))
    return out


def _parse(fix: str) -> tuple[str, dict]:
    t = shlex.split(fix)
    wf, args = t[3], {}
    for i, x in enumerate(t):
        if x == "-f":
            k, _, v = t[i + 1].partition("=")
            args[k] = v
    return wf, args


def test_every_item_has_a_command():
    cmds = _cmds()
    # kind=toss_md 는 워크플로가 아니라 겸이 노트북(작업 스케줄러)이 복구 주체 — gh 명령 없음 (10/21)
    items = [i for i in freshness.load_contract(ROOT / "ops" / "freshness.json") if i.get("kind") != "toss_md"]
    assert len(cmds) == len(items) >= 20


@pytest.mark.parametrize("iid,fix", _cmds())
def test_fix_commits_and_inputs_exist(iid, fix):
    wf, args = _parse(fix)
    inputs = _dispatch_inputs(wf)
    assert inputs, f"{iid}: {wf} 에 workflow_dispatch 입력 없음"
    assert set(args) <= set(inputs), f"{iid}: 없는 입력 {set(args) - set(inputs)}"
    if "commit" in inputs:   # 커밋하는 워크플로 — 복구가 저장되려면 commit=true
        assert args.get("commit") == "true", f"{iid}: 복구 명령에 -f commit=true 없음 → 슬롯 밖 수동 실행은 읽기 전용"
        ok, why = slot_guard.dispatch_commit(args["commit"], {"slots": []}, wf, args.get("mode", ""), datetime.now(timezone.utc))
        assert ok, why
    if wf == "briefing.yml":   # mode 값이 워크플로가 받는 목록 안
        modes = {m.strip() for m in inputs["mode"]["description"].split("|")}
        assert args.get("mode") in modes, f"{iid}: briefing mode={args.get('mode')} 없음"


def test_alert_text_shows_commit_true(tmp_path):
    o = {"checked_at": "2026-10-19 08:20", "late": [{"id": "detail_us", "path": "reports/detail/US/_index.json", "expected": "2026-10-16",
                                                      "actual": "2026-10-15", "mode": "m", "fix": dict(_cmds())["detail_us"]}]}
    text, _ = freshness.alert_text(o, set())
    assert "-f commit=true" in text
