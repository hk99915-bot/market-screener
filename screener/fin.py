"""OpenDART 재무제표 수집 → data/fin/ (가치평가 모델의 입력).

두 층으로 받는다.
1) 주요계정(fnlttMultiAcnt): 유니버스 전 종목, 100개사씩 묶어 기간당 수 콜. 매출·영업이익·순이익·자산·부채·자본.
2) 전체 재무제표(fnlttSinglAcntAll): 우선순위 종목(관심·리포트·보유)만. 현금흐름·감가상각·CAPEX·배당 등 모델링용.

분기 손익은 누적값 차분으로 단독 분기를 만든다 (Q2 = 반기누적 − Q1, Q4 = 연간 − 3분기누적).
현금흐름표는 분기보고서에서도 누적이라 같은 방식으로 처리.
"""
from __future__ import annotations

import io
import json
import logging
import re
import time
import zipfile
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import polars as pl
import requests

from .config import DATA_DIR, UNIVERSE_DIR
from .dart import BASE, key

log = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")
FIN = DATA_DIR / "fin"
MULTI = FIN / "multi.parquet"
FULL = FIN / "full.parquet"
TRIED = FIN / "tried.json"       # 전체재무제표: 데이터 없음(013)으로 확인된 (종목, 기간) — 30일간 재시도 안 함
CORP = UNIVERSE_DIR / "dart_corp.csv"

# 보고서 코드 → (분기 순번, 이름). 분기 순번은 정렬용
REPRT = {"11013": (1, "1Q"), "11012": (2, "반기"), "11014": (3, "3Q"), "11011": (4, "사업")}
CALLS = {"n": 0}

MULTI_SCHEMA = {"code": pl.Utf8, "year": pl.Int32, "reprt": pl.Utf8, "fs_div": pl.Utf8, "sj_div": pl.Utf8,
                "account": pl.Utf8, "amount": pl.Float64, "add_amount": pl.Float64}
FULL_SCHEMA = {"code": pl.Utf8, "year": pl.Int32, "reprt": pl.Utf8, "fs_div": pl.Utf8, "sj_div": pl.Utf8,
               "account_id": pl.Utf8, "account": pl.Utf8, "amount": pl.Float64, "add_amount": pl.Float64}


def _num(x) -> float | None:
    s = str(x or "").replace(",", "").strip()
    if s in ("", "-"):
        return None
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if neg else v


def _api(path: str, params: dict) -> dict:
    for i in range(3):
        try:
            CALLS["n"] += 1
            r = requests.get(f"{BASE}/{path}", params={"crtfc_key": key(), **params}, timeout=30)
            r.raise_for_status()
            j = r.json()
            st = j.get("status")
            if st in ("000", "013"):
                return j
            if st == "020":
                raise RuntimeError("DART 일일 한도 초과(020)")
            raise RuntimeError(f"DART {st}: {j.get('message')}")
        except RuntimeError:
            raise
        except Exception as e:  # noqa: BLE001
            if i == 2:
                raise
            time.sleep(2 * (i + 1))
    return {}


# ───────────── 고유번호 ─────────────

def corp_codes(refresh_days: int = 30) -> dict[str, str]:
    """{종목코드: DART 고유번호(8자리)}"""
    if CORP.exists() and (time.time() - CORP.stat().st_mtime) < refresh_days * 86400:
        df = pl.read_csv(CORP, schema_overrides={"code": pl.Utf8, "corp_code": pl.Utf8})
        return dict(zip(df["code"].to_list(), df["corp_code"].to_list()))
    CALLS["n"] += 1
    r = requests.get(f"{BASE}/corpCode.xml", params={"crtfc_key": key()}, timeout=60)
    r.raise_for_status()
    z = zipfile.ZipFile(io.BytesIO(r.content))
    xml = z.read(z.namelist()[0]).decode("utf-8", "ignore")
    rows = re.findall(r"<corp_code>(\d+)</corp_code>\s*<corp_name>[^<]*</corp_name>\s*"
                      r"(?:<corp_eng_name>[^<]*</corp_eng_name>\s*)?<stock_code>\s*(\d{6})\s*</stock_code>", xml)
    m = {code: cc for cc, code in rows}
    if not m:
        raise RuntimeError("corpCode.xml 파싱 0건")
    pl.DataFrame({"code": list(m), "corp_code": list(m.values())}).write_csv(CORP)
    log.info("DART 고유번호 %d개", len(m))
    return m


