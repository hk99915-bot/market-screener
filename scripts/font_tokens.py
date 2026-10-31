"""글자 크기 4단계 규칙 검사·고치기 (UXUI 재진단 Top10 #10 '글자 4단계 규칙', 10/24 결재 appr-uxui-top10-next).

화면(apps-script/*.html)의 글자 크기는 apps-script/Index.html :root 토큰만 쓴다:
  --fs-1 11px  보조(시각·단위·주석·태그)     --fs-2 13px   본문·표
  --fs-3 16px  강조·소제목                    --fs-4 17px   제목·큰 숫자 (2단계에서 히어로 28px)
  (10/31 UXUI 블룸버그식 재설계 §7 1단계: 12.5→13 · 14→16)
  --fs-icon 24px  아이콘(글자 아님: 💬 ✕ › ＋ 등)
`font-size:11px`·`font:12.5px/…` 같은 픽셀 직접 쓰기는 금지 — 새로 쓰면 tests/test_font_tokens.py 가 빨강.

  python3 scripts/font_tokens.py           # 검사 (위반 목록, 있으면 종료코드 1)
  python3 scripts/font_tokens.py --fix     # 가장 가까운 단계로 바꿔 씀 (≥20px 은 아이콘 — 글자라면 고친 뒤 손으로 --fs-4)

캔버스 차트(lightweight-charts layout.fontSize)·SVG 속성(font-size="10")은 CSS 가 아니라 대상 밖.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = sorted((ROOT / "apps-script").glob("*.html"))
STEPS = {"--fs-1": 11.0, "--fs-2": 13.0, "--fs-3": 16.0, "--fs-4": 17.0}
ICON_MIN = 20.0
PAT = re.compile(r"(font-size\s*:\s*|font\s*:\s*)(\d+(?:\.\d+)?)px")
DYN = re.compile(r"font-size\s*:\s*\$\{[^}]*\}px")   # 템플릿 계산 픽셀(자동 고치기 불가 — 손으로 토큰 고르기)


def token(px: float) -> str:
    if px >= ICON_MIN:
        return "--fs-icon"
    # 가장 가까운 단계 — 같은 거리면 큰 쪽(읽기 쉬운 쪽)
    return min(STEPS, key=lambda k: (abs(STEPS[k] - px), -STEPS[k]))


def scan(path: Path) -> list[tuple[int, str]]:
    out = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        for m in PAT.finditer(line):
            out.append((i, m.group(0)))
        for m in DYN.finditer(line):
            out.append((i, m.group(0)))
    return out


def fix(path: Path) -> int:
    s = path.read_text(encoding="utf-8")
    n = 0

    def rep(m: re.Match) -> str:
        nonlocal n
        n += 1
        return f"{m.group(1)}var({token(float(m.group(2)))})"
    t = PAT.sub(rep, s)
    if t != s:
        path.write_text(t, encoding="utf-8")
    return n


def main(argv: list[str]) -> int:
    if "--fix" in argv:
        tot = 0
        for p in FILES:
            n = fix(p)
            if n:
                print(f"{p.relative_to(ROOT)}: {n}곳")
            tot += n
        print(f"바꿈 {tot}곳")
        return 0
    bad = [(p, i, t) for p in FILES for i, t in scan(p)]
    for p, i, t in bad[:50]:
        m = PAT.search(t)
        print(f"{p.relative_to(ROOT)}:{i}: {t} → " + (f"var({token(float(m.group(2)))})" if m else "손으로 var(--fs-N)"))
    if bad:
        print(f"✗ 글자 크기 픽셀 직접 쓰기 {len(bad)}곳 — 토큰(--fs-1~4)만. 고치기: python3 scripts/font_tokens.py --fix")
        return 1
    print("✓ 글자 크기 4단계 토큰만 사용")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
