"""에이전트 완료 통계 1건을 ops/team.json runs 에 추가 (PB 가 에이전트 완료 알림을 받을 때마다 호출 — 저장소에서 자동 수집 불가한 유일한 칸).
사용: python3 scripts/team_run.py --owner 개발 --task "데이터 신선도 재발방지" --tokens 123456 --tools 40 --sec 600 [--model claude-opus-5-5] [--date 2026-10-17] [--trigger pb|auto]
--trigger: 누가 깨웠나 — pb(기본, PB 호출) · auto(watchdog·예약 등 자동). 10/21 PM 측정용 — 기존 행은 건드리지 않음(필드 없음 = pb 로 읽는다).
같은 날·같은 owner·같은 task 는 덮어씀(중복 방지).
owner 는 보드 이름으로 정규화(dev→개발·data→데이터·FRM→리스크 — team_stats.norm_owner, 감사 L5 req-pm-1dc0d451).
--normalize: 기존 runs 의 owner 키를 한 번에 정규화(값만 바꿈, 행 수 그대로)."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from team_stats import norm_owner  # noqa: E402

P = Path(__file__).resolve().parents[1] / "ops" / "team.json"


def add(t: dict, row: dict) -> dict:
    row = {**row, "owner": norm_owner(row["owner"])}
    runs = [r for r in t.get("runs", []) if not (r.get("date") == row["date"] and r.get("owner") == row["owner"] and r.get("task") == row["task"])]
    t["runs"] = runs + [row]
    return t


def normalize(t: dict) -> int:
    """기존 runs owner 키 정규화 — 바뀐 행 수."""
    n = 0
    for r in t.get("runs", []):
        o = norm_owner(r.get("owner", ""))
        if o != r.get("owner"):
            r["owner"] = o
            n += 1
    return n


def main(argv=None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if "--normalize" in argv:
        t = json.loads(P.read_text(encoding="utf-8"))
        n = normalize(t)
        P.write_text(json.dumps(t, ensure_ascii=False, indent=1), encoding="utf-8")
        print("normalized", n)
        return 0
    ap = argparse.ArgumentParser()
    for k in ("owner", "task"):
        ap.add_argument(f"--{k}", required=True)
    for k in ("tokens", "tools", "sec"):
        ap.add_argument(f"--{k}", type=int, required=True)
    ap.add_argument("--model", default=None)
    ap.add_argument("--trigger", choices=("pb", "auto"), default="pb")
    ap.add_argument("--date", default=datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d"))
    a = ap.parse_args(argv)
    row = {"date": a.date, "owner": a.owner, "task": a.task, "tools": a.tools, "sec": a.sec, "tokens": a.tokens, "trigger": a.trigger}
    if a.model:
        row["model"] = a.model
    t = json.loads(P.read_text(encoding="utf-8"))
    P.write_text(json.dumps(add(t, row), ensure_ascii=False, indent=1), encoding="utf-8")
    print("runs", len(t["runs"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
