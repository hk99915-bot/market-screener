"""WICS 수집기 (screener/wics.py) — 가짜 응답(10/21 Actions 탐침에서 본 실제 꼴: info·list[IDX_NM_KOR, CMP_CD, SEC_NM_KOR]). 네트워크 없음."""
from __future__ import annotations

from datetime import datetime

from screener import tradecal, wics


def fake_get(calls):
    data = {"G45": [("005930", "IT", "WICS IT"), ("000660", "IT", "WICS IT"), ("035420", "IT", "WICS IT")],
            "G4530": [("005930", "IT", "WICS 반도체와반도체장비"), ("000660", "IT", "WICS 반도체와반도체장비")],
            "G4510": [("035420", "IT", "WICS 소프트웨어와서비스")],
            "G25": [("005380", "경기관련소비재", "WICS 경기관련소비재")]}

    def get(url, params):
        calls.append(params)
        rows = data.get(params["sec_cd"], [])
        return {"info": {"CNT": len(rows)}, "list": [{"IDX_CD": params["sec_cd"], "IDX_NM_KOR": n, "CMP_CD": c, "SEC_NM_KOR": l1} for c, l1, n in rows]}
    return get


def test_fetch_builds_l1_l2_and_counts_calls():
    calls = []
    rows, st = wics.fetch(datetime(2026, 10, 20).date(), fake_get(calls), sleep=lambda s: None)
    by = {r["code"]: r for r in rows}
    assert by["005930"] == {"code": "005930", "wics_l1": "IT", "wics_l2": "반도체와반도체장비"}
    assert by["035420"]["wics_l2"] == "소프트웨어와서비스" and by["005380"]["wics_l2"] == ""   # 중분류 못 찾음 → 대분류만
    assert st["calls"] == len(calls) == len(wics.L1) * (1 + len(wics.L2_SUFFIX)) == 100
    assert all(p["dt"] == "20261020" for p in calls)


def test_update_if_stale_writes_and_skips(tmp_path, monkeypatch):
    p = tmp_path / "kr_wics.csv"
    monkeypatch.setattr(wics, "MIN_ROWS", 3)
    now = datetime(2026, 10, 21, 1, 0, tzinfo=tradecal.KST)       # 18시 전 → 전 거래일(10/20) 구성
    r = wics.update_if_stale(now, fake_get([]), p, sleep=lambda s: None)
    assert r["status"] == "updated" and r["asof"] == "2026-10-20"
    assert wics.read(p) == ("2026-10-20", 4)
    calls = []
    assert wics.update_if_stale(now, fake_get(calls), p, sleep=lambda s: None)["status"] == "fresh" and calls == []


def test_update_partial_failure_keeps_old_and_records_stale(tmp_path, monkeypatch):
    p = tmp_path / "universe" / "kr_wics.csv"
    p.parent.mkdir()
    wics.write([{"code": "005930", "wics_l1": "IT", "wics_l2": "반도체와반도체장비"}], "2026-10-15", p)
    seen = []
    monkeypatch.setattr("screener.guard.record_stale", lambda *a: seen.append(a))
    r = wics.update_if_stale(datetime(2026, 10, 21, 19, 0, tzinfo=tradecal.KST), lambda u, q: None, p, sleep=lambda s: None)
    assert r["status"] == "stale" and wics.read(p) == ("2026-10-15", 1) and seen and seen[0][2] == "2026-10-21"
