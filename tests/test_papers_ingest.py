"""논문 수집 파이프라인 1주차 회귀 검사 — 네트워크 없이 고정 픽스처만 쓴다(tests/conftest.py 가 소켓 차단).

검사: 소스 레지스트리 스키마 · 6개 파서 · 정규화 키 · 소스 간 중복 제거 · 철회 −100 즉시 폐기 · 문턱(≥60 요약/40~59 보류/<40 폐기)
      · 재실행 멱등 · 소스 1개 실패 fail-open · --dry-run 무쓰기 · 신규 상한 · paper_lit_check --ci 통과/차단.
"""
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 11, 15, 3, 0, tzinfo=KST)


def _load(module: str):
    spec = importlib.util.spec_from_file_location(f"test_{module}", ROOT / "scripts" / f"{module}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ing = _load("papers_ingest")
lit = _load("paper_lit_check")

SOURCES = json.loads((ROOT / "content" / "papers" / "sources.json").read_text(encoding="utf-8"))
RULES = json.loads((ROOT / "content" / "papers" / "triage_rules.json").read_text(encoding="utf-8"))
DESK_MAP = SOURCES["desk_map"]


# ── 고정 픽스처 ─────────────────────────────────────────────────────
ARXIV_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2611.00001v1</id>
    <title>Momentum Crashes in Korean Equity Portfolios</title>
    <summary>Using daily data from 2000 to 2020 with 12,345 observations we document momentum crashes in KOSPI.
    The timing rule is out-of-sample and pre-registered with walk-forward validation and net of transaction costs
    and slippage. Foreign investor net purchases predict reversals.</summary>
    <link href="https://arxiv.org/abs/2611.00001v1" rel="alternate" type="text/html"/>
    <published>2026-11-10T12:00:00Z</published>
    <author><name>Jin Park</name></author>
    <author><name>Mina Lee</name></author>
    <arxiv:comment>28 pages, 6 figures</arxiv:comment>
    <arxiv:primary_category term="q-fin.PM"/>
    <category term="q-fin.PM"/>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2607.17866v2</id>
    <title>Financial Statement Analysis with Large Language Models</title>
    <summary>We prompt a model with financial statements and find abnormal returns.</summary>
    <link href="https://arxiv.org/abs/2607.17866v2" rel="alternate"/>
    <published>2026-07-25T00:00:00Z</published>
    <author><name>Alex Kim</name></author>
    <arxiv:comment>Withdrawn: co-authors found a data inconsistency</arxiv:comment>
  </entry>
</feed>
"""

ARXIV_DOI_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2611.00002v1</id>
    <title>Volatility Risk Premium and Dealer Gamma</title>
    <summary>We estimate the volatility risk premium from option data, 1996 to 2020, out-of-sample.</summary>
    <link href="https://arxiv.org/abs/2611.00002v1" rel="alternate"/>
    <published>2026-11-11T12:00:00Z</published>
    <author><name>Lena Ortiz</name></author>
    <arxiv:doi>10.1111/jofi.13000</arxiv:doi>
  </entry>
</feed>
"""

NBER_RSS = """<?xml version="1.0" encoding="UTF-8" ?>
<rss version="2.0"><channel>
<title>National Bureau of Economic Research Working Papers</title>
<item>
<title>Term Premium and Fiscal Risk -- by Ana Silva, Robert King</title>
<description>We study fiscal shocks and the term premium in a panel from 1990 to 2020, out-of-sample.</description>
<link>https://www.nber.org/papers/w35984#fromrss</link>
<guid>https://www.nber.org/papers/w35984#fromrss</guid>
<pubDate>Mon, 10 Nov 2026 12:00:00 GMT</pubDate>
</item>
</channel></rss>
"""

FED_RSS = """<?xml version="1.0" encoding="utf-8" ?>
<rss version="2.0"><channel>
<title>FRB: Finance and Economics Discussion Series Working Papers</title>
<item>
  <title>FEDS Paper: Bank Liquidity and the Term Premium</title>
  <link><![CDATA[https://www.federalreserve.gov/econres/feds/bank-liquidity.htm]]></link>
  <description><![CDATA[<a href="https://www.federalreserve.gov/econres/a.htm">Nick Carollo</a>, and <a href="https://www.federalreserve.gov/econres/b.htm">Leland Crane</a><br><br>We document the boom in bank reserves with transaction costs and out-of-sample tests, 1990 to 2020.]]></description>
  <pubDate><![CDATA[Thu, 12 Nov 2026 15:20:00 GMT]]></pubDate>
</item>
</channel></rss>
"""

REPEC_HTML = """<html><body>
<div class="tab-pane fade show active" id="content">
<h1>BIS Working Papers</h1>
<h3>2026</h3><div class="panel-body"><UL CLASS="list-group paperlist">
<LI class="list-group-item downfree">  <B>1395 <A HREF="/p/bis/biswps/1395.html">MaRCo: AI-agentic econometric analysis for central bankers</A></B><BR><I>by</I> Marco Lombardi & Taejin Park

<LI class="list-group-item downfree">  <B>1394 <A HREF="/p/bis/biswps/1394.html">Scenarios for future banking: liquidity and solvency</A></B><BR><I>by</I> Christian Schmieder & Min Wei
</UL></div>
<h3>2025</h3><div class="panel-body"><UL CLASS="list-group paperlist">
<LI class="list-group-item">  <B>1300 <A HREF="/p/bis/biswps/1300.html">Monetary policy spillovers in Asia</A></B><BR><I>by</I> Sun Ho
</UL></div>
</div></body></html>
"""

KCMI_HTML = """<html><body>
<div class="list" id="rsidx_2337">
  <div class="link">
    <div class="rpt_title">
      <strong>미국 사모신용시장의 건전성, 유동성 및 시스템리스크</strong>
      <em>선임연구위원 신보성 <span>2026.10.12</span></em>
    </div>
    <p class="txt">
      사모신용펀드의 성과는 펀드에 담긴 중견기업의 상환능력에 달려 있다. 금리 상승으로 이자부담이 늘어나면서 수익성도 빠르게 나빠지고 있다. 때문에 펀드 순자산가치 하락에 대한 우려가 크지만, 펀드 자체의 디폴트 가능성은 크지 않다.
    </p>
  </div>
  <a href="javascript:void(0);" onclick='viewpage(2337, "./report_view", "_self");'>이동</a>
  <div class="init_btns"><a href="/flexer/view?fid=29234" class="view">바로보기</a></div>
</div>
<div class="list" id="rsidx_2336">
  <div class="link">
    <div class="rpt_title">
      <strong>퇴직연금 디폴트옵션 성과평가</strong>
      <em>연구위원 김하늘 <span>2026.09.30</span></em>
    </div>
    <p class="txt">디폴트옵션의 성과를 비교한다.</p>
  </div>
  <a href="javascript:void(0);" onclick='viewpage(2336, "./report_view", "_self");'>이동</a>
</div>
</body></html>
"""

CROSSREF_JSON = json.dumps({
    "message": {"items": [
        {"DOI": "10.1111/jofi.13000", "type": "journal-article",
         "title": ["Volatility Risk Premium and Dealer Gamma"],
         "author": [{"given": "Lena", "family": "Ortiz"}],
         "issued": {"date-parts": [[2026, 9, 1]]},
         "container-title": ["Journal of Finance"],
         "URL": "https://doi.org/10.1111/jofi.13000",
         "abstract": "<jats:p>Option gamma predicts returns, 1996 to 2020, out-of-sample, net of transaction costs.</jats:p>"},
        {"DOI": "10.1093/rfs/hhx001", "type": "journal-article",
         "title": ["An Anomaly That Did Not Replicate"],
         "author": [{"given": "Kim", "family": "Lee"}],
         "issued": {"date-parts": [[2025, 1, 1]]},
         "container-title": ["Review of Financial Studies"],
         "URL": "https://doi.org/10.1093/rfs/hhx001",
         "updated-by": [{"type": "retraction", "DOI": "10.1093/rfs/hhx002"}]},
    ]}
})


def _fetcher(pages: dict, fail: tuple = ()):
    def fetch(url, **kw):
        for key, body in pages.items():
            if key in url:
                return body
        if any(f in url for f in fail):
            raise RuntimeError("connection refused")
        raise AssertionError(f"예상 밖 URL: {url}")
    return fetch


def _sources_file(tmp_path, sources: list[dict]) -> Path:
    doc = {"schema_version": 1, "desk_map": DESK_MAP, "sources": sources,
           "fetch_defaults": {"timeout_s": 1, "retries": 0, "pause_s": 0, "max_new_per_run": 120, "user_agent": "test"}}
    p = tmp_path / "sources.json"
    p.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return p


def _src(sid: str, parser: str, url: str, **kw) -> dict:
    base = {"id": sid, "parser": parser, "url": url, "venue": sid, "max_items": 10,
            "fulltext": "free_pdf", "desks": ["quant"]}
    base.update(kw)
    return base


def _run(tmp_path, sources, pages, **kw):
    src = _sources_file(tmp_path, sources)
    return ing.run(sources_path=src, rules_path=ROOT / "content" / "papers" / "triage_rules.json",
                   index_path=tmp_path / "index.json", fetcher=_fetcher(pages), now=NOW,
                   log=lambda *a, **k: None, **kw)


# ── 1. 레지스트리 ───────────────────────────────────────────────────
def test_source_registry_seven_sources_and_desk_map():
    ids = [s["id"] for s in SOURCES["sources"]]
    assert ids == ["arxiv", "nber", "fed_feds", "bis_repec", "bok", "kcmi", "crossref"]
    assert len(set(ids)) == 7
    for s in SOURCES["sources"]:
        assert s["parser"] in ing.PARSERS, s["id"]
        assert s.get("url") or s.get("feeds"), s["id"]
        assert set(s["desks"]) <= set(DESK_MAP), s["id"]
        assert s["fulltext"] in RULES["weights"]["fulltext"], s["id"]
    assert set(DESK_MAP) == {"macro", "quant", "derivs", "hf", "allocation", "frm", "behavior"}
    for desk, cfg in DESK_MAP.items():
        assert len(cfg["keywords"]) >= 5, desk


def test_triage_rules_versioned_and_complete():
    assert RULES["version"].startswith("triage-")
    for k in ("desk_fit", "sample", "oos", "cost", "data_access", "method_risk", "withdraw", "fulltext"):
        assert k in RULES["weights"]
    assert RULES["weights"]["withdraw"] == -100
    assert RULES["thresholds"] == {"summarize": 60, "hold": 40}


# ── 2. 파서 ─────────────────────────────────────────────────────────
def test_parse_arxiv_atom():
    items = ing.parse_atom(ARXIV_XML, {"venue": "arXiv"})
    assert len(items) == 2
    a = items[0]
    assert a["title"] == "Momentum Crashes in Korean Equity Portfolios"
    assert a["arxiv_id"] == "2611.00001"
    assert a["authors"] == ["Jin Park", "Mina Lee"]
    assert a["year"] == 2026 and a["published_at"] == "2026-11-10"
    assert "out-of-sample" in a["abstract"]
    assert "Withdrawn" in items[1]["note"]


def test_parse_nber_rss():
    items = ing.parse_rss_nber(NBER_RSS, {"venue": "NBER Working Paper"})
    assert len(items) == 1
    it = items[0]
    assert it["title"] == "Term Premium and Fiscal Risk"
    assert it["authors"] == ["Ana Silva", "Robert King"]
    assert it["arxiv_id"] is None            # NBER 번호를 arXiv ID 로 저장하지 않는다
    assert it["venue"] == "NBER Working Paper No.w35984"
    assert it["year"] == 2026


def test_parse_fed_rss():
    items = ing.parse_rss_fed(FED_RSS, {"venue": "FEDS Working Paper"})
    it = items[0]
    assert it["title"] == "Bank Liquidity and the Term Premium"
    assert it["authors"] == ["Nick Carollo", "Leland Crane"]
    assert it["abstract"].startswith("We document the boom")
    assert "<" not in it["abstract"]
    assert it["year"] == 2026


def test_parse_repec_html():
    items = ing.parse_html_repec(REPEC_HTML, {"venue": "BIS Working Paper"})
    assert len(items) == 3
    assert items[0]["title"].startswith("MaRCo")
    assert items[0]["authors"] == ["Marco Lombardi", "Taejin Park"]
    assert items[0]["year"] == 2026 and items[0]["venue"].endswith("No.1395")
    assert items[0]["url"] == "https://ideas.repec.org/p/bis/biswps/1395.html"
    assert items[2]["year"] == 2025


def test_parse_kcmi_html():
    items = ing.parse_html_kcmi(KCMI_HTML, {"venue": "KCMI 보고서"})
    assert len(items) == 2
    it = items[0]
    assert it["title"] == "미국 사모신용시장의 건전성, 유동성 및 시스템리스크"
    assert it["authors"] == ["신보성"]
    assert it["published_at"] == "2026-10-12" and it["year"] == 2026
    assert it["url"].endswith("report_no=2337")
    assert "상환능력" in it["abstract"]


def test_parse_crossref_json():
    items = ing.parse_json_crossref(CROSSREF_JSON, {"venue": "Crossref"})
    assert len(items) == 2
    assert items[0]["doi"] == "10.1111/jofi.13000"
    assert items[0]["venue"] == "Journal of Finance"
    assert items[0]["year"] == 2026
    assert items[1]["withdraw_hint"] is True
    assert items[0]["withdraw_hint"] is False


# ── 3. 키·중복·철회·점수 ────────────────────────────────────────────
def test_key_priority_and_determinism():
    assert ing.make_key("T", ["A B"], doi="10.1/ABC") == "doi:10.1/abc"
    assert ing.make_key("T", ["A B"], arxiv_id="2611.00001") == "arxiv:2611.00001"
    k1 = ing.make_key("Same  Title!", ["Jin Park"])
    k2 = ing.make_key("same title", ["jin park"])
    k3 = ing.make_key("same title", ["Mina Lee"])
    assert k1 == k2 and k1 != k3 and k1.startswith("sha1:")


def test_key_distinguishes_korean_titles():
    """한글 제목은 ASCII 필터로 지우면 전부 같은 키가 된다 — 서로 달라야 한다."""
    a = ing.make_key("금융기관 상호연계성을 고려한 시스템리스크 측정", [])
    b = ing.make_key("가계부채와 관련한 거시건전성 정책의 경제적 효과", [])
    c = ing.make_key("금융기관 상호연계성을 고려한 시스템리스크 측정", [])
    assert a != b and a == c


def test_dedupe_same_doi_across_sources(tmp_path):
    sources = [_src("arxiv", "atom", "https://ex.test/arxiv"), _src("crossref", "json_crossref", "https://ex.test/crossref")]
    pages = {"ex.test/arxiv": ARXIV_DOI_XML, "ex.test/crossref": CROSSREF_JSON}
    summary = _run(tmp_path, sources, pages)
    doc = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))
    keys = [p["key"] for p in doc["papers"]]
    assert keys.count("doi:10.1111/jofi.13000") == 1
    rec = next(p for p in doc["papers"] if p["key"] == "doi:10.1111/jofi.13000")
    assert rec["source"] == ["arxiv", "crossref"]
    assert summary["duplicates"] >= 1
    assert len(keys) == len(set(keys))


