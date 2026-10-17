import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("node") is None, reason="node 없음")
def test_study_modules_render_in_browser_scope():
    r = subprocess.run(["node", "tests/js/study_smoke.js"], cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-800:]
    assert "rendered" in r.stdout and int(r.stdout.split()[-1]) > 50


def test_no_globalthis_access_to_toplevel_const():
    # Index.html 의 top-level const(esc 등)는 globalThis/window 속성이 아님 → 그렇게 읽으면 undefined 로 화면이 멈춘다
    bad = [p.name for p in (ROOT / "apps-script").glob("*.html")
           if any(k in p.read_text(encoding="utf-8") for k in ("globalThis.esc", "window.esc", "globalThis.num", "globalThis.pct"))]
    assert not bad, bad
