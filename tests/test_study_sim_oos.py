"""sim-oos 연구 스크립트의 창 시뮬 복제(_sim_one 과 같은 거래·순수익)와 일간 전략 수익 산식 점검."""
import importlib.util
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import polars as pl

from screener import detail

_spec = importlib.util.spec_from_file_location("study_sim_oos", Path(__file__).resolve().parents[1] / "scripts" / "study_sim_oos.py")
S = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(S)


def _series(n=400, seed=7):
    rng = np.random.default_rng(seed)
    c = 100 * np.cumprod(1 + rng.normal(0.0005, 0.02, n))
    h, l = c * 1.01, c * 0.99
    return c, h, l


def test_window_rets_match_detail_simulate():
    c, h, l = _series()
    sig, s20, s50, ps = S.signals(c, h, l)
    d0 = date(2020, 1, 1)
    for k in ("ma", "psar"):
        tl = S.trades(sig[k])
        exits = [x for _, x in tl]
        t = len(c) - 1
        ws = t - S.WIN + 1
        gross, net = S.window_rets(c, tl, exits, ws, t)
        g = pl.DataFrame({"date": [d0 + timedelta(days=i) for i in range(ws, t + 1)], "close": c[ws:t + 1],
                          "sma20": s20[ws:t + 1], "sma50": s50[ws:t + 1], "psar": ps[ws:t + 1]})
        rr = detail._simulate(g, days=S.WIN)[k]["long"]
        assert rr["trades"] == len(net) and rr["rets"] == net and rr["wins"] == sum(x > 0 for x in gross)


def test_strat_ret_equals_sim_one_equity():
    c, h, l = _series(n=300, seed=3)
    sig, *_ = S.signals(c, h, l)
    r = np.concatenate([[0.0], c[1:] / c[:-1] - 1])
    pos = sig["psar"]
    eq = float(np.prod(1 + S.strat_ret(r, pos)) - 1)
    ref = detail._sim_one(list(c), list(pos), list(range(len(c))))["ret"]
    # _sim_one 은 마지막 날 신호 변경 비용까지 넣는다 → 그 몫(최대 0.125%)만 차이 허용
    assert abs(round(eq, 4) - ref) <= 0.0013
