"""reports/views/pm_voices.json 장부 형식 검사 — 네트워크 없음 (analyst 데스크, 2026-11-07)."""
from __future__ import annotations

import json
from pathlib import Path

P = Path(__file__).resolve().parents[1] / "reports" / "views" / "pm_voices.json"
REQ = {"date", "who", "asset", "dir", "horizon", "why", "relay", "url", "src_kind", "status"}


def test_pm_voices_calls_have_fields():
    d = json.loads(P.read_text(encoding="utf-8"))
    assert d["grade"] == "검증전"
    kinds = set(d["meta"]["src_kinds"])
    names = {p["name"] for p in d["people"]}
    for c in d["calls"]:
        assert REQ <= set(c), c
        assert c["who"] in names
        # 복합 출처('A + B')도 각 조각이 정의된 src_kind 로 시작해야 한다
        for part in c["src_kind"].split(" + "):
            assert any(part.startswith(k) for k in kinds), part
        # 붙여넣기 글은 링크가 없으므로 url 이 비어 있어야 정직하다
        if c["src_kind"] == "겸이 붙여넣기":
            assert c["url"] is None


def test_pm_voices_candidates_have_risk():
    d = json.loads(P.read_text(encoding="utf-8"))
    for c in d["candidates"]:
        assert c["risk"] and c["channels"] and c["useful"], c["name"]
