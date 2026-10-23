#!/usr/bin/env python3
"""데스크→데스크 요청을 요청 장부(docs/desk_kb/rounds/_requests.json)에 PB 경유 없이 추가·닫기 (10/21 PM 안 E).

  python3 scripts/ask.py --from 퀀트 --to 데이터 --text "accum 60일 이력 백필 일정 회신" --due 2026-10-24
  python3 scripts/ask.py --from 겸이 --to 매크로 --text "..."            # 겸이(오너)도 같은 장부 — 텔레그램 'ask <데스크> <내용>'
  python3 scripts/ask.py --close req-data-1a2b3c4d [--by 데이터]           # 처리 끝 → 닫기
  python3 scripts/ask.py --reply req-data-1a2b3c4d --by 데이터 --text "..." --voc   # 회신(사내톡) — --voc = 데스크 에이전트가 직접 쓴 말
  python3 scripts/ask.py --chat --by 퀀트 [--to 데이터] --text "..."              # 사담(사내톡 잡담 — 업무 판단 근거 아님)
  python3 scripts/ask.py --issue-title "ask 퀀트" --issue-body "..."       # ask.yml (GitHub 이슈) 경로, from=겸이

마감(--due) 기본 = 요청일 + 2영업일(KR). 2영업일 지나도 open 이면 watchdog(매일 00:07 KST)·round_collect 가 보드 P1 승격.
라운드 파일의 `요청→<데스크>: …` 줄과 같은 장부·같은 id 규칙(round_collect.req_id)이라 중복으로 안 쌓인다.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import round_collect as rc  # noqa: E402

KST = timezone(timedelta(hours=9))
OWNER = "겸이"
DUE_BDAYS = 2
TRAILER = re.compile(r"\n*\(텔레그램[^)]*\)\s*$")


def desk_ok(name: str) -> str | None:
    """'퀀트'·'quant' → 'quant'. 모르는 데스크면 None."""
    k = rc.desk_key(name)
    return k if k in rc.DESKS else None


def add_bdays(d: date, n: int) -> date:
    """d 뒤로 n 번째 KR 영업일 (round_collect.biz_days 와 같은 달력)."""
    x = d
    while n > 0:
        x += timedelta(days=1)
        n -= rc.biz_days((x - timedelta(days=1)).isoformat(), x.isoformat())
    return x


def parse_ask_text(text: str) -> dict | None:
    """텔레그램 텍스트 → {desk, text} · {error} · None(ask 아님). apps-script/TelegramHook.gs tgParseAsk_ 와 같은 규칙."""
    t = str(text or "").strip()
    m = re.match(r"^/?ask(?=\s|$)\s*([\s\S]*)$", t, re.I)
    if not m:
        return None
    rest = m.group(1).strip()
    parts = rest.split(None, 1)
    if len(parts) < 2 or not desk_ok(parts[0]):
        return {"error": "형식: ask <데스크> <내용> — 데스크: " + " ".join(rc.DESKS.values())}
    return {"desk": rc.desk_owner(desk_ok(parts[0])), "text": parts[1].strip()}


def add(ledger: dict, frm: str, to: str, text: str, due: str | None, now: datetime) -> tuple[dict, dict]:
    """장부(원본 불변)에 요청 1건 추가 → (새 장부, 추가·기존 항목). 같은 (from, to, 본문 앞 40자) 면 기존 항목을 돌려준다."""
    L = json.loads(json.dumps(ledger)) if ledger else {}
    L.setdefault("_doc", "강화 루프 요청 장부 — scripts/round_collect.py·scripts/ask.py 가 쓴다. 손으로 고치지 말 것.")
    reqs = L.setdefault("requests", [])
    fk = OWNER if frm == OWNER else desk_ok(frm)
    tk = desk_ok(to)
    if not fk or not tk:
        raise ValueError(f"모르는 데스크: from={frm} to={to}")
    text = TRAILER.sub("", text.strip()).strip()
    if not text:
        raise ValueError("내용이 비었음")
    rid = rc.req_id(fk, tk, text)
    for r in reqs:
        if r["id"] == rid and r["status"] == "open":
            return L, r
    today = now.astimezone(KST).date()
    r = {"id": rid, "from": fk, "to": tk, "text": text, "opened": today.isoformat(),
         "opened_at": now.astimezone(KST).strftime("%Y-%m-%dT%H:%M+09:00"),
         "due": due or add_bdays(today, DUE_BDAYS).isoformat(), "via": "ask",
         "seen": [today.isoformat()], "checked": [today.isoformat()], "pending_rounds": 0, "status": "open"}
    reqs[:] = [x for x in reqs if x["id"] != rid] + [r]
    reqs.sort(key=lambda x: (x["opened"], x["id"]))
    L["updated"] = today.isoformat()
    return L, r


def close(ledger: dict, rid: str, by: str | None, now: datetime) -> tuple[dict, dict]:
    L = json.loads(json.dumps(ledger))
    for r in L.get("requests", []):
        if r["id"] == rid:
            if r["status"] in ("open", "promoted"):
                r["status"], r["done"] = "done", now.astimezone(KST).date().isoformat()
                r["done_at"] = now.astimezone(KST).strftime("%Y-%m-%dT%H:%M+09:00")
                if by:
                    r["done_by"] = by
            return L, r
    raise KeyError(rid)


def reply(ledger: dict, rid: str, by: str, text: str, voc: bool, now: datetime) -> tuple[dict, dict]:
    """요청에 회신 1건 추가(사내톡 탭 말풍선, 10/23 겸이 "실제 누나들의 voc로").
    voc=True = 그 데스크 에이전트를 실제로 호출해 받은 답을 무편집으로 옮긴 것. False = 진행자·PB 대행 요약."""
    L = json.loads(json.dumps(ledger))
    k = OWNER if by == OWNER else desk_ok(by)
    if not k:
        raise ValueError(f"모르는 데스크: by={by}")
    text = text.strip()
    if not text:
        raise ValueError("회신 내용이 비었음")
    for r in L.get("requests", []):
        if r["id"] == rid:
            r.setdefault("replies", []).append({"by": k, "at": now.astimezone(KST).strftime("%Y-%m-%dT%H:%M+09:00"),
                                                "text": text, "voc": bool(voc)})
            return L, r
    raise KeyError(rid)


def chat(ledger: dict, by: str, to: str | None, text: str, now: datetime) -> tuple[dict, dict]:
    """사담 1줄(10/23 겸이 "좀 사담들도 넣고"). 데스크 에이전트가 라운드·루프 중 직접 쓴 잡담만 — 업무 VOC·판단 근거로 인용 금지.
    공개 저장소라 겸이 금액·보유·건강·연애·실존 인물 언급 금지(scripts/ask.py 는 길이만 막고, 내용은 프롬프트 규칙)."""
    L = json.loads(json.dumps(ledger)) if ledger else {}
    k = desk_ok(by)
    t = desk_ok(to) if to else None
    if not k or (to and not t):
        raise ValueError(f"모르는 데스크: by={by} to={to}")
    text = " ".join(text.split())
    if not text or len(text) > 160:
        raise ValueError("사담은 1~160자")
    c = {"by": k, "at": now.astimezone(KST).strftime("%Y-%m-%dT%H:%M+09:00"), "text": text}
    if t:
        c["to"] = t
    L.setdefault("chat", []).append(c)
    return L, c


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="frm")
    ap.add_argument("--to")
    ap.add_argument("--text")
    ap.add_argument("--due", help="YYYY-MM-DD (기본 2영업일 뒤)")
    ap.add_argument("--close", metavar="ID")
    ap.add_argument("--by")
    ap.add_argument("--reply", metavar="ID")
    ap.add_argument("--chat", action="store_true", help="사담 1줄 (--by, 선택 --to, --text)")
    ap.add_argument("--voc", action="store_true", help="--reply 가 데스크 에이전트 실제 발언(무편집)일 때")
    ap.add_argument("--issue-title")
    ap.add_argument("--issue-body", default="")
    ap.add_argument("--ledger", type=Path, default=rc.ROUNDS_DIR / "_requests.json")
    a = ap.parse_args(argv)
    now = datetime.now(KST)
    led = json.loads(a.ledger.read_text(encoding="utf-8")) if a.ledger.exists() else {}
    try:
        if a.chat:
            if not (a.by and a.text):
                ap.error("--chat 은 --by --text 필요")
            L, r = chat(led, a.by, a.to, a.text, now)
            msg = f"☕ 사담 {a.by}: {r['text'][:60]}"
        elif a.reply:
            if not (a.by and a.text):
                ap.error("--reply 는 --by --text 필요")
            L, r = reply(led, a.reply, a.by, a.text, a.voc, now)
            msg = f"💬 회신 {r['id']} · {a.by}{' (VOC)' if a.voc else ' (대행)'}"
        elif a.close:
            L, r = close(led, a.close, a.by, now)
            msg = f"닫음 {r['id']} ({rc.desk_owner(r['from'])} → {rc.desk_owner(r['to'])})"
        else:
            if a.issue_title is not None:   # ask.yml: 제목 'ask <데스크>', 본문 = 내용 (from 은 항상 겸이 — 워크플로가 주인 이슈만 받음)
                p = parse_ask_text(a.issue_title.strip() + " " + (a.issue_body or "").strip())
                if not p or "error" in p:
                    print((p or {}).get("error", "ask 이슈 아님")); return 2
                a.frm, a.to, a.text = OWNER, p["desk"], p["text"]
            if not (a.frm and a.to and a.text):
                ap.error("--from --to --text 필요 (또는 --close / --issue-title)")
            L, r = add(led, a.frm, a.to, a.text, a.due, now)
            msg = f"📮 접수 {r['id']} · {rc.desk_owner(r['from'])} → {rc.desk_owner(r['to'])}: {r['text'][:80]} (마감 {r.get('due', '—')})"
    except (ValueError, KeyError) as e:
        print(f"실패: {e}"); return 2
    a.ledger.parent.mkdir(parents=True, exist_ok=True)
    a.ledger.write_text(json.dumps(L, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
