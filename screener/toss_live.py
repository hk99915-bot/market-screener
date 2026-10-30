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
        if ok and sec == "indices" and tradecal.in_session("KR", now) and (by.get(key) or {}).get("src") in ("naver", "krx"):
            # 10/24 겸이 "지수도 네이버로": 정규장 지수 1차 = 네이버. 토스는 네이버(→KRX)가 실패해 항목이 없을 때만 폴백
            # (10/21 '장중 지수 토스로 덮기' 대체). 네이버 지연은 응답에 시각이 없어 판정 못 함 → 실패 시 폴백만.
            ok, why = False, "정규장 — 네이버 1차(토스 폴백 대기)"
        if ok and sec == "indices" and not tradecal.in_session("KR", now):
            # 장 밖(마감 뒤·개장 전)엔 지수를 토스로 덮지 않는다 — 동시호가 15:20~15:30 값 고정으로 10/21·22·23 15:34 KRX 종가와
            # −13.1/+6.2/−3.2pt 차(10/22 5,539.94 = 토스), req-dev-a4d03413 ②. 장 밖 지수 = 네이버→KRX 종가.
            ok, why = False, "장 밖 — KRX 종가 우선(토스 지수 덮기 금지)"
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
    nxt = nxt_indices(doc, now, max_age_min)   # NXT 시간대 지수 = 토스, 정규장 값과 별도 키(종가·일봉에 안 섞음)
    if nxt:
        blk["nxt"] = nxt
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


# NXT(넥스트레이드) 시간대 — 프리 08:00~08:50 · 애프터 15:30~20:00 (KST, NXT 공시 기준 [확인 필요: 넥스트레이드 공식 거래시간 공지 재확인, 2026-10-30])
NXT_SESSIONS = (("nxt_pre", "08:00", "08:50"), ("nxt_after", "15:30", "20:00"))


def nxt_session(now: datetime) -> str | None:
    loc = now.astimezone(KST)
    if not tradecal.is_session("KR", loc.date()):
        return None
    hm = loc.strftime("%H:%M")
    return next((k for k, a, b in NXT_SESSIONS if a <= hm < b), None)


def nxt_indices(doc: dict | None, now: datetime, max_age_min: int = MAX_AGE_MIN) -> dict:
    """10/24 겸이 "NXT 지수는 토스로": NXT 시간대에만 토스 KOSPI·KOSDAQ 을 {키: {last, chg, asof, session, src:'toss'}} 로.
    live.json 'nxt' 별도 키 — 정규장 items(KRX 종가)·일봉에는 절대 합치지 않는다. 신선(asof 가 max_age_min 이내)할 때만."""
    ses = nxt_session(now)
    if not ses or not doc:
        return {}
    out = {}
    for key in ("KOSPI", "KOSDAQ"):
        v = (doc.get("indices") or {}).get(key) or {}
        t = guard.stamp(v.get("asof"))
        if not v.get("last") or t is None or (now - t).total_seconds() / 60 > max_age_min:
            continue
        pc = v.get("prev_close")
        out[key] = {"last": float(v["last"]), "chg": (float(v["last"]) / pc - 1) if pc else None, "asof": v.get("asof"),
                    "session": ses, "src": "toss"}
    return out


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
    # 날짜만 보면 장 전(04:10) publish 가 전날 값을 싣고도 '오늘분'으로 통과한다(10/30 04:10 뒤 멈춤 → 20:54 late 0).
    # 기대 거래일의 창 시작(09:30) 이후 publish 여야 그날 장중분.
    h, m = (int(x) for x in ws.split(":"))
    need = datetime(d.year, d.month, d.day, h, m, tzinfo=KST)
    if ts is None or ts < need:
        return f"{d.isoformat()} 장중 publish", act
    return None

