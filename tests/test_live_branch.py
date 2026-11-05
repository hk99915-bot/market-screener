"""scripts/live_branch.py — live-data 브랜치: put(fast-forward·역행/축소 차단)·get·squash·check(되돌림 트리거) + 브랜치 상수 1곳 (보드 data-live-branch)."""
import importlib.util
import json
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("live_branch", ROOT / "scripts" / "live_branch.py")
lb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lb)
KST = timezone(timedelta(hours=9))


def sh(cwd, *a):
    return subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def env(tmp_path):
    bare = tmp_path / "origin.git"
    sh(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    w = tmp_path / "w"
    sh(tmp_path, "clone", "-q", str(bare), str(w))
    sh(w, "config", "user.email", "t@t"); sh(w, "config", "user.name", "t")
    (w / "reports").mkdir()
    return w


def wr(w, name, obj):
    (w / "reports" / name).write_text(json.dumps(obj, ensure_ascii=False))


def main_commit(w, msg="m"):
    sh(w, "add", "-A", "-f"); sh(w, "commit", "-qm", msg); sh(w, "push", "-q", "origin", "HEAD:main")


def test_branch_constant_single_place():
    """브랜치 이름은 live_branch.LIVE_BRANCH 한 곳 — 화면 상수 LIVE_BASE(있다면)와 워크플로가 같은 이름을 쓴다."""
    assert lb.LIVE_BRANCH == "live-data"
    for p in list((ROOT / "apps-script").glob("*.html")) + [ROOT / "scripts" / "build_pages.py"]:
        for m in re.finditer(r"LIVE_BASE\s*=\s*'([^']+)'", p.read_text(encoding="utf-8")):
            assert m.group(1).rstrip("/").endswith("/" + lb.LIVE_BRANCH), p.name
    for p in (ROOT / ".github" / "workflows").glob("*.yml"):
        assert "origin/live-data" not in p.read_text(encoding="utf-8"), p.name


def test_stamp_formats():
    assert lb.stamp(json.dumps({"asof": "2026-11-05 09:11 KST"})) == "2026-11-05 09:11"
    assert lb.stamp(json.dumps({"updated_at": "11-05 09:11 KST", "checked_at": "2026-11-05 08:56"})) == "2026-11-05 08:56"
    assert lb.stamp(json.dumps({"items": []})) == "" and lb.stamp("not json") == ""


def test_put_creates_branch_then_fast_forwards_with_history(env):
    wr(env, "live.json", {"asof": "2026-11-05 09:00", "v": 1})
    r1 = lb.put(["reports/live.json"], cwd=env)
    assert r1["status"] == "pushed"
    wr(env, "live.json", {"asof": "2026-11-05 09:05", "v": 2})
    r2 = lb.put(["reports/live.json"], cwd=env)
    assert r2["status"] == "pushed"
    assert sh(env.parent / "origin.git", "rev-list", "--count", "live-data") == "2"      # 이력 쌓임(squash 전까지)
    assert lb.put(["reports/live.json"], cwd=env)["status"] == "same"          # 같으면 커밋 안 함
    assert sh(env, "ls-remote", "--heads", "origin", "main") == ""             # main 은 건드리지 않음(빈 원격)


def test_put_blocks_regress_and_shrink(env):
    wr(env, "live.json", {"asof": "2026-11-05 09:10", "items": list(range(50))})
    lb.put(["reports/live.json"], cwd=env)
    wr(env, "live.json", {"asof": "2026-11-05 09:00", "items": list(range(50))})   # 과거 시각
    r = lb.put(["reports/live.json"], cwd=env)
    assert "역행" in r["files"]["reports/live.json"] and r["status"] == "same"
    wr(env, "decisions.json", {"items": list(range(500))})
    lb.put(["reports/decisions.json"], cwd=env)
    wr(env, "decisions.json", {"items": []})                                       # 빈 실행(시각 없는 파일 = 크기로)
    assert "축소" in lb.put(["reports/decisions.json"], cwd=env)["files"]["reports/decisions.json"]
    got = lb.get(["reports/decisions.json"], cwd=env)
    assert json.loads((env / "reports/decisions.json").read_text())["items"] == list(range(500)) and got["reports/decisions.json"] == "덮음"


def test_put_retries_when_push_rejected(env, monkeypatch):
    """두 실행이 동시에 쓰면 한쪽 push 가 거부 → 다시 받아 그 위에 얹는다(데이터 안 잃음, 강제 push 없음)."""
    wr(env, "live.json", {"asof": "2026-11-05 09:00"})
    lb.put(["reports/live.json"], cwd=env)
    other = env.parent / "w2"
    sh(env.parent, "clone", "-q", str(env.parent / "origin.git"), str(other))
    (other / "reports").mkdir(exist_ok=True)
    wr(other, "heatmap_KR.json", {"asof": "2026-11-05 09:01"})
    real_fetch, state = lb.fetch, {"n": 0}

    def racing_fetch(remote, cwd=lb.ROOT):
        sha = real_fetch(remote, cwd)
        if state["n"] == 0:
            state["n"] = 1
            lb.put(["reports/heatmap_KR.json"], cwd=other)       # 내가 받은 직후 다른 실행이 먼저 얹음
        return sha
    monkeypatch.setattr(lb, "fetch", racing_fetch)
    wr(env, "live.json", {"asof": "2026-11-05 09:05"})
    r = lb.put(["reports/live.json"], cwd=env)
    assert r["status"] == "pushed" and r["attempt"] == 2
    monkeypatch.setattr(lb, "fetch", real_fetch)
    sha = real_fetch("origin", env)
    assert "reports/heatmap_KR.json" in sh(env, "ls-tree", "-r", "--name-only", sha)   # 다른 실행분이 남아 있음


def test_get_does_not_overwrite_newer_local(env):
    wr(env, "live.json", {"asof": "2026-11-05 09:00"})
    lb.put(["reports/live.json"], cwd=env)
    wr(env, "live.json", {"asof": "2026-11-05 09:30"})
    assert "더 새로움" in lb.get(["reports/live.json"], cwd=env)["reports/live.json"]
    assert json.loads((env / "reports/live.json").read_text())["asof"] == "2026-11-05 09:30"


def test_get_without_branch_keeps_main_copy(env):
    wr(env, "live.json", {"asof": "x"})
    assert "브랜치 없음" in lb.get(["reports/live.json"], cwd=env)["reports/live.json"]


def test_squash_makes_single_orphan_commit(env):
    for i in range(3):
        wr(env, "live.json", {"asof": f"2026-11-05 09:0{i}"})
        lb.put(["reports/live.json"], cwd=env)
    assert lb.squash(cwd=env)["status"] == "squashed"
    sha = lb.fetch("origin", env)
    assert sh(env, "show", f"{sha}:reports/live.json") and "주간 초기화" in sh(env, "log", "-1", "--format=%s", sha)
    assert sh(env, "rev-list", "--parents", "-n1", sha).split() == [sha]      # 부모 없음


def test_check_triggers_rollback_on_mismatch_or_stale(env):
    now = datetime(2026, 11, 5, 10, 0, tzinfo=KST)
    wr(env, "live.json", {"asof": "2026-11-05 09:55"})
    main_commit(env)
    lb.put(["reports/live.json"], cwd=env)
    assert lb.check(["reports/live.json"], cwd=env, now=now)["rollback"] is False
    # (a) 신선도 > 20분
    r = lb.check(["reports/live.json"], cwd=env, now=now + timedelta(minutes=30))
    assert r["rollback"] and r["stale"] and not r["mismatches"]
    # (b) main 이 더 새로움(병행 불일치 1건)
    wr(env, "live.json", {"asof": "2026-11-05 09:58"})
    main_commit(env)
    r = lb.check(["reports/live.json"], cwd=env, now=now)
    assert r["rollback"] and len(r["mismatches"]) == 1
    # (c) 같은 시각인데 내용이 다름
    wr(env, "live.json", {"asof": "2026-11-05 09:58", "x": 1}); lb.put(["reports/live.json"], cwd=env)
    wr(env, "live.json", {"asof": "2026-11-05 09:58", "x": 2}); main_commit(env)
    assert lb.check(["reports/live.json"], cwd=env, now=now)["mismatches"]
    # 병행 끝(--no-parallel) 이면 신선도만
    assert not lb.check(["reports/live.json"], cwd=env, now=now, parallel=False)["rollback"]


def test_check_missing_branch_is_rollback(env):
    assert lb.check(cwd=env)["rollback"] is True
