"""모멘텀: 현재 순위(KR·US) + 국장 장기 백테스트.

현재 순위 (reports/momentum_{KR,US}.json)
- 12-1개월 수익률(최근 1개월 제외, 단기 반전 효과 회피), 6-1개월, 3개월 수익률의 백분위 평균 = 모멘텀 점수 0~100
- 변동성(60일)도 같이 싣는다 — 같은 점수면 변동성 낮은 쪽이 질 좋은 모멘텀

백테스트 (reports/momentum_bt.json, 국장 2010~, 상장폐지 종목 포함)
- 매월 말 유동성 필터(종가 1,000원↑, 20일 평균 거래대금 10억↑) 통과 종목을 12-1개월 수익률로 줄 세워 상위 10% 동일가중
- 다음 달 말까지 보유, 교체분에 편도 0.3% 비용
- 비교: 같은 유니버스 동일가중, 그리고 '시장 필터'(유니버스 지수가 10개월 평균 아래면 현금) 버전
- 가격은 KRX 원시 일봉이라 시가/전일종가 ±45% 이상 갭을 액면분할 등으로 보고 과거를 보정
"""
from __future__ import annotations

import glob
import json
import logging
import math
from datetime import datetime
from zoneinfo import ZoneInfo

import polars as pl

from .config import DATA_DIR, REPORT_DIR

log = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")
COST = 0.003


# ───────────── 현재 순위 ─────────────

