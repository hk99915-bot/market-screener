"""scripts/check_rules_terms.py — 비율 한도 계산 줄의 denominator 라벨 린트 (저장소 실제 코드 + 합성 예시)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import check_rules_terms as crt  # noqa: E402


def test_repo_rules_code_has_denominator_labels():
    probs = crt.scan_files()
    assert probs == [], "\n".join(probs)


def test_missing_label_is_caught():
    bad = "nav = tot + cash\nif semi / nav > semi_cap:\n    pass\n"
    probs = crt.scan_text(bad, "x.py")
    assert len(probs) == 2
    assert "x.py:1" in probs[0] and "x.py:2" in probs[1]


def test_label_within_window_passes():
    ok = ("nav = tot + cash   # denominator=D2 전체 투자자산\n"
          "# denominator=D2\n"
          "x = 1\n"
          "if semi / nav > semi_cap:\n"
          "    pass\n")
    assert crt.scan_text(ok, "x.py") == []


def test_ratio_without_cap_is_not_flagged():
    # 한도와 비교하지 않는 단순 비율(표시용)은 라벨을 요구하지 않는다 — 린트가 과하게 깨지지 않도록
    assert crt.scan_text("share = r['v'] / nav * 100\n", "x.py") == []


def test_docs_mention_denominator_codes():
    doc = (ROOT / "docs" / "rules_terms.md").read_text(encoding="utf-8")
    for code in ("D1", "D2", "D3", "D4", "D5"):
        assert f"| {code} " in doc
    assert "denominator=" in doc
