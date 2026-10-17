"""KR 시세 — KRX 공식 데이터 (yfinance 대체).

백엔드 (환경변수 KRX_BACKEND, 기본 pykrx)
  pykrx   : data.krx.co.kr 스크래핑. 날짜별 전종목 OHLCV → 하루 2콜(KOSPI/KOSDAQ). 키 불필요.
  openapi : KRX Open API (openapi.krx.co.kr). KRX_API_KEY 필요. 엔드포인트는 KRX_OPENAPI_STK/KSQ 로 지정.

방식: data/kr_prices.parquet 를 증분 갱신 (마지막 저장일 다음 영업일부터 오늘까지만 호출).
      최초 백필(약 400 영업일 ≈ 800콜)은 국내 IP(내 PC)에서 한 번 돌리고 Parquet 를 커밋하는 걸 권장.
종가 확정 (2026-10-15 검증):
      KRX 전종목 시세(MDCSTAT01501)의 '당일' 행은 lateInfoMsgCd=ME006(잠정)이며 TDD_CLSPRC 가 장 마감 뒤에도
      시간외·NXT 체결로 계속 움직인다 (예: 005930 15:30 종가 210,000 인데 16:54 209,500 → 18:45 211,000).
      익일 확정(ME005)되면 정규장 종가로 바뀐다 → 최근 REFETCH_DAYS 영업일은 매번 다시 받아 확정치로 덮어쓰고,
      잠정 행의 종가는 야후 일봉 종가(.KS/.KQ = KRX 정규장 15:30 단일가와 일치 확인)로 교체한다.
      주의: 네이버 일별 시세(fchart·m.stock price·pykrx get_market_ohlcv 기본값 adjusted=True)의 종가는
      NXT 애프터마켓(~20:00) 마지막 체결가라 정규장 종가가 아님 (005930 10-14: 네이버 234,500 vs KRX 232,000).
수정주가: KRX 전종목 일별 시세는 '당일 실제 가격'이라 액면분할·병합 시 과거와 단절됨.
      저장 파일은 원본 그대로 두고, 읽을 때 screener/prices.load_kr() 가 조정한다 (규칙은 prices.py 문서).
"""
from __future__ import annotations

import logging
import os
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import polars as pl

from .config import DATA_DIR

log = logging.getLogger(__name__)
PARQUET = DATA_DIR / "kr_prices.parquet"
SCHEMA = {"yf": pl.Utf8, "date": pl.Date, "open": pl.Float64, "high": pl.Float64,
          "low": pl.Float64, "close": pl.Float64, "volume": pl.Float64}
KST = ZoneInfo("Asia/Seoul")
REFETCH_DAYS = 5          # 매 실행마다 다시 받는 최근 영업일 수 (잠정 → 확정 교체)


def _today_kst() -> date:
    return datetime.now(KST).date()


# ───────────── 백엔드 ─────────────

def _pykrx_raw_day(d: date) -> tuple[pl.DataFrame, bool]:
    """KRX 전종목 시세 원본 (lateInfoMsgCd 포함). 반환: (시세, 잠정 여부 — ME006 이면 True)."""
    from pykrx.website.krx.market.core import 전종목시세  # type: ignore
    frames, prov = [], False
    num = lambda v: float(str(v).replace(",", "").strip() or 0) if str(v).strip() not in ("-", "") else 0.0  # noqa: E731
    for mkt, suf in (("STK", ".KS"), ("KSQ", ".KQ")):
        raw = 전종목시세().fetch(d.strftime("%Y%m%d"), mkt)
        if raw is None or raw.empty:
            continue
        prov = prov or bool((raw.get("lateInfoMsgCd") == "ME006").any()) if "lateInfoMsgCd" in raw.columns else prov
        rows = [r for r in raw.to_dict("records") if num(r["ACC_TRDVOL"]) > 0]   # 휴장일·거래정지 제외
        if rows:
            frames.append(pl.DataFrame({
                "yf": [r["ISU_SRT_CD"] + suf for r in rows], "date": d,
                "open": [num(r["TDD_OPNPRC"]) for r in rows], "high": [num(r["TDD_HGPRC"]) for r in rows],
                "low": [num(r["TDD_LWPRC"]) for r in rows], "close": [num(r["TDD_CLSPRC"]) for r in rows],
                "volume": [num(r["ACC_TRDVOL"]) for r in rows],
            }, schema=SCHEMA))
        time.sleep(0.3)  # KRX 차단 방지
    return (pl.concat(frames) if frames else pl.DataFrame(schema=SCHEMA)), prov


