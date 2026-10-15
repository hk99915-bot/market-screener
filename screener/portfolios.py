"""모의 포트폴리오: 한·미 ETF·지수를 섞은 전략 백테스트(원화 기준) + 현재 목표 비중 → reports/portfolios.json

전략 (모두 월말 리밸런싱, 교체분 편도 0.1% 비용, 원화 환산 = 달러 자산 × USDKRW)
1. 글로벌 60/40        S&P500 30 · 나스닥100 15 · KOSPI200 15 · 미 중기국채 40
2. 리스크 패리티        6개 자산을 60일 변동성의 역수로 가중
3. 듀얼 모멘텀          미국·선진국·한국 중 12개월 수익률 1위, 그게 단기채보다 못하면 중기국채
4. 추세추종(GTAA)      6개 자산 각각 10개월 평균 위면 1/6 보유, 아래면 그 몫은 단기채
5. 한·미 로테이션       KOSPI200 vs S&P500 중 6개월 수익률이 높은 쪽 100%
6. 섹터 모멘텀 롱숏     미국 11개 섹터 ETF 중 12-1개월 상위 3 롱 / 하위 3 숏 (시장중립, 증거금은 단기채)
7. 롱 스트래들          매월 S&P500 1개월 ATM 스트래들에 자산 2% 지불, 나머지 단기채 (블랙숄즈, IV=VIX)
8. 숏 스트래들          같은 스트래들을 매도(프리미엄 2% 수취 규모), 손실 한도 없음 — 꼬리 위험 확인용

스트래들은 실제 옵션 호가가 아니라 VIX 를 내재변동성으로 쓴 블랙숄즈 모형가다(스큐·스프레드 미반영).
"""
from __future__ import annotations

import json
import logging
import math
from datetime import datetime
from zoneinfo import ZoneInfo

from .config import REPORT_DIR

log = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")
COST = 0.001

TICKERS = {
    "SPY": "SPY", "QQQ": "QQQ", "EFA": "EFA", "K200": "069500.KS", "IEF": "IEF", "TLT": "TLT", "SHY": "SHY",
    "GLD": "GLD", "DBC": "DBC", "USDKRW": "KRW=X", "VIX": "^VIX",
    "XLK": "XLK", "XLF": "XLF", "XLV": "XLV", "XLE": "XLE", "XLI": "XLI", "XLY": "XLY", "XLP": "XLP",
    "XLU": "XLU", "XLB": "XLB", "XLRE": "XLRE", "XLC": "XLC",
}
KRW_ASSETS = {"K200"}
LABEL = {"SPY": "S&P500", "QQQ": "나스닥100", "EFA": "선진국(미국 외)", "K200": "KOSPI200", "IEF": "미 중기국채",
         "TLT": "미 장기국채", "SHY": "미 단기채(현금)", "GLD": "금", "DBC": "원자재"}


def fetch(start: str = "2005-01-01"):
    import pandas as pd
    import yfinance as yf
    df = yf.download(list(TICKERS.values()), start=start, auto_adjust=True, progress=False, threads=True)["Close"]
    df = df.rename(columns={v: k for k, v in TICKERS.items()}).sort_index().ffill()
    return df[[c for c in TICKERS if c in df.columns]]


def _krw(px):
    """달러 자산을 원화로 환산한 가격표."""
    out = px.copy()
    fx = px["USDKRW"]
    for c in px.columns:
        if c not in KRW_ASSETS and c not in ("USDKRW", "VIX"):
            out[c] = px[c] * fx
    return out


def _bs_straddle(S: float, vol: float, T: float = 1 / 12, r: float = 0.0) -> float:
    """ATM 스트래들 가격 / 기초자산 (블랙숄즈, K=S)."""
    if not vol or vol <= 0:
        return 0.0
    d1 = (r + 0.5 * vol * vol) * T / (vol * math.sqrt(T))
    d2 = d1 - vol * math.sqrt(T)
    N = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))  # noqa: E731
    call = S * N(d1) - S * math.exp(-r * T) * N(d2)
    put = S * math.exp(-r * T) * N(-d2) - S * N(-d1)
    return (call + put) / S