def test_dedupe_title_hash_across_sources(tmp_path):
    a = """<?xml version="1.0"?><rss version="2.0"><channel><item>
    <title>Only A Working Paper: Evidence from Flows</title><description>본문</description>
    <link>https://ex.test/a/1</link></item></channel></rss>"""
    b = """<?xml version="1.0"?><rss version="2.0"><channel><item>
    <title>only a working paper — evidence from flows</title><description>본문</description>
    <link>https://ex.test/b/1</link></item></channel></rss>"""
    sources = [_src("bok", "rss", "https://ex.test/a"), _src("nber", "rss", "https://ex.test/b")]
    _run(tmp_path, sources, {"ex.test/a": a, "ex.test/b": b})
    doc = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))
    assert len(doc["papers"]) == 1
    assert doc["papers"][0]["key"].startswith("sha1:")
    assert doc["papers"][0]["source"] == ["bok", "nber"]


def test_withdrawn_paper_rejected_at_minus_100(tmp_path):
    _run(tmp_path, [_src("arxiv", "atom", "https://ex.test/arxiv")], {"ex.test/arxiv": ARXIV_XML})
    doc = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))
    bad = next(p for p in doc["papers"] if p["arxiv_id"] == "2607.17866")
    assert bad["withdraw_flag"] is True
    assert bad["status"] == "rejected"
    assert bad["score"] <= -100
    assert any(r["rule"] == "withdraw" and r["points"] == -100 for r in bad["reasons"])
    assert doc["counts"]["withdrawn"] == 1


