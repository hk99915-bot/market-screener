"""전략 연구소 (전략 공장): 사전 등록 가설 → 공통 백테스트 하네스 → 코드로 고정된 통계 관문 → 등급.

원칙
- 가설은 테스트 전에 REGISTRY 에 적는다 (등록일 고정). 결과를 보고 규칙을 고치면 새 id 로 다시 등록한다.
- 신호는 t일 종가까지의 데이터만 사용 → t+1 시가 진입, t+hold 종가 청산 (GAPDOWN 은 당일 시가 갭이 보이는 순간 진입).
- 2026-10-16: 진입 변형 'close'(t+1 종가 진입, 진입일 기준 전일까지 데이터만 사용) 추가 — 관문 m 은 (가설×진입) 조합 수.
- 비용 왕복 0.25% 차감, 기준 2개 = 유동성 유니버스 동일가중(EW) + 코스피 프록시(KOSPI, 규모가중). 등급은 두 기준 모두 통과해야 함.
  주 지표 = 리밸런싱당 초과수익.
- 겹치는 보유기간은 t-통계를 부풀리므로 겹치지 않는 날짜만 평가한다.
- 등급 관문은 고정 코드 (Bonferroni 보정 IS → OOS → 잠긴 HOLDOUT).

실행: python -m screener.main --mode lab  → reports/lab.json
"""
from __future__ import annotations

import json
import logging
import math
import time
from datetime import date, datetime
from statistics import NormalDist

import polars as pl

from .config import DATA_DIR, REPORT_DIR, UNIVERSE_DIR

log = logging.getLogger(__name__)

REG = "2026-10-15"
REG2 = "2026-10-16"      # 2차 등록 (코스피 프록시 기준·진입 변형·신규 가설 3개)
COST = 0.0025            # 왕복 비용
MIN_PX = 1000            # 원
MIN_TV = 5e9             # 20일 평균 거래대금 50억원
BAD = 0.32               # 가격제한폭 30% 초과 일간 변동 = 데이터 오류
TOP_TV = 200
SPLITS = {"IS": (date(2010, 1, 1), date(2019, 12, 31)),
          "OOS": (date(2020, 1, 1), date(2023, 12, 31)),
          "HOLDOUT": (date(2024, 1, 1), date(2100, 1, 1))}

