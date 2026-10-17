"""docs/peer_reviews/*.md — 반대 의견서 양식 린트 (주장/근거/반증 가능 조건/채점 3항목, 원 금액 금지)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / "docs" / "peer_reviews"
SECTIONS = ("주장", "근거", "반증 가능 조건", "채점 3항목")
AMOUNT = re.compile(r"\d[\d,.]*\s*(만|억)(?!\s*(명|건|주|개|배|년|일|회|p))")  # 300만·1.2억 등 원화 금액


def _docs():
    return sorted(DIR.glob("*.md"))


def test_peer_reviews_exist():
    assert _docs(), "docs/peer_reviews/ 에 의견서가 없다"


def test_four_sections_present():
    for p in _docs():
        txt = p.read_text(encoding="utf-8")
        heads = [h.strip() for h in re.findall(r"^#{2,3}\s+(.+)$", txt, re.M)]
        for s in SECTIONS:
            assert any(s in h for h in heads), f"{p.name}: '## {s}' 절 없음"


def test_falsification_conditions_at_least_three():
    for p in _docs():
        txt = p.read_text(encoding="utf-8")
        sec = txt.split("반증 가능 조건", 1)[1].split("\n## ", 1)[0]
        assert len(re.findall(r"^- \*\*R\d", sec, re.M)) >= 3, f"{p.name}: 반증 조건 3개 미만"


def test_scoring_table_has_three_rows():
    for p in _docs():
        txt = p.read_text(encoding="utf-8")
        sec = txt.split("채점 3항목", 1)[1].split("\n## ", 1)[0]
        assert len(re.findall(r"^\| S\d \|", sec, re.M)) == 3, f"{p.name}: 채점 행이 3개가 아님"


def test_no_won_amounts():
    for p in _docs():
        hit = AMOUNT.search(p.read_text(encoding="utf-8"))
        assert hit is None, f"{p.name}: 원화 금액 금지 — '{hit.group(0)}'"


def test_amount_regex_catches_examples():
    assert AMOUNT.search("한도 300만으로 축소")
    assert AMOUNT.search("약 1.2억원")
    assert not AMOUNT.search("25% · 5종목 · −15%")
