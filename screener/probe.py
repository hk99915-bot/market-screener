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
        "naver_research_industry": "https://m.stock.naver.com/api/research/industry?pageSize=3",
    }
    for k, u in urls.items():
        try:
            r = requests.get(u, headers=UA, timeout=20)
            out[k] = {"status": r.status_code, "ctype": r.headers.get("content-type"), "head": r.text[:1500]}
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
        out["yf"] = res
        out["yf_version"] = yf.__version__
    except Exception:  # noqa: BLE001
        out["yf"] = traceback.format_exc()
    p = REPORT_DIR / "logs" / "probe.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return {k: (v.get("status") if isinstance(v, dict) and "status" in v else "…") for k, v in out.items()}
