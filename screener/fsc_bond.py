"""금융위 채권시세정보 V2(data.go.kr, DATA_GO_KR_KEY, T+1) 국고채 잔존 3년 종목 수익률 ↔ KRX [14017] 국고 3년 대조 — req-bonds-d3eab49e.

공식 기준(채권 데스크 10/28 지정): 국고 3Y 의 공식 값 = KRX [14017] **장 마감 후 확정값**(bonds_hist kr_3Y, bonds.json·committee 가 읽는 값).
금융위 V2 는 개별 종목(지표물 포함) 장내 종가 수익률이라 '만기 3년 고정' 값이 아니다 → 기준이 아니라 **대조군**.
비교 규칙: 이름 '국고' + 이름의 만기 'YYMM' 으로 잔존만기 계산 → 2.5~3.5년 종목 중 3.0년에 가장 가까운 종목의 clprBnfRt 와 같은 날 KRX kr_3Y 차(bp).
|차| ≤ 3bp = 일치(종목·만기 차 허용폭 [가정: 지표물 롤 갭 ≈ 곡선 3Y 부근 기울기 × 잔존 차]), 초과면 목록.
산출: reports/fsc_bond_check.json. 실호출 검증 전 — 필드명(itmsNm·clprBnfRt)은 docs/data_go_kr_apis.md 탐침 기준, 다르면 status '행 없음'으로 드러난다 `[자체연구-C]`.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import date, datetime, timedelta
from statistics import median
from zoneinfo import ZoneInfo

from .config import REPORT_DIR
from .fsc_close import parse_items

log = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")
OUT = REPORT_DIR / "fsc_bond_check.json"
URL = "https://apis.data.go.kr/1160100/GetBondSecuritiesInfoService_V2/getBondPriceInfo_V2"
PAGE = 1000
TOL_BP = 3.0
_MAT = re.compile(r"(\d{2})(\d{2})\s*\(")   # '국고03250-2903(25-1)' → 29년 03월


def maturity(name: str) -> date | None:
    m = _MAT.search(name or "")
    if not m:
        return None
    yy, mm = int(m.group(1)), int(m.group(2))
    if not 1 <= mm <= 12:
        return None
    return date(2000 + yy, mm, 10)   # 국고채 만기일 = 해당 월 10일(관행) `[가정]`


def ktb_3y(rows: list[dict], day: date) -> dict | None:
    """국고채 행 중 잔존 2.5~3.5년, 3.0년에 가장 가까운 종목 + 같은 구간 중앙값."""
    cand = []
    for r in rows:
        nm = str(r.get("itmsNm") or "")
        if "국고" not in nm:
            continue
        mt = maturity(nm)
        try:
            y = float(str(r.get("clprBnfRt")).replace(",", ""))
        except (TypeError, ValueError):
            continue
        if mt is None or not 0 < y < 20:
            continue
        rem = (mt - day).days / 365.25
        if 2.5 <= rem <= 3.5:
            cand.append((abs(rem - 3.0), nm, round(rem, 2), y))
    if not cand:
        return None
    cand.sort()
    _, nm, rem, y = cand[0]
    return {"name": nm, "rem_y": rem, "yield": y, "n_band": len(cand), "band_median": round(median(c[3] for c in cand), 3)}


def compare(fsc: dict, krx: float | None) -> dict:
    if krx is None:
        return {"status": "비교 대상 없음(bonds_hist kr_3Y)"}
    gap = round((fsc["yield"] - krx) * 100, 1)
    return {"status": "ok", "krx_3Y": krx, "gap_bp": gap, "match": abs(gap) <= TOL_BP}


def _krx(day: date) -> float | None:
    try:
        rows = json.loads((REPORT_DIR / "bonds_hist.json").read_text(encoding="utf-8"))["rows"]
    except Exception:  # noqa: BLE001
        return None
    return next((r.get("kr_3Y") for r in rows if r.get("date") == day.isoformat()), None)


def run(get=None, env=None, days: int = 5, today: date | None = None, krx=None) -> dict:
    env = os.environ if env is None else env
    today = today or datetime.now(KST).date()
    krx = krx or _krx
    key = env.get("DATA_GO_KR_KEY") or ""
    st = {"asof": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "source": "금융위 채권시세정보 V2 (data.go.kr, T+1) vs KRX [14017]",
          "rule": f"공식 = KRX [14017] 확정값 · 금융위 = 대조군(잔존 2.5~3.5년 국고 종목, |차| ≤ {TOL_BP:g}bp 일치)", "days": []}
    if not key:
        st.update(status="키 대기", why="DATA_GO_KR_KEY 없음(이 실행 경로)")
    else:
        if get is None:
            import requests

            def get(params):
                return requests.get(URL, params=params, timeout=30).json()
        d, tried = today, 0
        while tried < days:
            d -= timedelta(days=1)
            if d.weekday() >= 5:
                continue
            tried += 1
            rows, page = [], 1
            try:
                while True:
                    items, total = parse_items(get({"serviceKey": key, "resultType": "json", "numOfRows": str(PAGE), "pageNo": str(page), "basDt": d.strftime("%Y%m%d")}))
                    rows += items
                    if not items or len(rows) >= total or page >= 3:
                        break
                    page += 1
            except Exception as e:  # noqa: BLE001  (키가 담긴 URL 문구 방지 — 예외 종류만)
                st["days"].append({"date": d.isoformat(), "status": "실패", "why": type(e).__name__})
                continue
            f = ktb_3y(rows, d)
            if not f:
                st["days"].append({"date": d.isoformat(), "status": "행 없음(휴장·T+1 미갱신·필드명 상이)", "n_rows": len(rows)})
                continue
            st["days"].append({"date": d.isoformat(), "fsc": f, **compare(f, krx(d))})
        okd = [x for x in st["days"] if x.get("status") == "ok"]
        st["status"] = "ok" if okd else "대조 불가"
        if okd:
            st["match_rate"] = round(sum(x["match"] for x in okd) / len(okd), 2)
            st["gap_bp_median"] = median(x["gap_bp"] for x in okd)
    OUT.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    return st


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    r = run()
    print(json.dumps({k: v for k, v in r.items() if k != "days"}, ensure_ascii=False), [(x["date"], x["status"], x.get("gap_bp")) for x in r["days"]])
