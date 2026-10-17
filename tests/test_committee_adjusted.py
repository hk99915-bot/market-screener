"""감사 M4 (2026-10-17 refactor_audit): PB 커밋 42954487 — committee.score · _ideas_log_score · main.rebuild_detail_kr 가
prices.load_kr(기업행위 조정가)로 바뀜. 1:5 액면분할 픽스처로 원본(raw)과 조정가가 다를 때 채점이 조정가를 쓰는지 고정.
과거 회의 채점은 소급 재계산된다(docs/peer_reviews/2026-10-17_external_audit_fixes.md 한 줄). 가격은 테스트 전용 가상 숫자."""
import inspect
import json

import polars as pl
import pytest

from screener import committee, prices
from tests.test_prices import _bdays

DAYS = [d.isoformat() for d in _bdays(8)]
# SPL: 3일째(인덱스 3) 1:5 분할 — 원본 100 → 20 (실질 수익 0). B·C: 보합.
SPL = [(100, 100), (100, 100), (100, 100), (20, 20), (20, 20), (20, 20), (20, 20), (20, 20)]
FLAT = [(50, 50)] * 8


def _parquet(tmp_path):
    recs = []
    for s, rows in (("000001.KS", SPL), ("000002.KS", FLAT), ("000003.KS", FLAT)):
        for d, (o, c) in zip(_bdays(8), rows):
            recs.append({"yf": s, "date": d, "open": float(o), "high": float(max(o, c)), "low": float(min(o, c)),
                         "close": float(c), "volume": 1000.0})
    p = tmp_path / "kr_prices.parquet"
    pl.DataFrame(recs).write_parquet(p)
    return p


def test_fixture_raw_and_adjusted_differ(tmp_path):
    p = _parquet(tmp_path)
    raw = prices.load_kr(raw=True, path=p).filter(pl.col("yf") == "000001.KS")["close"].to_list()
    adj = prices.load_kr(path=p).filter(pl.col("yf") == "000001.KS")["close"].to_list()
    assert raw[0] == 100 and raw[-1] == 20
    assert adj[0] == pytest.approx(20) and adj[-1] == pytest.approx(20)


def test_committee_score_uses_adjusted(tmp_path, monkeypatch):
    _parquet(tmp_path)
    hist = tmp_path / "committee_hist.json"
    hist.write_text(json.dumps({"rows": [{"date": DAYS[0], "long": ["000001"], "avoid": ["000002"], "probs": {}}]}))
    monkeypatch.setattr(committee, "HIST", hist)
    monkeypatch.setattr(committee, "DATA_DIR", tmp_path)
    monkeypatch.setattr(committee, "_j", lambda name, default=None: default)
    out = committee.score()
    h5 = out["summary"]["h5"]
    # 조정가: 분할 종목 5일 수익 0, 시장 중앙값 0 → 초과 0. 원본이었다면 −80% (분할을 폭락으로 채점).
    assert h5["n"] == 1 and h5["long_avg"] == pytest.approx(0.0, abs=1e-4)
    assert out["recent"][0]["long"] == pytest.approx(0.0, abs=1e-4)


def test_ideas_log_score_reads_adjusted_bars(tmp_path, monkeypatch):
    """조정가 경로 고정: 분할 뒤 원본 20 은 '손절'이 아니다 — 기록이 조정 기준(20)이면 손절 없음."""
    _parquet(tmp_path)
    log_p = tmp_path / "ideas_log.json"
    log_p.write_text(json.dumps({"rows": [{"date": DAYS[0], "ticker": "000001", "entry": 20.0, "stop": 18.0,
                                           "sources": [{"k": "t", "side": "agree"}]}]}))
    monkeypatch.setattr(committee, "IDEAS_LOG", log_p)
    monkeypatch.setattr(committee, "IDEAS_ATTRIB", tmp_path / "ideas_attrib.json")
    monkeypatch.setattr(committee, "DATA_DIR", tmp_path)
    committee._ideas_log_score()
    sc = json.loads(log_p.read_text())["rows"][0]["score"]
    assert sc["stopped"] is False and sc["days"] == 7 and sc["ret5"] == pytest.approx(0.0, abs=1e-6)


@pytest.mark.xfail(strict=True, reason="감사 M4 후속(보드 audit-ideas-basis): ideas_log 의 entry·stop 은 기록 당시 원본가인데 "
                                       "채점 봉은 나중 분할로 소급 조정됨 → 기준 불일치로 가짜 손절. committee.py 잠금(잔여) 해제 뒤 수정")
def test_ideas_log_entry_recorded_in_raw_basis_is_not_false_stop(tmp_path, monkeypatch):
    _parquet(tmp_path)
    log_p = tmp_path / "ideas_log.json"
    log_p.write_text(json.dumps({"rows": [{"date": DAYS[0], "ticker": "000001", "entry": 100.0, "stop": 90.0,
                                           "sources": [{"k": "t", "side": "agree"}]}]}))
    monkeypatch.setattr(committee, "IDEAS_LOG", log_p)
    monkeypatch.setattr(committee, "IDEAS_ATTRIB", tmp_path / "ideas_attrib.json")
    monkeypatch.setattr(committee, "DATA_DIR", tmp_path)
    committee._ideas_log_score()
    assert json.loads(log_p.read_text())["rows"][0]["score"]["stopped"] is False


def test_main_kr_detail_path_uses_load_kr():
    from screener import main
    src = inspect.getsource(main.rebuild_detail_kr)
    assert "load_kr()" in src and "read_parquet" not in src
    for fn in (committee.score, committee._ideas_log_score):
        s = inspect.getsource(fn)
        assert "load_kr(path=p)" in s and "pl.read_parquet(p)" not in s