def _stats(r) -> dict:
    import numpy as np
    r = np.asarray([x for x in r if x == x])
    if len(r) < 6:
        return {}
    eq = np.cumprod(1 + r)
    peak = np.maximum.accumulate(eq)
    sd = r.std(ddof=1)
    return {"cagr": round(float(eq[-1] ** (12 / len(r)) - 1), 4), "vol": round(float(sd * 12 ** 0.5), 4),
            "sharpe": round(float(r.mean() / sd * 12 ** 0.5), 2) if sd else None,
            "mdd": round(float((eq / peak - 1).min()), 4), "total": round(float(eq[-1] - 1), 4),
            "months": int(len(r)), "worst_month": round(float(r.min()), 4), "best_month": round(float(r.max()), 4)}


def run(start_bt: str = "2011-01-01") -> dict:
    import pandas as pd
    px = fetch()
    kp = _krw(px)
    me = kp.resample("ME").last()
    rets = me.pct_change()
    daily = kp.pct_change()
    vol60 = daily.rolling(60).std().resample("ME").last() * math.sqrt(252)
    me_usd = px.resample("ME").last()
    months = [m for m in me.index if m >= pd.Timestamp(start_bt)]

    def weights(name: str, m) -> dict[str, float]:
        i = me.index.get_loc(m)
        if name == "60/40":
            return {"SPY": .30, "QQQ": .15, "K200": .15, "IEF": .40}
        if name == "리스크 패리티":
            assets = ["SPY", "K200", "TLT", "IEF", "GLD", "DBC"]
            v = {a: vol60.loc[m, a] for a in assets if vol60.loc[m, a] == vol60.loc[m, a] and vol60.loc[m, a] > 0}
            inv = {a: 1 / x for a, x in v.items()}
            s = sum(inv.values())
            return {a: x / s for a, x in inv.items()} if s else {"SHY": 1.0}
        if name == "듀얼 모멘텀":
            if i < 12:
                return {"SHY": 1.0}
            r12 = {a: me[a].iloc[i] / me[a].iloc[i - 12] - 1 for a in ("SPY", "EFA", "K200", "SHY")}
            best = max(("SPY", "EFA", "K200"), key=lambda a: r12[a])
            return {best: 1.0} if r12[best] > r12["SHY"] else {"IEF": 1.0}
        if name == "추세추종 GTAA":
            assets = ["SPY", "EFA", "K200", "IEF", "GLD", "DBC"]
            w = {}
            for a in assets:
                sma = me[a].iloc[max(0, i - 9): i + 1].mean()
                k = a if me[a].iloc[i] >= sma else "SHY"
                w[k] = w.get(k, 0) + 1 / len(assets)
            return w
        if name == "한·미 로테이션":
            if i < 6:
                return {"SPY": 1.0}
            a, b = me["K200"].iloc[i] / me["K200"].iloc[i - 6], me["SPY"].iloc[i] / me["SPY"].iloc[i - 6]
            return {"K200": 1.0} if a > b else {"SPY": 1.0}
        raise KeyError(name)

    names = ["60/40", "리스크 패리티", "듀얼 모멘텀", "추세추종 GTAA", "한·미 로테이션"]
    res: dict[str, dict] = {}
    for nm in names:
        prev, rr, curve, eq = {}, [], [], 1.0
        for k, m in enumerate(months[:-1]):
            w = weights(nm, m)
            nxt = months[k + 1]
            r = sum(wt * (me.loc[nxt, a] / me.loc[m, a] - 1) for a, wt in w.items())
            turn = sum(abs(w.get(a, 0) - prev.get(a, 0)) for a in set(w) | set(prev))
            r -= turn * COST
            prev = w
            rr.append(r)
            eq *= 1 + r
            curve.append([str(nxt.date())[:7], round(eq, 4)])
        res[nm] = {"stats": _stats(rr), "curve": curve, "now": weights(nm, me.index[-1]), "rets": rr}

    # 6. 섹터 모멘텀 롱숏 (미국 섹터 ETF, 달러 기준 롱숏 스프레드 + 단기채)
    secs = [c for c in ("XLK", "XLF", "XLV", "XLE", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC") if c in me_usd.columns]
    rr, curve, eq, longs, shorts = [], [], 1.0, [], []
    mu = [m for m in me_usd.index if m >= pd.Timestamp(start_bt)]
    for k, m in enumerate(mu[:-1]):
        i = me_usd.index.get_loc(m)
        if i < 12:
            continue
        mom = {s: me_usd[s].iloc[i - 1] / me_usd[s].iloc[i - 12] - 1 for s in secs
               if me_usd[s].iloc[i - 12] == me_usd[s].iloc[i - 12] and me_usd[s].iloc[i - 1] == me_usd[s].iloc[i - 1]}
        if len(mom) < 6:
            continue
        srt = sorted(mom, key=mom.get, reverse=True)
        longs, shorts = srt[:3], srt[-3:]
        nxt = mu[k + 1]
        lr = sum(me_usd.loc[nxt, s] / me_usd.loc[m, s] - 1 for s in longs) / 3
        sr = sum(me_usd.loc[nxt, s] / me_usd.loc[m, s] - 1 for s in shorts) / 3
        cash = me_usd.loc[nxt, "SHY"] / me_usd.loc[m, "SHY"] - 1
        r = lr - sr + cash - 4 * COST * 0.5
        rr.append(r)
        eq *= 1 + r
        curve.append([str(nxt.date())[:7], round(eq, 4)])
    res["섹터 모멘텀 롱숏"] = {"stats": _stats(rr), "curve": curve, "rets": rr,
                          "now": {**{f"롱 {s}": 1 / 3 for s in longs}, **{f"숏 {s}": -1 / 3 for s in shorts}}}

    # 7·8. 스트래들 (S&P500, 1개월, IV=VIX)
    for nm, sign in (("롱 스트래들", 1), ("숏 스트래들", -1)):
        rr, curve, eq = [], [], 1.0
        for k, m in enumerate(mu[:-1]):
            S0, S1 = me_usd.loc[m, "SPY"], me_usd.loc[mu[k + 1], "SPY"]
            iv = me_usd.loc[m, "VIX"] / 100 if "VIX" in me_usd.columns else None
            prem = _bs_straddle(S0, iv)
            if not prem:
                continue
            payoff = abs(S1 / S0 - 1)
            budget = 0.02                         # 자산의 2% 를 프리미엄 규모로
            leg = budget * (payoff / prem - 1)    # 프리미엄 대비 손익 배수
            cash = me_usd.loc[mu[k + 1], "SHY"] / me_usd.loc[m, "SHY"] - 1
            r = sign * leg + cash * (1 - budget if sign > 0 else 1)
            rr.append(r)
            eq *= 1 + r
            curve.append([str(mu[k + 1].date())[:7], round(eq, 4)])
        iv_now = float(me_usd["VIX"].iloc[-1]) / 100 if "VIX" in me_usd.columns else None
        res[nm] = {"stats": _stats(rr), "curve": curve, "rets": rr,
                   "now": {"SPY 1M ATM 스트래들" + (" 매수" if sign > 0 else " 매도"): 0.02 * sign, "SHY": 0.98},
                   "note": f"현재 IV(VIX) {iv_now*100:.1f}% → 스트래들 가격 약 {_bs_straddle(1, iv_now)*100:.1f}%" if iv_now else ""}

    # 상관관계 (월간 수익률)
    import numpy as np
    keys = list(res)
    L = min(len(res[k]["rets"]) for k in keys)
    mat = np.array([res[k]["rets"][-L:] for k in keys])
    corr = np.corrcoef(mat).round(2).tolist() if L > 12 else []
    out = {"asof": datetime.now(KST).strftime("%Y-%m-%d %H:%M KST"), "base": "KRW (롱숏·스트래들은 USD)",
           "data_to": str(me.index[-1].date()), "cost": COST,
           "strategies": [{"name": k, "stats": v["stats"], "now": {LABEL.get(a, a): round(w, 3) for a, w in v["now"].items()},
                           "curve": v["curve"], "note": v.get("note", "")} for k, v in res.items()],
           "corr": {"names": keys, "matrix": corr}}
    REPORT_DIR.mkdir(exist_ok=True)
    (REPORT_DIR / "portfolios.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    log.info("모의 포트폴리오 %d개: %s", len(res), {k: v["stats"].get("cagr") for k, v in res.items()})
    return out