# ───────────── 기간 ─────────────

def periods(years: int = 3) -> list[tuple[int, str]]:
    """최근 years 년의 (연도, 보고서코드), 오래된 것부터. 아직 제출 기한 전인 기간은 제외(기한 +15일 여유)."""
    today = datetime.now(KST).date()
    due = {"11013": (5, 31), "11012": (8, 31), "11014": (11, 30), "11011": (4, 15)}   # 다음해 4월 (사업보고서)
    out = []
    for y in range(today.year - years, today.year + 1):
        for rc, (qn, _) in sorted(REPRT.items(), key=lambda x: x[1][0]):
            mo, d = due[rc]
            dy = y + 1 if rc == "11011" else y
            if datetime(dy, mo, d).date() <= today:
                out.append((y, rc))
    return out


# ───────────── 1) 주요계정 (전 종목) ─────────────

def _load(p, schema) -> pl.DataFrame:
    return pl.read_parquet(p) if p.exists() else pl.DataFrame(schema=schema)


def update_multi(codes: list[str], cmap: dict[str, str], refetch_last: int = 2) -> int:
    old = _load(MULTI, MULTI_SCHEMA)
    have = set(zip(old["year"].to_list(), old["reprt"].to_list())) if len(old) else set()
    pers = periods()
    todo = [p for p in pers if p not in have] + [p for p in pers[-refetch_last:] if p in have]
    corp = [cmap[c] for c in codes if c in cmap]
    back = {v: k for k, v in cmap.items()}
    new = []
    for y, rc in todo:
        for i in range(0, len(corp), 100):
            j = _api("fnlttMultiAcnt.json", {"corp_code": ",".join(corp[i:i + 100]), "bsns_year": str(y), "reprt_code": rc})
            for r in j.get("list") or []:
                code = (r.get("stock_code") or "").strip() or back.get(r.get("corp_code"), "")
                new.append({"code": code, "year": y, "reprt": rc, "fs_div": r.get("fs_div", ""),
                            "sj_div": r.get("sj_div", ""), "account": (r.get("account_nm") or "").replace(" ", ""),
                            "amount": _num(r.get("thstrm_amount")), "add_amount": _num(r.get("thstrm_add_amount"))})
            time.sleep(0.1)
        log.info("주요계정 %d %s 누적 %d행", y, REPRT[rc][1], len(new))
    if not new:
        return 0
    add = pl.DataFrame(new, schema=MULTI_SCHEMA)
    keys = ["code", "year", "reprt", "fs_div", "sj_div", "account"]
    df = pl.concat([old, add]).unique(keys, keep="last")
    FIN.mkdir(parents=True, exist_ok=True)
    df.write_parquet(MULTI)
    return len(add)


# ───────────── 2) 전체 재무제표 (우선 종목) ─────────────

def update_full(codes: list[str], cmap: dict[str, str], budget: int = 3000) -> int:
    old = _load(FULL, FULL_SCHEMA)
    have = set(zip(old["code"].to_list(), old["year"].to_list(), old["reprt"].to_list())) if len(old) else set()
    tried = json.loads(TRIED.read_text()) if TRIED.exists() else {}
    cut = (datetime.now(KST) - timedelta(days=30)).strftime("%Y-%m-%d")
    tried = {k: v for k, v in tried.items() if v >= cut}
    pers = periods()
    new, used = [], 0
    for code in codes:
        cc = cmap.get(code)
        if not cc:
            continue
        for y, rc in reversed(pers):                      # 최신 기간부터
            k = f"{code}|{y}|{rc}"
            if (code, y, rc) in have and (y, rc) not in pers[-1:]:
                continue
            if k in tried:
                continue
            if used >= budget:
                break
            got = False
            for fs in ("CFS", "OFS"):                     # 연결 우선, 없으면 별도
                j = _api("fnlttSinglAcntAll.json", {"corp_code": cc, "bsns_year": str(y), "reprt_code": rc, "fs_div": fs})
                used += 1
                rows = j.get("list") or []
                if rows:
                    for r in rows:
                        new.append({"code": code, "year": y, "reprt": rc, "fs_div": fs, "sj_div": r.get("sj_div", ""),
                                    "account_id": r.get("account_id", ""),
                                    "account": (r.get("account_nm") or "").replace(" ", ""),
                                    "amount": _num(r.get("thstrm_amount")), "add_amount": _num(r.get("thstrm_add_amount"))})
                    got = True
                    break
                time.sleep(0.08)
            if not got:
                tried[k] = datetime.now(KST).strftime("%Y-%m-%d")
            time.sleep(0.08)
            if new and used % 300 < 2:          # 중간 저장 (작업이 시간 초과로 끊겨도 받은 만큼 남김)
                _save_full(old, new, tried)
                log.info("전체재무제표 중간 저장: %d콜 · %d행", used, len(new))
        if used >= budget:
            log.info("전체재무제표 예산 %d콜 소진 — 다음 실행에서 이어서", budget)
            break
    _save_full(old, new, tried)
    return len(new)


