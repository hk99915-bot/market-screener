"""엔트리포인트.

python -m screener.main --market KR          # 국내 마감 후
python -m screener.main --market US          # 미국 마감 후
python -m screener.main --market KR --live   # 장중 [LIVE] 태그 (종가 미확정)
python -m screener.main --market KR --prices data/kr_prices.parquet  # 캐시/합성 데이터로 실행
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime
from zoneinfo import ZoneInfo

import polars as pl

from . import context, data, data_krx, indicators, news, report, scoring, universe
from .config import CFG

log = logging.getLogger("screener")


def _status(market_tz: str, live: bool) -> str:
    """기획 원칙: 장중 [LIVE] vs 종가 [CONFIRMED]. 로컬 시각이 장중이면 강제로 LIVE."""
    now = datetime.now(ZoneInfo(market_tz))
    hm = now.hour * 100 + now.minute
    in_session = (900 <= hm < 1540) if market_tz == "Asia/Seoul" else (930 <= hm < 1605)
    return "LIVE" if (live or (in_session and now.weekday() < 5)) else "CONFIRMED"


def run(market: str, live: bool = False, prices_path: str | None = None, no_send: bool = False) -> None:
    mc = CFG.kr if market == "KR" else CFG.us
    status = _status(mc.tz, live)

    # 1) 유니버스
    uni = universe.kr_universe() if market == "KR" else universe.us_universe()
    if mc.min_mcap and "mcap" in uni.columns and uni["mcap"].null_count() < len(uni):
        uni = uni.filter(pl.col("mcap").is_null() | (pl.col("mcap") >= mc.min_mcap))
    if market == "US" and not prices_path:
        uni = universe.us_liquid_subset(uni)   # 전종목 → 거래대금 상위 N (기본 1500)
    log.info("%s 유니버스 %d종목", market, len(uni))

    # 2) 시세
    if prices_path:
        px = pl.read_parquet(prices_path)
    elif market == "KR":
        px = data_krx.fetch_prices_krx()          # KRX 공식 데이터 (증분)
    else:
        px = data.fetch_prices(uni["yf"].to_list(), market)
    px = px.filter(pl.col("yf").is_in(uni["yf"].implode()))
    log.info("시세 %d행 / %d종목", len(px), px["yf"].n_unique())

    # 3) 지표 → 최신행 → 필터 → 점수
    full = indicators.add_indicators(px)
    last = indicators.latest(full).join(uni.select("yf", "symbol", "name", "market"), on="yf", how="left")
    # 유니버스 전체가 같은 날짜여야 함: 최빈 날짜 외(상폐·거래정지)는 제외
    asof = last["date"].mode()[0]
    last = last.filter(pl.col("date") == asof)
    last = scoring.apply_filters(last, mc.min_price, mc.min_dollar_vol)
    last = scoring.score(last)
    log.info("필터 후 %d종목 · 기준일 %s · %s", len(last), asof, status)

    # 4) 컨텍스트
    br = context.breadth(last, full)
    anom = context.anomalies(last, full)
    macro = data.fetch_macro() if not prices_path else pl.DataFrame(schema={"key": pl.Utf8, "date": pl.Date, "close": pl.Float64})
    mr = context.macro_regime(macro)
    regime_line = context.regime_summary(mr)
    nw = news.build_news_context(last) if not prices_path else None

    # 5) 출력
    report.write_markdown(market, status, last, br, anom, mr, mc.top_n, nw)
    msg = report.telegram_summary(market, status, last, br, anom, mr, regime_line, mc.top_n, nw)
    print(msg)
    if not no_send:
        report.send_telegram(msg)
        report.push_gsheet(market, last)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", choices=["KR", "US"], required=True)
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--prices", help="Parquet 경로 (수집 생략)")
    ap.add_argument("--no-send", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        stream=sys.stderr)
    run(a.market, a.live, a.prices, a.no_send)


if __name__ == "__main__":
    main()
