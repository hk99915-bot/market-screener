"""scripts/brier_score.py — 확률 장부 채점 (req-quant-9aace2dc)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import brier_score as b  # noqa: E402

CALL = {"id": "x", "desk": "퀀트", "prob": 0.7, "status": "open", "outcome": None, "horizon_end": "2026-01-08",
        "auto": {"type": "close_up", "yf": "A.KS", "base_date": "2026-01-02", "horizon_days": 2}}
PX = {"A.KS": [("2026-01-02", 100.0), ("2026-01-05", 90.0), ("2026-01-06", 101.0)]}


def test_resolve_waits_until_horizon_then_scores():
    assert b.resolve(CALL, {"A.KS": PX["A.KS"][:2]}) is None            # 만기 시세 없음 → open 유지
    assert b.resolve(CALL, PX, asof="2026-01-05") is None
    r = b.resolve(CALL, PX)
    assert r["outcome"] == 1 and r["status"] == "hit" and r["resolved"] == "2026-01-06"
    down = {"A.KS": PX["A.KS"][:2] + [("2026-01-06", 100.0)]}
    assert b.resolve(CALL, down)["outcome"] == 0                         # 같으면 0 (높아야 1)
    assert b.resolve({**CALL, "status": "hit"}, PX) is None              # 이미 판정된 건은 안 건드림
    assert b.resolve({**CALL, "auto": None}, PX) is None


def test_brier_and_score_split_prob_vs_binary():
    assert b.brier([(0.4, 1), (0.5, 1), (0.57, 0), (0.44, 0)]) == 0.2821
    assert b.brier([]) is None
    calls = [{"id": "a", "desk": "퀀트", "prob": 0.8, "base_rate": 0.5, "status": "hit", "outcome": 1, "horizon_end": "2026-01-01"},
             {"id": "b", "desk": "퀀트", "prob": 0.3, "status": "miss", "outcome": 0, "horizon_end": "2026-01-01"},
             {"id": "c", "desk": "애널", "prob": None, "status": "hit", "outcome": None, "horizon_end": "2026-01-01"},
             {"id": "d", "desk": "애널", "prob": None, "status": "open", "outcome": None, "horizon_end": "2026-02-01"}]
    calls[2]["outcome"] = 1
    s = b.score(calls)
    assert s["brier"] == round((0.04 + 0.09) / 2, 4) and s["n_prob_resolved"] == 2
    assert s["brier_base_rate"] == 0.25 and s["brier_same_calls_as_base"] == 0.04
    assert s["binary_resolved"] == 1 and s["binary_hits"] == 1 and s["n_open"] == 1 and s["next_due"] == "2026-02-01"
    assert s["by_desk"]["애널"]["hit_rate"] == 1.0 and s["by_desk"]["퀀트"]["brier"] == 0.065
    assert "0.25" in b.build_md(calls, s, "2026-01-02")


def test_ledger_structure_and_no_private_levels():
    led = json.loads(b.LEDGER.read_text(encoding="utf-8"))
    keys = {"id", "desk", "made", "subject", "claim", "prob", "horizon_end", "checks", "wrong_if", "resolve_rule", "status", "outcome"}
    ids = [c["id"] for c in led["calls"]]
    assert len(ids) == len(set(ids))
    for c in led["calls"]:
        assert keys <= set(c), c["id"]
        assert c["status"] in ("open", "hit", "miss", "void")
        assert c["prob"] is None or 0 <= c["prob"] <= 1
        if c["status"] in ("hit", "miss"):
            assert c["outcome"] in (0, 1) and (c["status"] == "hit") == (c["outcome"] == 1)
    assert "원" not in json.dumps(led["calls"], ensure_ascii=False).replace("원문", "")   # 가격·금액 수준 기록 금지
