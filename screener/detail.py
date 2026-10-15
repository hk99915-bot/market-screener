"""종목 상세 데이터 → reports/detail_{MARKET}.json
대상: 신호 섹션 종목 + 관심종목 + 최근 리포트 종목 (수백 개). 각 종목에
  chart(60일 OHLCV + SMA20/50/200), 지표, 리포트 이력, 수급(10일, KR), 손익비, 시나리오, 코멘트(거시/개별)
"""
from __future__ import annotations

import json
import logging
from datetime import date, timedelta

import polars as pl

from .commentary import market_comment, stock_comment
from .config import REPORT_DIR

log = logging.getLogger(__name__)


def _targets(last: pl.DataFrame, max_n: int = 220) -> list[str]:
    parts = [
        last.filter(pl.col("class") == "TREND_LONG").sort("trend_score", descending=True).head(60),
        last.filter(pl.col("class") == "PULLBACK_IN_UPTREND").sort("trend_score", descending=True).head(40),
        last.filter(pl.col("class") == "COUNTERTREND_BOUNCE").sort("momentum_score", descending=True).head(30),
        last.filter(pl.col("reversal_risk") >= 60).sort("reversal_risk", descending=True).head(30),
        last.filter(pl.col("vol_ratio") >= 3).sort("vol_ratio", descending=True).head(30),
    ]
    if "rp_last_date" in last.columns:
        parts.append(last.filter(pl.col("rp_last_date").is_not_null()).sort("rp_last_date", descending=True).head(60))
    syms = []
    for p in parts:
        for s in p["symbol"].to_list():
            if s not in syms:
                syms.append(s)
    return syms[:max_n]


def _flows_kr(codes: list[str], asof: date, days: int = 10) -> dict[str, list[dict]]:
    """종목별 투자자 순매수(억원) 최근 N일 — pykrx, 종목당 1콜."""
    out = {}
    try:
        from pykrx import stock  # type: ignore
    except Exception:  # noqa: BLE001
        return out
    s, e = (asof - timedelta(days=days * 2)).strftime("%Y%m%d"), asof.strftime("%Y%m%d")
    for c in codes:
        try:
            df = stock.get_market_trading_value_by_date(s, e, c)
            if df is None or df.empty:
                continue
            cols = {k: [x for x in df.columns if k in str(x)] for k in ("외국인", "기관", "개인")}
            rows = []
            for idx, r in df.tail(days).iterrows():
                rows.append({"date": idx.strftime("%m/%d"),
                             **{k: round(float(r[v[0]]) / 1e8, 1) for k, v in cols.items() if v}})
            out[c] = rows
        except Exception as ex:  # noqa: BLE001
            log.debug("수급 %s 실패: %s", c, ex)
    return out


COST = 0.0025   # 왕복 거래비용 가정 (수수료+세금+슬리피지 대략)


def _sim_one(c: list[float], pos: list[int], dates: list, cost: float = COST) -> dict:
    """pos[i] = i일 종가 기준 결정한 포지션(+1 롱, -1 숏, 0 무포지션) → i+1일 수익에 적용."""
    eq, peak, mdd, trades, wins = 1.0, 1.0, 0.0, 0, 0
    entry_px, entry_i, cur = None, None, 0
    for i in range(1, len(c)):
        p = pos[i - 1]
        if p != cur:                       # 포지션 변경 (i-1일 종가에 체결)
            if cur != 0 and entry_px:
                ret = (c[i - 1] / entry_px - 1) * cur
                trades += 1
                wins += ret > 0
            if p != 0:
                entry_px, entry_i = c[i - 1], i - 1
            eq *= (1 - cost / 2) ** (abs(p - cur))
            cur = p
        eq *= 1 + cur * (c[i] / c[i - 1] - 1)
        peak = max(peak, eq)
        mdd = min(mdd, eq / peak - 1)
    open_ret = (c[-1] / entry_px - 1) * cur if cur and entry_px else None
    return {"ret": round(eq - 1, 4), "mdd": round(mdd, 4), "trades": trades,
            "win": round(wins / trades, 3) if trades else None, "pos": cur,
            "entry_date": str(dates[entry_i]) if cur and entry_i is not None else None,
            "entry_px": round(entry_px, 2) if cur and entry_px else None,
            "open_ret": round(open_ret, 4) if open_ret is not None else None}


