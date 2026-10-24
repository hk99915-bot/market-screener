"""엑셀 스킨(html.xl) 대비 재발 방지(10/24 req-dev-0d1eee58, 겸이 "엑셀버전 톡방이 검정색"):
화면 파일에 다크 전용 배경(#111·#151515·#0a0a0a 류)과 '강조 배경 위 검정 글자'를 직접 쓰지 않고 토큰(--bg2·--bg3·--panel·--on-amber)을 쓴다.
xl 이 토큰만 밝게 바꾸므로 하드코딩이 남으면 엑셀 스킨에서 검정 바탕에 검정 글자가 된다. 브라우저 전수 측정은 scripts/skin_audit.py · ui_smoke check_xl."""
import re
from pathlib import Path

import pytest

APPS = Path(__file__).resolve().parents[1] / "apps-script"
DARK_BG = re.compile(r"background(?:-color)?:\s*(?:#111(?:111)?|#1[456]1[456]1[456]|#1a1a1a|#0[9abcd]0[9abcd]0[9abcd])(?![0-9a-fA-F])")
BLACK_ON_AMBER = re.compile(r"background:var\(--amber\);\s*color:#000(?![0-9a-fA-F])|color:#000;\s*background:var\(--amber\)")
FILES = sorted(APPS.glob("*.html"))


@pytest.mark.parametrize("f", FILES, ids=lambda f: f.name)
def test_no_dark_only_hardcoded_background(f):
    s = f.read_text(encoding="utf-8")
    bad = [(s.count("\n", 0, m.start()) + 1, m.group(0)) for r in (DARK_BG, BLACK_ON_AMBER) for m in r.finditer(s)]
    assert not bad, f"{f.name}: 토큰(var(--bg2)/--bg3/--panel, 글자 var(--on-amber))으로 — {bad[:5]}"


def test_tokens_defined_for_both_skins():
    s = (APPS / "Index.html").read_text(encoding="utf-8")
    root = s[s.index(":root{"): s.index("}", s.index(":root{"))]
    xl = s[s.index("html.xl{"): s.index("}", s.index("html.xl{"))]
    for t in ("--bg2", "--bg3", "--on-amber", "--panel", "--txt"):
        assert t + ":" in root and t + ":" in xl, t
