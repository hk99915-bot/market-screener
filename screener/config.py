"""전역 설정. 환경변수로 덮어쓸 수 있는 값은 os.environ 참조."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"          # Parquet 캐시 (gitignore)
UNIVERSE_DIR = ROOT / "universe"  # 유니버스 CSV (커밋됨, 폴백용)
REPORT_DIR = ROOT / "reports"


@dataclass
class MarketCfg:
    name: str                       # "KR" | "US"
    tz: str
    min_price: float                # 저가주 제외
    min_dollar_vol: float           # 20일 평균 거래대금 하한 (현지통화)
    min_mcap: float | None          # 시총 하한 (유니버스 소스가 제공할 때만)
    top_n: int = 15                 # 텔레그램 요약 종목 수


@dataclass
class Cfg:
    lookback_days: int = 400        # 지표 계산용 (SMA200 + 여유)
    batch_size: int = 150           # yfinance 배치 크기
    threads: int = 8
    kr: MarketCfg = field(default_factory=lambda: MarketCfg(
        name="KR", tz="Asia/Seoul", min_price=1000, min_dollar_vol=1_000_000_000,  # 10억원
        min_mcap=100_000_000_000))                                                # 1000억
    us: MarketCfg = field(default_factory=lambda: MarketCfg(
        name="US", tz="America/New_York", min_price=3.0, min_dollar_vol=5_000_000,  # $5M
        min_mcap=None))
    # 매크로 컨텍스트 심볼 (yfinance)
    macro: dict[str, str] = field(default_factory=lambda: {
        "WTI": "CL=F", "US10Y": "^TNX", "USDJPY": "JPY=X", "USDKRW": "KRW=X",
        "DXY": "DX-Y.NYB", "VIX": "^VIX", "SPX": "^GSPC", "KOSPI": "^KS11", "KOSDAQ": "^KQ11",
        "NASDAQ": "^IXIC", "RUT": "^RUT", "GOLD": "GC=F", "BTC": "BTC-USD",
        "NIKKEI": "^N225", "TOPIX": "^TOPX",   # 일본 (도쿄도 09:00 KST 개장) — japan.py
    })
    telegram_token: str = os.environ.get("TELEGRAM_TOKEN", "")
    telegram_chat: str = os.environ.get("TELEGRAM_CHAT_ID", "")
    gsheet_id: str = os.environ.get("GSHEET_ID", "")
    gcp_sa_json: str = os.environ.get("GCP_SA_JSON", "")


CFG = Cfg()
