"""보존 규칙 집행기 (결재 #10 ②, 데이터 초안 2026-10-23 · 개발 설계 3조건 반영 — req-data-47bce057).

규칙 (나이 = 파일 이름의 YYYY-MM-DD, mtime 아님 — 체크아웃은 mtime 을 전부 '오늘'로 바꾼다)
  reports/archive/**            90일 초과
  reports/signals/*.csv         10일 초과
  reports/anomalies/*.csv       10일 초과
  reports/daily/*.md            10일 초과 (DAILY 탭 원본, cleanup_proposal 2026-10-18 §25 — signals 와 같은 자리)

설계 3조건 (docs/desk_kb/rounds/2026-10-17/dev.md §4)
  1. 기본 드라이런: 삭제 후보 목록만 reports/logs/retention_YYYY-MM-DD.json 에 쓴다(삭제 0건).
  2. --apply 일 때만 `git rm` — 워크플로에서는 workflow_dispatch 입력 apply=true 로만 부른다(오너가 드라이런 로그를 본 뒤).
  3. 대상은 `git ls-files` 추적 파일만. 미추적 파일·이름에 날짜 없는 파일은 절대 건드리지 않는다.

  python3 scripts/retention.py                  # 드라이런 (로그만)
  python3 scripts/retention.py --apply          # git rm (커밋은 호출자 몫)
  python3 scripts/retention.py --today 2026-12-31 --no-log   # 시점 지정·로그 생략(점검용)

롤백: --apply 는 `git rm` 만 하고 커밋하지 않는다 → 커밋 전이면 `git restore --staged --worktree <파일>`, 커밋 후면 그 커밋 revert.
영향 범위: 이 스크립트 단독 — 워크플로 연결(ops.yml 드라이런 매일·dispatch apply)은 개발 몫(아직 연결 안 됨).
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KST = timezone(timedelta(hours=9))
DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")

# (glob, 보존 일수) — 위에서부터 첫 매치가 규칙
RULES: list[tuple[str, int]] = [
    ("reports/archive/*", 90),
    ("reports/signals/*.csv", 10),
    ("reports/anomalies/*.csv", 10),
    ("reports/daily/*.md", 10),
]


def tracked(root: Path | None = None) -> list[str]:
    """git 추적 파일(경로 문자열, 한글 이름 그대로)."""
    out = subprocess.run(["git", "ls-files", "-z", "reports"], cwd=root or ROOT, capture_output=True, check=True).stdout
    return [p for p in out.decode("utf-8").split("\0") if p]


def file_date(path: str) -> date | None:
    m = DATE_RE.search(Path(path).name)
    if not m:
        return None
    try:
        return date.fromisoformat(m.group(1))
    except ValueError:
        return None


def plan(files: list[str], today: date) -> dict:
    """삭제 후보·건너뜀(날짜 없음) 목록. 파일 시스템을 건드리지 않는 순수 함수."""
    cands, skipped = [], []
    for f in sorted(files):
        rule = next(((g, days) for g, days in RULES if fnmatch.fnmatch(f, g)), None)
        if not rule:
            continue
        d = file_date(f)
        if d is None:
            skipped.append({"path": f, "why": "이름에 날짜 없음"})
            continue
        age = (today - d).days
        if age > rule[1]:
            cands.append({"path": f, "date": d.isoformat(), "age_days": age, "rule": f"{rule[0]} > {rule[1]}일"})
    return {"today": today.isoformat(), "rules": [{"glob": g, "keep_days": k} for g, k in RULES],
            "candidates": cands, "skipped": skipped, "n": len(cands)}


def apply(paths: list[str], root: Path | None = None) -> None:
    for i in range(0, len(paths), 200):
        subprocess.run(["git", "rm", "-q", "--", *paths[i:i + 200]], cwd=root or ROOT, check=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true", help="후보를 git rm (기본은 드라이런)")
    ap.add_argument("--today", help="기준일 YYYY-MM-DD (기본 KST 오늘)")
    ap.add_argument("--no-log", action="store_true", help="reports/logs 에 쓰지 않음")
    a = ap.parse_args(argv)
    today = date.fromisoformat(a.today) if a.today else datetime.now(KST).date()
    res = plan(tracked(), today)
    res["mode"] = "apply" if a.apply else "dry-run"
    if a.apply and res["candidates"]:
        apply([c["path"] for c in res["candidates"]])
    if not a.no_log:
        log = ROOT / "reports" / "logs" / f"retention_{today.isoformat()}.json"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"retention {res['mode']}: 후보 {res['n']}건 · 날짜 없음 건너뜀 {len(res['skipped'])}건 (기준 {today})")
    for c in res["candidates"][:20]:
        print(f"  {c['path']}  ({c['age_days']}일, {c['rule']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