REGISTRY: list[dict] = [
    {"id": "TREND_12_1", "name": "12-1 모멘텀", "family": "추세추종", "hold": 20,
     "hypothesis": "지난 12개월(최근 1개월 제외) 많이 오른 종목은 투자자의 과소반응 때문에 다음 한 달도 시장보다 더 오른다.",
     "rule": "20거래일마다 12-1개월 수익률 상위 10% 동일가중 매수, 20거래일 보유"},
    {"id": "REV_5D", "name": "단기 반전", "family": "평균회귀", "hold": 5,
     "hypothesis": "5일간 가장 많이 빠진 종목은 유동성 충격·과잉반응이 풀리며 다음 5일 시장보다 더 오른다.",
     "rule": "5일 수익률 하위 10% 동일가중 매수, 5거래일 보유"},
    {"id": "CRASH_REBOUND", "name": "급락장 반등 (5일)", "family": "이벤트", "hold": 5,
     "hypothesis": "시장 전체가 이미 크게 빠진 상태에서 하루 더 급락하면 투매가 과도해 대형 유동주가 단기 반등한다.",
     "rule": "유동성 유니버스 동일가중 지수 일간 −4% 이하 & 20일 고점 대비 −10% 이하인 날, 거래대금 상위 200종목 다음날 시가 매수, 5거래일 보유"},
    {"id": "CRASH_REBOUND_20", "name": "급락장 반등 (20일)", "family": "이벤트", "hold": 20,
     "hypothesis": "같은 급락 이벤트 후 반등이 한 달 동안 이어진다.",
     "rule": "CRASH_REBOUND 와 같은 진입, 20거래일 보유"},
    {"id": "HI52_BREAK", "name": "52주 신고가 돌파", "family": "돌파", "hold": 20,
     "hypothesis": "52주 고점 근처에서 거래량이 터지면 기준점(앵커링) 저항이 깨진 것이라 이후 한 달 추세가 이어진다.",
     "rule": "종가가 252일 고가의 2% 이내 & 거래량 ≥ 직전 20일 평균의 2배인 종목 매수, 20거래일 보유"},
    {"id": "LOWVOL", "name": "저변동성", "family": "저변동", "hold": 20,
     "hypothesis": "변동성이 낮은 종목은 복권형 종목 선호 때문에 저평가돼 위험 대비 더 나은 수익을 낸다.",
     "rule": "20거래일마다 60일 일간 변동성 하위 10% 동일가중 매수, 20거래일 보유"},
    {"id": "GAPDOWN_INTRADAY", "name": "갭하락 장중 반등", "family": "평균회귀", "hold": 0,
     "hypothesis": "대형 유동주가 시가에 −5% 이상 갭하락하면 시초가 투매가 과도해 그날 장중에 되돌린다.",
     "rule": "전일 기준 거래대금 상위 200종목 중 시가 갭 −5% 이하 종목을 시가 매수, 당일 종가 매도"},
    # ── 2차 등록 (2026-10-16, 결과 보기 전에 가설·규칙·비교 기준을 먼저 적음) ──
    {"id": "CRASH_REBOUND_LARGE", "name": "급락장 대형주 반등", "family": "이벤트", "hold": 20, "reg": REG2, "bench": "KOSPI",
     "hypothesis": "시가총액가중 시장(코스피 프록시)이 이미 20일 고점 대비 −10% 이상 빠진 상태에서 하루에 −4% 이상 더 급락하면, "
                   "강제 청산·투매로 대형주가 펀더멘털보다 과하게 눌린 것이라 이후 한 달(20거래일) 대형주 묶음이 시가총액가중 지수보다 더 오른다.",
     "rule": "코스피 프록시 일간 ≤ −4% & 20일 고점 대비 ≤ −10% 인 날, 코스피 규모(120일 평균 거래대금) 상위 50종목 동일가중 매수, "
             "20거래일 보유, 보유기간 겹치는 이벤트는 건너뜀. 주 비교 기준 = 코스피 프록시"},
    {"id": "LOWVOL_LARGE", "name": "대형주 저변동성", "family": "저변동", "hold": 20, "reg": REG2, "bench": "KOSPI",
     "hypothesis": "대형주(코스피 규모 상위 200) 안에서도 변동성 낮은 종목이 저평가되어 있어(복권 선호·레버리지 제약), "
                   "저변동 5분위를 매달 사면 시가총액가중 지수보다 더 번다. 소형·관심주가 섞인 기존 LOWVOL 의 잡음을 대형주로 줄인 판.",
     "rule": "20거래일마다 코스피 규모 상위 200종목 중 60일 일간 변동성 하위 20% 동일가중 매수, 20거래일 보유. 주 비교 기준 = 코스피 프록시"},
    {"id": "DUAL_MOMENTUM_INDEX", "name": "지수 절대모멘텀", "family": "추세추종", "hold": 20, "reg": REG2, "bench": "KOSPI",
     "hypothesis": "코스피 프록시의 12개월 수익률이 0보다 클 때만 지수를 들고 아니면 현금으로 빠지면, 긴 하락장을 피해서 "
                   "같은 기간 지수 계속 보유(buy & hold)보다 20거래일당 수익이 높고 최대낙폭도 작다.",
     "rule": "20거래일마다 코스피 프록시 252일 수익률 > 0 이면 지수 보유, 아니면 현금(이자 0으로 계산 — 전략에 불리). "
             "보유↔현금 전환 시 편도 비용 0.125%. 비교 = 같은 기간 지수 계속 보유. 최대낙폭·연복리는 참고 지표(등급은 공통 관문)"},
    {"id": "TREND_SECTOR", "name": "업종 추세", "family": "추세추종", "hold": None, "wait": True, "reg": REG2,
     "hypothesis": "최근 6~12개월 강한 업종이 다음 달에도 강하다.",
     "rule": "universe/kr_sector.csv 는 현재 시점 업종 스냅샷뿐이라 상장폐지 종목·과거 업종 변경이 빠짐(생존 편향) → 시점별 업종 이력 확보 전까지 대기"},
    # ── 데이터 부족: 등록만, 테스트 안 함 ──
    {"id": "MACRO_TILT", "name": "글로벌 매크로 틸트", "family": "매크로", "hold": None, "wait": True,
     "hypothesis": "금리·달러·유가 국면에 따라 업종 비중을 기울이면 초과수익이 난다.",
     "rule": "국면 정의·업종 시계열이 2010~ 일관되게 확보되면 테스트"},
    {"id": "VRP_OPTIONS", "name": "변동성 프리미엄(VRP) 옵션", "family": "변동성", "hold": None, "wait": True,
     "hypothesis": "내재변동성이 실현변동성보다 체계적으로 높아 옵션 매도에 프리미엄이 있다.",
     "rule": "코스피200 옵션 일별 장기 히스토리 확보 전까지 대기"},
    {"id": "SHORT_SQUEEZE", "name": "숏스퀴즈", "family": "이벤트", "hold": None, "wait": True,
     "hypothesis": "공매도 잔고가 많은 종목이 반등하면 숏커버로 추가 상승한다.",
     "rule": "종목별 공매도 잔고 장기 히스토리(2010~) 확보 전까지 대기"},
    {"id": "FOREIGN_FLOW_FILTER", "name": "외국인 수급 필터", "family": "수급", "hold": None, "wait": True,
     "hypothesis": "외국인 순매수는 단독 신호가 아니라 다른 전략의 필터로만 의미가 있다.",
     "rule": "기존 백테스트(외국인 종목고유 수급 × K200 선물 레짐)에서 H1·H2 기각 → 단독 전략 금지, 등급 A/B 전략의 필터로만 재검증. 종목별 수급 장기 데이터 필요"},
    {"id": "PAIR_RV", "name": "롱숏 상대가치", "family": "상대가치", "hold": None, "wait": True,
     "hypothesis": "같은 업종 내 가격 괴리는 평균으로 돌아온다.",
     "rule": "국내 개인 공매도 실행이 현실적으로 어려움 → 페이퍼 트레이딩 기록만, 실전 등급 대상 아님"},
]
for _r in REGISTRY:
    _r["registered"] = _r.pop("reg", REG)
    _r.setdefault("bench", "EW")
    _r["status"] = "데이터 부족 — 대기" if _r.get("wait") else "검증"

