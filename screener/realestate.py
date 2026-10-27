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
- regions: 권역 정의 + 지도 칸(서울 25구·경기 21시) 값·출처 단계·칸별 뉴스 + 지오(assets/realestate_map.json, CC BY 3.0) — 10/24.
- seoul_trades: 국토부 RTMS 서울 25개 구 최근 3개월 매매·전세 집계(DATA_GO_KR_KEY 있을 때, 하루 1회 — 10/24).
  드릴다운(10/26): 같은 원자료로 법정동·단지 집계 → reports/realestate_trades/<구코드>.json(구 누를 때 화면이 읽음), 구 행에 detail·n_dong·n_cx.
못 쓰는 소스(KB 약관 미확인 등)는 unavailable·source_notes 에 이유와 함께.
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
from pathlib import Path
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
# ── 지도 칸(10/24 겸이 "서울·경기권 지도") — 서울 25개 구 + 경기 시. 지오 = assets/realestate_map.json(screener/realestate_geo.py, CC BY 3.0).
# 칸 id = 자산 id(한글 이름). R-ONE 매칭 정규식 · 뉴스 별칭(제목 매칭, 공개 산출물엔 제목 비공개) · 소속 권역(설계서 §2).
_GU = ["종로구", "중구", "용산구", "성동구", "광진구", "동대문구", "중랑구", "성북구", "강북구", "도봉구", "노원구", "은평구", "서대문구",
       "마포구", "양천구", "강서구", "구로구", "금천구", "영등포구", "동작구", "관악구", "서초구", "강남구", "송파구", "강동구"]
_GG = ["성남시", "용인시", "수원시", "화성시", "안양시", "광명시", "부천시", "고양시", "하남시", "과천시", "군포시", "의왕시", "시흥시",
       "안산시", "오산시", "김포시", "구리시", "남양주시", "의정부시", "평택시", "광주시"]
_ALIAS = {"양천구": "양천|목동", "중구": r"서울 ?중구|(?<![가-힣])중구 ?(신당|중림)", "구로구": r"구로[구동]|(?<![가-힣])구로(?![가-힣])",
          "강북구": r"강북구", "성남시": "성남|분당|판교", "수원시": "수원|영통|광교", "용인시": "용인|수지|기흥", "화성시": "화성|동탄|병점",
          "안양시": "안양|평촌|동안구", "고양시": "고양|일산", "광주시": r"경기 ?광주|광주시(?!.*광역)", "광명시": "광명", "하남시": "하남|미사"}
AREA_GROUPS = {"강남구": ["core"], "서초구": ["core"], "송파구": ["core"], "용산구": ["core"],
               **{g: ["lower"] for g in ["노원구", "도봉구", "강북구", "금천구", "관악구", "구로구"]},
               **{g: ["gg_south_city"] for g in ["성남시", "과천시", "수원시", "용인시", "화성시", "안양시"]}}
AREAS: list[dict] = ([{"id": g, "sido": "서울", "rx": rf"^서울>.*>{g}$", "news": _ALIAS.get(g, g[:-1] if len(g) > 2 else g)} for g in _GU]
                     + [{"id": g, "sido": "경기", "rx": rf"^경기>.*>{g}$", "news": _ALIAS.get(g, g[:-1])} for g in _GG])
AREA_NEWS_MAX = 3
VIEWS = REPORT_DIR / "views" / "realestate.json"
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
        rxs = [rx for _, _, ms in REGIONS for _, rx in ms] + [a["rx"] for a in AREAS]
        want = {k: v for k, v in cls.items() if any(re.search(rx, k) for rx in rxs)}
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
        out[f"{kind}_areas"] = area_stats(ser)
    return out


def area_stats(series: dict[str, list[tuple[str, float]]]) -> dict[str, dict]:
    """지도 칸별 R-ONE 지수 통계 {칸 id: idx_stats}. 매칭 안 되면 빠짐(화면 '미확인')."""
    out = {}
    for a in AREAS:
        hit = next((k for k in series if re.search(a["rx"], k)), None)
        if hit:
            out[a["id"]] = {"cls": hit, **idx_stats(series[hit])}
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


