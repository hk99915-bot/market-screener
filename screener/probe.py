"""데이터 소스 점검 (Actions 에서 실행, 결과는 reports/logs/probe.json)."""
from __future__ import annotations

import json
import traceback

import requests

from .config import REPORT_DIR

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}


def run() -> dict:
    out = {}
    urls = {
        "naver_news_stock": "https://m.stock.naver.com/api/news/stock/000660?pageSize=5&page=1",
        "naver_news_list": "https://m.stock.naver.com/api/news/list?category=mainnews&pageSize=5&page=1",
        "google_news": "https://news.google.com/rss/search?q=SK%ED%95%98%EC%9D%B4%EB%8B%89%EC%8A%A4+when:7d&hl=ko&gl=KR&ceid=KR:ko",
        "google_news_en": "https://news.google.com/rss/search?q=DRAM+prices+when:7d&hl=en-US&gl=US&ceid=US:en",
        "naver_etf_list": "https://finance.naver.com/api/sise/etfItemList.nhn?etfType=0&targetColumn=market_sum&sortOrder=desc",
        "naver_etf_basic": "https://m.stock.naver.com/api/stock/139260/basic",
        "naver_etf_integration": "https://m.stock.naver.com/api/stock/139260/integration",
        "naver_etf_analysis": "https://m.stock.naver.com/api/stock/139260/etfAnalysis",
        "naver_etf_comp": "https://m.stock.naver.com/api/etf/139260/component",
        "naver_etf_list_m": "https://m.stock.naver.com/api/stocks/etf?page=1&pageSize=5",
        "fut_index": "https://m.stock.naver.com/api/index/FUT/basic",
        "fut_index2": "https://m.stock.naver.com/api/index/KPI200/integration",
        "fut_naver_sise": "https://m.stock.naver.com/api/futures/KS200/basic",
        "deal_trend_fut": "https://m.stock.naver.com/api/index/KOSPI/investorTrend?type=futures",
        "theme_list1": "https://m.stock.naver.com/api/stocks/theme?page=1&pageSize=5",
        "theme_list2": "https://m.stock.naver.com/front-api/stock/theme/list?page=1&pageSize=5",
        "theme_list3": "https://m.stock.naver.com/api/stocks/theme/list?page=1&pageSize=5",
        "theme_stock": "https://m.stock.naver.com/api/stock/000660/integration",
        "theme_pc": "https://finance.naver.com/sise/theme.naver",
        "theme_pc_detail": "https://finance.naver.com/sise/sise_group_detail.naver?type=theme&no=536",
    }
    for k, u in urls.items():
        try:
            r = requests.get(u, headers=UA, timeout=20)
            txt = r.content.decode(r.encoding or "utf-8", "ignore") if "euc" not in (r.encoding or "").lower() else r.content.decode("euc-kr", "ignore")
            i = txt.find("theme") if k == "theme_stock" else 0
            out[k] = {"status": r.status_code, "ctype": r.headers.get("content-type"), "head": txt[max(0, i - 200):i + 1800]}
        except Exception as e:  # noqa: BLE001
            out[k] = {"error": str(e)}
    try:
        import yfinance as yf
        t = yf.Ticker("MU")
        res = {}
        for name in ("eps_trend", "eps_revisions", "earnings_estimate", "revenue_estimate", "earnings_history"):
            try:
                v = getattr(t, name)
                res[name] = v.to_json() if hasattr(v, "to_json") else str(v)[:800]
            except Exception as e:  # noqa: BLE001
                res[name] = "ERR " + str(e)
        try:
            cf = yf.Ticker("MSFT").quarterly_cashflow
            res["msft_capex"] = cf.loc["Capital Expenditure"].to_json() if "Capital Expenditure" in cf.index else list(cf.index)[:30]
        except Exception as e:  # noqa: BLE001
            res["msft_capex"] = "ERR " + str(e)
        try:
            inc = t.quarterly_income_stmt
            res["mu_rev"] = inc.loc["Total Revenue"].to_json() if "Total Revenue" in inc.index else list(inc.index)[:30]
        except Exception as e:  # noqa: BLE001
            res["mu_rev"] = "ERR " + str(e)
        try:
            fd = yf.Ticker("PSI").funds_data
            res["psi_top"] = fd.top_holdings.to_json()
            res["psi_sector"] = str(fd.sector_weightings)[:400]
        except Exception as e:  # noqa: BLE001
            res["psi_top"] = "ERR " + str(e)
        out["yf"] = res
        try:
            from pykrx import stock
            from datetime import date, timedelta
            for back in range(1, 6):
                ymd = (date.today() - timedelta(days=back)).strftime("%Y%m%d")
                try:
                    sb = stock.get_shorting_balance_by_ticker(ymd, market="KOSPI")
                    if sb is not None and len(sb):
                        out["pykrx_short_balance"] = {"date": ymd, "cols": list(sb.columns), "head": sb.head(5).to_json(force_ascii=False)}
                        break
                except Exception as e:  # noqa: BLE001
                    out["pykrx_short_balance"] = "ERR " + str(e)[:200]
            try:
                sv = stock.get_shorting_volume_by_ticker((date.today() - timedelta(days=1)).strftime("%Y%m%d"), market="KOSPI")
                out["pykrx_short_volume"] = {"cols": list(sv.columns), "head": sv.head(3).to_json(force_ascii=False)}
            except Exception as e:  # noqa: BLE001
                out["pykrx_short_volume"] = "ERR " + str(e)[:200]
            try:
                fx = stock.get_market_trading_value_by_investor((date.today() - timedelta(days=7)).strftime("%Y%m%d"), date.today().strftime("%Y%m%d"), "KOSPI")
                out["pykrx_inv"] = fx.head(12).to_json(force_ascii=False)
            except Exception as e:  # noqa: BLE001
                out["pykrx_inv"] = "ERR " + str(e)[:200]
        except Exception as e:  # noqa: BLE001
            out["pykrx_short"] = "ERR " + str(e)[:200]
        try:
            from pykrx import stock
            df = stock.get_etf_portfolio_deposit_file("139260")
            out["pykrx_pdf"] = df.head(15).to_json(force_ascii=False)
        except Exception as e:  # noqa: BLE001
            out["pykrx_pdf"] = "ERR " + str(e)[:300]
        out["yf_version"] = yf.__version__
    except Exception:  # noqa: BLE001
        out["yf"] = traceback.format_exc()
    # KRX 파생 (pykrx 세션 재사용, bld 후보 탐색)
    try:
        from datetime import date, timedelta
        from pykrx.website.krx.krxio import KrxWebIo

        class _B(KrxWebIo):
            def __init__(self, b):
                super().__init__()
                self._b = b
            @property
            def bld(self):
                return self._b
            def fetch(self, **kw):
                return self.read(**kw)
        d = date.today()
        while d.weekday() >= 5:
            d -= timedelta(days=1)
        ymd = d.strftime("%Y%m%d")
        st = (d - timedelta(days=7)).strftime("%Y%m%d")
        tries = [
            ("opt_series", "dbms/MDC/STAT/standard/MDCSTAT12501", {"trdDd": ymd, "prodId": "KRDRVOPK2I", "mktTpCd": "T", "rghtTpCd": "T"}),
            ("opt_series_2", "dbms/MDC/STAT/standard/MDCSTAT12502", {"trdDd": ymd, "prodId": "KRDRVOPK2I", "mktTpCd": "T", "rghtTpCd": "T"}),
            ("fut_series", "dbms/MDC/STAT/standard/MDCSTAT12501", {"trdDd": ymd, "prodId": "KRDRVFUK2I", "mktTpCd": "T", "rghtTpCd": "T"}),
        ]
        for code in ("MDCSTAT13101", "MDCSTAT13102", "MDCSTAT13201", "MDCSTAT13202", "MDCSTAT13001", "MDCSTAT13301"):
            tries.append((code, f"dbms/MDC/STAT/standard/{code}", {"strtDd": st, "endDd": ymd, "prodId": "KRDRVFUK2I", "inqTpCd": "1", "trdVolVal": "2"}))
        for name, bld, prm in tries:
            try:
                r = _B(bld).fetch(**prm)
                o = r.get("output") or r.get("OutBlock_1") or r.get("block1") or []
                out["krx_" + name] = {"keys": list(r.keys())[:6], "n": len(o) if isinstance(o, list) else None,
                                      "head": json.dumps(o[:4] if isinstance(o, list) else r, ensure_ascii=False)[:1500]}
            except Exception as e:  # noqa: BLE001
                out["krx_" + name] = "ERR " + str(e)[:300]
    except Exception as e:  # noqa: BLE001
        out["krx_deriv"] = "ERR " + str(e)[:300]
    try:
        from pykrx import stock as _st
        import yfinance as _yf
        df = _st.get_index_ohlcv("20261001", "20261015", "1001")
        out["krx_kospi_daily"] = {str(i.date()): float(r["종가"]) for i, r in df.iterrows()}
        y = _yf.download("^KS11", start="2026-10-01", interval="1d", auto_adjust=False, progress=False)
        if hasattr(y.columns, "levels"):
            y.columns = [c[0] for c in y.columns]
        out["yf_kospi_daily"] = {str(i): float(r["Close"]) for i, r in y.iterrows()}
    except Exception as e:  # noqa: BLE001
        out["kospi_cmp"] = "ERR " + str(e)[:300]
    try:   # 종가 대조: KRX 정규장 vs 네이버(정규·NXT) vs 야후
        import requests as _rq
        from pykrx import stock as _st2
        cmp = {}
        for code in ("000660", "005930", "009150"):
            df = _st2.get_market_ohlcv("20261013", "20261015", code)
            j = _rq.get(f"https://m.stock.naver.com/api/stock/{code}/basic", headers={"User-Agent": "Mozilla/5.0"}, timeout=10).json()
            cmp[code] = {"krx": {str(i.date()): float(r["종가"]) for i, r in df.iterrows()},
                         "naver": {k: j.get(k) for k in ("closePrice", "fluctuationsRatio", "marketStatus", "localTradedAt")},
                         "naver_over": (j.get("overMarketPriceInfo") or {})}
        out["close_cmp"] = cmp
    except Exception as e:  # noqa: BLE001
        out["close_cmp"] = "ERR " + str(e)[:300]
    try:   # 종가 대조 2: 후보 소스별 10-13~15 OHLC
        out["close_cmp3"] = _close_cmp3()
    except Exception as e:  # noqa: BLE001
        out["close_cmp2"] = "ERR " + traceback.format_exc()[-600:]
    p = REPORT_DIR / "logs" / "probe.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return {k: (v.get("status") if isinstance(v, dict) and "status" in v else "…") for k, v in out.items()}


