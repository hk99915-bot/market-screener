"""부동산 트래킹 — 부동산 데스크 (10/23 겸이 "MARKET 탭에 부동산 누나 추가", 담당: 정책·뉴스·서울 상급지/하급지·경기남부·재개발·신도시).

출력: reports/realestate.json. 화면 설계: docs/realestate/2026-10-23_tab_design.md. 데스크 해석(손으로)은 reports/views/realestate.json.
섹션:
- prices: 한국부동산원 R-ONE 주간 아파트 매매·전세 지수 — 권역(상급지·하급지·경기남부)별 1주/4주/52주 변화·52주 위치.
  R-ONE 오픈API 는 **인증키 없이 호출하면 샘플 모드(1회 5행, 페이지 무시 — 2026-10-23 실측)** → 환경변수 REB_API_KEY 가 있을 때만 수집.
  키가 없으면 지어내지 않고 status='키 필요'. 주간 표 id 는 키로 표 목록(SttsApiTbl)을 받아 이름으로 찾는다(하드코딩 안 함, 검증전).
- rates: 한은 ECOS — 기준금리 · 예금은행 주담대 신규취급 금리 · 예금은행 주택관련대출 잔액(전월 대비 증감).
  ECOS_API_KEY 없으면 공개 'sample' 키(1회 10행)로 최근 10개월만 — 샘플 키는 시험용이라 키 등록 권고(source_notes).
- reits: 야후 일봉(screener.data.fetch_prices) — 상장 리츠·리츠 ETF·건설 ETF. 통계는 commodities.stats 재사용(1주·1개월·52주 위치).
- news: Google News 검색 RSS(한국어) 축별 — 파서·중복키는 geo_news 재사용. 제목·매체·시각·링크만(본문 저장 안 함, 제목은 비공개 — G3).
  축 검색이 실패하면 그 축은 이전 값 유지 + stale{why,since,kept}, 최상위 stale_axes(10/24 c3d27b87, geo_news G1 과 같은 규칙).
못 쓰는 소스(국토부 실거래가 API 키, KB 약관 미확인)는 unavailable·source_notes 에 이유와 함께.
실행: write_macro_series 끝(geo_news 다음, 15:45·16:20·06:52 편승). 수동 `python -m screener.realestate`.
표시 전용 — 매크로 바람 점수·매매 신호에 넣지 않는다. 권역 정의는 데스크 주관(설계서 §2), 권역 값 = 소속 지역 변동률 단순평균(가중 아님).
"""
from __future__ import annotations

import json
import logging
import os
import re
import urllib.parse
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .config import REPORT_DIR

log = logging.getLogger(__name__)
OUT = REPORT_DIR / "realestate.json"
KST = ZoneInfo("Asia/Seoul")

# ── 권역 정의 (사전등록 2026-10-23, 데스크 주관 — 설계서 §2. 바꾸면 설계서·KB 같이) ──
# (권역 id, 이름, [(표시 이름, R-ONE CLS_FULLNM 매칭 정규식)])
REGIONS: list[tuple[str, str, list[tuple[str, str]]]] = [
    ("seoul", "서울 전체", [("서울", r"^서울$")]),
    ("core", "서울 상급지(강남3구·용산)", [("강남구", r"^서울>.*강남구$"), ("서초구", r"^서울>.*서초구$"),
                                      ("송파구", r"^서울>.*송파구$"), ("용산구", r"^서울>.*용산구$")]),
    ("lower", "서울 하급지(노도강·금관구)", [("노원구", r"^서울>.*노원구$"), ("도봉구", r"^서울>.*도봉구$"), ("강북구", r"^서울>.*>강북구$"),
                                       ("금천구", r"^서울>.*금천구$"), ("관악구", r"^서울>.*관악구$"), ("구로구", r"^서울>.*구로구$")]),
    ("gg_south", "경기남부(부동산원 경부1·2권)", [("경부1권", r"^경기>경부1권$"), ("경부2권", r"^경기>경부2권$")]),
    ("gg_south_city", "경기남부 대표 시·구", [("성남 분당구", r"^경기>.*분당구$"), ("과천시", r"^경기>.*과천시$"),
                                        ("수원 영통구", r"^경기>.*영통구$"), ("용인 수지구", r"^경기>.*수지구$"),
                                        ("화성시(동탄 포함)", r"^경기>.*화성시$|^경기>.*동탄구$"), ("안양 동안구", r"^경기>.*동안구$")]),
]
RONE = "https://www.reb.or.kr/r-one/openapi/{}.do"
WEEKS_KEEP = 60   # 52주 위치 + 여유


