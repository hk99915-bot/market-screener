"""검증 스터디 (Actions 에서 실행, 결과 reports/studies/*.json).

1. 급락일 다음날: 코스피 2000~ 일봉, 하루 −3% / −5% / −8% 이하 하락일 이후 다음날·5일·20일 수익률
2. 조건부: 급락일이 '이미 20일간 −15% 이상 빠진 상태'에서 나왔을 때 vs 아닐 때 (오늘이 전자)
3. 매매 시뮬레이션: KODEX 레버리지(122630, 2010~)를 급락일 종가에 사서
   (a) 다음날 시가 매도 (b) 다음날 종가 매도 (c) 5일 보유 — 승률·평균·최악·기대값
4. 연속 급락: 5거래일 안에 −5% 이하가 두 번째로 나온 날 이후
"""
from __future__ import annotations

import json
import logging
import statistics as st

from .config import REPORT_DIR

log = logging.getLogger(__name__)


def _dl(t: str, start: str):
    import yfinance as yf
    df = yf.download(t, start=start, interval="1d", auto_adjust=False, progress=False)
    if df is None or not len(df):
        return []
    if hasattr(df.columns, "levels"):
        df.columns = [c[0] for c in df.columns]
    df = df.dropna(subset=["Close"])
    return [{"d": str(i.date()), "o": float(r["Open"]), "h": float(r["High"]), "l": float(r["Low"]), "c": float(r["Close"])}
            for i, r in df.iterrows() if r["Close"] > 0 and r["Open"] > 0]


def _summ(xs: list[float]) -> dict | None:
    xs = [x for x in xs if x is not None]
    if not xs:
        return None
    return {"n": len(xs), "avg": round(st.mean(xs), 4), "med": round(st.median(xs), 4), "up": round(sum(1 for x in xs if x > 0) / len(xs), 3),
            "worst": round(min(xs), 4), "best": round(max(xs), 4)}


def run() -> dict:
    k = _dl("^KS11", "1999-01-01")
    lv = _dl("122630.KS", "2010-01-01")
    out = {"kospi_from": k[0]["d"] if k else None, "lev_from": lv[0]["d"] if lv else None}
    c = [x["c"] for x in k]
    ds = [x["d"] for x in k]
    ret = [None] + [c[i] / c[i - 1] - 1 for i in range(1, len(c))]

    def fwd(i, n):
        return c[i + n] / c[i] - 1 if i + n < len(c) else None

    def dd20(i):
        return c[i] / max(c[max(0, i - 20):i + 1]) - 1

    base = {"all_days": {"d1": _summ([fwd(i, 1) for i in range(1, len(c))]), "d5": _summ([fwd(i, 5) for i in range(1, len(c))]),
                         "d20": _summ([fwd(i, 20) for i in range(1, len(c))])}}
    out["base"] = base
    th = {}
    for t in (-0.03, -0.05, -0.08):
        idx = [i for i in range(1, len(c)) if ret[i] is not None and ret[i] <= t]
        th[f"{int(t*100)}%"] = {"days": len(idx), "d1": _summ([fwd(i, 1) for i in idx]), "d5": _summ([fwd(i, 5) for i in idx]),
                                "d20": _summ([fwd(i, 20) for i in idx]),
                                "dates": [ds[i] for i in idx][-15:]}
    out["drop_days"] = th
    # 조건부: 20일 고점 대비 −15% 이상인 상태에서의 −5% 급락
    idx5 = [i for i in range(21, len(c)) if ret[i] is not None and ret[i] <= -0.05]
    deep = [i for i in idx5 if dd20(i) <= -0.15]
    shallow = [i for i in idx5 if dd20(i) > -0.15]
    out["conditional"] = {
        "deep_(20일 −15% 이상 하락 중)": {"days": len(deep), "d1": _summ([fwd(i, 1) for i in deep]), "d5": _summ([fwd(i, 5) for i in deep]),
                                     "d20": _summ([fwd(i, 20) for i in deep]), "dates": [ds[i] for i in deep][-15:]},
        "shallow_(그 외)": {"days": len(shallow), "d1": _summ([fwd(i, 1) for i in shallow]), "d5": _summ([fwd(i, 5) for i in shallow]),
                          "d20": _summ([fwd(i, 20) for i in shallow])}}
    # 시나리오 확률용: 20일 뒤 분포 버킷 (전체 / −5% 급락일 / 깊은 하락 중 급락일)
    def bucket(idx):
        v = [fwd(i, 20) for i in idx if fwd(i, 20) is not None]
        if not v:
            return None
        n = len(v)
        return {"n": n, "bull": round(sum(1 for x in v if x > 0.05) / n, 3), "base": round(sum(1 for x in v if -0.05 <= x <= 0.05) / n, 3),
                "bear": round(sum(1 for x in v if x < -0.05) / n, 3), "deep_bear": round(sum(1 for x in v if x < -0.15) / n, 3)}
    out["buckets20"] = {"all": bucket(list(range(1, len(c)))), "drop5": bucket(idx5), "deep": bucket(deep),
                        "dd15": bucket([i for i in range(21, len(c)) if dd20(i) <= -0.15])}
    # 연속 급락
    clus = [i for i in idx5 if any(j in idx5 for j in range(i - 5, i))]
    out["cluster_(5일 내 두 번째 −5%)"] = {"days": len(clus), "d1": _summ([fwd(i, 1) for i in clus]), "d20": _summ([fwd(i, 20) for i in clus]),
                                       "dates": [ds[i] for i in clus][-15:]}
    # 레버리지 ETF 매매 시뮬레이션 (거래비용 0.05% 왕복 가정 — ETF 세금 없음)
    if lv:
        lm = {x["d"]: j for j, x in enumerate(lv)}
        cost = 0.0005
        sims = {}
        for t in (-0.03, -0.05):
            a, b, c5 = [], [], []
            for i in range(1, len(c)):
                if ret[i] is None or ret[i] > t or ds[i] not in lm:
                    continue
                j = lm[ds[i]]
                if j + 1 >= len(lv):
                    continue
                buy = lv[j]["c"]
                a.append(lv[j + 1]["o"] / buy - 1 - cost)
                b.append(lv[j + 1]["c"] / buy - 1 - cost)
                if j + 5 < len(lv):
                    c5.append(lv[j + 5]["c"] / buy - 1 - cost)
            sims[f"코스피 {int(t*100)}% 이하 날 종가 매수"] = {"다음날 시가 매도": _summ(a), "다음날 종가 매도": _summ(b), "5일 보유": _summ(c5)}
        out["lev_trade"] = sims
    p = REPORT_DIR / "studies"
    p.mkdir(parents=True, exist_ok=True)
    (p / "crash_rebound.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    log.info("스터디 완료")
    return out
