"""GAS 붙여넣기 묶음 — Index.html 의 include(tab_*) 를 미리 풀어 apps-script/dist/Index.html 한 파일로 만든다.
붙여넣기 대상이 17개(Code.gs·Scheduler.gs·Index·tab_* 14개) → 3개(Code.gs·Scheduler.gs·dist/Index.html)로 준다.
GAS 결과는 같다: Code.gs doGet 이 템플릿으로 평가하므로 include 가 이미 풀려 있어도 그대로 출력된다.
사용: python3 scripts/build_gas_bundle.py [--check]  (--check: 묶음이 최신인지만 확인, 다르면 종료코드 1)"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from build_pages import resolve_includes  # noqa: E402

SRC = ROOT / "apps-script" / "Index.html"
OUT = ROOT / "apps-script" / "dist" / "Index.html"
HEAD = "<!-- 자동 생성: scripts/build_gas_bundle.py — 직접 고치지 말 것. 원본은 apps-script/Index.html + tab_*.html -->\n"


def bundle() -> str:
    return HEAD + resolve_includes(SRC.read_text(encoding="utf-8"))


def main(argv: list[str]) -> int:
    text = bundle()
    if "--check" in argv:
        ok = OUT.exists() and OUT.read_text(encoding="utf-8") == text
        print("GAS 묶음 최신" if ok else "GAS 묶음 낡음 → python3 scripts/build_gas_bundle.py")
        return 0 if ok else 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    print(f"{OUT.relative_to(ROOT)} ({len(text.splitlines())}줄)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
