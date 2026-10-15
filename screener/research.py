"""증권사 리포트 수집·저장·분석 (네이버증권 종목분석 + 한경컨센서스).

저장소: data/research.parquet (커밋)
  [key, date, source, code, name, title, broker, opinion, target, link, collected_at]
key = 날짜|종목|증권사(정규화) — 같은 날 같은 증권사의 같은 종목 리포트는 1건 (한경 우선: 목표가 포함).

분석 함수는 모두 KRX 시세(data/kr_prices.parquet)와 결합:
  attach_latest()      종목별 최근 리포트·컨센서스 목표가·여력·손익비
  revisions()          같은 증권사 직전 리포트 대비 목표가/의견 변화
  crowding()           최근 N일 다수 증권사 동시 커버·목표가 상향
  post_performance()   발간 후 +5/+20/+60 영업일 수익률 (시장 중앙값 대비 초과)
  broker_stats()       증권사별 평균 초과수익·적중률
"""
from __future__ import annotations

import html as htmlmod
import logging
import re
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import polars as pl
import requests

from .config import DATA_DIR

log = logging.getLogger(__name__)
STORE = DATA_DIR / "research.parquet"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"}
SCHEMA = {"key": pl.Utf8, "date": pl.Date, "source": pl.Utf8, "code": pl.Utf8, "name": pl.Utf8, "title": pl.Utf8,
          "broker": pl.Utf8, "opinion": pl.Utf8, "target": pl.Float64, "link": pl.Utf8, "collected_at": pl.Utf8,
          "summary": pl.Utf8, "analyst": pl.Utf8}
KST = ZoneInfo("Asia/Seoul")

BUY_WORDS = re.compile(r"(?i)buy|매수|outperform|overweight|비중확대|strong")
SELL_WORDS = re.compile(r"(?i)sell|매도|underperform|underweight|비중축소|reduce")


def opinion_rank(op: str | None) -> int:
    """매수 2 / 중립 1 / 매도 0 / 없음 -1"""
    if not op:
        return -1
    if SELL_WORDS.search(op):
        return 0
    if BUY_WORDS.search(op):
        return 2
    return 1


def _strip(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s or "")
    return re.sub(r"\s+", " ", htmlmod.unescape(s)).strip()


def _num(s) -> float | None:
    s = re.sub(r"[^\d.]", "", str(s or ""))
    try:
        v = float(s)
        return v if v > 0 else None
    except ValueError:
        return None


def _get(url: str, referer: str, encoding: str | None = None) -> str:
    r = requests.get(url, headers={**UA, "Referer": referer}, timeout=20)
    r.raise_for_status()
    if encoding:
        r.encoding = encoding
    elif not r.encoding or r.encoding.lower() in ("iso-8859-1", "ascii"):
        r.encoding = r.apparent_encoding
    return r.text


def _norm_broker(b: str) -> str:
    return re.sub(r"\s|\(주\)|증권|투자|금융|주식회사", "", b or "")


def make_key(d: date, code: str, broker: str) -> str:
    return f"{d}|{code}|{_norm_broker(broker)}"


# ───────────── 네이버증권 ─────────────

def fetch_naver(since: date, max_pages: int = 60) -> list[dict]:
    out = []
    for p in range(1, max_pages + 1):
        h = _get(f"https://finance.naver.com/research/company_list.naver?page={p}",
                 "https://finance.naver.com/research/", "euc-kr")
        rows = re.split(r"<tr[\s>]", h, flags=re.I)[1:]
        found = older = 0
        for row in rows:
            nid = re.search(r"company_read\.naver\?nid=(\d+)", row)
            stock = re.search(r"code=(\d{6})[^>]*>([^<]+)</a>", row)
            dm = re.search(r"(\d{2})\.(\d{2})\.(\d{2})", row)
            if not (nid and stock and dm):
                continue
            d = date(2000 + int(dm.group(1)), int(dm.group(2)), int(dm.group(3)))
            found += 1
            if d < since:
                older += 1
                continue
            tds = [_strip(x) for x in re.findall(r"<td[^>]*>([\s\S]*?)</td>", row, flags=re.I)]
            tm = re.search(r"company_read\.naver\?nid=\d+[^\"']*[\"'][^>]*>([\s\S]*?)</a>", row)
            out.append({
                "date": d, "source": "네이버", "code": stock.group(1), "name": stock.group(2).strip(),
                "title": _strip(tm.group(1)) if tm else (tds[1] if len(tds) > 1 else ""),
                "broker": tds[2] if len(tds) > 2 else "", "opinion": None, "target": None,
                "link": f"https://finance.naver.com/research/company_read.naver?nid={nid.group(1)}",
            })
        if p == 1 and found == 0:   # 진단: 파싱 0건이면 응답 일부를 남김 (reports/logs/naver_list.html)
            try:
                from .config import REPORT_DIR
                (REPORT_DIR / "logs").mkdir(parents=True, exist_ok=True)
                (REPORT_DIR / "logs" / "naver_list.html").write_text(h[:20000], encoding="utf-8")
                log.warning("네이버 리스트 파싱 0건 — 응답 %d자, tr %d개 저장", len(h), len(rows))
            except Exception:  # noqa: BLE001
                pass
        if found == 0 or older > 0:
            break
        time.sleep(0.2)
    return out


