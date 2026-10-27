"""공공 리포트 트래커·Jiang 피드(screener/public_reports) + 리서치 종합 카드 — 합성 데이터, 네트워크 없음."""
from datetime import date
from pathlib import Path

from screener import public_reports as pr
from screener import research_synthesis as rs

RSS = """<?xml version="1.0" encoding="UTF-8"?><rss><channel>
<item><title>Minutes of the Federal Open Market Committee, September 16-17, 2026</title><link>https://fed/m1</link>
<pubDate>Wed, 08 Oct 2026 18:00:00 GMT</pubDate><description>&lt;p&gt;The Federal Reserve released minutes&lt;/p&gt;</description></item>
<item><title>Federal Reserve Board announces enforcement action</title><link>https://fed/x</link><pubDate>Thu, 09 Oct 2026 18:00:00 GMT</pubDate></item>
</channel></rss>"""
ATOM = """<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom" xmlns:yt="http://www.youtube.com/xml/schemas/2015" xmlns:media="http://search.yahoo.com/mrss/">
<entry><yt:videoId>abc</yt:videoId><title>Game Theory #12: Why Iran and Israel Go to War</title>
<link rel="alternate" href="https://www.youtube.com/watch?v=abc"/><published>2026-10-18T12:00:00+00:00</published>
<media:group><media:title>t</media:title><media:description>In this lecture we use game theory to explain the war.</media:description></media:group></entry>
</feed>"""
HTML = """<ul><li><a href="/portal/view.do?id=1">2026년 9월 소비자동향조사 결과</a><span>2026.09.24</span></li>
<li><a href="/portal/view.do?id=2">금융안정보고서(2026년 6월)</a><span>2026-06-25</span></li><li><a href="/m">메뉴</a></li></ul>"""
BOK = next(s for s in pr.SOURCES if s["id"] == "bok_press")
FED = next(s for s in pr.SOURCES if s["id"] == "fed")


def test_parse_and_classify():
    rows = pr.classify(FED, pr.parse_feed(RSS))
    assert len(rows) == 1 and rows[0]["series"] == "FOMC 의사록" and rows[0]["date"] == date(2026, 10, 8)
    assert rows[0]["summary"] == "The Federal Reserve released minutes"
    h = pr.classify(BOK, pr.parse_html_list(HTML, "https://www.bok.or.kr/portal/list.do"))
    assert [r["series"] for r in h] == ["소비자동향조사(CSI)", "금융안정보고서"]
    assert h[0]["link"] == "https://www.bok.or.kr/portal/view.do?id=1" and h[1]["date"] == date(2026, 6, 25)


def test_fetch_manual_and_error():
    kofia = next(s for s in pr.SOURCES if s["id"] == "kofia")
    assert pr.fetch_source(kofia)[1]["status"] == "manual"

    def boom(u):
        raise OSError("blocked")
    rows, st = pr.fetch_source(FED, get=boom)
    assert rows == [] and st["status"] == "error" and "blocked" in st["reason"]
    rows, st = pr.fetch_source(FED, get=lambda u: RSS)
    assert st["status"] == "ok" and st["n"] == 2   # 피드 2개가 같은 응답 → 병합 단계에서 중복 제거


def test_merge_backfill_rule():
    t = date(2026, 10, 21)
    new = [{"title": "a", "date": date(2026, 10, 20), "series": "s"}, {"title": "b", "date": date(2026, 9, 1), "series": "s"}]
    items, added = pr.merge([], new, "fed", "Fed", "해외", "2026-10-21 03:30", t)
    assert added == 0 and all(i["collected_at"].startswith("backfill") for i in items)   # 첫 수집 = 전부 백필
    items, added = pr.merge(items, new + [{"title": "c", "date": date(2026, 10, 20), "series": "s"},
                                          {"title": "d", "date": date(2026, 9, 2), "series": "s"}], "fed", "Fed", "해외", "x", t)
    assert added == 1 and len(items) == 4 and items[-1]["collected_at"].startswith("backfill")   # 14일 지난 새 행 = 백필


