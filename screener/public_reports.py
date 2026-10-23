"""공공 리포트 트래커 + 외부 지정학 논평(Jiang Xueqin) 피드 — 애널 public-reports (10/21).

출력
- reports/public_reports.json : 소스 표(ok/empty/error/manual) · 발간 목록(기관·시리즈·제목·발간일·링크·요약≤500자) · '다음 발간' 캘린더(규칙 추정)
- reports/views/jiang.json     : Predictive History(Jiang Xueqin) 유튜브 새 영상 제목·날짜·링크 + 제목 기반 태그만(전사·요약 안 함)
- reports/views/jiang_predictions.json : 사람이 채우는 예측 장부(판정은 검증 데스크) — 없을 때만 빈 장부 생성
실행: python -m screener.public_reports [--probe | --pending]   (fin.yml 03:30, research_views 다음 · research_synthesis 앞)
컨테이너는 외부 사이트가 막혀 있어 Actions 에서만 실수집된다.

규칙
- 원문 복제 금지: 제목·링크·발간일·RSS 가 주는 요약(≤500자)만.
- 백필: 소스를 처음 수집할 때 들어온 행, 그리고 처음 보는데 발간 14일 지난 행은 collected_at='backfill …' — '신규 수집' 집계·알림 제외.
- 요약·뷰·우리 해석(3종)+한 줄 뷰는 reports/views/digest.json(id = items[].key, 데스크 작성). --pending 이 빈 칸 목록.
- 등급: 공공 리포트 = 1차 자료 목록(우리 판단 아님). Jiang = '참고 뷰(외부 논평·검증전)' — 우리 판단·매매에 쓰지 않음.
"""
from __future__ import annotations

import argparse
import email.utils
import hashlib
import html as htmlmod
import json
import logging
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

from .config import REPORT_DIR

log = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")
OUT = REPORT_DIR / "public_reports.json"
VIEWS = REPORT_DIR / "views"
JIANG = VIEWS / "jiang.json"
JIANG_PRED = VIEWS / "jiang_predictions.json"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36",
      "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8"}
KEEP_DAYS = 400
BACKFILL_AGE = 14