def rone_rows(js: dict, key: str) -> tuple[int | None, list[dict]]:
    """R-ONE JSON → (list_total_count, row 목록). 오류 응답({'RESULT':{'CODE':'ERROR-…'}})은 예외."""
    if key not in js:
        res = (js.get("RESULT") or {}) if isinstance(js, dict) else {}
        if str(res.get("CODE", "")).startswith("INFO-200"):   # 해당 데이터 없음
            return 0, []
        raise ValueError(f"R-ONE 오류 {res.get('CODE')} {res.get('MESSAGE')}")
    parts = js[key]
    total = None
    for h in (parts[0].get("head") or []):
        if "list_total_count" in h:
            total = int(h["list_total_count"])
    rows = parts[1].get("row", []) if len(parts) > 1 else []
    return total, rows


def find_weekly_tables(tables: list[dict]) -> dict[str, str | None]:
    """표 목록 → {'sale': 주간 아파트 매매가격지수 id, 'jeonse': 주간 아파트 전세가격지수 id}. 계절조정·규모별·연립 제외."""
    out: dict[str, str | None] = {"sale": None, "jeonse": None}
    for t in tables:
        nm, cyc = t.get("STATBL_NM") or "", t.get("DTACYCLE_CD") or ""
        if "WK" not in cyc or "아파트" not in nm or any(x in nm for x in ("계절", "규모", "연립", "단독", "수급", "평균", "중위")):
            continue
        if "매매가격지수" in nm and not out["sale"]:
            out["sale"] = t["STATBL_ID"]
        elif "전세가격지수" in nm and not out["jeonse"]:
            out["jeonse"] = t["STATBL_ID"]
    return out


def series_by_region(rows: list[dict]) -> dict[str, list[tuple[str, float]]]:
    """SttsApiTblData 행 → {CLS_FULLNM: [(WRTTIME_IDTFR_ID, 값)] 오름차순}. 지수 항목(ITM_NM '지수')만."""
    res: dict[str, dict[str, float]] = {}
    for r in rows:
        if r.get("ITM_NM") not in (None, "지수") or r.get("DTA_VAL") is None:
            continue
        nm = r.get("CLS_FULLNM") or r.get("CLS_NM") or ""
        res.setdefault(nm, {})[str(r.get("WRTTIME_IDTFR_ID"))] = float(r["DTA_VAL"])
    return {k: sorted(v.items()) for k, v in res.items()}


def idx_stats(s: list[tuple[str, float]]) -> dict:
    """주간 지수 [(주 id, 값)] → 최근 값·1주/4주/52주 변화율(%)·52주 위치."""
    if len(s) < 2:
        return {"status": "미확인", "why": f"주간 {len(s)}개 — 부족"}
    v = [x for _, x in s]
    ch = lambda n: round((v[-1] / v[-1 - n] - 1) * 100, 3) if len(v) > n and v[-1 - n] else None  # noqa: E731
    y = v[-53:]
    hi, lo = max(y), min(y)
    return {"status": "ok", "week": s[-1][0], "last": round(v[-1], 3), "chg1w": ch(1), "chg4w": ch(4), "chg52w": ch(52),
            "pos52": round((v[-1] - lo) / (hi - lo), 3) if hi > lo else None}


