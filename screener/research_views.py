"""비종목 리포트 수집 (섹터·전략·매크로·채권·외환·파생·인뎁스) — 종목 리포트(research.py)와 분리.

저장소: data/research_views.parquet (커밋) — 종목 리포트 스키마·analysts 적중률 계산과 섞지 않는다.
  [key, date, source, kind, kind_reason, sector, title, broker, analyst, link, summary, collected_at]
  PDF 원문·전문은 저장하지 않는다(공개 저장소·저작권) — 요약 ≤ SUMMARY_MAX 자와 링크만.
산출물: reports/research_views.json — status(출처별 ok/empty/error/layout_changed/skipped + reason),
  kind별 최근 N건, kind×broker 집계, generated_at/asof.

출처
- 네이버 리서치 5종(산업·시황·투자정보·경제·채권). 2026-10-15 화면 개편(Next.js, Npay 증권)으로 옛 표가 사라져
  10/21 부터 목록 API(stock.naver.com/api/stockSecurity/researches/v2/{type}, 근거 screener/naver_research_api.py)로 받는다.
- 한경 컨센서스: 비CO report_type 값을 **목록 페이지의 '분류선택' 메뉴에서 읽어** 쓴다(값을 코드에 박지 않음 — 추정 금지).
  10/21 실제 응답 확인: IN·MA·EC·DE·FE·BO·FU·QU·FC·ET (UP/DW 는 상향·하향 필터라 제외). 메뉴를 못 찾으면 status=skipped.
"""
from __future__ import annotations

import hashlib
import html as htmlmod
import json
import logging
import re
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import polars as pl

from .config import DATA_DIR, REPORT_DIR
from .report_kind import KINDS, classify

log = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")
STORE = DATA_DIR / "research_views.parquet"
OUT = REPORT_DIR / "research_views.json"
SUMMARY_MAX = 500
SCHEMA = {"key": pl.Utf8, "date": pl.Date, "source": pl.Utf8, "kind": pl.Utf8, "kind_reason": pl.Utf8,
          "sector": pl.Utf8, "title": pl.Utf8, "broker": pl.Utf8, "analyst": pl.Utf8, "link": pl.Utf8,
          "summary": pl.Utf8, "collected_at": pl.Utf8}

NAVER = "https://finance.naver.com/research/"
# cat → (목록 이름 = 1차 분류 카테고리, 목록 파일, 상세 파일)
NAVER_CATS = {
    "industry": ("산업분석", "industry_list.naver", "industry_read.naver"),
    "market_info": ("시황정보", "market_info_list.naver", "market_info_read.naver"),
    "invest": ("투자정보", "invest_list.naver", "invest_read.naver"),
    "economy": ("경제분석", "economy_list.naver", "economy_read.naver"),
    "debenture": ("채권분석", "debenture_list.naver", "debenture_read.naver"),
}
HK = "https://consensus.hankyung.com"

# 머리행 이름 → 필드 (네이버·한경 공통)
HEAD_MAP = [(re.compile(r"작성일|날짜|일자"), "date"), (re.compile(r"제목|리포트"), "title"),
            (re.compile(r"증권사|제공\s*출처|출처"), "broker"), (re.compile(r"작성자|애널"), "analyst"),
            (re.compile(r"분류|업종|산업|종목명"), "sector")]


def _strip(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s or "")
    return re.sub(r"\s+", " ", htmlmod.unescape(s)).strip()


def norm_broker(b: str) -> str:
    """research._norm_broker 와 같은 규칙 (집계 키)."""
    return re.sub(r"\s|\(주\)|증권|투자|금융|주식회사", "", b or "")


def make_key(d: date, source: str, broker: str, title: str) -> str:
    h = hashlib.sha1(re.sub(r"\s+", "", title or "").encode("utf-8")).hexdigest()[:10]
    return f"{d}|{source}|{norm_broker(broker)}|{h}"


def _parse_date(s: str) -> date | None:
    m = re.search(r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})", s or "")
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    else:
        m = re.search(r"\b(\d{2})\.(\d{2})\.(\d{2})\b", s or "")
        if not m:
            return None
        y, mo, d = 2000 + int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def header_columns(h: str) -> dict[str, int]:
    """표 머리행(<th>)에서 필드별 열 번호. 같은 필드가 두 번이면 앞의 것."""
    ths = [_strip(x) for x in re.findall(r"<th[^>]*>([\s\S]*?)</th>", h, flags=re.I)]
    cols: dict[str, int] = {}
    for i, t in enumerate(ths):
        for rx, f in HEAD_MAP:
            if f not in cols and rx.search(t):
                cols[f] = i
                break
    return cols