M = "monthly"
# series: (이름, 제목 정규식, 일정) — 일정 = 발간 월 목록(M=매월) · 추정 규칙, 공식 일정표 아님
BOK_SERIES = [
    ("통화정책방향 의결문", r"통화정책방향", [1, 2, 4, 5, 7, 8, 10, 11]),
    ("금통위 의사록", r"금융통화위원회.*의사록|의사록", [1, 2, 3, 5, 6, 8, 9, 11, 12]),
    ("경제전망보고서", r"경제전망", [2, 5, 8, 11]),
    ("통화신용정책보고서", r"통화신용정책\s*보고서", [3, 6, 9, 12]),
    ("금융안정보고서", r"금융안정\s*보고서", [6, 12]),
    ("금융안정상황", r"금융안정\s*상황", [3, 9]),
    ("지역경제보고서", r"지역경제보고서", [2, 5, 8, 11]),
    ("소비자동향조사(CSI)", r"소비자동향조사|소비자심리", M),
    ("기업경기조사(BSI)·경제심리지수", r"기업경기조사|경제심리지수", M),
    ("국제수지", r"국제수지", M),
    ("수출입물가", r"수출입물가", M),
    ("BOK 이슈노트", r"이슈\s*노트", None),
    ("경제연구·조사통계월보", r"경제연구|조사통계월보", None),
]
SOURCES: list[dict] = [
    # ── 한국은행 ──
    {"id": "bok_press", "group": "한은", "inst": "한국은행", "series": BOK_SERIES,
     "urls": ["https://www.bok.or.kr/portal/bbs/B0000338/news.rss?menuNo=200761",
              "https://www.bok.or.kr/portal/bbs/B0000338/list.do?menuNo=200761",
              "https://www.bok.or.kr/portal/bbs/B0000338/news.rss", "https://www.bok.or.kr/portal/bbs/B0000245/news.rss",
              "https://www.bok.or.kr/portal/bbs/P0000559/news.rss"]},
    {"id": "bok_pub", "manual": "간행물 목록 날짜 형식 미파싱(10/21) — 한은 보도자료 RSS(bok_press)로 대체, 이슈노트 목록은 수동", "group": "한은", "inst": "한국은행", "series": BOK_SERIES,
     "urls": ["https://www.bok.or.kr/portal/bbs/P0002353/list.do?menuNo=200433",
              "https://www.bok.or.kr/portal/bbs/B0000217/list.do?menuNo=200144"]},
    # ── 정부·연구기관 ──
    {"id": "moef", "group": "정부·연구기관", "inst": "기재부", "series": [("그린북(최근 경제동향)", r"최근\s*경제동향|그린북", M)],
     "urls": ["https://www.moef.go.kr/com/detailRssTagService.do?bbsId=MOSFBBS_000000000028", "https://www.korea.kr/briefing/pressReleaseList.do"]},
    {"id": "kostat", "group": "정부·연구기관", "inst": "통계청", "series": [("산업활동동향", r"산업활동동향", M), ("소비자물가", r"소비자물가", M)],
     "urls": ["https://www.korea.kr/briefing/pressReleaseList.do"]},
    {"id": "kdi", "group": "정부·연구기관", "inst": "KDI", "series": [("KDI 경제동향", r"경제동향", M), ("KDI 경제전망", r"경제전망", [5, 11]),
                                                                    ("KDI FOCUS", r"FOCUS|포커스", None)],
     "urls": ["https://www.kdi.re.kr/research/economy", "https://www.kdi.re.kr/research/focus", "https://www.kdi.re.kr/research/outlook"]},
    {"id": "kiet", "group": "정부·연구기관", "inst": "산업연구원", "series": [("KIET 보고서", r".", None)],
     "urls": ["https://www.kiet.re.kr/research/paperList", "https://www.kiet.re.kr/kiet_web/main/"]},
    {"id": "kiep", "manual": "목록 정적 HTML 에 제목-날짜 짝 없음(10/21 확인) — 수동", "group": "정부·연구기관", "inst": "KIEP", "series": [("KIEP 보고서", r".", None)],
     "urls": ["https://www.kiep.go.kr/gallery.es?mid=a10101010000&bid=0001"]},
    {"id": "kif", "manual": "목록이 스크립트로 그려져 정적 HTML 에 날짜 없음(10/21 확인) — 수동", "group": "정부·연구기관", "inst": "금융연구원", "series": [("KIF 보고서", r".", None)],
     "urls": ["https://www.kif.re.kr/kif4/publication/pub_list?mid=10"]},
    {"id": "kcmi", "group": "정부·연구기관", "inst": "자본시장연구원", "series": [("KCMI 보고서", r".", None)],
     "urls": ["https://www.kcmi.re.kr/report/report_list"]},
    {"id": "nabo", "manual": "첫 화면이 스크립트 리다이렉트(10/21 확인) — 수동", "group": "정부·연구기관", "inst": "국회예산정책처", "series": [("NABO 보고서", r"경제|재정|전망|동향", None)],
     "urls": ["https://www.nabo.go.kr/", "https://www.nabo.go.kr/ko/issue.do"]},
    # ── 시장기관 ──
    {"id": "fsc", "group": "시장기관", "inst": "금융위", "series": [("금융위 보도", r"자본시장|증권|공매도|밸류업|금융시장|가계부채|금융안정|PF", None)],
     "urls": ["https://www.fsc.go.kr/no010101", "https://www.korea.kr/briefing/pressReleaseList.do"]},
    {"id": "fss", "group": "시장기관", "inst": "금감원", "series": [("금감원 증권시장 보도", r"증권|공시|불공정|공매도|펀드|자산운용|투자자", None)],
     "urls": ["https://www.fss.or.kr/fss/bbs/B0000188/list.do?menuNo=200218"]},
    {"id": "krx", "manual": "보도자료 목록이 동적 화면(10/21 확인) — 수동", "group": "시장기관", "inst": "한국거래소", "series": [("KRX 시장 동향·보도", r".", None)],
     "urls": ["https://www.krx.co.kr/", "https://open.krx.co.kr/contents/OPN/01/01040100/OPN01040100.jsp"]},
    {"id": "kofia", "group": "시장기관", "inst": "금융투자협회", "manual": "freesis 통계 포털(동적 화면) — 채권·펀드 동향 수동 확인",
     "series": [("채권·펀드 동향", r".", M)], "urls": []},
    {"id": "ksd", "group": "시장기관", "inst": "예탁결제원", "manual": "SEIBro 해외주식 결제 동향(동적 화면) — 수동 확인",
     "series": [("해외주식 결제 동향", r".", M)], "urls": []},
    {"id": "nps", "group": "시장기관", "inst": "국민연금", "manual": "기금운용본부 공시(분기, 동적 화면) — 수동 확인",
     "series": [("기금운용 공시", r".", [3, 6, 9, 12])], "urls": []},
    # ── 해외 ──
    {"id": "fed", "group": "해외", "inst": "Fed", "series": [("Financial Stability Report", r"Financial Stability Report", [4, 11]),
                                                             ("FOMC 의사록", r"[Mm]inutes of the Federal Open Market Committee|FOMC.*minutes", [1, 2, 4, 5, 7, 8, 10, 11])],
     "urls": ["https://www.federalreserve.gov/feeds/press_monetary.xml", "https://www.federalreserve.gov/feeds/press_all.xml"]},
    {"id": "imf", "manual": "imf.org 가 Actions 요청을 403 차단(10/21 확인) — WEO·GFSR 는 4·10월 수동 확인", "group": "해외", "inst": "IMF", "series": [("WEO", r"World Economic Outlook", [1, 4, 7, 10]),
                                                             ("GFSR", r"Global Financial Stability", [4, 10])],
     "urls": ["https://www.imf.org/en/Publications/RSS?language=eng&series=World%20Economic%20Outlook",
              "https://www.imf.org/en/Publications/RSS?language=eng&series=Global%20Financial%20Stability%20Report",
              "https://www.imf.org/en/News/RSS?language=eng"]},
    {"id": "bis", "group": "해외", "inst": "BIS", "series": [("BIS Quarterly Review", r"Quarterly Review", [3, 6, 9, 12])],
     "urls": ["https://www.bis.org/doclist/qtrpdf.rss", "https://www.bis.org/doclist/all_pressrels.rss", "https://www.bis.org/list/qtrpdf/index.htm"]},
]
JIANG_HANDLE = "https://www.youtube.com/@PredictiveHistory"
JIANG_TAGS = {"중국": r"China|Chinese|Beijing|Xi\b|Taiwan", "미국": r"America|American|\bUS\b|U\.S\.|United States|Trump|Biden",
              "중동": r"Iran|Israel|Gaza|Middle East|Saudi|Arab", "러시아·우크라": r"Russia|Ukraine|Putin|NATO",
              "전쟁": r"\bwar\b|War|conflict|invasion|military", "게임이론": r"[Gg]ame [Tt]heory|strategy|Strategic",
              "경제·금융": r"econom|dollar|debt|market|financ|bank|gold", "제국·역사": r"[Ee]mpire|[Hh]istory|civilization|Rome|collapse"}