def group_prices(series: dict[str, list[tuple[str, float]]]) -> list[dict]:
    """권역별: 소속 지역 줄 + 권역 값(소속 지역 변동률 단순평균). 매칭 안 된 지역은 '미확인(지역 코드 없음)'."""
    out = []
    for gid, gname, members in REGIONS:
        mrows = []
        for label, rx in members:
            hit = next((k for k in series if re.search(rx, k)), None)
            mrows.append({"name": label, "cls": hit, **(idx_stats(series[hit]) if hit else
                                                         {"status": "미확인", "why": "R-ONE 지역 이름 매칭 실패(권역 정의 확인)"})})
        ok = [m for m in mrows if m["status"] == "ok"]
        # pos52_avg = 소속 지역 52주 위치의 단순평균 — '권역 지수의 52주 위치'가 아님(지역마다 고저 시점 다름, 피어 10/24 R4)
        avg = lambda k: round(sum(m[k] for m in ok) / len(ok), 3) if ok and all(m.get(k) is not None for m in ok) else None  # noqa: E731
        out.append({"id": gid, "name": gname, "n_ok": len(ok), "n": len(mrows), "chg1w": avg("chg1w"), "chg4w": avg("chg4w"),
                    "chg52w": avg("chg52w"), "pos52_avg": avg("pos52"), "week": max((m["week"] for m in ok), default=None), "members": mrows})
    return out


def _rone_get(fetch_json, op: str, **params) -> dict:
    return fetch_json(RONE.format(op), {"Type": "json", **params})


