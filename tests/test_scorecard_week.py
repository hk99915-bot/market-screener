"""scripts/scorecard_week.py — 주간 집계 순수 로직 (네트워크·파일 없이)."""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import scorecard_week as sw  # noqa: E402


def _item(d, picks, result, market="KR"):
    return {"id": f"{d}-x", "date": d, "market": market, "picks": picks, "result": result}


def test_week_bounds_iso():
    assert sw.week_bounds(date(2026, 10, 16)) == (date(2026, 10, 12), date(2026, 10, 18))
    assert sw.week_bounds(date(2026, 10, 18)) == (date(2026, 10, 12), date(2026, 10, 18))   # 일요일은 그 주의 끝
    assert sw.week_bounds(date(2026, 10, 19))[0] == date(2026, 10, 19)


def test_duel_record_splits_bold_by_basis_and_skips_void():
    items = [
        _item("2026-10-13", {"나": {"ticker": "A", "notional": 1e6}, "PB": {"cash": True},
                             "나🔥": {"ticker": "B", "notional": 1e6, "why": "감", "basis": "감"}},
              {"나": {"ret": 0.02, "pnl": 20000}, "PB": {"ret": 0.0, "pnl": 0}, "나🔥": {"ret": -0.05, "pnl": -50000}, "winner": "나"}),
        _item("2026-10-14", {"나": {"ticker": "A", "notional": 1e6}, "PB": {"ticker": "C", "notional": 1e6},
                             "나🔥": {"ticker": "B", "notional": 1e6, "why": "근거 있음", "basis": "판단"}, "규칙": {"cash": True}},
              {"나": {"ret": -0.01, "pnl": -10000}, "PB": {"ret": 0.03, "pnl": 30000}, "나🔥": {"ret": 0.04, "pnl": 40000},
               "규칙": {"ret": 0.0, "pnl": 0}, "winner": "나🔥"}),
        _item("2026-10-15", {"나": {"pending": True}, "PB": {"cash": True}}, {"void": "나 미제출 — 채점 제외"}),
        _item("2026-10-16", {"나": {"ticker": "A"}, "PB": {"cash": True}}, None),
        _item("2026-10-09", {"나": {"ticker": "A"}, "PB": {"cash": True}}, {"나": {"ret": 0.5, "pnl": 1}, "PB": {"pnl": 0}, "winner": "나"}),  # 지난주
    ]
    r = sw.duel_record(items, date(2026, 10, 12), date(2026, 10, 18))
    assert (r["scored"], r["void"], r["pending"]) == (2, 1, 1)
    me = r["by"]["나"]
    assert me["n"] == 2 and me["win"] == 1 and me["trades"] == 2 and me["hit"] == 0.5 and me["pnl"] == 10000
    pb = r["by"]["PB"]
    assert pb["n"] == 2 and pb["trades"] == 1 and pb["hit"] == 1.0 and pb["win"] == 0   # 현금 판은 진입 아님
    bb = r["by"]["나🔥"]["by_basis"]
    assert bb["감"]["n"] == 1 and bb["감"]["win"] == 0 and bb["감"]["avg_ret"] == -0.05
    assert bb["판단"]["n"] == 1 and bb["판단"]["win"] == 1 and bb["판단"]["pnl"] == 40000
    assert r["by"]["규칙"]["n"] == 1 and r["by"]["PB🔥"]["n"] == 0


def test_event_counts_and_health():
    ev = [{"date": "2026-10-15", "type": "경보:서킷 1단계 기준(−8%) 도달"}, {"date": "2026-10-15", "type": "서킷브레이커"},
          {"date": "2026-10-16", "type": "매수 사이드카"}, {"date": "2026-10-16", "type": "연준 의장 발언"},
          {"date": "2026-10-01", "type": "사이드카"}]
    c = sw.event_counts(ev, date(2026, 10, 12), date(2026, 10, 18))
    assert c == {"서킷": 1, "사이드카": 1, "경보": 1, "total": 3}
    h = sw.health_summary({"asof": "x", "issues": ["a"], "fails7d": {"briefing": 1, "live": 2}})
    assert h["failed_runs_7d"] == 3 and h["issues"] == 1


def test_lens_table_and_study_grades(tmp_path):
    reg = {"updated": "2026-10-16", "lenses": [{"id": "a", "name_ko": "A", "evidence": {"grade": "B"}, "status": "채택"},
                                               {"id": "b", "name_ko": "B", "evidence": {}}]}
    t = sw.lens_table(reg)
    assert t["n"] == 2 and t["by_grade"]["B"] == 1 and t["by_grade"]["검증전"] == 1
    (tmp_path / "s1.json").write_text('{"grades": {"H1": "A", "H2": {"grade": "F", "why": "x"}}}', encoding="utf-8")
    (tmp_path / "s2.json").write_text('{"signals": [{"id": "H1", "grade": "검증전"}], "lens_grade": "F"}', encoding="utf-8")
    g = sw.study_grades(tmp_path)
    assert [(x["study"], x["id"], x["grade"]) for x in g] == [("s1", "H1", "A"), ("s1", "H2", "F"), ("s2", "H1", "검증전"), ("s2", "lens", "F")]


def test_telegram_line_ratios_only():
    res = sw.build(date(2026, 10, 16))
    line = sw.telegram_line(res)
    assert line.startswith("📊 주간 성적표 준비됨") and "나🔥(감)" in line and "원" not in line
    assert "누나" not in sw.render_md(res)
