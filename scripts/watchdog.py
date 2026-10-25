#!/usr/bin/env python3
"""감시 자동화 (10/21 PM 안 B·E — 토큰 0, 코드만). ops.yml 00:07 KST 회차에서 하루 1번.

감지 5종 (+ 요청 장부)
  zero     데이터 0건/실패 — reports/*_status.json(overall error·n_errors·rows 0), research_views status, research.json 0건, accum 결측/실패
  fresh    신선도 지연 — screener/freshness.py check()(ops/freshness.json 계약) 그대로 재사용 (쓰기 없이)
  toss     토스 live.json(origin/toss-live) 신선도 — 같은 계약의 toss_md 항목
  overdue  보드 마감 초과 — ops/board.json due < 오늘, 상태 완료 아님
  waiting  대기 3일+ — 상태 '대기' 이고 보드에 처음 들어온 날(git 이력·이전 watchdog.json)부터 3일 이상 (마감 초과면 그쪽으로만)
  executor 정시 실행기 20분+ 무소식 — --executor (heartbeat.yml 장중 30분마다, 즉시 텔레그램 · 10/21 A2)
  request  요청 장부 2영업일 미처리 — scripts/round_collect.promotions (라운드 없이도 매일 판정, 보드 P1 '대기' 작업 추가)

결과
  reports/watchdog.json      owner 별 묶음 + 건수 + 사내 메신저(지난 24h 새·닫힘·승격 요청)
  ops/board.json             걸린 작업에 escalated: <날짜>(처음 걸린 날, 우선순위는 그대로) · 작업이 아닌 감지(zero/fresh/toss)는
                             owner 이름으로 'wd-<종류>-<항목>' P1 대기 작업을 열고, 다음 날 감지가 사라지면 자동 완료
  텔레그램                   하루 1통(무음) — 무이상이면 한 줄 + '📮 사내 메신저' 절

  python3 scripts/watchdog.py                 # 드라이런 — 요약만 출력, 파일·텔레그램 없음
  python3 scripts/watchdog.py --apply --send  # ops.yml
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import round_collect as rc  # noqa: E402

KST = timezone(timedelta(hours=9))
BOARD = ROOT / "ops" / "board.json"
LEDGER = ROOT / "docs" / "desk_kb" / "rounds" / "_requests.json"
OUT = ROOT / "reports" / "watchdog.json"
WAIT_DAYS = 3
MSG_MAX = 8   # 사내 메신저 절 종류별 최대 줄 (첫 실행 일괄 승격 같은 폭주 대비)
KIND_KO = {"zero": "데이터0", "fresh": "지연", "toss": "토스", "overdue": "마감초과", "waiting": "대기3일+", "request": "요청승격"}
STATUS_OWNER = {"deriv_hist_status": "파생", "research_status": "데이터"}   # reports/<이름>.json → 담당 (없으면 데이터)
ACCUM = (("accum.json", "퀀트"), ("us_accum.json", "퀀트"))


def _load(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def F(kind: str, owner: str, fid: str, msg: str, task: str | None = None) -> dict:
    d = {"kind": kind, "owner": owner, "id": fid, "msg": msg}
    if task:
        d["task"] = task
    return d


# ── 감지 (순수에 가깝게: 경로·now 를 받는다) ─────────────────────────────────────────
def detect_zero(root: Path = ROOT) -> list[dict]:
    rep = root / "reports"
    out = []
    for p in sorted(rep.glob("*_status.json")):
        d = _load(p)
        if not isinstance(d, dict):
            out.append(F("zero", STATUS_OWNER.get(p.stem, "데이터"), p.stem, f"{p.name} 읽기 실패")); continue
        why = []
        if str(d.get("overall", d.get("status", "ok"))).lower() in ("error", "fail", "failed"):
            why.append(f"overall={d.get('overall', d.get('status'))}")
        if (d.get("n_errors") or 0) > 0 or d.get("errors"):
            why.append(f"오류 {d.get('n_errors') or len(d.get('errors') or [])}건")
        if "rows" in d and not d.get("rows"):
            why.append("rows 0")
        if why:
            out.append(F("zero", STATUS_OWNER.get(p.stem, "데이터"), p.stem, f"{p.name}: " + ", ".join(why)))
    rv = _load(rep / "research_views.json")
    if rv is not None:
        ov = ((rv.get("status") or {}).get("overall") if isinstance(rv, dict) else None) or "?"
        if ov != "ok":
            out.append(F("zero", "애널", "research_views", f"research_views.json status.overall={ov}"))
    rs = _load(rep / "research.json")
    if isinstance(rs, dict) and not rs.get("items"):
        out.append(F("zero", "데이터", "research", "research.json 종목 리포트 0건"))
    for name, owner in ACCUM:
        p = rep / name
        if not p.exists():
            if name == "accum.json":
                out.append(F("zero", owner, "accum", "accum.json 결측"))
            continue
        d = _load(p) or {}
        st = d.get("status")
        n = d.get("n", d.get("n_scanned"))
        if st in ("fail", "stale") or not n:
            out.append(F("zero", owner, p.stem, f"{name} status={st} n={n} {d.get('reason') or ''}".strip()))
    return out


def detect_fresh(now: datetime, root: Path = ROOT, check=None) -> list[dict]:
    """freshness.check(write=False) 재사용. toss_md 는 'toss' 로 분리."""
    if check is None:
        from screener import freshness
        check = lambda: freshness.check(now, root, write=False)
    try:
        o = check()
    except Exception as e:  # noqa: BLE001
        return [F("fresh", "운영", "freshness", f"신선도 점검 실패 {type(e).__name__}: {e}")]
    out = []
    for x in o.get("late") or []:
        xid = str(x.get("id"))
        kind = "toss" if xid.startswith("toss") else "fresh"
        owner = "데이터" if kind == "toss" else "개발" if xid.startswith("calendar_") else "운영"
        out.append(F(kind, owner, xid, f"{x.get('path')}: 기대 {x.get('expected')} · 실제 {x.get('actual')}"))
    return out


def board_history(root: Path = ROOT) -> tuple[dict[str, str], dict[str, int]]:
    """ops/board.json git 이력 한 번 훑어 (작업 id 처음 추가일, 작업 id 별 마감(due) 변경 횟수).
    마감 변경 = 같은 hunk 에서 `-"due": 옛값` 과 `+"due": 새값` 이 다르고 옛값이 null 이 아닌 경우(처음 정하는 건 변경 아님).
    id 는 hunk 안 가장 가까운 앞 `"id"` 줄(-U12 문맥). 이력이 얕은 클론이면 보이는 구간만 센다."""
    try:
        r = subprocess.run(["git", "-C", str(root), "log", "--reverse", "--format=@@%cs", "-p", "--unified=12", "--", "ops/board.json"],
                           capture_output=True, text=True, timeout=60)
    except Exception:  # noqa: BLE001
        return {}, {}
    seen: dict[str, str] = {}
    changes: dict[str, int] = {}
    day, cur, old_due = None, None, None
    pid = re.compile(r'^([+\- ])\s*\{?\s*"id":\s*"([^"]+)"')
    pdue = re.compile(r'^([+-])\s*"due":\s*(null|"[^"]*")')
    for ln in r.stdout.splitlines():
        if ln.startswith("@@") and not ln.startswith("@@ "):
            day, cur, old_due = ln[2:12], None, None
        elif ln.startswith("@@ "):
            cur, old_due = None, None
        elif day:
            m = pid.match(ln)
            if m:
                cur, old_due = m.group(2), None
                if m.group(1) == "+" and cur not in seen:
                    seen[cur] = day
                continue
            m = pdue.match(ln)
            if m and cur:
                if m.group(1) == "-":
                    old_due = m.group(2)
                elif old_due is not None and old_due != "null" and m.group(2) != old_due:
                    changes[cur] = changes.get(cur, 0) + 1
                    old_due = None
    return seen, changes


def board_first_seen(root: Path = ROOT) -> dict[str, str]:
    return board_history(root)[0]


def is_new_finding(f: dict, prev_board: dict, today: str) -> bool:
    """'오늘 새로 생긴 것' 판정. 이미 보드에 escalated 가 찍혀 있거나(어제까지 걸린 것) 오늘 이전부터 이어진 상태면 원래 밀린 것.
    overdue: 마감이 어제(=오늘 처음 초과)일 때만 새 것. waiting: 등록 후 정확히 WAIT_DAYS 일째. 그 외 비작업 감지·요청 승격: 보드에 같은 wd-/작업 id 가 없었으면 새 것."""
    by_id = {t["id"]: t for t in prev_board.get("tasks", [])}
    t0 = date.fromisoformat(today)
    tid = f.get("task") or re.sub(r"[^0-9A-Za-z가-힣_.-]+", "-", f"wd-{f['kind']}-{f['id']}")[:80]
    t = by_id.get(tid)
    if f["kind"] == "request":
        return True   # 승격은 오늘 apply_promotions 가 처음 만든 것
    if t is not None and t.get("escalated") and t["escalated"] < today:
        return False
    if f["kind"] == "overdue":
        return bool(t and t.get("due") == (t0 - timedelta(days=1)).isoformat())
    if f["kind"] == "waiting":
        return f.get("days") == WAIT_DAYS
    return t is None or t.get("escalated") == today


def detect_board(board: dict, today: str, first_seen: dict[str, str]) -> list[dict]:
    out = []
    t0 = date.fromisoformat(today)
    for t in board.get("tasks", []):
        if t.get("status") == "완료" or str(t.get("id", "")).startswith("wd-"):
            continue
        if t.get("due") and t["due"] < today:
            out.append(F("overdue", t["owner"], t["id"], f"마감 {t['due']} 지남 ({t['status']}) {t['title'][:40]}", task=t["id"]))
        elif t.get("status") == "대기":
            fs = first_seen.get(t["id"])
            if fs and (t0 - date.fromisoformat(fs)).days >= WAIT_DAYS:
                days = (t0 - date.fromisoformat(fs)).days
                out.append({**F("waiting", t["owner"], t["id"], f"대기 {days}일 (등록 {fs}) {t['title'][:40]}", task=t["id"]), "days": days})
    return out


# ── 반영 ─────────────────────────────────────────────────────────────────────────
def escalate(board: dict, findings: list[dict], today: str) -> tuple[dict, int, int]:
    """원본 불변. 작업 감지 → escalated 표시(처음 날짜 유지), 비작업 감지 → wd-* P1 작업, 사라진 wd-* 대기 → 완료.
    반환 (새 보드, 새로 escalated 된 수, 자동 완료 수)."""
    B = json.loads(json.dumps(board))
    tasks = B.setdefault("tasks", [])
    by_id = {t["id"]: t for t in tasks}
    n_new = 0
    live_wd = set()
    for f in findings:
        if f["kind"] == "request":
            continue   # round_collect.apply_promotions 가 이미 escalated 를 넣은 작업을 추가함
        tid = f.get("task") or re.sub(r"[^0-9A-Za-z가-힣_.-]+", "-", f"wd-{f['kind']}-{f['id']}")[:80]
        if not f.get("task"):
            live_wd.add(tid)
        t = by_id.get(tid)
        if t is None and not f.get("task"):
            t = {"id": tid, "title": f"[watchdog] {KIND_KO[f['kind']]}: {f['msg'][:70]}", "owner": f["owner"], "priority": "P1",
                 "status": "대기", "started": None, "due": (date.fromisoformat(today) + timedelta(days=2)).isoformat(),
                 "repo": "public", "files": [], "depends_on": [],
                 "notes": "scripts/watchdog.py 자동 생성 — 감지가 사라지면 다음 날 자동 완료."}
            tasks.append(t); by_id[tid] = t
        if t is not None and t.get("status") != "완료" and not t.get("escalated"):
            t["escalated"] = today
            n_new += 1
    n_closed = 0
    for t in tasks:
        if t["id"].startswith("wd-") and t["status"] == "대기" and t["id"] not in live_wd:
            t["status"], t["done"] = "완료", today
            t["notes"] = (t.get("notes") or "") + f" · {today} 감지 해소 → 자동 완료"
            n_closed += 1
    if n_new or n_closed:
        B["updated"] = today
    return B, n_new, n_closed


def _within(r: dict, ts_key: str, d_key: str, since: datetime) -> bool:
    v = r.get(ts_key)
    if v:
        try:
            return datetime.fromisoformat(v) >= since
        except ValueError:
            pass
    d = r.get(d_key)
    return bool(d) and str(d)[:10] >= (since.astimezone(KST).date()).isoformat()


def messenger(ledger: dict, now: datetime, board: dict | None = None) -> dict:
    """지난 24시간 새 요청·닫힌 요청·승격된 요청 → {new, closed, promoted} 각 줄 목록."""
    since = now - timedelta(hours=24)
    due_of = {t["id"]: t.get("due") for t in (board or {}).get("tasks", [])}

    def line(r):
        due = r.get("due") or due_of.get(r.get("task_id") or r["id"]) or "—"
        return f"{rc.desk_owner(r['from'])} → {rc.desk_owner(r['to'])}: {r['text'][:60]}({due})"
    reqs = ledger.get("requests", [])
    return {"new": [line(r) for r in reqs if _within(r, "opened_at", "opened", since)],
            "closed": [line(r) for r in reqs if r.get("status") == "done" and _within(r, "done_at", "done", since)],
            "promoted": [line(r) for r in reqs if r.get("status") == "promoted" and _within(r, "promoted_at", "promoted", since)]}


def render(result: dict) -> str:
    d = result["date"][5:].replace("-", "/")
    by = result["by_owner"]
    n = sum(len(v) for v in by.values())
    if not n:
        lines = [f"🐶 watchdog {d} · 이상 없음"]
    else:
        cnt = " · ".join(f"{KIND_KO[k]} {v}" for k, v in result["counts"].items() if v)
        lines = [f"🐶 watchdog {d} · 이상 {n}건 ({cnt})"]
        if "new_today" in result:
            lines.append(f"🆕 오늘 새로 {result['new_today']} · 원래 밀린 것 {result['backlog']}")
        dch = result.get("due_changed") or {}
        if dch.get("tasks_any"):
            lines.append(f"📅 마감 바뀐 작업 {dch['tasks_any']}건(총 {dch['total_changes']}회, 2회+ {dch['tasks_2plus']}건)")
        for owner, fs in sorted(by.items(), key=lambda kv: -len(kv[1]))[:8]:
            kinds = {}
            for f in fs:
                kinds[f["kind"]] = kinds.get(f["kind"], 0) + 1
            top = next((f for f in fs if f["kind"] in ("zero", "fresh", "toss", "request")), fs[0])
            nn = sum(1 for f in fs if f.get("new"))
            lines.append(f"· {owner} {len(fs)}(새 {nn}) — " + "·".join(f"{KIND_KO[k]}{v}" for k, v in kinds.items()) + f" | {top['msg'][:50]}")
        if len(by) > 8:
            lines.append(f"· 외 {len(by) - 8}개 데스크")
        lines.append(f"보드 ⏫ 새 승격 {result.get('escalated_new', 0)} · 자동 완료 {result.get('auto_closed', 0)} — 상세 reports/watchdog.json")
    m = result.get("messenger") or {}
    if any(m.get(k) for k in ("new", "closed", "promoted")):
        lines += ["", "📮 사내 메신저 (24h)"]
        for k, tag in (("new", "새"), ("closed", "닫힘"), ("promoted", "승격")):
            xs = m.get(k) or []
            lines += [f"{tag} · {x}" for x in xs[:MSG_MAX]] + ([f"{tag} · 외 {len(xs) - MSG_MAX}건 (reports/watchdog.json)"] if len(xs) > MSG_MAX else [])
    return "\n".join(lines)


def run(now: datetime, root: Path = ROOT, apply: bool = False, send: bool = False, out=print,
        fresh_check=None, first_seen: dict | None = None, due_changes: dict | None = None) -> dict:
    today = now.astimezone(KST).date().isoformat()
    board_p, ledger_p, out_p = root / "ops" / "board.json", root / "docs" / "desk_kb" / "rounds" / "_requests.json", root / "reports" / "watchdog.json"
    board = _load(board_p) or {"tasks": []}
    ledger = _load(ledger_p) or {}
    prev = _load(out_p) or {}
    fs = dict(prev.get("first_seen") or {})
    hist = board_history(root) if (first_seen is None or due_changes is None) else ({}, {})
    dc = dict(due_changes if due_changes is not None else hist[1])
    for k, v in (first_seen if first_seen is not None else hist[0]).items():
        fs[k] = min(fs.get(k, v), v)
    for t in board.get("tasks", []):
        fs.setdefault(t["id"], today)
    findings = detect_zero(root) + detect_fresh(now, root, fresh_check) + detect_board(board, today, fs)
    for f in findings:   # 새/밀린 구분은 보드가 바뀌기 전(escalated 찍기 전) 기준
        f["new"] = is_new_finding(f, board, today)
        if f["kind"] == "overdue" and dc.get(f["id"]):
            f["due_changes"] = dc[f["id"]]
    # E: 요청 장부 2영업일 → 보드 P1 (라운드 없이도)
    promos = rc.promotions(ledger, today, board)
    ledger2, board2 = rc.apply_promotions(ledger, board, promos, today)
    stamp = now.astimezone(KST).strftime("%Y-%m-%dT%H:%M+09:00")
    for r in ledger2.get("requests", []):
        if r.get("promoted") == today and r.get("status") == "promoted" and not r.get("promoted_at"):
            r["promoted_at"] = stamp
    for t in promos:
        findings.append({**F("request", t["owner"], t["id"], t["title"][:70], task=t["id"]), "new": True})
    board3, n_new, n_closed = escalate(board2, findings, today)
    by: dict[str, list] = {}
    for f in findings:
        by.setdefault(f["owner"], []).append(f)
    result = {"checked_at": now.astimezone(KST).strftime("%Y-%m-%d %H:%M KST"), "date": today,
              "counts": {k: sum(f["kind"] == k for f in findings) for k in KIND_KO},
              "by_owner": dict(sorted(by.items(), key=lambda kv: -len(kv[1]))),
              "new_today": sum(1 for f in findings if f.get("new")), "backlog": sum(1 for f in findings if not f.get("new")),
              "due_changed": {"tasks_2plus": sum(1 for f in findings if f.get("due_changes", 0) >= 2),
                              "tasks_any": sum(1 for f in findings if f.get("due_changes")),
                              "total_changes": sum(f.get("due_changes", 0) for f in findings),
                              "top": sorted(((f["id"], f["due_changes"]) for f in findings if f.get("due_changes")), key=lambda x: -x[1])[:5]},
              "escalated_new": n_new, "auto_closed": n_closed,
              "messenger": messenger(ledger2, now, board3),
              "first_seen": dict(sorted(fs.items())), "sent": prev.get("sent")}
    text = render(result)
    out(("[APPLY]" if apply else "[DRY-RUN]") + f" watchdog {today} · 감지 {len(findings)}건 · 새 escalated {n_new} · 요청 승격 {len(promos)} · wd 자동완료 {n_closed}")
    out(text)
    if send:
        if prev.get("sent") == today:
            out("  텔레그램: 오늘 이미 보냄 — 건너뜀(하루 1통)")
        else:
            try:
                from screener.report import send_telegram
                import html
                # send_telegram 은 HTML 모드 — 요청 본문의 '<json>' 같은 꺾쇠가 태그로 파싱돼 400(10/21 첫 실행 실패). 전부 이스케이프.
                send_telegram(html.escape(text, quote=False))
                result["sent"] = today
            except Exception as e:  # noqa: BLE001
                out(f"::warning::watchdog 텔레그램 실패: {type(e).__name__}: {e}")
    if apply:
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        if board3 != board:
            board_p.write_text(json.dumps(board3, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if ledger2 != ledger:
            ledger_p.write_text(json.dumps(ledger2, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    else:
        out("  (드라이런 — 파일·텔레그램 없음. 반영은 --apply [--send])")
    return result


# ── 정시 실행기 하트비트 (10/21 A2 — GAS 예약기 정지 08:40·08:50 미발송) ─────────────────────────────
# 하루 1통 묶음과 별개: heartbeat.yml 이 장중 30분마다 --executor --send 로 부른다(커밋 없음).
# GAS 하트비트 = 슬롯마다 남는 workflow_dispatch run 자체, 노트북 하트비트 = toss-live live.json 'dispatcher_heartbeat'.
# 알림은 무음 — RING_KINDS(결재 #9) 다섯 종류 밖이고, defs.TELEGRAM_ALL_SILENT=True 라 소리는 어차피 꺼져 있다.
EXEC_STALE_MIN = 20     # 슬롯 예정 + 이 시간까지 dispatch 가 없으면 '무소식'
EXEC_CHECK_MIN = 30     # heartbeat.yml 간격 — [STALE, STALE+CHECK) 안의 슬롯만 봐서 같은 슬롯을 두 번 알리지 않는다


def detect_executor(now: datetime, gas: dict, runs_of, laptop_hb: dict | None) -> list[dict]:
    """runs_of(wf, since_utc) → workflow_dispatch run 목록. 슬롯 창 [예정+20, 예정+50) 의 미dispatch 슬롯 + 노트북 하트비트 20분+."""
    import slot_guard as g
    k = now.astimezone(KST)
    nm, dow = k.hour * 60 + k.minute, k.isoweekday() % 7
    out, checking = [], False
    for s in gas["slots"]:
        late = nm - s["min"]
        if dow not in s["days"] or not (EXEC_STALE_MIN <= late < EXEC_STALE_MIN + EXEC_CHECK_MIN):
            continue
        checking = True
        since = (k - timedelta(minutes=late + g.SINCE_PAD_MIN)).replace(second=0, microsecond=0).astimezone(timezone.utc)
        try:
            hit = g.primary_ran(runs_of(s["wf"], since), g.gas_key(s), since)
        except Exception as e:  # noqa: BLE001
            out.append(F("executor", "개발", f"api-{s['time']}", f"실행 목록 조회 실패 {type(e).__name__} — {s['time']} 확인 불가")); continue
        if not hit:
            out.append(F("executor", "개발", f"{s['time']}-{s['wf']}-{g.gas_key(s)}",
                         f"{s['time']} {s['wf']} [{g.gas_key(s)}] {late}분째 dispatch 없음 — GAS·노트북 둘 다 무소식"))
    if checking:
        lr = (laptop_hb or {}).get("last_run")
        try:
            age = (k - datetime.fromisoformat(lr)).total_seconds() / 60 if lr else None
        except ValueError:
            age = None
        if age is None or age >= EXEC_STALE_MIN:
            out.append(F("executor", "개발", "laptop", "노트북 dispatcher 하트비트 " + (f"{age:.0f}분 전" if age is not None else "없음")))
    return out


def run_executor(now: datetime, send: bool = False, out=print, runs_of=None, laptop_hb=None) -> list[dict]:
    import slot_guard as g
    if runs_of is None:
        runs_of = g.list_runs
    if laptop_hb is None:
        try:
            from screener import toss_live
            laptop_hb = (toss_live.fetch() or {}).get("dispatcher_heartbeat")
        except Exception:  # noqa: BLE001
            laptop_hb = None
    fs = detect_executor(now, g.parse_gas(), runs_of, laptop_hb)
    slots = [f for f in fs if f["id"] != "laptop"]
    text = (f"⏰ 정시 실행기 무소식 {now.astimezone(KST):%H:%M}\n" + "\n".join("· " + f["msg"] for f in fs)
            + "\n→ GAS tickTest·노트북 dispatcher 확인 (docs/toss_md_laptop_setup.md ⑧)") if fs else ""
    out(text or f"executor {now.astimezone(KST):%H:%M} — 이상 없음")
    if send and slots:   # 노트북 하트비트만 늦은 건(GAS 는 정상 dispatch) 출력만 — 슬롯 누락일 때만 텔레그램
        try:
            from screener.report import send_telegram
            import html
            send_telegram(html.escape(text, quote=False))
        except Exception as e:  # noqa: BLE001
            out(f"::warning::executor 텔레그램 실패: {type(e).__name__}")
    return fs


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--send", action="store_true", help="텔레그램 하루 1통 (--apply 와 함께 — 보낸 날을 watchdog.json 에 기록)")
    ap.add_argument("--now", help="YYYY-MM-DDTHH:MM (테스트·재현용, KST)")
    ap.add_argument("--executor", action="store_true", help="정시 실행기 하트비트만 (heartbeat.yml, 장중 30분마다)")
    a = ap.parse_args(argv)
    now = datetime.fromisoformat(a.now).replace(tzinfo=KST) if a.now else datetime.now(KST)
    if a.executor:
        run_executor(now, send=a.send)
        return 0
    run(now, apply=a.apply, send=a.send and a.apply)
    return 0


if __name__ == "__main__":
    sys.exit(main())
