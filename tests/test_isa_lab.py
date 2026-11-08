"""ISA 실험실 — 화면 JS 계산(tab_isalab.html ILAB_CALC 블록)이 Python 기준 구현(screener/isa_lab.py)과 같은 숫자를 내는지,
그리고 매크로 금 보고서(10/17, 비용 미차감·월 리밸) 숫자를 같은 방식으로 재현하는지 검사."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from screener import isa_lab as L

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "reports" / "isa_lab_returns.json"
D = json.loads(DATA.read_text(encoding="utf-8"))
CUSTOM = {"SP": 30, "NDX": 20, "KS": 10, "KR3Y": 10, "KR10Y": 10, "UST": 10, "GOLD": 5}
CASES = [(w, rb, cost) for w in [*D["presets"].values(), CUSTOM] for rb in "MAN" for cost in (True, False)]


def _js_calc() -> str:
    s = (ROOT / "apps-script" / "tab_isalab.html").read_text(encoding="utf-8")
    m = re.search(r"/\* ILAB_CALC_BEGIN.*?\*/(.*?)/\* ILAB_CALC_END \*/", s, re.S)
    assert m, "ILAB_CALC 블록 없음"
    return m.group(1)


def _run_js(jobs: list) -> list:
    code = _js_calc() + """
const fs=require('fs'); const D=JSON.parse(fs.readFileSync(process.argv[2],'utf8')); const jobs=JSON.parse(fs.readFileSync(process.argv[3],'utf8'));
const out=jobs.map(j=>j.boot?ilabBoot(D,j.w,j.rb,j.cost,j.P,120,12,7):(e=>({lump:e.lump,dca:e.dca,crisis:e.crisis}))(ilabEval(D,j.w,j.rb,j.cost,100)));
console.log(JSON.stringify(out));"""
    return code


@pytest.fixture(scope="module")
def js_results(tmp_path_factory):
    if shutil.which("node") is None:
        pytest.skip("node 없음")
    d = tmp_path_factory.mktemp("ilab")
    jobs = [{"w": w, "rb": rb, "cost": c} for w, rb, c in CASES]
    jobs += [{"w": D["presets"]["이전안(금15·NDX10)"], "rb": "A", "cost": True, "boot": True, "P": 200},
             {"w": CUSTOM, "rb": "N", "cost": False, "boot": True, "P": 200}]
    (d / "c.js").write_text(_run_js(jobs), encoding="utf-8")
    (d / "j.json").write_text(json.dumps(jobs, ensure_ascii=False), encoding="utf-8")
    r = subprocess.run(["node", str(d / "c.js"), str(DATA), str(d / "j.json")], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-800:]
    return json.loads(r.stdout)


def _close(a, b, tol=1e-9):
    if isinstance(a, dict):
        assert a.keys() == b.keys()
        for k in a:
            _close(a[k], b[k], tol)
    else:
        assert abs(a - b) <= tol * max(1.0, abs(b)), (a, b)


def test_js_matches_python_backtest(js_results):
    for (w, rb, cost), js in zip(CASES, js_results):
        _close(js, L.evaluate(D, w, rb, cost, 100.0))


def test_js_matches_python_bootstrap(js_results):
    _close(js_results[-2], L.bootstrap(D, D["presets"]["이전안(금15·NDX10)"], "A", True, P=200))
    _close(js_results[-1], L.bootstrap(D, CUSTOM, "N", False, P=200))


# 10/17 보고서가 쓴 원천 스냅샷의 2026-10 행(10/15 부분 월, pb-private monthly_returns_krw.csv 마지막 행 — 시장 데이터).
# 11/8 재생성에서 이 달은 10/30 종가 전체 월로 바뀌었으므로, 보고서 재현은 2026-09 까지 + 이 행으로 한다.
SNAP_2026_10 = {"SP": 0.001955, "NDX": -0.031502, "KS": -0.205578, "KR3Y": 0.006965, "KR10Y": 0.018929, "UST": 0.013581, "GOLD": -0.0036}


def _snapshot_1015() -> dict:
    n = D["months"].index("2026-09") + 1
    return {**D, "months": D["months"][:n] + ["2026-10"], "r": {a: D["r"][a][:n] + [SNAP_2026_10[a]] for a in D["assets"]}}


def test_reproduces_macro_gold_report_table():
    # ops/desk_answers/2026-10-17_macro_gold.md 5절 (pb-private): 월 리밸·비용 미차감 — CAGR/MDD
    # 보고서 표기 '현행 ISA' = 이전안(금15·NDX10), '나스닥안(금10·NDX15)' = C안(현행) (같은 비중, 11/8 이름 정정)
    want = {"이전안(금15·NDX10)": (0.108, -0.137), "매크로안 (금10·국고25)": (0.104, -0.144), "C안(현행)": (0.110, -0.160)}
    S = _snapshot_1015()
    for k, (cagr, mdd) in want.items():
        e = L.evaluate(S, D["presets"][k], "M", cost=False)["lump"]
        assert round(e["cagr"], 3) == cagr and round(e["mdd"], 3) == mdd, (k, e)


def test_data_shape_and_no_personal_amounts():
    n = len(D["months"])
    assert D["assets"] == L.ASSETS and n >= 275 and D["months"][0] == "2004-01" and D["months"][273] == "2026-10"
    assert all(len(D["r"][a]) == n for a in L.ASSETS)
    assert D["asof"][:7] == D["months"][-1] and D["asof"] >= "2026-11-06"   # asof = 실제 마지막 거래일(미래 월말 아님)
    txt = DATA.read_text(encoding="utf-8")
    assert "만" not in txt.replace("만기", "").replace("미만", "") and "원금" not in txt   # 금액 표현 없음 (수익률·비중만, 운용회의 정의의 '미만' 제외)
    for p in D["presets"].values():
        assert sum(p.values()) == 100


def test_presets_current_core_first():
    # 11/7 확정 C안 = 첫 프리셋(화면 비교 기준), 이전안·매크로안 보존 (req-quant-a74f9f91)
    ks = list(D["presets"])
    assert ks[0] == "C안(현행)" and D["presets"]["C안(현행)"] == {"SP": 40, "NDX": 15, "KS": 15, "KR3Y": 20, "GOLD": 10}
    assert D["presets"]["이전안(금15·NDX10)"] == {"SP": 40, "NDX": 10, "KS": 15, "KR3Y": 20, "GOLD": 15}
    assert D["presets"]["매크로안 (금10·국고25)"] == {"SP": 40, "NDX": 10, "KS": 15, "KR3Y": 25, "GOLD": 10}
    assert "현행 ISA" not in D["presets"] and D["presets"] == L.PRESETS


def test_build_ext_overrides_partial_month(tmp_path):
    src = tmp_path / "s.csv"
    src.write_text("date," + ",".join(L.ASSETS) + "\n2026-09-30," + ",".join(["0.01"] * 7) + "\n2026-10-31," + ",".join(["0.02"] * 7) + "\n", encoding="utf-8")
    ext = tmp_path / "e.csv"
    ext.write_text("date,thru," + ",".join(L.ASSETS) + "\n2026-10-31,2026-10-30," + ",".join(["0.03"] * 7) + "\n2026-11-30,2026-11-06," + ",".join(["0.04"] * 7) + "\n", encoding="utf-8")
    o = L.build(src, tmp_path / "o.json", ext)
    assert o["months"] == ["2026-09", "2026-10", "2026-11"] and o["r"]["SP"] == [0.01, 0.03, 0.04]
    assert o["asof"] == "2026-11-06" and o["note"].startswith("2026-11 은 11/6 까지의 부분 월.")


def test_regime_scenarios_replay_from_monthly():
    # 위기 유형 블록 = 이 파일 월수익 재생(월 리밸·비용 차감) — 지어낸 값 없음
    S = D["scenarios"]
    assert S["rebal"] == "M" and S["cost"] is True and set(S["rows"]) == set(D["presets"])
    assert S["rows"] == L.scenarios(D)["rows"]
    for name, cell in S["rows"].items():
        e = L.evaluate(D, D["presets"][name], "M", True)
        assert abs(cell["전체 기간 연복리"] - e["lump"]["cagr"]) < 1e-6
        assert abs(cell["2022형"] - e["crisis"]["2022 금리쇼크"]) < 1e-6 and abs(cell["2008형"] - e["crisis"]["2008 금융위기"]) < 1e-6
    assert "권고 아님" in S["note"]


def test_desk_block_from_sources_only():
    K = D["scenarios"]["desk"]
    F = K["frm"]
    txt = DATA.read_text(encoding="utf-8")
    assert '"pnl"' not in txt and '"by_pos"' not in txt   # FRM 금액 칸은 옮기지 않음
    if F["available"]:
        for name, wm in D["presets"].items():
            for sc in F["scenarios"]:
                want = sum(wm[a] / 100 * sc["shock"][a] for a in wm if wm[a])
                assert abs(F["rows"][name][sc["id"]] - want) < 1e-6
    for k in ("macro", "committee", "analyst"):          # 원천에 자산별 수치 없음 → 빈칸
        assert all(v is None for v in K[k]["rows"].values()) and "원천에 수치 없음" in K[k]["why_blank"]


def test_regime_calm_excludes_partial_month_and_caveats():
    # 피어리뷰(97341c82a): 진행 중 부분 월은 평시에서 빼고, 사후 선택·K3 표본 없음·§1-B 기준 차이를 note 에 적는다
    S = D["scenarios"]
    assert S["calm_excluded_partial"] == D["months"][-1] and D["asof"] < D["months"][-1] + "-28"
    M = L.net_returns(D, True)
    m = D["months"]
    excl = {len(m) - 1}
    for _, a, b in [(e[0], e[1], e[2]) for g in S["regimes"] for e in g["events"]]:
        excl |= set(range(m.index(a), m.index(b) + 1))
    twr = L.simulate(M, L.weights(D, D["presets"]["C안(현행)"]), "M", 0)["twr"]
    calm = [twr[t] for t in range(len(m)) if t not in excl]
    g = 1.0
    for r in calm:
        g *= 1 + r
    assert abs(S["rows"]["C안(현행)"]["평시 연환산"] - (g ** (12 / len(calm)) - 1)) < 1e-6
    for k in ("사후 선택", "K3", "§1-B", "권고 아님"):
        assert k in S["note"], k
    k0 = [x for x in S["regimes"] if x["key"] == "K0"][0]
    assert "사후 선택" in k0["def"] and k0["def_orig"] == "위 셋 아님"
    assert "424행" in S["now"]["regime_rebalance"] and "하락장" in S["now"]["vs_frm"]


def test_projection_paths_from_scenarios():
    # 예상 경로 점선 (데이터엔지니어 11/8) — 생성기 계산값을 JSON 에 저장, 화면은 곱하기만
    P = D["projection"]
    core = lambda X: [l for l in X["lines"] if not l["kind"].startswith("er_")]   # 데스크 er 파일은 데스크가 따로 갱신 — 재생성 전 CI 빨강 방지(b32339f85 사고)
    assert core(P) == core(L.projection(D)) and P["horizon_m"] == 36 and len(P["months"]) == 37 and P["months"][0] == D["months"][-1]
    assert "권고 아님" in P["note"]
    rows = D["scenarios"]["rows"]
    by = {l["key"]: l for l in P["lines"]}
    for name in D["presets"]:
        calm = rows[name]["평시 연환산"]
        a = by["평시 연환산"]["path"][name]
        assert a[0] == 1.0 and abs(a[12] - (1 + calm)) < 1e-6 and abs(a[36] - (1 + calm) ** 3) < 1e-5
        for ev, n in (("2008형", 16), ("2022형", 12), ("2026-07형", 5)):   # 위기 창을 다시 겪은 끝 = 구간 누적, 이후 평시 복리
            c = by[ev]["path"][name]
            assert abs(c[n] - (1 + rows[name][ev])) < 1e-5 and abs(c[n + 12] / c[n] - (1 + calm)) < 1e-5
        for l in P["lines"]:
            if l["kind"] == "shock":
                assert abs(l["path"][name][1] - (1 + l["rate"][name])) < 1e-6
    for l in P["lines"]:
        assert l["src"] and set(l["path"]) <= set(D["presets"])
    sk = {s["key"] for s in P["skipped"]}
    assert {"macro", "committee", "analyst"} & sk or any(k.startswith("er:") for k in by)   # 수치 없는 국면은 그리지 않음


def test_desk_er_files_optional(tmp_path):
    v = tmp_path / "reports" / "views"
    v.mkdir(parents=True)
    er = {"SP": 0.08, "NDX": 0.10, "KS": 0.06, "KR3Y": 0.03, "GOLD": 0.04}
    (v / "scenario_er_macro.json").write_text(json.dumps({"asof": "2026-11-08", "scenarios": [{"name": "기본", "er": er}]}), encoding="utf-8")
    (v / "scenario_er_committee.json").write_text(json.dumps({"scenarios": [{"name": "약세", "horizon": "20d", "er": er, "er_ann": None}]}), encoding="utf-8")
    lines, skipped = L._desk_er_lines(D, None, root=tmp_path)
    assert [l["key"] for l in lines] == ["er:macro:기본"] and lines[0]["kind"] == "er_macro"
    want = (40 * .08 + 15 * .10 + 15 * .06 + 20 * .03 + 10 * .04) / 100
    assert abs(lines[0]["rate"]["C안(현행)"] - want) < 1e-9 and abs(lines[0]["path"]["C안(현행)"][12] - (1 + want)) < 1e-6
    sk = {s["key"]: s["why"] for s in skipped}
    assert "아직 안 옴" in sk["er:analyst"] and "20d" in sk["er:committee:약세"]   # 파일 없음 · 연환산 없음 → 안 그림


def test_js_projection_draws_json_only(tmp_path):
    if shutil.which("node") is None:
        pytest.skip("node 없음")
    code = _js_calc() + """
