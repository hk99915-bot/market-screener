"""screener.sec 회전 배치·증분·진행 상태 (네트워크 없음 — _get 을 가짜로 바꾼다) + 반도체 바스켓 확장 (10/24 ra-sec-coverage)."""
import json
from datetime import date

import polars as pl
import pytest

from screener import sec
from screener import valuation_daily as vd


def _sub(*pairs):
    return {"filings": {"recent": {"form": [f for f, _ in pairs], "filingDate": [d for _, d in pairs]}}}


def test_last_periodic_filed_ignores_8k_and_proxy():
    s = _sub(("8-K", "2026-10-20"), ("10-Q", "2026-08-01"), ("DEF 14A", "2026-09-01"), ("10-K", "2026-02-01"))
    assert sec.last_periodic_filed(s) == "2026-08-01"
    assert sec.last_periodic_filed(_sub(("20-F", "2026-04-16"))) == "2026-04-16"
    assert sec.last_periodic_filed({}) is None


def test_plan_priority_first_then_oldest_and_budget():
    now = 100 * 86400
    stamp = {"A": now - 10 * 86400, "B": now - 30 * 86400, "C": now - 1 * 86400, "P": now - 8 * 86400}
    out = sec.plan(["A", "B", "C", "D", "P"], stamp, now, refresh_days=7, budget=3, priority=["P", "C"])
    assert out == ["P", "D", "B"]          # P 우선(C 는 아직 주기 안 됨) → 한 번도 안 받은 D → 가장 오래된 B (A 는 예산 밖)
    assert sec.plan(["A"], {}, now, 7, 0) == []


def test_progress_summary_eta():
    prog = {"tickers": {"A": {"checked": "x", "fetched": "x", "status": "ok"}, "Z": {"status": "no_cik"}}}
    s = sec.progress_summary(prog, ["A", "B", "C", "Z"], budget=1, today=date(2026, 10, 24))
    assert s["universe"] == 4 and s["fetched_ever"] == 1 and s["pending_first_check"] == 2
    assert s["by_status"] == {"ok": 1, "never": 2, "no_cik": 1}
    assert s["eta_first_cycle"] == "2026-10-26"


def _facts(ni=5.0):
    rec = [{"start": "2026-01-01", "end": "2026-03-31", "val": ni, "fp": "Q1", "filed": "2026-04-30"}]
    return {"facts": {"us-gaap": {"NetIncomeLoss": {"units": {"USD": rec}}}}}


@pytest.fixture
def fake(tmp_path, monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "test test@example.com")
    for k, v in {"FIN": tmp_path, "OUT": tmp_path / "q.parquet", "STAMP": tmp_path / "stamp.json", "PROGRESS": tmp_path / "prog.json"}.items():
        monkeypatch.setattr(sec, k, v)
    monkeypatch.setattr(sec, "ticker_map", lambda: {"AAA": 1, "IFR": 2})
    calls = []
    state = {"filed": "2026-04-30"}

    def get(url):
        calls.append(url)
        if "submissions" in url:
            return _sub(("10-Q", state["filed"]))
        if "CIK0000000002" in url:
            return {"facts": {"ifrs-full": {}, "dei": {}}}
        return _facts()
    monkeypatch.setattr(sec, "_get", get)
    return calls, state, tmp_path


def test_update_incremental_and_progress(fake):
    calls, state, tmp = fake
    assert sec.update(["AAA", "IFR", "GONE"], refresh_days=0, budget=10) == 2
    prog = json.loads((tmp / "prog.json").read_text())
    t = prog["tickers"]
    assert t["AAA"]["status"] == "ok" and t["AAA"]["last_filed"] == "2026-04-30"
    assert t["IFR"]["status"] == "ifrs" and t["GONE"]["status"] == "no_cik"     # 조용히 빼지 않는다
    assert sum("companyfacts" in c for c in calls) == 2
    # 같은 정기보고서 → companyfacts 생략(증분), 상태 유지
    calls.clear()
    sec.update(["AAA", "IFR"], refresh_days=0, budget=10)
    assert not any("companyfacts" in c for c in calls)
    t = json.loads((tmp / "prog.json").read_text())["tickers"]
    assert t["AAA"]["status"] == "unchanged" and t["IFR"]["status"] == "ifrs"
    # 새 10-Q 제출 → 다시 받는다
    state["filed"] = "2026-07-30"
    calls.clear()
    sec.update(["AAA"], refresh_days=0, budget=10)
    assert sum("companyfacts" in c for c in calls) == 1
    df = pl.read_parquet(tmp / "q.parquet")
    assert df.filter(pl.col("ticker") == "AAA")["value"].to_list() == [5.0]


