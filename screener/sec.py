"""미장 재무: SEC EDGAR XBRL companyfacts (무료, 키 없음) → data/fin/us_quarterly.parquet

SEC 는 User-Agent 에 연락처를 요구한다 → 환경변수 SEC_USER_AGENT (예: "market-screener name@example.com").
없으면 건너뛴다. 요청은 초당 10회 이하로 제한.

분기 값 만들기
- 손익·현금흐름(기간 값): 3개월짜리 기록이 있으면 그대로, 없으면 같은 회계연도 시작일의 누적(YTD) 차분(derived=True).
  2분기 = 6개월 − 1분기, 3분기 = 9개월 − 6개월, 4분기 = 연간(10-K) − 9개월. 앞 누적이 빠지면 그 분기는 비워 둔다.
  12월 결산이 아닌 회사(MU 8~9월·SNDK 6~7월)도 시작일 사슬이라 같은 식으로 처리된다.
- 재무상태(시점 값): 분기 말 값.
회전 배치(10/24 겸이 "전종목으로 나눠서 천천히 꾸준히"): 실행당 SEC_BUDGET(기본 80)종목 — 우선 목록(반도체 바스켓) 먼저,
나머지는 마지막 확인이 오래된 순. 이미 받은 종목은 submissions 의 최신 정기보고서(10-Q/10-K/20-F…) 제출일이
지난번과 같으면 companyfacts 를 다시 받지 않는다(증분). 진행 상태 = data/fin/sec_progress.json (확인·수집·실패·CIK 없음·IFRS).
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import date, datetime, timezone

import polars as pl
import requests

from .config import DATA_DIR, UNIVERSE_DIR

log = logging.getLogger(__name__)
FIN = DATA_DIR / "fin"
OUT = FIN / "us_quarterly.parquet"
STAMP = FIN / "us_stamp.json"
PROGRESS = FIN / "sec_progress.json"   # 종목별 {cik, checked, fetched, last_filed, status, err, rows} + 요약·완주 예상
PERIODIC = ("10-Q", "10-K", "10-Q/A", "10-K/A", "10-KT", "20-F", "20-F/A", "40-F", "40-F/A")
BUDGET = 80                            # 실행당 종목 수 기본값(환경변수 SEC_BUDGET) — 약 560종목 ÷ 80 ≈ 7일 한 바퀴
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


def last_periodic_filed(sub: dict) -> str | None:
    """submissions JSON 에서 최신 정기보고서(10-Q/10-K/20-F/40-F) 제출일 (YYYY-MM-DD). 없으면 None."""
    r = (sub.get("filings") or {}).get("recent") or {}
    ds = [d for f, d in zip(r.get("form") or [], r.get("filingDate") or []) if f in PERIODIC and d]
    return max(ds) if ds else None


def plan(tickers: list[str], stamp: dict, now: float, refresh_days: int, budget: int, priority: list[str] | None = None) -> list[str]:
    """이번 실행에서 확인할 종목(최대 budget). 갱신 주기(refresh_days)가 지난 것만.
    순서: 우선 목록(입력 순서) → 나머지는 마지막 확인(stamp)이 오래된 순(한 번도 안 받은 종목 = 0 이 맨 앞)."""
    pri = [t for t in dict.fromkeys(priority or []) if t in set(tickers)]
    due = [t for t in dict.fromkeys(tickers) if now - stamp.get(t, 0) > refresh_days * 86400]
    ps = set(pri)
    first = [t for t in pri if t in set(due)]
    rest = sorted((t for t in due if t not in ps), key=lambda t: (stamp.get(t, 0), t))
    return (first + rest)[:budget]


def progress_summary(prog: dict, universe: list[str], budget: int, today: date | None = None) -> dict:
    """전체 n 중 수집 완료·미수집·실패·CIK 없음 수와 완주 예상일(미수집 ÷ 실행당 종목, 하루 1회 실행 가정)."""
    from datetime import timedelta
    per = prog.get("tickers", {})
    st = {t: (per.get(t) or {}).get("status", "never") for t in universe}
    cnt: dict[str, int] = {}
    for v in st.values():
        cnt[v] = cnt.get(v, 0) + 1
    got = sum(1 for t in universe if (per.get(t) or {}).get("fetched"))
    pending = sum(1 for t in universe if not (per.get(t) or {}).get("checked") and st[t] != "no_cik")
    days = -(-pending // budget) if budget else None
    today = today or date.today()
    return {"universe": len(universe), "fetched_ever": got, "pending_first_check": pending, "by_status": cnt,
            "budget_per_run": budget, "eta_first_cycle": (today + timedelta(days=days)).isoformat() if days is not None else None,
            "eta_basis": "미확인 종목 ÷ 실행당 종목 수, fin.yml 하루 1회(03:30 KST) 가정"}


def update(tickers: list[str], refresh_days: int = 7, budget: int | None = None, priority: list[str] | None = None) -> int:
    if not ua():
        log.info("SEC_USER_AGENT 없음 — 미장 재무 건너뜀")
        return 0
    budget = budget if budget is not None else int(os.environ.get("SEC_BUDGET", BUDGET))
    FIN.mkdir(parents=True, exist_ok=True)
    stamp = json.loads(STAMP.read_text()) if STAMP.exists() else {}
    prog = json.loads(PROGRESS.read_text()) if PROGRESS.exists() else {}
    per = prog.setdefault("tickers", {})
    cmap = ticker_map()
    old = pl.read_parquet(OUT) if OUT.exists() else pl.DataFrame(schema=SCHEMA)
    if "derived" not in old.columns:   # 예전 파일: 차분 여부 모름 → null
        old = old.with_columns(pl.lit(None, dtype=pl.Boolean).alias("derived"))
    have = set(old["ticker"].unique().to_list()) if not old.is_empty() else set()
    universe = list(dict.fromkeys((priority or []) + list(tickers)))
    for t in universe:
        if t not in cmap:   # 상장폐지·인수(예: CYBR)·티커 변경 — 조용히 빼지 않고 기록
            per[t] = {**per.get(t, {}), "status": "no_cik"}
    now = time.time()
    nowiso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    todo = plan([t for t in universe if t in cmap], stamp, now, refresh_days, budget, priority)
    new, n_fetch = [], 0
    for t in todo:
        e = {**per.get(t, {}), "cik": cmap[t], "checked": nowiso}
        try:
            cik = f"{cmap[t]:010d}"
            lf = last_periodic_filed(_get(f"https://data.sec.gov/submissions/CIK{cik}.json"))
            if lf and e.get("fetched") and e.get("last_filed") == lf and e.get("status") in ("ok", "unchanged", "ifrs", "no_data") \
                    and (t in have or e.get("status") != "ok"):
                if e.get("status") in ("ok", "unchanged"):   # 새 정기보고서 없음 → companyfacts 생략(증분). ifrs·no_data 는 상태 유지
                    e.update(status="unchanged", err=None)
            else:
                facts = _get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json")
                n_fetch += 1
                rows = [r for r in parse(facts) if r["end"] >= "2019-01-01"]
                if rows:
                    new += [{"ticker": t, **r} for r in rows]
                flows = sum(1 for r in rows if r["item"] in ("revenue", "op", "ni"))
                if flows:
                    e.update(status="ok", fetched=nowiso, last_filed=lf, rows=len(rows), err=None)
                else:   # 20-F(연간만)·IFRS 제출사: 시점 값(주식 수 등)만 있거나 아무것도 없음 — 분기 손익 없음을 기록
                    tax = sorted((facts.get("facts") or {}).keys())
                    e.update(status="ifrs" if "ifrs-full" in tax else "no_data", fetched=nowiso, last_filed=lf, rows=len(rows),
                             err=f"us-gaap 분기 손익 없음 (taxonomy {','.join(tax) or '없음'})")
            stamp[t] = now
        except Exception as ex:  # noqa: BLE001
            e.update(status="fail", err=f"{type(ex).__name__}: {ex}"[:200])
            log.warning("SEC %s 실패: %s", t, ex)
        per[t] = e
    if new:
        add = pl.DataFrame(new, schema=SCHEMA)
        done = set(add["ticker"].unique().to_list())
        df = pl.concat([old.filter(~pl.col("ticker").is_in(sorted(done))), add])
        df.write_parquet(OUT)
    STAMP.write_text(json.dumps(stamp))
    prog.update({"_doc": "SEC companyfacts 회전 수집 진행 상태 (screener/sec.py update). status: ok=이번 수집 · unchanged=새 정기보고서 없어 생략 · "
                         "fail=요청 실패 · no_cik=SEC 티커 목록에 없음 · ifrs=IFRS 제출사(us-gaap 없음, 미지원) · no_data=분기 값 없음 · never=아직 차례 안 옴",
                 "updated": nowiso, "last_run": {"checked": len(todo), "companyfacts": n_fetch, "rows_added": len(new)},
                 "summary": progress_summary(prog, universe, budget)})
    PROGRESS.write_text(json.dumps(prog, ensure_ascii=False, indent=0, sort_keys=True))
    log.info("SEC 재무 %d종목 확인(companyfacts %d) — 남은 대상은 다음 실행", len(todo), n_fetch)
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
