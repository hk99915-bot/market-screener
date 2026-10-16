"""반도체 비중 한도 — 밴드 · 글라이드 패스 · 하락장 하드캡 사전등록 비교 (semis_cap).

python scripts/study_semis_cap.py  → reports/studies/semis_cap.json (+ 표준출력 요약)

공개 저장소 — 비율(%)만 다룬다. 개인 금액·수량은 쓰지 않는다.

════════════════════════ 0. 사전 등록 (결과 계산 전에 고정, 2026-10-16) ════════════════════════
질문: '테마(반도체) 40% 고정 한도'를 (a) 밴드(목표 40 / 발동 45 / 하단 30, 주 1회 점검) (b) 글라이드 패스
(적립으로만 희석, 매도 없음) (c) 하락장 하드캡 30/35/40 으로 바꾸면 무엇이 달라지나.

0-1. 데이터 (네트워크 없음 — 저장본만)
- 반도체 대용치 = 삼성전자(005930)·SK하이닉스(000660) 50/50, 월말 리밸런싱. screener.lab.load_kr (data/hist 2010~2025 +
  data/kr_prices.parquet 2026, 분할 ±45% 갭 보정). 배당 제외(가격수익). ETF(091160·139260·069500)는 저장본에 없음 → 사용 불가.
- 나머지 자산 대용치 = 코스피200 (data/deriv/daily.csv k200_close), 배당 제외. 레짐·반등일 판정은 코스피 종가(kospi_close).
  (실제 '나머지'는 다자산 코어(S&P·나스닥·K200·국고채·금)라 변동성이 더 낮다 → 희석 속도는 같고, 낙폭은 실제가 더 작을 것. 한계로 명시.)
- 기간 2010-01-04 ~ 저장본 마지막 날(2026-10). IS = 윈도 시작일 ≤ 2019-12-31, OOS = 2020-01-01~.
- 비용: 매매 금액의 편도 0.125% (왕복 0.25%). 현금 이자 0. 적립은 비용 0.
- 반등일 = 코스피 종가 ≥ 전일 종가 +0.5% (14:30 데이터 없음 → 종가 근사, rule_audit T4와 같은 한계).
- 레짐: 하락장 = 코스피 종가 < 200일 단순이동평균 또는 종가 ≤ 20일 최고 종가 × 0.85. 그 외 = '회복 이상'.
- 주 1회 점검 = 주의 마지막 거래일 종가. 월 1회 점검 = 달의 마지막 거래일 종가. 체결은 판정 다음 거래일 종가(미래참조 금지).

0-2. 비교 단위와 검정
- 12개월(250거래일) 윈도를 매월 첫 거래일에 시작(겹침 허용), 모든 안을 같은 시작 상태(반도체 40 / 나머지 60)로 시작해
  같은 윈도끼리 짝지은 차이 d = 대안 − 기준 을 본다. 겹침 때문에 t는 Newey-West(HAC, lag 11) 표준오차로 계산.
- 전체 경로(2010~2026 한 번 돌린 것)의 CAGR·MDD·샤프·회전율은 서술용(검정 없음).
- m = 7 (H1 3 + H2 1 + H3 3) → Bonferroni α = 0.05/7 = 0.00714.
- 등급(rule_audit 규약): A = p<α & 전체·IS·OOS 부호 일치 / B = p<α / C = p<0.10 / F = p≥0.10 / 검증전 = 표본<10.
  위험 표기: 대안의 윈도 MDD 평균이 기준보다 1.5배 나쁘면 '위험 증가'.

0-3. 가설
H1 밴드 vs 고정캡 vs 보유. 안: BH(리밸런싱 없음) · CAP40M(월말 40% 초과분만 매도, 되사기 없음 = 현행 40% 고정 한도의 기계적 근사)
   · BAND(주말 점검: >45% → 다음 반등일에 40%로 매도, <30% → 회복 이상 레짐이면 다음 날 40%로 매수).
   비교: BAND−CAP40M, BAND−BH, CAP40M−BH (12개월 수익). 보조: MDD, 회전율, 발동 횟수, 45% 도달까지 거래일.
   PB 주장 검증: "45%는 자주 안 걸린다(나머지 대비 +23% 필요)" → 12개월 안 45% 도달 윈도 비율로 판정(≥25%면 '자주').
   사전 예상: 삼성·하이닉스 고베타라 상승장에 자주 걸릴 것. 수익 차이는 작고 MDD 차이도 작을 것.
H2 글라이드 패스(적립으로만 희석) vs 즉시 35% 매도 후 같은 적립. 적립 = 월 초 순자산 대비 c 를 나머지(K200)에 넣음.
   c 기본 = 0.137 (월 적립 ÷ 시작 순자산; 사전에 알려진 비율), 민감도 c = 0.07 / 0.03. 반도체 신규 매수 없음.
   지표: 12개월 뒤 순자산(적립 포함)/시작 순자산 → 차이 d = GLIDE − SELL35. 보조: MDD 분포, 글라이드가 35% 이하로
   처음 내려가는 달(분포), 12개월 중 반도체 비중 평균.
   PB 주장 검증: "글라이드 패스로 1개월 뒤 35%" → 산술상 가격 변동 없으면 40/(1+0.137)=35.2%. 실제 분포에서 1개월 안
   35% 이하 도달 윈도 비율을 보고(≥75%면 '맞음', 50~75 '대체로', <50 '틀림').
   사전 예상: 두 안의 12개월 순자산 차이는 반도체 5%p × 12개월 상대수익이라 평균 0 근처, 유의하지 않을 것.
H3 하락장 레짐에서 시작한 윈도만: 캡 30/35/40/45 (월말 초과분 매도, 되사기 없음). 지표: 12개월 수익/변동성(월간 수익 ÷ 월간 표준편차,
   보조로 윈도 MDD). 비교 (30,35,45)−40. '최소 MDD 캡' = 윈도 MDD 평균이 가장 작은 캡.
   PB 주장 검증: "30 vs 35는 −20% 충격에서 ≈1%p 차이" → 하락장 윈도 MDD 평균 차이(35−30)와 시작 후 반도체 −20%
   시점의 손실 차이로 판정(0.5~1.5%p 안이면 '맞음').
   사전 예상: 하락장에서 반도체는 코스피보다 더 빠지므로 낮은 캡이 MDD는 작게 하지만, 반등 구간을 놓쳐 수익은 비슷할 것.
   차이는 Bonferroni를 못 넘을 것.
═══════════════════════════════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import json
import math
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from screener.lab import load_kr  # noqa: E402
from study_entry_signals import t_cdf  # noqa: E402

CSV = ROOT / "data" / "deriv" / "daily.csv"
OUT = ROOT / "reports" / "studies" / "semis_cap.json"

SEMIS = ["005930.KS", "000660.KS"]
COST = 0.00125          # 편도
IS_END = pd.Timestamp("2019-12-31")
WIN = 250               # 12개월
M = 7
ALPHA = 0.05 / M
W0 = 0.40
CONTRIB = [0.137, 0.07, 0.03]
REBOUND = 0.005
HAC_LAG = 11


# ───────────────────────── 통계 ─────────────────────────
def hac_t(d: np.ndarray, lag: int = HAC_LAG) -> dict:
    d = np.asarray([x for x in d if x is not None and np.isfinite(x)], float)
    n = len(d)
    if n < 10:
        return {"n": n, "mean": float(d.mean()) if n else None, "t": None, "p": None}
    e = d - d.mean()
    s = float(e @ e)
    for k in range(1, min(lag, n - 1) + 1):
        s += 2 * (1 - k / (lag + 1)) * float(e[k:] @ e[:-k])
    se = math.sqrt(max(s, 1e-18)) / n
    t = d.mean() / se if se > 0 else float("nan")
    p = 2 * (1 - t_cdf(abs(t), n - 1)) if np.isfinite(t) else None
    return {"n": n, "mean": float(d.mean()), "t": float(t), "p": float(p) if p is not None else None}


def compare(d: np.ndarray, is_mask: np.ndarray) -> dict:
    return {"all": hac_t(d), "is": hac_t(d[is_mask]), "oos": hac_t(d[~is_mask])}


def grade(c: dict) -> tuple[str, str]:
    a = c["all"]
    p, m = a["p"], a["mean"]
    if p is None:
        return "검증전", f"표본 {a['n']}"
    if p < ALPHA:
        subs = [c[k]["mean"] for k in ("is", "oos") if c[k]["mean"] is not None]
        if all(np.sign(x) == np.sign(m) for x in subs):
            return "A", f"Bonferroni 유의(p={p:.4f}) + IS·OOS 같은 방향"
        return "B", f"Bonferroni 유의(p={p:.4f}), IS/OOS 방향 불일치"
    if p < 0.10:
        return "C", f"방향만(p={p:.3f}, α={ALPHA:.4f} 미달)"
    return "F", f"구별 안 됨(p={p:.2f})"


def mdd_of(nav: np.ndarray) -> float:
    return float((nav / np.maximum.accumulate(nav) - 1).min())


# ───────────────────────── 데이터 ─────────────────────────
def load() -> pd.DataFrame:
    idx = pd.read_csv(CSV, usecols=["date", "kospi_close", "k200_close"]).dropna()
    idx["date"] = pd.to_datetime(idx["date"])
    idx = idx.sort_values("date").reset_index(drop=True)
    st = load_kr().filter(pl.col("yf").is_in(SEMIS)).select("yf", "date", "c").to_pandas()
    st["date"] = pd.to_datetime(st["date"])
    px = st.pivot(index="date", columns="yf", values="c").sort_index()
    px = px.reindex(idx["date"]).ffill()
    df = idx.set_index("date")
    r = px.pct_change().fillna(0.0)
    # 50/50 월말 리밸런싱 바스켓
    ym = px.index.to_period("M")
    w = pd.DataFrame(0.5, index=px.index, columns=px.columns)
    basket = np.empty(len(px))
    cur = np.array([0.5, 0.5])
    for i in range(len(px)):
        ri = r.iloc[i].values
        basket[i] = float(cur @ ri)
        cur = cur * (1 + ri) / max(1 + basket[i], 1e-9)
        if i + 1 < len(px) and ym[i + 1] != ym[i]:
            cur = np.array([0.5, 0.5])
    df["sem"] = basket
    df["k200"] = df["k200_close"].pct_change().fillna(0.0)
    df["kret"] = df["kospi_close"].pct_change()
    df["sma200"] = df["kospi_close"].rolling(200).mean()
    df["hi20"] = df["kospi_close"].rolling(20).max()
    df["bear"] = ((df["kospi_close"] < df["sma200"]) | (df["kospi_close"] <= 0.85 * df["hi20"])).fillna(False)
    df["rebound"] = (df["kret"] >= REBOUND).fillna(False)
    d = df.index
    df["week_end"] = np.r_[(d[1:].isocalendar().week.values != d[:-1].isocalendar().week.values) | (d[1:].year != d[:-1].year), True]
    df["month_end"] = np.r_[d[1:].month != d[:-1].month, True]
    df["month_start"] = np.r_[True, d[1:].month != d[:-1].month]
    return df.reset_index()


# ───────────────────────── 시뮬레이션 ─────────────────────────
def simulate(df: pd.DataFrame, i0: int, i1: int, rule: str, *, cap: float = 0.40, upper: float = 0.45,
             lower: float = 0.30, target: float = 0.40, contrib: float = 0.0, sell_to: float | None = None,
             w_start: float = W0) -> dict:
    """i0 종가에 반도체 w_start / 나머지 1−w_start 로 시작해 i1 종가까지. 순자산 1.0 시작.
    rule: BH | CAP(월말 초과분 매도) | BAND(주말 점검, 반등일 매도, 회복 레짐 되사기) | BAND_NOW(반등일 안 기다림)
    contrib: 매월 첫 거래일에 시작 순자산 × contrib 를 나머지에 적립(비용 0). sell_to: 시작 시점 즉시 반도체를 그 비중까지 매도."""
    sem = df["sem"].values; oth = df["k200"].values
    bear = df["bear"].values; reb = df["rebound"].values
    wend = df["week_end"].values; mend = df["month_end"].values; mstart = df["month_start"].values
    S, R = w_start, 1 - w_start
    cost = 0.0
    if sell_to is not None and S / (S + R) > sell_to:
        amt = S - sell_to * (S + R)
        S -= amt; R += amt * (1 - COST); cost += amt * COST
    nav = [S + R]; wts = [S / (S + R)]
    pending = None      # ('sell', target) / ('buy', target)
    turnover = 0.0; n_sell = 0; n_buy = 0; first_hit = None; contributed = 0.0
    for i in range(i0 + 1, i1 + 1):
        if contrib and mstart[i] and i > i0:
            R += contrib; contributed += contrib
        # 전일 판정에 따른 체결(오늘 종가) — 체결은 수익 반영 후
        S *= 1 + sem[i]; R *= 1 + oth[i]
        tot = S + R; w = S / tot
        if first_hit is None and w >= upper:
            first_hit = i - i0
        if rule == "CAP" and mend[i] and w > cap:
            amt = S - cap * tot
            S -= amt; R += amt * (1 - COST); cost += amt * COST; turnover += amt / tot; n_sell += 1
        elif rule in ("BAND", "BAND_NOW"):
            # 1) 보류 중인 주문 집행 조건
            if pending is not None:
                kind, tgt = pending
                if kind == "sell" and (reb[i] or rule == "BAND_NOW"):
                    if w > tgt:
                        amt = S - tgt * tot
                        S -= amt; R += amt * (1 - COST); cost += amt * COST; turnover += amt / tot; n_sell += 1
                    pending = None
                elif kind == "buy":
                    if w < tgt and not bear[i]:
                        amt = tgt * tot - S
                        R -= amt; S += amt * (1 - COST); cost += amt * COST; turnover += amt / tot; n_buy += 1
                    pending = None
            # 2) 주말 점검 → 다음 거래일부터 집행 대기
            if wend[i] and pending is None:
                w = S / (S + R)
                if w > upper:
                    pending = ("sell", target)
                elif w < lower and not bear[i]:
                    pending = ("buy", target)
        nav.append(S + R); wts.append(S / (S + R))
    nav = np.asarray(nav); wts = np.asarray(wts)
    base = 1.0 + contributed
    # 적립 포함 경로의 MDD: 적립 효과를 빼기 위해 '적립 누적을 더한 기준선' 대비가 아니라 단순 NAV 기준(보수적, 적립이 낙폭을 가림) → 보조로 수익률 가중 MDD도 계산
    out = {"ret": float(nav[-1] / base - 1), "mdd": mdd_of(nav), "turnover": turnover, "cost": cost,
           "n_sell": n_sell, "n_buy": n_buy, "first_hit": first_hit, "w_mean": float(wts.mean()), "w_end": float(wts[-1]),
           "nav": nav, "wts": wts, "contributed": contributed}
    return out


def path_metrics(res: dict, years: float) -> dict:
    nav = res["nav"]
    r = np.diff(nav) / nav[:-1]
    sharpe = float(r.mean() / r.std(ddof=1) * math.sqrt(250)) if r.std(ddof=1) > 0 else None
    return {"cagr": float(nav[-1] ** (1 / years) - 1), "mdd": res["mdd"], "sharpe": sharpe,
            "turnover_yr": res["turnover"] / years, "n_sell": res["n_sell"], "n_buy": res["n_buy"],
            "w_mean": res["w_mean"], "w_min": float(res["wts"].min()), "w_max": float(res["wts"].max())}


def vol_adj(nav: np.ndarray) -> float | None:
    """12개월 윈도 수익/변동성: 월간(21일) 수익의 평균 ÷ 표준편차."""
    m = nav[::21]
    r = np.diff(m) / m[:-1]
    return float(r.mean() / r.std(ddof=1)) if len(r) > 2 and r.std(ddof=1) > 0 else None


# ───────────────────────── 본체 ─────────────────────────
def main() -> None:
    df = load()
    n = len(df)
    starts = [i for i in range(201, n - WIN) if df["month_start"].iloc[i]]
    dates = df["date"].values
    is_mask = np.array([pd.Timestamp(dates[i]) <= IS_END for i in starts])
    years = (pd.Timestamp(dates[-1]) - pd.Timestamp(dates[200])).days / 365.25
    out: dict = {"generated": datetime.now().isoformat(timespec="seconds"),
                 "prereg": {"m": M, "alpha": ALPHA, "window_days": WIN, "is_end": str(IS_END.date()), "cost_oneway": COST,
                            "semis_proxy": "005930+000660 50/50 월말 리밸런싱(가격수익)", "rest_proxy": "KOSPI200 가격지수",
                            "regime": "bear = KOSPI < SMA200 or <= 0.85×20d high close", "rebound": "KOSPI close >= prev +0.5%"},
                 "data": {"start": str(pd.Timestamp(dates[200]).date()), "end": str(pd.Timestamp(dates[-1]).date()),
                          "windows": len(starts), "windows_is": int(is_mask.sum()), "windows_oos": int((~is_mask).sum()),
                          "bear_share": float(df["bear"].iloc[200:].mean())},
                 "results": {}, "grades": {}, "claims": {}}

    # ── 전체 경로(서술) ──
    full = {}
    for name, kw in {"BH": dict(rule="BH"), "CAP40M": dict(rule="CAP", cap=0.40), "BAND": dict(rule="BAND"),
                     "BAND_NOW": dict(rule="BAND_NOW"), "CAP35M": dict(rule="CAP", cap=0.35), "CAP30M": dict(rule="CAP", cap=0.30)}.items():
        full[name] = path_metrics(simulate(df, 200, n - 1, **kw), years)
    out["results"]["full_path"] = full
    semis_only = path_metrics(simulate(df, 200, n - 1, rule="BH", w_start=1.0), years)
    k200_only = path_metrics(simulate(df, 200, n - 1, rule="BH", w_start=0.0), years)
    out["results"]["reference"] = {"semis_100": semis_only, "k200_100": k200_only}

    # ── H1 ──
    runs = {k: [] for k in ("BH", "CAP40M", "BAND", "BAND_NOW")}
    kw1 = {"BH": dict(rule="BH"), "CAP40M": dict(rule="CAP", cap=0.40), "BAND": dict(rule="BAND"), "BAND_NOW": dict(rule="BAND_NOW")}
    for i in starts:
        for k, kw in kw1.items():
            runs[k].append(simulate(df, i, i + WIN, **kw))
    ret = {k: np.array([r["ret"] for r in v]) for k, v in runs.items()}
    mddw = {k: np.array([r["mdd"] for r in v]) for k, v in runs.items()}
    h1 = {"summary": {}, "tests": {}}
    for k, v in runs.items():
        h1["summary"][k] = {"ret12_mean": float(ret[k].mean()), "ret12_med": float(np.median(ret[k])),
                            "mdd_mean": float(mddw[k].mean()), "mdd_p90": float(np.percentile(mddw[k], 10)),
                            "turnover_mean": float(np.mean([r["turnover"] for r in v])),
                            "sells_mean": float(np.mean([r["n_sell"] for r in v])), "buys_mean": float(np.mean([r["n_buy"] for r in v])),
                            "w_mean": float(np.mean([r["w_mean"] for r in v]))}
    for a, b in (("BAND", "CAP40M"), ("BAND", "BH"), ("CAP40M", "BH")):
        c = compare(ret[a] - ret[b], is_mask)
        g, why = grade(c)
        risk = bool(mddw[a].mean() < 1.5 * mddw[b].mean())
        c.update({"grade": g, "why": why, "mdd_diff": float(mddw[a].mean() - mddw[b].mean()), "risk_up": risk})
        h1["tests"][f"{a}-{b}"] = c
        out["grades"][f"H1 {a}−{b}"] = g
    # 보조: 반등일 대기 비용
    c = compare(ret["BAND"] - ret["BAND_NOW"], is_mask)
    h1["tests"]["BAND-BAND_NOW (보조, m 미포함)"] = c
    hits = np.array([r["first_hit"] for r in runs["BH"]], dtype=object)
    hit_mask = np.array([h is not None for h in hits])
    hit_days = np.array([h for h in hits if h is not None], float)
    h1["band_hit"] = {"share_12m": float(hit_mask.mean()), "share_is": float(hit_mask[is_mask].mean()), "share_oos": float(hit_mask[~is_mask].mean()),
                      "days_median": float(np.median(hit_days)) if len(hit_days) else None,
                      "rel_move_needed": float((0.45 / 0.55) / (0.40 / 0.60) - 1)}
    # 전체 경로 주간 발동 횟수(BAND 전체 경로)
    h1["band_full_path_events"] = {"sells": full["BAND"]["n_sell"], "buys": full["BAND"]["n_buy"], "years": years}
    out["results"]["H1"] = h1
    share = h1["band_hit"]["share_12m"]
    out["claims"]["band45_rare"] = {"pb": "45% 발동선은 자주 안 걸린다(나머지 대비 +23%)", "math_rel_move": h1["band_hit"]["rel_move_needed"],
                                    "share_12m_windows_hit": share, "verdict": "틀림(자주 걸림)" if share >= 0.25 else "맞음(드묾)"}

    # ── H2 ──
    h2 = {}
    for c_ in CONTRIB:
        g_runs = [simulate(df, i, i + WIN, rule="BH", contrib=c_) for i in starts]
        s_runs = [simulate(df, i, i + WIN, rule="BH", contrib=c_, sell_to=0.35) for i in starts]
        tw_g = np.array([r["nav"][-1] for r in g_runs]); tw_s = np.array([r["nav"][-1] for r in s_runs])
        d = tw_g / tw_s - 1
        c = compare(d, is_mask)
        mg = np.array([r["mdd"] for r in g_runs]); ms = np.array([r["mdd"] for r in s_runs])
        # 글라이드가 처음 35% 이하로 가는 달
        first35 = []
        for r in g_runs:
            w = r["wts"]
            idx = np.where(w <= 0.35)[0]
            first35.append(int(math.ceil(idx[0] / 21)) if len(idx) else None)
        f = np.array([x for x in first35 if x is not None], float)
        res = {"contrib": c_, "test": c, "tw_glide_mean": float(tw_g.mean()), "tw_sell_mean": float(tw_s.mean()),
               "mdd_glide": {"mean": float(mg.mean()), "p10": float(np.percentile(mg, 10)), "min": float(mg.min())},
               "mdd_sell": {"mean": float(ms.mean()), "p10": float(np.percentile(ms, 10)), "min": float(ms.min())},
               "w_mean_glide": float(np.mean([r["w_mean"] for r in g_runs])), "w_mean_sell": float(np.mean([r["w_mean"] for r in s_runs])),
               "w_end_glide_med": float(np.median([r["w_end"] for r in g_runs])),
               "first35_month": {"reached_12m": float(np.mean([x is not None for x in first35])),
                                 "within_1m": float(np.mean([x is not None and x <= 1 for x in first35])),
                                 "within_2m": float(np.mean([x is not None and x <= 2 for x in first35])),
                                 "median": float(np.median(f)) if len(f) else None, "p90": float(np.percentile(f, 90)) if len(f) else None}}
        if c_ == CONTRIB[0]:
            g, why = grade(c)
            res["test"].update({"grade": g, "why": why, "mdd_diff": float(mg.mean() - ms.mean()), "risk_up": bool(mg.mean() < 1.5 * ms.mean())})
            out["grades"]["H2 GLIDE−SELL35"] = g
            w1 = res["first35_month"]["within_1m"]
            out["claims"]["glide_1m"] = {"pb": "글라이드 패스로 1개월 뒤 ≈35%", "arith_no_move": float(W0 / (1 + c_)),
                                        "within_1m_share": w1, "within_2m_share": res["first35_month"]["within_2m"],
                                        "verdict": "맞음" if w1 >= 0.75 else ("대체로" if w1 >= 0.5 else "틀림")}
        h2[f"c={c_}"] = res
    out["results"]["H2"] = h2

    # ── H3 ──
    bear_starts = [i for i in starts if df["bear"].iloc[i]]
    bmask = np.array([pd.Timestamp(dates[i]) <= IS_END for i in bear_starts])
    caps = [0.30, 0.35, 0.40, 0.45]
    runs3 = {c_: [simulate(df, i, i + WIN, rule="CAP", cap=c_) for i in bear_starts] for c_ in caps}
    h3 = {"n_windows": len(bear_starts), "n_is": int(bmask.sum()), "n_oos": int((~bmask).sum()), "summary": {}, "tests": {}}
    va = {c_: np.array([vol_adj(r["nav"]) if vol_adj(r["nav"]) is not None else np.nan for r in v]) for c_, v in runs3.items()}
    m3 = {c_: np.array([r["mdd"] for r in v]) for c_, v in runs3.items()}
    r3 = {c_: np.array([r["ret"] for r in v]) for c_, v in runs3.items()}
    for c_ in caps:
        h3["summary"][str(c_)] = {"ret12_mean": float(r3[c_].mean()), "voladj_mean": float(np.nanmean(va[c_])), "mdd_mean": float(m3[c_].mean()),
                                  "mdd_p10": float(np.percentile(m3[c_], 10)), "mdd_min": float(m3[c_].min()),
                                  "w_mean": float(np.mean([r["w_mean"] for r in runs3[c_]])), "sells_mean": float(np.mean([r["n_sell"] for r in runs3[c_]]))}
    for c_ in (0.30, 0.35, 0.45):
        c = compare(va[c_] - va[0.40], bmask)
        g, why = grade(c)
        c.update({"grade": g, "why": why, "ret_diff": float(r3[c_].mean() - r3[0.40].mean()), "mdd_diff": float(m3[c_].mean() - m3[0.40].mean()),
                  "risk_up": bool(m3[c_].mean() < 1.5 * m3[0.40].mean())})
        h3["tests"][f"CAP{int(c_*100)}-CAP40"] = c
        out["grades"][f"H3 CAP{int(c_*100)}−CAP40"] = g
    h3["best_voladj"] = str(max(caps, key=lambda c_: np.nanmean(va[c_])))
    h3["min_mdd"] = str(max(caps, key=lambda c_: m3[c_].mean()))
    # −20% 충격: 하락장 윈도 안에서 반도체가 시작 대비 처음 −20% 이하가 된 시점의 손실 차이(35 vs 30)
    shock = []
    for k, i in enumerate(bear_starts):
        sem_idx = np.cumprod(1 + df["sem"].values[i + 1:i + WIN + 1])
        j = np.where(sem_idx <= 0.80)[0]
        if len(j):
            jj = j[0] + 1
            shock.append((runs3[0.35][k]["nav"][jj] - 1) - (runs3[0.30][k]["nav"][jj] - 1))
    h3["shock20_loss_diff_35_minus_30"] = {"n": len(shock), "mean": float(np.mean(shock)) if shock else None,
                                           "median": float(np.median(shock)) if shock else None}
    out["results"]["H3"] = h3
    sd = h3["shock20_loss_diff_35_minus_30"]["mean"]
    md = h3["tests"]["CAP35-CAP40"]["mdd_diff"] - h3["tests"]["CAP30-CAP40"]["mdd_diff"]
    out["claims"]["cap30_vs_35_1pp"] = {"pb": "30 vs 35는 −20% 충격에서 ≈1%p 차이", "shock20_loss_diff": sd, "bear_mdd_diff_35_minus_30": float(md),
                                        "verdict": ("맞음" if sd is not None and 0.005 <= abs(sd) <= 0.015 else "틀림(범위 밖)")}

    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    # 요약
    print(f"윈도 {len(starts)} (IS {is_mask.sum()} / OOS {(~is_mask).sum()}), 하락장 시작 {len(bear_starts)}, 기간 {out['data']['start']}~{out['data']['end']}")
    print("전체 경로:", {k: {m: round(v, 3) if isinstance(v, float) else v for m, v in d.items()} for k, d in full.items()})
    for k, v in h1["tests"].items():
        print("H1", k, {m: round(x, 4) if isinstance(x, float) else x for m, x in v["all"].items()}, v.get("grade"), "mdd_diff", round(v.get("mdd_diff", 0), 4))
    print("H1 band_hit", h1["band_hit"])
    for k, v in h2.items():
        print("H2", k, v["test"]["all"], v["test"].get("grade"), v["first35_month"], "mdd", v["mdd_glide"]["mean"], v["mdd_sell"]["mean"])
    for k, v in h3["tests"].items():
        print("H3", k, v["all"], v["grade"], "ret_diff", round(v["ret_diff"], 4), "mdd_diff", round(v["mdd_diff"], 4))
    print("H3 summary", h3["summary"], h3["best_voladj"], h3["min_mdd"], h3["shock20_loss_diff_35_minus_30"])
    print("claims", json.dumps(out["claims"], ensure_ascii=False))


if __name__ == "__main__":
    main()
