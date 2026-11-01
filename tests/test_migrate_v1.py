"""리팩토링 v1 이전 스크립트 분류 규칙 — 인벤토리 §1·§3·§3-1 의 대표 경로가 맞는 판으로 가는지 (dry-run 만, 쓰기 없음)."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import migrate_v1 as mv  # noqa: E402


@pytest.mark.parametrize("path,ed", [
    ("docs/desk_kb/rounds/_requests.json", mv.PERSONAL), ("reports/msgr_feed.md", mv.PERSONAL),
    ("reports/audit/x.md", mv.PERSONAL), ("docs/desk_kb/OKR.md", mv.PERSONAL), ("reports/logs/pdf_boxes.json", mv.PERSONAL),
    ("ops/cooldown.json", mv.PERSONAL), ("ops/renego.json", mv.PERSONAL), ("reports/decisions.json", mv.PERSONAL),
    ("reports/battle_scoreboard.json", mv.PERSONAL), ("assets/avatars/a.png", mv.PERSONAL), ("docs/desk_kb/CHARACTERS.md", mv.PERSONAL),
    ("docs/desk_kb/dev.md", mv.INTERNAL), ("docs/desk_kb/STANDARD.md", mv.PUBLIC), ("content/study.json", mv.INTERNAL),
    ("ops/board.json", mv.INTERNAL), ("ops/freshness.json", mv.PUBLIC), ("CLAUDE.md", mv.INTERNAL), (".claude/skills/a/SKILL.md", mv.INTERNAL),
    ("reports/committee.json", mv.INTERNAL), ("reports/archive/committee/2026-10-30.json", mv.INTERNAL),
    ("reports/archive/dotplot/2026-10-30.json", mv.PUBLIC), ("docs/refactor_v1_inventory.md", mv.INTERNAL),
    (".github/workflows/pick.yml", mv.INTERNAL), (".github/workflows/live.yml", mv.PUBLIC), (".github/workflows/laor_ib_data.yml", mv.ARCHIVE),
    ("screener/report.py", mv.PUBLIC), ("reports/detail/KR/005930.json", mv.PUBLIC), ("docs/valuation_notes/a.md", mv.PUBLIC),
    ("tests/test_study_content.py", mv.INTERNAL), ("tests/test_alerts_off.py", mv.PUBLIC), ("apps-script/tab_my.html", mv.PUBLIC),
])
def test_classify(path, ed):
    assert mv.classify(path)[0] == ed


def test_secret_file_pattern():
    for p in (".env", "tools/toss_md/env", "token.json", "a/key.pem", "x/credentials_sa.json"):
        assert mv.SECRET_FILE_RX.search(p), p
    assert not mv.SECRET_FILE_RX.search("docs/environment.md")


def test_plan_has_no_forbidden_and_public_index():
    pl = mv.make_plan("HEAD")
    assert mv.check_forbidden(pl) == []
    blobs: dict = {}
    mv.swap_public_index(pl, blobs)
    assert pl.files["index.html"][1] == mv.PUBLIC_INDEX and b"edition: public" in blobs[mv.PUBLIC_INDEX]


def test_apply_requires_dest_and_outside_repo(tmp_path):
    assert mv.main(["--apply"]) == 2
    assert mv.main(["--apply", "--dest", str(ROOT / "x_tmp_dest")]) == 2
