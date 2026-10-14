"""뉴스·이슈 레이어 (Context 전용 — 점수에 합산하지 않음).

소스
1) yfinance 종목 뉴스: 신호 상위 종목에 대해 최근 헤드라인 N개. US 는 풍부, KR 은 종목별로 비어 있는 경우 많음.
2) 텔레그램 채널 (선택): Telethon 유저 세션으로 지정 채널의 최근 메시지를 읽고, 유니버스 종목명과 매칭.
   시크릿: TG_API_ID, TG_API_HASH, TG_SESSION(StringSession), TG_CHANNELS(쉼표 구분 @채널명)
3) fiscal.ai (선택, 미검증): 펀더멘털 컨텍스트 어댑터 자리. FISCAL_AI_KEY 가 있을 때만 호출하며,
   엔드포인트는 계정 문서 기준으로 fetch_fiscal_ai() 안에서 채워야 함.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta, timezone

import polars as pl

log = logging.getLogger(__name__)


# ───────────── 1) yfinance 뉴스 ─────────────

def yf_news(yf_symbols: list[str], per_symbol: int = 3, max_age_days: int = 3) -> dict[str, list[dict]]:
    import yfinance as yf
    out: dict[str, list[dict]] = {}
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    for s in yf_symbols:
        try:
            items = yf.Ticker(s).news or []
        except Exception as e:  # noqa: BLE001
            log.debug("뉴스 실패 %s: %s", s, e)
            continue
        rows = []
        for it in items:
            c = it.get("content", it)  # 신버전은 content 하위에 있음
            title = c.get("title") or it.get("title")
            ts = c.get("pubDate") or it.get("providerPublishTime")
            if isinstance(ts, (int, float)):
                dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            else:
                try:
                    dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                except Exception:  # noqa: BLE001
                    dt = None
            if not title or (dt and dt < cutoff):
                continue
            link = (c.get("canonicalUrl") or {}).get("url") or it.get("link") or ""
            src = (c.get("provider") or {}).get("displayName") or it.get("publisher") or ""
            rows.append({"title": title, "url": link, "source": src, "time": dt.strftime("%m/%d") if dt else ""})
            if len(rows) >= per_symbol:
                break
        if rows:
            out[s] = rows
    return out


# ───────────── 2) 텔레그램 채널 ─────────────

def telegram_channel_mentions(names: pl.DataFrame, hours: int = 24, limit_per_channel: int = 200) -> pl.DataFrame:
    """names: [yf, symbol, name]. 반환: [yf, channel, time, text]"""
    api_id, api_hash = os.environ.get("TG_API_ID"), os.environ.get("TG_API_HASH")
    session, channels = os.environ.get("TG_SESSION"), os.environ.get("TG_CHANNELS", "")
    empty = pl.DataFrame(schema={"yf": pl.Utf8, "channel": pl.Utf8, "time": pl.Utf8, "text": pl.Utf8})
    if not (api_id and api_hash and session and channels):
        return empty
    try:
        from telethon.sessions import StringSession  # type: ignore
        from telethon.sync import TelegramClient  # type: ignore
    except ImportError:
        log.warning("telethon 미설치 — 텔레그램 채널 레이어 생략")
        return empty

    # 2글자 이하·너무 흔한 이름은 오탐이 커서 제외
    pats = [(r["yf"], re.compile(re.escape(r["name"]))) for r in names.to_dicts() if len(str(r["name"])) >= 3]
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = []
    try:
        with TelegramClient(StringSession(session), int(api_id), api_hash) as client:
            for ch in [c.strip() for c in channels.split(",") if c.strip()]:
                for msg in client.iter_messages(ch, limit=limit_per_channel):
                    if msg.date < cutoff:
                        break
                    text = (msg.message or "").strip()
                    if not text:
                        continue
                    for yf_sym, pat in pats:
                        if pat.search(text):
                            rows.append({"yf": yf_sym, "channel": ch, "time": msg.date.astimezone().strftime("%m/%d %H:%M"),
                                         "text": text[:160].replace("\n", " ")})
    except Exception as e:  # noqa: BLE001
        log.error("텔레그램 채널 읽기 실패: %s", e)
        return empty
    return pl.DataFrame(rows) if rows else empty


# ───────────── 3) fiscal.ai 어댑터 (자리만) ─────────────

def fetch_fiscal_ai(symbols: list[str]) -> dict[str, dict]:
    """FISCAL_AI_KEY 가 있을 때만. 엔드포인트·응답 포맷은 계정의 API 문서로 확인 후 채울 것.
    반환 예: {"AAPL": {"rev_growth": 0.08, "fcf_margin": 0.25, "ev_ebitda": 22.1}}"""
    key = os.environ.get("FISCAL_AI_KEY")
    if not key:
        return {}
    log.warning("fiscal.ai 어댑터는 미구현 — API 문서 확인 후 fetch_fiscal_ai() 를 채우세요")
    return {}


# ───────────── 조립 ─────────────

def build_news_context(last: pl.DataFrame, top_per_section: int = 8) -> dict:
    """신호 상위 종목(추세상승·눌림·반등·과열)에 한해 뉴스 수집. 전체 유니버스는 호출 수 때문에 제외."""
    focus = pl.concat([
        last.filter(pl.col("class") == "TREND_LONG").sort("trend_score", descending=True).head(top_per_section),
        last.filter(pl.col("class") == "PULLBACK_IN_UPTREND").sort("trend_score", descending=True).head(top_per_section),
        last.filter(pl.col("class") == "COUNTERTREND_BOUNCE").sort("momentum_score", descending=True).head(top_per_section),
        last.filter(pl.col("reversal_risk") >= 60).sort("reversal_risk", descending=True).head(top_per_section),
    ]).unique(subset=["yf"], maintain_order=True)
    ctx = {"yf": {}, "tg": pl.DataFrame(), "fiscal": {}}
    try:
        ctx["yf"] = yf_news(focus["yf"].to_list())
    except Exception as e:  # noqa: BLE001
        log.warning("yfinance 뉴스 실패: %s", e)
    ctx["tg"] = telegram_channel_mentions(last.select("yf", "symbol", "name"))
    ctx["fiscal"] = fetch_fiscal_ai(focus["symbol"].to_list())
    return ctx
