"""검증 데스크 — scripts/replicate_crash_rebound.py 의 simulate/compare 를 손으로 계산 가능한 합성 시세로 검사."""
import sys
from datetime import date, timedelta
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from replicate_crash_rebound import EXITS, compare, simulate  # noqa: E402


def _frame(symbol, closes, opens=None):
    n = len(closes)
    dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(n)]
    opens = opens or closes
    return pl.DataFrame({"date": dates, "symbol": symbol, "open": opens, "high": closes, "low": closes,
                         "close": closes, "adj_close": closes, "volume": [1.0] * n, "src": "t"})


def test_simulate_hand_calc():
    # 코스피: 3일째 −6%(사건), 나머지 보합. 레버리지: 사건일 종가 100 → 다음 시가 103, 종가 104, 5거래일 뒤 종가 110.
    kospi = _frame("KOSPI", [100.0, 100.0, 94.0, 94.0, 94.0, 94.0, 94.0, 94.0, 94.0, 94.0])
    lev = _frame("122630", [100.0, 100.0, 100.0, 104.0, 105.0, 106.0, 107.0, 110.0, 111.0, 112.0],
                 opens=[100.0, 100.0, 100.0, 103.0, 105.0, 106.0, 107.0, 110.0, 111.0, 112.0])
    out = simulate(kospi, lev, cost=0.0)
    r5 = out["코스피 -5% 이하 날 종가 매수"]
    assert r5["days"] == 1 and r5["dates"] == ["2024-01-03"]
    assert r5[EXITS[0]]["avg"] == 0.03 and r5[EXITS[1]]["avg"] == 0.04 and r5[EXITS[2]]["avg"] == 0.10
    assert r5[EXITS[2]]["up"] == 1.0
    # −3% 조건은 −5% 사건을 포함한다
    assert out["코스피 -3% 이하 날 종가 매수"]["days"] == 1
    # 왕복 비용은 수익률에서 그대로 차감
    assert simulate(kospi, lev, cost=0.01)["코스피 -5% 이하 날 종가 매수"][EXITS[0]]["avg"] == 0.02


def test_simulate_skips_days_without_lev_and_tail():
    kospi = _frame("KOSPI", [100.0, 94.0, 94.0, 88.0])          # 2일째·4일째 급락
    lev = _frame("122630", [100.0, 100.0, 100.0]).filter(pl.col("date") >= date(2024, 1, 2))  # 2일째부터만 존재, 4일째 없음
    r = simulate(kospi, lev, cost=0.0)["코스피 -5% 이하 날 종가 매수"]
    assert r["days"] == 1                      # 4일째는 레버리지 시세 없음 → 제외
    assert r[EXITS[0]]["n"] == 1 and r[EXITS[2]] is None   # 5일 뒤 가격 없음 → 5일 보유 표본 없음


def test_compare_verdict():
    rep = {"c": {EXITS[0]: {"n": 26, "up": 0.615, "avg": 0.072}, EXITS[1]: {"n": 26, "up": 0.615, "avg": 0.072}, EXITS[2]: None}}
    orig = {"c": {EXITS[0]: {"n": 25, "up": 0.60, "avg": 0.068}, EXITS[1]: {"n": 20, "up": 0.60, "avg": 0.068}, EXITS[2]: {"n": 1}}}
    v = {r["exit"]: r["verdict"] for r in compare(orig, rep)}
    assert v == {EXITS[0]: "일치", EXITS[1]: "불일치", EXITS[2]: "재현 없음"}