# 진입 시점 변형. open = t일 종가 신호 → t+1 시가 진입, t+H 종가 청산 (1차 등록 규칙).
# close = t일 종가 신호 → t+1 종가 진입, t+1+H 종가 청산. 진입일(t+1) 입장에서 신호가 t−1(=전일)까지 데이터만 쓰므로
# 같은 날 종가 진입이어도 미래 참조 없음. 시가 갭(당일 정보)을 쓰는 GAPDOWN_INTRADAY 는 종가 변형 없음.
# 1차 등록 7개의 close 변형은 첫 결과를 본 뒤(2026-10-16) 추가한 사후 변형 → 관문 m 에 포함해 다중검정 비용을 치른다.
ENTRIES = {"open": "다음날 시가 진입", "close": "다음날 종가 진입"}
NO_CLOSE = {"GAPDOWN_INTRADAY"}
# 코스피 프록시: 과거 시가총액 이력이 없어 '규모 = 직전일까지 120일 평균 거래대금' 으로 대신한다.
# 코스피(.KS) 종목 중 규모 상위 200개, 같은 규모로 가중. 실제 코스피와 겹치는 2024-09~ 구간에서 일간 상관·추적오차를 run() 에서 검증해 lab.json 에 남긴다.
KOSPI_N = 200
# 프록시 장기 검증용: 공개된 코스피 연말 종가 (수기 입력). 실제 지수와 해마다 얼마나 어긋나는지(drift)를 lab.json 에 남긴다.
# 알려진 한계: data/hist 는 원주가 + ±45% 갭만 보정 → 유상증자 권리락·소규모 무상증자 등은 '하락'으로 남아 프록시·EW 모두 아래로 끌림.
KOSPI_YE = {2010: 2051.00, 2011: 1825.74, 2012: 1997.05, 2013: 2011.34, 2014: 1915.59, 2015: 1961.31, 2016: 2026.46,
            2017: 2467.49, 2018: 2041.04, 2019: 2197.67, 2020: 2873.47, 2021: 2977.65, 2022: 2236.40, 2023: 2655.28, 2024: 2399.49}
GRADE_ORDER = "ABCF"


# ───────────────────────── 데이터 ─────────────────────────
def load_kr() -> pl.DataFrame:
    """장기 히스토리(상폐 포함) + 올해 일일 데이터 병합, (yf,date) 중복은 kr_prices 우선.
    분할·병합 보정은 공통 로더 screener.prices (원본 열 rc = 조정 전 종가, tv = 원본 거래대금)."""
    from .prices import adjust, load_kr as _load
    raw = _load(raw=True, hist_from=0).filter((pl.col("close") > 0) & (pl.col("open") > 0))
    adj = adjust(raw)
    return adj.select(
        "yf", "date",
        *[pl.col(c).alias(c[0]) for c in ("open", "high", "low", "close")],
        pl.col("volume").alias("v"),
        raw["close"].alias("rc"),
        (raw["close"] * raw["volume"]).alias("tv"),
    )


def features(df: pl.DataFrame) -> pl.DataFrame:
    gmax = df["date"].max()
    pc = pl.col("c").shift(1)
    df = df.with_columns(
        (pl.col("c") / pc - 1).over("yf").alias("r1"),
        (pl.col("o") / pc - 1).over("yf").alias("gap"),
        ((pl.col("date") - pl.col("date").shift(1)).dt.total_days()).over("yf").alias("dgap"),
        pl.col("tv").rolling_mean(20).over("yf").alias("tv20"),
        pl.col("tv").rolling_mean(120, min_samples=20).shift(1).over("yf").alias("tv120_p"),
        pl.col("yf").str.ends_with(".KS").alias("ks"),
    )
    df = df.with_columns(
        ((pl.col("r1").abs() > BAD) | (pl.col("gap").abs() > BAD) | ((pl.col("c") / pl.col("o") - 1).abs() > BAD))
        .fill_null(False).cast(pl.Int32).alias("bad"),
        ((pl.col("rc") >= MIN_PX) & (pl.col("tv20") >= MIN_TV)).fill_null(False).alias("liq"),
    )
    o = pl.col
    df = df.with_columns(
        (o("c").shift(20) / o("c").shift(252) - 1).over("yf").alias("mom"),
        (o("c") / o("c").shift(5) - 1).over("yf").alias("r5"),
        o("r1").rolling_std(60).over("yf").alias("vol60"),
        o("h").rolling_max(252).over("yf").alias("hi252"),
        o("v").shift(1).rolling_mean(20).over("yf").alias("vavg20"),
        o("bad").rolling_sum(252, min_samples=1).over("yf").alias("bad252"),
        o("bad").rolling_sum(60, min_samples=1).over("yf").alias("bad60"),
        o("bad").rolling_sum(5, min_samples=1).over("yf").alias("bad5"),
        o("liq").shift(1).fill_null(False).over("yf").alias("liq_p"),
        o("tv20").shift(1).over("yf").alias("tv20_p"),
        o("date").last().over("yf").alias("_last"),
        o("c").last().over("yf").alias("_lastc"),
        o("date").cum_count().over("yf").alias("_age"),
    )
    # 미래 수익률 (진입 t+1 시가 → 청산 t+H 종가). 상장폐지로 창이 잘리면 마지막 종가로 청산(생존 편향 방지),
    # 아직 상장 중인데 데이터가 끝난 경우(최근)는 미완성 → 제외. 창 안에 데이터 오류일이 있으면 제외.
    for H in (5, 20):
        entry = o("o").shift(-1).over("yf")
        ex = o("c").shift(-H).over("yf")
        ex = pl.when(ex.is_null() & (o("_last") < gmax)).then(o("_lastc")).otherwise(ex)
        badf = o("bad").reverse().rolling_sum(H, min_samples=1).reverse().shift(-1).over("yf")
        df = df.with_columns(pl.when(badf.fill_null(0) == 0).then(ex / entry - 1).otherwise(None).alias(f"f{H}"))
        # 종가 진입 변형: t+1 종가 진입 → t+1+H 종가 청산 (신호일 t 에 기록)
        entry = o("c").shift(-1).over("yf")
        ex = o("c").shift(-(H + 1)).over("yf")
        ex = pl.when(ex.is_null() & entry.is_not_null() & (o("_last") < gmax)).then(o("_lastc")).otherwise(ex)
        badf = o("bad").reverse().rolling_sum(H, min_samples=1).reverse().shift(-2).over("yf")
        df = df.with_columns(pl.when(badf.fill_null(0) == 0).then(ex / entry - 1).otherwise(None).alias(f"fc{H}"))
    df = df.with_columns(pl.when(o("bad") == 0).then(o("c") / o("o") - 1).otherwise(None).alias("f0"))
    return df.drop("_lastc")


