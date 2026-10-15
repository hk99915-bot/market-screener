"""ETF 상세 — 종목처럼 검색·조회되고, 구성종목으로 풀어서(look-through) 노출·드라이버·가치평가를 합산.

KR: 네이버 ETF 목록(시총 상위) + 꼭 필요한 헷지/레버리지 ETF, 구성은 KRX PDF(pykrx), 가격은 야후(.KS)
US: 주요 ETF 목록, 구성은 야후 funds_data.top_holdings
출력: reports/detail/{KR,US}/{코드}.json (+ _index.json 에 병합)
"""
from __future__ import annotations

import json
import logging
import time
from datetime import date, datetime, timedelta

import requests

from .config import REPORT_DIR

log = logging.getLogger(__name__)
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}
KR_MUST = ["114800", "252670", "122630", "069500", "102110", "139260", "091160", "091230", "396500", "229200", "233740",
           "251340", "261240", "138230", "133690", "360750", "379800", "381170", "305720", "364980", "471760", "117700"]
US_LIST = ["SPY", "QQQ", "DIA", "IWM", "VOO", "VTI", "SCHD", "SOXX", "SMH", "PSI", "XLK", "XLE", "XLF", "XLV", "XLY", "XLP",
           "XLI", "XLU", "XLB", "XLRE", "XLC", "TLT", "IEF", "SHY", "HYG", "LQD", "BND", "GLD", "SLV", "USO", "UNG", "UUP",
           "ARKK", "TQQQ", "SQQQ", "SOXL", "SOXS", "SH", "PSQ", "SDS", "UVXY", "EEM", "EWY", "EWJ", "FXI", "KWEB", "VEA", "VWO",
           "IBIT", "JEPI", "JEPQ", "KRE", "KBE", "ITA", "URA", "LIT", "TAN", "XBI", "IBB", "MAGS", "COPX", "GDX"]
INVERSE_HINT = ("인버스", "SQQQ", "SOXS", "SH", "PSQ", "SDS")


def _kr_list(n: int = 200) -> list[dict]:
    r = requests.get("https://finance.naver.com/api/sise/etfItemList.nhn?etfType=0&targetColumn=market_sum&sortOrder=desc",
                     headers=UA, timeout=30)
    items = r.json()["result"]["etfItemList"]
    items.sort(key=lambda x: -(x.get("marketSum") or 0))
    top = items[:n]
    have = {x["itemcode"] for x in top}
    top += [x for x in items if x["itemcode"] in KR_MUST and x["itemcode"] not in have]
    return top


def _kr_info(code: str) -> dict:
    try:
        j = requests.get(f"https://m.stock.naver.com/api/stock/{code}/etfAnalysis", headers=UA, timeout=15).json()
        return {"summary": j.get("etfSummary"), "base": j.get("etfBaseIndex"), "issuer": j.get("issuerName"),
                "fee": j.get("totalFee"), "nav_total": j.get("totalNav"), "listed": j.get("listedDate")}
    except Exception:  # noqa: BLE001
        return {}


def _kr_holdings(code: str) -> list[dict]:
    try:
        from pykrx import stock  # type: ignore
        df = stock.get_etf_portfolio_deposit_file(code)
        if df is None or len(df) == 0:
            return []
        col = "금액" if "금액" in df.columns else df.columns[-1]
        tot = float(df[col].sum()) or 1.0
        out = [{"code": str(k), "name": str(r.get("구성종목명", k)), "weight": float(r[col]) / tot} for k, r in df.iterrows() if r[col]]
        out.sort(key=lambda x: -x["weight"])
        return out[:20]
    except Exception as e:  # noqa: BLE001
        log.info("ETF 구성 %s 실패: %s", code, e)
        return []


def _us_holdings(t: str) -> tuple[list[dict], dict]:
    try:
        import yfinance as yf
        fd = yf.Ticker(t).funds_data
        th = fd.top_holdings
        hold = []
        if th is not None and len(th):
            for sym, r in th.iterrows():
                hold.append({"code": str(sym).replace(".", "-"), "name": str(r.get("Name", sym)), "weight": float(r.get("Holding Percent") or 0)})
        info = {}
        try:
            info["summary"] = (fd.description or "")[:600]
        except Exception:  # noqa: BLE001
            pass
        try:
            ov = fd.fund_overview or {}
            info["category"] = ov.get("categoryName")
            info["family"] = ov.get("family")
        except Exception:  # noqa: BLE001
            pass
        try:
            info["sectors"] = {k: round(v, 3) for k, v in (fd.sector_weightings or {}).items() if v}
        except Exception:  # noqa: BLE001
            pass
        return hold, info
    except Exception as e:  # noqa: BLE001
        log.info("US ETF 구성 %s 실패: %s", t, e)
        return [], {}


def _prices(tickers: list[str]) -> dict:
    import yfinance as yf
    out = {}
    for i in range(0, len(tickers), 80):
        chunk = tickers[i:i + 80]
        px = yf.download(chunk, period="14mo", interval="1d", auto_adjust=True, progress=False, threads=True, group_by="ticker")
        for t in chunk:
            try:
                g = px[t] if len(chunk) > 1 else px
                g = g.dropna(subset=["Close"])
                if len(g) >= 20:
                    out[t] = g
            except Exception:  # noqa: BLE001
                continue
    return out


