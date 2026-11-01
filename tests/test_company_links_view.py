"""RESEARCH › 관계도 (11/1 겸이 — Bloomberg 'Circular AI Deals' 형식 기업 관계도) 화면·예시 데이터 계약.
데이터 = reports/company_links.json (애널 데스크, 공통 스키마). 없으면 tests/fixtures/company_links_sample.json(예시)로 개발·ui_smoke."""
import json
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "company_links_sample.json"
FIX_AUTO = ROOT / "tests" / "fixtures" / "company_links_auto_sample.json"
TAB = ROOT / "apps-script" / "tab_links.html"
TYPES = {"investment", "service", "hardware", "supply", "customer", "license", "jv"}
STATUS = {"1차", "2차", "검증전", "1차(자동)"}   # 1차(자동) = 애널 DART 원문 자동 추출(사람 대조 전)


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
    for name in ("company_links.json", "company_links_auto.json"):
        p = ROOT / "reports" / name
        if p.exists():
            _check_schema(json.loads(p.read_text(encoding="utf-8")))


def test_auto_fixture_schema_and_tiers():
    d = json.loads(FIX_AUTO.read_text(encoding="utf-8"))
    assert "예시" in d["_example"]
    _check_schema(d)
    assert all(n.get("tier") in (None, 1, 2, 3, "holding") for n in d["nodes"])
    assert {g.get("anchor") for g in d["groups"]} <= {n["id"] for n in d["nodes"]}


# ── 순수 함수(병합·회사 중심 2단계·계단 층) — 화면 코드 그대로를 node 로 돌린다 ─────────────
def _pure_js() -> str:
    t = TAB.read_text(encoding="utf-8")
    a, b = t.index("/*LK-PURE-BEGIN"), t.index("/*LK-PURE-END*/")
    return t[a:b]


def _node(body: str):
    if not shutil.which("node"):
        import pytest
        pytest.skip("node 없음")
    js = _pure_js() + "\nconst OUT=(()=>{" + body + "})();\nprocess.stdout.write(JSON.stringify(OUT));"
    r = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-800:]
    return json.loads(r.stdout)


def _N(i, g=("g",)):
    return {"id": i, "name": i, "mkt": "KR", "mc_usd": None, "groups": list(g)}


def _E(f, t, ty="supply", **k):
    return {"from": f, "to": t, "type": ty, "why": "w", "src": "s", "status": "1차", **k}


def test_merge_manual_wins_and_auto_marked():
    man = {"asof": "2026-11-01", "groups": [{"key": "g", "name": "G"}], "nodes": [_N("A"), _N("B")],
           "edges": [_E("A", "B", size="수작업 규모", why="수작업 설명")]}
    auto = {"asof": "2026-11-02", "groups": [{"key": "ch", "name": "체인", "anchor": "B"}], "nodes": [_N("A", ["ch"]), _N("C", ["ch"])],
            "edges": [_E("A", "B", "customer", size="자동 규모", why="자동", tier=1, groups=["ch"]),   # customer = supply 같은 방향 → 같은 엣지
                      _E("C", "A", tier=2, groups=["ch"]), _E("C", "Z", tier=2)]}                   # Z = 없는 회사 → 버림
    D = _node(f"const D=lkMerge({json.dumps(man)},{json.dumps(auto)}); return D;")
    ab = [e for e in D["edges"] if e["from"] == "A" and e["to"] == "B"]
    assert len(ab) == 1 and ab[0]["size"] == "수작업 규모" and not ab[0].get("_auto")   # 수작업 우선
    assert ab[0]["tier"] == 1 and "ch" in ab[0]["groups"]                                  # 자동 쪽 tier·체인만 보탬
    ca = [e for e in D["edges"] if e["from"] == "C"]
    assert len(ca) == 1 and ca[0]["_auto"] is True
    assert D["_stat"] == {"man": 1, "auto": 1, "dup": 1, "autoN": 1}   # C→Z 는 버린 뒤로 셈
    a = next(n for n in D["nodes"] if n["id"] == "A")
    assert set(a["groups"]) == {"g", "ch"} and not a.get("_auto")
    assert [g["key"] for g in D["groups"]] == ["g", "ch"]


