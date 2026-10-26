"""반도체 바스켓 실적 발표일·컨센서스 EPS (python -m screener.earnings_cal) → reports/earnings_cal.json

대상: universe/semis_basket.json 의 US 종목(PSI·SOXX 구성 + SNDK). 무료 소스 조사(10/24 ra-sec-coverage) 결과 키 없이
바로 되는 것은 야후(yfinance, 비공식) — 예정일(calendar 'Earnings Date')과 이번 분기(0q) EPS·매출 컨센 평균·애널 수.
등급: 예정일은 '추정'(회사 확정 전 포함), 컨센은 야후 집계(공급사 미공개) — 비교용 참고, 매매 트리거 아님.
실패는 종목별 err 로 남기고(조용히 빼지 않음) 전체가 실패하면 이전 파일을 유지한다.
컨센 결측 대용(req-analyst-16fe6a15, 검수 ra-sec-coverage): eps_avg 가 없으면 SEC 직전 분기 순이익÷주식수를
eps_proxy 로 채우고 eps_basis='전분기 대용' 표기 — 컨센이 아닌 '전분기 대비' 비교 기준임을 JSON·화면에 남긴다.
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


BASIS_CONS = "컨센"
BASIS_PROXY = "전분기 대용(컨센 없음 · SEC 순이익÷주식수, 애널 환산)"
BASIS_NONE = "컨센·대용 없음"


def prev_q_eps(sym: str) -> dict | None:
    """SEC 직전 분기 EPS 대용 {eps, period} — 순이익($M)÷주식수(M). 없으면 None."""
    try:
        from . import sec
        q = (sec.summary(sym, n=4) or {}).get("quarters") or []
    except Exception:  # noqa: BLE001
        return None
    for r in reversed(q):
        ni, sh = r.get("ni"), r.get("shares")
        if ni is not None and sh:
            return {"eps": round(ni / sh, 4), "period": r.get("period")}
    return None


def fill_proxy(rows: list[dict], proxy=prev_q_eps) -> int:
    """컨센 결측 행에 전분기 대용·표기. 채운 건수."""
    n = 0
    for r in rows:
        if r.get("eps_avg") is not None:
            r["eps_basis"] = BASIS_CONS
            continue
        p = proxy(r["sym"])
        if p and p.get("eps") is not None:
            r["eps_proxy"], r["eps_proxy_period"], r["eps_basis"] = p["eps"], p.get("period"), BASIS_PROXY
            n += 1
        else:
            r["eps_basis"] = BASIS_NONE
    return n


def build(tickers: list[str] | None = None, fetch=one, proxy=prev_q_eps) -> dict:
    tickers = tickers or members()
    with ThreadPoolExecutor(max_workers=6) as ex:
        rows = list(ex.map(fetch, tickers))
    n_proxy = fill_proxy(rows, proxy)
    today = datetime.now(KST).strftime("%Y-%m-%d")
    for r in rows:   # 야후가 다음 예정일로 아직 안 넘긴 '지난 발표일' — 다음 일정 아님을 표시
        r["past"] = bool(r.get("date") and r["date"] < today)
    ok = sum(1 for r in rows if r.get("date"))
    out = {"asof": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "src": SRC, "grade": "추정·참고 — 매매 트리거 아님",
           "unit": "EPS·매출 컨센 = 회사 보고 통화(USD 등), 비율 계산용", "n": len(rows), "n_dated": ok,
           "n_cons_missing": sum(1 for r in rows if r.get("eps_avg") is None), "n_proxy": n_proxy,
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
