"""채권 스킬 곡선 라벨 — 10/31 라운드 표(rounds/2026-10-31/bonds_curve.md)를 재현하는지 (네트워크 없음).
실행: python3 -m pytest .claude/skills/bonds-desk/scripts/test_curve_label.py"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import curve_label as cl  # noqa: E402


def test_round_table_cases():
    assert cl.classify(-3, 7) == "트위스트 스티프"          # 10/28 d1 2s30s +10
    assert cl.classify(-3, 6) == "판정 보류(10bp 미만)"     # 10/28 d1 2s10s +9
    assert cl.classify(-28, -27) == "불 평행"               # m1
    assert cl.classify(102, 71) == "베어 플래트닝"          # y1 2s30s
    assert cl.classify(-4, 3) == "판정 보류(10bp 미만)"     # w1
    assert cl.classify(5, 20) == "베어 스티프닝"
    assert cl.classify(-30, -5) == "불 스티프닝"
    assert cl.classify(-5, -30) == "불 플래트닝"
    assert cl.classify(None, 3).startswith("미확인")


def test_rows_regime_and_stale(tmp_path, capsys):
    o = {"us": {"chg": {"2Y": {"date": "2026-10-29", "d1": -6, "m1": -28}, "10Y": {"date": "2026-10-29", "d1": -7, "m1": -28},
                        "30Y": {"date": "2026-10-28", "m1": -27}}}, "kr": {"chg": {}}}
    rs = cl.rows(o, "us")
    assert cl.regime(rs, "us")["label"] == "불 평행"
    assert all(r["label"].startswith("미확인") for r in rs if r["pair"] == "2Y-30Y")
    p = tmp_path / "b.json"
    p.write_text(json.dumps(o), encoding="utf-8")
    assert cl.main(["--json", str(p)]) == 0
    out = capsys.readouterr().out
    assert "[m1] 2Y-10Y" in out and "국면(m1, 2Y-10Y): 불 평행" in out and "국고 — 데이터 없음" in out
    assert cl.main(["--json", str(tmp_path / "none.json")]) == 1
