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

from . import briefings, context, dashboard, data, data_krx, detail, indicators, live, news, report, research, scoring, universe
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
        idx = universe.us_index_universe(uni)   # S&P500 ∪ NDX
        uni = idx if idx is not None else universe.us_liquid_subset(uni)  # 실패 시 거래대금 상위 N
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
    last_all = last                                   # 종목 상세는 필터와 무관하게 전 종목
    last = scoring.apply_filters(last, mc.min_price, mc.min_dollar_vol)
    last = scoring.score(last)
    log.info("필터 후 %d종목 · 기준일 %s · %s", len(last), asof, status)

    # 4) 컨텍스트
    br = context.breadth(last, full)
    anom = context.anomalies(last, full)
    macro = data.fetch_macro() if not prices_path else pl.DataFrame(schema={"key": pl.Utf8, "date": pl.Date, "close": pl.Float64})
    mr = context.macro_regime(macro)
    if not prices_path:
        try:
            mr = live.patch_macro(mr)   # 국내 지수는 네이버/KRX 값으로 (야후 오표시 방지)
        except Exception as e:  # noqa: BLE001
            log.warning("국내 지수 보정 실패: %s", e)
    regime_line = context.regime_summary(mr)
    nw = news.build_news_context(last) if not prices_path else None
    if market == "KR":
        try:
            last = research.attach_latest(last, research.load_store(), px)
        except Exception as e:  # noqa: BLE001
            log.warning("리포트 결합 실패: %s", e)

    # 5) 출력
    report.write_markdown(market, status, last, br, anom, mr, mc.top_n, nw)
    msg = report.telegram_summary(market, status, last, br, anom, mr, regime_line, mc.top_n, nw)
    tail = ""
    if status == "CONFIRMED" and not prices_path:
        try:
            tail = briefings.close_kr(last, br) if market == "KR" else briefings.close_us(last, br)
        except Exception as e:  # noqa: BLE001
            log.warning("마감 코멘트 실패: %s", e)
    print(msg + ("\n\n" + tail if tail else ""))
    try:
        dashboard.put_state(f"macro_{market}", mr)
        dashboard.put_state(f"regime_{market}", regime_line)
        dashboard.put_state(f"market_comment_{market}", report.market_comment(br))
        if tail:
            dashboard.put_state(f"close_{market}", tail)
        dashboard.put_state(f"telegram_{market}", msg)
        det = scoring.score(last_all)
        if market == "KR":
            try:
                det = research.attach_latest(det, research.load_store(), px)
            except Exception as e:  # noqa: BLE001
                log.warning("상세용 리포트 결합 실패: %s", e)
        detail.build(market, det, full, research.load_store() if market == "KR" else None, mr, regime_line, br,
                     with_flows=not prices_path)
        dashboard.build()
    except Exception as e:  # noqa: BLE001
        log.warning("대시보드 갱신 실패: %s", e)
    if not no_send:
        report.send_telegram(msg)
        if tail:
            report.send_telegram(tail)
        report.push_gsheet(market, last)


def _record_error(e: BaseException) -> None:
    """실패 원인을 reports/last_error.txt 에 남김 → 워크플로가 커밋 → 로그 없이도 원인 확인 가능."""
    import traceback
    from .config import REPORT_DIR
    REPORT_DIR.mkdir(exist_ok=True)
    (REPORT_DIR / "last_error.txt").write_text(
        f"{datetime.now(ZoneInfo('Asia/Seoul')):%Y-%m-%d %H:%M} KST\n{type(e).__name__}: {e}\n\n{traceback.format_exc()}",
        encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", choices=["KR", "US"])
    ap.add_argument("--mode", default="screen",
                    choices=["screen", "premarket_kr", "intraday_kr", "premarket_us", "intraday_us", "reports", "quotes", "dashboard", "dart"])
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--prices", help="Parquet 경로 (수집 생략)")
    ap.add_argument("--no-send", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        stream=sys.stderr)
    modes = {"premarket_kr": briefings.premarket_kr, "intraday_kr": briefings.intraday_kr,
             "premarket_us": briefings.premarket_us, "intraday_us": briefings.intraday_us,
             "reports": briefings.reports_alert}
    try:
        if a.mode == "quotes":
            print(live.snapshot())
        elif a.mode == "dashboard":   # 알림 없이 웹 데이터만 다시 생성
            dashboard.build()
        elif a.mode == "dart":        # 알림 없이 공시만 수집 (최근 7일)
            from . import dart
            df, n = dart.update(days=7)
            print(f"DART 저장 {df.height}건, 신규 {n}건")
            dashboard.build()
        elif a.mode == "screen":
            if not a.market:
                ap.error("--market 필요")
            run(a.market, a.live, a.prices, a.no_send)
        else:
            out = modes[a.mode](send=not a.no_send)
            print(out)
            try:
                dashboard.put_state(a.mode, out)
                dashboard.build()
            except Exception as e:  # noqa: BLE001
                log.warning("대시보드 갱신 실패: %s", e)
    except Exception as e:  # noqa: BLE001
        _record_error(e)
        raise
    else:
        from .config import REPORT_DIR
        (REPORT_DIR / "last_error.txt").unlink(missing_ok=True)


if __name__ == "__main__":
    main()
