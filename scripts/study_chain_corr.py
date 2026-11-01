"""체인(27개) 시총가중 바스켓 상관·군집·하방 동조·미장 연계 (퀀트 데스크, 2026-11-01, 기술통계).

선행 docs/desk_kb/rounds/2026-10-30/quant_theme_corr.md 와 같은 식:
  r_basket,t = Σ w_i r_i,t / Σ w_i (당일 수익률 있는 종목만, |r|≥35% 제외), w = 현재 시총 고정
  ρ = Pearson, 주간 = 금요일 마감 복리, 하방 = KOSPI 일간 ≤ −3% 날 평균
입력: screener.drivers.CHAINS(codes) · reports/peers_KR.json mc (없으면 screener.shares × 최근 종가)
      · screener.prices.load_kr(hist_from=2019) · data/hist/kr_index_daily.parquet(KOSPI, ~10/16) + reports/chains.json ^KS11(이후)
      · US: data/hist/us_YYYY.parquet(2020~2025) + data/hist/us_daily.parquet(~10/16) + reports/chains.json series(14개월, ~10/30) — 수익률 단위로 이음(우선순위 chains > us_daily > us_YYYY), USD·환율 미반영
출력: reports/studies/2026-11-01_chain_corr.json (+ --md 로 표 텍스트 stdout)
사용: python3 scripts/study_chain_corr.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from screener.drivers import CHAINS  # noqa: E402
from screener.prices import load_kr  # noqa: E402

START = "2020-01-01"
OUTLIER = 0.35
K_RANGE = (4, 5, 6)
OUT = ROOT / "reports/studies/2026-11-01_chain_corr.json"


def kr_returns() -> tuple[pd.DataFrame, pd.DataFrame]:
    codes = sorted({c for ch in CHAINS.values() for c in ch["codes"]})
    df = load_kr(hist_from=2019).with_columns(pl.col("yf").str.slice(0, 6).alias("code")).filter(pl.col("code").is_in(codes))
    px = df.select("code", "date", "close").to_pandas().pivot_table(index="date", columns="code", values="close")
    px.index = pd.to_datetime(px.index)
    r = px.pct_change(fill_method=None)
    r = r.where(r.abs() < OUTLIER)
    raw = load_kr(raw=True, hist_from=2019).with_columns(pl.col("yf").str.slice(0, 6).alias("code")).filter(pl.col("code").is_in(codes))
    last = raw.sort("date").group_by("code").agg(pl.col("close").last()).to_pandas().set_index("code")["close"]
    return r.loc[START:], last


def weights(last: pd.Series) -> tuple[dict, dict]:
    peers = json.loads((ROOT / "reports/peers_KR.json").read_text(encoding="utf-8"))
    mc = {r["s"]: r.get("mc") for r in peers["rows"] if r.get("mc")}
    src = {c: "peers_KR mc" for c in mc}
    try:
        from screener.shares import shares_map
        sm = shares_map()
    except Exception:  # noqa: BLE001
        sm = {}
    for ch in CHAINS.values():
        for c in ch["codes"]:
            if c not in mc and c in sm and c in last.index:
                mc[c] = sm[c]["n"] * float(last[c])
                src[c] = "shares×종가"
    return mc, src


def baskets(r: pd.DataFrame, mc: dict) -> tuple[pd.DataFrame, dict]:
    out, meta = {}, {}
    for k, ch in CHAINS.items():
        cs = [c for c in ch["codes"] if c in mc and c in r.columns]
        w = pd.Series({c: mc[c] for c in cs}, dtype=float)
        sub = r[cs]
        m = sub.notna()
        num = (sub.fillna(0) * w).sum(axis=1)
        den = (m * w).sum(axis=1)
        out[k] = (num / den).where(den > 0)
        top = (w / w.sum()).sort_values(ascending=False) if len(w) else w
        meta[k] = {"n": len(cs), "dropped": [c for c in ch["codes"] if c not in cs],
                   "top": [(c, round(float(v), 2)) for c, v in top.head(2).items()]}
    return pd.DataFrame(out), meta


def weekly(r: pd.DataFrame) -> pd.DataFrame:
    return (1 + r.fillna(0)).resample("W-FRI").prod().sub(1).where(r.notna().resample("W-FRI").sum() > 0)


def avg_linkage(D: np.ndarray, k: int) -> list[int]:
    """평균 연결 계층 군집 (scipy 없이). D = 거리행렬, k = 군집 수 → 라벨."""
    clusters = [[i] for i in range(len(D))]
    while len(clusters) > k:
        best, bi, bj = np.inf, 0, 0
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                d = D[np.ix_(clusters[i], clusters[j])].mean()
                if d < best:
                    best, bi, bj = d, i, j
        clusters[bi] = clusters[bi] + clusters[bj]
        del clusters[bj]
    lab = [0] * len(D)
    for ci, c in enumerate(sorted(clusters, key=lambda c: min(c))):
        for i in c:
            lab[i] = ci
    return lab


def silhouette(D: np.ndarray, lab: list[int]) -> float:
    lab = np.array(lab)
    s = []
    for i in range(len(D)):
        same = lab == lab[i]
        if same.sum() <= 1:
            s.append(0.0)
            continue
        a = D[i, same & (np.arange(len(D)) != i)].mean()
        b = min(D[i, lab == c].mean() for c in set(lab) if c != lab[i])
        s.append((b - a) / max(a, b))
    return float(np.mean(s))


def residual_corr(B: pd.DataFrame, since: pd.Timestamp) -> pd.DataFrame:
    """27체인 동일가중 평균(시장 요인 대용)에 대한 OLS 잔차 상관."""
    b = B.loc[B.index > since]
    f = b.mean(axis=1)
    res = {}
    for k in b:
        x = pd.concat([b[k], f], axis=1).dropna()
        beta = np.cov(x.iloc[:, 0], x.iloc[:, 1])[0, 1] / x.iloc[:, 1].var()
        res[k] = b[k] - beta * f
    return pd.DataFrame(res).corr()


# 군집 이름: 대표 체인(signature)이 들어 있는 군집에 붙인다 (결과 확인 후 붙인 사후 이름)
CLUSTER_NAMES = [("memory", "반도체·IT 하드웨어(수출 제조)"), ("shipbuilding", "수주 산업재(조선·방산·전력·원전)"),
                 ("chem", "소재·경기민감(화학·철강·정유·2차전지·해운)"), ("banks", "금리·방어(금융·증권·통신·공기업·항공)"),
                 ("bio", "내수 성장·소비(바이오·인터넷·화장품·음식료·보안·엔터)"), ("nonferrous", "비철(고려아연 단일)")]


def name_clusters(members: list[list[str]]) -> list[str]:
    out, used = [], set()
    for m in members:
        nm = next((n for sig, n in CLUSTER_NAMES if sig in m and n not in used), "")
        used.add(nm)
        out.append(nm)
    return out


def kospi() -> pd.Series:
    k = pd.read_parquet(ROOT / "data/hist/kr_index_daily.parquet")
    k = k[k.symbol == "KOSPI"].set_index("date")["close"]
    k.index = pd.to_datetime(k.index)
    r = k.pct_change(fill_method=None)
    ch = json.loads((ROOT / "reports/chains.json").read_text(encoding="utf-8"))["series"].get("^KS11")
    if ch:
        s = pd.Series({pd.Timestamp(d): v for d, v in ch}).pct_change(fill_method=None)
        r = r.combine_first(s[s.index > r.index.max()])
    return r.loc[START:]


def us_returns(tickers: set[str]) -> pd.DataFrame:
    parts = []
    for y in range(2019, 2026):
        p = ROOT / f"data/hist/us_{y}.parquet"
        if p.exists():
            u = pd.read_parquet(p, columns=["yf", "date", "close"])
            parts.append(u[u.yf.isin(tickers)])
    hist = pd.concat(parts).pivot_table(index="date", columns="yf", values="close")
    hist.index = pd.to_datetime(hist.index)
    r_hist = hist.pct_change(fill_method=None)
    ud = pd.read_parquet(ROOT / "data/hist/us_daily.parquet", columns=["symbol", "date", "adj_close"])
    ud = ud[ud.symbol.isin(tickers)].pivot_table(index="date", columns="symbol", values="adj_close")
    ud.index = pd.to_datetime(ud.index)
    r_ud = ud.pct_change(fill_method=None)
    ser = json.loads((ROOT / "reports/chains.json").read_text(encoding="utf-8"))["series"]
    r_ch = pd.DataFrame({t: pd.Series({pd.Timestamp(d): v for d, v in ser[t]}) for t in tickers if t in ser}).sort_index().pct_change(fill_method=None)
    r = r_ch.combine_first(r_ud).combine_first(r_hist)
    return r.loc[START:]


def usdkrw() -> tuple[pd.Series, dict]:
    """USD/KRW 종가(상승 = 원화 약세). 저장소 우선: reports/macro_series.json USDKRW(2024-09-30~) + reports/chains.json KRW=X.
    3y 창(2023-10~)에 모자라는 앞부분만 yfinance KRW=X 로 보충(같은 원천 — 겹침 540일 수익률 ρ 0.99997 확인 11/1)."""
    ms = json.loads((ROOT / "reports/macro_series.json").read_text(encoding="utf-8"))
    rows = ms["series"]["USDKRW"]   # fmt dohlcv → close = [4]
    s = pd.Series({pd.Timestamp(r[0]): float(r[4]) for r in rows}).sort_index()
    src = {"repo": f"reports/macro_series.json USDKRW {s.index.min().date()}~{s.index.max().date()} (asof {ms.get('asof')})"}
    ch = json.loads((ROOT / "reports/chains.json").read_text(encoding="utf-8"))["series"].get("KRW=X") or []
    c = pd.Series({pd.Timestamp(d): float(v) for d, v in ch})
    if len(c):
        s = s.combine_first(c[c.index > s.index.max()])
    r = s.pct_change(fill_method=None)
    try:
        import yfinance as yf
        y = yf.download("KRW=X", start="2019-12-01", end=str(s.index.min().date()), auto_adjust=True, progress=False)["Close"]
        y = (y["KRW=X"] if isinstance(y, pd.DataFrame) else y).dropna()
        y.index = pd.to_datetime(y.index).tz_localize(None)
        ry = y.pct_change(fill_method=None)
        r = r.combine_first(ry[ry.index < s.index.min()])
        src["backfill"] = f"yfinance KRW=X {y.index.min().date()}~{y.index.max().date()} (저장소에 없음 — 3y·전기간 앞부분 보충)"
    except Exception as e:  # noqa: BLE001
        src["backfill"] = f"실패({e}) — 3y 는 {s.index.min().date()}~ 만"
    return r.loc[START:], s, src


def fx_block(B: pd.DataFrame, y1, y3) -> tuple[dict, dict]:
    """27체인 원/달러 민감도 (11/1 추가 요청)."""
    rfx, lvl, src = usdkrw()
    keys = list(B)
    f = rfx.reindex(B.index)            # 같은 날짜(야후 FX 일봉은 런던·뉴욕 기준 — 국장 마감과 시차 있음)
    f_lag = rfx.shift(1).reindex(B.index)
    W = weekly(B)
    fw = (1 + rfx.fillna(0)).resample("W-FRI").prod().sub(1)
    mkt = B.mean(axis=1)
    # 원화 강세 구간: 2026 2Q말 → 3Q말 (요청 예시 구간)
    a, b = pd.Timestamp("2026-06-30"), pd.Timestamp("2026-09-30")
    fx_chg = float(lvl.loc[:b].iloc[-1] / lvl.loc[:a].iloc[-1] - 1)
    seg = B.loc[(B.index > a) & (B.index <= b)]
    out = {}
    for k in keys:
        def rb(since, x=f, y=B[k]):
            d = pd.concat([y, x], axis=1).loc[lambda z: z.index > since].dropna()
            if len(d) < 30:
                return None, None, 0
            beta = np.cov(d.iloc[:, 0], d.iloc[:, 1])[0, 1] / d.iloc[:, 1].var()
            return float(d.iloc[:, 0].corr(d.iloc[:, 1])), float(beta), len(d)
        rho3, beta3, n3 = rb(y3)
        rho1, beta1, n1 = rb(y1)
        rhol3, _, _ = rb(y3, x=f_lag)
        rhow3, betaw3, _ = rb(y3, x=fw, y=W[k])
        rho60, _, _ = rb(B.index[-61], x=f)
        # 시장 요인(27체인 동일가중) 통제 후 환율 베타 (3y 일간, 다중회귀)
        d = pd.concat([B[k], f, mkt], axis=1).loc[lambda z: z.index > y3].dropna()
        X = np.column_stack([np.ones(len(d)), d.iloc[:, 1], d.iloc[:, 2]])
        coef = np.linalg.lstsq(X, d.iloc[:, 0].values, rcond=None)[0]
        ret = float((1 + seg[k].fillna(0)).prod() - 1)
        out[k] = {"beta_3y": r2(beta3), "rho_3y": r2(rho3), "rho_1y": r2(rho1), "beta_1y": r2(beta1),
                  "rho_w3y": r2(rhow3), "beta_w3y": r2(betaw3), "rho_lag_3y": r2(rhol3), "rho_60": r2(rho60),
                  "beta_3y_mktctl": r2(coef[1]), "strong_krw_ret": r2(ret * 100),
                  "strong_krw_rel": r2((ret - float((1 + seg.mean(axis=1).fillna(0)).prod() - 1)) * 100), "n_3y": n3}
    kr = kospi()
    kseg = kr.loc[(kr.index > a) & (kr.index <= b)]
    meta = {"src": src, "sign": "USD/KRW 변화율(+ = 원화 약세). beta = 체인 수익률 / USD/KRW 변화율", "fx_last": str(lvl.index.max().date()),
            "strong_krw": {"from": str(a.date()), "to": str(b.date()), "usdkrw_chg_pct": r2(fx_chg * 100),
                           "usdkrw": [r2(lvl.loc[:a].iloc[-1]), r2(lvl.loc[:b].iloc[-1])], "kospi_pct": r2(((1 + kseg.fillna(0)).prod() - 1) * 100),
                           "ew27_pct": r2(((1 + seg.mean(axis=1).fillna(0)).prod() - 1) * 100), "unit": "strong_krw_ret %, 체인 일간 복리; rel = 27체인 동일가중 평균 대비 %p"},
            "rolling": "rho_60 = 최근 60거래일 일간 ρ(체인, USD/KRW)", "timing": "rho_lag_3y = 전일 USD/KRW 변화 → 당일 체인(야후 FX 일봉 시차 점검용)"}
    return out, meta


def r2(x):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), 2)


def main() -> None:
    r, last = kr_returns()
    mc, wsrc = weights(last)
    B, meta = baskets(r, mc)
    keys = list(CHAINS)
    asof = B.dropna(how="all").index.max()
    y1, y3 = asof - pd.DateOffset(years=1), asof - pd.DateOffset(years=3)
    c1 = B.loc[B.index > y1].corr()
    c3 = B.loc[B.index > y3].corr()
    W = weekly(B)
    cw3 = W.loc[W.index > y3].corr()
    call = B.corr()

    # (가) 원 상관 1−ρ 군집 — 요청 그대로. 공통(시장) 요인이 커서 '큰 덩어리 1 + 외톨이'로 나오는 경향
    D = 1 - c3.values
    np.fill_diagonal(D, 0)
    sil_raw = {k: silhouette(D, avg_linkage(D, k)) for k in K_RANGE}
    k_raw = max(sil_raw, key=sil_raw.get)
    lab_raw = avg_linkage(D, k_raw)
    # (나) 시장 요인 제거 후 1−ρ 군집 — 27체인 동일가중 평균에 대한 회귀 잔차(3y 일간) 상관. 화면 기본값
    res1, res3 = residual_corr(B, y1), residual_corr(B, y3)
    Dr = 1 - res3.loc[keys, keys].values
    np.fill_diagonal(Dr, 0)
    sil = {k: silhouette(Dr, avg_linkage(Dr, k)) for k in K_RANGE}
    kbest = max(sil, key=sil.get)
    labs = {k: avg_linkage(Dr, k) for k in K_RANGE}
    lab = labs[kbest]
    Dr1 = 1 - res1.loc[keys, keys].values
    np.fill_diagonal(Dr1, 0)
    lab_1y = avg_linkage(Dr1, kbest)   # 안정성: 같은 k 로 1y 잔차 군집

    # 하방 동조
    kr = kospi()
    down_all = kr[kr <= -0.03].index
    down_1y = down_all[down_all > y1]
    down_pre = down_all[down_all <= y1]   # 1y 이전(국면 하나 빼고 재계산용)
    downside = {k: {"all": r2(B.loc[B.index.isin(down_all), k].mean() * 100), "1y": r2(B.loc[B.index.isin(down_1y), k].mean() * 100),
                    "pre1y": r2(B.loc[B.index.isin(down_pre), k].mean() * 100)} for k in keys}
    downside["_KOSPI"] = {"all": r2(kr.loc[down_all].mean() * 100), "1y": r2(kr.loc[down_1y].mean() * 100), "pre1y": r2(kr.loc[down_pre].mean() * 100)}
    down_n = {"all": int(len(down_all)), "1y": int(len(down_1y)), "pre1y": int(len(down_pre)), "kospi_last": str(kr.dropna().index.max().date()),
              "by_year": {str(y): int(n) for y, n in pd.Series(1, index=down_all).groupby(down_all.year).sum().items()}}

    # 미장 연계 (3y, KR t vs US t 동일일 / US t → KR 다음 거래일)
    cv = json.loads((ROOT / "reports/chains_view.json").read_text(encoding="utf-8"))
    prox = {k: [p["ticker"] for p in cv["chains"][k]["proxies"] if p.get("relation") == 1] for k in keys}
    U = us_returns({t for v in prox.values() for t in v})
    us_link, us_cov = {}, {}
    kr_dates = B.index
    for k in keys:
        rows = []
        for t in prox[k]:
            if t not in U.columns:
                rows.append({"ticker": t, "rho_same": None, "rho_next": None, "n": 0})
                continue
            u = U[t].dropna()
            u = u[u.index > y3]
            same = pd.concat([B[k], u], axis=1, join="inner").dropna()
            # 미장 t → 국장 t+1: 각 KR 날짜 d 에 대해 d 직전(<d) 마지막 미장 거래일 수익률
            pos = u.index.searchsorted(kr_dates, side="left") - 1
            prev = pd.Series([u.iloc[p] if p >= 0 else np.nan for p in pos], index=kr_dates)
            nxt = pd.concat([B[k], prev], axis=1).loc[lambda x: x.index > max(y3, u.index.min())].dropna()
            rows.append({"ticker": t, "rho_same": r2(same.iloc[:, 0].corr(same.iloc[:, 1])) if len(same) > 30 else None,
                         "rho_next": r2(nxt.iloc[:, 0].corr(nxt.iloc[:, 1])) if len(nxt) > 30 else None,
                         "n": int(len(nxt)), "from": str(u.index.min().date()) if len(u) else None,
                         "to": str(u.index.max().date()) if len(u) else None})
        us_link[k] = rows

    # 최근 변화: 롤링 60일(최근값) vs 3y 평균 ρ
    rec = B.iloc[-60:]
    c60 = rec.corr()
    shifts = []
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            if pd.notna(c60.loc[a, b]) and pd.notna(c3.loc[a, b]):
                shifts.append({"a": a, "b": b, "rho60": r2(c60.loc[a, b]), "rho3y": r2(c3.loc[a, b]),
                               "d": r2(c60.loc[a, b] - c3.loc[a, b])})
    shifts.sort(key=lambda x: -abs(x["d"]))
    # 체인 평균 상관(다른 26개와) 변화
    avgc = {k: {"rho60_avg": r2(c60[k].drop(k).mean()), "rho3y_avg": r2(c3[k].drop(k).mean()), "rho1y_avg": r2(c1[k].drop(k).mean())} for k in keys}

    fx, fx_meta = fx_block(B, y1, y3)

    out = {
        "asof": str(asof.date()),
        "grade": "해당 없음(기술통계·사후 탐색) — 판단 근거 상한 C",
        "grades": {"체인 상관·군집·하방·미장 연계(기술통계)": "해당 없음(상한 C)"},
        "prereg": {"m": None, "alpha_bonf": None, "is_end": None, "cost": "해당 없음(기술통계, 가설검정 아님)"},
        "survivorship": "있음 — 현재 CHAINS 구성·현재 시총 고정가중으로 2020~ 소급(상폐·편출 미반영, 010620 2025-11 상폐 제외)",
        "dsr_pbo": "해당 없음(전략 성과 아님)",
        "basis": {"kr": f"load_kr(hist_from=2019) 조정 종가 {START}~{asof.date()}", "weights": "reports/peers_KR.json mc 고정(없으면 shares×최근 종가)",
                  "window_1y": f"> {y1.date()}", "window_3y": f"> {y3.date()}", "rolling": f"최근 60거래일 {rec.index.min().date()}~{rec.index.max().date()}",
                  "kospi": down_n, "us": "us_YYYY(~2025)+us_daily(~2026-10-16)+reports/chains.json series(~2026-10-30), USD·환율 미반영",
                  "cluster": f"평균 연결, 거리 1−ρ. 기본=시장 요인(27체인 동일가중 평균) 제거 잔차 일간 3y, k∈{list(K_RANGE)} 실루엣 최대 k={kbest}; 원 상관 군집은 clusters_raw(k={k_raw})",
                  "silhouette": {str(k): round(v, 3) for k, v in sil.items()},
                  "silhouette_raw": {str(k): round(v, 3) for k, v in sil_raw.items()}},
        "chains": [{"key": k, "name": CHAINS[k]["name"], "n": meta[k]["n"], "cluster": lab[i], "thin": meta[k]["n"] < 3,
                    "dropped": meta[k]["dropped"], "top": meta[k]["top"]} for i, k in enumerate(keys)],
        "corr_1y": [[r2(x) for x in row] for row in c1.loc[keys, keys].values],
        "corr_3y": [[r2(x) for x in row] for row in c3.loc[keys, keys].values],
        "corr_w3y": [[r2(x) for x in row] for row in cw3.loc[keys, keys].values],
        "corr_all": [[r2(x) for x in row] for row in call.loc[keys, keys].values],
        "clusters": [{"id": c, "name": "", "members": [k for i, k in enumerate(keys) if lab[i] == c]} for c in sorted(set(lab))],
        "clusters_alt": {str(k): [[keys[i] for i in range(len(keys)) if v[i] == c] for c in sorted(set(v))] for k, v in labs.items()},
        "clusters_1y_resid": [[keys[i] for i in range(len(keys)) if lab_1y[i] == c] for c in sorted(set(lab_1y))],
        "clusters_raw": [[keys[i] for i in range(len(keys)) if lab_raw[i] == c] for c in sorted(set(lab_raw))],
        "resid_corr_3y": [[r2(x) for x in row] for row in res3.loc[keys, keys].values],
        "downside": downside,
        "us_link": us_link,
        "shifts": shifts[:10],
        "fx": fx,
        "fx_meta": fx_meta,
        "avg_corr": avgc,
        "weight_src": {c: wsrc.get(c) for ch in CHAINS.values() for c in ch["codes"]},
    }
    for c, nm in zip(out["clusters"], name_clusters([c["members"] for c in out["clusters"]])):
        c["name"] = nm
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {OUT} asof={asof.date()} k={kbest} sil={sil}")


if __name__ == "__main__":
    main()