def _simulate(g: pl.DataFrame, days: int = 250) -> dict:
    """추세추종 백테스트 (단일 종목, 최근 days 영업일, 종가 체결, 비용 왕복 0.25% 가정).
    1) 이평 추세: 종가>SMA50 & SMA20>SMA50 이면 롱, 반대면 숏(롱숏) / 무포지션(롱온리)
    2) PSAR: 종가>PSAR 롱, 아니면 숏/무포지션"""
    g = g.drop_nulls(["close", "sma20", "sma50"]).tail(days)
    if len(g) < 60:
        return {}
    c, s20, s50 = g["close"].to_list(), g["sma20"].to_list(), g["sma50"].to_list()
    ps = g["psar"].to_list() if "psar" in g.columns else [None] * len(c)
    dates = g["date"].to_list()
    ma = [1 if (c[i] > s50[i] and s20[i] > s50[i]) else -1 if (c[i] < s50[i] and s20[i] < s50[i]) else 0 for i in range(len(c))]
    sar = [0 if ps[i] is None else (1 if c[i] > ps[i] else -1) for i in range(len(c))]
    out = {"days": len(c), "from": str(dates[0]), "bh": round(c[-1] / c[0] - 1, 4), "cost": COST}
    for name, sig in (("ma", ma), ("psar", sar)):
        out[name] = {"long": _sim_one(c, [max(x, 0) for x in sig], dates),
                     "ls": _sim_one(c, sig, dates)}
    return out


def _scenarios(r: dict, chart: list[dict]) -> dict:
    """규칙 기반 시나리오: 지지/저항 레벨과 조건. 예측이 아니라 '어느 레벨에서 무엇이 바뀌는가'."""
    c = r.get("close") or 0
    atr = r.get("atr14") or 0
    hi20 = max((x["h"] for x in chart[-20:]), default=c)
    lo20 = min((x["l"] for x in chart[-20:]), default=c)
    tp = r.get("consensus_tp")
    s20, s50, s200, h52, l52 = r.get("sma20"), r.get("sma50"), r.get("sma200"), r.get("high52"), r.get("low52")
    up_target = tp if tp and tp > c else (h52 if h52 and h52 > c else c + 3 * atr)
    dn_next = max([x for x in (s50, s200, l52) if x and x < lo20], default=c - 3 * atr)
    f = lambda v: None if v is None else round(v, 2)  # noqa: E731
    bull = {"trigger": f"20일 고점 {hi20:,.0f} 돌파 + 거래량 1.5배 이상", "target": f(up_target),
            "upside": f((up_target / c - 1) * 100) if c else None,
            "note": "컨센서스 목표가" if tp and tp > c else ("52주 고점" if h52 and h52 > c else "현재가+3ATR")}
    base = {"range": [f(lo20), f(hi20)], "note": f"20일 박스 {lo20:,.0f}~{hi20:,.0f}, 20일선 {s20:,.0f}" if s20 else ""}
    bear = {"trigger": f"20일 저점 {lo20:,.0f} 이탈(종가 기준)", "stop": f(lo20),
            "loss": f((lo20 / c - 1) * 100) if c else None, "next": f(dn_next),
            "note": "다음 지지: " + ("50일선" if dn_next == s50 else "200일선" if dn_next == s200 else "52주 저점" if dn_next == l52 else "현재가-3ATR")}
    rr = None
    if c > lo20 and up_target > c:
        rr = round((up_target - c) / (c - lo20), 1)
    # 급등주는 20일 저점이 너무 멀다 → PSAR(추적 손절) 기준 손익비도 함께
    psar = r.get("psar")
    rr_trail = None
    if psar and c > psar and up_target > c:
        rr_trail = round((up_target - c) / (c - psar), 1)
        bear["trail"] = f(psar)
        bear["trail_loss"] = f((psar / c - 1) * 100)
    return {"bull": bull, "base": base, "bear": bear, "rr": rr, "rr_trail": rr_trail,
            "rr_note": "손익비 = (상승목표-현재가)/(현재가-20일저점). 1.5 미만이면 진입 매력 낮음, 3 이상이어도 확률은 별개"}