# ───────────────────────── 전략 ─────────────────────────
def _rank_pct(col: str) -> pl.Expr:
    return pl.col(col).rank("average").over("date") / pl.col(col).count().over("date")


def _fcol(H: int, entry: str) -> str:
    return f"f{H}" if entry == "open" else f"fc{H}"


def _bench(df: pl.DataFrame, H: int, entry: str = "open") -> pl.DataFrame:
    """기준 1: 유동성 유니버스 동일가중 (같은 진입·청산 시점)."""
    liq = "liq_p" if H == 0 else "liq"
    f = _fcol(H, entry)
    return (df.filter(pl.col(liq) & pl.col(f).is_not_null())
              .group_by("date").agg(pl.col(f).mean().alias("bench"), pl.len().alias("n_univ")))


def kospi_proxy(df: pl.DataFrame) -> pl.DataFrame:
    """기준 2: 코스피 프록시 (규모가중). 규모 = 직전일까지 120일 평균 거래대금, 코스피(.KS) 상위 KOSPI_N.
    kret = 종가→종가, kgap = 전일 종가→당일 시가 (같은 가중). 신호일 t 기준 미래 수익률 kb_* 도 붙인다."""
    w = pl.col("tv120_p")
    x = df.filter(pl.col("ks") & w.is_not_null() & (pl.col("bad") == 0) & (pl.col("dgap") <= 10)
                  & pl.col("r1").is_not_null() & pl.col("gap").is_not_null())
    x = x.filter(w.rank("ordinal", descending=True).over("date") <= KOSPI_N)
    k = (x.group_by("date").agg(((w * pl.col("r1")).sum() / w.sum()).alias("kret"),
                                ((w * pl.col("gap")).sum() / w.sum()).alias("kgap"), pl.len().alias("kn"))
           .sort("date").filter(pl.col("kn") >= 50))
    k = k.with_columns((1 + pl.col("kret")).cum_prod().alias("kidx"))
    I = pl.col("kidx")
    k = k.with_columns(
        (I / I.rolling_max(20, min_samples=1) - 1).alias("kdd20"),
        (I / I.shift(252) - 1).alias("k12m"),
        ((1 + pl.col("kret")) / (1 + pl.col("kgap")) - 1).alias("kb_o0"),     # 당일 시가→종가
    )
    for H in (5, 20):
        k = k.with_columns((I.shift(-H) / (I * (1 + pl.col("kgap").shift(-1))) - 1).alias(f"kb_o{H}"),
                           (I.shift(-(H + 1)) / I.shift(-1) - 1).alias(f"kb_c{H}"))
    return k


def _series(picks: pl.DataFrame, ew: pl.DataFrame, kp: pl.DataFrame, H: int, entry: str = "open") -> pl.DataFrame:
    """날짜별 픽 평균(비용 차감) − 기준 (EW 동일가중 유니버스 / 코스피 프록시)."""
    f = _fcol(H, entry)
    kc = f"kb_{'o' if entry == 'open' else 'c'}{H}"
    s = (picks.filter(pl.col(f).is_not_null())
              .group_by("date").agg((pl.col(f).mean() - COST).alias("raw"), pl.len().alias("k")))
    return (s.join(ew, on="date", how="inner").join(kp.select("date", pl.col(kc).alias("kbench")), on="date", how="left")
             .with_columns((pl.col("raw") - pl.col("bench")).alias("ex"), (pl.col("raw") - pl.col("kbench")).alias("kex"))
             .sort("date"))


