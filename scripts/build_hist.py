"""연구용 시세 창고 빌드 → data/hist/{kr_etf,kr_index,kr_sector,us}_daily.parquet + _manifest.json

왜: 연구 스크립트가 ETF·지수 대신 종목 합성 프록시를 써 왔다 (ETF 는 KRX 전종목 시세 백필에 없고, 지수는 2년치 JSON 뿐).
    여기서 한 번 모아 두고 studies 는 screener.hist.load() 로만 읽는다 (네트워크 없이).

두 단계, 멱등·증분
  (a) 오프라인 병합 — 저장소 안에 이미 있는 것: data/deriv/daily.csv(코스피 OHLC 2010~, K200 종가),
      reports/macro_series.json(코스피·코스닥·SPX·나스닥·러셀·VIX·US10Y 2년 OHLCV), data/hist/us_YYYY.parquet(미국 2010~2025),
      reports/chains.json(체인 프록시 종가 14개월), data/hist/kr_YYYY.parquet × universe/kr_sector.csv → 업종 동일가중 합성지수.
  (b) 네트워크 백필 (--network, GitHub Actions 에서 자동) — yfinance(.KS ETF·^KS11·미국), pykrx(KRX 지수·업종지수·ETF 폴백).
      심볼별 마지막 날짜 -14일부터만 다시 받는다. 어느 출처가 실패해도 나머지는 진행.
  같은 (symbol, date) 는 출처 우선순위(pykrx > yfinance = hist_parquet = ew_composite > deriv_csv = macro_series > chains_json)로 하나만 남긴다.
  내용이 같으면 파일을 다시 쓰지 않는다 (커밋 잡음 방지). 전체 ≤ 25 MB 목표 (float32, zstd).

  python scripts/build_hist.py            # 오프라인 병합 (Actions 안에서는 네트워크도)
  python scripts/build_hist.py --network  # 네트워크 백필 강제
  python scripts/build_hist.py --offline  # 네트워크 금지
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from screener.hist import FILES, HIST_DIR, SCHEMA, empty, norm_symbol  # noqa: E402

log = logging.getLogger("build_hist")
START = date(2010, 1, 1)
OVERLAP_DAYS = 14
SIZE_BUDGET = 25 * 1024 * 1024
PRIORITY = {"pykrx": 5, "yfinance": 4, "hist_parquet": 3, "ew_composite": 3, "deriv_csv": 2, "macro_series": 2, "chains_json": 1}
NET_SRC = ("pykrx", "yfinance")
WARNINGS: list[str] = []

# 국내 ETF: screener.etf.KR_MUST (헷지·레버리지·섹터 필수 목록) + 연구에서 자주 쓰는 것
KR_ETF_EXTRA = ["114260", "148070", "091170", "091180", "157450", "152100",
                "379810", "411060", "418670"]  # 10/24 퀀트 ISA 코어(req-data-b372d367)·알록(5b659e78)·애널 사이버보안(c77cf2b8)
KR_INDEX = {"^KS11": "KOSPI", "^KS200": "KOSPI200", "^KQ11": "KOSDAQ"}           # yfinance → 창고 심볼
KRX_INDEX = {"1001": "KOSPI", "1028": "KOSPI200", "2001": "KOSDAQ"}              # pykrx 지수 코드
MACRO_MAP = {"KOSPI": ("kr_index_daily", "KOSPI"), "KOSDAQ": ("kr_index_daily", "KOSDAQ"),
             "SPX": ("us_daily", "^GSPC"), "NASDAQ": ("us_daily", "^IXIC"), "RUT": ("us_daily", "^RUT"),
             "VIX": ("us_daily", "^VIX"), "US10Y": ("us_daily", "^TNX")}
# 미국: 연구에 필요한 핵심만 (크기 예산) — 지수·광역 ETF·섹터 ETF·반도체 체인·메가캡
US_SYMBOLS = ["SPY", "QQQ", "IWM", "DIA", "SOXX", "SMH", "PSI", "XLK", "XLE", "XLF", "XLV", "XLY", "XLP", "XLI", "XLU",
              "XLB", "XLRE", "XLC", "TLT", "IEF", "SHY", "HYG", "LQD", "GLD", "SLV", "USO", "UUP", "EEM", "EWY", "EWJ",
              "FXI", "KWEB", "URA", "LIT", "XBI", "GDX", "COPX", "ITA", "KRE", "IBIT",
              "MU", "SNDK", "NVDA", "AVGO", "AMD", "TSM", "AMAT", "LRCX", "KLAC", "ASML", "WDC", "STX",
              "MSFT", "AAPL", "AMZN", "GOOGL", "META", "TSLA",
              "^GSPC", "^IXIC", "^SOX", "^VIX", "^TNX", "^RUT", "^DJI",
              "MUU", "BUG", "KRW=X", "CL=F"]  # 10/24 행동 MUU(c389dd16)·애널 BUG(c77cf2b8)·퀀트 USDKRW 2010~(b372d367, 야후 KRW=X = 원/달러) · 10/30 퀀트 WTI 근월(4a8febd2, 2020-04-20 음수가 있음 — 수익률은 FRED DCOILWTICO 대조)


def kr_etf_codes() -> list[str]:
    try:
        from screener.etf import KR_MUST
    except Exception:  # noqa: BLE001
        KR_MUST = ["069500", "122630", "252670", "114800", "091160", "139260", "229200", "233740"]
    return sorted(set(KR_MUST) | set(KR_ETF_EXTRA))


# ───────────── 공통 ─────────────

def frame(rows: dict | pl.DataFrame, src: str) -> pl.DataFrame:
    """느슨한 입력 → 창고 스키마. 없는 컬럼은 null, adj_close 없으면 close."""
    df = rows if isinstance(rows, pl.DataFrame) else pl.DataFrame(rows)
    if not len(df):
        return empty()
    for c in ("open", "high", "low", "adj_close", "volume"):
        if c not in df.columns:
            df = df.with_columns(pl.lit(None).alias(c))
    df = df.with_columns(pl.col("adj_close").fill_null(pl.col("close")), pl.lit(src).alias("src"))
    return (df.select(*[pl.col(c).cast(t, strict=False) for c, t in SCHEMA.items()])
              .filter(pl.col("close").is_not_null() & (pl.col("close") > 0) & pl.col("date").is_not_null()))


def split_adjust(df: pl.DataFrame) -> pl.DataFrame:
    """원주가 → adj_close: 기업행위 조정은 공통 규칙 screener.prices.adjust (시가·종가 ±31% + 정리매매 제외)."""
    if not len(df):
        return df
    from screener.prices import adjust
    df = df.sort("symbol", "date")
    a = adjust(df.select("symbol", "date", pl.col("open").cast(pl.Float64), pl.col("close").cast(pl.Float64)), sym="symbol")
    return df.with_columns(a["close"].cast(pl.Float32).alias("adj_close"))


def merge(parts: list[pl.DataFrame]) -> pl.DataFrame:
    parts = [p for p in parts if p is not None and len(p)]
    if not parts:
        return empty()
    df = pl.concat(parts, how="vertical_relaxed").with_columns(
        pl.col("src").replace_strict(PRIORITY, default=0, return_dtype=pl.Int32).alias("_p"))
    return (df.sort("symbol", "date", "_p").unique(["symbol", "date"], keep="last", maintain_order=True)
              .drop("_p").select(*[pl.col(c).cast(t) for c, t in SCHEMA.items()]).sort("symbol", "date"))


def existing(name: str) -> pl.DataFrame:
    p = HIST_DIR / f"{name}.parquet"
    if not p.exists():
        return empty()
    try:
        return pl.read_parquet(p).select(*[pl.col(c).cast(t) for c, t in SCHEMA.items()])
    except Exception as e:  # noqa: BLE001
        log.warning("%s 읽기 실패(%s) → 새로 만듦", p.name, e)
        return empty()


def since(cur: pl.DataFrame, symbols: list[str]) -> date:
    """증분 시작일. 요청 심볼이 모두 네트워크 출처(yfinance/pykrx)로 처음부터 채워져 있으면 가장 이른 '마지막 날짜' - 겹침,
    하나라도 없거나 오프라인 출처(deriv_csv·macro_series·chains_json·hist_parquet)로만 시작하면 2010 부터 전부 다시 받는다."""
    if not len(cur):
        return START
    c = cur.filter(pl.col("symbol").is_in(symbols))
    g = c.group_by("symbol").agg(pl.col("date").min().alias("d0"), pl.col("date").max().alias("d1"),
                                 pl.col("date").filter(pl.col("src").is_in(NET_SRC)).min().alias("n0"))
    if g["symbol"].n_unique() < len(set(symbols)):
        return START
    if g["n0"].null_count() or (g["n0"] > g["d0"] + timedelta(days=30)).any():
        return START
    return max(START, min(g["d1"].to_list()) - timedelta(days=OVERLAP_DAYS))


# ───────────── 오프라인 출처 ─────────────

def src_deriv_csv() -> pl.DataFrame:
    p = ROOT / "data/deriv/daily.csv"
    if not p.exists():
        return empty()
    d = pl.read_csv(p, columns=["date", "kospi_open", "kospi_high", "kospi_low", "kospi_close", "k200_close"],
                    schema_overrides={"date": pl.Utf8}).with_columns(pl.col("date").str.to_date(strict=False))
    kospi = d.select(pl.col("date"), pl.lit("KOSPI").alias("symbol"), pl.col("kospi_open").alias("open"), pl.col("kospi_high").alias("high"),
                     pl.col("kospi_low").alias("low"), pl.col("kospi_close").alias("close"))
    k200 = d.select(pl.col("date"), pl.lit("KOSPI200").alias("symbol"), pl.col("k200_close").alias("close"))
    return pl.concat([frame(kospi, "deriv_csv"), frame(k200, "deriv_csv")])


def src_macro_series() -> dict[str, pl.DataFrame]:
    p = ROOT / "reports/macro_series.json"
    out: dict[str, list] = {f: [] for f in FILES}
    if not p.exists():
        return {}
    ser = json.loads(p.read_text(encoding="utf-8")).get("series", {})
    for key, (fn, sym) in MACRO_MAP.items():
        rows = [r for r in ser.get(key, []) if len(r) >= 5 and r[4]]
        if not rows:
            continue
        out[fn].append(frame({"date": [date.fromisoformat(r[0]) for r in rows], "symbol": sym,
                              "open": [r[1] for r in rows], "high": [r[2] for r in rows], "low": [r[3] for r in rows],
                              "close": [r[4] for r in rows], "volume": [float(r[5]) if len(r) > 5 and r[5] else None for r in rows]},
                             "macro_series"))
    return {k: pl.concat(v) for k, v in out.items() if v}


def src_us_hist() -> pl.DataFrame:
    files = sorted(HIST_DIR.glob("us_[0-9][0-9][0-9][0-9].parquet"))
    if not files:
        return empty()
    lf = pl.concat([pl.scan_parquet(f) for f in files], how="vertical_relaxed").filter(pl.col("yf").is_in(US_SYMBOLS))
    df = lf.rename({"yf": "symbol"}).collect()
    return frame(df, "hist_parquet")


def src_chains_json() -> pl.DataFrame:
    p = ROOT / "reports/chains.json"
    if not p.exists():
        return empty()
    ser = json.loads(p.read_text(encoding="utf-8")).get("series", {})
    parts = []
    for t, rows in ser.items():
        if t in US_SYMBOLS and rows:
            parts.append(frame({"date": [date.fromisoformat(r[0]) for r in rows], "symbol": t, "close": [r[1] for r in rows]}, "chains_json"))
    return pl.concat(parts) if parts else empty()


def src_ew_sectors() -> pl.DataFrame:
    """universe/kr_sector.csv 업종별 동일가중 일간수익 합성지수 (EW:<업종>) + 시장별 (EW:KOSPI, EW:KOSDAQ). 2010-01-04 = 1000.
    종목: 전일 종가 ≥ 1,000원, |일간수익| ≤ 32% (데이터 오류 컷), 업종당 5종목 이상인 날만."""
    sec = ROOT / "universe/kr_sector.csv"
    if not sec.exists() or not list(HIST_DIR.glob("kr_[0-9][0-9][0-9][0-9].parquet")):
        return empty()
    from screener.lab import load_kr
    t0 = time.time()
    px = load_kr().select("yf", "date", "c")
    smap = pl.read_csv(sec, schema_overrides={"code": pl.Utf8}).with_columns(pl.col("code").str.zfill(6))
    px = (px.with_columns(pl.col("yf").str.slice(0, 6).alias("code"), pl.col("yf").str.slice(7).alias("mkt"))
            .join(smap, on="code", how="left")
            .with_columns((pl.col("c") / pl.col("c").shift(1).over("yf") - 1).alias("r"), pl.col("c").shift(1).over("yf").alias("pc"))
            .filter(pl.col("r").is_not_null() & (pl.col("pc") >= 1000) & (pl.col("r").abs() <= 0.32)))
    by_sec = (px.filter(pl.col("sector").is_not_null()).group_by("sector", "date").agg(pl.col("r").mean(), pl.len().alias("n"))
                .filter(pl.col("n") >= 5).with_columns(("EW:" + pl.col("sector")).alias("symbol")))
    by_mkt = (px.group_by("mkt", "date").agg(pl.col("r").mean(), pl.len().alias("n")).filter(pl.col("n") >= 50)
                .with_columns(pl.when(pl.col("mkt") == "KS").then(pl.lit("EW:KOSPI")).otherwise(pl.lit("EW:KOSDAQ")).alias("symbol")))
    comp = (pl.concat([by_sec.select("symbol", "date", "r"), by_mkt.select("symbol", "date", "r")]).sort("symbol", "date")
              .with_columns((1000.0 * (1 + pl.col("r")).cum_prod().over("symbol")).alias("close")))
    log.info("업종 합성지수 %d개, %.0fs", comp["symbol"].n_unique(), time.time() - t0)
    return frame(comp.select("date", "symbol", "close"), "ew_composite")


# ───────────── 네트워크 출처 ─────────────

def yf_download(symbols: list[str], start: date, rename: dict[str, str] | None = None) -> pl.DataFrame:
    """yfinance 일봉 (auto_adjust → close == adj_close). 실패한 배치는 건너뜀."""
    try:
        import pandas as pd
        import yfinance as yf
    except Exception as e:  # noqa: BLE001
        log.warning("yfinance 없음: %s", e)
        return empty()
    parts = []
    for i in range(0, len(symbols), 50):
        chunk = symbols[i:i + 50]
        try:
            raw = yf.download(chunk, start=start.isoformat(), auto_adjust=True, group_by="ticker", threads=True, progress=False, timeout=120)
        except Exception as e:  # noqa: BLE001
            log.warning("yfinance 배치 %d 실패: %r", i // 50, e)
            continue
        if raw is None or raw.empty:
            continue
        if len(chunk) == 1:
            raw = pd.concat({chunk[0]: raw}, axis=1)
        for s in chunk:
            if s not in raw.columns.get_level_values(0):
                continue
            d = raw[s].dropna(subset=["Close"])
            if d.empty:
                continue
            parts.append(frame({"date": [x.date() for x in pd.to_datetime(d.index)], "symbol": (rename or {}).get(s, norm_symbol(s)),
                                "open": d["Open"].astype(float).values, "high": d["High"].astype(float).values,
                                "low": d["Low"].astype(float).values, "close": d["Close"].astype(float).values,
                                "volume": d["Volume"].fillna(0).astype(float).values}, "yfinance"))
        time.sleep(1)
    return pl.concat(parts) if parts else empty()


def _pykrx_ohlcv(fn, code: str, start: date, symbol: str) -> pl.DataFrame:
    import pandas as pd
    d = fn(start.strftime("%Y%m%d"), date.today().strftime("%Y%m%d"), code)
    if d is None or d.empty:
        return empty()
    d = d.rename(columns={"시가": "open", "고가": "high", "저가": "low", "종가": "close", "거래량": "volume"})
    d = d[d["close"] > 0]
    return frame({"date": [x.date() for x in pd.to_datetime(d.index)], "symbol": symbol,
                  "open": d["open"].astype(float).values, "high": d["high"].astype(float).values, "low": d["low"].astype(float).values,
                  "close": d["close"].astype(float).values, "volume": d["volume"].astype(float).values}, "pykrx")


def krx_indices(start: date) -> pl.DataFrame:
    try:
        from pykrx import stock
    except Exception as e:  # noqa: BLE001
        log.warning("pykrx 없음: %s", e)
        return empty()
    parts = []
    for code, sym in KRX_INDEX.items():
        try:
            parts.append(_pykrx_ohlcv(stock.get_index_ohlcv_by_date, code, start, sym))
            time.sleep(0.5)
        except Exception as e:  # noqa: BLE001
            log.warning("pykrx 지수 %s 실패: %r", sym, e)
    return pl.concat(parts) if parts else empty()


def krx_sectors(start: date) -> pl.DataFrame:
    """KRX 업종지수 (KOSPI 1002~, KOSDAQ 2002~) → 'KRX:<이름>'."""
    try:
        from pykrx import stock
    except Exception as e:  # noqa: BLE001
        log.warning("pykrx 없음: %s", e)
        return empty()
    parts, today = [], date.today().strftime("%Y%m%d")
    for mkt in ("KOSPI", "KOSDAQ"):
        try:
            codes = [c for c in stock.get_index_ticker_list(today, market=mkt) if c not in KRX_INDEX]
        except Exception as e:  # noqa: BLE001
            log.warning("pykrx 업종 목록(%s) 실패: %r", mkt, e)
            continue
        for c in codes:
            try:
                name = stock.get_index_ticker_name(c)
                parts.append(_pykrx_ohlcv(stock.get_index_ohlcv_by_date, c, start, f"KRX:{name}"))
                time.sleep(0.5)
            except Exception as e:  # noqa: BLE001
                log.warning("pykrx 업종 %s 실패: %r", c, e)
    return pl.concat(parts) if parts else empty()


def krx_etfs(codes: list[str], start: date) -> pl.DataFrame:
    try:
        from pykrx import stock
    except Exception as e:  # noqa: BLE001
        log.warning("pykrx 없음: %s", e)
        return empty()
    parts = []
    for c in codes:
        try:
            parts.append(_pykrx_ohlcv(stock.get_etf_ohlcv_by_date, c, start, c))
            time.sleep(0.5)
        except Exception as e:  # noqa: BLE001
            log.warning("pykrx ETF %s 실패: %r", c, e)
    return pl.concat(parts) if parts else empty()


# ───────────── 조립 ─────────────

def build(network: bool) -> dict[str, pl.DataFrame]:
    out: dict[str, list[pl.DataFrame]] = {f: [existing(f)] for f in FILES}
    macro = src_macro_series()
    for f, df in macro.items():
        out[f].append(df)
    out["kr_index_daily"].append(src_deriv_csv())
    out["us_daily"].append(src_us_hist())
    out["us_daily"].append(src_chains_json())
    try:
        out["kr_sector_daily"].append(src_ew_sectors())
    except Exception as e:  # noqa: BLE001
        log.warning("업종 합성 실패: %s", e)

    if network:
        etf = kr_etf_codes()
        cur = out["kr_etf_daily"][0]
        got = yf_download([f"{c}.KS" for c in etf], since(cur, etf))
        missing = sorted(set(etf) - set(got["symbol"].unique().to_list() if len(got) else []))
        if missing:
            log.info("yfinance 에 없는 ETF %d개 → pykrx: %s", len(missing), ",".join(missing))
            got = pl.concat([got, krx_etfs(missing, since(cur, missing))])
        out["kr_etf_daily"].append(split_adjust(got) if len(got) else got)

        cur = out["kr_index_daily"][0]
        s = since(cur, list(KRX_INDEX.values()))
        out["kr_index_daily"].append(krx_indices(s))
        out["kr_index_daily"].append(yf_download(list(KR_INDEX), s, KR_INDEX))

        cur = out["kr_sector_daily"][0]
        have = [x for x in cur["symbol"].unique().to_list() if x.startswith("KRX:")] if len(cur) else []
        out["kr_sector_daily"].append(krx_sectors(since(cur, have) if have else START))

        cur = out["us_daily"][0]
        out["us_daily"].append(yf_download(US_SYMBOLS, since(cur, US_SYMBOLS)))

    return {f: merge(parts) for f, parts in out.items()}


def write(frames: dict[str, pl.DataFrame]) -> dict:
    HIST_DIR.mkdir(parents=True, exist_ok=True)
    man_p = HIST_DIR / "_manifest.json"
    old = json.loads(man_p.read_text(encoding="utf-8")) if man_p.exists() else {}
    files, total = {}, 0
    for name, df in frames.items():
        p = HIST_DIR / f"{name}.parquet"
        if not len(df):
            log.info("%s: 데이터 없음 (건너뜀)", name)
            continue
        prev = existing(name)
        if len(prev) == len(df) and prev.equals(df):
            log.info("%s: 변경 없음", name)
        else:
            df.write_parquet(p, compression="zstd", compression_level=9)
            log.info("%s: %d행 %d심볼 → %.1f MB", name, len(df), df["symbol"].n_unique(), p.stat().st_size / 1e6)
        total += p.stat().st_size
        g = df.group_by("symbol").agg(pl.col("date").min().alias("first"), pl.col("date").max().alias("last"), pl.len().alias("rows"),
                                      pl.col("src").mode().first().alias("source")).sort("symbol")
        files[name] = {"rows": len(df), "bytes": p.stat().st_size,
                       "symbols": {r["symbol"]: {"first": r["first"].isoformat(), "last": r["last"].isoformat(), "rows": r["rows"], "source": r["source"]}
                                   for r in g.to_dicts()}}
    man = {"schema": {k: str(v) for k, v in SCHEMA.items()}, "files": files, "total_bytes": total, "warnings": WARNINGS[:40],
           "note": "yfinance 출처는 close==adj_close(배당·분할 반영), pykrx/KRX 는 close 원주가·adj_close 분할보정, EW: 합성지수 2010-01-04=1000"}
    if {k: v for k, v in old.items() if k != "built"} != man:
        man["built"] = date.today().isoformat()
        man_p.write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
    else:
        man["built"] = old.get("built")
    if total > SIZE_BUDGET:
        log.warning("크기 예산 초과: %.1f MB > 25 MB — US_SYMBOLS 를 줄이세요", total / 1e6)
    return man


def main() -> None:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--network", action="store_true", help="yfinance/pykrx 백필 (Actions 에서는 기본)")
    g.add_argument("--offline", action="store_true", help="저장소 안의 자료만 병합")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", stream=sys.stderr)

    class _Cap(logging.Handler):
        def emit(self, r):
            WARNINGS.append(self.format(r)[:300])
    h = _Cap(level=logging.WARNING)
    h.setFormatter(logging.Formatter("%(name)s: %(message)s"))
    logging.getLogger().addHandler(h)
    network = a.network or (not a.offline and bool(os.environ.get("GITHUB_ACTIONS")))
    log.info("build_hist network=%s dir=%s", network, HIST_DIR)
    man = write(build(network))
    for name, info in man["files"].items():
        syms = info["symbols"]
        lo = min(v["first"] for v in syms.values())
        hi = max(v["last"] for v in syms.values())
        print(f"{name:18s} {len(syms):4d} symbols  {info['rows']:8d} rows  {lo}~{hi}  {info['bytes'] / 1e6:.1f} MB")
    print(f"total {man['total_bytes'] / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
