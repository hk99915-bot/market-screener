"""RESEARCH › 관계도 (11/1 겸이 — Bloomberg 'Circular AI Deals' 형식 기업 관계도) 화면·예시 데이터 계약.
데이터 = reports/company_links.json (애널 데스크, 공통 스키마). 없으면 tests/fixtures/company_links_sample.json(예시)로 개발·ui_smoke."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "company_links_sample.json"
TYPES = {"investment", "service", "hardware", "supply", "customer", "license", "jv"}
STATUS = {"1차", "2차", "검증전"}


def _check_schema(d: dict) -> None:
    assert re.match(r"^\d{4}-\d\d-\d\d$", d["asof"])
    gk = {g["key"] for g in d["groups"]}
    assert gk and all(g.get("name") for g in d["groups"])
    ids = [n["id"] for n in d["nodes"]]
    assert len(ids) == len(set(ids)), "노드 id 중복"
    for n in d["nodes"]:
        assert n["mkt"] in {"US", "KR", "PRIVATE", "OTHER", "GOV"} and n.get("name")   # OTHER = 미국 밖 해외 상장, GOV = 정부·방위사업청 (애널 11/1)
        assert n["mc_usd"] is None or n["mc_usd"] > 0
        assert set(n.get("groups") or []) <= gk
        if n["mkt"] == "PRIVATE":
            assert n.get("listed") is False
    for e in d["edges"]:
        assert e["from"] in ids and e["to"] in ids and e["from"] != e["to"], e
        assert e["type"] in TYPES, e["type"]
        assert e["status"] in STATUS, e["status"]
        assert e.get("why") and e.get("src")
        assert set(e.get("groups") or []) <= gk


def test_sample_fixture_schema_and_marked_example():
    d = json.loads(FIX.read_text(encoding="utf-8"))
    assert "예시" in d["_example"]
    _check_schema(d)
    for g in d["groups"]:   # 그룹마다 관계가 하나 이상 있어야 칩을 눌러 볼 게 있다
        assert any(g["key"] in (e.get("groups") or []) for e in d["edges"]), g["key"]


def test_real_file_schema_when_present():
    p = ROOT / "reports" / "company_links.json"
    if p.exists():
        _check_schema(json.loads(p.read_text(encoding="utf-8")))


def test_view_registered_and_getters_paired():
    idx = (ROOT / "apps-script" / "Index.html").read_text(encoding="utf-8")
    assert "['links','관계도']" in idx and "v==='links'?linksView():" in idx
    assert "new URLSearchParams(location.search).get('v')" in idx   # ?v=links 바로 열기(정렬 검사용)
    bp = (ROOT / "scripts" / "build_pages.py").read_text(encoding="utf-8")
    assert "getCompanyLinks: () => get('reports/company_links.json')" in bp
    assert "getCompanyLinksSample: () => get('tests/fixtures/company_links_sample.json')" in bp
    tab = (ROOT / "apps-script" / "tab_research.html").read_text(encoding="utf-8")
    assert "function linksView(" in tab and "typeof R.getCompanyLinks!=='function'" in tab   # Code.gs 짝이 없어도 화면이 죽지 않음


def test_edge_colors_distinct_from_up_down_and_verdict():
    """관계 유형 색은 상승 빨강(--up)·하락 파랑(--down)·판정(--bad)과 겹치지 않고, 선 모양으로도 구분(색약)."""
    idx = (ROOT / "apps-script" / "Index.html").read_text(encoding="utf-8")
    root = idx[idx.index(":root{"): idx.index("}", idx.index(":root{"))]
    taken = {m.lower() for m in re.findall(r"--(?:up|down|bad|alarm-bg|accent):(#[0-9a-fA-F]{6})", root)}
    assert {"#ff4d4d", "#4c8dff"} <= taken
    tab = (ROOT / "apps-script" / "tab_research.html").read_text(encoding="utf-8")
    m = re.search(r"\.lk\{([^}]*)\}", tab)
    cols = re.findall(r"--lk-(inv|svc|hw|sup):(#[0-9a-fA-F]{6})", m.group(1))
    assert len(cols) == 4 and len({c for _, c in cols}) == 4
    for _, c in cols:
        assert c.lower() not in taken
        r, g, b = (int(c[i:i + 2], 16) for i in (1, 3, 5))
        assert not (r > 200 and g < 120 and b < 120), f"{c} 빨강 계열(상승과 혼동)"
        assert not (b > 200 and r < 120 and g < 170), f"{c} 파랑 계열(하락과 혼동)"
    assert "html.xl .lk{" in tab   # 엑셀 스킨 값
    assert "const LK_DASH={'lk-svc':'6 4','lk-sup':'2 3'" in tab