def area_news(items: list[dict], now: datetime) -> dict[str, list[dict]]:
    """지도 칸별 최근 기사(제목에 부동산 단서 + 칸 별칭). 중복·7일 규칙은 assign_news 와 같음. 공개 출력은 public_item(제목 비공개)."""
    from .geo_news import norm_key, public_item
    cut, seen, uniq = now - timedelta(days=NEWS_DAYS), set(), []
    for r in sorted(items, key=lambda r: r.get("when") or cut, reverse=True):
        k = norm_key(r.get("title") or "")
        if not k or k in seen or r.get("when") is None or r["when"] < cut or r["when"] > now + timedelta(hours=1):
            continue
        seen.add(k)
        uniq.append(r)
    out: dict[str, list[dict]] = {}
    for a in AREAS:
        rx = re.compile(a["news"])
        hits = [public_item({**r, "via": "검색"}) for r in uniq if _CUE.search(r["title"]) and rx.search(r["title"])][:AREA_NEWS_MAX]
        if hits:
            out[a["id"]] = hits
    return out


def _area_snapshot() -> tuple[dict, dict]:
    """데스크 해석 파일의 지도 스냅샷(2차 보도·검증전)·칸별 해석 → (area_snapshot, area_takes). 없음·깨짐 → 빈 dict."""
    try:
        v = json.loads(VIEWS.read_text(encoding="utf-8"))
        return v.get("area_snapshot") or {}, v.get("area_takes") or {}
    except Exception:  # noqa: BLE001
        return {}, {}


def build_regions(prices: dict, anews: dict[str, list[dict]], snap: dict | None = None) -> dict:
    """reports/realestate.json 'regions' 블록: 권역 정의(groups) + 지도 칸(areas: 값·출처 단계·뉴스) + 지오(assets/realestate_map.json).
    값 우선순위: R-ONE 1차(키 있을 때) → 데스크 2차 보도 스냅샷(views.area_snapshot, 검증전) → 미확인. 숫자를 지어내지 않는다."""
    from .realestate_geo import load_asset
    if snap is None:
        snap = _area_snapshot()[0]
    meta = {k: v for k, v in snap.items() if k.startswith("_")}
    sa, ja = prices.get("sale_areas") or {}, prices.get("jeonse_areas") or {}
    areas = []
    for a in AREAS:
        aid, row = a["id"], {"id": a["id"], "sido": a["sido"], "groups": AREA_GROUPS.get(a["id"], [])}
        r1, j1, s2 = sa.get(aid), ja.get(aid), snap.get(aid)
        if r1 and r1.get("status") == "ok":
            row.update(stage="1차", src="부동산원 R-ONE 주간", week=r1.get("week"), sale_1w=r1.get("chg1w"), sale_4w=r1.get("chg4w"),
                       pos52=r1.get("pos52"), jeonse_1w=(j1 or {}).get("chg1w"))
        elif isinstance(s2, dict) and s2.get("sale_1w") is not None:
            row.update(stage="2차 보도·검증전", src=s2.get("src") or meta.get("_src"), week=s2.get("week") or meta.get("_week"),
                       **{k: s2.get(k) for k in ("sale_1w", "sale_1w_prev", "jeonse_1w", "jeonse_ratio", "rep") if s2.get(k) is not None})
        else:
            row.update(stage="미확인", why=(s2.get("why") if isinstance(s2, dict) else None) or "구별 숫자 미보도·R-ONE 키 대기")
        row["news"] = anews.get(aid, [])
        areas.append(row)
    geo = load_asset()
    return {
        "groups": [{"id": g, "name": n, "members": [m for m, _ in ms]} for g, n, ms in REGIONS],
        "areas": areas,
        "n_valued": sum(1 for r in areas if r["stage"] != "미확인"),
        "unit": "주간 매매가격 변동률 %(부동산원 주간 아파트, 전주 대비) — 전세가율 % 는 보도에 있을 때만",
        "legend": [-0.2, 0.0, 0.1, 0.3],
        "legend_note": "구간 경계(%): ≤−0.2 · −0.2~0 · 0~0.1 · 0.1~0.3 · ≥0.3 — 색과 함께 숫자 표기(색만으로 의미 전달 금지)",
        "geo": geo,
        "geo_note": None if geo else "assets/realestate_map.json 없음 — python -m screener.realestate_geo 로 재생성",
    }


