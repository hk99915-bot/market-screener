"""한은 ECOS 시장금리(일별) 817Y002 — 국고채 3년(010200000)·10년(010210000) 일별 백필 + KRX [14017] 대조.

req-data-76cf9141(ECOS 국고 일별 백필, PM 10/26: req-data-a555e088 2021-12~2022-12 구간 먼저) · req-data-1fd3dc04(국고 3Y 출처 대조).
- 키: ECOS_API_KEY(개인키) 없으면 공개 'sample' 키 — 한 번에 10행 한도라 14일(≤10영업일) 창으로 나눠 부른다.
- 산출: data/hist/kr_ktb_ecos_daily.csv (date, ktb3y, ktb10y, src) — 기존 행은 덮지 않고 새 날짜만 추가(point-in-time).
  reports/ktb_ecos_check.json — bonds_hist(KRX [14017]) 와 같은 날 대조(차이 bp 분포).
- 출처 표기: '한국은행 경제통계시스템(ECOS)'. ECOS 이용약관 재배포 조항 원문은 미열람 `[확인 필요: ECOS 이용약관 재배포 조항, 2026-11-03, 데이터]`.
- ECOS '국고채(3년)' = 금융투자협회 최종호가수익률을 한은이 옮긴 값으로 알려짐 `[가정: 원천 기관 표기 원문 미대조]`.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .config import DATA_DIR, REPORT_DIR

log = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")
CSV = DATA_DIR / "hist" / "kr_ktb_ecos_daily.csv"
CHECK = REPORT_DIR / "ktb_ecos_check.json"
URL = "https://ecos.bok.or.kr/api/StatisticSearch/{key}/json/kr/1/{n}/817Y002/D/{s}/{e}/{item}"
ITEMS = {"ktb3y": "010200000", "ktb10y": "010210000"}
FIELDS = ["date", "ktb3y", "ktb10y", "src"]


def parse(js: dict) -> dict[str, float]:
    rows = ((js or {}).get("StatisticSearch") or {}).get("row") or []
    out = {}
    for r in rows:
        t = str(r.get("TIME") or "")
        try:
            if len(t) == 8:
                out[f"{t[:4]}-{t[4:6]}-{t[6:]}"] = float(r["DATA_VALUE"])
        except (KeyError, TypeError, ValueError):
            pass
    return out


def windows(start: date, end: date, span: int) -> list[tuple[date, date]]:
    out, s = [], start
    while s <= end:
        e = min(end, s + timedelta(days=span - 1))
        out.append((s, e))
        s = e + timedelta(days=1)
    return out


def load() -> dict[str, dict]:
    if not CSV.exists():
        return {}
    with CSV.open(encoding="utf-8") as f:
        return {r["date"]: r for r in csv.DictReader(f)}


def save(db: dict[str, dict]) -> None:
    CSV.parent.mkdir(parents=True, exist_ok=True)
    with CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for k in sorted(db):
            w.writerow({c: db[k].get(c, "") for c in FIELDS})


def backfill(start: date, end: date, fetch_json=None, env=None) -> dict:
    env = os.environ if env is None else env
    key = env.get("ECOS_API_KEY") or "sample"
    span, n = (14, 10) if key == "sample" else (3650, 10000)
    if fetch_json is None:
        import requests

        def fetch_json(url):
            return requests.get(url, timeout=20).json()
    db = load()
    got: dict[str, dict] = {}
    errs = []
    for col, item in ITEMS.items():
        for s, e in windows(start, end, span):
            try:
                vals = parse(fetch_json(URL.format(key=key, n=n, s=s.strftime("%Y%m%d"), e=e.strftime("%Y%m%d"), item=item)))
            except Exception as ex:  # noqa: BLE001
                errs.append(f"{col} {s}: {type(ex).__name__}")
                continue
            for d, v in vals.items():
                got.setdefault(d, {"date": d, "src": "ECOS 817Y002"})[col] = f"{v:.3f}"
    added = 0
    for d, r in got.items():
        if d not in db:
            db[d] = r
            added += 1
        else:   # 기존 행은 값 유지, 빈 칸만 채움
            for c in ("ktb3y", "ktb10y"):
                if not db[d].get(c) and r.get(c):
                    db[d][c] = r[c]
    if db:
        save(db)
    return {"key": "개인키" if key != "sample" else "sample", "range": [start.isoformat(), end.isoformat()],
            "fetched_days": len(got), "added": added, "rows": len(db), "errors": errs[:10], "n_errors": len(errs)}


def reconcile(krx_rows: list[dict] | None = None) -> dict:
    """ECOS 국고 3·10Y vs KRX [14017](reports/bonds_hist.json kr_3Y·kr_10Y) 같은 날 차이(bp)."""
    if krx_rows is None:
        p = REPORT_DIR / "bonds_hist.json"
        krx_rows = json.loads(p.read_text(encoding="utf-8")).get("rows", []) if p.exists() else []
    ecos = load()
    out = {"asof": datetime.now(KST).strftime("%Y-%m-%d %H:%M"),
           "what": "국고채 수익률 출처 대조 — ECOS 817Y002(한은) vs KRX [14017](bonds_hist)",
           "unit": "bp = (ECOS − KRX) × 100"}
    for col, kcol in (("ktb3y", "kr_3Y"), ("ktb10y", "kr_10Y")):
        diffs = []
        for r in krx_rows:
            e = ecos.get(r.get("date"), {}).get(col)
            if e and r.get(kcol) is not None:
                diffs.append((r["date"], round((float(e) - float(r[kcol])) * 100, 1)))
        if not diffs:
            out[col] = {"n": 0}
            continue
        ab = sorted(abs(x[1]) for x in diffs)
        out[col] = {"n": len(diffs), "from": diffs[0][0], "to": diffs[-1][0],
                    "abs_median_bp": ab[len(ab) // 2], "abs_max_bp": ab[-1],
                    "n_over_1bp": sum(1 for x in ab if x > 1.0), "largest": sorted(diffs, key=lambda x: -abs(x[1]))[:5]}
    CHECK.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2021-12-01")
    ap.add_argument("--end", default="2022-12-31")
    ap.add_argument("--reconcile", action="store_true")
    a = ap.parse_args(argv)
    r = backfill(date.fromisoformat(a.start), date.fromisoformat(a.end))
    print("SUMMARY ecos_ktb", json.dumps(r, ensure_ascii=False))
    if a.reconcile:
        print("SUMMARY ecos_ktb_check", json.dumps(reconcile(), ensure_ascii=False)[:800])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
