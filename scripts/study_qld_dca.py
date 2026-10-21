"""QLD(나스닥100 2배) 매일 1만원 적립 백테스트 — 연구 전용(실계좌 레버리지·인버스는 2027-04-15까지 금지, 불변 규칙).

입력: data/study/qld_dca_px.csv (scripts/fetch_qld_dca.py, Actions 수집 — 야후 Close/Adj Close + FRED DEXKOUS·DTB3)
출력: reports/studies/2026-10-21_qld_daily_dca.json (+ md 는 사람이 쓴다)

설계(가정은 ASSUME 한 곳에):
- 기초 수익(1배, 배당 포함 총수익): QQQ Adj Close(1999-03-10~) / 이전은 ^NDX 가격 + 배당 0.7%/년 − 보수 0.20%/년.
- QLD: 실 QLD Adj Close(2006-06-21~) / 이전은 합성 r = 2·r_NDX_TR − (rf + spread)·dt/360 − 0.95%/252.
  spread 는 2006-06~2015-12 실 QLD 로 보정(연 누적 차이 0), 2016~ 표본 외로 추적오차 확인.
- SPY: SPY Adj Close(1993-01-29~) / 이전 ^GSPC 가격 + 배당 3.0%/년 − 보수 0.09%/년.
- 원화: 매 미국 거래일 종가에 1만원 → 달러(환율 × (1+환전 스프레드)) → 매수수수료 차감 후 소수점 매수.
  환율 = 야후 KRW=X(2003-12~) 우선, 없으면 FRED DEXKOUS(정오 NY), 결측은 직전값.
- 평가: 보유 주수 × 종가 × 환율(중간값). 최종 평가는 매도수수료·환전 스프레드 차감(세전, 양도세 미반영).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data/study/qld_dca_px.csv"
OUT = ROOT / "reports/studies/2026-10-21_qld_daily_dca.json"

ASSUME = {
    "daily_krw": 10_000,
    "fx_spread": 0.0025,       # 환전 스프레드 편도 0.25% [가정: 증권사 환전 우대 후 수준, 보수적]
    "fee_buy": 0.001,          # 매수 수수료 0.1% [가정: 국내 증권사 미국주식 온라인 수수료 수준]
    "fee_sell": 0.001,         # 매도 수수료 0.1% (최종 평가에만)
    "qld_er": 0.0095,          # QLD 총보수 0.95%/년
    "qqq_er": 0.0020,          # QQQ 총보수 0.20%/년 (합성 구간에만)
    "spy_er": 0.0009,          # SPY 0.0945% ≈ 0.09%/년 (합성 구간에만)
    "ndx_div": 0.007,          # ^NDX 배당 근사 0.7%/년 (1999-03 이전 합성에만)
    "spx_div": 0.030,          # ^GSPC 배당 근사 3.0%/년 (1993-01 이전 합성에만)
    "calib_end": "2015-12-31",  # QLD 합성 spread 보정 구간 끝 (이후는 표본 외)
}


FX_COLS = ["KRW=X_close", "fred_DEXKOUS", "dbn_DEXKOUS", "stooq_USDKRW"]


def load(src: Path = SRC) -> pd.DataFrame:
    df = pd.read_csv(src, parse_dates=["date"]).set_index("date").sort_index()
    return df


def _r(s: pd.Series) -> pd.Series:
    return s / s.shift(1) - 1


def build_returns(df: pd.DataFrame, spread: float | None = None) -> tuple[pd.DataFrame, dict]:
    """미국 거래일(^NDX 또는 ^GSPC 종가가 있는 날) 기준 일간 총수익 + 원/달러. 합성 여부 플래그 포함."""
    a = ASSUME
    cal = df.index[df["^GSPC_close"].notna() | df["^NDX_close"].notna()]
    d = df.loc[cal].copy()
    dt = pd.Series(d.index, index=d.index).diff().dt.days.fillna(1).clip(lower=1)
    rf = (d["fred_DTB3"] if "fred_DTB3" in d else d["^IRX_close"]).ffill().fillna(0) / 100   # 3개월 T-bill(%)
    # 1배 나스닥100 총수익
    ndx_syn = _r(d["^NDX_close"]) + a["ndx_div"] / 252
    qqq_real = _r(d["QQQ_adj"])
    ndx_tr = qqq_real.where(d["QQQ_adj"].notna() & d["QQQ_adj"].shift(1).notna(), ndx_syn + a["qqq_er"] / 252)
    qqq = qqq_real.where(qqq_real.notna(), ndx_syn - a["qqq_er"] / 252)   # 합성 QQQ = NDX + 배당 − 보수 (10/21 검증 정정 ②)
    # 2배
    qld_real = _r(d["QLD_adj"])
    real_mask = d["QLD_adj"].notna() & d["QLD_adj"].shift(1).notna()
    if spread is None:
        spread = calibrate_spread(ndx_tr, rf, dt, qld_real, real_mask)
    qld_syn = 2 * ndx_tr - (rf + spread) * dt / 360 - a["qld_er"] / 252
    qld = qld_real.where(real_mask, qld_syn)
    # S&P500
    spx_syn = _r(d["^GSPC_close"]) + a["spx_div"] / 252 - a["spy_er"] / 252
    spy_real = _r(d["SPY_adj"])
    spy = spy_real.where(d["SPY_adj"].notna() & d["SPY_adj"].shift(1).notna(), spx_syn)
    fx = pd.Series(np.nan, index=d.index)
    fx_src = pd.Series("", index=d.index)
    for c in FX_COLS:   # 우선순위: 야후 → FRED → DBnomics(H.10) → Stooq
        if c in d:
            v = d[c].where(d[c].between(500, 3000))
            take = fx.isna() & v.notna()
            fx, fx_src = fx.where(~take, v), fx_src.where(~take, c)
    fx = fx.ffill()
    out = pd.DataFrame({"QLD": qld, "QQQ": qqq, "SPY": spy, "QLD_syn": qld_syn, "fx": fx, "fx_src": fx_src,
                        "qld_is_syn": ~real_mask, "qqq_is_syn": qqq_real.isna(), "spy_is_syn": spy_real.isna()})
    out = out.iloc[1:].dropna(subset=["QQQ", "SPY", "fx"])
    out = out[out.index >= out["QLD"].first_valid_index()]
    return out, {"spread": spread}


def calibrate_spread(ndx_tr, rf, dt, qld_real, real_mask) -> float:
    """합성 QLD 의 연 누적이 실 QLD 와 같아지는 차입 스프레드(보정 구간만). 이분법."""
    m = real_mask & (qld_real.index <= ASSUME["calib_end"])
    lo, hi = -0.05, 0.10
    real = np.log1p(qld_real[m]).sum()
    for _ in range(60):
        mid = (lo + hi) / 2
        syn = 2 * ndx_tr[m] - (rf[m] + mid) * dt[m] / 360 - ASSUME["qld_er"] / 252
        if np.log1p(syn).sum() > real:
            lo = mid
        else:
            hi = mid
    return round((lo + hi) / 2, 5)


def tracking(rets: pd.DataFrame, df: pd.DataFrame) -> dict:
    """합성 vs 실 QLD 추적오차: 보정 구간(IS)과 그 뒤(OOS) 분리."""
    real = _r(df["QLD_adj"].dropna()).reindex(rets.index)   # 휴장 행 제거 뒤 수익률(10/21 검증 정정 ①)
    m = real.notna() & ~rets["qld_is_syn"]
    res = {}
    for name, sel in (("IS_2006_2015", m & (rets.index <= ASSUME["calib_end"])), ("OOS_2016_", m & (rets.index > ASSUME["calib_end"]))):
        diff = rets["QLD_syn"][sel] - real[sel]
        yrs = sel.sum() / 252
        cs, cr = np.expm1(np.log1p(rets["QLD_syn"][sel]).sum()), np.expm1(np.log1p(real[sel]).sum())
        res[name] = {"days": int(sel.sum()), "te_ann": round(float(diff.std() * np.sqrt(252)), 4),
                     "corr": round(float(np.corrcoef(rets["QLD_syn"][sel], real[sel])[0, 1]), 5),
                     "cagr_syn": round(float((1 + cs) ** (1 / yrs) - 1), 4), "cagr_real": round(float((1 + cr) ** (1 / yrs) - 1), 4)}
    return res


def xirr(dates: np.ndarray, cfs: np.ndarray) -> float:
    """머니웨이티드 수익률(연). cfs: 납입 음수, 마지막 평가 양수. 이분법."""
    t = (dates - dates[0]).astype("timedelta64[D]").astype(float) / 365.25
    def npv(r):
        return float(np.sum(cfs / (1 + r) ** t))
    lo, hi = -0.99, 5.0
    if npv(lo) * npv(hi) > 0:
        return float("nan")
    for _ in range(100):
        mid = (lo + hi) / 2
        if npv(lo) * npv(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def dca(rets: pd.DataFrame, asset: str, start, end=None, whole_shares: float = 0.0, usd: bool = False) -> dict:
    """start~end 매 거래일 종가 1만원 적립. 가격은 총수익 지수(시작일 100)로 — 소수점 매수면 결과가 같다.
    whole_shares: >0 이면 정수주만 매수(남는 달러는 무이자 현금). 값 = 마지막 날 1주 가격(USD) — 총수익 지수를 그 가격에 맞춘 근사.
    usd: 환율 고정(첫날) → 환율 효과 분리용."""
    a = ASSUME
    r = rets.loc[start:end]
    if len(r) < 20:
        return {}
    px = (1 + r[asset]).cumprod().to_numpy() * 100   # 총수익 지수(USD)
    fx = r["fx"].to_numpy() if not usd else np.full(len(r), r["fx"].iloc[0])
    if whole_shares:
        px = px / px[-1] * whole_shares
    usd_in = a["daily_krw"] / (fx * (1 + a["fx_spread"])) * (1 - a["fee_buy"])
    if not whole_shares:
        sh = np.cumsum(usd_in / px)
        cash = np.zeros(len(r))
    else:
        sh, cash, s, c = np.zeros(len(r)), np.zeros(len(r)), 0.0, 0.0
        for i in range(len(r)):
            c += usd_in[i]
            k = np.floor(c / px[i])
            s += k
            c -= k * px[i]
            sh[i], cash[i] = s, c
    paid = a["daily_krw"] * np.arange(1, len(r) + 1)
    val = (sh * px + cash) * fx                         # 중간 환율 평가
    final = (sh[-1] * px[-1] * (1 - a["fee_sell"]) + cash[-1]) * fx[-1] / (1 + a["fx_spread"])
    under = val < paid
    longest, cur = 0, 0
    for u in under:
        cur = cur + 1 if u else 0
        longest = max(longest, cur)
    dates = r.index.to_numpy()
    cfs = np.full(len(r) + 1, -float(a["daily_krw"]))
    cfs[-1] = final
    irr = xirr(np.append(dates, dates[-1]), cfs)
    vmax = np.maximum.accumulate(val)
    return {"start": str(r.index[0].date()), "end": str(r.index[-1].date()), "days": len(r),
            "paid": float(paid[-1]), "final": round(float(final)), "moic": round(float(final / paid[-1]), 3),
            "irr": round(irr, 4), "loss_vs_paid_min": round(float((val / paid - 1).min()), 4),
            "val_mdd": round(float((val / vmax - 1).min()), 4),
            "underwater_max_yrs": round(longest / 252, 2), "underwater_share": round(float(under.mean()), 3),
            "syn_share": round(float(r[f"{asset.lower()}_is_syn"].mean()) if f"{asset.lower()}_is_syn" in r else 0.0, 3)}




def lump(rets: pd.DataFrame, asset: str, start, end, total_krw: float) -> dict:
    """같은 총액을 첫날 한 번에. 비용 동일 가정."""
    a = ASSUME
    r = rets.loc[start:end]
    g = float(np.prod(1 + r[asset].to_numpy()))
    fx0, fx1 = r["fx"].iloc[0], r["fx"].iloc[-1]
    final = total_krw / (fx0 * (1 + a["fx_spread"])) * (1 - a["fee_buy"]) * g * (1 - a["fee_sell"]) * fx1 / (1 + a["fx_spread"])
    yrs = (r.index[-1] - r.index[0]).days / 365.25
    return {"final": round(final), "moic": round(final / total_krw, 3), "cagr": round((final / total_krw) ** (1 / yrs) - 1, 4)}


def asset_mdd(rets: pd.DataFrame, asset: str, krw: bool = True) -> dict:
    lv = (1 + rets[asset]).cumprod() * (rets["fx"] / rets["fx"].iloc[0] if krw else 1)
    dd = lv / lv.cummax() - 1
    trough = dd.idxmin()
    peak = lv.loc[:trough].idxmax()
    rec = lv.loc[trough:][lv.loc[trough:] >= lv.loc[peak]]
    return {"mdd": round(float(dd.min()), 4), "peak": str(peak.date()), "trough": str(trough.date()),
            "recovered": str(rec.index[0].date()) if len(rec) else None}


def pct(xs, q):
    xs = [x for x in xs if x == x]
    return round(float(np.percentile(xs, q)), 4) if xs else None


def rolling(rets: pd.DataFrame, years: int) -> dict:
    """월초 시작 years 년 적립 — IRR·원금 대비 최대 손실·종료 시 손실 확률 분포. 겹침 창이라 독립 표본 ≈ 기간/years."""
    starts = rets.resample("MS").first().index
    last = rets.index[-1]
    res = {}
    for a in ("QLD", "QQQ", "SPY"):
        rows = []
        for s in starts:
            e = s + pd.DateOffset(years=years) - pd.DateOffset(days=1)
            if e > last:
                break
            x = dca(rets, a, s, e)
            if x:
                rows.append(x)
        irr = [x["irr"] for x in rows]
        res[a] = {"n_windows": len(rows), "n_indep_approx": round(len(rows) / (12 * years), 1),
                  "irr_min": pct(irr, 0), "irr_p10": pct(irr, 10), "irr_med": pct(irr, 50), "irr_p90": pct(irr, 90),
                  "p_loss_end": round(sum(1 for x in rows if x["moic"] < 1) / len(rows), 3) if rows else None,
                  "loss_vs_paid_med": pct([x["loss_vs_paid_min"] for x in rows], 50),
                  "loss_vs_paid_worst": pct([x["loss_vs_paid_min"] for x in rows], 0),
                  "worst_start": min(rows, key=lambda x: x["irr"])["start"] if rows else None}
    return res


def run(src: Path = SRC) -> dict:
    df = load(src)
    rets, cal = build_returns(df)
    first, last = rets.index[0], rets.index[-1]
    out = {"meta": {"asof": str(last.date()), "first": str(first.date()), "assume": ASSUME, "spread_calibrated": cal["spread"],
                    "qld_real_from": str(df["QLD_adj"].first_valid_index().date()),
                    "qqq_real_from": str(df["QQQ_adj"].first_valid_index().date()),
                    "spy_real_from": str(df["SPY_adj"].first_valid_index().date()),
                    "fx_yahoo_from": str(df["KRW=X_close"].first_valid_index().date()) if "KRW=X_close" in df else None,
                    "note": "연구 전용. 실계좌 레버리지·인버스 2027-04-15까지 금지(불변 규칙). 가상 금액(매일 1만원), 실보유와 무관."},
           "tracking": tracking(rets, df)}
    out["asset_mdd_krw"] = {a: asset_mdd(rets, a) for a in ("QLD", "QQQ", "SPY")}
    out["asset_mdd_usd"] = {a: asset_mdd(rets, a, krw=False) for a in ("QLD", "QQQ", "SPY")}
    # 전 기간 + 실데이터 구간
    out["full"] = {a: dca(rets, a, first, None) for a in ("QLD", "QQQ", "SPY")}
    out["real_only"] = {a: dca(rets, a, out["meta"]["qld_real_from"], None) for a in ("QLD", "QQQ", "SPY")}
    out["real_only_usd"] = {a: dca(rets, a, out["meta"]["qld_real_from"], None, usd=True) for a in ("QLD", "QQQ", "SPY")}
    last_px = {a: float(df[f"{a}_close"].dropna().iloc[-1]) for a in ("QLD", "QQQ", "SPY")}
    out["meta"]["last_close_usd"] = last_px
    out["meta"]["fx_src_share"] = {k: round(float(v), 3) for k, v in rets["fx_src"].value_counts(normalize=True).items()}
    # 정수주 민감도: 최근 5년(2021-11~)을 실제 주가 수준으로 — 하루 1만원(≈7달러)이 1주보다 작아 며칠씩 모았다 산다
    out["whole_vs_frac_5y"] = {a: {"frac": dca(rets, a, "2021-11-01", None), "whole": dca(rets, a, "2021-11-01", None, whole_shares=last_px[a])}
                               for a in ("QLD", "QQQ", "SPY")}
    # 매년 1월 시작 → 현재까지
    yearly = []
    for y in range(first.year + (first.month > 1), last.year):
        row = {"year": y}
        for a in ("QLD", "QQQ", "SPY"):
            x = dca(rets, a, f"{y}-01-01", None)
            row[a] = {k: x[k] for k in ("irr", "moic", "loss_vs_paid_min", "underwater_max_yrs", "syn_share")}
        yearly.append(row)
    out["yearly_to_now"] = yearly
    # 고정 10년 적립 (매년 시작) — 기간을 맞춰 비교
    out["rolling5"] = rolling(rets, 5)
    out["rolling10"] = rolling(rets, 10)
    # 최악 진입 시나리오 (고점 직전 시작) — 5년·현재까지
    worst = {}
    for tag, s in (("2000-03 닷컴 고점", "2000-03-01"), ("2007-10 금융위기 전", "2007-10-01"), ("2021-11 2022 하락 전", "2021-11-01")):
        worst[tag] = {}
        for a in ("QLD", "QQQ", "SPY"):
            x5 = dca(rets, a, s, pd.Timestamp(s) + pd.DateOffset(years=5))
            xn = dca(rets, a, s, None)
            worst[tag][a] = {"5y": {k: x5[k] for k in ("irr", "moic", "loss_vs_paid_min", "underwater_max_yrs")},
                             "to_now": {k: xn[k] for k in ("irr", "moic", "loss_vs_paid_min", "underwater_max_yrs", "end")}}
    out["worst_entry"] = worst
    # 적립 vs 일시 (10년, 매년 1월 시작)
    lvd = []
    for y in range(first.year + (first.month > 1), last.year - 9):
        s, e = f"{y}-01-01", f"{y + 9}-12-31"
        row = {"year": y}
        for a in ("QLD", "QQQ", "SPY"):
            d = dca(rets, a, s, e)
            ls = lump(rets, a, s, e, d["paid"])
            row[a] = {"dca_moic": d["moic"], "lump_moic": ls["moic"], "dca_irr": d["irr"], "lump_cagr": ls["cagr"]}
        lvd.append(row)
    out["lump_vs_dca_10y"] = lvd
    out["lump_win_share_10y"] = {a: round(sum(1 for r in lvd if r[a]["lump_moic"] > r[a]["dca_moic"]) / len(lvd), 3) for a in ("QLD", "QQQ", "SPY")}
    return out


def main() -> int:
    out = run(Path(sys.argv[1]) if len(sys.argv) > 1 else SRC)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("meta", "tracking", "full", "real_only")}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
