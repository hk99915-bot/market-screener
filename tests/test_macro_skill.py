"""매크로 스킬 시범(.claude/skills/macro-desk, 2026-10-31) — 구조·KB 누락·flip_watch 계산 (네트워크 없음)."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SK = ROOT / ".claude" / "skills" / "macro-desk"
sys.path.insert(0, str(SK / "scripts"))
import flip_watch as fw  # noqa: E402


def test_skill_frontmatter_and_refs():
    t = (SK / "SKILL.md").read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", t, re.S)
    assert m, "frontmatter 없음"
    fm = dict(l.split(":", 1) for l in m.group(1).splitlines() if ":" in l)
    assert fm["name"].strip() == "macro-desk" and fm["description"].strip()
    assert len(t.splitlines()) <= 120
    for ref in re.findall(r"`references/([\w.]+)`", t):
        assert (SK / "references" / ref).exists(), ref


def test_references_cover_every_kb_line():
    """macro.md 본문 줄(절 제목 제외)이 references 어딘가에 같은 줄로 있어야 한다(옮기고 쪼개기만)."""
    kb = (ROOT / "docs" / "desk_kb" / "macro.md").read_text(encoding="utf-8").splitlines()
    refs = set()
    for f in (SK / "references").glob("*.md"):
        refs |= set(f.read_text(encoding="utf-8").splitlines())
    items = [l for l in kb if re.match(r"^(\d+\. |- )", l)]
    assert len(items) >= 34
    missing = [l[:40] for l in items if l not in refs]
    assert not missing, f"references 와 macro.md 가 갈라짐: {missing}"


def _series(vals, start=1):
    return [[f"2026-10-{i + start:02d}", v, v, v, v, 0] for i, v in enumerate(vals)]


def test_flip_watch_counts(tmp_path):
    t10 = [5.30] * 19 + [4.95, 4.89, 4.88]           # 22개, 끝 2일 4.90 아래
    spx = [100.0] * 21 + [95.0]
    dxy = [100.0] * 21 + [97.0]
    ksp = [100.0] * 21 + [80.0]
    (tmp_path / "macro_series.json").write_text(json.dumps({"asof": "x", "series": {
        "US10Y": _series(t10), "SPX": _series(spx), "DXY": _series(dxy), "KOSPI": _series(ksp)}}), encoding="utf-8")
    (tmp_path / "bonds.json").write_text(json.dumps({"asof": "x", "credit_us": {"r20": -0.035}, "us": {"curve": {
        "now": {"2Y": 4.40, "30Y": 5.40}, "m1": {"2Y": 4.60, "30Y": 5.30}}}}), encoding="utf-8")
    (tmp_path / "macro_view.json").write_text(json.dumps({"asof": "x", "glance": [{"line": "미2Y 4.40%(FF상단 4.00% +40bp)"}]}), encoding="utf-8")
    rows = {r["id"]: r for r in fw.evaluate(tmp_path)["rows"]}
    assert rows["F1"]["hit"] == "2/2"
    assert rows["F2"]["hit"] == "1/2"                 # HYG/IEF −3.5% 만, 10Y 4.88 < 5.25
    assert rows["F3"]["hit"] == "미충족"               # HYG/IEF −3% 도달이라 안전판 문장 불가
    assert rows["F4"]["hit"].startswith("3/4")        # 2s30s +30bp·DXY −3%·S&P 하락, 10Y 5.25 미만
    assert "2025-04형 2/3" in rows["F4"]["hit"]        # 10Y 20일 하락이라 장기물↑ 빠짐
    assert rows["F5"]["hit"].startswith("한국 고유")    # −20% − (−5%) = −15%p
    assert rows["F6"]["hit"] is None                  # commodities 없음 → 판정 불가, 예외 없음


def test_flip_watch_missing_inputs(tmp_path):
    res = fw.evaluate(tmp_path)
    assert len(res["rows"]) == 6 and all(r["hit"] is None and "데이터 없음" in r["value"] for r in res["rows"])
