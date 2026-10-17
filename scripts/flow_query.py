"""종목 수급 조회 — 1년 일별 투자자별 순매수(거래대금 억원·수량) + 종가·거래량 → reports/flowq/<code>.json.

용도: 오너/PB 가 특정 종목·ETF 의 매집 구간·외인/기관 매수 타점을 물을 때. 샌드박스에서 KRX 가 막혀 Actions 로 돌린다.
  python scripts/flow_query.py 0015B0 [005930 ...] [--days 400]
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
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


def naver(code: str, pages: int = 14) -> dict:
    """pykrx 가 못 읽는 신형 코드(예: 0015B0) 폴백 — 네이버 외국인·기관 일별 표(기관/외국인 순매매 '수량', 외국인 보유율)."""
    import re
    import requests
    ua = {"User-Agent": "Mozilla/5.0", "Referer": "https://finance.naver.com/"}
    rows, seen = [], set()
    num = lambda x: float(str(x).replace(",", "").replace("%", "").replace("+", "")) if str(x).strip() not in ("", "-", "nan") else 0.0
    for pg in range(1, pages + 1):
        t = requests.get(f"https://finance.naver.com/item/frgn.naver?code={code}&page={pg}", headers=ua, timeout=15).content.decode("euc-kr", "ignore")
        got = 0
        import io
        import pandas as pd
        try:
            tabs = pd.read_html(io.StringIO(t))
        except Exception:  # noqa: BLE001
            tabs = []
        for tb in tabs:
            tb.columns = [" ".join(map(str, c)) if isinstance(c, tuple) else str(c) for c in tb.columns]
            if not any("날짜" in c for c in tb.columns) or tb.shape[1] < 9:
                continue
            for r in tb.itertuples(index=False):
                v = [str(x) for x in r]
                if not re.match(r"\d{4}\.\d{2}\.\d{2}", v[0]) or v[0] in seen:
                    continue
                seen.add(v[0]); got += 1
                rows.append({"d": v[0].replace(".", "-"), "c": num(v[1]), "v": int(num(v[4])), "기관합계_q": int(num(v[5])),
                             "외국인_q": int(num(v[6])), "외인보유주": int(num(v[7])), "외인보유율": num(v[8])})
        if pg == 1 and not got:
            log.warning("네이버 표 파싱 0행 — 길이 %d, 표 %d개, 앞부분: %s", len(t), len(tabs), re.sub(r"\s+", " ", t[:300]))
        if not got:
            break
    rows.sort(key=lambda r: r["d"])
    return {"code": code, "asof": rows[-1]["d"] if rows else None, "unit": "주(_q)", "source": "naver frgn",
            "generated_at": datetime.now(KST).isoformat(timespec="minutes"), "rows": rows}


def naver_api(code: str, need: int = 260) -> dict:
    """네이버 모바일 API 투자자 추이 — bizdate 커서로 과거 페이지."""
    import requests
    ua = {"User-Agent": "Mozilla/5.0", "Referer": "https://m.stock.naver.com/"}
    num = lambda x: float(str(x).replace(",", "").replace("+", "")) if str(x).strip() not in ("", "-", "None") else 0.0
    rows, seen, cur = [], set(), None
    for _ in range(40):
        u = f"https://m.stock.naver.com/api/stock/{code}/trend?pageSize=60" + (f"&bizdate={cur}" if cur else "")
        r = requests.get(u, headers=ua, timeout=15)
        try:
            js = r.json()
        except Exception:  # noqa: BLE001
            log.warning("trend API 비JSON %s %s", r.status_code, r.text[:200]); break
        if not isinstance(js, list) or not js:
            if not rows:
                log.warning("trend API 응답: %s", str(js)[:300])
            break
        if not rows:
            log.info("trend 키: %s", list(js[0].keys()))
        new = 0
        for x in js:
            d = str(x.get("bizdate", ""))
            if len(d) != 8 or d in seen:
                continue
            seen.add(d); new += 1
            rows.append({"d": f"{d[:4]}-{d[4:6]}-{d[6:]}", "c": num(x.get("closePrice")),
                         "v": int(num(x.get("accumulatedTradingVolume"))),
                         "외국인_q": int(num(x.get("foreignerPureBuyQuant"))), "기관합계_q": int(num(x.get("organPureBuyQuant"))),
                         "개인_q": int(num(x.get("individualPureBuyQuant"))), "외인보유율": num(str(x.get("foreignerHoldRatio", "0")).replace("%", ""))})
        if not new or len(rows) >= need:
            break
        cur = min(seen)
    rows.sort(key=lambda r: r["d"])
    return {"code": code, "asof": rows[-1]["d"] if rows else None, "unit": "주(_q)", "source": "naver m.stock trend",
            "generated_at": datetime.now(KST).isoformat(timespec="minutes"), "rows": rows}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("codes", nargs="+")
    ap.add_argument("--days", type=int, default=400)
    a = ap.parse_args()
    os.makedirs("reports/flowq", exist_ok=True)
    failed = []
    for c in a.codes:
        try:
            try:
                out = query(c, a.days)
            except Exception as ex:  # noqa: BLE001
                log.warning("%s pykrx 실패 → 네이버 폴백: %s", c, str(ex)[:120])
                out = {"rows": []}
            if not out.get("rows"):
                out = naver_api(c)
            if not out.get("rows"):
                out = naver(c)
            out["status"] = "ok" if out.get("rows") else "fail"
            json.dump(out, open(f"reports/flowq/{c}.json", "w"), ensure_ascii=False)
            log.info("%s: %d행 asof %s", c, len(out["rows"]), out["asof"])
            if out["status"] == "fail":
                failed.append(c)
        except Exception as ex:  # noqa: BLE001
            log.error("%s 실패: %s", c, ex)
            failed.append(c)
            json.dump({"code": c, "error": str(ex)[:300]}, open(f"reports/flowq/{c}.json", "w"), ensure_ascii=False)

    if failed:   # 0행·예외 = 실패 (실행 성공 ≠ 데이터 정확, 10/17 레슨런 1)
        log.error("수급 조회 실패: %s", " ".join(failed))
        sys.exit(1)


if __name__ == "__main__":
    main()
