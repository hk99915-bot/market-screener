"""글자 크기 4단계 규칙(UXUI Top10 #10, 10/24 결재 appr-uxui-top10-next): 화면 HTML 은 --fs-1~4·--fs-icon 토큰만 — 픽셀 직접 쓰기 0."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("font_tokens", ROOT / "scripts" / "font_tokens.py")
ft = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ft)


def test_no_raw_px_font_size():
    bad = [(p.name, i, t) for p in ft.FILES for i, t in ft.scan(p)]
    assert not bad, f"글자 크기 픽셀 직접 쓰기 {len(bad)}곳(예: {bad[:3]}) — python3 scripts/font_tokens.py --fix"


def test_tokens_defined_once_in_root():
    s = (ROOT / "apps-script" / "Index.html").read_text(encoding="utf-8")
    root = s[s.index(":root{"):s.index("}", s.index(":root{"))]
    for k, v in ft.STEPS.items():
        assert f"{k}:{v:g}px" in root, k
    assert "--fs-icon:" in root


def test_nearest_step_mapping():
    assert ft.token(10) == "--fs-1" and ft.token(11.5) == "--fs-1"
    assert ft.token(12) == "--fs-2" and ft.token(13) == "--fs-2" and ft.token(14) == "--fs-2"
    assert ft.token(15) == "--fs-3" and ft.token(16) == "--fs-3"
    assert ft.token(16.5) == "--fs-4" and ft.token(18) == "--fs-4"
    assert ft.token(24) == "--fs-icon"


def test_fix_rewrites(tmp_path):
    p = tmp_path / "x.html"
    p.write_text('<b style="font-size:10.5px">a</b><style>body{font:12.5px/1.4 x}</style>', encoding="utf-8")
    assert ft.fix(p) == 2
    t = p.read_text(encoding="utf-8")
    assert "font-size:var(--fs-1)" in t and "font:var(--fs-2)/1.4" in t and not ft.scan(p)
