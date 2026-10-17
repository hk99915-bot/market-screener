"""재협상 카운터 (행동 데스크, 오너 승인 2026-10-17 14:09 · pb-private ops/agreements.md §7-3).

같은 규칙을 다시 협상하는 것(예: '이번만 손익비 1:1.5 로')은 규칙이 행동을 막는 순간 규칙을 바꾸려는 패턴이다(kb:behavior#22 밤 재협상).
같은 규칙이 RENEGO_WINDOW_DAYS(30일) 안에 RENEGO_WARN_AT(2)회째 재협상되면 주문표에 ⛔ '재협상 2회째' 를 띄우고 **사유 칸**을 요구한다.

저장: ops/renego.json (공개 저장소) — 규칙 id(screener/defs.py 상수 이름) + 날짜 + 횟수만. 금액·사유 글은 넣지 않는다.
사유 글은 어디에도 공개 저장하지 않는다(주문표 이슈 본문에는 '재협상사유: 기재' 표시만, 기록에는 True/False 만).

  python3 -m screener.renego add MIN_RR              # 오늘 MIN_RR 재협상 1건 기록 (횟수 자동)
  python3 -m screener.renego add SEMI_CAP --date 2026-10-17
  python3 -m screener.renego list                    # 30일 안 규칙별 횟수 · ⛔ 표시
영향 범위: 주문표 검사(screener/ticket.py evaluate)·주문표 입력 화면(apps-script/tab_duel.html). 롤백: RENEGO_WARN_AT 를 크게 하거나 커밋 revert.
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from . import defs
from .defs import RENEGO_WARN_AT, RENEGO_WINDOW_DAYS

KST = ZoneInfo("Asia/Seoul")
FILE = Path(__file__).resolve().parents[1] / "ops" / "renego.json"
ALLOWED_KEYS = {"rule", "date", "count"}   # 공개 파일 스키마 — 이 밖의 키(사유·금액)는 저장 거부


def valid_rule(rule: str) -> bool:
    """규칙 id = screener/defs.py 의 대문자 상수 이름 (TERMS 에 있거나 모듈 속성)."""
    return bool(rule) and rule.isupper() and (rule in defs.TERMS or hasattr(defs, rule))


def load(path: Path | None = None) -> dict:
    try:
        return json.loads((path or FILE).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"events": []}


def _d(v) -> date | None:
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def counts(on: date, path: Path | None = None) -> dict[str, dict]:
    """on 기준 최근 RENEGO_WINDOW_DAYS 일 안 규칙별 {count, last}. 미래 날짜는 세지 않는다."""
    lo = on - timedelta(days=RENEGO_WINDOW_DAYS - 1)
    out: dict[str, dict] = {}
    for e in load(path).get("events") or []:
        d = _d(e.get("date"))
        r = str(e.get("rule") or "")
        if d is None or not valid_rule(r) or not (lo <= d <= on):
            continue
        c = out.setdefault(r, {"count": 0, "last": None})
        c["count"] += 1
        c["last"] = max(c["last"] or d, d)
    return {r: {"count": v["count"], "last": str(v["last"])} for r, v in out.items()}


def active(on: date, path: Path | None = None) -> list[dict]:
    """⛔ 대상: 30일 안 같은 규칙 RENEGO_WARN_AT 회 이상. [{rule, term, count, last}] (횟수 많은 순)."""
    rows = [{"rule": r, "term": defs.TERMS.get(r, r), **v} for r, v in counts(on, path).items() if v["count"] >= RENEGO_WARN_AT]
    return sorted(rows, key=lambda x: (-x["count"], x["rule"]))


def add(rule: str, on: date | None = None, path: Path | None = None) -> dict:
    """재협상 1건 기록 → 저장한 항목 {rule, date, count}. count = 30일 안 n번째."""
    if not valid_rule(rule):
        raise ValueError(f"규칙 id '{rule}' 는 screener/defs.py 상수 이름이 아님 (예: {', '.join(sorted(defs.TERMS)[:4])} …)")
    on = on or datetime.now(KST).date()
    fp = path or FILE
    d = load(fp)
    d.setdefault("_doc", "재협상 카운터 — 규칙 id(screener/defs.py 상수)·날짜·횟수만. 사유 글·금액 금지. screener/renego.py")
    item = {"rule": rule, "date": str(on), "count": counts(on, fp).get(rule, {"count": 0})["count"] + 1}
    d["events"] = [{k: v for k, v in e.items() if k in ALLOWED_KEYS} for e in (d.get("events") or [])] + [item]
    fp.write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return item


def banner(rows: list[dict]) -> str:
    """주문표 ⛔ 문구 — 예: '⛔ 재협상 2회째 — MIN_RR(주문표 R:R) 2회 · 마지막 2026-10-17'."""
    return "⛔ 재협상 2회째 — " + " · ".join(f"{r['rule']}({r['term']}) {r['count']}회 · 마지막 {r['last']}" for r in rows)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["add", "list"])
    ap.add_argument("rule", nargs="?")
    ap.add_argument("--date")
    a = ap.parse_args(argv)
    on = _d(a.date) if a.date else datetime.now(KST).date()
    if a.cmd == "add":
        print(add(a.rule or "", on))
        return 0
    for r, v in sorted(counts(on).items()):
        print(f"{'⛔' if v['count'] >= RENEGO_WARN_AT else '  '} {r:<20} {v['count']}회 · 마지막 {v['last']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