def test_crossref_retraction_flag_rejects(tmp_path):
    _run(tmp_path, [_src("crossref", "json_crossref", "https://ex.test/crossref")], {"ex.test/crossref": CROSSREF_JSON})
    doc = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))
    bad = next(p for p in doc["papers"] if p["key"] == "doi:10.1093/rfs/hhx001")
    assert bad["withdraw_flag"] is True and bad["status"] == "rejected"


def test_score_thresholds_high_and_low(tmp_path):
    _run(tmp_path, [_src("arxiv", "atom", "https://ex.test/arxiv"),
                    _src("kcmi", "html_kcmi", "https://ex.test/kcmi", fulltext="free_pdf")],
         {"ex.test/arxiv": ARXIV_XML, "ex.test/kcmi": KCMI_HTML})
    doc = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))
    strong = next(p for p in doc["papers"] if p["arxiv_id"] == "2611.00001")
    assert strong["score"] >= 60 and strong["status"] == "summarize"
    assert any(r["rule"] == "oos" and r["points"] == 20 for r in strong["reasons"])
    assert any(r["rule"] == "cost" for r in strong["reasons"])
    weak = next(p for p in doc["papers"] if "사모신용" in p["title"])
    assert weak["score"] < 40 and weak["status"] == "rejected"
    assert weak["reasons"]