def _macro_view(r: dict, mr: list[dict], regime_line: str, br: dict) -> str:
    bits = [market_comment(br)] if br else []
    if regime_line:
        bits.append(regime_line)
    m = {d["key"]: d for d in (mr or [])}
    if r.get("market") in ("KOSPI", "KOSDAQ"):
        if "USDKRW" in m and m["USDKRW"]["chg20"] > 0.02:
            bits.append("원화 약세 지속 — 외국인 수급에 부담")
        elif "USDKRW" in m and m["USDKRW"]["chg20"] < -0.02:
            bits.append("원화 강세 — 외국인 유입 우호")
    if "US10Y" in m and m["US10Y"]["chg20"] > 0.05:
        bits.append("금리 상승 구간 — 고밸류 성장주 할인율 부담")
    if "VIX" in m and m["VIX"]["last"] >= 22:
        bits.append("변동성 높음 — 포지션 크기 축소 구간")
    return " · ".join(b for b in bits if b)


def _flows_bulk(asof_dates: list[date], days: int = 10) -> dict[str, list[dict]]:
    """전 종목 투자자별 순매수(억원) — 날짜×투자자×시장 단위 일괄 조회(약 60콜)로 모든 종목을 한 번에."""
    out: dict[str, dict[str, dict]] = {}
    try:
        from pykrx import stock  # type: ignore
    except Exception:  # noqa: BLE001
        return {}
    inv = {"외국인": "외국인", "기관": "기관합계", "개인": "개인"}
    for d in asof_dates[-days:]:
        ymd = d.strftime("%Y%m%d")
        for mkt in ("KOSPI", "KOSDAQ"):
            for k, name in inv.items():
                try:
                    df = stock.get_market_net_purchases_of_equities(ymd, ymd, mkt, name)
                except Exception as e:  # noqa: BLE001
                    log.debug("일괄 수급 %s %s %s 실패: %s", ymd, mkt, k, e)
                    continue
                if df is None or df.empty:
                    continue
                col = [c for c in df.columns if "순매수거래대금" in str(c)]
                if not col:
                    continue
                for code, v in zip(df.index.astype(str), df[col[0]]):
                    out.setdefault(code.zfill(6), {}).setdefault(d.strftime("%m/%d"), {})[k] = round(float(v) / 1e8, 1)
    return {c: [{"date": dd, **vals} for dd, vals in sorted(m.items(), key=lambda x: x[0])] for c, m in out.items()}