def _key(*parts) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:16]


def _clean(s: str | None, n: int = 500) -> str | None:
    if not s:
        return None
    s = re.sub(r"<[^>]+>", " ", htmlmod.unescape(s))
    s = re.sub(r"\s+", " ", s).strip()
    return s[:n] or None


def _date(s: str | None) -> date | None:
    if not s:
        return None
    s = s.strip()
    try:
        return email.utils.parsedate_to_datetime(s).date()
    except Exception:  # noqa: BLE001
        pass
    m = re.search(r"(20\d\d)[.\-/년]\s*(\d{1,2})[.\-/월]\s*(\d{1,2})", s)
    if m:
        try:
            return date(int(m[1]), int(m[2]), int(m[3]))
        except ValueError:
            return None
    return None


def parse_feed(text: str) -> list[dict]:
    """RSS 2.0 / Atom 공통 → [{title, link, date, summary, vid}]"""
    root = ET.fromstring(text.encode("utf-8") if isinstance(text, str) else text)
    out = []
    loc = lambda t: t.rsplit("}", 1)[-1]  # noqa: E731
    for el in root.iter():
        if loc(el.tag) not in ("item", "entry"):
            continue
        d = {"title": None, "link": None, "date": None, "summary": None, "vid": None}
        for c in el:
            n = loc(c.tag)
            if n == "title":
                d["title"] = _clean(c.text, 300)
            elif n == "link":
                d["link"] = c.get("href") or (c.text or "").strip() or d["link"]
            elif n in ("pubDate", "published", "date") or (n == "updated" and not d["date"]):
                d["date"] = _date(c.text) or d["date"]
            elif n in ("description", "summary") and not d["summary"]:
                d["summary"] = _clean(c.text)
            elif n == "videoId":
                d["vid"] = (c.text or "").strip()
            elif n == "group" and not d["summary"]:   # 유튜브 Atom: media:group > media:description (영상 설명, ≤500자 발췌)
                for g in c:
                    if loc(g.tag) == "description":
                        d["summary"] = _clean(g.text)
        if d["title"]:
            out.append(d)
    return out


