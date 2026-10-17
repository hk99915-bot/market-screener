"""KR 가격 공통 로더 — 수익률·지표를 계산하는 모든 모듈은 여기서 읽는다 (외부감사 10/17 P1 px-adjust-unify).

원본(raw) = data/kr_prices.parquet 그대로 (KRX 전종목 일별 시세 = 당일 실제 가격, 액면분할·병합·무상증자 때 과거와 단절).
조정(adjusted) = 아래 규칙으로 찾은 기업행위일 '이전' 구간에 비율을 곱한 가격 (가격은 곱하고 거래량은 나눔).

기업행위 판정 (v2, 2026-10-17 — 13개월 원본 373건 분류 결과는 docs/peer_reviews/2026-10-17_external_audit_fixes.md):
  KRX 일일 가격제한폭은 ±30% 이므로, 전일 종가 대비 **시가와 종가가 모두** 같은 방향으로 ±31% 밖이면
  기준가가 다시 정해진 날(분할·병합·무상증자 권리락·감자) 외에는 나올 수 없다.
  1) open>0·close>0·전일 close>0 인 행만 본다.
  2) r = 시가/전일종가, rc = 종가/전일종가. (r<0.69 且 rc<0.69) 또는 (r>1.31 且 rc>1.31) → 후보.
     - v1(시가만 ±45%)이 잡던 '시가만 튄 행'(체결 오류·단일가 왜곡, 종가는 제한폭 안)은 제외.
     - v1이 놓친 1:0.5 무상증자 권리락(r≈0.67)은 포함.
  3) 정리매매(가격제한 없음) 제외: 하락 후보가 시계열 마지막 7행 안에 있고 그 종목이 데이터 마지막 날 전에 끝났으면 건너뜀.
     (진행 중인 정리매매는 아직 끝나지 않아 걸러지지 않음 — 한계, 문서 참고)
  조정 비율은 r(시가 비율 = 새 기준가 근사)을 쓴다. 실제 분할 비율과는 재개일 시가 변동만큼(최대 ±30%) 다를 수 있다.
"""
from __future__ import annotations

import glob
import logging
from functools import lru_cache
from pathlib import Path

import polars as pl

from .config import DATA_DIR

log = logging.getLogger(__name__)
PARQUET = DATA_DIR / "kr_prices.parquet"
BAND = 0.31            # KRX 가격제한폭 30% + 호가 단위 여유
LIQ_TAIL = 7           # 정리매매 기간(7매매일)
PX = ("open", "high", "low", "close")


def detect_events(df: pl.DataFrame, sym: str = "yf", band: float = BAND) -> pl.DataFrame:
    """기업행위 추정일 목록: [sym, date, r, rc]. df 는 sym·date·open·close 필요."""
    lo, hi = 1 - band, 1 + band
    mx = df["date"].max()
    d = (df.filter((pl.col("open") > 0) & (pl.col("close") > 0)).sort(sym, "date")
           .with_columns(pc=pl.col("close").shift(1).over(sym),
                         _left=(pl.len() - 1 - pl.int_range(pl.len())).over(sym),
                         _last=pl.col("date").max().over(sym))
           .filter(pl.col("pc") > 0)
           .with_columns(r=pl.col("open") / pl.col("pc"), rc=pl.col("close") / pl.col("pc")))
    cand = ((pl.col("r") < lo) & (pl.col("rc") < lo)) | ((pl.col("r") > hi) & (pl.col("rc") > hi))
    liq = (pl.col("r") < 1) & (pl.col("_left") <= LIQ_TAIL) & (pl.col("_last") < mx)
    return d.filter(cand & ~liq).select(sym, "date", "r", "rc")


