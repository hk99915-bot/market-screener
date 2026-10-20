"""토스 시세 요약(toss-live 브랜치 live.json) 읽기 · 신선도 판정 · 기존 시세에 덮기 (2026-10-21, 보드 toss-md-publish).

노트북 수집기(tools/toss_md/collect.py --publish)가 10분마다 `toss-live` 브랜치에 live.json 을 커밋한다(main 엔 안 씀).
여기서는 raw.githubusercontent 에서 읽어(캐시 최대 5분 → 캐시버스터 쿼리) 신선하면 토스, 아니면 기존 네이버/야후 그대로.

신선도 (화면 tab_market·tab_detail 의 JS 와 같은 규칙 — 바꾸면 둘 다):
- KR 정규장 중: 항목 asof 가 now − MAX_AGE_MIN(20분) 이후여야 신선. (10분 수집 + raw 캐시 5분 + 여유)
- 장 밖: 항목 날짜가 '기대 거래일'(마지막 KR 거래일, 당일 09:00 전이면 전 거래일) 이상이면 신선 = "당일분".
- 수급은 날짜 기준(같은 규칙의 날짜 부분) + 장중엔 문서 generated_at 이 20분 이내.
"""
from __future__ import annotations

import logging
import time as _time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from . import guard, tradecal

log = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")
RAW_URL = "https://raw.githubusercontent.com/hk99915-bot/market-screener/toss-live/live.json"
MAX_AGE_MIN = 20
OVERLAY = {"KOSPI": ("indices", "KOSPI"), "KOSDAQ": ("indices", "KOSDAQ"), "USDKRW": ("fx", "USDKRW")}


def fetch(url: str = RAW_URL, timeout: float = 10.0) -> dict | None:
    """원격 live.json (실패하면 None — 호출부는 기존 소스로 폴백)."""
    try:
        import requests
        r = requests.get(f"{url}?t={int(_time.time())}", timeout=timeout, headers={"Cache-Control": "no-cache"})
        if r.status_code != 200:
            log.info("toss live 없음: HTTP %s", r.status_code)
            return None
        j = r.json()
        return j if isinstance(j, dict) and j.get("source") == "toss" else None
    except Exception as e:  # noqa: BLE001
        log.info("toss live 읽기 실패: %s", type(e).__name__)
        return None


def expected_day(now: datetime) -> date:
    loc = now.astimezone(KST)
    d = tradecal.session_on_or_before("KR", loc.date())
    if d == loc.date() and loc.hour < 9:
        d = tradecal.prev_session("KR", d)
    return d


def fresh_ts(asof, now: datetime, max_age_min: int = MAX_AGE_MIN) -> tuple[bool, str]:
    t = guard.stamp(asof)
    if t is None:
        return False, "asof 없음"
    if tradecal.in_session("KR", now):
        age = (now - t).total_seconds() / 60
        return (age <= max_age_min), f"{age:.0f}분 전"
    exp = expected_day(now).isoformat()
    return (t.strftime("%Y-%m-%d") >= exp), f"{t:%m-%d %H:%M} (기대 {exp} 이후)"


def fresh_flows(doc: dict, f: dict, now: datetime, max_age_min: int = MAX_AGE_MIN) -> tuple[bool, str]:
    d = guard.day(f.get("date"))
    if d is None or d < expected_day(now).isoformat():
        return False, f"수급 날짜 {d} < 기대 {expected_day(now)}"
    if tradecal.in_session("KR", now):
        return fresh_ts(doc.get("generated_at"), now, max_age_min)
    return True, "당일분"


def overlay(items: list[dict], doc: dict | None, now: datetime, max_age_min: int = MAX_AGE_MIN) -> tuple[list[dict], dict]:
    """live.json items 의 KOSPI·KOSDAQ·USDKRW 를 신선한 토스 값으로 바꾼다. 반환: (items, toss 블록).
    등락률(chg)은 토스 전일 종가가 있으면 그것, 없으면 바꾸기 전 항목의 last/(1+chg) 로 구한 전일 종가 기준."""
    blk: dict = {"url": RAW_URL, "used": [], "skipped": {}}
    if not doc:
        blk.update(state="missing", reason="toss-live/live.json 못 읽음 — 기존 소스")
        return items, blk
    blk.update(asof=doc.get("asof"), generated_at=doc.get("generated_at"))
    by = {x.get("key"): x for x in items}
    for key, (sec, sub) in OVERLAY.items():
        v = (doc.get(sec) or {}).get(sub) or {}
        last = v.get("mid") if sec == "fx" else v.get("last")
        ok, why = fresh_ts(v.get("asof"), now, max_age_min) if last else (False, "값 없음")
        if not ok:
            blk["skipped"][key] = why
            continue
        old = by.get(key)
        prev = v.get("prev_close")
        if not prev and old and old.get("last") and old.get("chg") is not None and old["chg"] > -1:
            prev = old["last"] / (1 + old["chg"])
        new = {"key": key, "last": float(last), "chg": (float(last) / prev - 1) if prev else (old or {}).get("chg"),
               "src": "toss", "asof": v.get("asof"), "fallback_src": (old or {}).get("src")}
        if old and old.get("status"):
            new["status"] = old["status"]
        if sec == "fx":
            new["date"] = guard.kst_day(v.get("asof"))
        if old:
            old.clear()
            old.update(new)
        else:
            items.append(new)
        blk["used"].append(key)
    fl = {}
    for mk, f in (doc.get("flows") or {}).items():
        ok, why = fresh_flows(doc, f, now, max_age_min)
        if ok:
            fl[mk] = {k: f.get(k) for k in ("date", "status", "개인", "외국인", "기관", "기타법인", "unit")}
        else:
            blk["skipped"][f"flows_{mk}"] = why
    if fl:
        blk["flows"] = fl
    blk["state"] = "fresh" if blk["used"] else "stale"
    return items, blk


def _get_path(obj, key: str):
    return guard._get(obj, key) if obj is not None else None


def read_value(url: str, key: str, fetcher=None):
    """freshness.py 의 원격 항목(kind=toss_md) 값 읽기 → (값, 오류)."""
    doc = (fetcher or fetch)(url)
    if doc is None:
        return None, "원격 파일 없음/읽기 실패"
    return _get_path(doc, key), None


def check_late(val, now: datetime, it: dict) -> tuple[str, str | None] | None:
    """kind=toss_md 신선도 계약. 창(window, 기본 09:30~15:40) 안: published_at 이 max_age_min 이내.
    창 밖: published_at 날짜 ≥ 기대 거래일(창 시작 전이면 전 거래일). 늦으면 (기대, 실제) 반환."""
    loc = now.astimezone(KST)
    ws, we = (it.get("window") or "09:30-15:40").split("-")
    hm = loc.strftime("%H:%M")
    ts = guard.stamp(val)
    act = ts.strftime("%Y-%m-%d %H:%M") if ts else None
    if tradecal.is_session("KR", loc.date()) and ws <= hm < we:
        age = int(it.get("max_age_min") or 30)
        need = now - timedelta(minutes=age)
        if ts is None or ts < need:
            return f"{need.astimezone(KST):%Y-%m-%d %H:%M} 이후", act
        return None
    d = tradecal.session_on_or_before("KR", loc.date())
    if d == loc.date() and hm < ws:
        d = tradecal.prev_session("KR", d)
    if ts is None or ts.strftime("%Y-%m-%d") < d.isoformat():
        return f"{d.isoformat()} 장중 publish", act
    return None