def _save_full(old: pl.DataFrame, new: list[dict], tried: dict) -> None:
    FIN.mkdir(parents=True, exist_ok=True)
    TRIED.write_text(json.dumps(tried))
    if not new:
        return
    add = pl.DataFrame(new, schema=FULL_SCHEMA)
    keys = ["code", "year", "reprt", "fs_div", "sj_div", "account_id", "account"]
    pl.concat([old, add]).unique(keys, keep="last").write_parquet(FULL)


# ───────────── 분기 시계열 ─────────────

# 표준 항목 ← (account_id 후보, 계정명 후보)
ITEMS = {
    "revenue": (["ifrs-full_Revenue"], ["매출액", "수익(매출액)", "영업수익", "매출"]),
    "op": (["dart_OperatingIncomeLoss"], ["영업이익", "영업이익(손실)"]),
    "ni": (["ifrs-full_ProfitLoss"], ["당기순이익", "당기순이익(손실)", "분기순이익", "반기순이익"]),
    "ni_owner": (["ifrs-full_ProfitLossAttributableToOwnersOfParent"], ["지배기업의소유주에게귀속되는당기순이익", "지배기업소유주지분"]),
    "assets": (["ifrs-full_Assets"], ["자산총계"]),
    "liab": (["ifrs-full_Liabilities"], ["부채총계"]),
    "equity": (["ifrs-full_Equity"], ["자본총계"]),
    "equity_owner": (["ifrs-full_EquityAttributableToOwnersOfParent"], ["지배기업의소유주에게귀속되는자본", "지배기업소유주지분"]),
    "cash": (["ifrs-full_CashAndCashEquivalents"], ["현금및현금성자산"]),
    "cfo": (["ifrs-full_CashFlowsFromUsedInOperatingActivities"], ["영업활동현금흐름", "영업활동으로인한현금흐름"]),
    "capex": (["ifrs-full_PurchaseOfPropertyPlantAndEquipment"], ["유형자산의취득"]),
    "da": (["ifrs-full_DepreciationAndAmortisationExpense", "ifrs-full_AdjustmentsForDepreciationAndAmortisationExpense"], ["감가상각비"]),
    "div_paid": (["ifrs-full_DividendsPaidClassifiedAsFinancingActivities"], ["배당금의지급", "배당금지급"]),
}
FLOW = {"revenue", "op", "ni", "ni_owner", "cfo", "capex", "da", "div_paid"}    # 기간 값(누적 차분 대상)


def _pick(g: pl.DataFrame, ids: list[str], names: list[str], flow: bool) -> float | None:
    for cond in ([pl.col("account_id").is_in(ids)] if "account_id" in g.columns else []) + [pl.col("account").is_in(names)]:
        h = g.filter(cond)
        if len(h):
            r = h.row(0, named=True)
            if flow and r.get("add_amount") is not None and r["reprt"] in ("11012", "11014"):
                return r["add_amount"]   # 반기·3분기는 누적값
            return r["amount"]
    return None


_CACHE: dict[str, pl.DataFrame] = {}


def _frames() -> tuple[pl.DataFrame, pl.DataFrame]:
    if "full" not in _CACHE:
        _CACHE["full"] = _load(FULL, FULL_SCHEMA)
        _CACHE["multi"] = _load(MULTI, MULTI_SCHEMA).with_columns(pl.lit("").alias("account_id"))
    return _CACHE["full"], _CACHE["multi"]


