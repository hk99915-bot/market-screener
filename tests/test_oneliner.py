"""종목 한 줄 설명(screener/oneliner.py) — 네트워크 없이: KIND 표 파싱·유형 줄·첫 문장·규칙 검사·증분·병합·저장소 파일·화면 배선."""
import json
from datetime import date
from pathlib import Path

import pytest

from screener import contracts, oneliner as o

ROOT = Path(__file__).resolve().parents[1]

KIND_HTML = """<html><head><meta http-equiv="Content-Type" content="application/vnd.ms-excel;charset=euc-kr"></head><body>
<table border="1"><tr><th>회사명</th><th>시장구분</th><th>종목코드</th><th>업종</th><th>주요제품</th><th>상장일</th></tr>
<tr><td>삼성전자</td><td>유가</td><td style="mso-number-format:'\\@'">005930</td><td>통신 및 방송 장비 제조업</td>
<td>IMT2000 서비스용 동기식 기지국,교환국장비,데이터단말기,동영상휴대폰,핵심칩,반도체 메모리</td><td>1975-06-11</td></tr>
<tr><td>에코프로비엠</td><td>코스닥</td><td>247540</td><td>일차전지 및 이차전지 제조업</td><td>양극활물질</td><td>2019-03-05</td></tr>
<tr><td>빈칸회사</td><td>코스닥</td><td></td><td>x</td><td>y</td><td></td></tr>
</table></body></html>"""


def test_parse_kind_and_line():
    d = o.parse_kind(KIND_HTML)
    assert set(d) == {"005930", "247540"}
    assert d["247540"]["industry"] == "일차전지 및 이차전지 제조업"
    ln = o.kind_line(d["005930"]["industry"], d["005930"]["products"])
    assert ln.startswith("통신 및 방송 장비 · 주요제품 IMT2000") and len(ln) <= 45
    assert o.kind_line("일차전지 및 이차전지 제조업", "양극활물질") == "일차전지 및 이차전지 · 주요제품 양극활물질"
    assert o.kind_line("소프트웨어 개발 및 공급업", "") == "소프트웨어 개발 및 공급"


def test_kinds_and_type_lines():
    assert o.kind_of("삼성전자우") == "우선주" and o.kind_of("CJ4우(전환)") == "우선주" and o.kind_of("현대차2우B") == "우선주"
    assert o.kind_of("삼성전자") is None and o.kind_of("우리금융지주") is None
    assert o.kind_of("엔에이치스팩30호") == "스팩" and o.kind_of("SK리츠") == "리츠"
    assert o.kind_of("KODEX 200", is_etf=True) == "ETF"
    assert o.type_line("우선주", "현대차2우B").startswith("현대차 우선주")
    assert o.etf_line("KODEX 200", "코스피 200") == "코스피 200 추종 ETF"
    assert o.etf_line("KODEX 머니마켓액티브", "KAP MMF 지수(TR)") == "KAP MMF 지수 비교지수 액티브 ETF"
    long = o.etf_line("X 커버드콜", "KEDI 미국 AI밸류체인 90%참여+데일리옵션 프리미엄 지수(TR)")
    assert len(long) <= 45 and long.endswith("추종 커버드콜 ETF") and o.check_line(long, "ETF") == []
    assert o.check_line(long) != []   # 회사 줄이면 수치 규칙 위반
    assert o.etf_line("KODEX 200선물인버스2X", "F-KOSPI200") == "F-KOSPI200 추종 인버스2X ETF"
    for ln in (o.etf_line("TIGER 미국나스닥100", "NASDAQ 100"), o.type_line("스팩", "x스팩1호"), o.type_line("리츠", "y리츠")):
        assert not o.check_line(ln), ln


def test_first_sentence_keeps_abbreviations():
    assert o.first_sentence("Apple Inc. designs phones. It also sells.") == "Apple Inc. designs phones."
    assert o.first_sentence("J.P. Morgan Chase & Co. is a bank. More.") == "J.P. Morgan Chase & Co. is a bank."
    assert o.first_sentence("U.S. Bancorp provides services in the U.S. and abroad. X") == "U.S. Bancorp provides services in the U.S. and abroad."
    long = "A" * 500
    assert len(o.first_sentence(long)) == o.EV_MAX
    assert o.first_sentence(None) == ""


def test_check_line_rules():
    assert o.check_line("GPU·AI 가속기 설계, 데이터센터·게임용 칩 판매") == []
    assert any("홍보" in e for e in o.check_line("세계 최고 메모리 반도체 회사"))
    assert any("수치" in e for e in o.check_line("매출 30% 성장 중인 반도체 회사"))
    assert any("자" in e for e in o.check_line("가" * 60))
    assert o.check_line("") != []


def _uni():
    return {"005930": {"name": "삼성전자", "etf": False}, "005935": {"name": "삼성전자우", "etf": False},
            "069500": {"name": "KODEX 200", "etf": True, "base": "코스피 200", "summary": "KOSPI200 추종.", "category": None},
            "247540": {"name": "에코프로비엠", "etf": False}}


