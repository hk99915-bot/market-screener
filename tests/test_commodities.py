"""원자재 트래킹(screener/commodities.py)·지정학 축(reports/views/geopolitics.json) — 매크로 10/23. 네트워크 없음(가짜 fetch)."""
import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from screener import commodities as cm

ROOT = Path(__file__).resolve().parents[1]
TODAY = date(2026, 10, 23)


def _ser(vals, end=TODAY):
    return [((end - timedelta(days=len(vals) - 1 - i)).isoformat(), v) for i, v in enumerate(vals)]


def test_stats_levels_and_pos52():
    s = cm.stats(_ser([100.0 + i for i in range(300)]), TODAY)
    assert s["status"] == "ok" and s["last"] == 399
    assert s["chg1w"] == pytest.approx(399 / 394 - 1, abs=1e-4)
    assert s["chg1m"] == pytest.approx(399 / 378 - 1, abs=1e-4)
    assert s["pos52"] == 1.0 and s["d1m"] == 21


def test_stats_flags_frozen_quotes_and_old_dates():
    frozen = cm.stats(_ser([float(i) for i in range(1, 60)] + [5.0] * 20), TODAY)
    assert frozen["status"] == "미확인" and "호가 정체" in frozen["why"]
    old = cm.stats(_ser([1.0 + i for i in range(100)], TODAY - timedelta(days=30)), TODAY)
    assert old["status"] == "미확인" and "갱신 없음" in old["why"]
    assert cm.stats(_ser([1.0] * 10), TODAY)["status"] == "미확인"


def test_crack321_formula():
    # (2×2.5×42 + 3.0×42 − 3×80) ÷ 3 = (210 + 126 − 240) ÷ 3 = 32
    assert cm.crack321(80, 2.5, 3.0) == pytest.approx(32.0)


def test_build_with_fake_fetch_marks_missing_as_unconfirmed(tmp_path, monkeypatch):
    monkeypatch.setattr(cm, "OUT", tmp_path / "commodities.json")
    real_today = date.today()
    base = [50 + (i % 7) for i in range(260)]
    fake = {sym: _ser([b * (1 + 0.01 * j) for b in base], real_today) for j, (_, sym, *_r) in enumerate(cm.SPEC) if sym != "ZINC.L"}
    out = cm.build(fetch=lambda syms: fake)
    keys = {r["key"]: r for r in out["rows"]}
    assert keys["ZINC"]["status"] == "미확인"
    assert keys["WTI"]["status"] == "ok"
    assert {"CRACK321", "BRENT_WTI", "GOLD_SILVER", "CU_AU"} <= set(keys)
    assert all(r.get("kr") for r in out["rows"]), "모든 지표에 한국 업종 연결"
    assert {u["key"] for u in out["unavailable"]} >= {"SG_GRM", "RE_OXIDE", "COBALT"}
    assert keys["NICKEL"]["status"] == "ok" and keys["JKM"]["status"] == "ok"   # 10/23 데이터: ETC·NYMEX 정산가로 일간 대용
    assert keys["NICKEL_M"]["status"] == "미확인" and keys["NICKEL_M"]["freq"] == "월간"   # 가짜 fetch 면 월간은 네트워크 없이 생략
    assert out["source_notes"] and any("토스" in t for t in out["source_notes"])
    assert "매수 권유 아님" in out["label"]


def test_build_fetch_failure_writes_reason(tmp_path, monkeypatch):
    monkeypatch.setattr(cm, "OUT", tmp_path / "commodities.json")

    def boom(_):
        raise RuntimeError("yahoo down")
    out = cm.build(fetch=boom)
    assert out["errors"] and all(r["status"] == "미확인" for r in out["rows"])


def test_geopolitics_axes_have_required_fields_and_three_column_sources():
    g = json.loads((ROOT / "reports/views/geopolitics.json").read_text(encoding="utf-8"))
    ids = {a["id"] for a in g["axes"]}
    assert {"hormuz", "redsea", "ruukr", "rare_earth", "chips", "taiwan", "korea", "tariff"} <= ids
    known = {k for k, *_ in cm.SPEC} | {"CRACK321", "BRENT_WTI", "GOLD_SILVER", "CU_AU", "USDKRW"}
    for a in g["axes"]:
        for f in ("name", "level", "status", "path", "watch", "triggers", "sources"):
            assert a.get(f), (a["id"], f)
        assert set(a["watch"]) <= known, a["id"]
        for s in a["sources"]:   # STANDARD §4: 링크만 금지 — 내용·뷰·우리 해석 세 칸 + 날짜
            assert s.get("summary") and s.get("view") and s.get("our_take") and s.get("date"), (a["id"], s.get("title"))


def test_parse_fred_csv_skips_missing_and_html():
    txt = "observation_date,PNICKUSDM\n2026-07-01,15000.5\n2026-08-01,.\n2026-09-01,16323.8\n"
    assert cm.parse_fred_csv(txt) == [("2026-07-01", 15000.5), ("2026-09-01", 16323.8)]
    assert cm.parse_fred_csv("<html><script src=x></script></html>") == []   # 없는 시리즈 = 봇 확인 페이지


def _months(vals, last="2026-09-01"):
    y, m = int(last[:4]), int(last[5:7])
    out = []
    for i in range(len(vals)):
        k = m - (len(vals) - 1 - i)
        yy, mm = y + (k - 1) // 12, (k - 1) % 12 + 1
        out.append((f"{yy:04d}-{mm:02d}-01", vals[i]))
    return out


def test_stats_monthly_changes_and_staleness():
    s = cm.stats_monthly(_months([100.0 + i for i in range(24)]), TODAY)
    assert s["status"] == "ok" and s["freq"] == "월간" and s["last"] == 123
    assert s["chg1m"] == pytest.approx(123 / 122 - 1, abs=1e-4) and s["chg12m"] == pytest.approx(123 / 111 - 1, abs=1e-4)
    assert s["pos52"] == 1.0
    old = cm.stats_monthly(_months([1.0 + i for i in range(24)], "2026-05-01"), TODAY)
    assert old["status"] == "미확인" and "새 값 없음" in old["why"]
    assert cm.stats_monthly(_months([1.0] * 5), TODAY)["status"] == "미확인"


def test_build_monthly_rows_marked_and_excluded_from_movers(tmp_path, monkeypatch):
    monkeypatch.setattr(cm, "OUT", tmp_path / "commodities.json")
    real_today = date.today()
    first = date(real_today.year, real_today.month, 1)
    last = (first - timedelta(days=1)).replace(day=1).isoformat()
    jump = _months([100.0] * 23 + [200.0], last)   # 전월 +100% 라도 '1개월 급변' 요약에는 안 들어가야 함(월간)
    out = cm.build(fetch=lambda syms: {}, fetch_monthly=lambda ids: {i: jump for i in ids})
    m = [r for r in out["rows"] if r.get("freq") == "월간"]
    assert len(m) == len(cm.MONTHLY) and all(r["status"] == "ok" and r["note"].startswith("월간") for r in m)
    assert "없음" in out["summary"] and out["asof"] is None   # 일간이 전부 없으면 날짜 비움(월간 날짜로 대체 안 함)