def market_index(df: pl.DataFrame) -> pl.DataFrame:
    """유동성 유니버스(전일 기준) 동일가중 지수 — 급락 이벤트 판정용."""
    m = (df.filter(pl.col("liq_p") & (pl.col("bad") == 0) & pl.col("r1").is_not_null() & (pl.col("dgap") <= 10))
           .group_by("date").agg(pl.col("r1").mean().alias("mret"), pl.len().alias("n")).sort("date")
           .filter(pl.col("n") >= 50))
    m = m.with_columns((1 + pl.col("mret")).cum_prod().alias("idx"))
    return m.with_columns((pl.col("idx") / pl.col("idx").rolling_max(20, min_samples=1) - 1).alias("dd20"))


def candidates(df: pl.DataFrame, sid: str) -> pl.DataFrame:
    """t일 종가 기준 신호 대상 (모든 날짜). 리밸런싱/이벤트 샘플링은 run 에서."""
    L = df.filter(pl.col("liq"))
    if sid == "TREND_12_1":
        x = L.filter(pl.col("mom").is_not_null() & (pl.col("bad252") == 0) & (pl.col("_age") >= 253))
        return x.filter(_rank_pct("mom") > 0.9)
    if sid == "REV_5D":
        x = L.filter(pl.col("r5").is_not_null() & (pl.col("bad5") == 0) & (pl.col("_age") >= 6))
        return x.filter(_rank_pct("r5") <= 0.1)
    if sid == "LOWVOL":
        x = L.filter(pl.col("vol60").is_not_null() & (pl.col("bad60") == 0) & (pl.col("_age") >= 61))
        return x.filter(_rank_pct("vol60") <= 0.1)
    if sid == "HI52_BREAK":
        return L.filter((pl.col("_age") >= 253) & (pl.col("bad252") == 0) & (pl.col("c") >= 0.98 * pl.col("hi252"))
                        & (pl.col("v") >= 2 * pl.col("vavg20")) & (pl.col("vavg20") > 0))
    if sid == "CRASH_REBOUND_LARGE":
        x = L.filter(pl.col("ks") & pl.col("tv120_p").is_not_null())
        return x.filter(pl.col("tv120_p").rank("ordinal", descending=True).over("date") <= 50)
    if sid == "LOWVOL_LARGE":
        x = L.filter(pl.col("ks") & pl.col("tv120_p").is_not_null())
        x = x.filter(pl.col("tv120_p").rank("ordinal", descending=True).over("date") <= KOSPI_N)
        x = x.filter(pl.col("vol60").is_not_null() & (pl.col("bad60") == 0) & (pl.col("_age") >= 61))
        return x.filter(_rank_pct("vol60") <= 0.2)
    if sid.startswith("CRASH_REBOUND"):
        return L.filter(pl.col("tv20").rank("ordinal", descending=True).over("date") <= TOP_TV)
    if sid == "GAPDOWN_INTRADAY":
        P = df.filter(pl.col("liq_p") & pl.col("tv20_p").is_not_null())
        P = P.filter(pl.col("tv20_p").rank("ordinal", descending=True).over("date") <= TOP_TV)
        return P.filter((pl.col("gap") <= -0.05) & (pl.col("dgap") <= 10) & (pl.col("bad") == 0))
    raise KeyError(sid)


# ───────────────────────── 통계·관문 ─────────────────────────
def stats(s: pl.DataFrame) -> dict:
    n = len(s)
    if n == 0:
        return {"n": 0}
    ex = s["ex"].to_list()
    mu = sum(ex) / n
    sd = (sum((x - mu) ** 2 for x in ex) / (n - 1)) ** 0.5 if n > 1 else 0.0
    t = mu / (sd / n ** 0.5) if sd > 0 else 0.0
    w = [x for x in ex if x > 0]
    l_ = [x for x in ex if x <= 0]
    hit = len(w) / n
    aw = sum(w) / len(w) if w else 0.0
    al = sum(l_) / len(l_) if l_ else 0.0
    d0, d1 = s["date"].min(), s["date"].max()
    yrs = max((d1 - d0).days / 365.25, 0.5)
    eq = peak = 1.0
    mdd = 0.0
    for x in ex:
        eq *= 1 + x
        peak = max(peak, eq)
        mdd = min(mdd, eq / peak - 1)
    r = lambda x, k=4: None if x is None else round(x, k)  # noqa: E731
    return {"n": n, "from": str(d0), "to": str(d1), "mean_ex": r(mu), "t": r(t, 2), "hit": r(hit, 3),
            "avg_win": r(aw), "avg_loss": r(al), "payoff": r(aw / abs(al), 2) if al else None,
            "ev": r(hit * aw + (1 - hit) * al), "sharpe": r(mu / sd * (n / yrs) ** 0.5, 2) if sd > 0 else None,
            "mdd": r(mdd), "mean_raw": r(s["raw"].mean()), "mean_bench": r(s["bench"].mean()),
            "avg_picks": round(s["k"].mean(), 1)}