def _close_cmp2() -> dict:
    import re
    import requests as rq
    from pykrx import stock as st
    codes = {"005930": ".KS", "000660": ".KS", "009150": ".KS", "247540": ".KQ", "086520": ".KQ", "196170": ".KQ"}
    days = ["20261013", "20261014", "20261015"]
    res: dict = {c: {} for c in codes}
    ua = {"User-Agent": UA["User-Agent"]}

    def _safe(name, fn):
        for c in codes:
            try:
                res[c][name] = fn(c)
            except Exception as e:  # noqa: BLE001
                res[c][name] = "ERR " + str(e)[:200]

    # KRX 전종목 시세 (MDCSTAT01501) — 파이프라인이 쓰는 것
    for d in days:
        for mkt in ("KOSPI", "KOSDAQ"):
            try:
                df = st.get_market_ohlcv_by_ticker(d, market=mkt)
                for c in codes:
                    if c in df.index:
                        r = df.loc[c]
                        res[c].setdefault("krx_bytkr", {})[d] = [float(r["시가"]), float(r["고가"]), float(r["저가"]), float(r["종가"]), float(r["거래량"])]
            except Exception as e:  # noqa: BLE001
                res["_err_bytkr_" + d + mkt] = str(e)[:200]
    # 원시 응답 필드 (1행)
    try:
        from pykrx.website.krx.market.core import 전종목시세
        raw = 전종목시세().fetch(days[-1], "STK")
        res["_bytkr_cols"] = list(raw.columns)
        res["_bytkr_row"] = raw[raw["ISU_SRT_CD"] == "005930"].to_dict("records")
    except Exception as e:  # noqa: BLE001
        res["_bytkr_cols"] = "ERR " + str(e)[:200]
    # KRX 개별종목 (MDCSTAT01701, 단순종가)
    _safe("krx_bydate", lambda c: {str(i.date()): [float(x) for x in r[["시가", "고가", "저가", "종가", "거래량"]]]
                                   for i, r in st.get_market_ohlcv(days[0], days[-1], c, adjusted=False).iterrows()})
    # 네이버 fchart (pykrx adjusted=True 경로)
    def _fchart(c):
        t = rq.get(f"https://fchart.stock.naver.com/sise.nhn?symbol={c}&timeframe=day&count=5&requestType=0", headers=ua, timeout=10).text
        return re.findall(r'data="([^"]+)"', t)
    _safe("naver_fchart", _fchart)
    # 네이버 모바일 일별 시세
    _safe("naver_m_price", lambda c: [{k: x.get(k) for k in ("localTradedAt", "openPrice", "highPrice", "lowPrice", "closePrice", "accumulatedTradingVolume")}
                                      for x in rq.get(f"https://m.stock.naver.com/api/stock/{c}/price?pageSize=4&page=1", headers=ua, timeout=10).json()])
    # 네이버 차트 API
    def _chart(c):
        u = f"https://api.stock.naver.com/chart/domestic/item/{c}/day?startDateTime=202610130000&endDateTime=202610152359"
        r = rq.get(u, headers=ua, timeout=10)
        try:
            j = r.json()
        except Exception:  # noqa: BLE001
            return {"status": r.status_code, "head": r.text[:300]}
        return j if isinstance(j, list) else {"status": r.status_code, "head": str(j)[:600]}
    _safe("naver_chart", _chart)
    # 네이버 PC 일별 시세 (sise_day)
    def _sday(c):
        t = rq.get(f"https://finance.naver.com/item/sise_day.naver?code={c}&page=1", headers=ua, timeout=10).content.decode("euc-kr", "ignore")
        rows = re.findall(r'<span class="tah p10 gray03">(\d{4}\.\d\d\.\d\d)</span>(.*?)</tr>', t, re.S)
        o = {}
        for d, rest in rows[:4]:
            nums = re.findall(r'>([\d,]+)<', rest)
            o[d] = nums
        return o
    _safe("naver_sise_day", _sday)
    # 네이버 basic (현재)
    _safe("naver_basic", lambda c: (lambda j: {**{k: j.get(k) for k in ("closePrice", "compareToPreviousClosePrice", "fluctuationsRatio", "marketStatus", "localTradedAt", "stockExchangeType", "tradeStopType")},
                                                 "over": {k: (j.get("overMarketPriceInfo") or {}).get(k) for k in ("overPrice", "overMarketStatus", "tradingSessionType", "localTradedAt")}})
                                    (rq.get(f"https://m.stock.naver.com/api/stock/{c}/basic", headers=ua, timeout=10).json()))
    # 야후
    try:
        import yfinance as yf
        syms = [c + s for c, s in codes.items()]
        y = yf.download(syms, start="2026-10-13", auto_adjust=False, group_by="ticker", progress=False)
        for c, s in codes.items():
            d = y[c + s].dropna(subset=["Close"])
            res[c]["yahoo"] = {str(i.date()): [float(r["Open"]), float(r["High"]), float(r["Low"]), float(r["Close"]), float(r["Volume"])] for i, r in d.iterrows()}
    except Exception as e:  # noqa: BLE001
        res["_yahoo"] = "ERR " + str(e)[:200]
    return res


