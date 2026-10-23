"""지정학 뉴스 자동 트래킹 — 데이터 데스크 (10/23 겸이 "지정학은 뉴스트래킹하면 되지않나? 각종 뭐 외신이나 야후파이낸스?").

입력: 공개 RSS(외신 직접 피드 + Google News RSS 검색 + 야후 파이낸스 헤드라인 RSS). 출력: reports/geo_news.json.
reports/views/geopolitics.json 의 8축마다 제목 키워드 매칭 → 최근 7일 헤드라인 최대 5개(제목·매체·시각·링크), 중복 제거.
- 원문 복제 금지: 제목·매체·시각·링크만 저장(본문·요약 저장 안 함). 링크는 깨질 수 있어 화면은 제목·매체·날짜가 본문.
- 자동 수집 = 키워드 매칭일 뿐 해석 아님. 축의 상태·해석(geopolitics.json)은 매크로 데스크가 손으로 쓰고, 이 파일은 그 옆에 '최근 뉴스'로만 붙는다.
- 피드별 성공/실패를 feeds[] 에 남긴다. 전 피드 실패면 이전 파일을 덮지 않고 stale 기록(LOOP '조용한 대체 금지').
- (10/24 피어 G1) 축 단위 stale: 그 축의 Google News 검색이 실패하면 그 축은 직접 피드 매칭으로 새로 채우지 않고 이전 파일 값 유지 + `stale` 표시.
- (10/24 피어 G2) 사건 단위 중복 제거: 축 안에서 같은 링크 대상이거나 제목 단어 유사도(자카드) ≥ EVENT_SIM 이면 같은 사건 → 1칸(직접 피드판 우선).
- (10/24 피어 G3) Google News RSS 는 피드 copyright 원문이 '개인 피드 리더·개인 비상업 용도 외 금지' → 공개 산출물에는 그 항목의
  제목을 싣지 않는다(매체·시각·축·링크만, `title=None`·`title_withheld`). 같은 사건이 직접 피드에도 있으면 직접 피드판을 쓴다. 근거·출처별 약관은 data.md 소스 목록.
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
# Google News RSS <copyright> 원문(2026-10-24 01시 KST 실조회): "This XML feed is made available solely for the purpose of rendering
# Google News results within a personal feed reader for personal, non-commercial use. Any other use of the feed is expressly prohibited."
GN_WITHHELD = "Google News 경유 — 피드 약관(개인 피드 리더·비상업 전용)상 공개 게시본엔 제목 비공개 · 매체·시각·링크만"
EVENT_SIM = 0.4   # 같은 사건 판정 자카드 하한 — 10/23 산출물 대조: 같은 사건 쌍 0.45~1.0, 다른 사건 쌍 최대 0.31 (tests/test_geo_news.py 실제 제목)

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


_STOP = set("the a an and or of to in on at for from with by as is are was were be been has have had will would could "
             "says say said after amid over into new than more its it this that what how why who live latest update updates news "
             "report reports reportedly".split())
_ALIAS = {"chinese": "china", "russian": "russia", "iranian": "iran", "ukrainian": "ukraine", "korean": "korea", "taiwanese": "taiwan",
          "houthis": "houthi"}


def _stem(w: str) -> str:
    w = _ALIAS.get(w, w)
    for suf in ("ing", "ed", "es", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            w = w[: -len(suf)]
            break
    return w[:-1] if w.endswith("e") and len(w) >= 5 else w   # secure/secured·criminalize/criminalizes 맞춤


def event_tokens(title: str) -> frozenset[str]:
    """사건 비교용 단어 집합: 소문자·문장부호 제거·불용어·3글자 미만 제외·간단 어간(s/es/ed/ing)·국명 형용사 → 국명."""
    ws = re.sub(r"[^\w\s]", " ", (title or "").lower()).split()
    return frozenset(_stem(w) for w in ws if len(w) >= 3 and w not in _STOP)


def link_key(link: str) -> str:
    """같은 링크 대상 판정: 스킴·www·쿼리·조각·끝 / 제거."""
    u = urllib.parse.urlsplit((link or "").strip())
    return (u.netloc.lower().removeprefix("www.") + u.path.rstrip("/")) if u.netloc else ""


def same_event(a: dict, b: dict, sim: float = EVENT_SIM) -> bool:
    la, lb = link_key(a.get("link", "")), link_key(b.get("link", ""))
    if la and la == lb:
        return True
    ta, tb = event_tokens(a.get("title", "")), event_tokens(b.get("title", ""))
    if not (ta and tb):
        return False
    k = len(ta & tb)
    # 자카드 ≥ sim, 또는 짧은 쪽 제목 단어의 60% 이상·5단어 이상 겹침(긴 라이브 블로그 제목 vs 짧은 속보 제목 — 10/24 00:33 ruukr 0.375 쌍)
    return k / len(ta | tb) >= sim or (k >= 5 and k / min(len(ta), len(tb)) >= 0.6)


def assign(items: list[dict], axis_ids: list[str], now: datetime, days: int = DAYS,
           per_axis: int = PER_AXIS, per_src: int = PER_SRC, matcher=None) -> dict[str, list[dict]]:
    """수집 순서(직접 피드 → 검색)대로 제목 중복 제거 후 축별로 최근 days 일·최신순·매체당 per_src·축당 per_axis.
    축 안에서 같은 사건(same_event)은 1칸 — 먼저(최신) 들어온 게 검색판이고 나중 것이 직접 피드판이면 직접 피드판으로 바꾼다(G3).
    matcher(title)→[축 id] 는 부동산(realestate.assign_news) 재사용용."""
    matcher = matcher or match_axes
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
        for a in matcher(r["title"]):
            if a not in res:
                continue
            dup = next((i for i, x in enumerate(res[a]) if same_event(x, r)), None)
            if dup is not None:
                old = res[a][dup]
                if old.get("via") == "검색" and r.get("via", "직접") != "검색" and cnt.get((a, r["src"]), 0) < per_src:
                    cnt[(a, old["src"])] -= 1
                    cnt[(a, r["src"])] = cnt.get((a, r["src"]), 0) + 1
                    res[a][dup] = r
                continue
            if len(res[a]) >= per_axis or cnt.get((a, r["src"]), 0) >= per_src:
                continue
            cnt[(a, r["src"])] = cnt.get((a, r["src"]), 0) + 1
            res[a].append(r)
    for a in res:
        res[a].sort(key=lambda r: r["when"], reverse=True)
    return res


def is_google(item: dict) -> bool:
    """Google News 경유 항목인가 — via='검색' 또는 링크가 news.google.com(옛 파일 항목 판정용)."""
    return item.get("via") == "검색" or "news.google.com" in (item.get("link") or "")


def public_item(r: dict) -> dict:
    """공개 산출물용 항목. Google News 경유면 제목 비공개(G3). r['when'] 은 datetime 또는 이미 포맷된 r['time']."""
    t = r["when"].astimezone(KST).strftime("%Y-%m-%d %H:%M") if r.get("when") else r.get("time")
    out = {"title": r.get("title"), "src": r.get("src"), "time": t, "link": r.get("link") or ""}
    if is_google(r):
        out.update(title=None, title_withheld=GN_WITHHELD, via="검색")
    return out


def _prev_file() -> tuple[str | None, dict[str, dict]]:
    """이전 geo_news.json → (generated_at, {축 id: 축}). 없음·깨짐 → (None, {})."""
    try:
        d = json.loads(OUT.read_text(encoding="utf-8"))
        return d.get("generated_at"), {a["id"]: a for a in d.get("axes", [])}
    except Exception:  # noqa: BLE001
        return None, {}


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
            if kind == "검색" and sleep is not None:
                sleep(1)   # 연속 호출 간격 — 10/23 23:03·10/24 00:33 두 번 다 6번째 검색(taiwan)만 503, 단독 호출은 200(10/24 실측)
            try:
                text = fetch(url)
            except Exception:  # noqa: BLE001 — Google News 는 연속 호출 때 간헐 503(10/23 실측) → 3초·10초 쉬고 최대 2회 재시도
                if kind != "검색" or sleep is None:
                    raise
                for i, wait in enumerate((3, 10)):
                    sleep(wait)
                    try:
                        text = fetch(url)
                        break
                    except Exception:  # noqa: BLE001
                        if i == 1:
                            raise
            rows = parse_feed(text, name.split(":")[0] if kind == "직접" else "Google News")
            for r in rows:
                r["via"] = kind
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
    gen = now.astimezone(KST).strftime("%Y-%m-%d %H:%M KST")
    # G1: 축 검색 실패 → 그 축은 새 매칭으로 채우지 않고 이전 값(창 안 항목만, 제목 공개 규칙 재적용) + stale
    failed = {f["name"].split(": ", 1)[1]: f.get("err", "") for f in feeds if f["kind"] == "검색" and not f["ok"]}
    prev_gen, prev = _prev_file() if failed else (None, {})
    cut_s = (now - timedelta(days=DAYS)).astimezone(KST).strftime("%Y-%m-%d %H:%M")
    out_axes = []
    for a, n in axes:
        if a in failed:
            p = prev.get(a) or {}
            since = (p.get("stale") or {}).get("since") or (prev_gen if p else None)   # 이전 값이 언제 것인지(연속 실패면 최초 시각 유지)
            keep = [public_item(x) for x in p.get("items", []) if (x.get("time") or "") >= cut_s]
            out_axes.append({"id": a, "name": n, "items": keep,
                             "stale": {"why": f"Google News 검색 실패({failed[a][:60]}) — 직접 피드 매칭으로 새로 채우지 않고 이전 값 유지",
                                       "since": since, "kept": len(keep)}})
            log.warning("지정학 뉴스: 축 %s 검색 실패 — 이전 값 %d건 유지(stale)", a, len(keep))
        else:
            out_axes.append({"id": a, "name": n, "items": [public_item(r) for r in res.get(a, [])]})
    out = {
        "asof": now.astimezone(KST).date().isoformat(),
        "generated_at": gen,
        "window_days": DAYS,
        "axes": out_axes,
        "feeds": feeds,
        "stale_axes": sorted(failed),
        "label": "자동 수집 헤드라인 — 제목 키워드 매칭일 뿐 데스크 해석 아님 · 원문 미대조(검증전) · 링크는 깨질 수 있음",
        "method": f"공개 RSS {ok}/{len(feeds)}개 성공 · 축별 제목 정규식(screener/geo_news.py AXES) · 최근 {DAYS}일 · 축당 {PER_AXIS}개 · 같은 매체 {PER_SRC}개까지 · "
                  f"제목 정규화 중복 + 축 안 같은 사건(같은 링크·제목 자카드 ≥{EVENT_SIM}) 1칸 · 축 검색 실패 시 그 축 이전 값 유지(stale) · Google News 경유 제목 비공개(약관)",
        "terms": GN_WITHHELD,
    }
    from .guard import write_json
    write_json(OUT, out)
    log.info("지정학 뉴스 %s", " · ".join(f"{a['id']} {len(a['items'])}" for a in out["axes"]))
    return out


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    build()
