"""CPI 날짜표(reports/cpi_releases.json)·전년비 날짜 일치·캘린더 CPI 결과 줄 (req-macro-4198c8f8·b0e9d552, 네트워크 없음)."""
import importlib.util
import json
from pathlib import Path

from screener import calendar_ev

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("cpi_release_table", ROOT / "scripts" / "cpi_release_table.py")
crt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(crt)


def test_yoy_matches_same_month_not_row_offset():
    # 2025-10 결측: 행 기준이면 2026-09 가 2025-08 과 비교돼 13개월 변화가 된다
    obs = [(f"2025-{m:02d}", 100.0 + m) for m in range(1, 13) if m != 10] + [(f"2026-{m:02d}", 110.0 + m) for m in range(1, 11)]
    per, v, pv = calendar_ev._calc(obs, "yoy")
    assert per == "2026-10" and v is None                       # 전년 동월 없음 → 산출 불가
    assert abs(pv - (119.0 / 109.0 - 1) * 100) < 1e-9            # 2026-09 vs 2025-09


def test_pct_bls_rounding_and_kst_dst():
    assert crt.pct(337.476, 336.298) == 0.4 and crt.pct(339.900, 338.896) == 0.3
    assert crt.pct(1.0, None) is None and str(crt.pct(100.0, 100.001)) == "0.0"
    assert crt.kst_of("2026-10-14") == "2026-10-14 21:30"        # EDT
    assert crt.kst_of("2026-11-10") == "2026-11-10 22:30"        # EST


def test_cpi_lines_cons_only_with_source():
    row = {"release_et": "2026-11-10", "actual": {"hl_mom": 0.4, "core_mom": 0.3, "hl_yoy": None, "core_yoy": None},
           "actual_note": "전년비: 전년 동월 2025-10 지수 결측", "cons": {"hl_mom": 0.3, "core_mom": None}, "cons_src": "x"}
    L = calendar_ev.cpi_lines(row)
    assert L[0].startswith("CPI 전월비(계절조정) +0.4% · 컨센 +0.3% → 차이 +0.1%p")
    assert L[1] == "근원 CPI 전월비(계절조정) +0.3% · 컨센 없음"
    assert L[2].startswith("전년비 산출 불가")
    for s in L:
        if "차이" in s:
            assert "컨센" in s                                    # 컨센 없이 비교 표현 금지(결재 #9)


def test_table_file_shape():
    d = json.loads((ROOT / "reports" / "cpi_releases.json").read_text(encoding="utf-8"))
    rows = d["rows"]
    dates = [r["release_et"] for r in rows]
    assert len(rows) >= 58 and dates == sorted(set(dates)) and rows[0]["ref"] == "2021-12"
    for r in rows:
        assert r["release_kst"].endswith(("21:30", "22:30"))
        has_cons = any(v is not None for v in r["cons"].values())
        assert has_cons == (r["cons_src"] != "출처 없음")         # 컨센 값은 출처와 함께만
        assert r["date_check"] != "BLS 아카이브와 불일치 — 확인 필요"
