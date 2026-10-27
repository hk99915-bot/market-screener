"""scripts/privacy_history_audit.py — 합성 문자열만 쓴다(실제 개인 수치 금지). 결과 미리보기에 값이 남지 않는지 본다."""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("privacy_history_audit", ROOT / "scripts" / "privacy_history_audit.py")
pa = importlib.util.module_from_spec(spec)
sys.modules["privacy_history_audit"] = pa   # dataclass 가 모듈을 찾는다
spec.loader.exec_module(pa)


def test_detects_and_masks_synthetic_personal_lines(tmp_path):
    pdir = tmp_path / "private"
    pdir.mkdir()
    (pdir / "holdings.txt").write_text("ZZZQ 7 12.5\n현금 31415926\n", encoding="utf-8")
    sc = pa.Scanner(pdir)
    lines = {
        "ctx": "예시: 이번 달 월 적립 271만 원으로 올림",
        "private": "잔액 31,415,926 기록",
        "holding": "ZZZQ 7주 그대로",
        "account": "급여 계좌 123-456-789012",
        "birth": "생년월일 1999.01.02",
        "email": "연락 someone" + "@" + "fakecorp.co.kr",
    }
    kinds = {k: {h.kind for h in sc.hits("tree", "docs/x.md", 1, t)} for k, t in lines.items()}
    assert "ctx_amount" in kinds["ctx"] or "amount" in kinds["ctx"]
    assert "private" in kinds["private"]
    assert "holding" in kinds["holding"]
    assert "account" in kinds["account"]
    assert "birth" in kinds["birth"]
    assert "email" in kinds["email"]
    for t in lines.values():
        for h in sc.hits("tree", "docs/x.md", 1, t):
            assert not any(c.isdigit() and c != "9" for c in h.preview)   # 숫자는 9로 가림
            assert "ZZZQ" not in h.preview and "fakecorp" not in h.preview


def test_false_positive_classes():
    sc = pa.Scanner()
    assert {h.category for h in sc.hits("tree", "docs/x.md", 1, "기준일 2026-10-27 계좌 점검")} == {"date"}
    assert all(h.category == "synthetic" for h in sc.hits("tree", "docs/x.md", 1, "예시: 보유 1,000만 원"))
    assert sc.hits("tree", "docs/x.md", 1, "비율만 적는다 — 보유 비중 12%") == []
