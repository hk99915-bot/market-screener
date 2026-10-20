"""네이버 리서치 새 화면(10/15~ Next.js, Npay 증권) 데이터 경로 탐침 — 디버그 전용, 저장 없음.

추정 경로를 코드에 박지 않으려고, 실제 응답에서만 경로를 찾는다:
  1) 목록 페이지 HTML 의 __NEXT_DATA__ / self.__next_f (RSC flight) 안에 리포트 행이 있는지
  2) 페이지가 싣는 JS 청크(app/research/* 우선) 안의 API 문자열(https://…naver.com/… · /api/… · /front-api/…)
  3) 2)에서 찾은 문자열 중 템플릿 변수가 없는 것만 실제 GET 해 상태·앞부분 출력
실행: python -m screener.main --mode probe (briefing.yml workflow_dispatch mode=probe commit=false → 로그로만 확인)
"""
from __future__ import annotations

import json
import re

import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36",
      "Accept-Language": "ko-KR,ko;q=0.9"}
BASE = "https://finance.naver.com/research/"
PAGES = ["company_list.naver", "industry_list.naver", "market_info_list.naver", "invest_list.naver",
         "economy_list.naver", "debenture_list.naver"]
KEYS = re.compile(r"nid|researchId|reportId|brokerName|stockName|itemCode|firmName|writeDate|regDate|title")
URL_RX = [re.compile(r"[\"'`](https?://[a-z0-9.\-]*naver\.com[^\"'`\s]{0,200})[\"'`]"),
          re.compile(r"[\"'`](/(?:api|front-api|research)[^\"'`\s]{0,200})[\"'`]")]


def flight(h: str) -> str:
    out = []
    for m in re.finditer(r"self\.__next_f\.push\(\[1,\s*(\"(?:[^\"\\]|\\.)*\")\]\)", h):
        try:
            out.append(json.loads(m.group(1)))
        except Exception:  # noqa: BLE001
            pass
    return "".join(out)


def _p(*a) -> None:
    print("[NAVER_PROBE]", *a, flush=True)


def discover(fetch_js: bool = True) -> dict:
    res: dict = {}
    s = requests.Session()
    s.headers.update(UA)
    chunks: list[str] = []
    for pg in PAGES:
        try:
            r = s.get(BASE + pg, headers={"Referer": BASE}, timeout=20)
            h = r.text
            fl = flight(h)
            nd = re.search(r"<script[^>]+id=\"__NEXT_DATA__\"[^>]*>([\s\S]*?)</script>", h)
            info = {"status": r.status_code, "final": r.url, "len": len(h), "next_f": h.count("self.__next_f.push"),
                    "flight_len": len(fl), "next_data": bool(nd), "table": "<table" in h.lower()}
            res[pg] = info
            _p("PAGE", pg, json.dumps(info, ensure_ascii=False))
            body = (nd.group(1) if nd else "") + fl
            hits = [m.start() for m in KEYS.finditer(body)][:3]
            for i in hits[:1]:
                _p("FLIGHT", pg, body[max(0, i - 1500):i + 3500].replace("\n", " "))
            if not hits and fl:
                _p("FLIGHT_HEAD", pg, fl[:3000].replace("\n", " "))
            if pg == "company_list.naver":
                chunks = re.findall(r"src=\"(https://[^\"]+/_next/static/chunks/[^\"]+\.js)\"", h)
                _p("TAIL", pg, h[-3000:].replace("\n", " "))
        except Exception as e:  # noqa: BLE001
            res[pg] = {"error": str(e)}
            _p("PAGE", pg, "ERR", e)
    if not fetch_js:
        return res
    found: dict[str, str] = {}
    chunks.sort(key=lambda u: ("app/research" not in u, u))
    for u in chunks[:90]:
        try:
            js = s.get(u, timeout=20).text
        except Exception as e:  # noqa: BLE001
            _p("JS", u, "ERR", e)
            continue
        for rx in URL_RX:
            for m in rx.finditer(js):
                v = m.group(1)
                if "static" in v or v.endswith((".js", ".css", ".png", ".svg")):
                    continue
                found.setdefault(v, u.rsplit("/", 1)[-1])
        for m in re.finditer(r"research", js, flags=re.I):
            ctx = js[max(0, m.start() - 160):m.start() + 200]
            if re.search(r"api|fetch|url|path|endpoint", ctx, flags=re.I):
                _p("CTX", u.rsplit("/", 1)[-1], ctx.replace("\n", " "))
    res["urls"] = found
    for v, src in sorted(found.items()):
        _p("URL", src, v)
    tried = 0
    for v in sorted(found):
        if "research" not in v.lower() or "${" in v or "{" in v or tried >= 25:
            continue
        origin = re.match(r"https?://[^/]+", (res.get("company_list.naver") or {}).get("final") or BASE).group(0)
        full = v if v.startswith("http") else origin + v
        tried += 1
        try:
            r = s.get(full, headers={"Referer": BASE}, timeout=20)
            _p("TRY", full, r.status_code, r.headers.get("content-type"), r.text[:1500].replace("\n", " "))
        except Exception as e:  # noqa: BLE001
            _p("TRY", full, "ERR", e)
    return res
