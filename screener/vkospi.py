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


# 10/27 req-data-cb6315c2 점검 중 발견: 옛 부분일치('코스피200변동성' 포함)가 VKOSPI 가 아닌 지수(종가 786~810, 같은 날
# 대표 IV 45~52)를 잡아 10/19~10/26 6행을 잘못 적재. → 이름 정확 일치 + 파생형 단어 제외 + 값 범위(VKOSPI 는 % 단위 변동성).
_EXACT = {"VKOSPI", "코스피200변동성지수", "KOSPI200변동성지수", "KOSPI200VOLATILITYINDEX", "변동성지수"}
_EXCLUDE = ("선물", "타겟", "TARGET", "레버리지", "인버스", "커버드", "콜", "풋", "위클리")
LO, HI = 5.0, 150.0   # [가정: VKOSPI 는 % 단위 변동성이라 5~150 밖이면 다른 지수(가격형)로 본다]


def is_vkospi(name: str) -> bool:
    n = (name or "").replace(" ", "").upper()
    if any(w.upper() in n for w in _EXCLUDE):
        return False
    return n in _EXACT or n.endswith("VKOSPI") or n == "KOSPI200VKOSPI"


def plausible(v: float) -> bool:
    return LO <= v <= HI


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
        matched, rejected, ambiguous = set(), set(), set()
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
            cands = []
            for r in rows:
                nm = str(r.get("idxNm", ""))
                if not is_vkospi(nm):
                    continue
                try:
                    v = float(str(r["clpr"]).replace(",", ""))
                except (KeyError, ValueError):
                    continue
                if plausible(v):
                    cands.append((nm, v, r))
                else:
                    rejected.add(f"{nm}={v:g}")
            if len(cands) == 1:
                nm, v, r = cands[0]
                matched.add(nm)
                db[d.isoformat()] = {"date": d.isoformat(), "close": f"{v:.2f}", "chg_pct": f"{float(r.get('fltRt') or 0):.2f}"}
                found += 1
            elif len(cands) > 1:
                ambiguous.add(" | ".join(sorted(c[0] for c in cands)))
        if rejected:
            st["rejected"] = sorted(rejected)[:10]
        if ambiguous:
            st["ambiguous"] = sorted(ambiguous)[:5]
        if found:
            st.update(status="ok", idxNm=sorted(matched))
        elif ambiguous:
            st.update(status="후보 여러 개", why="VKOSPI 후보 이름이 둘 이상 — 이름 확인 전 적재 안 함", idxNm_sample=sorted(names)[:40])
        elif names:
            st.update(status="소스에 없음", why="파생상품지수 V2 응답에 VKOSPI 이름 없음", idxNm_sample=sorted(names)[:40])
        else:
            st.update(status="실패", why="응답 행 0 (키·기준일·T+1 확인)")
    bad = [k for k, r in db.items() if not plausible(float(r.get("close") or 0))]
    for k in bad:   # 과거 오적재(범위 밖) 정리 — 조용히 지우지 않고 상태에 남김
        db.pop(k)
    if bad:
        st["purged"] = {"n": len(bad), "why": "VKOSPI 범위(5~150) 밖 — 다른 지수 오매칭 행 제거", "dates": sorted(bad)[:10]}
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
        if CSV.exists():
            CSV.unlink()
    st["license"] = "공공누리 제4유형(출처표시·상업적 이용금지·변경금지, 제3자 재배포 금지 문구) — 공개 게시 범위 오너 결재 대기(req-data-cb6315c2)"
    STATUS.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    return st


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(json.dumps(run(), ensure_ascii=False)[:500])