def _close_cmp3() -> dict:
    """당일 정규장(15:30) 종가 확정: 야후 1분봉·네이버 분봉·네이버 dealTrend·KRX 재조회."""
    import requests as rq
    from pykrx import stock as st
    ua = {"User-Agent": UA["User-Agent"]}
    codes = {"005930": ".KS", "000660": ".KS", "009150": ".KS", "247540": ".KQ", "086520": ".KQ", "196170": ".KQ"}
    res: dict = {c: {} for c in codes}
    try:
        for mkt in ("KOSPI", "KOSDAQ"):
            df = st.get_market_ohlcv_by_ticker("20261015", market=mkt)
            for c in codes:
                if c in df.index:
                    res[c]["krx_bytkr_now"] = [float(df.loc[c, "종가"]), float(df.loc[c, "거래량"])]
    except Exception as e:  # noqa: BLE001
        res["_krx"] = str(e)[:200]
    try:
        from pykrx.website.krx.market.core import 전종목시세
        raw = 전종목시세().fetch("20261014", "STK")
        res["_krx_1014_row"] = raw[raw["ISU_SRT_CD"] == "005930"].to_dict("records")
        res["_lateInfo_counts"] = raw["lateInfoMsgCd"].value_counts().to_dict()
        raw = 전종목시세().fetch("20261015", "STK")
        res["_lateInfo_counts_1015"] = raw["lateInfoMsgCd"].value_counts().to_dict()
    except Exception as e:  # noqa: BLE001
        res["_krx_raw"] = str(e)[:200]
    try:
        import yfinance as yf
        for c, s in codes.items():
            y = yf.download(c + s, period="2d", interval="1m", auto_adjust=False, progress=False)
            if hasattr(y.columns, "levels"):
                y.columns = [x[0] for x in y.columns]
            y.index = y.index.tz_convert("Asia/Seoul")
            y = y[(y.index.strftime("%Y-%m-%d") == "2026-10-15")]
            res[c]["yahoo_1m_tail"] = [[str(i.time()), float(r["Close"]), float(r["Volume"])] for i, r in y.tail(4).iterrows()]
    except Exception as e:  # noqa: BLE001
        res["_y1m"] = str(e)[:200]
    for c in codes:
        try:
            u = f"https://api.stock.naver.com/chart/domestic/item/{c}/minute?startDateTime=202610151517&endDateTime=202610151545"
            j = rq.get(u, headers=ua, timeout=10).json()
            res[c]["naver_min"] = [[x.get("localDateTime"), x.get("currentPrice") or x.get("closePrice"), x.get("accumulatedTradingVolume")] for x in j] if isinstance(j, list) else str(j)[:300]
            res[c]["naver_min_keys"] = list(j[0].keys()) if isinstance(j, list) and j else None
        except Exception as e:  # noqa: BLE001
            res[c]["naver_min"] = "ERR " + str(e)[:200]
        try:
            j = rq.get(f"https://m.stock.naver.com/api/stock/{c}/integration", headers=ua, timeout=10).json()
            res[c]["naver_dealtrend"] = [{k: x.get(k) for k in ("bizdate", "closePrice", "compareToPreviousClosePrice", "accumulatedTradingVolume")} for x in (j.get("dealTrendInfos") or [])[:3]]
            res[c]["naver_integ_keys"] = list(j.keys())
        except Exception as e:  # noqa: BLE001
            res[c]["naver_dealtrend"] = "ERR " + str(e)[:200]
    return res
