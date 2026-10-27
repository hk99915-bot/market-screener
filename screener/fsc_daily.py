"""금융위 V2(data.go.kr) T+1 일일 수집기 — req-data-784ffc43 · req-data-1a3f3978 ①.

대상 7종(10/24 탐침 run 40078360285 전부 200, docs/data_go_kr_apis.md): 주식·주가지수·채권지수·파생상품지수·채권·옵션·주식선물.
금융위 = T+1(기준일 다음 영업일 갱신). 실시간 층(네이버·토스)은 장중, 이 층은 사후 확정값 대조·덮어쓰기용.

**라이선스(req-data-cb6315c2):** 금융위 V2 = 공공누리 제4유형(출처표시·상업적 이용금지·변경금지) + "제3자 무단 제공 및 재배포
엄격 금지" 문구(docs/desk_kb/rounds/2026-10-26/research_realtime_deriv.md §금융위 V2, 2026-10-26 원문 인용). 그래서
- 원자료(행 전체)는 `data/fsc/<api>/<YYYYMMDD>.csv.gz` — `data/*` gitignore 라 공개 저장소에 안 올라간다(Actions 에선 cache 로만 유지).
- 공개 산출물 `reports/fsc_daily_status.json` 에는 **값 없이** 상태·행 수·기준일·지연만 남긴다.
- 파생 요약(ATM IV·PCR 등)의 공개 게시 여부는 오너 결재 전 — `summary_*` 함수는 로컬 원자료에서만 계산하고 공개 파일에 쓰지 않는다.
키 값·요청 URL 은 로그·산출물에 남기지 않는다(예외 종류만).
"""
from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import logging
import os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .config import DATA_DIR, REPORT_DIR

log = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")
B = "https://apis.data.go.kr/1160100"
RAW = DATA_DIR / "fsc"
STATUS = REPORT_DIR / "fsc_daily_status.json"
PAGE = 1000
MAX_PAGES = 40   # 옵션 10/22 20,974행 → 21쪽. 여유 2배.

# 이름 → (경로, 행 식별 키 — 중복 제거·검증용)
APIS: dict[str, tuple[str, tuple[str, ...]]] = {
    "stock": ("/GetStockSecuritiesInfoService_V2/getStockPriceInfo_V2", ("srtnCd",)),
    "index": ("/GetMarketIndexInfoService_V2/getStockMarketIndex_V2", ("idxNm",)),
    "bond_index": ("/GetMarketIndexInfoService_V2/getBondMarketIndex_V2", ("idxNm",)),
    "deriv_index": ("/GetMarketIndexInfoService_V2/getDerivationProductMarketIndex_V2", ("idxNm",)),
    "bond": ("/GetBondSecuritiesInfoService_V2/getBondPriceInfo_V2", ("isinCd",)),
    "option": ("/GetDerivativeProductInfoService_V2/getOptionsPriceInfo_V2", ("srtnCd", "isinCd")),
    "stock_future": ("/GetDerivativeProductInfoService_V2/getStockFuturesPriceInfo_V2", ("srtnCd", "isinCd")),
}
LICENSE = ("금융위원회 data.go.kr V2 — 공공누리 제4유형(출처표시·상업적 이용금지·변경금지), 제3자 재배포 금지 문구. "
           "원자료는 공개 저장소에 올리지 않음(req-data-cb6315c2)")


def parse_items(js: dict) -> tuple[list[dict], int, str]:
    """(행, totalCount, resultCode). 단건 dict 응답도 리스트로."""
    resp = (js or {}).get("response") or {}
    code = str(((resp.get("header") or {}).get("resultCode")) or "")
    body = resp.get("body") or {}
    items = body.get("items") or {}
    items = items.get("item") if isinstance(items, dict) else None
    if isinstance(items, dict):
        items = [items]
    try:
        total = int(body.get("totalCount") or 0)
    except (TypeError, ValueError):
        total = 0
    return items or [], total, code


def _default_get(api: str):
    import requests
    url = B + APIS[api][0]

    def get(params):
        return requests.get(url, params=params, timeout=30).json()
    return get


