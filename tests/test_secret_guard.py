"""시크릿 가드(scripts/secret_guard.py, pre-commit) — 토큰·계좌번호 모양·개인 금액.
테스트 문자열의 토큰·계좌·금액은 조각으로 이어 붙인다(이 파일이 가드·pre-push 금액 검사에 걸리지 않게)."""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("secret_guard", ROOT / "scripts" / "secret_guard.py")
sg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sg)

GHP = "gh" + "p_" + "Xy7" * 12
ACCT = "110" + "-" + "234" + "-" + "567890"
TG = "1234" + "56789" + ":" + "A" * 35
AMT = "연봉 " + "5" + ",000" + "만원 기준"


def test_selftest():
    assert sg.selftest() == 0


def test_blocks_tokens_without_echoing_value():
    hits = sg.scan({"a.py": [(3, f'T = "{GHP}"'), (4, f"bot = '{TG}'")]})
    assert len(hits) == 2 and "a.py:3" in hits[0]
    assert not any(GHP in h or TG in h for h in hits)


def test_account_shape_vs_dates_phones():
    assert sg.scan({"n.md": [(1, f"입금 {ACCT}")]})
    assert not sg.scan({"n.md": [(1, "2026-11-06 · 0000-00-00 · 02-123-4567 · 010-1234-5678 · v1.2.3")]})
    assert not sg.scan({"n.md": [(1, f"예시 {ACCT}  # secret-guard: allow")]})


def test_moved_lines_not_new():
    assert not sg.scan({"r.md": [(9, f"x {ACCT}")]}, {"r.md": [f"x {ACCT}"]})


def test_public_runs_personal_amount():
    assert not sg.scan({"d.md": [(1, AMT)]}, public=False)
    hits = sg.scan({"d.md": [(1, AMT)]}, public=True)
    assert hits and "값 생략" in hits[0]
    assert not sg.scan({"d.md": [(1, "보유 비중 12.5%")]}, public=True)