CUT = re.compile(r"(본\s*조사분석자료|본\s*자료는|Compliance|컴플라이언스|당사는\s*동\s*자료|투자등급\s*관련)")


def parse_summary(h: str) -> str:
    """네이버 리서치 상세 페이지의 본문 요약(애널리스트 작성 핵심 문단)."""
    m = re.search(r"class=[\"']view_cnt[\"'][^>]*>([\s\S]*?)</td>", h, flags=re.I)
    if not m:
        return ""
    body = re.sub(r"<br\s*/?>|</p>|</li>", "\n", m.group(1), flags=re.I)
    lines = [_strip(x) for x in body.split("\n")]
    txt = " ".join(x for x in lines if x)
    c = CUT.search(txt)
    if c:
        txt = txt[:c.start()]
    return txt.strip()[:600]


SKIP_SENT = re.compile(r"(Tel|TEL|@|Analyst|애널리스트|Compliance|본\s*조사분석|투자의견\s*\(|목표주가\s*\(|현재주가|시가총액|발행주식|52주|외국인\s*(보유|지분)|주요주주|\d{2,3}-\d{3,4}-\d{4}|www\.|http)")


HANGUL = re.compile(r"[가-힣]")


def _join_lines(txt: str) -> str:
    """PDF 줄을 잇는다. 줄 끝/시작에 공백이 있으면 원래 띄어쓰기, 한글-한글로 바로 이어지면
    줄바꿈 때문에 단어가 끊긴 것으로 보고 붙인다 ("재" + "차" → "재차")."""
    out = ""
    for raw in (txt or "").splitlines():
        if not raw.strip():
            if out and not out.endswith(" "):
                out += " "
            continue
        line = re.sub(r"[ \t\u3000]+", " ", raw)
        if not out:
            out = line.lstrip()
            continue
        prev_space = out.endswith(" ") or raw[:1].isspace()
        a, b = out.rstrip()[-1:], line.strip()[:1]
        if not prev_space and HANGUL.match(a or "") and HANGUL.match(b or ""):
            out = out.rstrip() + line.lstrip()           # 끝 공백은 남겨 다음 줄 판단에 씀
        else:
            out = out.rstrip() + " " + line.lstrip()
    return re.sub(r"\s+", " ", out).strip()


def summarize_text(txt: str, max_chars: int = 500) -> str:
    """리포트 1페이지 텍스트에서 핵심 문장만 추린다 (규칙 기반: 한국어 완결 문장, 표·연락처·면책 제외)."""
    joined = _join_lines(txt)
    sents = re.split(r"(?<=[다음함임됨])\.\s+|\s[-•·▶■□◆◇●○*▷►]\s", joined)
    keep: list[str] = []
    for s in sents:
        s = s.strip(" -•·▶■□◆◇●○*▷►")
        if not (25 <= len(s) <= 260) or not re.search(r"[가-힣]{4}", s):
            continue
        if SKIP_SENT.search(s) or s.count(",") > 8 or len(re.findall(r"\d", s)) > len(s) * 0.35:
            continue
        keep.append(s if s.endswith((".", "다", "음", "함", "임", "됨")) else s)
        if sum(len(x) for x in keep) >= max_chars:
            break
    out = ". ".join(x.rstrip(".") for x in keep)
    return (out + ".")[:max_chars] if out else ""