def fetch_day(api: str, bas: date, key: str, get=None) -> dict:
    """한 API·한 기준일 전 쪽 수집. 반환 {status, rows, total, items}."""
    get = get or _default_get(api)
    rows, page, total, code = [], 1, 0, ""
    try:
        while page <= MAX_PAGES:
            items, total, code = parse_items(get({"serviceKey": key, "resultType": "json", "numOfRows": str(PAGE),
                                                  "pageNo": str(page), "basDt": bas.strftime("%Y%m%d")}))
            rows += items
            if not items or len(rows) >= total:
                break
            page += 1
    except Exception as e:  # noqa: BLE001  (URL 에 키가 있어 메시지 대신 종류만)
        return {"status": "실패", "why": type(e).__name__, "rows": len(rows), "total": total, "items": []}
    if code and code not in ("00", "0"):
        return {"status": "실패", "why": f"resultCode {code}", "rows": 0, "total": total, "items": []}
    if not rows:
        return {"status": "행 없음", "why": "휴장 또는 T+1 미갱신", "rows": 0, "total": total, "items": []}
    st = "ok" if len(rows) >= total else "일부"
    return {"status": st, "rows": len(rows), "total": total, "items": rows}


def raw_path(api: str, bas: date):
    return RAW / api / f"{bas.strftime('%Y%m%d')}.csv.gz"


def save_raw(api: str, bas: date, items: list[dict]) -> None:
    """원자료 행 전체(point-in-time: 받은 날 그대로, 덮어쓰기 대신 수집 시각 열 추가)."""
    if not items:
        return
    cols = sorted({k for r in items for k in r})
    got = datetime.now(KST).strftime("%Y-%m-%dT%H:%M")
    p = raw_path(api, bas)
    p.parent.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols + ["_fetched"], extrasaction="ignore")
    w.writeheader()
    for r in items:
        w.writerow({**r, "_fetched": got})
    with gzip.open(p, "wt", encoding="utf-8") as f:
        f.write(buf.getvalue())


