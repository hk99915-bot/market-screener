"""데스크 운용회의 결론 → 텔레그램 3줄형 (STANDARD.md 8절: ① What ② So What ③ Now What + 원본 1줄).
입력 reports/views/desk_meeting.json (PB 가 회의 후 갱신, 금액·보유 종목명 금지). 발송은 screener.report.send_telegram
(ALERTS_OFF 존중). CLI: python -m screener.desk_meeting [--dry] [--marker PATH [--today-only] [--force]]
11/8 Pro 대비(dev.md #6): desk_meeting_tg.yml 이 desk_meeting.json push 때 자동 발송 — 같은 date 재발송 금지는
--marker(Actions 캐시로 날짜별 보존되는 파일, 보낸 date 목록)로 막는다. --today-only = push 발송은 오늘(KST) 회의만."""
from __future__ import annotations

import json
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from .config import ROOT

VIEW = ROOT / "reports" / "views" / "desk_meeting.json"
MAX = 90


def _clip(s: str, n: int = MAX) -> str:
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def load(path=VIEW) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def is_today(o: dict, today: str | None = None) -> bool:
    today = today or datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
    return o.get("date") == today


def telegram_text(o: dict, today: str | None = None) -> str:
    """① What=변곡 판정, ② So What=결론 1줄, ③ Now What=CIO 조치, 원본. 아래에 피어/PB 줄·결재 대기."""
    lines = list(o.get("lines") or [])
    lines += [""] * (3 - len(lines))
    head = f"데스크 운용회의 결론 · 기준 {o.get('asof') or o.get('date', '')}"
    if not is_today(o, today):
        head = f"지난 회의({o.get('date', '')}) · " + head
    out = [_clip(head),
           f"① What: {_clip(o.get('inflection', ''), MAX - 9)}",
           f"② So What: {_clip(lines[0], MAX - 12)}",
           f"③ Now What: {_clip(lines[1], MAX - 14)}",
           f"원본: {o.get('path', '')}"]
    if lines[2]:
        out.append("- " + _clip(lines[2], MAX - 2))
    for a in o.get("asks") or []:
        out.append("- 결재 대기: " + _clip(a, MAX - 9))
    return "\n".join(out)


def sent_dates(marker) -> set[str]:
    """마커 파일(한 줄에 date 하나)에 적힌 이미 보낸 회의 date."""
    from pathlib import Path
    p = Path(marker)
    if not p.exists():
        return set()
    return {x.strip() for x in p.read_text(encoding="utf-8").splitlines() if x.strip()}


def should_send(o: dict, sent: set[str], *, today: str | None = None, today_only: bool = False,
                force: bool = False) -> tuple[bool, str]:
    """(보낼지, 이유). force 는 재발송 허용(수동 dispatch 의 force 입력)."""
    d = str(o.get("date") or "")
    if not d:
        return False, "date 없음 — 발송 안 함"
    if force:
        return True, f"force — {d} 재발송"
    if d in sent:
        return False, f"{d} 회의 결론은 이미 발송됨 — 같은 date 재발송 금지(고친 회의록은 탭 카드로만 반영)"
    if today_only and not is_today(o, today):
        return False, f"{d} 는 오늘 회의가 아님 — push 자동 발송 생략"
    return True, f"{d} 첫 발송"


def _arg(argv: list[str], name: str) -> str | None:
    return argv[argv.index(name) + 1] if name in argv and argv.index(name) + 1 < len(argv) else None


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    o = load()
    txt = telegram_text(o)
    print(txt)
    if "--dry" in argv:
        return 0
    marker = _arg(argv, "--marker")
    if marker:
        ok, why = should_send(o, sent_dates(marker), today_only="--today-only" in argv, force="--force" in argv)
        print(f"[desk_meeting] {why}")
        if not ok:
            return 0
    from .report import alerts_off, send_telegram
    send_telegram(txt)
    if marker and not alerts_off():   # 실제로 보낸 경우만 기록(ALERTS_OFF 로 생략된 날은 나중에 다시 보낼 수 있게)
        from pathlib import Path
        p = Path(marker)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(str(o.get("date")) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