def pdf_summary(url: str) -> str:
    """한경 컨센서스 리포트 PDF 1페이지에서 요약 문장 추출 (파일은 저장하지 않음)."""
    r = requests.get(url, headers={**UA, "Referer": "https://consensus.hankyung.com/"}, timeout=40)
    r.raise_for_status()
    if not r.content[:5].startswith(b"%PDF"):
        return ""
    from io import BytesIO
    from pdfminer.high_level import extract_text  # type: ignore
    return summarize_text(extract_text(BytesIO(r.content), maxpages=1))


def enrich_summaries(rows: list[dict], links: dict[str, str], limit: int = 200) -> int:
    """summary 가 비어 있는 행에 요약을 채운다. 네이버 상세가 있으면 그것, 없으면 한경 PDF 1페이지.
    시도했는데 못 뽑은 건 '-' 로 표시해 다시 받지 않는다 (일시 오류는 None 으로 남겨 재시도)."""
    n = 0
    for r in rows:
        if r.get("summary") not in (None, "") or n >= limit:
            continue
        nv = links.get(r["key"]) or (r["link"] if r.get("source") == "네이버" else None)
        try:
            if nv:
                n += 1
                r["summary"] = parse_summary(_get(nv, "https://finance.naver.com/research/", "euc-kr")) or "-"
            elif r.get("link") and "hankyung" in r["link"]:
                n += 1
                r["summary"] = pdf_summary(r["link"]) or "-"
            else:
                r["summary"] = "-"
        except Exception as e:  # noqa: BLE001
            log.debug("요약 실패 %s: %s", r.get("link"), e)
            r["summary"] = None
        time.sleep(0.3)
    return n


def enrich_naver(rows: list[dict], limit: int = 400) -> None:
    """상세 페이지에서 목표가·투자의견 보강 (상한 limit건)."""
    n = 0
    for r in rows:
        if r["source"] != "네이버" or r.get("target") or n >= limit:
            continue
        n += 1
        try:
            h = _get(r["link"], "https://finance.naver.com/research/", "euc-kr")
        except Exception as e:  # noqa: BLE001
            log.debug("네이버 상세 실패 %s: %s", r["link"], e)
            continue
        t = re.search(r"class=[\"']money[\"'][^>]*>\s*(?:<strong>)?\s*([\d,]+)", h)
        o = re.search(r"class=[\"']coment[\"'][^>]*>\s*([^<]+)", h)
        if t:
            r["target"] = _num(t.group(1))
        if o:
            r["opinion"] = o.group(1).strip()
        time.sleep(0.15)
    log.info("네이버 상세 보강 %d건", n)


# ───────────── 한경컨센서스 ─────────────

def fetch_hankyung(since: date, max_pages: int = 10, until: date | None = None) -> list[dict]:
    base = "https://consensus.hankyung.com"
    today = until or datetime.now(KST).date()
    out = []
    for p in range(1, max_pages + 1):
        url = (f"{base}/analysis/list?sdate={since}&edate={today}&report_type=CO"
               f"&order_type=&pagenum=80&now_page={p}")
        h = _get(url, base + "/")
        rows = re.split(r"<tr[\s>]", h, flags=re.I)[1:]
        found = 0
        for row in rows:
            tds = re.findall(r"<td[^>]*>([\s\S]*?)</td>", row, flags=re.I)
            if len(tds) < 6:
                continue
            dm = re.search(r"\d{4}-\d{2}-\d{2}", _strip(tds[0]))
            if not dm:
                continue
            strong = re.search(r"<strong[^>]*>([\s\S]*?)</strong>", tds[1], flags=re.I)
            tt = _strip(strong.group(1) if strong else tds[1])
            m = re.match(r"^(.+?)\s*\((\d{6})\)\s*(.*)$", tt)
            if not m:
                continue
            href = re.search(r"href=[\"']([^\"']*report_idx=\d+[^\"']*)[\"']", row, flags=re.I)
            link = ""
            if href:
                link = href.group(1) if href.group(1).startswith("http") else base + "/" + href.group(1).lstrip("/")
            found += 1
            out.append({
                "date": date.fromisoformat(dm.group(0)), "source": "한경", "code": m.group(2),
                "name": m.group(1).strip(), "title": m.group(3).strip() or tt,
                "broker": _strip(tds[5]), "opinion": _strip(tds[3]) or None, "target": _num(_strip(tds[2])),
                "link": link, "analyst": _strip(tds[4]) or None,
            })
        if found < 80:
            break
        time.sleep(0.3)
    return out