def gate(sp: dict, req: float) -> tuple[str, list[str]]:
    IS, OOS, HO = sp["IS"], sp["OOS"], sp["HOLDOUT"]
    g = lambda d, k: d.get(k) if d.get(k) is not None else 0.0  # noqa: E731
    reasons = []
    is_pass = g(IS, "t") >= req and IS.get("n", 0) >= 30
    if g(IS, "t") < req:
        reasons.append(f"IS t {g(IS, 't'):.2f} < Bonferroni 기준 {req:.2f}")
    if IS.get("n", 0) < 30:
        reasons.append(f"IS 표본 {IS.get('n', 0)} < 30")
    oos_pass = g(OOS, "mean_ex") > 0 and g(OOS, "t") >= 1
    if not oos_pass:
        reasons.append(f"OOS 미통과 (평균 {g(OOS, 'mean_ex') * 100:+.2f}%, t {g(OOS, 't'):.2f}; 평균>0·t≥1 필요)")
    ho_pass = g(HO, "mean_ex") > 0 and HO.get("n", 0) >= 10
    if not ho_pass:
        reasons.append(f"HOLDOUT 미통과 (평균 {g(HO, 'mean_ex') * 100:+.2f}%, 표본 {HO.get('n', 0)}; 평균>0·표본≥10 필요)")
    if is_pass and oos_pass and ho_pass:
        return "A", ["IS(Bonferroni)·OOS·HOLDOUT 모두 통과"]
    if is_pass and oos_pass:
        return "B", reasons
    if g(IS, "mean_ex") > 0 and g(IS, "t") >= 2:
        return "C", reasons
    if g(IS, "mean_ex") <= 0:
        reasons.insert(0, "IS 평균 초과수익 ≤ 0")
    return "F", reasons


def _names() -> dict:
    try:
        u = pl.read_csv(UNIVERSE_DIR / "kr.csv", schema_overrides={"symbol": pl.Utf8})
        return dict(zip(u["yf"].to_list(), u["name"].to_list()))
    except Exception:  # noqa: BLE001
        return {}


def _proxy_check(kp: pl.DataFrame) -> dict | None:
    """코스피 프록시 vs 실제 코스피 (reports/macro_series.json, 2024-09~) 일간 수익률 비교."""
    try:
        ms = json.loads((REPORT_DIR / "macro_series.json").read_text(encoding="utf-8"))["series"]["KOSPI"]
        k = (pl.DataFrame({"date": [x[0] for x in ms], "kc": [float(x[4]) for x in ms]})
               .with_columns(pl.col("date").str.to_date()).sort("date")
               .with_columns((pl.col("kc") / pl.col("kc").shift(1) - 1).alias("act")))
        j = kp.select("date", "kret").join(k, on="date").drop_nulls()
        ye = kp.group_by(pl.col("date").dt.year().alias("y")).agg(pl.col("kidx").last()).sort("y")
        lv = dict(zip(ye["y"].to_list(), ye["kidx"].to_list()))
        yearly = [{"y": y, "proxy": round(lv[y] / lv[y - 1] - 1, 4), "kospi": round(KOSPI_YE[y] / KOSPI_YE[y - 1] - 1, 4)}
                  for y in sorted(KOSPI_YE) if y - 1 in KOSPI_YE and y in lv and y - 1 in lv]
        drift = sum(x["proxy"] - x["kospi"] for x in yearly) / len(yearly) if yearly else None
        if len(j) < 60:
            return {"yearly": yearly, "drift_ann": round(drift, 4) if drift is not None else None}
        return {"yearly": yearly, "drift_ann": round(drift, 4) if drift is not None else None,
                "from": str(j["date"].min()), "to": str(j["date"].max()), "n": len(j),
                "corr": round(j.select(pl.corr("kret", "act")).item(), 3),
                "te_ann": round(float((j["kret"] - j["act"]).std()) * 252 ** 0.5, 3),
                "cum_proxy": round(float((1 + j["kret"]).product()) - 1, 3),
                "cum_kospi": round(float((1 + j["act"]).product()) - 1, 3)}
    except Exception as e:  # noqa: BLE001
        log.warning("lab: 코스피 프록시 검증 실패 %s", e)
        return None


def _nonoverlap(s: pl.DataFrame, evs: pl.DataFrame | None, H: int) -> pl.DataFrame:
    if evs is not None:   # 이벤트형: 신호일을 순서대로 보며 보유기간이 겹치지 않는 것만 채택
        ev, last = [], -10 ** 9
        for d, ci in evs.select("date", "ci").sort("date").iter_rows():
            if ci - last >= max(H, 1):
                ev.append(d)
                last = ci
        return s.filter(pl.col("date").is_in(ev))
    if H == 0:
        return s           # 매일 독립 (당일 시가→종가)
    ci0 = s["ci"].min()
    return s.filter(((pl.col("ci") - ci0) % H) == 0)


def _splits(s: pl.DataFrame, ew: bool) -> dict:
    out = {}
    for k, (a, b) in SPLITS.items():
        x = s.filter((pl.col("date") >= a) & (pl.col("date") <= b))
        kx = x.filter(pl.col("kex").is_not_null()).with_columns(pl.col("kex").alias("ex"), pl.col("kbench").alias("bench"))
        out[k] = {"kospi": stats(kx)}
        if ew:
            out[k]["ew"] = stats(x)
    return out


