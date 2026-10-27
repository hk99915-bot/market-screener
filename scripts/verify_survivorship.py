"""검증 데스크 — 백테스트 가격 창고 생존편향 점검 (req-verify-cb391f74).

사전등록 기준(§0, reports/studies/verify_fsc_survivorship.md 와 같음 — 결과 보기 전 고정):
  ① 창고 자체 점검(키 불필요): data/hist/<kr|us>_YYYY.parquet 에서 마지막 거래일이 창고 끝보다 30일 넘게 이른 종목 = '퇴출'.
     퇴출 0% = 현재 생존 종목만 담은 창고(생존편향 확정) · 퇴출 > 0 = 상장폐지 포함 여부 1차 통과.
  ② 금융위 주식시세정보 V2 대조(DATA_GO_KR_KEY 있을 때): 표본일(각 연도 첫 거래일 2020~2025) 금융위 목록의 6자리 코드 중
     같은 날 창고에 있는 비율 = 수록률. 통과 ≥ 99.0% · 경고 95~99% · 실패 < 95%. 누락 코드 상위 20개를 남긴다.
     금융위 V2 의 과거 제공 범위는 [확인 필요: basDt 하한 — 2020-01 이전 응답 여부, 첫 실호출 때] — 응답 0행 연도는 '범위 밖'.
원 가격 코드(screener.prices·build_hist) 미사용 — parquet 를 직접 읽는다(kb:verify#8).

  python scripts/verify_survivorship.py            # reports/studies/verify_survivorship.json
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
HIST = ROOT / "data" / "hist"
OUT = ROOT / "reports" / "studies" / "verify_survivorship.json"
FSC_URL = "https://apis.data.go.kr/1160100/GetStockSecuritiesInfoService_V2/getStockPriceInfo_V2"
PASS, WARN = 0.99, 0.95
SAMPLE_YEARS = range(2020, 2026)


def exits(last: dict[str, date], gap_days: int = 30) -> dict:
    """종목별 마지막 거래일 → 퇴출 집계."""
    if not last:
        return {"n": 0, "exited": 0, "share": None, "by_year": {}}
    end = max(last.values())
    gone = [s for s, d in last.items() if (end - d).days > gap_days]
    return {"n": len(last), "end": str(end), "exited": len(gone), "share": round(len(gone) / len(last), 4),
            "by_year": dict(sorted(Counter(str(last[s].year) for s in gone).items())),
            "verdict": "생존 종목만(생존편향)" if not gone else "상장폐지 포함(1차 통과)"}


def coverage(fsc: set[str], ours: set[str]) -> dict:
    if not fsc:
        return {"status": "범위 밖(0행)"}
    miss = sorted(fsc - ours)
    cov = 1 - len(miss) / len(fsc)
    return {"n_fsc": len(fsc), "n_ours": len(ours), "coverage": round(cov, 4), "missing": miss[:20], "n_missing": len(miss),
            "status": "통과" if cov >= PASS else ("경고" if cov >= WARN else "실패")}


def hist_last(market: str) -> tuple[dict, dict]:
    last, by_day = {}, {}
    for f in sorted(HIST.glob(f"{market}_[0-9][0-9][0-9][0-9].parquet")):
        d = pl.read_parquet(f, columns=["yf", "date"])
        for s, dt in d.group_by("yf").agg(pl.col("date").max()).iter_rows():
            last[s] = max(last.get(s, dt), dt)
        if market == "kr":
            first = d["date"].min()
            by_day[str(first)] = {str(s).split(".")[0] for s in d.filter(pl.col("date") == first)["yf"]}
    return last, by_day


def fsc_codes(key: str, day: str, get=None) -> set[str]:
    if get is None:
        import requests

        def get(params):
            return requests.get(FSC_URL, params=params, timeout=30).json()
    codes, page = set(), 1
    while page <= 8:
        body = ((get({"serviceKey": key, "resultType": "json", "numOfRows": "1000", "pageNo": str(page),
                      "basDt": day.replace("-", "")}) or {}).get("response") or {}).get("body") or {}
        items = (body.get("items") or {}).get("item") or []
        items = [items] if isinstance(items, dict) else items
        codes |= {str(r.get("srtnCd") or "").lstrip("A") for r in items if len(str(r.get("srtnCd") or "").lstrip("A")) == 6}
        if not items or len(codes) >= int(body.get("totalCount") or 0):
            break
        page += 1
    return codes


def run(env=None, get=None) -> dict:
    env = os.environ if env is None else env
    out = {"asof": str(date.today()), "criteria": {"pass": PASS, "warn": WARN, "gap_days": 30}, "hist": {}, "fsc": {}}
    kr_by_day = {}
    for mk in ("kr", "us"):
        last, by_day = hist_last(mk)
        out["hist"][mk] = exits(last)
        kr_by_day = by_day if mk == "kr" else kr_by_day
    key = env.get("DATA_GO_KR_KEY") or ""
    if not key:
        out["fsc"] = {"status": "키 대기", "why": "DATA_GO_KR_KEY 없음(이 실행 경로)"}
    else:
        for day, ours in sorted(kr_by_day.items()):
            if int(day[:4]) not in SAMPLE_YEARS:
                continue
            try:
                out["fsc"][day] = coverage(fsc_codes(key, day, get), ours)
            except Exception as e:  # noqa: BLE001  (키 담긴 URL 문구 방지 — 예외 종류만)
                out["fsc"][day] = {"status": "실패", "why": type(e).__name__}
    return out


if __name__ == "__main__":
    r = run()
    OUT.write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: (v if k != "hist" else {m: {x: y for x, y in s.items() if x != "by_year"} for m, s in v.items()}) for k, v in r.items()}, ensure_ascii=False))
    sys.exit(0)
