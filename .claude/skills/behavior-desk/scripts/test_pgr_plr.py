"""행동 스킬 PGR/PLR 집계 — kb:behavior#2·#11 규칙 재현 + 스킬 구조·KB 번호 누락 (네트워크 없음).
실행: python3 -m pytest .claude/skills/behavior-desk/scripts/test_pgr_plr.py
숫자는 가상값(드릴 behavior-d1 과 다른 숫자 — 채점 키 노출 방지)."""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SK = HERE.parent
ROOT = SK.parents[2]
sys.path.insert(0, str(HERE))
import pgr_plr as pp  # noqa: E402


def row(m, a, b, c, d, **kw):
    return {"month": m, "gain_real": a, "gain_hold": b, "loss_real": c, "loss_hold": d, **kw}


def test_odean_table1_ratio_not_suspect_by_formula():
    # Odean 1998 Table I 연간 전체 14.8% vs 9.8% → 비율 1.51 (≥1.5 경계). 건수로 재현: 148/1000, 98/1000
    j = pp.judge(row("x", 148, 852, 98, 902))
    assert round(j["pgr"], 3) == 0.148 and round(j["plr"], 3) == 0.098
    assert j["verdict"].startswith("처분효과 의심") and "검증전" not in j["verdict"]


def test_threshold_and_small_n():
    j = pp.judge(row("2026-11", 3, 7, 2, 8))          # 30% vs 20% → 1.5 (경계 포함)
    assert j["verdict"].startswith("처분효과 의심") and "검증전(n 20" not in j["verdict"]
    j = pp.judge(row("2026-11", 2, 8, 2, 8))          # 1.0
    assert j["verdict"].startswith("의심 아님")
    j = pp.judge(row("2026-11", 2, 3, 0, 4))          # n 9 <20
    assert "검증전" in j["verdict"] and "PLR 0" in j["verdict"]
    assert pp.judge(row("m", 0, 0, 1, 1))["verdict"].startswith("판정 불가")


def test_month_under_10_rolls_into_quarter():
    rows = [row("2026-10", 1, 2, 1, 3, rule_sell=1), row("2026-11", 4, 4, 2, 6, rule_sell=2)]
    t = pp.table(rows)
    assert "분기 합산" in t[0]["verdict"] and not "분기 합산" in t[1]["verdict"]
    q = t[-1]
    assert q["month"] == "2026-Q4(합산)" and q["n"] == 23 and q["rule_sell"] == 3
    out = pp.render(t)
    assert out.splitlines()[0].count("|") == 11 and "2026-Q4(합산)" in out


def test_csv_rejects_amount_columns(tmp_path, capsys):
    p = tmp_path / "c.csv"
    p.write_text("month,gain_real,gain_hold,loss_real,loss_hold,amount\n2026-11,1,1,1,1,5\n", encoding="utf-8")
    assert pp.main(["--csv", str(p)]) == 2
    p.write_text("month,gain_real,gain_hold,loss_real,loss_hold\n2026-11,5,5,2,8\n", encoding="utf-8")
    assert pp.main(["--csv", str(p)]) == 0
    assert "50.0%" in capsys.readouterr().out


def test_skill_frontmatter_refs_and_kb_coverage():
    t = (SK / "SKILL.md").read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", t, re.S)
    assert m and "name: behavior-desk" in m.group(1) and "description:" in m.group(1)
    assert len(t.splitlines()) <= 120
    for ref in re.findall(r"`references/([\w.]+)`", t):
        assert (SK / "references" / ref).exists(), ref
    refs = set()
    for f in (SK / "references").glob("*.md"):
        refs |= set(f.read_text(encoding="utf-8").splitlines())
    kb = (ROOT / "docs" / "desk_kb" / "behavior.md").read_text(encoding="utf-8").splitlines()
    items = [l for l in kb if re.match(r"^(\d+\. |- 20\d\d-)", l)]
    assert len(items) >= 34
    missing = [l[:40] for l in items if l not in refs]
    assert not missing, f"references 와 behavior.md 가 갈라짐: {missing}"