# ───────────── 저장소 ─────────────

def load_store() -> pl.DataFrame:
    if not STORE.exists():
        return pl.DataFrame(schema=SCHEMA)
    df = pl.read_parquet(STORE)
    for c, t in SCHEMA.items():
        if c not in df.columns:
            df = df.with_columns(pl.lit(None, dtype=t).alias(c))
    return df.select(list(SCHEMA))


def update_store(backfill_days: int = 20, overlap_days: int = 2) -> tuple[pl.DataFrame, pl.DataFrame]:
    """증분 수집. 반환: (전체 저장소, 이번에 새로 추가된 행)."""
    store = load_store()
    today = datetime.now(KST).date()
    since = (store["date"].max() - timedelta(days=overlap_days)) if len(store) else today - timedelta(days=backfill_days)
    existing = set(store["key"].to_list()) if len(store) else set()

    hk, nv = [], []
    try:
        hk = fetch_hankyung(since)
        log.info("한경 %d건", len(hk))
    except Exception as e:  # noqa: BLE001
        log.warning("한경 수집 실패: %s", e)
    try:
        nv = fetch_naver(since)
        log.info("네이버 %d건", len(nv))
    except Exception as e:  # noqa: BLE001
        log.warning("네이버 수집 실패: %s", e)
    if not hk and not nv:
        raise RuntimeError("리포트 수집 0건 — 두 사이트 모두 실패")

    fresh, seen = [], set(existing)
    for r in hk + nv:  # 한경 우선
        k = make_key(r["date"], r["code"], r["broker"])
        if k in seen:
            continue
        seen.add(k)
        r["key"] = k
        fresh.append(r)
    enrich_naver(fresh)
    nv_links = {make_key(r["date"], r["code"], r["broker"]): r["link"] for r in nv}   # 한경 우선이어도 요약은 네이버에서
    for r in fresh:
        r.setdefault("summary", None)
    n_sum = enrich_summaries(fresh, nv_links)
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    for r in fresh:
        r["collected_at"] = now
    new = pl.DataFrame(fresh, schema=SCHEMA) if fresh else pl.DataFrame(schema=SCHEMA)
    store = pl.concat([store, new]).unique("key", keep="first").sort("date", "code")
    # 기존 저장분 중 요약이 비어 있는 최근 30일치 보충 (한 번 시도해 없으면 '' 로 표시)
    try:
        cut = today - timedelta(days=30)
        miss = store.filter((pl.col("date") >= cut) & (pl.col("summary").is_null() | (pl.col("summary") == "")))
        if len(miss):
            more = fetch_naver(cut) if cut < since else []
            links = {**nv_links, **{make_key(r["date"], r["code"], r["broker"]): r["link"] for r in more}}
            rows = miss.to_dicts()
            n_sum += enrich_summaries(rows, links)
            fill = pl.DataFrame(rows, schema=SCHEMA).select("key", pl.col("summary").alias("_s"))
            store = (store.join(fill, on="key", how="left")
                          .with_columns(pl.when(pl.col("_s").is_not_null()).then(pl.col("_s"))
                                          .otherwise(pl.col("summary")).alias("summary")).drop("_s"))
    except Exception as e:  # noqa: BLE001
        log.warning("요약 보충 실패: %s", e)
    log.info("리포트 요약 %d건 수집", n_sum)
    DATA_DIR.mkdir(exist_ok=True)
    store.write_parquet(STORE)
    log.info("리포트 저장소 %d건 (신규 %d)", len(store), len(new))
    return store, new


# ───────────── 분석 ─────────────

def _support(px: pl.DataFrame) -> pl.DataFrame:
    """종목별 최근 20영업일 저가 최저 (손절 기준선)."""
    return (px.sort("yf", "date").group_by("yf").tail(20)
              .group_by("yf").agg(pl.col("low").min().alias("support20"))
              .with_columns(pl.col("yf").str.slice(0, 6).alias("code")).drop("yf"))


