import importlib.util
from pathlib import Path

import pandas as pd

spec = importlib.util.spec_from_file_location("rsr", Path(__file__).resolve().parents[1] / "scripts" / "replicate_sox_rel.py")
rsr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rsr)


def _px():
    idx = pd.bdate_range("2026-10-01", periods=10)
    sox = [100, 100, 100, 100, 90, 90, 90, 90, 88, 88]
    spx = [100, 100, 100, 100, 99, 99, 99, 99, 98, 98]
    return pd.DataFrame({rsr.SOX: sox, rsr.SPX: spx}, index=idx)


def test_window_diff_ratio_and_count():
    px = _px()
    w = rsr.window(px, "2026-10-01", "2026-10-14")
    assert w["n_ret"] == 9
    assert w["sox"] == -0.12 and w["mkt"] == -0.02
    assert w["diff"] == -0.10
    assert w["ratio"] == round(0.88 / 0.98 - 1, 4)


def test_rank_and_episodes():
    s = pd.Series([-0.01, -0.2, -0.19, 0.0, -0.05], index=pd.bdate_range("2026-01-01", periods=5))
    r = rsr.rank(s, -0.05)
    assert r["worse"] == 2 and r["n_windows"] == 5
    ep = rsr.episodes(s, -0.05, 1)
    assert ep[0] == ("2026-01-02", -0.2)