def test_next_expected():
    ser = [("금융안정보고서", "", [6, 12]), ("국제수지", "", pr.M), ("이슈노트", "", None)]
    nx = {x["series"]: x["next"] for x in pr.next_expected(ser, {"국제수지": date(2026, 10, 8)}, date(2026, 10, 21))}
    assert nx == {"금융안정보고서": "2026-12", "국제수지": "2026-11"}


def test_jiang_feed_and_ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(pr, "JIANG", tmp_path / "jiang.json")
    monkeypatch.setattr(pr, "JIANG_PRED", tmp_path / "jiang_predictions.json")
    monkeypatch.setattr(pr, "VIEWS", tmp_path)
    page = '<meta itemprop="identifier"><script>{"externalId":"UC1234567890123456789012"}</script>'
    j = pr.run_jiang(get=lambda u: page if "@" in u else ATOM, now="n", today=date(2026, 10, 21))
    assert j["channel_id"] == "UC1234567890123456789012" and j["status"]["status"] == "ok"
    v = j["videos"][0]
    assert v["tags"] == ["중동", "전쟁", "게임이론"] and v["collected_at"].startswith("backfill")
    assert "참고 뷰" in j["grade"] and set(v) == {"date", "title", "link", "tags", "desc", "collected_at"}   # 전사 없음, 설명 발췌만
    assert v["desc"].startswith("In this lecture") and len(v["desc"]) <= 500
    # 기존 영상(설명 없던 행)도 피드에 남아 있으면 desc 채움 — 이미 있는 desc 는 덮지 않음
    import json as _j
    old = dict(j, videos=[dict(v, desc=None)])
    (tmp_path / "jiang.json").write_text(_j.dumps(old), encoding="utf-8")
    j2 = pr.run_jiang(get=lambda u: ATOM, now="m", today=date(2026, 10, 22))
    assert j2["videos"][0]["desc"].startswith("In this lecture") and j2["videos"][0]["collected_at"].startswith("backfill")
    assert pr.ensure_ledger() and not pr.ensure_ledger()
    import json
    led = json.loads((tmp_path / "jiang_predictions.json").read_text(encoding="utf-8"))
    assert led["predictions"] == [] and led["fields"]["verdict"].startswith("null")


def test_synthesis_cards():
    t = date(2026, 10, 21)
    pub = pr.build_output([{"key": "1", "src": "bok_press", "group": "한은", "inst": "한국은행", "series": "국제수지",
                            "title": "2026년 8월 국제수지(잠정)", "date": "2026-10-17", "link": "l", "collected_at": "x"}],
                          {"bok_press": {"status": "ok", "n": 1}}, t, "n")
    c = rs.public_card(pub, t)
    assert c["groups"][0]["n30"] == 1 and c["new7"][0]["series"] == "국제수지"
    assert any(x["series"] == "금융안정보고서" and x["next"] == "2026-12" for x in c["calendar"])
    assert c["sources"]["ok"] == 1 and c["sources"]["미실행"] == len(pr.SOURCES) - 1
    assert rs.public_card(None, t)["status"] == "없음" and rs.geo_card(None)["videos"] == []


def test_digest_card_three_fields():
    """STANDARD §4(10/23 겸이): 외부 자료는 요약·뷰·우리 해석 세 칸 — 하나라도 비면 카드에 안 나간다(링크만 금지)."""
    full = {"id": "a", "src": "bok_press", "date": "2026-10-22", "title": "t", "link": "l", "summary": ["s"], "view": "v",
            "our_take": "o", "grade": "B", "by": "애널", "written_at": "w"}
    dg = {"updated": "u", "items": [full, dict(full, id="b", our_take=""), dict(full, id="c", src="jiang", date="2026-10-11"),
                                    dict(full, id="d", date="2026-10-01")]}
    c = rs.digest_card(dg)
    assert [i["id"] for i in c["public"]] == ["a", "d"] and [i["id"] for i in c["geo"]] == ["c"]
    assert rs.digest_card(None)["status"] == "없음"


