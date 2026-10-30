"""req-data-630b1bfe — 네이버 테마 버킷이 WICS 와 양립 안 하면 WICS 중분류 버킷으로 (SK스퀘어·롯데쇼핑 엔터·미디어 오분류)."""
from screener.themes import BUCKETS, THEME_WICS_L1, THEME_WICS_L2, WICS_L2_BUCKET, gated_theme, wics_compatible


def test_sk_square_not_entertainment():
    # 10/29 마감 코멘트 '엔터·미디어 +2.7%' 의 87.9% 가 SK스퀘어(테마 '모바일콘텐츠' 부분 일치)
    assert gated_theme("엔터·미디어", "IT", "반도체와반도체장비") == "반도체"


def test_lotte_shopping_retail_not_entertainment():
    # '영화'(롯데시네마) 테마로 엔터 — 같은 경기관련소비재라도 소매(유통)는 아님 → 중분류 게이트
    assert gated_theme("엔터·미디어", "경기관련소비재", "소매(유통)") == "유통"


def test_compatible_theme_kept():
    assert gated_theme("2차전지", "소재", "소재") == "2차전지"          # 테마는 업종을 가로지름 — 넓게 허용
    assert gated_theme("엔터·미디어", "커뮤니케이션서비스", "미디어와엔터테인먼트") == "엔터·미디어"
    assert gated_theme("반도체", "IT", "반도체와반도체장비") == "반도체"


def test_unknown_wics_keeps_theme():
    assert gated_theme("엔터·미디어", None, None) == "엔터·미디어"
    assert wics_compatible(None, "IT", "디스플레이")


def test_unmapped_l2_returns_none_for_next_source():
    # WICS 중분류 빈 칸이면 None → detail.py 가 다음 출처(KRX 업종)로
    assert gated_theme("조선", "IT", "") is None


def test_every_bucket_has_gate_and_l2_map_complete():
    names = {b for b, _ in BUCKETS}
    assert names == set(THEME_WICS_L1) | set(THEME_WICS_L2)
    import csv
    from pathlib import Path
    p = Path(__file__).resolve().parents[1] / "universe" / "kr_wics.csv"
    if p.exists():
        l2s = {r["wics_l2"] for r in csv.DictReader(p.open(encoding="utf-8")) if r["wics_l2"]}
        assert l2s <= set(WICS_L2_BUCKET), l2s - set(WICS_L2_BUCKET)
