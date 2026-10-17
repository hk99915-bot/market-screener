"""A1 시범(refactor_plan 결정 A·단계 3): 큰 산출물을 이력 없는 `data` 고아 브랜치에 두고, Pages 는 main + data 를 합쳐 게시.

  python scripts/data_branch.py push reports/detail/US      # 작업 트리의 그 폴더만으로 고아 커밋 1개 → origin/data 강제 갱신
  python scripts/data_branch.py pull reports/detail/US      # origin/data 의 그 폴더를 작업 트리에 덮어씀(색인 asof 가 같거나 새로울 때만)
  python scripts/data_branch.py site --out _site reports/detail/US   # Pages 산출물 폴더 = main 작업 트리 + data 덮어쓰기(제외 목록 적용)

원칙
- data 브랜치는 매번 부모 없는 커밋 1개로 덮는다(이력 없음 → 저장소가 안 붇는다). 어제 값이 필요하면 archive 스냅샷.
- 역행 금지: 폴더의 `_index.json` asof 가 원격보다 과거면 push 하지 않고, 원격이 로컬보다 과거면 pull/site 에서 덮지 않는다
  (screener/guard.py 와 같은 기준 — 폴더 통째는 색인 1개로 판정).
- 빈 실행 방지: 파일 수가 원격의 절반 미만이면 push 거부.
- 작업 트리·색인(index)을 건드리지 않는다: push 는 임시 GIT_INDEX_FILE, pull 은 git archive | tar.
롤백: 워크플로 변수 DATA_BRANCH_US / PAGES_ACTIONS 를 끄면 예전(main 커밋 + 브랜치 배포) 그대로.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRANCH = "data"
# Pages 에 올리지 않는 경로(브라우저가 읽지 않는 큰 원천 데이터·도구). 화면 fetch 는 reports/·ops/·content/·data/deriv/ 뿐.
SITE_EXCLUDE = {".git", ".github", ".claude", "data/fin", "data/hist", "tests", "__pycache__"}
SITE_EXCLUDE_SUFFIX = (".parquet", ".pyc")


def git(*a: str, cwd: Path = ROOT, env: dict | None = None, check: bool = True, binary: bool = False):
    r = subprocess.run(["git", *a], cwd=cwd, env={**os.environ, **(env or {})}, capture_output=True,
                       text=not binary)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(a)} 실패: {r.stderr if not binary else r.stderr.decode(errors='replace')}")
    return r


def index_asof(text: str | bytes | None) -> str:
    try:
        return str(json.loads(text).get("asof") or "")[:10] if text else ""
    except Exception:
        return ""


def fetch_remote(remote: str, cwd: Path = ROOT) -> str | None:
    """origin/data 를 얕게 받아 커밋 sha. 브랜치가 없으면 None."""
    r = git("fetch", "-q", "--depth=1", remote, f"+refs/heads/{BRANCH}:refs/remotes/{remote}/{BRANCH}", cwd=cwd, check=False)
    if r.returncode != 0:
        return None
    return git("rev-parse", f"refs/remotes/{remote}/{BRANCH}", cwd=cwd).stdout.strip()


def remote_file(sha: str, path: str, cwd: Path = ROOT) -> str | None:
    r = git("show", f"{sha}:{path}", cwd=cwd, check=False)
    return r.stdout if r.returncode == 0 else None


def count_files(sha: str, path: str, cwd: Path = ROOT) -> int:
    out = git("ls-tree", "-r", "--name-only", sha, "--", path, cwd=cwd, check=False).stdout
    return len([x for x in out.splitlines() if x])


def push(paths: list[str], remote: str = "origin", cwd: Path = ROOT, dry: bool = False) -> str:
    for p in paths:
        if not (cwd / p).is_dir():
            raise SystemExit(f"push: {p} 폴더 없음")
    rsha = fetch_remote(remote, cwd)
    for p in paths:
        loc = index_asof((cwd / p / "_index.json").read_text(encoding="utf-8") if (cwd / p / "_index.json").exists() else None)
        rem = index_asof(remote_file(rsha, f"{p}/_index.json", cwd)) if rsha else ""
        if loc and rem and loc < rem:
            print(f"⛔ 역행 차단: {p} 로컬 asof {loc} < data 브랜치 {rem} — push 안 함")
            return "regress"
        n_loc = sum(1 for _ in (cwd / p).rglob("*") if _.is_file())
        n_rem = count_files(rsha, p, cwd) if rsha else 0
        if n_rem and n_loc < n_rem / 2:
            print(f"⛔ 빈 실행 의심: {p} 파일 {n_loc} < data 브랜치 {n_rem}/2 — push 안 함")
            return "shrink"
    with tempfile.TemporaryDirectory() as td:
        env = {"GIT_INDEX_FILE": str(Path(td) / "idx")}
        git("add", "-A", "-f", "--", *paths, cwd=cwd, env=env)
        tree = git("write-tree", cwd=cwd, env=env).stdout.strip()
    if rsha and git("rev-parse", f"{rsha}^{{tree}}", cwd=cwd).stdout.strip() == tree:
        print("data 브랜치와 같음 — push 생략")
        return "same"
    asofs = ",".join(index_asof((cwd / p / "_index.json").read_text(encoding="utf-8")) if (cwd / p / "_index.json").exists() else "?"
                     for p in paths)
    msg = f"data: {' '.join(paths)} asof {asofs} ({datetime.now(timezone.utc):%Y-%m-%dT%H:%MZ})"
    ident = {"GIT_AUTHOR_NAME": "screener-bot", "GIT_AUTHOR_EMAIL": "screener-bot@users.noreply.github.com",
             "GIT_COMMITTER_NAME": "screener-bot", "GIT_COMMITTER_EMAIL": "screener-bot@users.noreply.github.com"}
    sha = git("commit-tree", tree, "-m", msg, cwd=cwd, env=ident).stdout.strip()   # 부모 없음 = 고아 커밋
    if dry:
        print(f"(dry) {sha} {msg}")
        return "dry"
    git("push", "-q", "--force", remote, f"{sha}:refs/heads/{BRANCH}", cwd=cwd)
    print(f"data 브랜치 갱신: {sha[:10]} {msg}")
    return "pushed"


def _extract(sha: str, paths: list[str], dest: Path, cwd: Path = ROOT) -> None:
    raw = git("archive", "--format=tar", sha, "--", *paths, cwd=cwd, binary=True).stdout
    with tarfile.open(fileobj=io.BytesIO(raw)) as t:
        t.extractall(dest, filter="data") if sys.version_info >= (3, 12) else t.extractall(dest)


def pull(paths: list[str], remote: str = "origin", cwd: Path = ROOT, dest: Path | None = None) -> list[str]:
    """data 브랜치 폴더를 dest(기본 작업 트리)에 덮어씀. 원격 asof 가 dest 의 것보다 과거인 폴더는 건너뜀. 덮은 폴더 목록."""
    dest = dest or cwd
    rsha = fetch_remote(remote, cwd)
    if not rsha:
        print("data 브랜치 없음 — main 판 그대로 사용")
        return []
    done = []
    for p in paths:
        rem_txt = remote_file(rsha, f"{p}/_index.json", cwd)
        if rem_txt is None:
            print(f"data 브랜치에 {p} 없음 — 건너뜀")
            continue
        loc_f = dest / p / "_index.json"
        loc = index_asof(loc_f.read_text(encoding="utf-8")) if loc_f.exists() else ""
        rem = index_asof(rem_txt)
        if loc and rem and rem < loc:
            print(f"data 브랜치 {p} asof {rem} < 현재 {loc} — 덮지 않음(main 판이 더 새로움)")
            continue
        _extract(rsha, [p], dest, cwd)
        print(f"{p}: data 브랜치 asof {rem or '?'} 로 덮음 (현재 {loc or '-'})")
        done.append(p)
    return done


def _excluded(rel: str) -> bool:
    return any(rel == e or rel.startswith(e + "/") or f"/{e}/" in f"/{rel}/" for e in SITE_EXCLUDE) or rel.endswith(SITE_EXCLUDE_SUFFIX)


def site(out: Path, paths: list[str], remote: str = "origin", cwd: Path = ROOT) -> dict:
    """Pages 산출물: HEAD(main) 추적 파일 - 제외 목록 → out, 그 위에 data 브랜치 폴더(역행 아닐 때)."""
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    _extract("HEAD", ["."], out, cwd)
    for f in sorted(out.rglob("*"), reverse=True):
        rel = f.relative_to(out).as_posix()
        if _excluded(rel):
            shutil.rmtree(f) if f.is_dir() else f.unlink()
    over = pull(paths, remote, cwd, dest=out)
    n = sum(1 for f in out.rglob("*") if f.is_file())
    size = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    print(f"site: {out} 파일 {n} · {size / 1e6:.1f} MB · data 덮음 {over or '없음'}")
    return {"files": n, "bytes": size, "overlaid": over}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["push", "pull", "site"])
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--remote", default="origin")
    ap.add_argument("--out", default="_site")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    if a.cmd == "push":
        push(a.paths, a.remote, dry=a.dry)
    elif a.cmd == "pull":
        pull(a.paths, a.remote)
    else:
        site(Path(a.out).resolve(), a.paths, a.remote)
    return 0


if __name__ == "__main__":
    sys.exit(main())
