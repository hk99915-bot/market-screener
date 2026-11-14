#!/usr/bin/env python3
"""논문 수집 파이프라인 1단계 — 7소스 수집 · 중복 제거 · 결정론 스코어링 · `content/papers/index.json` 갱신.

  python3 scripts/papers_ingest.py                    # 7소스 수집 → index.json 갱신
  python3 scripts/papers_ingest.py --dry-run          # 파일 쓰지 않고 결과 요약만
  python3 scripts/papers_ingest.py --source arxiv --max-new 10
  python3 scripts/papers_ingest.py --index /tmp/index.json    # 시험용 경로

설계 원칙(근거 `market-screener-research/PAPER_RESEARCH_AND_AUTO_UPDATE_PLAN.md` §3-1~§3-4)
- 표준 라이브러리만: urllib + xml.etree + json. requirements.txt 변경 없음.
- 네트워크는 이 스크립트에서만. 점수·중복·폐기는 전부 결정론(LLM 호출 없음).
- 소스 1개 실패는 ::warning + index.json `sources_status` 기록 후 나머지로 진행(fail-open). 조용한 실패 금지.
- 정규화 키: doi → arxiv_id → sha1(제목 영숫자 + 제1저자 성). 재실행 멱등(같은 키는 새로 넣지 않는다).
- 철회·정정은 1급: 제목·주석·Crossref retraction 신호가 있으면 총점을 −100 이하로 고정하고 status=rejected(즉시 폐기).
- 규칙은 `content/papers/triage_rules.json`(version 고정·사전등록). 점수·사유·규칙 버전을 항목마다 남긴다.
종료 코드: 성공 소스 0곳 1, 그 밖 0.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
import time
import unicodedata
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SOURCES_PATH = ROOT / "content" / "papers" / "sources.json"
RULES_PATH = ROOT / "content" / "papers" / "triage_rules.json"
INDEX_PATH = ROOT / "content" / "papers" / "index.json"
KST = timezone(timedelta(hours=9))
SCHEMA_VERSION = 1
REJECTED, HOLD, SUMMARIZE = "rejected", "hold", "summarize"
ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV_NS = "{http://arxiv.org/schemas/atom}"


# ── 공통 ────────────────────────────────────────────────────────────
class FetchError(RuntimeError):
    """소스 접속 실패(재시도 후). 소스 단위로 잡아 ::warning 으로 남긴다."""


def load_json(path: Path, default=None):
    p = Path(path)
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8"))


def clean_ws(s: str | None) -> str:
    return re.sub(r"\s+", " ", html.unescape(s or "")).strip()


TAG_RE = re.compile(r"<[^>]+>")


def strip_tags(s: str | None) -> str:
    return clean_ws(TAG_RE.sub(" ", s or ""))


def http_get(url: str, *, timeout: int = 40, retries: int = 2, pause: float = 2.5,
             headers: dict | None = None) -> str:
    """GET → 텍스트. 재시도는 지수 backoff(Crossref 429 대응). 실패는 FetchError."""
    hdrs = {"User-Agent": "market-screener-papers/1.0", "Accept": "*/*"}
    hdrs.update(headers or {})
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
            return raw.decode("utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001 — 소스별 실패를 모아 ::warning 으로 남긴다
            last = exc
            if attempt < retries:
                time.sleep(pause * (2 ** attempt))
    raise FetchError(f"{type(last).__name__}: {last}")


def now_kst() -> datetime:
    return datetime.now(KST).replace(microsecond=0)


# ── 정규화 키 · 철회 판정 ────────────────────────────────────────────
def surname_of(author: str) -> str:
    a = clean_ws(author)
    if not a:
        return ""
    if " " in a:
        return a.split()[-1]
    return a  # 한국·중국식 표기(공백 없음)는 전체를 성씨 자리로


def make_key(title: str, authors: list[str], doi: str | None = None,
             arxiv_id: str | None = None) -> str:
    if doi:
        return "doi:" + doi.lower().strip()
    if arxiv_id:
        return "arxiv:" + arxiv_id.strip()
    # 제목 영숫자만(한글·유니코드 포함) + 제1저자 성 — 한글 제목도 서로 구분되어야 한다(ASCII 만 남기면 전부 같은 키가 된다).
    norm = re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", title or "").lower())
    return "sha1:" + hashlib.sha1((norm + "|" + surname_of(authors[0] if authors else "").lower()).encode()).hexdigest()


def withdraw_signal(title: str, note: str, rules: dict, hint: bool = False) -> str | None:
    """철회·정정 신호. 제목과 소스 주석(comment·journal_ref)만 본다 — 초록의 'retraction' 언급은 오탐이 많다."""
    if hint:
        return "crossref retraction/withdrawal 표지"
    text = f"{title or ''} {note or ''}".lower()
    for term in rules.get("withdraw_terms", []):
        if term in text:
            return f"'{term}' 표기"
    return None


# ── 파서 (텍스트 → 원시 항목. 네트워크 없음 — 테스트가 고정 픽스처로 부른다) ──
def parse_atom(text: str, source: dict) -> list[dict]:
    root = ET.fromstring(text)
    out = []
    for e in root.findall(f"{ATOM}entry"):
        link = ""
        for ln in e.findall(f"{ATOM}link"):
            if ln.get("rel") in (None, "alternate"):
                link = ln.get("href") or link
        ident = e.findtext(f"{ATOM}id") or ""
        aid = ""
        m = re.search(r"abs/([^/\s]+?)(?:v\d+)?$", ident.strip())
        if m:
            aid = m.group(1)
        doi = e.findtext(f"{ARXIV_NS}doi")
        comment = e.findtext(f"{ARXIV_NS}comment") or ""
        journal = e.findtext(f"{ARXIV_NS}journal_ref") or ""
        cats = [c.get("term") for c in e.findall(f"{ATOM}category") if c.get("term")]
        out.append({
            "title": clean_ws(e.findtext(f"{ATOM}title")),
            "url": link or ident,
            "authors": [clean_ws(a.findtext(f"{ATOM}name")) for a in e.findall(f"{ATOM}author")],
            "abstract": clean_ws(e.findtext(f"{ATOM}summary")),
            "published_at": (e.findtext(f"{ATOM}published") or "")[:10] or None,
            "year": int((e.findtext(f"{ATOM}published") or "0")[:4] or 0) or None,
            "doi": clean_ws(doi) or None,
            "arxiv_id": aid or None,
            "venue": source.get("venue") or "arXiv",
            "note": " ".join(x for x in (comment, journal) if x),
            "categories": cats,
            "withdraw_hint": False,
        })
    return out


def _rss_channel(text: str):
    root = ET.fromstring(text.lstrip("\ufeff"))
    ch = root.find("channel")
    if ch is None:
        raise ValueError("RSS channel 없음")
    return ch


def _rss_items(ch) -> list[dict]:
    out = []
    for it in ch.findall("item"):
        out.append({
            "title": clean_ws(it.findtext("title")),
            "url": clean_ws(it.findtext("link")),
            "raw_desc": it.findtext("description") or "",
            "pub": clean_ws(it.findtext("pubDate") or it.findtext("{http://purl.org/dc/elements/1.1/}date")),
        })
    return out


def _pub_to_date(pub: str) -> str | None:
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            return datetime.strptime(pub.strip(), fmt).date().isoformat()
        except (ValueError, TypeError):
            continue
    return None


def parse_rss(text: str, source: dict) -> list[dict]:
    """일반 RSS(한국은행 계열). 초록은 첨부파일 안내뿐일 수 있다."""
    ch = _rss_channel(text)
    venue = source.get("venue") or clean_ws(ch.findtext("title"))
    out = []
    for it in _rss_items(ch):
        if not it["title"]:
            continue
        published = _pub_to_date(it["pub"])
        out.append({
            "title": it["title"], "url": it["url"], "authors": [],
            "abstract": strip_tags(it["raw_desc"]), "published_at": published,
            "year": int(published[:4]) if published else None,
            "doi": None, "arxiv_id": None, "venue": venue, "note": "", "withdraw_hint": False,
        })
    return out


def parse_rss_nber(text: str, source: dict) -> list[dict]:
    """NBER: 제목이 'Title -- by 저자1, 저자2' 형태."""
    ch = _rss_channel(text)
    out = []
    for it in _rss_items(ch):
        title, authors = it["title"], []
        m = re.split(r"\s+--\s+by\s+", title, maxsplit=1, flags=re.I)
        if len(m) == 2:
            title = clean_ws(m[0])
            authors = [a.strip() for a in re.split(r",|\band\b", m[1]) if a.strip()]
        m_id = re.search(r"/papers/(w\d+)", it["url"])
        wp = m_id.group(1) if m_id else ""
        published = _pub_to_date(it["pub"])
        out.append({
            "title": title, "url": it["url"], "authors": authors,
            "abstract": strip_tags(it["raw_desc"]), "published_at": published,
            "year": int(published[:4]) if published else None,
            "doi": None, "arxiv_id": None,   # NBER 번호는 arXiv ID 가 아니다 — venue 에 남긴다(키는 제목해시)
            "venue": (source.get("venue") or "NBER Working Paper") + (f" No.{wp}" if wp else ""),
            "note": "", "withdraw_hint": False,
        })
    return out


def parse_rss_fed(text: str, source: dict) -> list[dict]:
    """FEDS: 제목 접두 'FEDS Paper: ' — description 이 '저자 링크들<br><br>초록'."""
    ch = _rss_channel(text)
    out = []
    for it in _rss_items(ch):
        desc = it["raw_desc"]
        head, sep, body = desc.partition("<br><br>")
        authors = [clean_ws(a) for a in re.findall(r"<a [^>]*>([^<]+)</a>", head if sep else "")]
        title = re.sub(r"^(?:FEDS Paper|FEDS Notes)\s*:\s*", "", it["title"]).strip()
        published = _pub_to_date(it["pub"])
        out.append({
            "title": title, "url": it["url"], "authors": authors,
            "abstract": strip_tags(body if sep else desc), "published_at": published,
            "year": int(published[:4]) if published else None,
            "doi": None, "arxiv_id": None, "venue": source.get("venue") or "FEDS Working Paper",
            "note": "", "withdraw_hint": False,
        })
    return out


def parse_html_repec(text: str, source: dict) -> list[dict]:
    """RePEc/BIS 목록 HTML: '<h3>연도</h3>' 아래 '<LI class=...><B>번호 <A>제목</A></B><BR><I>by</I> 저자 & 저자'."""
    start = text.find('id="content"')
    body = text[start:] if start >= 0 else text
    years = [(m.start(), int(m.group(1))) for m in re.finditer(r"<h3>(\d{4})</h3>", body)]
    out = []
    pat = re.compile(r'(?is)<li class="list-group-item[^"]*">\s*<b>(\d+)\s*<a href="([^"]+)">(.*?)</a></b>\s*<br\s*/?>\s*<i>by</i>(.*?)(?=<li class="list-group-item|\Z)')
    for m in pat.finditer(body):
        number, href, title, tail = m.group(1), m.group(2), strip_tags(m.group(3)), m.group(4)
        authors = [clean_ws(a) for a in re.split(r"\s&\s|,", strip_tags(tail)) if clean_ws(a)]
        year = None
        for pos, y in years:
            if pos < m.start():
                year = y
        url = href if href.startswith("http") else "https://ideas.repec.org" + href
        out.append({
            "title": title, "url": url, "authors": authors[:12], "abstract": "",
            "published_at": None, "year": year,   # RePEc 목록은 연도만 준다 — 날짜를 지어내지 않는다
            "doi": None, "arxiv_id": None,
            "venue": f"{source.get('venue') or 'BIS Working Paper'} No.{number}",
            "note": "", "withdraw_hint": False,
        })
    return out


_KCMI_ROLE = re.compile(r"^(?:선임연구위원|수석연구위원|전문연구위원|객원연구위원|연구위원|선임연구원|책임연구원|원장|부원장|센터장|실장|팀장)\s*")


def parse_html_kcmi(text: str, source: dict) -> list[dict]:
    """자본시장연구원 목록 HTML: '<div class="list" id="rsidx_N">' 블록의 rpt_title·em(저자+날짜)·p.txt(초록)."""
    marks = [(m.start(), m.group(1)) for m in re.finditer(r'<div class="list" id="rsidx_(\d+)"', text)]
    out = []
    for i, (pos, no) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else min(len(text), pos + 6000)
        block = text[pos:end]
        m_title = re.search(r'(?s)<div class="rpt_title">\s*<strong>(.*?)</strong>', block)
        if not m_title:
            continue
        m_em = re.search(r"(?s)<em>(.*?)</em>", block)
        authors, published = [], None
        if m_em:
            em = m_em.group(1)
            m_date = re.search(r"<span>\s*(\d{4})\.(\d{2})\.(\d{2})\s*</span>", em)
            if m_date:
                published = f"{m_date.group(1)}-{m_date.group(2)}-{m_date.group(3)}"
            who = strip_tags(re.sub(r"<span>.*?</span>", "", em))
            for a in re.split(r",|·|ㆍ", who):
                a = _KCMI_ROLE.sub("", clean_ws(a)).strip()
                if a:
                    authors.append(a)
        m_txt = re.search(r'(?s)<p class="txt">(.*?)</p>', block)
        out.append({
            "title": strip_tags(m_title.group(1)), "url": f"https://www.kcmi.re.kr/report/report_view?report_no={no}",
            "authors": authors[:12], "abstract": strip_tags(m_txt.group(1)) if m_txt else "",
            "published_at": published, "year": int(published[:4]) if published else None,
            "doi": None, "arxiv_id": None, "venue": source.get("venue") or "KCMI 보고서",
            "note": "", "withdraw_hint": False,
        })
    return out


def parse_json_crossref(text: str, source: dict) -> list[dict]:
    data = json.loads(text)
    out = []
    for it in (data.get("message") or {}).get("items") or []:
        title = clean_ws(" ".join(it.get("title") or []))
        if not title:
            continue
        authors = []
        for a in it.get("author") or []:
            nm = " ".join(x for x in (a.get("given"), a.get("family")) if x)
            if nm:
                authors.append(clean_ws(nm))
        issued = ((it.get("issued") or {}).get("date-parts") or [[None]])[0]
        year = issued[0] if issued and isinstance(issued[0], int) else None
        published = None
        if year and len(issued) == 3 and all(isinstance(x, int) for x in issued):
            published = f"{issued[0]:04d}-{issued[1]:02d}-{issued[2]:02d}"
        rel = it.get("relation") or {}
        hint = bool(rel.get("is-retracted-by")) or any(
            (u.get("type") or "").lower() in {"retraction", "withdrawal", "removal"}
            for u in (it.get("updated-by") or [])
        )
        out.append({
            "title": title, "url": it.get("URL") or f"https://doi.org/{it.get('DOI')}",
            "authors": authors[:12], "abstract": strip_tags(it.get("abstract") or ""),
            "published_at": published, "year": year,
            "doi": it.get("DOI"), "arxiv_id": None,
            "venue": ((it.get("container-title") or [source.get("venue") or "Crossref"])[0]),
            "note": "", "withdraw_hint": hint,
        })
    return out


PARSERS = {
    "atom": parse_atom,
    "rss": parse_rss,
    "rss_nber": parse_rss_nber,
    "rss_fed": parse_rss_fed,
    "html_repec": parse_html_repec,
    "html_kcmi": parse_html_kcmi,
    "json_crossref": parse_json_crossref,
}


# ── 스코어링 ────────────────────────────────────────────────────────
def best_desk(text: str, desk_map: dict, seeded: list[str] | None = None) -> tuple[str | None, int, list[str]]:
    """키워드 최다 적중 데스크. 동점이면 소스 기본 데스크 순서 → 이름순(결정론)."""
    low = text.lower()
    scores = {}
    for desk, cfg in desk_map.items():
        hit = [k for k in cfg.get("keywords", []) if k.lower() in low]
        scores[desk] = hit
    best = max((len(v) for v in scores.values()), default=0)
    if best == 0:
        return ((seeded or [None])[0], 0, [])
    order = {d: i for i, d in enumerate(seeded or [])}
    cands = sorted([d for d, v in scores.items() if len(v) == best], key=lambda d: (order.get(d, 99), d))
    desk = cands[0]
    return desk, best, scores[desk][:6]


def score_item(item: dict, rules: dict, desk_map: dict) -> tuple[int, str, list[dict], str | None, int]:
    """(score, status, reasons, 배정 데스크, 적중 수). 항상 같은 입력 → 같은 출력."""
    w = rules["weights"]
    text = f"{item.get('title', '')} {item.get('abstract', '')}"
    low = text.lower()
    reasons: list[dict] = []
    score = 0

    desk, hits, matched = best_desk(text, desk_map, item.get("desks") or [])
    cfg = w["desk_fit"]
    pts = cfg["full"] if hits >= cfg["hits_full"] else cfg["mid"] if hits >= cfg["hits_mid"] else cfg["low"] if hits else 0
    score += pts
    reasons.append({"rule": "desk_fit", "points": pts,
                    "why": (f"{desk} 키워드 {hits}개: " + ", ".join(matched)) if hits else "키워드 적중 없음(소스 기본 데스크)"})

    period_re = rules.get("sample_period_re")
    obs_re = rules.get("observations_re")
    spans = []
    for m in re.findall(period_re, text) if period_re else []:
        ys = [int(y) for y in re.findall(r"\d{4}", m if isinstance(m, str) else " ".join(m))]
        if len(ys) == 2:
            spans.append(abs(ys[1] - ys[0]))
    obs = [int(x.replace(",", "")) for x in (re.findall(obs_re, text) if obs_re else [])]
    sc = w["sample"]
    if spans and max(spans) >= sc["min_sample_years"]:
        score += sc["long"]
        reasons.append({"rule": "sample", "points": sc["long"], "why": f"표본 기간 {max(spans)}년"})
    elif obs and max(obs) >= sc["min_observations"]:
        score += sc["long"]
        reasons.append({"rule": "sample", "points": sc["long"], "why": f"관측 {max(obs):,}"})
    elif spans:
        score += sc["short"]
        reasons.append({"rule": "sample", "points": sc["short"], "why": f"표본 기간 {max(spans)}년(<10년)"})
    else:
        reasons.append({"rule": "sample", "points": 0, "why": "표본 기간·관측 수 미기재"})

    oos_hits = [t for t in rules.get("oos_terms", []) if t in low]
    oc = w["oos"]
    op = oc["two_plus"] if len(oos_hits) >= 2 else oc["one"] if oos_hits else 0
    score += op
    reasons.append({"rule": "oos", "points": op,
                    "why": ("OOS·사전등록 표현: " + ", ".join(oos_hits[:4])) if oos_hits else "OOS·사전등록 표현 없음"})

    cost_hits = [t for t in rules.get("cost_terms", []) if t in low]
    cc = w["cost"]
    cp = cc["two_plus"] if len(cost_hits) >= 2 else cc["one"] if cost_hits else 0
    score += cp
    reasons.append({"rule": "cost", "points": cp,
                    "why": ("비용 반영 표현: " + ", ".join(cost_hits[:4])) if cost_hits else "거래비용 미반영(표현 없음)"})

    data_hits = [t for t in rules.get("data_access_terms", []) if t in low]
    dc = w["data_access"]
    dp = dc["two_plus"] if len(data_hits) >= 2 else dc["one"] if data_hits else 0
    score += dp
    reasons.append({"rule": "data_access", "points": dp,
                    "why": ("우리 데이터 접점: " + ", ".join(data_hits[:4])) if data_hits else "우리 데이터 접점 없음"})

    risk_hits = [t for t in rules.get("method_risk_terms", []) if t in low]
    if risk_hits:
        score += w["method_risk"]
        reasons.append({"rule": "method_risk", "points": w["method_risk"], "why": "위험 표현: " + ", ".join(risk_hits[:4])})

    ft = w["fulltext"].get(item.get("fulltext") or "unknown", 0)
    score += ft
    reasons.append({"rule": "fulltext", "points": ft, "why": f"전문 접근성 {item.get('fulltext') or 'unknown'}"})

    status = SUMMARIZE if score >= rules["thresholds"]["summarize"] else HOLD if score >= rules["thresholds"]["hold"] else REJECTED
    if item.get("withdraw_flag"):
        score = min(score + w["withdraw"], w["withdraw"])
        status = REJECTED
        reasons.append({"rule": "withdraw", "points": w["withdraw"],
                        "why": f"철회·정정({item.get('withdraw_reason') or '신호'}) → 즉시 폐기"})
    elif status == REJECTED and item.get("abstract_state") == "missing":
        # 제목만 주는 소스는 '표본·OOS·비용 미기재'가 논문 탓이 아니라 재료 부족이다 — 산식은 그대로 두고 폐기만 보류.
        status = HOLD
        reasons.append({"rule": "abstract_state", "points": 0,
                        "why": "초록 없음 — 텍스트 확보 후 재평가(점수 산식 불변)"})
    return score, status, reasons, desk, hits


def normalize(raw: dict, source: dict, desk_map: dict, rules: dict, stamp: str) -> dict:
    title = clean_ws(raw.get("title"))
    authors = [clean_ws(a) for a in (raw.get("authors") or []) if clean_ws(a)]
    doi = (raw.get("doi") or "").strip().lower() or None
    arxiv_id = (raw.get("arxiv_id") or "").strip() or None
    reason = withdraw_signal(title, raw.get("note") or "", rules, bool(raw.get("withdraw_hint")))
    abstract = (raw.get("abstract") or "").strip()
    item = {
        "key": make_key(title, authors, doi, arxiv_id),
        "source": [source["id"]],
        "primary_source": source["id"],
        "title": title,
        "authors": authors,
        "year": raw.get("year"),
        "venue": raw.get("venue") or source.get("venue"),
        "doi": doi,
        "arxiv_id": arxiv_id,
        "url": raw.get("url") or "",
        "abstract": abstract[:4000],
        "abstract_state": "present" if len(abstract) >= 100 else "missing",
        "published_at": raw.get("published_at"),
        "desks": [d for d in (source.get("desks") or [])],
        "fulltext": source.get("fulltext") or "unknown",
        "fetched_at": stamp,
        "status": None,
        "score": None,
        "reasons": [],
        "withdraw_flag": bool(reason),
        "withdraw_reason": reason,
    }
    score, status, reasons, desk, _hits = score_item(item, rules, desk_map)
    item["score"], item["status"], item["reasons"] = score, status, reasons
    if desk and desk not in item["desks"]:
        item["desks"].insert(0, desk)
    return item


# ── 수집 ────────────────────────────────────────────────────────────
def fetch_source(source: dict, *, fetcher, defaults: dict, since: str) -> tuple[list[dict], dict]:
    """소스 1개 수집 → (원시 항목, 상태). 피드 여러 개면 합치고 피드별 실패를 상태에 남긴다."""
    status = {"ok": True, "items": 0, "new": 0, "error": None, "feeds": {}, "fetched_at": None}
    parser = PARSERS.get(source.get("parser") or "")
    if parser is None:
        status.update(ok=False, error=f"미지원 parser: {source.get('parser')}")
        return [], status
    hdrs = {"User-Agent": defaults.get("user_agent") or "market-screener-papers/1.0"}
    timeout = int(defaults.get("timeout_s") or 40)
    retries = int(defaults.get("retries") or 0)
    pause = float(defaults.get("pause_s") or 2.5)
    feeds = source.get("feeds") or [{"url": source.get("url"), "venue": source.get("venue")}]
    got: list[dict] = []
    errors = []
    for feed in feeds:
        url = (feed.get("url") or "").replace("{since}", since)
        if not url:
            errors.append("url 없음")
            status["feeds"]["(none)"] = {"ok": False, "error": "url 없음", "items": 0}
            continue
        label = feed.get("venue") or source.get("venue") or url
        try:
            text = fetcher(url, timeout=timeout, retries=retries, pause=pause, headers=hdrs)
            cfg = dict(source)
            if feed.get("venue"):
                cfg["venue"] = feed["venue"]
            items = parser(text, cfg)
            got.extend(items)
            status["feeds"][label] = {"ok": True, "items": len(items), "error": None}
        except Exception as exc:  # noqa: BLE001 — 피드 1개 실패는 나머지로 진행
            errors.append(f"{label}: {type(exc).__name__}: {exc}")
            status["feeds"][label] = {"ok": False, "items": 0, "error": f"{type(exc).__name__}: {exc}"}
    cap = int(source.get("max_items") or len(got) or 0)
    got = got[:cap]
    status["items"] = len(got)
    status["fetched_at"] = now_kst().isoformat()
    if errors and not got:
        status.update(ok=False, error="; ".join(errors)[:400])
    elif errors:
        status["error"] = "부분 실패: " + "; ".join(errors)[:300]
    return got, status


# ── index 갱신 ──────────────────────────────────────────────────────
def run(*, sources_path=SOURCES_PATH, rules_path=RULES_PATH, index_path=INDEX_PATH,
        fetcher=None, now: datetime | None = None, max_new: int | None = None,
        only: list[str] | None = None, dry_run: bool = False, log=print) -> dict:
    fetcher = fetcher or http_get
    now = now or now_kst()
    stamp = now.astimezone(KST).isoformat()
    sources_doc = load_json(sources_path)
    rules = load_json(rules_path)
    if not sources_doc or not rules:
        raise SystemExit(f"설정 없음: {sources_path} / {rules_path}")
    desk_map = sources_doc.get("desk_map") or {}
    defaults = sources_doc.get("fetch_defaults") or {}
    since = (now.date() - timedelta(days=30)).isoformat()
    index = load_json(index_path, default=None) or {"schema_version": SCHEMA_VERSION, "rules_version": rules["version"],
                                                    "papers": [], "sources_status": {}, "counts": {}}
    papers = {p["key"]: p for p in index.get("papers") or []}
    limit = int(max_new if max_new is not None else defaults.get("max_new_per_run") or 120)

    wanted = [s for s in (sources_doc.get("sources") or []) if s.get("enabled", True)]
    if only:
        wanted = [s for s in wanted if s["id"] in only]
    statuses: dict[str, dict] = {}
    pending: dict[str, dict] = {}
    added, refreshed, skipped = 0, 0, 0
    for src in wanted:
        raw_items, st = fetch_source(src, fetcher=fetcher, defaults=defaults, since=since)
        if not st["ok"]:
            log(f"::warning::논문 소스 실패 — {src['id']}: {st.get('error')}")
        else:
            log(f"[{src['id']}] {st['items']}건 수집" + (f" ({st['error']})" if st.get("error") else ""))
        for raw in raw_items:
            item = normalize(raw, src, desk_map, rules, stamp)
            key = item["key"]
            if key in papers:
                cur = papers[key]
                if src["id"] not in cur["source"]:
                    cur["source"].append(src["id"])
                    skipped += 1
                if item["withdraw_flag"] and not cur["withdraw_flag"]:
                    cur["withdraw_flag"], cur["withdraw_reason"] = True, item["withdraw_reason"]
                    score, status, reasons, desk, _ = score_item(cur, rules, desk_map)
                    cur.update(score=score, status=status, reasons=reasons + [{"rule": "withdraw_note", "points": 0,
                                                                               "why": f"수집 중 철회 신호 발견: {item['withdraw_reason']}"}])
                    refreshed += 1
                continue
            if key in pending:
                if src["id"] not in pending[key]["source"]:
                    pending[key]["source"].append(src["id"])
                    skipped += 1
                continue
            pending[key] = item
        statuses[src["id"]] = st

    # 신규 상한은 소스 1곳이 독식하지 않게 1차로 공평 배분(share), 남은 자리는 2차로 소스 순서대로 채운다.
    share = max(10, limit // max(1, len(wanted)))
    chosen_keys: list[str] = []
    overflow: list[str] = []
    per_source: dict[str, int] = {}
    for key, item in pending.items():
        sid = item["primary_source"]
        if per_source.get(sid, 0) < share and len(chosen_keys) < limit:
            chosen_keys.append(key)
            per_source[sid] = per_source.get(sid, 0) + 1
        else:
            overflow.append(key)
    for key in overflow:
        if len(chosen_keys) >= limit:
            break
        chosen_keys.append(key)
    for key in chosen_keys[:limit]:
        item = pending[key]
        papers[key] = item
        added += 1
    for src in wanted:
        sid = src["id"]
        if sid in statuses:
            statuses[sid]["new"] = sum(1 for k in chosen_keys if pending[k]["primary_source"] == sid)


    all_papers = [papers[k] for k in sorted(papers)]
    counts = {
        "total": len(all_papers),
        "new_this_run": added,
        "sources_ok": sum(1 for s in statuses.values() if s["ok"]),
        "sources_failed": sum(1 for s in statuses.values() if not s["ok"]),
        "summarize": sum(1 for p in all_papers if p["status"] == SUMMARIZE),
        "hold": sum(1 for p in all_papers if p["status"] == HOLD),
        "rejected": sum(1 for p in all_papers if p["status"] == REJECTED),
        "withdrawn": sum(1 for p in all_papers if p["withdraw_flag"]),
    }
    if not dry_run:
        merged_status = dict(index.get("sources_status") or {})
        merged_status.update(statuses)
        index.update({"schema_version": SCHEMA_VERSION, "rules_version": rules["version"], "updated_at": stamp,
                      "counts": counts, "sources_status": merged_status, "papers": all_papers})
        index_path = Path(index_path)
        index_path.parent.mkdir(parents=True, exist_ok=True)
        index_path.write_text(json.dumps(index, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    summary = {"dry_run": dry_run, "added": added, "duplicates": skipped, "flags_refreshed": refreshed,
               "counts": counts, "sources_status": {k: {"ok": v["ok"], "items": v["items"], "new": v["new"],
                                                        "error": v.get("error")} for k, v in statuses.items()},
               "index": str(index_path)}
    log(json.dumps(summary, ensure_ascii=False))
    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="논문 수집 → content/papers/index.json")
    ap.add_argument("--dry-run", action="store_true", help="index.json 을 쓰지 않고 요약만")
    ap.add_argument("--source", action="append", default=None, help="소스 id 만 수집(반복 가능)")
    ap.add_argument("--max-new", type=int, default=None, help="이번 실행 신규 상한(기본 120)")
    ap.add_argument("--index", default=str(INDEX_PATH))
    ap.add_argument("--sources", default=str(SOURCES_PATH))
    ap.add_argument("--rules", default=str(RULES_PATH))
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    log = (lambda *x, **k: None) if a.quiet else print
    summary = run(sources_path=a.sources, rules_path=a.rules, index_path=a.index, max_new=a.max_new,
                  only=a.source, dry_run=a.dry_run, log=log)
    ok = summary["counts"]["sources_ok"]
    if ok == 0:
        print("::error::논문 소스 0곳 성공 — index.json 갱신 안 함", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