def fetch_news(fetch_text, now: datetime, sleep=None, area_out: dict | None = None) -> tuple[list[dict], list[dict]]:
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
    if area_out is not None:
        area_out.update(area_news(items, now))
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



# ── 국토부 RTMS 실거래(10/24 겸이 "부동산 다 터미널에") — 서울 25개 구 최근 3개월 매매(취소 제외)·전월세(전세=월세 0) 구별 집계 ──
# 엔드포인트·필드·취소 제외 로직 = scripts/probe_deriv_sources.py p_seoul_apt(실호출 검증, docs/realestate/2026-10-24_seoul_trades.md).
# 키(DATA_GO_KR_KEY)는 요청 파라미터로만 쓰고 로그·json·오류 문구에 남기지 않는다(_scrub).
# 호출량 25구×3개월×2API(+페이지) → 하루 1회만(같은 날 재실행은 이전 정상값 재사용).
RTMS_BASE = "https://apis.data.go.kr/1613000/"
RTMS_TRADE = ("RTMSDataSvcAptTradeDev", "getRTMSDataSvcAptTradeDev")
RTMS_RENT = ("RTMSDataSvcAptRent", "getRTMSDataSvcAptRent")
RTMS_ROWS = 1000
RTMS_MAX_PAGES = 10
GU_CODES = {"종로구": "11110", "중구": "11140", "용산구": "11170", "성동구": "11200", "광진구": "11215", "동대문구": "11230",
            "중랑구": "11260", "성북구": "11290", "강북구": "11305", "도봉구": "11320", "노원구": "11350", "은평구": "11380",
            "서대문구": "11410", "마포구": "11440", "양천구": "11470", "강서구": "11500", "구로구": "11530", "금천구": "11545",
            "영등포구": "11560", "동작구": "11590", "관악구": "11620", "서초구": "11650", "강남구": "11680", "송파구": "11710", "강동구": "11740"}
ENTRY_RULE = "진입 난이도(가격만): 하 = 59㎡ 중위 7억 미만 · 중 = 7~12억 · 상 = 12억 이상"


def _scrub(msg: str, key: str | None) -> str:
    """오류 문구에서 서비스키 제거(원문·URL 인코딩·serviceKey= 파라미터 모두)."""
    msg = re.sub(r"(?i)serviceKey=[^&\s'\"]+", "serviceKey=***", str(msg))
    if key:
        for k in {key, urllib.parse.quote(key, safe=""), urllib.parse.quote_plus(key)}:
            msg = msg.replace(k, "***")
    return msg[:160]


def rtms_months(today: date, n: int = 3) -> list[str]:
    """최근 n개 '완결 월'(이번 달 제외 — 신고 기한 30일이라 이번 달은 덜 참). 10/24 → 202607·08·09."""
    y, m, out = today.year, today.month, []
    for _ in range(n):
        m -= 1
        if m == 0:
            y, m = y - 1, 12
        out.append(f"{y}{m:02d}")
    return sorted(out)


def parse_rtms_xml(content: bytes | str) -> tuple[list[dict], int | None]:
    """RTMS XML → (item dict 목록, totalCount). resultCode 가 정상(0/00/000)이 아니면 ValueError(코드·메시지만, 키 없음)."""
    import xml.etree.ElementTree as ET
    root = ET.fromstring(content.encode("utf-8") if isinstance(content, str) else content)
    code = (root.findtext(".//resultCode") or root.findtext(".//returnReasonCode") or "").strip()
    if code and code.strip("0") != "":
        msg = (root.findtext(".//resultMsg") or root.findtext(".//returnAuthMsg") or "").strip()
        raise ValueError(f"RTMS 응답 오류 {code} {msg}"[:120])
    items = [{c.tag: (c.text or "").strip() for c in it} for it in root.iter("item")]
    tc = root.findtext(".//totalCount")
    try:
        total = int(tc) if tc is not None else None
    except ValueError:
        total = None
    return items, total


