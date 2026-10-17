"""종목 수급 조회 — 1년 일별 투자자별 순매수(거래대금 억원·수량) + 종가·거래량 → reports/flowq/<code>.json.

용도: 오너/PB 가 특정 종목·ETF 의 매집 구간·외인/기관 매수 타점을 물을 때. 샌드박스에서 KRX 가 막혀 Actions 로 돌린다.
  python scripts/flow_query.py 0015B0 [005930 ...] [--days 400]
"""
from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import date, datetime, timedelta, timezone

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("flowq")
KST = timezone(timedelta(hours=9))
KEYS = ("외국인", "기관합계", "개인", "금융투자", "투신", "연기금")


def _pick(df, key):
    cols = [c for c in df.columns if str(c).replace(" ", "") == key] or [c for c in df.columns if key in str(c)]
    return cols[0] if cols else None


def query(code: str, days: int) -> dict:
    from pykrx import stock  # type: ignore
    e = date.today()
    s = e - timedelta(days=days)
    S, E = s.strftime("%Y%m%d"), e.strftime("%Y%m%d")
    val = stock.get_market_trading_value_by_date(S, E, code, detail=True)
    vol = stock.get_market_trading_volume_by_date(S, E, code, detail=True)
    ohlcv = None
    try:
        ohlcv = stock.get_market_ohlcv_by_date(S, E, code)
    except Exception as ex:  # noqa: BLE001
        log.warning("ohlcv 실패 %s: %s", code, ex)
    rows = []
    for idx in val.index:
        r = {"d": idx.strftime("%Y-%m-%d")}
        for k in KEYS:
            c = _pick(val, k)
            if c is not None:
                r[k] = round(float(val.loc[idx, c]) / 1e8, 2)
            c2 = _pick(vol, k) if vol is not None else None
            if c2 is not None and idx in vol.index:
                r[k + "_q"] = int(vol.loc[idx, c2])
        if ohlcv is not None and idx in ohlcv.index:
            r["c"] = float(ohlcv.loc[idx, "종가"])
            r["v"] = int(ohlcv.loc[idx, "거래량"])
        rows.append(r)
    return {"code": code, "asof": rows[-1]["d"] if rows else None, "unit": "억원(값)·주(_q)",
            "generated_at": datetime.now(KST).isoformat(timespec="minutes"), "source": "pykrx/KRX", "rows": rows}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("codes", nargs="+")
    ap.add_argument("--days", type=int, default=400)
    a = ap.parse_args()
    os.makedirs("reports/flowq", exist_ok=True)
    for c in a.codes:
        try:
            out = query(c, a.days)
            json.dump(out, open(f"reports/flowq/{c}.json", "w"), ensure_ascii=False)
            log.info("%s: %d행 asof %s", c, len(out["rows"]), out["asof"])
        except Exception as ex:  # noqa: BLE001
            log.error("%s 실패: %s", c, ex)
            json.dump({"code": c, "error": str(ex)[:300]}, open(f"reports/flowq/{c}.json", "w"), ensure_ascii=False)


if __name__ == "__main__":
    main()
