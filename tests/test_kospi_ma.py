"""코스피 20일선 단일 계산 (req-quant-d3a3735d): committee·views 가 같은 값, 기준일이 하루 굴러가면 값이 달라지는 것은 정상."""
import json
import statistics as st

from screener import committee, kospi_ma, views


def test_sma_tail_rolls_one_day():
    c = [float(x) for x in range(100, 140)]
    assert kospi_ma.sma_tail(c) == st.mean(c[-20:])
    assert kospi_ma.sma_tail(c[:-1]) != kospi_ma.sma_tail(c)      # 기준일 하루 차이 = 다른 값(불일치 아님)


def test_streak_matches_committee_wrapper():
    c = [100.0] * 25 + [101.0, 102.0, 90.0, 95.0, 96.0]
    assert committee._above_sma_streak(c) == kospi_ma.sma_streak(c)


def test_committee_and_views_same_sma20(tmp_path, monkeypatch):
    rows = [[f"2026-09-{d:02d}", 1, 2, 1, 100 + d, 0] for d in range(1, 31)]
    mac = {"series": {"KOSPI": rows}}
    monkeypatch.setattr(committee, "_j", lambda n, d=None: mac if n == "macro_series.json" else d)
    monkeypatch.setattr(views, "_j", lambda n, d=None: mac if n == "macro_series.json" else d)
    monkeypatch.setitem(__import__("sys").modules, "pykrx", None)      # KRX 덮어쓰기 실패 경로
    kc = committee._kospi_state()
    kv = views._kospi({})
    assert round(kc["sma20"], 6) == round(kv["sma20"], 6) == round(st.mean(r[4] for r in rows[-20:]), 6)