def test_digest_file_schema():
    """reports/views/digest.json — 항목마다 세 칸 + 작성자·시각, 재료 없음은 정직하게 표시."""
    import json
    from pathlib import Path
    d = json.loads((Path(__file__).resolve().parents[1] / "reports/views/digest.json").read_text(encoding="utf-8"))
    for i in d["items"]:
        assert all(i.get(k) for k in ("id", "src", "date", "title", "link", "summary", "view", "our_take", "grade", "by", "written_at")), i["id"]
        assert isinstance(i["summary"], list) and len(i["summary"]) <= 5
        assert i["status"] == "ok" or "재료 없음" in i["summary"][0]


def test_fix_link_known_broken():
    """10/23 매크로 확인: 한은 RSS 링크 menuNo 빈칸 → 404, 기재부 mofe.go.kr(www 없음) → DNS 실패."""
    assert pr.fix_link("https://www.bok.or.kr/portal/bbs/B0000245/view.do?nttId=1&menuNo=").endswith("menuNo=200761")
    assert pr.fix_link("http://mofe.go.kr/nw/x.do?a=1") == "https://www.mofe.go.kr/nw/x.do?a=1"
    assert pr.fix_link("https://fed/m1") == "https://fed/m1" and pr.fix_link(None) is None


def test_public_items30_one_line_first_and_pending():
    """공공 리포트 카드(10/23 겸이 "우리 요약/뷰를 더 앞으로"): 30일 발간물마다 digest 연결 — 3종+한 줄 뷰 있으면 ok, 없으면 '요약 대기'."""
    t = date(2026, 10, 23)
    rows = [{"key": "k1", "src": "fed", "group": "해외", "inst": "Fed", "series": "FOMC 의사록", "title": "Minutes", "date": "2026-10-07",
             "link": "l1", "collected_at": "x"},
            {"key": "k2", "src": "bok_press", "group": "한은", "inst": "한국은행", "series": "금통위 의사록", "title": "의사록", "date": "2026-10-13",
             "link": "https://www.bok.or.kr/v.do?menuNo=", "collected_at": "x"},
            {"key": "old", "src": "bok_press", "group": "한은", "inst": "한국은행", "series": "국제수지", "title": "옛것", "date": "2026-08-01",
             "link": "l", "collected_at": "x"}]
    pub = pr.build_output(rows, {}, t, "n")
    full = {"summary": ["s"], "view": "v", "our_take": "o", "one_line": "한 줄", "grade": "A", "confidence": "중", "source_checked": "원문 확인"}
    dg = {"items": [dict(full, id="k1", src="fed", date="2026-10-07", title="FOMC 의사록"),
                    dict(full, id="k2", src="bok_press", date="2026-10-13", one_line=""),            # 한 줄 뷰 없음 → 대기
                    dict(full, id="aud", src="bok_audit", date="2026-10-23", title="국감 발언", link="la"),  # 수집 밖 1차 자료
                    dict(full, id="j", src="jiang", date="2026-10-20")]}                           # 지정학 영상은 이 카드 아님
    c = rs.public_card(pub, t, dg)
    assert [r["id"] for r in c["items30"]] == ["aud", "k2", "k1"] and c["pending_n"] == 1
    k1 = c["items30"][2]
    assert k1["status"] == "ok" and k1["one_line"] == "한 줄" and k1["inst"] == "Fed" and k1["link"] == "l1" and k1["title"] == "FOMC 의사록"
    assert c["items30"][1]["status"] == "요약 대기" and "one_line" not in c["items30"][1]
    assert c["items30"][1]["link"].endswith("menuNo=200761")   # 저장된 깨진 링크도 build_output 이 보정
    assert c["items30"][0]["inst"] == "한국은행"
    assert [p["key"] for p in pr.pending(pub, dg, t)] == ["k2"]
    assert rs.public_card(None, t)["items30"] == []


