#!/usr/bin/env python3
"""사내톡 피드 — 요청 장부 + 회신을 터미널 SYSTEM › 사내톡 탭용으로 묶는다 (10/23 겸이 "터미널에 사내톡 탭 만들어줘 자동갱신되게, 그리고 실제 누나들의 voc로").

입력
- docs/desk_kb/rounds/_requests.json — 요청(from→to) + replies[{by, at, text, voc}] (scripts/ask.py --reply)
- docs/desk_kb/rounds/*-msg-*.md — 사내 메신저 라운드 기록. 요청 id 가 들어간 '- `req-…`' 줄은 진행자 대행 회신(voc=False)으로 붙인다(옛 기록 호환).

출력: reports/msgr_feed.md — 내용은 JSON 한 덩어리.
  확장자가 .md 인 이유: GAS 는 Code.gs 의 getter 만 GitHub 에서 읽는데, 새 getter 를 만들면 겸이가 Code.gs 를 다시 붙여넣어야 한다.
  기존 getMarkdown(name)(reports/<name>.md 원문 반환)을 그대로 쓰면 HTML 탭만 추가해도 된다.

사용: python3 scripts/msgr_feed.py [--out reports/msgr_feed.md]   (표준 라이브러리만)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROUNDS = ROOT / "docs" / "desk_kb" / "rounds"
KST = timezone(timedelta(hours=9))
RID = re.compile(r"req-[a-z]+-[0-9a-f]{8}")
MSG = re.compile(r"(\d{4}-\d{2}-\d{2})-msg-(\d{2})(\d{2})\.md$")
KEEP = ("id", "from", "to", "text", "opened", "opened_at", "due", "status", "done_at", "done_by", "resolution", "promoted_at")


def round_replies(rounds: Path) -> dict[str, list[dict]]:
    """메신저 라운드 기록의 요청별 줄 → 대행 회신."""
    out: dict[str, list[dict]] = {}
    for f in sorted(rounds.glob("*-msg-*.md")):
        m = MSG.search(f.name)
        if not m:
            continue
        at = f"{m.group(1)}T{m.group(2)}:{m.group(3)}+09:00"
        sec = ""
        for ln in f.read_text(encoding="utf-8").splitlines():
            if ln.startswith("## "):
                sec = ln[3:].strip()
                continue
            ids = RID.findall(ln)
            if not (ln.startswith("- ") and ids):
                continue
            t = re.sub(r"^- `req-[a-z]+-[0-9a-f]{8}`\s*(\([^)]*\))?\s*:?\s*", "", ln.strip()).replace("**", "").strip()
            out.setdefault(ids[0], []).append({"by": None, "at": at, "text": t, "voc": False, "sec": sec, "src": f.name})
    return out


def build(ledger: dict, rounds: Path, now: datetime) -> dict:
    rr = round_replies(rounds)
    items = []
    for r in ledger.get("requests", []):
        x = {k: r.get(k) for k in KEEP if r.get(k) is not None}
        reps = [dict(p) for p in rr.get(r["id"], [])]
        for p in reps:
            p["by"] = r["to"]
        reps += [dict(p, sec="회신") for p in r.get("replies", [])]
        reps.sort(key=lambda p: p.get("at") or "")
        x["replies"] = reps
        items.append(x)
    items.sort(key=lambda x: (x.get("opened_at") or x.get("opened") or ""), reverse=True)
    st = {}
    for x in items:
        st[x["status"]] = st.get(x["status"], 0) + 1
    return {"asof": now.strftime("%Y-%m-%d %H:%M"), "n": len(items), "status": st,
            "n_reply": sum(1 for x in items if x["replies"]),
            "n_voc": sum(1 for x in items for p in x["replies"] if p.get("voc")),
            "items": items}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=ROOT / "reports" / "msgr_feed.md")
    ap.add_argument("--ledger", type=Path, default=ROUNDS / "_requests.json")
    a = ap.parse_args(argv)
    led = json.loads(a.ledger.read_text(encoding="utf-8")) if a.ledger.exists() else {}
    feed = build(led, a.ledger.parent, datetime.now(KST))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(feed, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"사내톡 피드 {feed['n']}건 · 회신 {feed['n_reply']} · VOC {feed['n_voc']} → {a.out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
