#!/usr/bin/env python3
"""강화 루프 라운드 수집 (코디네이터 보조 — 운영 데스크).

docs/desk_kb/rounds/<date>/*.md 를 읽어
  1) 데스크별 5항목(배움·고침·피어·복기) 유무와 마지막 줄 `요청→<데스크>: …` 을 모은다
  2) docs/desk_kb/_scoreboard.md 의 **라운드 표**에 1줄씩 붙인다 (같은 라운드·데스크 줄은 다시 안 붙임)
  3) 요청 장부(docs/desk_kb/rounds/_requests.json)에 요청을 누적하고, 대상 데스크가 다음 라운드 파일에
     `처리→<요청 데스크>: …` 를 쓰지 않아 **2라운드 연속 미처리**면 ops/board.json 에 P1 '대기' 작업으로 승격한다

기본은 **드라이런**: 바뀔 내용만 출력하고 아무 파일도 쓰지 않는다. 실제 반영은 --apply.

  python3 scripts/round_collect.py                       # 오늘(KST) 라운드, 드라이런
  python3 scripts/round_collect.py --date 2026-10-17 --apply

라운드 파일 규약(LOOP.md): 1~5 항목 각 3줄 이내, 마지막 줄 `요청→<데스크>: …`.
응답 규약(이 스크립트가 추가): 요청을 받은 데스크는 자기 라운드 파일에 `처리→<요청 데스크>: …` 한 줄 — 그래야 장부가 닫힌다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUNDS_DIR = ROOT / "docs" / "desk_kb" / "rounds"
SCOREBOARD = ROOT / "docs" / "desk_kb" / "_scoreboard.md"
BOARD = ROOT / "ops" / "board.json"
LEDGER = ROUNDS_DIR / "_requests.json"
KST = timezone(timedelta(hours=9))

PROMOTE_AFTER = 2          # 연속 미처리 라운드 수 → P1 승격
PROMOTE_DUE_DAYS = 7

# 라운드 파일명(영문 소문자 키) ↔ 보드 담당 이름. 요청 줄은 어느 쪽으로 써도 받는다.
DESKS = {
    "pb": "PB", "quant": "퀀트", "bonds": "채권", "frm": "리스크", "backtest": "백테스트", "life": "LIFE",
    "alloc": "자산배분", "macro": "매크로", "ops": "운영", "pm": "PM", "health": "헬스", "cio": "CIO",
    "derivs": "파생", "analyst": "애널", "dev": "개발", "edu": "교육", "data": "데이터", "verify": "검증",
    "eval": "평가", "peer": "피어리뷰", "behavior": "행동",
}
_KO2KEY = {v: k for k, v in DESKS.items()}

ITEMS = ("배움", "고침", "피어", "복기")
_ITEM_PAT = {
    "배움": re.compile(r"배움|배우기"),
    "고침": re.compile(r"고침|고치기"),
    "피어": re.compile(r"피어"),
    "복기": re.compile(r"복기"),
}
# 항목 머리줄: '## 2. 배우기', '2) 배움 —', '**고치기**', '- 피어:' 처럼 줄 앞머리에 표식이 있고 키워드가 가까이 있는 줄
_HEAD = re.compile(r"^\s*(?:#{1,6}\s*|\d+[.)]\s*|\*\*|-\s+|•\s*)\s*([^\n]{0,24})")
REQ = re.compile(r"^\s*요청\s*→\s*([^:：]+?)\s*[:：]\s*(.+?)\s*$")
RESP = re.compile(r"^\s*(?:처리|답|완료)\s*→\s*([^:：]+?)\s*[:：]\s*(.+?)\s*$")
_WS = re.compile(r"[\s\W_]+", re.U)


# ---------------------------------------------------------------- 순수 함수
def desk_key(name: str) -> str:
    """'개발' → 'dev', 'dev' → 'dev', 모르는 이름은 소문자 그대로."""
    n = name.strip()
    if n in _KO2KEY:
        return _KO2KEY[n]
    return n.lower()


def desk_owner(key: str) -> str:
    return DESKS.get(key, key)


def norm_text(s: str) -> str:
    return _WS.sub("", s).lower()


def req_id(frm: str, to: str, text: str) -> str:
    h = hashlib.sha1(f"{frm}|{to}|{norm_text(text)[:40]}".encode()).hexdigest()[:8]
    return f"req-{to}-{h}"


def parse_round_file(text: str, desk: str) -> dict:
    """라운드 파일 한 장 → {desk, items{배움:bool,…}, requests[(to_key, text)], responses[(to_key, text)]}."""
    lines = text.splitlines()
    heads: list[tuple[int, str]] = []
    for i, ln in enumerate(lines):
        m = _HEAD.match(ln)
        if not m or not ln.strip():
            continue
        head = m.group(1)
        for item, pat in _ITEM_PAT.items():
            if pat.search(head):
                heads.append((i, item))
                break
    items = {k: False for k in ITEMS}
    for n, (i, item) in enumerate(heads):
        end = heads[n + 1][0] if n + 1 < len(heads) else len(lines)
        body = [l for l in lines[i + 1:end] if l.strip() and not REQ.match(l) and not RESP.match(l)]
        # 머리줄 자체에 내용이 붙은 경우('**배움** — …', '2) 배움: …')도 인정
        inline = re.sub(r"^\s*(?:#{1,6}\s*|\d+[.)]\s*|\*\*|-\s+|•\s*)", "", lines[i])
        inline = re.sub(r"^[^—:\-–]*(?:\*\*)?\s*[—:\-–]\s*", "", inline, count=1) if re.search(r"[—:\-–]", inline) else ""
        if body or len(inline.strip()) >= 8:
            items[item] = True
    requests, responses = [], []
    for ln in lines:
        m = REQ.match(ln)
        if m:
            requests.append((desk_key(m.group(1)), m.group(2)))
            continue
        m = RESP.match(ln)
        if m:
            responses.append((desk_key(m.group(1)), m.group(2)))
    return {"desk": desk, "items": items, "requests": requests, "responses": responses}


def collect_round(round_dir: Path) -> list[dict]:
    """<date>/ 안의 *.md (밑줄로 시작하는 파일 제외) → 데스크별 파싱 결과, 데스크 키 순."""
    out = []
    for p in sorted(round_dir.glob("*.md")):
        if p.name.startswith("_"):
            continue
        out.append(parse_round_file(p.read_text(encoding="utf-8"), p.stem))
    return out


ROUND_HEAD = "## 라운드 표"
ROUND_COLS = "| 라운드 | 데스크 | 배움 | 고침 | 피어 | 복기 | 요청수 |"
ROUND_SEP = "|---|---|---|---|---|---|---|"


def round_rows(rnd: str, parsed: list[dict]) -> list[str]:
    mark = lambda b: "✓" if b else "—"
    return [f"| {rnd} | {p['desk']} | " + " | ".join(mark(p["items"][k]) for k in ITEMS) + f" | {len(p['requests'])} |"
            for p in parsed]


def append_scoreboard(text: str, rnd: str, parsed: list[dict]) -> tuple[str, int]:
    """_scoreboard.md 본문에 라운드 표 줄을 붙인 새 본문과 추가된 줄 수. 이미 있는 (라운드, 데스크) 줄은 건너뛴다."""
    lines = text.rstrip("\n").split("\n") if text.strip() else []
    if ROUND_HEAD not in lines:
        if lines:
            lines.append("")
        lines += [ROUND_HEAD, "", "라운드 파일(docs/desk_kb/rounds/<날짜>/<데스크>.md)에서 자동 수집 — `scripts/round_collect.py`. "
                  "✓ = 항목 작성, 요청수 = `요청→` 줄 수. 2라운드 연속 미처리 요청은 보드 P1 승격.", "",
                  ROUND_COLS, ROUND_SEP]
    have = set()
    for ln in lines:
        m = re.match(r"^\|\s*(\S+)\s*\|\s*(\S+)\s*\|", ln)
        if m:
            have.add((m.group(1), m.group(2)))
    new = [r for r in round_rows(rnd, parsed) if (rnd, r.split("|")[2].strip()) not in have]
    # 표 끝(헤더 뒤 마지막 '|' 줄) 다음에 끼운다 — 표 뒤에 다른 절이 와도 표가 깨지지 않게
    hi = lines.index(ROUND_HEAD)
    end = hi
    for i in range(hi + 1, len(lines)):
        if lines[i].startswith("|"):
            end = i
        elif lines[i].startswith("## "):
            break
    lines[end + 1:end + 1] = new
    return "\n".join(lines) + "\n", len(new)


def update_ledger(ledger: dict, rnd: str, parsed: list[dict]) -> dict:
    """요청 장부 갱신(원본 변경 없이 새 dict).

    - 이미 열린 요청: 이번 라운드에 대상 데스크가 `처리→<요청 데스크>` 를 썼으면 done, 아니면 pending_rounds+1
      (같은 라운드를 두 번 돌려도 한 번만 센다: checked 에 라운드 기록)
    - 새 요청: (from, to, 본문 앞 40자 정규화) 가 같으면 기존 항목에 합치고, 아니면 pending_rounds=1 로 연다
    """
    L = json.loads(json.dumps(ledger)) if ledger else {}
    L.setdefault("_doc", "강화 루프 요청 장부 — scripts/round_collect.py 가 쓴다. 손으로 고치지 말 것.")
    reqs: dict[str, dict] = {r["id"]: r for r in L.get("requests", [])}
    responses = {(p["desk"], to) for p in parsed for to, _ in p["responses"]}      # (답한 데스크, 요청했던 데스크)
    for r in reqs.values():
        if r["status"] != "open" or rnd in r.get("checked", []):
            continue
        r.setdefault("checked", []).append(rnd)
        if (r["to"], r["from"]) in responses:
            r["status"], r["done"] = "done", rnd
        else:
            r["pending_rounds"] = r.get("pending_rounds", 0) + 1
    for p in parsed:
        for to, text in p["requests"]:
            rid = req_id(p["desk"], to, text)
            r = reqs.get(rid)
            if r is None:
                reqs[rid] = {"id": rid, "from": p["desk"], "to": to, "text": text, "opened": rnd, "seen": [rnd],
                             "checked": [rnd], "pending_rounds": 1, "status": "open"}
            elif rnd not in r["seen"]:
                r["seen"].append(rnd)
                if r["status"] == "done" and r.get("done") != rnd:   # 닫힌 뒤 라운드에 또 요청 → 다시 연다 (같은 라운드 답+재요청은 답이 이김)
                    r["status"], r["pending_rounds"] = "open", 1
                    r["checked"] = [rnd]
    L["requests"] = sorted(reqs.values(), key=lambda r: (r["opened"], r["id"]))
    L["updated"] = rnd
    return L


def promotions(ledger: dict, rnd: str, board: dict, after: int = PROMOTE_AFTER) -> list[dict]:
    """승격 대상 요청 → 보드 작업(dict) 목록. 이미 보드에 같은 id 가 있거나 status 가 open 이 아니면 제외."""
    have = {t["id"] for t in board.get("tasks", [])}
    due = (date.fromisoformat(rnd) + timedelta(days=PROMOTE_DUE_DAYS)).isoformat()
    out = []
    for r in ledger.get("requests", []):
        if r["status"] != "open" or r.get("pending_rounds", 0) < after or r["id"] in have:
            continue
        out.append({
            "id": r["id"],
            "title": f"[요청 승격] {desk_owner(r['from'])}→{desk_owner(r['to'])}: {r['text'][:60]}",
            "owner": desk_owner(r["to"]), "priority": "P1", "status": "대기", "started": None, "due": due,
            "repo": "public", "files": [], "depends_on": [],
            "notes": f"강화 루프 요청 {r['pending_rounds']}라운드 연속 미처리({r['opened']}~{rnd}) → 자동 승격(LOOP.md). "
                     f"처리 후 {desk_owner(r['to'])} 라운드 파일에 `처리→{desk_owner(r['from'])}: …` 한 줄.",
        })
    return out


def apply_promotions(ledger: dict, board: dict, tasks: list[dict], rnd: str) -> tuple[dict, dict]:
    """보드에 작업 추가 + 장부 상태 promoted. 원본은 건드리지 않는다."""
    B = json.loads(json.dumps(board))
    L = json.loads(json.dumps(ledger))
    ids = {t["id"] for t in tasks}
    B.setdefault("tasks", []).extend(tasks)
    if tasks:
        B["updated"] = rnd
    for r in L.get("requests", []):
        if r["id"] in ids:
            r["status"], r["task_id"], r["promoted"] = "promoted", r["id"], rnd
    return L, B


def run(rnd: str, rounds_dir: Path, scoreboard: Path, board: Path, ledger_path: Path, apply: bool, out=print) -> int:
    rd = rounds_dir / rnd
    if not rd.is_dir():
        out(f"라운드 폴더 없음: {rd}"); return 1
    parsed = collect_round(rd)
    if not parsed:
        out(f"라운드 파일 없음: {rd}"); return 1
    sb_text = scoreboard.read_text(encoding="utf-8") if scoreboard.exists() else ""
    new_sb, n_rows = append_scoreboard(sb_text, rnd, parsed)
    ledger = json.loads(ledger_path.read_text(encoding="utf-8")) if ledger_path.exists() else {}
    new_ledger = update_ledger(ledger, rnd, parsed)
    bd = json.loads(board.read_text(encoding="utf-8"))
    tasks = promotions(new_ledger, rnd, bd)
    new_ledger, new_bd = apply_promotions(new_ledger, bd, tasks, rnd)

    tag = "APPLY" if apply else "DRY-RUN"
    out(f"[{tag}] 라운드 {rnd} · 데스크 {len(parsed)} · 요청 {sum(len(p['requests']) for p in parsed)} · "
        f"응답 {sum(len(p['responses']) for p in parsed)}")
    for r in round_rows(rnd, parsed):
        out("  " + r)
    out(f"  스코어보드 추가 {n_rows}줄 · 장부 열린 요청 {sum(r['status'] == 'open' for r in new_ledger['requests'])}건")
    for r in new_ledger["requests"]:
        if r["status"] == "open":
            out(f"    - {r['id']} {r['from']}→{r['to']} 미처리 {r['pending_rounds']}R: {r['text'][:50]}")
    for t in tasks:
        out(f"  보드 P1 승격: {t['id']} ({t['owner']}) {t['title']}")
    if not apply:
        out("  (드라이런 — 파일 미변경. 반영은 --apply)")
        return 0
    scoreboard.write_text(new_sb, encoding="utf-8")
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(json.dumps(new_ledger, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    if tasks:
        board.write_text(json.dumps(new_bd, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        out("  ops/board.json 갱신 — `python3 scripts/board.py --check` 후 커밋")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", default=datetime.now(KST).strftime("%Y-%m-%d"), help="라운드 날짜 (기본 오늘 KST)")
    ap.add_argument("--apply", action="store_true", help="실제로 쓴다 (기본 드라이런)")
    ap.add_argument("--rounds-dir", type=Path, default=ROUNDS_DIR)
    ap.add_argument("--scoreboard", type=Path, default=SCOREBOARD)
    ap.add_argument("--board", type=Path, default=BOARD)
    ap.add_argument("--ledger", type=Path, default=None, help="요청 장부 (기본 <rounds-dir>/_requests.json)")
    a = ap.parse_args(argv)
    return run(a.date, a.rounds_dir, a.scoreboard, a.board, a.ledger or a.rounds_dir / "_requests.json", a.apply)


if __name__ == "__main__":
    sys.exit(main())