def test_title_only_item_is_held_not_discarded(tmp_path):
    """제목만 주는 소스(BOK RSS 등)는 재료 부족 — 점수로 폐기하지 않고 hold·abstract_state=missing."""
    only_title = """<?xml version="1.0"?><rss version="2.0"><channel><item>
    <title>금융기관 상호연계성을 고려한 시스템리스크 측정 및 정책시사점</title>
    <description><![CDATA[<p>자세한 내용은 첨부파일을 참고하시기 바랍니다.</p>]]></description>
    <link>https://www.bok.or.kr/portal/bbs/B0000257/view.do?nttId=1</link>
    <pubDate>Thu, 30 Jul 2026 08:15:10 +0900</pubDate></item></channel></rss>"""
    _run(tmp_path, [_src("bok", "rss", "https://ex.test/bok")], {"ex.test/bok": only_title})
    doc = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))
    it = doc["papers"][0]
    assert it["abstract_state"] == "missing"
    assert it["status"] == "hold"
    assert any(r["rule"] == "abstract_state" for r in it["reasons"])
    assert it["score"] < 40


def test_rerun_is_idempotent(tmp_path):
    src = _sources_file(tmp_path, [_src("nber", "rss_nber", "https://ex.test/nber")])
    pages = {"ex.test/nber": NBER_RSS}
    kw = dict(sources_path=src, rules_path=ROOT / "content" / "papers" / "triage_rules.json",
              index_path=tmp_path / "index.json", fetcher=_fetcher(pages), now=NOW, log=lambda *a, **k: None)
    first = ing.run(**kw)
    papers_first = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))["papers"]
    second = ing.run(**kw)
    papers_second = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))["papers"]
    assert first["added"] == 1 and second["added"] == 0
    assert first["counts"]["total"] == second["counts"]["total"] == 1
    assert papers_first == papers_second  # 원장은 그대로(중복·재점수 없음)


