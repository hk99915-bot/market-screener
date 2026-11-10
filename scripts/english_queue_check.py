"""영어 사전 생성 큐(content/english_queue/<날짜>.json) 검사 — 커밋 전·CI(tests/test_english_queue.py)·보충 세션이 돌린다.

파일마다: 스키마(오늘의 영어 v2, reports/english 와 같음) · 날짜=파일명·평일 · 단어가 본문에 **굵게** · 4지 문항 정답 번호 ·
          독해 퀴즈 4문항 꼬리표 [어휘]·[어법]·[요지]·[내용 일치] 순서(평가 데스크가 '두 번째 = 어법' 전제로 채점) ·
          복습 문항의 from_date 가 그날보다 앞이고 그 날짜 단어 목록에 있는 말 · 인적성 3문항 규칙 v1(apt_daily_check, 정답 자리 = plan).
큐 전체: 4지 문항(복습+독해) 정답 위치 한 자리 40% 이하 · 어법 문항이 3일 연속 같은 정답 자리 금지 · 단어 중복 금지(큐 안).
경고(실패 아님): 정답이 유일하게 가장 긴 보기인 비율 50% 초과, 과거 게시분과 단어 중복.

  python3 scripts/english_queue_check.py            # 전체
  python3 scripts/english_queue_check.py --left     # 오늘 뒤 잔량만
종료 코드: 실패 1.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import apt_daily_check as apt  # noqa: E402

QUEUE = ROOT / "content" / "english_queue"
ENG = ROOT / "reports" / "english"
TAGS = ["[어휘]", "[어법]", "[요지]", "[내용 일치]"]
POS_MAX = 0.40
MIN = {"vocab": 5, "grammar": 2, "tense": 2, "review": 3, "quiz": 4, "talk": 2, "aptitude": 3}


def _mc(q: dict, n: int = 4) -> bool:
    ch = q.get("choices")
    return (isinstance(ch, list) and len(ch) == n and len({str(c).strip() for c in ch}) == n
            and isinstance(q.get("a"), int) and 0 <= q["a"] < n and bool(q.get("q")) and bool(q.get("exp_ko")))


def _vocab_by_date(extra: dict[str, dict]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for p in ENG.glob("2026-*.json"):
        try:
            out[p.stem] = {v.get("w") for v in json.loads(p.read_text(encoding="utf-8")).get("vocab", [])}
        except Exception:  # noqa: BLE001
            continue
    for k, d in extra.items():
        out[k] = {v.get("w") for v in d.get("vocab", [])}
    return out


def check_doc(d: dict, stem: str, vocab_by_date: dict[str, set[str]]) -> list[str]:
    e: list[str] = []
    w = lambda m: e.append(f"{stem}: {m}")  # noqa: E731
    try:
        day = date.fromisoformat(stem)
    except ValueError:
        return [f"{stem}: 파일명이 날짜가 아님"]
    if d.get("date") != stem:
        w(f"date {d.get('date')!r} ≠ 파일명")
    if day.weekday() >= 5:
        w("주말 날짜 — 게시는 평일만")
    for k in ("level", "title", "body", "ko"):
        if not isinstance(d.get(k), str) or not d[k].strip():
            w(f"{k} 비어 있음")
    if str(d.get("title", "")).startswith("SAMPLE"):
        w("SAMPLE 제목")
    for k, n in MIN.items():
        if not isinstance(d.get(k), list) or len(d[k]) < n:
            w(f"{k} {len(d.get(k) or [])}개 (최소 {n})")
    for v in d.get("vocab") or []:
        if not {"w", "pos", "ko", "en_easy", "ipa", "ex"} <= set(v):
            w(f"vocab 키 부족: {v.get('w')}")
        elif f"**{v['w']}**" not in d.get("body", ""):
            w(f"vocab '{v['w']}' 가 본문에 **굵게** 없음")
    for g in d.get("grammar") or []:
        if not {"point", "quote", "explain_ko", "examples"} <= set(g):
            w("grammar 키 부족")
    for t in d.get("tense") or []:
        if not {"sentence", "tense", "why_ko"} <= set(t):
            w("tense 키 부족")
    for i, q in enumerate(d.get("review") or []):
        if not _mc(q) or not {"w", "from_date"} <= set(q):
            w(f"review[{i}] 형식(4지·정답 번호·해설·w·from_date)")
            continue
        if not q["from_date"] < stem:
            w(f"review[{i}] from_date {q['from_date']} 가 그날보다 앞이 아님")
        elif q["w"] not in vocab_by_date.get(q["from_date"], set()):
            w(f"review[{i}] '{q['w']}' 가 {q['from_date']} 단어 목록에 없음")
    quiz = d.get("quiz") or []
    for i, q in enumerate(quiz):
        if not _mc(q):
            w(f"quiz[{i}] 형식(4지·정답 번호·해설)")
    if len(quiz) == 4 and [next((t for t in TAGS if str(q.get("q", "")).startswith(t)), None) for q in quiz] != TAGS:
        w("quiz 꼬리표 순서가 [어휘]·[어법]·[요지]·[내용 일치] 가 아님")
    talks = d.get("talk") or []
    if [t.get("kind") for t in talks] != ["시사", "일상"]:
        w("talk kind 는 ['시사', '일상']")
    for t in talks:
        if not t.get("topic") or len(t.get("dialogue") or []) < 4 or not all({"who", "en", "ko"} <= set(x) for x in t["dialogue"]):
            w("talk dialogue 4줄 이상·who/en/ko")
        if len(t.get("expressions") or []) < 3 or not all({"en", "ko"} <= set(x) for x in t["expressions"]):
            w("talk expressions 3개 이상")
        if not {"q_en", "hint_ko", "sample_answer"} <= set(t.get("your_turn") or {}):
            w("talk your_turn 키 부족")
    o = d.get("opic") or {}
    if len(o.get("combo") or []) != 3 or len(o.get("useful") or []) < 3 or not o.get("survey_topic") or not o.get("practice_ko"):
        w("opic: combo 3·useful 3 이상·survey_topic·practice_ko")
    for c in o.get("combo") or []:
        if not {"type", "q_en", "q_ko", "strategy_ko", "model_answer", "key_phrases"} <= set(c):
            w("opic combo 키 부족")
    want = apt.plan(day)
    for i, it in enumerate((d.get("aptitude") or [])[:3]):
        e += apt.check_item(it, f"{stem}: aptitude[{i}]", want[i])
        if not it.get("q") or not it.get("exp_ko") or not it.get("type"):
            w(f"aptitude[{i}] q·exp_ko·type")
    return e


def check_all(queue: Path = QUEUE) -> tuple[list[str], list[str]]:
    docs: dict[str, dict] = {}
    errs: list[str] = []
    warns: list[str] = []
    for p in sorted(queue.glob("*.json")):
        try:
            docs[p.stem] = json.loads(p.read_text(encoding="utf-8"))
        except Exception as ex:  # noqa: BLE001
            errs.append(f"{p.name}: JSON 오류 {ex}")
    vbd = _vocab_by_date(docs)
    for stem, d in docs.items():
        errs += check_doc(d, stem, vbd)
    pos: Counter = Counter()
    longest = n = 0
    gram: list[int] = []
    words: Counter = Counter()
    for stem in sorted(docs):
        d = docs[stem]
        for q in (d.get("review") or []) + (d.get("quiz") or []):
            if _mc(q):
                pos[q["a"]] += 1
                n += 1
                ln = [len(str(c)) for c in q["choices"]]
                longest += ln[q["a"]] == max(ln) and ln.count(max(ln)) == 1
        if len(d.get("quiz") or []) >= 2 and _mc(d["quiz"][1]):
            gram.append(d["quiz"][1]["a"])
        words.update(v.get("w") for v in d.get("vocab") or [])
    if n >= 20:
        for k, c in pos.items():
            if c / n > POS_MAX:
                errs.append(f"큐 전체: 4지 문항 정답 {k + 1}번 {c}/{n} > {POS_MAX:.0%}")
        if longest / n > 0.5:
            warns.append(f"정답이 유일하게 가장 긴 보기 {longest}/{n}")
    for i in range(len(gram) - 2):
        if gram[i] == gram[i + 1] == gram[i + 2]:
            errs.append(f"어법 문항 정답 자리 {gram[i] + 1}번이 3일 연속({sorted(docs)[i]}~)")
    errs += [f"큐 안 단어 중복: {w} ×{c}" for w, c in words.items() if c > 1]
    past = set().union(*[v for k, v in vbd.items() if k not in docs]) if vbd else set()
    dup = sorted(w for w in words if w in past)
    if dup:
        warns.append(f"과거 게시분과 단어 중복 {len(dup)}개: {', '.join(dup[:8])}")
    return errs, warns


def left(today: date, queue: Path = QUEUE) -> list[str]:
    return sorted(p.stem for p in queue.glob("*.json") if p.stem > today.isoformat())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--left", action="store_true")
    a = ap.parse_args(argv)
    today = datetime.now(timezone(timedelta(hours=9))).date()
    rest = left(today)
    if a.left:
        print(json.dumps({"today": today.isoformat(), "left": len(rest), "last": rest[-1] if rest else None}, ensure_ascii=False))
        return 0
    errs, warns = check_all()
    for x in warns:
        print("WARN", x)
    for x in errs:
        print("FAIL", x)
    print(f"{'FAIL' if errs else 'ok'}: 영어 큐 {len(list(QUEUE.glob('*.json')))}일 · 오늘 뒤 잔량 {len(rest)}일" + (f" (마지막 {rest[-1]})" if rest else ""))
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
