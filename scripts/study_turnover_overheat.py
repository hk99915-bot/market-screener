"""가설 — 거래대금 과열 페널티: '조용한 강세주' vs '거래대금 폭발 급등주' (사전등록 백테스트, 연구 전용).

python3 scripts/study_turnover_overheat.py   → reports/studies/2026-11-14_turnover_overheat.json

## §0 사전등록 (결과 보기 전에 이 파일을 커밋한다)
- 주제: turnover_overheat (새 주제 — 거래량 폭발 자체를 다룬 us_spike N 722 는 '폭등 뒤 방향'이라 질문이 다르다.
        이 연구 m=2 를 더하면 주제 N = 2, α(N) = 0.025)
- 데이터: `data/hist/kr_YYYY.parquet`(KR 전종목 2010~2025) · `data/hist/us_YYYY.parquet`(US 666종목 2010~2025).
        메모리 때문에 3년씩 읽고 그 해 행만 남긴다 → **사건은 2011~2025**, 2010 은 워밍업(60거래일·20일 기준선).
        열 = yf·date·open·high·low·close·volume (조정 종가 없음) → 기업행위는 `screener.turnover_filter.adjust_series`
        규칙(KRX ±31% 밴드)으로 추정해 과거 가격을 조정한다.
- 거래대금 근사: tv = 조정 종가 × 조정 거래량 (KR 원, US 달러). 회전율(시총 대비)은 상장주식수 이력이 없어 계산 불가 —
  대신 '직전 20일 평균 대비 배수'를 과열 지표로 쓴다.
- 지표 (모두 t일 종가 시점까지 정보):
    tv5(t)    = 최근 5거래일 평균 tv
    base20(t) = 직전 20거래일 평균 tv (t−24 ~ t−5, 오늘·최근 5일 제외)
    ratio(t)  = tv5 / base20                     ← 과열 배수
    r5(t)     = 종가(t)/종가(t−5) − 1
- 사건(강세): r5 ≥ +10% 인 유동성 종목일
    유동성: 종가 ≥ 1,000원(KR)·$3(US) · base20 ≥ 50억원(KR)·$5백만(US) · 상장 후 60거래일 이상
    제외: 창(t ~ t+10)에 데이터 오류일(|일간·갭·장중| > 32%) 포함, 창 미완성(상장폐지·데이터 끝)
- 그룹: 과열(hot) ratio ≥ 2.0 · 조용(quiet) ratio ≤ 1.2 · 그 사이(mid)는 대조에서 제외
- 성과: t+1 시가 매수 → t+5 / t+10 종가 매도. 초과수익 = 종목 성과 − 같은 날 같은 시장 유동성 유니버스 평균 성과
- 가설 m=2, α = 0.05/2 = 0.025 (단측)
    H1: (조용 − 과열) 5일 초과수익 차이 > 0
    H2: (조용 − 과열) 10일 초과수익 차이 > 0
- 검정: 날짜별 두 그룹 평균의 차 → **월 단위 군집 t**(겹치는 5·10일 창과 같은 날 군집 완화). 날짜 단위 Welch t 는 참고만.
- 분할: IS ≤ 2019-12-31 / OOS ≥ 2020-01-01
- 등급: `screener.turnover_filter.grade()` — A=Bonferroni 통과+IS·OOS 같은 방향 · B=통과, 방향 불일치
        C=방향만(p<0.10) · F=구별 안 됨 · 검증전=사건<30 또는 월<12
- 시장: H1·H2 는 **KR** 에서 검정(겸님 국장 중심). US 동일 정의 재현은 탐색(등급 대상 아님).
- 탐색(등급 대상 아님, `exploratory`): 문턱 변형(과열 3.0·조용 1.0), 강세 문턱 20%, 겹침 제거(10거래일 간격),
        거래량(주식수) 배수만 사용, US 재현. **결과를 본 뒤 주 가설·문턱을 바꾸지 않는다.**
"""
from __future__ import annotations

