"""산출물 데이터 계약 (refactor_plan 결정 B — 2026-10-17 실행).

산출물마다 schema_version + 필수 키(+형) + 날짜 키. `guard.write_json` 이 쓰기 직전에 `check()` 를 부르고,
위반이면 **쓰지 않고** 로그 + reports/freshness.json `contract_violation` 기록. 통과하면 schema_version 을 채워 쓴다.
테스트(tests/test_contracts.py)가 같은 계약으로 저장소의 현재 파일을 검사한다 — 필드를 바꾸는 사람은 여기부터 고친다.

왜(10/17): bonds 바스켓 이름 자리에 관측 수(316)가 찍힘, detail_us 수동 실행 날짜 역행 — '성공 = 데이터 맞음' 이 아니었다.
"""
from __future__ import annotations

import fnmatch
from pathlib import Path

# 경로(reports/ 기준, glob) → 계약. date: 날짜 키(None 이면 날짜 없음), date_required: 날짜 값이 비면 위반.
CONTRACTS: dict[str, dict] = {
    "detail/*/_index.json": {"v": 1, "date": "asof", "required": {"asof": str, "symbols": list}},
    "peers_*.json": {"v": 1, "date": "asof", "required": {"asof": str, "rows": list}},
    "momentum_KR.json": {"v": 1, "date": "asof", "required": {"asof": str, "market": str, "n": int, "top": list, "bottom": list}},
    "momentum_US.json": {"v": 1, "date": "asof", "required": {"asof": str, "market": str, "n": int, "top": list, "bottom": list}},
    "sim_signals_*.json": {"v": 1, "date": "asof", "required": {"asof": str, "market": str}},
    "derivs.json": {"v": 1, "date": "date", "required": {"date": str, "asof": str, "spot": (int, float)}},
    "committee.json": {"v": 1, "date": "date", "required": {"asof": str, "date": str, "session": str, "head": list, "verdict": str}},
    "committee_us.json": {"v": 1, "date": "date", "required": {"asof": str, "date": str, "head": list, "verdict": str}},
    "valuation.json": {"v": 1, "date": "asof", "required": {"asof": str, "generated_at": str, "rows": list, "basket": dict}},
    "bonds.json": {"v": 1, "date": "asof", "date_required": False, "required": {"generated_at": str, "us": dict, "kr": dict}},
    "daily_brief.json": {"v": 1, "date": "asof", "required": {"asof": str, "headline": str}},
    "macro_view.json": {"v": 1, "date": "asof", "required": {"asof": str, "rows": list}},
    "japan.json": {"v": 1, "date": "date", "required": {"asof": str, "date": str}},
    # 원자재 트래킹(매크로 10/23): 전부 실패하면 asof=None 이므로 날짜 비어도 허용(rows 의 status='미확인' 이 신호). 화면: MARKET › MACRO (getCommodities)
    "commodities.json": {"v": 1, "date": "asof", "date_required": False, "required": {"generated_at": str, "rows": list}},
    # 지정학 뉴스(데이터 10/23): 공개 RSS 헤드라인 축별 매칭. 화면: MARKET › MACRO 지정학 축 '최근 뉴스' (getGeoNews)
    "geo_news.json": {"v": 1, "date": "asof", "required": {"asof": str, "generated_at": str, "axes": list, "feeds": list}},
    # 부동산 트래킹(부동산 10/23): R-ONE 주간(키 있을 때)·ECOS·리츠·뉴스. 화면: MARKET › 부동산(예정, 설계서 docs/realestate/2026-10-23_tab_design.md)
    "realestate.json": {"v": 1, "date": "asof", "required": {"asof": str, "generated_at": str, "prices": dict, "rates": list,
                                                             "reits": list, "news": list, "unavailable": list}},
    "macro_series.json": {"v": 1, "date": "asof", "required": {"asof": str, "fmt": str, "series": dict}},
    # 매집 스캔(데이터 요청 10/17): 실패 시 asof=None 으로 쓰므로 날짜는 비어도 허용(status='fail' 이 신호). 화면: MARKET › ACCUM (getAccum/getUsAccum)
    "accum.json": {"v": 1, "date": "asof", "date_required": False, "required": {"asof": str, "generated_at": str, "status": str, "n": int}},
    "us_accum.json": {"v": 1, "date": "asof", "date_required": False,
                      "required": {"asof": str, "generated_at": str, "status": str, "n_scanned": int, "hits": list}},
    # 토스 시세 요약(노트북 publish → toss-live 브랜치 live.json, 10/21). 원시 호가·계좌 없음 — tools/toss_md/publish.py assert_public
    "toss_md/live.json": {"v": 1, "date": "asof", "required": {"asof": str, "generated_at": str, "source": str, "date": str,
                                                               "indices": dict, "flows": dict, "fx": dict, "quotes": dict}},
}


def contract_for(path) -> tuple[str, dict] | None:
    p = Path(path).as_posix()
    rel = p.split("/reports/", 1)[1] if "/reports/" in p else p.split("reports/", 1)[-1]
    for pat, c in CONTRACTS.items():
        if fnmatch.fnmatch(rel, pat):
            return pat, c
    return None


def check(path, obj) -> list[str]:
    """위반 목록 (빈 목록 = 통과, 계약 없는 경로도 통과)."""
    hit = contract_for(path)
    if not hit:
        return []
    pat, c = hit
    if not isinstance(obj, dict):
        return [f"{pat}: 최상위가 dict 아님({type(obj).__name__})"]
    errs = []
    for k, t in c["required"].items():
        if k not in obj:
            errs.append(f"{pat}: 필수 키 '{k}' 없음")
        elif obj[k] is not None and (not isinstance(obj[k], t) or isinstance(obj[k], bool)):
            errs.append(f"{pat}: '{k}' 형이 {type(obj[k]).__name__} (기대 {getattr(t, '__name__', t)})")
    dk = c.get("date")
    if dk and c.get("date_required", True):
        from .guard import day
        if day(obj.get(dk)) is None:
            errs.append(f"{pat}: 날짜 키 '{dk}' 값 없음/형식 오류 ({obj.get(dk)!r})")
    sv = obj.get("schema_version")
    if sv is not None and sv != c["v"]:
        errs.append(f"{pat}: schema_version {sv} ≠ 계약 {c['v']}")
    return errs


KR_SERIES = ("KOSPI", "KOSDAQ")   # KR 시장 날짜를 대표하는 시리즈 (앞에서부터 첫 번째로 있는 것)


def series_asof(obj: dict) -> dict:
    """macro_series → {'asof_by': {시리즈: 끝 행 날짜}, 'asof_kr': KOSPI 끝 행 날짜}. 감사 M3(10/17):
    최상위 asof = 전 시리즈 최대 날짜라 24시간 시리즈(BTC·USDKRW)가 토요일 날짜로 끌어올림 → KR 소비자(신선도·16:20 손절선)는 asof_kr 를 본다."""
    by = {}
    for k, rows in (obj.get("series") or {}).items():
        if rows and isinstance(rows[-1], (list, tuple)) and rows[-1]:
            by[k] = str(rows[-1][0])[:10]
    kr = next((by[k] for k in KR_SERIES if k in by), None)
    return {"asof_by": by, "asof_kr": kr}


def stamp(path, obj) -> None:
    """계약이 있으면 schema_version 을 채운다 (쓰기 직전, check 통과 후). macro_series 는 시리즈별 asof 도 채운다(감사 M3)."""
    hit = contract_for(path)
    if hit and isinstance(obj, dict):
        obj["schema_version"] = hit[1]["v"]
        if hit[0] == "macro_series.json":
            obj.update(series_asof(obj))
