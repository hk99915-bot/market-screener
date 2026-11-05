"""고빈도 JSON(live·events·decisions·heatmap·intraday·freshness)을 main 이 아니라 `live-data` 브랜치에 둔다 (보드 data-live-branch, 겸이 11/4 18:28 결재 · 개발).

  python scripts/live_branch.py put   [FILES...]            # 작업 트리의 파일을 live-data 맨 위에 1커밋 (fast-forward push, 강제 아님)
  python scripts/live_branch.py get   [FILES...] [--dest D] # live-data 의 최신본을 작업 트리(또는 D)에 받음 — 읽는 워크플로 스텝
  python scripts/live_branch.py squash                       # 주 1회 초기화: 현재 트리를 부모 없는 커밋 1개로 (force-with-lease)
  python scripts/live_branch.py check [--max-age-min 20]     # 병행 대조: main 사본 vs live-data 사본, 신선도 → 되돌림 트리거 판정(종료코드 1)

원칙 (보드 피어 조건 ①~④)
- 브랜치 이름 상수는 이 파일 `LIVE_BRANCH` 한 곳. 화면의 직접 URL 상수(`LIVE_BASE`, TOSS_BASE 패턴)는 tests/test_live_branch.py 가 같은지 검사한다.
- 쓰는 길은 `put` 하나(분산 쓰기 금지). 일반 push 만 — 동시에 두 실행이 쓰면 한쪽이 거부돼 다시 받아 얹는다(최대 4회). 매일 force-push 없음, `squash` 만 주 1회.
- 역행 차단: 파일 안 시각(asof·checked_at·updated_at)이 원격보다 과거면 그 파일은 얹지 않음. 시각이 없는 파일(decisions·event_state)은 크기 절반 미만 축소만 막는다.
- 되돌림 숫자: `check` — 병행 기간 main 사본과 불일치 1건 이상 또는 live-data 신선도 > 20분 1회 → 종료코드 1(그날 main 복귀, 워크플로가 LIVE_BRANCH_ON 변수를 끈다).
- 작업 트리·색인을 건드리지 않는다(임시 GIT_INDEX_FILE).
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KST = timezone(timedelta(hours=9))
LIVE_BRANCH = "live-data"          # ← 브랜치 이름은 여기 한 곳. 화면 상수 LIVE_BASE 는 이것과 같아야 한다(테스트).
FILES = [                           # live-data 가 진실인 파일 (보드 제목의 여섯 묶음)
    "reports/live.json", "reports/events.json", "reports/events_stats.json", "reports/event_state.json",
    "reports/decisions.json", "reports/heatmap_KR.json", "reports/heatmap_US.json", "reports/intraday_last.json",
    "reports/freshness.json",
]
TS_KEYS = ("asof", "checked_at", "updated_at")
MAX_AGE_MIN = 20
_TS = re.compile(r"(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})")


def git(*a: str, cwd: Path = ROOT, env: dict | None = None, check: bool = True, binary: bool = False):
    r = subprocess.run(["git", *a], cwd=cwd, env={**os.environ, **(env or {})}, capture_output=True, text=not binary)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(a)} 실패: {r.stderr if not binary else r.stderr.decode(errors='replace')}")
    return r


def stamp(text: str | bytes | None) -> str:
    """파일 안 시각 'YYYY-MM-DD HH:MM'(KST 표기 그대로). 없으면 ''."""
    try:
        d = json.loads(text) if text else {}
    except Exception:  # noqa: BLE001
        return ""
    if isinstance(d, dict):
        for k in TS_KEYS:
            m = _TS.search(str(d.get(k) or ""))
            if m:
                return f"{m.group(1)} {m.group(2)}"
    return ""


def fetch(remote: str, cwd: Path = ROOT) -> str | None:
    r = git("fetch", "-q", "--depth=1", remote, f"+refs/heads/{LIVE_BRANCH}:refs/remotes/{remote}/{LIVE_BRANCH}", cwd=cwd, check=False)
    if r.returncode != 0:
        return None
    return git("rev-parse", f"refs/remotes/{remote}/{LIVE_BRANCH}", cwd=cwd).stdout.strip()


def show(rev: str, path: str, cwd: Path = ROOT) -> str | None:
    r = git("show", f"{rev}:{path}", cwd=cwd, check=False)
    return r.stdout if r.returncode == 0 else None


_IDENT = {"GIT_AUTHOR_NAME": "screener-bot", "GIT_AUTHOR_EMAIL": "screener-bot@users.noreply.github.com",
          "GIT_COMMITTER_NAME": "screener-bot", "GIT_COMMITTER_EMAIL": "screener-bot@users.noreply.github.com"}


def _guard(path: str, local: str, remote: str | None) -> str | None:
    """얹지 않을 이유(없으면 None)."""
    if remote is None:
        return None
    a, b = stamp(local), stamp(remote)
    if a and b and a < b:
        return f"역행: 로컬 {a} < live-data {b}"
    if not a and len(local) < len(remote) * 0.5:
        return f"축소: {len(local)}B < live-data {len(remote)}B/2"
    return None


def put(files: list[str] | None = None, remote: str = "origin", cwd: Path = ROOT, tries: int = 4, dry: bool = False) -> dict:
    files = [f for f in (files or FILES) if (cwd / f).is_file()]
    out: dict = {"status": "same", "files": {}}
    for i in range(tries):
        rsha = fetch(remote, cwd)
        with tempfile.TemporaryDirectory() as td:
            env = {"GIT_INDEX_FILE": str(Path(td) / "idx")}
            if rsha:
                git("read-tree", rsha, cwd=cwd, env=env)
            for f in files:
                loc = (cwd / f).read_text(encoding="utf-8")
                why = _guard(f, loc, show(rsha, f, cwd) if rsha else None)
                out["files"][f] = why or "ok"
                if not why:
                    git("add", "-f", "--", f, cwd=cwd, env=env)
            tree = git("write-tree", cwd=cwd, env=env).stdout.strip()
        if rsha and git("rev-parse", f"{rsha}^{{tree}}", cwd=cwd).stdout.strip() == tree:
            return out
        msg = f"live {datetime.now(timezone.utc):%Y-%m-%dT%H:%MZ}"
        args = ["commit-tree", tree, "-m", msg] + (["-p", rsha] if rsha else [])
        sha = git(*args, cwd=cwd, env=_IDENT).stdout.strip()
        if dry:
            return {**out, "status": "dry", "sha": sha}
        r = git("push", "-q", remote, f"{sha}:refs/heads/{LIVE_BRANCH}", cwd=cwd, check=False)   # 강제 아님 — 거부되면 다시 받아 얹는다
        if r.returncode == 0:
            return {**out, "status": "pushed", "sha": sha, "attempt": i + 1}
        out["files"] = {}
    return {**out, "status": "failed"}


def get(files: list[str] | None = None, remote: str = "origin", cwd: Path = ROOT, dest: Path | None = None) -> dict:
    dest = dest or cwd
    rsha = fetch(remote, cwd)
    res: dict = {}
    if not rsha:
        return {f: "브랜치 없음 — main 사본 유지" for f in (files or FILES)}
    take = []
    for f in files or FILES:
        rem = show(rsha, f, cwd)
        if rem is None:
            res[f] = "live-data 에 없음 — 유지"
            continue
        lp = dest / f
        loc = lp.read_text(encoding="utf-8") if lp.exists() else ""
        a, b = stamp(loc), stamp(rem)
        if a and b and b < a:
            res[f] = f"main 사본 {a} 이 더 새로움 — 덮지 않음"
            continue
        take.append(f)
        res[f] = "덮음"
    if take:
        raw = git("archive", "--format=tar", rsha, "--", *take, cwd=cwd, binary=True).stdout
        with tarfile.open(fileobj=io.BytesIO(raw)) as t:
            t.extractall(dest, filter="data") if sys.version_info >= (3, 12) else t.extractall(dest)
    return res


def squash(remote: str = "origin", cwd: Path = ROOT, dry: bool = False) -> dict:
    """주 1회 초기화 — 현재 트리를 부모 없는 커밋 1개로. force-with-lease(그 사이 누가 얹었으면 실패 → 다음 주기)."""
    rsha = fetch(remote, cwd)
    if not rsha:
        return {"status": "no-branch"}
    tree = git("rev-parse", f"{rsha}^{{tree}}", cwd=cwd).stdout.strip()
    iso = datetime.now(KST).isocalendar()
    sha = git("commit-tree", tree, "-m", f"live-data: 주간 초기화 {iso[0]}-W{iso[1]:02d}", cwd=cwd, env=_IDENT).stdout.strip()
    if dry:
        return {"status": "dry", "sha": sha}
    r = git("push", "-q", f"--force-with-lease=refs/heads/{LIVE_BRANCH}:{rsha}", remote, f"{sha}:refs/heads/{LIVE_BRANCH}", cwd=cwd, check=False)
    return {"status": "squashed" if r.returncode == 0 else "lease-failed", "sha": sha}


def check(files: list[str] | None = None, remote: str = "origin", cwd: Path = ROOT, max_age_min: int = MAX_AGE_MIN,
          now: datetime | None = None, parallel: bool = True) -> dict:
    """병행 대조 + 신선도. mismatches/stale 가 하나라도 있으면 rollback=True (보드 피어 조건 ④)."""
    now = now or datetime.now(KST)
    rsha = fetch(remote, cwd)
    if not rsha:
        return {"rollback": True, "why": "live-data 브랜치 없음", "mismatches": [], "stale": []}
    mrev = git("rev-parse", f"refs/remotes/{remote}/main", cwd=cwd, check=False).stdout.strip() or "HEAD"
    mism, stale = [], []
    for f in files or FILES:
        b = show(rsha, f, cwd)
        if b is None:
            mism.append(f"{f}: live-data 에 없음")
            continue
        ts = stamp(b)
        if ts and (now - datetime.strptime(ts, "%Y-%m-%d %H:%M").replace(tzinfo=KST)) > timedelta(minutes=max_age_min):
            stale.append(f"{f}: {ts} (>{max_age_min}분)")
        if parallel:
            m = show(mrev, f, cwd)
            if m is not None and ((stamp(m) and stamp(m) > ts) or (stamp(m) == ts and m != b)):
                mism.append(f"{f}: main {stamp(m) or '-'} ≠ live-data {ts or '-'}")
    return {"rollback": bool(mism or stale), "mismatches": mism, "stale": stale, "checked_at": now.strftime("%Y-%m-%d %H:%M")}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["put", "get", "squash", "check"])
    ap.add_argument("files", nargs="*")
    ap.add_argument("--remote", default="origin")
    ap.add_argument("--dest")
    ap.add_argument("--max-age-min", type=int, default=MAX_AGE_MIN)
    ap.add_argument("--no-parallel", action="store_true", help="main 병행 기간이 끝났으면(되돌림 대조 불필요) 신선도만")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    if a.cmd == "put":
        r = put(a.files or None, a.remote, dry=a.dry)
    elif a.cmd == "get":
        r = get(a.files or None, a.remote, dest=Path(a.dest).resolve() if a.dest else None)
    elif a.cmd == "squash":
        r = squash(a.remote, dry=a.dry)
    else:
        r = check(a.files or None, a.remote, max_age_min=a.max_age_min, parallel=not a.no_parallel)
    print(json.dumps(r, ensure_ascii=False, indent=1))
    return 1 if (a.cmd == "check" and r.get("rollback")) or r.get("status") in ("failed", "lease-failed") else 0


if __name__ == "__main__":
    sys.exit(main())
