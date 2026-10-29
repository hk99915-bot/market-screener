"""STUDY 진행 기록 (평가 데스크) — GitHub 이슈 `study <module_id> done` → reports/study_progress.json.

워크플로 `.github/workflows/study.yml` 이 저장소 주인이 연 이슈를 읽어 호출한다(pick.yml 과 같은 경로).

이슈 형식
  제목  study <module_id> done
  본문  quiz <qid> <답>               (선택, 한 줄에 하나. 답 = 번호 0~3 또는 선택지 문장 앞부분 2자+)
        min <n>                      (선택, 걸린 분)
  퀴즈만(모듈 완료 아님): 제목 `study quiz` + 본문 `quiz <qid> <답>` — 텔레그램 답장 'quiz H2-b2 브레이크' 경로
  (10/24 겸이 결재 G3: 퀴즈 응답 텔레그램 수집 허용. 문장 답은 선택지 순서가 바뀌어도 같은 선택지로 채점 — 10/23 셔플 오채점 방지)

파일  reports/study_progress.json
  {"note", "done":[{id,date,min}], "quiz":[{qid,module,answer,correct,ok,date}], "streak", "last",
   "unlocked":[id…],                                 ← 게이트(index.json gate) 밖 모듈 중 '앞 모듈 done'으로 열린 것
   "modules":{id:{done:[날짜], stage, next_due, scores:[[날짜, 비율]]}}}   ← study_daily 복습 선택용 파생 뷰
  + STUDY 탭 내보내기(apply_export) → "days":[활동일], "exports":[{v,sent,issue}], "summary":{영역·유형별 비율·횟수}
    문항 단위 기록(문항id → 정답 여부·초·날짜)은 공개 파일에 두지 않는다 — pb-private study/items.json 에만
    (10/24 피어리뷰 E2: 공개는 비율만). 같은 문항은 **첫 응답 고정**(E1, kb:eval#8 사전 커밋 · req-dev-826c4bf0).
  날짜는 모두 KST. tz "K" = 한국 날짜 확정, "U" = 옛(v1) UTC 날짜 → 한국 날짜는 같은 날 또는 +1일.
오답은 reports/study_wrong.json 에 쌓고 docs/desk_kb/_quiz_feedback.md 큐에 한 줄 추가한다
(모듈·데스크·개념·오답 — 해당 데스크 KB '흔한 오해' 후보, 피드백 루프). 금액·보유 없음. 네트워크 없음.

  python -m screener.study_progress --title "study H2 done" --body "quiz H2-b4 1\\nmin 15"
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
KST = ZoneInfo("Asia/Seoul")
REPO = "hk99915-bot/market-screener"
INTERVALS = [1, 3, 7, 21]
TRACK_DESK = {"H": "behavior", "R": "frm", "D": "derivs", "Q": "quant", "M": "cio", "A": "behavior", "0": "macro", "B": "quant"}
INITIAL = {"note": "10/17 시작, 출석 = done 이슈 + STUDY 내보내기 활동일(KST)", "done": [], "quiz": [], "streak": 0, "last": None, "unlocked": [], "modules": {}}

TITLE_RE = re.compile(r"^\s*study\s+([0-9A-Za-z][\w-]*)\s+done\s*$", re.I)
QUIZ_RE = re.compile(r"^\s*quiz\s+(\S+)\s+(.+?)\s*$", re.I)
QUIZ_ONLY_RE = re.compile(r"^\s*study\s+quiz\s*$", re.I)
_TEXT_ANS = re.compile(r"[가-힣A-Za-z]")
MIN_RE = re.compile(r"^\s*min(?:utes)?\s*[=: ]\s*(\d{1,3})\s*$", re.I)


def _j(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def _dump(p: Path, o) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(o, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def issue_url_study(module_id: str, body: str = "") -> str:
    """터미널·텔레그램용 미리 채운 이슈 링크 (duel.py issue_url 과 같은 패턴)."""
    return f"https://github.com/{REPO}/issues/new?title={quote(f'study {module_id} done')}&body={quote(body)}"


# ───────────────────────── 파싱 ─────────────────────────
def parse_issue(title: str, body: str | None) -> dict | None:
    """`study <id> done` + 본문 `quiz <qid> <idx>`·`min <n>` → {id, quiz:[(qid, idx)], min}. 형식이 아니면 None."""
    m = TITLE_RE.match(title or "")
    quiz_only = bool(QUIZ_ONLY_RE.match(title or ""))
    if not m and not quiz_only:
        return None
    out: dict = {"id": None if quiz_only else m.group(1), "quiz_only": quiz_only, "quiz": [], "min": None, "bad": []}
    for line in (body or "").splitlines():
        line = line.strip()
        q = QUIZ_RE.match(line)
        if q:
            ans = q.group(2).strip()
            idx = re.fullmatch(r"([0-3])\s*(?:\)|번)?", ans)   # '3'·'3)'(텔레그램 보기 표기)·'3번'
            if idx:
                out["quiz"].append((q.group(1), int(idx.group(1))))
            elif len(ans) >= 2 and not ans.startswith("<") and not ans.isdigit() and (_TEXT_ANS.search(ans) or re.search(r"\d", ans)):
                out["quiz"].append((q.group(1), ans))       # 문장 답 → grade 에서 선택지로 해석
            else:
                out["bad"].append(line)   # '<0~3>' 그대로·범위 밖 번호('4'·'10') — 조용히 버리지 않는다(STANDARD §3)
            continue
        if line.lower().startswith("quiz"):
            out["bad"].append(line)   # 'quiz H2-b3 <0~3>' 처럼 번호를 안 바꾼 줄
            continue
        n = MIN_RE.match(line)
        if n:
            out["min"] = int(n.group(1))
    return out


# ───────────────────────── 채점 ─────────────────────────
def _squash(s: str) -> str:
    return re.sub(r"[\s\W_]+", "", str(s), flags=re.U).lower()


def resolve_choice(choices: list, text: str) -> int | None:
    """문장 답 → 선택지 번호. 앞부분 일치가 하나면 그것, 아니면 포함 일치가 하나면 그것, 그 외 None(모호·불일치)."""
    t = _squash(text)
    if len(t) < 2:
        return None
    for pred in (lambda c: c.startswith(t), lambda c: t in c):
        hit = [i for i, c in enumerate(choices) if pred(_squash(c))]
        if len(hit) == 1:
            return hit[0]
        if len(hit) > 1:
            return None
    return None


def grade(bank: dict, qid: str, answer: int | str) -> dict | None:
    item = next((q for q in (bank or {}).get("items", []) if q.get("id") == qid), None)
    if not item:
        return None
    if isinstance(answer, str):
        idx = resolve_choice(list(item.get("choices", [])), answer)
        if idx is None:
            return {"qid": qid, "unmatched": answer, "choices": list(item.get("choices", []))}
        answer = idx
    correct = int(item.get("answer", -1))
    return {"qid": qid, "module": item.get("module"), "answer": answer, "correct": correct, "ok": answer == correct,
            "q": item.get("q", ""), "choices": list(item.get("choices", [])), "why": item.get("why", ""),
            "desk": quiz_desk(item), "duel": item.get("duel"), "rule_ref": item.get("rule_ref")}


def quiz_desk(item: dict) -> str:
    """오답 피드백을 보낼 데스크: src 태그(kb:frm / consult:derivs)에서, 없으면 트랙 글자로."""
    for s in item.get("src", []) or []:
        m = re.match(r"(?:kb|consult):([a-z_]+)#", s)
        if m and m.group(1) != "pb_learner":
            return m.group(1)
    mod = str(item.get("module", ""))
    return TRACK_DESK.get(mod[:1], "behavior")


# ───────────────────────── 출석·SRS ─────────────────────────
def _weekday_gap_ok(a: date, b: date, rest: frozenset = frozenset()) -> bool:
    """a < b. 사이에 빠진 평일이 없으면 연속으로 본다 (주말은 건너뛰어도 됨 — 평일 기준 출석).
    rest = 쉼 신청일 — 빠져도 끊지 않는다(10/29 겸이 "쉼 신청한 날은 안 끊기로 해", +1 도 안 함)."""
    d = a + timedelta(days=1)
    while d < b:
        if d.weekday() < 5 and d not in rest:
            return False
        d += timedelta(days=1)
    return True


def streak(dates: list[str], rest_days: list[str] | None = None) -> int:
    ds = sorted({date.fromisoformat(x) for x in dates})
    rest = frozenset(date.fromisoformat(x) for x in rest_days or [])
    if not ds:
        return 0
    n = 1
    for a, b in zip(ds, ds[1:]):
        n = n + 1 if _weekday_gap_ok(a, b, rest) else 1
    return n


def derive_modules(done: list[dict], quiz: list[dict], intervals: list[int] | None = None) -> dict:
    """done·quiz 기록 → study_daily.pick_review 가 읽는 {id:{done, stage, next_due, scores}} (srs.json 규칙)."""
    iv = intervals or INTERVALS
    mods: dict[str, dict] = {}
    events: list[tuple[str, int, str, dict]] = []   # (날짜, 순서, 종류, 레코드)
    for d in done:
        events.append((d["date"], 0, "done", d))
    for q in quiz:
        events.append((q["date"], 1, "quiz", q))
    for day, _, kind, rec in sorted(events, key=lambda e: (e[0], e[1])):
        mid = rec["id"] if kind == "done" else rec.get("module")
        if not mid:
            continue
        m = mods.setdefault(mid, {"done": [], "stage": 0, "next_due": None, "scores": []})
        t = date.fromisoformat(day)
        if kind == "done":
            if day not in m["done"]:
                m["done"].append(day)
            if m["stage"] == 0 or m["next_due"] is None:
                m["next_due"] = (t + timedelta(days=iv[0])).isoformat()
            continue
        # 퀴즈: 복습 due 가 지났거나 당일이면 SRS 판정, 아니면 점수만 기록
        m["scores"].append([day, 1.0 if rec.get("ok") else 0.0])
        if not m["done"]:
            continue
        if rec.get("ok"):
            if m["next_due"] and t >= date.fromisoformat(m["next_due"]) and m["stage"] < 4:
                m["stage"] += 1
                m["next_due"] = None if m["stage"] >= 4 else (t + timedelta(days=iv[min(m["stage"], len(iv) - 1)])).isoformat()
        else:
            m["stage"] = 0
            m["next_due"] = (t + timedelta(days=iv[0])).isoformat()
    return mods


# ───────────────────────── 적용 ─────────────────────────
def _order(study: dict) -> list[str]:
    rm = (study or {}).get("roadmap", {})
    ftw = list(rm.get("first_two_weeks", []))
    return ftw + [i for i in rm.get("order", []) if i not in ftw]


def _titles(study: dict) -> dict[str, str]:
    return {m["id"]: m.get("title", "") for t in (study or {}).get("tracks", []) for m in t.get("modules", [])}


def unlock_next(progress: dict, study: dict, done_id: str) -> str | None:
    """'앞 모듈 done 이슈' 규칙: roadmap.order 에서 done_id 바로 다음의 잠긴 모듈 1개를 연다."""
    gate = (study or {}).get("gate") or {}
    locked = list(gate.get("locked", []))
    if not locked:
        return None
    order = list((study or {}).get("roadmap", {}).get("order", []))
    if done_id not in order:
        return None
    opened = set(gate.get("open", [])) | set(progress.get("unlocked", []))
    for nxt in order[order.index(done_id) + 1:]:
        if nxt in locked and nxt not in opened:
            progress.setdefault("unlocked", []).append(nxt)
            return nxt
    return None


def apply(progress: dict, parsed: dict, bank: dict, study: dict, today: date) -> tuple[dict, list[dict], list[str]]:
    """진행 파일에 반영. 반환 (progress, 채점 결과[], 답글 줄[])."""
    p = {**copy.deepcopy(INITIAL), **copy.deepcopy(progress or {})}
    mid, day = parsed["id"], today.isoformat()
    quiz_only = bool(parsed.get("quiz_only"))
    titles = _titles(study)
    lines: list[str] = []
    if not quiz_only and mid not in titles and titles:
        lines.append(f"⚠️ 모듈 '{mid}' 는 content/study.json 에 없습니다. 기록하지 않았습니다.")
        return p, [], lines
    if not quiz_only and not any(d["id"] == mid and d["date"] == day for d in p["done"]):
        p["done"].append({"id": mid, "date": day, "min": parsed.get("min")})
    graded: list[dict] = []
    for b in parsed.get("bad", []):
        lines.append(f"⚠️ 퀴즈 줄 형식 오류 '{b}' — `quiz <qid> <0~3 또는 선택지 앞 2자 이상>`.")
    answered = {(q["qid"], q["date"]) for q in p["quiz"]}
    for qid, ans in parsed["quiz"]:
        g = grade(bank, qid, ans)
        if g is None:
            lines.append(f"⚠️ 문항 '{qid}' 없음 — quiz_bank id 를 확인하세요.")
            continue
        if "unmatched" in g:
            opts = " / ".join(f"{i}) {c}" for i, c in enumerate(g["choices"]))
            lines.append(f"⚠️ {qid} 답 '{g['unmatched']}' 이 선택지 하나로 안 정해짐 — 앞부분을 더 쓰거나 번호로: {opts}")
            continue
        graded.append(g)
        ans = g["answer"]
        if (qid, day) in answered:
            continue
        p["quiz"].append({"qid": qid, "module": g["module"], "answer": ans, "correct": g["correct"], "ok": g["ok"], "date": day})
    p["streak"] = streak(activity_dates(p), p.get("rest_days"))
    p["last"] = max([day] + activity_dates(p))
    p["modules"] = derive_modules(p["done"], p["quiz"])
    opened = None if quiz_only else unlock_next(p, study, mid)
    # 답글
    t = titles.get(mid, "")
    if quiz_only:
        lines.insert(0, f"📝 퀴즈 {len(graded)}문항 기록 ({day}) — 모듈 완료는 `study <id> done`.")
    else:
        lines.insert(0, f"✅ {mid} {t.split(' — ')[0]} 완료 기록 ({day}{', ' + str(parsed['min']) + '분' if parsed.get('min') else ''}).")
    for g in graded:
        mark = "정답" if g["ok"] else "오답"
        lines.append(f"{'🟢' if g['ok'] else '🔴'} {g['qid']} {mark} — 내 답: {g['choices'][g['answer']]} / 정답: {g['choices'][g['correct']]}. {g['why']}")
        if g.get("duel"):
            d = g["duel"]
            pick = d.get("pick")
            lines.append(f"   ⚔️ {d.get('desk')} 데스크 답: {g['choices'][pick] if isinstance(pick, int) and 0 <= pick < len(g['choices']) else '—'}")
        if not g["ok"]:
            lines.append(f"   → docs/desk_kb/_quiz_feedback.md 큐에 추가({g['desk']} '흔한 오해' 후보)")
    m = p["modules"].get(mid, {}) if mid else {}
    if m.get("next_due"):
        lines.append(f"🔁 다음 복습: {m['next_due']} (단계 {m.get('stage', 0)}/4, 간격 1·3·7·21일)")
    lines.append(f"📅 출석 {p['streak']}일 연속")
    if opened:
        lines.append(f"🔓 다음 모듈 열림: {opened} {titles.get(opened, '').split(' — ')[0]} — 완료 시 `study {opened} done`")
    return p, graded, lines


# ───────────────────────── STUDY 탭 내보내기 (10/23~) ─────────────────────────
E_ID_RE = re.compile(r"^E(\d{4}-\d{2}-\d{2})-\d+$")
JSON_BLOCK_RE = re.compile(r"```json\s*(\{.*?\})\s*```", re.S)


def activity_dates(p: dict) -> list[str]:
    """출석 판정용 활동일(KST) — done 이슈·내보내기 done·인적성 응답일·영어 응답일."""
    ds = [d["date"] for d in p.get("done", []) if d.get("date")]
    ds += [d for d in p.get("days") or [] if d]
    ds += [r["date"] for r in (p.get("apt") or {}).values() if r.get("date")]
    ds += [r["date"] for r in (p.get("eng") or {}).values() if r.get("date")]
    return sorted(set(ds))


def load_export(src) -> dict:
    """dict · JSON 파일 경로 · 이슈 본문(```json 블록) 중 하나 → 내보내기 dict."""
    if isinstance(src, dict):
        return src
    s = str(src)
    if len(s) < 4096 and Path(s).exists():
        s = Path(s).read_text(encoding="utf-8")
    m = JSON_BLOCK_RE.search(s)
    return json.loads(m.group(1) if m else s)


def _apt_date(item_id: str, d: str | None, tz: str) -> tuple[str | None, str]:
    """인적성 응답일 → (KST 날짜, 'K'|'U'). v1(UTC) 날짜 d 의 한국 날짜는 d 또는 d+1.
    오늘의 인적성 E<출제일>-i 는 출제일(KST) 전에 풀 수 없으므로 출제일 = d+1 이면 KST d+1 로 확정한다."""
    if not d or tz == "K":
        return d, "K"
    m = E_ID_RE.match(item_id)
    nxt = (date.fromisoformat(d) + timedelta(days=1)).isoformat()
    if m and m.group(1) == nxt:
        return nxt, "K"
    return d, "U"


def _rank(r: dict) -> tuple:
    """첫 응답 판정 순서: 날짜가 이른 것 → 같은 날이면 오답 먼저(사전 커밋 보수 원칙) → 초 → tz. 전순서라 적용 순서와 무관."""
    sec = r.get("sec")
    return (r.get("date") or "9999-12-31", r.get("ok", 1), sec if isinstance(sec, (int, float)) else 1e9, r.get("tz") or "")


def _first(old: dict | None, new: dict) -> bool:
    """같은 항목이면 **첫 응답**을 남긴다(kb:eval#8). 같은 날짜 내보내기 여러 개도 순서와 무관하게 같은 결과(결정적)."""
    return old is None or _rank(new) < _rank(old)


# 영어 빈칸형 복습 정답 노출 버그(정답 단어 라벨이 풀기 전 보임) 수정 = 커밋 9842e63e, 2026-10-26 08:21 KST.
# 그 전에 푼 복습(r) 응답은 tainted — 원응답은 보존하고 정답률·n·일수 집계에서만 뺀다(req-dev-1a14cbe5 ①, 평가·교육 10/26).
# 응답 기록은 날짜만 있어 10/26 당일 08:21 전/후를 못 가름 → 10/25 까지만 tainted(10/26 응답은 수정 후로 간주, 한계).
ENG_TAINT_UNTIL = "2026-10-25"


def eng_tainted(key: str, rec: dict) -> bool:
    parts = key.split("|")
    return len(parts) > 1 and parts[1] == "r" and bool(rec.get("date")) and rec["date"] <= ENG_TAINT_UNTIL


APT_SERIES = {"E": "오늘의 인적성", "N": "유형 대응", "M": "암산", "G": "GSAT 수리", "R": "GSAT 추리", "L": "언어논리", "D": "자료해석"}


def _summary(p: dict, items: dict | None = None) -> dict:
    """공개용 집계 — 영역·유형별 비율·횟수만(문항 id 없음)."""
    rate = lambda ok, n: round(ok / n, 3) if n else None  # noqa: E731
    src = items if items is not None else p
    apt_d = src.get("apt") or {}
    apt = list(apt_d.values())
    eng = src.get("eng") or {}
    out = {"apt": {"n": len(apt), "ok": sum(r["ok"] for r in apt)},
           "apt_timed": {"n": sum(1 for r in apt if r.get("sec") is not None)}}
    out["apt"]["rate"] = rate(out["apt"]["ok"], out["apt"]["n"])
    by: dict = {}
    for qid, r in sorted(apt_d.items()):
        k = APT_SERIES.get(str(qid)[:1], "기타")
        b = by.setdefault(k, {"n": 0, "ok": 0})
        b["n"] += 1
        b["ok"] += r["ok"]
    for b in by.values():
        b["rate"] = rate(b["ok"], b["n"])
    out["apt_by"] = by
    for k, name in (("r", "eng_review"), ("q", "eng_quiz")):
        rs = [r for key, r in eng.items() if key.split("|")[1] == k and not r.get("tainted")]
        out[name] = {"n": len(rs), "ok": sum(r["ok"] for r in rs), "rate": rate(sum(r["ok"] for r in rs), len(rs))}
        nt = sum(1 for key, r in eng.items() if key.split("|")[1] == k and r.get("tainted"))
        if nt:
            out[name]["tainted"] = nt      # 집계 제외 건수(정답 노출 버그 수정 전 응답)
    mq = list((src.get("mq") or {}).values())
    if mq:   # 모듈 확인문제(v2 quiz) — 보기 고른 것(사전 커밋)만 점수, 자기 채점은 '확인'(kb:eval#8)
        c = [r for r in mq if not r.get("self")]
        out["mod_quiz"] = {"n": len(mq), "ok": sum(r["ok"] for r in mq), "rate": rate(sum(r["ok"] for r in mq), len(mq)),
                           "committed": {"n": len(c), "ok": sum(r["ok"] for r in c), "rate": rate(sum(r["ok"] for r in c), len(c))},
                           "self_n": len(mq) - len(c)}
    out["done_modules"] = len({d["id"] for d in p.get("done", [])})
    out["active_days"] = len(activity_dates(p))
    return out


def _item_dates(items: dict) -> list[str]:
    return sorted({r["date"] for k in ("apt", "eng", "mq") for r in (items.get(k) or {}).values() if r.get("date") and not r.get("tainted")})


def apply_export(progress: dict, export, study: dict | None = None, items: dict | None = None) -> dict:
    """공개 진행 파일만 돌려준다(문항 단위 기록 없음). 문항 단위 상태까지 필요하면 merge_export."""
    return merge_export(progress, export, study, items)[0]


def merge_export(progress: dict, export, study: dict | None = None, items: dict | None = None) -> tuple[dict, dict]:
    """STUDY 탭 '📤 학습 기록 보내기' JSON(v1 UTC · v2 KST) → (공개 진행 파일, 비공개 문항 상태).
    같은 문항은 첫 응답 고정(_first), 다시 넣어도·순서를 바꿔 넣어도 같은 결과(멱등·가환).
    items = pb-private study/items.json {"apt":{문항id:{ok,sec,date,tz}}, "eng":{"출제일|r/q|idx":{ok,date,tz}}}.
    None 이면 옛 공개 파일의 apt·eng 를 옮겨 온다(1회 이전).

    v1 {v:1, sent, done{id:날짜}, apt[[id, ok, 초|None, UTC 날짜]], eng[[출제일, r|q, idx, ok]], op[]}
    v2 {v:2, tz:'KST', ...} apt 5번째 칸 'K'|'U', eng 5번째 칸 = 푼 날(KST), op 4번째 칸 = 푼 날,
       quiz[[날짜, 모듈, 문항 idx, ok, 고른 보기|None, 자기채점]] → items mq{"모듈|idx"}, 공개는 summary.mod_quiz 비율만.
    공개 파일에는 문항·모듈 id 와 정답 여부·초·날짜만 남긴다(원자료·OPIc 자기평가 내용은 넣지 않음, 횟수만)."""
    x = load_export(export)
    v = int(x.get("v", 1))
    kst = v >= 2 or str(x.get("tz", "")).upper() == "KST"
    p = {**copy.deepcopy(INITIAL), **copy.deepcopy(progress or {})}
    p["note"] = INITIAL["note"]
    it = copy.deepcopy(items) if items is not None else {"apt": p.get("apt") or {}, "eng": p.get("eng") or {}}
    it.setdefault("apt", {})
    it.setdefault("eng", {})
    it.setdefault("mq", {})
    p.pop("apt", None)
    p.pop("eng", None)
    p.setdefault("exports", [])
    # 완료 모듈: 내보내기 done 은 체크박스라 모듈당 날짜 1개 → 같은 모듈의 export 행은 최신으로 교체
    titles = _titles(study or {})
    new_done = []
    for mid, d in sorted((x.get("done") or {}).items(), key=lambda kv: (kv[1] or "", kv[0])):
        if not d or (titles and mid not in titles):
            continue
        tz = "K" if kst else "U"
        if any(r["id"] == mid and r["date"] == d for r in p["done"]):
            continue
        old = [r for r in p["done"] if r["id"] == mid and r.get("src") == "export"]
        if old and old[0]["date"] > d:
            continue
        p["done"] = [r for r in p["done"] if not (r["id"] == mid and r.get("src") == "export")]
        p["done"].append({"id": mid, "date": d, "min": None, "src": "export", "tz": tz})
        new_done.append(mid)
    p["done"].sort(key=lambda r: (r["date"], r["id"]))
    for row in x.get("apt") or []:
        qid, ok, sec, d = (list(row) + [None] * 5)[:4]
        tz_in = (row[4] if len(row) > 4 and row[4] else ("K" if kst else "U"))
        day, tz = _apt_date(str(qid), d, str(tz_in).upper())
        rec = {"ok": 1 if ok else 0, "sec": sec if isinstance(sec, (int, float)) else None, "date": day, "tz": tz}
        c = row[5] if len(row) > 5 else None   # 6번째 칸: 고른 보기 번호(오답지 = 함정 유형 진단, kb:eval#9)
        if isinstance(c, int) and not isinstance(c, bool) and c >= 0:
            rec["c"] = c
        if _first(it["apt"].get(qid), rec):
            it["apt"][qid] = rec
    for row in x.get("eng") or []:
        cd, kind, idx, ok = (list(row) + [None] * 4)[:4]
        solved = row[4] if len(row) > 4 and row[4] else None
        rec = {"ok": 1 if ok else 0, "date": solved or cd, "tz": "K" if solved else "C"}   # C = 출제일(푼 날 미기록, v1)
        key = f"{cd}|{kind}|{idx}"
        if _first(it["eng"].get(key), rec):
            it["eng"][key] = rec
    for key, rec in it["eng"].items():     # 기존 기록까지 다시 판정(멱등) — 원응답(ok·date)은 그대로
        if eng_tainted(key, rec):
            rec["tainted"] = 1
    for row in x.get("quiz") or []:   # v2 모듈 확인문제 [날짜(KST), 모듈, 문항 idx, ok, 고른 보기|None, 자기채점 1|0]
        d, mid, qi, ok, _choice, self_ = (list(row) + [None] * 6)[:6]
        rec = {"ok": 1 if ok else 0, "self": 1 if self_ else 0, "date": d, "tz": "K"}
        key = f"{mid}|{qi}"
        if _first(it["mq"].get(key), rec):
            it["mq"][key] = rec
    p["op_count"] = max(int(p.get("op_count") or 0), len(x.get("op") or []))
    tag = {"v": v, "sent": x.get("sent"), "issue": x.get("issue")}
    if tag not in p["exports"]:
        p["exports"].append(tag)
    p["days"] = sorted(set(p.get("days") or []) | set(_item_dates(it)))
    p["streak"] = streak(activity_dates(p), p.get("rest_days"))
    p["last"] = (activity_dates(p) or [None])[-1]
    p["modules"] = derive_modules([{"id": r["id"], "date": r["date"]} for r in p["done"]], p["quiz"])
    for mid in new_done:
        unlock_next(p, study or {}, mid)
    p["summary"] = _summary(p, it)
    return p, it


def private_dir(root: Path = ROOT) -> Path | None:
    """문항 단위 상태 저장 위치 — 환경변수 STUDY_PRIVATE_DIR, 없으면 형제 체크아웃 pb-private/study (있을 때만)."""
    env = os.environ.get("STUDY_PRIVATE_DIR")
    if env:
        return Path(env)
    for base in (root.parent, Path.home(), Path("/home/user")):
        d = base / "pb-private" / "study"
        if d.is_dir():
            return d
    return None


def apply_export_file(export, root: Path = ROOT, priv: Path | None = None) -> dict:
    """reports/study_progress.json(공개, 집계만) + pb-private study/items.json(문항 단위) 에 반영. 반환 = summary.
    비공개 경로가 없으면 문항 상태를 잃으므로 조용히 넘기지 않고 멈춘다."""
    priv = priv or private_dir(root)
    if priv is None:
        raise SystemExit("pb-private study/ 경로 없음 — STUDY_PRIVATE_DIR 지정 필요(문항 단위 기록은 공개 저장소에 쓰지 않음)")
    pp = root / "reports" / "study_progress.json"
    ip = Path(priv) / "items.json"
    items = _j(ip, None)
    p, it = merge_export(_j(pp, copy.deepcopy(INITIAL)), export, _j(root / "content" / "study.json", {}), items)
    Path(priv).mkdir(parents=True, exist_ok=True)
    _dump(ip, {"note": "STUDY 문항 단위 상태(첫 응답 고정) — 공개 저장소에 올리지 않는다. screener/study_progress.merge_export", **it})
    _dump(pp, p)
    return p["summary"]


def append_wrong(graded: list[dict], today: date, root: Path = ROOT) -> int:
    """오답 → reports/study_wrong.json + docs/desk_kb/_quiz_feedback.md 큐 (데스크 KB '흔한 오해' 후보)."""
    wrong = [g for g in graded if not g["ok"]]
    if not wrong:
        return 0
    wp = root / "reports" / "study_wrong.json"
    w = _j(wp, {"note": "study 이슈 오답 누적 — 데스크 KB '흔한 오해' 재료. 금액·보유 없음", "items": []})
    day = today.isoformat()
    fb = root / "docs" / "desk_kb" / "_quiz_feedback.md"
    if not fb.exists():
        fb.parent.mkdir(parents=True, exist_ok=True)
        fb.write_text("# 퀴즈 오답 큐 → 데스크 KB '흔한 오해'\n\n"
                      "> `study <id> done` 이슈의 오답이 자동으로 쌓인다(screener/study_progress.py). 해당 데스크가 KB `흔한 오해` 절에 반영하면 줄 앞에 `[x]` 로 표시한다. 모듈·개념·오답만, 개인 데이터 없음.\n\n"
                      "| 날짜 | 모듈 | 데스크 | 문항 | 개념(문제) | 오답 → 정답 | 반영 |\n|---|---|---|---|---|---|---|\n", encoding="utf-8")
    rows = []
    for g in wrong:
        if any(x["qid"] == g["qid"] and x["date"] == day for x in w["items"]):
            continue
        w["items"].append({"qid": g["qid"], "module": g["module"], "desk": g["desk"], "answer": g["answer"], "correct": g["correct"],
                           "wrong_choice": g["choices"][g["answer"]], "correct_choice": g["choices"][g["correct"]], "date": day})
        esc = lambda s: str(s).replace("|", "／").replace("\n", " ")  # noqa: E731
        rows.append(f"| {day} | {g['module']} | {g['desk']} | {g['qid']} | {esc(g['q'])} | {esc(g['choices'][g['answer']])} → {esc(g['choices'][g['correct']])} | [ ] |\n")
    if rows:
        _dump(wp, w)
        with fb.open("a", encoding="utf-8") as f:
            f.writelines(rows)
    return len(rows)


def apply_issue(title: str, body: str | None, created_at: str | None = None, root: Path = ROOT) -> str:
    parsed = parse_issue(title, body)
    if not parsed:
        return "형식: 제목 `study <module_id> done`(또는 퀴즈만 `study quiz`), 본문(선택) `quiz <qid> <0~3 또는 선택지 앞 2자+>` 한 줄씩, `min <n>`."
    today = datetime.now(KST).date()
    if created_at:
        try:
            today = datetime.fromisoformat(created_at.replace("Z", "+00:00")).astimezone(KST).date()
        except ValueError:
            pass
    pp = root / "reports" / "study_progress.json"
    progress = _j(pp, copy.deepcopy(INITIAL))
    bank = _j(root / "content" / "study" / "quiz_bank.json", {})
    study = _j(root / "content" / "study.json", {})
    progress, graded, lines = apply(progress, parsed, bank, study, today)
    _dump(pp, progress)
    append_wrong(graded, today, root)
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--title")
    ap.add_argument("--body", default="")
    ap.add_argument("--created")
    ap.add_argument("--export", help="STUDY 탭 내보내기 JSON 경로(또는 이슈 본문 파일)")
    a = ap.parse_args()
    if a.export:
        print(json.dumps(apply_export_file(a.export), ensure_ascii=False))
    elif a.title:
        print(apply_issue(a.title, a.body.replace("\\n", "\n"), a.created))
    else:
        ap.error("--title 또는 --export")


if __name__ == "__main__":
    main()