def adjust(df: pl.DataFrame, sym: str = "yf", band: float = BAND, events: pl.DataFrame | None = None) -> pl.DataFrame:
    """기업행위일 이전 구간을 비율 조정 (벡터화). 없는 열(high·low·volume)은 건너뜀. 열 순서·이름 유지."""
    if not len(df):
        return df
    ev = detect_events(df, sym, band) if events is None else events
    if not len(ev):
        return df.sort(sym, "date")
    cols = df.columns
    out = (df.sort(sym, "date").join(ev.select(sym, "date", pl.col("r").alias("_f")), on=[sym, "date"], how="left")
             .with_columns(pl.col("_f").fill_null(1.0))
             # 각 행의 배수 = 그 행 '이후'(당일 제외) 이벤트 비율의 곱
             .with_columns((pl.col("_f").reverse().cum_prod().reverse().over(sym) / pl.col("_f")).alias("_a")))
    exprs = [(pl.col(c) * pl.col("_a")).alias(c) for c in PX if c in cols]
    if "volume" in cols:
        exprs.append((pl.col("volume") / pl.col("_a")).alias("volume"))
    return out.with_columns(exprs).select(cols)


@lru_cache(maxsize=4)
def _load_cached(path: str, mtime: float, hist_from: int | None) -> pl.DataFrame:
    parts = []
    if hist_from is not None:
        for f in sorted(glob.glob(str(Path(path).parent / "hist" / "kr_[0-9][0-9][0-9][0-9].parquet"))):
            if int(f[-12:-8]) >= hist_from:
                parts.append(pl.read_parquet(f))
    if Path(path).exists():
        parts.append(pl.read_parquet(path))
    if not parts:
        return pl.DataFrame()
    keep = ["yf", "date", "open", "high", "low", "close", "volume"]
    df = (pl.concat([p.select([c for c in keep if c in p.columns]) for p in parts], how="vertical_relaxed")
            .with_columns(pl.col("date").cast(pl.Date), *[pl.col(c).cast(pl.Float64) for c in keep[2:]])
            .unique(["yf", "date"], keep="last", maintain_order=True).sort("yf", "date"))
    return df


def load_kr(raw: bool = False, hist_from: int | None = None, path: Path | None = None) -> pl.DataFrame:
    """KR 일봉 [yf,date,open,high,low,close,volume]. raw=True 면 원본, 기본은 기업행위 조정.
    hist_from=연도 → data/hist/kr_YYYY.parquet(그 연도부터, 상폐 포함)을 앞에 붙임 ((yf,date) 중복은 kr_prices 우선).
    파일 수정시각으로 캐시 → 같은 실행에서 refresh_recent() 뒤 다시 부르면 새로 읽는다."""
    p = Path(path or PARQUET)
    mtime = p.stat().st_mtime if p.exists() else 0.0
    df = _load_cached(str(p), mtime, hist_from)
    if raw or not len(df):
        return df
    return _adjusted_cached(str(p), mtime, hist_from)


@lru_cache(maxsize=4)
def _adjusted_cached(path: str, mtime: float, hist_from: int | None) -> pl.DataFrame:
    return adjust(_load_cached(path, mtime, hist_from))


def crosscheck_dart(events: pl.DataFrame, dart: pl.DataFrame, window_days: int = 60) -> dict:
    """DART 공시(data/dart.parquet)의 분할·병합·무상·감자 제목과 이벤트 대조.
    반환: {disclosures: 해당 공시 종목 수, matched: 공시 후 window_days 안에 이벤트가 있는 종목 수, missing: [code]}.
    공시 저장소가 아직 짧으면(10/17 기준 5일) 표본이 작다 — 누적될수록 의미가 커진다."""
    if not len(dart) or not len(events):
        return {"disclosures": 0, "matched": 0, "missing": []}
    # 변경상장(액면분할·병합 재개) + 무상증자 권리락만 — 유상증자 권리락은 비율이 작아(<31%) 규칙 대상이 아님
    t = pl.col("title")
    k = (dart.filter(t.str.contains("변경상장") | (t.str.contains("권리락") & t.str.contains("무상")))
             .select("code", pl.col("date").alias("dd")).unique())
    ev = events.with_columns(pl.col("yf").str.slice(0, 6).alias("code")).select("code", "date")
    j = k.join(ev, on="code", how="left").with_columns(
        ((pl.col("date") - pl.col("dd")).dt.total_days().is_between(0, window_days)).fill_null(False).alias("ok"))
    g = j.group_by("code").agg(pl.col("ok").any())
    return {"disclosures": len(g), "matched": int(g["ok"].sum()), "missing": sorted(g.filter(~pl.col("ok"))["code"].to_list())}
