"""push 전 필수 검사 (pre-push 훅이 부른다) — 하나라도 실패하면 exit 1 → git 이 push 를 막는다.

10/20 사고: check_functions 가 '푸시 금지'를 냈는데 `a && b; git push` 같은 명령 체인 때문에 push 가 진행됨.
→ 사람이 출력 문구를 읽는 대신 git 훅의 종료 코드로 막는다. 우회(--no-verify) 금지 — docs/desk_kb/LOOP.md.

검사(빠른 것만, 목표 30초 이내):
  1) python3 scripts/board.py --check
  2) python3 scripts/check_functions.py
  3) python3 scripts/check_rules_terms.py
  4) 공개 저장소 이메일 검사 — push 될 커밋들이 추가한 줄에 허용 목록 밖 이메일이 있으면 차단 (10/21 감사 D1:
     애널리스트 실명·이메일이 공개 로그에 저장됨). 허용: noreply@anthropic.com, *@users.noreply.github.com,
     example.com·.test·.invalid 등 예약 도메인 (screener/redact.py). 값은 출력하지 않고 파일·개수만.
  5) pytest 서브셋 — push 될 커밋들이 바꾼 파일과 관련된 테스트만:
     tests/test_*.py 를 직접 바꿨으면 그 파일, screener/X.py·scripts/X.py 를 바꿨으면 그 모듈 이름을
     import/언급하는 테스트. 공용 모듈(CORE)이 바뀌었거나 서브셋이 MAX_SUBSET 개를 넘으면 전체(≈15초).
사용: python3 scripts/prepush_check.py [--base <rev>] [--all]   (훅은 stdin 의 push 범위로 base 를 정한다)
Actions 봇 push 에는 적용되지 않는다: core.hooksPath 는 로컬 git 설정이고 러너의 checkout 은 설정하지 않음.
"""
from __future__ import annotations

import argparse
import os
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


def clean_env() -> dict:
    """훅은 GIT_DIR·GIT_INDEX_FILE 등을 물려받는다 → 검사(pytest 의 임시 git 저장소 명령)가 실제 저장소를 건드림
    (10/21 core.bare=true 3회 재현). 검사 하위 프로세스에는 GIT_* 를 모두 지워서 넘긴다."""
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def git(*a: str) -> str:
    r = subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True, env=clean_env())
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


def added_lines(base: str | None, head: str = "HEAD") -> dict[str, list[str]]:
    """push 범위에서 추가된 줄 (파일별). 바이너리는 git 이 줄을 주지 않으므로 자동 제외."""
    if not base:
        base = git("merge-base", head, "origin/main") or "origin/main"
    out = git("diff", "--no-color", "--no-ext-diff", "-U0", f"{base}..{head}")
    res: dict[str, list[str]] = {}
    cur = None
    for ln in out.splitlines():
        if ln.startswith("+++ "):
            cur = ln[6:] if ln.startswith("+++ b/") else None
        elif cur and ln.startswith("+") and not ln.startswith("+++"):
            res.setdefault(cur, []).append(ln[1:])
    return res


def email_hits(added: dict[str, list[str]]) -> dict[str, int]:
    """허용 목록 밖 이메일 개수 (파일별). 값은 돌려주지 않는다 — 출력·로그에 남기지 않기 위해."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from screener.redact import public_emails
    hits = {}
    for f, lines in added.items():
        n = sum(len(public_emails(x)) for x in lines)
        if n:
            hits[f] = n
    return hits


def email_check(base: str | None, head: str = "HEAD") -> bool:
    hits = email_hits(added_lines(base, head))
    if not hits:
        print("  ✓ 공개 이메일 검사 (허용 목록 밖 0건)")
        return True
    print(f"  ✗ 공개 이메일 검사 — 허용 목록 밖 이메일 {sum(hits.values())}건 (값은 표시 안 함):")
    for f, n in sorted(hits.items()):
        print(f"      {f}: {n}건")
    print("    → 값을 지우거나 가린 뒤(screener/redact.mask_emails) 커밋을 고쳐 다시 push. 예시는 analyst@example.com 처럼 예약 도메인")
    return False


def run(name: str, cmd: list[str]) -> bool:
    t = time.time()
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, env=clean_env())
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
    if git("config", "--get", "core.bare").lower() == "true":   # 10/21 공유 체크아웃 core.bare=true 사고
        print("  ✗ core.bare=true — 공유 체크아웃 git 설정이 망가짐. `git config core.bare false` 로 복구 후 PB 에 보고. push 차단")
        return 1
    ok = run("board --check", [py, "scripts/board.py", "--check"])
    ok &= run("check_functions", [py, "scripts/check_functions.py"])
    ok &= run("check_rules_terms", [py, "scripts/check_rules_terms.py"])
    ok &= email_check(a.base, a.head)
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
