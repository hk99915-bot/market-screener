"""진입 전 세 줄 도우미(scripts/three_lines.py)."""
import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import three_lines as T  # noqa: E402


def _w(root, code, ch, flow=""):
    p = root / "reports" / "detail" / "KR"
    p.mkdir(parents=True, exist_ok=True)
    (p / f"{code}.json").write_text(json.dumps({"name": code, "chart": ch, "flow_note": flow}))


def _ch(n=260, c=100.0):
    d, out = date(2025, 9, 1), []
    for _ in range(n):
        while d.weekday() >= 5:
            d += timedelta(days=1)
        out.append({"t": d.isoformat(), "o": c, "h": c * 1.02, "l": c * 0.98, "c": c, "v": 1000, "s50": c, "s200": c * 0.9})
        d += timedelta(days=1)
    return out


def test_numbers_and_options(tmp_path):
    _w(tmp_path, "A", _ch(), "5일 외국인 +5억 · 기관 +3억 — 동반 매수")
    o = T.build("A", "KR", root=tmp_path, today=date(2026, 10, 22))
    assert o["stop"] < o["close"] < o["t1"] and o["p_be"] == 0.4
    assert any("수급" in x for x in o["why_options"]) and o["kill_options"][0].startswith("종가가 손절")
    assert "세 줄 예시" in T.render(o)


def test_chase_and_outflow_warnings(tmp_path):
    ch = _ch()
    ch[-1].update({"c": 110.0, "h": 111.0, "v": 5000})
    _w(tmp_path, "B", ch, "5일 외국인 -5억 · 기관 -3억 — 동반 매도")
    o = T.build("B", "KR", root=tmp_path, today=date(2026, 10, 22))
    assert any("추격" in x for x in o["warn"]) and any("수급 이탈" in x for x in o["warn"])


def test_missing_data(tmp_path):
    assert "안 산다" in T.render(T.build("ZZZ", "US", root=tmp_path))
