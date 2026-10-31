"""리스크(FRM) 스킬 시범(.claude/skills/frm-desk, 2026-10-31) — 구조·KB 번호 누락·var_backtest 동작 (네트워크 없음).

  python3 -m pytest .claude/skills/frm-desk/scripts/test_var_backtest.py
"""
import random
import re
import sys
from pathlib import Path

SK = Path(__file__).resolve().parents[1]
ROOT = SK.parents[2]
sys.path.insert(0, str(SK / "scripts"))
import var_backtest as vb  # noqa: E402


def test_skill_frontmatter_and_refs():
    t = (SK / "SKILL.md").read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", t, re.S)
    assert m, "frontmatter 없음"
    fm = dict(l.split(":", 1) for l in m.group(1).splitlines() if ":" in l)
    assert fm["name"].strip() == "frm-desk"
    assert fm["description"].strip()
    assert len(t.splitlines()) <= 120
    for ref in re.findall(r"`references/([\w.]+)`", t):
        assert (SK / "references" / ref).exists(), ref


def test_references_cover_every_kb_item():
    """frm.md 의 #번호 항목·복기 제목이 references 어딘가에 같은 줄로 있어야 한다(옮기고 쪼개기만)."""
    kb = (ROOT / "docs" / "desk_kb" / "frm.md").read_text(encoding="utf-8").splitlines()
    refs = set()
    for f in (SK / "references").glob("*.md"):
        refs |= set(f.read_text(encoding="utf-8").splitlines())
    must = [l for l in kb if re.match(r"^- (#\d+ |\*\*#\d )", l)]
    assert len(must) >= 29
    missing = [l[:40] for l in must if l not in refs]
    assert not missing, missing


def test_constants_and_light():
    assert vb.Z99 == 2.326 and vb.K_ES975 == 2.338
    assert vb.traffic_light(4).startswith("녹")
    assert vb.traffic_light(5).startswith("황") and vb.traffic_light(9).startswith("황")
    assert vb.traffic_light(10).startswith("적")
    assert "과대" in vb.traffic_light(0)


def test_stress_and_recovery_match_kb():
    assert round(vb.stress_cap(15, 50), 1) == 30.0      # #10 반도체 −50 → ≤30%
    assert round(vb.stress_cap(15, 37.5), 1) == 40.0    # #10 비중 40% → 허용 충격 −37.5%
    assert round(vb.recovery_needed(20), 1) == 25.0     # #1
    assert round(vb.recovery_needed(50), 1) == 100.0


def test_hist_var_es_on_known_series():
    r = [-(i + 1) / 1000 for i in range(250)]  # 손실 0.1%~25%
    v, e, n = vb.hist_var_es(r)
    assert n == 250
    assert abs(v - 0.248) < 1e-9                        # 1% 분위 = 최악 3번째(ceil 2.5)
    assert abs(e - sum([0.250, 0.249, 0.248, 0.247, 0.246, 0.245]) / 6) < 1e-9  # 최악 6일 평균


def test_backtest_counts_normal_near_expected():
    random.seed(7)
    r = [random.gauss(0, 0.01) for _ in range(310)]
    b = vb.backtest(r, 60, 250)
    assert b["n"] == 250 and b["expected"] == 2.5
    assert 0 <= b["exc"] <= 9
    r2 = r[:-10] + [-0.2] * 10                           # 끝 10일 급락 → 적
    assert vb.backtest(r2, 60, 250)["exc"] >= 10


def test_cli_csv(tmp_path):
    random.seed(1)
    p = tmp_path / "r.csv"
    p.write_text("date,ret\n" + "\n".join(f"d{i},{random.gauss(0, 1):.4f}" for i in range(300)), encoding="utf-8")
    assert vb.main(["--csv", str(p), "--pct"]) == 0
    assert vb.main(["--stress", "--shock", "50"]) == 0
