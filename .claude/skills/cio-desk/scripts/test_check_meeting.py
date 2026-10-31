"""CIO 스킬 시범(.claude/skills/cio-desk, 2026-10-31) — 구조·KB 누락·검사 스크립트 동작 (네트워크 없음).
실행: python3 -m pytest .claude/skills/cio-desk/scripts/test_check_meeting.py  (testpaths=tests 밖이라 직접 지정)"""
import re
import sys
from pathlib import Path

SK = Path(__file__).resolve().parents[1]
ROOT = SK.parents[2]
sys.path.insert(0, str(SK / "scripts"))
import check_meeting as cm  # noqa: E402


def test_skill_frontmatter_and_refs():
    t = (SK / "SKILL.md").read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", t, re.S)
    assert m
    fm = dict(l.split(":", 1) for l in m.group(1).splitlines() if ":" in l)
    assert fm["name"].strip() == "cio-desk" and fm["description"].strip()
    assert len(t.splitlines()) <= 125
    for ref in re.findall(r"`references/([\w.]+)`", t):
        assert (SK / "references" / ref).exists(), ref


def test_references_cover_every_kb_item():
    kb = (ROOT / "docs" / "desk_kb" / "cio.md").read_text(encoding="utf-8").splitlines()
    refs = set()
    for f in (SK / "references").glob("*.md"):
        refs |= set(f.read_text(encoding="utf-8").splitlines())
    items = [l for l in kb if re.match(r"^(\d+\. |- )", l)]
    assert len(items) >= 30
    assert not [l[:40] for l in items if l not in refs]


GOOD = """# 운용회의
기준 2026-10-30 08:50 KST
- What: 코스피 −1.25%
- So What: 반등 미성립 · 반대 근거: 표본 9
- Now What: 관망 · 급락일 종가 진입 후보(C) · 채택안 ΔS +0.1%p
- 20일선 6,102(10/29 창) vs 6,148(10/28 창) 불일치 아님
원본: rounds/x.md
"""


def test_good_passes():
    f, w = cm.check(GOOD)
    assert f == [] and w == []


def test_flags():
    bad = "# x\n- So What: a\n- 외국인 2일 순매수 확인 후 진입\n- 두 값 불일치\n- 결재 수량 선형 환산 −15.1%\n- 채택\n"
    f, w = cm.check(bad)
    assert any("'What'" in x for x in f) and any("'Now What'" in x for x in f)
    assert any("기준 시각" in x for x in f) and any("kb:cio#18" in x for x in f)
    assert any("불일치" in x for x in w) and any("환산" in x for x in w)
    assert any("ΔS" in x for x in w) and any("반대" in x for x in w) and any("원본" in x for x in w)
    f, _ = cm.check(GOOD + "- 외국인 2일 순매수는 tell(관측)로만 (F)\n")
    assert f == []


def test_cli_exit_codes(tmp_path):
    g, b = tmp_path / "g.md", tmp_path / "b.md"
    g.write_text(GOOD, encoding="utf-8")
    b.write_text("없음", encoding="utf-8")
    assert cm.main([str(g)]) == 0
    assert cm.main([str(b)]) == 1
    assert cm.main([str(tmp_path / "none.md")]) == 1
