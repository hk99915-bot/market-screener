"""OpenDART 공시 수집 (PDF 없음, 목록·분류만).

- 시장 전체(유가·코스닥) 최근 공시 목록을 하루 단위로 받아 data/dart.parquet 에 누적 (접수번호 기준 중복 제거)
- 제목으로 유형 분류 + 주의 플래그 (희석·감자·관리종목 등)
- reports/disclosures.json: 최근 30일 주요 공시 (웹 터미널용)

환경변수 DART_API_KEY 가 없으면 아무것도 하지 않는다.
API 문서: https://opendart.fss.or.kr/guide/main.do
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import polars as pl
import requests

from .config import DATA_DIR, REPORT_DIR

log = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")
BASE = "https://opendart.fss.or.kr/api"
STORE = DATA_DIR / "dart.parquet"
KEEP_DAYS = 400
SCHEMA = {"rcept_no": pl.Utf8, "date": pl.Date, "code": pl.Utf8, "name": pl.Utf8, "corp_cls": pl.Utf8,
          "title": pl.Utf8, "filer": pl.Utf8, "rm": pl.Utf8, "category": pl.Utf8, "flag": pl.Utf8}

# (유형, 제목 키워드들, 주의 플래그) — 위에서부터 먼저 맞는 것
RULES: list[tuple[str, tuple[str, ...], str]] = [
    ("상장폐지·관리", ("상장폐지", "관리종목", "거래정지", "매매거래정지", "불성실공시", "감사의견"), "주의"),
    ("감자", ("감자결정", "자본감소"), "주의"),
    ("유상증자", ("유상증자결정", "유상증자"), "희석"),
    ("CB·BW·EB", ("전환사채", "신주인수권부사채", "교환사채", "전환청구권", "신주인수권행사"), "희석"),
    ("무상증자", ("무상증자",), ""),
    ("자사주", ("자기주식", "자사주"), ""),
    ("배당", ("배당",), ""),
    ("실적", ("영업(잠정)실적", "잠정실적", "매출액또는손익구조", "손익구조"), ""),
    ("수주·계약", ("단일판매", "공급계약"), ""),
    ("합병·분할", ("합병", "분할", "영업양수", "영업양도", "주식교환", "주식이전"), ""),
    ("최대주주", ("최대주주변경", "최대주주 변경"), "주의"),
    ("지분 5%", ("대량보유상황",), ""),
    ("임원·주요주주 매매", ("임원ㆍ주요주주", "임원·주요주주", "특정증권등소유상황"), ""),
    ("타법인 투자", ("타법인주식", "출자증권"), ""),
    ("소송", ("소송",), ""),
    ("정기보고서", ("사업보고서", "반기보고서", "분기보고서"), ""),
    ("IR·공정공시", ("기업설명회", "공정공시", "IR"), ""),
]
MAJOR = {"상장폐지·관리", "감자", "유상증자", "CB·BW·EB", "무상증자", "자사주", "배당", "실적", "수주·계약",
         "합병·분할", "최대주주", "지분 5%", "타법인 투자", "소송"}


def key() -> str:
    return os.environ.get("DART_API_KEY", "").strip()


def classify(title: str) -> tuple[str, str]:
    t = (title or "").replace(" ", "")
    for cat, kws, flag in RULES:
        if any(k.replace(" ", "") in t for k in kws):
            # 정정공시는 유형은 유지하되 플래그를 약하게
            return cat, flag
    return "기타", ""


def link(rcept_no: str) -> str:
    return f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"


def _get(path: str, params: dict, tries: int = 3) -> dict:
    for i in range(tries):
        try:
            r = requests.get(f"{BASE}/{path}", params={"crtfc_key": key(), **params}, timeout=20)
            r.raise_for_status()
            j = r.json()
            st = j.get("status")
            if st in ("000", "013"):          # 013 = 조회된 데이터 없음
                return j
            if st == "020":                   # 요청 제한 초과
                raise RuntimeError("DART 일일 요청 한도 초과(020)")
            raise RuntimeError(f"DART {st}: {j.get('message')}")
        except RuntimeError:
            raise
        except Exception as e:  # noqa: BLE001
            if i == tries - 1:
                raise
            log.warning("DART 재시도 %d: %s", i + 1, e)
            time.sleep(2 * (i + 1))
    return {}


def fetch_day(d: date, max_pages: int = 60) -> list[dict]:
    """하루치 시장 전체 공시 (유가 Y · 코스닥 K). corp_code 없이 조회하면 하루 수백~수천 건."""
    out: list[dict] = []
    for cls in ("Y", "K"):
        page = 1
        while page <= max_pages:
            j = _get("list.json", {"bgn_de": d.strftime("%Y%m%d"), "end_de": d.strftime("%Y%m%d"),
                                   "corp_cls": cls, "page_no": page, "page_count": 100})
            rows = j.get("list") or []
            out += rows
            total = int(j.get("total_page") or 1)
            if page >= total or not rows:
                break
            page += 1
            time.sleep(0.15)
    return out


def _to_df(rows: list[dict]) -> pl.DataFrame:
    recs = []
    for r in rows:
        title = (r.get("report_nm") or "").strip()
        cat, flag = classify(title)
        if title.startswith("[기재정정]") or title.startswith("[첨부정정]"):
            flag = flag or "정정"
        try:
            d = datetime.strptime(r.get("rcept_dt", ""), "%Y%m%d").date()
        except ValueError:
            continue
        recs.append({"rcept_no": r.get("rcept_no", ""), "date": d, "code": (r.get("stock_code") or "").strip(),
                     "name": r.get("corp_name", ""), "corp_cls": r.get("corp_cls", ""), "title": title,
                     "filer": r.get("flr_nm", ""), "rm": r.get("rm", ""), "category": cat, "flag": flag})
    return pl.DataFrame(recs, schema=SCHEMA) if recs else pl.DataFrame(schema=SCHEMA)


def load() -> pl.DataFrame:
    return pl.read_parquet(STORE) if STORE.exists() else pl.DataFrame(schema=SCHEMA)


def update(days: int = 3) -> tuple[pl.DataFrame, int]:
    """최근 days 일(오늘 포함)을 다시 받아 누적. 이미 있는 접수번호는 건너뛴다. 키 없으면 기존 저장분 반환."""
    old = load()
    if not key():
        log.info("DART_API_KEY 없음 — 공시 수집 건너뜀")
        return old, 0
    today = datetime.now(KST).date()
    new = []
    for i in range(days):
        d = today - timedelta(days=i)
        if d.weekday() >= 5:
            continue
        try:
            new.append(_to_df(fetch_day(d)))
        except Exception as e:  # noqa: BLE001
            log.warning("DART %s 실패: %s", d, e)
    if not new:
        return old, 0
    add = pl.concat(new, how="vertical_relaxed")
    seen = set(old["rcept_no"].to_list())
    n_new = add.filter(~pl.col("rcept_no").is_in(sorted(seen))).height if seen else add.height
    df = (pl.concat([old, add], how="vertical_relaxed").unique("rcept_no", keep="last")
            .filter(pl.col("date") >= today - timedelta(days=KEEP_DAYS)).sort("rcept_no", descending=True))
    DATA_DIR.mkdir(exist_ok=True)
    df.write_parquet(STORE)
    log.info("DART 공시 %d건 저장 (신규 %d)", df.height, n_new)
    return df, n_new


def by_code(df: pl.DataFrame, codes: list[str], days: int = 90, n: int = 10, major_only: bool = True) -> dict[str, list[dict]]:
    if not len(df):
        return {}
    cut = datetime.now(KST).date() - timedelta(days=days)
    f = df.filter(pl.col("code").is_in(codes) & (pl.col("date") >= cut))
    if major_only:
        f = f.filter(pl.col("category").is_in(sorted(MAJOR)) | (pl.col("flag") != ""))
    out: dict[str, list[dict]] = {}
    for (code,), g in f.sort("rcept_no", descending=True).group_by("code", maintain_order=True):
        out[code] = [{"date": str(x["date"]), "title": x["title"], "category": x["category"], "flag": x["flag"],
                      "link": link(x["rcept_no"])} for x in g.head(n).to_dicts()]
    return out


def write_json(df: pl.DataFrame | None = None, days: int = 30) -> int:
    """웹 터미널용 최근 주요 공시."""
    df = load() if df is None else df
    if not len(df):
        return 0
    cut = datetime.now(KST).date() - timedelta(days=days)
    f = (df.filter((pl.col("date") >= cut) & (pl.col("code") != "")
                   & (pl.col("category").is_in(sorted(MAJOR)) | (pl.col("flag") != "")))
           .sort("rcept_no", descending=True))
    items = [{"date": str(x["date"]), "code": x["code"], "name": x["name"], "title": x["title"],
              "category": x["category"], "flag": x["flag"], "link": link(x["rcept_no"])} for x in f.to_dicts()]
    out = {"asof": datetime.now(KST).strftime("%Y-%m-%d %H:%M KST"), "days": days, "items": items}
    (REPORT_DIR / "disclosures.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return len(items)


def brief_lines(df: pl.DataFrame, codes: set[str], since: date, limit: int = 10) -> list[str]:
    """장전 브리핑용: since 이후 관심·리포트·신호 종목의 주요 공시."""
    if not len(df) or not codes:
        return []
    f = (df.filter((pl.col("date") >= since) & pl.col("code").is_in(sorted(codes))
                   & (pl.col("category").is_in(sorted(MAJOR)) | (pl.col("flag") != "")))
           .sort("rcept_no", descending=True).head(limit))
    return [f"{'⚠️ ' if x['flag'] in ('희석', '주의') else ''}{x['name']} · {x['category']} · {x['title'][:40]}"
            for x in f.to_dicts()]
