"""추세 탐색 레이어(screener/trend_discovery.py) — 구조·정의 검사 (퀀트 10/24). 정식 규칙(detail FRESH_*·EXP_*) 불변 확인 포함."""
import json
from datetime import date, timedelta

from screener import detail, trend_discovery as T


def _chart(closes, vols=None):
    d0 = date(2024, 1, 1)
    out = []
    for i, c in enumerate(closes):
        out.append({"t": str(d0 + timedelta(days=i)), "o": c, "h": c * 1.01, "l": c * 0.99, "c": c,
                    "v": (vols[i] if vols else 1000)})
    return out


def test_official_thresholds_unchanged():
    assert (detail.FRESH_MIN_TRADES, detail.FRESH_WILSON_MIN, detail.EXP_MIN_TRADES, detail.EXP_LB_MIN) == (6, 0.5, 8, 0.0)
    assert set(detail.FRESH_STRATS) == {"ma", "psar"}


def test_hi52_breakout_and_chase():
    closes = [100.0] * 300 + [101.0 + i for i in range(5)]
    vols = [1000] * 300 + [5000] + [1000] * 4
    cols = {k: [b[x] for b in _chart(closes, vols)] for k, x in (("t", "t"), ("o", "o"), ("h", "h"), ("l", "l"), ("c", "c"), ("v", "v"))}
    sig = T.signals(cols)
    assert sig["hi52"][299] == 0 and sig["hi52"][300] == 1          # 직전 252일 최고 종가 돌파한 날 켜짐
    ch = T.chase_days(cols)
    assert ch[300] and not ch[299]                                   # 거래량 5배 + 20일 최고 종가


def test_splice_ratio_and_fallback():
    chart = _chart([10.0 + i * 0.01 for i in range(60)])
    hist = [(str(date(2023, 6, 1) + timedelta(days=i)), 5, 5, 5, 5.0, 1) for i in range(100)]
    hist += [(b["t"], 0, 0, 0, b["c"] / 2, 1) for b in chart[:30]]  # 겹침 30일, 비율 2.0
    cols, how = T.splice(chart, hist)
    assert how == "spliced" and len(cols["c"]) == 160 and abs(cols["c"][0] - 10.0) < 1e-9
    bad = hist[:100] + [(b["t"], 0, 0, 0, b["c"] / (2 if i % 2 else 3), 1) for i, b in enumerate(chart[:30])]
    assert T.splice(chart, bad)[1].startswith("chart_only")


def test_null_band_probabilities_sane():
    p = T._wilson_band_null(10, 0.45, 0.5)
    assert 0 <= p < 0.2
    assert T._exp_band_null(10, 0.05, -0.005) > 0
    assert abs(T.binom_tail(0, 10, 0.3) - 1) < 1e-12 and T.binom_tail(11, 10, 0.3) == 0


def test_build_labels_and_blocks(tmp_path):
    dd = tmp_path / "detail"
    dd.mkdir()
    closes = [100 + (i % 40) * 0.5 + i * 0.05 for i in range(260)]
    for s in ("AAA", "BBB"):
        (dd / f"{s}.json").write_text(json.dumps({"name": s, "chart": _chart(closes), "sim": {}}), encoding="utf-8")
    (dd / "_index.json").write_text(json.dumps({"asof": "2024-09-16"}), encoding="utf-8")
    out = T.build("US", write=False, detail_dir=dd, hist_dir=tmp_path / "nohist")
    assert out["not_for_orders"] is True and out["grade"].startswith("탐색")
    assert "주문표 근거 불가" in out["use"]
    for k in ("diagnosis", "near_miss", "explore", "sectors", "multiple_testing"):
        assert k in out
    ex = out["explore"]
    assert set(ex["by_strategy"]) == set(T.EXPLORE_STRATS)
    assert ex["chase"]["exclude_from_candidates"] is False and T.CHASE["KR"]["exclude"] is True
    assert out["multiple_testing"]["m_total"] >= 0 and "expected_chance_total" in out["multiple_testing"]
