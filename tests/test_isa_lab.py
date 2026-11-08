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
