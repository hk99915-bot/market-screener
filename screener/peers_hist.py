"""peers_{시장}.json 종목별 drv·r20·r1 거래일별 누적 (req-dev-808893e4 → 묶음 C ④, 퀀트 H_b 재판정용).

왜: peers_US.json 은 매 실행 덮어써서 과거 값이 git 이력에만 있음 → 미장 후보 Δdrv 정렬(reports/studies/2026-10-23_us_long_sort.md) 재판정 불안정.
저장: reports/peers_hist/<시장>.csv  (asof,s,drv,r20,r1) — 텍스트 append 라 git 이 차이만 저장(parquet 통째 누적 회피, repo-size-stage1 교훈).
같은 asof 가 다시 오면 그 날짜 행을 새 값으로 교체(하루 여러 번 실행 대비). reports/ 는 screener·briefing 저장 단계가 이미 git add 함.
백필: python -m screener.peers_hist --backfill US   (git log 의 reports/peers_US.json 판별로, asof 마다 마지막 커밋 값 — 얕은 클론이면 보이는 구간만)
"""
from __future__ import annotations

import csv
import io
import json
import logging
import subprocess
import sys

from .config import REPORT_DIR

log = logging.getLogger(__name__)
COLS = ("asof", "s", "drv", "r20", "r1")


def path(market: str):
    return REPORT_DIR / "peers_hist" / f"{market}.csv"


def _num(v):
    return "" if v is None else f"{float(v):.4f}".rstrip("0").rstrip(".") if v == v else ""


def _read(fp) -> list[dict]:
    if not fp.exists():
        return []
    with open(fp, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def append(market: str, asof: str, rows: list[dict], fp=None) -> int:
    """rows = peers_*.json rows. asof 행을 교체 저장 → 저장한 행 수. 날짜 정렬 유지(백필이 섞여도)."""
    fp = fp or path(market)
    asof = str(asof)[:10]
    new = [{"asof": asof, "s": r["s"], "drv": _num(r.get("drv")), "r20": _num(r.get("r20")), "r1": _num(r.get("r1"))}
           for r in rows if r.get("s")]
    if not new:
        return 0
    old = [r for r in _read(fp) if r["asof"] != asof]
    allr = sorted(old + new, key=lambda r: (r["asof"], r["s"]))
    fp.parent.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=COLS, lineterminator="\n")
    w.writeheader()
    w.writerows(allr)
    fp.write_text(buf.getvalue(), encoding="utf-8")
    return len(new)


def backfill(market: str) -> dict:
    """git 이력의 reports/peers_<시장>.json → asof 별 마지막 판 누적. 반환 {asof: 행 수}."""
    rel = f"reports/peers_{market}.json"
    revs = subprocess.run(["git", "log", "--format=%H", "--", rel], capture_output=True, text=True, check=True).stdout.split()
    seen, out = set(), {}
    for h in revs:   # 최신 → 과거: asof 마다 처음 본(=마지막) 판만
        try:
            d = json.loads(subprocess.run(["git", "show", f"{h}:{rel}"], capture_output=True, text=True, check=True).stdout)
        except Exception:  # noqa: BLE001
            continue
        a = str(d.get("asof") or "")[:10]
        if not a or a in seen:
            continue
        seen.add(a)
        out[a] = append(market, a, d.get("rows") or [])
    return out


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--backfill":
        print(json.dumps(backfill(sys.argv[2]), ensure_ascii=False))