def _grade(sp: dict, req: float, ew: bool) -> tuple[str, list[str], dict]:
    """두 기준 모두 통과해야 하는 결합 판정(더 낮은 등급). 결합(AND)이라 다중검정 보정은 더 필요 없다."""
    gs = {"kospi": gate({k: v["kospi"] for k, v in sp.items()}, req)}
    if ew:
        gs["ew"] = gate({k: v["ew"] for k, v in sp.items()}, req)
    worst = max(g for g, _ in gs.values())   # 'A'<'B'<'C'<'F'
    lab = {"ew": "EW", "kospi": "KOSPI"}
    reasons = [] if worst == "A" else [f"[{lab[b]}] {x}" for b, (g, rs) in gs.items() if g != "A" for x in rs]
    return worst, reasons or ["IS(Bonferroni)·OOS·HOLDOUT 모두 통과 (두 기준)"], {b: g for b, (g, _) in gs.items()}


def _path(raw: list[float], dates: list, H: int) -> dict:
    eq = peak = 1.0
    mdd = 0.0
    for x in raw:
        eq *= 1 + x
        peak = max(peak, eq)
        mdd = min(mdd, eq / peak - 1)
    yrs = max(len(raw) * H / 252, 0.5)
    return {"cagr": round(eq ** (1 / yrs) - 1, 4), "mdd": round(mdd, 4), "total": round(eq - 1, 4)}


def dual_series(kp: pl.DataFrame, cal: pl.DataFrame, entry: str) -> tuple[pl.DataFrame, dict]:
    kc = "kb_o20" if entry == "open" else "kb_c20"
    x = kp.join(cal, on="date").filter(pl.col("k12m").is_not_null() & pl.col(kc).is_not_null()).sort("date")
    ci0 = x["ci"].min()
    x = x.filter(((pl.col("ci") - ci0) % 20) == 0)
    rows, prev = [], False
    for d, ci, m12, kb in x.select("date", "ci", "k12m", kc).iter_rows():
        on = m12 > 0
        cost = COST / 2 if on != prev else 0.0
        raw = (kb if on else 0.0) - cost
        rows.append({"date": d, "ci": ci, "raw": raw, "bench": kb, "kbench": kb, "ex": raw - kb, "kex": raw - kb, "k": 1.0 if on else 0.0})
        prev = on
    s = pl.DataFrame(rows)
    extra = {}
    for k, (a, b) in {"ALL": (date(1900, 1, 1), date(2100, 1, 1)), **SPLITS}.items():
        y = s.filter((pl.col("date") >= a) & (pl.col("date") <= b))
        if len(y):
            extra[k] = {"strat": _path(y["raw"].to_list(), y["date"].to_list(), 20),
                        "bh": _path(y["bench"].to_list(), y["date"].to_list(), 20),
                        "on": round(float(y["k"].mean()), 3)}
    return s, extra


