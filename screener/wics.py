"""국장 공식 섹터 WICS(FnGuide WiseIndex) 수집 → universe/kr_wics.csv (code, wics_l1, wics_l2, asof). 보드 toss-sectors.

소스 확인(10/21 01:1x, Actions run 39453753347 — 이 컨테이너는 wiseindex 차단): 무료·로그인 없이
  GET https://www.wiseindex.com/Index/GetIndexComponets?ceil_yn=0&dt=YYYYMMDD&sec_cd=<코드>
  → JSON {"info": {TRD_DT, CNT…}, "list": [{IDX_CD, IDX_NM_KOR, CMP_CD, CMP_KOR, SEC_CD, SEC_NM_KOR, WGT…}]}
  sec_cd=G45(대분류 IT) 681종목, sec_cd=G4530(중분류) 은 IDX_NM_KOR='WICS 반도체와반도체장비' 165종목(SEC_NM_KOR 는 대분류 'IT').
중분류 코드 목록을 주는 API 는 확인 못 해서, 대분류 10개 × 중분류 후보(10~90, 10 간격)를 돌려 빈 목록은 버린다(호출 100회, 0.2초 간격).
검증: 중분류 합집합이 대분류 종목을 다 덮지 못하면 그 종목은 wics_l2 빈칸(대분류만) + 로그.
실행: detail(KR) 이 universe 를 쓰기 전에 update_if_stale() — asof 가 마지막 KR 거래일보다 오래됐을 때만(screener.yml 저장 단계가 universe/ 를 커밋).
실패하면 이전 파일을 쓰되 guard.record_stale 로 기록(조용한 대체 금지).
"""
from __future__ import annotations

import csv
import logging
import time
from datetime import date, datetime
from pathlib import Path
from typing import Callable

from .config import UNIVERSE_DIR

log = logging.getLogger(__name__)

URL = "https://www.wiseindex.com/Index/GetIndexComponets"
L1 = {"G10": "에너지", "G15": "소재", "G20": "산업재", "G25": "경기관련소비재", "G30": "필수소비재",
      "G35": "건강관리", "G40": "금융", "G45": "IT", "G50": "커뮤니케이션서비스", "G55": "유틸리티"}
L2_SUFFIX = tuple(range(10, 100, 10))
GAP_SEC = 0.2
PATH = UNIVERSE_DIR / "kr_wics.csv"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}

Getter = Callable[[str, dict], dict | None]   # (url, params) → JSON(dict) 또는 None


def _http_get(url: str, params: dict) -> dict | None:
    import requests
    r = requests.get(url, params=params, headers=UA, timeout=20)
    if r.status_code != 200:
        return None
    try:
        return r.json()
    except ValueError:
        return None


def _rows(j: dict | None) -> list[dict]:
    return [x for x in ((j or {}).get("list") or []) if isinstance(x, dict) and x.get("CMP_CD")]


def _name(x: dict) -> str:
    return str(x.get("IDX_NM_KOR") or "").replace("WICS ", "", 1).strip()


def fetch(dt: date, get: Getter = _http_get, sleep: Callable[[float], None] = time.sleep) -> tuple[list[dict], dict]:
    """dt(거래일) 기준 전 종목 WICS → ([{code, wics_l1, wics_l2}], 통계). 대분류가 하나도 안 오면 빈 목록."""
    ymd = dt.strftime("%Y%m%d")
    l1_of: dict[str, str] = {}
    l2_of: dict[str, str] = {}
    calls = 0
    for c1, n1 in L1.items():
        calls += 1
        j = get(URL, {"ceil_yn": 0, "dt": ymd, "sec_cd": c1})
        for x in _rows(j):
            l1_of[str(x["CMP_CD"]).zfill(6)] = str(x.get("SEC_NM_KOR") or n1)
        sleep(GAP_SEC)
        for s in L2_SUFFIX:
            calls += 1
            j = get(URL, {"ceil_yn": 0, "dt": ymd, "sec_cd": f"{c1}{s}"})
            for x in _rows(j):
                l2_of.setdefault(str(x["CMP_CD"]).zfill(6), _name(x))
            sleep(GAP_SEC)
    out = [{"code": c, "wics_l1": l1, "wics_l2": l2_of.get(c, "")} for c, l1 in sorted(l1_of.items())]
    st = {"calls": calls, "n": len(out), "no_l2": sum(1 for r in out if not r["wics_l2"]), "l2_groups": len(set(l2_of.values()))}
    if st["no_l2"]:
        log.warning("WICS 중분류 못 찾은 종목 %d (대분류만 기록)", st["no_l2"])
    return out, st


def read(path: Path = PATH) -> tuple[str | None, int]:
    if not path.exists():
        return None, 0
    with path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return (rows[0].get("asof") if rows else None), len(rows)


def write(rows: list[dict], asof: str, path: Path = PATH) -> None:
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["code", "wics_l1", "wics_l2", "asof"])
        for r in rows:
            w.writerow([r["code"], r["wics_l1"], r["wics_l2"], asof])
    tmp.replace(path)


MIN_ROWS = 1500   # 코스피+코스닥 상장 ~2,700 중 WICS 편입 — 이보다 적으면 부분 실패로 보고 덮어쓰지 않는다 [가정: 첫 실수집 n 으로 조정]


def update_if_stale(now: datetime | None = None, get: Getter = _http_get, path: Path = PATH,
                    sleep: Callable[[float], None] = time.sleep) -> dict:
    """asof < 마지막 KR 거래일이면 다시 받는다. 반환 {status, asof, n, …}."""
    from . import tradecal
    loc = (now or datetime.now(tradecal.KST)).astimezone(tradecal.KST)
    want = tradecal.prev_session("KR", loc.date()) if loc.hour < 18 \
        else tradecal.session_on_or_before("KR", loc.date())   # 18시 전엔 전 거래일 구성(당일분 확정 전)
    have, n = read(path)
    if have and have >= want.isoformat():
        return {"status": "fresh", "asof": have, "n": n}
    rows, st = [], {}
    for d in (want, tradecal.prev_session("KR", want)):
        try:
            rows, st = fetch(d, get, sleep)
        except Exception as e:  # noqa: BLE001
            log.warning("WICS 수집 실패 %s: %s", d, e)
            rows = []
        if len(rows) >= MIN_ROWS:
            write(rows, d.isoformat(), path)
            log.info("WICS %s: %d종목 · 중분류 %d개 · 중분류 없음 %d · 호출 %d", d, len(rows), st["l2_groups"], st["no_l2"], st["calls"])
            return {"status": "updated", "asof": d.isoformat(), **st}
    from .guard import record_stale
    record_stale(str(path.relative_to(path.parents[1])) if len(path.parents) > 1 else str(path), "WICS 구성", want.isoformat(), have)
    return {"status": "stale", "asof": have, "n": n, "got_rows": len(rows)}
