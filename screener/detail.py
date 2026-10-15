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
                           "title": x["title"], "link": x["link"], "summary": x.get("summary") or ""}
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