const fs=require('fs'); const D=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
const pn=ilabPresetOf(D,{SP:40,NDX:15,KS:15,KR3Y:20,KR10Y:0,UST:0,GOLD:10}), none=ilabPresetOf(D,{SP:50,NDX:50});
console.log(JSON.stringify({pn,none,pj:ilabProj(D,pn,2.0),empty:ilabProj(D,none,2.0).length}));"""
    (tmp_path / "p.js").write_text(code, encoding="utf-8")
    r = subprocess.run(["node", str(tmp_path / "p.js"), str(DATA)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-800:]
    o = json.loads(r.stdout)
    assert o["pn"] == "C안(현행)" and o["none"] is None and o["empty"] == 0
    for js, l in zip(o["pj"], D["projection"]["lines"]):
        assert js["key"] == l["key"] and [p["v"] for p in js["pts"]] == [2.0 * v for v in l["path"]["C안(현행)"]]
        assert [p["m"] for p in js["pts"]] == D["projection"]["months"]


def test_projection_desk_er_matches_files():
    # 데스크 er 파일이 저장소에 있으면 점선 연율 = 프리셋 Σ비중×er (애널 12m·매크로 연), CIO 20d(er_ann null) 는 안 그림
    by = {l["key"]: l for l in D["projection"]["lines"]}
    f = ROOT / "reports" / "views" / "scenario_er_analyst.json"
    if not f.exists():
        pytest.skip("애널 er 파일 없음")
    J = json.loads(f.read_text(encoding="utf-8"))
    for sc in J["scenarios"]:
        k = "er:analyst:" + (sc.get("name") or sc["key"])
        for pn, wm in D["presets"].items():
            assert abs(by[k]["rate"][pn] - sum(w / 100 * sc["er"][a] for a, w in wm.items() if w)) < 1e-6
    assert not any(k.startswith("er:committee:") for k in by)
