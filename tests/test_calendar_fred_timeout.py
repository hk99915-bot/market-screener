"""calendar_ev FRED: 첫 타임아웃 뒤 나머지 FRED 직접 호출 건너뜀 (req-data-fb0157f5)."""
import json

import requests

from screener import calendar_ev as ce


def test_fred_skip_after_timeout(tmp_path, monkeypatch):
    calls = []

    def fake_get(url, **kw):
        calls.append(url)
        assert "headers" not in kw  # 브라우저 UA 금지 — 기본 UA
        raise requests.Timeout("read timeout")

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(ce, "REL", tmp_path / "rel.json")
    monkeypatch.setattr(ce, "DBN", {})  # BLS/DBnomics 경로 끔 → 전부 FRED 직행
    monkeypatch.setattr(ce, "IND", {"g": [("PCEPI", "yoy", "a"), ("GDP", "yoy", "b"), ("DFEDTARU", "lvl", "c")]})
    ce.releases()
    assert len(calls) == 1  # 나머지 2개는 호출 안 함
    err = json.loads((tmp_path / "rel.json").read_text())["errors"]
    assert set(err) == {"PCEPI", "GDP", "DFEDTARU"} and "건너뜀" in err["GDP"]
    calls.clear()
    ce.releases()  # 다음 실행은 다시 시도
    assert len(calls) == 1
