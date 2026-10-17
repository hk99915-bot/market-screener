"""행동주의 운용사 트래킹 (애널 데스크, 2026-10-17) → reports/activist.json

입력 (새 수집기를 만들지 않고 재사용)
- 한국: data/dart.parquet (screener/dart.py 가 이미 모으는 '지분 5%' = 대량보유상황보고서, 화면에서는 숨김).
  * 명단 매칭: 제출인(filer)이 docs/desk_kb/activists.json KR 별칭과 부분일치.
  * 서식: '(일반)' 서식은 경영참가 목적이면 필수(전문투자자의 단순·일반투자는 '(약식)'). 개인도 일반 서식을 쓰므로 필요조건일 뿐.
  * 보유목적 확인(키 있을 때만): OpenDART document.xml 원문에서 '보유목적' 뒤 문구 → 경영참가/일반투자/단순투자.
  * 지분율(키 있을 때만): OpenDART majorstock.json (대량보유 상황보고, stkrt).
- 미국: SEC EDGAR 일별 master index (daily-index/master.YYYYMMDD.idx) 의 13D 행. 한 접수번호에 제출인·대상회사가 같이 찍히므로
  명단(CIK 또는 이름) 쪽을 제출인, 나머지를 대상회사로 본다. 13G(수동)는 보지 않는다. 지분율은 제출 원문의 percentOfClass/Row 13.
- 가격: KR = screener.prices.load_kr(조정), US = data/hist/us_daily.parquet(adj_close).

수익률 = 공시일 **전 거래일 종가** 기준 → 공시일(d0)·+5·+20·+60 거래일 종가 (원 수익률, 비용·벤치마크 차감 전, 검증전).
캠페인 판정
- KR: 명단 매칭 + (보유목적 경영참가 또는 보유목적 미확인인 '(일반)' 서식) → campaign. 명단 + 약식 → 'holding'(캠페인 아님).
       명단 밖 + 보유목적 경영참가 확인 → campaign(명단 밖). 명단 밖 '(일반)' 은 개수만 센다(개인·지주사 내부 보고가 대부분).
- US: 명단 매칭 13D 원본 → campaign, 13D/A → amend.
event 플래그 = 대상이 우리 유니버스(kr.csv · us_top/us_priority) 또는 관심 목록(universe/us_watch.csv + 환경변수 ACTIVIST_WATCH,
쉼표 구분 종목코드/티커 — 비공개 목록은 이름만, 금액·수량 없음)에 있으면 True. 알림·텔레그램 발송 없음(전체 무음).

  python -m screener.activist            # DART 저장분 + (SEC_USER_AGENT 있으면) 최근 7일 EDGAR
  python -m screener.activist --days 30
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import os
import re
import time
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl
import requests

from .config import DATA_DIR, REPORT_DIR, UNIVERSE_DIR

log = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")
ROOT = Path(__file__).resolve().parents[1]
ROSTER = ROOT / "docs" / "desk_kb" / "activists.json"
OUT = REPORT_DIR / "activist.json"
KEEP_DAYS = 400
HORIZONS = (0, 5, 20, 60)
US_FORMS = {"SC 13D": "new", "SCHEDULE 13D": "new", "SC 13D/A": "amend", "SCHEDULE 13D/A": "amend"}
PURPOSE_WORDS = [("경영참가", ("경영권영향", "경영참가", "경영권에영향")), ("일반투자", ("일반투자",)), ("단순투자", ("단순투자",))]


# ── 명단 ──────────────────────────────────────────────────────────────────────
def norm(s: str) -> str:
    s = (s or "").upper()
    for x in ("(주)", "㈜", "주식회사", "유한회사"):
        s = s.replace(x, "")
    return re.sub(r"[\s.,'’\-&/()]", "", s)


def load_roster(path: Path = ROSTER) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def match(name: str, entries: list[dict], cik: int | None = None) -> dict | None:
    """제출인 이름(또는 CIK)이 명단 항목과 맞으면 그 항목."""
    n = norm(name)
    for e in entries:
        if cik is not None and e.get("cik") and int(e["cik"]) == int(cik):
            return e
        if n and any(norm(a) in n for a in e.get("aliases", [])):
            return e
    return None


# ── 한국 ──────────────────────────────────────────────────────────────────────
def parse_purpose(text: str) -> str | None:
    """대량보유보고서 원문에서 보유목적. '보유목적' 뒤 300자 안의 첫 키워드 (공백 제거 후)."""
    t = re.sub(r"<[^>]+>", " ", text or "")
    t = re.sub(r"\s+", "", t)
    for m in re.finditer(r"보유목적", t):
        win = t[m.end(): m.end() + 300]
        hits = [(win.find(k), lab) for lab, ks in PURPOSE_WORDS for k in ks if win.find(k) >= 0]
        if hits:
            return min(hits)[1]
    return None


def form_of(title: str) -> str:
    t = (title or "").replace(" ", "")
    return "일반" if "(일반)" in t else "약식" if "(약식)" in t else "?"


def kr_events(dart: pl.DataFrame, roster: list[dict], purposes: dict[str, str] | None = None,
              stakes: dict[str, float] | None = None) -> tuple[list[dict], int]:
    """(이벤트 목록, 명단 밖 '(일반)' 서식 건수). purposes/stakes = {rcept_no: 값} (DART 키 있을 때 채움)."""
    purposes, stakes = purposes or {}, stakes or {}
    if not len(dart):
        return [], 0
    f = dart.filter(pl.col("category") == "지분 5%")
    out, other_general = [], 0
    for r in f.to_dicts():
        e = match(r["filer"], roster)
        form, purpose = form_of(r["title"]), purposes.get(r["rcept_no"])
        if e:
            kind = "campaign" if (purpose == "경영참가" or (purpose is None and form == "일반")) else "holding"
        elif purpose == "경영참가":
            kind = "campaign"
        else:
            other_general += form == "일반"
            continue
        out.append({"id": f"KR-{r['rcept_no']}", "market": "KR", "date": str(r["date"]), "filer": r["filer"],
                    "roster_id": e["id"] if e else None, "roster_verified": bool(e and e.get("verified")),
                    "target": r["name"], "symbol": r["code"], "form": form, "purpose": purpose,
                    "purpose_basis": "원문" if purpose else ("서식 추정(일반=경영참가 필요조건)" if form == "일반" else "미확인"),
                    "stake_pct": stakes.get(r["rcept_no"]), "kind": kind, "amend": r["title"].startswith("["),
                    "link": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={r['rcept_no']}"})
    return out, other_general


def _dart_key() -> str:
    return os.environ.get("DART_API_KEY", "").strip()


def fetch_purpose(rcept_no: str) -> str | None:
    """OpenDART 원문(zip) → 보유목적. 실패 시 None."""
    r = requests.get("https://opendart.fss.or.kr/api/document.xml",
                     params={"crtfc_key": _dart_key(), "rcept_no": rcept_no}, timeout=30)
    r.raise_for_status()
    try:
        z = zipfile.ZipFile(io.BytesIO(r.content))
    except zipfile.BadZipFile:
        return None
    for n in z.namelist():
        raw = z.read(n)
        for enc in ("utf-8", "euc-kr"):
            try:
                p = parse_purpose(raw.decode(enc))
                if p:
                    return p
                break
            except UnicodeDecodeError:
                continue
    return None


def fetch_stakes(corp_code: str) -> dict[str, float]:
    """OpenDART majorstock.json → {rcept_no: 보유비율 %}."""
    r = requests.get("https://opendart.fss.or.kr/api/majorstock.json",
                     params={"crtfc_key": _dart_key(), "corp_code": corp_code}, timeout=30)
    r.raise_for_status()
    out = {}
    for x in r.json().get("list") or []:
        try:
            out[x["rcept_no"]] = float(str(x.get("stkrt", "")).replace(",", ""))
        except (KeyError, ValueError):
            continue
    return out


def enrich_kr(dart: pl.DataFrame, roster: list[dict], budget: int = 40) -> tuple[dict, dict]:
    """키가 있으면 명단 매칭분·'(일반)' 서식(예산 안)의 보유목적과 지분율을 받는다."""
    purposes, stakes = {}, {}
    if not _dart_key() or not len(dart):
        return purposes, stakes
    f = dart.filter(pl.col("category") == "지분 5%")
    rows = f.to_dicts()
    pri = [r for r in rows if match(r["filer"], roster)] + [r for r in rows if not match(r["filer"], roster) and form_of(r["title"]) == "일반"]
    for r in pri[:budget]:
        try:
            p = fetch_purpose(r["rcept_no"])
            if p:
                purposes[r["rcept_no"]] = p
        except Exception as e:  # noqa: BLE001
            log.warning("DART 원문 %s 실패: %s", r["rcept_no"], e)
        time.sleep(0.2)
    cmap = {}
    p = UNIVERSE_DIR / "dart_corp.csv"
    if p.exists():
        cc = pl.read_csv(p, schema_overrides={"code": pl.Utf8, "corp_code": pl.Utf8})
        cmap = dict(zip(cc["code"].to_list(), cc["corp_code"].to_list()))
    want = {r["code"] for r in rows if match(r["filer"], roster) or purposes.get(r["rcept_no"]) == "경영참가"}
    for code in sorted(c for c in want if c in cmap):
        try:
            stakes.update(fetch_stakes(cmap[code]))
        except Exception as e:  # noqa: BLE001
            log.warning("DART 대량보유 %s 실패: %s", code, e)
        time.sleep(0.2)
    return purposes, stakes


# ── 미국 ──────────────────────────────────────────────────────────────────────
def parse_master(text: str) -> list[dict]:
    """EDGAR master.idx (CIK|Company Name|Form Type|Date Filed|Filename) → 13D 행만."""
    out = []
    for ln in (text or "").splitlines():
        p = ln.split("|")
        if len(p) != 5 or not p[0].strip().isdigit():
            continue
        form = p[2].strip()
        if form not in US_FORMS:
            continue
        d = p[3].strip()
        d = f"{d[:4]}-{d[4:6]}-{d[6:]}" if re.fullmatch(r"\d{8}", d) else d
        acc = p[4].strip().rsplit("/", 1)[-1].replace(".txt", "")
        out.append({"cik": int(p[0]), "name": p[1].strip(), "form": form, "date": d, "path": p[4].strip(), "acc": acc})
    return out


def us_events(rows: list[dict], roster: list[dict], cik_ticker: dict[int, str]) -> list[dict]:
    by: dict[str, list[dict]] = {}
    for r in rows:
        by.setdefault(r["acc"], []).append(r)
    out = []
    for acc, g in by.items():
        act = [(r, match(r["name"], roster, r["cik"])) for r in g]
        hit = [(r, e) for r, e in act if e]
        if not hit:
            continue
        filer, e = hit[0]
        others = [r for r, m in act if not m]
        subj = next((r for r in others if r["cik"] in cik_ticker), others[0] if others else None)
        out.append({"id": f"US-{acc}", "market": "US", "date": filer["date"], "filer": filer["name"],
                    "roster_id": e["id"], "roster_verified": bool(e.get("verified")),
                    "target": subj["name"] if subj else None, "symbol": cik_ticker.get(subj["cik"]) if subj else None,
                    "target_cik": subj["cik"] if subj else None, "form": filer["form"], "purpose": None,
                    "purpose_basis": "13D(경영 영향 의도 포함 가능 — Item 4 원문 미분류)", "stake_pct": None,
                    "kind": "campaign" if US_FORMS[filer["form"]] == "new" else "amend", "amend": US_FORMS[filer["form"]] == "amend",
                    "link": f"https://www.sec.gov/Archives/{filer['path']}"})
    return out


def parse_13d_pct(text: str) -> float | None:
    """13D 원문의 지분율: XML(2024-12 이후) percentOfClass, 아니면 표지 Row 13 'PERCENT OF CLASS ...' 뒤 첫 %."""
    m = re.search(r"<(?:\w+:)?percentOfClass>\s*([\d.]+)\s*<", text or "")
    if m:
        return float(m.group(1))
    m = re.search(r"PERCENT\s+OF\s+CLASS\s+REPRESENTED\s+BY\s+AMOUNT\s+IN\s+ROW\s*\(?11\)?.{0,200}?([\d]+(?:\.\d+)?)\s*%",
                  re.sub(r"<[^>]+>", " ", text or ""), re.I | re.S)
    return float(m.group(1)) if m else None


def _sec_get(url: str) -> str:
    ua = os.environ.get("SEC_USER_AGENT", "").strip()
    r = requests.get(url, headers={"User-Agent": ua, "Accept-Encoding": "gzip, deflate"}, timeout=40)
    if r.status_code == 404:
        return ""
    r.raise_for_status()
    time.sleep(0.15)
    return r.text


def fetch_us(days: int, roster: list[dict], cik_ticker: dict[int, str], today: date | None = None) -> list[dict]:
    today = today or datetime.now(KST).date()
    rows = []
    for i in range(1, days + 1):
        d = today - timedelta(days=i)
        if d.weekday() >= 5:
            continue
        q = (d.month - 1) // 3 + 1
        try:
            rows += parse_master(_sec_get(f"https://www.sec.gov/Archives/edgar/daily-index/{d.year}/QTR{q}/master.{d:%Y%m%d}.idx"))
        except Exception as e:  # noqa: BLE001
            log.warning("EDGAR %s 실패: %s", d, e)
    ev = us_events(rows, roster, cik_ticker)
    for x in ev:
        try:
            x["stake_pct"] = parse_13d_pct(_sec_get(x["link"]))
        except Exception as e:  # noqa: BLE001
            log.warning("13D 원문 %s 실패: %s", x["id"], e)
    return ev


# ── 수익률·플래그 ─────────────────────────────────────────────────────────────
def post_returns(px: pl.DataFrame, symbol: str, d: str, horizons=HORIZONS) -> dict:
    """px[sym,date,close]: 공시일 전 거래일 종가 → 공시일 이후 h 거래일 종가 (h=0 은 공시일 당일 종가). 데이터 없으면 None."""
    if not symbol or not len(px):
        return {}
    g = px.filter(pl.col("sym") == symbol).sort("date")
    if not len(g):
        return {}
    dd = date.fromisoformat(d)
    pre = g.filter(pl.col("date") < dd)
    post = g.filter(pl.col("date") >= dd)
    if not len(pre):
        return {}
    base = pre["close"][-1]
    out = {"base_date": str(pre["date"][-1])}
    for h in horizons:
        out[f"d{h}"] = round((post["close"][h] / base - 1) * 100, 2) if len(post) > h and base else None
    return out


def _prices(market: str) -> pl.DataFrame:
    try:
        if market == "KR":
            from .prices import load_kr
            df = load_kr()
            return df.select(pl.col("yf").str.replace(r"\.K[SQ]$", "").alias("sym"), "date", "close")
        p = DATA_DIR / "hist" / "us_daily.parquet"
        df = pl.read_parquet(p)
        c = "adj_close" if "adj_close" in df.columns else "close"
        return df.select(pl.col("symbol").alias("sym"), pl.col("date").cast(pl.Date), pl.col(c).cast(pl.Float64).alias("close"))
    except Exception as e:  # noqa: BLE001
        log.warning("%s 가격 없음: %s", market, e)
        return pl.DataFrame(schema={"sym": pl.Utf8, "date": pl.Date, "close": pl.Float64})


def universe_sets() -> tuple[set[str], set[str]]:
    uni, watch = set(), set()
    for f, col in (("kr.csv", "symbol"), ("us_top.csv", "yf"), ("us_priority.csv", "yf")):
        p = UNIVERSE_DIR / f
        if p.exists():
            uni |= set(pl.read_csv(p, schema_overrides={col: pl.Utf8})[col].drop_nulls().to_list())
    p = UNIVERSE_DIR / "us_watch.csv"
    if p.exists():
        watch |= set(pl.read_csv(p)["yf"].drop_nulls().to_list())
    watch |= {x.strip() for x in os.environ.get("ACTIVIST_WATCH", "").split(",") if x.strip()}
    return uni, watch


def flag(ev: list[dict], uni: set[str], watch: set[str]) -> list[dict]:
    for x in ev:
        s = x.get("symbol")
        x["in_universe"], x["in_watch"] = bool(s and s in uni), bool(s and s in watch)
        x["event"] = x["kind"] == "campaign" and (x["in_universe"] or x["in_watch"])
    return ev


def merge(old: list[dict], new: list[dict], today: date) -> list[dict]:
    """id 기준 누적 (새 값 우선, 단 새 값이 None 인 보유목적·지분율은 옛 값 유지). KEEP_DAYS 넘은 것 버림."""
    m = {x["id"]: x for x in old}
    for x in new:
        o = m.get(x["id"], {})
        for k in ("purpose", "stake_pct"):
            if x.get(k) is None and o.get(k) is not None:
                x[k] = o[k]
        m[x["id"]] = {**o, **x}
    cut = str(today - timedelta(days=KEEP_DAYS))
    return sorted((x for x in m.values() if x["date"] >= cut), key=lambda x: (x["date"], x["id"]), reverse=True)


def build(events: list[dict], roster: dict, other_general: int, notes: list[str], asof: str) -> dict:
    camp = [x for x in events if x["kind"] == "campaign"]
    return {"asof": asof, "grade": "검증전",
            "roster_n": {"KR": len(roster.get("KR", [])), "US": len(roster.get("US", []))},
            "counts": {"campaign": len(camp), "amend": sum(x["kind"] == "amend" for x in events),
                       "holding": sum(x["kind"] == "holding" for x in events), "event": sum(bool(x.get("event")) for x in events),
                       "kr_general_form_unmatched_window": other_general},
            "returns_basis": "공시일 전 거래일 종가 대비 d0(공시일)·d5·d20·d60 거래일 종가, 원 수익률(%) · 비용·벤치마크 차감 전 · 검증전",
            "notes": notes, "events": events}


def run(days: int = 7, out: Path = OUT) -> dict:
    from . import dart
    roster = load_roster()
    now = datetime.now(KST)
    notes = []
    old = []
    if Path(out).exists():
        try:
            old = json.loads(Path(out).read_text(encoding="utf-8")).get("events", [])
        except Exception:  # noqa: BLE001
            old = []
    store = dart.load()
    if len(store):
        store = store.filter(pl.col("date") >= now.date() - timedelta(days=max(days, 7)))
    purposes, stakes = enrich_kr(store, roster["KR"])
    if not _dart_key():
        notes.append("DART_API_KEY 없음 — 보유목적·지분율 원문 확인 생략(서식으로 추정)")
    kr, other_general = kr_events(store, roster["KR"], purposes, stakes)
    us = []
    if os.environ.get("SEC_USER_AGENT", "").strip():
        tm = {}
        p = UNIVERSE_DIR / "sec_tickers.json"
        if p.exists():
            tm = {int(v): k for k, v in json.loads(p.read_text()).items()}
        us = fetch_us(days, roster["US"], tm, now.date())
    else:
        notes.append("SEC_USER_AGENT 없음 — 미국 13D 수집 생략(이전 미국 이벤트 유지)")
        if any(x["market"] == "US" for x in old):
            try:
                from .guard import record_stale
                record_stale(str(out), "activist US 13D", now.strftime("%Y-%m-%d"), "이전 실행분")
            except Exception:  # noqa: BLE001
                pass
    ev = merge(old, kr + us, now.date())
    pxs = {m: _prices(m) for m in ("KR", "US")}
    for x in ev:
        x["returns"] = post_returns(pxs[x["market"]], x.get("symbol"), x["date"])
    uni, watch = universe_sets()
    ev = flag(ev, uni, watch)
    rep = build(ev, roster, other_general, notes, now.strftime("%Y-%m-%d %H:%M KST"))
    try:
        from .guard import write_json
        write_json(Path(out), rep, ensure_ascii=False, indent=1)
    except Exception as e:  # noqa: BLE001
        log.warning("guard.write_json 실패(%s) — 직접 씀", e)
        Path(out).write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    log.info("activist: 캠페인 %d · 수정 %d · 보유 %d · event %d", rep["counts"]["campaign"], rep["counts"]["amend"],
             rep["counts"]["holding"], rep["counts"]["event"])
    return rep


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    a = ap.parse_args()
    run(a.days)
