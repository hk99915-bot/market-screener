"""screener.accum — 네트워크 없이 합성 저장소로 지표·신호·상태 필드 검사."""
from __future__ import annotations

import json
from datetime import date

import numpy as np
import pandas as pd
import pytest

from screener import accum


def _synth(n_days=90, codes=("000001", "000002", "000003", "000004"), seed=0):
    rng = np.random.default_rng(seed)
    ds = pd.bdate_range("2026-05-01", periods=n_days)
    rows = []
    for j, c in enumerate(codes):
        px = 10000.0
        for k, d in enumerate(ds):
            px *= 1 + rng.normal(0, 0.01)
            f = 500 if (c == "000001" and k >= n_days - 7) else int(rng.normal(0, 50))   # 000001: 최근 7일 외국인 연속 매수
            i = 300 if (c == "000001" and k >= n_days - 4) else int(rng.normal(0, 50))
            if c == "000001" and k == n_days - 8:
                f = -100
            if c == "000001" and k == n_days - 5:
                i = -100
            rows.append({"date": d.date(), "code": c, "mkt": "K", "close": round(px), "mcap": 5000, "tv": 2000,
                         "f": f, "i": i, "pen": 10 if c == "000002" else 0, "trust": 0})
    return accum._typed(pd.DataFrame(rows))


def test_store_roundtrip(tmp_path):
    df = _synth(30)
    n = accum.save_days([df], root=tmp_path)
    assert n == len(df)
    # 같은 날짜 재저장은 교체(중복 없음)
    accum.save_days([df[df["date"] == df["date"].max()]], root=tmp_path)
    back = accum.load_store(root=tmp_path)
    assert len(back) == len(df)
    assert back["code"].str.len().eq(6).all()
    assert str(back["f"].dtype) == "int32"
    assert accum.stored_dates(tmp_path) == {str(d) for d in df["date"].unique()}


def test_split_adjusted_returns():
    df = pd.DataFrame({"date": pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06"]), "code": "000001", "mkt": "K",
                       "close": [10000, 2000, 2100], "mcap": [1000, 1000, 1050], "tv": 1, "f": 0, "i": 0, "pen": 0, "trust": 0})
    r = accum.add_returns(df)["r"].round(4).tolist()
    assert r == [0.0, 0.0, 0.05]     # 1:5 분할일은 시총 비율(0%), 다음날 +5%


def test_streak_and_windows():
    df = accum.features(accum.add_returns(_synth()))
    last = df[df["date"] == df["date"].max()].set_index("code")
    assert last.loc["000001", "st_f"] == 7
    assert last.loc["000001", "st_i"] == 4
    assert last.loc["000001", "st_fi"] == 4
    assert last.loc["000001", "f5"] == 2500                       # 백만원
    # 매집 강도 % = 순매수(백만원) / (시총 억원×100) × 100
    assert last.loc["000001", "fi5_cap"] == pytest.approx((2500 + 1200 + last.loc["000001", "i5"] - 1200) / 5000, rel=1e-6)


def test_eligibility_excludes_etf_spac():
    df = accum.features(accum.add_returns(_synth()))
    names = {"000001": "좋은회사", "000002": "KODEX 200", "000003": "미래에셋스팩5호", "000004": "삼성 ETN 레버리지"}
    el = accum.eligible(df, names)
    got = set(df.loc[el, "code"])
    assert got == {"000001"}


def test_scan_status_and_fields():
    names = {"000001": "가", "000002": "나", "000003": "다", "000004": "라"}
    df = _synth()
    out = accum.scan(pd.DataFrame(df).assign(date=lambda x: pd.to_datetime(x["date"])), names,
                     today=pd.Timestamp(df["date"].max()).date())
    for k in ("asof", "generated_at", "source", "status"):
        assert out.get(k), k
    assert out["status"] in ("ok", "partial")
    assert out["top"]["accum"][0]["code"] == "000001"
    assert "fstreak" in out["top"]["accum"][0]["tags"]
    assert set(out["market"]) == {"KOSPI"}
    json.dumps(out)    # 직렬화 가능


def test_empty_is_fail():
    out = accum.scan(pd.DataFrame(columns=accum.COLS), {})
    assert out["status"] == "fail" and out["n"] == 0 and out["reason"]


def test_stale_flag():
    df = _synth()
    out = accum.scan(df.assign(date=pd.to_datetime(df["date"])), {}, today=date(2027, 1, 1))
    assert out["status"] == "stale"


def test_repo_output_contract():
    """저장소의 reports/accum.json 이 있으면 계약(필드·빈 결과=fail)을 지킨다."""
    p = accum.OUT
    if not p.exists():
        pytest.skip("reports/accum.json 아직 없음")
    o = json.loads(p.read_text(encoding="utf-8"))
    for k in ("asof", "generated_at", "source", "status"):
        assert k in o
    if not o.get("n"):
        assert o["status"] == "fail"
