"""scripts/data_branch.py — A1 시범(US 상세 data 고아 브랜치) 동작: 고아 커밋·역행 차단·빈 실행 차단·site 합치기."""
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("data_branch", Path(__file__).resolve().parents[1] / "scripts" / "data_branch.py")
db = importlib.util.module_from_spec(spec)
spec.loader.exec_module(db)

P = "reports/detail/US"


def sh(cwd, *a):
    return subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def write_detail(wt: Path, asof: str, n: int = 4):
    d = wt / P
    d.mkdir(parents=True, exist_ok=True)
    for f in d.glob("*.json"):
        f.unlink()
    (d / "_index.json").write_text(json.dumps({"asof": asof, "symbols": [f"S{i}" for i in range(n)]}))
    for i in range(n):
        (d / f"S{i}.json").write_text(json.dumps({"asof": asof, "close": i}))


@pytest.fixture
def repo(tmp_path):
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    wt = tmp_path / "wt"
    subprocess.run(["git", "clone", "-q", str(bare), str(wt)], check=True, capture_output=True)
    for k, v in (("user.name", "t"), ("user.email", "t@t")):
        sh(wt, "config", k, v)
    (wt / "index.html").write_text("<!doctype html>")
    (wt / "data" / "fin").mkdir(parents=True)
    (wt / "data" / "fin" / "big.parquet").write_text("x")
    (wt / "reports").mkdir()
    (wt / "reports" / "dashboard.json").write_text("{}")
    write_detail(wt, "2026-10-15")
    sh(wt, "add", "-A")
    sh(wt, "commit", "-qm", "init")
    sh(wt, "push", "-q", "origin", "HEAD:main")
    return wt, bare


def test_push_creates_orphan_and_skips_same(repo):
    wt, bare = repo
    write_detail(wt, "2026-10-16")
    assert db.push([P], cwd=wt) == "pushed"
    sha = sh(bare, "rev-parse", "data")
    assert sh(bare, "rev-list", "--count", sha) == "1"                       # 부모 없음 = 이력 없음
    files = sh(bare, "ls-tree", "-r", "--name-only", sha).splitlines()
    assert all(f.startswith(P + "/") for f in files) and len(files) == 5      # US 상세만
    assert sh(wt, "status", "--porcelain") .count("reports/detail/US") >= 1     # 작업 트리·색인 그대로(커밋 안 됨)
    assert db.push([P], cwd=wt) == "same"
    write_detail(wt, "2026-10-17")
    assert db.push([P], cwd=wt) == "pushed"
    assert sh(bare, "rev-list", "--count", "data") == "1"                     # 강제 갱신 후에도 1커밋


def test_push_blocks_regress_and_shrink(repo):
    wt, _ = repo
    write_detail(wt, "2026-10-16")
    db.push([P], cwd=wt)
    write_detail(wt, "2026-10-15")
    assert db.push([P], cwd=wt) == "regress"                                  # 10/17 detail_us 역행 사례
    write_detail(wt, "2026-10-17", n=1)
    assert db.push([P], cwd=wt) == "shrink"


def test_pull_respects_asof(repo):
    wt, _ = repo
    write_detail(wt, "2026-10-16")
    db.push([P], cwd=wt)
    write_detail(wt, "2026-10-17")                                            # 로컬이 더 새로움 → 덮지 않음
    assert db.pull([P], cwd=wt) == []
    write_detail(wt, "2026-10-14")
    assert db.pull([P], cwd=wt) == [P]
    assert json.loads((wt / P / "_index.json").read_text())["asof"] == "2026-10-16"


def test_pull_without_branch_is_noop(repo):
    wt, _ = repo
    assert db.pull([P], cwd=wt) == []


def test_site_merges_and_excludes(repo, tmp_path):
    wt, _ = repo
    write_detail(wt, "2026-10-16")
    db.push([P], cwd=wt)
    sh(wt, "checkout", "-q", "--", P)                                         # main 판(10/15)으로 되돌린 뒤 site
    out = tmp_path / "_site"
    r = db.site(out, [P], cwd=wt)
    assert r["overlaid"] == [P]
    assert json.loads((out / P / "_index.json").read_text())["asof"] == "2026-10-16"
    assert (out / "index.html").exists() and (out / "reports" / "dashboard.json").exists()
    assert not (out / "data" / "fin").exists() and not (out / ".git").exists()


def test_site_stage2_folder_absent_on_main(repo, tmp_path):
    """2단계: main 에서 US 상세를 지운 뒤에도 site 가 data 브랜치에서 채운다."""
    wt, _ = repo
    write_detail(wt, "2026-10-16")
    db.push([P], cwd=wt)
    sh(wt, "rm", "-rq", "--cached", P)
    sh(wt, "commit", "-qm", "rm US detail")
    out = tmp_path / "_site"
    db.site(out, [P], cwd=wt)
    assert len(list((out / P).glob("*.json"))) == 5
