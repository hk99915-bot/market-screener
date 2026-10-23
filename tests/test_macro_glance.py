"""MACRO 한눈에 층별 줄 (macroview.glance, 10/24 매크로) — 숫자는 산출물에서 자동, 해석은 views/macro_glance.json, 점수 불변."""
import json

from screener import config, macroview


def _w(d, name, obj):
    p = d / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def _fixture(tmp_path, monkeypatch):
    rep, data = tmp_path / "reports", tmp_path / "data"
    monkeypatch.setattr(macroview, "REPORT_DIR", rep)
    monkeypatch.setattr(config, "DATA_DIR", data)
    _w(rep, "bonds.json", {"kr": {"chg": {"3Y": {"v": 3.80, "m1": -20.0, "date": "2026-10-23"}}},
                           "us": {"chg": {"2Y": {"v": 4.65, "m1": -6.0, "date": "2026-10-22"}}}})
    _w(rep, "realestate.json", {"rates": [{"key": "BOK_BASE", "status": "ok", "last": 3.0, "month": "2026-09"}]})
    _w(rep, "views/macro_glance.json", {"updated": "2026-10-24 KST", "policy": {"fed_upper": 4.0},
                                        "layers": {"rates": {"take": "매파적 동결", "flip": "FOMC 동결", "grade": "검증전"}}})
    _w(rep, "commodities.json", {"asof": "2026-10-23", "rows": [
        {"key": "BRENT", "status": "ok", "last": 111.45, "chg1m": 0.045, "pos52": 0.88},
        {"key": "TTF", "status": "ok", "last": 93.8, "chg1m": 0.25, "pos52": 1.0},
        {"key": "COPPER", "status": "ok", "last": 6.49, "chg1m": -0.034},
        {"key": "GOLD", "status": "ok", "last": 4034, "chg1m": -0.061},
        {"key": "CU_AU", "status": "ok", "last": 1.609, "d1m": 0.046, "pos52": 0.999}]})
    _w(rep, "views/geopolitics.json", {"updated": "2026-10-23", "axes": [
        {"id": "redsea", "name": "홍해", "level": "중간"}, {"id": "hormuz", "name": "호르무즈", "level": "높음"},
        {"id": "rare_earth", "name": "희토류", "level": "높음"}]})
    _w(rep, "geo_news.json", {"generated_at": "2026-10-23 23:03 KST", "axes": [
        {"id": "hormuz", "items": [{"title": "Oil above $115", "src": "X", "time": "2026-10-23 22:27"}]}]})
    for code, r in (("005930", -0.21), ("000660", -0.32)):
        _w(rep, f"detail/KR/{code}.json", {"asof": "2026-10-23", "stats": {"ret20": r}})
    (data / "deriv").mkdir(parents=True)
    rows = ["date,spot_frgn,spot_inst,spot_indiv"] + [f"2026-10-{i:02d},-1000,100,500" for i in range(1, 23)]
    (data / "deriv" / "daily.csv").write_text("\n".join(rows), encoding="utf-8")
    _w(rep, "calendar.json", {"asof": "2026-10-23 19:22", "events": [
        {"date": "2026-10-28", "type": "매크로", "imp": 3, "name": "FOMC 금리 결정", "note": "10/28 14:00 ET → 한국 10/29 03:00"},
        {"date": "2026-10-28", "type": "실적", "imp": 3, "name": "SK하이닉스 실적"},
        {"date": "2026-10-29", "type": "실적", "imp": 3, "name": "삼성전자 실적"},
        {"date": "2026-10-29", "type": "실적", "imp": 3, "name": "Amazon 실적"},
        {"date": "2026-10-30", "type": "매크로", "imp": 3, "name": "BOJ 금리 결정"},
        {"date": "2026-11-06", "type": "매크로", "imp": 2, "name": "미 고용보고서"}]})
    return {"KOSPI": {"chg20": -0.208, "date": "2026-10-23"}, "SPX": {"chg20": -0.005}, "KOSDAQ": {"chg20": -0.10},
            "USDKRW": {"chg20": -0.03}}


def test_glance_layers(tmp_path, monkeypatch):
    st = _fixture(tmp_path, monkeypatch)
    g = {r["id"]: r for r in macroview.glance(st, today="2026-10-24")}
    assert list(g) == ["rates", "cmd", "geo", "kr", "events"]
    assert "+80bp" in g["rates"]["line"] and "+65bp" in g["rates"]["line"] and "2.6회분" in g["rates"]["line"]
    assert g["rates"]["desk"]["take"] == "매파적 동결" and g["cmd"]["desk"] is None   # 해석은 views 파일에 있는 층만
    assert "금이 더 빠진 몫" in g["cmd"]["line"] and "52주 100%" in g["cmd"]["line"]
    assert g["geo"]["line"].startswith("호르무즈[높음]") and "희토류[높음]" in g["geo"]["line"] and "홍해" not in g["geo"]["line"]
    assert "Oil above $115" in g["geo"]["line"] and "최근 매칭 뉴스 없음" in g["geo"]["line"]
    k = g["kr"]["line"]
    assert "격차 -20.3%p" in k and "반도체 쏠림 ○" in k and "외국인 매도 ○" in k and "-2.0조" in k and "환율 ✕" in k and "미확인" in k
    e = g["events"]["line"]
    assert e.startswith("10/29 03:00 FOMC★") and "SK하이닉스 10/28·삼성전자 10/29" in e and "BOJ" in e
    assert "Amazon" not in e and "고용" not in e   # 7일 밖·한국 반도체 아닌 실적 제외
    assert all(r["src"] and r["label"] for r in g.values())


def test_glance_missing_inputs(tmp_path, monkeypatch):
    monkeypatch.setattr(macroview, "REPORT_DIR", tmp_path)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    g = {r["id"]: r for r in macroview.glance({}, today="2026-10-24")}
    assert len(g) == 5   # 재료 없어도 층을 빼지 않는다
    assert "데이터 없음" in g["rates"]["line"] and "데이터 없음" in g["cmd"]["line"] and "데이터 없음" in g["geo"]["line"]
    assert "데이터 없음" in g["kr"]["line"] and "일정 없음" in g["events"]["line"]


def test_glance_not_in_score(tmp_path, monkeypatch):
    """glance 는 표시 전용 — views 해석이 있든 없든 score·rows 동일."""
    rep = tmp_path / "reports"
    st = _fixture(tmp_path, monkeypatch)
    from screener import guard
    monkeypatch.setattr(guard, "_report_dir", lambda: rep)
    rows = [[f"2026-{m:02d}-{d:02d}", 100 + i * 0.1, 100 + i * 0.1, 100 + i * 0.1, 100 + i * 0.1, 0]
            for i, (m, d) in enumerate((m, d) for m in range(1, 11) for d in range(1, 28))]
    _w(rep, "macro_series.json", {"series": {"SPX": rows, "KOSPI": rows, "USDKRW": rows}})
    a = macroview.build()
    (rep / "views" / "macro_glance.json").unlink()
    (rep / "macro_view.json").unlink()
    b = macroview.build()
    assert a["score"] == b["score"] and a["rows"] == b["rows"] and a["summary"] == b["summary"]
    assert len(a["glance"]) == 5 and a["glance"][0]["desk"] and not b["glance"][0]["desk"]
    assert st   # fixture 사용