def _stats(g) -> tuple[dict, list, list]:
    c = g["Close"].astype(float).tolist()
    d = [str(x.date()) for x in g.index]
    last = c[-1]

    def r(n):
        return last / c[-1 - n] - 1 if len(c) > n and c[-1 - n] else None
    hi = max(c[-250:])
    lo = min(c[-250:])
    sma = lambda n: sum(c[-n:]) / n if len(c) >= n else None  # noqa: E731
    gains = [max(c[i] - c[i - 1], 0) for i in range(len(c) - 14, len(c))]
    losses = [max(c[i - 1] - c[i], 0) for i in range(len(c) - 14, len(c))]
    rsi = 100 - 100 / (1 + (sum(gains) / (sum(losses) or 1e-9))) if len(c) > 15 else None
    st = {"ret1": r(1), "ret5": r(5), "ret20": r(20), "ret60": r(60), "high52": hi, "low52": lo, "from_high52": last / hi - 1,
          "sma20": sma(20), "sma50": sma(50), "sma200": sma(200), "rsi14": rsi}
    rd = lambda v: None if v is None else round(float(v), 4)  # noqa: E731
    chart = [{"d": d[i][5:], "o": rd(g["Open"].iloc[i]), "h": rd(g["High"].iloc[i]), "l": rd(g["Low"].iloc[i]), "c": rd(c[i]),
              "v": int(g["Volume"].iloc[i] or 0), "s20": None, "s50": None} for i in range(max(0, len(c) - 60), len(c))]
    c1y = [[d[i], rd(c[i])] for i in range(max(0, len(c) - 260), len(c))]
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in st.items()}, chart, c1y


def _look(hold: list[dict], market: str) -> dict:
    """구성종목 상세 파일을 읽어 가중 합산."""
    d = REPORT_DIR / "detail"
    acc = {"drv": [0.0, 0.0], "sig": [0.0, 0.0], "norm": [0.0, 0.0], "per": [0.0, 0.0]}
    chains: dict[str, float] = {}
    cov = 0.0
    for h in hold:
        mk = "KR" if h["code"].isdigit() and len(h["code"]) == 6 else "US"
        p = d / mk / f"{h['code']}.json"
        if not p.exists():
            continue
        try:
            s = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if s.get("etf"):
            continue
        w = h["weight"]
        cov += w
        dv, v = s.get("drivers") or {}, s.get("valuation") or {}
        h["drv"] = dv.get("score")
        h["sig"] = (v.get("signal_fv") or {}).get("upside")
        h["norm"] = (v.get("group_upside") or {}).get("normal")
        h["ret20"] = (s.get("stats") or {}).get("ret20")
        h["mk"] = mk
        ch = (dv.get("chain") or {}).get("name") or v.get("sector") or s.get("theme")
        if ch:
            chains[ch] = chains.get(ch, 0) + w
        for k, x in (("drv", h["drv"]), ("sig", h["sig"]), ("norm", h["norm"])):
            if x is not None:
                acc[k][0] += w * x
                acc[k][1] += w
    res = {"coverage": round(cov, 3), "chains": {k: round(v, 3) for k, v in sorted(chains.items(), key=lambda z: -z[1])}}
    for k, (num, den) in acc.items():
        if den > 0.2:
            res[k] = round(num / den, 3)
    return res


def build(market: str) -> int:
    t0 = time.time()
    d = REPORT_DIR / "detail" / market
    if not d.exists():
        return 0
    if market == "KR":
        lst = _kr_list()
        meta = {x["itemcode"]: x for x in lst}
        px = _prices([f"{c}.KS" for c in meta])
        rows = []
        for code, x in meta.items():
            g = px.get(f"{code}.KS")
            if g is None:
                continue
            hold = _kr_holdings(code)
            info = _kr_info(code)
            rows.append((code, x["itemname"], g, hold, info, {"nav": x.get("nav"), "mcap_eok": x.get("marketSum"),
                                                              "r3m": x.get("threeMonthEarnRate")}))
            time.sleep(0.15)
    else:
        px = _prices(US_LIST)
        rows = []
        for t in US_LIST:
            g = px.get(t)
            if g is None:
                continue
            hold, info = _us_holdings(t)
            rows.append((t, t, g, hold, info, {}))
            time.sleep(0.2)
    idx_p = d / "_index.json"
    idx = json.loads(idx_p.read_text(encoding="utf-8")) if idx_p.exists() else {"symbols": [], "names": {}}
    n = 0
    asof = str(date.today())
    for code, name, g, hold, info, extra in rows:
        st, chart, c1y = _stats(g)
        inv = any(h in name for h in INVERSE_HINT) or code in INVERSE_HINT
        look = _look(hold, market) if hold else {}
        rec = {"symbol": code, "name": name if market == "KR" else (info.get("category") and f"{code} · {info['category']}" or code),
               "market": "ETF", "close": round(float(g["Close"].iloc[-1]), 4), "asof": str(g.index[-1].date()),
               "etf": {**info, **extra, "inverse": inv, "holdings": hold, "look": look},
               "stats": st, "chart": chart, "c1y": c1y, "research": {"items": []}, "flows": [], "disclosures": [],
               "financials": {}, "sim": {}, "scenarios": {}, "comment": {}}
        (d / f"{code}.json").write_text(json.dumps(rec, ensure_ascii=False, default=str), encoding="utf-8")
        if code not in idx["symbols"]:
            idx["symbols"].append(code)
        idx.setdefault("names", {})[code] = rec["name"]
        idx.setdefault("etf", [])
        if code not in idx["etf"]:
            idx["etf"].append(code)
        n += 1
    idx_p.write_text(json.dumps(idx, ensure_ascii=False), encoding="utf-8")
    log.info("ETF %s %d개 (%.0fs)", market, n, time.time() - t0)
    return n
