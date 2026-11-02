"""DART 사업보고서 본문 수집기 — 네트워크 없이 샘플 XML 로 섹션 추출·표 탭 보존·보고서 선택·건너뜀 검증 (req-dev-8d32d432)."""
import io
import json
import zipfile
from pathlib import Path

from screener import dart_biz as db

SAMPLE = """<?xml version="1.0" encoding="utf-8"?>
<DOCUMENT><DOCUMENT-NAME ACODE="11011">사업보고서</DOCUMENT-NAME><BODY>
<SECTION-1 ACLASS="MANDATORY"><TITLE ATOC="Y" AASSOCNOTE="D-0-1-0-0">I. 회사의 개요</TITLE><P>회사 개요 문단</P></SECTION-1>
<SECTION-1 ACLASS="MANDATORY"><TITLE ATOC="Y" AASSOCNOTE="D-0-2-0-0">II. 사업의 내용</TITLE>
<SECTION-2><TITLE ATOC="Y">1. 사업의 개요</TITLE>
<P>당사는 &quot;엔드포인트 보안&quot; 시장에서&cr;점유율 1위입니다.</P>
<P><SPAN USERMARK="B">경쟁 현황</SPAN> 국내 경쟁사는   3개사입니다.</P>
<TABLE BORDER="1"><TBODY>
<TR><TH>구분</TH><TH>2024년</TH><TH>2025년</TH></TR>
<TR><TD>시장점유율</TD><TD>31.2%</TD><TD><P>33.5%</P></TD></TR>
</TBODY></TABLE>
</SECTION-2>
<SECTION-2><TITLE ATOC="Y">2. 주요 제품 및 서비스</TITLE><P>V3 제품군 매출 비중 60%</P><IMAGE><IMG>x.jpg</IMG></IMAGE></SECTION-2>
</SECTION-1>
<SECTION-1><TITLE ATOC="Y">III. 재무에 관한 사항</TITLE><P>재무 문단(들어오면 안 됨)</P></SECTION-1>
</BODY></DOCUMENT>"""


def test_section_extract_and_table_tabs():
    sec = db.biz_section(SAMPLE)
    assert sec is not None
    t = db.xml_to_text(sec)
    assert t.startswith("II. 사업의 내용")
    assert "1. 사업의 개요" in t and "2. 주요 제품 및 서비스" in t
    assert '"엔드포인트 보안" 시장에서\n점유율 1위입니다.' in t            # 엔티티·&cr; 처리
    assert "경쟁 현황 국내 경쟁사는 3개사입니다." in t                    # 태그 제거·공백 정리
    assert "구분\t2024년\t2025년" in t.splitlines()                       # 표 = 행 한 줄, 칸 탭
    assert "시장점유율\t31.2%\t33.5%" in t.splitlines()
    assert "재무 문단" not in t and "회사 개요 문단" not in t and "<" not in t and "x.jpg" not in t


def test_section_missing_and_fallback_without_section_tags():
    assert db.biz_section("<DOCUMENT><TITLE>I. 회사의 개요</TITLE></DOCUMENT>") is None
    flat = "<TITLE>Ⅱ. 사업의 내용</TITLE><P>본문 A</P><TITLE>Ⅲ. 재무에 관한 사항</TITLE><P>본문 B</P>"
    t = db.xml_to_text(db.biz_section(flat))
    assert "본문 A" in t and "본문 B" not in t


def test_nested_table_rows_survive():
    x = ("<SECTION-1><TITLE>II. 사업의 내용</TITLE><TABLE><TR><TD>바깥</TD><TD>"
         "<TABLE><TR><TD>안1</TD><TD>안2</TD></TR></TABLE></TD></TR></TABLE></SECTION-1>")
    t = db.xml_to_text(db.biz_section(x))
    assert "안1\t안2" in t.splitlines() and "바깥" in t


def _zip(files: dict[str, str], enc="utf-8") -> bytes:
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        for n, s in files.items():
            z.writestr(n, s.encode(enc))
    return b.getvalue()


def test_extract_from_zip_prefers_main_and_handles_cp949():
    rn = "20260310000123"
    audit = "<DOCUMENT><TITLE>감사보고서</TITLE></DOCUMENT>"
    t = db.extract_from_zip(_zip({f"{rn}_00760.xml": audit, f"{rn}.xml": SAMPLE}), rn)
    assert t and "시장점유율\t31.2%\t33.5%" in t
    cp = SAMPLE.replace('encoding="utf-8"', 'encoding="euc-kr"')
    assert "점유율 1위" in db.extract_from_zip(_zip({f"{rn}.xml": cp}, enc="cp949"), rn)
    assert db.extract_from_zip(_zip({f"{rn}.xml": audit}), rn) is None


