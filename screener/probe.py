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
    p = REPORT_DIR / "logs" / "probe.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return {k: (v.get("status") if isinstance(v, dict) and "status" in v else "…") for k, v in out.items()}