def test_digest_public_items_have_one_line():
    """digest.json 공공 리포트 항목 = 한 줄 뷰·신뢰도·원문 확인 여부 필수(매크로 KB '공공 리포트 3종 작성 규칙')."""
    import json
    from pathlib import Path
    d = json.loads((Path(__file__).resolve().parents[1] / "reports/views/digest.json").read_text(encoding="utf-8"))
    pub = [i for i in d["items"] if i["src"] != "jiang"]
    assert pub
    for i in pub:
        assert i.get("one_line") and i.get("confidence") in ("상", "중", "하") and i.get("source_checked"), i["id"]
        assert ("원문 확인" in i["source_checked"]) or ("미확인" in i["source_checked"] and "검증전" in i["source_checked"]), i["id"]


# ── 한은 조사연구 목록(BOK 이슈노트·경제연구) · KCMI 목록 — 저장 HTML 픽스처(2026-10-26 접속 발췌) ──
FIX = Path(__file__).parent / "fixtures" / "public_reports"


def test_bok_issue_note_list_fixture():
    rows = pr.parse_bok_list((FIX / "bok_issue_list.html").read_text(encoding="utf-8"))
    assert [r["date"] for r in rows] == [date(2026, 10, 26), date(2026, 10, 6), date(2026, 9, 15)]
    r = rows[0]
    assert r["title"] == "[제2026-27호] 청년고용 부진 및 정책 과제" and r["series"] == "BOK 이슈노트" and r["depart"] == "고용동향팀"
    assert r["link"] == "https://www.bok.or.kr/portal/bbs/P0002353/view.do?nttId=11065913&menuNo=200433"


def test_bok_research_series_by_board():
    rows = pr.parse_bok_list((FIX / "bok_research_list.html").read_text(encoding="utf-8"))
    assert [r["series"] for r in rows] == ["BOK 경제연구(국문)", "BOK 경제연구(영문)"]
    assert rows[0]["date"] == date(2026, 10, 1) and rows[1]["depart"] == "경제안보연구실"
    assert pr.parse_bok_list('<li class="bbsRowCls"><a href="/portal/bbs/B0000502/view.do?nttId=1" class="title">보도</a></li>') == []   # 모르는 게시판 버림


def test_bok_view_meta_and_gist():
    v = pr.parse_bok_view((FIX / "bok_issue_view.html").read_text(encoding="utf-8"))
    assert v["pdf"].startswith("https://www.bok.or.kr/fileSrc/portal/") and v["pdf"].endswith(".pdf") and "token" not in v["pdf"]
    assert v["kind"] == "경제일반" and v["depart"] == "고용동향팀"
    assert v["gist"].startswith("팬데믹 이후") and v["gist"].endswith("다.") and len(v["gist"]) <= 200


def test_bok_research_source_end_to_end():
    src = next(s for s in pr.SOURCES if s["id"] == "bok_research")
    lst, view = (FIX / "bok_issue_list.html").read_text(encoding="utf-8"), (FIX / "bok_issue_view.html").read_text(encoding="utf-8")
    rows, st = pr.fetch_source(src, get=lambda u: view if "view.do" in u else lst)
    assert st["status"] == "ok" and rows[0]["pdf"] and rows[0]["summary_src"] == "한은 게시 요지 첫 문장"
    items, _ = pr.merge([], rows, "bok_research", "한국은행", "한은", "x", date(2026, 10, 26))
    assert items[0]["series"] == "BOK 이슈노트" and items[0]["pdf"] and items[0]["depart"] == "고용동향팀"
    items2, _ = pr.merge([dict(i, pdf=None) for i in items], rows, "bok_research", "한국은행", "한은", "y", date(2026, 10, 27))
    assert len(items2) == len(items) and items2[0]["pdf"]   # 이미 있는 행은 빈 메타만 채움


