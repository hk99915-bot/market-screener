"""금융위 주식시세정보 V2(data.go.kr, DATA_GO_KR_KEY, T+1) 종가 ↔ 우리 일봉(kr_prices) 대조 — req-data-23bdae79 ②.

목적: 우리 종가(야후/pykrx 계열)가 KRX 공식 확정 종가와 같은지 표본 대조. 일치율·불일치 목록만 남기고 FSC 원문 전체는 저장 안 함.
산출: reports/fsc_close_check.json. 비교 종가 = kr_prices(Actions 에선 deriv_hist.yml 이 릴리스 자산을 받음) → 없으면 reports/detail/KR chart 종가(상세 종목만, 공통<2,000 이면 표본 부족). 키 없음/비교 대상 없음/응답 0행은 각각 status 로 구분 — 실호출 검증 전에는 구현·합성 테스트 수준 `[자체연구-C]`.
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
    """srtnCd(단축코드, 'A005930' 또는 '005930') → clpr. 6자리 코드만. 접두 'A' 는 1개만 제거(verify #17 ⑥)."""
    out = {}
    for r in rows:
        code = str(r.get("srtnCd") or "").strip()
        if code[:1] == "A":
            code = code[1:]
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
    bad.sort(key=lambda x: -abs(x["diff_pct"] if x["diff_pct"] is not None else 1e9))  # 큰 차이 먼저 (#17 ③)
    return {"n_fsc": len(fsc), "n_ours": len(ours), "n_common": len(common), "n_match": len(common) - len(bad),
            "mismatch": bad[:20], "n_mismatch": len(bad)}


# 사전등록 기준 reports/studies/verify_fsc_survivorship.md §0-A (결과 보기 전 고정)
MIN_COMMON, MIN_DAYS, PASS_RATE, WARN_RATE, PARTIAL_FRAC = 2000, 5, 0.995, 0.98, 0.9


def verdict(rate: float) -> str:
    return "통과" if rate >= PASS_RATE else ("경고" if rate >= WARN_RATE else "실패")


def _is_session(d: date) -> bool:
    """KRX 영업일(공휴일·임시휴장 포함). 라이브러리 없으면 평일만."""
    try:
        import exchange_calendars as xc
        import pandas as pd
        return bool(xc.get_calendar("XKRX").is_session(pd.Timestamp(d)))
    except Exception:  # noqa: BLE001
        return d.weekday() < 5


_ours_cache: dict = {}


def _detail_closes(day: date) -> dict[str, float]:
    """kr_prices(릴리스 자산) 가 없을 때의 차선 — 저장소에 커밋되는 reports/detail/KR/*.json chart(최근 260일 종가).
    상세 대상 종목만이라 전 종목 대조(§0-A n≥2,000)에는 못 미친다 → 그날은 '표본 부족' 으로 따로 표기."""
    if "detail" not in _ours_cache:
        by: dict[str, dict[str, float]] = {}
        for f in (REPORT_DIR / "detail" / "KR").glob("*.json"):
            try:
                ch = json.loads(f.read_text(encoding="utf-8")).get("chart") or []
            except (OSError, ValueError):
                continue
            for x in ch:
                if x.get("t") and x.get("c") is not None:
                    by.setdefault(x["t"], {})[f.stem] = float(x["c"])
        _ours_cache["detail"] = by
    return _ours_cache["detail"].get(day.isoformat(), {})


def _our_closes(day: date) -> tuple[dict[str, float], str]:
    from . import prices
    df = prices.load_kr(raw=True)
    if len(df):
        d = df.filter(df["date"] == day)
        o = {str(y).split(".")[0]: float(c) for y, c in zip(d["yf"], d["close"]) if c is not None}
        if o:
            return o, "kr_prices"
    return _detail_closes(day), "reports/detail"


def _get_day(get, key: str, d: date, retries: int, sleep) -> list[dict]:
    """하루치 전 페이지. ReadTimeout 등은 retries 회까지 다시(#17 ②) — 마지막에도 실패면 예외 그대로."""
    rows, page = [], 1
    while True:
        for k in range(retries + 1):
            try:
                items, total = parse_items(get({"serviceKey": key, "resultType": "json", "numOfRows": str(PAGE), "pageNo": str(page), "basDt": d.strftime("%Y%m%d")}))
                break
            except Exception:  # noqa: BLE001
                if k >= retries:
                    raise
                sleep(2 * (k + 1))
        rows += items
        if not items or len(rows) >= total or page >= 8:
            return rows
        page += 1


def run(get=None, env=None, days: int = 10, today: date | None = None, ours=None, retries: int = 2, sleep=None, is_session=None) -> dict:
    import time
    env = os.environ if env is None else env
    today = today or datetime.now(KST).date()
    sleep = sleep or time.sleep
    is_session = is_session or _is_session
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
            if not is_session(d):
                continue  # 주말·공휴일은 조회·창 소진 없이 건너뜀(#17 ⑤)
            tried += 1
            try:
                rows = _get_day(get, key, d, retries, sleep)
            except Exception as e:  # noqa: BLE001  (키가 담긴 URL 문구 방지 — 예외 종류만)
                st["days"].append({"date": d.isoformat(), "status": "실패", "why": type(e).__name__})
                continue
            fsc = fsc_closes(rows)
            if not fsc:
                st["days"].append({"date": d.isoformat(), "status": "T+1 미갱신(영업일인데 행 0)"})
                continue
            o = ours(d)
            o, src = o if isinstance(o, tuple) else (o, "kr_prices")
            if not o:
                st["days"].append({"date": d.isoformat(), "status": "비교 대상 없음", "n_fsc": len(fsc)})
                continue
            st["days"].append({"date": d.isoformat(), "status": "ok", "ours_src": src, **compare(fsc, o)})
        # 부분 적재: n_fsc 가 이웃 일들 중앙값의 90% 미만이면 표본에서 뺌(#16)
        ns = sorted(x["n_fsc"] for x in st["days"] if x.get("n_fsc"))
        med = ns[len(ns) // 2] if ns else 0
        for x in st["days"]:
            if x.get("status") == "ok":
                if med and x["n_fsc"] < PARTIAL_FRAC * med:
                    x["status"] = "부분 적재 의심(n_fsc<중앙값 90%)"
                elif x["n_common"] < MIN_COMMON:
                    x["status"] = f"표본 부족(공통 {x['n_common']}<{MIN_COMMON})"
        okd = [x for x in st["days"] if x.get("status") == "ok"]
        ref = [x for x in st["days"] if x.get("n_common")]   # 참고용: 기준 미달 일 포함
        if ref:
            st["match_rate_all"] = round(sum(x["n_match"] for x in ref) / max(1, sum(x["n_common"] for x in ref)), 4)
        if len(okd) >= MIN_DAYS:
            st["status"] = "ok"
            st["match_rate"] = round(sum(x["n_match"] for x in okd) / max(1, sum(x["n_common"] for x in okd)), 4)
            st["verdict"] = verdict(st["match_rate"])
        elif ref:
            st["status"] = f"표본 부족(기준 충족 {len(okd)}일 < {MIN_DAYS}일 — 판정 보류, match_rate_all 은 참고)"
        else:
            st["status"] = "대조 불가"
    OUT.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    return st


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    r = run()
    print(json.dumps({k: v for k, v in r.items() if k != "days"}, ensure_ascii=False), [(x["date"], x["status"][:12], x.get("n_common"), x.get("n_mismatch")) for x in r["days"]])
