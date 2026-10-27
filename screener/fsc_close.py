"""금융위 주식시세정보 V2(data.go.kr, DATA_GO_KR_KEY, T+1) 종가 ↔ 우리 일봉(kr_prices) 대조 — req-data-23bdae79 ②.

목적: 우리 종가(야후/pykrx 계열)가 KRX 공식 확정 종가와 같은지 표본 대조. 일치율·불일치 목록만 남기고 FSC 원문 전체는 저장 안 함.
산출: reports/fsc_close_check.json. 키 없음/비교 대상 없음/응답 0행은 각각 status 로 구분 — 실호출 검증 전에는 구현·합성 테스트 수준 `[자체연구-C]`.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .config import REPORT_DIR

log = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")
OUT = REPORT_DIR / "fsc_close_check.json"
URL = "https://apis.data.go.kr/1160100/GetStockSecuritiesInfoService_V2/getStockPriceInfo_V2"
PAGE = 1000


def parse_items(js: dict) -> tuple[list[dict], int]:
    body = ((js or {}).get("response") or {}).get("body") or {}
    items = (body.get("items") or {})
    items = items.get("item") if isinstance(items, dict) else None
    if isinstance(items, dict):
        items = [items]
    try:
        total = int(body.get("totalCount") or 0)
    except (TypeError, ValueError):
        total = 0
    return items or [], total


def fsc_closes(rows: list[dict]) -> dict[str, float]:
    """srtnCd(단축코드, 'A005930' 또는 '005930') → clpr. 6자리 코드만."""
    out = {}
    for r in rows:
        code = str(r.get("srtnCd") or "").strip().lstrip("A")
        try:
            if len(code) == 6:
                out[code] = float(str(r["clpr"]).replace(",", ""))
        except (KeyError, ValueError):
            pass
    return out


def compare(fsc: dict[str, float], ours: dict[str, float]) -> dict:
    common = sorted(set(fsc) & set(ours))
    # 공공누리 4유형(재배포 금지) — 금융위 원값(clpr)은 공개 산출물에 남기지 않고 차이율만 (req-data-cb6315c2, 10/27)
    bad = [{"code": c, "ours": ours[c], "diff_pct": round((ours[c] / fsc[c] - 1) * 100, 3) if fsc[c] else None}
           for c in common if abs(fsc[c] - ours[c]) > 0.5]
    return {"n_fsc": len(fsc), "n_ours": len(ours), "n_common": len(common), "n_match": len(common) - len(bad),
            "mismatch": bad[:20], "n_mismatch": len(bad)}


def _our_closes(day: date) -> dict[str, float]:
    from . import prices
    df = prices.load_kr(raw=True)
    if not len(df):
        return {}
    d = df.filter(df["date"] == day)
    return {str(y).split(".")[0]: float(c) for y, c in zip(d["yf"], d["close"]) if c is not None}


def run(get=None, env=None, days: int = 10, today: date | None = None, ours=None) -> dict:
    env = os.environ if env is None else env
    today = today or datetime.now(KST).date()
    ours = ours or _our_closes
    key = env.get("DATA_GO_KR_KEY") or ""
    st = {"asof": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "source": "금융위 주식시세정보 V2 (data.go.kr, T+1)", "days": []}
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
                    if not items or len(rows) >= total or page >= 8:
                        break
                    page += 1
            except Exception as e:  # noqa: BLE001  (키가 담긴 URL 문구 방지 — 예외 종류만)
                st["days"].append({"date": d.isoformat(), "status": "실패", "why": type(e).__name__})
                continue
            fsc = fsc_closes(rows)
            if not fsc:
                st["days"].append({"date": d.isoformat(), "status": "행 없음(휴장 또는 T+1 미갱신)"})
                continue
            o = ours(d)
            st["days"].append({"date": d.isoformat(), "status": "ok" if o else "비교 대상 없음(kr_prices)", **compare(fsc, o)})
        okd = [x for x in st["days"] if x.get("status") == "ok"]
        st["status"] = "ok" if okd else "대조 불가"
        if okd:
            st["match_rate"] = round(sum(x["n_match"] for x in okd) / max(1, sum(x["n_common"] for x in okd)), 4)
    OUT.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    return st


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    r = run()
    print(json.dumps({k: v for k, v in r.items() if k != "days"}, ensure_ascii=False), [(x["date"], x["status"], x.get("n_common"), x.get("n_mismatch")) for x in r["days"]])
