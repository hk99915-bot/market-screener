"""미국 소형주 급등 사건연구 — 원가격 복원·숏 손절·사건 선택·전체 파이프라인(합성 데이터, 네트워크 없음)."""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import fetch_us_spikes as F  # noqa: E402
import study_us_spikes as S  # noqa: E402


def test_split_factor_reverse_split():
    sp = pd.Series([0, 0, 0.02, 0, 0.5, 0])  # 1:50 역분할 후 2:1 분할
    f = F.split_factor(sp).tolist()
    assert np.allclose(f, [0.01, 0.01, 0.5, 0.5, 1.0, 1.0])


def _ticker(seed: int, n: int = 200, spikes=(100,), post=-0.05, rev_split_at=None):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2015-01-01", periods=n)
    c = 5 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    v = np.full(n, 1e5)
    for p in spikes:
        c[p:] *= 1.6
        c[p + 1:] *= 1 + post
        v[p] = 1e6
    o = c.copy()
    o[1:] = c[:-1] * 1.0
    sp = np.zeros(n)
    if rev_split_at is not None:
        sp[rev_split_at] = 0.1
        c[:rev_split_at] *= 10  # 조정가 = 원가격 / 0.1
        o[:rev_split_at] *= 10
    return pd.DataFrame({"Open": o, "High": np.maximum(o, c) * 1.01, "Low": np.minimum(o, c) * 0.99,
                         "Close": c, "Volume": v, "Stock Splits": sp}, index=idx)


def test_short_ret_stop_and_gap():
    W = pd.DataFrame({"o1": [10.0, 10.0, 10.0], "c5": [8.0, 8.0, 20.0]})
    for k in range(1, 6):
        W[f"o{k}"] = [10.0, 10.0, 10.0] if k == 1 else [9.0, 9.0, 15.0 if k == 2 else 20.0]
        W[f"h{k}"] = [10.5, 13.5 if k == 3 else 10.5, 10.5 if k == 1 else 21.0]
        W[f"c{k}"] = [8.0, 8.0, 20.0]
    r = S.short_ret(W, 5, 0.30, 0.0)
    assert abs(r[0] - (0.2 - S.COST)) < 1e-9          # 손절 안 걸림
    assert abs(r[1] - (-0.3 - S.COST)) < 1e-9         # D+3 고가 13.5 ≥ 13 → 13 에 환매
    assert abs(r[2] - (-0.5 - S.COST)) < 1e-9         # D+2 시가 15 갭 → 15 에 환매(손절가보다 나쁨)
    r0 = S.short_ret(W, 5, None, 0.5)
    assert abs(r0[2] - (-1.0 - S.COST - 0.5 * 5 / 252)) < 1e-9


def test_pipeline_synthetic(tmp_path):
    elig = Counter()
    ev, metas = [], []
    frames = {"AAA": _ticker(1), "BBB": _ticker(2, spikes=(100, 110)), "CCC": _ticker(3, rev_split_at=150),
              "DDD": _ticker(4, spikes=(30,))}
    for s, d in frames.items():
        o, m = F.process(s, d, elig)
        ev += o
        metas.append({**m, "name": f"{s} Inc. Common Stock", "market": "NASDAQ"})
    E = pd.concat(ev, ignore_index=True)
    E.to_parquet(tmp_path / "events.parquet", index=False)
    pd.DataFrame(metas).to_csv(tmp_path / "meta.csv", index=False)
    pd.DataFrame(sorted(elig.items()), columns=["year", "elig_days"]).to_csv(tmp_path / "elig_days.csv", index=False)
    res = S.run(tmp_path)
    json.dumps(res, default=str)
    f = res["funnel"]
    # BBB 두 번째 급등은 쿨다운, DDD 는 이력 60일 미달 → AAA·BBB 첫째·CCC(원가격 ~$8, 조정가 ~$80) 3건
    assert f["+이력60일·시총<$2B/미상·쿨다운20"] == 3
    assert res["data"]["same_filter_on_adjusted_price_n"] < f["+가격 $1~20(원가격)"]
    assert [h["id"] for h in res["hypotheses"]] == ["H1", "H2", "H3", "H4", "H5", "H6"]
    assert res["m"] == 6 and res["hypotheses"][0]["grade"] == "검증전"
    t = res["tiers"]["T30"]
    assert t["n"] == 3 and abs(t["S5_gross"]["mean"] - 0.0) < 0.2
