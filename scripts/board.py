"""작업 보드: ops/board.json → ops/BOARD.md (사람이 읽는 판).

  python scripts/board.py                      # 검증 + BOARD.md 생성
  python scripts/board.py --set lab-r2 검수     # 상태 변경 (완료/진행이면 날짜 자동 기입) + 생성
  python scripts/board.py --check              # 검증만 (잘못되면 종료코드 1)
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
            row = [t["priority"], f"`{t['id']}`", t["title"], t["owner"], t.get("started") or "—", due, files,
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", nargs=2, metavar=("ID", "STATUS"))
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    b = load()
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
