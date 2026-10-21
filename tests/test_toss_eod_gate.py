"""토스 EOD 보충 실데이터 검증 게이트 (보드 us-eod-toss, 10/21 오너 "토스 보충이 실데이터로 검증 안 됐으면 검증을 하고 넣어").

토스 값 = toss-live 브랜치 daily_today.json(2026-10-21T10:10 KST 게시)의 **실** 1d 봉 — 같은 엔드포인트(/api/v1/candles 1d)·같은 파서
(collect._daily_rows)가 만든 값이다. 응답 키 꼴(result.candles[{timestamp, openPrice, …}])은 10/21 노트북 --shape 실측,
timestamp 원문 형식만 미확인(daily_today 날짜는 이미 ET 날짜로 바뀐 결과) → 여기선 ET 16:00 로 둔다.
야후 값 = 이 컨테이너에서 야후 접속 차단이라 **픽스처**(토스 값과 같다고 둔 가정값 + 일부러 어긋낸 값). 네트워크 없음.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl

from screener import data, guard
from screener import main as smain
from screener.config import TOSS_EOD_CLOSE_TOL, TOSS_EOD_MIN_MATCH, TOSS_EOD_MIN_OVERLAP
from tools.toss_md import collect, publish

KST = ZoneInfo("Asia/Seoul")
NOW = datetime(2026, 10, 21, 6, 52, tzinfo=KST)   # screen_us 슬롯 — 기대 거래일 10/20
WANT = date(2026, 10, 20)

# toss-live daily_today.json 실값 (10/20 정규장 봉 · 10/21 = 21:10 ET 시점 다음 ET 날짜 야간거래 봉)
REAL = {
    "DIA": [["2026-10-20", 519.07, 526.17, 518.46, 524.36, 4731796], ["2026-10-21", 524.24, 524.46, 524.0, 524.04, 432]],
    "IWM": [["2026-10-20", 271.53, 276.9, 271.29, 275.78, 33079265], ["2026-10-21", 275.95, 276.28, 275.52, 275.64, 31012]],
    "QQQ": [["2026-10-20", 715.25, 722.75, 710.39, 717.63, 36246381], ["2026-10-21", 722.91, 725.42, 721.5, 722.03, 144713]],
    "SOXX": [["2026-10-20", 494.99, 508.89, 489.7, 500.01, 11675312], ["2026-10-21", 512.18, 516.21, 510.74, 512.3, 21206]],
    "SPY": [["2026-10-20", 765.86, 772.29, 764.25, 769.05, 44771486], ["2026-10-21", 770.8, 771.82, 770.22, 770.42, 21037]],
}


def _resp(rows):
    """daily_today 봉 → /api/v1/candles 1d 응답 꼴(키 = 실측 --shape)."""
    return {"result": {"candles": [{"timestamp": f"{d}T16:00:00-04:00", "openPrice": o, "highPrice": h, "lowPrice": lo,
                                    "closePrice": c, "volume": v} for d, o, h, lo, c, v in rows]}, "nextBefore": None}


def test_real_bars_roundtrip_parser_and_publish():
    """실값이 collect 파서(eod_bar·eod_prev_bar) → us_eod.json(publish) 꼴로 그대로 통과하는지 — daily_today 와 같은 값."""
    for k, rows in REAL.items():
        r = _resp(rows)
        assert collect.eod_bar(r, "2026-10-20") == [float(x) for x in rows[0][1:]]
        assert collect.eod_prev_bar(r, "2026-10-21") == ["2026-10-20", *[float(x) for x in rows[0][1:]]]
        # 늦은 회차(야간 봉이 붙은 응답)에서도 10/20 이 당일 봉, 전날 봉은 count=3 이라 남는다
        assert collect.eod_prev_bar(_resp([["2026-10-19", 1, 1, 1, 1, 1], *rows]), "2026-10-20")[0] == "2026-10-19"
        # daily_today(publish._bar)와 us_eod prev 의 [날짜,o,h,l,c,v] 순서가 같다
        assert publish._bar(k, "US", "2026-10-20", rows[0][1:]) == rows[0]
    assert collect.US_EOD_COUNT == 3


def test_collect_publish_prev_real_values(tmp_path):
    class C:
        def get(self, path, params):
            return _resp([["2026-10-17", 1, 1, 1, 1, 1], *REAL[params["symbol"]]])   # 10/21 ET 장 마감 후 응답 흉내
    now = datetime(2026, 10, 22, 5, 30, tzinfo=KST)   # = 10/21 16:30 ET
    ok, fail, _ = collect.collect_us_eod(C(), tmp_path, now, dry_run=True, symbols=list(REAL))
    assert (ok, fail) == (5, 0)
    pub = publish.build_us_eod(tmp_path, now)
    publish.assert_public(pub)
    assert pub["date"] == "2026-10-21" and pub["prev"]["DIA"] == ["2026-10-20", 519.07, 526.17, 518.46, 524.36, 4731796]


def _yahoo(n_extra=0, close_bump=None, skip=()):
    """야후 픽스처: REAL 5종 + 합성 n_extra 종목, 10/19·10/20 봉(10/21 은 없음 = 야후 지연). close_bump={sym: 배율}."""
    close_bump = close_bump or {}
    rows = []
    for k, r in REAL.items():
        _, o, h, lo, c, v = r[0]
        rows += [(k, date(2026, 10, 19), o, h, lo, c, v), (k, WANT, o, h, lo, c * close_bump.get(k, 1.0), v)]
    for i in range(n_extra):
        s = f"X{i:03d}"
        rows += [(s, date(2026, 10, 19), 10, 10, 10, 10, 100), (s, WANT, 10, 10, 10, 10 * close_bump.get(s, 1.0), 100)]
    rows = [r for r in rows if r[0] not in skip]
    return pl.DataFrame(rows, schema=["yf", "date", "open", "high", "low", "close", "volume"], orient="row").with_columns(
        pl.col("date").cast(pl.Date), *[pl.col(c).cast(pl.Float64) for c in ("open", "high", "low", "close", "volume")])


def _eod(n_extra=0, drop=()):
    """us_eod.json 꼴: date=10/21, bars=10/21 봉, prev=10/20 봉(토스 실값)."""
    bars = {k: r[1][1:] for k, r in REAL.items()}
    prev = {k: r[0] for k, r in REAL.items()}
    for i in range(n_extra):
        s = f"X{i:03d}"
        bars[s], prev[s] = [10, 10, 10, 10.1, 50], ["2026-10-20", 10, 10, 10, 10, 100]
    return {"date": "2026-10-21", "bars": bars, "prev": {k: v for k, v in prev.items() if k not in drop}}


NOW2 = datetime(2026, 10, 22, 6, 52, tzinfo=KST)   # 기대 거래일 10/21


def test_rule_constants_documented():
    assert (TOSS_EOD_CLOSE_TOL, TOSS_EOD_MIN_OVERLAP, TOSS_EOD_MIN_MATCH) == (0.001, 0.90, 0.98)


def test_gate_pass_real_values_and_report(tmp_path, monkeypatch):
    monkeypatch.setattr(guard, "_report_dir", lambda: tmp_path)
    px, info = smain.us_toss_fill(_yahoo(n_extra=95), date(2026, 10, 20), NOW2, load=lambda: _eod(n_extra=95))
    assert info["applied"] and info["filled"] == 100 and info["check"]["match_pct"] == 100.0
    assert info["label"].endswith("(토스 검증 일치 100%)")
    assert px.filter((pl.col("yf") == "DIA") & (pl.col("date") == date(2026, 10, 21)))["close"][0] == 524.04
    rep = json.loads((tmp_path / "toss_eod_check.json").read_text(encoding="utf-8"))["last"]
    assert rep["n_overlap"] == 100 and rep["prev_date"] == "2026-10-20" and rep["max_dev_pct"] == 0.0 and rep["pass"]
    assert "ok_syms" not in rep and len(json.dumps(rep)) < 1500   # 작게 — 원값 대량 저장 X


def test_gate_fail_keeps_stale_and_labels(tmp_path, monkeypatch):
    monkeypatch.setattr(guard, "_report_dir", lambda: tmp_path)
    bump = {f"X{i:03d}": 1.01 for i in range(5)}   # 100종목 중 5개 1% 괴리 → 일치 95% < 98%
    px0 = _yahoo(n_extra=95, close_bump=bump)
    px, info = smain.us_toss_fill(px0, date(2026, 10, 20), NOW2, load=lambda: _eod(n_extra=95))
    assert px.equals(px0) and info["applied"] is False
    assert info["label"] == "src: 야후 · 토스 검증 불통과(일치 95%·겹침 100%)"
    rep = json.loads((tmp_path / "toss_eod_check.json").read_text(encoding="utf-8"))["last"]
    assert not rep["pass"] and rep["n_failed"] == 5 and abs(rep["max_dev_pct"] - 0.9901) < 1e-3   # 10/10.1 −1
    assert not (tmp_path / "freshness.json").exists() or "filled" not in json.loads((tmp_path / "freshness.json").read_text())


def test_gate_pass_excludes_mismatch_individually(tmp_path, monkeypatch):
    monkeypatch.setattr(guard, "_report_dir", lambda: tmp_path)
    px, info = smain.us_toss_fill(_yahoo(n_extra=95, close_bump={"SPY": 1.002}), date(2026, 10, 20), NOW2,
                                  load=lambda: _eod(n_extra=95))   # SPY 0.2% 괴리(예: 배당락 수정) — 99% 일치로 통과
    assert info["applied"] and info["filled"] == 99 and info["check"]["n_failed"] == 1
    assert px.filter((pl.col("yf") == "SPY") & (pl.col("date") == date(2026, 10, 21))).is_empty()   # SPY 만 개별 제외
    rep = json.loads((tmp_path / "toss_eod_check.json").read_text(encoding="utf-8"))["last"]
    assert rep["failed"][0][0] == "SPY" and rep["max_dev_sym"] == "SPY"


def test_gate_fail_low_overlap(tmp_path, monkeypatch):
    monkeypatch.setattr(guard, "_report_dir", lambda: tmp_path)
    drop = [f"X{i:03d}" for i in range(15)]   # 토스 prev 15개 빠짐 → 겹침 85% < 90%
    px0 = _yahoo(n_extra=95)
    px, info = smain.us_toss_fill(px0, date(2026, 10, 20), NOW2, load=lambda: _eod(n_extra=95, drop=drop))
    assert px.equals(px0) and info["applied"] is False and "겹침 85%" in info["label"]
    # 옛 us_eod.json(prev 없음) 도 겹침 0% 로 불통과 → 보충 안 함(검증 없이 넣지 않음)
    old = {k: v for k, v in _eod().items() if k != "prev"}
    _, info = smain.us_toss_fill(_yahoo(), date(2026, 10, 20), NOW2, load=lambda: old)
    assert info["applied"] is False and info["check"]["overlap_pct"] == 0.0


def test_symbol_form_consistent_collect_to_data():
    """collect 키 = 유니버스 yf 꼴(BRK-B) 그대로, 토스 요청만 점 꼴(BRK.B) → data 쪽 px["yf"] 와 같은 키로 맞물림."""
    syms = collect.us_eod_symbols(Path(__file__).resolve().parent.parent)
    assert syms and not any("." in s for s in syms)
    assert "BRK-B" in syms and "BF-B" in syms

    class C:
        def __init__(self):
            self.asked = []

        def get(self, path, params):
            self.asked.append(params["symbol"])
            return _resp([["2026-10-19", 1, 1, 1, 1, 1], *REAL["DIA"]])   # count=3 + 야간 봉
    c = C()
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        collect.collect_us_eod(c, Path(d), datetime(2026, 10, 21, 6, 20, tzinfo=KST), dry_run=True, symbols=["BRK-B", "BF-B", "AAPL"])
        rec = json.loads((Path(d) / "us_eod" / "2026-10-20.json").read_text(encoding="utf-8"))
    assert c.asked == ["BRK.B", "BF.B", "AAPL"]
    assert set(rec["bars"]) == set(rec["prev"]) == {"BRK-B", "BF-B", "AAPL"}
    px = pl.DataFrame({"yf": ["BRK-B", "BF-B", "AAPL"], "date": [date(2026, 10, 19)] * 3, "open": 1.0, "high": 1.0,
                       "low": 1.0, "close": 1.0, "volume": 1.0}).with_columns(pl.col("date").cast(pl.Date))
    eod = {"date": "2026-10-20", "bars": rec["bars"]}
    out, info = data.fill_last_day(px, WANT, eod)
    assert info["filled"] == 3   # 키가 그대로 맞물림(변환 없음)