def test_kcmi_list_skips_hashtags():
    rows = pr.parse_kcmi_list((FIX / "kcmi_list.html").read_text(encoding="utf-8"))
    assert [r["title"] for r in rows] == ["임팩트투자 생태계 현황과 과제", "미국 사모신용시장의 건전성, 유동성 및 시스템리스크"]
    assert rows[1]["link"] == "https://www.kcmi.re.kr/report/report_view?report_no=2337" and rows[1]["date"] == date(2026, 10, 12)
    assert not any(r["title"].startswith("#") for r in rows)


def test_bok_view_author_paragraph():
    v = pr.parse_bok_view('<dd class="depart">거시경제연구실(02-1)</dd><div class="dbdata "><p>저자: 최영준(한국은행)</p>'
                          '<p>본 연구는 환율급등 경험을 분석한다. 둘째 문장.</p></div>')
    assert v["author"] == "최영준(한국은행)" and v["gist"] == "본 연구는 환율급등 경험을 분석한다." and v["depart"] == "거시경제연구실"


def test_public_card_carries_pdf_and_bok_gist():
    pub = {"items": [{"key": "k", "src": "bok_research", "group": "한은", "inst": "한국은행", "series": "BOK 이슈노트", "title": "[제2026-27호] t",
                      "date": "2026-10-26", "link": "l", "pdf": "https://www.bok.or.kr/fileSrc/x.pdf", "summary": "요지 문장이다.",
                      "summary_src": "한은 게시 요지 첫 문장", "collected_at": "x"}], "calendar": [], "sources": []}
    row = rs.public_card(pub, date(2026, 10, 26))["items30"][0]
    assert row["pdf"].endswith(".pdf") and row["src_gist"] == "요지 문장이다." and row["status"] == "요약 대기"


# ── 국제금융센터(KCIF) 목록 — 저장 HTML 축약 픽스처(2026-10-27 접속 발췌, 10/27 겸이 "앞으로 저것도 트래킹할 수 있나?") ──
KCIF_SRC = next(s for s in pr.SOURCES if s["id"] == "kcif")


def _kcif_get(u):
    name = "daily" if "dailyList" in u else "analysis" if "analysisList" in u else "brief"
    return (FIX / f"kcif_{name}_list.html").read_text(encoding="utf-8")


def test_kcif_daily_list_series_by_topic_tab():
    rows = pr.parse_kcif_list(_kcif_get("dailyList"), "https://www.kcif.or.kr/annual/dailyList?pp=20")
    assert [r["rpt_no"] for r in rows] == ["37642", "37639", "37632"]
    r = rows[0]
    assert r["title"] == "최근 국내 주가 변동성 확대에 대한 해외시각(10.27)" and r["date"] == date(2026, 10, 27)
    assert r["series"] == "특별일보·주가 급락 해외시각" and r["author"] == "이다영" and r["kind"] is None
    assert r["link"] == "https://www.kcif.or.kr/annual/reportView?rpt_no=37642&mn=001005&pe=002015"   # 검색·페이지 꼬리 제거


