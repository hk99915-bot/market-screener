"""DART 타법인 출자·최대주주 수집기 — 네트워크 없이 숫자 정리·합계 행 제외·기간 폴백·건너뜀 검증 (11/1 금융·원자재 지분 엣지)."""
import json

from screener import dart_equity as de


def test_num_and_tidy():
    assert de.num("1,234") == 1234.0 and de.num("-") is None and de.num("(5)") == -5.0 and de.num("") is None
    rows = [{"inv_prm": " 신한은행 ", "trmend_blce_qota_rt": "100.00", "trmend_blce_acntbk_amount": "15,000", "invstmnt_purps": "경영참여"},
            {"inv_prm": "합 계", "trmend_blce_acntbk_amount": "15,000"}]
    t = de.tidy(rows, de.INV)
    assert len(t) == 1 and t[0]["name"] == "신한은행" and t[0]["pct"] == 100.0 and t[0]["book"] == 15000.0
    assert t[0]["purpose"] == "경영참여" and t[0]["shares"] is None


def test_fresh_rules():
    assert not de.fresh(None, (2026, "11012"), "2026-11-01")
    assert de.fresh({"status": "ok", "year": 2026, "reprt": "11012"}, (2026, "11012"), "2026-11-01")
    assert de.fresh({"status": "ok", "year": 2025, "reprt": "11011", "fetched": "2026-10-25"}, (2026, "11012"), "2026-11-01")
    assert not de.fresh({"status": "ok", "year": 2025, "reprt": "11011", "fetched": "2026-08-01"}, (2026, "11012"), "2026-11-01")
    assert de.fresh({"status": "none", "fetched": "2026-10-20"}, (2026, "11012"), "2026-11-01")
    assert not de.fresh({"status": "none", "fetched": "2026-09-01"}, (2026, "11012"), "2026-11-01")


def test_update_falls_back_and_skips(tmp_path, monkeypatch):
    monkeypatch.setattr(de, "OUT", tmp_path)
    monkeypatch.setattr(de, "INDEX", tmp_path / "index.json")
    monkeypatch.setattr(de, "key", lambda: "k")
    monkeypatch.setattr(de, "candidates", lambda tries=3: [(2026, "11012"), (2025, "11011")])
    import screener.fin as fin
    monkeypatch.setattr(fin, "corp_codes", lambda: {"105560": "00688996", "000001": "00000001"})
    calls = []

    def fake_get(path, params, bud, binary=False):
        bud.take()
        calls.append((path, params["bsns_year"]))
        if params["corp_code"] == "00000001" or params["bsns_year"] == "2026":
            return {"status": "013"}
        if path.startswith("otr"):
            return {"status": "000", "list": [{"corp_name": "KB금융", "rcept_no": "2025R", "inv_prm": "국민은행", "trmend_blce_qota_rt": "100"}]}
        return {"status": "000", "list": [{"corp_name": "KB금융", "nm": "국민연금공단", "relate": "최대주주", "trmend_posesn_stock_qota_rt": "8.1"}]}

    monkeypatch.setattr(de, "_get", fake_get)
    st = de.update(["105560", "000001", "999999"], sleep=0)
    assert st["new"] == 1 and st["none"] == 1 and st["no_corp"] == 1 and st["api_calls"] == 8
    doc = json.loads((tmp_path / "105560.json").read_text(encoding="utf-8"))
    assert (doc["year"], doc["reprt"], doc["rcept_no"]) == (2025, "11011", "2025R")
    assert doc["invest"][0]["name"] == "국민은행" and doc["holders"][0]["pct"] == 8.1
    ix = {r["code"]: r for r in json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))["items"]}
    assert ix["105560"]["n_invest"] == 1 and ix["000001"]["status"] == "none"
    calls.clear()
    st = de.update(["000001"], sleep=0)                   # 없음 판정 30일 안 → 건너뜀
    assert st["skip"] == 1 and calls == []
