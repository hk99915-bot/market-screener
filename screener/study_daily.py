"""오늘의 공부 한 줄 (교육-후임) — 평일 07:10 KST, GitHub Actions `study_daily.yml`.

content/study.json(빌드본) + content/study/quiz_bank.json + content/study/srs.json + reports/study_progress.json(선택)
+ reports/english/latest.json(헤드라인) → reports/study_daily.json, 텔레그램 한 줄(환경변수 있을 때만).

선택 규칙(srs.json rules): 복습 1개(가장 오래 밀린 것) + 새 모듈 1개(로드맵 순서·선행 충족, 첫 2주 우선 목록 먼저) + 퀴즈 1개(복습 모듈 우선, 날짜 해시로 결정적).
하루 20분 상한 — 모듈 하나만 노출한다(consult:pb_learner#L5). 네트워크 없이 돈다. 싸게.

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


def pick_new(study: dict, progress: dict, mods: dict) -> str | None:
    """로드맵 순서에서 미완료·선행 충족 첫 모듈. 첫 2주 우선 목록을 먼저 소진 (srs.rules.new_pick)."""
    done = {mid for mid, p in (progress or {}).get("modules", {}).items() if p.get("done")}
    rm = study.get("roadmap", {})
    cands = [i for i in rm.get("first_two_weeks", []) if i in mods] + [i for i in rm.get("order", []) if i in mods]
    seen: set[str] = set()
    for mid in cands:
        if mid in seen or mid in done:
            continue
        seen.add(mid)
        if all(p in done for p in mods[mid].get("prereq", []) if p in mods) or mid in rm.get("first_two_weeks", []):
            return mid
    return None


def pick_quiz(bank: dict, module_id: str | None, day: date) -> dict | None:
    items = [q for q in (bank or {}).get("items", []) if q.get("module") == module_id]
    if not items:
        return None
    items.sort(key=lambda q: (q.get("kind") != "situation", q.get("id", "")))  # situation 우선
    h = int(hashlib.sha1(f"{day.isoformat()}:{module_id}".encode()).hexdigest(), 16)
    return items[h % len(items)]


def build(today: date, study: dict, bank: dict, srs: dict, progress: dict | None, english: dict | None) -> dict:
    mods = _modules(study)
    review = pick_review(progress or {}, today, mods)
    new_id = pick_new(study, progress or {}, mods)
    quiz_mod = (review or {}).get("id") or new_id
    quiz = pick_quiz(bank, quiz_mod, today)
    new = mods.get(new_id) if new_id else None
    est = int(new.get("est_min") or round(float(new.get("hours", 0)) * 60)) if new else 0
    out = {
        "date": today.isoformat(),
        "weekday": today.weekday(),
        "review": ({"id": review["id"], "title": mods[review["id"]]["title"], "stage": review["stage"], "overdue_days": review["overdue_days"],
                    "interval_days": (srs or {}).get("intervals", [1, 3, 7, 21])[min(review["stage"], 3)]} if review else None),
        "new": ({"id": new_id, "title": new["title"], "track": new["_track"], "est_min": est, "level": new.get("level"),
                 "summary": new.get("summary"), "terminal_lookup": new.get("terminal_lookup"), "rule_link": new.get("rule_link"),
                 "prereq": new.get("prereq", []), "first_two_weeks": new_id in study.get("roadmap", {}).get("first_two_weeks", [])} if new else None),
        "quiz": ({"id": quiz["id"], "module": quiz["module"], "kind": quiz.get("kind"), "q": quiz["q"], "choices": quiz["choices"],
                  "duel_desk": (quiz.get("duel") or {}).get("desk"), "rule_ref": quiz.get("rule_ref")} if quiz else None),
        "english": ({"date": english.get("date"), "title": english.get("title"), "level": english.get("level")} if english else None),
        "daily_cap_min": (srs or {}).get("rules", {}).get("daily_cap", {}).get("est_min_total", 20),
        "progress_source": "reports/study_progress.json" if progress else "없음(이슈 'study <id> done' 제안 — srs.json progress_store)",
        "srs": {"intervals": (srs or {}).get("intervals", [1, 3, 7, 21])},
    }
    return out


def telegram_text(o: dict) -> str:
    n, r, q = o.get("new"), o.get("review"), o.get("quiz")
    bits = ["📚 오늘 공부:"]
    bits.append(f"{n['id']} {n['title'].split(' — ')[0]} ({n['est_min']}분)" if n else "새 모듈 없음(로드맵 완주)")
    bits.append(f"· 복습 {r['id']}" if r else "· 복습 없음")
    bits.append("· 퀴즈 1" if q else "")
    line = " ".join(b for b in bits if b)
    extra = []
    if n and n.get("terminal_lookup"):
        extra.append(f"🔎 {n['terminal_lookup']}")
    if q:
        extra.append(f"❓ [{q['module']}] {q['q']}")
    e = o.get("english")
    if e and e.get("title"):
        extra.append(f"🗞 {e['title']}")
    return "\n".join([line, *extra])


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