def fetch_rone(fetch_json, key: str | None) -> dict:
    """R-ONE 주간 매매·전세 → {'sale': [권역…], 'jeonse': [...], 'tables': {...}} 또는 status '키 필요'/'실패'."""
    if not key:
        return {"status": "키 필요", "why": "R-ONE 오픈API 무키 호출 = 샘플 모드(1회 5행·페이지 무시, 2026-10-23 실측) — 무료 인증키(REB_API_KEY) 등록 전 수집 안 함"}
    _, tables = rone_rows(_rone_get(fetch_json, "SttsApiTbl", KEY=key, pIndex=1, pSize=1000), "SttsApiTbl")
    ids = find_weekly_tables(tables)
    out: dict = {"status": "ok", "tables": ids}
    for kind, sid in ids.items():
        if not sid:
            out[kind] = []
            out["status"] = "부분"
            continue
        # 최신 주 지역 목록 = 마지막 페이지(행이 시간 오름차순이라는 가정 — 검증전, 키 등록 후 첫 실행에서 확인)
        total, _ = rone_rows(_rone_get(fetch_json, "SttsApiTblData", KEY=key, STATBL_ID=sid, DTACYCLE_CD="WK", pIndex=1, pSize=1), "SttsApiTblData")
        _, last = rone_rows(_rone_get(fetch_json, "SttsApiTblData", KEY=key, STATBL_ID=sid, DTACYCLE_CD="WK",
                                      pIndex=max(1, -(-(total or 1) // 1000)), pSize=1000), "SttsApiTblData")
        cls = {}
        for r in last:
            cls.setdefault(r.get("CLS_FULLNM") or r.get("CLS_NM") or "", r.get("CLS_ID"))
        want = {k: v for k, v in cls.items() if any(re.search(rx, k) for _, _, ms in REGIONS for _, rx in ms)}
        rows: list[dict] = []
        for nm, cid in want.items():
            t, rs = rone_rows(_rone_get(fetch_json, "SttsApiTblData", KEY=key, STATBL_ID=sid, DTACYCLE_CD="WK", CLS_ID=cid,
                                        pIndex=1, pSize=1000), "SttsApiTblData")
            if t and t > 1000:   # 긴 이력이면 마지막 페이지(최근)를 다시
                _, rs2 = rone_rows(_rone_get(fetch_json, "SttsApiTblData", KEY=key, STATBL_ID=sid, DTACYCLE_CD="WK", CLS_ID=cid,
                                             pIndex=-(-t // 1000), pSize=1000), "SttsApiTblData")
                rs = rs + rs2
            rows += rs
        ser = {k: v[-WEEKS_KEEP:] for k, v in series_by_region(rows).items()}
        out[kind] = group_prices(ser)
    return out


# ── ECOS (한국은행) ──
ECOS = "https://ecos.bok.or.kr/api/StatisticSearch/{key}/json/kr/1/10/{code}/M/{start}/{end}/{item}"
RATES: list[tuple[str, str, str, str, str, str]] = [
    # (key, 통계표, 항목, 이름, 단위, 읽는 법)
    ("BOK_BASE", "722Y001", "0101000", "한은 기준금리", "%", "주담대 변동금리(코픽스) 경로의 출발점 — 오르면 이자 부담↑, 매수 여력↓"),
    ("MORT_RATE", "121Y006", "BECBLA0302", "예금은행 주담대 금리(신규취급)", "%", "실제 새로 빌리는 사람의 금리 — 기준금리보다 시장에 가까움"),
    ("HOUSING_LOAN", "151Y005", "11110A0", "예금은행 주택관련대출 잔액", "조원", "전월 대비 증가폭 = 레버리지 유입 속도. 규제(DSR·총량) 효과를 가장 먼저 보여줌"),
]


def parse_ecos(js: dict) -> list[tuple[str, float]]:
    """ECOS StatisticSearch JSON → [(YYYYMM, 값)] 오름차순. 오류 응답({'RESULT':…})은 빈 목록."""
    rows = ((js or {}).get("StatisticSearch") or {}).get("row") or []
    out = []
    for r in rows:
        try:
            out.append((str(r["TIME"]), float(r["DATA_VALUE"])))
        except (KeyError, TypeError, ValueError):
            continue
    return sorted(out)


def rate_row(key: str, name: str, unit: str, what: str, s: list[tuple[str, float]], today: date) -> dict:
    if not s:
        return {"key": key, "name": name, "unit": unit, "what": what, "status": "미확인", "why": "ECOS 응답 없음"}
    v = [x for _, x in s]
    scale = 1000.0 if unit == "조원" else 1.0   # ECOS 단위 십억원 → 조원
    last, prev = v[-1] / scale, (v[-2] / scale if len(v) > 1 else None)
    r = {"key": key, "name": name, "unit": unit, "what": what, "status": "ok", "month": s[-1][0][:4] + "-" + s[-1][0][4:6],
         "last": round(last, 2), "chg1m": None if prev is None else round(last - prev, 2),
         "chg6m": round(last - v[-7] / scale, 2) if len(v) >= 7 else None, "recent": [[t, round(x / scale, 2)] for t, x in s[-6:]]}
    try:   # 월간 통계는 1~2개월 늦게 나옴 — 4개월 넘게 새 달이 없으면 미확인
        if (today - date(int(s[-1][0][:4]), int(s[-1][0][4:6]), 1)).days > 125:
            r.update(status="미확인", why=f"마지막 {r['month']} — 4개월 넘게 새 값 없음")
    except ValueError:
        pass
    return r


SAMPLE_KEY_NOTE = "sample(시험용 공개 키 — ECOS 정책 변경 시 예고 없이 끊길 수 있음, 개인키 결재 a391f778 보류 중 · 피어 10/24 R7)"


def fetch_rates(fetch_json, key: str | None, today: date) -> list[dict]:
    k = key or "sample"
    start = (today.replace(day=1) - timedelta(days=280)).strftime("%Y%m")   # 샘플 키 10행 한도 안 — 최근 약 9~10개월
    out = []
    for rk, code, item, name, unit, what in RATES:
        try:
            s = parse_ecos(fetch_json(ECOS.format(key=k, code=code, start=start, end=today.strftime("%Y%m"), item=item), None))
            out.append({**rate_row(rk, name, unit, what, s, today), "ecos_key": "개인키" if key else SAMPLE_KEY_NOTE})
        except Exception as e:  # noqa: BLE001
            out.append({"key": rk, "name": name, "unit": unit, "what": what, "status": "미확인", "why": f"ECOS 실패: {str(e)[:80]}"})
    return out


# ── 리츠·건설 (야후) ──
REITS: list[tuple[str, str, str]] = [
    ("329200.KS", "TIGER 리츠부동산인프라(ETF)", "국내 리츠·인프라 바스켓"),
    ("476800.KS", "KODEX 한국부동산리츠인프라(ETF)", "국내 리츠·인프라 바스켓"),
    ("330590.KS", "롯데리츠", "리테일(백화점·마트)"),
    ("365550.KS", "ESR켄달스퀘어리츠", "물류센터"),
    ("395400.KS", "SK리츠", "오피스·주유소"),
    ("448730.KS", "삼성FN리츠", "오피스"),
    ("338100.KS", "NH프라임리츠", "오피스(재간접)"),
    ("088980.KS", "맥쿼리인프라", "인프라 펀드 — 리츠 아님(비교용, 금리 민감 대표)"),
    ("117700.KS", "KODEX 건설(ETF)", "건설주 — 주택 공급·PF 심리"),
    ("VNQ", "Vanguard 미국 리츠(ETF)", "미국 리츠 비교(달러)"),
]


def fetch_reits(fetch) -> list[dict]:
    from .commodities import stats
    syms = [s for s, _, _ in REITS]
    if fetch is None:
        def fetch(ss):
            from . import data
            df = data.fetch_prices(ss, "MACRO", lookback_days=400)
            res: dict = {}
            for x in df.sort("date").select("yf", "date", "close").iter_rows():
                res.setdefault(x[0], []).append((str(x[1]), float(x[2]) if x[2] is not None else None))
            return res
    raw = fetch(syms)
    out = []
    for sym, name, what in REITS:
        rs = raw.get(sym) or []
        s = stats(rs) if rs else {"status": "미확인", "why": f"야후 {sym} 데이터 없음"}
        out.append({"sym": sym, "name": name, "what": what, **s})
    return out


# ── 뉴스 (Google News 검색 RSS, 한국어) ──
GN_KR = "https://news.google.com/rss/search?q={q}&hl=ko&gl=KR&ceid=KR:ko"
NEWS_DAYS, PER_AXIS, PER_SRC = 7, 5, 2
CUE = r"아파트|집값|부동산|전세|전셋|매매|분양|재건축|재개발|청약|주택|입주|(?<!산업)(?<!산업 )단지|정비|토허|토지거래허가|주담대|DSR|LTV|신도시"
# 축 id → (이름, 제목 정규식, 검색어). 제목에 CUE 도 있어야 채택(수원 축구·용인 반도체 공장 기사 등 오탐 제거)
NEWS_AXES: dict[str, tuple[str, str, str]] = {
    "policy": ("정책·대출·세제", r"대책|규제|DSR|LTV|주담대|대출|토지거래허가|토허|조정대상|투기과열|보유세|양도세|취득세|재산세|국토부|국토교통부|금융위|공급 확대|공급대책",
               "부동산 대책 OR 주택담보대출 규제 OR DSR OR 토지거래허가구역"),
    "market": ("시장 동향(지수·거래)", r"부동산원|KB.{0,4}(시세|통계)|아파트값|집값|전셋값|매매가격|전세가격|거래량|미분양|신고가",
               "아파트값 부동산원 OR 서울 집값 OR 전셋값"),
    "core": ("서울 상급지", r"강남|서초|송파|용산|압구정|반포|잠실|대치|한강벨트", "(강남 OR 서초 OR 송파 OR 용산) 아파트"),
    "lower": ("서울 하급지", r"노원|도봉|강북구|노도강|금천|관악|구로[구동]|(?<![가-힣])구로(?![가-힣])|금관구|중랑|외곽", "(노원 OR 도봉 OR 노도강 OR 금관구) 아파트"),
    "gg_south": ("경기남부", r"분당|판교|수원|영통|광교|용인|수지|동탄|화성|병점|평택|과천|안양|평촌|경기 ?남부|반도체 ?벨트",
                 "(분당 OR 수원 OR 동탄 OR 용인 OR 과천 OR 평택) 아파트"),
    "redev": ("재개발·재건축", r"재개발|재건축|정비사업|관리처분|사업시행|조합원|신속통합|모아타운|정비구역|선도지구", "재건축 OR 재개발 OR 정비사업"),
    "newtown": ("신도시", r"신도시|왕숙|교산|계양|창릉|대장지구|광명시흥|노후계획도시|공공택지", "3기 신도시 OR 1기 신도시 OR 노후계획도시"),
}
_CUE = re.compile(CUE, re.I)
_NRX = {k: re.compile(v[1], re.I) for k, v in NEWS_AXES.items()}


def match_news(title: str) -> list[str]:
    if not _CUE.search(title or ""):
        return []
    return [k for k, rx in _NRX.items() if rx.search(title)]


def assign_news(items: list[dict], now: datetime) -> dict[str, list[dict]]:
    """geo_news.assign 과 같은 규칙(중복 제거·최근 7일·최신순·매체당 2·축당 5)에 부동산 축 매칭."""
    from .geo_news import norm_key
    cut = now - timedelta(days=NEWS_DAYS)
    seen, uniq = set(), []
    for r in items:
        k = norm_key(r["title"])
        if not k or k in seen or r.get("when") is None or r["when"] < cut or r["when"] > now + timedelta(hours=1):
            continue
        seen.add(k)
        uniq.append(r)
    uniq.sort(key=lambda r: r["when"], reverse=True)
    res: dict[str, list[dict]] = {a: [] for a in NEWS_AXES}
    cnt: dict[tuple[str, str], int] = {}
    for r in uniq:
        for a in match_news(r["title"]):
            if len(res[a]) >= PER_AXIS or cnt.get((a, r["src"]), 0) >= PER_SRC:
                continue
            cnt[(a, r["src"])] = cnt.get((a, r["src"]), 0) + 1
            res[a].append(r)
    return res


def fetch_news(fetch_text, now: datetime, sleep=None) -> tuple[list[dict], list[dict]]:
    from .geo_news import parse_feed
    items, feeds = [], []
    for a, (name, _, q) in NEWS_AXES.items():
        url = GN_KR.format(q=urllib.parse.quote(f"{q} when:{NEWS_DAYS}d"))
        try:
            try:
                text = fetch_text(url)
            except Exception:  # noqa: BLE001 — Google News 간헐 503(10/23 geo_news 실측) → 한 번 쉬고 재시도
                if sleep is None:
                    raise
                sleep(3)
                text = fetch_text(url)
            rows = parse_feed(text, "Google News")
            items += rows
            feeds.append({"name": f"Google News: {a}", "ok": True, "n": len(rows)})
        except Exception as e:  # noqa: BLE001
            feeds.append({"name": f"Google News: {a}", "ok": False, "err": str(e)[:120]})
    res = assign_news(items, now)
    from .geo_news import public_item   # 10/24 피어 G3: Google News 경유 = 공개 산출물에 제목 비공개(매체·시각·링크만) — geo_news 와 같은 규칙
    # 10/24 req-realestate-c3d27b87(geo_news G1 과 같은 규칙): 축 검색 실패 → 다른 축 검색에서 들어온 기사로 새로 채우지 않고
    # 이전 파일 값(최근 NEWS_DAYS 일 안 항목만, 제목 비공개 재적용) + stale{why,since,kept}. 조용한 빈 칸 금지(LOOP 금지 3).
    failed = {f["name"].split(": ", 1)[1]: f.get("err", "") for f in feeds if not f["ok"]}
    prev_gen, prev = _prev_news() if failed else (None, {})
    cut_s = (now - timedelta(days=NEWS_DAYS)).astimezone(KST).strftime("%Y-%m-%d %H:%M")
    axes = []
    for a in NEWS_AXES:
        if a in failed:
            p = prev.get(a) or {}
            since = (p.get("stale") or {}).get("since") or (prev_gen if p else None)   # 연속 실패면 최초 수집 시각 유지
            keep = [public_item({**x, "via": "검색"}) for x in p.get("items", []) if (x.get("time") or "") >= cut_s]
            axes.append({"id": a, "name": NEWS_AXES[a][0], "items": keep,
                         "stale": {"why": f"Google News 검색 실패({failed[a][:60]}) — 이전 값 유지", "since": since, "kept": len(keep)}})
            log.warning("부동산 뉴스: 축 %s 검색 실패 — 이전 값 %d건 유지(stale)", a, len(keep))
        else:
            axes.append({"id": a, "name": NEWS_AXES[a][0], "items": [public_item({**r, "via": "검색"}) for r in res[a]]})
    return axes, feeds


def _prev_news() -> tuple[str | None, dict[str, dict]]:
    """이전 realestate.json → (generated_at, {뉴스 축 id: 축}). 없음·깨짐 → (None, {})."""
    try:
        d = json.loads(OUT.read_text(encoding="utf-8"))
        return d.get("generated_at"), {a["id"]: a for a in d.get("news", [])}
    except Exception:  # noqa: BLE001
        return None, {}


UNAVAILABLE = [
    {"key": "MOLIT_RTMS", "name": "국토부 아파트 매매 실거래가(공공데이터포털 API)", "status": "키 필요",
     "why": "apis.data.go.kr 무키 호출 401 SERVICE_KEY_IS_NULL(2026-10-23 실측) — 공공데이터포털 활용신청(무료) 후 DATA_GO_KR_KEY 등록 필요(겸이 결재)",
     "use": "권역별 거래량(선행 지표, KB #18)·신고가 비중 — 지수보다 먼저 움직임"},
    {"key": "KB_WEEKLY", "name": "KB 주간 아파트 시계열", "status": "미사용",
     "why": "KB 데이터허브는 SPA 화면(엑셀은 화면 내 다운로드) · 자동 수집·재배포 허용 여부 약관 원문 미확인 → 확인 전 수집 안 함 [확인 필요: KB 이용약관 자동수집·재배포 조항, 2026-10-30, 부동산]",
     "use": "부동산원과 다른 표본(중개업소 시세) — 두 지수 괴리 비교용"},
    {"key": "REB_TRADE_IDX", "name": "부동산원 공동주택 실거래가격지수(월)", "status": "키 필요",
     "why": "R-ONE 같은 키로 받을 수 있음(표 id 확인 전) — REB_API_KEY 등록 후 추가",
     "use": "실제 거래 기반, 2~3개월 늦지만 평활화 덜함(KB #19)"},
]
SOURCE_NOTES = [
    "R-ONE(한국부동산원) 오픈API: 무키 호출도 200 이지만 샘플 모드 — 1회 5행, pIndex 무시(표 목록 738개 중 앞 5개만 반복, 2026-10-23 실측). 키는 R-ONE 회원가입 후 무료 발급",
    "ECOS(한국은행) 오픈API: 'sample' 키로 1회 10행까지 실측 확인(기준금리 722Y001·주담대 121Y006·주택관련대출 151Y005). 운영은 무료 개인키(ECOS_API_KEY) 권고",
    "Google News 검색 RSS: 피드 <copyright> 원문 '개인 피드 리더·개인 비상업 용도 외 금지'(2026-10-24 실조회) → 공개 산출물엔 제목 비공개, 매체·시각·링크만(geo_news 와 같은 규칙, 데이터 data.md 소스 목록). 제목은 매칭에만 쓰고 저장 안 함",
    "정책 원문(국토부·금융위 보도자료): korea.kr 부처 RSS 경로 404, molit.go.kr RSS 연결 끊김(2026-10-23) → 뉴스 축 '정책'으로 대신 찾고 원문 링크는 데스크 해석(views)에서 확인",
    "야후 *.KS 리츠: 2026-10-23 10종 일봉 정상(screener.data.fetch_prices 경로). 국내 '리츠 지수' 자체는 무료 시계열 미확인 → 리츠 ETF 2종으로 대용",
]


def _fetch_json(url: str, params: dict | None) -> dict:
    import requests
    last = None
    for _ in range(3):   # reb.or.kr 연결 끊김(Connection reset) 잦음 — 10/23 실측 → 3회
        try:
            r = requests.get(url, params=params, timeout=(10, 30))
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001
            last = e
    raise last  # type: ignore[misc]


def _fetch_text(url: str) -> str:
    import requests
    r = requests.get(url, timeout=(10, 20), headers={"User-Agent": "Mozilla/5.0 (market-screener realestate; +github)"})
    r.raise_for_status()
    if "<rss" not in r.text[:2000]:
        raise ValueError("RSS 아님(차단·오류 페이지)")
    return r.text


def build(fetch_json=None, fetch_text=None, fetch_prices=None, now: datetime | None = None, sleep=None, env=None) -> dict | None:
    """주입 가능한 fetch 들(테스트는 네트워크 없이). 전 섹션 실패면 쓰지 않고 None + stale 기록."""
    live = fetch_json is None
    fetch_json = fetch_json or _fetch_json
    fetch_text = fetch_text or _fetch_text
    if live and sleep is None:
        import time
        sleep = time.sleep
    env = os.environ if env is None else env
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(KST).date()
    errors = []
    try:
        prices = fetch_rone(fetch_json, env.get("REB_API_KEY"))
    except Exception as e:  # noqa: BLE001
        prices = {"status": "실패", "why": f"R-ONE 수집 실패: {str(e)[:120]}"}
        errors.append(prices["why"])
    try:
        rates = fetch_rates(fetch_json, env.get("ECOS_API_KEY"), today)
    except Exception as e:  # noqa: BLE001
        rates = []
        errors.append(f"ECOS 실패: {e}")
    try:
        reits = fetch_reits(fetch_prices if fetch_prices is not None else (None if live else (lambda s: {})))
    except Exception as e:  # noqa: BLE001
        reits = []
        errors.append(f"리츠 수집 실패: {e}")
    try:
        news, feeds = fetch_news(fetch_text, now, sleep)
    except Exception as e:  # noqa: BLE001
        news, feeds = [], []
        errors.append(f"뉴스 실패: {e}")
    ok_any = (prices.get("status") in ("ok", "부분") or any(r.get("status") == "ok" for r in rates)
              or any(r.get("status") == "ok" for r in reits) or any(f.get("ok") for f in feeds))
    if not ok_any:
        from .guard import record_stale
        log.warning("부동산: 전 섹션 실패 — 이전 파일 유지")
        record_stale("reports/realestate.json", "전 섹션 실패", today.isoformat(), None)
        return None
    out = {
        "asof": today.isoformat(),
        "generated_at": now.astimezone(KST).strftime("%Y-%m-%d %H:%M KST"),
        "regions": [{"id": g, "name": n, "members": [m for m, _ in ms]} for g, n, ms in REGIONS],
        "region_note": "권역 정의 = 부동산 데스크 사전등록(2026-10-23, 주관) — 상급지: 강남3구·용산 = 시장 통용 묶음(주관). 역사적 근거 = 2023-01-05 규제지역 "
                       "일괄 해제 때 유일하게 남은 4구(뉴시스 2023-01-03, 2차) — 10·15 대책(2025)으로 서울 25개구 전역이 규제지역이 된 뒤로는 규제 기준으로 구분 안 됨 · "
                       "하급지: 시장 통용 '노도강·금관구'(언론 관행) · 경기남부: 부동산원 경부1·2권. 권역 값 = 소속 지역 변동률 단순평균(가중 아님)",
        "prices": prices,
        "rates": rates,
        "reits": reits,
        "news": news,
        "feeds": feeds,
        "stale_axes": sorted(a["id"] for a in news if a.get("stale")),
        "unavailable": UNAVAILABLE,
        "source_notes": SOURCE_NOTES,
        "errors": errors,
        "label": "표시 전용 · 매매 신호 아님 · 뉴스는 제목 키워드 매칭(해석 아님, 검증전) · 데스크 해석은 reports/views/realestate.json",
        "src": "R-ONE 주간 지수(키 있을 때) · ECOS 월간 · 야후 일봉(1주=5거래일·1개월=21거래일·52주 위치) · Google News 검색 RSS 최근 7일",
    }
    from .guard import write_json
    write_json(OUT, out)
    log.info("부동산: 가격 %s · 금리 %d · 리츠 %d · 뉴스 %s", prices.get("status"), len(rates), len(reits),
             " · ".join(f"{a['id']} {len(a['items'])}" for a in news))
    return out


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    build()
