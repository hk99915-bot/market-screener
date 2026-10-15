"""전략 연구소 (전략 공장): 사전 등록 가설 → 공통 백테스트 하네스 → 코드로 고정된 통계 관문 → 등급.

원칙
- 가설은 테스트 전에 REGISTRY 에 적는다 (등록일 고정). 결과를 보고 규칙을 고치면 새 id 로 다시 등록한다.
- 신호는 t일 종가까지의 데이터만 사용 → t+1 시가 진입, t+hold 종가 청산 (GAPDOWN 은 당일 시가 갭이 보이는 순간 진입).
- 비용 왕복 0.25% 차감, 기준 = 같은 기간 유동성 유니버스 동일가중. 주 지표 = 리밸런싱당 초과수익.
- 겹치는 보유기간은 t-통계를 부풀리므로 겹치지 않는 날짜만 평가한다.
- 등급 관문은 고정 코드 (Bonferroni 보정 IS → OOS → 잠긴 HOLDOUT).

실행: python -m screener.main --mode lab  → reports/lab.json
"""
from __future__ import annotations

import glob
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
    _r["registered"] = REG
    _r["status"] = "데이터 부족 — 대기" if _r.get("wait") else "검증"


# ───────────────────────── 데이터 ─────────────────────────
def load_kr() -> pl.DataFrame:
    """장기 히스토리(상폐 포함) + 올해 일일 데이터 병합, (yf,date) 중복은 kr_prices 우선.
    분할·병합 보정은 backfill.load_hist → data_krx.adjust_splits 와 같은 규칙(전일 종가→시가 ±45%)을
    벡터화해서 적용한다 (원본은 이벤트마다 전체 프레임을 다시 써서 수천 건이면 수십 분 걸림)."""
    files = sorted(glob.glob(str(DATA_DIR / "hist" / "kr_[0-9][0-9][0-9][0-9].parquet")))
    parts = [pl.scan_parquet(f).select("yf", "date", "open", "high", "low", "close", "volume") for f in files]
    cur = DATA_DIR / "kr_prices.parquet"
    if cur.exists():
        parts.append(pl.scan_parquet(cur).select("yf", "date", "open", "high", "low", "close", "volume"))
    df = (pl.concat(parts, how="vertical_relaxed")
            .with_columns(pl.col("date").cast(pl.Date), *[pl.col(c).cast(pl.Float64) for c in ("open", "high", "low", "close", "volume")])
            .filter((pl.col("close") > 0) & (pl.col("open") > 0))
            .unique(["yf", "date"], keep="last", maintain_order=True).sort("yf", "date").collect())
    df = df.with_columns((pl.col("open") / pl.col("close").shift(1).over("yf")).alias("_r"))
    df = df.with_columns(pl.when((pl.col("_r") > 1.45) | (pl.col("_r") < 0.55)).then(pl.col("_r"))
                         .otherwise(1.0).fill_null(1.0).alias("_f"))
    df = df.with_columns((pl.col("_f").reverse().cum_prod().reverse().over("yf") / pl.col("_f")).alias("_a"))
    return df.select(
        "yf", "date",
        *[(pl.col(c) * pl.col("_a")).alias(c[0]) for c in ("open", "high", "low", "close")],
        (pl.col("volume") / pl.col("_a")).alias("v"),
        pl.col("close").alias("rc"),
        (pl.col("close") * pl.col("volume")).alias("tv"),
    )