def looks_like_app_shell(h: str) -> bool:
    """옛 서버 렌더 표 대신 Next.js 앱 껍데기가 온 경우 (10/15 이후 네이버 리서치 목록)."""
    return "_next/static" in (h or "") and "<table" not in (h or "").lower()


def parse_table(h: str, link_rx: str, base: str) -> tuple[list[dict], str]:
    """머리행 이름으로 열을 찾아 행을 뽑는다. 반환 (행, 진단). 행: date,title,broker,analyst,sector,link."""
    if looks_like_app_shell(h):
        return [], "layout_changed: Next.js 앱 화면(표 없음)"
    cols = header_columns(h)
    if "date" not in cols or "title" not in cols:
        return [], f"header_unmapped: 머리행 {sorted(cols)}"
    out = []
    for row in re.split(r"<tr[\s>]", h, flags=re.I)[1:]:
        tds = re.findall(r"<td[^>]*>([\s\S]*?)</td>", row, flags=re.I)
        if len(tds) <= max(cols.values()):
            continue
        d = _parse_date(_strip(tds[cols["date"]]))
        lm = re.search(r"href=[\"']([^\"']*" + link_rx + r"[^\"']*)[\"']", row, flags=re.I)
        if not d or not lm:
            continue
        href = htmlmod.unescape(lm.group(1))
        link = href if href.startswith("http") else base.rstrip("/") + "/" + href.lstrip("/")
        g = lambda f: (_strip(tds[cols[f]]) or None) if f in cols else None  # noqa: E731
        # 제목 칸에는 숨은 요약 팝업(div.layerPop)이 같이 있어(한경 실제 구조) 링크 글자만 제목으로
        ta = re.search(r"<a[^>]+href=[\"'][^\"']*" + link_rx + r"[^\"']*[\"'][^>]*>([\s\S]*?)</a>", tds[cols["title"]], flags=re.I)
        title = _strip(ta.group(1)) if ta else g("title")
        out.append({"date": d, "title": title or "", "broker": g("broker") or "", "analyst": g("analyst"),
                    "sector": g("sector"), "link": link})
    return out, ("ok" if out else "empty: 표는 있으나 행 0")


