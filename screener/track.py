"""시그널 성과 추적 — 화면에 띄우는 지표가 실제로 다음 수익률을 맞추는지 매일 기록·채점.

- 매일 종목별 시그널 스냅샷 → data/signals.parquet (date, code, 시그널들, close)
- 채점: 스냅샷일 이후 5/20/60 거래일 수익률(시장 중앙값 대비 초과)과의 순위상관(IC), 5분위 스프레드
- 결과 → reports/signal_scores.json (웹 SIGNALS 탭)
표본이 쌓이기 전(20거래일 미만)에는 '검증 중'으로 표시.
"""
from __future__ import annotations

import json
import logging
from datetime import date

import polars as pl

from .config import DATA_DIR, REPORT_DIR

log = logging.getLogger(__name__)
STORE = DATA_DIR / "signals.parquet"
SIG = {   # 컬럼: (설명, 클수록 좋다고 보는 방향)
    "val_mid": ("가치평가 모델 중앙 괴리", 1),
    "val_normal": ("정상화(평균 회귀) 적정가 괴리", 1),
    "val_signal": ("신호 가중 적정가 괴리", 1),
    "drv_score": ("이익 지속성 드라이버 종합", 1),
    "drv_chain": ("공급망 체인 점수", 1),
    "drv_analyst": ("애널리스트 점수(평균 대비)", 1),
    "drv_news": ("뉴스 이벤트 점수", 1),
    "fscore": ("F-score", 1),
    "trend_score": ("추세 점수", 1),
    "momentum_score": ("모멘텀 점수", 1),
    "reversal_risk": ("반전 위험", -1),
    "tp_upside": ("컨센서스 목표가 괴리", 1),
}
HORIZONS = (5, 20, 60)


def snapshot(asof, stocks: dict[str, dict]) -> int:
    """stocks: detail 의 out["stocks"]."""
    rows = []
    for c, s in stocks.items():
        v, d, st = s.get("valuation") or {}, s.get("drivers") or {}, s.get("stats") or {}
        gu = v.get("group_upside") or {}
        rows.append({"date": str(asof), "code": c, "close": s.get("close"),
                     "val_mid": (v.get("range") or {}).get("mid_upside"), "val_normal": gu.get("normal"),
                     "val_signal": (v.get("signal_fv") or {}).get("upside"),
                     "drv_score": d.get("score"), "drv_chain": (d.get("parts") or {}).get("chain"),
                     "drv_analyst": (d.get("parts") or {}).get("analyst"), "drv_news": (d.get("parts") or {}).get("news"),
                     "fscore": (v.get("fscore") or {}).get("score"),
                     "trend_score": st.get("trend_score"), "momentum_score": st.get("momentum_score"),
                     "reversal_risk": st.get("reversal_risk"), "tp_upside": (s.get("research") or {}).get("tp_upside")})
    if not rows:
        return 0
    schema = {"date": pl.Utf8, "code": pl.Utf8, "close": pl.Float64, **{k: pl.Float64 for k in SIG}}
    new = pl.DataFrame(rows, schema=schema)
    if STORE.exists():
        old = pl.read_parquet(STORE).filter(pl.col("date") != str(asof))
        new = pl.concat([old, new], how="vertical_relaxed")
    new.write_parquet(STORE)
    log.info("시그널 스냅샷 %s %d종목 (누적 %d일)", asof, len(rows), new["date"].n_unique())
    return len(rows)


