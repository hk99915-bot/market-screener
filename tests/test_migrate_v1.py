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


@pytest.mark.parametrize("path", [
    "reports/studies/2026-10-23_frm_replay_2026-07.md", "reports/studies/2026-10-28_frm_core_lookthrough.md",
    "docs/peer_reviews/2026-10-17_integrity_audit.md", "docs/peer_reviews/2026-10-17_legacy_book.md",
    "docs/peer_reviews/2026-10-17_recheck.md", "docs/valuation_notes/2026-10-17_cio_lab_review.md",
])
def test_audit_1101_personal_book_excluded(path):
    """감사 11/1 경계 검사: 개인 북·원장 분석 문서는 스냅샷 제외(내부판엔 남음)."""
    assert mv.classify(path)[0] == mv.PERSONAL
    assert mv.classify("docs/peer_reviews/2026-10-24_pick_gate.md")[0] == mv.PUBLIC


def test_allow_list_preview_pins_sentence():
    from privacy_history_audit import Hit
    old = Hit("snapshot", "a.json", 1, "amount", "내", category="review", preview='"note": "기간 끝(99/99) 금')
    new = Hit("snapshot", "a.json", 2, "amount", "내", category="review", preview='"note": "새 문장 999만')
    other = Hit("snapshot", "a.json", 3, "amount", "보유", category="review", preview='"note": "기간 끝(9')
    n = mv.apply_allow([old, new, other], [{"path": "a.json", "kind": "amount", "ctx": "내", "preview": '"note": "기간 끝('}])
    assert n == 1 and old.category == "allowed" and new.category == "review" and other.category == "review"


def test_default_allow_file_is_internal_and_valid():
    items = mv.load_allow(ROOT / mv.ALLOW_DEFAULT)
    assert items and all({"path", "kind", "why"} <= set(x) for x in items)
    assert mv.classify(mv.ALLOW_DEFAULT)[0] == mv.INTERNAL   # 감사 판정 목록은 범용판에 안 감
