import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _mod():
    spec = importlib.util.spec_from_file_location("bgb", ROOT / "scripts" / "build_gas_bundle.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_bundle_has_no_include_and_all_tabs():
    text = _mod().bundle()
    assert "<?!= include(" not in text
    for p in (ROOT / "apps-script").glob("tab_*.html"):   # 묶음은 템플릿으로 평가되므로 탭에 스크립틀릿 표식이 있으면 깨진다
        body = p.read_text(encoding="utf-8")
        assert "<?" not in body and "?>" not in body, p.name
    for p in (ROOT / "apps-script").glob("tab_*.html"):
        first = next(l for l in p.read_text(encoding="utf-8").splitlines() if l.strip())
        assert first in text, p.name


def test_bundle_committed_is_current():
    # 탭을 고치고 묶음을 다시 안 만들면 GAS 에 옛 화면이 붙여넣어진다
    assert (ROOT / "apps-script" / "dist" / "Index.html").read_text(encoding="utf-8") == _mod().bundle()
