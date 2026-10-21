"""crash_rebound json meta(req-quant-892676d8): 5일 보유 창 정의·데이터 마지막 날·실행 커밋이 남는지."""
from screener.study import HOLD5_DEF, run_meta


def test_run_meta_fields(monkeypatch):
    monkeypatch.setenv("GITHUB_SHA", "abcdef1234567890")
    k = [{"d": "2026-10-14"}, {"d": "2026-10-15"}]
    lv = [{"d": "2026-10-15"}]
    m = run_meta(k, lv)
    assert m["kospi_last"] == "2026-10-15" and m["lev_last"] == "2026-10-15"
    assert m["git_sha"] == "abcdef12" and m["hold5_def"] == HOLD5_DEF
    assert "j+5" in HOLD5_DEF and "122630" in HOLD5_DEF


def test_run_meta_empty(monkeypatch):
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    m = run_meta([], [])
    assert m["kospi_last"] is None and m["git_sha"] is None