import glob
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from screener import turnover_filter as tf  # noqa: E402

OUT = ROOT / "reports" / "studies" / "2026-11-14_turnover_overheat.json"

M = 2
ALPHA = 0.05 / M
IS_END = "2019-12-31"
H = (5, 10)
R5_MIN = 0.10
COLLECT_R5 = 0.05        # 후보 수집 문턱(탐색용 여유분) — 주 가설 문턱은 R5_MIN
HOT, QUIET = 2.0, 1.2
FAST, SLOW = 5, 20
MIN_AGE = 60

MARKETS = {
    "KR": {"prefix": "kr", "min_px": 1000.0, "min_tv": 5e9, "label": "KR (KOSPI+KOSDAQ, 2010~2025)"},
    "US": {"prefix": "us", "min_px": 3.0, "min_tv": 5e6, "label": "US (대형주 666, 2010~2025)"},
}


# ───────────────────────── 데이터 스캔 ─────────────────────────
def _future_any(bad: np.ndarray, h: int) -> np.ndarray:
    """t~t+h 안에 오류일이 하나라도 있으면 True."""
    n = bad.size
    cum = np.concatenate([[0], np.cumsum(bad.astype(np.int64))])
    hi = np.minimum(np.arange(n) + h + 1, n)
    return (cum[hi] - cum[np.arange(n)]) > 0


def _year_files(prefix: str, y: int) -> list[str]:
    return [f for f in (ROOT / "data" / "hist" / f"{prefix}_{yy}.parquet" for yy in (y - 2, y - 1, y)) if f.exists()]