def test_update_incremental_and_recheck():
    calls = []

    def yh(sym):
        calls.append(sym)
        return {"sector": "Tech", "industry": "Consumer Electronics", "ev": f"{sym} makes things."}

    store, ev = o.empty(date(2026, 10, 24)), {"KR": {}, "US": {}}
    st = o.update("KR", budget=10, today=date(2026, 10, 24), uni=_uni(), yahoo=yh, kind=lambda: o.parse_kind(KIND_HTML),
                  store=store, ev=ev, write=False)
    S = store["KR"]
    assert S["069500"]["line"] == "코스피 200 추종 ETF" and S["069500"]["src"] == "etf"
    assert S["005935"]["src"] == "type" and S["247540"]["src"] == "kind" and S["005930"]["src"] == "kind"
    assert st["etf_type"] == 2 and st["kind"] == 2 and st["pending"] == 0
    assert calls == ["005930.KS", "247540.KQ"]        # ETF·우선주는 야후 근거 안 부름
    # 에이전트 줄로 교체 → 다음 실행(분기 안)은 아무것도 다시 부르지 않음
    S["005930"].update(line="스마트폰·가전·메모리 반도체 제조 판매", src="yahoo+agent")
    calls.clear()
    o.update("KR", budget=10, today=date(2026, 11, 1), uni=_uni(), yahoo=yh, kind=lambda: {}, store=store, ev=ev, write=False)
    assert calls == [] and S["005930"]["line"].startswith("스마트폰")
    # 분기 경과 + 근거 문장 바뀜 → recheck 표시, 줄 유지
    o.update("KR", budget=10, today=date(2027, 2, 1), uni=_uni(),
             yahoo=lambda s: {"sector": "", "industry": "X", "ev": "Changed."}, kind=lambda: {}, store=store, ev=ev, write=False)
    assert S["005930"].get("recheck") is True and S["005930"]["line"].startswith("스마트폰")
    # 유니버스에서 빠진 종목은 정리
    u = _uni(); u.pop("247540")
    o.update("KR", budget=0, today=date(2027, 2, 1), uni=u, yahoo=yh, kind=lambda: {}, store=store, ev=ev, write=False)
    assert "247540" not in S


def test_kind_failure_keeps_going():
    store, ev = o.empty(date(2026, 10, 24)), {"KR": {}, "US": {}}

    def boom():
        raise RuntimeError("KIND 403")
    st = o.update("KR", budget=5, today=date(2026, 10, 24), uni=_uni(), yahoo=lambda s: None, kind=boom,
                  store=store, ev=ev, write=False)
    assert st["kind_err"].startswith("KIND 403") and store["KR"]["005930"]["line"] == "" and st["yahoo_fail"] == 2


def test_apply_rejects_bad_lines(monkeypatch):
    store = o.empty(date(2026, 10, 24))
    store["US"] = {"NVDA": {"line": "", "industry": "", "src": ""}, "AAPL": {"line": "", "industry": "", "src": ""}}
    monkeypatch.setattr(o, "load", lambda path=o.STORE: {} if path == o.EV_STORE else store)
    r = o.apply("US", {"NVDA": "GPU·AI 가속기 칩 설계 판매(생산은 위탁)", "AAPL": "세계 최고 스마트폰 회사", "ZZZZ": "없는 종목"},
                store=store, write=False)
    assert r["applied"] == 1 and set(r["rejected"]) == {"AAPL", "ZZZZ"}
    assert store["US"]["NVDA"]["src"] == "yahoo+agent"


def test_repo_files_contract_and_rules():
    p = ROOT / "reports" / "company_oneliner.json"
    if not p.exists():
        pytest.skip("아직 생성 전")
    d = json.loads(p.read_text(encoding="utf-8"))
    assert contracts.check(p, d) == []
    for m in ("KR", "US"):
        for s, v in d[m].items():
            assert set(v) >= {"line", "industry", "src"}, s
            if v["line"]:
                assert o.check_line(v["line"], v.get("kind")) == [], (m, s, v["line"])
    e = json.loads((ROOT / "reports" / "company_oneliner_ev.json").read_text(encoding="utf-8"))
    assert contracts.check(ROOT / "reports" / "company_oneliner_ev.json", e) == []
    for m in ("KR", "US"):
        for s, v in e[m].items():
            assert len(v.get("ev") or "") <= o.EV_MAX, (m, s)   # 원문 전문 저장 금지 — 첫 문장 200자 이내만


def test_screen_wiring():
    gs = (ROOT / "apps-script" / "Code.gs").read_text(encoding="utf-8")
    pages = (ROOT / "scripts" / "build_pages.py").read_text(encoding="utf-8")
    tab = (ROOT / "apps-script" / "tab_detail.html").read_text(encoding="utf-8")
    assert "function getOneliners()" in gs and "reports/company_oneliner.json" in gs
    assert "getOneliners: () => get('reports/company_oneliner.json')" in pages
    assert tab.count("let h=oneBox(sym,mk)+") == 2 and ".getOneliners()" in tab and "설명 대기" in tab


def test_save_sorts_in_place(tmp_path, monkeypatch):
    """중간 저장 뒤에도 update() 가 들고 있는 dict 참조가 살아 있어야 한다(10/24 KR 근거 950건 유실 회귀)."""
    import screener.guard as g
    monkeypatch.setattr(g, "write_json", lambda *a, **k: True)
    store, ev = o.empty(date(2026, 10, 24)), {"KR": {}, "US": {}}
    S, E = store["KR"], ev["KR"]
    S["b"], S["a"] = {"line": ""}, {"line": ""}
    o.save(store, ev, date(2026, 10, 24))
    E["z"] = {"ev": "x"}
    S["c"] = {"line": ""}
    assert ev["KR"] is E and "z" in ev["KR"] and store["KR"] is S and list(store["KR"])[:2] == ["a", "b"]
