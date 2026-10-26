#!/usr/bin/env python3
"""결재 ✅ → rules.txt 반영 현황 블록 생성 + 미반영 검사 (감사 2026-10-17 P0-2, 설계 docs/integrity_dev_plan_2026-10-17.md §2).

입력(둘 다 비공개 저장소 — 이 스크립트는 경로만 받고 본문을 출력하지 않는다):
  - 합의 원장 ops/agreements.md 의 §7-3 '일요일 결재 일괄 도장'(헤더 ✅) 줄
      · `결재 이슈 #1·#2·…` 줄 = 도장 받은 결재 목록, `#a→#b` = 통합
      · `- #n …` 줄(한 줄에 `· #m …` 여러 건 가능)의 `[k]` 토큰 = 결재 #n 이 고치는 rules.txt 조항
      · 원장 어디서든 ✅ 줄의 `결재 #n [k]` (바로 붙은 토큰) 도 매핑에 더함
  - rules.txt 조항 헤더 `[k. …]` 와 조항 본문의 꼬리표 `(결재 #n 반영 m/d)`
상태: 반영(매핑 조항 모두 꼬리표) · 일부 반영 · 미반영(조항 있음, 꼬리표 없음) · 조항 없음(rules.txt 에 [k] 헤더 없음) ·
      미지정(원장에 [k] 토큰 없음 — 기록 데스크가 토큰을 달아야 함) · 규정 무관(원장 줄에 '(규정 무관)') · 통합→#b
출력에는 결재 번호·조항 번호·상태·원장 키만 — 금액·종목·규칙 문구는 절대 넣지 않는다(공개 저장소 규칙).

  python3 scripts/rules_status.py                    # 블록 미리보기 (기본 경로 ../pb-private)
  python3 scripts/rules_status.py --write            # rules.txt 맨 위 생성 블록만 교체 (본문 무변경)
  python3 scripts/rules_status.py --check [--today 2026-10-26]
        # 미반영 검사: 발효일+7일 지난 미반영 = 중, 예약 PB 가 읽는 조항([5]·[12]) = 치명, 블록 낡음 = 경
        # 종료코드: 치명 ≥1 이면 1
비공개 integrity_check.py (g) 가 이 모듈의 findings() 를 그대로 쓴다.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PB_DEFAULT = Path(os.environ.get("PB_PRIVATE_DIR", ROOT.parent / "pb-private"))
LEDGER_REL = "ops/agreements.md"
RULES_REL = "rules.txt"

PB_READ_CLAUSES = {5, 12}       # 14:42 예약 PB 가 직접 읽는 조항 — 미반영이면 치명 (설계 §2)
GRACE_DAYS = 7                  # 발효일 + 7일 지나면 미반영 경보
SECTION_KEY = "7-3"

BLOCK_START = "# [결재 반영 현황 — 자동 생성, scripts/rules_status.py]"
BLOCK_END = "# [/결재 반영 현황]"

RE_SECTION = re.compile(r"^(#{2,4})\s*(\d+(?:-\d+)?)\.")
RE_MD = re.compile(r"(?<![\d/])(\d{1,2})/(\d{1,2})(?![\d/])")
RE_ISSUES = re.compile(r"결재\s*이슈\s*((?:#\d+\s*[·,]?\s*)+)")
RE_MERGE = re.compile(r"#(\d+)[^#·,()→]{0,8}→\s*#(\d+)")
RE_SEG = re.compile(r"(?:^\s*[-*]\s*|\s·\s)(?=#\d+\s)")
RE_SEG_ID = re.compile(r"^#(\d+)\s")
RE_CLAUSE_TOK = re.compile(r"\[(\d{1,2})\]")
RE_ADJ = re.compile(r"결재\s*#(\d+)\s*((?:\[\d{1,2}\]\s*[,·]?\s*)+)")
RE_RULE_HEAD = re.compile(r"^\[(\d{1,2})\.")
RE_TAG = re.compile(r"\(결재\s*#(\d+)\s*반영\s*(\d{1,2})/(\d{1,2})\)")


@dataclass
class Approval:
    no: int
    key: str = SECTION_KEY
    clauses: set = field(default_factory=set)
    effective: date | None = None
    merged_into: int | None = None
    exempt: bool = False            # 원장 줄에 '(규정 무관)' — rules.txt 를 고치지 않는 결재


@dataclass
class Row:
    no: int
    clauses: list
    state: str
    key: str
    effective: date | None
    tagged: list = field(default_factory=list)


def mk_date(today: date, m: int, d: int) -> date | None:
    """연도 없는 m/d → today 에 가장 가까운 연도."""
    best = None
    for y in (today.year - 1, today.year, today.year + 1):
        try:
            c = date(y, m, d)
        except ValueError:
            continue
        if best is None or abs((c - today).days) < abs((best - today).days):
            best = c
    return best


def _first_date(text: str, today: date) -> date | None:
    m = RE_MD.search(text)
    return mk_date(today, int(m.group(1)), int(m.group(2))) if m else None


def parse_ledger(text: str, today: date) -> dict[int, Approval]:
    lines = text.splitlines()
    out: dict[int, Approval] = {}
    start = level = None
    for i, ln in enumerate(lines):
        m = RE_SECTION.match(ln)
        if m and m.group(2) == SECTION_KEY:
            start, level = i, len(m.group(1))
            break
    if start is None or "✅" not in lines[start]:
        sec = []
        head_date = None
    else:
        head_date = _first_date(lines[start], today)
        sec = []
        for ln in lines[start + 1:]:
            m = RE_SECTION.match(ln)
            if m and len(m.group(1)) <= level:
                break
            sec.append(ln)

    def get(n: int) -> Approval:
        if n not in out:
            out[n] = Approval(no=n, effective=head_date)
        return out[n]

    for ln in sec:
        mi = RE_ISSUES.search(ln)
        if mi:
            for n in re.findall(r"#(\d+)", mi.group(1)):
                get(int(n))
        for a, b in RE_MERGE.findall(ln):
            get(int(a)).merged_into = int(b)
            get(int(b))
        if mi:
            continue
        for seg in RE_SEG.split(ln)[1:]:
            ms = RE_SEG_ID.match(seg)
            if not ms:
                continue
            ap = get(int(ms.group(1)))
            ap.clauses |= {int(k) for k in RE_CLAUSE_TOK.findall(seg)}
            ap.exempt |= "규정 무관" in seg
            d = _first_date(seg, today) if re.search(r"\(\s*\d{1,2}/\d{1,2}\s*(?:발효|시행)", seg) else None
            if d:
                ap.effective = d
    # 원장 전체: ✅ 줄의 '결재 #n [k]' — 도장 받은 결재에만 더한다
    for ln in lines:
        if "✅" not in ln:
            continue
        for n, toks in RE_ADJ.findall(ln):
            n = int(n)
            if n in out:
                out[n].clauses |= {int(k) for k in RE_CLAUSE_TOK.findall(toks)}
    return out


def strip_block(text: str) -> str:
    lines = text.splitlines(keepends=True)
    if lines and lines[0].startswith(BLOCK_START):
        for i, ln in enumerate(lines):
            if ln.startswith(BLOCK_END):
                return "".join(lines[i + 1:])
    return text


def parse_rules(text: str) -> tuple[set, dict]:
    """→ (조항 번호 집합, {결재#: [꼬리표가 붙은 조항 번호…]})"""
    clauses, tags = set(), {}
    cur = None
    for ln in strip_block(text).splitlines():
        m = RE_RULE_HEAD.match(ln)
        if m:
            cur = int(m.group(1))
            clauses.add(cur)
        for n, _mm, _dd in RE_TAG.findall(ln):
            tags.setdefault(int(n), [])
            if cur is not None and cur not in tags[int(n)]:
                tags[int(n)].append(cur)
    return clauses, tags


def build_rows(ledger_text: str, rules_text: str, today: date) -> list[Row]:
    aps = parse_ledger(ledger_text, today)
    clauses, tags = parse_rules(rules_text)
    rows = []
    for n in sorted(aps):
        ap = aps[n]
        cl = sorted(ap.clauses)
        tagged = sorted(tags.get(n, []))
        if ap.merged_into is not None:
            st = f"통합→#{ap.merged_into}"
        elif not cl:
            st = "반영" if tagged else ("규정 무관" if ap.exempt else "미지정")
        elif any(k not in clauses for k in cl):
            st = "조항 없음"
        elif all(k in tagged for k in cl):
            st = "반영"
        elif tagged:
            st = "일부 반영"
        else:
            st = "미반영"
        rows.append(Row(n, cl, st, ap.key, ap.effective, tagged))
    return rows


def _cl(row: Row) -> str:
    return ",".join(f"[{k}]" for k in row.clauses) or "-"


def render_block(rows: list[Row], stamp: str) -> str:
    out = [f"{BLOCK_START} 기준 원장 {stamp}",
           "# 사람이 고치지 않음 — 본문 조항에 '(결재 #n 반영 m/d)' 꼬리표를 달면 다음 생성 때 '반영'으로 바뀜",
           f"# {'결재#':<6} {'조항':<10} {'상태':<8} 원장 키"]
    for r in rows:
        out.append(f"# {'#' + str(r.no):<6} {_cl(r):<10} {r.state:<8} {r.key}")
    if not rows:
        out.append("# (원장 §7-3 에서 도장 받은 결재를 찾지 못함)")
    out.append(BLOCK_END)
    return "\n".join(out) + "\n"


def apply_block(rules_text: str, block: str) -> str:
    return block + strip_block(rules_text)


def current_block(rules_text: str) -> str | None:
    if not rules_text.startswith(BLOCK_START):
        return None
    body = strip_block(rules_text)
    return rules_text[: len(rules_text) - len(body)]


def _norm_block(b: str | None) -> str:
    """블록 비교 — 기준 스탬프 줄은 빼고 본다(원장 커밋만 바뀌고 내용 같으면 낡음 아님)."""
    if b is None:
        return ""
    return "\n".join(ln for ln in b.splitlines() if not ln.startswith(BLOCK_START))


def findings(ledger_text: str, rules_text: str, today: date) -> list[tuple[str, str, str]]:
    """→ [(심각도, 위치, 메시지)] — 금액·문구 없음. integrity_check (g) 가 그대로 쓴다."""
    rows = build_rows(ledger_text, rules_text, today)
    fs = []
    for r in rows:
        where = f"{LEDGER_REL} §{r.key} 결재 #{r.no}"
        if r.state in ("미반영", "일부 반영", "조항 없음"):
            eff = r.effective
            if eff is None:
                fs.append(("경", where, f"{r.state} {_cl(r)} — 발효일 미확인"))
                continue
            due = eff + timedelta(days=GRACE_DAYS)
            if today <= due:
                continue
            sev = "치명" if set(r.clauses) & PB_READ_CLAUSES else "중"
            fs.append((sev, where, f"{r.state} {_cl(r)} — 발효 {eff:%m/%d} + {GRACE_DAYS}일({due:%m/%d}) 경과"
                       + (" · 예약 PB 가 읽는 조항" if sev == "치명" else "")))
        elif r.state == "미지정":
            fs.append(("경", where, "rules.txt 조항 토큰 [k] 없음 — 원장 §7-3 줄에 조항 번호 [k] 를 달거나,"
                       " rules.txt 를 고치지 않는 결재면 '(규정 무관)' 표기 필요"))
    gen = render_block(rows, "-")
    cur = current_block(rules_text)
    if cur is None:
        fs.append(("경", RULES_REL, "반영 현황 블록 없음 — `python3 scripts/rules_status.py --write`"))
    elif _norm_block(cur) != _norm_block(gen):
        fs.append(("경", RULES_REL, "반영 현황 블록이 원장·꼬리표와 다름(낡음) — `--write` 로 재생성"))
    return fs


def ledger_stamp(pb_dir: Path) -> str:
    try:
        s = subprocess.run(["git", "log", "-1", "--format=%cd", "--date=format:%Y-%m-%d %H:%M", "--", LEDGER_REL],
                           cwd=pb_dir, capture_output=True, text=True, timeout=10).stdout.strip()
        if s:
            return s
    except Exception:  # noqa: BLE001
        pass
    try:
        return datetime.fromtimestamp((pb_dir / LEDGER_REL).stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    except OSError:
        return "미확인"


def _kst_today() -> date:
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Asia/Seoul")).date()
    except Exception:  # noqa: BLE001
        return date.today()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--pb", default=str(PB_DEFAULT), help="비공개 저장소 경로 (기본 ../pb-private)")
    ap.add_argument("--today", help="YYYY-MM-DD (기본: KST 오늘)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--write", action="store_true", help="rules.txt 맨 위 생성 블록만 교체")
    g.add_argument("--check", action="store_true", help="미반영 검사 (치명 ≥1 → 종료코드 1)")
    a = ap.parse_args(argv)
    pb = Path(a.pb)
    today = datetime.strptime(a.today, "%Y-%m-%d").date() if a.today else _kst_today()
    try:
        ledger = (pb / LEDGER_REL).read_text(encoding="utf-8")
        rules = (pb / RULES_REL).read_text(encoding="utf-8")
    except OSError as e:
        print(f"rules_status: 비공개 파일 없음 ({type(e).__name__}) — --pb 경로 확인", file=sys.stderr)
        return 2
    if a.check:
        fs = findings(ledger, rules, today)
        c = {s: sum(1 for f in fs if f[0] == s) for s in ("치명", "중", "경")}
        print(f"rules_status: 치명 {c['치명']} · 중 {c['중']} · 경 {c['경']}")
        for sev, where, msg in fs:
            print(f"[{sev}] {where} — {msg}")
        return 1 if c["치명"] else 0
    block = render_block(build_rows(ledger, rules, today), ledger_stamp(pb))
    if a.write:
        new = apply_block(rules, block)
        if strip_block(new) != strip_block(rules):   # 본문 무변경 보증
            print("rules_status: 본문이 바뀌는 쓰기 — 중단", file=sys.stderr)
            return 2
        if new != rules:
            (pb / RULES_REL).write_text(new, encoding="utf-8")
            print(f"rules_status: {RULES_REL} 반영 현황 블록 갱신")
        else:
            print("rules_status: 변경 없음")
        return 0
    sys.stdout.write(block)
    return 0


if __name__ == "__main__":
    sys.exit(main())