def build(market: str, last: pl.DataFrame, full: pl.DataFrame, store: pl.DataFrame | None,
          mr: list[dict], regime_line: str, br: dict, with_flows: bool = True) -> None:
    syms = [s for s in last["symbol"].to_list() if s]   # 전 종목
    asof = last["date"].max()
    rows = {r["symbol"]: r for r in last.filter(pl.col("symbol").is_in(syms)).to_dicts()}
    hist = (full.filter(pl.col("yf").is_in(last.filter(pl.col("symbol").is_in(syms))["yf"].implode()))
                .sort("yf", "date").group_by("yf").tail(60))
    sims: dict[str, dict] = {}
    try:
        cols = [x for x in ("yf", "date", "close", "sma20", "sma50", "psar") if x in full.columns]
        for (yf,), g in full.select(cols).sort("yf", "date").group_by("yf", maintain_order=True):
            sims[yf] = _simulate(g)
    except Exception as e:  # noqa: BLE001
        log.warning("시뮬레이션 실패: %s", e)
    charts: dict[str, list[dict]] = {}
    for (yf,), g in hist.group_by("yf", maintain_order=True):
        rd = lambda v: None if v is None else round(v, 2)  # noqa: E731
        charts[yf] = [{"d": str(x["date"])[5:], "o": rd(x["open"]), "h": rd(x["high"]), "l": rd(x["low"]), "c": rd(x["close"]),
                       "v": int(x["volume"] or 0), "s20": rd(x.get("sma20")), "s50": rd(x.get("sma50"))} for x in g.to_dicts()]
    reps: dict[str, list[dict]] = {}
    if store is not None and len(store):
        rr = (store.filter(pl.col("code").is_in(syms) & (pl.col("date") >= asof - timedelta(days=180)))
                   .sort("date", descending=True))
        for (code,), g in rr.group_by("code", maintain_order=True):
            reps[code] = [{"date": str(x["date"]), "broker": x["broker"], "opinion": x["opinion"], "target": x["target"],
                           "title": x["title"], "link": x["link"], "summary": x.get("summary") or "",
                           "analyst": x.get("analyst")}
                          for x in g.head(12).to_dicts()]
    flows: dict[str, list[dict]] = {}
    if with_flows and market == "KR":
        days = sorted(set(full["date"].to_list()))[-10:]
        flows = _flows_bulk(days)
        log.info("일괄 수급 %d종목", len(flows))
        if not flows:   # 일괄 조회가 막히면 상위 150종목만 종목별로
            flows = _flows_kr(_targets(last)[:150], asof)
    fins: dict[str, dict] = {}
    if market == "KR":
        try:
            from . import fin
            for s0 in syms:
                v = fin.summary(s0)
                if v:
                    fins[s0] = v
            log.info("재무 요약 %d종목", len(fins))
        except Exception as e:  # noqa: BLE001
            log.warning("재무 요약 실패: %s", e)
    discl = {}
    if market == "KR":
        try:
            from . import dart
            discl = dart.by_code(dart.load(), list(syms), days=180, n=12)
        except Exception as e:  # noqa: BLE001
            log.warning("종목별 공시 실패: %s", e)

    out = {"asof": str(asof), "market": market, "stocks": {}}
    for s in syms:
        r = rows.get(s)
        if not r:
            continue
        ch = charts.get(r["yf"], [])
        fl = flows.get(s, [])
        flow_note = ""
        if fl:
            f5 = sum(x.get("외국인", 0) for x in fl[-5:]); i5 = sum(x.get("기관", 0) for x in fl[-5:])
            flow_note = f"5일 외국인 {f5:+,.0f}억 · 기관 {i5:+,.0f}억 — " + (
                "쌍끌이 매수" if f5 > 0 and i5 > 0 else "동반 매도" if f5 < 0 and i5 < 0 else "엇갈림")
        out["stocks"][s] = {
            "name": r["name"], "market": r["market"], "close": r["close"],
            "stats": {k: (round(r[k], 4) if isinstance(r.get(k), float) else r.get(k)) for k in ("ret1", "ret5", "ret20", "ret60", "trend_score", "momentum_score", "reversal_risk",
                                             "class", "adx14", "rsi14", "cci20", "stoch_k", "macd", "macd_sig", "atr14",
                                             "sma20", "sma50", "sma200", "high52", "low52", "from_high52", "vol_ratio",
                                             "dollar_vol20", "dist_sma20_atr", "psar")},
            "research": {"items": reps.get(s, []), "consensus_tp": r.get("consensus_tp"), "tp_upside": r.get("tp_upside"),
                         "brokers30": r.get("rp_brokers30"), "n30": r.get("rp_n30")},
            "flows": fl, "flow_note": flow_note,
            "disclosures": discl.get(s, []),
            "financials": fins.get(s, {}),
            "sim": sims.get(r["yf"], {}),
            "chart": ch,
            "scenarios": _scenarios(r, ch),
            "comment": {"stock": stock_comment(r, max_parts=5), "macro": _macro_view(r, mr, regime_line, br)},
        }
    import shutil
    d = REPORT_DIR / "detail" / market
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True, exist_ok=True)
    size = 0
    for s, v in out["stocks"].items():
        fp = d / f"{s}.json"
        fp.write_text(json.dumps({**v, "symbol": s, "asof": out["asof"]}, ensure_ascii=False, default=str), encoding="utf-8")
        size += fp.stat().st_size
    (d / "_index.json").write_text(json.dumps({"asof": out["asof"], "symbols": sorted(out["stocks"])}, ensure_ascii=False),
                                   encoding="utf-8")
    old = REPORT_DIR / f"detail_{market}.json"
    old.unlink(missing_ok=True)   # 예전 묶음 파일 제거
    log.info("detail/%s: %d종목, %d KB", market, len(out["stocks"]), size // 1024)
