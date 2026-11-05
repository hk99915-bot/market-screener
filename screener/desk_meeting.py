"""데스크 운용회의 결론 → 텔레그램 3줄형 (STANDARD.md 8절: ① What ② So What ③ Now What + 원본 1줄).
입력 reports/views/desk_meeting.json (PB 가 회의 후 갱신, 금액·보유 종목명 금지). 발송은 screener.report.send_telegram
(ALERTS_OFF 존중). CLI: python -m screener.desk_meeting [--dry]"""
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


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    txt = telegram_text(load())
    print(txt)
    if "--dry" in argv:
        return 0
    from .report import send_telegram
    send_telegram(txt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
