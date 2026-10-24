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


def test_event_study_states_match_daily_layer():
    """사전등록 2026-10-24_trend_events 의 진입 정의 = 일일 레이어(trend_discovery.signals) 0→1 전환."""
    import random
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import numpy as np
    import study_trend_events as E
    rng = random.Random(7)
    c, v = [100.0], []
    for i in range(700):
        c.append(c[-1] * (1 + rng.gauss(0.0006, 0.02)))
    v = [1000 + rng.random() * 2000 for _ in c]
    h = [x * 1.01 for x in c]
    cols = {"t": [str(i) for i in range(len(c))], "o": c, "h": h, "l": [x * 0.99 for x in c], "c": c, "v": v}
    sig = T.signals(cols)
    ev = E.states(np.array(c), np.array(h), np.array(v))
    for k in ("hi52", "gcv", "sqz"):
        s = sig[k]
        on = [i for i in range(1, len(s)) if s[i] == 1 and s[i - 1] == 0]
        assert on == list(np.flatnonzero(ev[k])), k


def test_b1_ref_rule():
    def ch(n, last):
        out = _chart([100.0] * (n - 1) + [last], [2_000_000] * n)
        return out
    stocks = {"111111": {"name": "A", "chart": ch(260, 99.0)}, "222222": {"name": "B", "chart": ch(260, 80.0)}}
    b = T.b1_ref(stocks)
    syms = {r["s"] for r in b["rows"]}
    # kr_sector.csv 에 없는 가짜 코드는 업종 필터로 빠질 수 있어 '미해당 종목이 안 들어감'만 검사
    assert "222222" not in syms
    assert "주문 근거 아님" in b["label"]


def test_committee_trend_off_and_b1(tmp_path, monkeypatch):
    from screener import committee as C
    (tmp_path / "detail" / "US").mkdir(parents=True)
    (tmp_path / "detail" / "US" / "AAA.json").write_text(json.dumps({"sim": {"ma": {"long": {"pos": 0}}}}), encoding="utf-8")
    (tmp_path / "detail" / "US" / "BBB.json").write_text(json.dumps({"sim": {"ma": {"long": {"pos": 1}}}}), encoding="utf-8")
    monkeypatch.setattr(C, "REPORT_DIR", tmp_path)
    assert C._trend_off("AAA") is True and C._trend_off("BBB") is False and C._trend_off("ZZZ") is None
    assert C._b1_ref("US") is None
    (tmp_path / "trend_discovery_KR.json").write_text(json.dumps({"asof": str(C._kst_today()), "b1_ref": {"label": "B · 참고(주문 근거 아님)", "rows": []}}), encoding="utf-8")
    assert C._b1_ref("KR")["label"].startswith("B")


def test_adopt_judge_rules(tmp_path):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import trend_adopt_judge as J
    (tmp_path / "reports" / "signal_tracking").mkdir(parents=True)
    (tmp_path / "ops").mkdir()
    evs = [{"src": "disc_kr", "tag": "adopt:hi52", "fwd": {"h20": {"ex": 0.01}}} for _ in range(30)]
    evs += [{"src": "disc_kr", "tag": "adopt:gcv", "fwd": {"h20": {"ex": -0.01}}} for _ in range(30)]
    evs += [{"src": "disc_kr", "tag": "adopt:sqz", "fwd": {"h20": {"ex": 0.05}}} for _ in range(29)]
    evs += [{"src": "disc_kr", "tag": "new:sqz", "fwd": {"h20": {"ex": 0.05}}}]   # 필터 전 — 판정 대상 아님
    (tmp_path / "reports" / "signal_tracking" / "2026-11.json").write_text(json.dumps(evs), encoding="utf-8")
    early = J.judge("2026-11-19", tmp_path)
    assert not early["due"] and early["strategies"]["hi52"]["status"] == "전진 추적 중"
    r = J.judge("2026-11-20", tmp_path)
    assert [r["strategies"][k]["status"] for k in ("hi52", "gcv", "sqz")] == ["정식 후보", "폐기 후보", "보류"]
    assert r["auto_promote"] is False and r["ref_new_all"]["sqz"]["n"] == 1
    (tmp_path / "ops" / "board.json").write_text(json.dumps({"tasks": []}), encoding="utf-8")
    assert J.board_add(r, tmp_path) is True and J.board_add(r, tmp_path) is False   # 같은 달 1회
    b = json.loads((tmp_path / "ops" / "board.json").read_text(encoding="utf-8"))
    assert b["tasks"][0]["approval"] == "겸이" and b["tasks"][0]["id"] == "appr-trend-adopt-judge-2026-11"
    assert J.board_add(J.judge("2026-11-25", tmp_path), tmp_path) is False


def test_adopt_pending_excludes_chase_and_us():
    rows = [{"s": "X", "strategy": "hi52", "age": 0, "chase": True}, {"s": "Y", "strategy": "ma3", "age": 0}]
    a = T.adopt_pending(rows)
    assert a["n"] == 0 and a["conv"] == "low" and "주문 근거 아님" in a["tag"] and "분산" in a["basket"]
    from screener import committee as C
    assert C._adopt_pending("US") is None
