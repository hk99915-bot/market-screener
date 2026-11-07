"""reports/views/hf_positioning.json 장부 형식 검사 — 네트워크 없음 (hf 데스크, 2026-11-07)."""
from __future__ import annotations

import json
from pathlib import Path

P = Path(__file__).resolve().parents[1] / "reports" / "views" / "hf_positioning.json"
SERIES_REQ = {"name", "value", "pctile", "base_period", "src", "src_kind", "verified"}
SIG_REQ = {"id", "name", "series", "rule", "current", "state", "disclaimer"}


def _d():
    return json.loads(P.read_text(encoding="utf-8"))


def test_series_fields_and_honesty():
    d = _d()
    assert d["grade"] == "검증전" and d["asof"]
    kinds = set(d["meta"]["src_kinds"])
    for s in d["series"]:
        assert SERIES_REQ <= set(s), s
        assert s["src_kind"] in kinds
        assert s["pctile"] is None or 0 <= s["pctile"] <= 100
        # 붙여넣기 2차 기준선은 원문 미확인 → verified 가 참이면 안 된다
        if s["src_kind"].startswith("겸이 붙여넣기"):
            assert s["verified"] is False, s["name"]
    for block in ("flows", "sold_assets", "strategy_pnl"):
        for row in d[block]:
            assert "verified" in row and "src_kind" in row, (block, row)


def test_signals_are_observations_not_trades():
    d = _d()
    names = {s["name"] for s in d["series"]}
    assert len(d["signals"]) >= 4
    for g in d["signals"]:
        assert SIG_REQ <= set(g), g
        assert g["series"] in names, g["series"]
        assert "매매 신호 아님" in g["disclaimer"]
        cur = next(s["pctile"] for s in d["series"] if s["name"] == g["series"])
        assert g["current"] == cur, g["id"]


def test_narratives_unverified_and_refresh_not_applied():
    d = _d()
    assert all(n["status"] == "미확인" for n in d["narratives"])
    assert "[제안-미적용]" in d["refresh"]["tag"]
    assert len(d["hf_book_view"]) == 4
