"""네이버(Npay 증권) 리서치 목록 API — 10/15 화면 개편 뒤의 실제 데이터 경로.

근거(추정 아님, 2026-10-21 Actions 탐침 briefing.yml mode=probe 실행 39452041399·39453092263 로그):
- 옛 finance.naver.com/research/*_list.naver → stock.naver.com/research/{company|industry|daily|invest|economy|debenture}
  로 리다이렉트(200, Next.js RSC, 표·__NEXT_DATA__ 없음 — 목록은 브라우저가 API 로 받음).
- 페이지 JS 청크(2248-*.js)의 목록 함수: GET /api/stockSecurity/researches/v2/{researchType}?index&size&startDate&endDate&
  query&brokerCodes&industryTypes&itemCodes. researchType enum(400 응답 메시지) = market|invest|economy|debenture|industry|company.
  ('page'·'brokerCode' 인자는 무시됨 — 같은 첫 행 반환)
- 응답 {"hasNext", "totalCount", "items":[…]} — 항목(실응답 tests/fixtures/naver_api_*_20261021.json):
  공통 nid·title·content(HTML 요약)·brokerName·brokerCode·writeDate(YYYY-MM-DD)·readCount
  company + itemCode·itemName·goalPrice·opinionText·opinionType / industry + industry·industryKoreanName·analystName
- 웹 상세 경로(JS 청크 63607-*.js): /research/{daily|company|industry|invest|economy|debenture}/{nid} (market → daily)
미확인: index 가 0 기준인지 1 기준인지 → fetch() 가 첫 응답과 index=1 응답의 첫 nid 를 비교해 스스로 판정한다.
원문 PDF·전문은 저장하지 않는다 — content 는 태그 제거 후 SUMMARY_MAX 자로 잘라 요약으로만 쓴다.
"""
from __future__ import annotations

import html as htmlmod
import re
import time
from datetime import date
from typing import Callable

import requests

API = "https://stock.naver.com/api/stockSecurity/researches/v2/"
WEB = "https://stock.naver.com/research/"
TYPES = ("company", "industry", "market", "invest", "economy", "debenture")
ROUTE = {"market": "daily"}            # API 종류 → 웹 상세 경로 이름
SUMMARY_MAX = 500
SIZES = (100, 50, 30, 20, 10)          # 시도 순서 (상한 미확인)
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36",
      "Referer": "https://stock.naver.com/research", "Accept": "application/json"}


def _get_json(url: str) -> dict:
    r = requests.get(url, headers=UA, timeout=20)
    r.raise_for_status()
    return r.json()


def link(rtype: str, nid) -> str:
    return f"{WEB}{ROUTE.get(rtype, rtype)}/{nid}"


def summary(content: str | None, limit: int = SUMMARY_MAX) -> str:
    """content(HTML) → 평문 요약 ≤ limit 자."""
    s = re.sub(r"<br\s*/?>|</p>|</li>", " ", content or "", flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\s+", " ", htmlmod.unescape(s)).strip()
    return (s[:limit - 1] + "…") if len(s) > limit else s


def _date(s) -> date | None:
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(s or ""))
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None
    except ValueError:
        return None


def _num(s) -> float | None:
    try:
        v = float(re.sub(r"[^\d.]", "", str(s or "")) or "nan")
        return v if v > 0 else None
    except ValueError:
        return None


def parse_item(rtype: str, it: dict) -> dict | None:
    """API 항목 → 공통 행. 날짜·nid·제목이 없으면 None."""
    d, nid, title = _date(it.get("writeDate")), str(it.get("nid") or "").strip(), (it.get("title") or "").strip()
    if not (d and nid.isdigit() and title):
        return None
    row = {"date": d, "nid": nid, "title": title, "broker": (it.get("brokerName") or "").strip(),
           "analyst": (it.get("analystName") or None), "link": link(rtype, nid), "summary": summary(it.get("content")) or "-"}
    if rtype == "company":
        code = str(it.get("itemCode") or "").strip()
        if not re.fullmatch(r"\d{6}|[0-9A-Z]{6}", code):
            return None
        row.update(code=code, name=(it.get("itemName") or "").strip(), opinion=(it.get("opinionText") or None),
                   target=_num(it.get("goalPrice")))
    if rtype == "industry":
        row["sector"] = it.get("industryKoreanName") or None
    return row


def fetch(rtype: str, since: date, size: int = 100, max_pages: int = 60,
          get: Callable[[str], dict] | None = None, pause: float = 0.2) -> tuple[list[dict], dict]:
    """since 이후 행(최신순 응답을 날짜가 since 보다 과거가 될 때까지 넘김). 반환 (행, 진단)."""
    if rtype not in TYPES:
        raise ValueError(rtype)
    get = get or _get_json
    rows: list[dict] = []
    seen: set[str] = set()
    # size 상한 미공개: 10/21 첫 실수집에서 size=100 → 400. 화면 기본값 10(JS 확인)까지 줄여 가며 받는 크기로 고정
    first, err = None, None
    for sz in [x for x in SIZES if x <= size] or [10]:
        try:
            first = get(f"{API}{rtype}?size={sz}")
            size = sz
            break
        except requests.HTTPError as e:
            err = e
            if e.response is None or e.response.status_code != 400:
                raise
    if first is None:
        raise err
    pages = [first]
    base = None                                  # index 기준(0/1) — 두 번째 요청에서 판정
    total = first.get("totalCount")
    for p in range(max_pages):
        cur = pages[-1]
        items = cur.get("items") or []
        older = False
        for it in items:
            r = parse_item(rtype, it)
            if r is None or r["nid"] in seen:
                continue
            seen.add(r["nid"])
            if r["date"] < since:
                older = True
                continue
            rows.append(r)
        if older or not items or not cur.get("hasNext") or p + 1 >= max_pages:
            break
        time.sleep(pause)
        if base is None:
            nxt = get(f"{API}{rtype}?size={size}&index=1")
            same = (nxt.get("items") or [{}])[0].get("nid") == items[0].get("nid")
            base = 1 if same else 0              # index=1 이 첫 쪽과 같으면 1 기준
            if same:
                nxt = get(f"{API}{rtype}?size={size}&index=2")
            pages.append(nxt)
        else:
            pages.append(get(f"{API}{rtype}?size={size}&index={len(pages) + base}"))
    diag = {"status": "ok" if rows else "empty", "n": len(rows), "pages": len(pages), "size": size, "index_base": base,
            "total": total, "reason": None if rows else f"since {since} 이후 0건 (첫 쪽 {len(first.get('items') or [])}건)"}
    return rows, diag
