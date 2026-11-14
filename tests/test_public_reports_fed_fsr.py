"""Fed 금융안정보고서(FSR) 전용 소스 `fed_fsr` — 발간 페이지 PDF 파일명 파싱 (11/14).

왜: press_all.xml RSS 에는 FSR 이 실리지 않아 `fed` 소스의 FSR 시리즈가 늘 비어 있었고 '다음 발간' 캘린더만 남았다.
픽스처 = 2026-11-14 접속 발췌(tests/fixtures/public_reports/fed_fsr_page.html). 네트워크 없음.
"""
from datetime import date
from pathlib import Path

from screener import public_reports as pr

FIX = Path(__file__).parent / "fixtures" / "public_reports" / "fed_fsr_page.html"
FSR = next(s for s in pr.SOURCES if s["id"] == "fed_fsr")
FED = next(s for s in pr.SOURCES if s["id"] == "fed")


def test_parse_fsr_page_rows():
    rows = pr.parse_fed_fsr_list(FIX.read_text(encoding="utf-8"))
    assert [r["date"] for r in rows] == [date(2026, 11, 13), date(2026, 5, 8), date(2025, 11, 7), date(2025, 4, 25)]
    r = rows[0]
    assert r["series"] == "Financial Stability Report" and r["title"] == "Financial Stability Report (2026-11)"
    assert r["link"] == "https://www.federalreserve.gov/publications/files/financial-stability-report-20261113.pdf"
    assert r["summary"] is None and r["vid"] is None
    assert all(len(x["link"]) > 0 for x in rows)


def test_parse_fsr_ignores_non_8digit_and_garbage():
    """파일명이 8자리가 아닌 2018-11 호(201811)·없는 날짜는 버린다 — 규칙 밖 예외를 제목으로 만들지 않는다."""
    rows = pr.parse_fed_fsr_list(FIX.read_text(encoding="utf-8"))
    assert not any("2018" in r["link"] for r in rows)
    assert pr.parse_fed_fsr_list("") == []
    assert pr.parse_fed_fsr_list('<a href="/publications/files/financial-stability-report-20261340.pdf">PDF</a>') == []


def test_fed_source_no_longer_carries_fsr():
    """FSR 시리즈는 fed_fsr 로 분리 — fed 는 FOMC 의사록만(RSS 에 FSR 이 없어 빈 시리즈·잘못된 캘린더가 남던 자리)."""
    assert [s[0] for s in FED["series"]] == ["FOMC 의사록"]
    assert [s[0] for s in FSR["series"]] == ["Financial Stability Report"] and FSR["parser"] == "fed_fsr"
    # RSS 에 FSR 제목이 섞여 와도 fed 는 그 행을 만들지 않는다(시리즈 불일치 → classify 가 버림)
    rss = ("<?xml version=\"1.0\"?><rss><channel><item><title>Financial Stability Report</title>"
           "<link>https://fed/fsr</link><pubDate>Fri, 13 Nov 2026 18:00:00 GMT</pubDate></item></channel></rss>")
    assert pr.classify(FED, pr.parse_feed(rss)) == []


def test_fed_fsr_source_fetch_merge_calendar():
    html = FIX.read_text(encoding="utf-8")
    rows, st = pr.fetch_source(FSR, get=lambda u: html)
    assert st["status"] == "ok" and st["n"] == len(rows) == 4
    assert st["url"] == pr.FSR_PAGE
    t = date(2026, 11, 14)
    items, _ = pr.merge([], rows, "fed_fsr", "Fed", "해외", "2026-11-14 03:30", t)
    assert items[0]["series"] == "Financial Stability Report" and items[0]["src"] == "fed_fsr" and items[0]["inst"] == "Fed"
    assert items[0]["collected_at"].startswith("backfill")   # 첫 수집 = 백필(신규 알림 제외)
    pub = pr.build_output(items, {"fed_fsr": st}, t, "n")
    cal = {c["series"]: c["next"] for c in pub["calendar"] if c["inst"] == "Fed"}
    assert cal["Financial Stability Report"] == "2027-04"   # 11/13 발간분 수집 → 다음은 4월(4·11월 규칙)
    assert cal["FOMC 의사록"]   # 기존 시리즈 캘린더는 그대로


def test_fed_fsr_source_failure_is_isolated():
    def blocked(u):
        raise OSError("403 Forbidden")
    rows, st = pr.fetch_source(FSR, get=blocked)
    assert rows == [] and st["status"] == "error" and "federalreserve.gov" in st["reason"]