def revisions(store: pl.DataFrame) -> pl.DataFrame:
    """같은 종목·같은 증권사 직전 리포트 대비 목표가 변화율·의견 변화."""
    if store.is_empty():
        return store.with_columns(pl.lit(None, pl.Float64).alias("tp_chg"), pl.lit(None, pl.Int8).alias("op_chg"))
    s = store.with_columns(
        pl.col("broker").map_elements(_norm_broker, return_dtype=pl.Utf8).alias("_b"),
        pl.col("opinion").map_elements(opinion_rank, return_dtype=pl.Int8).alias("op_rank"),
    ).sort("code", "_b", "date")
    s = s.with_columns(
        pl.col("target").shift(1).over("code", "_b").alias("prev_target"),
        pl.col("op_rank").shift(1).over("code", "_b").alias("prev_op_rank"),
    ).with_columns(
        (pl.col("target") / pl.col("prev_target") - 1).alias("tp_chg"),
        pl.when((pl.col("op_rank") >= 0) & (pl.col("prev_op_rank") >= 0))
          .then(pl.col("op_rank") - pl.col("prev_op_rank")).otherwise(None).cast(pl.Int8).alias("op_chg"),
    )
    return s.drop("_b")


def attach_latest(last: pl.DataFrame, store: pl.DataFrame, px: pl.DataFrame, days: int = 90) -> pl.DataFrame:
    """last(스크리너 최신행)에 리포트 컨텍스트 컬럼 추가."""
    cols = {"rp_n30": pl.UInt32, "rp_brokers30": pl.UInt32, "rp_last_date": pl.Date, "rp_last_broker": pl.Utf8,
            "rp_last_opinion": pl.Utf8, "rp_last_title": pl.Utf8, "rp_last_link": pl.Utf8,
            "consensus_tp": pl.Float64, "tp_upside": pl.Float64, "support20": pl.Float64, "rr": pl.Float64}
    if store.is_empty():
        return last.with_columns(*[pl.lit(None, t).alias(c) for c, t in cols.items()])
    asof = last["date"].max()
    recent = store.filter(pl.col("date") >= asof - timedelta(days=days))
    # 컨센서스 목표가 = 증권사별 최신 목표가의 중앙값
    tp = (recent.filter(pl.col("target").is_not_null())
                .with_columns(pl.col("broker").map_elements(_norm_broker, return_dtype=pl.Utf8).alias("_b"))
                .sort("date").group_by("code", "_b").last()
                .group_by("code").agg(pl.col("target").median().alias("consensus_tp")))
    r30 = recent.filter(pl.col("date") >= asof - timedelta(days=30))
    cnt = r30.group_by("code").agg(pl.len().cast(pl.UInt32).alias("rp_n30"),
                                    pl.col("broker").n_unique().cast(pl.UInt32).alias("rp_brokers30"))
    lastrep = (recent.sort("date").group_by("code").last()
                     .select("code", pl.col("date").alias("rp_last_date"), pl.col("broker").alias("rp_last_broker"),
                             pl.col("opinion").alias("rp_last_opinion"), pl.col("title").alias("rp_last_title"),
                             pl.col("link").alias("rp_last_link")))
    out = (last.join(lastrep, left_on="symbol", right_on="code", how="left")
               .join(cnt, left_on="symbol", right_on="code", how="left")
               .join(tp, left_on="symbol", right_on="code", how="left")
               .join(_support(px), left_on="symbol", right_on="code", how="left"))
    return out.with_columns(
        (pl.col("consensus_tp") / pl.col("close") - 1).alias("tp_upside"),
        pl.when(pl.col("close") > pl.col("support20"))
          .then((pl.col("consensus_tp") - pl.col("close")) / (pl.col("close") - pl.col("support20")))
          .otherwise(None).round(1).alias("rr"),
    )


def crowding(store: pl.DataFrame, asof: date, days: int = 7, min_brokers: int = 3) -> pl.DataFrame:
    """최근 days일 다수 증권사 커버 또는 목표가 상향 2건 이상."""
    if store.is_empty():
        return pl.DataFrame()
    rv = revisions(store).filter(pl.col("date") >= asof - timedelta(days=days))
    return (rv.group_by("code").agg(
                pl.col("name").last(), pl.col("broker").n_unique().alias("brokers"),
                (pl.col("tp_chg") > 0.001).sum().alias("tp_up"), (pl.col("tp_chg") < -0.001).sum().alias("tp_down"),
                (pl.col("op_chg") > 0).sum().alias("op_up"), (pl.col("op_chg") < 0).sum().alias("op_down"))
              .filter((pl.col("brokers") >= min_brokers) | (pl.col("tp_up") >= 2) | (pl.col("op_up") >= 1))
              .sort(["brokers", "tp_up"], descending=True))


