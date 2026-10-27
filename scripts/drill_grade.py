#!/usr/bin/env python3
"""데스크 10년차 드릴 채점 (교육 데스크, 10/24 겸이 결재 G1 — appr-edu-g1-g4).

왜: 27개 KB 의 드릴 답이 문제 바로 뒤(`**답:**`)에 있어 인출이 아니라 복사였다(edu_self W2, 응답 0).
어떻게:
  - 문제는 각 KB `## 10년차 기준` 의 `- 드릴 [<id>]: …` 줄, 답·채점 키는 `content/drills/<desk>.json` (KB 엔 답 없음).
  - 데스크는 라운드 파일에 `드릴: <id> <내 답>` 한 줄을 **먼저** 쓰고, 그 뒤에 키 파일을 열어 본다.
  - `scripts/round_collect.py` 가 라운드 수집 때 이 모듈로 채점해 `_scoreboard.md` 의 `## 드릴 표` 에 싣는다.
채점: 키 = 숫자 {"n": 값, "tol": 허용오차} 또는 용어 {"t": [동의어…]}. 점수 = 맞힌 키 / 전체 키, `pass`(기본 0.6) 이상이면 통과.
     키에 "req": true 가 있으면 필수 — 점수가 넘어도 그 키를 놓치면 불통과(10/27 평가 키 역검사, req-edu-ff390d0d).
     숫자는 부호 무시 일치도 인정(−1.4% 를 '1.4% 하락'으로 써도), 허용오차 기본 max(1%, 0.05). 용어는 부분 문자열(영문 1~2자는 단어 경계, 're:' 접두는 정규식).
     필수 용어 키는 부정 문맥이면 불적중('능동이 아니라 수동'·'1건도 없다' — 10/28 감사 재검수, `_negated`). 키 옵션: "negative": true(부정 개념 키) · "negcheck": false(끔).
     기계 채점은 '핵심 숫자·용어를 꺼냈나'만 본다 — 판단의 질은 감사 데스크 채점(LOOP 7항)이 본다.

  python3 scripts/drill_grade.py --check                       # KB↔키 파일 정합(답이 KB 에 남았나·id 누락)
  python3 scripts/drill_grade.py --grade frm-d1 --text "황 …"   # 한 건 채점
  python3 scripts/drill_grade.py --round 2026-10-24 [--apply]  # 라운드 파일의 드릴: 줄 채점 → 드릴 표 (round_collect 가 같은 함수 사용)

온보딩 확인 퀴즈(10/24 교육 — 프론트·컴플라이언스·포지션리스크 과정, 같은 G1 규칙): 문제는 `docs/desk_kb/onboarding/<desk>[_quiz].md` 의 `- 퀴즈 [<desk>-qN]: …` 줄,
키는 `content/onboarding/<desk>.json`(문서엔 답 없음, 과정 = 파일 하나, 문서 이름 앞부분 = 퀴즈 id 의 데스크). 응시자는 답안 파일에 `퀴즈: <id> <내 답>` 줄을 먼저 쓰고, 채점은 검수 데스크(평가)가 한다.
  python3 scripts/drill_grade.py --sheet docs/desk_kb/rounds/2026-10-27/front.md   # 답안의 퀴즈:·드릴: 줄 채점 (키 = 드릴 + 온보딩)
  python3 scripts/drill_grade.py --grade front-q3 --text "…"                        # 온보딩 문항도 같은 --grade
  --check 는 온보딩 문서↔키 정합(답이 문서에 남았나·id 누락·키 형식)도 본다.
재시험(10/28 평가 '답안 커밋 먼저 → 키 공개'): 문제지에 KEY_PENDING 줄을 두면 키 없는 id 를 허용하고, 평가는 키 공개 전
  python3 scripts/drill_grade.py --sheet <답안> --keys <비공개 키.json> 로 채점한다. 키 공개 커밋 = 키를 content/onboarding 에 합치고 그 줄 삭제.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEYS_DIR = ROOT / "content" / "drills"
KB_DIR = ROOT / "docs" / "desk_kb"
ROUNDS_DIR = KB_DIR / "rounds"
SCOREBOARD = KB_DIR / "_scoreboard.md"
ONB_KEYS_DIR = ROOT / "content" / "onboarding"
ONB_DOC_DIR = KB_DIR / "onboarding"
PASS = 0.6

DRILL_LINE = re.compile(r"^\s*(?:[-*]\s*)?(?:\*\*)?드릴(?:\*\*)?\s*[:：]\s*([a-z_]+-d\d+)\s+(.+?)\s*$")
KB_DRILL = re.compile(r"^- 드릴(?:\s*\[([a-z_]+-d\d+)\])?\s*[:(]")
QUIZ_LINE = re.compile(r"^\s*(?:[-*]\s*)?(?:\*\*)?퀴즈(?:\*\*)?\s*[:：]\s*([a-z_]+-q\d+)\s+(.+?)\s*$")
DOC_QUIZ = re.compile(r"^- 퀴즈(?:\s*\[([a-z_]+-q\d+)\])?\s*[:(]")
KEY_PENDING = "<!-- 키 비공개: 답안 커밋 뒤 공개 -->"   # 문제지에 이 줄이 있으면 키 없는 퀴즈 id 허용(키 공개 커밋에서 줄 삭제)
DRILL_HEAD = "## 드릴 표"
DRILL_COLS = "| 라운드 | 데스크 | 드릴 | 점수 | 판정 | 놓친 키 |"
DRILL_SEP = "|---|---|---|---|---|---|"
_NUM = re.compile(r"[-+]?\d+(?:,\d{3})*(?:\.\d+)?(?:e[-+]?\d+)?", re.I)


def load_keys(keys_dir: Path = KEYS_DIR) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for p in sorted(keys_dir.glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        for it in d.get("items", []):
            out[it["id"]] = {**it, "desk": d.get("desk", p.stem)}
    return out


def load_key_file(path: Path) -> dict[str, dict]:
    """키 파일 하나(공개 저장소 밖 비공개 재시험 키 등) — load_keys 와 같은 형식."""
    d = json.loads(path.read_text(encoding="utf-8"))
    return {it["id"]: {**it, "desk": d.get("desk", path.stem)} for it in d.get("items", [])}


def load_onboarding(keys_dir: Path = ONB_KEYS_DIR) -> dict[str, dict]:
    """온보딩 확인 퀴즈 키 (content/onboarding/<desk>.json) — 드릴과 같은 키 형식, id 는 <desk>-qN."""
    return load_keys(keys_dir) if keys_dir.exists() else {}


def check_onboarding(doc_dir: Path = ONB_DOC_DIR, keys_dir: Path = ONB_KEYS_DIR) -> list[str]:
    """온보딩 문서에 답이 없고, 문서의 퀴즈 id ↔ 키가 1:1 이고, 키 형식이 맞고, 모범답이 자기 키로 통과하는지."""
    errs = []
    keys = load_onboarding(keys_dir)
    for qid, it in keys.items():
        if not it.get("q") or not it.get("answer") or not it.get("keys"):
            errs.append(f"{qid}: q·answer·keys 필요")
            continue
        for k in it["keys"]:
            if not (isinstance(k.get("n"), (int, float)) or (isinstance(k.get("t"), list) and k["t"])):
                errs.append(f"{qid}: 키 형식 오류 {k}")
            if "req" in k and not isinstance(k["req"], bool):
                errs.append(f"{qid}: req 는 true/false {k}")
        if not re.fullmatch(rf"{re.escape(it['desk'])}-q\d+", qid):
            errs.append(f"{qid}: id 형식 ≠ '{it['desk']}-qN'")
        if grade(it, it["answer"])["score"] < 1.0:
            errs.append(f"{qid}: 모범답이 자기 키를 다 못 맞힘 {grade(it, it['answer'])['miss']}")
    seen = set()
    for p in sorted(doc_dir.glob("*.md")) if doc_dir.exists() else []:
        body = p.read_text(encoding="utf-8")
        pending = KEY_PENDING in body   # 재시험 문제지: 키는 답안 커밋 뒤 공개(G1 순서 증명) — 그 전엔 '키 없음'을 오류로 안 본다
        for ln in body.splitlines():
            m = DOC_QUIZ.match(ln)
            if not m:
                continue
            if "**답:**" in ln or "정답:" in ln:
                errs.append(f"{p.name}: 퀴즈 답이 문서에 남음 — content/onboarding/{p.stem}.json 로 (G1)")
            if not m.group(1):
                errs.append(f"{p.name}: 퀴즈 id 없음 — '- 퀴즈 [{p.stem}-qN]: …'")
            elif m.group(1).rsplit("-q", 1)[0] != p.stem.split("_")[0]:
                errs.append(f"{p.name}: 퀴즈 {m.group(1)} 가 다른 과정 문서에 있음 — '{p.stem.split('_')[0]}-qN' 만 (과정별 문서·키 1:1)")
            elif m.group(1) not in keys:
                if pending:
                    continue
                errs.append(f"{p.name}: 퀴즈 {m.group(1)} 키 없음 (content/onboarding/{m.group(1).rsplit('-q', 1)[0]}.json)")
            else:
                seen.add(m.group(1))
    for qid in sorted(set(keys) - seen):
        errs.append(f"{qid}: 키는 있는데 온보딩 문서에 문제 줄이 없음")
    return errs


def grade_sheet(text: str, keys: dict[str, dict]) -> list[dict]:
    """답안 텍스트의 `퀴즈: <id> <답>`·`드릴: <id> <답>` 줄 채점. 모르는 id 는 score None."""
    out = []
    for ln in text.splitlines():
        m = QUIZ_LINE.match(ln) or DRILL_LINE.match(ln)
        if not m:
            continue
        qid, ans = m.group(1), m.group(2)
        out.append(grade(keys[qid], ans) if qid in keys else {"id": qid, "score": None, "pass": False, "hit": [], "miss": ["id 없음"]})
    return out


def _nums(text: str) -> list[float]:
    t = text.replace("−", "-").replace("–", "-")
    out = []
    for m in _NUM.finditer(t):
        try:
            out.append(float(m.group(0).replace(",", "")))
        except ValueError:
            pass
    return out


def _term_spans(term: str, text: str) -> list[tuple[int, int]]:
    if term.startswith("re:"):   # 한 글자 신호등(황·적)처럼 부분 문자열이면 오탐('상황')인 용어
        return [m.span() for m in re.finditer(term[3:], text)]
    if re.fullmatch(r"[A-Za-z]{1,2}", term):
        return [m.span() for m in re.finditer(rf"(?<![A-Za-z]){re.escape(term)}(?![A-Za-z])", text)]
    return [m.span() for m in re.finditer(re.escape(term.lower()), text.lower())]


def _term_hit(term: str, text: str) -> bool:
    return bool(_term_spans(term, text))


# 부정 문맥 (10/28 감사 재검수 req-audit-5c11f8ac — '능동이 아니라 수동'·'1건도 없다'·"'없음'이 아니라" 가 필수 키를 적중시킴).
# 필수(req) 용어 키의 적중 위치 앞뒤 같은 절(쉼표·마침표 등 경계, NEG_WIN 자 창) 안에 부정 표지가 그 키를 부정하면 그 적중은 무효.
#  - 강한 부정('아니라·아님·아니다·not'): 긍정 키를 부정.
#  - 부재 표지('도 없·없다·없음·않·안 '): 긍정 키만 부정. 부정 개념 키(negative:true, 또는 키에 없·않·아니·미커버·불가·불필요 포함)는
#    반대로 처리 — 부재 표지는 같은 방향이라 무시('미커버(없음)' 정상), 키에 바로 붙은 '…이 아니라' 만 무효("'없음'이 아니라 수동").
#  - 한국어는 부정이 뒤에 붙는다: 뒤 창 = 위 표지, 앞 창 = 바로 앞 'not '·'안 '·'못 ' 만('A가 아니라 B' 의 B 는 긍정).
# 키에 "negcheck": false 면 끔(옵션 필드 — 기존 키 파일 호환).
NEG_WIN = 12
_CLAUSE_END = re.compile(r"[,;!?\n。]|(?<!\d)\.|\.(?!\d)|\s—\s")
_NEG_STRONG = re.compile(r"아니(?:라|다|고|며|에요|야)?|아님|\bnot\b|\bisn't\b", re.I)
_NEG_ABSENT = re.compile(r"도\s*없|없다|없음|없어|없고|않|(?<![가-힣])안\s")
_NEG_PRE = re.compile(r"(?:\bnot|(?<![가-힣])안|(?<![가-힣])못)\s+$", re.I)
_NEG_ATTACHED = re.compile(r"[\'\"‘’“”)\]]*\s*(?:이|가|은|는)?\s*(?:아니|아님|not\b)", re.I)
_NEG_CONCEPT = re.compile(r"없|않|아니|미커버|미지정|불가|불필요|부재")


def _is_negative_key(k: dict) -> bool:
    if "negative" in k:
        return bool(k["negative"])
    return any(_NEG_CONCEPT.search(t) for t in k.get("t", []))


def _negated(text: str, s: int, e: int, negative: bool) -> bool:
    post = text[e:e + NEG_WIN]
    m = _CLAUSE_END.search(post)
    if m:
        post = post[:m.start()]
    if negative:   # 부정 개념 키: 키에 바로 붙은 '…이/가 아니(라)' 만 반대 뜻("'없음'이 아니라") — '창 안이라 시행 아님' 처럼 뒤 낱말 부정은 무시
        return _NEG_ATTACHED.match(post) is not None
    if _NEG_STRONG.search(post) or _NEG_ABSENT.search(post):
        return True
    pre = text[max(0, s - 6):s]
    if _NEG_PRE.search(pre):
        return True
    return False


def _key_hit(k: dict, text: str) -> bool:
    terms = k.get("t", [])
    if not (k.get("req") and k.get("negcheck", True)):
        return any(_term_hit(t, text) for t in terms)
    negative = _is_negative_key(k)
    return any(not _negated(text, s, e, negative) for t in terms for s, e in _term_spans(t, text))


def key_label(k: dict) -> str:
    return f"{k['n']:g}" if "n" in k else "/".join(k["t"][:2])


def grade(item: dict, text: str) -> dict:
    nums = _nums(text)
    hit, miss = [], []
    for k in item.get("keys", []):
        if "n" in k:
            tol = k.get("tol", max(abs(k["n"]) * 0.01, 0.05))
            ok = any(abs(x - k["n"]) <= tol + 1e-12 or abs(abs(x) - abs(k["n"])) <= tol + 1e-12 for x in nums)
        else:
            ok = _key_hit(k, text)
        (hit if ok else miss).append(key_label(k))
    n = len(hit) + len(miss)
    score = len(hit) / n if n else 0.0
    # 필수 키(req): 점수가 넘어도 핵심 판단(예: 사용률 99.1·신호등 적)을 놓치면 불통과 — 평가 키 역검사 10/27(req-edu-ff390d0d)
    req_miss = [key_label(k) for k in item.get("keys", []) if k.get("req") and key_label(k) in miss]
    return {"id": item["id"], "desk": item.get("desk"), "score": round(score, 2),
            "pass": score >= item.get("pass", PASS) and not req_miss, "hit": hit, "miss": miss, "req_miss": req_miss}


def parse_drill_lines(text: str) -> list[tuple[str, str]]:
    return [(m.group(1), m.group(2)) for m in map(DRILL_LINE.match, text.splitlines()) if m]


def grade_round(round_dir: Path, keys: dict[str, dict]) -> list[dict]:
    """라운드 폴더의 *.md(밑줄 파일 제외) `드릴:` 줄 → 채점 결과. 모르는 id 는 score None."""
    out = []
    for p in sorted(round_dir.glob("*.md")):
        if p.name.startswith("_"):
            continue
        for did, ans in parse_drill_lines(p.read_text(encoding="utf-8")):
            if did in keys:
                out.append({**grade(keys[did], ans), "file_desk": p.stem})
            else:
                out.append({"id": did, "desk": p.stem, "file_desk": p.stem, "score": None, "pass": False, "hit": [], "miss": ["id 없음"]})
    return out


def drill_rows(rnd: str, graded: list[dict]) -> list[str]:
    rows = []
    for g in graded:
        sc = "—" if g["score"] is None else f"{g['score']:.0%}"
        verdict = "id 없음" if g["score"] is None else ("통과" if g["pass"] else "미달")
        rows.append(f"| {rnd} | {g['file_desk']} | {g['id']} | {sc} | {verdict} | {', '.join(g['miss']) or '—'} |")
    return rows


def append_drill_table(text: str, rnd: str, graded: list[dict]) -> tuple[str, int]:
    """_scoreboard.md 에 `## 드릴 표` 절(없으면 만들고)과 줄을 붙인다. 같은 (라운드, 데스크, 드릴) 줄은 건너뜀."""
    if not graded:
        return text, 0
    lines = text.rstrip("\n").split("\n") if text.strip() else []
    if DRILL_HEAD not in lines:
        lines += ["", DRILL_HEAD, "",
                  "라운드 파일의 `드릴: <id> <내 답>` 줄을 `scripts/drill_grade.py` 가 content/drills/<desk>.json 키로 채점(round_collect 수집 때). "
                  "점수 = 맞힌 핵심 숫자·용어 비율, 60% 이상 통과 — 판단의 질은 감사 채점이 본다 (10/24 겸이 결재 G1).", "",
                  DRILL_COLS, DRILL_SEP]
    have = set()
    for ln in lines:
        c = [x.strip() for x in ln.split("|")]
        if len(c) >= 5 and re.fullmatch(r"[a-z_]+-d\d+", c[3]):
            have.add((c[1], c[2], c[3]))
    new = [r for r, g in zip(drill_rows(rnd, graded), graded) if (rnd, g["file_desk"], g["id"]) not in have]
    hi = lines.index(DRILL_HEAD)
    end = hi
    for i in range(hi + 1, len(lines)):
        if lines[i].startswith("|"):
            end = i
        elif lines[i].startswith("## "):
            break
    lines[end + 1:end + 1] = new
    return "\n".join(lines).rstrip("\n") + "\n", len(new)


def check(kb_dir: Path = KB_DIR, keys_dir: Path = KEYS_DIR) -> list[str]:
    """KB 드릴 줄에 답이 남아 있지 않고(`**답:**`·`드릴 답:`), 모든 드릴 id 에 키가 있고, 키 형식이 맞는지."""
    errs = []
    keys = load_keys(keys_dir)
    for did, it in keys.items():
        if not it.get("q") or not it.get("answer") or not it.get("keys"):
            errs.append(f"{did}: q·answer·keys 필요")
        for k in it.get("keys", []):
            if not (isinstance(k.get("n"), (int, float)) or (isinstance(k.get("t"), list) and k["t"])):
                errs.append(f"{did}: 키 형식 오류 {k}")
        if not did.startswith(f"{it['desk']}-d"):
            errs.append(f"{did}: id 접두 ≠ 파일 데스크 '{it['desk']}'")
    seen = set()
    for p in sorted(kb_dir.glob("*.md")):
        for ln in p.read_text(encoding="utf-8").splitlines():
            if ln.startswith("- 드릴 답"):
                errs.append(f"{p.name}: '드릴 답' 줄이 KB 에 남음 — content/drills/{p.stem}.json 로 (G1)")
                continue
            m = KB_DRILL.match(ln)
            if not m:
                continue
            if "**답:**" in ln:
                errs.append(f"{p.name}: 드릴 답이 문제 줄에 남음 — content/drills/{p.stem}.json 로 (G1)")
            if not m.group(1):
                errs.append(f"{p.name}: 드릴 id 없음 — '- 드릴 [{p.stem}-dN]: …'")
            elif m.group(1) not in keys:
                errs.append(f"{p.name}: 드릴 {m.group(1)} 키 없음 (content/drills/{p.stem}.json)")
            else:
                seen.add(m.group(1))
    for did in sorted(set(keys) - seen):
        errs.append(f"{did}: 키는 있는데 KB 에 문제 줄이 없음")
    return errs


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--grade")
    ap.add_argument("--text", default="")
    ap.add_argument("--round")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--sheet", help="답안 파일(퀴즈:·드릴: 줄) 채점")
    ap.add_argument("--keys", action="append", default=[], help="비공개 키 파일 추가(재시험 — 키 공개 전 평가 채점용, 드릴 키 형식)")
    a = ap.parse_args(argv)
    if a.check:
        errs = check() + check_onboarding()
        for e in errs:
            print("FAIL", e)
        print(f"{'ok' if not errs else str(len(errs)) + ' errors'}: 드릴 {len(load_keys())}개 · 온보딩 퀴즈 {len(load_onboarding())}개")
        return 1 if errs else 0
    keys = {**load_keys(), **load_onboarding()}
    for kp in a.keys:
        keys.update(load_key_file(Path(kp)))
    if a.sheet:
        res = grade_sheet(Path(a.sheet).read_text(encoding="utf-8"), keys)
        for r in res:
            sc = "—" if r["score"] is None else f"{r['score']:.0%}"
            print(f"| {r['id']} | {sc} | {'통과' if r['pass'] else '미달'} | {', '.join(r['miss']) or '—'} |")
        q = [r for r in res if r["id"].split("-")[-1].startswith("q")]
        if q:
            print(f"퀴즈 통과 {sum(r['pass'] for r in q)}/{len(q)}")
        return 0
    if a.grade:
        if a.grade not in keys:
            print(f"드릴 id 없음: {a.grade}")
            return 1
        print(json.dumps(grade(keys[a.grade], a.text), ensure_ascii=False))
        return 0
    if a.round:
        graded = grade_round(ROUNDS_DIR / a.round, keys)
        for r in drill_rows(a.round, graded):
            print(r)
        if a.apply and graded:
            sb = SCOREBOARD.read_text(encoding="utf-8") if SCOREBOARD.exists() else ""
            new, n = append_drill_table(sb, a.round, graded)
            SCOREBOARD.write_text(new, encoding="utf-8")
            print(f"드릴 표 +{n}줄")
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
