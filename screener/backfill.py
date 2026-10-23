"""장기 히스토리 백필 (백테스트용) → data/hist/{kr,us}_{YYYY}.parquet

KR: KRX 날짜별 전종목 시세 (상장폐지 종목 포함 → 생존편향 없음). 연도별 파일, 원주가(수정 전).
    로드 시 load_hist('KR') 가 전 기간을 합쳐 기업행위 보정.
US: yfinance, 현재 거래대금 상위 N 종목의 전체 이력 (생존편향 있음 — 상폐 종목 빠짐).
    첫 일괄(us_done.txt) 뒤에는 backfill_us_fill() 이 상세 유니버스(reports/detail/US) 중 연도별 파일에
    없는 종목만 배치로 받아 연도 파일에 합친다 — 진행은 data/hist/us_fill.json (10/24 req-data-4e6e68fe).

시간 예산(기본 300분)을 넘기면 스스로 멈추고, 다음 실행에서 이어서 받는다.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import date, timedelta

import polars as pl

from .config import DATA_DIR, UNIVERSE_DIR

log = logging.getLogger("backfill")
HIST = DATA_DIR / "hist"


def _done_marker(market: str, year: int):
    return HIST / f"{market.lower()}_{year}.parquet"


def backfill_kr(start_year: int, budget_s: float, t0: float) -> bool:
    """True = 전부 완료."""
    from .data_krx import _fetch_day
    HIST.mkdir(parents=True, exist_ok=True)
    this_year = date.today().year
    for y in range(start_year, this_year):  # 올해는 일일 파이프라인(kr_prices.parquet)이 담당
        out = _done_marker("KR", y)
        if out.exists():
            continue
        part = HIST / f"kr_{y}.partial.parquet"
        have = pl.read_parquet(part) if part.exists() else None
        done_days = set(have["date"].unique().to_list()) if have is not None else set()
        frames = [have] if have is not None else []
        d = date(y, 1, 1)
        fails = 0
        while d.year == y:
            if d.weekday() < 5 and d not in done_days:
                if time.time() - t0 > budget_s:
                    if frames:
                        pl.concat(frames).write_parquet(part)
                    log.info("시간 예산 소진 — %s 까지 저장, 다음 실행에서 이어감", d)
                    return False
                try:
                    df = _fetch_day(d)
                    if len(df):
                        frames.append(df)
                    fails = 0
                except Exception as e:  # noqa: BLE001
                    fails += 1
                    log.warning("KR %s 실패: %s", d, e)
                    if fails >= 8:
                        if frames:
                            pl.concat(frames).write_parquet(part)
                        raise RuntimeError("KRX 연속 실패 — 중단 (진행분 저장됨)") from e
                    time.sleep(5)
            d += timedelta(days=1)
            if d.month != (d - timedelta(days=1)).month and frames:  # 월마다 중간 저장
                pl.concat(frames).write_parquet(part)
                log.info("KR %d-%02d 저장", y, (d - timedelta(days=1)).month)
        df = pl.concat(frames).unique(["yf", "date"]).sort("yf", "date")
        df.write_parquet(out, compression="zstd")
        part.unlink(missing_ok=True)
        log.info("KR %d 완료: %d행", y, len(df))
    return True


def backfill_us(start_year: int, budget_s: float, t0: float) -> bool:
    import pandas as pd
    import yfinance as yf
    HIST.mkdir(parents=True, exist_ok=True)
    marker = HIST / "us_done.txt"
    if marker.exists():
        return backfill_us_fill(start_year, budget_s, t0)
    top = UNIVERSE_DIR / "us_top.csv"
    if not top.exists():
        log.warning("universe/us_top.csv 없음 — US 일일 실행 후 다시 시도")
        return False
    syms = pl.read_csv(top)["yf"].to_list() + ["SPY", "QQQ", "IWM", "^GSPC", "^IXIC", "^VIX", "^TNX"]
    frames = []
    for i in range(0, len(syms), 100):
        if time.time() - t0 > budget_s:
            return False
        chunk = syms[i:i + 100]
        try:
            raw = yf.download(chunk, start=f"{start_year}-01-01", end=f"{date.today().year}-01-01", auto_adjust=True,
                              group_by="ticker", threads=True, progress=False, timeout=120)
        except Exception as e:  # noqa: BLE001
            log.warning("US 배치 %d 실패: %s", i // 100, e)
            continue
        if len(chunk) == 1:
            raw = pd.concat({chunk[0]: raw}, axis=1)
        for s in chunk:
            if s not in raw.columns.get_level_values(0):
                continue
            d = raw[s].dropna(subset=["Close"])
            if d.empty:
                continue
            frames.append(pl.DataFrame({
                "yf": s, "date": [x.date() for x in pd.to_datetime(d.index)],
                "open": d["Open"].astype(float).values, "high": d["High"].astype(float).values,
                "low": d["Low"].astype(float).values, "close": d["Close"].astype(float).values,
                "volume": d["Volume"].fillna(0).astype(float).values}))
        log.info("US 배치 %d/%d", i // 100 + 1, (len(syms) + 99) // 100)
    if not frames:
        return False
    df = pl.concat(frames).with_columns(pl.col("date").cast(pl.Date))
    for (y,), g in df.with_columns(pl.col("date").dt.year().alias("_y")).group_by("_y"):
        g.drop("_y").sort("yf", "date").write_parquet(HIST / f"us_{y}.parquet", compression="zstd")
    marker.write_text(date.today().isoformat())
    log.info("US 완료: %d행, %d종목", len(df), df["yf"].n_unique())
    return True


FILL_LOG = HIST / "us_fill.json"
FILL_BATCH = 40


def _us_targets() -> list[str]:
    """채울 대상 = 상세 유니버스(reports/detail/US/*.json) ∪ us_top.csv."""
    from .config import REPORT_DIR
    syms = {f.stem for f in (REPORT_DIR / "detail" / "US").glob("*.json") if not f.stem.startswith("_")}
    top = UNIVERSE_DIR / "us_top.csv"
    if top.exists():
        syms |= set(pl.read_csv(top)["yf"].to_list())
    return sorted(syms)


def _us_have(start_year: int, end_year: int) -> set[str]:
    have: set[str] = set()
    for y in range(start_year, end_year):
        f = HIST / f"us_{y}.parquet"
        if f.exists():
            have |= set(pl.read_parquet(f, columns=["yf"])["yf"].unique().to_list())
    return have


def _merge_years(df: pl.DataFrame) -> list[int]:
    """새 종목 행을 연도 파일에 합친다(같은 yf·date 는 새 값 우선). 반환 = 바뀐 연도."""
    years = []
    for (y,), g in df.with_columns(pl.col("date").dt.year().alias("_y")).group_by("_y"):
        g = g.drop("_y")
        f = HIST / f"us_{y}.parquet"
        if f.exists():
            old = pl.read_parquet(f)
            g = pl.concat([old, g.select(old.columns).cast(old.schema)], how="vertical")
        g.unique(["yf", "date"], keep="last").sort("yf", "date").write_parquet(f, compression="zstd")
        years.append(int(y))
    return sorted(years)


def backfill_us_fill(start_year: int, budget_s: float, t0: float, end_year: int | None = None,
                     batch: int = FILL_BATCH, pause_s: float = 3.0, download=None) -> bool:
    """연도별 hist 에 없는 상세 유니버스 종목만 백필. True = 남은 종목 0(받을 수 없는 종목 포함 판정 끝)."""
    import json
    import pandas as pd
    end_year = end_year or date.today().year  # 올해는 일일 파이프라인 몫
    HIST.mkdir(parents=True, exist_ok=True)
    st = json.loads(FILL_LOG.read_text()) if FILL_LOG.exists() else {}
    rng = f"{start_year}~{end_year - 1}"
    no_data = set(st.get("no_data", [])) if st.get("range") == rng else set()  # 기간 바뀌면(연 넘김) 다시 물음
    targets = _us_targets()
    have = _us_have(start_year, end_year)
    todo = [s for s in targets if s not in have and s not in no_data]
    log.info("US 채우기: 대상 %d · 보유 %d · 받을 것 %d · 원천 없음 %d", len(targets), len(set(targets) & have),
             len(todo), len(no_data))
    if download is None:
        import yfinance as yf

        def download(chunk):
            return yf.download(chunk, start=f"{start_year}-01-01", end=f"{end_year}-01-01", auto_adjust=True,
                               group_by="ticker", threads=True, progress=False, timeout=120)
    fails = 0
    added: list[str] = []
    for i in range(0, len(todo), batch):
        if time.time() - t0 > budget_s:
            log.info("시간 예산 소진 — 다음 실행에서 이어감")
            break
        chunk = todo[i:i + batch]
        try:
            raw = download(chunk)
            fails = 0
        except Exception as e:  # noqa: BLE001
            fails += 1
            log.warning("US 채우기 배치 %d 실패: %s", i // batch, e)
            if fails >= 3:
                log.warning("연속 3회 실패 — 중단(진행분 저장됨)")
                break
            time.sleep(30)
            continue
        if len(chunk) == 1 and not isinstance(raw.columns, pd.MultiIndex):
            raw = pd.concat({chunk[0]: raw}, axis=1)
        frames = []
        lv0 = set(raw.columns.get_level_values(0)) if len(raw.columns) else set()
        for s in chunk:
            d = raw[s].dropna(subset=["Close"]) if s in lv0 else None
            if d is None or d.empty:
                no_data.add(s)  # 상장 전(2026 신규)·야후 없음 — 다시 묻지 않음
                continue
            frames.append(pl.DataFrame({
                "yf": s, "date": [x.date() for x in pd.to_datetime(d.index)],
                "open": d["Open"].astype(float).values, "high": d["High"].astype(float).values,
                "low": d["Low"].astype(float).values, "close": d["Close"].astype(float).values,
                "volume": d["Volume"].fillna(0).astype(float).values}))
            added.append(s)
        if frames:
            _merge_years(pl.concat(frames).with_columns(pl.col("date").cast(pl.Date)))
        log.info("US 채우기 배치 %d/%d: +%d", i // batch + 1, (len(todo) + batch - 1) // batch, len(frames))
        time.sleep(pause_s)
    have = _us_have(start_year, end_year)
    left = [s for s in targets if s not in have and s not in no_data]
    st = {"asof": date.today().isoformat(), "range": rng, "targets": len(targets),
          "have": len(set(targets) & have), "no_data": sorted(no_data), "left": len(left),
          "src": "yfinance auto_adjust", "note": "생존편향 있음 — 현재 상세 유니버스 기준(상폐 종목 없음)"}
    FILL_LOG.write_text(json.dumps(st, ensure_ascii=False, indent=1) + "\n")
    log.info("US 채우기: 이번 +%d · 보유 %d/%d · 남음 %d · 원천 없음 %d", len(added), st["have"], len(targets),
             len(left), len(no_data))
    return not left


def load_hist(market: str) -> pl.DataFrame:
    """전 기간 시세 (장기 히스토리 + 올해 일일 데이터). KR 은 기업행위 보정 적용."""
    files = sorted(HIST.glob(f"{market.lower()}_[0-9][0-9][0-9][0-9].parquet"))
    parts = [pl.read_parquet(f) for f in files]
    cur = DATA_DIR / f"{market.lower()}_prices.parquet"
    if cur.exists():
        parts.append(pl.read_parquet(cur))
    df = pl.concat(parts, how="vertical_relaxed").unique(["yf", "date"], keep="last").sort("yf", "date")
    if market == "KR":
        from .data_krx import adjust_splits
        df = adjust_splits(df)
    return df


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", choices=["KR", "US", "ALL"], default="ALL")
    ap.add_argument("--start", type=int, default=int(os.environ.get("BACKFILL_START", "2010")))
    ap.add_argument("--budget-min", type=float, default=300)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", stream=sys.stderr)
    t0, budget = time.time(), a.budget_min * 60
    done = True
    if a.market in ("US", "ALL"):
        done &= backfill_us(max(a.start, 2005), budget, t0)
    if a.market in ("KR", "ALL"):
        done &= backfill_kr(a.start, budget, t0)
    print("BACKFILL", "COMPLETE" if done else "PARTIAL")


if __name__ == "__main__":
    main()