def _pykrx_day(d: date) -> pl.DataFrame:
    from pykrx import stock  # type: ignore
    frames = []
    for mkt, suf in (("KOSPI", ".KS"), ("KOSDAQ", ".KQ")):
        df = stock.get_market_ohlcv_by_ticker(d.strftime("%Y%m%d"), market=mkt)
        if df is None or df.empty:
            continue
        df = df[df["거래량"] > 0]  # 휴장일·거래정지 제외
        frames.append(pl.DataFrame({
            "yf": [t + suf for t in df.index], "date": d,
            "open": df["시가"].astype(float).values, "high": df["고가"].astype(float).values,
            "low": df["저가"].astype(float).values, "close": df["종가"].astype(float).values,
            "volume": df["거래량"].astype(float).values,
        }))
        time.sleep(0.3)  # KRX 차단 방지
    return pl.concat(frames) if frames else pl.DataFrame(schema=SCHEMA)


def _openapi_day(d: date) -> pl.DataFrame:
    """KRX Open API. 응답 필드명은 계정 문서 기준으로 아래 매핑만 손보면 됨."""
    import requests
    key = os.environ["KRX_API_KEY"]
    eps = {".KS": os.environ.get("KRX_OPENAPI_STK", "https://data-dbg.krx.co.kr/svc/apis/sto/stk_bydd_trd"),
           ".KQ": os.environ.get("KRX_OPENAPI_KSQ", "https://data-dbg.krx.co.kr/svc/apis/sto/ksq_bydd_trd")}
    fmap = {"code": "ISU_CD", "open": "TDD_OPNPRC", "high": "TDD_HGPRC", "low": "TDD_LWPRC",
            "close": "TDD_CLSPRC", "volume": "ACC_TRDVOL"}
    frames = []
    for suf, url in eps.items():
        r = requests.get(url, headers={"AUTH_KEY": key}, params={"basDd": d.strftime("%Y%m%d")}, timeout=30)
        r.raise_for_status()
        rows = r.json().get("OutBlock_1", [])
        num = lambda v: float(str(v).replace(",", "") or 0)  # noqa: E731
        rows = [x for x in rows if num(x.get(fmap["volume"], 0)) > 0]
        if rows:
            frames.append(pl.DataFrame({
                "yf": [x[fmap["code"]] + suf for x in rows], "date": d,
                **{k: [num(x[fmap[k]]) for x in rows] for k in ("open", "high", "low", "close", "volume")},
            }))
    return pl.concat(frames) if frames else pl.DataFrame(schema=SCHEMA)


def _fetch_day(d: date) -> pl.DataFrame:
    return _fetch_day_flag(d)[0]


def _fetch_day_flag(d: date) -> tuple[pl.DataFrame, bool]:
    """(시세, 잠정 여부). 잠정 = KRX 가 아직 확정하지 않은 행(ME006) 또는 오늘(KST) 이후."""
    be = os.environ.get("KRX_BACKEND", "pykrx")
    if be == "openapi":
        return _openapi_day(d), d >= _today_kst()
    try:
        df, prov = _pykrx_raw_day(d)
        return df, prov or d >= _today_kst()
    except Exception as e:  # noqa: BLE001
        log.warning("KRX 원본 조회 실패(%s) → pykrx 래퍼: %s", d, e)
        return _pykrx_day(d), d >= _today_kst()