def scan(market: str, spec: dict, years=range(2011, 2026)) -> dict:
    """한 시장을 연도 청크(직전 2년 워밍업 포함)로 훑어 (a) 강세 후보 (b) 날짜별 유동성 유니버스 평균 성과를 모은다.

    8.5M 행을 한 번에 올리면 메모리가 모자라(3GB 환경) 3년씩 읽고 **그 해 행만** 남긴다.
    age(60거래일) 는 청크 안 행 위치로 세므로 청크 시작 연도가 2011 이면 2010 이 워밍업이 된다.
    high·low 는 읽지 않는다(조정·오류일 판정은 시가·종가만 쓴다).
    """
    cand = {k: [] for k in ("d", "r5", "r20", "ratio", "ratio1", "f5", "f10")}
    bench: dict[int, list[float]] = {}
    n_rows, n_file_rows, syms, first, last = 0, 0, set(), None, None
    for f in sorted(glob.glob(str(ROOT / "data" / "hist" / f"{spec['prefix']}_[0-9][0-9][0-9][0-9].parquet"))):
        n_file_rows += pl.scan_parquet(f).select(pl.len()).collect().item()
        syms |= set(pl.read_parquet(f, columns=["yf"])["yf"].unique().to_list())
    for y in years:
        files = _year_files(spec["prefix"], y)
        if not files:
            continue
        df = pl.concat([pl.read_parquet(f) for f in files], how="vertical_relaxed").select(
            "yf", "date", "open", "close", "volume")
        df = df.filter((pl.col("open") > 0) & (pl.col("close") > 0) & (pl.col("volume") >= 0)).sort(["yf", "date"])
        n_rows += df.height
        gid = df.select(pl.col("yf").rle_id()).to_series().to_numpy()
        starts = np.concatenate([[0], np.flatnonzero(np.diff(gid) != 0) + 1])
        o_all = df["open"].to_numpy().astype(np.float64)
        c_all = df["close"].to_numpy().astype(np.float64)
        v_all = df["volume"].to_numpy().astype(np.float64)
        d_all = df["date"].to_numpy().astype("datetime64[D]").astype(np.int64)
        del df
        d0 = int(np.datetime64(f"{y}-01-01", "D").astype(np.int64))
        d1 = int(np.datetime64(f"{y + 1}-01-01", "D").astype(np.int64))
        if first is None:
            first = str(np.datetime64(int(d_all.min()), "D"))
        last = str(np.datetime64(int(d_all.max()), "D"))

        ends = np.concatenate([starts[1:], [o_all.size]])
        for a, b in zip(starts, ends):
            if b - a < MIN_AGE + max(H) + 1:
                continue
            o, c, v, dd = o_all[a:b], c_all[a:b], v_all[a:b], d_all[a:b]
            delisted = dd[-1] < int(d_all.max()) - 14      # 그 해 중간에 끝난 종목(상장폐지·정리매매 추정)
            adj = tf.adjust_series(o, o, o, c, v, delisted=delisted)
            o, c, v = adj["open"], adj["close"], adj["volume"]
            bad = tf.bad_days(o, c)
            tv = tf.turnover(c, v)
            ratio = tf.intensity(tv, FAST, SLOW)
            base = tf.prior_mean(tv, SLOW, FAST)
            with np.errstate(divide="ignore", invalid="ignore"):
                ratio1 = np.where(base > 0, tv / base, np.nan)     # 당일 하루 배수(탐색용)
            r5 = tf.ret(c, 5)
            r20 = tf.ret(c, 20)
            in_yr = (dd >= d0) & (dd < d1)
            liq = (c >= spec["min_px"]) & (base >= spec["min_tv"]) & in_yr
            liq[:MIN_AGE] = False
            fw = {h: tf.forward_open_return(o, c, h) for h in H}
            n = c.size
            ok5 = liq & (np.arange(n) + 5 <= n - 1) & ~_future_any(bad, 5)
            ok10 = liq & (np.arange(n) + 10 <= n - 1) & ~_future_any(bad, 10)
            # 유동성 유니버스 평균(초과수익 기준선) — 신호와 무관한 같은 날 전 종목
            for h, ok in ((5, ok5), (10, ok10)):
                sel = ok & ~np.isnan(fw[h])
                if not sel.any():
                    continue
                di, inv = np.unique(dd[sel], return_inverse=True)
                s = np.bincount(inv, weights=fw[h][sel])
                k = np.bincount(inv)
                for d_, s_, k_ in zip(di.tolist(), s.tolist(), k.tolist()):
                    row = bench.setdefault(d_, [0.0, 0, 0.0, 0])
                    row[0] += s_; row[1] += int(k_)
                    if h == 10:
                        row[2] += s_; row[3] += int(k_)
            sig = ok5 & (r5 >= COLLECT_R5) & ~np.isnan(ratio)
            if sig.any():
                cand["d"].append(dd[sig]); cand["r5"].append(r5[sig]); cand["r20"].append(r20[sig])
                cand["ratio"].append(ratio[sig]); cand["ratio1"].append(ratio1[sig])
                cand["f5"].append(fw[5][sig])
                cand["f10"].append(np.where(ok10[sig], fw[10][sig], np.nan))
        del o_all, c_all, v_all, d_all

    cat = {k: (np.concatenate(v_) if v_ else np.array([])) for k, v_ in cand.items()}
    bench_mean = {int(d_): (v_[0] / v_[1], v_[2] / v_[3] if v_[3] else np.nan) for d_, v_ in bench.items()}
    return {"cand": cat, "bench": bench_mean, "rows": n_file_rows, "syms": len(syms),
            "chunk_rows": n_rows, "years": [years[0], years[-1]], "first": first, "last": last}


# ───────────────────────── 집단 비교 ─────────────────────────
def _frame(scan_res: dict) -> pd.DataFrame:
    c = scan_res["cand"]
    if c["d"].size == 0:
        return pd.DataFrame(columns=["day", "date", "r5", "r20", "ratio", "ratio1", "f5", "f10", "exc5", "exc10"])
    df = pd.DataFrame({"day": c["d"].astype(np.int64), "r5": c["r5"], "r20": c["r20"],
                       "ratio": c["ratio"], "ratio1": c["ratio1"], "f5": c["f5"], "f10": c["f10"]})
    df["date"] = pd.to_datetime(df["day"], unit="D").dt.strftime("%Y-%m-%d")
    mean5 = {d: v[0] for d, v in scan_res["bench"].items()}
    mean10 = {d: v[1] for d, v in scan_res["bench"].items()}
    df["exc5"] = df.f5 - df.day.map(mean5)
    df["exc10"] = df.f10 - df.day.map(mean10)
    return df


