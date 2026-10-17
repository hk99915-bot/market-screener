"""미국 매집 흔적 스캔(screener/us_accum.py) — 네트워크 없이 합성 OHLCV 로 검사."""
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from screener import us_accum as ua

ROOT = Path(__file__).resolve().parents[1]


def _df(n=120, seed=0, px=50.0, vol=1e6):
    rng = np.random.default_rng(seed)
    c = px * np.cumprod(1 + rng.normal(0, 0.01, n))
    o = np.r_[c[0], c[:-1]] * (1 + rng.normal(0, 0.002, n))
    h = np.maximum(o, c) * 1.005
    l = np.minimum(o, c) * 0.995
    v = vol * (1 + rng.uniform(-0.2, 0.2, n))
    d = pd.date_range("2026-01-02", periods=n, freq="B").strftime("%Y-%m-%d")
    return pd.DataFrame({"date": d, "open": o, "high": h, "low": l, "close": c, "volume": v})


def test_obv_ad_cmf_basic():
    df = pd.DataFrame({"open": [10, 10, 11, 10.5], "high": [10, 11, 11, 11], "low": [10, 10, 10, 10],
                       "close": [10, 11, 10.5, 11], "volume": [100, 200, 300, 400]})
    f = ua.features(df)
    assert f["obv"].tolist() == [0, 200, -100, 300]          # +200, −300, +400
    assert f["clv"].tolist()[:2] == [0.0, 1.0]                # 고=저 → 0, 고가 마감 → +1
    big = ua.features(_df(200))
    cm = big["cmf20"].dropna()
    assert ((cm >= -1) & (cm <= 1)).all()


def test_no_lookahead():
    a = _df(150, seed=1)
    b = a.copy()
    b.loc[120:, ["open", "high", "low", "close"]] *= 1.5     # 미래만 바꿈
    b.loc[120:, "volume"] *= 9
    fa, fb = ua.features(a), ua.features(b)
    cols = ua.SIGNALS + ["cmf20", "obv20", "rvol", "udv50"]
    pd.testing.assert_frame_equal(fa.loc[:119, cols], fb.loc[:119, cols])


def test_acc_day_and_gap_fire():
    df = _df(120, seed=2)
    i = 110
    prev = df.loc[i - 1, "close"]
    df.loc[i, ["open", "low", "high", "close", "volume"]] = [prev * 1.05, prev * 1.04, prev * 1.10, prev * 1.095, 5e6]
    f = ua.features(df)
    assert f.loc[i, "S7"] and f.loc[i, "S8"] and f.loc[i, "S9"]
    assert f.loc[i, "rvol"] > 4


def test_liquidity_filter_blocks_penny():
    df = _df(120, seed=3, px=2.0)                            # 종가 < $5
    f = ua.features(df)
    assert not f[ua.SIGNALS].any().any()
    assert not f["elig"].any()


def test_wilson():
    assert ua.wilson_lo(0, 0) is None
    assert ua.wilson_lo(60, 100) == pytest.approx(0.502, abs=1e-3)


def _write_detail(d: Path, sym: str, df: pd.DataFrame, market="NYSE"):
    ch = [{"t": r.date, "o": r.open, "h": r.high, "l": r.low, "c": r.close, "v": r.volume} for r in df.itertuples()]
    (d / f"{sym}.json").write_text(json.dumps({"name": sym, "market": market, "chart": ch}), encoding="utf-8")


def test_scan_status(tmp_path):
    empty = ua.scan(tmp_path, grades={})
    assert empty["status"] == "fail" and "입력 없음" in empty["reason"]
    df = _df(120, seed=4)
    i = len(df) - 1
    prev = df.loc[i - 1, "close"]
    df.loc[i, ["open", "low", "high", "close", "volume"]] = [prev * 1.05, prev * 1.04, prev * 1.10, prev * 1.095, 5e6]
    _write_detail(tmp_path, "AAA", df)
    _write_detail(tmp_path, "EEE", df, market="ETF")          # ETF 는 제외
    _write_detail(tmp_path, "OLD", df.iloc[:-1])               # 하루 낡은 종목 → hits 제외
    o = ua.scan(tmp_path, grades={"S7": "C"})
    assert o["status"] == "ok" and o["asof"] == df["date"].iloc[-1]
    assert [h["symbol"] for h in o["hits"]] == ["AAA"]
    assert o["n_etf_skipped"] == 1 and o["hits"][0]["score"] == 1     # C=1 가중
    for k in ("asof", "generated_at", "source", "status", "reason", "hits"):
        assert k in o


def test_scan_no_hits_is_fail(tmp_path):
    df = _df(120, seed=5, vol=1e6)
    df["volume"] = 1e6                                        # 거래량 평탄 → 신호 거의 없음
    df["close"] = df["open"] = df["high"] = df["low"] = 50.0  # 가격 고정 → 상승일 없음
    _write_detail(tmp_path, "FLAT", df)
    o = ua.scan(tmp_path, grades={})
    assert o["status"] == "fail" and "신호 0건" in o["reason"]


def test_study_cooldown_and_nw():
    spec = importlib.util.spec_from_file_location("study_us_accum", ROOT / "scripts" / "study_us_accum.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    mask = np.array([1, 1, 0, 1, 0, 0, 1, 1], bool)
    assert np.flatnonzero(m.cooldown(mask, 3)).tolist() == [0, 3, 6]
    x = np.array([0.01, 0.02, 0.0, 0.015, 0.012, 0.018])
    assert m.nw_t(x, 0) == pytest.approx(x.mean() / (x.std() / np.sqrt(len(x))), rel=1e-9)
    assert m.p_one(0.0) == pytest.approx(0.5)


def test_repo_outputs_structure():
    p = ROOT / "reports" / "us_accum.json"
    if not p.exists():
        pytest.skip("스캔 산출물 없음")
    o = json.loads(p.read_text(encoding="utf-8"))
    assert o["status"] in ("ok", "fail")
    assert o["status"] == "fail" or o["hits"]
    s = json.loads((ROOT / "reports" / "studies" / "us_accum.json").read_text(encoding="utf-8"))
    assert s["prereg"]["m"] == len(ua.SIGNALS)
    assert set(s["grades"]) == set(ua.SIGNALS)