def test_kcif_analysis_and_brief_boards():
    a = pr.parse_kcif_list(_kcif_get("analysisList"), "https://www.kcif.or.kr/analysis/analysisList?pp=20")
    assert a[0]["series"] == "분석보고서" and a[0]["kind"] == "주식" and a[0]["title"] == "AI 생태계 내 순환금융 현황 및 리스크 점검"
    assert a[0]["link"] == "https://www.kcif.or.kr/finance/financeView?rpt_no=37631&mn=002004" and a[0]["date"] == date(2026, 10, 23)
    b = pr.parse_kcif_list(_kcif_get("briefList"), "https://www.kcif.or.kr/brief/briefList?pp=20")
    assert b[0]["series"] == "이슈브리핑" and b[0]["kind"] == "신흥국" and b[0]["author"] == "김기봉,이윤탁"
    sp = [r for r in b if r["rpt_no"] == "37600"][0]   # 이슈브리핑 목록에 섞여 나온 특별일보 = 링크(mn·pe) 기준 특별일보
    assert sp["series"] == "특별일보·주가 급락 해외시각" and sp["kind"] is None
    assert pr.parse_kcif_list('<ul class="page_list"><li><div class="tit_box">메뉴</div></li></ul>') == []


def test_kcif_source_fetch_merge_and_failure():
    rows, st = pr.fetch_source(KCIF_SRC, get=_kcif_get)
    assert st["status"] == "ok" and st["n"] == len(rows) == 3 + 2 + 6
    items, _ = pr.merge([], rows, "kcif", "국제금융센터", "정부·연구기관", "x", date(2026, 10, 27))
    assert len(items) == len({r["rpt_no"] for r in rows})   # 게시판 간 겹친 발간물은 한 행
    assert items[0]["rpt_no"] == "37642" and items[0]["series"].startswith("특별일보")

    def blocked(u):   # Actions(해외 IP) 차단 가정 — 조용히 error 상태만 남기고 다른 소스 수집은 계속
        raise OSError("403 Forbidden")
    rows, st = pr.fetch_source(KCIF_SRC, get=blocked)
    assert rows == [] and st["status"] == "error" and "www.kcif.or.kr" in st["reason"]


def test_kcif_digest_written_before_collection_is_not_pending():
    """애널이 10/27 먼저 요약한 rpt_no=37642(digest id kcif_kospi_vol_20261027)는 수집 key 가 달라도 같은 링크면 요약 있음."""
    rows, _ = pr.fetch_source(KCIF_SRC, get=_kcif_get)
    items, _ = pr.merge([], rows, "kcif", "국제금융센터", "정부·연구기관", "x", date(2026, 10, 27))
    t = date(2026, 10, 27)
    pub = pr.build_output(items, {"kcif": {"status": "ok", "n": len(items)}}, t, "n")
    full = {"summary": ["s"], "view": "v", "our_take": "o", "one_line": "한 줄", "grade": "B", "confidence": "중", "source_checked": "원문 확인"}
    dg = {"items": [dict(full, id="kcif_kospi_vol_20261027", src="kcif", date="2026-10-27", title="[국제금융센터 특별일보] 해외시각(10.27)",
                         link="https://www.kcif.or.kr/annual/reportView?rpt_no=37642&mn=001005&pe=002015")]}
    todo = {p["key"] for p in pr.pending(pub, dg, t)}
    assert len(todo) == len(items) - 1 and not any(i["rpt_no"] == "37642" and i["key"] in todo for i in items)
    c = rs.public_card(pub, t, dg)
    hit = [r for r in c["items30"] if r["link"].endswith("rpt_no=37642&mn=001005&pe=002015")]
    assert len(hit) == 1 and hit[0]["status"] == "ok" and hit[0]["one_line"] == "한 줄"   # 두 번 안 나옴
    assert c["pending_n"] == len(items) - 1


def test_real_digest_covers_kcif_37642():
    """실제 digest.json 에 rpt_no=37642 요약이 있다 — 첫 수집 날 '요약 대기'로 중복 표시되지 않는 근거."""
    import json
    d = json.loads((Path(__file__).resolve().parents[1] / "reports/views/digest.json").read_text(encoding="utf-8"))
    hit = pr.digest_for(pr.digest_index(d), {"key": "x", "link": "https://www.kcif.or.kr/annual/reportView?rpt_no=37642&mn=001005&pe=002015"})
    assert hit["id"] == "kcif_kospi_vol_20261027"
