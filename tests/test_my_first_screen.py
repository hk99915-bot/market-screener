"""MY 첫 화면(UXUI 스펙 docs/uxui/2026-10-28_my_tab_spec.md) — 화면 상수가 엔진과 같은지, 첫 화면 규칙이 코드에 남아 있는지."""
import re
from pathlib import Path

from screener import defs

SRC = (Path(__file__).resolve().parents[1] / "apps-script" / "tab_my.html").read_text(encoding="utf-8")


def test_stress_limit_matches_engine():
    m = re.search(r"const MYFS_LIM=([\d.]+);", SRC)
    assert m, "tab_my.html 에 MYFS_LIM 상수가 없다"
    assert float(m.group(1)) == defs.STRESS_LIMIT


def test_first_screen_reads_headline_and_stats_only():
    assert "pbGet('analysis/headline.json')" in SRC and "pbGet('analysis/latest.json')" in SRC
    assert "오늘 PB 미작성" in SRC and "PB 결론 미갱신" in SRC and "날짜 확인 필요" in SRC
    # 블록 순서: 첫 화면(①~④) → 성적표 전체 접힘 → 보유 입력
    i, j, k = SRC.index('id="myfirst"'), SRC.index('id="mycorr"'), SRC.index('id="myin"')
    assert i < j < k
