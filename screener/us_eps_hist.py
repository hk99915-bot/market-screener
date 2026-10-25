"""미장 EPS 추정 일별 스냅숏 이력 (req-data-751d13c7, hf: US 이익 추정 상향 알파 D2 검정용).

reports/us_eps.json 은 매일 덮어쓰는 캐시라 이력이 없다. 실행마다 (날짜·티커·기간·cur·chg30·chg90) 행을
reports/us_eps_hist.parquet 에 (date,ticker,period) 키로 upsert 한다. 같은 날 재실행 = 마지막 값으로 덮어씀.
날짜 = us_eps.json 'asof'(KST) 의 날짜. 과거분은 reports/archive/us_eps/*.json (2026-10-17~, 같은 asof 규칙)에서 복원.
빠진 날(휴일·워크플로 미실행)은 행이 없다 — 채우지 않는다(이력은 있었던 스냅숏만, 룩어헤드 없음).
한계: 2026-10-15~16 스냅숏은 보관된 적 없어 복원 불가. 컬럼 chg30/chg90 은 yfinance eps_trend 기준 비율(0.02=+2%).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import polars as pl

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]
HIST = ROOT / "reports" / "us_eps_hist.parquet"
ARCHIVE = ROOT / "reports" / "archive" / "us_eps"
SCHEMA = {"date": pl.Utf8, "ticker": pl.Utf8, "period": pl.Utf8, "cur": pl.Float64, "chg30": pl.Float64, "chg90": pl.Float64}


def rows_from_snapshot(asof: str, data: dict) -> list[dict]:
    day = str(asof)[:10]
    out = []
    for t, rec in (data or {}).items():
        for per in ("0y", "+1y"):
            x = ((rec or {}).get("eps") or {}).get(per) or {}
            if x.get("cur") is None and x.get("chg30") is None and x.get("chg90") is None:
                continue
            out.append({"date": day, "ticker": t, "period": per, "cur": x.get("cur"), "chg30": x.get("chg30"), "chg90": x.get("chg90")})
    return out


def upsert(rows: list[dict], path: Path = HIST) -> int:
    """행을 (date,ticker,period) 키로 병합 저장. 반환 = 저장 후 총 행 수."""
    new = pl.DataFrame(rows, schema=SCHEMA) if rows else pl.DataFrame(schema=SCHEMA)
    if path.exists():
        old = pl.read_parquet(path).select(list(SCHEMA)).cast(SCHEMA)
        new = pl.concat([old.join(new.select("date", "ticker", "period"), on=["date", "ticker", "period"], how="anti"), new])
    new = new.sort(["date", "ticker", "period"])
    path.parent.mkdir(parents=True, exist_ok=True)
    new.write_parquet(path, compression="zstd")
    return new.height


def record(asof: str, data: dict, path: Path = HIST) -> int:
    try:
        return upsert(rows_from_snapshot(asof, data), path)
    except Exception as e:  # noqa: BLE001 - 이력 실패가 본 수집을 막지 않게
        log.warning("us_eps 이력 적재 실패: %s", e)
        return -1


def rebuild_from_archive(archive: Path = ARCHIVE, path: Path = HIST) -> int:
    rows: list[dict] = []
    for f in sorted(archive.glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        rows += rows_from_snapshot(d.get("asof") or f.stem, d.get("data") or {})
    return upsert(rows, path)


if __name__ == "__main__":
    print("총 행", rebuild_from_archive())
