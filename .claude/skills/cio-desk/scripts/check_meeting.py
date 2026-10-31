#!/usr/bin/env python3
"""운용회의·CIO 판정 문서 검사 — CIO 스킬 시범(2026-10-31). 검사만 한다(문서를 고치지 않음).

  python3 .claude/skills/cio-desk/scripts/check_meeting.py docs/desk_kb/rounds/<날짜>/ops_meeting_kr.md [...]

근거(원본 KB docs/desk_kb/cio.md, STANDARD.md):
실패(종료코드 1)
  - 상단 3칸 What / So What / Now What 중 빠진 칸 (STANDARD §8)
  - 기준 시각 줄 없음 — '기준 YYYY-MM-DD' 또는 '기준 MM/DD' (STANDARD §8 숫자 표기)
  - F등급 확인 신호(외국인 2일·당일 순매수, 5일 고점 회복)를 tell·관측·(F)·금지·기각 표기 없이 씀
    (kb:cio#18, 복기 2026-10-16(밤), registry confirm_signals)
경고(통과는 함)
  - '진입·추격·회복' 문구 줄에 등급 꼬리표((A)·(B)·(C)·(F)·검증전)·관측·금지 표기 없음 (복기 2026-10-16(밤))
  - '불일치' 줄에 기준일(MM/DD·YYYY-MM-DD) 없음 (복기 2026-10-30)
  - 결재·수량 줄의 '환산'에 검증전·방향 참고 표기 없음 — 결재 수량은 FRM 엔진 출력만 인용 (복기 2026-10-30)
  - 제안·채택이 있는데 ΔS 표기 0건 (OKR 본부 KR2)
  - 반대 근거 0건 (STANDARD §2) · 원본 줄 없음 (STANDARD §8)
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

GRADE_TAG = re.compile(r"\((?:A|B|C|F|검증전)[^)]*\)|검증전|등급|registry")
SOFT_OK = re.compile(r"tell|관측|금지|기각|하지 말|아님|\bF\b|F등급")
F_SIGNAL = re.compile(r"외국인\s*(?:2일|당일)\s*순매수|5일\s*고점")
ACTION_WORD = re.compile(r"진입|추격|회복")
DATE = re.compile(r"\d{1,2}/\d{1,2}|20\d\d-\d\d-\d\d")
BASE_LINE = re.compile(r"기준\s*\**\s*(?:20\d\d-\d\d-\d\d|\d{1,2}/\d{1,2})")


def _has_label(text: str, label: str) -> bool:
    if label == "What":   # 'So What'·'Now What' 이 아닌 단독 What
        return re.search(r"(?<!So )(?<!Now )\bWhat\b", text) is not None
    return re.search(rf"\b{label}\b", text) is not None


def check(text: str) -> tuple[list[str], list[str]]:
    fails, warns = [], []
    for lab in ("What", "So What", "Now What"):
        if not _has_label(text, lab):
            fails.append(f"상단 칸 '{lab}' 없음 (STANDARD §8)")
    if not BASE_LINE.search(text):
        fails.append("기준 시각 줄 없음 — '기준 YYYY-MM-DD HH:MM KST' (STANDARD §8)")
    for i, line in enumerate(text.splitlines(), 1):
        if F_SIGNAL.search(line) and not SOFT_OK.search(line):
            fails.append(f"{i}행: F등급 확인 신호를 판단 문장에 씀 — tell(관측)로 옮기고 (F) 표기 (kb:cio#18): {line.strip()[:70]}")
        if ACTION_WORD.search(line) and not (GRADE_TAG.search(line) or SOFT_OK.search(line)):
            warns.append(f"{i}행: 진입·추격·회복 문구에 등급 꼬리표 없음 (복기 10/16 밤): {line.strip()[:70]}")
        if "불일치" in line and not DATE.search(line):
            warns.append(f"{i}행: '불일치' 판정 줄에 기준일·창 없음 (복기 10/30): {line.strip()[:70]}")
        if "환산" in line and re.search(r"결재|수량", line) and not re.search(r"검증전|방향 참고", line):
            warns.append(f"{i}행: 결재·수량 환산에 '검증전/방향 참고' 없음 — FRM 엔진 출력만 인용 (복기 10/30): {line.strip()[:70]}")
    if re.search(r"제안|채택", text) and "ΔS" not in text:
        warns.append("제안·채택이 있으나 ΔS 표기 0건 (OKR 본부 KR2: 제안마다 ΔS·손실 영향·대안)")
    if "반대" not in text:
        warns.append("반대 근거 0건 (STANDARD §2 — 없으면 '반대 근거 못 찾음(탐색 범위)')")
    if not re.search(r"원본", text):
        warns.append("원본 줄 없음 (STANDARD §8)")
    return fails, warns


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("files", nargs="+")
    ap.add_argument("--quiet", action="store_true", help="경고 본문 생략(개수만)")
    a = ap.parse_args(argv)
    bad = 0
    for f in a.files:
        p = Path(f)
        if not p.exists():
            print(f"✕ {f}: 파일 없음")
            bad += 1
            continue
        fails, warns = check(p.read_text(encoding="utf-8"))
        print(f"{'✕' if fails else '✓'} {f}: 실패 {len(fails)} · 경고 {len(warns)}")
        for x in fails:
            print(f"  실패 {x}")
        if not a.quiet:
            for x in warns:
                print(f"  경고 {x}")
        bad += bool(fails)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