def test_merge_with_fixtures_badge_and_no_auto():
    man = json.loads(FIX.read_text(encoding="utf-8"))
    auto = json.loads(FIX_AUTO.read_text(encoding="utf-8"))
    D = _node(f"const D=lkIndex(lkMerge({json.dumps(man)},{json.dumps(auto)})); const D0=lkMerge({json.dumps(man)},null);"
              "return {n:D.nodes.length, e:D.edges.length, ex:D.edges.filter(e=>e._ex).length, auto:D._auto, n0:D0.edges.length, a0:D0._auto};")
    assert D["e"] == D["n0"] + D["ex"] and D["ex"] >= 10 and D["auto"]["example"]
    assert D["a0"] is None   # 자동 파일 없으면 수작업만


def test_ego_two_steps():
    # 현대차(H) ← 화신(W) ← 2차(W2) ← 3차(W3) / H → 딜러(D) → 고객(DD) / 화신 → 기아(K) 는 '공급사의 고객'(2단계 아님)
    nodes = [_N(i) for i in ["H", "W", "W2", "W3", "D", "DD", "K", "M", "M2"]]
    edges = [_E("W", "H"), _E("M", "H"), _E("W2", "W"), _E("M2", "M"), _E("W3", "W2"), _E("H", "D"), _E("D", "DD"), _E("W", "K"), _E("W", "M")]
    G = _node(f"const D=lkIndex(lkMerge({json.dumps({'nodes': nodes, 'edges': edges, 'groups': [{'key': 'g', 'name': 'g'}]})},null));"
              "return lkEgo(D,'H',24,60);")
    r1 = {x["id"]: x["side"] for x in G["r1"]}
    r2 = {x["id"]: (x["side"], sorted(x["via"])) for x in G["r2"]}
    assert r1 == {"W": 1, "M": 1, "D": 2}
    assert r2 == {"W2": (1, ["W"]), "M2": (1, ["M"]), "DD": (2, ["D"])}   # W3(3단계)·K(형제 고객) 제외
    pairs = {(e["from"], e["to"]) for e in G["E"]}
    assert ("W", "M") in pairs and ("W3", "W2") not in pairs and ("W", "K") not in pairs
    G2 = _node(f"const D=lkIndex(lkMerge({json.dumps({'nodes': nodes, 'edges': edges, 'groups': []})},null)); return lkEgo(D,'H',1,1);")
    assert len(G2["r1"]) == 1 and G2["n1"] == 3 and len(G2["r2"]) <= 1   # 상한 + 전체 수


def test_tiers_node_tier_then_bfs():
    """자동 노드 tier(1=완성·대형 2=1차 협력 3=2차 협력) → 칸 0·1·2, tier 없는 회사는 완성·대형에서 거꾸로 BFS, 4단계 이상 = 3(3차+)."""
    def n(i, t=None):
        x = _N(i); x["tier"] = t; return x
    nodes = [n("H", 1), n("K", 1), n("W", 2), n("W2", 3), n("W3"), n("W4"), n("X"), n("C")]
    edges = [_E("W", "H"), _E("W", "K"), _E("W2", "W"), _E("W3", "W2"), _E("W4", "W3"), _E("X", "W", "investment")]
    T = _node(f"const D=lkIndex(lkMerge({json.dumps({'nodes': nodes, 'edges': edges, 'groups': [{'key': 'g', 'name': 'g'}]})},null)); return lkTiers(D,'g');")
    assert sorted(T["anchors"]) == ["H", "K"] and T["anchor"] is None
    assert T["tier"] == {"H": 0, "K": 0, "W": 1, "W2": 2, "W3": 3, "W4": 3}
    assert T["out"] == 2   # X(투자자만), C(관계 없음)
    # 앵커 지정(수작업 그룹 anchor) + tier 없음 → BFS, 앵커 고객 = -1
    nodes2 = [_N(i) for i in ["H", "W", "W2", "C"]]
    edges2 = [_E("W", "H"), _E("W2", "W"), _E("H", "C")]
    T2 = _node(f"const D=lkIndex(lkMerge({json.dumps({'nodes': nodes2, 'edges': edges2, 'groups': [{'key': 'g', 'name': 'g', 'anchor': 'H'}]})},null)); return lkTiers(D,'g');")
    assert T2["anchor"] == "H" and T2["tier"] == {"H": 0, "W": 1, "W2": 2, "C": -1}


