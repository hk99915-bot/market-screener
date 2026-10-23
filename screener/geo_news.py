"""지정학 뉴스 자동 트래킹 — 데이터 데스크 (10/23 겸이 "지정학은 뉴스트래킹하면 되지않나? 각종 뭐 외신이나 야후파이낸스?").

입력: 공개 RSS(외신 직접 피드 + Google News RSS 검색 + 야후 파이낸스 헤드라인 RSS). 출력: reports/geo_news.json.
reports/views/geopolitics.json 의 8축마다 제목 키워드 매칭 → 최근 7일 헤드라인 최대 5개(제목·매체·시각·링크), 중복 제거.
- 원문 복제 금지: 제목·매체·시각·링크만 저장(본문·요약 저장 안 함). 링크는 깨질 수 있어 화면은 제목·매체·날짜가 본문.
- 자동 수집 = 키워드 매칭일 뿐 해석 아님. 축의 상태·해석(geopolitics.json)은 매크로 데스크가 손으로 쓰고, 이 파일은 그 옆에 '최근 뉴스'로만 붙는다.
- 피드별 성공/실패를 feeds[] 에 남긴다. 전 피드 실패면 이전 파일을 덮지 않고 stale 기록(LOOP '조용한 대체 금지').
실행: write_macro_series 끝(commodities 다음, 15:45·16:20·06:52 일정 편승), 수동 `python -m screener.geo_news`.
"""
from __future__ import annotations

import html
import json
import logging
import re
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

from .config import REPORT_DIR

log = logging.getLogger(__name__)
OUT = REPORT_DIR / "geo_news.json"
AXES_FILE = REPORT_DIR / "views" / "geopolitics.json"
KST = ZoneInfo("Asia/Seoul")
DAYS, PER_AXIS, PER_SRC = 7, 5, 2   # 최근 7일 · 축당 5개 · 같은 매체 최대 2개(한 매체 도배 방지)

