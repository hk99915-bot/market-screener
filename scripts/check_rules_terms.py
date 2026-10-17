"""규칙 용어 린트 — 비율 한도를 계산하는 코드에 분모 라벨이 있는지 확인한다 (docs/rules_terms.md 의 코드 쪽 강제 장치).

배경(2026-10-16): "테마 합계 ≤ 전체 투자자산의 40%" 의 분모가 정의되지 않은 채 집행됐다. 같은 포지션이 분모에 따라
세 가지 비율로 읽혔다. 다음부터는 **한도와 비교하는 비율을 계산하는 줄** 근처에 `denominator=` (또는 `denominator:`)
라벨이 반드시 있어야 한다 — 라벨은 docs/rules_terms.md 의 분모 코드(D1~D5)를 가리킨다.

규칙 (단순하게, 깨지기 쉽지 않게):
  A. 분모 변수 정의 줄 (`nav = …`, `book = …`, `invest_total = …`, `total_assets = …`) 은 같은 줄 또는 바로 위 줄에 `denominator` 라벨.
  B. 한도 이름(…_cap/…_CAP/…_limit/…_LIMIT/THRESHOLD/BAND)과 분모 변수로 나누는 식(`/ nav` 등)이 **같은 줄**에 있으면,
     그 줄부터 위로 3줄 안에 `denominator` 라벨.
  검사 대상 파일은 FILES. 주석·문서 문자열은 라벨로 인정한다 (라벨은 사람이 읽는 것이 목적).

  python scripts/check_rules_terms.py            # 종료코드 0 = 통과, 1 = 라벨 누락
  python scripts/check_rules_terms.py --list     # 검사 대상과 규칙만 출력
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# 규칙 관련 코드 — 한도·비율을 계산하거나 알림으로 내보내는 파일만 (교육·연구 스크립트 제외)
FILES = ["screener/pb.py", "screener/alerts.py", "screener/briefings.py", "screener/rebound.py", "screener/ticket.py", "scripts/scorecard_week.py"]
LABEL = re.compile(r"denominator\s*[=:]", re.I)
DENOM_NAMES = r"(?:nav|NAV|tot|total|total_assets|book|sat_book\(\)|invest_total|h_total|E_end|equity)"
DENOM_DEF = re.compile(rf"^\s*(?:nav|NAV|book|invest_total|total_assets|h_total)\s*=[^=]")
DIV_BY_DENOM = re.compile(rf"/\s*{DENOM_NAMES}\b")
CAP_NAME = re.compile(r"\b\w*(?:_cap|_CAP|[a-z]cap|CAP|_limit|_LIMIT|limit|THRESHOLD|BAND|MIN_RR)\b")
WINDOW = 3


def scan_text(text: str, path: str = "<text>") -> list[str]:
    """라벨 누락 목록. 비어 있으면 통과."""
    lines = text.splitlines()
    out = []

    def labelled(i: int, back: int) -> bool:
        lo = max(0, i - back)
        return any(LABEL.search(lines[j]) for j in range(lo, i + 1))

    for i, ln in enumerate(lines):
        code = ln.split("#", 1)[0]
        if DENOM_DEF.match(code) and not labelled(i, 1):
            out.append(f"{path}:{i + 1}: 분모 정의에 denominator 라벨 없음 → {ln.strip()[:80]}")
        if DIV_BY_DENOM.search(code) and CAP_NAME.search(code) and not labelled(i, WINDOW):
            out.append(f"{path}:{i + 1}: 한도 비교 비율에 denominator 라벨 없음(위 {WINDOW}줄 안) → {ln.strip()[:80]}")
    return out


def scan_files(files: list[str] | None = None, root: Path = ROOT) -> list[str]:
    out = []
    for rel in files or FILES:
        p = root / rel
        if not p.exists():
            continue   # 파일이 없으면 통과 (이름이 바뀌면 FILES 를 고친다)
        out += scan_text(p.read_text(encoding="utf-8"), rel)
    return out


# ── 규칙 상수 단일 원천 (screener/defs.py, refactor_plan 결정 B 2026-10-17) ──
DEF_FILES = FILES + ["screener/committee.py"]
UI_CONSTS = {"apps-script/tab_my.html": ("SEMI_CAP", "SEMI_BAND", "ISA_BAND")}


def _defs():
    sys.path.insert(0, str(ROOT))
    from screener import defs   # noqa: E402
    return defs


def scan_defs(root: Path = ROOT, defs=None) -> list[str]:
    """① defs.TERMS 용어가 rules_terms.md 에 있는가 ② 규칙 파일이 같은 이름을 숫자로 재정의하지 않는가 ③ 화면 상수 = defs 값."""
    defs = defs or _defs()
    out = []
    doc = (root / "docs" / "rules_terms.md").read_text(encoding="utf-8")
    for name, term in defs.TERMS.items():
        if term not in doc:
            out.append(f"docs/rules_terms.md: defs.{name} 의 용어 '{term}' 가 용어표에 없음 (definition-first)")
    names = "|".join(sorted(defs.LOCAL_ALIASES, key=len, reverse=True))
    redef = re.compile(rf"^\s*(?:{names})\s*(?:,\s*\w+\s*)*=\s*[-\d.(]")
    dict_lit = re.compile(r"[\"'](?:loss_limit|semi_cap|semi_band)[\"']\s*:\s*-?\d")
    for rel in DEF_FILES:
        p = root / rel
        if not p.exists():
            continue
        for i, ln in enumerate(p.read_text(encoding="utf-8").splitlines()):
            code = ln.split("#", 1)[0]
            if redef.search(code) or dict_lit.search(code):
                out.append(f"{rel}:{i + 1}: 규칙 상수를 숫자로 재정의 — screener/defs.py 에서 import → {ln.strip()[:80]}")
    for rel, keys in UI_CONSTS.items():
        p = root / rel
        if not p.exists():
            continue
        txt = p.read_text(encoding="utf-8")
        for k in keys:
            m = re.search(rf"\b{k}\s*=\s*(-?[\d.]+)", txt)
            if m and abs(float(m.group(1)) - getattr(defs, k)) > 1e-12:
                out.append(f"{rel}: 화면 {k}={m.group(1)} ≠ screener/defs.py {getattr(defs, k)}")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args(argv)
    if a.list:
        print("files:", ", ".join(FILES))
        print("rule A:", DENOM_DEF.pattern)
        print("rule B:", DIV_BY_DENOM.pattern, "+", CAP_NAME.pattern, f"(window {WINDOW})")
        return 0
    probs = scan_files() + scan_defs()
    for p in probs:
        print("❌", p)
    if probs:
        print(f"\n{len(probs)}건 — 비율 한도 계산 줄에 `# denominator=<D1~D5> …` 라벨, 규칙 상수는 screener/defs.py 에서 (docs/rules_terms.md).")
        return 1
    print(f"✅ rules terms: {len(FILES)} files, denominator labels OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