def _num(s) -> float | None:
    try:
        return float(str(s).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def area_band(a) -> str | None:
    """전용면적 → '59'(55~65㎡) · '84'(80~90㎡) · None."""
    v = _num(a)
    if v is None:
        return None
    return "59" if 55 <= v < 65 else ("84" if 80 <= v < 90 else None)


def is_cancelled(x: dict) -> bool:
    """해제(취소) 거래 — cdealType 값이 있으면(예: 'O') 제외."""
    return bool((x.get("cdealType") or "").strip())


def is_jeonse(x: dict) -> bool:
    """전세 = 월세 0(또는 빈 값)."""
    return (x.get("monthlyRent") or "0").replace(",", "").strip() in ("0", "")


def entry_level(p59: float | None) -> str | None:
    if p59 is None:
        return None
    return "하" if p59 < 7 else ("중" if p59 < 12 else "상")


def summarize_gu(trades: list[dict], rents: list[dict]) -> dict:
    """구 하나의 매매·전세 item → 집계(금액 억 원, 소수 2자리). 매매는 취소 제외, 전세는 월세 0 만."""
    import statistics

    def eok(x, k):
        v = _num(x.get(k))
        return None if v is None else v / 10000

    tr = [x for x in trades if not is_cancelled(x)]
    js = [x for x in rents if is_jeonse(x)]
    p59 = [v for v in (eok(x, "dealAmount") for x in tr if area_band(x.get("excluUseAr")) == "59") if v is not None]
    p84 = sorted(v for v in (eok(x, "dealAmount") for x in tr if area_band(x.get("excluUseAr")) == "84") if v is not None)
    j84 = [v for v in (eok(x, "deposit") for x in js if area_band(x.get("excluUseAr")) == "84") if v is not None]
    md = lambda v: round(statistics.median(v), 2) if v else None  # noqa: E731
    old = sum(1 for x in tr if (_num(x.get("buildYear")) or 9999) < 2000)
    m59, m84, mj = md(p59), md(p84), md(j84)
    return {"n": len(tr), "n_cancel": len(trades) - len(tr), "n_jeonse": len(js),
            "p59": m59, "n59": len(p59), "p84": m84, "n84": len(p84),
            "p84_q1": round(p84[len(p84) // 4], 2) if len(p84) >= 4 else None,
            "j84": mj, "nj84": len(j84),
            "jeonse_ratio": round(mj / m84 * 100) if mj and m84 else None,
            "pre1999": round(old / len(tr) * 100) if tr else None,
            "entry": entry_level(m59)}


# ── 드릴다운(10/26 겸이 "구 클릭하면 동, 동 클릭하면 그 더 세부단위") — 같은 원자료(새 호출 0)로 법정동·단지 집계 → 구별 파일 ──
DETAIL_DIR = REPORT_DIR / "realestate_trades"
DETAIL_REL = "reports/realestate_trades"
DETAIL_RECENT = 3     # 단지별 최근 거래 건수
DETAIL_AREAS = 6      # 단지별 면적 타입 상한(거래 많은 순)


def _deal_date(x: dict) -> str:
    try:
        return f"{int(x.get('dealYear')):04d}-{int(x.get('dealMonth')):02d}-{int(x.get('dealDay')):02d}"
    except (TypeError, ValueError):
        return ""


def summarize_detail(trades: list[dict], rents: list[dict]) -> dict:
    """구 하나의 item → {dongs:[법정동 집계], complexes:[단지 집계]}. 금액 억 원 2자리, 취소 제외·전세=월세 0(summarize_gu 와 같은 정의).
    단지 키 = (법정동, 단지명) — 전월세 API 와 맞추려고 aptSeq 대신 이름(같은 동 같은 이름은 드묾)."""
    import statistics
    md = lambda v: round(statistics.median(v), 2) if v else None  # noqa: E731

    def eok(x, k):
        v = _num(x.get(k))
        return None if v is None else round(v / 10000, 2)

    dong: dict[str, dict] = {}
    cx: dict[tuple, dict] = {}

    def d_of(x):
        nm = (x.get("umdNm") or "").strip() or "미상"
        return dong.setdefault(nm, {"name": nm, "tr": [], "n_cancel": 0, "n_jeonse": 0})

    def c_of(x):
        k = ((x.get("umdNm") or "").strip() or "미상", (x.get("aptNm") or "").strip() or "미상")
        return cx.setdefault(k, {"dong": k[0], "name": k[1], "by": None, "tr": [], "n_cancel": 0, "n_jeonse": 0, "pnu": None})

    from .realestate_coords import make_pnu
    for x in trades:
        d, c = d_of(x), c_of(x)
        if not c["pnu"]:
            c["pnu"] = make_pnu(x)   # 단지 좌표(브이월드 연속지적도) 매칭 키 — realestate_coords.attach_coords
        by = _num(x.get("buildYear"))
        if by and not c["by"]:
            c["by"] = int(by)
        if is_cancelled(x):
            d["n_cancel"] += 1
            c["n_cancel"] += 1
            continue
        if eok(x, "dealAmount") is None:
            continue
        d["tr"].append(x)
        c["tr"].append(x)
    for x in rents:
        if is_jeonse(x):
            d_of(x)["n_jeonse"] += 1
            c = c_of(x)
            c["n_jeonse"] += 1
            by = _num(x.get("buildYear"))
            if by and not c["by"]:
                c["by"] = int(by)
    dongs = []
    for d in dong.values():
        tr = d["tr"]
        p59 = [eok(x, "dealAmount") for x in tr if area_band(x.get("excluUseAr")) == "59"]
        p84 = [eok(x, "dealAmount") for x in tr if area_band(x.get("excluUseAr")) == "84"]
        dongs.append({"name": d["name"], "n": len(tr), "n_cancel": d["n_cancel"], "n_jeonse": d["n_jeonse"],
                      "med": md([eok(x, "dealAmount") for x in tr]), "p59": md(p59), "n59": len(p59), "p84": md(p84), "n84": len(p84),
                      "n_cx": sum(1 for c in cx.values() if c["dong"] == d["name"] and (c["tr"] or c["n_jeonse"] or c["n_cancel"]))})
    dongs.sort(key=lambda r: (-r["n"], r["name"]))
    comps = []
    for c in cx.values():
        tr = sorted(c["tr"], key=lambda x: (_deal_date(x), _num(x.get("floor")) or 0), reverse=True)
        areas: dict[int, list] = {}
        for x in tr:
            a = _num(x.get("excluUseAr"))
            if a is not None:
                areas.setdefault(int(round(a)), []).append(x)
        ar = [{"a": a, "n": len(v), "med": md([eok(x, "dealAmount") for x in v]), "last": eok(v[0], "dealAmount"), "last_d": _deal_date(v[0])}
              for a, v in sorted(areas.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:DETAIL_AREAS]]
        comps.append({"dong": c["dong"], "name": c["name"], "by": c["by"], "n": len(tr), "n_cancel": c["n_cancel"], "n_jeonse": c["n_jeonse"],
                      "med": md([eok(x, "dealAmount") for x in tr]), "last_d": _deal_date(tr[0]) if tr else None, "areas": ar, "pnu": c["pnu"],
                      "recent": [{"d": _deal_date(x), "fl": (x.get("floor") or "").strip() or None, "a": _num(x.get("excluUseAr")),
                                  "p": eok(x, "dealAmount")} for x in tr[:DETAIL_RECENT]]})
    comps.sort(key=lambda r: (r["dong"], -r["n"], r["name"]))
    # 법정동 '가' 묶음(10/26 겸이 OK): '○○동N가' → '○○동'. 기본 화면은 묶음, 누르면 1가~N가로 분리. n·중위는 합친 거래로 다시 계산.
    grp: dict[str, list] = {}
    for d in dong.values():
        grp.setdefault(dong_group_name(d["name"]), []).append(d)
    dong_groups = {}
    for g, ms in grp.items():
        if len(ms) < 2 and not GA_RE.match(ms[0]["name"]):
            continue
        tr = [x for d in ms for x in d["tr"]]
        p59 = [eok(x, "dealAmount") for x in tr if area_band(x.get("excluUseAr")) == "59"]
        p84 = [eok(x, "dealAmount") for x in tr if area_band(x.get("excluUseAr")) == "84"]
        names = sorted(d["name"] for d in ms)
        dong_groups[g] = {"name": g, "members": names, "n": len(tr), "n_cancel": sum(d["n_cancel"] for d in ms),
                          "n_jeonse": sum(d["n_jeonse"] for d in ms), "med": md([eok(x, "dealAmount") for x in tr]),
                          "p59": md(p59), "n59": len(p59), "p84": md(p84), "n84": len(p84),
                          "n_cx": sum(1 for c in cx.values() if c["dong"] in names and (c["tr"] or c["n_jeonse"] or c["n_cancel"]))}
    return {"dongs": dongs, "complexes": comps, "dong_groups": dong_groups}


GA_RE = re.compile(r"^(.+동)\d+가$")


def dong_group_name(name: str) -> str:
    """'문래동3가' → '문래동' (법정동 '가' 묶음). 그 외 이름은 그대로."""
    m = GA_RE.match(name or "")
    return m.group(1) if m else name


def fetch_rtms(get, svc: tuple[str, str], cd: str, ym: str, key: str) -> list[dict]:
    """한 구·한 달·한 API 전 페이지. get(url, params) → bytes. 실패는 예외(호출자가 구 단위로 건너뜀)."""
    out: list[dict] = []
    for page in range(1, RTMS_MAX_PAGES + 1):
        items, total = parse_rtms_xml(get(RTMS_BASE + svc[0] + "/" + svc[1],
                                          {"serviceKey": key, "LAWD_CD": cd, "DEAL_YMD": ym, "numOfRows": str(RTMS_ROWS), "pageNo": str(page)}))
        out += items
        if len(items) < RTMS_ROWS or (total is not None and len(out) >= total):
            break
    return out


def _prev_trades() -> dict | None:
    try:
        return json.loads(OUT.read_text(encoding="utf-8")).get("seoul_trades")
    except Exception:  # noqa: BLE001
        return None


def fetch_seoul_trades(get, key: str | None, today: date, prev: dict | None = None, sleep=None, detail_out: dict | None = None) -> dict:
    """서울 25개 구 RTMS 집계 → reports/realestate.json 'seoul_trades'. 키 없음 → '키 필요'(이전 정상값 있으면 유지).
    같은 날 이미 받은 정상값이 있으면 재호출 안 함(하루 1회). 실패 구는 failed 에 이름·오류 형식만(키 제거)."""
    base = {"unit": "억 원(중위·하위25% = 전용 59㎡ 55~65 · 84㎡ 80~90) · 전세가율 = 84㎡ 전세 중위 ÷ 매매 중위 · 구축 = 1999년 이전 준공 비중(매매 건수)",
            "entry_rule": ENTRY_RULE,
            "src": "국토교통부 아파트 매매(상세)·전월세 실거래가 — 공공데이터포털 apis.data.go.kr (1차, 신고 기준·해제 거래 제외)",
            "label": "표시 전용 · 매매 신호 아님"}
    good = bool(prev) and prev.get("status") in ("ok", "부분")
    # 같은 날 재사용 — 단, 드릴다운 파일이 생기기 전 값(detail_dir 없음)이면 한 번 더 받는다(10/26 배포 당일 1회, 호출 ~200)
    if good and prev.get("asof") == today.isoformat() and (detail_out is None or prev.get("detail_dir")):
        return {**prev, "reused": True}
    if not key:
        if good:
            return {**prev, "reused": True, "why": "DATA_GO_KR_KEY 없음(이 실행 경로) — 이전 수집값 유지"}
        return {"status": "키 필요", "why": "DATA_GO_KR_KEY 없음 — 공공데이터포털 키 등록 필요", **base}
    months = rtms_months(today)
    districts, failed = {}, []
    for gu, cd in GU_CODES.items():
        try:
            tr, rent = [], []
            for ym in months:
                tr += fetch_rtms(get, RTMS_TRADE, cd, ym, key)
                rent += fetch_rtms(get, RTMS_RENT, cd, ym, key)
                if sleep:
                    sleep(0.2)
            districts[gu] = {"code": cd, **summarize_gu(tr, rent)}
            if detail_out is not None:
                det = summarize_detail(tr, rent)
                detail_out[cd] = {"gu": gu, "code": cd, **det}
                districts[gu].update(n_dong=len(det["dongs"]), n_cx=len(det["complexes"]), detail=f"{DETAIL_REL}/{cd}.json")
        except Exception as e:  # noqa: BLE001
            failed.append({"id": gu, "why": _scrub(f"{type(e).__name__}: {e}", key)})
    n_ok = len(districts)
    status = "ok" if n_ok == len(GU_CODES) else ("부분" if n_ok else "실패")
    log.info("부동산 RTMS: 성공 구 %d/%d · 실패 %s", n_ok, len(GU_CODES), ",".join(f["id"] for f in failed) or "없음")
    if status == "실패" and good:
        return {**prev, "reused": True, "why": f"이번 수집 전 구 실패({failed[0]['why'] if failed else ''}) — 이전 값 유지"}
    return {"status": status, "asof": today.isoformat(), "period": f"{months[0]}~{months[-1]}", "months": months,
            "n_ok": n_ok, "n_total": len(GU_CODES), "failed": failed, "districts": districts, **base,
            **({"detail_dir": DETAIL_REL} if detail_out is not None and n_ok else {})}


def write_details(trades: dict, details: dict, out_dir: Path | None = None) -> int:
    """구별 드릴다운 파일 reports/realestate_trades/<구코드>.json (화면이 구를 누를 때만 읽음). 쓴 파일 수."""
    from .guard import write_json
    out_dir = out_dir or DETAIL_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    for cd, d in details.items():
        doc = {"schema": 1, "asof": trades.get("asof"), "period": trades.get("period"), "months": trades.get("months"), **d,
               "unit": "억 원 · 중위 = 취소 제외 매매 · 59㎡ 55~65 · 84㎡ 80~90 · 면적 = 전용㎡ 반올림 · 전세 = 월세 0 건수",
               "src": trades.get("src"), "label": "표시 전용 · 매매 신호 아님"}
        n += bool(write_json(out_dir / f"{cd}.json", doc, separators=(",", ":")))
    return n


def _fetch_bytes(url: str, params: dict | None) -> bytes:
    import requests
    last = None
    for _ in range(2):
        try:
            r = requests.get(url, params=params, timeout=(10, 30))
            r.raise_for_status()
            return r.content
        except Exception as e:  # noqa: BLE001 — 예외 문구엔 URL(키 포함)이 들어갈 수 있어 형식·HTTP 코드만 남김
            last = RuntimeError(f"{type(e).__name__} (HTTP {getattr(getattr(e, 'response', None), 'status_code', '-')})")
    raise last  # type: ignore[misc]


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


def build(fetch_json=None, fetch_text=None, fetch_prices=None, now: datetime | None = None, sleep=None, env=None,
          fetch_bytes=None, prev_trades=None) -> dict | None:
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
        anews: dict = {}
        news, feeds = fetch_news(fetch_text, now, sleep, area_out=anews)
    except Exception as e:  # noqa: BLE001
        news, feeds, anews = [], [], {}
        errors.append(f"뉴스 실패: {e}")
    try:
        details: dict = {}
        trades = fetch_seoul_trades(fetch_bytes or (_fetch_bytes if live else (lambda u, p: b"")), env.get("DATA_GO_KR_KEY"), today,
                                    _prev_trades() if prev_trades is None else (prev_trades or None), sleep, detail_out=details)
        if details and not trades.get("reused"):
            log.info("부동산 RTMS 드릴다운: 구별 파일 %d개", write_details(trades, details))
        if live:   # 단지 좌표(10/26) — 키 없으면 호출 0(노트북 CLI 가 채운 캐시만 붙임), 화면은 동 단위까지
            from .realestate_coords import _get_json, attach_coords
            try:
                attach_coords(DETAIL_DIR, env.get("VWORLD_KEY"), _get_json, today, env.get("VWORLD_DOMAIN"), sleep=sleep)
            except Exception as e:  # noqa: BLE001
                errors.append(_scrub(f"단지 좌표 실패: {e}", env.get("VWORLD_KEY")))
    except Exception as e:  # noqa: BLE001
        trades = {"status": "실패", "why": _scrub(f"RTMS 집계 실패: {e}", env.get("DATA_GO_KR_KEY"))}
        errors.append(trades["why"])
    ok_any = (trades.get("status") in ("ok", "부분") or prices.get("status") in ("ok", "부분") or any(r.get("status") == "ok" for r in rates)
              or any(r.get("status") == "ok" for r in reits) or any(f.get("ok") for f in feeds))
    if not ok_any:
        from .guard import record_stale
        log.warning("부동산: 전 섹션 실패 — 이전 파일 유지")
        record_stale("reports/realestate.json", "전 섹션 실패", today.isoformat(), None)
        return None
    out = {
        "asof": today.isoformat(),
        "generated_at": now.astimezone(KST).strftime("%Y-%m-%d %H:%M KST"),
        "regions": build_regions(prices, anews),
        "region_note": "권역 정의 = 부동산 데스크 사전등록(2026-10-23, 주관) — 상급지: 강남3구·용산 = 시장 통용 묶음(주관). 역사적 근거 = 2023-01-05 규제지역 "
                       "일괄 해제 때 유일하게 남은 4구(뉴시스 2023-01-03, 2차) — 10·15 대책(2025)으로 서울 25개구 전역이 규제지역이 된 뒤로는 규제 기준으로 구분 안 됨 · "
                       "하급지: 시장 통용 '노도강·금관구'(언론 관행) · 경기남부: 부동산원 경부1·2권. 권역 값 = 소속 지역 변동률 단순평균(가중 아님)",
        "prices": prices,
        "rates": rates,
        "reits": reits,
        "news": news,
        "feeds": feeds,
        "stale_axes": sorted(a["id"] for a in news if a.get("stale")),
        "seoul_trades": trades,
        "unavailable": [u for u in UNAVAILABLE if not (u["key"] == "MOLIT_RTMS" and trades.get("status") in ("ok", "부분"))],
        "source_notes": SOURCE_NOTES,
        "errors": errors,
        "label": "표시 전용 · 매매 신호 아님 · 뉴스는 제목 키워드 매칭(해석 아님, 검증전) · 데스크 해석은 reports/views/realestate.json",
        "src": "R-ONE 주간 지수(키 있을 때) · ECOS 월간 · 야후 일봉(1주=5거래일·1개월=21거래일·52주 위치) · Google News 검색 RSS 최근 7일",
    }
    try:   # STANDARD 8절 상단 3칸(묶음 B, 추가만)
        from . import topline_from
        out["top"] = topline_from.realestate(out)
    except Exception as e:  # noqa: BLE001
        log.warning("부동산 top 실패: %s", e)
    from .guard import write_json
    write_json(OUT, out)
    log.info("부동산: 가격 %s · 금리 %d · 리츠 %d · 뉴스 %s", prices.get("status"), len(rates), len(reits),
             " · ".join(f"{a['id']} {len(a['items'])}" for a in news))
    return out


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    build()
