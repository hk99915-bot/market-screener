"""오늘의 공부 한 줄 (교육-후임) — 평일 07:10 KST, GitHub Actions `study_daily.yml`.

content/study.json(빌드본) + content/study/quiz_bank.json + content/study/srs.json + reports/study_progress.json(선택)
+ reports/english/latest.json(헤드라인) → reports/study_daily.json, 텔레그램 한 줄(환경변수 있을 때만).

선택 규칙(srs.json rules): 복습 1개(가장 오래 밀린 것) + 새 모듈 1개(2주 게이트 열린 모듈 + 'study <id> done' 으로 열린 모듈 중, 첫 2주 우선 목록 먼저, 미완료)
+ 퀴즈 1개(복습 모듈 우선, 아직 답하지 않은 문항, 날짜 해시로 결정적).
진행 파일 reports/study_progress.json 은 screener/study_progress.py(이슈 `study <id> done`)가 쓴다 — 여기서는 읽기만.
텔레그램 2블록(10/17 결재 #9 후속): ① 오늘 공부·복습·출석 ② 퀴즈 + 완료 이슈 링크. 하루 20분 상한(consult:pb_learner#L5). 네트워크 없이 돈다. 싸게.

  python -m screener.study_daily            # 오늘
  python -m screener.study_daily --date 2026-10-20 --no-telegram
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .study_progress import issue_url_study

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]
KST = ZoneInfo("Asia/Seoul")


def _j(p: Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def _modules(study: dict) -> dict[str, dict]:
    return {m["id"]: {**m, "_track": t["id"]} for t in study.get("tracks", []) for m in t.get("modules", [])}


def pick_review(progress: dict, today: date, mods: dict) -> dict | None:
    """due 가 지난 모듈 중 가장 오래 밀린 것 1개 (srs.rules.overdue_pick)."""
    best, best_late = None, -1
    for mid, p in (progress or {}).get("modules", {}).items():
        if mid not in mods or p.get("stage", 0) >= 4 or not p.get("next_due"):
            continue
        try:
            due = date.fromisoformat(p["next_due"])
        except ValueError:
            continue
        late = (today - due).days
        if late >= 0 and late > best_late:
            best, best_late = mid, late
    return {"id": best, "overdue_days": best_late, "stage": progress["modules"][best].get("stage", 0)} if best else None


def _done_ids(progress: dict) -> set[str]:
    p = progress or {}
    return {mid for mid, m in p.get("modules", {}).items() if m.get("done")} | {d["id"] for d in p.get("done", []) if d.get("id")}


def pick_new(study: dict, progress: dict, mods: dict) -> str | None:
    """열린 모듈(gate.open + progress.unlocked) 중 미완료 첫 모듈. 첫 2주 우선 목록 → 로드맵 순서 (srs.rules.new_pick).
    게이트가 없으면(구형 빌드) 선행 충족 규칙만."""
    done = _done_ids(progress)
    rm = study.get("roadmap", {})
    gate = study.get("gate") or {}
    opened = set(gate.get("open", [])) | set((progress or {}).get("unlocked", [])) if gate else None
    cands = [i for i in rm.get("first_two_weeks", []) if i in mods] + [i for i in rm.get("order", []) if i in mods]
    seen: set[str] = set()
    for mid in cands:
        if mid in seen or mid in done:
            continue
        seen.add(mid)
        if opened is not None:
            if mid in opened:
                return mid
            continue
        if all(p in done for p in mods[mid].get("prereq", []) if p in mods) or mid in rm.get("first_two_weeks", []):
            return mid
    return None


def pick_quiz(bank: dict, module_id: str | None, day: date, progress: dict | None = None) -> dict | None:
    """모듈의 문항 1개 — 아직 답하지 않은 것 우선(progress.quiz), 모두 답했으면 전체에서."""
    pool = [q for q in (bank or {}).get("items", []) if q.get("module") == module_id]
    answered = {q.get("qid") for q in (progress or {}).get("quiz", [])}
    items = [q for q in pool if q.get("id") not in answered] or pool
    if not items:
        return None
    # situation 우선(srs.rules.quiz_pick, consult:pb_learner#L8 상황 판단 70%): 미답 situation 이 남아 있으면 그 안에서만 고른다.
    # (정렬만 하고 해시로 뽑으면 우선순위가 사라진다 — 교육 라운드1 수정)
    items = [q for q in items if q.get("kind") == "situation"] or items
    items.sort(key=lambda q: q.get("id", ""))
    h = int(hashlib.sha1(f"{day.isoformat()}:{module_id}".encode()).hexdigest(), 16)
    return items[h % len(items)]


def build(today: date, study: dict, bank: dict, srs: dict, progress: dict | None, english: dict | None) -> dict:
    mods = _modules(study)
    review = pick_review(progress or {}, today, mods)
    new_id = pick_new(study, progress or {}, mods)
    quiz_mod = (review or {}).get("id") or new_id
    quiz = pick_quiz(bank, quiz_mod, today, progress)
    new = mods.get(new_id) if new_id else None
    gate = study.get("gate") or {}
    next_locked = None
    if gate and not new_id:
        done = _done_ids(progress or {})
        next_locked = next((i for i in study.get("roadmap", {}).get("order", []) if i not in done), None)
    issue_mod = new_id or (review or {}).get("id")
    cap = int((srs or {}).get("rules", {}).get("daily_cap", {}).get("est_min_total", 20))
    total_min = int(new.get("est_min") or round(float(new.get("hours", 0)) * 60)) if new else 0
    # 하루 1모듈 20분 상한(consult:pb_learner#L5): 구형(시간 단위) 모듈은 '오늘 분량'만 보여준다 — 총량(360분)을 보여주면 역효과.
    est = min(total_min, cap) if total_min else 0
    body = (f"quiz {quiz['id']} <0~3>\n" if quiz else "") + f"min {est or 15}"
    out = {
        "date": today.isoformat(),
        "weekday": today.weekday(),
        "review": ({"id": review["id"], "title": mods[review["id"]]["title"], "stage": review["stage"], "overdue_days": review["overdue_days"],
                    "interval_days": (srs or {}).get("intervals", [1, 3, 7, 21])[min(review["stage"], 3)]} if review else None),
        "new": ({"id": new_id, "title": new["title"], "track": new["_track"], "est_min": est, "total_min": total_min, "multi_day": total_min > cap,
                 "level": new.get("level"),
                 "summary": new.get("summary"), "terminal_lookup": new.get("terminal_lookup"), "rule_link": new.get("rule_link"),
                 "prereq": new.get("prereq", []), "first_two_weeks": new_id in study.get("roadmap", {}).get("first_two_weeks", [])} if new else None),
        "quiz": ({"id": quiz["id"], "module": quiz["module"], "kind": quiz.get("kind"), "q": quiz["q"], "choices": quiz["choices"],
                  "duel_desk": (quiz.get("duel") or {}).get("desk"), "rule_ref": quiz.get("rule_ref")} if quiz else None),
        "english": ({"date": english.get("date"), "title": english.get("title"), "level": english.get("level")} if english else None),
        "daily_cap_min": cap,
        "progress_source": "reports/study_progress.json" if progress else "없음(이슈 'study <id> done' 으로 기록 — screener/study_progress.py)",
        "srs": {"intervals": (srs or {}).get("intervals", [1, 3, 7, 21])},
        "streak": int((progress or {}).get("streak") or 0),
        "issue_url": issue_url_study(issue_mod, body) if issue_mod else None,
        "issue_title": f"study {issue_mod} done" if issue_mod else None,
        "gate": ({"open_until": gate.get("open_until"), "open": len(gate.get("open", [])), "unlocked": list((progress or {}).get("unlocked", [])),
                  "next_locked": next_locked, "unlock_rule": gate.get("unlock_rule")} if gate else None),
    }
    return out


def telegram_text(o: dict) -> str:
    """2블록(결재 #9 후속, 10/17: 4→2): ① 오늘 공부·복습·퀴즈·출석 한 줄 ② 퀴즈 문항 + 완료 이슈 링크 한 줄."""
    n, r, q, g = o.get("new"), o.get("review"), o.get("quiz"), o.get("gate") or {}
    bits = ["📚 오늘 공부:"]
    if n:
        bits.append(f"{n['id']} {n['title'].split(' — ')[0]} ({n['est_min']}분)")
    elif g.get("next_locked"):
        bits.append(f"새 모듈 잠김({g['next_locked']}) — {g.get('unlock_rule') or '앞 모듈 done 이슈'}")
    else:
        bits.append("새 모듈 없음(로드맵 완주)")
    bits.append(f"· 복습 {r['id']}" + (f"(D+{r['overdue_days']})" if r.get("overdue_days") else "") if r else "· 복습 없음")
    bits.append("· 퀴즈 1" if q else "")
    bits.append(f"· 📅 출석 {o.get('streak', 0)}일 연속")
    lines = [" ".join(b for b in bits if b)]
    second = []
    if q:
        ch = " / ".join(f"{i}){c}" for i, c in enumerate(q["choices"]))
        second.append(f"❓ [{q['module']}] {q['q']} — {ch}")
    if o.get("issue_url"):
        second.append(f"📝 완료·답 기록(이슈 '{o['issue_title']}', 본문 quiz <qid> <번호>): {o['issue_url']}")
    if second:
        lines.append(" · ".join(second))
    return "\n".join(lines[:2])


def run(today: date | None = None, send: bool = True, root: Path = ROOT) -> dict:
    today = today or datetime.now(KST).date()
    study = _j(root / "content" / "study.json", {}) or {}
    bank = _j(root / "content" / "study" / "quiz_bank.json", {}) or {}
    srs = _j(root / "content" / "study" / "srs.json", {}) or {}
    progress = _j(root / "reports" / "study_progress.json", None)
    english = _j(root / "reports" / "english" / "latest.json", None)
    out = build(today, study, bank, srs, progress, english)
    (root / "reports").mkdir(exist_ok=True)
    (root / "reports" / "study_daily.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    text = telegram_text(out)
    log.info("study_daily %s\n%s", today, text)
    if send:
        try:
            from .report import send_telegram
            send_telegram(text)
        except Exception as e:  # noqa: BLE001  — 환경변수 없으면 조용히 건너뜀 (싸게)
            log.warning("텔레그램 생략: %s", e)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--no-telegram", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    d = date.fromisoformat(a.date) if a.date else None
    o = run(d, send=not a.no_telegram)
    print(telegram_text(o))


if __name__ == "__main__":
    main()
