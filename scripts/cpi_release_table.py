"""미 CPI 발표 날짜표 → reports/cpi_releases.json (req-macro-4198c8f8 · 퀀트 event_driven H4·H9 입력)

행 = 발표 1회(2022-01~). 칸: 대상월·발표일(ET)·발표 시각(ET·KST)·실적치(발표 당시 첫 공표 빈티지)·컨센서스·차이.

출처
  - 발표일: ALFRED 빈티지 날짜(https://alfred.stlouisfed.org/series/downloaddata?seid=CPIAUCSL) 중 '새 대상월이 처음 나타난 날'.
    퀀트 BLS 아카이브 파일명(reports/studies/2026-11-10_event_cpi.json cpi_table_2015, 10/21 취득)과 대조해 일치 여부를 date_check 칸에 남긴다.
  - 시각: 08:30 ET [가정: 전 회차 동일 — BLS 일정표 원문 미열람(컨테이너에서 bls.gov 차단)]. KST 는 zoneinfo 로 서머타임 반영.
  - 실적치: ALFRED alfredgraph.csv?vintage_date=<발표일> 의 BLS 지수(CPIAUCSL·CPILFESL 계절조정 → 전월비, CPIAUCNS·CPILFENS 원계열 → 전년비).
    BLS 방식대로 소수 3자리 지수로 % 변화 계산 후 1자리 반올림(half-up). 직전·전년 동월 지수가 없으면 null + 사유.
  - 컨센서스: 무료 1차 출처 없음 → 기본 null·'출처 없음'. 수기 입력은 CONS 사전에만(출처·신뢰도 필수). 지어내기 금지.

실행: python3 scripts/cpi_release_table.py [--dry]   (네트워크: alfred.stlouisfed.org)
"""
from __future__ import annotations

import csv
import io
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "cpi_releases.json"
QUANT = ROOT / "reports" / "studies" / "2026-11-10_event_cpi.json"
ET, KST = ZoneInfo("America/New_York"), ZoneInfo("Asia/Seoul")
START = "2022-01-01"
SERIES = {"hl_sa": "CPIAUCSL", "core_sa": "CPILFESL", "hl_nsa": "CPIAUCNS", "core_nsa": "CPILFENS"}
ALFRED_CSV = "https://alfred.stlouisfed.org/graph/alfredgraph.csv?id={sid}&vintage_date={d}&cosd=2020-01-01"
ALFRED_VD = "https://alfred.stlouisfed.org/series/downloaddata?seid=CPIAUCSL"

# 수기 컨센서스 — 1차 출처가 없으면 넣지 않는다. 키 = 발표일(ET). 값: 전월비 %(계절조정), src, conf(신뢰도)
CONS: dict[str, dict] = {
    "2026-11-10": {"hl_mom": 0.3, "core_mom": 0.2,
                   "src": "2차 속보·애널 digest us_cpi_202610, 1차 아님",
                   "conf": "하(헤드라인)·중(근원)"},
}


def pct(a: float | None, b: float | None) -> float | None:
    """BLS 방식: (a/b−1)×100 을 소수 1자리 half-up. 입력 없으면 None."""
    if a is None or b is None or b == 0:
        return None
    return float(Decimal(str((a / b - 1) * 100)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)) + 0.0   # −0.0 → 0.0


def kst_of(d: str, hhmm: str = "08:30") -> str:
    h, m = map(int, hhmm.split(":"))
    dt = datetime(*map(int, d.split("-")), h, m, tzinfo=ET)
    return dt.astimezone(KST).strftime("%Y-%m-%d %H:%M")


def shift(ym: str, k: int) -> str:
    y, m = map(int, ym.split("-"))
    n = y * 12 + (m - 1) + k
    return f"{n // 12:04d}-{n % 12 + 1:02d}"


def row_for(rel: str, idx: dict[str, dict[str, float]]) -> dict:
    """idx = {키: {'YYYY-MM': 지수}} (발표일 빈티지). 대상월 = 계절조정 헤드라인의 마지막 관측월."""
    ref = max(idx["hl_sa"])
    prv, yago = shift(ref, -1), shift(ref, -12)
    g = lambda k, ym: idx[k].get(ym)  # noqa: E731
    act = {"hl_mom": pct(g("hl_sa", ref), g("hl_sa", prv)), "core_mom": pct(g("core_sa", ref), g("core_sa", prv)),
           "hl_yoy": pct(g("hl_nsa", ref), g("hl_nsa", yago)), "core_yoy": pct(g("core_nsa", ref), g("core_nsa", yago))}
    miss = []
    if g("hl_sa", prv) is None:
        miss.append(f"전월비: 직전월 {prv} 지수 결측")
    if g("hl_nsa", yago) is None:
        miss.append(f"전년비: 전년 동월 {yago} 지수 결측")
    c = CONS.get(rel) or {}
    cons = {"hl_mom": c.get("hl_mom"), "core_mom": c.get("core_mom"), "hl_yoy": c.get("hl_yoy"), "core_yoy": c.get("core_yoy")}
    diff = {k: (round(act[k] - cons[k], 1) if act[k] is not None and cons[k] is not None else None) for k in act}
    return {"ref": ref, "release_et": rel, "time_et": "08:30", "release_kst": kst_of(rel),
            "actual": act, "actual_note": "; ".join(miss) or None,
            "index": {k: g(k, ref) for k in idx},
            "cons": cons, "cons_src": c.get("src") or "출처 없음", "cons_conf": c.get("conf"),
            "diff_vs_cons_pp": diff}