def test_update_respects_budget(fake):
    calls, _, tmp = fake
    assert sec.update(["AAA", "IFR"], refresh_days=0, budget=1) == 1
    s = json.loads((tmp / "prog.json").read_text())["summary"]
    assert s["pending_first_check"] == 1 and s["budget_per_run"] == 1


def test_basket_extends_with_semis_file(tmp_path):
    p = tmp_path / "semis.json"
    p.write_text(json.dumps({"asof": {"SOXX": "2026-06-30"}, "members": [
        {"sym": "MU", "name": "Micron", "etf": {"SOXX": 8.5}}, {"sym": "ICHR", "name": "Ichor", "etf": {"PSI": 3.3}}]}), encoding="utf-8")
    b = vd.basket_members(str(p))
    syms = [x["sym"] for x in b]
    assert syms[:len(vd.BASKET)] == [x["sym"] for x in vd.BASKET]      # 고정 바스켓 순서 유지
    assert syms.count("MU") == 1 and syms[-1] == "ICHR"
    assert next(x for x in b if x["sym"] == "MU")["etf_w"] == {"SOXX": 8.5}
    assert len(vd.basket_members(str(tmp_path / "none.json"))) == len(vd.BASKET)   # 파일 없으면 고정만


def test_stale_quarter():
    assert vd.stale_quarter("2024-06-30", date(2026, 10, 24))
    assert not vd.stale_quarter("2026-06-30", date(2026, 10, 24))


def test_semis_basket_file_is_consistent():
    j = json.loads(open("universe/semis_basket.json", encoding="utf-8").read())
    syms = [m["sym"] for m in j["members"]]
    assert len(syms) == len(set(syms)) == j["n"] >= 30
    assert set(j["asof"]) == {"SOXX", "PSI"}
    pri = set(pl.read_csv("universe/us_priority.csv")["yf"].to_list())
    assert set(syms) <= pri                                       # 바스켓 전 종목이 SEC 우선 수집 목록에


def test_earnings_cal_marks_past_and_keeps_errors(tmp_path, monkeypatch):
    from screener import earnings_cal as ec
    monkeypatch.setattr(ec, "OUT", tmp_path / "e.json")
    fake = {"A": {"sym": "A", "date": "2000-01-01", "eps_avg": 1.0, "eps_n": 3, "rev_avg": None, "err": None},
            "B": {"sym": "B", "date": None, "eps_avg": None, "eps_n": None, "rev_avg": None, "err": "예정일 없음"},
            "C": {"sym": "C", "date": "2999-01-01", "eps_avg": 2.0, "eps_n": 5, "rev_avg": None, "err": None}}
    o = ec.build(["A", "B", "C"], fetch=lambda t: dict(fake[t]))
    by = {r["sym"]: r for r in o["rows"]}
    assert by["A"]["past"] and not by["C"]["past"] and by["B"]["err"] == "예정일 없음"
    assert o["n_dated"] == 2 and (tmp_path / "e.json").exists()
    (tmp_path / "e.json").unlink()
    ec.build(["B"], fetch=lambda t: dict(fake[t]))
    assert not (tmp_path / "e.json").exists()      # 0건이면 이전 파일 유지(덮어쓰지 않음)


def test_build_runs_with_extended_basket(tmp_path, monkeypatch):
    """build() 이 확장 바스켓으로 끝까지 돈다(10/24 basket 이름 충돌 회귀 방지) — 재무·가격 없으면 플래그만."""
    from screener import config
    monkeypatch.setattr(config, "REPORT_DIR", tmp_path)
    monkeypatch.setattr(vd, "us_quarters", lambda s: ([], None))
    monkeypatch.setattr(vd, "kr_quarters", lambda s: ([], None))
    monkeypatch.setattr(vd, "sec_status", lambda: {"TSM": "ifrs"})
    o = vd.build(send=False)
    assert o["basket"]["n"] == len(vd.basket_members()) > len(vd.BASKET)
    tsm = next(r for r in o["rows"] if r["sym"] == "TSM")
    assert any("IFRS" in f for f in tsm["flags"])
