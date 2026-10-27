"""ECOS 국고 일별 백필·KRX 대조 — 네트워크 없음 (data 10/27, req-data-76cf9141)."""
from datetime import date

from screener import ecos_ktb as ek


def _patch(tmp_path, monkeypatch):
    monkeypatch.setattr(ek, "CSV", tmp_path / "k.csv")
    monkeypatch.setattr(ek, "CHECK", tmp_path / "c.json")


def test_windows_sample_limit():
    w = ek.windows(date(2022, 1, 1), date(2022, 1, 31), 14)
    assert w[0] == (date(2022, 1, 1), date(2022, 1, 14)) and w[-1][1] == date(2022, 1, 31) and len(w) == 3


def test_backfill_keeps_existing_and_reconcile(tmp_path, monkeypatch):
    _patch(tmp_path, monkeypatch)
    ek.CSV.write_text("date,ktb3y,ktb10y,src\n2022-01-03,1.900,,old\n", encoding="utf-8")

    def fj(url):
        v = "2.000" if "010200000" in url else "2.500"
        return {"StatisticSearch": {"row": [{"TIME": "20220103", "DATA_VALUE": v}, {"TIME": "20220104", "DATA_VALUE": v}]}}
    r = ek.backfill(date(2022, 1, 3), date(2022, 1, 4), fetch_json=fj, env={})
    db = ek.load()
    assert r["key"] == "sample" and r["added"] == 1
    assert db["2022-01-03"]["ktb3y"] == "1.900" and db["2022-01-03"]["ktb10y"] == "2.500"   # 기존값 유지·빈칸만 채움
    out = ek.reconcile([{"date": "2022-01-04", "kr_3Y": 1.99, "kr_10Y": 2.5}])
    assert out["ktb3y"]["n"] == 1 and out["ktb3y"]["abs_max_bp"] == 1.0 and out["ktb10y"]["abs_max_bp"] == 0.0


def test_backfill_error_recorded(tmp_path, monkeypatch):
    _patch(tmp_path, monkeypatch)
    r = ek.backfill(date(2022, 1, 3), date(2022, 1, 4), fetch_json=lambda u: 1 / 0, env={})
    assert r["n_errors"] == 2 and r["rows"] == 0
