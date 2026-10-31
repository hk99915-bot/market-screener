#!/usr/bin/env python3
"""애널 산출물(밸류에이션 노트·셀사이드 정리·라운드 파일 .md) 형식 검사 — 애널 스킬 시범(2026-10-31). 검사만, 고치지 않는다.

  python3 .claude/skills/analyst-desk/scripts/check_note.py <파일.md> [...] [--sellside] [--round]
  python3 .claude/skills/analyst-desk/scripts/check_note.py --selftest

근거(모두 KB·STANDARD 에 이미 있는 규칙):
  실패(종료코드 1)
  - 기준일 없음 (STANDARD §1·§8 '기준 YYYY-MM-DD')
  - What / So What / Now What 칸 누락 (STANDARD §8)
  - PER 숫자를 쓰면서 분모가 1개뿐 — TTM·런레이트·가이던스·정규화 중 2개 이상 (kb:analyst#현업 vs 교과서, 복기 10/17 ①)
  - 기한 없는 [확인 필요: …] (STANDARD §1)
  - --sellside(또는 '셀사이드' 언급 자동 감지): 세 칸 '말하는 것 / 확인되는 것 / 확인 불가' 중 누락 (kb:analyst#셀사이드 자료 읽는 법)
  경고(통과는 함)
  - 셀사이드: 매수 의견 비율('N건 중 M건' 또는 'M/N')·런레이트 배수 표기 없음 (같은 절)
  - 밸류에이션 숫자를 쓰는데 E/P−rf·20일 분해 언급 없음 (복기 10/16 '세 숫자')
  - 매수·편입·진입 권고 문구가 있는데 trade plan 언급 없음 (STANDARD §2)
  - 길이: 노트 150줄·라운드 파일(--round) 40줄 초과 (STANDARD §4)
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

DENOMS = {"TTM": r"TTM", "런레이트": r"런레이트|run[- ]?rate", "가이던스": r"가이던스", "정규화": r"정규화|정상화"}
PER_NUM = re.compile(r"PER\s*(?:TTM\s*)?\d")
DATE = re.compile(r"(기준|기준일)[^\n]{0,20}\d{4}-\d{2}-\d{2}|\d{4}-\d{2}-\d{2}[^\n]{0,6}KST")
CONFIRM = re.compile(r"\[확인 필요:([^\]]*)\]")
CONFIRM_DUE = re.compile(r"\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}")
SELL3 = {"말하는 것": r"말하는 것", "확인되는 것": r"확인되는 것|확인된 것", "확인 불가": r"확인 불가"}
BUY_RATIO = re.compile(r"\d+\s*건\s*중\s*\d+\s*건|\d+\s*/\s*\d+")
RECO = re.compile(r"(매수|편입|진입)\s*(권고|추천|제안|하자|하라)")


def check(text: str, sellside: bool | None = None, round_file: bool = False) -> tuple[list[str], list[str]]:
    fails, warns = [], []
    if not DATE.search(text):
        fails.append("기준일 없음 — 머리에 '기준 YYYY-MM-DD' (STANDARD §8)")
    for k in ("What", "So What", "Now What"):
        pat = r"(?<!So )(?<!Now )What" if k == "What" else k
        if not re.search(pat, text):
            fails.append(f"'{k}' 칸 없음 (STANDARD §8)")
    if PER_NUM.search(text):
        found = [k for k, p in DENOMS.items() if re.search(p, text, re.I)]
        if len(found) < 2:
            fails.append(f"PER 분모 {len(found)}개({','.join(found) or '없음'}) — TTM/런레이트/가이던스/정규화 중 2개 이상 범위로 (복기 10/17)")
        if not re.search(r"E/P|이익수익률", text):
            warns.append("E/P−rf 없음 — 의견엔 PER/PBR·E/P−rf·20일 분해 세 숫자, 없으면 제목에 (검증전) (복기 10/16)")
        if not re.search(r"20일|분해", text):
            warns.append("20일 분해(멀티플/EPS) 언급 없음 (복기 10/16)")
    for m in CONFIRM.finditer(text):
        if not CONFIRM_DUE.search(m.group(1)):
            fails.append(f"기한 없는 [확인 필요:{m.group(1)[:30]}] (STANDARD §1)")
    if sellside is None:
        sellside = bool(re.search(r"셀사이드", text))
    if sellside:
        for k, p in SELL3.items():
            if not re.search(p, text):
                fails.append(f"셀사이드 세 칸 중 '{k}' 없음 (kb:analyst#셀사이드)")
        if not BUY_RATIO.search(text):
            warns.append("매수 의견 비율('N건 중 M건') 없음 — 낙관 편향 표기 (kb:analyst#셀사이드)")
        if not re.search(r"런레이트|×4|배\b|배\)", text):
            warns.append("전망치를 현 런레이트(분기×4) 배수로 적지 않음 (kb:analyst#셀사이드)")
    if RECO.search(text) and not re.search(r"trade ?plan|tradeplan|매매 계획", text, re.I):
        warns.append("매수·편입·진입 권고 문구에 trade plan 없음 (STANDARD §2)")
    n = len(text.splitlines())
    cap = 40 if round_file else 150
    if n > cap:
        warns.append(f"{n}줄 > 상한 {cap} — 부록으로 (STANDARD §4)")
    return fails, warns


GOOD = """# 애널 — 셀사이드 X 정리 · 기준 2026-10-30 KST
- ① What: PER TTM 9.6 / 런레이트 5.0 / 정규화 16~23 · E/P−rf +6.7%p · 20일 분해 전부 배수
- ② So What: 매수 쏠림 11건 중 11건 · 전망 608조 = 런레이트 426조의 1.43배
- ③ Now What: 조치 없음 [확인 필요: 원문 PDF, 2026-11-01]
## 이 자료가 말하는 것
## 우리 산출물로 확인되는 것
## 확인 불가
"""
BAD = """# 애널 — 셀사이드 Y
- PER 11.7 이라 싸다. 매수 추천. [확인 필요: 원문]
"""


def selftest() -> int:
    f, w = check(GOOD)
    assert f == [] and w == [], (f, w)
    f, w = check(BAD)
    joined = " ".join(f)
    for s in ("기준일", "'What'", "PER 분모", "기한 없는", "말하는 것"):
        assert s in joined, (s, f)
    assert any("trade plan" in x for x in w), w
    f, _ = check(GOOD.replace("셀사이드 ", ""), sellside=False)
    assert f == [], f
    _, w = check(GOOD + "x\n" * 40, round_file=True)
    assert any("상한 40" in x for x in w), w
    print("selftest ok")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*")
    ap.add_argument("--sellside", action="store_true", help="셀사이드 세 칸 강제(기본: '셀사이드' 언급 시 자동)")
    ap.add_argument("--round", action="store_true", help="라운드 파일 길이 상한 40줄")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if not a.files:
        ap.error("파일을 주거나 --selftest")
    bad = 0
    for p in a.files:
        f, w = check(Path(p).read_text(encoding="utf-8"), True if a.sellside else None, a.round)
        print(f"{'FAIL' if f else 'ok  '} {p} — 실패 {len(f)} · 경고 {len(w)}")
        for x in f:
            print(f"  ✗ {x}")
        for x in w:
            print(f"  ! {x}")
        bad += bool(f)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