def test_hierarchy_sector_segment_and_l0_l1():
    """위계: 섹터 = chain(구체) → 자동 sector 문구 → groups → 기타. 세그먼트 = 구체 체인 → 층. L0 묶음 회사 수·섹터 사이 관계 수, L3 출구 = 다른 섹터."""
    nodes = [{"id": "SEC", "name": "삼성전자", "mkt": "KR", "chain": "memory", "groups": []},
             {"id": "SEMCO", "name": "삼성전기", "mkt": "KR", "chain": "components", "groups": []},
             {"id": "ABC", "name": "아비코", "mkt": "KR", "chain": "other", "sector": "전기·전자", "tier": 2, "groups": []},
             {"id": "HMC", "name": "현대차", "mkt": "KR", "chain": "auto", "tier": 1, "groups": []},
             {"id": "HS", "name": "화신", "mkt": "KR", "chain": "auto", "tier": 2, "groups": []},
             {"id": "NVDA", "name": "엔비디아", "mkt": "US", "chain": None, "groups": ["ai_circle", "kr_semis"]},
             {"id": "COS", "name": "화장품", "mkt": "KR", "chain": "other", "sector": "화장품·소비재", "groups": []}]
    edges = [_E("SEMCO", "SEC"), _E("ABC", "SEMCO"), _E("HS", "HMC"), _E("SEMCO", "HMC"), _E("NVDA", "SEC"), _E("COS", "HS")]
    R = _node("const D=lkHier(lkIndex(lkMerge(" + json.dumps({'nodes': nodes, 'edges': edges, 'groups': []}) + """,null)));
      const L0=lkL0(D), L1=lkL1(D,'auto'), G=lkEgo(D,'HMC',12,8,id=>D._sec[id]===D._sec['HMC']);
      return {sec:D._sec, seg:D._seg, L0, L1:L1.G.map(g=>[g.k,g.n]), r1:G.r1.map(x=>x.id), ex:G.ex.map(x=>x.id), X:lkExits(D,['HMC','HS'],id=>D._sec[id]==='auto')};""")
    assert R["sec"] == {"SEC": "semi", "SEMCO": "elec", "ABC": "elec", "HMC": "auto", "HS": "auto", "NVDA": "ai", "COS": "etc"}
    assert R["seg"]["SEC"] == "메모리" and R["seg"]["SEMCO"] == "기판·부품" and R["seg"]["ABC"] == "1차 협력" and R["seg"]["HMC"] == "완성·대형" and R["seg"]["COS"] == "화장품·소비재"
    L = {tuple(sorted((x["a"], x["b"]))): x["n"] for x in R["L0"]["L"]}
    assert L == {("elec", "semi"): 1, ("auto", "elec"): 1, ("ai", "semi"): 1, ("auto", "etc"): 1}
    assert {g["k"]: g["n"] for g in R["L0"]["G"]}["elec"] == 2
    assert sorted(R["L1"]) == [["1차 협력", 1], ["완성·대형", 1]]
    assert R["r1"] == ["HS"] and R["ex"] == ["SEMCO"]   # 다른 섹터 거래처 = 출구
    assert sorted((x["s"], x["n"]) for x in R["X"]) == [("elec", 1), ("etc", 1)]


