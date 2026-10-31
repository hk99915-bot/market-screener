"""컴플 스킬 시범 — 구조·KB 번호 누락·night_rules 동작(임시 git 저장소, 네트워크 없음).
실행: python3 -m pytest .claude/skills/compliance-desk/scripts/test_night_rules.py (tests/ 밖이라 기본 수집 대상 아님)."""
import os
import re
import subprocess
import sys
from pathlib import Path

SK = Path(__file__).resolve().parents[1]
ROOT = SK.parents[2]
sys.path.insert(0, str(SK / "scripts"))
import night_rules as nr  # noqa: E402


def test_skill_frontmatter_and_refs():
    t = (SK / "SKILL.md").read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", t, re.S)
    assert m
    fm = dict(l.split(":", 1) for l in m.group(1).splitlines() if ":" in l)
    assert fm["name"].strip() == "compliance-desk" and fm["description"].strip()
    assert len(t.splitlines()) <= 125
    for ref in re.findall(r"`references/([\w.]+)`", t):
        assert (SK / "references" / ref).exists(), ref


def test_references_cover_every_kb_item():
    kb = (ROOT / "docs" / "desk_kb" / "compliance.md").read_text(encoding="utf-8").splitlines()
    refs = set()
    for f in (SK / "references").glob("*.md"):
        refs |= set(f.read_text(encoding="utf-8").splitlines())
    items = [l for l in kb if re.match(r"^(- #\d+|\| \[|- 드릴 )", l)]
    assert len(items) >= 15
    missing = [l[:40] for l in items if l not in refs]
    assert not missing, missing


def _git(repo, *a, when=None):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    for k in [k for k in env if k.startswith("GIT_") and k not in
              ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL")]:
        env.pop(k)
    if when:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = when
    subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, env=env)


def test_night_rules_scan(tmp_path, capsys):
    _git(tmp_path, "init", "-q")
    cases = [("screener/defs.py", "2026-10-20T23:30:00+09:00", "밤 규칙"),
             ("screener/defs.py", "2026-10-21T10:00:00+09:00", "낮 규칙"),
             ("README.md", "2026-10-21T02:00:00+09:00", "밤 비규칙"),
             ("ops/cooldown.json", "2026-10-22T06:59:00+09:00", "새벽 입력")]
    for i, (f, when, msg) in enumerate(cases):
        p = tmp_path / f
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(str(i))
        _git(tmp_path, "add", f)
        _git(tmp_path, "commit", "-q", "-m", msg, when=when)
    assert nr.main([str(tmp_path), "2026-10-20", "2026-10-22"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "커밋 4 · 22~07시 3 · 그중 규칙 파일 2"
    assert "10-22 06:59 새벽 입력 | ops/cooldown.json" in out[1] and "10-20 23:30 밤 규칙 | screener/defs.py" in out[2]  # git log 최신순
    assert nr.main([str(tmp_path), "2026-10-20", "2026-10-22", "--extra", "README.md"]) == 0
    assert capsys.readouterr().out.splitlines()[0].endswith("규칙 파일 3")


def test_is_night_edges():
    from datetime import datetime
    assert nr.is_night(datetime(2026, 10, 1, 22, 0, tzinfo=nr.KST))
    assert nr.is_night(datetime(2026, 10, 1, 6, 59, tzinfo=nr.KST))
    assert not nr.is_night(datetime(2026, 10, 1, 7, 0, tzinfo=nr.KST))