def _side(x: pd.Series, col: str) -> dict:
    """한 그룹 요약 — 초과수익·절대수익·승률·하락 꼬리."""
    e = x[col].dropna()
    ab = x[col.replace("exc", "f")].dropna() if col.startswith("exc") else e
    if e.size == 0:
        return {"n": 0}
    return {"n": int(e.size), "exc_mean": float(e.mean()), "exc_median": float(e.median()),
            "raw_mean": float(ab.mean()), "win_exc": float((e > 0).mean()), "win_raw": float((ab > 0).mean()),
            "tail10": float((e <= -0.10).mean()), "tail20": float((e <= -0.20).mean()),
            "worst": float(e.min()), "p05": float(np.percentile(e, 5))}


def compare(df: pd.DataFrame, horizon: int, *, hot: float, quiet: float, r5_min: float,
            nonoverlap: bool = False, ratio_col: str = "ratio", strength_col: str = "r5",
            strength_min: float | None = None) -> dict:
    """과열 vs 조용 비교 1건. 초과수익 차이(조용−과열)를 날짜·월 단위로 검정한다."""
    col, fcol = (f"exc{horizon}", f"f{horizon}")
    smin = r5_min if strength_min is None else strength_min
    d = df[(df[strength_col] >= smin) & df[col].notna()].copy()
    if d.empty:
        return {"n_events": 0}
    d["lab"] = np.where(d[ratio_col] >= hot, "hot", np.where(d[ratio_col] <= quiet, "quiet", "mid"))
    if nonoverlap:
        keep, last = [], None
        for x in sorted(d.date.unique()):
            if last is None or (pd.Timestamp(x) - pd.Timestamp(last)).days >= 14:
                keep.append(x); last = x
        d = d[d.date.isin(keep)]
    hotg, quietg, midg = d[d.lab == "hot"], d[d.lab == "quiet"], d[d.lab == "mid"]
    g = d[d.lab != "mid"].groupby(["date", "lab"])[col].mean().unstack()
    g = g.dropna(subset=["hot", "quiet"]) if {"hot", "quiet"} <= set(g.columns) else g.iloc[0:0]
    diffs = (g["quiet"] - g["hot"]) if len(g) else pd.Series(dtype=float)
    month = tf.month_cluster(diffs.to_numpy(), g.index.to_numpy()) if len(g) else {"p_one": None, "n_months": 0}
    mon = np.array([str(x)[:7] for x in g.index]) if len(g) else np.array([])
    is_mask = np.array([m <= IS_END[:7] for m in mon]) if len(g) else np.array([], bool)
    return {
        "n_events": int(len(d)), "n_dates": int(len(g)), "n_months": month.get("n_months"),
        "n_hot": int(len(hotg)), "n_quiet": int(len(quietg)), "n_mid": int(len(midg)),
        "share_hot": float((d.lab == "hot").mean()), "share_quiet": float((d.lab == "quiet").mean()),
        "hot": _side(hotg, col), "quiet": _side(quietg, col), "mid": _side(midg, col),
        "all": _side(d, col),
        "diff": tf.welch(quietg[col], hotg[col]),
        "month": month,
        "is": tf.month_cluster(diffs.to_numpy()[is_mask], g.index.to_numpy()[is_mask]) if len(g) and is_mask.any() else {"p_one": None},
        "oos": tf.month_cluster(diffs.to_numpy()[~is_mask], g.index.to_numpy()[~is_mask]) if len(g) and (~is_mask).any() else {"p_one": None},
        "nonoverlap": nonoverlap,
    }