def test_source_failure_fail_open(tmp_path):
    sources = [_src("broken", "rss", "https://ex.test/broken"), _src("nber", "rss_nber", "https://ex.test/nber")]
    summary = _run(tmp_path, sources, {"ex.test/nber": NBER_RSS}, )
    assert summary["counts"]["sources_ok"] == 1 and summary["counts"]["sources_failed"] == 1
    assert summary["sources_status"]["broken"]["ok"] is False
    doc = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))
    assert doc["sources_status"]["broken"]["error"]
    assert len(doc["papers"]) == 1


def test_all_sources_failed_is_error(tmp_path):
    src = _sources_file(tmp_path, [_src("broken", "rss", "https://ex.test/broken")])
    rc = ing.main(["--sources", str(src), "--rules", str(ROOT / "content" / "papers" / "triage_rules.json"),
                   "--index", str(tmp_path / "index.json"), "--quiet"])
    assert rc == 1


def test_dry_run_writes_nothing(tmp_path):
    summary = _run(tmp_path, [_src("nber", "rss_nber", "https://ex.test/nber")], {"ex.test/nber": NBER_RSS}, dry_run=True)
    assert summary["dry_run"] is True and summary["added"] == 1
    assert not (tmp_path / "index.json").exists()


def test_max_new_cap(tmp_path):
    summary = _run(tmp_path, [_src("arxiv", "atom", "https://ex.test/arxiv")], {"ex.test/arxiv": ARXIV_XML}, max_new=1)
    assert summary["added"] == 1


