"""엔트리포인트.

python -m screener.main --market KR          # 국내 마감 후
python -m screener.main --market US          # 미국 마감 후
python -m screener.main --market KR --live   # 장중 [LIVE] 태그 (종가 미확정)
python -m screener.main --market KR --prices data/kr_prices.parquet  # 캐시/합성 데이터로 실행
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, datetime
from zoneinfo import ZoneInfo

import polars as pl

from . import briefings, context, dashboard, data, data_krx, detail, indicators, live, news, report, research, scoring, universe
from .config import CFG, DATA_DIR, REPORT_DIR

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
    if not prices_path and len(macro):
        write_macro_series(macro)
        try:
            mv = json.loads((REPORT_DIR / "macro_view.json").read_text(encoding="utf-8"))
            if mv.get("summary"):
                regime_line = mv["summary"] + (" · " + regime_line if regime_line else "")
        except Exception:  # noqa: BLE001
            pass
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
        try:
            from . import momentum
            momentum.ranks(full, last, market)
        except Exception as e:  # noqa: BLE001
            log.warning("모멘텀 순위 실패: %s", e)
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


class _Redact(logging.Filter):
    """로그에 비밀값(API 키·비밀번호·토큰)이 찍히지 않게 가림 — 로그 파일이 공개 저장소에 커밋되므로."""
    def __init__(self) -> None:
        super().__init__()
        import os
        self.secrets = [v for k, v in os.environ.items()
                        if any(t in k for t in ("KEY", "TOKEN", "PW", "PASS", "SECRET", "CHAT")) and v and len(v) >= 6]

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        for v in self.secrets:
            msg = msg.replace(v, "***")
        import re as _re
        msg = _re.sub(r"(crtfc_key=)[^&\s'\"]+", r"\1***", msg)
        msg = _re.sub(r"bot\d+:[A-Za-z0-9_-]+", "bot***", msg)
        record.msg, record.args = msg, None
        return True


def _file_log(name: str | None) -> None:
    """실행 로그를 reports/logs/{name}.log 에 남김 (마지막 실행분만, 비밀값 가림)."""
    from .config import REPORT_DIR
    d = REPORT_DIR / "logs"
    d.mkdir(parents=True, exist_ok=True)
    h = logging.FileHandler(d / f"{name or 'run'}.log", mode="w", encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    red = _Redact()
    h.addFilter(red)
    root = logging.getLogger()
    for hh in root.handlers:
        hh.addFilter(red)
    root.addHandler(h)


def _krx_override(ser: dict) -> None:
    """야후 한국 지수는 하루 늦게 들어오거나 장중 값이 남아 있음 → 최근 15일은 KRX 확정 일봉으로 덮어씀 (날짜 정렬 기준 = KRX)."""
    try:
        from datetime import date as _d, timedelta as _td
        from pykrx import stock  # type: ignore
        t = _d.today()
        for key, code in (("KOSPI", "1001"), ("KOSDAQ", "2001")):
            df = stock.get_index_ohlcv((t - _td(days=21)).strftime("%Y%m%d"), t.strftime("%Y%m%d"), code)
            if df is None or not len(df):
                continue
            rows = {r[0]: r for r in ser.get(key, [])}
            for i, x in df.iterrows():
                ds = str(i.date())
                c = float(x["종가"])
                if c <= 0:
                    continue
                rows[ds] = [ds, float(x["시가"]) or c, float(x["고가"]) or c, float(x["저가"]) or c, c, int(x.get("거래량") or 0)]
            ser[key] = [rows[k] for k in sorted(rows)]
        log.info("KRX 지수 일봉으로 코스피·코스닥 최근분 보정")
    except Exception as e:  # noqa: BLE001
        log.warning("KRX 지수 보정 실패: %s", e)


def write_macro_series(macro: pl.DataFrame | None = None) -> None:
    """매크로 지표 일봉 OHLCV 2년 → reports/macro_series.json (웹 티커·매크로 표 클릭 차트용).
    항목: [날짜, 시가, 고가, 저가, 종가, 거래량]. 스크린용 200일 데이터와 별도로 2년치를 받는다."""
    import json as _json
    from .config import REPORT_DIR
    try:
        try:
            long = data.fetch_prices(list(CFG.macro.values()), "MACRO", lookback_days=760)
            inv = {v: k for k, v in CFG.macro.items()}
            macro = long.with_columns(pl.col("yf").replace_strict(inv, default=pl.col("yf")).alias("key"))
        except Exception as e:  # noqa: BLE001
            log.warning("매크로 2년 수집 실패, 기존 데이터 사용: %s", e)
            macro = data.fetch_macro() if macro is None else macro
        if not len(macro):
            return
        r = lambda v: None if v is None else round(float(v), 4)  # noqa: E731
        cols = [c for c in ("open", "high", "low", "close", "volume") if c in macro.columns]
        ser = {}
        for (k,), g in macro.sort("date").group_by("key", maintain_order=True):
            rows = []
            for x in g.select("date", *cols).to_dicts():
                if x.get("close") is None:
                    continue
                c = r(x["close"])
                o, h, lo = r(x.get("open")) or c, r(x.get("high")) or c, r(x.get("low")) or c
                rows.append([str(x["date"]), o, max(h, o, c), min(lo, o, c), c, int(x.get("volume") or 0)])
            ser[k] = rows
        _krx_override(ser)
        (REPORT_DIR / "macro_series.json").write_text(_json.dumps(
            {"asof": str(macro["date"].max()), "fmt": "dohlcv", "series": ser}, ensure_ascii=False), encoding="utf-8")
        try:
            from . import macroview
            macroview.build()
        except Exception as e:  # noqa: BLE001
            log.warning("매크로 해설 실패: %s", e)
    except Exception as e:  # noqa: BLE001
        log.warning("매크로 시계열 저장 실패: %s", e)


def rebuild_detail_kr() -> None:
    """저장된 KR 일봉(어제 종가까지)으로 종목 상세 파일만 다시 생성. 알림·리포트·매크로 상태는 건드리지 않음."""
    import json as _json
    from .config import REPORT_DIR
    mc = CFG.kr
    uni = universe.kr_universe()
    if mc.min_mcap and "mcap" in uni.columns and uni["mcap"].null_count() < len(uni):
        uni = uni.filter(pl.col("mcap").is_null() | (pl.col("mcap") >= mc.min_mcap))
    px = pl.read_parquet(DATA_DIR / "kr_prices.parquet").filter(pl.col("yf").is_in(uni["yf"].implode()))
    full = indicators.add_indicators(px)
    last = indicators.latest(full).join(uni.select("yf", "symbol", "name", "market"), on="yf", how="left")
    asof = last["date"].mode()[0]
    last_all = last.filter(pl.col("date") == asof)
    flt = scoring.score(scoring.apply_filters(last_all, mc.min_price, mc.min_dollar_vol))
    br = context.breadth(flt, full)
    try:
        st = _json.loads((REPORT_DIR / "dashboard_state.json").read_text(encoding="utf-8"))
        mr = (st.get("macro_KR") or {}).get("value") or []
        regime_line = (st.get("regime_KR") or {}).get("value") or ""
    except Exception:  # noqa: BLE001
        mr, regime_line = [], ""
    store = research.load_store()
    try:
        from . import momentum
        momentum.ranks(full, flt, "KR")
    except Exception as e:  # noqa: BLE001
        log.warning("모멘텀 순위 실패: %s", e)
    det = scoring.score(last_all)
    try:
        det = research.attach_latest(det, store, px)
    except Exception as e:  # noqa: BLE001
        log.warning("리포트 결합 실패: %s", e)
    detail.build("KR", det, full, store, mr, regime_line, br, with_flows=True)


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
                    choices=["screen", "premarket_kr", "intraday_kr", "premarket_us", "intraday_us", "reports", "quotes", "dashboard", "dart", "fin", "detail_kr", "analysts", "momentum", "portfolios", "shares", "probe", "drivers", "etf", "pb", "themes", "study", "calendar", "committee", "close_kr", "duel", "pb_call"])
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--prices", help="Parquet 경로 (수집 생략)")
    ap.add_argument("--no-send", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        stream=sys.stderr)
    _file_log(a.market if a.mode == "screen" else a.mode)
    modes = {"premarket_kr": briefings.premarket_kr, "intraday_kr": briefings.intraday_kr,
             "premarket_us": briefings.premarket_us, "intraday_us": briefings.intraday_us,
             "reports": briefings.reports_alert}
    try:
        if a.mode == "quotes":
            snap = live.snapshot()
            print(snap)
            try:   # 서킷브레이커·사이드카 감지 → events.json + 텔레그램(새 이벤트만, --no-send 와 무관)
                from . import events
                events.check(snap, send=True)
                events.stats()
            except Exception as e:  # noqa: BLE001
                log.warning("이벤트 추적 실패: %s", e)
        elif a.mode == "pb_call":   # PB 재량 판단 기록 (예약 세션 → workflow_dispatch payload)
            import os as _os
            from . import duel
            print(duel.record_pb(json.loads(_os.environ.get("PB_PAYLOAD") or "{}"), send=not a.no_send))
        elif a.mode == "duel":   # 14:55 진입 타점 대결 (PB 판정 기록 + 텔레그램)
            from . import duel
            print(duel.run(send=not a.no_send))
        elif a.mode == "close_kr":   # 장 마감 후: 모든 화면의 코스피를 KRX 확정 종가로 맞춤 (텔레그램 없음)
            try:
                live.snapshot()
            except Exception as e:  # noqa: BLE001
                log.warning("시세 실패: %s", e)
            try:   # 종목 상세(차트·가격·시나리오)도 확정 종가로 — 16:20 스크리너보다 먼저 반영
                rebuild_detail_kr()
            except Exception as e:  # noqa: BLE001
                log.warning("종목 상세 갱신 실패: %s", e)
            try:   # 마감 해석은 별도 키 — 장중(판단 시점) 기록은 덮어쓰지 않음
                briefings.intraday_kr(send=False, state_key="close_snapshot")
            except Exception as e:  # noqa: BLE001
                log.warning("마감 해석 실패: %s", e)
            write_macro_series()
            try:
                from . import dashboard as _db
                _db.build() if hasattr(_db, "build") else None
            except Exception as e:  # noqa: BLE001
                log.warning("대시보드 실패: %s", e)
            try:
                from . import daily
                daily.build()
            except Exception as e:  # noqa: BLE001
                log.warning("데일리 실패: %s", e)
            try:
                from . import calendar_ev, committee, derivs
                try:
                    derivs.build()
                except Exception as e:  # noqa: BLE001
                    log.warning("옵션 포지션 실패: %s", e)
                committee.build("장후")
                calendar_ev.build()
            except Exception as e:  # noqa: BLE001
                log.warning("운용회의 실패: %s", e)
        elif a.mode == "dashboard":   # 알림 없이 웹 데이터 갱신 (리포트·요약 수집 포함)
            try:
                research.update_store()
            except Exception as e:  # noqa: BLE001
                log.warning("리포트 갱신 실패: %s", e)
            write_macro_series()
            try:
                from . import events
                events.stats()
            except Exception as e:  # noqa: BLE001
                log.warning("이벤트 통계 실패: %s", e)
            try:
                from . import calendar_ev
                calendar_ev.build()
            except Exception as e:  # noqa: BLE001
                log.warning("캘린더 실패: %s", e)
            dashboard.build()
        elif a.mode == "detail_kr":   # 종목 상세만 재생성 (어제 종가 기준, 알림 없음)
            rebuild_detail_kr()
        elif a.mode == "committee":    # 운용회의 자료 (+텔레그램)
            from . import committee
            try:
                from . import derivs
                derivs.build()
            except Exception as e:  # noqa: BLE001
                log.warning("옵션 포지션 실패: %s", e)
            o = committee.build()
            ou = committee.build_us()
            if not a.no_send:
                from .report import send_telegram
                send_telegram(committee.telegram_text(o))
                send_telegram(committee.telegram_text_us(ou))
        elif a.mode == "calendar":     # 실적·이벤트 캘린더
            from . import calendar_ev
            print(len(calendar_ev.build()["events"]))
        elif a.mode == "study":        # 검증 스터디 (급락 후 반등·레버리지 매매)
            from . import study
            study.run()
        elif a.mode == "themes":       # 테마 분류 강제 갱신 (네이버 모바일 API)
            from .themes import kr_themes
            print(len(kr_themes(force=True)))
        elif a.mode == "pb":           # PB 아침 점검만 (MY_HOLDINGS 시크릿 필요)
            from . import pb
            pb.send()
        elif a.mode == "etf":          # ETF 상세만 재생성 (KR·US)
            from . import etf
            print(etf.build("KR"), etf.build("US"))
        elif a.mode == "probe":
            from . import probe
            print(probe.run())
        elif a.mode == "shares":      # 주식 수(DART 자사주 제외·우선주 포함 + KRX 상장주식수) → 가치평가 재계산
            from . import shares
            from .config import UNIVERSE_DIR
            u = pl.read_csv(UNIVERSE_DIR / "kr.csv", schema_overrides={"symbol": pl.Utf8})
            print("주식 수", shares.update(u["symbol"].to_list()))
            rebuild_detail_kr()
        elif a.mode == "fin":         # 재무제표 수집 (알림 없음): KR(DART) + US(SEC)
            from . import fin
            print(fin.update())
            try:
                from . import shares
                from .config import UNIVERSE_DIR
                u = pl.read_csv(UNIVERSE_DIR / "kr.csv", schema_overrides={"symbol": pl.Utf8})
                print("주식 수", shares.update(u["symbol"].to_list()))
            except Exception as e:  # noqa: BLE001
                log.warning("주식 수 실패: %s", e)
            try:
                from . import sec
                from .config import UNIVERSE_DIR
                us = pl.read_csv(UNIVERSE_DIR / "us_index.csv")["yf"].to_list() if (UNIVERSE_DIR / "us_index.csv").exists() else []
                print("SEC", sec.update(us))
            except Exception as e:  # noqa: BLE001
                log.warning("SEC 재무 실패: %s", e)
        elif a.mode == "portfolios":  # 모의 포트폴리오 (ETF·지수, 2011~)
            from . import portfolios
            portfolios.run()
        elif a.mode == "momentum":    # 모멘텀 백테스트(국장 2010~)
            from . import momentum
            momentum.backtest_kr()
        elif a.mode == "analysts":    # 과거 리포트 백필(최초 1회) + 애널리스트 성향·적중률
            from . import analysts
            research.backfill_hankyung()
            print(analysts.build())
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
            if a.mode in ("premarket_kr", "reports", "intraday_kr"):   # 판단 성적표 채점 (다음 거래일 시가가 생기면)
                try:
                    from . import decisions
                    decisions.score()
                except Exception as e:  # noqa: BLE001
                    log.warning("성적표 채점 실패: %s", e)
            if a.mode in ("premarket_kr", "reports"):   # 캘린더는 하루 두 번 갱신 (장전 브리핑 D-2 에 쓰임)
                try:
                    from . import calendar_ev
                    calendar_ev.build()
                except Exception as e:  # noqa: BLE001
                    log.warning("캘린더 실패: %s", e)
            out = modes[a.mode](send=not a.no_send)
            print(out)
            if a.mode == "reports":   # 저녁 운용회의
                try:
                    from . import committee
                    try:
                        from . import derivs
                        derivs.build()
                    except Exception as e:  # noqa: BLE001
                        log.warning("옵션 포지션 실패: %s", e)
                    o = committee.build("장후")
                    ou = committee.build_us()
                    if not a.no_send:
                        from .report import send_telegram
                        send_telegram(committee.telegram_text(o))
                        send_telegram(committee.telegram_text_us(ou))
                except Exception as e:  # noqa: BLE001
                    log.warning("운용회의 실패: %s", e)
            if a.mode in ("premarket_kr", "intraday_kr"):   # 장전·장중 운용회의 (웹 기록용, 텔레그램은 저녁 회의만)
                try:
                    from . import committee
                    committee.build("장전" if a.mode == "premarket_kr" else "장중")
                except Exception as e:  # noqa: BLE001
                    log.warning("운용회의(%s) 실패: %s", a.mode, e)
            if a.mode == "premarket_kr" and not a.no_send:
                try:
                    from . import pb
                    pb.send()
                except Exception as e:  # noqa: BLE001
                    log.warning("PB 점검 실패: %s", type(e).__name__)
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
