"""반도체 바스켓 실적 발표일·컨센서스 EPS (python -m screener.earnings_cal) → reports/earnings_cal.json

대상: universe/semis_basket.json 의 US 종목(PSI·SOXX 구성 + SNDK). 무료 소스 조사(10/24 ra-sec-coverage) 결과 키 없이
바로 되는 것은 야후(yfinance, 비공식) — 예정일(calendar 'Earnings Date')과 이번 분기(0q) EPS·매출 컨센 평균·애널 수.
등급: 예정일은 '추정'(회사 확정 전 포함), 컨센은 야후 집계(공급사 미공개) — 비교용 참고, 매매 트리거 아님.
실패는 종목별 err 로 남기고(조용히 빼지 않음) 전체가 실패하면 이전 파일을 유지한다.
"""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from zoneinfo import ZoneInfo

from .config import REPORT_DIR, UNIVERSE_DIR

log = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")
OUT = REPORT_DIR / "earnings_cal.json"
SRC = "Yahoo Finance (yfinance 비공식 API) — 예정일은 추정 포함, 컨센은 야후 집계"


def members() -> list[str]:
    j = json.loads((UNIVERSE_DIR / "semis_basket.json").read_text(encoding="utf-8"))
    return [m["sym"] for m in j.get("members") or []]


def _num(x):
    try:
        x = float(x)
        return x if x == x else None
    except (TypeError, ValueError):
        return None


def one(t: str) -> dict:
    import yfinance as yf
    r: dict = {"sym": t, "date": None, "eps_avg": None, "eps_n": None, "rev_avg": None, "err": None}
    try:
        tk = yf.Ticker(t)
        cal = tk.calendar
        ds = (cal or {}).get("Earnings Date") if isinstance(cal, dict) else None
        if ds:
            r["date"] = str(ds[0] if isinstance(ds, list) else ds)[:10]
        try:
            ee = tk.earnings_estimate
            r["eps_avg"], r["eps_n"] = _num(ee.loc["0q", "avg"]), _num(ee.loc["0q", "numberOfAnalysts"])
        except Exception as e:  # noqa: BLE001
            r["err"] = f"EPS 컨센 없음({type(e).__name__})"
        try:
            r["rev_avg"] = _num(tk.revenue_estimate.loc["0q", "avg"])
        except Exception:  # noqa: BLE001
            pass
        if not r["date"]:
            r["err"] = (r["err"] + " · " if r["err"] else "") + "예정일 없음"
    except Exception as e:  # noqa: BLE001
        r["err"] = f"{type(e).__name__}: {e}"[:160]
    return r


def build(tickers: list[str] | None = None, fetch=one) -> dict:
    tickers = tickers or members()
    with ThreadPoolExecutor(max_workers=6) as ex:
        rows = list(ex.map(fetch, tickers))
    today = datetime.now(KST).strftime("%Y-%m-%d")
    for r in rows:   # 야후가 다음 예정일로 아직 안 넘긴 '지난 발표일' — 다음 일정 아님을 표시
        r["past"] = bool(r.get("date") and r["date"] < today)
    ok = sum(1 for r in rows if r.get("date"))
    out = {"asof": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "src": SRC, "grade": "추정·참고 — 매매 트리거 아님",
           "unit": "EPS·매출 컨센 = 회사 보고 통화(USD 등), 비율 계산용", "n": len(rows), "n_dated": ok,
           "rows": sorted(rows, key=lambda r: (r.get("date") or "9999", r["sym"]))}
    if ok == 0:
        log.warning("실적일 0건 — 이전 earnings_cal.json 유지")
        return out
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=0), encoding="utf-8")
    log.info("반도체 바스켓 실적일 %d/%d", ok, len(rows))
    return out


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    o = build()
    print(f"실적일 {o['n_dated']}/{o['n']}")