A_RE = re.compile(r"<a\b[^>]*href=[\"']([^\"'#]+)[\"'][^>]*>(.*?)</a>", re.S | re.I)
D_RE = re.compile(r"20\d\d[.\-/]\s*\d{1,2}[.\-/]\s*\d{1,2}")


def parse_html_list(text: str, base: str) -> list[dict]:
    """목록 페이지 근사 파서: 링크 텍스트 8자 이상 + 뒤 400자 안의 날짜(YYYY.MM.DD)."""
    out, seen = [], set()
    for m in A_RE.finditer(text):
        title = _clean(m.group(2), 300)
        if not title or len(title) < 8:
            continue
        tail = text[m.end(): m.end() + 400]
        dm = D_RE.search(tail) or D_RE.search(text[max(0, m.start() - 300): m.start()])
        if not dm:
            continue
        link = urljoin(base, htmlmod.unescape(m.group(1)))
        if (title, link) in seen or link.startswith("javascript"):
            continue
        seen.add((title, link))
        out.append({"title": title, "link": link, "date": _date(dm.group(0)), "summary": None, "vid": None})
    return out


def _get(url: str, timeout: int = 20) -> str:
    import requests
    r = requests.get(url, headers=UA, timeout=timeout)
    r.raise_for_status()
    r.encoding = r.apparent_encoding if not r.encoding or r.encoding.lower() == "iso-8859-1" else r.encoding
    return r.text


