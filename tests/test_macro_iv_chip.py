"""req-macro-e0ef2a13 (파생→매크로): 코스피200 ATM IV 칩 — 표시 전용·점수 제외·검증전."""
import json

from screener import macroview


def _w(d, name, obj):
    (d / name).write_text(json.dumps(obj), encoding="utf-8")


def test_iv_chip_daily_sigma(tmp_path, monkeypatch):
    monkeypatch.setattr(macroview, "REPORT_DIR", tmp_path)
    _w(tmp_path, "derivs.json", {"date": "2026-10-23", "atm_iv": 0.5403, "rv20": 0.482})
    c = macroview.iv_chip()
    assert c["label"] == "검증전" and c["scored"] is False
    assert abs(c["day_1s"] - 0.5403 / 252 ** 0.5) < 1e-4   # ≈ 3.4%
    assert "±3.4%" in c["state"] and c["date"] == "2026-10-23"


def test_iv_chip_missing_or_bad(tmp_path, monkeypatch):
    monkeypatch.setattr(macroview, "REPORT_DIR", tmp_path)
    assert macroview.iv_chip() is None
    _w(tmp_path, "derivs.json", {"atm_iv": None})
    assert macroview.iv_chip() is None
    _w(tmp_path, "derivs.json", {"atm_iv": 54.0})   # 퍼센트 단위 오입력 → 표시 안 함
    assert macroview.iv_chip() is None


def test_chip_not_in_score(tmp_path, monkeypatch):
    """칩이 있어도 rows·score 는 칩 없을 때와 같아야 한다."""
    monkeypatch.setattr(macroview, "REPORT_DIR", tmp_path)
    from screener import guard
    monkeypatch.setattr(guard, "_report_dir", lambda: tmp_path)
    rows = [[f"2026-{m:02d}-{d:02d}", 100 + i * 0.1, 100 + i * 0.1, 100 + i * 0.1, 100 + i * 0.1, 0]
            for i, (m, d) in enumerate((m, d) for m in range(1, 11) for d in range(1, 28))]
    _w(tmp_path, "macro_series.json", {"series": {"SPX": rows, "VIX": [[r[0], 18, 18, 18, 18, 0] for r in rows]}})
    a = macroview.build()
    _w(tmp_path, "derivs.json", {"date": "2026-10-23", "atm_iv": 0.9})
    (tmp_path / "macro_view.json").unlink()
    b = macroview.build()
    assert a["score"] == b["score"] and a["rows"] == b["rows"]
    assert "chips" not in a and b["chips"][0]["key"] == "K200_ATM_IV"
    assert all(r["key"] != "K200_ATM_IV" for r in b["rows"])
