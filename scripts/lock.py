"""공유 파일 잠금 (ops/locks.json). 규칙은 ops/LOCKS.md.

  python scripts/lock.py list
  python scripts/lock.py take  apps-script/tab_quant.html --owner "퀀트" --task lab-r2   # 탭 하나만 잠근다
  python scripts/lock.py take  apps-script/Index.html --owner "개발" --task shell-fix      # 공용 셸을 고칠 때만
  python scripts/lock.py drop  apps-script/tab_quant.html --owner "퀀트"
  python scripts/lock.py drop  --owner "퀀트"          # 내 잠금 전부 해제

take/drop 은 파일만 고친다. 바로 작은 커밋으로 푸시해야 다른 에이전트가 본다:
  git add ops/locks.json && git commit -m "lock: <파일> (<담당>, <작업>)" && git pull --rebase origin main && git push
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCKS = ROOT / "ops" / "locks.json"
KST = timezone(timedelta(hours=9))
SHARED = ["apps-script/Index.html", "apps-script/tab_*.html", "apps-script/Code.gs", "scripts/build_pages.py",
          "screener/committee.py", "screener/main.py", ".github/workflows/*"]   # 탭 파일은 하나씩 따로 잠근다 (ops/LOCKS.md)
STALE_H = 6   # 이보다 오래된 잠금은 '방치' 로 표시 (팀장이 정리)


def load() -> dict:
    try:
        return json.loads(LOCKS.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"locks": []}


def save(d: dict) -> None:
    LOCKS.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def age_h(since: str) -> float | None:
    try:
        return (datetime.now(KST) - datetime.fromisoformat(since)).total_seconds() / 3600
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["list", "take", "drop"])
    ap.add_argument("file", nargs="?")
    ap.add_argument("--owner")
    ap.add_argument("--task", default="")
    a = ap.parse_args()
    d = load()
    L = d.setdefault("locks", [])
    if a.cmd == "list":
        if not L:
            print("잠금 없음")
        for x in L:
            h = age_h(x.get("since", ""))
            print(f"{x['file']:<32} {x['owner']:<10} {x.get('task',''):<18} {x.get('since','')}"
                  + (f"  ⚠ {h:.0f}시간 방치" if h and h > STALE_H else ""))
        return 0
    if not a.owner:
        print("--owner 필요", file=sys.stderr); return 2
    if a.cmd == "take":
        if not a.file:
            print("파일 경로 필요", file=sys.stderr); return 2
        cur = next((x for x in L if x["file"] == a.file), None)
        if cur and cur["owner"] != a.owner:
            print(f"✗ {a.file} 는 {cur['owner']} 가 잠금 중 ({cur.get('task')}, {cur.get('since')}) — 기다리거나 팀장에게 요청", file=sys.stderr)
            return 1
        if cur:
            print("이미 내 잠금"); return 0
        L.append({"file": a.file, "owner": a.owner, "since": datetime.now(KST).strftime("%Y-%m-%dT%H:%M+09:00"), "task": a.task})
        save(d); print(f"잠금: {a.file}"); return 0
    # drop
    keep = [x for x in L if not (x["owner"] == a.owner and (a.file is None or x["file"] == a.file))]
    n = len(L) - len(keep)
    d["locks"] = keep
    save(d); print(f"해제 {n}개"); return 0


if __name__ == "__main__":
    sys.exit(main())