def test_scale_1000_nodes_3000_edges_fast():
    """노드 1,000·엣지 3,000: 병합+색인+회사 중심 2단계+계단 층 계산이 node 에서 300ms 안(화면 그리기는 ui_smoke 가 잰다)."""
    R = _node("""
      const N=[],E=[]; let s=7; const rnd=()=>(s=(s*48271)%2147483647)/2147483647;
      for(let i=0;i<1000;i++) N.push({id:'N'+i,name:'회사'+i,mkt:'KR',mc_usd:null,groups:['g'+(i%10)]});
      for(let j=0;j<3000;j++){ const a=Math.floor(rnd()*1000), b=Math.floor(rnd()*1000); if(a!==b) E.push({from:'N'+a,to:'N'+b,type:'supply',why:'w',src:'s',status:'1차',groups:['g'+(a%10)],tier:1+(j%3)}); }
      const t0=Date.now(); const D=lkIndex(lkMerge({nodes:N.slice(0,500),edges:E.slice(0,1500),groups:[{key:'g0',name:'g0'}]},{nodes:N,edges:E,groups:[...Array(10)].map((_,i)=>({key:'g'+i,name:'g'+i}))}));
      const G=lkEgo(D,'N1',24,60), T=lkTiers(D,'g0'); return {ms:Date.now()-t0, n:D.nodes.length, e:D.edges.length, r1:G.r1.length, r2:G.r2.length, t:Object.keys(T.tier).length};""")
    assert R["n"] == 1000 and R["e"] >= 2900 and R["r1"] > 0 and R["r2"] > 0 and R["t"] > 1
    assert R["ms"] < 300, R


def test_view_registered_and_getters_paired():
    idx = (ROOT / "apps-script" / "Index.html").read_text(encoding="utf-8")
    assert "['links','관계도']" in idx and "v==='links'?linksView():" in idx
    assert "new URLSearchParams(location.search).get('v')" in idx   # ?v=links 바로 열기(정렬 검사용)
    bp = (ROOT / "scripts" / "build_pages.py").read_text(encoding="utf-8")
    assert "getCompanyLinks: () => get('reports/company_links.json')" in bp
    assert "getCompanyLinksSample: () => get('tests/fixtures/company_links_sample.json')" in bp
    assert "getCompanyLinksAuto: () => get('reports/company_links_auto.json')" in bp
    assert "getCompanyLinksAutoSample: () => get('tests/fixtures/company_links_auto_sample.json')" in bp
    assert "<?!= include('tab_links') ?>" in idx   # 11/1 tab_research 에서 분리(서고 작업과 잠금 단위 분리)
    tab = TAB.read_text(encoding="utf-8")
    assert "function linksView(" in tab and "typeof R.getCompanyLinks!=='function'" in tab   # Code.gs 짝이 없어도 화면이 죽지 않음
    assert "typeof R.getCompanyLinksAuto!=='function'" in tab   # 자동 파일 공급 경로가 없어도 수작업만으로 그림
    assert "function linksView(" not in (ROOT / "apps-script" / "tab_research.html").read_text(encoding="utf-8")


def test_edge_colors_distinct_from_up_down_and_verdict():
    """관계 유형 색은 상승 빨강(--up)·하락 파랑(--down)·판정(--bad)과 겹치지 않고, 선 모양으로도 구분(색약)."""
    idx = (ROOT / "apps-script" / "Index.html").read_text(encoding="utf-8")
    root = idx[idx.index(":root{"): idx.index("}", idx.index(":root{"))]
    taken = {m.lower() for m in re.findall(r"--(?:up|down|bad|alarm-bg|accent):(#[0-9a-fA-F]{6})", root)}
    assert {"#ff4d4d", "#4c8dff"} <= taken
    tab = TAB.read_text(encoding="utf-8")
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
