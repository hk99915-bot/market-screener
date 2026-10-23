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
    fake = {sym: _ser([b * (1 + 0.01 * j) for b in base], real_today) for j, (_, sym, *_r) in enumerate(cm.SPEC) if sym != "ZNC=F"}
    out = cm.build(fetch=lambda syms: fake)
    keys = {r["key"]: r for r in out["rows"]}
    assert keys["ZINC"]["status"] == "미확인"
    assert keys["WTI"]["status"] == "ok"
    assert {"CRACK321", "BRENT_WTI", "GOLD_SILVER", "CU_AU"} <= set(keys)
    assert all(r.get("kr") for r in out["rows"]), "모든 지표에 한국 업종 연결"
    assert {u["key"] for u in out["unavailable"]} >= {"NICKEL", "SG_GRM"}
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
