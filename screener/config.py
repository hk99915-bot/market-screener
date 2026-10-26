"""전역 설정. 환경변수로 덮어쓸 수 있는 값은 os.environ 참조."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"          # Parquet 캐시 (gitignore)
UNIVERSE_DIR = ROOT / "universe"  # 유니버스 CSV (커밋됨, 폴백용)
REPORT_DIR = ROOT / "reports"

# 운용회의 TOP3 v2 규칙 스위치 (CIO 진단 reports/studies/cio_top3_review_2026-10-21.md §5 P1~P3, 10/21 개발 데스크).
# False = 기존 결과 그대로(10/21 01시 기준). True = P1 필수 5칸 없으면 TOP3 자격 없음 · P2 실행 후보 우선, 대기는 시장당 하루 1개,
# 자기 참조 원천(exec_plan·committee_ideas) 합산 대신 max + 동점 정렬(촉매 있음 우선) · P3 진입 하한 = max(손절+0.5R, 종가−0.5×ATR).
# 10/21 02:3x·02:4x·02:5x 겸이 명시 승인으로 [13](22:00~07:00 규칙 변경 금지) 예외 ON. 되돌리기 = 아래 한 줄을 False 로.
# 범위: 운용회의 TOP3 표시·모의 추적(idea_tracking)만 — 포트폴리오 한도·주문 경로(pb 등)는 읽지 않음(tests/test_cio_top3_v2.py::Scope).
CIO_TOP3_V2 = True

# 실계좌 위성(신규 종목) 해금 여부 — 운용회의 신호등 표시만 (10/21 겸이 승인 B1). False 면 TOP3 '실행 후보'는 🟡 '모의 추적 후보 n개'
# (🔴 '오늘 행동 필요'는 해금 + 판정이 매수 쪽일 때만 후보로 켠다). 원장은 읽지 않는다 — 해금되면 이 한 줄을 True 로.
SATELLITE_LIVE = False

# 보고 상단 3줄형(① What ② So What ③ Now What + 원본) 텔레그램 적용 스위치 — STANDARD.md 8절 · 보드 report-format-rollout.
# False = 기존 텔레그램 그대로(JSON `top` 키는 항상 생성). True = 운용회의(국·미)·HF 알파북 꼬리·데일리 브리프 상단을 topline.render_tg3 로.
# 샘플 1건씩 겸이 확인 후 True (지시서 rounds/2026-10-26/report_format_rollout.md 4절 2단계). 되돌리기 = False.
TOPLINE_TG = False

# 토스 EOD 보충 검증 게이트 (보드 us-eod-toss, 10/21 오너 "토스 보충이 실데이터로 검증 안 됐으면 검증을 하고 넣어").
# 매일 보충 직전에 us_eod.json 의 '전날' 봉(prev)을 야후 같은 날짜 봉과 대조 → 통과할 때만 보충, 불일치 종목은 개별 제외.
# - 종가 허용 0.1%: 둘 다 같은 거래소 정규장 종가(마감 단일가)라 원래 센트 단위로 같아야 함. publish 반올림(소수 4자리)은 $1 이상에서
#   <0.01% → 10배 여유. 0.1% 를 넘는 건 날짜 어긋남·시간외 가격 섞임·분할/배당 수정 차이(야후 auto_adjust) 같은 실제 불일치.
# - 겹침 ≥90%: 유니버스 중 토스 prev·야후 같은 날 봉이 둘 다 있는 종목 비율. 그 아래면 수집 일부만 됨·날짜 어긋남 같은 계통 문제.
# - 일치 ≥98%: S&P500∪NDX 하루 배당락·분할 종목은 보통 수 개(≤2%) — 그만큼은 개별 제외로 흡수, 넘으면 계통 불일치로 보고 전체 보류.
# 시가·고가·저가·거래량 괴리는 기록만(게이트 아님 — 거래량 집계 범위가 출처마다 달라 정의 미확인).
TOSS_EOD_CLOSE_TOL = 0.001
TOSS_EOD_MIN_OVERLAP = 0.90
TOSS_EOD_MIN_MATCH = 0.98


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
        "NIKKEI": "^N225", "TOPIX": "1306.T",   # 일본 (도쿄도 09:00 KST 개장) — 야후에 TOPIX 지수(^TOPX)가 없어 TOPIX ETF 로 대체
    })
    telegram_token: str = os.environ.get("TELEGRAM_TOKEN", "")
    telegram_chat: str = os.environ.get("TELEGRAM_CHAT_ID", "")
    gsheet_id: str = os.environ.get("GSHEET_ID", "")
    gcp_sa_json: str = os.environ.get("GCP_SA_JSON", "")


CFG = Cfg()
