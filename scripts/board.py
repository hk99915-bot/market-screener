"""작업 보드: ops/board.json → ops/BOARD.md (사람이 읽는 판).

  python scripts/board.py                      # 검증 + BOARD.md 생성
  python scripts/board.py --set lab-r2 검수     # 상태 변경 (완료/진행이면 날짜 자동 기입) + 생성
  python scripts/board.py --check              # 검증만 (잘못되면 종료코드 1)
  python scripts/board.py --approval appr-x 겸이  # 결재 필드 설정 ('-' 면 비움) + 생성
  python scripts/board.py --add '{"id":..,"title":..,"owner":..,"priority":"P1","status":"대기"}'
                                               # 작업 추가 — validate 통과할 때만 기록 (생략한 선택 필드는 기본값)
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / "ops" / "board.json"
OUT = ROOT / "ops" / "BOARD.md"
KST = timezone(timedelta(hours=9))

STATUSES = ["진행", "검수", "대기", "보류", "완료"]   # 표시 순서
PRIORITIES = ["P0", "P1", "P2", "P3"]
FIELDS = ["id", "title", "owner", "priority", "status", "started", "due", "files", "depends_on", "notes"]
# 결재 필드 (선택, req-pm-47712fe7 · 피어 2026-10-24 U1): approval = 결재자 이름(지금은 '겸이'만) | 없음/null.
# 미완료 + approval 있음 = '결재 대기' (화면 tab_system sysApprOpen·BOARD.md 가 이 필드만 센다 — 글자 판정 금지).
# 운영 관례(10/24 0c77b0c1)와 호환: id 'appr-*' 또는 제목 '겸이 결재 필요' 로 시작하는 미완료 작업은 approval 필수.
APPROVERS = ["겸이"]
APPR_ID_PREFIX = "appr-"
APPR_TITLE_PREFIX = "겸이 결재 필요"


def needs_approval(t: dict) -> bool:
    """운영 관례상 결재 항목인가 (id·제목 접두)."""
    return str(t.get("id", "")).startswith(APPR_ID_PREFIX) or str(t.get("title", "")).startswith(APPR_TITLE_PREFIX)


def approval_open(tasks: list[dict]) -> list[dict]:
    """결재 대기 = 완료 아닌 작업 중 approval 이 채워진 것 (tab_system.html sysApprOpen 과 같은 규칙)."""
    return [t for t in tasks if t.get("status") != "완료" and t.get("approval")]


def today() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d")


def load() -> dict:
    return json.loads(BOARD.read_text(encoding="utf-8"))


def validate(b: dict) -> list[str]:
    errs, ids = [], set()
    for t in b.get("tasks", []):
        tid = t.get("id", "?")
        for f in FIELDS:
            if f not in t:
                errs.append(f"{tid}: '{f}' 필드 없음")
        if tid in ids:
            errs.append(f"{tid}: id 중복")
        ids.add(tid)
        if t.get("status") not in STATUSES:
            errs.append(f"{tid}: 상태 '{t.get('status')}' 는 {STATUSES} 중 하나여야 함")
        if t.get("priority") not in PRIORITIES:
            errs.append(f"{tid}: 우선순위 '{t.get('priority')}' 는 P0~P3")
        ap = t.get("approval")
        if ap is not None and ap not in APPROVERS:
            errs.append(f"{tid}: approval '{ap}' 는 {APPROVERS} 중 하나 또는 null")
        if needs_approval(t) and t.get("status") != "완료" and not ap:
            errs.append(f"{tid}: 결재 항목(id '{APPR_ID_PREFIX}*'·제목 '{APPR_TITLE_PREFIX}')인데 approval 없음 — \"approval\": \"겸이\"")
    for t in b.get("tasks", []):
        for d in t.get("depends_on") or []:
            if d not in ids:
                errs.append(f"{t.get('id')}: depends_on '{d}' 없는 작업")
    return errs


def render(b: dict) -> str:
    td = today()
    tasks = b.get("tasks", [])
    key = lambda t: (PRIORITIES.index(t["priority"]) if t["priority"] in PRIORITIES else 9, t.get("due") or "9999", t["id"])
    L = ["# 작업 보드", "",
         "> 자동 생성 — `ops/board.json` 을 고치고 `python scripts/board.py` 로 다시 만든다. 이 파일을 직접 고치지 말 것.", "",
         f"기준일 {td} · 작업 {len(tasks)}개 · " + " · ".join(f"{s} {sum(t['status'] == s for t in tasks)}" for s in STATUSES), ""]
    late = [t for t in tasks if t.get("due") and t["due"] < td and t["status"] != "완료"]
    appr = approval_open(tasks)
    if appr:
        L += [f"**결재 대기 {len(appr)}:** " + ", ".join(f"`{t['id']}` ({t['approval']}{' · ' + t['status'] if t['status'] == '보류' else ''})" for t in appr), ""]
    if late:
        L += ["**기한 지남:** " + ", ".join(f"`{t['id']}` ({t['due']})" for t in late), ""]
    for s in STATUSES:
        grp = sorted((t for t in tasks if t["status"] == s), key=key)
        if not grp:
            continue
        L += [f"## {s} ({len(grp)})", "", "| 우선 | id | 작업 | 담당 | 시작 | 기한 | 파일 | 선행 | 메모 |", "|---|---|---|---|---|---|---|---|---|"]
        for t in grp:
            files = "private 전용" if t.get("repo") == "private" else "<br>".join(f"`{f}`" for f in t.get("files") or []) or "—"
            due = t.get("due") or "—"
            if t.get("due") and t["due"] < td and s != "완료":
                due = f"**{due} 지남**"
            pri = t["priority"] + (f" ⏫P1 {t['escalated'][5:]}" if t.get("escalated") and t["priority"] != "P1" else " ⏫" if t.get("escalated") else "")   # watchdog 승격 표시(우선순위 보존, 10/21 B)
            row = [pri, f"`{t['id']}`", t["title"], t["owner"], t.get("started") or "—", due, files,
                   ", ".join(f"`{d}`" for d in t.get("depends_on") or []) or "—", (t.get("notes") or "").replace("|", "/")]
            L.append("| " + " | ".join(row) + " |")
        L.append("")
    # 같은 파일을 고치는 진행 중 작업 (충돌 위험)
    act = [t for t in tasks if t["status"] in ("진행", "검수")]
    share: dict[str, list[str]] = {}
    for t in act:
        for f in t.get("files") or []:
            share.setdefault(f, []).append(t["id"])
    hot = {f: ids for f, ids in share.items() if len(ids) > 1}
    if hot:
        L += ["## 충돌 주의 (진행 중 작업이 같은 파일을 고침)", ""]
        L += [f"- `{f}` ← " + ", ".join(f"`{i}`" for i in ids) + " — 편집 전 `ops/locks.json` 잠금 필수" for f, ids in sorted(hot.items())]
        L.append("")
    return "\n".join(L)


REQUIRED = ["id", "title", "owner", "priority", "status"]
OPTIONAL_DEFAULTS = {"started": None, "due": None, "files": [], "depends_on": [], "notes": ""}


def add_task(b: dict, task: dict) -> list[str]:
    """task 를 b 에 추가. validate 가 통과하면 [] 를 돌려주고 b 를 바꾼다, 아니면 오류 목록만 돌려주고 b 는 그대로."""
    miss = [f for f in REQUIRED if not task.get(f)]
    if miss:
        return [f"{task.get('id', '?')}: 필수 필드 없음 {miss}"]
    t = {**{k: (v.copy() if isinstance(v, list) else v) for k, v in OPTIONAL_DEFAULTS.items()}, **task}
    trial = {**b, "tasks": [*b.get("tasks", []), t]}
    errs = validate(trial)
    if errs:
        return errs
    b["tasks"].append(t)
    b["updated"] = today()
    return []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", nargs=2, metavar=("ID", "STATUS"))
    ap.add_argument("--add", metavar="JSON", help="작업 1건(JSON 객체) 추가 — validate 통과 시에만 기록")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--approval", nargs=2, metavar=("ID", "WHO"), help="결재 필드 설정 (WHO='-' 면 비움)")
    a = ap.parse_args()
    b = load()
    if a.add:
        try:
            task = json.loads(a.add)
        except ValueError as e:
            print(f"✗ --add JSON 해석 실패: {e}", file=sys.stderr); return 1
        if not isinstance(task, dict):
            print("✗ --add 는 JSON 객체 1건이어야 함", file=sys.stderr); return 1
        errs = add_task(b, task)
        for e in errs:
            print("✗", e, file=sys.stderr)
        if errs:
            return 1
        BOARD.write_text(json.dumps(b, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if a.set:
        tid, st = a.set
        t = next((x for x in b["tasks"] if x["id"] == tid), None)
        if not t:
            print(f"작업 '{tid}' 없음", file=sys.stderr); return 1
        t["status"] = st
        if st in ("진행", "검수") and not t.get("started"):
            t["started"] = today()
        if st == "완료":
            t["done"] = today()
        b["updated"] = today()
        BOARD.write_text(json.dumps(b, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if a.approval:
        tid, who = a.approval
        t = next((x for x in b["tasks"] if x["id"] == tid), None)
        if not t:
            print(f"작업 '{tid}' 없음", file=sys.stderr); return 1
        t["approval"] = None if who == "-" else who
        aerrs = validate(b)
        for e in aerrs:
            print("✗", e, file=sys.stderr)
        if aerrs:
            return 1
        b["updated"] = today()
        BOARD.write_text(json.dumps(b, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    errs = validate(b)
    for e in errs:
        print("✗", e, file=sys.stderr)
    if errs:
        return 1
    if a.check:
        print(f"board OK ({len(b['tasks'])}개)"); return 0
    OUT.write_text(render(b) + "\n", encoding="utf-8")
    print(f"ops/BOARD.md 생성 ({len(b['tasks'])}개)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