def _get(url: str) -> str:
    import requests
    for i in range(3):
        try:
            r = requests.get(url, timeout=40)
            r.raise_for_status()
            return r.text
        except Exception:  # noqa: BLE001
            if i == 2:
                raise
            time.sleep(2 * (i + 1))
    return ""


def _parse(text: str) -> dict[str, float]:
    out = {}
    for row in list(csv.reader(io.StringIO(text)))[1:]:
        try:
            out[row[0][:7]] = float(row[1])
        except (ValueError, IndexError):
            continue
    return out


def vintages() -> list[str]:
    import re
    return sorted({d for d in re.findall(r"\d{4}-\d{2}-\d{2}", _get(ALFRED_VD)) if START <= d <= str(date.today())})


def build() -> dict:
    vds = vintages()
    def fetch(d):
        return d, {k: _parse(_get(ALFRED_CSV.format(sid=s, d=d))) for k, s in SERIES.items()}
    with ThreadPoolExecutor(4) as ex:
        snap = dict(ex.map(fetch, vds))
    rows, last = [], None
    for d in vds:
        ref = max(snap[d]["hl_sa"]) if snap[d]["hl_sa"] else None
        if ref is None or ref == last:      # 새 대상월이 안 나온 빈티지(계절요인 개정·정정) = 발표일 아님
            continue
        last = ref
        rows.append(row_for(d, snap[d]))
    try:
        q = {r["us"] for r in json.loads(QUANT.read_text(encoding="utf-8")).get("cpi_table_2015", [])}
        qmax = max(q)
    except Exception:  # noqa: BLE001
        q, qmax = set(), ""
    for r in rows:
        r["date_check"] = ("BLS 아카이브 파일명 일치" if r["release_et"] in q else
                           "BLS 아카이브 대조 범위 밖(퀀트 취득 10/21 이후)" if r["release_et"] > qmax else "BLS 아카이브와 불일치 — 확인 필요")
    return {"asof": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "by": "매크로", "req": "req-macro-4198c8f8",
            "src": {"dates": ALFRED_VD, "values": ALFRED_CSV.replace("{sid}", "<CPIAUCSL|CPILFESL|CPIAUCNS|CPILFENS>").replace("{d}", "<release_et>"),
                    "dates_crosscheck": "reports/studies/2026-11-10_event_cpi.json cpi_table_2015 (BLS https://www.bls.gov/bls/news-release/cpi.htm 파일명)",
                    "time": "08:30 ET [가정: 전 회차 동일, BLS 일정표 원문 미열람]", "cons": "기본 '출처 없음' — CONS 수기 입력분만 값"},
            "note": ("실적치 = 발표일 ALFRED 빈티지(첫 공표) 지수로 계산, 이후 개정 미반영. 전월비=계절조정, 전년비=원계열(BLS 헤드라인 관행). "
                     "2025-10 지수는 BLS 미수집(빈칸) → 2025-11 전월비·2026-10 전년비 null. 컨센 대비 차이만 '서프라이즈'로 해석, 직전 대비는 서프라이즈 아님."),
            "cols": {"ref": "대상월", "release_et": "발표일(미 동부)", "time_et": "발표 시각 ET", "release_kst": "발표 시각 KST",
                     "actual": "실적치 % (hl/core × mom 계절조정·yoy 원계열)", "cons": "컨센서스 %(없으면 null)", "diff_vs_cons_pp": "실적−컨센 %p"},
            "rows": rows}


def main() -> int:
    doc = build()
    n_ok = sum(r["date_check"] == "BLS 아카이브 파일명 일치" for r in doc["rows"])
    print(f"발표 {len(doc['rows'])}회 · 아카이브 일치 {n_ok} · 끝 {doc['rows'][-1]['release_et']} {doc['rows'][-1]['actual']}")
    if "--dry" not in sys.argv:
        OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