def classify(src: dict, rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        for name, pat, _ in src["series"]:
            if re.search(pat, r["title"] or ""):
                out.append({**r, "series": name})
                break
    return out


def fetch_source(src: dict, get=_get) -> tuple[list[dict], dict]:
    if src.get("manual"):
        return [], {"status": "manual", "n": 0, "reason": src["manual"], "url": None}
    errs, rows, used, diag = [], [], None, []
    for u in src["urls"]:
        try:
            t = _get(u) if get is None else get(u)
            feed = t.lstrip().startswith("<?xml") or "<rss" in t[:500] or "<feed" in t[:500]
            raw = parse_feed(t) if feed else parse_html_list(t, u)
            got = classify(src, raw)
            tm = re.search(r"<title[^>]*>(.*?)</title>", t, re.S | re.I)
            diag.append(f"{u.split('/', 3)[-1][:40]} {len(t)}B {'feed' if feed else 'html'} a{len(A_RE.findall(t)) if not feed else 0} "
                        f"d{len(D_RE.findall(t))} raw{len(raw)} hit{len(got)} '{_clean(tm.group(1), 30) if tm else ''}'")
            if got:
                rows += got
                used = used or u
        except Exception as e:  # noqa: BLE001
            errs.append(f"{u.split('/')[2]}: {type(e).__name__} {str(e)[:80]}")
            diag.append(f"{u.split('/', 3)[-1][:40]} ERR {str(e)[:40]}")
    st = {"diag": diag, "status": "ok" if rows else ("error" if errs and len(errs) == len(src["urls"]) else "empty"),
          "n": len(rows), "reason": "; ".join(errs)[:300] or None, "url": used}
    return rows, st


def next_expected(series: list, last_by_series: dict[str, date], today: date) -> list[dict]:
    out = []
    for name, _, months in series:
        if not months:
            continue
        ms = list(range(1, 13)) if months == M else months
        last = last_by_series.get(name)
        cand = []
        for k in range(0, 13):
            y, m = today.year + (today.month - 1 + k) // 12, (today.month - 1 + k) % 12 + 1
            if m in ms:
                cand.append((y, m))
        nxt = None
        for y, m in cand:
            if (y, m) == (today.year, today.month) and ((last and (last.year, last.month) == (y, m)) or (not last and today.day > 20)):
                continue   # 이번 달 것은 이미 나옴(또는 수집 기록 없이 20일 지남 → 다음 차례로)
            nxt = (y, m)
            break
        if nxt:
            out.append({"series": name, "next": f"{nxt[0]}-{nxt[1]:02d}", "last": str(last) if last else None,
                        "rule": "매월" if months == M else "·".join(f"{x}월" for x in months)})
    return out


def fix_link(u: str | None) -> str | None:
    """알려진 깨진 링크 보정(10/23 매크로 확인): 한은 RSS 링크는 menuNo 가 비어 404 → 아무 메뉴 번호나 붙이면 열림,
    기재부 mofe.go.kr(www 없음)은 DNS 실패 → www."""
    if not u:
        return u
    if "bok.or.kr" in u and u.endswith("menuNo="):
        u += "200761"
    return re.sub(r"^https?://mofe\.go\.kr/", "https://www.mofe.go.kr/", u)


DIGEST = VIEWS / "digest.json"
THREE = ("summary", "view", "our_take")


def digest_ok(d: dict | None) -> bool:
    """STANDARD §4: 세 칸(내용·뷰·우리 해석)이 다 있어야 '요약 있음'. 한 줄 뷰(one_line)는 화면 첫 줄 — 없으면 대기."""
    return bool(d) and all(d.get(k) for k in THREE + ("one_line",))


def pending(pub: dict | None, digest: dict | None, today: date, days: int = 30) -> list[dict]:
    """최근 days일 발간물 중 digest 세 칸·한 줄 뷰가 없는 것 = 데스크 작업 목록(매크로 KB '공공 리포트 3종 작성 규칙')."""
    dm = {i.get("id"): i for i in (digest or {}).get("items") or []}
    cut = str(today - timedelta(days=days))
    return [{k: i.get(k) for k in ("key", "date", "inst", "series", "title", "link")}
            for i in (pub or {}).get("items") or [] if (i.get("date") or "") >= cut and not digest_ok(dm.get(i["key"]))]


def merge(old: list[dict], new: list[dict], src_id: str, inst: str, group: str, now: str, today: date) -> tuple[list[dict], int]:
    keys = {o["key"] for o in old}
    first = not any(o.get("src") == src_id for o in old)
    added = 0
    for r in new:
        k = _key(src_id, r["title"], r.get("date"))
        if k in keys:
            continue
        keys.add(k)
        d = r.get("date")
        bf = first or (d is not None and (today - d).days > BACKFILL_AGE)
        old.append({"key": k, "src": src_id, "group": group, "inst": inst, "series": r["series"], "title": r["title"],
                    "date": str(d) if d else None, "link": fix_link(r.get("link")), "summary": _clean(r.get("summary")),
                    "collected_at": ("backfill " if bf else "") + now})
        added += 0 if bf else 1
    return old, added


def build_output(items: list[dict], status: dict, today: date, now: str) -> dict:
    cut = str(today - timedelta(days=KEEP_DAYS))
    items = [dict(i, link=fix_link(i.get("link"))) for i in items]   # 이미 저장된 행도 보정(키는 그대로 → digest 연결 유지)
    items = sorted([i for i in items if (i.get("date") or "9999") >= cut], key=lambda i: (i.get("date") or "", i["key"]), reverse=True)
    cal = []
    for s in SOURCES:
        last = {}
        for i in items:
            if i["src"] == s["id"] and i.get("date"):
                d = date.fromisoformat(i["date"])
                last[i["series"]] = max(last.get(i["series"], d), d)
        for x in next_expected(s["series"], last, today):
            cal.append({"group": s["group"], "inst": s["inst"], **x})
    seen, cal2 = set(), []
    for c in sorted(cal, key=lambda c: c["next"]):
        if (c["inst"], c["series"]) not in seen:
            seen.add((c["inst"], c["series"]))
            cal2.append(c)
    return {"schema_version": 1, "asof": str(today), "generated_at": now,
            "label": "공공기관 1차 자료 목록 — 우리 판단 아님 · 다음 발간 = 월 단위 규칙 추정(공식 일정표 확인 필요)",
            "sources": [{"id": s["id"], "group": s["group"], "inst": s["inst"], **status.get(s["id"], {"status": "미실행", "n": 0})}
                        for s in SOURCES],
            "items": items, "calendar": cal2}


def tag_title(t: str) -> list[str]:
    return [k for k, p in JIANG_TAGS.items() if re.search(p, t or "")]


def run_jiang(get=_get, now: str = "", today: date | None = None) -> dict:
    today = today or datetime.now(KST).date()
    old = {}
    try:
        old = json.loads(JIANG.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        pass
    cid, st = old.get("channel_id"), {}
    try:
        if not cid:
            page = get(JIANG_HANDLE)
            m = re.search(r'"(?:channelId|externalId)":"(UC[\w-]{22})"', page) or re.search(r"channel/(UC[\w-]{22})", page)
            cid = m.group(1) if m else None
        if not cid:
            raise RuntimeError("채널 ID 를 찾지 못함")
        rows = parse_feed(get(f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}"))
        st = {"status": "ok" if rows else "empty", "n": len(rows), "reason": None}
    except Exception as e:  # noqa: BLE001
        rows, st = [], {"status": "error", "n": 0, "reason": f"{type(e).__name__}: {str(e)[:120]}"}
    vids = {v["link"]: v for v in old.get("videos") or []}
    first = not vids
    for r in rows:
        if r["link"] in vids:
            if r.get("summary") and not vids[r["link"]].get("desc"):
                vids[r["link"]]["desc"] = r["summary"]   # 기존 영상도 피드에 남아 있는 동안 설명 발췌를 채운다
            continue
        vids[r["link"]] = {"date": str(r["date"]) if r["date"] else None, "title": r["title"], "link": r["link"],
                           "tags": tag_title(r["title"]), "desc": r.get("summary"), "collected_at": ("backfill " if first else "") + now}
    v = sorted(vids.values(), key=lambda x: x.get("date") or "", reverse=True)[:200]
    tc: dict[str, int] = {}
    for x in v:
        if x.get("date") and x["date"] >= str(today - timedelta(days=60)):
            for t in x["tags"]:
                tc[t] = tc.get(t, 0) + 1
    out = {"schema_version": 1, "asof": str(today), "generated_at": now, "channel": JIANG_HANDLE, "channel_id": cid,
           "who": "Jiang Xueqin(蒋学勤) · Predictive History — 역사 유추+게임이론 지정학 논평",
           "grade": "참고 뷰(외부 논평·검증전) — 우리 판단·매매에 쓰지 않음. 반증 어려움·학술 엄밀성 비판 있음",
           "method": "유튜브 채널 RSS 의 제목·날짜·링크 + 영상 설명 발췌(desc ≤500자, 요약 재료). 자막 전사는 저장소 밖(개발 요청). 요약은 reports/views/digest.json(데스크 작성). 태그 = 제목 영어 키워드 사전(JIANG_TAGS)",
           "status": st, "videos": v, "tags60": dict(sorted(tc.items(), key=lambda kv: -kv[1]))}
    return out


def ensure_ledger() -> bool:
    if JIANG_PRED.exists():
        return False
    VIEWS.mkdir(parents=True, exist_ok=True)
    JIANG_PRED.write_text(json.dumps({
        "schema_version": 1,
        "grade": "참고 뷰 — 우리 판단에 쓰지 않음. 판정은 검증 데스크(보드 jiang-prediction-ledger)",
        "how": "영상 제목·설명에서 그가 '명시한' 예측만 사람이 확인해 추가. 해석·확대 금지. 판정 전 verdict=null",
        "fields": {"id": "jp-YYYYMMDD-n", "said_on": "YYYY-MM-DD", "source_link": "영상 URL", "claim": "예측 문장(원문 인용 요지)",
                   "deadline": "YYYY-MM-DD 또는 null(기한 없음 = 반증 불가로 표시)", "falsifiable": "true/false",
                   "verdict": "null | hit | miss | void", "judged_by": "검증", "judged_on": None, "note": None},
        "predictions": []}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return True


def run(probe: bool = False) -> dict:
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    today = datetime.now(KST).date()
    old = {}
    try:
        old = json.loads(OUT.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        pass
    items, status, added = list(old.get("items") or []), {}, 0
    for s in SOURCES:
        rows, st = fetch_source(s)
        status[s["id"]] = st
        print(f"[공공] {s['id']:10s} {s['inst']:8s} {st['status']:6s} {st['n']:4d}건 {st.get('url') or ''} {st.get('reason') or ''}"[:300])
        if probe:
            for r in rows[:3]:
                print(f"    {r.get('date')} [{r['series']}] {r['title'][:70]}")
        items, a = merge(items, rows, s["id"], s["inst"], s["group"], now, today)
        added += a
    out = build_output(items, status, today, now)
    out["added_new"] = added
    if not probe:
        OUT.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    j = run_jiang(now=now, today=today)
    print(f"[지정학] Jiang 채널 {j['channel_id']} {j['status']['status']} {j['status'].get('reason') or ''} 영상 {len(j['videos'])}개")
    if not probe:
        VIEWS.mkdir(parents=True, exist_ok=True)
        JIANG.write_text(json.dumps(j, ensure_ascii=False), encoding="utf-8")
        ensure_ledger()
    return out


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true", help="저장 없이 소스별 결과와 앞 3건만 출력")
    ap.add_argument("--pending", action="store_true", help="수집 없이: 최근 30일 발간물 중 digest 3종·한 줄 뷰가 없는 것(데스크 작업 목록)")
    a = ap.parse_args()
    if a.pending:
        def _j(p):
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                return None
        todo = pending(_j(OUT), _j(DIGEST), datetime.now(KST).date())
        for r in todo:
            print(f"{r['key']} {r['date']} [{r['inst']}·{r['series']}] {r['title'][:60]} {r['link']}")
        print(f"요약 대기 {len(todo)}건 — reports/views/digest.json 에 id=key 로 3종+one_line 작성 (docs/desk_kb/macro.md '공공 리포트 3종')")
        raise SystemExit(0)
    o = run(probe=a.probe)
    ok = sum(1 for s in o["sources"] if s["status"] == "ok")
    print(f"공공 리포트: 소스 {ok}/{len(o['sources'])} ok · 목록 {len(o['items'])}건 · 신규 {o['added_new']}")
    import os
    if os.environ.get("GITHUB_ACTIONS"):   # 컨테이너에서 Actions 로그(blob)를 못 읽어 소스 표를 주석(annotation)으로 남긴다
        tab = " | ".join(f"{s['id']}:{s['status']}:{s['n']}" + (f"({(s.get('reason') or '')[:60]})" if s['status'] == 'error' else "") for s in o["sources"])
        try:
            j = json.loads(JIANG.read_text(encoding="utf-8")) if not a.probe else {}
        except Exception:  # noqa: BLE001
            j = {}
        js = j.get("status") or {}
        dg = " ## ".join(f"{s['id']}: " + " / ".join(s.get("diag") or []) for s in o["sources"] if s["status"] not in ("ok", "manual"))
        print(f"::notice title=공공 리포트 진단::{dg[:3500]}")
        print(f"::notice title=공공 리포트 소스 표::{tab} || jiang:{js.get('status')}:{js.get('n')}:{j.get('channel_id')}:{(js.get('reason') or '')[:80]}".replace("\n", " "))