def post_performance(store: pl.DataFrame, px: pl.DataFrame, horizons=(5, 20, 60)) -> pl.DataFrame:
    """리포트 발간일(또는 직후 첫 거래일) 종가 기준 +h 영업일 수익률과 시장 중앙값 대비 초과수익."""
    if store.is_empty():
        return pl.DataFrame()
    p = px.with_columns(pl.col("yf").str.slice(0, 6).alias("code")).sort("code", "date")
    p = p.with_columns(pl.int_range(pl.len()).over("code").alias("i"))
    # 시장 벤치마크: 날짜별 전종목 일간수익률 중앙값 → 누적지수
    mkt = (p.with_columns((pl.col("close") / pl.col("close").shift(1).over("code") - 1).alias("r"))
             .group_by("date").agg(pl.col("r").median()).sort("date")
             .with_columns((1 + pl.col("r").fill_null(0)).cum_prod().alias("mkt_idx")))
    p = p.join(mkt.select("date", "mkt_idx"), on="date", how="left")
    # 발간일 이상 첫 거래일 찾기
    rep = store.select("key", "date", "code", "broker", "opinion", "target").sort("date")
    base = rep.join_asof(p.select("code", "date", "close", "i", "mkt_idx").sort("date").rename({"date": "d0"}),
                         left_on="date", right_on="d0", by="code", strategy="forward")
    base = base.filter(pl.col("i").is_not_null())
    out = base
    for h in horizons:
        fut = p.select("code", (pl.col("i") - h).alias("i"), pl.col("close").alias(f"c{h}"), pl.col("mkt_idx").alias(f"m{h}"))
        out = out.join(fut, on=["code", "i"], how="left").with_columns(
            (pl.col(f"c{h}") / pl.col("close") - 1).alias(f"ret{h}"),
            (pl.col(f"c{h}") / pl.col("close") - pl.col(f"m{h}") / pl.col("mkt_idx")).alias(f"exc{h}"),
        ).drop(f"c{h}", f"m{h}")
    return out


def broker_stats(perf: pl.DataFrame, horizon: int = 20, min_n: int = 15) -> pl.DataFrame:
    """증권사별 '매수' 리포트의 +h일 초과수익 평균·적중률(초과수익>0 비율)."""
    if perf.is_empty() or f"exc{horizon}" not in perf.columns:
        return pl.DataFrame()
    x = (perf.filter(pl.col(f"exc{horizon}").is_not_null())
             .with_columns(pl.col("opinion").map_elements(opinion_rank, return_dtype=pl.Int8).alias("op"))
             .filter(pl.col("op") == 2))
    return (x.group_by("broker").agg(
                pl.len().alias("n"), pl.col(f"exc{horizon}").mean().alias("avg_exc"),
                (pl.col(f"exc{horizon}") > 0).mean().alias("hit"))
              .filter(pl.col("n") >= min_n).sort("avg_exc", descending=True))


# ───────────── 리포트 구조화 (규칙 기반, 센터장 보고 형식) ─────────────

POS_KW = re.compile(r"상회|상향|개선|증가|확대|성장|호조|서프라이즈|최대|반등|회복|수혜|강세|턴어라운드|가속")
NEG_KW = re.compile(r"하회|하향|부진|감소|축소|둔화|우려|부담|약세|적자|리스크|하락|불확실|지연|역성장|감익")
RISK_KW = re.compile(r"리스크|우려|부담|불확실|하회|하향|둔화|지연|변수|경쟁\s*심화|규제")
EVID_KW = re.compile(r"영업이익|매출|EPS|순이익|컨센서스|추정|전망|성장률|마진|OPM|YoY|QoQ|가이던스|수주|출하|판가|ASP")
METHOD = re.compile(r"(SOTP|DCF|RIM|EV\s*/\s*EBITDA|Target\s*P\s*/?\s*E|P\s*/\s*E|PER|P\s*/\s*B|PBR)[^.]{0,60}?(\d+(?:\.\d+)?\s*(?:배|x|X))?", re.I)


def _sents(txt: str) -> list[str]:
    return [x.strip() for x in re.split(r"(?<=[다음함임됨])\.\s*|\.\s+(?=[가-힣A-Z0-9])", txt or "") if len(x.strip()) >= 12]


