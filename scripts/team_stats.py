#!/usr/bin/env python3
"""팀 업무량 자동 집계 (PM 데스크 소관) → ops/team.json 의 `auto` 블록.

ops/team.json 의 runs(에이전트 완료 통계: 토큰·도구·시간)는 수작업이라 10/15 이후 갱신이 끊겼다(복기: docs/desk_kb/pm.md).
이 스크립트는 사람 손 없이 저장소에서 얻을 수 있는 실측만 모아 `auto` 에 쓰고, runs·earlier 는 건드리지 않는다.

  데스크별 지표 (키 = 보드 담당 이름: PB·개발·퀀트 …)
    commits_7d   최근 7일 커밋 수 — 커밋 메시지를 COMMIT_RULES 표로 데스크에 귀속 (봇 계정 커밋 제외, 못 붙인 건 unmapped)
    board        ops/board.json 상태별 건수 (owner 기준 진행/검수/대기/보류/완료)
    rounds       강화 루프 라운드 참여 수 (docs/desk_kb/rounds/<날짜>/<desk>.md) + 최근 날짜
    req_open     요청 장부(rounds/_requests.json)에서 이 데스크가 받은 미처리(open) 요청 수
    audit        reports/audit/*.json by_desk 치명/중/경 합계 (최근 7일 파일)

  python3 scripts/team_stats.py            # 집계 → ops/team.json auto + updated(실행 시각 KST)
  python3 scripts/team_stats.py --dry-run  # 출력만
  python3 scripts/team_stats.py --check    # updated 날짜가 오늘(KST)이 아니면 종료코드 1

실행 경로: .github/workflows/ops.yml (00:07·23:47 KST) + scripts/round_collect.py --apply 끝.
롤백: ops.yml 단계와 round_collect 호출 두 줄을 지우면 이전(수작업만)으로 돌아간다. auto 블록은 화면에서만 읽는다.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEAM = ROOT / "ops" / "team.json"
BOARD = ROOT / "ops" / "board.json"
ROUNDS_DIR = ROOT / "docs" / "desk_kb" / "rounds"
LEDGER = ROUNDS_DIR / "_requests.json"
AUDIT_DIR = ROOT / "reports" / "audit"
KST = timezone(timedelta(hours=9))
WINDOW_DAYS = 7
STATUSES = ("진행", "검수", "대기", "보류", "완료")
SEVS = ("치명", "중", "경")

# 영문 데스크 키(라운드 파일명·감사 by_desk·커밋 접두) ↔ 보드 담당 이름. round_collect.DESKS + 감사·기록.
DESKS = {
    "pb": "PB", "quant": "퀀트", "bonds": "채권", "frm": "리스크", "backtest": "백테스트", "life": "LIFE",
    "alloc": "자산배분", "macro": "매크로", "ops": "운영", "pm": "PM", "health": "헬스", "cio": "CIO",
    "derivs": "파생", "analyst": "애널", "dev": "개발", "edu": "교육", "data": "데이터", "verify": "검증",
    "eval": "평가", "peer": "피어리뷰", "behavior": "행동", "audit": "감사", "record": "기록",
}
# 한글 별칭 → 보드 이름 (커밋·잠금에 쓰인 다른 이름)
ALIASES = {"팀장(PB)": "PB", "팀장": "PB", "FRM": "리스크", "frm": "리스크"}

# 커밋 메시지 → 데스크 매핑 표 (위에서부터 첫 일치). 그룹 1 = 데스크 이름/키 또는 보드 작업 id.
#   종류 desk  : 그룹이 데스크 키·한글 이름
#   종류 task  : 그룹이 ops/board.json 작업 id → 그 작업의 owner
COMMIT_RULES: list[tuple[str, re.Pattern, str]] = [
    ("desk", re.compile(r"^([A-Za-z]+) 라운드"), "'<desk> 라운드N: …' (강화 루프)"),
    ("desk", re.compile(r"^(?:un)?lock: .*?\(([^,()]+?)\s*[,)]"), "'lock:/unlock: 파일 (<데스크>, 작업)'"),
    ("desk", re.compile(r"^board: .*\(([^,()]+?)\s*,\s*P\d"), "'board: id (<데스크>, P1, 기한)'"),
    ("desk", re.compile(r"^board: .*\(P\d\s*,\s*([^,()]+?)\s*\)"), "'board: 제목(P0, <데스크>)'"),
    ("desk", re.compile(r"^kb\(([^()]+)\)\s*:"), "'kb(<desk>): …'"),
    ("task", re.compile(r"^board: ([A-Za-z0-9][\w-]*)"), "'board: <작업 id> …' → 보드 owner"),
    ("desk", re.compile(r"^([a-z]+|[가-힣]+)\s*:"), "'<desk>: …' 접두 (pb:·audit:·감사:, 데스크 이름일 때만)"),
]
BOT_AUTHORS = ("screener-bot",)


def now_kst() -> datetime:
    return datetime.now(KST)


def norm_owner(name: str) -> str:
    """'dev'·'개발'·'팀장(PB)'·'개발 누나' → 보드 이름. 모르는 이름은 그대로(공백 정리)."""
    n = re.sub(r"\s*누나$", "", (name or "").strip())
    if n in ALIASES:
        return ALIASES[n]
    if n.lower() in DESKS:
        return DESKS[n.lower()]
    return n


def _known(name: str) -> bool:
    return norm_owner(name) in set(DESKS.values())


def commit_desk(msg: str, task_owner: dict[str, str] | None = None) -> str | None:
    """커밋 제목 한 줄 → 데스크 보드 이름 (COMMIT_RULES 첫 일치, 아는 데스크만). 못 붙이면 None."""
    subj = (msg or "").splitlines()[0].strip() if msg else ""
    task_owner = task_owner or {}
    for kind, pat, _ in COMMIT_RULES:
        m = pat.search(subj)
        if not m:
            continue
        g = m.group(1)
        if kind == "task":
            if g in task_owner:
                return norm_owner(task_owner[g])
            continue
        if _known(g):
            return norm_owner(g)
    return None


def git_commits(days: int = WINDOW_DAYS, cwd: Path = ROOT) -> list[tuple[str, str]]:
    """(작성자, 제목) 목록. git 실패 시 RuntimeError (조용히 0으로 두지 않는다)."""
    r = subprocess.run(["git", "log", f"--since={days} days ago", "--format=%an%x1f%s"],
                       cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"git log 실패: {r.stderr.strip()[:200]}")
    out = []
    for line in r.stdout.splitlines():
        if "\x1f" in line:
            a, s = line.split("\x1f", 1)
            out.append((a, s))
    return out


def commit_counts(commits: list[tuple[str, str]], task_owner: dict[str, str]) -> tuple[dict[str, int], int, int]:
    """→ (데스크별 커밋 수, 못 붙인 사람·에이전트 커밋 수, 봇 커밋 수)."""
    by: dict[str, int] = {}
    unmapped = bots = 0
    for author, subj in commits:
        if author in BOT_AUTHORS:
            bots += 1
            continue
        d = commit_desk(subj, task_owner)
        if d is None:
            unmapped += 1
        else:
            by[d] = by.get(d, 0) + 1
    return by, unmapped, bots


def board_counts(board: dict) -> dict[str, dict[str, int]]:
    """owner 기준 상태별 건수."""
    out: dict[str, dict[str, int]] = {}
    for t in board.get("tasks", []):
        o = norm_owner(t.get("owner", ""))
        s = t.get("status", "")
        c = out.setdefault(o, {k: 0 for k in STATUSES})
        if s in c:
            c[s] += 1
    return out


def round_counts(rounds_dir: Path) -> dict[str, dict]:
    """데스크별 라운드 참여 수·최근 날짜 (rounds/<YYYY-MM-DD>/<desk>.md)."""
    out: dict[str, dict] = {}
    if not rounds_dir.is_dir():
        return out
    for d in sorted(p for p in rounds_dir.iterdir() if p.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.name)):
        for f in d.glob("*.md"):
            o = norm_owner(f.stem)
            r = out.setdefault(o, {"n": 0, "last": None})
            r["n"] += 1
            r["last"] = d.name
    return out


def open_requests(ledger: dict) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in ledger.get("requests", []):
        if r.get("status") == "open":
            o = norm_owner(r.get("to", ""))
            out[o] = out.get(o, 0) + 1
    return out


def audit_counts(audit_dir: Path, since: date) -> tuple[dict[str, dict[str, int]], list[str]]:
    """since 이후 날짜의 reports/audit/<date>.json by_desk 합계 → (데스크별 치명/중/경, 읽은 날짜)."""
    out: dict[str, dict[str, int]] = {}
    used: list[str] = []
    if not audit_dir.is_dir():
        return out, used
    for p in sorted(audit_dir.glob("*.json")):
        try:
            d = date.fromisoformat(p.stem)
        except ValueError:
            continue
        if d < since:
            continue
        try:
            j = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"감사 파일 JSON 오류 — 건너뜀: {p} ({e})", file=sys.stderr)
            continue
        used.append(p.stem)
        for k, v in (j.get("by_desk") or {}).items():
            c = out.setdefault(norm_owner(k), {s: 0 for s in SEVS})
            for s in SEVS:
                c[s] += int((v or {}).get(s, 0) or 0)
    return out, used


def build_auto(commits: list[tuple[str, str]], board: dict, ledger: dict, rounds_dir: Path, audit_dir: Path,
               today: date, days: int = WINDOW_DAYS) -> dict:
    task_owner = {t.get("id"): t.get("owner", "") for t in board.get("tasks", [])}
    cc, unmapped, bots = commit_counts(commits, task_owner)
    bc = board_counts(board)
    rc = round_counts(rounds_dir)
    rq = open_requests(ledger)
    ac, aud_days = audit_counts(audit_dir, today - timedelta(days=days - 1))
    names = sorted(set(cc) | set(bc) | set(rc) | set(rq) | set(ac))
    desks = {}
    for n in names:
        desks[n] = {
            "commits_7d": cc.get(n, 0),
            "board": bc.get(n, {k: 0 for k in STATUSES}),
            "rounds": rc.get(n, {}).get("n", 0),
            "round_last": rc.get(n, {}).get("last"),
            "req_open": rq.get(n, 0),
            "audit": ac.get(n, {s: 0 for s in SEVS}),
        }
    return {
        "_doc": "scripts/team_stats.py 자동 집계 — 손으로 고치지 말 것. 매핑 규칙은 스크립트 COMMIT_RULES.",
        "window_days": days,
        "since": (today - timedelta(days=days - 1)).isoformat(),
        "commits_total": len(commits),
        "commits_bot": bots,
        "commits_unmapped": unmapped,
        "audit_files": aud_days,
        "desks": desks,
    }


def is_stale(updated: str | None, today: date) -> int:
    """updated('YYYY-MM-DD…') 가 today 보다 며칠 뒤졌나. 없거나 못 읽으면 999. 0 = 오늘."""
    try:
        d = date.fromisoformat(str(updated)[:10])
    except (TypeError, ValueError):
        return 999
    return max(0, (today - d).days)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="updated 가 오늘(KST)이 아니면 종료코드 1")
    ap.add_argument("--dry-run", action="store_true", help="쓰지 않고 출력만")
    ap.add_argument("--team", type=Path, default=TEAM)
    a = ap.parse_args(argv)
    now = now_kst()
    team = json.loads(a.team.read_text(encoding="utf-8")) if a.team.exists() else {"runs": []}
    if a.check:
        lag = is_stale(team.get("updated"), now.date())
        print(f"team.json updated={team.get('updated')} · {'오늘' if lag == 0 else f'{lag}일 갱신 안 됨'}")
        return 0 if lag == 0 else 1
    board = json.loads(BOARD.read_text(encoding="utf-8")) if BOARD.exists() else {}
    ledger = json.loads(LEDGER.read_text(encoding="utf-8")) if LEDGER.exists() else {}
    auto = build_auto(git_commits(), board, ledger, ROUNDS_DIR, AUDIT_DIR, now.date())
    team["updated"] = now.strftime("%Y-%m-%dT%H:%M+09:00")
    team["auto"] = auto
    for n, d in auto["desks"].items():
        b = d["board"]
        print(f"  {n:6s} 커밋7d {d['commits_7d']:3d} · 진행 {b['진행']} 검수 {b['검수']} 대기 {b['대기']} · "
              f"라운드 {d['rounds']} · 요청대기 {d['req_open']} · 감사 중 {d['audit']['중']} 경 {d['audit']['경']}")
    print(f"커밋 {auto['commits_total']} (봇 {auto['commits_bot']} · 미분류 {auto['commits_unmapped']}) · updated {team['updated']}")
    if a.dry_run:
        return 0
    a.team.write_text(json.dumps(team, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
