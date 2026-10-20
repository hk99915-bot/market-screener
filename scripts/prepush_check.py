"""push 전 필수 검사 (pre-push 훅이 부른다) — 하나라도 실패하면 exit 1 → git 이 push 를 막는다.

10/20 사고: check_functions 가 '푸시 금지'를 냈는데 `a && b; git push` 같은 명령 체인 때문에 push 가 진행됨.
→ 사람이 출력 문구를 읽는 대신 git 훅의 종료 코드로 막는다. 우회(--no-verify) 금지 — docs/desk_kb/LOOP.md.

검사(빠른 것만, 목표 30초 이내):
  1) python3 scripts/board.py --check
  2) python3 scripts/check_functions.py
  3) python3 scripts/check_rules_terms.py
  4) pytest 서브셋 — push 될 커밋들이 바꾼 파일과 관련된 테스트만:
     tests/test_*.py 를 직접 바꿨으면 그 파일, screener/X.py·scripts/X.py 를 바꿨으면 그 모듈 이름을
     import/언급하는 테스트. 공용 모듈(CORE)이 바뀌었거나 서브셋이 MAX_SUBSET 개를 넘으면 전체(≈15초).
사용: python3 scripts/prepush_check.py [--base <rev>] [--all]   (훅은 stdin 의 push 범위로 base 를 정한다)
Actions 봇 push 에는 적용되지 않는다: core.hooksPath 는 로컬 git 설정이고 러너의 checkout 은 설정하지 않음.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ZERO = "0" * 40
CORE = {"screener/config.py", "screener/defs.py", "screener/guard.py", "screener/contracts.py", "screener/tradecal.py",
        "requirements.txt", "pytest.ini", "tests/conftest.py"}
MAX_SUBSET = 25


def git(*a: str) -> str:
    r = subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def changed_files(base: str | None, head: str = "HEAD") -> list[str]:
    if not base:
        base = git("merge-base", head, "origin/main") or "origin/main"
    out = git("diff", "--name-only", f"{base}..{head}")
    return [x for x in out.splitlines() if x]


def tests_for(files: list[str]) -> list[str] | None:
    """관련 테스트 경로 목록. None = 전체 실행."""
    if any(f in CORE for f in files):
        return None
    tests = sorted((ROOT / "tests").glob("test_*.py"))
    picked: set[str] = set()
    mods = []
    for f in files:
        p = Path(f)
        if f.startswith("tests/") and p.name.startswith("test_") and p.suffix == ".py":
            if (ROOT / f).exists():
                picked.add(f)
        elif p.suffix == ".py" and p.parts[0] in ("screener", "scripts"):
            mods.append((p.parts[0], p.stem))
        elif f.startswith("tests/fixtures/"):
            mods.append(("fixture", p.name))
    if mods:
        texts = {t: t.read_text(encoding="utf-8", errors="replace") for t in tests}
        for kind, name in mods:
            if kind == "fixture":
                rx = re.compile(re.escape(name))
            elif kind == "screener":
                rx = re.compile(rf"\bscreener\.{name}\b|from screener import[^\n]*\b{name}\b|from \.{name}\b|\b{name}\.py\b")
            else:
                rx = re.compile(rf"\b{re.escape(name)}\b")
            for t, txt in texts.items():
                if rx.search(txt):
                    picked.add(str(t.relative_to(ROOT)))
    if len(picked) > MAX_SUBSET:
        return None
    return sorted(picked)


def run(name: str, cmd: list[str]) -> bool:
    t = time.time()
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    ok = r.returncode == 0
    print(f"  {'✓' if ok else '✗'} {name} ({time.time() - t:.1f}s)")
    if not ok:
        print("\n".join((r.stdout + r.stderr).strip().splitlines()[-25:]))
    return ok


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", help="비교 기준 rev (기본: origin/main 과의 merge-base)")
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--all", action="store_true", help="pytest 전체")
    a = ap.parse_args(argv)
    t0 = time.time()
    py = sys.executable or "python3"
    print("pre-push 검사 (우회 --no-verify 금지 — LOOP.md)")
    ok = run("board --check", [py, "scripts/board.py", "--check"])
    ok &= run("check_functions", [py, "scripts/check_functions.py"])
    ok &= run("check_rules_terms", [py, "scripts/check_rules_terms.py"])
    files = changed_files(a.base, a.head)
    sel = None if a.all else tests_for(files)
    if sel is None:
        ok &= run("pytest 전체", [py, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider"])
    elif sel:
        ok &= run(f"pytest 서브셋 {len(sel)}개", [py, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", *sel])
    else:
        print(f"  - pytest: 변경 {len(files)}개 파일과 관련된 테스트 없음 (건너뜀)")
    print(f"{'통과' if ok else '실패 — push 차단'} ({time.time() - t0:.1f}s)")
    return 0 if ok else 1


def hook_main() -> int:
    """pre-push 훅 진입점: stdin 'local_ref local_sha remote_ref remote_sha' 줄들에서 범위를 잡는다."""
    base = head = None
    for line in sys.stdin.read().splitlines():
        parts = line.split()
        if len(parts) != 4 or parts[1] == ZERO:      # 브랜치 삭제 push 는 검사할 것 없음
            continue
        head = parts[1]
        if parts[3] != ZERO and git("cat-file", "-t", parts[3]) == "commit":
            base = git("merge-base", parts[1], parts[3]) or parts[3]
    if head is None:
        return 0                                       # 보낼 커밋 없음(삭제·빈 push)
    args = ["--head", head] + (["--base", base] if base else [])
    return main(args)


if __name__ == "__main__":
    if "--hook" in sys.argv:
        sys.exit(hook_main())
    sys.exit(main())