def structure(r: dict, close: float | None = None) -> dict:
    """요약·제목·의견·목표가로 핵심 논지 / 근거 / 리스크 / 밸류 방법 / 톤 을 규칙 기반으로 뽑는다."""
    summ = r.get("summary") or ""
    summ = "" if summ == "-" else summ
    title = (r.get("title") or "").strip()
    sents = _sents(summ)
    evid = [x for x in sents if EVID_KW.search(x) and not RISK_KW.search(x)][:2]
    risk = [x for x in sents if RISK_KW.search(x)][:1]
    m = METHOD.search(summ)
    method = None
    if m:
        method = re.sub(r"\s+", "", m.group(1)).upper().replace("TARGETP/E", "Target P/E")
        if m.group(2):
            method += " " + m.group(2).replace(" ", "")
    text = title + " " + summ
    pos, neg = len(POS_KW.findall(text)), len(NEG_KW.findall(text))
    rank = opinion_rank(r.get("opinion"))
    if re.search(r"없음|Not\s*Rated|^NR$|N/R", r.get("opinion") or "", re.I) or not (r.get("opinion") or "").strip():
        rank = -9   # 투자의견 없음 (IR협의회·스몰캡 커버 등)
    up = (r["target"] / close - 1) if (r.get("target") and close) else None
    tpc = r.get("tp_chg")
    why = []
    if rank == 0:
        tone = "매도"
    elif rank == 2 and tpc is not None and tpc < -0.001:
        tone, _ = "사실상 중립", why.append(f"매수 유지지만 목표가 {tpc*100:+.0f}%")
    elif rank == 2 and up is not None and up < 0.10:
        tone, _ = "사실상 중립", why.append(f"매수지만 여력 {up*100:+.0f}%")
    elif rank == 2 and neg > pos + 1:
        tone, _ = "신중한 매수", why.append("본문에 부정 표현이 더 많음")
    elif rank == 2 and ((tpc or 0) > 0.001 or pos >= neg + 2) and (up is None or up >= 0.15):
        tone = "낙관"
        if tpc and tpc > 0:
            why.append(f"목표가 {tpc*100:+.0f}%")
        if up is not None:
            why.append(f"여력 {up*100:+.0f}%")
    elif rank == 1:
        tone = "중립"
    elif rank == -9:
        tone = "의견 없음"
    else:
        tone = "긍정(유지)" if rank == 2 else "의견 없음"
    return {"thesis": title, "evidence": evid, "risk": risk[0] if risk else None, "method": method,
            "tone": tone, "tone_why": " · ".join(why) if why else None}


def backfill_hankyung(years: int = 2, window_days: int = 20) -> int:
    """한경 컨센서스 과거 리포트를 기간 창 단위로 받아 저장소에 합친다 (요약 없이 메타데이터만).
    이미 있는 키는 애널리스트 이름만 보충. 한 번 끝나면 store_min ≤ 시작일이라 다시 돌지 않는다."""
    store = load_store()
    today = datetime.now(KST).date()
    start = today - timedelta(days=365 * years)
    if len(store) and store["date"].min() <= start + timedelta(days=7) and store["analyst"].null_count() < len(store) * 0.2:
        log.info("과거 리포트 백필 이미 완료")
        return 0
    rows: list[dict] = []
    d = start
    while d < today:
        e = min(d + timedelta(days=window_days), today)
        try:
            got = fetch_hankyung(d, max_pages=40, until=e)
            rows += got
            log.info("한경 백필 %s~%s %d건", d, e, len(got))
        except Exception as ex:  # noqa: BLE001
            log.warning("한경 백필 %s 실패: %s", d, ex)
        d = e + timedelta(days=1)
        time.sleep(0.5)
    if not rows:
        return 0
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    for r in rows:
        r["key"] = make_key(r["date"], r["code"], r["broker"])
        r.setdefault("summary", "-" if r["date"] < today - timedelta(days=30) else None)
        r["collected_at"] = "backfill " + now
    new = pl.DataFrame(rows, schema=SCHEMA).unique("key", keep="first")
    # 기존 행의 애널리스트 보충
    an = new.select("key", pl.col("analyst").alias("_a"))
    store = (store.join(an, on="key", how="left")
                  .with_columns(pl.coalesce("analyst", "_a").alias("analyst")).drop("_a"))
    add = new.filter(~pl.col("key").is_in(store["key"].implode()))
    store = pl.concat([store, add]).unique("key", keep="first").sort("date", "code")
    store.write_parquet(STORE)
    log.info("백필 추가 %d건 · 저장소 %d건", len(add), len(store))
    return len(add)
