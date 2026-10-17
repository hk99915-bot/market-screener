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
    jobs += [{"w": D["presets"]["현행 ISA"], "rb": "A", "cost": True, "boot": True, "P": 200},
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
    _close(js_results[-2], L.bootstrap(D, D["presets"]["현행 ISA"], "A", True, P=200))
    _close(js_results[-1], L.bootstrap(D, CUSTOM, "N", False, P=200))


def test_reproduces_macro_gold_report_table():
    # ops/desk_answers/2026-10-17_macro_gold.md 5절 (pb-private): 월 리밸·비용 미차감 — CAGR/MDD
    want = {"현행 ISA": (0.108, -0.137), "매크로안 (금10·국고25)": (0.104, -0.144), "나스닥안 (금10·NDX15)": (0.110, -0.160)}
    for k, (cagr, mdd) in want.items():
        e = L.evaluate(D, D["presets"][k], "M", cost=False)["lump"]
        assert round(e["cagr"], 3) == cagr and round(e["mdd"], 3) == mdd, (k, e)


def test_data_shape_and_no_personal_amounts():
    assert D["assets"] == L.ASSETS and len(D["months"]) == 274 and D["months"][0] == "2004-01"
    assert all(len(D["r"][a]) == 274 for a in L.ASSETS)
    txt = DATA.read_text(encoding="utf-8")
    assert "만" not in txt.replace("만기", "") and "원금" not in txt   # 금액 표현 없음 (수익률·비중만)
    for p in D["presets"].values():
        assert sum(p.values()) == 100