def test_pick_reports_latest_annual_and_newer_half():
    rows = [
        {"report_nm": "사업보고서 (2024.12)", "rcept_no": "20250312000001", "rcept_dt": "20250312"},
        {"report_nm": "[기재정정]사업보고서 (2025.12)", "rcept_no": "20260320000002", "rcept_dt": "20260320"},
        {"report_nm": "분기보고서 (2026.03)", "rcept_no": "20260515000003", "rcept_dt": "20260515"},
        {"report_nm": "반기보고서 (2025.06)", "rcept_no": "20250814000004", "rcept_dt": "20250814"},
        {"report_nm": "반기보고서 (2026.06)", "rcept_no": "20260814000005", "rcept_dt": "20260814"},
    ]
    got = db.pick_reports(rows)
    assert [(r["kind"], r["rcept_no"]) for r in got] == [("사업", "20260320000002"), ("반기", "20260814000005")]
    # 반기가 사업보고서보다 옛것이면 사업보고서만
    assert [r["kind"] for r in db.pick_reports(rows[:2] + rows[3:4])] == ["사업"]


def test_update_skips_known_rcept_and_writes_index(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "OUT", tmp_path)
    monkeypatch.setattr(db, "INDEX", tmp_path / "index.json")
    monkeypatch.setenv("DART_API_KEY", "x")
    monkeypatch.setattr("screener.fin.corp_codes", lambda: {"053800": "00100000"})
    old = "20250312000001"
    (tmp_path / f"053800_{old}.txt").write_text("옛것")
    (tmp_path / "index.json").write_text(json.dumps({"items": [
        {"code": "053800", "name": "안랩", "rcept_no": "20260814000005", "report": "반기보고서 (2026.06)", "kind": "반기",
         "date": "20260814", "chars": 10, "status": "ok", "parser": db.PARSER},
        {"code": "053800", "name": "안랩", "rcept_no": old, "report": "사업보고서 (2024.12)", "kind": "사업",
         "date": "20250312", "chars": 3, "status": "ok"}]}))
    rows = [{"corp_name": "안랩", "report_nm": "사업보고서 (2025.12)", "rcept_no": "20260320000002", "rcept_dt": "20260320"},
            {"corp_name": "안랩", "report_nm": "반기보고서 (2026.06)", "rcept_no": "20260814000005", "rcept_dt": "20260814"}]
    calls = []

    def fake_get(path, params, bud, binary=False):
        bud.take()
        calls.append(path)
        if path == "list.json":
            return {"status": "000", "list": rows}
        return _zip({f"{params['rcept_no']}.xml": SAMPLE})

    monkeypatch.setattr(db, "_get", fake_get)
    st = db.update(["053800", "999999"], sleep=0)
    assert calls == ["list.json", "document.xml"]                   # 반기(이미 있음)는 건너뜀
    assert st["new"] == 1 and st["skip"] == 1 and st["no_corp"] == 1
    ix = json.loads((tmp_path / "index.json").read_text())
    assert {r["rcept_no"] for r in ix["items"]} == {"20260320000002", "20260814000005"}   # 옛 사업보고서 정리
    assert not (tmp_path / f"053800_{old}.txt").exists()
    body = (tmp_path / "053800_20260320000002.txt").read_text()
    assert body.splitlines()[0].startswith("# 안랩 (053800) · 사업보고서 (2025.12)") and "점유율 1위" in body
    r = next(r for r in ix["items"] if r["rcept_no"] == "20260320000002")
    assert set(r) >= {"code", "name", "rcept_no", "report", "date", "chars"} and r["chars"] > 50


def test_budget_stops_cleanly(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "OUT", tmp_path)
    monkeypatch.setattr(db, "INDEX", tmp_path / "index.json")
    monkeypatch.setenv("DART_API_KEY", "x")
    monkeypatch.setattr("screener.fin.corp_codes", lambda: {"053800": "1", "263860": "2"})

    def fake_get(path, params, bud, binary=False):
        bud.take()
        return {"status": "013", "list": []}

    monkeypatch.setattr(db, "_get", fake_get)
    st = db.update(["053800", "263860"], max_calls=1, sleep=0)
    assert st["api_calls"] == 1 and "예산" in st["stopped"]
    assert json.loads((tmp_path / "index.json").read_text())["last_run"]["no_report"] == 1