# ── 4. paper_lit_check ──────────────────────────────────────────────
GOOD_CARD = """- **Bailey & López de Prado (2014)** The Deflated Sharpe Ratio · JPM 40(5) · DOI 10.3905/jpm.2014.40.5.094
  - 결론: 시도 수가 많으면 표본 밖 성과를 할인해야 한다.
  - 한계: 정규분포 가정에 기댄다.
  - 적용: quant · scripts/study_rule_audit.py
  - 뒤집힐 조건: 시도 수를 사전에 고정하는 규율이 자리 잡으면 할인 폭을 줄인다.
"""


def _paper(**kw) -> dict:
    base = {"key": "doi:10.3905/jpm.2014.40.5.094", "source": ["crossref"], "primary_source": "crossref",
            "title": "The Deflated Sharpe Ratio", "authors": ["David H. Bailey"], "year": 2014,
            "venue": "Journal of Portfolio Management", "doi": "10.3905/jpm.2014.40.5.094", "arxiv_id": None,
            "url": "https://doi.org/10.3905/jpm.2014.40.5.094", "abstract": "", "desks": ["quant"],
            "fulltext": "free_pdf", "fetched_at": "2026-11-15T03:00:00+09:00", "status": "hold", "score": 45,
            "reasons": [{"rule": "desk_fit", "points": 25, "why": "x"}], "withdraw_flag": False, "withdraw_reason": None}
    base.update(kw)
    return base