def _prop_diff_p(p_q, p_h, n_q, n_h) -> float | None:
    """하락 꼬리 비율 차(조용−과열)의 **양측** 정규 p — 서술 통계용(등급 대상 아님, 겹침 미보정)."""
    if not all(isinstance(x, float) for x in (p_q, p_h)) or not n_q or not n_h:
        return None
    pool = (p_q * n_q + p_h * n_h) / (n_q + n_h)
    se = math.sqrt(pool * (1 - pool) * (1 / n_q + 1 / n_h))
    if se <= 0:
        return None
    z = (p_q - p_h) / se
    return 2 * tf.p_one_sided(abs(z), +1)


def summarize(name: str, res: dict, alpha: float = ALPHA, cap: str | None = None) -> dict:
    """등급 부여 + 사람이 읽는 요약 1건. cap="C" 는 사전등록 밖 탐색의 등급 상한."""
    if not res.get("n_events"):
        return {"id": name, "grade": "검증전", "why": "사건 없음", "n": 0}
    mon = res["month"]
    p = mon.get("p_one")
    subs = {"is": (res.get("is") or {}).get("mean"), "oos": (res.get("oos") or {}).get("mean")}
    g, why = tf.grade(p, subs, res["n_events"], res.get("n_months") or 0, alpha)
    if cap and g in ("A", "B"):
        g, why = cap, f"{why} — 단 사전등록 밖 탐색이라 상한 {cap}"
    q, h = res["quiet"], res["hot"]
    return {"id": name, "grade": g, "why": why, "n": res["n_events"], "n_dates": res["n_dates"],
            "n_hot": res["n_hot"], "n_quiet": res["n_quiet"], "n_mid": res.get("n_mid"),
            "share_hot": res.get("share_hot"), "share_quiet": res.get("share_quiet"),
            "quiet_exc": q.get("exc_mean"), "hot_exc": h.get("exc_mean"),
            "diff_exc": (q.get("exc_mean") or 0) - (h.get("exc_mean") or 0) if q.get("n") and h.get("n") else None,
            "quiet_raw": q.get("raw_mean"), "hot_raw": h.get("raw_mean"),
            "quiet_win": q.get("win_exc"), "hot_win": h.get("win_exc"),
            "quiet_win_raw": q.get("win_raw"), "hot_win_raw": h.get("win_raw"),
            "quiet_tail10": q.get("tail10"), "hot_tail10": h.get("tail10"),
            "quiet_tail20": q.get("tail20"), "hot_tail20": h.get("tail20"),
            "tail10_diff_p": _prop_diff_p(q.get("tail10"), h.get("tail10"), q.get("n"), h.get("n")),
            "tail20_diff_p": _prop_diff_p(q.get("tail20"), h.get("tail20"), q.get("n"), h.get("n")),
            "quiet_worst": q.get("worst"), "hot_worst": h.get("worst"),
            "p_month": p, "t_month": mon.get("t"), "month_mean": mon.get("mean"), "n_months": mon.get("n_months"),
            "p_date_welch": res["diff"].get("p_one"), "t_date_welch": res["diff"].get("t"),
            "is": {"diff": (res.get("is") or {}).get("mean"), "p": (res.get("is") or {}).get("p_one"),
                   "months": (res.get("is") or {}).get("n_months")},
            "oos": {"diff": (res.get("oos") or {}).get("mean"), "p": (res.get("oos") or {}).get("p_one"),
                    "months": (res.get("oos") or {}).get("n_months")},
            "nonoverlap": res.get("nonoverlap", False)}


