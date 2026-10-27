import importlib.util
from datetime import date
from pathlib import Path

spec = importlib.util.spec_from_file_location("vs", Path(__file__).resolve().parents[1] / "scripts" / "verify_survivorship.py")
vs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vs)


def test_exits_flags_survivor_only_store():
    r = vs.exits({"A": date(2025, 12, 30), "B": date(2025, 12, 29)})
    assert r["exited"] == 0 and r["verdict"].startswith("생존 종목만")
    r = vs.exits({"A": date(2025, 12, 30), "B": date(2020, 3, 2)})
    assert r["exited"] == 1 and r["share"] == 0.5 and r["by_year"] == {"2020": 1}


def test_coverage_thresholds():
    fsc = {f"{i:06d}" for i in range(100)}
    assert vs.coverage(fsc, set(fsc))["status"] == "통과"
    assert vs.coverage(fsc, set(sorted(fsc)[:97]))["status"] == "경고"
    r = vs.coverage(fsc, set(sorted(fsc)[:90]))
    assert r["status"] == "실패" and r["n_missing"] == 10
    assert vs.coverage(set(), {"x"})["status"].startswith("범위 밖")


def test_fsc_codes_paging_and_prefix():
    pages = {1: [{"srtnCd": "A005930"}, {"srtnCd": "000660"}], 2: [{"srtnCd": "123"}]}

    def get(p):
        items = pages.get(int(p["pageNo"]), [])
        return {"response": {"body": {"totalCount": 3, "items": {"item": items}}}}
    assert vs.fsc_codes("k", "2020-01-02", get) == {"005930", "000660"}
