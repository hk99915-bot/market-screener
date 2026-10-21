"""비종목 리포트(research_views)·분류기(report_kind)·종목 리포트 감사 수정(research) 테스트 — 네트워크 없음.

HTML 픽스처는 직접 만들지 않는다: tests/fixtures/naver_research_nextjs_20261020.html 은 Actions 가 실제로 받은
네이버 리서치 목록 응답(앞 20,000자, reports/logs/naver_list.html 10/20 판)이다.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import polars as pl
import pytest

from screener import report_kind, research, research_views as rv

FIX = Path(__file__).parent / "fixtures" / "naver_research_nextjs_20261020.html"


# ── 분류기 ──
@pytest.mark.parametrize("title,cat,kind", [
    ("반도체 업황 점검", "산업분석", "섹터"),
    ("주간 시장 전략", "시황정보", "전략"),
    ("미국 고용 지표 리뷰", "경제분석", "매크로"),
    ("크레딧 시장 동향", "채권분석", "채권"),
    ("원/달러 환율 4분기 전망", "시황정보", "외환"),
    ("달러 강세와 신흥국", "경제분석", "외환"),
    ("12월 선물옵션 동시만기 점검", "시황정보", "파생"),
    ("ELS 발행 동향", "투자정보", "파생"),
    ("국고채 만기 구조 변화", "채권분석", "채권"),          # 채권의 '만기'는 파생 아님
    ("환율 수혜 업종", "산업분석", "섹터"),                # 섹터의 환율은 섹터 유지
    ("2차전지 Deep Dive", "산업분석", "인뎁스"),
    ("삼성전자(005930) 실적 리뷰", "종목분석", "종목"),
    ("삼성전자 변동성 확대", "기업", "종목"),
])
def test_classify_category_then_keyword(title, cat, kind):
    k, why = report_kind.classify(title, cat)
    assert k == kind and k in report_kind.KINDS and why


def test_classify_without_category_and_pages():
    assert report_kind.classify("FOMC 리뷰: 연준 동결")[0] == "매크로"
    assert report_kind.classify("회사채 스프레드 점검")[0] == "채권"
    assert report_kind.classify("KOSPI200 옵션 만기 영향")[0] == "파생"
    assert report_kind.classify("엔화 약세 시나리오")[0] == "외환"
    assert report_kind.classify("자동차 산업 3분기")[0] == "섹터"
    k, why = report_kind.classify("월간 포트폴리오", pages=42)
    assert k == "인뎁스" and "pages:42" in why
    k, why = report_kind.classify("제목 없음 같은 것")
    assert k == "전략" and why.startswith("default")
    # 본문(text)도 근거가 된다 — 텔레그램 PDF 수집기 용
    k, why = report_kind.classify("Morning Note", text="오늘 국고채 금리는 하락했다")
    assert k == "채권" and "text" in why


def test_classify_is_pure():
    a = report_kind.classify("원화 약세", "시황정보")
    assert a == report_kind.classify("원화 약세", "시황정보")


# ── 종목 리포트 감사 수정 ──
@pytest.mark.parametrize("op", ["Not Rated", "투자의견없음", "nr", "N/A", "na", "NR", "-", None, ""])
def test_opinion_rank_not_rated_is_none(op):
    assert research.opinion_rank(op) == -1   # 예전엔 1(중립) → 매수→NR 이 '의견 하향'으로 잡힘


@pytest.mark.parametrize("op,r", [("Buy", 2), ("매수", 2), ("Strong Buy", 2), ("Hold", 1), ("중립", 1), ("Sell", 0)])
def test_opinion_rank_rated(op, r):
    assert research.opinion_rank(op) == r


def test_revisions_buy_to_nr_is_not_downgrade():
    s = pl.DataFrame({"key": ["a", "b"], "date": [date(2026, 9, 1), date(2026, 10, 1)], "source": ["한경"] * 2,
                      "code": ["000001"] * 2, "name": ["x"] * 2, "title": ["t"] * 2, "broker": ["A증권"] * 2,
                      "opinion": ["Buy", "Not Rated"], "target": [100.0, None], "link": ["", ""],
                      "collected_at": ["", ""], "summary": ["", ""], "analyst": ["", ""]}, schema=research.SCHEMA)
    rv_ = research.revisions(s)
    assert rv_.filter(pl.col("key") == "b")["op_chg"][0] is None


def test_write_status(tmp_path, monkeypatch):
    import screener.config as cfg
    monkeypatch.setattr(cfg, "REPORT_DIR", tmp_path)
    research.write_status({"한경": {"status": "ok", "n": 3}, "네이버": {"status": "layout_changed", "n": 0, "reason": "x"}})
    d = json.loads((tmp_path / "research_status.json").read_text(encoding="utf-8"))
    assert d["overall"] == "partial" and d["sources"]["네이버"]["status"] == "layout_changed"


# ── 파서: 실제 응답(Next.js 껍데기) ──
def test_real_naver_response_is_app_shell():
    h = FIX.read_text(encoding="utf-8")
    assert rv.looks_like_app_shell(h)
    rows, diag = rv.parse_table(h, r"industry_read\.naver\?[^\"']*nid=\d+", rv.NAVER)
    assert rows == [] and diag.startswith("layout_changed")
    assert rv.hankyung_types(h) == {}


def test_header_unmapped_when_no_th():
    rows, diag = rv.parse_table("<table><tr><td>1</td></tr></table>", r"nid=\d+", rv.NAVER)
    assert rows == [] and diag.startswith("header_unmapped")


# ── 저장·산출물 ──
def _raw(d, title, cat, broker="A증권", src="네이버"):
    return {"date": d, "title": title, "category": cat, "broker": broker, "analyst": None, "sector": "반도체",
            "link": "https://example.invalid/x", "source": src}


def test_records_merge_and_json():
    now = datetime(2026, 10, 20, 23, 50, tzinfo=rv.KST)
    recs = [rv.to_record(_raw(date(2026, 10, 20), "반도체 업황", "산업분석"), "t"),
            rv.to_record(_raw(date(2026, 10, 20), "원/달러 환율 전망", "시황정보", "B투자증권"), "t"),
            rv.to_record(_raw(date(2026, 10, 19), "국고채 금리 점검", "채권분석"), "t")]
    assert recs[0]["kind"] == "섹터" and recs[0]["sector"] == "반도체"
    assert recs[1]["kind"] == "외환" and recs[1]["sector"] is None
    store, n = rv.merge(rv.load_store().clear(), recs + [dict(recs[0])])   # 같은 key 중복은 1건
    assert n == 3 and store.height == 3
    store2, n2 = rv.merge(store, recs)
    assert n2 == 0 and store2.height == 3
    out = rv.build_json(store, {"overall": "ok", "sources": {}}, now)
    assert out["asof"] == "2026-10-20" and out["kinds"]["외환"]["n"] == 1 and "종목" not in out["kinds"]
    assert {r["kind"] for r in out["by_kind_broker"]} == {"섹터", "외환", "채권"}
    assert set(store.columns) == set(rv.SCHEMA) and "code" not in store.columns   # 종목 스키마와 분리


def test_key_stable_and_summary_clip():
    k1 = rv.make_key(date(2026, 10, 20), "한경", "A투자증권", "제목  하나")
    assert k1 == rv.make_key(date(2026, 10, 20), "한경", "A 투자증권", "제목 하나")
    assert len(rv.clip_summary("가" * 900)) == rv.SUMMARY_MAX
    assert rv.clip_summary(None) is None


def test_update_records_failure_status(tmp_path, monkeypatch):
    monkeypatch.setattr(rv, "STORE", tmp_path / "rv.parquet")
    monkeypatch.setattr(rv, "OUT", tmp_path / "rv.json")
    monkeypatch.setattr(rv, "DATA_DIR", tmp_path)
    monkeypatch.setattr(rv, "REPORT_DIR", tmp_path)

    # 종목 백필 분기(research.backfill_naver)가 실제 data/research.parquet 를 읽고 쓰지 않게
    monkeypatch.setattr(research, "STORE", tmp_path / "research.parquet")
    monkeypatch.setattr(research, "DATA_DIR", tmp_path)

    def boom(*a, **k):
        raise ConnectionError("403")
    # 네트워크 출구 둘 다 막는다: 한경·요약 = rv._get, 네이버 = 목록 API(10/21 64c1ae52~ researches/v2, nra._get_json).
    # rv._get 만 막으면 외부망이 열린 CI 에서 네이버가 실제로 성공해 overall='ok' 가 됨(10/20 23:44Z~ tests 빨강).
    from screener import naver_research_api as nra
    monkeypatch.setattr(rv, "_get", boom)
    monkeypatch.setattr(nra, "_get_json", boom)
    st = rv.update()
    assert st["overall"] == "error"
    assert all(v["status"] == "error" for v in st["sources"].values())
    d = json.loads((tmp_path / "rv.json").read_text(encoding="utf-8"))
    assert d["status"]["overall"] == "error" and "403" in d["status"]["sources"]["hankyung"]["reason"]
    assert not (tmp_path / "rv.parquet").exists()   # 새 행 없으면 저장소를 다시 쓰지 않음


# ── 파서: 실제 응답(한경 컨센서스 목록, Actions 10/21 00:11 KST, 앞 40,000자) ──
HKFIX = Path(__file__).parent / "fixtures" / "hankyung_list_co_20261021.html"


def test_real_hankyung_types_from_menu():
    t = rv.hankyung_types(HKFIX.read_text(encoding="utf-8"))
    assert set(t) == {"IN", "MA", "EC", "DE", "FE", "BO", "FU", "QU", "FC", "ET"}
    assert t["FE"] == "[파생]외환" and "CO" not in t and "UP" not in t
    kinds = {c: report_kind.classify("제목", n)[0] for c, n in t.items()}
    assert kinds == {"IN": "섹터", "MA": "전략", "EC": "매크로", "DE": "파생", "FE": "외환", "BO": "채권",
                     "FU": "전략", "QU": "전략", "FC": "전략", "ET": "파생"}


def test_real_hankyung_table_by_header_names():
    rows, diag = rv.parse_table(HKFIX.read_text(encoding="utf-8"), r"report_idx=\d+", rv.HK)
    assert diag == "ok" and len(rows) >= 5
    r = rows[0]
    assert r["date"] == date(2026, 10, 20) and r["broker"] and r["analyst"]
    assert "report_idx=" in r["link"] and r["link"].startswith("https://consensus.hankyung.com/")
    assert r["title"].count("(") <= 1          # 숨은 요약 팝업이 제목에 섞이지 않음


def test_hankyung_subtypes_win_dedupe(monkeypatch):
    """같은 리포트가 DE(파생)와 FE([파생]외환) 목록에 다 나오면 세부 분류(외환)로 남아야 한다 (10/21 실행 재현)."""
    calls = []

    def fake_get(url, ref, enc=None):
        calls.append(url)
        return "menu"
    monkeypatch.setattr(rv, "_get", fake_get)
    monkeypatch.setattr(rv, "hankyung_types", lambda h: {"DE": "파생", "FE": "[파생]외환", "BO": "[파생]채권"})
    row = {"date": date(2026, 10, 20), "title": "Daily Forex Live", "broker": "B은행", "analyst": None, "sector": None,
           "link": "https://consensus.hankyung.com/analysis/downpdf?report_idx=1"}
    monkeypatch.setattr(rv, "parse_table", lambda h, rx, base: ([dict(row)], "ok"))
    rows, st = rv.fetch_hankyung(date(2026, 10, 19), date(2026, 10, 20), max_pages=1)
    recs = [rv.to_record(r, "t") for r in rows]
    store, n = rv.merge(rv.load_store().clear(), recs)
    assert n == 1 and store["kind"][0] in ("외환", "채권") and "report_type=DE" in calls[-1]
    assert report_kind.classify("Daily Forex Live", "시장")[0] == "외환"
