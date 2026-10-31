#!/usr/bin/env python3
"""밤사이(22~07시 KST) 규칙 파일 커밋 필터 — 컴플 스킬 시범(2026-10-31). kb:compliance 체크리스트 ⑤ · 온보딩 실습 1 원형.

  python3 .claude/skills/compliance-desk/scripts/night_rules.py <repo> <since YYYY-MM-DD> <until YYYY-MM-DD> [--extra 경로 ...]

출력 첫 줄: `커밋 N · 22~07시 M · 그중 규칙 파일 K` 다음 후보 줄 `해시 MM-DD HH:MM 제목 | 규칙 파일`.
후보 = '규칙 변경 후보'일 뿐 — (a) 규칙 변경인가(한도·금지·판정 입력·절차·공개 기준) (b) 원장 🌙 줄·07시 이후 ✅ 확인이 있나는
사람이 판정한다(원장·발화 색인은 비공개 저장소). 한계: RULE_FILES 밖 규칙 · 커밋 시각 ≠ 결정 시각(감사 M7).
얕은 클론이면 경고(커밋을 적게 센다 — `git fetch --unshallow`). 이 스크립트는 판정·기록을 하지 않는다 — 목록만.
RULE_FILES 는 실습 1 출발점 그대로. renego.py·guard.py 추가는 첫 업무 판정 전이라 `--extra` 로만.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
RULE_FILES = ("screener/defs.py", "screener/pb.py", "screener/sectors.py", "screener/pick_gate.py", "screener/ticket.py",
              "screener/tradeplan.py", "scripts/hf_book.py", "screener/alphabook.py", "docs/desk_kb/STANDARD.md",
              "docs/desk_kb/LOOP.md", "docs/schedule_table.md", "docs/rules_terms.md", "ops/cooldown.json")


def parse_log(text: str) -> list[list]:
    rows, cur = [], None
    for ln in text.splitlines():
        if ln.startswith("@@"):
            h, t, s = ln[2:].split("|", 2)
            cur = [h, datetime.fromtimestamp(int(t), KST), s, []]
            rows.append(cur)
        elif ln.strip() and cur:
            cur[3].append(ln.strip())
    return rows


def is_night(t: datetime) -> bool:
    return t.hour >= 22 or t.hour < 7


def scan(rows: list[list], rule_files=RULE_FILES):
    night = [r for r in rows if is_night(r[1])]
    hit = [r for r in night if any(f in rule_files for f in r[3])]
    return night, hit


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("repo"), ap.add_argument("since"), ap.add_argument("until")
    ap.add_argument("--extra", nargs="*", default=[], help="RULE_FILES 에 더할 경로(판정 전 임시)")
    a = ap.parse_args(argv)
    files = tuple(RULE_FILES) + tuple(a.extra)
    sh = subprocess.run(["git", "-C", a.repo, "rev-parse", "--is-shallow-repository"], capture_output=True, text=True)
    if sh.stdout.strip() == "true":
        print("경고: 얕은 클론 — 커밋을 적게 셀 수 있음(git fetch --unshallow 후 재실행)", file=sys.stderr)
    p = subprocess.run(["git", "-C", a.repo, "log", f"--since={a.since}T00:00+09:00", f"--until={a.until}T23:59+09:00",
                        "--no-merges", "--format=@@%h|%ct|%s", "--name-only"], capture_output=True, text=True)
    if p.returncode != 0:
        print(f"데이터 없음(git log 실패: {p.stderr.strip()[:120]})", file=sys.stderr)
        return 2
    rows = parse_log(p.stdout)
    night, hit = scan(rows, files)
    print(f"커밋 {len(rows)} · 22~07시 {len(night)} · 그중 규칙 파일 {len(hit)}")
    for h, t, s, fs in hit:
        print(f"{h} {t:%m-%d %H:%M} {s[:70]} | {', '.join(f for f in fs if f in files)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