def load_raw(api: str, bas: date) -> list[dict]:
    p = raw_path(api, bas)
    if not p.exists():
        return []
    with gzip.open(p, "rt", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def business_days(today: date, n: int) -> list[date]:
    out, d = [], today
    while len(out) < n:
        d -= timedelta(days=1)
        if d.weekday() < 5:
            out.append(d)
    return out


def run(get_factory=None, env=None, days: int = 3, today: date | None = None, apis: list[str] | None = None,
        redo: bool = False) -> dict:
    """최근 days 영업일 × apis 수집. 이미 받은 날(원자료 있음)은 redo 아니면 건너뜀. 공개 상태 파일엔 값 없음."""
    env = os.environ if env is None else env
    today = today or datetime.now(KST).date()
    apis = apis or list(APIS)
    key = env.get("DATA_GO_KR_KEY") or ""
    st = {"asof": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "source": "금융위 V2 (data.go.kr, T+1)",
          "license": LICENSE, "apis": {}}
    if not key:
        st.update(status="키 대기", why="DATA_GO_KR_KEY 없음(이 실행 경로)")
        _write(st)
        return st
    for api in apis:
        get = get_factory(api) if get_factory else None
        per = []
        for d in business_days(today, days):
            if not redo and raw_path(api, d).exists():
                per.append({"basDt": d.isoformat(), "status": "보유", "rows": len(load_raw(api, d))})
                continue
            r = fetch_day(api, d, key, get)
            if r["items"]:
                save_raw(api, d, r["items"])
            per.append({k: v for k, v in r.items() if k != "items"} | {"basDt": d.isoformat()})
        okd = [x for x in per if x["status"] in ("ok", "보유")]
        st["apis"][api] = {"days": per, "latest_ok": max((x["basDt"] for x in okd), default=None)}
    n_ok = sum(1 for a in st["apis"].values() if a["latest_ok"])
    st["status"] = "ok" if n_ok == len(apis) else ("일부" if n_ok else "실패")
    st["n_ok"], st["n_api"] = n_ok, len(apis)
    _write(st)
    return st


def probe_range(get_factory=None, env=None, dates: list[date] | None = None, apis: list[str] | None = None) -> dict:
    """과거 백필 범위 확인 — 각 API 에 옛 기준일 numOfRows=1 로 totalCount 만. 값 저장 없음."""
    env = os.environ if env is None else env
    key = env.get("DATA_GO_KR_KEY") or ""
    dates = dates or [date(2010, 1, 4), date(2015, 1, 5), date(2018, 1, 2), date(2020, 1, 2), date(2022, 1, 3), date(2024, 1, 2)]
    out = {}
    if not key:
        return {"status": "키 대기"}
    for api in apis or list(APIS):
        get = get_factory(api) if get_factory else _default_get(api)
        row = {}
        for d in dates:
            try:
                _, total, code = parse_items(get({"serviceKey": key, "resultType": "json", "numOfRows": "1", "pageNo": "1",
                                                  "basDt": d.strftime("%Y%m%d")}))
                row[d.isoformat()] = total if (not code or code in ("00", "0")) else f"code {code}"
            except Exception as e:  # noqa: BLE001
                row[d.isoformat()] = type(e).__name__
        oldest = min((k for k, v in row.items() if isinstance(v, int) and v > 0), default=None)
        out[api] = {"totals": row, "oldest_with_rows": oldest}
    return out


def _write(st: dict) -> None:
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    STATUS.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")


# ─── 로컬 요약 (공개 파일에 쓰지 않음 — 결재 전) ───

def _f(x) -> float | None:
    try:
        return float(str(x).replace(",", ""))
    except (TypeError, ValueError):
        return None


def summary_stock_futures(bas: date, names: list[str] | None = None) -> list[dict]:
    """주식선물 기초자산별 미결제약정 합·거래량 합 (req-data-1a3f3978 ① — 삼성전자·SK하이닉스·시총 상위)."""
    rows = load_raw("stock_future", bas)
    agg: dict[str, dict] = {}
    for r in rows:
        nm = str(r.get("itmsNm") or r.get("prdNm") or "")
        base = nm.split(" F ")[0].split("F ")[0].strip() or nm
        if names and not any(n in nm for n in names):
            continue
        a = agg.setdefault(base, {"base": base, "oi": 0.0, "vol": 0.0, "n": 0})
        a["oi"] += _f(r.get("opnint")) or 0
        a["vol"] += _f(r.get("trqu")) or 0
        a["n"] += 1
    return sorted(agg.values(), key=lambda x: -x["oi"])


def summary_options(bas: date, prd_hint: str = "코스피200") -> dict:
    """지수옵션 풋콜 미결제 비율·IV 중앙값(로컬). 행 이름 규칙은 실응답 확인 전 — 콜/풋 판별은 이름의 'C '/'P ' 또는 '콜'/'풋'."""
    rows = [r for r in load_raw("option", bas) if prd_hint in str(r.get("itmsNm") or r.get("prdCtg") or "")]
    call = [r for r in rows if " C " in f" {r.get('itmsNm', '')} " or "콜" in str(r.get("itmsNm", ""))]
    put = [r for r in rows if " P " in f" {r.get('itmsNm', '')} " or "풋" in str(r.get("itmsNm", ""))]
    oi = lambda xs: sum(_f(r.get("opnint")) or 0 for r in xs)  # noqa: E731
    ivs = sorted(v for v in (_f(r.get("iptVlty")) for r in rows) if v)
    return {"n": len(rows), "n_call": len(call), "n_put": len(put),
            "pcr_oi": round(oi(put) / oi(call), 3) if oi(call) else None,
            "iv_median": ivs[len(ivs) // 2] if ivs else None}


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--apis", default="")
    ap.add_argument("--redo", action="store_true")
    ap.add_argument("--probe-range", action="store_true", help="백필 가능 범위만 확인(값 저장 없음)")
    a = ap.parse_args(argv)
    apis = [x for x in a.apis.split(",") if x] or None
    if a.probe_range:
        print("SUMMARY fsc_range", json.dumps(probe_range(apis=apis), ensure_ascii=False))
        return
    st = run(days=a.days, apis=apis, redo=a.redo)
    print("SUMMARY fsc_daily", st.get("status"), {k: (v["latest_ok"], [(x["basDt"], x["status"], x.get("rows")) for x in v["days"]])
                                                  for k, v in st.get("apis", {}).items()})


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