def test_library_kept_and_img_without_selfclose_does_not_eat_text():
    """11/1 첫 실행: LIBRARY 묶음을 그림처럼 지워 13/14 '사업의 내용' 누락 + <IMG> 가 다음 '/>' 까지 본문을 삼킴."""
    x = ("<SECTION-1><TITLE>II. 사업의 내용</TITLE><LIBRARY><SECTION-2><TITLE>1. 사업의 개요</TITLE>"
         "<P>점유율 서술</P></SECTION-2></LIBRARY><P><IMG USEMAP=\"a\">pic.jpg</IMG>그림 뒤 문단</P>"
         "<TABLE-GROUP><TABLE><TR><TD>가</TD><TD>나</TD></TR></TABLE></TABLE-GROUP><PGBRK/>"
         "<P>마지막 문단</P></SECTION-1>")
    t = db.xml_to_text(db.biz_section(x))
    assert "1. 사업의 개요" in t and "점유율 서술" in t and "그림 뒤 문단" in t and "마지막 문단" in t
    assert "가\t나" in t.splitlines() and "pic.jpg" not in t


def test_old_parser_failures_are_retried(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "OUT", tmp_path)
    monkeypatch.setattr(db, "INDEX", tmp_path / "index.json")
    monkeypatch.setenv("DART_API_KEY", "x")
    monkeypatch.setattr("screener.fin.corp_codes", lambda: {"053800": "1"})
    rn = "20260320000868"
    (tmp_path / "index.json").write_text(json.dumps({"items": [
        {"code": "053800", "name": "안랩", "rcept_no": rn, "report": "사업보고서 (2025.12)", "kind": "사업",
         "date": "20260320", "chars": 0, "status": "no_section"}]}))      # parser 키 없음 = 버전 1

    def fake_get(path, params, bud, binary=False):
        bud.take()
        if path == "list.json":
            return {"list": [{"corp_name": "안랩", "report_nm": "사업보고서 (2025.12)", "rcept_no": rn, "rcept_dt": "20260320"}]}
        return _zip({f"{rn}.xml": SAMPLE})

    monkeypatch.setattr(db, "_get", fake_get)
    assert db.update(["053800"], sleep=0)["new"] == 1
    items = json.loads((tmp_path / "index.json").read_text())["items"]
    assert len(items) == 1 and items[0]["status"] == "ok" and items[0]["parser"] == db.PARSER


def test_single_cell_box_keeps_paragraph_breaks():
    x = ("<SECTION-1><TITLE>II. 사업의 내용</TITLE><TABLE><TR><TD><P>나. 회사의 현황</P><P>(1) 영업 개황</P>"
         "<P>점유율 1위</P></TD></TR></TABLE></SECTION-1>")
    lines = db.xml_to_text(db.biz_section(x)).splitlines()
    assert "나. 회사의 현황" in lines and "(1) 영업 개황" in lines and "점유율 1위" in lines


def test_time_budget_stops_and_saves(tmp_path, monkeypatch):
    """11/1 전 체인 실행 53분+ — job 60분 한도 전에 받은 만큼 저장하고 끊는다(stopped='time budget')."""
    monkeypatch.setattr(db, "OUT", tmp_path)
    monkeypatch.setattr(db, "INDEX", tmp_path / "index.json")
    monkeypatch.setenv("DART_API_KEY", "x")
    monkeypatch.setattr("screener.fin.corp_codes", lambda: {"053800": "1", "263860": "2", "042510": "3"})
    clock = [0.0]
    monkeypatch.setattr(db, "_now", lambda: clock[0])
    calls = []

    def fake_get(path, params, bud, binary=False):
        bud.take()
        calls.append(path)
        clock[0] += 10 * 60                                        # 호출마다 10분 흐른 셈
        if path == "list.json":
            rn = {"1": "20260320000001", "2": "20260320000002", "3": "20260320000003"}[params.get("corp_code", "1")]
            return {"list": [{"corp_name": "x", "report_nm": "사업보고서 (2025.12)", "rcept_no": rn, "rcept_dt": "20260320"}]}
        return _zip({f"{params['rcept_no']}.xml": SAMPLE})

    monkeypatch.setattr(db, "_get", fake_get)
    monkeypatch.setattr(db, "list_reports", lambda cc, bud, days=560: fake_get("list.json", {"corp_code": cc}, bud)["list"])
    st = db.update(["053800", "263860", "042510"], sleep=0, max_minutes=35)
    assert st["stopped"] == "time budget"
    assert st["new"] == 2 and calls == ["list.json", "document.xml"] * 2      # 40분 시점에서 셋째 종목 전 중단
    assert st["done_codes"] == 2 and st["remaining"] == 1
    ix = json.loads((tmp_path / "index.json").read_text())
    assert len(ix["items"]) == 2 and ix["last_run"]["stopped"] == "time budget"
    assert (tmp_path / "053800_20260320000001.txt").exists()


