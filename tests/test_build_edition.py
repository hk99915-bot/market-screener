"""범용판 빌드(scripts/build_edition.py public) — 리팩토링 v1 '내부 탭 9개 숨김 · 11/7 전 필수' (docs/refactor_v1_inventory.md §6).
internal 은 지금 index.html 과 바이트 동일, public 은 내부 탭 파일 6개 include 제외 + 메뉴·주소·setView 차단."""
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_edition as be  # noqa: E402
import build_pages as bp  # noqa: E402

INTERNAL_TABS = {"my", "life", "isalab", "msgr", "duel", "study", "committee", "rboard", "system"}


def test_internal_is_byte_identical():
    assert be.build_edition("internal") == bp.build(bp.screen_source())


def test_nine_internal_tabs_covered():
    dropped = {k.removeprefix("tab_") for k in be.PUBLIC_DROP_TABS}
    kept = {k.removeprefix("tab_") for k in be.PUBLIC_KEEP_HIDDEN_TABS}
    assert dropped | kept == INTERNAL_TABS and not dropped & kept


def test_public_drops_internal_sources_and_injects_prune():
    out = be.build_edition("public")
    assert "<!-- edition: public (범용판) -->" in out and "window.MS_EDITION='public'" in out
    for name in be.PUBLIC_DROP_TABS:   # 버린 탭의 고유 함수가 남지 않음
        assert f"범용판: {name} 제외" in out
    assert "function mgOrg(" not in out and "function rbOwnerTodo(" not in out and "function sysBoardView(" not in out
    for v in be.PUBLIC_HIDE_VIEWS:
        assert f"'{v}'" in out
    assert out.index(be.GROUPS_ANCHOR) < out.index("window.MS_EDITION")


def test_unknown_edition_rejected():
    with pytest.raises(ValueError):
        be.build_edition("friends")


def test_default_edition_reads_marker(monkeypatch, tmp_path):
    monkeypatch.delenv("MS_EDITION", raising=False)
    monkeypatch.setattr(be, "ROOT", tmp_path)
    assert be.default_edition() == "internal"
    (tmp_path / ".edition").write_text("public\n")
    assert be.default_edition() == "public"
    monkeypatch.setenv("MS_EDITION", "internal")
    assert be.default_edition() == "internal"


def test_cli_refuses_other_edition_on_root(tmp_path, monkeypatch):
    monkeypatch.delenv("MS_EDITION", raising=False)
    if be.default_edition() != "internal":
        pytest.skip("범용판 저장소")
    assert be.main(["--edition", "public"]) == 2
    out = tmp_path / "x" / "index.html"
    assert be.main(["--edition", "public", "--out", str(out)]) == 0 and out.read_text().startswith("<!doctype html>")


@pytest.mark.skipif(not shutil.which("node"), reason="node 없음")
def test_public_scripts_parse(tmp_path):
    out = be.build_edition("public")
    (tmp_path / "i.html").write_text(out, encoding="utf-8")
    js = ("const fs=require('fs');const h=fs.readFileSync(process.argv[1],'utf8');let bad=0;"
          "for(const m of h.matchAll(/<script>([\\s\\S]*?)<\\/script>/g)){try{new Function(m[1]);}catch(e){bad++;console.log(e.message);}}"
          "process.exit(bad?1:0);")
    r = subprocess.run(["node", "-e", js, str(tmp_path / "i.html")], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout[:400]