def quarterly(code: str) -> pl.DataFrame:
    """종목의 단독 분기 시계열 (전체재무제표 우선, 없으면 주요계정). 금액 단위: 원."""
    full, multi = _frames()
    src = full.filter(pl.col("code") == code)
    if src.is_empty():
        src = multi.filter(pl.col("code") == code).select(list(FULL_SCHEMA))
    if src.is_empty():
        return pl.DataFrame()
    fs = "CFS" if (src["fs_div"] == "CFS").any() else "OFS"
    src = src.filter(pl.col("fs_div") == fs)
    recs = []
    for (y, rc), g in src.group_by("year", "reprt"):
        rec = {"year": y, "q": REPRT[rc][0]}
        for k, (ids, names) in ITEMS.items():
            rec[k] = _pick(g, ids, names, k in FLOW)
        recs.append(rec)
    if not recs:
        return pl.DataFrame()
    df = pl.DataFrame(recs).sort("year", "q")
    # 누적 → 단독 분기
    out = df.with_columns(pl.col("q").shift(1).over("year").alias("_pq"))
    for k in FLOW & set(df.columns):
        prev = pl.col(k).shift(1).over("year")
        out = out.with_columns(
            pl.when(pl.col("q") == 1).then(pl.col(k))
              .when(pl.col("_pq") == pl.col("q") - 1).then(pl.col(k) - prev)   # 직전 분기가 있어야 차분
              .otherwise(None).alias(k))
    out = out.drop("_pq")
    # 손익계산서는 분기보고서 thstrm 이 이미 단독 분기인 경우가 있어 add_amount 로 누적을 맞췄으므로 위 차분이 맞다.
    # 빠진 분기가 있으면 차분이 틀어지므로 해당 연도는 연속 분기가 있을 때만 신뢰
    return out.with_columns((pl.col("year").cast(pl.Utf8) + "Q" + pl.col("q").cast(pl.Utf8)).alias("period"))


def summary(code: str, n: int = 8) -> dict:
    """웹 상세용: 최근 n분기 + TTM."""
    q = quarterly(code)
    if q.is_empty():
        return {}
    q = q.tail(n)
    rows = q.to_dicts()
    ttm = {}
    if len(q) >= 4:
        last4 = q.tail(4)
        for k in FLOW & set(q.columns):
            vals = last4[k].to_list()
            ttm[k] = sum(vals) if all(v is not None for v in vals) else None
        for k in ("assets", "liab", "equity", "equity_owner", "cash"):
            ttm[k] = q[k].to_list()[-1] if k in q.columns else None
    return {"quarters": [{k: (round(v / 1e8, 1) if isinstance(v, float) else v) for k, v in r.items()} for r in rows],
            "ttm": {k: (round(v / 1e8, 1) if isinstance(v, float) else v) for k, v in ttm.items()}, "unit": "억원"}


def priority_codes(limit: int = 300) -> list[str]:
    """전체재무제표를 받을 우선 종목: 관심종목 → 최근 90일 리포트 종목 → 시총 상위."""
    from .config import REPORT_DIR
    codes: list[str] = []
    try:
        codes += [w["code"] for w in json.loads((REPORT_DIR / "watchlist_KR.json").read_text(encoding="utf-8"))]
    except Exception:  # noqa: BLE001
        pass
    try:
        from .research import load_store
        st = load_store()
        cut = datetime.now(KST).date() - timedelta(days=90)
        codes += st.filter(pl.col("date") >= cut).group_by("code").len().sort("len", descending=True)["code"].to_list()
    except Exception:  # noqa: BLE001
        pass
    try:
        u = pl.read_csv(UNIVERSE_DIR / "kr.csv", schema_overrides={"symbol": pl.Utf8}).sort("mcap", descending=True, nulls_last=True)
        codes += u["symbol"].to_list()
    except Exception:  # noqa: BLE001
        pass
    seen, out = set(), []
    for c in codes:
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out[:limit]


def update(full_budget: int = 3000) -> dict:
    if not key():
        log.info("DART_API_KEY 없음 — 재무제표 건너뜀")
        return {}
    cmap = corp_codes()
    u = pl.read_csv(UNIVERSE_DIR / "kr.csv", schema_overrides={"symbol": pl.Utf8})
    if "mcap" in u.columns:
        u = u.filter(pl.col("mcap").is_null() | (pl.col("mcap") >= 1e11))   # 스크리너와 같은 시총 1,000억 이상
    uni = u["symbol"].to_list()
    n_multi = update_multi(uni, cmap)
    n_full = update_full(priority_codes(), cmap, budget=full_budget)
    out = {"multi_rows": n_multi, "full_rows": n_full, "api_calls": CALLS["n"]}
    log.info("재무제표 %s", out)
    return out