def run() -> dict:
    t0 = time.time()
    df = features(load_kr())
    log.info("lab: 데이터 %d행 %.0fs", len(df), time.time() - t0)
    cal = (df.group_by("date").agg(pl.len().alias("n")).filter(pl.col("n") >= 100).sort("date")
             .with_row_index("ci").select("date", "ci"))
    asof = df["date"].max()
    mkt = market_index(df)
    kp = kospi_proxy(df)
    crash = mkt.filter((pl.col("mret") <= -0.04) & (pl.col("dd20") <= -0.10)).join(cal, on="date")
    crash_k = kp.filter((pl.col("kret") <= -0.04) & (pl.col("kdd20") <= -0.10)).join(cal, on="date")
    ews = {(H, e): _bench(df, H, e) for H in (0, 5, 20) for e in ENTRIES if not (H == 0 and e == "close")}
    names = _names()
    tested = [r for r in REGISTRY if not r.get("wait")]
    plan = [(r, e) for r in tested for e in ENTRIES if not (e == "close" and r["id"] in NO_CLOSE)]
    m = len(plan)
    req = NormalDist().inv_cdf(1 - 0.05 / m / 2)
    results: dict = {}
    for r, e in plan:
        sid, H = r["id"], r["hold"]
        res = results.setdefault(sid, {"variants": {}})
        if sid == "DUAL_MOMENTUM_INDEX":
            s, extra = dual_series(kp, cal, e)
            ew, cand = False, None
        else:
            cand = candidates(df, sid)
            s = _series(cand, ews[(H, e)], kp, H, e).join(cal, on="date", how="inner")
            evs = (crash if sid in ("CRASH_REBOUND", "CRASH_REBOUND_20") else crash_k if sid == "CRASH_REBOUND_LARGE"
                   else s if sid == "HI52_BREAK" else None)
            s = _nonoverlap(s, evs, H)
            ew, extra = True, None
        sp = _splits(s, ew)
        grade, reasons, by = _grade(sp, req, ew)
        v = {"entry": e, "label": ENTRIES[e], "splits": sp, "grade": grade, "grade_by": by, "reasons": reasons,
             "posthoc": e == "close" and r["registered"] == REG}
        if extra:
            v["path"] = extra
        res["variants"][e] = v
        if sid.startswith("CRASH_REBOUND"):
            ce = crash_k if sid == "CRASH_REBOUND_LARGE" else crash
            res["events"] = [str(d) for d in ce["date"].to_list()][-8:]
            res["n_events"] = len(ce)
        log.info("lab %s/%s: %s IS %s", sid, e, grade, sp["IS"]["kospi"])
        best = min(x["grade"] for x in res["variants"].values())
        res["grade"] = best
        if best in ("A", "B") and cand is not None and "last_signals" not in res:
            if sid.startswith("CRASH_REBOUND"):
                ce = crash_k if sid == "CRASH_REBOUND_LARGE" else crash
                last_ev = ce["date"].max() if len(ce) else None
                ld = last_ev if last_ev is not None and (asof - last_ev).days <= 7 else None
            else:
                ld = cand["date"].max()
            if ld is not None:
                p = cand.filter(pl.col("date") == ld).sort("tv20", descending=True).head(30)
                res["last_signals"] = {"date": str(ld), "picks": [
                    {"s": y.split(".")[0], "n": names.get(y, y.split(".")[0])} for y in p["yf"].to_list()]}
        if best in ("A", "B") and sid == "DUAL_MOMENTUM_INDEX":
            lk = kp.filter(pl.col("k12m").is_not_null()).tail(1)
            res["state"] = {"date": str(lk["date"][0]), "k12m": round(lk["k12m"][0], 4), "hold": bool(lk["k12m"][0] > 0)}
    # 기준·진입 시점 진단 (주의사항 1·2 를 숫자로)
    liq = df.filter(pl.col("liq_p") & (pl.col("bad") == 0) & (pl.col("dgap") <= 10) & pl.col("gap").is_not_null())
    ew_on = liq.group_by("date").agg(pl.col("gap").mean().alias("on"), (pl.col("c") / pl.col("o") - 1).mean().alias("id"))
    kp_d = kp.with_columns(((1 + pl.col("kret")) / (1 + pl.col("kgap")) - 1).alias("id"))
    bench_info = {
        "ew_level": round(float(mkt["idx"][-1]), 3), "ew_from": str(mkt["date"][0]),
        "kospi_level": round(float(kp["kidx"][-1]), 3), "kospi_from": str(kp["date"][0]),
        "kospi_check": _proxy_check(kp),
        "kospi_method": f"코스피(.KS) 중 직전일까지 120일 평균 거래대금 상위 {KOSPI_N}종목, 같은 값으로 가중 (과거 시가총액 이력이 없어 거래대금으로 규모를 대신함)",
        "overnight_bp": {"ew": round(float(ew_on["on"].mean()) * 1e4, 1), "kospi": round(float(kp_d["kgap"].mean()) * 1e4, 1)},
        "intraday_bp": {"ew": round(float(ew_on["id"].mean()) * 1e4, 1), "kospi": round(float(kp_d["id"].mean()) * 1e4, 1)},
        "crash_events": {"ew": len(crash), "kospi": len(crash_k)},
    }
    out = {
        "asof": str(asof),
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "method": (f"비용 왕복 {COST * 100:.2f}% 차감 · 기준 2개: ① EW = 같은 기간 유동성 유니버스(종가 ≥ 1,000원, 20일 평균 거래대금 ≥ 50억) 동일가중, "
                   f"② KOSPI = 코스피 프록시(코스피 종목 규모 상위 {KOSPI_N}, 120일 평균 거래대금 가중) · "
                   f"진입 2가지: 시가 = t일 종가 신호 → t+1 시가 진입·t+H 종가 청산 / 종가 = t+1 종가 진입·t+1+H 종가 청산(진입일 기준 전일까지 데이터만 사용) · "
                   f"겹치지 않는 리밸런싱/이벤트만 평가 · 상폐 포함 데이터, 일간 ±32% 초과 변동은 오류로 제외 · "
                   f"IS 2010~2019 / OOS 2020~2023 / HOLDOUT 2024~ (잠금) · 관문: 검증한 (가설×진입) 조합 m={m}개 Bonferroni 양측 5% → IS t ≥ {req:.2f} & 표본 ≥ 30, "
                   f"OOS 평균>0 & t ≥ 1, HOLDOUT 평균>0 & 표본 ≥ 10 → A / HOLDOUT만 실패 B / IS t≥2지만 보정·OOS 실패 C / 나머지 F · "
                   f"등급은 두 기준 각각 판정 후 낮은 쪽 (지수 전략은 KOSPI 기준만)"),
        "gate": {"m": m, "req_t": round(req, 3), "alpha": 0.05, "tests": [f"{r['id']}/{e}" for r, e in plan]},
        "entries": ENTRIES,
        "bench_info": bench_info,
        "registry": [{k: v for k, v in r.items() if k != "wait"} for r in REGISTRY],
        "results": results,
        "runtime_s": round(time.time() - t0, 1),
    }
    (REPORT_DIR / "lab.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def summary(out: dict) -> str:
    lines = [f"전략 연구소 {out['asof']} · 관문 t≥{out['gate']['req_t']} (m={out['gate']['m']}) · {out['runtime_s']}s"]

    def f(d: dict) -> str:
        return f"{d.get('mean_ex', 0) * 100:+.2f}% t{d.get('t', 0):.1f} n{d.get('n', 0)}" if d and d.get("n") else "—"
    for sid, r in out["results"].items():
        for e, v in r["variants"].items():
            sp = v["splits"]
            seg = " | ".join(f"{k} EW {f(sp[k].get('ew'))} K {f(sp[k]['kospi'])}" for k in SPLITS)
            lines.append(f"  {v['grade']} {sid:<20} {e:<5} {seg}")
    return "\n".join(lines)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(summary(run()))
