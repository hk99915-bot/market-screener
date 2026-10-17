"""미장 재무: SEC EDGAR XBRL companyfacts (무료, 키 없음) → data/fin/us_quarterly.parquet

SEC 는 User-Agent 에 연락처를 요구한다 → 환경변수 SEC_USER_AGENT (예: "market-screener name@example.com").
없으면 건너뛴다. 요청은 초당 10회 이하로 제한.

분기 값 만들기
- 손익·현금흐름(기간 값): 3개월짜리 기록이 있으면 그대로, 없으면 같은 회계연도 시작일의 누적(YTD) 차분(derived=True).
  2분기 = 6개월 − 1분기, 3분기 = 9개월 − 6개월, 4분기 = 연간(10-K) − 9개월. 앞 누적이 빠지면 그 분기는 비워 둔다.
  12월 결산이 아닌 회사(MU 8~9월·SNDK 6~7월)도 시작일 사슬이라 같은 식으로 처리된다.
- 재무상태(시점 값): 분기 말 값.
종목당 7일마다 갱신(하루 약 1/7씩 순환).
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import date, datetime

import polars as pl
import requests

from .config import DATA_DIR, UNIVERSE_DIR

log = logging.getLogger(__name__)
FIN = DATA_DIR / "fin"
OUT = FIN / "us_quarterly.parquet"
STAMP = FIN / "us_stamp.json"
TICKERS = UNIVERSE_DIR / "sec_tickers.json"
SCHEMA = {"ticker": pl.Utf8, "end": pl.Utf8, "item": pl.Utf8, "value": pl.Float64, "derived": pl.Boolean}   # derived: 누적 차분으로 만든 분기 값

FLOW = {
    "revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet",
                "RevenueFromContractWithCustomerIncludingAssessedTax"],
    "op": ["OperatingIncomeLoss"],
    "ni": ["NetIncomeLoss", "ProfitLoss"],
    "cfo": ["NetCashProvidedByUsedInOperatingActivities", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment"],
    "da": ["DepreciationDepletionAndAmortization", "DepreciationAndAmortization"],
    "div_paid": ["PaymentsOfDividends", "PaymentsOfDividendsCommonStock"],
}
INSTANT = {
    "assets": ["Assets"], "liab": ["Liabilities"], "equity": ["StockholdersEquity"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue"],
    "shares": ["CommonStockSharesOutstanding", "EntityCommonStockSharesOutstanding"],
}


def ua() -> str:
    return os.environ.get("SEC_USER_AGENT", "").strip()


def _get(url: str) -> dict:
    for i in range(3):
        r = requests.get(url, headers={"User-Agent": ua(), "Accept-Encoding": "gzip, deflate"}, timeout=40)
        if r.status_code == 404:
            return {}
        if r.status_code == 429:
            time.sleep(5 * (i + 1))
            continue
        r.raise_for_status()
        time.sleep(0.15)
        return r.json()
    return {}


def ticker_map() -> dict[str, int]:
    if TICKERS.exists() and (time.time() - TICKERS.stat().st_mtime) < 30 * 86400:
        return json.loads(TICKERS.read_text())
    j = _get("https://www.sec.gov/files/company_tickers.json")
    m = {v["ticker"].upper().replace(".", "-"): int(v["cik_str"]) for v in j.values()}
    TICKERS.write_text(json.dumps(m))
    return m


def _days(a: str, b: str) -> int:
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


Q_MIN, Q_MAX = 80, 100      # 3개월 기록으로 인정하는 기간(일). 연간(≈365일)·6·9개월 누적은 모두 사슬 차분 대상


def _flow_quarters(recs: list[dict]) -> dict[str, tuple[float, bool]]:
    """{분기말: (3개월 값, 차분으로 만든 값인지)}

    1) 기간 80~100일 기록은 그대로 분기 값(derived=False).
    2) 그보다 긴 누적(6·9개월·연간) 기록은 **같은 시작일**(=같은 회계연도) 사슬에서 바로 앞 기록(3개월·6개월·9개월)과의
       차가 80~100일일 때만 그 차로 분기 값을 만든다(derived=True). 4분기 = 연간 − 9개월.
       앞 기록이 없거나(예: 6개월 누적만 빠짐) 간격이 한 분기가 아니면 그 분기는 내지 않는다 — 만들어 내지 않는다.
    3) 100일 넘는 기록은 차분 없이는 절대 분기 값으로 내보내지 않는다.
    fy/fp 는 companyfacts 에서 '제출한 보고서'의 연도·기간이라 10-K 의 전년 비교치에도 당해 fy 가 붙는다 → 회계연도 묶음은
    시작일 동일성으로 하고, fp 는 같은 (start,end) 중 어느 제출본을 쓸지(FY > Qn 보고서, 그다음 filed 최신) 고르는 데만 쓴다.
    """
    recs = [r for r in recs if r.get("start") and r.get("end") and r.get("val") is not None and _days(r["start"], r["end"]) >= Q_MIN]
    by: dict[tuple[str, str], dict] = {}
    for r in recs:   # 같은 (start,end) 는 가장 최근 제출본 (연간 보고서 우선)
        k = (r["start"], r["end"])
        rank = (1 if r.get("fp") == "FY" else 0, r.get("filed", ""))
        if k not in by or rank > by[k]["_rank"]:
            by[k] = {**r, "_rank": rank}
    q: dict[str, tuple[float, bool]] = {}
    for (s, e), r in by.items():
        if _days(s, e) <= Q_MAX:
            q[e] = (r["val"], False)
    chain: dict[str, dict[str, float]] = {}   # 시작일 → {끝: 누적 값} (3개월 기록 포함 — 1분기가 6개월 차분의 앞 기록)
    for (s, e), r in by.items():
        chain.setdefault(s, {})[e] = r["val"]
    for s, ends in chain.items():
        es = sorted(ends)
        for i, e in enumerate(es):
            if e in q or _days(s, e) <= Q_MAX:
                continue
            if i == 0:
                continue   # 앞 기록 없는 누적치 — 분기로 만들 수 없음
            prev = es[i - 1]
            if Q_MIN <= _days(prev, e) <= Q_MAX:
                q[e] = (ends[e] - ends[prev], True)
    return q


def _instant(recs: list[dict]) -> dict[str, float]:
    out, filed = {}, {}
    for r in recs:
        if r.get("end") and r.get("val") is not None and not r.get("start"):
            if r["end"] not in out or r.get("filed", "") > filed[r["end"]]:
                out[r["end"]], filed[r["end"]] = r["val"], r.get("filed", "")
    return out


def parse(facts: dict) -> list[dict]:
    g = (facts.get("facts") or {})
    ug, dei = g.get("us-gaap", {}), g.get("dei", {})
    rows = []

    def units(tag: str, src: dict) -> list[dict]:
        u = (src.get(tag) or {}).get("units", {})
        return u.get("USD") or u.get("shares") or []

    for item, tags in FLOW.items():
        # 태그 전환 회사(예: ASC 606 전후 SalesRevenueNet → RevenueFromContractWithCustomer…)는 태그마다 다른 연도의
        # 분기를 갖는다. 첫 태그에서 끊지 않고 전부 합치되, 같은 분기말은 앞선 태그 우선 (setdefault).
        merged: dict[str, tuple[float, bool]] = {}
        for t in tags:
            for e, vd in _flow_quarters(units(t, ug)).items():
                merged.setdefault(e, vd)
        rows += [{"end": e, "item": item, "value": float(v), "derived": d} for e, (v, d) in merged.items()]
    for item, tags in INSTANT.items():
        for t in tags:
            v = _instant(units(t, ug) or units(t, dei))
            if v:
                rows += [{"end": e, "item": item, "value": float(x), "derived": False} for e, x in v.items()]
                break
    return rows


def update(tickers: list[str], refresh_days: int = 7, budget: int = 200) -> int:
    if not ua():
        log.info("SEC_USER_AGENT 없음 — 미장 재무 건너뜀")
        return 0
    FIN.mkdir(parents=True, exist_ok=True)
    stamp = json.loads(STAMP.read_text()) if STAMP.exists() else {}
    cmap = ticker_map()
    old = pl.read_parquet(OUT) if OUT.exists() else pl.DataFrame(schema=SCHEMA)
    if "derived" not in old.columns:   # 예전 파일: 차분 여부 모름 → null
        old = old.with_columns(pl.lit(None, dtype=pl.Boolean).alias("derived"))
    now = time.time()
    todo = [t for t in tickers if t in cmap and now - stamp.get(t, 0) > refresh_days * 86400][:budget]
    new = []
    for t in todo:
        try:
            rows = parse(_get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cmap[t]:010d}.json"))
            new += [{"ticker": t, **r} for r in rows if r["end"] >= "2019-01-01"]
            stamp[t] = now
        except Exception as e:  # noqa: BLE001
            log.warning("SEC %s 실패: %s", t, e)
    if new:
        add = pl.DataFrame(new, schema=SCHEMA)
        done = set(add["ticker"].unique().to_list())
        df = pl.concat([old.filter(~pl.col("ticker").is_in(sorted(done))), add])
        df.write_parquet(OUT)
    STAMP.write_text(json.dumps(stamp))
    log.info("SEC 재무 %d종목 갱신 (남은 대상은 다음 실행)", len(todo))
    return len(todo)


_C: dict[str, pl.DataFrame] = {}


def summary(ticker: str, n: int = 8) -> dict:
    """웹 상세용: 최근 n분기 + TTM (단위 $M)."""
    if "df" not in _C:
        _C["df"] = pl.read_parquet(OUT) if OUT.exists() else pl.DataFrame()
    df = _C["df"]
    if df.is_empty():
        return {}
    g = df.filter(pl.col("ticker") == ticker)
    if g.is_empty():
        return {}
    w = g.pivot(on="item", index="end", values="value", aggregate_function="first").sort("end")
    if "revenue" not in w.columns and "ni" not in w.columns:
        return {}
    w = w.filter(pl.any_horizontal([pl.col(c).is_not_null() for c in ("revenue", "ni", "op") if c in w.columns])).tail(n)
    rows = []
    for r in w.to_dicts():
        d = date.fromisoformat(r["end"])
        rec = {"period": f"{d.year}Q{(d.month - 1) // 3 + 1}", "end": r["end"]}
        for k in list(FLOW) + list(INSTANT):
            v = r.get(k)
            rec[k] = None if v is None else (round(v / 1e6, 1) if k != "shares" else round(v / 1e6, 2))
        rows.append(rec)
    ttm = {}
    if len(rows) >= 4:
        for k in FLOW:
            vals = [x[k] for x in rows[-4:]]
            ttm[k] = round(sum(vals), 1) if all(v is not None for v in vals) else None
        for k in INSTANT:
            ttm[k] = rows[-1].get(k)
    return {"quarters": rows, "ttm": ttm, "unit": "$M"}
