"""정책금리 시리즈 — 미 연방기금 목표 상·하단(FRED DFEDTARU·DFEDTARL, 키 불필요) + 한은 기준금리(ECOS 722Y001).

산출물 reports/policy_rates.json (MACRO 탭 '기준금리' 칸이 읽음 — req-data-2964da3f).
한은: ECOS_API_KEY 있으면 개인키, 없으면 공개 sample 키(10행 한도, 월 단위). 키 없는 실행에서 이전 값이 있으면 유지.
금통위 일정은 공식 원문을 이 환경에서 못 읽어 채우지 않는다(지어내기 금지) — kr.meeting = '미확인'.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime
from zoneinfo import ZoneInfo

from .config import REPORT_DIR

log = logging.getLogger(__name__)
OUT = REPORT_DIR / "policy_rates.json"
KST = ZoneInfo("Asia/Seoul")
ECOS = "https://ecos.bok.or.kr/api/StatisticSearch/{key}/json/kr/1/10/722Y001/M/{start}/{end}/0101000"
US = (("DFEDTARU", "upper", "연방기금 목표 상단"), ("DFEDTARL", "lower", "연방기금 목표 하단"))


def us_summary(obs: list[tuple[str, float]]) -> dict | None:
    """일별 [(날짜, %)] → 마지막 값·직전 변경(날짜·폭)·최근 변경 이력 5건."""
    if not obs:
        return None
    changes = [(obs[i][0], round(obs[i][1] - obs[i - 1][1], 4)) for i in range(1, len(obs)) if obs[i][1] != obs[i - 1][1]]
    last = changes[-1] if changes else None
    return {"date": obs[-1][0], "value": round(obs[-1][1], 4),
            "last_change": {"date": last[0], "bp": round(last[1] * 100)} if last else None,
            "changes": [{"date": d, "bp": round(c * 100)} for d, c in changes[-5:]]}


def kr_summary(rows: list[dict]) -> dict | None:
    s = []
    for r in rows or []:
        try:
            s.append((str(r["TIME"]), float(r["DATA_VALUE"])))
        except (KeyError, TypeError, ValueError):
            continue
    s.sort()
    if not s:
        return None
    last = s[-1][1]
    prev = s[-2][1] if len(s) > 1 else None
    t = s[-1][0]
    return {"month": f"{t[:4]}-{t[4:6]}", "value": last, "chg1m_bp": None if prev is None else round((last - prev) * 100),
            "recent": [[a, b] for a, b in s[-6:]]}


def display(out: dict) -> dict:
    """화면 표기 — 미국은 목표 '범위'(하단–상단, FRED 일별 기준일), 한국은 단일 기준금리(ECOS 월 시계열 = 월말 값, 일별 아님)."""
    us, kr = out.get("us") or {}, out.get("kr") or {}
    lo, hi = (us.get("lower") or {}).get("value"), (us.get("upper") or {}).get("value")
    d = {}
    if lo is not None and hi is not None:
        d["us"] = f"{lo:.2f}–{hi:.2f}%"
        d["us_basis"] = f"FRED 일별 {(us.get('upper') or {}).get('date', '?')} 기준"
    if kr.get("value") is not None:
        d["kr"] = f"{kr['value']:.2f}%"
        d["kr_basis"] = (f"ECOS 월말 {kr.get('month', '?')} 기준 — 이후 금통위 결정은 다음 달 행에 반영(일별 아님)"
                         + (" · stale" if kr.get("stale") else ""))
    return d


def collect(fred=None, fetch_json=None, env=None, today: date | None = None) -> dict:
    env = os.environ if env is None else env
    today = today or datetime.now(KST).date()
    try:
        old = json.loads(OUT.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        old = {}
    if fred is None:
        from .calendar_ev import _FRED_DOWN, _fred
        _FRED_DOWN.clear()
        fred = _fred
    out = {"asof": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "us": {}, "kr": {}}
    for sid, k, label in US:
        try:
            s = us_summary(fred(sid))
            if s:
                out["us"][k] = {"series": sid, "label": label, **s}
        except Exception as e:  # noqa: BLE001
            log.warning("정책금리 %s 실패: %s", sid, e)
            out["us"][k] = {**(old.get("us", {}).get(k) or {"series": sid, "label": label}), "stale": str(e)[:100]}
    key = env.get("ECOS_API_KEY") or ""
    if fetch_json is None:
        import requests

        def fetch_json(url):
            r = requests.get(url, timeout=20)
            r.raise_for_status()
            return r.json()
    m = today.year * 12 + today.month - 1 - 8   # sample 키 10행 한도 — 최근 9개월만 요청(오래된 쪽부터 잘림)
    start = f"{m // 12}{m % 12 + 1:02d}"
    try:
        url = ECOS.format(key=key or "sample", start=start, end=today.strftime("%Y%m"))
        k = kr_summary(((fetch_json(url) or {}).get("StatisticSearch") or {}).get("row"))
        if k:
            out["kr"] = {"series": "ECOS 722Y001/0101000", "label": "한국은행 기준금리", **k,
                         "key": "개인키" if key else "sample(시험용 공개 키, 월 단위 최근 10행 — 개인키 ECOS_API_KEY 대기)"}
        else:
            raise ValueError("ECOS 응답 없음")
    except Exception as e:  # noqa: BLE001
        log.warning("한은 기준금리 실패: %s", str(e).replace(key, "***") if key else e)
        out["kr"] = {**(old.get("kr") or {}), "stale": "ECOS 실패 — 이전 값 유지" if old.get("kr") else "ECOS 실패"}
    out["display"] = display(out)   # 채권 데스크 검토(req-bonds-6a40b909): 미국 = 범위, 한국 = 단일, 기준일 라벨 분리
    out["kr_meeting"] = "미확인 — 금통위 일정(2026-11·2027) 공식 원문 미열람, calendar.json 미등록"
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(json.dumps(collect(), ensure_ascii=False)[:600])
