"""VKOSPI(코스피200 변동성지수) 일별 수집 — 금융위 파생상품지수 V2(data.go.kr, DATA_GO_KR_KEY).

req-data-4e390b32. 무키 경로 탐색 결과(2026-10-25): 야후 ^VKOSPI 404 · 네이버 VKOSPI 코드 없음(409) · stooq 접속 거부 → 키 경로만.
이 V2 응답에 변동성지수가 들어 있는지는 10/24 탐침이 이름을 안 찍어 미확인 — 없으면 status='소스에 없음'과 idxNm 목록을 남긴다.
산출: data/deriv/vkospi.csv (date,close,chg_pct) · reports/vkospi.json (상태).
"""
from __future__ import annotations

import csv
import json
import logging
import os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .config import DATA_DIR, REPORT_DIR

log = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")
CSV = DATA_DIR / "deriv" / "vkospi.csv"
STATUS = REPORT_DIR / "vkospi.json"
URL = "https://apis.data.go.kr/1160100/GetMarketIndexInfoService_V2/getDerivationProductMarketIndex_V2"


def is_vkospi(name: str) -> bool:
    n = (name or "").replace(" ", "").upper()
    return "VKOSPI" in n or "코스피200변동성" in n or n in ("변동성지수", "KOSPI200변동성지수")


def parse_items(js: dict) -> list[dict]:
    items = ((((js or {}).get("response") or {}).get("body") or {}).get("items") or {})
    items = items.get("item") if isinstance(items, dict) else None
    if isinstance(items, dict):
        items = [items]
    return items or []


def load() -> dict[str, dict]:
    if not CSV.exists():
        return {}
    with CSV.open(encoding="utf-8") as f:
        return {r["date"]: r for r in csv.DictReader(f)}


def run(get=None, env=None, days: int = 5, today: date | None = None) -> dict:
    """최근 days 영업일(주말 제외) basDt 를 받아 csv 에 병합. 키 없으면 '키 대기'."""
    env = os.environ if env is None else env
    today = today or datetime.now(KST).date()
    key = env.get("DATA_GO_KR_KEY") or ""
    db = load()
    st = {"asof": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "source": "금융위 파생상품지수 V2 (data.go.kr, T+1)"}
    if not key:
        st.update(status="키 대기", why="DATA_GO_KR_KEY 없음(이 실행 경로)")
    else:
        if get is None:
            import requests

            def get(params):
                return requests.get(URL, params=params, timeout=25).json()
        names, found = set(), 0
        d, tried = today, 0
        while tried < days:
            d -= timedelta(days=1)
            if d.weekday() >= 5:
                continue
            tried += 1
            try:
                rows = parse_items(get({"serviceKey": key, "resultType": "json", "numOfRows": "1000", "pageNo": "1", "basDt": d.strftime("%Y%m%d")}))
            except Exception as e:  # noqa: BLE001
                log.warning("VKOSPI %s 실패: %s", d, type(e).__name__)
                continue
            names |= {str(r.get("idxNm", "")) for r in rows}
            for r in rows:
                if is_vkospi(str(r.get("idxNm", ""))):
                    try:
                        db[d.isoformat()] = {"date": d.isoformat(), "close": f"{float(r['clpr']):.2f}", "chg_pct": f"{float(r.get('fltRt') or 0):.2f}"}
                        found += 1
                    except (KeyError, ValueError):
                        pass
        if found:
            st.update(status="ok")
        elif names:
            st.update(status="소스에 없음", why="파생상품지수 V2 응답에 VKOSPI 이름 없음", idxNm_sample=sorted(names)[:40])
        else:
            st.update(status="실패", why="응답 행 0 (키·기준일·T+1 확인)")
    rows = sorted(db.values(), key=lambda r: r["date"])
    if rows:
        CSV.parent.mkdir(parents=True, exist_ok=True)
        with CSV.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["date", "close", "chg_pct"])
            w.writeheader()
            w.writerows(rows)
        st.update(rows=len(rows), first=rows[0]["date"], last=rows[-1]["date"], last_close=float(rows[-1]["close"]))
    else:
        st.update(rows=0)
    STATUS.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    return st


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(json.dumps(run(), ensure_ascii=False)[:500])