def ranks(full: pl.DataFrame, last: pl.DataFrame, market: str, top: int = 60) -> list[dict]:
    p = (full.select("yf", "date", "close").sort("yf", "date")
             .with_columns(
                 (pl.col("close").shift(21).over("yf") / pl.col("close").shift(252).over("yf") - 1).alias("m12_1"),
                 (pl.col("close").shift(21).over("yf") / pl.col("close").shift(126).over("yf") - 1).alias("m6_1"),
                 (pl.col("close") / pl.col("close").shift(63).over("yf") - 1).alias("m3"),
                 (pl.col("close") / pl.col("close").shift(1).over("yf") - 1).rolling_std(60).over("yf").alias("vol60"),
             ).group_by("yf").last())
    p = p.join(last.select("yf", "symbol", "name", "market", "close", "trend_score", "class"), on="yf", how="inner")
    p = p.filter(pl.col("m6_1").is_not_null())
    if p.is_empty():
        return []
    pr = lambda c: (pl.col(c).rank("average") / pl.col(c).count() * 100)  # noqa: E731
    p = p.with_columns(
        pr("m12_1").alias("_a"), pr("m6_1").alias("_b"), pr("m3").alias("_c"))
    p = p.with_columns(pl.mean_horizontal(pl.col("_a").fill_null(pl.col("_b")), "_b", "_c").alias("mom_score"))
    p = p.sort("mom_score", descending=True)
    rd = lambda v, k=4: None if v is None else round(float(v), k)  # noqa: E731
    out = [{"symbol": r["symbol"], "name": r["name"], "market": r["market"], "close": r["close"],
            "m12_1": rd(r["m12_1"]), "m6_1": rd(r["m6_1"]), "m3": rd(r["m3"]),
            "vol": rd(r["vol60"] * math.sqrt(252) if r["vol60"] is not None else None),
            "score": rd(r["mom_score"], 1), "trend": rd(r["trend_score"], 0), "class": r["class"]}
           for r in p.to_dicts()]
    data = {"asof": str(last["date"].max()), "market": market, "n": len(out), "top": out[:top],
            "bottom": out[-20:][::-1]}
    REPORT_DIR.mkdir(exist_ok=True)
    (REPORT_DIR / f"momentum_{market}.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    log.info("모멘텀 순위 %s %d종목", market, len(out))
    return out


# ───────────── 백테스트 ─────────────

def _load_kr() -> pl.DataFrame:
    files = sorted(glob.glob(str(DATA_DIR / "hist" / "kr_*.parquet")))
    parts = [pl.scan_parquet(f) for f in files if "partial" not in f]
    cur = DATA_DIR / "kr_prices.parquet"
    if cur.exists():
        parts.append(pl.scan_parquet(cur))
    if not parts:
        return pl.DataFrame()
    df = (pl.concat(parts, how="vertical_relaxed").select("yf", "date", "open", "close", "volume")
            .unique(["yf", "date"], keep="last").sort("yf", "date").collect())
    # 분할·병합 보정 (벡터화): 이벤트일 비율 r 을 그 이전 모든 날짜에 곱한다
    df = df.with_columns((pl.col("open") / pl.col("close").shift(1).over("yf")).alias("_r"))
    df = df.with_columns(
        pl.when((pl.col("_r") > 1.45) | (pl.col("_r") < 0.55)).then(pl.col("_r")).otherwise(1.0).fill_null(1.0).alias("_f"))
    df = df.with_columns((pl.col("_f").reverse().cum_prod().reverse().over("yf") / pl.col("_f")).alias("_adj"))
    return df.with_columns((pl.col("close") * pl.col("_adj")).alias("adj"),
                           (pl.col("close") * pl.col("volume")).alias("tv")).drop("_r", "_f", "_adj")


def _stats(r: list[float]) -> dict:
    if not r:
        return {}
    eq, peak, mdd = 1.0, 1.0, 0.0
    for x in r:
        eq *= 1 + x
        peak = max(peak, eq)
        mdd = min(mdd, eq / peak - 1)
    n = len(r)
    mu = sum(r) / n
    sd = (sum((x - mu) ** 2 for x in r) / max(n - 1, 1)) ** 0.5
    return {"cagr": round(eq ** (12 / n) - 1, 4), "vol": round(sd * 12 ** 0.5, 4),
            "sharpe": round(mu / sd * 12 ** 0.5, 2) if sd else None, "mdd": round(mdd, 4),
            "total": round(eq - 1, 4), "months": n}


def backtest_kr(min_px: float = 1000, min_tv: float = 1e9, top_frac: float = 0.10, min_names: int = 20) -> dict:
    df = _load_kr()
    if df.is_empty():
        return {}
    df = df.with_columns(pl.col("tv").rolling_mean(20).over("yf").alias("tv20"),
                         pl.col("date").dt.truncate("1mo").alias("m"))
    me = df.group_by("yf", "m").agg(pl.col("date").last(), pl.col("adj").last(), pl.col("close").last().alias("raw"),
                                    pl.col("tv20").last()).sort("yf", "m")
    me = me.with_columns(
        (pl.col("adj").shift(1).over("yf") / pl.col("adj").shift(12).over("yf") - 1).alias("mom"),
        (pl.col("adj").shift(-1).over("yf") / pl.col("adj") - 1).alias("fwd"),
        pl.col("m").shift(-1).over("yf").alias("m_next"),
    )
    # 다음 행이 바로 다음 달이 아니면(거래정지 등) 수익률 불명 → 0 처리 대신 제외하지 않고 다음 관측까지의 수익으로 둔다
    elig = me.filter((pl.col("raw") >= min_px) & (pl.col("tv20") >= min_tv) & pl.col("mom").is_not_null()
                     & pl.col("fwd").is_not_null() & (pl.col("fwd") > -0.99) & (pl.col("fwd") < 5))
    months = sorted(elig["m"].unique().to_list())
    rows, prev = [], set()
    for m in months:
        g = elig.filter(pl.col("m") == m)
        if len(g) < min_names * 3:
            continue
        k = max(min_names, int(len(g) * top_frac))
        topg = g.sort("mom", descending=True).head(k)
        names = set(topg["yf"].to_list())
        turn = 1.0 if not prev else 1 - len(names & prev) / len(names)
        prev = names
        rows.append({"m": m, "port": float(topg["fwd"].mean()) - turn * COST * 2, "bench": float(g["fwd"].mean()),
                     "n": len(g), "k": k, "turn": round(turn, 3)})
    if not rows:
        return {}
    # 시장 필터: 벤치마크 누적지수가 10개월 평균 아래면 다음 달 현금
    eq, hist = 1.0, []
    for r in rows:
        hist.append(eq)
        ma10 = sum(hist[-10:]) / len(hist[-10:])
        r["filt"] = r["port"] if (len(hist) < 10 or eq >= ma10) else 0.0
        eq *= 1 + r["bench"]
    port, bench, filt = [r["port"] for r in rows], [r["bench"] for r in rows], [r["filt"] for r in rows]
    years: dict[int, dict] = {}
    for r in rows:
        y = r["m"].year
        d = years.setdefault(y, {"port": 1.0, "bench": 1.0, "filt": 1.0})
        for k in ("port", "bench", "filt"):
            d[k] *= 1 + r[k]
    curve, a, b, c = [], 1.0, 1.0, 1.0
    for r in rows:
        a *= 1 + r["port"]; b *= 1 + r["bench"]; c *= 1 + r["filt"]  # noqa: E702
        curve.append([str(r["m"])[:7], round(a, 4), round(b, 4), round(c, 4)])
    worst = sorted(rows, key=lambda r: r["port"] - r["bench"])[:5]
    out = {
        "asof": datetime.now(KST).strftime("%Y-%m-%d %H:%M KST"),
        "rule": f"월말 리밸런싱 · 12-1개월 수익률 상위 {int(top_frac*100)}%(최소 {min_names}종목) 동일가중 · "
                f"종가 {min_px:,.0f}원↑ · 20일 평균 거래대금 {min_tv/1e8:,.0f}억↑ · 교체분 편도 {COST*100:.1f}% 비용 · 상장폐지 포함",
        "stats": {"momentum": _stats(port), "universe_ew": _stats(bench), "momentum_filtered": _stats(filt)},
        "hit_vs_bench": round(sum(1 for r in rows if r["port"] > r["bench"]) / len(rows), 3),
        "avg_names": round(sum(r["k"] for r in rows) / len(rows)), "avg_turnover": round(sum(r["turn"] for r in rows) / len(rows), 3),
        "years": [{"year": y, **{k: round(v - 1, 4) for k, v in d.items()}} for y, d in sorted(years.items())],
        "curve": curve,
        "worst_months": [{"m": str(r["m"])[:7], "port": round(r["port"], 4), "bench": round(r["bench"], 4)} for r in worst],
    }
    (REPORT_DIR / "momentum_bt.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    log.info("모멘텀 백테스트 %d개월: %s", len(rows), out["stats"]["momentum"])
    return out