def _save_probe(name: str, h: str) -> None:
    try:
        (REPORT_DIR / "logs").mkdir(parents=True, exist_ok=True)
        (REPORT_DIR / "logs" / f"rv_{name}.html").write_text((h or "")[:40000], encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def _get(url: str, referer: str, encoding: str | None = None) -> str:
    from .research import _get as rget
    return rget(url, referer, encoding)


NAVER_API_TYPE = {"industry": "industry", "market_info": "market", "invest": "invest", "economy": "economy",
                  "debenture": "debenture"}   # 옛 목록 이름 → researches/v2 researchType (screener/naver_research_api.py)


def fetch_naver(cat: str, since: date, max_pages: int = 10) -> tuple[list[dict], dict]:
    """10/15 화면 개편 뒤 목록 API 로 수집(근거 screener/naver_research_api.py). 요약은 목록 content 에서 ≤500자."""
    from . import naver_research_api as nra
    label = NAVER_CATS[cat][0]
    got, diag = nra.fetch(NAVER_API_TYPE[cat], since, max_pages=max_pages)
    rows = [{"date": r["date"], "title": r["title"], "broker": r["broker"], "analyst": r.get("analyst"),
             "sector": r.get("sector"), "link": r["link"], "summary": r["summary"], "source": "네이버", "category": label}
            for r in got]
    return rows, {**diag, "label": label, "via": "stock.naver.com researches/v2 API"}


HK_SKIP = {"CO", "UP", "DW"}   # 기업(종목 리포트는 research.py) · 상향/하향(필터, 종류 아님) — 사이트 분류 선택 메뉴 기준


def hankyung_types(h: str) -> dict[str, str]:
    """한경 컨센서스 목록 페이지의 '분류선택' 메뉴에서 report_type 값 → 이름 (CO·상향·하향 제외).
    실제 구조(2026-10-21 Actions 응답, tests/fixtures/hankyung_list_co_20261021.html):
      <a href="javascript:_text_change('2','IN','산업')">산업</a> … IN 산업·MA 시장·EC 경제·DE 파생·FE [파생]외환·
      BO [파생]채권·FU [파생]펀드·QU [파생]퀀트·FC [파생]해외·ET [파생]기타 · UP 상향·DW 하향"""
    out: dict[str, str] = {}
    for code, name in re.findall(r"_text_change\('2',\s*'([A-Za-z]{2,4})',\s*'([^']{1,20})'\)", h):
        if code.upper() not in HK_SKIP:
            out.setdefault(code.upper(), name.strip())
    if out:
        return out
    for m in re.finditer(r"<a[^>]+href=[\"'][^\"']*report_type=([A-Za-z]{1,4})[^\"']*[\"'][^>]*>([\s\S]*?)</a>", h, flags=re.I):
        code, name = m.group(1).upper(), _strip(m.group(2))
        if code not in HK_SKIP and name and code not in out and len(name) <= 12:
            out[code] = name
    return out


def fetch_hankyung(since: date, until: date, max_pages: int = 5) -> tuple[list[dict], dict]:
    first = _get(f"{HK}/analysis/list?sdate={since}&edate={until}&report_type=CO&pagenum=80&now_page=1", HK + "/")
    types = hankyung_types(first)
    if not types:
        _save_probe("hankyung_list", first)
        return [], {"status": "skipped", "n": 0, "reason": "report_type 탭 미발견 — 목록 HTML reports/logs/rv_hankyung_list.html", "types": {}}
    rows: list[dict] = []
    per: dict[str, str] = {}
    # 세부 분류([파생]외환·[파생]채권 …)를 상위(파생)보다 먼저 — 같은 리포트가 상위 목록에도 나와서(10/21 실행: FE·BO 행이
    # 모두 DE 로 분류됨) 먼저 본 쪽이 key 중복 제거에서 남기 때문
    for code, name in sorted(types.items(), key=lambda kv: (not kv[1].startswith("["), kv[0])):
        try:
            for p in range(1, max_pages + 1):
                h = _get(f"{HK}/analysis/list?sdate={since}&edate={until}&report_type={code}&pagenum=80&now_page={p}", HK + "/")
                got, diag = parse_table(h, r"report_idx=\d+", HK)
                if p == 1 and not got:
                    _save_probe(f"hankyung_{code}", h)
                for r in got:
                    r.update(source="한경", category=name)
                rows += got
                per[code] = diag if p == 1 else per.get(code, diag)
                if len(got) < 80:
                    break
                time.sleep(0.3)
        except Exception as e:  # noqa: BLE001
            per[code] = f"error: {type(e).__name__}: {str(e)[:120]}"
    st = "ok" if rows else ("error" if all(v.startswith("error") for v in per.values()) else "empty")
    return rows, {"status": st, "n": len(rows), "reason": "; ".join(f"{k}({types[k]}):{v}" for k, v in per.items()),
                  "types": types}


def to_record(r: dict, now: str) -> dict:
    kind, why = classify(r.get("title") or "", r.get("category"))
    sector = r.get("sector") if kind == "섹터" else None
    return {"key": make_key(r["date"], r["source"], r.get("broker") or "", r.get("title") or ""),
            "date": r["date"], "source": r["source"], "kind": kind, "kind_reason": why, "sector": sector,
            "title": r.get("title") or "", "broker": r.get("broker") or "", "analyst": r.get("analyst"),
            "link": r.get("link") or "", "summary": clip_summary(r.get("summary")), "collected_at": now}


def clip_summary(s: str | None) -> str | None:
    if s is None:
        return None
    s = re.sub(r"\s+", " ", s).strip()
    return (s[:SUMMARY_MAX - 1] + "…") if len(s) > SUMMARY_MAX else s


def enrich(rows: list[dict], limit: int = 40) -> int:
    """요약(≤500자). 한경은 PDF 1페이지(research.pdf_summary, 파일 저장 없음), 네이버는 상세 view_cnt."""
    from . import research
    n = 0
    for r in rows:
        if r.get("summary") is not None or n >= limit or not r.get("link"):
            continue
        n += 1
        try:
            if "hankyung" in r["link"]:
                s = research.pdf_summary(r["link"])
            else:
                s = research.parse_summary(_get(r["link"], NAVER, "euc-kr"))
            r["summary"] = clip_summary(s) or "-"
        except Exception as e:  # noqa: BLE001
            log.debug("비종목 요약 실패 %s: %s", r["link"], e)
        time.sleep(0.3)
    return n


def load_store() -> pl.DataFrame:
    if not STORE.exists():
        return pl.DataFrame(schema=SCHEMA)
    df = pl.read_parquet(STORE)
    for c, t in SCHEMA.items():
        if c not in df.columns:
            df = df.with_columns(pl.lit(None, dtype=t).alias(c))
    return df.select(list(SCHEMA))


def merge(store: pl.DataFrame, recs: list[dict]) -> tuple[pl.DataFrame, int]:
    if not recs:
        return store, 0
    new = pl.DataFrame(recs, schema=SCHEMA).unique("key", keep="first")
    add = new.filter(~pl.col("key").is_in(store["key"].implode())) if len(store) else new
    return pl.concat([store, add]).sort("date", "source"), len(add)


def build_json(store: pl.DataFrame, status: dict, now: datetime, recent_n: int = 40, days: int = 90) -> dict:
    cut = now.date() - timedelta(days=days)
    df = store.filter(pl.col("date") >= cut).sort("date", descending=True)
    kinds = {}
    for k in KINDS:
        if k == "종목":
            continue
        sub = df.filter(pl.col("kind") == k)
        kinds[k] = {"n": sub.height, "recent": sub.head(recent_n).with_columns(pl.col("date").cast(pl.Utf8))
                                                  .select("date", "source", "kind_reason", "sector", "title", "broker",
                                                          "analyst", "link", "summary").to_dicts()}
    agg = (df.with_columns(pl.col("broker").map_elements(norm_broker, return_dtype=pl.Utf8).alias("b"))
             .group_by("kind", "b").agg(pl.len().alias("n"), pl.col("date").max().cast(pl.Utf8).alias("last"))
             .sort(["kind", "n"], descending=[False, True]).rename({"b": "broker"}).to_dicts()) if df.height else []
    asof = str(store["date"].max()) if store.height else None
    return {"schema_version": 1, "generated_at": now.strftime("%Y-%m-%d %H:%M KST"), "asof": asof, "days": days,
            "status": status, "kinds": kinds, "by_kind_broker": agg, "n_store": store.height,
            "note": "비종목 리포트(섹터·전략·매크로·채권·외환·파생·인뎁스). 요약 ≤500자·링크만, 원문 저장 안 함. 종목 리포트는 research.json."}


def update(backfill_days: int = 14, overlap_days: int = 3) -> dict:
    """수집 → 저장 → reports/research_views.json. 반환: status (출처별)."""
    now = datetime.now(KST)
    today = now.date()
    store = load_store()
    since = (store["date"].max() - timedelta(days=overlap_days)) if store.height else today - timedelta(days=backfill_days)
    raw: list[dict] = []
    sources: dict[str, dict] = {}
    for cat in NAVER_CATS:
        try:
            got, st = fetch_naver(cat, since)
            raw += got
        except Exception as e:  # noqa: BLE001
            st = {"status": "error", "n": 0, "reason": f"{type(e).__name__}: {str(e)[:160]}", "label": NAVER_CATS[cat][0]}
        sources[f"naver:{cat}"] = st
        log.info("비종목 네이버 %s: %s", cat, st)
    try:
        got, st = fetch_hankyung(since, today)
        raw += got
    except Exception as e:  # noqa: BLE001
        st = {"status": "error", "n": 0, "reason": f"{type(e).__name__}: {str(e)[:160]}"}
    sources["hankyung"] = st
    log.info("비종목 한경: %s", st)

    stamp = now.strftime("%Y-%m-%d %H:%M")
    recs = [to_record(r, stamp) for r in raw]
    existing = set(store["key"].to_list()) if store.height else set()
    fresh = [r for r in recs if r["key"] not in existing]
    n_sum = enrich(fresh)
    store, n_add = merge(store, fresh)
    ok = [k for k, v in sources.items() if v.get("status") == "ok"]
    status = {"overall": "ok" if ok else "error", "ok_sources": ok, "added": n_add, "summaries": n_sum,
              "checked_at": now.strftime("%Y-%m-%d %H:%M KST"), "sources": sources}
    DATA_DIR.mkdir(exist_ok=True)
    if n_add:
        store.write_parquet(STORE)
    REPORT_DIR.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(build_json(store, status, now), ensure_ascii=False), encoding="utf-8")
    log.info("비종목 리포트 저장소 %d건 (신규 %d, 요약 %d) · 상태 %s", store.height, n_add, n_sum, status["overall"])
    return status
