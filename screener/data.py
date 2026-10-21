"""시세 수집 (yfinance) → Parquet 캐시.

정규장 일봉만 사용 (기획 원칙: 시간외/프리·애프터는 기술지표에 섞지 않음).
yfinance 일봉은 정규장 OHLCV이므로 조건 충족. 배당/분할 조정은 auto_adjust=True.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

import polars as pl

from .config import CFG, DATA_DIR

log = logging.getLogger(__name__)


def fetch_prices(yf_symbols: list[str], market: str, lookback_days: int | None = None) -> pl.DataFrame:
    """long 포맷 [yf, date, open, high, low, close, volume] 반환."""
    import pandas as pd
    import yfinance as yf

    lookback_days = lookback_days or CFG.lookback_days
    start = (date.today() - timedelta(days=lookback_days)).isoformat()
    frames: list[pl.DataFrame] = []
    bs = CFG.batch_size
    for i in range(0, len(yf_symbols), bs):
        chunk = yf_symbols[i:i + bs]
        try:
            raw = yf.download(chunk, start=start, auto_adjust=True, group_by="ticker",
                              threads=CFG.threads, progress=False, timeout=60)
        except Exception as e:  # noqa: BLE001
            log.warning("배치 %d 실패: %s", i // bs, e)
            continue
        if raw is None or raw.empty:
            continue
        if len(chunk) == 1:  # 단일 티커면 컬럼이 1단계
            raw = pd.concat({chunk[0]: raw}, axis=1)
        for sym in chunk:
            if sym not in raw.columns.get_level_values(0):
                continue
            d = raw[sym].dropna(subset=["Close"])
            if d.empty:
                continue
            frames.append(pl.DataFrame({
                "yf": sym,
                "date": [x.date() for x in pd.to_datetime(d.index)],
                "open": d["Open"].astype(float).values, "high": d["High"].astype(float).values,
                "low": d["Low"].astype(float).values, "close": d["Close"].astype(float).values,
                "volume": d["Volume"].fillna(0).astype(float).values,
            }))
        log.info("%s 시세 배치 %d/%d", market, i // bs + 1, (len(yf_symbols) + bs - 1) // bs)
    if not frames:
        raise RuntimeError(f"{market} 시세 수집 결과 없음")
    df = pl.concat(frames).with_columns(pl.col("date").cast(pl.Date)).sort("yf", "date")
    DATA_DIR.mkdir(exist_ok=True)
    df.write_parquet(DATA_DIR / f"{market.lower()}_prices.parquet")
    return df


def load_cached(market: str) -> pl.DataFrame | None:
    p = DATA_DIR / f"{market.lower()}_prices.parquet"
    return pl.read_parquet(p) if p.exists() else None


def fetch_macro() -> pl.DataFrame:
    """매크로 컨텍스트 시계열 (long). 실패해도 전체 파이프라인은 계속."""
    try:
        df = fetch_prices(list(CFG.macro.values()), "MACRO", lookback_days=200)
        inv = {v: k for k, v in CFG.macro.items()}
        return df.with_columns(pl.col("yf").replace_strict(inv, default=pl.col("yf")).alias("key"))
    except Exception as e:  # noqa: BLE001
        log.warning("매크로 수집 실패: %s", e)
        return pl.DataFrame(schema={"key": pl.Utf8, "date": pl.Date, "close": pl.Float64})


# ── 마지막 날 토스 보충 (보드 us-eod-toss, 10/21 겸이 "야후가 아니라 토스로 하기로 했잖아") ─────────────────────
# 야후가 장후 몇 시간 당일 종목봉을 안 주면(10/21: 10/20 봉 없음 → STALE) 노트북 수집기가 toss-live 에 올린 us_eod.json
# ({date(ET), bars:{yf: [o,h,l,c,v]}})에서 **그 날짜 봉만** 붙인다. 이력은 야후 그대로. 파일 없음·날짜 다름 → 손대지 않음(기존 STALE).
TOSS_EOD_URL = "https://raw.githubusercontent.com/hk99915-bot/market-screener/toss-live/us_eod.json"


def load_toss_eod(url: str = TOSS_EOD_URL) -> dict | None:
    import time

    import requests
    try:
        r = requests.get(f"{url}?t={int(time.time())}", timeout=20)   # raw 캐시 최대 5분 → 캐시버스터
        return r.json() if r.ok else None
    except Exception as e:  # noqa: BLE001
        log.warning("토스 us_eod.json 못 읽음: %s", e)
        return None


def _dev(a, b) -> float | None:
    try:
        a, b = float(a), float(b)
    except (TypeError, ValueError):
        return None
    return abs(a / b - 1) if b else None


def check_toss_eod(px: pl.DataFrame, want: date, eod: dict | None, tol: float | None = None,
                   min_overlap: float | None = None, min_match: float | None = None) -> dict:
    """보충 전 실데이터 검증 게이트: us_eod.json prev(직전 거래일 [날짜,o,h,l,c,v])를 야후 px 같은 날짜 봉과 종목별 대조.
    반환 = 작은 요약(dict) + ok_syms(종가 |괴리| ≤ tol 인 종목 — 보충은 이 종목만). 원값은 남기지 않음."""
    from .config import TOSS_EOD_CLOSE_TOL, TOSS_EOD_MIN_MATCH, TOSS_EOD_MIN_OVERLAP
    tol = TOSS_EOD_CLOSE_TOL if tol is None else tol
    min_overlap = TOSS_EOD_MIN_OVERLAP if min_overlap is None else min_overlap
    min_match = TOSS_EOD_MIN_MATCH if min_match is None else min_match
    prev = (eod or {}).get("prev") or {}
    syms = px["yf"].unique().to_list() if not px.is_empty() else []
    dates = sorted({str(v[0]) for v in prev.values() if isinstance(v, list) and len(v) >= 6})
    y = {}
    if dates:
        sub = px.filter(pl.col("date").cast(pl.Utf8).is_in(dates))
        y = {(r["yf"], str(r["date"])): r for r in sub.iter_rows(named=True)}
    devs, ohl, vol, pdates = {}, [], [], {}
    for s in syms:
        v = prev.get(s)
        if not isinstance(v, list) or len(v) < 6:
            continue
        r = y.get((s, str(v[0])))
        if r is None:
            continue
        dc = _dev(v[4], r["close"])
        if dc is None:
            continue
        devs[s] = dc
        pdates[str(v[0])] = pdates.get(str(v[0]), 0) + 1
        ohl += [d for d in (_dev(v[1], r["open"]), _dev(v[2], r["high"]), _dev(v[3], r["low"])) if d is not None]
        if r["volume"] and v[5] is not None:
            vol.append(_dev(v[5], r["volume"]))
    n, ok = len(devs), sorted(s for s, d in devs.items() if d <= tol)
    overlap = n / len(syms) if syms else 0.0
    match = len(ok) / n if n else 0.0
    bad = sorted(((s, d) for s, d in devs.items() if d > tol), key=lambda x: -x[1])
    mx = max(devs.items(), key=lambda x: x[1]) if devs else (None, None)
    vol = sorted(x for x in vol if x is not None)
    res = {"date": want.isoformat(), "prev_date": max(pdates, key=pdates.get) if pdates else None,
           "n_universe": len(syms), "n_prev": len(prev), "n_overlap": n, "overlap_pct": round(100 * overlap, 1),
           "n_match": len(ok), "match_pct": round(100 * match, 1),
           "max_dev_pct": None if mx[1] is None else round(100 * mx[1], 4), "max_dev_sym": mx[0],
           "ohl_max_dev_pct": round(100 * max(ohl), 4) if ohl else None,
           "vol_median_dev_pct": round(100 * vol[len(vol) // 2], 2) if vol else None,
           "failed": [[s, round(100 * d, 3)] for s, d in bad[:10]], "n_failed": len(bad),
           "rule": {"close_tol_pct": 100 * tol, "min_overlap_pct": 100 * min_overlap, "min_match_pct": 100 * min_match},
           "pass": bool(syms) and overlap >= min_overlap and match >= min_match}
    res["ok_syms"] = ok
    return res


def write_toss_check(res: dict, path) -> None:
    """reports/toss_eod_check.json — 최근 검증 요약만(ok_syms·원값 제외), 날짜별 최근 30회."""
    import json
    from pathlib import Path
    p = Path(path)
    try:
        cur = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except Exception:  # noqa: BLE001
        cur = {}
    item = {k: v for k, v in res.items() if k != "ok_syms"}
    hist = [h for h in (cur.get("history") or []) if h.get("date") != item["date"]] + [item]
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"last": item, "history": hist[-30:],
                             "note": "토스 us_eod prev(직전 거래일) vs 야후 같은 날짜 봉 — 종가 괴리 게이트(screener/config.py TOSS_EOD_*)"},
                            ensure_ascii=False, indent=1), encoding="utf-8")


def fill_last_day(px: pl.DataFrame, want: date, eod: dict | None, only=None) -> tuple[pl.DataFrame, dict | None]:
    """px(야후 long)에 want 날짜 봉이 없는 종목만 토스 봉으로 채움. only(검증 통과 종목 집합)가 있으면 그 종목만.
    반환 (px, {src, date, filled, total, pct, label} | None)."""
    if not eod or str(eod.get("date")) != want.isoformat() or px.is_empty():
        return px, None
    bars = eod.get("bars") or {}
    syms = px["yf"].unique().to_list()
    have = set(px.filter(pl.col("date") == want)["yf"].to_list())
    only = None if only is None else set(only)
    rows = []
    for s in syms:
        v = bars.get(s)
        if (only is not None and s not in only) or s in have or not isinstance(v, list) or len(v) < 5 or v[3] is None:
            continue
        o, h, lo, c = (float(x) if x is not None else float(v[3]) for x in v[:4])
        rows.append({"yf": s, "date": want, "open": o, "high": h, "low": lo, "close": c, "volume": float(v[4] or 0)})
    if not rows:
        return px, None
    add = pl.DataFrame(rows).with_columns(pl.col("date").cast(pl.Date)).select(px.columns).cast(px.schema)
    out = pl.concat([px, add]).sort("yf", "date")
    pct = round(100 * len(rows) / len(syms), 1)
    info = {"src": "yahoo+toss", "date": want.isoformat(), "filled": len(rows), "total": len(syms), "pct": pct,
            "label": f"src: 야후+토스 보충 {pct:g}%"}
    log.info("마지막 날 토스 보충 %s: %d/%d 종목 (%s%%)", want, len(rows), len(syms), pct)
    return out, info
