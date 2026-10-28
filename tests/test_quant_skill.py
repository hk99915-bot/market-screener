"""퀀트 스킬 시범(.claude/skills/quant-desk, 2026-10-28) — 구조·크기·KB 번호 누락·스크립트 동작 (네트워크 없음)."""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SK = ROOT / ".claude" / "skills" / "quant-desk"
sys.path.insert(0, str(SK / "scripts"))
import check_backtest as cb  # noqa: E402


def test_skill_frontmatter_and_size():
    t = (SK / "SKILL.md").read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", t, re.S)
    assert m, "frontmatter 없음"
    fm = dict(l.split(":", 1) for l in m.group(1).splitlines() if ":" in l)
    assert fm["name"].strip() == "quant-desk"
    assert fm["description"].strip()
    assert len(t.encode("utf-8")) <= 4096, "SKILL.md 본문 4KB 상한"
    for ref in re.findall(r"`references/([\w.]+)`", t):
        assert (SK / "references" / ref).exists(), ref


def test_references_cover_every_kb_item():
    """quant.md 의 #번호 항목이 references 어딘가에 같은 줄로 있어야 한다(옮기고 쪼개기만 — 누락·변형 탐지)."""
    kb = (ROOT / "docs" / "desk_kb" / "quant.md").read_text(encoding="utf-8").splitlines()
    refs = set()
    for f in (SK / "references").glob("*.md"):
        refs |= set(f.read_text(encoding="utf-8").splitlines())
    items = [l for l in kb if re.match(r"^- (#\d+|\*\*20\d\d-)", l)]
    assert len(items) >= 30
    missing = [l[:40] for l in items if l not in refs]
    assert not missing, f"references 와 quant.md 가 갈라짐: {missing}"


def test_check_backtest_flags(tmp_path):
    topics, manual = {"x": {"N": 20, "alpha_N": 0.0025}}, {"good": {"topic": "x"}}
    good = {"prereg": {"m": 4, "alpha_bonf": 0.0125, "is_end": "2023-12-31", "cost_oneway": 0.001},
            "grades": {"H1": "C", "H2": {"grade": "F"}}, "survivorship": "n/a", "dsr": 0.4}
    f, w, i = cb.check(good, "good", topics, manual)
    assert f == [] and w == [] and any("α(N)=0.0025" in x for x in i)
    f, _, _ = cb.check({"prereg": {"m": 4, "alpha_bonf": 0.05 / 3}, "grades": {"H1": "좋음"}}, "bad", topics, manual)
    assert any("α" in x for x in f) and any("형식" in x for x in f)
    f, _, _ = cb.check({"results": {}}, "none", topics, manual)
    assert len(f) == 3   # prereg·m·등급


def test_donothing_add_refuses_public_repo(tmp_path):
    p = ROOT / "docs" / "nope.csv"
    r = subprocess.run([sys.executable, str(SK / "scripts" / "donothing_add.py"), "--book", str(p), "--date", "2026-10-28",
                        "--mkt", "KR", "--key", "A", "--qty", "1", "--price", "1", "--source", "t"], capture_output=True, text=True)
    assert r.returncode == 2 and not p.exists()


def test_donothing_add_validates_and_appends(tmp_path):
    book = tmp_path / "donothing_book.csv"
    book.write_text("kind,date,mkt,key,qty,price,bucket,source\n# bucket: aa = 가 · bb = 나\n", encoding="utf-8")
    cmd = [sys.executable, str(SK / "scripts" / "donothing_add.py"), "--book", str(book), "--date", "2026-10-20",
           "--mkt", "US", "--key", "XYZ", "--qty", "-2", "--price", "10.5", "--bucket", "bb", "--source", "t"]
    assert subprocess.run(cmd, capture_output=True).returncode == 0
    assert "trade" not in book.read_text(encoding="utf-8")              # 기본은 검사만
    assert subprocess.run(cmd + ["--write"], capture_output=True).returncode == 0
    assert book.read_text(encoding="utf-8").splitlines()[-1] == "trade,2026-10-20,US,XYZ,-2,10.5,bb,t"
    assert subprocess.run(cmd + ["--write"], capture_output=True).returncode == 1   # 중복 거부
    bad = cmd[:-2] + ["--bucket", "zz", "--source", "t"]
    assert subprocess.run(bad, capture_output=True).returncode == 1
