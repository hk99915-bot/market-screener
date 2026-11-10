"""오늘의 영어·OPIc·오늘의 인적성 — 사전 생성 큐 게시 (교육 데스크, 2026-11-10).

배경: 매일 07:18 Claude 예약 세션이 그날 치를 새로 쓰던 것을, 여러 날 치를 미리 써 두고 GitHub Actions 가 날짜에 맞춰
게시하는 구조로 옮긴다(Pro 전환 뒤 매일 토큰 0). 이 모듈은 네트워크·LLM 없이 파일만 옮긴다.

  큐:   content/english_queue/<YYYY-MM-DD>.json   (reports/english/<날짜>.json 과 같은 스키마 — 검사 scripts/english_queue_check.py)
  게시: reports/english/<날짜>.json + latest.json + index.json   (study_daily.yml 이 평일 07:10 KST 에 '오늘의 공부' 앞 단계로 실행)

규칙
- 그날 reports/english/<날짜>.json 이 이미 있으면(세션이 직접 썼거나 재실행) 덮어쓰지 않는다.
- 큐에 그날 파일이 없으면 이전 latest 를 그대로 두되 조용히 넘어가지 않는다: freshness stale 기록 + 텔레그램 + Actions 경고.
- 큐 잔량(오늘 뒤 평일 파일 수)이 WARN_LEFT 일 이하이면 텔레그램·로그 경고(바닥나는 날짜 포함).
- 게시한 큐 파일은 지우지 않는다(잔량은 '오늘 뒤 날짜'만 센다).

  python -m screener.english_queue                      # 오늘(KST) 게시
  python -m screener.english_queue --date 2026-11-11 --no-telegram
  python -m screener.english_queue --status              # 잔량만 출력(쓰기 없음)
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]
KST = ZoneInfo("Asia/Seoul")
WARN_LEFT = 3
REQUIRED = ("date", "level", "title", "body", "ko", "vocab", "grammar", "tense", "review", "quiz", "talk", "opic", "aptitude")


def queue_dir(root: Path = ROOT) -> Path:
    return root / "content" / "english_queue"


def queue_dates(root: Path = ROOT) -> list[date]:
    out = []
    for p in queue_dir(root).glob("*.json"):
        try:
            out.append(date.fromisoformat(p.stem))
        except ValueError:
            continue
    return sorted(out)


def remaining(today: date, root: Path = ROOT) -> list[date]:
    """오늘 뒤(오늘 제외) 큐에 남은 날짜."""
    return [d for d in queue_dates(root) if d > today]


def basic_errors(doc: dict, day: date) -> list[str]:
    """게시 직전 최소 검사(전체 검사는 scripts/english_queue_check.py — 커밋 전·CI)."""
    errs = [f"키 없음: {k}" for k in REQUIRED if not doc.get(k)]
    if doc.get("date") != day.isoformat():
        errs.append(f"date {doc.get('date')!r} ≠ 파일 날짜 {day}")
    return errs


def _dump(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def publish(today: date, root: Path = ROOT) -> dict:
    """그날 큐 파일을 reports/english 로 게시. 반환 status: published | already | missing | invalid."""
    eng = root / "reports" / "english"
    dst = eng / f"{today.isoformat()}.json"
    src = queue_dir(root) / f"{today.isoformat()}.json"
    left = remaining(today, root)
    out = {"date": today.isoformat(), "left": len(left), "last": left[-1].isoformat() if left else None, "errors": []}
    if dst.exists():
        out["status"] = "already"
        return out
    if not src.exists():
        out["status"] = "missing"
        return out
    try:
        doc = json.loads(src.read_text(encoding="utf-8"))
        errs = basic_errors(doc, today)
    except Exception as e:  # noqa: BLE001
        doc, errs = None, [f"JSON 읽기 실패: {e}"]
    if errs:
        out["status"], out["errors"] = "invalid", errs
        return out
    _dump(dst, doc)
    _dump(eng / "latest.json", doc)
    try:
        idx = json.loads((eng / "index.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        idx = {}
    dates = sorted({*(idx.get("dates") or []), today.isoformat()}, reverse=True)
    _dump(eng / "index.json", {**idx, "dates": dates})
    out["status"], out["title"] = "published", doc.get("title")
    return out


def warn_text(o: dict) -> str | None:
    """경고가 필요할 때만 한 줄. 게시 실패(missing·invalid)가 잔량 경고보다 먼저."""
    if o["status"] in ("missing", "invalid"):
        why = "큐에 오늘 파일 없음" if o["status"] == "missing" else "큐 파일 검사 실패: " + "; ".join(o["errors"][:3])
        return (f"⚠️ 오늘의 영어 {o['date']} 게시 못 함 — {why}. 화면은 이전 날짜 그대로. "
                f"보충: content/english_queue/ 에 날짜 파일 추가(docs/study_spec.md §영어 큐)")
    if o["left"] <= WARN_LEFT:
        tail = f"마지막 {o['last']}" if o["last"] else "오늘이 마지막"
        return (f"⚠️ 오늘의 영어 큐 잔량 {o['left']}일({tail}) — {WARN_LEFT}일 이하. "
                f"보충: content/english_queue/ 에 다음 평일 파일 추가(docs/study_spec.md §영어 큐)")
    return None


def run(today: date | None = None, send: bool = True, root: Path = ROOT) -> dict:
    today = today or datetime.now(KST).date()
    o = publish(today, root)
    log.info("english_queue %s: %s · 잔량 %d일%s", today, o["status"], o["left"], f"(마지막 {o['last']})" if o["last"] else "")
    if o["status"] in ("missing", "invalid") and root == ROOT:   # 임시 root(테스트)는 실제 freshness.json 을 건드리지 않는다
        try:   # 조용한 대체 금지(LOOP 금지 항목): 이전 latest 를 쓰게 되므로 stale 로 남긴다
            from .guard import record_stale
            latest = json.loads((root / "reports" / "english" / "latest.json").read_text(encoding="utf-8")).get("date")
            record_stale("reports/english/latest.json", f"english_queue {o['status']}", today.isoformat(), latest)
        except Exception as e:  # noqa: BLE001
            log.warning("stale 기록 실패: %s", e)
    w = warn_text(o)
    if w:
        print(f"::warning::{w}")
        if send:
            try:
                from .report import send_telegram
                send_telegram(w)
            except Exception as e:  # noqa: BLE001
                log.warning("텔레그램 생략: %s", e)
    o["warn"] = w
    return o


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--no-telegram", action="store_true")
    ap.add_argument("--status", action="store_true", help="잔량만 출력(쓰기 없음)")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    d = date.fromisoformat(a.date) if a.date else datetime.now(KST).date()
    if a.status:
        left = remaining(d)
        print(json.dumps({"date": d.isoformat(), "left": len(left), "last": left[-1].isoformat() if left else None,
                          "dates": [x.isoformat() for x in left]}, ensure_ascii=False))
        return
    o = run(d, send=not a.no_telegram)
    print(json.dumps({k: o[k] for k in ("date", "status", "left", "last", "errors")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