# 직접 피드 (2026-10-23 실요청 200 확인). 실패: AP index.rss 403 · CNBC 403 · DW 404 · 로이터 공개 RSS 2020 종료(→ Google News 검색으로 로이터 기사 제목 수집)
FEEDS: list[tuple[str, str]] = [
    ("BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ("BBC Business", "https://feeds.bbci.co.uk/news/business/rss.xml"),
    ("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml"),
    ("The Guardian", "https://www.theguardian.com/world/rss"),
    ("NYT World", "https://rss.nytimes.com/services/xml/rss/nyt/World.xml"),
    ("NPR World", "https://feeds.npr.org/1004/rss.xml"),
    ("Yonhap", "https://en.yna.co.kr/RSS/news.xml"),
    ("gCaptain", "https://gcaptain.com/feed/"),
    ("OilPrice", "https://oilprice.com/rss/main"),
    ("Yahoo Finance", "https://feeds.finance.yahoo.com/rss/2.0/headline?s=CL=F,BZ=F,GC=F,HG=F&region=US&lang=en-US"),
]
GN = "https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"

# 축 id → (제목 매칭 정규식, Google News 검색어). 정규식은 제목에만 건다(검색 결과도 제목이 안 맞으면 버림 — 오탐 축소).
AXES: dict[str, tuple[str, str]] = {
    "hormuz": (r"hormuz|persian gulf|kharg|\biran(ian)?\b|호르무즈|이란",
               '(Hormuz OR Iran OR "Persian Gulf") (oil OR tanker OR navy OR blockade OR talks)'),
    "redsea": (r"red sea|houthis?|bab[\s-]?el[\s-]?mandeb|suez|홍해|후티|수에즈",
               '"Red Sea" OR Houthi OR Houthis OR "Bab el-Mandeb" OR "Suez Canal"'),
    "ruukr": (r"ukrain|kremlin|zelensk|putin|russia.{0,40}(war|ceasefire|truce|peace|gas|sanction|strike|drone)|european gas|\bttf\b|우크라이나|러시아",
              '(Ukraine OR Kremlin OR Zelensky) (ceasefire OR truce OR peace OR gas OR war)'),
    "rare_earth": (r"rare[\s-]?earths?|critical minerals?|gallium|germanium|antimony|graphite.{0,30}export|lithium.{0,30}export|희토류|핵심\s*광물",
                   '"rare earth" OR "rare earths" OR "critical minerals" OR gallium OR germanium export'),
    "chips": (r"(chips?|semiconductors?|asml|nvidia|ai accelerators?|hbm).{0,50}(export|curb|ban|control|restrict|licen[cs]e|china)|"
              r"(export|curb|ban|control|restrict).{0,40}(chips?|semiconductors?|asml|nvidia)|entity list|반도체.{0,10}(수출\s*통제|규제)",
              '(chip OR semiconductor OR Nvidia OR ASML) ("export control" OR "export controls" OR curbs OR ban) China'),
    "taiwan": (r"taiwan strait|taiwan.{0,50}(china|pla|military|drill|invasion|blockade|beijing)|(china|pla|beijing|chinese).{0,50}taiwan|대만\s*해협|양안",
               '"Taiwan Strait" OR (Taiwan PLA drills) OR (China Taiwan military)'),
    "korea": (r"north korea|pyongyang|kim jong[\s-]un|\bdprk\b|\bnk\b.{0,20}missile|북한|한반도|김정은",
              '"North Korea" OR Pyongyang OR "Kim Jong Un"'),
    # 관세는 미 국내 정치 기사가 많아 상대국·품목이 같이 나와야 매칭 (10/23 첫 실행: 치즈·선거 토론 기사 걸러냄)
    "tariff": (r"section 232|trade war|trade (deal|talks|truce)|(tariffs?|duties|levies).{0,60}(china|chinese|korea|japan|\beu\b|europe|steel|alumin|copper|chips?|semiconductor|\bautos?\b|\bcars?\b|metals?|pharma)|"
               r"(china|chinese|korea|japan|\beu\b|europe|steel|alumin|copper|chips?|semiconductor|\bautos?\b|\bcars?\b|metals?).{0,60}(tariffs?|duties|levies)|관세",
               'tariff OR tariffs OR "Section 232" OR "trade deal"'),
}


def _txt(el, tag: str, ns: dict | None = None) -> str:
    x = el.find(tag, ns or {})
    return (x.text or "").strip() if x is not None and x.text else ""


def _when(s: str) -> datetime | None:
    """RFC 822(RSS pubDate) 또는 ISO 8601(Atom) → UTC datetime. 실패 None."""
    s = (s or "").strip()
    if not s:
        return None
    try:
        d = parsedate_to_datetime(s)
    except (TypeError, ValueError, IndexError):
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def _clean(t: str) -> str:
    t = html.unescape(re.sub(r"<!\[CDATA\[|\]\]>|<[^>]+>", "", t or ""))
    return re.sub(r"\s+", " ", t).strip()


def parse_feed(text: str, default_src: str) -> list[dict]:
    """RSS 2.0 / Atom → [{title, src, when(UTC datetime|None), link}]. Google News 는 <source> 를 매체로, 제목 끝 ' - 매체' 를 뗀다.
    XML 이 깨져 있으면 <item> 정규식으로 한 번 더 시도(일부 피드가 잘못된 엔티티를 냄)."""
    out: list[dict] = []
    try:
        root = ET.fromstring(text.encode("utf-8") if isinstance(text, str) else text)
    except ET.ParseError:
        for m in re.finditer(r"<item\b[^>]*>(.*?)</item>", text or "", re.S):
            b = m.group(1)
            g = lambda tag: (re.search(rf"<{tag}\b[^>]*>(.*?)</{tag}>", b, re.S) or [None, ""])[1]  # noqa: E731
            out.append(_row(_clean(g("title")), _clean(g("source")), _clean(g("link")), _when(_clean(g("pubDate"))), default_src))
        return [r for r in out if r]
    atom = "{http://www.w3.org/2005/Atom}"
    items = root.findall(".//item")
    if items:
        for it in items:
            src = it.find("source")
            out.append(_row(_clean(_txt(it, "title")), _clean(src.text if src is not None and src.text else ""),
                            _txt(it, "link"), _when(_txt(it, "pubDate") or _txt(it, "{http://purl.org/dc/elements/1.1/}date")), default_src))
    else:
        for e in root.findall(f".//{atom}entry"):
            ln = e.find(f"{atom}link")
            out.append(_row(_clean(_txt(e, f"{atom}title")), "", ln.get("href", "") if ln is not None else "",
                            _when(_txt(e, f"{atom}published") or _txt(e, f"{atom}updated")), default_src))
    return [r for r in out if r]


def _row(title: str, src: str, link: str, when, default_src: str) -> dict | None:
    if not title:
        return None
    for _ in range(2):   # Google News 는 ' - 매체', 일부 매체는 제목 끝에 ' | 매체' 를 또 붙인다
        for sep in (" - ", " | "):
            if src and title.endswith(sep + src):
                title = title[: -len(src) - len(sep)].rstrip()
    return {"title": title, "src": src or default_src, "when": when, "link": (link or "").strip()}


def norm_key(title: str) -> str:
    """중복 판정 키: 소문자·문장부호 제거·앞 70자. 같은 기사가 직접 피드와 Google News 로 두 번 와도 하나로."""
    t = re.sub(r"[^\w\s]", " ", (title or "").lower())
    return re.sub(r"\s+", " ", t).strip()[:70]


_RX = {k: re.compile(v[0], re.I) for k, v in AXES.items()}


def match_axes(title: str) -> list[str]:
    return [k for k, rx in _RX.items() if rx.search(title or "")]


def assign(items: list[dict], axis_ids: list[str], now: datetime, days: int = DAYS,
           per_axis: int = PER_AXIS, per_src: int = PER_SRC) -> dict[str, list[dict]]:
    """수집 순서(직접 피드 → 검색)대로 중복 제거 후 축별로 최근 days 일·최신순·매체당 per_src·축당 per_axis."""
    cut = now - timedelta(days=days)
    seen: set[str] = set()
    uniq = []
    for r in items:
        k = norm_key(r["title"])
        if not k or k in seen or r.get("when") is None or r["when"] < cut or r["when"] > now + timedelta(hours=1):
            continue
        seen.add(k)
        uniq.append(r)
    uniq.sort(key=lambda r: r["when"], reverse=True)
    res: dict[str, list[dict]] = {a: [] for a in axis_ids}
    cnt: dict[tuple[str, str], int] = {}
    for r in uniq:
        for a in match_axes(r["title"]):
            if a not in res or len(res[a]) >= per_axis or cnt.get((a, r["src"]), 0) >= per_src:
                continue
            cnt[(a, r["src"])] = cnt.get((a, r["src"]), 0) + 1
            res[a].append(r)
    return res


def _fetch(url: str) -> str:
    import requests
    r = requests.get(url, timeout=(10, 20), headers={"User-Agent": "Mozilla/5.0 (market-screener geo_news; +github)"})
    r.raise_for_status()
    t = r.text
    if "<rss" not in t[:2000] and "<feed" not in t[:2000]:
        raise ValueError("RSS 아님(차단·오류 페이지)")
    return t


def build(fetch=None, now: datetime | None = None, sleep=None) -> dict | None:
    """fetch(url) → 응답 텍스트. 기본 requests(+검색 실패 시 3초 뒤 1회 재시도). 전 피드 실패면 쓰지 않고 None."""
    if fetch is None:
        import time
        fetch, sleep = _fetch, sleep or time.sleep
    now = now or datetime.now(timezone.utc)
    try:
        axes = [(a["id"], a["name"]) for a in json.loads(AXES_FILE.read_text(encoding="utf-8")).get("axes", [])]
    except Exception as e:  # noqa: BLE001
        log.warning("지정학 축 파일 읽기 실패: %s", e)
        axes = [(k, k) for k in AXES]
    urls = [(n, u, "직접") for n, u in FEEDS] + [
        (f"Google News: {a}", GN.format(q=urllib.parse.quote(AXES[a][1] + f" when:{DAYS}d")), "검색") for a, _ in axes if a in AXES]
    items, feeds = [], []
    for name, url, kind in urls:
        try:
            try:
                text = fetch(url)
            except Exception:  # noqa: BLE001 — Google News 는 연속 호출 때 간헐 503(10/23 실측) → 한 번만 쉬고 재시도
                if kind != "검색" or sleep is None:
                    raise
                sleep(3)
                text = fetch(url)
            rows = parse_feed(text, name.split(":")[0] if kind == "직접" else "Google News")
            items += rows
            feeds.append({"name": name, "kind": kind, "ok": True, "n": len(rows)})
        except Exception as e:  # noqa: BLE001 — 피드 하나 실패는 기록만, 나머지는 계속
            feeds.append({"name": name, "kind": kind, "ok": False, "err": str(e)[:120]})
    ok = sum(f["ok"] for f in feeds)
    if not ok:
        from .guard import record_stale
        log.warning("지정학 뉴스: 전 피드 실패 — 이전 파일 유지")
        record_stale("reports/geo_news.json", "전 피드 실패", now.astimezone(KST).date().isoformat(), None)
        return None
    res = assign(items, [a for a, _ in axes], now)
    fmt = lambda d: d.astimezone(KST).strftime("%Y-%m-%d %H:%M")  # noqa: E731
    out = {
        "asof": now.astimezone(KST).date().isoformat(),
        "generated_at": now.astimezone(KST).strftime("%Y-%m-%d %H:%M KST"),
        "window_days": DAYS,
        "axes": [{"id": a, "name": n, "items": [{"title": r["title"], "src": r["src"], "time": fmt(r["when"]), "link": r["link"]}
                                                for r in res.get(a, [])]} for a, n in axes],
        "feeds": feeds,
        "label": "자동 수집 헤드라인 — 제목 키워드 매칭일 뿐 데스크 해석 아님 · 원문 미대조(검증전) · 링크는 깨질 수 있음",
        "method": f"공개 RSS {ok}/{len(feeds)}개 성공 · 축별 제목 정규식(screener/geo_news.py AXES) · 최근 {DAYS}일 · 축당 {PER_AXIS}개 · 같은 매체 {PER_SRC}개까지 · 제목 정규화 중복 제거",
    }
    from .guard import write_json
    write_json(OUT, out)
    log.info("지정학 뉴스 %s", " · ".join(f"{a['id']} {len(a['items'])}" for a in out["axes"]))
    return out


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    build()