def test_missing_from_file_skips_indexed(tmp_path, monkeypatch):
    ix = tmp_path / "index.json"
    ix.write_text(json.dumps({"items": [{"code": "005930", "rcept_no": "1"}]}), encoding="utf-8")
    monkeypatch.setattr(db, "INDEX", ix)
    f = tmp_path / "t.txt"
    f.write_text("# 주석\n005930\n010690  # 화신\n\n036010\n010690\n", encoding="utf-8")
    assert db.missing_from_file(f) == ["010690", "036010"]


def test_file_all_done_does_nothing(tmp_path, monkeypatch):
    ix = tmp_path / "index.json"
    ix.write_text(json.dumps({"items": [{"code": "005930", "rcept_no": "1"}]}), encoding="utf-8")
    monkeypatch.setattr(db, "INDEX", ix)
    f = tmp_path / "t.txt"
    f.write_text("005930\n", encoding="utf-8")
    monkeypatch.setattr(db, "update", lambda *a, **k: (_ for _ in ()).throw(AssertionError("update 호출 안 돼야 함")))
    monkeypatch.setattr(db, "default_codes", lambda *a, **k: (_ for _ in ()).throw(AssertionError("기본 대상으로 넘어가면 안 됨")))
    assert db.main(["--file", str(f)]) == 0
    assert "last_run" not in json.loads(ix.read_text(encoding="utf-8"))


def test_parallel_workers_and_latest_only(tmp_path, monkeypatch):
    """11/1 '오픈API인데 왜 느려' — 본문 동시 받기(workers)와 최신 1건만(latest_only)이 순차 결과와 같은 색인을 만든다."""
    monkeypatch.setattr(db, "OUT", tmp_path)
    monkeypatch.setattr(db, "INDEX", tmp_path / "index.json")
    monkeypatch.setenv("DART_API_KEY", "x")
    codes = [f"0000{i:02d}" for i in range(1, 8)]
    monkeypatch.setattr("screener.fin.corp_codes", lambda: {c: c for c in codes if c != "000004"})
    calls = []

    def fake_get(path, params, bud, binary=False):
        bud.take()
        calls.append(path)
        if path == "list.json":
            c = params["corp_code"]
            return {"status": "000", "list": [
                {"corp_name": c, "report_nm": "사업보고서 (2025.12)", "rcept_no": f"{c}A", "rcept_dt": "20260320"},
                {"corp_name": c, "report_nm": "반기보고서 (2026.06)", "rcept_no": f"{c}H", "rcept_dt": "20260814"}]}
        return _zip({f"{params['rcept_no']}.xml": SAMPLE})

    monkeypatch.setattr(db, "_get", fake_get)
    st = db.update(codes, sleep=0, workers=3, latest_only=True)
    assert st["new"] == 6 and st["no_corp"] == 1 and st["done_codes"] == 7 and st["remaining"] == 0
    assert calls.count("document.xml") == 6 and st["api_calls"] == 12
    items = json.loads((tmp_path / "index.json").read_text())["items"]
    assert sorted(r["rcept_no"] for r in items) == sorted(f"{c}H" for c in codes if c != "000004")   # 반기만


def test_supply_targets_include_hwashin_abico():
    """11/1 겸이 '하청까지' 예시 2종목 — 수집 대상 목록·확장 이름 사전에 있어야 공급망 자동 추출에 잡힘(req-dev-786a95ac)."""
    root = Path(__file__).resolve().parents[1]
    lines = [ln.split("#", 1)[0].strip() for ln in (root / "data/dart_biz/targets_supply.txt").read_text(encoding="utf-8").splitlines()]
    assert {"010690", "036010"} <= set(lines)
    names = json.loads((root / "data/flows/names.json").read_text(encoding="utf-8"))
    assert names["010690"] == "화신" and names["036010"] == "아비코전자"      # 아비코전자는 peers_KR 밖 — 이름 사전이 2차 확장 목록


def test_code_gs_company_links_getters():
    """RESEARCH › 관계도 getter 가 Code.gs 에 build_pages.py 와 같은 파일로 있다(req-dev-23c7fc19)."""
    root = Path(__file__).resolve().parents[1]
    gs = (root / "apps-script/Code.gs").read_text(encoding="utf-8")
    assert "function getCompanyLinks() { return raw_('reports/company_links.json'); }" in gs
    assert "function getCompanyLinksAuto() { return raw_('reports/company_links_auto.json'); }" in gs