def run() -> dict:
    frames, metas = {}, {}
    for mk, spec in MARKETS.items():
        sc = scan(mk, spec)
        frames[mk] = _frame(sc)
        metas[mk] = {"rows": sc["rows"], "symbols": sc["syms"], "first": sc["first"], "last": sc["last"],
                     "years": sc["years"], "candidates": int(frames[mk].shape[0])}
        del sc                       # 메모리(3GB 환경) — 원시 사건 행은 프레임으로 옮겼다

    kr = frames["KR"]
    main5 = compare(kr, 5, hot=HOT, quiet=QUIET, r5_min=R5_MIN)
    main10 = compare(kr, 10, hot=HOT, quiet=QUIET, r5_min=R5_MIN)
    exp = {
        "hot3_quiet1": summarize("hot3_quiet1", compare(kr, 5, hot=3.0, quiet=1.0, r5_min=R5_MIN), cap="C"),
        "r5_20pct": summarize("r5_20pct", compare(kr, 5, hot=HOT, quiet=QUIET, r5_min=0.20), cap="C"),
        "r5_5pct": summarize("r5_5pct", compare(kr, 5, hot=HOT, quiet=QUIET, r5_min=0.05), cap="C"),
        "r20_20pct": summarize("r20_20pct", compare(kr, 5, hot=HOT, quiet=QUIET, r5_min=R5_MIN,
                                                    strength_col="r20", strength_min=0.20), cap="C"),
        "spike_day_3x": summarize("spike_day_3x", compare(kr, 5, hot=3.0, quiet=1.2, r5_min=R5_MIN,
                                                          ratio_col="ratio1"), cap="C"),
        "nonoverlap_2weeks": summarize("nonoverlap_2weeks", compare(kr, 5, hot=HOT, quiet=QUIET, r5_min=R5_MIN, nonoverlap=True), cap="C"),
        "us_replication_5": summarize("us_replication_5", compare(frames["US"], 5, hot=HOT, quiet=QUIET, r5_min=R5_MIN), cap="C"),
        "us_replication_10": summarize("us_replication_10", compare(frames["US"], 10, hot=HOT, quiet=QUIET, r5_min=R5_MIN), cap="C"),
    }
    exp = {k: v for k, v in exp.items() if v}
    return {
        "generated": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "id": "turnover_overheat",
        "title": "거래대금 과열 페널티 — 조용한 강세주 vs 거래대금 폭발 급등주",
        "prereg": {"m": M, "alpha_bonf": round(ALPHA, 5), "is_end": IS_END, "horizons": list(H),
                   "entry": "t+1 시가", "signal": f"r5 >= {R5_MIN}", "fast": FAST, "slow": SLOW,
                   "hot": HOT, "quiet": QUIET, "min_age": MIN_AGE,
                   "liquidity": {mk: {"min_px": s["min_px"], "min_tv": s["min_tv"]} for mk, s in MARKETS.items()},
                   "test": "월 단위 군집 t 단측, IS ≤2019 / OOS 2020~", "main_market": "KR",
                   "data": metas},
        "main": summarize("H1_5d", main5),
        "main10": summarize("H2_10d", main10),
        "exploratory": exp,
        "grades": {"H1": summarize("H1_5d", main5)["grade"], "H2": summarize("H2_10d", main10)["grade"]},
        "detail": {"H1": main5, "H2": main10},
        "meta": {"run_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")},
    }


def main(argv=None) -> int:
    out = run()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o)) + "\n",
                   encoding="utf-8")
    for k in ("main", "main10"):
        m = out[k]
        print(f"[{m['id']}] 사건 {m['n']}건/날짜 {m['n_dates']} (과열 {m['n_hot']}·조용 {m['n_quiet']}·중간 {m['n_mid']}) "
              f"초과 {m['quiet_exc']:+.4f} vs {m['hot_exc']:+.4f} (차 {m['diff_exc']:+.4f}, 월 p {m['p_month']}) → {m['grade']}")
        print(f"   IS {m['is']['diff']} (p {m['is']['p']}, {m['is']['months']}M) · OOS {m['oos']['diff']} (p {m['oos']['p']}, {m['oos']['months']}M)")
    for k, v in out["exploratory"].items():
        print(f"   [{k}] n {v['n']} 차 {v['diff_exc']}  p {v['p_month']} → {v['grade']}")
    print(f"→ {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