def score(prices: pl.DataFrame) -> dict:
    """prices: yf,date,close (KR)."""
    if not STORE.exists():
        return {}
    sn = pl.read_parquet(STORE)
    px = (prices.with_columns(pl.col("yf").str.slice(0, 6).alias("code"), pl.col("date").cast(pl.Utf8))
                .select("code", "date", "close").sort("code", "date"))
    px = px.with_columns(pl.col("date").rank("dense").over("code").alias("_i"))
    days = sorted(px["date"].unique().to_list())
    out = {"asof": str(date.today()), "n_days": sn["date"].n_unique(), "first": sn["date"].min(), "signals": {}}
    for h in HORIZONS:
        fut = px.with_columns(pl.col("close").shift(-h).over("code").alias("_f")).select("code", "date", "_f")
        j = sn.join(fut, on=["code", "date"], how="inner").filter(pl.col("_f").is_not_null() & (pl.col("close") > 0))
        if j.is_empty():
            continue
        j = j.with_columns((pl.col("_f") / pl.col("close") - 1).alias("r"))
        j = j.with_columns((pl.col("r") - pl.col("r").median().over("date")).alias("ex"))
        for k, (desc, sign) in SIG.items():
            g = j.filter(pl.col(k).is_not_null())
            if g.height < 200:
                continue
            per = []
            spreads = []
            for (d0,), gd in g.group_by("date"):
                if gd.height < 30:
                    continue
                ic = gd.select(pl.corr(pl.col(k).rank(), pl.col("ex").rank())).item()
                if ic is not None:
                    per.append(ic * sign)
                q = gd.with_columns((pl.col(k).rank() / gd.height * 5).ceil().clip(1, 5).alias("q"))
                m = q.group_by("q").agg(pl.col("ex").mean())
                d = dict(zip(m["q"].to_list(), m["ex"].to_list()))
                if 5 in d and 1 in d:
                    spreads.append((d[5] - d[1]) * sign)
            if not per:
                continue
            n = len(per)
            mean = sum(per) / n
            sd = (sum((x - mean) ** 2 for x in per) / (n - 1)) ** 0.5 if n > 1 else None
            rec = out["signals"].setdefault(k, {"desc": desc})
            n_eff = max(n / h, 1.0)   # h일 수익률을 매일 겹쳐 쓰므로 독립 표본은 대략 n/h 개 → t값 과대 방지
            rec[f"h{h}"] = {"ic": round(mean, 3), "t": round(mean / (sd / n_eff ** 0.5), 1) if sd else None, "days": n,
                            "spread": round(sum(spreads) / len(spreads), 4) if spreads else None,
                            "hit": round(sum(1 for x in per if x > 0) / n, 2)}
    for k, rec in out["signals"].items():
        h = rec.get("h20") or rec.get("h5")
        if not h or h["days"] < 20:
            rec["verdict"] = "검증 중 (표본 부족)"
        elif h["t"] is not None and h["t"] >= 2 and h["ic"] > 0.02:
            rec["verdict"] = "유효"
        elif h["t"] is not None and h["t"] <= -2:
            rec["verdict"] = "역방향 (반대로 작동)"
        else:
            rec["verdict"] = "효과 불분명"
    (REPORT_DIR / "signal_scores.json").write_text(json.dumps(out, ensure_ascii=False, default=str), encoding="utf-8")
    return out


def backfill_tech(full: pl.DataFrame, days: int = 250) -> int:
    """과거 기술적 시그널(추세·모멘텀·반전위험)은 지표 테이블로 복원 가능 → 즉시 채점 표본 확보."""
    if "trend_score" not in full.columns:
        from .scoring import score as _score
        full = _score(full.sort("yf", "date"))
    cols = [c for c in ("trend_score", "momentum_score", "reversal_risk") if c in full.columns]
    have = set(pl.read_parquet(STORE)["date"].unique().to_list()) if STORE.exists() else set()
    ds = sorted({str(d) for d in full["date"].unique().to_list()})[-days:]
    ds = [d for d in ds if d not in have]
    if not ds:
        return 0
    f = (full.with_columns(pl.col("date").cast(pl.Utf8), pl.col("yf").str.slice(0, 6).alias("code"))
             .filter(pl.col("date").is_in(ds)).select("date", "code", "close", *cols))
    schema = {"date": pl.Utf8, "code": pl.Utf8, "close": pl.Float64, **{k: pl.Float64 for k in SIG}}
    f = f.with_columns([pl.lit(None, dtype=pl.Float64).alias(k) for k in SIG if k not in cols]).select(list(schema)).cast(schema)
    if STORE.exists():
        f = pl.concat([pl.read_parquet(STORE), f], how="vertical_relaxed")
    f.write_parquet(STORE)
    log.info("기술 시그널 과거 %d일 복원", len(ds))
    return len(ds)
