"""섹터 체계 (보드 toss-sectors, 10/21): 공식 1종목1섹터(GICS/WICS) 정규화·반도체 판정·전환 스위치 기본값. 네트워크 없음."""
from __future__ import annotations

import pytest

from screener import sectors


@pytest.mark.parametrize("name,want", [
    ("Technology", "IT"), ("Information Technology", "IT"), ("technology", "IT"), ("IT", "IT"),
    ("Healthcare", "헬스케어"), ("Financial Services", "금융"), ("Consumer Cyclical", "경기소비재"),
    ("Consumer Defensive", "필수소비재"), ("Basic Materials", "소재"), ("realestate", "부동산"),
    ("Communication Services", "커뮤니케이션"), ("Nonsense", None), (None, None),
])
def test_yahoo_and_gics_names_normalize_to_11(name, want):
    assert sectors.gics_ko(name) == want


def test_gics_eleven_and_yahoo_map_complete():
    assert len(sectors.GICS_KO) == 11
    assert set(sectors.YAHOO_TO_GICS.values()) == set(sectors.GICS_KO)


def test_switch_on_since_1024():
    # 10/24 07:10 KST 전환(겸이 결재 appr-toss-sectors-switch) — 롤백하면 이 테스트도 같이 False 로
    assert sectors.OFFICIAL_LIMITS is True


def test_official_us_and_kr(tmp_path, monkeypatch):
    (tmp_path / "us_sector.csv").write_text("yf,sector,gics_sub\nNVDA,IT,Semiconductors\nAAPL,IT,\"Technology Hardware, Storage & Peripherals\"\nJPM,금융,Diversified Banks\n", encoding="utf-8")
    (tmp_path / "kr_sector.csv").write_text("code,sector\n005930,전기·전자\n", encoding="utf-8")
    monkeypatch.setattr(sectors, "UNIVERSE_DIR", tmp_path)
    sectors.clear_cache()
    try:
        assert sectors.semi_official("US", "NVDA") is True and sectors.semi_official("US", "AAPL") is False
        assert sectors.semi_official("US", "ASML") is True           # NDX 전용 — 수동 GICS
        assert sectors.official("US", "ZZZZ")["sector"] is None and sectors.semi_official("US", "ZZZZ") is None
        o = sectors.official("KR", "005930")
        assert o["src"] == "KRX업종(WICS 대체)" and sectors.semi_official("KR", "005930") is None   # KRX 업종으론 가를 수 없음
        (tmp_path / "kr_wics.csv").write_text("code,wics_l1,wics_l2,asof\n005930,IT,반도체와반도체장비,2026-10-20\n035420,커뮤니케이션서비스,미디어와엔터테인먼트,2026-10-20\n", encoding="utf-8")
        sectors.clear_cache()
        assert sectors.official("KR", "005930") == {"sector": "IT", "group": "반도체와반도체장비", "src": "WICS"}
        assert sectors.semi_official("KR", "005930") is True and sectors.semi_official("KR", "035420") is False
    finally:
        sectors.clear_cache()


def test_repo_us_sector_has_gics_sub():
    sectors.clear_cache()
    assert sectors.semi_official("US", "NVDA") is True and sectors.semi_official("US", "MSFT") is False


def test_pb_evaluate_switch_picks_basis(monkeypatch):
    """스위치 False(롤백) 면 semi_ex(판정 입력) = 예전 값, True(10/24~ 기본) 면 공식 섹터 값. 병행 필드(*_old·*_new)는 둘 다 계속 나간다."""
    from screener import pb
    if not (pb._index() or {}):
        pytest.skip("detail 색인 없음")
    monkeypatch.setattr(pb.sectors, "OFFICIAL_LIMITS", False)
    ev = pb.evaluate("NVDA 10\nAAPL 10\n현금 100\n")
    if ev is None:
        pytest.skip("detail 없음")
    assert ev["semi_ex"] == ev["semi_ex_old"] and "semi_ex_new" in ev
    assert ev["sector_basis"]["using"] == "old" and ev["sector_basis"]["switch"] is False
    assert {r["s"]: r["semi_new"] for r in ev["rows"]}.get("NVDA") is True
    assert abs(sum(ev["sector_w_new"].values()) - (ev["tot"] / (ev["nav"] or 1))) < 1e-6
    monkeypatch.setattr(pb.sectors, "OFFICIAL_LIMITS", True)
    ev2 = pb.evaluate("NVDA 10\nAAPL 10\n현금 100\n")
    assert ev2["semi_ex"] == ev2["semi_ex_new"] and ev2["sector_basis"]["using"] == "new"
    assert "semi_ex_old" in ev2 and ev2["sector_basis"]["switch"] is True


def test_switch_moves_storage_and_eda_out_of_semi():
    """전환으로 판정이 바뀌는 대표 종목(10/24 기록): GICS 하위산업 기준 — 스토리지(STX·WDC·SNDK)·EDA(SNPS·CDNS)는 반도체 아님, FSLR 은 반도체."""
    sectors.clear_cache()
    for t in ("STX", "WDC", "SNDK", "SNPS", "CDNS"):
        assert sectors.semi_official("US", t) is False, t
    assert sectors.semi_official("US", "FSLR") is True