def _yahoo_close(syms: list[str], d: date) -> dict[str, float]:
    """야후 일봉에서 d 일자 종가 (KRX 정규장 종가와 일치). 실패·누락은 빈 dict/누락."""
    import pandas as pd
    import yfinance as yf
    from .config import CFG
    out: dict[str, float] = {}
    bs = max(CFG.batch_size, 200)
    for i in range(0, len(syms), bs):
        chunk = syms[i:i + bs]
        try:
            raw = yf.download(chunk, start=(d - timedelta(days=3)).isoformat(), end=(d + timedelta(days=1)).isoformat(),
                              auto_adjust=False, group_by="ticker", threads=CFG.threads, progress=False, timeout=30)
        except Exception as e:  # noqa: BLE001
            log.warning("야후 종가 배치 %d 실패: %s", i // bs, e)
            continue
        if raw is None or raw.empty:
            continue
        if len(chunk) == 1:
            raw = pd.concat({chunk[0]: raw}, axis=1)
        lv0 = set(raw.columns.get_level_values(0))
        for sym in chunk:
            if sym not in lv0:
                continue
            c = raw[sym]["Close"].dropna()
            c = c[[x.date() == d for x in pd.to_datetime(c.index)]]
            if len(c) and float(c.iloc[-1]) > 0:
                out[sym] = float(c.iloc[-1])
    return out


def fix_provisional(df: pl.DataFrame, d: date) -> pl.DataFrame:
    """잠정 행(d)의 종가를 야후 정규장 종가로 교체. 고가/저가는 종가를 포함하도록 보정. 실패 시 원본 유지."""
    try:
        yc = _yahoo_close(df["yf"].to_list(), d)
    except Exception as e:  # noqa: BLE001
        log.warning("잠정 종가 교체 실패(%s) — KRX 잠정치 유지: %s", d, e)
        return df
    if not yc:
        log.warning("잠정 종가 교체: 야후 %s 종가 없음 — KRX 잠정치 유지", d)
        return df
    m = pl.DataFrame({"yf": list(yc), "_yc": list(yc.values())}, schema={"yf": pl.Utf8, "_yc": pl.Float64})
    out = df.join(m, on="yf", how="left").with_columns(
        # 시간외 단일가(±10%)·NXT 범위를 벗어난 값은 다른 종목/오류로 보고 버림
        pl.when(pl.col("_yc").is_not_null() & ((pl.col("_yc") / pl.col("close") - 1).abs() < 0.15))
          .then(pl.col("_yc")).otherwise(None).alias("_yc"))
    n = out["_yc"].is_not_null().sum()
    chg = out.filter(pl.col("_yc").is_not_null() & (pl.col("_yc") != pl.col("close"))).height
    out = out.with_columns(pl.coalesce("_yc", "close").alias("close")).with_columns(
        pl.max_horizontal("high", "close").alias("high"), pl.min_horizontal("low", "close").alias("low")).drop("_yc")
    log.info("KRX %s 잠정 종가 → 야후 정규장 종가 교체: %d/%d종목 확인, %d종목 값 변경", d, n, len(df), chg)
    return out.select(list(SCHEMA))


# ───────────── 증분 갱신 ─────────────

def update(lookback_days: int = 400, max_calls: int = 450, until: date | None = None) -> pl.DataFrame:
    """증분 갱신. until: 이 날짜까지만 조회 (기본 오늘 KST)."""
    DATA_DIR.mkdir(exist_ok=True)
    hist = pl.read_parquet(PARQUET) if PARQUET.exists() else pl.DataFrame(schema=SCHEMA)
    until = until or _today_kst()
    # 최근 REFETCH_DAYS 저장일은 다시 받는다: 마감 직후 저장된 잠정 종가(시간외·NXT 반영)를 KRX 확정치로 덮어씀
    if len(hist):
        stored = sorted(hist["date"].unique().to_list())
        start = stored[-REFETCH_DAYS] if len(stored) >= REFETCH_DAYS else stored[0]
    else:
        start = until - timedelta(days=lookback_days)
    days = [start + timedelta(i) for i in range((until - start).days + 1)]
    days = [d for d in days if d.weekday() < 5][-max_calls:]
    new, fails = [], 0
    for d in days:
        try:
            df, prov = _fetch_day_flag(d)
            if len(df) and prov:
                df = fix_provisional(df, d)
            if len(df):
                new.append(df)
            log.info("KRX %s: %d행%s", d, len(df), " (잠정)" if prov else "")
        except Exception as e:  # noqa: BLE001
            fails += 1
            log.warning("KRX %s 실패: %s", d, e)
            if fails >= 5:
                raise RuntimeError("KRX 연속 실패 — IP 차단 또는 사이트 변경 가능성") from e
    if new:
        hist = pl.concat([hist, pl.concat(new)]).unique(subset=["yf", "date"], keep="last")
    if not len(hist):
        raise RuntimeError("KRX 시세 없음")
    hist = hist.sort("yf", "date")
    hist.write_parquet(PARQUET)
    return hist


# ───────────── 기업행위 조정 ─────────────

def adjust_splits(df: pl.DataFrame, threshold: float | None = None) -> pl.DataFrame:
    """기업행위 조정 — 규칙은 screener/prices.py 한 곳 (시가·종가 모두 ±31% 밖 + 정리매매 제외, 10/17 v2).
    threshold 는 옛 호출 호환용(무시). 반환 열은 입력과 같다."""
    from .prices import adjust
    return adjust(df)


def refresh_recent() -> pl.DataFrame:
    """최근 REFETCH_DAYS 영업일 교정만 (상세 재생성·성적표 채점 전에 호출).
    16:00 KST 전에는 어제까지만 — 장중/마감 직후의 미완성 봉을 새로 만들지 않음."""
    now = datetime.now(KST)
    return update(until=now.date() if now.hour >= 16 else now.date() - timedelta(days=1))


def fetch_prices_krx() -> pl.DataFrame:
    return adjust_splits(update())
