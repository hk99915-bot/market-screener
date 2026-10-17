"""데이터 계약(screener/contracts.py)·규칙 상수 단일 원천(screener/defs.py) — refactor_plan 결정 B (2026-10-17)."""
import glob
import json
import sys
from pathlib import Path

import pytest

from screener import contracts, defs, guard

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import check_rules_terms as crt  # noqa: E402


@pytest.fixture
def rep(tmp_path, monkeypatch):
    r = tmp_path / "reports"
    r.mkdir()
    monkeypatch.setattr(guard, "_report_dir", lambda: r)
    return r


@pytest.mark.parametrize("pat", sorted(contracts.CONTRACTS))
def test_repo_artifacts_satisfy_contract(pat):
    files = glob.glob(str(ROOT / "reports" / pat))
    for f in files:
        errs = contracts.check(f, json.loads(Path(f).read_text(encoding="utf-8")))
        assert errs == [], f"{f}: {errs}"


def test_violation_blocks_write_and_records(rep):
    p = rep / "momentum_US.json"
    p.write_text(json.dumps({"asof": "2026-10-16", "market": "US", "n": 5, "top": [], "bottom": []}))
    bad = {"asof": "2026-10-17", "market": "US", "n": "316", "top": [], "bottom": []}     # 숫자 자리에 문자열 (10/17 bonds 316 류)
    assert guard.write_json(p, bad) is False
    assert json.loads(p.read_text())["n"] == 5
    cv = json.loads((rep / "freshness.json").read_text())["contract_violation"][-1]
    assert cv["path"] == "momentum_US.json" and "'n'" in cv["errors"][0]


def test_missing_key_and_missing_date(rep):
    assert contracts.check(rep / "peers_US.json", {"asof": "2026-10-16"}) == ["peers_*.json: 필수 키 'rows' 없음"]
    assert any("날짜 키" in e for e in contracts.check(rep / "macro_view.json", {"asof": None, "rows": []}))
    assert contracts.check(rep / "bonds.json", {"asof": None, "generated_at": "x", "us": {}, "kr": {}}) == []   # bonds 는 날짜 비어도 허용


def test_pass_stamps_schema_version(rep):
    p = rep / "detail" / "US" / "_index.json"
    p.parent.mkdir(parents=True)
    assert guard.write_json(p, {"asof": "2026-10-16", "symbols": ["AAPL"]})
    assert json.loads(p.read_text())["schema_version"] == 1
    assert contracts.check(p, {"asof": "2026-10-16", "symbols": [], "schema_version": 9})   # 버전 불일치 = 위반


def test_uncontracted_path_passes():
    assert contracts.check("reports/whatever.json", [1, 2]) == []


# ── defs.py 단일 원천 ──
def test_repo_defs_consistent():
    assert crt.scan_defs() == []


def test_redefinition_and_ui_mismatch_caught(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "rules_terms.md").write_text((ROOT / "docs" / "rules_terms.md").read_text(encoding="utf-8"))
    (tmp_path / "screener").mkdir()
    (tmp_path / "screener" / "rebound.py").write_text("THRESHOLD = 0.006\n")
    (tmp_path / "screener" / "pb.py").write_text('o = {"semi_cap": 0.5}\n')
    (tmp_path / "apps-script").mkdir()
    (tmp_path / "apps-script" / "tab_my.html").write_text("const SEMI_CAP=0.35; const SEMI_BAND=0.45;")
    out = crt.scan_defs(tmp_path, defs)
    assert any("rebound.py:1" in x for x in out) and any("pb.py:1" in x for x in out) and any("SEMI_CAP=0.35" in x for x in out)
    assert len(out) == 3


def test_modules_use_defs():
    from screener import alerts, committee, pb, rebound, ticket
    assert rebound.THRESHOLD == defs.REBOUND_THRESHOLD and alerts.CRASH_ALERT_PCT == defs.CRASH_ALERT_PCT
    assert committee.CRASH_PCT == defs.CRASH_PCT and pb.STRESS_LIMIT == defs.STRESS_LIMIT
    assert ticket.MIN_RR == defs.MIN_RR and ticket.HARD_STOP == defs.HARD_STOP
    assert pb.rules("")["semi_band"] == defs.SEMI_BAND and pb.rules("SEMI_CAP 0.35")["semi_cap"] == 0.35


def test_accum_contracts_and_getters():
    """데이터 요청(10/17): accum.json·us_accum.json 계약 등록 + 화면 전용 getter 를 Pages 셸·Code.gs 양쪽에 같은 이름으로."""
    assert contracts.contract_for("reports/accum.json")[0] == "accum.json"
    assert contracts.contract_for("reports/us_accum.json")[0] == "us_accum.json"
    assert contracts.check("reports/accum.json", {"asof": None, "generated_at": "x", "status": "fail", "n": 0}) == []
    assert contracts.check("reports/us_accum.json", {"asof": "2026-10-16", "generated_at": "x", "status": "ok", "n_scanned": 3})
    root = Path(__file__).resolve().parents[1]
    bp = (root / "scripts" / "build_pages.py").read_text(encoding="utf-8")
    gs = (root / "apps-script" / "Code.gs").read_text(encoding="utf-8")
    for g, f in (("getAccum", "reports/accum.json"), ("getUsAccum", "reports/us_accum.json")):
        assert f"{g}: () => get('{f}')" in bp and f"function {g}()" in gs
    assert ".getAccum()" in (root / "apps-script" / "tab_market.html").read_text(encoding="utf-8")
