#!/usr/bin/env python3
"""시크릿 가드 (pre-commit) — 커밋에 '추가되는 줄'(git diff --cached)에서 토큰·계좌번호 모양을 찾아 커밋을 막는다.

11/6 겸이 결재: oh-my-agent 의 secret guard 아이디어만 가져와 우리 방식으로 새로 짬(그 프로젝트 코드·설치 없음).
같은 파일이 pb-private·market-screener 두 저장소에 있다. 저장소 루트에 screener/redact.py 가 있으면(= 공개 저장소)
screener.redact.personal_amount_hits(개인 금액 + 개인 문맥어)도 함께 검사한다.

막는 것
  - 토큰: ghp_/gho_… · github_pat_ · sk-…(20자↑, 숫자 포함) · xoxb-/xoxp- · AKIA… · -----BEGIN … PRIVATE KEY · 텔레그램 봇 토큰
  - 계좌번호 모양: 숫자{3,6}-숫자{2,6}-숫자{2,8} (날짜 YYYY-MM-DD·전화 0xx-xxxx-xxxx 모양은 통과)
  - (공개 저장소만) 개인 금액 — 같은 서명이 지워진 줄에도 있으면(재생성·이동) 새 누출로 안 센다
값은 출력하지 않는다(앞 4자 + ***). 줄 끝에 'secret-guard: allow' 가 있으면 그 줄의 계좌·금액 모양은 통과(토큰은 예외 없음).

우회: SECRET_GUARD_SKIP=1 — 쓸 때마다 stderr 와 <git-common-dir>/secret_guard_skip.log 에 남는다. --no-verify 는 금지.
사용: python3 scripts/secret_guard.py          (pre-commit 훅이 부른다)
      python3 scripts/secret_guard.py --selftest
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))
ALLOW_MARK = "secret-guard: allow"

TOKEN_RX: list[tuple[str, re.Pattern]] = [
    ("GitHub 토큰(ghp_ 등)", re.compile(r"(?<![A-Za-z0-9_])gh[pousr]_[A-Za-z0-9]{30,}")),
    ("GitHub 세분화 토큰(github_pat_)", re.compile(r"github_pat_[A-Za-z0-9_]{22,}")),
    ("API 키(sk-)", re.compile(r"(?<![A-Za-z0-9_-])sk-[A-Za-z0-9_-]{20,}")),
    ("Slack 토큰(xoxb/xoxp)", re.compile(r"(?<![A-Za-z0-9])xox[bp]-[A-Za-z0-9-]{10,}")),
    ("AWS 액세스 키(AKIA)", re.compile(r"(?<![A-Z0-9])AKIA[0-9A-Z]{16}(?![A-Z0-9])")),
    ("개인 키 블록(PRIVATE KEY)", re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")),
    ("텔레그램 봇 토큰", re.compile(r"(?<![\d])\d{8,10}:[A-Za-z0-9_-]{35}(?![A-Za-z0-9_-])")),
]
ACCT_RX = re.compile(r"(?<![\w.:/-])(\d{3,6})-(\d{2,6})-(\d{2,8})(?![\w.:/-])")


def _is_date(a: str, b: str, c: str) -> bool:
    return len(a) == 4 and len(b) == 2 and len(c) == 2 and int(b) <= 12 and int(c) <= 31   # 0000-00-00·9999-12-31 자리표시 포함


def _is_phone(a: str, b: str, c: str) -> bool:
    return a.startswith("0") and len(a) in (2, 3) and len(b) in (3, 4) and len(c) == 4


def token_hits(line: str) -> list[str]:
    out = []
    for name, rx in TOKEN_RX:
        for m in rx.finditer(line):
            if name.startswith("API 키") and not (re.search(r"\d", m.group(0)) and re.search(r"[A-Za-z0-9]{20,}", m.group(0))):
                continue   # sk-hynix-…-listing 같은 슬러그·식별자는 통과 — 실제 키는 숫자 섞인 20자↑ 무작위 덩어리가 있다
            out.append(f"{name} {m.group(0)[:4]}***")
    return out


def acct_hits(line: str) -> list[str]:
    if ALLOW_MARK in line:
        return []
    return [m.group(0) for m in ACCT_RX.finditer(line) if not (_is_date(*m.groups()) or _is_phone(*m.groups()))]


def _git(*a: str) -> str:
    r = subprocess.run(["git", *a], capture_output=True, text=True, errors="replace")
    return r.stdout if r.returncode == 0 else ""


def staged_diff() -> tuple[dict[str, list[tuple[int, str]]], dict[str, list[str]]]:
    """(추가된 줄 {파일: [(줄번호, 내용)]}, 지워진 줄 {파일: [내용]}). 바이너리는 git 이 줄을 안 준다."""
    added: dict[str, list[tuple[int, str]]] = {}
    removed: dict[str, list[str]] = {}
    f, ln = None, 0
    for raw in _git("diff", "--cached", "-U0", "--no-color", "--no-ext-diff").splitlines():
        if raw.startswith("+++ "):
            f = raw[6:] if raw.startswith("+++ b/") else None
        elif raw.startswith("--- "):
            continue
        elif raw.startswith("@@"):
            m = re.search(r"\+(\d+)", raw)
            ln = int(m.group(1)) if m else 0
        elif raw.startswith("+") and f:
            added.setdefault(f, []).append((ln, raw[1:]))
            ln += 1
        elif raw.startswith("-") and f is not None:
            removed.setdefault(f, []).append(raw[1:])
    return added, removed


def scan(added: dict[str, list[tuple[int, str]]], removed: dict[str, list[str]] | None = None,
         public: bool = False) -> list[str]:
    """막을 항목 문장 목록(값은 가림). 빈 목록이면 통과."""
    removed = removed or {}
    out: list[str] = []
    amount = None
    if public:
        try:
            from screener.redact import personal_amount_hits as amount
        except Exception as e:  # noqa: BLE001
            out.append(f"(공개 저장소 개인 금액 검사 모듈을 못 불러옴: {type(e).__name__} — 검사 없이 통과시키지 않음)")
    for f, lines in added.items():
        for ln, x in lines:
            for h in token_hits(x):
                out.append(f"{f}:{ln} 토큰 의심 — {h}")
        old_acct = Counter(a for x in removed.get(f, []) for a in acct_hits(x))
        for ln, x in lines:
            for a in acct_hits(x):
                if old_acct[a] > 0:
                    old_acct[a] -= 1
                    continue
                out.append(f"{f}:{ln} 계좌번호 모양 — {a[:4]}***")
        if amount:
            old = Counter(c for x in removed.get(f, []) if ALLOW_MARK not in x for c in amount(x))
            for ln, x in lines:
                if ALLOW_MARK in x:
                    continue
                for c in amount(x):
                    if old[c] > 0:
                        old[c] -= 1
                        continue
                    out.append(f"{f}:{ln} 개인 금액 의심(금액+개인 문맥어) — 값 생략")
    return out


def _log_skip(root: Path) -> None:
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S KST")
    msg = f"⚠️ SECRET_GUARD_SKIP=1 — 시크릿 가드 건너뜀 ({now}, {root.name}, HEAD {(_git('rev-parse', '--short', 'HEAD').strip() or '?')}). 사용 기록됨 — 이유를 커밋 메시지에 남길 것."
    print(msg, file=sys.stderr)
    try:
        cd = _git("rev-parse", "--git-common-dir").strip()
        if cd:
            p = Path(cd) if Path(cd).is_absolute() else root / cd
            with open(p / "secret_guard_skip.log", "a", encoding="utf-8") as fh:
                fh.write(msg + "\n")
    except Exception:  # noqa: BLE001
        pass


def selftest() -> int:
    g = "gh" + "p_" + "A1b2" * 9
    acct = "110" + "-" + "234" + "-" + "567890"
    cases = {
        "a.py": [(1, f'TOKEN = "{g}"'), (2, f"계좌 {acct}"), (3, "날짜 2026-11-06 · 전화 010-1234-5678"),
                 (4, f"kv = {'12345678' + '9'}:{'A' * 35}"), (5, "x = 'sk-some-kebab-identifier-name'"),
                 (6, "url = '/sk-hynix-29-billion-us-adr-listing'"), (7, f"k = '{'s' + 'k-'}{'Zq9' * 8}'")],
    }
    hits = scan(cases)
    ok = (any("a.py:1 토큰" in h for h in hits) and any("a.py:2 계좌" in h for h in hits)
          and not any("a.py:3" in h for h in hits) and any("a.py:4 토큰" in h for h in hits)
          and not any("a.py:5" in h or "a.py:6" in h for h in hits) and any("a.py:7 토큰" in h for h in hits) and not any(g in h or acct in h for h in hits))
    moved = scan({"b.md": [(1, f"계좌 {acct}")]}, {"b.md": [f"계좌 {acct}"]})
    ok = ok and not moved
    print("selftest", "OK" if ok else "FAIL", *hits, sep="\n  ")
    return 0 if ok else 1


def main(argv: list[str]) -> int:
    if "--selftest" in argv:
        return selftest()
    root = Path(_git("rev-parse", "--show-toplevel").strip() or ".")
    if os.environ.get("SECRET_GUARD_SKIP") == "1":
        _log_skip(root)
        return 0
    public = (root / "screener" / "redact.py").exists()
    if public and str(root) not in sys.path:
        sys.path.insert(0, str(root))
    hits = scan(*staged_diff(), public=public)
    if not hits:
        return 0
    print("⛔ 시크릿 가드: 커밋 차단 — 추가된 줄에 토큰·계좌번호·개인 금액으로 보이는 값이 있습니다 (값은 가림).", file=sys.stderr)
    for h in hits[:30]:
        print("  - " + h, file=sys.stderr)
    if len(hits) > 30:
        print(f"  … 외 {len(hits) - 30}건", file=sys.stderr)
    print("조치: 값을 지우고(토큰이면 즉시 폐기·재발급) git add 후 다시 커밋. 오탐(계좌·금액 모양)이면 그 줄 끝에 "
          f"'{ALLOW_MARK}' 주석. 긴급 우회 SECRET_GUARD_SKIP=1 (기록됨) · --no-verify 금지.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Exception as e:  # noqa: BLE001  — 가드 자체 버그로 모든 커밋이 막히지 않게: 경고만 하고 통과
        print(f"⚠️ 시크릿 가드 내부 오류({type(e).__name__}: {e}) — 이번 커밋은 검사 없이 통과. scripts/secret_guard.py 확인 필요.",
              file=sys.stderr)
        sys.exit(0)