def _lit_root(tmp_path, papers: list[dict], card: str | None = GOOD_CARD) -> Path:
    (tmp_path / "content" / "papers").mkdir(parents=True)
    (tmp_path / "content" / "papers" / "index.json").write_text(json.dumps(
        {"schema_version": 1, "rules_version": "triage-v1", "papers": papers, "sources_status": {}, "counts": {}},
        ensure_ascii=False), encoding="utf-8")
    if card is not None:
        d = tmp_path / "docs" / "desk_kb" / "lit"
        d.mkdir(parents=True)
        (d / "quant.md").write_text(card, encoding="utf-8")
    (tmp_path / "scripts").mkdir(exist_ok=True)
    (tmp_path / "scripts" / "study_rule_audit.py").write_text("# placeholder\n", encoding="utf-8")
    return tmp_path


def test_lit_check_passes_on_valid_card_and_index(tmp_path):
    root = _lit_root(tmp_path, [_paper()])
    findings = lit.check(root)
    assert [f for f in findings if f["level"] == "error"] == []
    assert lit.main(["--root", str(root), "--ci"]) == 0


def test_lit_check_warns_on_missing_field(tmp_path):
    card = GOOD_CARD.replace("  - 한계: 정규분포 가정에 기댄다.\n", "")
    root = _lit_root(tmp_path, [_paper()], card)
    warns = [f for f in lit.check(root) if f["level"] == "warning"]
    assert any("한계" in f["msg"] for f in warns)
    assert lit.main(["--root", str(root), "--ci"]) == 0  # 경고는 실패 아님


def test_lit_check_blocks_citing_withdrawn_paper(tmp_path):
    root = _lit_root(tmp_path, [_paper(withdraw_flag=True, withdraw_reason="공저자 데이터 불일치",
                                       status="rejected", score=-100)])
    assert lit.main(["--root", str(root), "--ci"]) == 1
    assert any("철회" in f["msg"] for f in lit.check(root) if f["level"] == "error")


def test_lit_check_blocks_broken_apply_path(tmp_path):
    card = GOOD_CARD.replace("scripts/study_rule_audit.py", "scripts/nope_missing.py")
    root = _lit_root(tmp_path, [_paper()], card)
    assert lit.main(["--root", str(root), "--ci"]) == 1
    assert any("적용 경로 없음" in f["msg"] for f in lit.check(root))


def test_lit_check_flags_index_status_mismatch(tmp_path):
    root = _lit_root(tmp_path, [_paper(status="summarize", score=45)])
    assert lit.main(["--root", str(root), "--ci"]) == 1


def test_lit_check_flags_withdraw_low_score(tmp_path):
    root = _lit_root(tmp_path, [_paper(withdraw_flag=True, status="rejected", score=-40)])
    assert lit.main(["--root", str(root), "--ci"]) == 1


def test_lit_check_pending_without_date(tmp_path):
    card = GOOD_CARD.replace("한계: 정규분포 가정에 기댄다.", "한계: 표본 정의 [확인 필요]")
    root = _lit_root(tmp_path, [_paper()], card)
    assert any("기한 없는" in f["msg"] for f in lit.check(root))


def test_repo_paper_lit_check_ci_passes():
    """저장소 실제 장부·lit 파일로 --ci 통과 (1주차 산출물 자체 검증)."""
    errs = [f for f in lit.check(ROOT) if f["level"] == "error"]
    assert errs == [], errs


def test_ingest_module_stdlib_only():
    """추가 패키지 0 — scripts 두 개가 표준 라이브러리만 import 하는지 소스로 확인."""
    allowed = {"__future__", "argparse", "hashlib", "html", "json", "re", "sys", "time", "urllib",
               "datetime", "pathlib", "xml", "difflib", "date", "unicodedata"}
    for name in ("papers_ingest.py", "paper_lit_check.py"):
        text = (ROOT / "scripts" / name).read_text(encoding="utf-8")
        for line in text.splitlines():
            s = line.strip()
            if s.startswith("import ") or s.startswith("from "):
                head = s.replace("from ", "").replace("import ", "").split()[0].split(".")[0]
                assert head in allowed, f"{name}: 외부 패키지 의심 {s}"