def features(df: pl.DataFrame) -> pl.DataFrame:
    gmax = df["date"].max()
    pc = pl.col("c").shift(1)
    df = df.with_columns(
        (pl.col("c") / pc - 1).over("yf").alias("r1"),
        (pl.col("o") / pc - 1).over("yf").alias("gap"),
        ((pl.col("date") - pl.col("date").shift(1)).dt.total_days()).over("yf").alias("dgap"),
        pl.col("tv").rolling_mean(20).over("yf").alias("tv20"),
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
    df = df.with_columns(pl.when(o("bad") == 0).then(o("c") / o("o") - 1).otherwise(None).alias("f0"))
    return df.drop("_lastc")


# ───────────────────────── 전략 ─────────────────────────
def _rank_pct(col: str) -> pl.Expr:
    return pl.col(col).rank("average").over("date") / pl.col(col).count().over("date")


def _bench(df: pl.DataFrame, H: int) -> pl.DataFrame:
    liq = "liq_p" if H == 0 else "liq"
    return (df.filter(pl.col(liq) & pl.col(f"f{H}").is_not_null())
              .group_by("date").agg(pl.col(f"f{H}").mean().alias("bench"), pl.len().alias("n_univ")))


def _series(picks: pl.DataFrame, bench: pl.DataFrame, H: int) -> pl.DataFrame:
    """날짜별 픽 평균(비용 차감) − 기준."""
    s = (picks.filter(pl.col(f"f{H}").is_not_null())
              .group_by("date").agg((pl.col(f"f{H}").mean() - COST).alias("raw"), pl.len().alias("k")))
    return s.join(bench, on="date", how="inner").with_columns((pl.col("raw") - pl.col("bench")).alias("ex")).sort("date")


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


def run() -> dict:
    t0 = time.time()
    df = features(load_kr())
    log.info("lab: 데이터 %d행 %.0fs", len(df), time.time() - t0)
    cal = (df.group_by("date").agg(pl.len().alias("n")).filter(pl.col("n") >= 100).sort("date")
             .with_row_index("ci").select("date", "ci"))
    asof = df["date"].max()
    mkt = market_index(df)
    crash = mkt.filter((pl.col("mret") <= -0.04) & (pl.col("dd20") <= -0.10)).join(cal, on="date")
    benches = {H: _bench(df, H) for H in (0, 5, 20)}
    names = _names()
    tested = [r for r in REGISTRY if not r.get("wait")]
    m = len(tested)
    req = NormalDist().inv_cdf(1 - 0.05 / m / 2)
    results = {}
    for r in tested:
        sid, H = r["id"], r["hold"]
        cand = candidates(df, sid)
        s = _series(cand, benches[H], H).join(cal, on="date", how="inner")
        if sid.startswith("CRASH_REBOUND") or sid == "HI52_BREAK":
            # 이벤트형: 신호가 난 날을 순서대로 보며 보유기간이 겹치지 않는 것만 채택
            evs = crash.select("date", "ci") if sid.startswith("CRASH") else s.select("date", "ci")
            ev, last = [], -10 ** 9
            for d, ci in evs.iter_rows():
                if ci - last >= H:
                    ev.append(d)
                    last = ci
            s = s.filter(pl.col("date").is_in(ev))
        elif H == 0:
            pass   # 매일 독립 (당일 시가→종가) — 겹침 없음
        else:
            step = max(H, 1)
            ci0 = s["ci"].min()
            s = s.filter(((pl.col("ci") - ci0) % step) == 0)
        sp = {k: stats(s.filter((pl.col("date") >= a) & (pl.col("date") <= b))) for k, (a, b) in SPLITS.items()}
        grade, reasons = gate(sp, req)
        res = {"splits": sp, "grade": grade, "reasons": reasons}
        if sid.startswith("CRASH_REBOUND"):
            res["events"] = [str(d) for d in crash["date"].to_list()][-8:]
        if grade in ("A", "B"):
            if sid.startswith("CRASH_REBOUND"):
                last_ev = crash["date"].max() if len(crash) else None
                ld = last_ev if last_ev is not None and (asof - last_ev).days <= 7 else None
            else:
                ld = cand["date"].max()
            if ld is not None:
                p = cand.filter(pl.col("date") == ld).sort("tv20", descending=True).head(30)
                res["last_signals"] = {"date": str(ld), "picks": [
                    {"s": y.split(".")[0], "n": names.get(y, y.split(".")[0])} for y in p["yf"].to_list()]}
        results[sid] = res
        log.info("lab %s: %s IS %s", sid, grade, sp["IS"])
    out = {
        "asof": str(asof),
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "method": (f"비용 왕복 {COST * 100:.2f}% 차감 · 기준 = 같은 기간 유동성 유니버스(종가 ≥ 1,000원, 20일 평균 거래대금 ≥ 50억) 동일가중 · "
                   f"t일 종가 신호 → t+1 시가 진입 · 겹치지 않는 리밸런싱/이벤트만 평가 · 상폐 포함 데이터, 일간 ±32% 초과 변동은 오류로 제외 · "
                   f"IS 2010~2019 / OOS 2020~2023 / HOLDOUT 2024~ (잠금) · 관문: 검증 가설 m={m}개 Bonferroni 양측 5% → IS t ≥ {req:.2f} & 표본 ≥ 30, "
                   f"OOS 평균>0 & t ≥ 1, HOLDOUT 평균>0 & 표본 ≥ 10 → A / HOLDOUT만 실패 B / IS t≥2지만 보정·OOS 실패 C / 나머지 F"),
        "gate": {"m": m, "req_t": round(req, 3), "alpha": 0.05},
        "registry": [{k: v for k, v in r.items() if k != "wait"} for r in REGISTRY],
        "results": results,
        "runtime_s": round(time.time() - t0, 1),
    }
    (REPORT_DIR / "lab.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def summary(out: dict) -> str:
    lines = [f"전략 연구소 {out['asof']} · 관문 t≥{out['gate']['req_t']} (m={out['gate']['m']}) · {out['runtime_s']}s"]
    for sid, r in out["results"].items():
        f = lambda k: (lambda d: f"{d.get('mean_ex', 0) * 100:+.2f}% t{d.get('t', 0):.1f} n{d.get('n', 0)}" if d.get("n") else "—")(r["splits"][k])  # noqa: E731
        lines.append(f"  {r['grade']} {sid:<18} IS {f('IS')} | OOS {f('OOS')} | HO {f('HOLDOUT')}")
    return "\n".join(lines)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(summary(run()))
