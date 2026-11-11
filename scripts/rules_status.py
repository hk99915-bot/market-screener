#!/usr/bin/env python3
"""결재 ✅ → rules.txt 반영 현황 블록 생성 + 미반영 검사 (감사 2026-10-17 P0-2, 설계 docs/integrity_dev_plan_2026-10-17.md §2).

입력(둘 다 비공개 저장소 — 이 스크립트는 경로만 받고 본문을 출력하지 않는다):
  - 합의 원장 ops/agreements.md 의 §7-3 '일요일 결재 일괄 도장'(헤더 ✅) 줄
      · `결재 이슈 #1·#2·…` 줄 = 도장 받은 결재 목록, `#a→#b` = 통합
      · `- #n …` 줄(한 줄에 `· #m …` 여러 건 가능)의 `[k]` 토큰 = 결재 #n 이 고치는 rules.txt 조항
      · 원장 어디서든 ✅ 줄의 `결재 #n [k]` (바로 붙은 토큰) 도 매핑에 더함
  - 원장 전체의 ✅ 결재·합의 줄 중 규칙·한도 관련 줄(감사 R01, 11/11) — 판별 기준은 아래 RE_APPROVED_HEAD 위 주석 ①~⑤.
      §7-3 번호 결재에 속한 줄은 번호 결재로만 센다(이중 추적 없음). 이 줄들은 '원장 행 L<n>' 단위로 추적한다.
  - rules.txt 조항 헤더 `[k. …]` 와 조항 본문의 꼬리표 두 형식
      · `(결재 #n 반영 m/d)`                 — 번호 결재 #n
      · `(결재: agreements N·M~K행, m/d 반영…)` — 원장 행 번호(11/5 반영분부터 쓰는 형식). 번호 결재에 속한 행이면
        그 결재의 조항(조항 토큰이 없으면 '(규정 무관)'이 아닐 때 아무 조항)에 대해 반영으로 센다.
      · `(결재 m/d 반영 m/d)` 처럼 결재를 날짜로만 가리키는 꼬리표는 행을 특정할 수 없어 인식하지 않는다.
상태: 반영(매핑 조항 모두 꼬리표) · 일부 반영 · 미반영(조항 있음, 꼬리표 없음) · 조항 없음(rules.txt 에 [k] 헤더 없음) ·
      미지정(원장에 [k] 토큰 없음 — 기록 데스크가 토큰을 달아야 함) · 규정 무관(원장 줄에 '(규정 무관)') · 통합→#b
경과일: 결재일(번호 결재 = §7-3 헤더 날짜, 원장 행 = `_approval_date()`: 머리 괄호 날짜→절 헤더 날짜→첫 m/d) 대비 today 까지 날짜 수(D+n).
출력에는 결재 번호·원장 행 번호·조항 번호·상태·날짜만 — 금액·종목·규칙 문구는 절대 넣지 않는다(공개 저장소 규칙).

  python3 scripts/rules_status.py                    # 블록 미리보기 (기본 경로 ../pb-private)
  python3 scripts/rules_status.py --write            # rules.txt 맨 위 생성 블록만 교체 (본문 무변경)
  python3 scripts/rules_status.py --check [--today 2026-10-26]
        # 미반영 검사: 발효일(원장 행은 결재일)+7일 지난 미반영 = 중, 예약 PB 가 읽는 조항([5]·[12]) = 치명, 블록 낡음 = 경
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
# 11/5 형식: (결재: agreements 22·26·134행, 11/5 반영) · (결재: agreements 24·102~103·134행, 11/5 반영 — …)
RE_TAG_ROWS = re.compile(r"\(결재\s*:\s*agreements\s*((?:\d+(?:\s*~\s*\d+)?\s*[·,]\s*)*\d+(?:\s*~\s*\d+)?)\s*행"
                         r"\s*,\s*(\d{1,2})/(\d{1,2})\s*반영")
RE_HEAD_APPROVAL = re.compile(r"^#{2,4}\s.*결재\s*#(\d+)")

# ── 원장 행 추적 대상 판별 (감사 R01) — 보수적 기준: '규칙·한도를 정하거나 바꾸는 결재'라는 표지가 그 줄 안에
#    명시된 경우만 잡는다(✅ 줄 509개 중 대부분은 운영·조직·개발 합의라 넣으면 경보가 소음이 된다).
#    여기서 빠진 결재는 원장 줄에 `규칙 [k]` 를 적으면 다음 생성 때 잡힌다. 기준(모두 만족):
#    ① 목록 줄이고 상태 머리가 ✅ (`- ✅`, `- 🌙✅`, `- ✅🌙`, `- ☑️→✅`, `- 🗳️→✅`). 인용(>)·헤더·☑️/🗳️ 단독은 제외.
#       줄 중간의 '→ ✅ 정정' 같은 표기는 결재 머리가 아니므로 보지 않는다.
#    ② 머리 바로 뒤가 '사전등록'·'집행'이면 제외 — 사전등록은 결재 전 단계, 집행은 매매 실행 기록이다.
#    ③ 줄에 비변경 표지가 있으면 제외: 반려·철회·취소·'규정 무관'·'rules.txt 무관'·'합의 아님'·
#       '규칙 변경 아님/아닌/없음'·'한도…아님'·'건드리지 않'·'rules.txt 정리/반영'(이미 추적되는 결재를
#       문언으로 옮기는 작업의 승인 — 새 결재가 아님).
#    ④ 규칙 관련 표지가 하나 이상: (a) `규칙|규정|조항 [k]` (b) `rules.txt` 또는 `rules N절`
#       (c) 조항 토큰 `[k]` + 같은 줄에 규칙 낱말(규칙·규정·한도·상한·하한·발동선·백스톱·손절)
#       (d) '결재' + 한도 낱말과 % 수치가 붙어 있음(예: '한도 −15%', '45% 발동선')
#    ⑤ §7-3 번호 결재(#n)에 속한 줄이 아님 — 그 줄은 번호 결재 행으로만 센다.
RE_APPROVED_HEAD = re.compile(r"^\s*[-*]\s*(?:☑️\s*→\s*|🗳️\s*→\s*)?(?:🌙\s*)?✅\s*(?:🌙\s*)?")
RE_HEAD_SKIP = re.compile(r"^(?:\*\*)?(?:사전등록|집행)")
RE_NOT_CHANGE = re.compile(r"반려|철회|취소|규정\s*무관|rules\.txt\s*무관|합의\s*아님"
                           r"|규칙\s*변경\s*(?:아[님닌니]|이\s*아|없)|한도[^\n]{0,8}?아님|건드리지\s*않"
                           r"|rules\.txt\s*(?:정리|반영)")
RE_RULE_REF = re.compile(r"(?:규칙|규정|조항)\s*\[(\d{1,2})\]|rules\.txt|rules\s*\d{1,2}\s*절")
RE_RULE_WORD = re.compile(r"규칙|규정|한도|상한|하한|발동선|백스톱|손절")
RE_LIMIT_NUM = re.compile(r"(?:한도|상한|하한|발동선|백스톱|손절선)[^\n]{0,12}?[−-]?\d+(?:\.\d+)?\s*%"
                          r"|[−-]?\d+(?:\.\d+)?\s*%\s*(?:한도|상한|하한|발동선|백스톱|손절선)")


@dataclass
class Approval:
    no: int
    key: str = SECTION_KEY
    clauses: set = field(default_factory=set)
    effective: date | None = None
    merged_into: int | None = None
    exempt: bool = False            # 원장 줄에 '(규정 무관)' — rules.txt 를 고치지 않는 결재
    approved: date | None = None    # 결재일(§7-3 헤더 날짜) — 경과일 기준
    lines: set = field(default_factory=set)   # 이 결재를 정의하는 원장 행 번호(1부터) — 11/5 형식 꼬리표 대조용


@dataclass
class Row:
    no: int
    clauses: list
    state: str
    key: str
    effective: date | None
    tagged: list = field(default_factory=list)
    approved: date | None = None
    line: int | None = None          # 원장 행 추적이면 행 번호(번호 결재는 None)
    today: date | None = None

    @property
    def ident(self) -> str:
        return f"L{self.line}" if self.line is not None else f"#{self.no}"

    @property
    def elapsed(self) -> int | None:
        if self.approved is None or self.today is None:
            return None
        return (self.today - self.approved).days


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
        for j, ln in enumerate(lines[start + 1:], start + 2):
            m = RE_SECTION.match(ln)
            if m and len(m.group(1)) <= level:
                break
            sec.append((j, ln))

    def get(n: int) -> Approval:
        if n not in out:
            out[n] = Approval(no=n, effective=head_date, approved=head_date)
        return out[n]

    for j, ln in sec:
        mi = RE_ISSUES.search(ln)
        if mi:
            for n in re.findall(r"#(\d+)", mi.group(1)):
                get(int(n))
        for a, b in RE_MERGE.findall(ln):
            get(int(a)).merged_into = int(b)
            get(int(b))
        if mi:
            continue                     # 결재 목록 줄은 특정 결재의 정의 행이 아님
        for seg in RE_SEG.split(ln)[1:]:
            ms = RE_SEG_ID.match(seg)
            if not ms:
                continue
            ap = get(int(ms.group(1)))
            ap.lines.add(j)
            ap.clauses |= {int(k) for k in RE_CLAUSE_TOK.findall(seg)}
            ap.exempt |= "규정 무관" in seg
            d = _first_date(seg, today) if re.search(r"\(\s*\d{1,2}/\d{1,2}\s*(?:발효|시행)", seg) else None
            if d:
                ap.effective = d
    # 원장 전체: ✅ 줄의 '결재 #n [k]' — 도장 받은 결재에만 더한다
    for j, ln in enumerate(lines, 1):
        if "✅" not in ln:
            continue
        for n, toks in RE_ADJ.findall(ln):
            n = int(n)
            if n in out:
                out[n].clauses |= {int(k) for k in RE_CLAUSE_TOK.findall(toks)}
                out[n].lines.add(j)
    # '### 7-1. 결재 #2 — …' 처럼 번호 결재 전용 절: 헤더와 본문 행을 그 결재의 정의 행으로
    for i, ln in enumerate(lines):
        m = RE_HEAD_APPROVAL.match(ln)
        if not m or int(m.group(1)) not in out or RE_SECTION.match(ln) is None:
            continue
        lv = len(RE_SECTION.match(ln).group(1))
        ap = out[int(m.group(1))]
        ap.lines.add(i + 1)
        for j, body in enumerate(lines[i + 1:], i + 2):
            ms = RE_SECTION.match(body)
            if (ms and len(ms.group(1)) <= lv) or body.startswith("#"):
                break
            ap.lines.add(j)
    return out


def is_rule_approval(ln: str) -> bool:
    """원장 한 줄이 추적 대상(✅ 결재·합의 중 규칙·한도 관련)인가 — 기준은 RE_APPROVED_HEAD 위 주석 ①~④."""
    m = RE_APPROVED_HEAD.match(ln)
    if not m:
        return False
    if RE_HEAD_SKIP.match(ln[m.end():].lstrip("( ")):
        return False
    if RE_NOT_CHANGE.search(ln):
        return False
    if RE_RULE_REF.search(ln):
        return True
    if RE_CLAUSE_TOK.search(ln) and RE_RULE_WORD.search(ln):
        return True
    return "결재" in ln and bool(RE_LIMIT_NUM.search(ln))


def ledger_rule_lines(text: str, today: date, numbered: dict[int, Approval] | None = None) -> dict[int, tuple]:
    """→ {원장 행 번호: (결재일, 조항 토큰 집합)} — 기준 ⑤: 번호 결재 정의 행은 뺀다."""
    taken = set().union(*(ap.lines for ap in (numbered or {}).values())) if numbered else set()
    out = {}
    head_date = None
    for j, ln in enumerate(text.splitlines(), 1):
        if ln.startswith("#"):
            head_date = _first_date(ln, today)
            continue
        if j in taken or not is_rule_approval(ln):
            continue
        toks = {int(k) for k in RE_CLAUSE_TOK.findall(ln)} | {int(k) for k in RE_RULE_REF.findall(ln) if k}
        out[j] = (_approval_date(ln, head_date, today), toks)
    return out


def _approval_date(ln: str, head_date: date | None, today: date) -> date | None:
    """결재일: ✅ 머리 뒤 16자 안의 괄호 '(m/d …' → 없으면 그 줄이 속한 절 헤더의 날짜 → 없으면 줄의 첫 m/d.
    (예: §7-3 안의 '☑️→✅ 규칙 [7] … 시행 전(10/16 이전)' 은 본문 날짜가 아니라 절 헤더 10/17 이 결재일)"""
    m = RE_APPROVED_HEAD.match(ln)
    rest = ln[m.end():] if m else ln
    p = re.search(r"\(\s*(\d{1,2})/(\d{1,2})(?![\d/])", rest[:16])
    if p:
        return mk_date(today, int(p.group(1)), int(p.group(2)))
    return head_date or _first_date(ln, today)


def _row_numbers(spec: str) -> set[int]:
    """'24·102~103·134' → {24, 102, 103, 134}"""
    out = set()
    for part in re.split(r"[·,]", spec):
        part = part.strip()
        if "~" in part:
            a, b = (int(x) for x in part.split("~"))
            if 0 < b - a < 200:
                out |= set(range(a, b + 1))
            else:
                out |= {a, b}
        elif part:
            out.add(int(part))
    return out


def strip_block(text: str) -> str:
    lines = text.splitlines(keepends=True)
    if lines and lines[0].startswith(BLOCK_START):
        for i, ln in enumerate(lines):
            if ln.startswith(BLOCK_END):
                return "".join(lines[i + 1:])
    return text


def parse_rules(text: str) -> tuple[set, dict]:
    """→ (조항 번호 집합, {결재#: [꼬리표가 붙은 조항 번호…]}) — '(결재 #n 반영 m/d)' 형식만."""
    clauses, tags, _rows = _scan_rules(text)
    return clauses, tags


def parse_row_tags(text: str) -> dict[int, list]:
    """→ {원장 행 번호: [꼬리표가 붙은 조항 번호…]} — '(결재: agreements N행, m/d 반영)' 형식.
    조항 헤더 앞(머리말)에 붙은 꼬리표는 조항 번호 없이(-1) 기록한다."""
    return _scan_rules(text)[2]


def _scan_rules(text: str) -> tuple[set, dict, dict]:
    clauses, tags, rows = set(), {}, {}
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
        for spec, _mm, _dd in RE_TAG_ROWS.findall(ln):
            k = cur if cur is not None else -1
            for r in _row_numbers(spec):
                rows.setdefault(r, [])
                if k not in rows[r]:
                    rows[r].append(k)
    return clauses, tags, rows


def build_rows(ledger_text: str, rules_text: str, today: date) -> list[Row]:
    aps = parse_ledger(ledger_text, today)
    clauses, tags = parse_rules(rules_text)
    row_tags = parse_row_tags(rules_text)
    # 11/5 형식 꼬리표 → 번호 결재: 꼬리표가 가리키는 행이 결재 #n 정의 행이고,
    # 꼬리표가 붙은 조항이 #n 의 조항이면(조항 토큰이 없으면 아무 조항이나) #n 반영으로 센다.
    for n, ap in aps.items():
        for ln_no in ap.lines:
            for k in row_tags.get(ln_no, []):
                # 조항 토큰 없는 결재는 '(규정 무관)'이 아닐 때만 — 무관 결재 행을 잘못 가리킨 꼬리표로 반영 처리 금지
                if k >= 0 and (k in ap.clauses or (not ap.clauses and not ap.exempt)):
                    tags.setdefault(n, [])
                    if k not in tags[n]:
                        tags[n].append(k)
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
        rows.append(Row(n, cl, st, ap.key, ap.effective, tagged, approved=ap.approved, today=today))
    # 원장 행 추적(감사 R01): ✅ 규칙·한도 결재 줄 — 꼬리표가 그 행을 한 번이라도 가리키면 반영
    for ln_no, (d, toks) in sorted(ledger_rule_lines(ledger_text, today, aps).items()):
        tagged = sorted(k for k in row_tags.get(ln_no, []) if k >= 0)
        st = "반영" if ln_no in row_tags else "미반영"
        rows.append(Row(0, sorted(toks), st, "행", d, tagged, approved=d, line=ln_no, today=today))
    return rows


def _cl(row: Row) -> str:
    return ",".join(f"[{k}]" for k in row.clauses) or "-"


def _elapsed(row: Row) -> str:
    e = row.elapsed
    return "D+?" if e is None else f"D+{e}"


def _approved(row: Row) -> str:
    return f"{row.approved:%m/%d}" if row.approved else "미확인"


def render_block(rows: list[Row], stamp: str) -> str:
    out = [f"{BLOCK_START} 기준 원장 {stamp}",
           "# 사람이 고치지 않음 — 본문 조항에 '(결재 #n 반영 m/d)' 또는 '(결재: agreements N행, m/d 반영)' 꼬리표를 달면"
           " 다음 생성 때 '반영'으로 바뀜. L<n> = 원장 n행(✅ 규칙·한도 결재), D+n = 결재일 대비 경과일",
           f"# {'결재':<6} {'조항':<10} {'상태':<8} {'결재일':<6} {'경과':<6} 원장 키"]
    for r in rows:
        out.append(f"# {r.ident:<6} {_cl(r):<10} {r.state:<8} {_approved(r):<6} {_elapsed(r):<6} {r.key}")
    if not rows:
        out.append("# (원장에서 도장 받은 결재를 찾지 못함)")
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
    """블록 비교 — 기준 스탬프 줄과 경과일(D+n)은 빼고 본다(날짜만 지나고 내용 같으면 낡음 아님)."""
    if b is None:
        return ""
    return "\n".join(re.sub(r"D\+(?:\d+|\?)\s*", "", ln) for ln in b.splitlines() if not ln.startswith(BLOCK_START))


def findings(ledger_text: str, rules_text: str, today: date) -> list[tuple[str, str, str]]:
    """→ [(심각도, 위치, 메시지)] — 금액·문구 없음. integrity_check (g) 가 그대로 쓴다."""
    rows = build_rows(ledger_text, rules_text, today)
    fs = []
    for r in rows:
        if r.line is not None:
            where = f"{LEDGER_REL}:{r.line}"
            if r.state != "미반영":
                continue
            if r.approved is None:
                fs.append(("경", where, f"✅ 규칙·한도 결재 미반영 {_cl(r)} — 결재일 미확인"))
                continue
            due = r.approved + timedelta(days=GRACE_DAYS)
            if today <= due:
                continue
            sev = "치명" if set(r.clauses) & PB_READ_CLAUSES else "중"
            fs.append((sev, where, f"✅ 규칙·한도 결재 미반영 {_cl(r)} — 결재 {r.approved:%m/%d} 뒤 {r.elapsed}일"
                       f"(+{GRACE_DAYS}일 {due:%m/%d} 경과), rules.txt 에 '(결재: agreements {r.line}행, m/d 반영)' 없음"
                       + (" · 예약 PB 가 읽는 조항" if sev == "치명" else "")))
            continue
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
                       + (f", 결재 뒤 {r.elapsed}일" if r.elapsed is not None else "")
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
