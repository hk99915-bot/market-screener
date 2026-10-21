"""라오어 무한매수법(V4.0 일반+리버스 / V3.0 / V2.2) SOXL·TQQQ 백테스트 — 연구 전용(실계좌 레버리지·인버스 2027-04-15까지 금지, 불변).

입력: data/study/laor_ib_px.csv (scripts/fetch_laor_ib.py, Actions laor_ib_data.yml — 야후 High/Close/Adj Close + Fed H.10 원/달러)
출력: reports/studies/2026-10-21_laor_infinite_buy.json (+ md 는 사람이 쓴다)

가격 경로(종목별, 총수익 기준 '수정' 가격):
- 실 ETF 구간: Adj Close, 고가 = High × Adj/Close. TQQQ 2010-02-11~, SOXL 2010-03-11~.
- 이전 합성: r = 3·(r_idx + div/252) − 2·(rf + spread)·dt/360 − ER/252 (idx = ^NDX / ^SOX, rf = ^IRX).
  spread 는 실 ETF 2010~2017 로 보정(연 누적 차이 0), 2018~ 표본 외 추적오차 보고. 합성 고가 = 전일 종가 × (1 + 3·(idx고가/idx전일종가 − 1)).
체결 근사(가정): LOC 매수 = 종가 ≤ 주문가면 종가 체결 / LOC 매도 = 종가 ≥ 주문가면 종가 / 지정가 매도 = 고가 ≥ 주문가면 주문가 /
  MOC = 종가. 소수점 수량(가격 수준과 무관하게 하기 위함). 매수·매도 수수료 0.1% 편도. 놀고 있는 현금 이자 0.
규칙은 RULES 한 곳에, 출처·미확인은 md §0.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data/study/laor_ib_px.csv"
OUT = ROOT / "reports/studies/2026-10-21_laor_infinite_buy.json"

ASSUME = {
    "fee": 0.001,               # 매수·매도 수수료 0.1% 편도 [가정: QLD 연구와 동일]
    "fx_spread": 0.0025,        # 환전 스프레드 편도 0.25% [가정: 우대 후]
    "seed_krw": 40_000_000,     # 1사이클 원금(가상) 4,000만원
    "tax_rate": 0.22,           # 해외주식 양도세 22%(지방세 포함)
    "tax_deduct_krw": 2_500_000,  # 연 기본공제 250만원
    "er": {"TQQQ": 0.0084, "SOXL": 0.0075},   # 총보수 [가정: 2026 운용사 공시 수준, 합성 구간에만]
    "div": {"TQQQ": 0.007, "SOXL": 0.010},    # 기초지수 배당 근사 [가정, 합성 구간에만]
    "calib_end": "2026-12-31",  # 합성 spread 보정 = 실 ETF 전 구간(2010~). 2010~2017 보정 → 2018~ 표본 외 진단은 tracking()
    "diag_split": "2017-12-31",
    "qqq_er": 0.0020, "ndx_div": 0.007,
}

IDX = {"TQQQ": "^NDX", "SOXL": "^SOX"}

# 규칙 변형. base = 별% 시작값(=목표 수익률), star(T) = base − (2·base/N)·T.
RULES = {
    "V4.0_20": {"N": 20, "star": "v3", "unit": "cash", "exhaust": "reverse"},
    "V4.0_40": {"N": 40, "star": "v3", "unit": "cash", "exhaust": "reverse"},
    "V3.0_20": {"N": 20, "star": "v3", "unit": "cash", "exhaust": "quarter_moc"},
    "V2.2_40": {"N": 40, "star": "v22", "unit": "seed", "exhaust": "quarter_moc"},
}
BASE = {"TQQQ": 15.0, "SOXL": 20.0}


def load(src: Path = SRC) -> pd.DataFrame:
    return pd.read_csv(src, parse_dates=["date"]).set_index("date").sort_index()


def _r(s: pd.Series) -> pd.Series:
    return s / s.shift(1) - 1


def build_path(df: pd.DataFrame, tk: str, spread: float | None = None, calib_end: str | None = None) -> tuple[pd.DataFrame, dict]:
    """종목 tk 의 일간 (수정)종가·고가 경로. 실 ETF 앞은 합성. 반환 열: close, high, is_syn, fx."""
    a = ASSUME
    ix = IDX[tk]
    cal = df.index[df[f"{ix}_close"].notna() | df[f"{tk}_adj"].notna()]
    d = df.loc[cal].copy()
    dt = pd.Series(d.index, index=d.index).diff().dt.days.fillna(1).clip(lower=1)
    rf = d["^IRX_close"].ffill().fillna(0) / 100
    r_idx = _r(d[f"{ix}_close"]) + a["div"][tk] / 252
    h_idx = d[f"{ix}_high"] / d[f"{ix}_close"].shift(1) - 1
    real_c = _r(d[f"{tk}_adj"])
    real_mask = d[f"{tk}_adj"].notna() & d[f"{tk}_adj"].shift(1).notna()
    adj_high = d[f"{tk}_high"] * d[f"{tk}_adj"] / d[f"{tk}_close"]
    real_h = adj_high / d[f"{tk}_adj"].shift(1) - 1
    if spread is None:
        spread = calibrate(r_idx, rf, dt, real_c, real_mask, tk, calib_end)
    syn = 3 * r_idx - 2 * (rf + spread) * dt / 360 - a["er"][tk] / 252
    ret = real_c.where(real_mask, syn)
    hret = real_h.where(real_mask & real_h.notna(), 3 * h_idx)
    out = pd.DataFrame({"ret": ret, "hret": hret, "syn_ret": syn, "is_syn": ~real_mask}).iloc[1:].dropna(subset=["ret"])
    out["close"] = 100 * np.cumprod(1 + out["ret"].values)
    prev = out["close"].shift(1).fillna(100)
    out["high"] = np.maximum(prev * (1 + out["hret"].fillna(out["ret"])), out["close"])
    out["fx"] = fx_series(df).reindex(out.index).ffill().bfill()
    return out, {"spread": spread, "first": str(out.index[0].date()),
                 "real_first": str(out.index[~out["is_syn"]][0].date())}


def fx_series(df: pd.DataFrame) -> pd.Series:
    fx = pd.Series(np.nan, index=df.index)
    for c in ("KRW=X_close", "dbn_DEXKOUS"):
        if c in df:
            v = df[c].where(df[c].between(500, 3000))
            fx = fx.where(fx.notna(), v)
    return fx.ffill()


def calibrate(r_idx, rf, dt, real, mask, tk, end: str | None = None) -> float:
    m = mask & (real.index <= (end or ASSUME["calib_end"]))
    tgt = np.log1p(real[m]).sum()
    lo, hi = -0.05, 0.10
    for _ in range(60):
        mid = (lo + hi) / 2
        syn = 3 * r_idx[m] - 2 * (rf[m] + mid) * dt[m] / 360 - ASSUME["er"][tk] / 252
        if np.log1p(syn).sum() > tgt:
            lo = mid
        else:
            hi = mid
    return round((lo + hi) / 2, 5)


def tracking(path: pd.DataFrame, df: pd.DataFrame, tk: str) -> dict:
    """합성 vs 실 ETF. ① 전 구간 보정 spread 로 두 하위 구간 ② 2010~2017 만으로 보정했을 때 2018~ 표본 외 CAGR 차(진단)."""
    real = _r(df[f"{tk}_adj"]).reindex(path.index)
    m = real.notna() & ~path["is_syn"]
    res = {}
    sp_is = build_path(df, tk, spread=None, calib_end=ASSUME["diag_split"])[1]["spread"]
    p_is = build_path(df, tk, spread=sp_is)[0]
    sel = m & (path.index > ASSUME["diag_split"])
    yrs = sel.sum() / 252
    res["diag_fit_2010_2017"] = {"spread": sp_is,
                                 "oos_cagr_syn": round(float(np.expm1(np.log1p(p_is["syn_ret"][sel]).sum() / yrs)), 4),
                                 "oos_cagr_real": round(float(np.expm1(np.log1p(real[sel]).sum() / yrs)), 4)}
    for name, sel in (("full_fit_2010_2017", m & (path.index <= ASSUME["diag_split"])), ("full_fit_2018_", m & (path.index > ASSUME["diag_split"]))):
        yrs = sel.sum() / 252
        cs, cr = np.expm1(np.log1p(path["syn_ret"][sel]).sum()), np.expm1(np.log1p(real[sel]).sum())
        res[name] = {"days": int(sel.sum()), "te_ann": round(float((path["syn_ret"][sel] - real[sel]).std() * np.sqrt(252)), 4),
                     "corr": round(float(np.corrcoef(path["syn_ret"][sel], real[sel])[0, 1]), 4),
                     "cagr_syn": round(float((1 + cs) ** (1 / yrs) - 1), 4), "cagr_real": round(float((1 + cr) ** (1 / yrs) - 1), 4)}
    return res


# ---------------------------------------------------------------- 규칙 엔진
@dataclass
class Pos:
    cash: float
    seed: float
    qty: float = 0.0
    avg: float = 0.0
    T: float = 0.0
    mode: str = "normal"     # normal / reverse
    rev_first: bool = False
    rev_entries: int = 0
    rev_pnl: float = 0.0
    qstop: int = 0
    qstop_pnl: float = 0.0
    events: list = field(default_factory=list)


def star_pct(rule: dict, base: float, T: float) -> float:
    if rule["star"] == "v22":
        return 10.0 - T / 2
    return base - (2 * base / rule["N"]) * T


def _buy(p: Pos, amt: float, px: float, fee: float) -> float:
    amt = min(amt, p.cash)
    if amt <= 1e-12:
        return 0.0
    q = amt / (px * (1 + fee))
    p.avg = (p.avg * p.qty + q * px) / (p.qty + q)   # 평단은 체결가 기준(수수료 별도) — 증권사 표시 평단 관행
    p.qty += q
    p.cash -= amt
    return q


def _sell(p: Pos, q: float, px: float, fee: float) -> float:
    q = min(q, p.qty)
    p.qty -= q
    p.cash += q * px * (1 - fee)
    pnl = q * (px * (1 - fee) - p.avg)
    if p.qty < 1e-12:
        p.qty = 0.0
    return pnl


def step(p: Pos, rule: dict, base: float, prev_close: float, close: float, high: float, last5: float, fee: float) -> str | None:
    """하루. 주문은 전날까지의 상태로 정해지고 오늘 고가·종가로 체결. 반환: 'end'(사이클 종료) 또는 None."""
    N = rule["N"]
    if p.qty <= 0:                                   # 첫 매수: 전일 종가 +base% LOC = 사실상 종가 매수
        if close <= prev_close * (1 + base / 100):
            _buy(p, p.cash / N if rule["unit"] == "cash" else p.seed / N, close, fee)
            p.T = 1.0
        return None
    if p.mode == "reverse":
        k = N / 2                                    # 20분할 10등분 / 40분할 20등분
        if p.rev_first:                              # 리버스 첫날: MOC 무조건 매도
            p.rev_pnl += _sell(p, p.qty / k, close, fee)
            p.T *= (1 - 1 / k)
            p.rev_first = False
        else:
            if close >= last5:
                p.rev_pnl += _sell(p, p.qty / k, close, fee)
                p.T *= (1 - 1 / k)
            elif close <= last5 - 0.01 * last5 / 100:
                amt = p.cash / 4
                if amt > 0:
                    _buy(p, amt, close, fee)
                    p.T += (N - p.T) / 4
        if close > p.avg * (1 - base / 100):         # 종가 > 평단 −base% → 다음날부터 일반모드
            p.mode = "normal"
        return "end" if p.qty <= 0 else None
    # 일반모드
    sp = star_pct(rule, base, p.T)
    star = p.avg * (1 + sp / 100)
    tgt_pct = 10.0 if rule["star"] == "v22" else base
    tgt = p.avg * (1 + tgt_pct / 100)
    q4 = p.qty / 4
    q_rest = p.qty - q4
    left = N - p.T
    unit = (p.cash / left if left > 0 else 0.0) if rule["unit"] == "cash" else p.seed / N
    avg0 = p.avg
    # 매도: 지정가(장중 고가) → LOC 쿼터(종가)
    sold_tgt = high >= tgt
    if sold_tgt:
        _sell(p, q_rest, tgt, fee)
        p.T *= 0.25
    if close >= star:
        _sell(p, q4, close, fee)
        p.T *= 0.75
    if p.qty <= 0:
        return "end"
    if sold_tgt:          # 목표가 체결된 날은 매수 주문 무시(가정: 같은 날 급등 후 평단 아래 마감은 드묾)
        return None
    # 매수
    star_buy = star - 0.01 * star / 100              # 별지점 −0.01 (가격 수준 무관하게 0.01% 로 근사)
    if p.T < N / 2:
        if close <= avg0:
            _buy(p, unit / 2, close, fee)
            p.T += 0.5
        if close <= star_buy:
            _buy(p, unit / 2, close, fee)
            p.T += 0.5
    else:
        if close <= star_buy:
            _buy(p, unit, close, fee)
            p.T += 1.0
    # 소진
    if p.T > N - 1 and p.mode == "normal":
        if rule["exhaust"] == "reverse":
            p.mode, p.rev_first = "reverse", True
            p.rev_entries += 1
        else:                                        # 쿼터손절: 다음 종가에 1/4 MOC → 아래 플래그로 처리
            p.mode, p.rev_first = "qstop", True
            p.qstop += 1
    return None


def step_qstop(p: Pos, close: float, fee: float) -> None:
    p.qstop_pnl += _sell(p, p.qty / 4, close, fee)
    p.T *= 0.75
    p.mode = "normal"


def run_strategy(path: pd.DataFrame, tk: str, rule_name: str, start=None, end=None, compound: bool = False) -> dict:
    """start 부터 end 까지 연속 운용. 사이클마다 원금 고정(seed=1 USD 상대값) 또는 복리(compound)."""
    rule, base, fee = RULES[rule_name], BASE[tk], ASSUME["fee"]
    px = path.loc[start:end] if start or end else path
    if start is not None:
        prev_ix = path.index.get_indexer([px.index[0]])[0] - 1
        prev_close0 = path["close"].iloc[prev_ix] if prev_ix >= 0 else px["close"].iloc[0]
    else:
        prev_close0 = px["close"].iloc[0]
    closes, highs, fxs = px["close"].values, px["high"].values, px["fx"].values
    dates = px.index
    l5 = path["close"].rolling(5, min_periods=1).mean().shift(1).reindex(dates).values   # 직전 5거래일 종가 평균
    p = Pos(cash=1.0, seed=1.0)
    cycles, cur = [], None
    eq_ratio_min = []
    daily_eq = np.empty(len(px))
    cash_share = np.empty(len(px))
    bank = 0.0                                       # 원금 고정: 사이클 끝 이익/손실 누적(사이클 밖)
    for i in range(len(px)):
        c, h = closes[i], highs[i]
        pc = closes[i - 1] if i else prev_close0
        last5 = l5[i] if np.isfinite(l5[i]) else pc
        if cur is None:
            cur = {"start": str(dates[i].date()), "i0": i, "seed": p.seed, "fx0": fxs[i], "min_eq": 1.0, "rev": 0, "qstop": 0,
                   "rev_pnl": 0.0, "qstop_pnl": 0.0, "maxT": 0.0}
            r0, q0 = p.rev_entries, p.qstop
            rp0, qp0 = p.rev_pnl, p.qstop_pnl
        if p.mode == "qstop":
            step_qstop(p, c, fee)
            res = "end" if p.qty <= 0 else None
        else:
            res = step(p, rule, base, pc, c, h, last5, fee)
        eq = p.cash + p.qty * c * (1 - fee)
        cur["min_eq"] = min(cur["min_eq"], eq / p.seed)
        cur["maxT"] = max(cur["maxT"], p.T)
        daily_eq[i] = bank + eq
        cash_share[i] = p.cash / eq if eq > 0 else 1.0
        if res == "end":
            cur.update({"end": str(dates[i].date()), "days": int((dates[i] - dates[cur["i0"]]).days), "ret": p.cash / p.seed - 1,
                        "fx1": fxs[i], "rev": p.rev_entries - r0, "qstop": p.qstop - q0,
                        "rev_pnl": (p.rev_pnl - rp0) / p.seed, "qstop_pnl": (p.qstop_pnl - qp0) / p.seed,
                        "syn": bool(px["is_syn"].iloc[cur["i0"]:i + 1].mean() > 0.5)})
            cycles.append(cur)
            cur = None
            if compound:
                p = Pos(cash=p.cash, seed=p.cash, rev_entries=p.rev_entries, qstop=p.qstop, rev_pnl=p.rev_pnl, qstop_pnl=p.qstop_pnl)
            else:
                bank += p.cash - p.seed
                p = Pos(cash=1.0, seed=1.0, rev_entries=p.rev_entries, qstop=p.qstop, rev_pnl=p.rev_pnl, qstop_pnl=p.qstop_pnl)
    open_c = None
    if cur is not None:
        eq = p.cash + p.qty * closes[-1] * (1 - fee)
        open_c = dict(cur, end=None, days=int((dates[-1] - dates[cur["i0"]]).days), ret=eq / p.seed - 1, fx1=fxs[-1],
                      rev=p.rev_entries - r0, qstop=p.qstop - q0, T=round(p.T, 2), mode=p.mode,
                      rev_pnl=(p.rev_pnl - rp0) / p.seed, qstop_pnl=(p.qstop_pnl - qp0) / p.seed)
    return {"cycles": cycles, "open": open_c, "dates": dates, "eq": daily_eq, "fx": fxs, "final_pos": p,
            "cash_share_mean": float(cash_share.mean())}


# ---------------------------------------------------------------- 요약
def xirr(dates, cfs) -> float:
    t = (np.asarray(dates, dtype="datetime64[D]") - np.datetime64(dates[0], "D")).astype(float) / 365.25
    cfs = np.asarray(cfs, float)
    def npv(r):
        return float(np.sum(cfs / (1 + r) ** t))
    lo, hi = -0.99, 10.0
    if npv(lo) * npv(hi) > 0:
        return float("nan")
    for _ in range(120):
        mid = (lo + hi) / 2
        if npv(lo) * npv(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def krw_flows(res: dict, tax: bool = False) -> dict:
    """원화·원금 고정: 사이클마다 4,000만원 환전 투입 → 끝에 원화 환전 회수. 열린 사이클은 마지막 날 평가(매도비용 차감).
    tax=True: 연도별 실현 원화 손익 합(사이클 종료 연도 귀속)에서 250만원 공제 후 22%, 그 해 말 납부. 열린 사이클은 마지막 날 매도로 간주."""
    a, S = ASSUME, ASSUME["seed_krw"]
    dts, cfs, gains = [], [], {}
    rows = list(res["cycles"]) + ([res["open"]] if res["open"] else [])
    for k, c in enumerate(rows):
        usd = S / (c["fx0"] * (1 + a["fx_spread"]))
        back = usd * (1 + c["ret"]) * c["fx1"] * (1 - a["fx_spread"])
        end = c["end"] or str(pd.Timestamp(res["dates"][-1]).date())
        dts += [c["start"], end]
        cfs += [-S, back]
        y = end[:4]
        gains[y] = gains.get(y, 0.0) + back - S
    if tax:
        for y, g in gains.items():
            t = max(0.0, g - a["tax_deduct_krw"]) * a["tax_rate"]
            if t > 0:
                dts.append(min(f"{y}-12-31", str(pd.Timestamp(res["dates"][-1]).date())))
                cfs.append(-t)
    order = np.argsort(np.array(dts, dtype="datetime64[D]"), kind="stable")
    d = np.array(dts, dtype="datetime64[D]")[order]
    f = np.array(cfs)[order]
    return {"irr": xirr(d, f), "profit_krw": float(sum(gains.values())), "years_active": None}


def summarize(res: dict, path: pd.DataFrame, tk: str) -> dict:
    cyc = res["cycles"]
    rets = np.array([c["ret"] for c in cyc]) if cyc else np.array([])
    days = np.array([c["days"] for c in cyc]) if cyc else np.array([])
    ann = np.array([(1 + c["ret"]) ** (365.25 / max(c["days"], 1)) - 1 for c in cyc]) if cyc else np.array([])
    mins = [c["min_eq"] - 1 for c in cyc] + ([res["open"]["min_eq"] - 1] if res["open"] else [])
    worst = min(cyc + ([res["open"]] if res["open"] else []), key=lambda c: c["min_eq"]) if (cyc or res["open"]) else None
    longest = max(cyc + ([res["open"]] if res["open"] else []), key=lambda c: c["days"]) if (cyc or res["open"]) else None
    # USD 원금 고정 IRR (seed 1 상대값)
    dts, cfs = [], []
    for c in cyc:
        dts += [c["start"], c["end"]]
        cfs += [-1.0, 1 + c["ret"]]
    if res["open"]:
        dts += [res["open"]["start"], str(pd.Timestamp(res["dates"][-1]).date())]
        cfs += [-1.0, 1 + res["open"]["ret"]]
    usd_irr = xirr(np.array(dts, dtype="datetime64[D]"), np.array(cfs)) if dts else float("nan")
    rev = [c for c in cyc + ([res["open"]] if res["open"] else []) if c["rev"] or c["qstop"]]
    k = krw_flows(res)
    kt = krw_flows(res, tax=True)
    yrs = (res["dates"][-1] - res["dates"][0]).days / 365.25
    return {
        "start": str(res["dates"][0].date()), "end": str(res["dates"][-1].date()), "years": round(yrs, 2),
        "n_cycles": len(cyc), "open_cycle": _brief(res["open"]) and dict(_brief(res["open"]), T=res["open"]["T"], mode=res["open"]["mode"]),
        "cycle_ret": {"min": _q(rets, 0), "p10": _q(rets, 10), "med": _q(rets, 50), "p90": _q(rets, 90), "max": _q(rets, 100)},
        "cycle_days": {"min": _q(days, 0), "p10": _q(days, 10), "med": _q(days, 50), "p90": _q(days, 90), "max": _q(days, 100)},
        "cycle_ann_med": _q(ann, 50),
        "usd_irr_fixed_seed": round(usd_irr, 4),
        "krw_irr_fixed_seed": round(k["irr"], 4), "krw_irr_fixed_seed_after_tax": round(kt["irr"], 4),
        "max_eval_loss_vs_seed": round(min(mins), 4) if mins else None,
        "worst_cycle": _brief(worst), "longest_cycle": _brief(longest),
        "exhaust_events": int(sum(c["rev"] + c["qstop"] for c in cyc + ([res["open"]] if res["open"] else []))),
        "exhaust_cycles": len(rev),
        "exhaust_realized_loss_vs_seed": round(float(sum(c["rev_pnl"] + c["qstop_pnl"] for c in rev)), 4),
        "exhaust_cycles_ret": [round(c["ret"], 4) for c in rev],
        "syn_cycles": int(sum(c["syn"] for c in cyc)),
        "loss_cycles": int((rets < 0).sum()) if len(rets) else 0,
        "cash_share_mean": round(res["cash_share_mean"], 3),
        "sum_profit_seeds": round(float(rets[rets > 0].sum()), 3) if len(rets) else 0.0,      # 이익 사이클 합(원금 1회분 단위)
        "sum_loss_refill_seeds": round(float(-rets[rets < 0].sum()), 3) if len(rets) else 0.0,  # 원금 고정을 위해 다시 채운 손실 합   # 놀고 있는 현금 비중(이자 0 가정의 크기)
    }


def _brief(c):
    if c is None:
        return None
    return {"start": c["start"], "end": c["end"], "days": c["days"], "ret": round(c["ret"], 4), "min_eq": round(c["min_eq"] - 1, 4),
            "exhaust": int(c["rev"] + c["qstop"])}


def _q(x, q):
    return round(float(np.percentile(x, q)), 4) if len(x) else None


def compound(path: pd.DataFrame, tk: str, rn: str, start=None, end=None) -> dict:
    """복리판: 사이클 끝 현금 전부를 다음 사이클 원금으로(인출·보충 없음) → 단순 보유 CAGR 과 같은 잣대(시간가중)."""
    cr = run_strategy(path, tk, rn, start=start, end=end, compound=True)
    eq = cr["eq"]
    yrs = (cr["dates"][-1] - cr["dates"][0]).days / 365.25
    a = ASSUME
    mult_krw = eq[-1] * cr["fx"][-1] / cr["fx"][0] * (1 - a["fx_spread"]) / (1 + a["fx_spread"])
    gain = a["seed_krw"] * (mult_krw - 1)
    return {"cagr_usd": round(float(eq[-1] ** (1 / yrs) - 1), 4), "mult_usd": round(float(eq[-1]), 3),
            "cagr_krw": round(float(mult_krw ** (1 / yrs) - 1), 4), "mult_krw": round(float(mult_krw), 3),
            "mdd_equity": round(float((eq / np.maximum.accumulate(eq) - 1).min()), 4),
            "min_vs_start": round(float(eq.min() - 1), 4)}


def hold(path: pd.DataFrame, start, end=None) -> dict:
    px = path.loc[start:end]
    c = px["close"]
    a = ASSUME
    yrs = (c.index[-1] - c.index[0]).days / 365.25
    mult_usd = c.iloc[-1] / c.iloc[0] * (1 - a["fee"]) ** 2
    mult_krw = mult_usd * px["fx"].iloc[-1] / px["fx"].iloc[0] * ((1 - a["fx_spread"]) / (1 + a["fx_spread"]))
    gain = a["seed_krw"] * (mult_krw - 1)
    after = a["seed_krw"] * mult_krw - max(0.0, gain - a["tax_deduct_krw"]) * a["tax_rate"]
    mdd = float((c / c.cummax() - 1).min())
    return {"cagr_usd": round(mult_usd ** (1 / yrs) - 1, 4), "cagr_krw": round(mult_krw ** (1 / yrs) - 1, 4),
            "cagr_krw_after_tax": round((after / a["seed_krw"]) ** (1 / yrs) - 1, 4), "mdd": round(mdd, 4),
            "min_vs_start": round(float(c.min() / c.iloc[0] - 1), 4), "mult_krw": round(mult_krw, 3)}


def qqq_path(df: pd.DataFrame) -> pd.Series:
    """QQQ 총수익(수정) 지수, 1999-03 이전은 ^NDX + 배당 − 보수."""
    a = ASSUME
    cal = df.index[df["^NDX_close"].notna()]
    d = df.loc[cal]
    syn = _r(d["^NDX_close"]) + a["ndx_div"] / 252 - a["qqq_er"] / 252
    real = _r(d["QQQ_adj"])
    r = real.where(d["QQQ_adj"].notna() & d["QQQ_adj"].shift(1).notna(), syn).iloc[1:]
    return 100 * (1 + r).cumprod()


def qqq_dca(q: pd.Series, fx: pd.Series, start, end=None) -> dict:
    """같은 기간 QQQ 매 거래일 같은 원화 적립(원화, 세전) IRR."""
    a = ASSUME
    px = q.loc[start:end]
    f = fx.reindex(px.index).ffill().bfill()
    units = (1 / (f * (1 + a["fx_spread"]))) * (1 - a["fee"]) / px
    val = units.cumsum() * px * f * (1 - a["fee"]) * (1 - a["fx_spread"])
    dates = np.append(px.index.values.astype("datetime64[D]"), px.index[-1].to_datetime64().astype("datetime64[D]"))
    cfs = np.append(-np.ones(len(px)), val.iloc[-1])
    paid = np.arange(1, len(px) + 1)
    return {"irr": round(xirr(dates, cfs), 4), "loss_vs_paid_min": round(float((val / paid - 1).min()), 4)}


def rolling_first_cycle(path: pd.DataFrame, tk: str, rule: str) -> dict:
    """매월 첫 거래일 시작 → 첫 사이클 결과 분포(끝날 때까지 추적, 미종료는 열린 채)."""
    starts = path.groupby(path.index.to_period("M")).head(1).index
    rows = []
    for s in starts:
        res = run_strategy(path, tk, rule, start=s, end=None)
        c = res["cycles"][0] if res["cycles"] else res["open"]
        if c is None:
            continue
        rows.append({"start": str(s.date()), "done": bool(res["cycles"]), "days": c["days"], "ret": c["ret"], "min_eq": c["min_eq"] - 1,
                     "exhaust": int(c["rev"] + c["qstop"]), "syn": bool(path.loc[s:, "is_syn"].iloc[:max(c["days"] * 5 // 7, 1)].mean() > 0.5)})
    done = [r for r in rows if r["done"]]
    d = np.array([r["days"] for r in done])
    rets = np.array([r["ret"] for r in done])
    mins = np.array([r["min_eq"] for r in rows])
    return {"n": len(rows), "n_done": len(done),
            "days": {"p10": _q(d, 10), "med": _q(d, 50), "p90": _q(d, 90), "max": _q(d, 100)},
            "share_over_1y": round(float((d > 365).mean()), 4) if len(d) else None,
            "share_over_2y": round(float((d > 730).mean()), 4) if len(d) else None,
            "ret": {"min": _q(rets, 0), "p10": _q(rets, 10), "med": _q(rets, 50)},
            "loss_share": round(float((rets < 0).mean()), 4) if len(rets) else None,
            "min_eq": {"worst": _q(mins, 0), "p10": _q(mins, 10), "med": _q(mins, 50)},
            "exhaust_share": round(float(np.mean([r["exhaust"] > 0 for r in rows])), 4),
            "worst": sorted(rows, key=lambda r: r["min_eq"])[:3],
            "longest": sorted(done, key=lambda r: -r["days"])[:3]}


STRESS = {"2000형(닷컴 고점)": ("2000-03-01", "2005-03-01"), "2008형(금융위기 전)": ("2007-10-01", "2012-10-01"),
          "2022형(긴축 하락 전)": ("2021-11-01", None)}


def run(src: Path = SRC) -> dict:
    df = load(src)
    q = qqq_path(df)
    fx = fx_series(df)
    out = {"assume": ASSUME, "rules": RULES, "base": BASE, "tickers": {}}
    for tk in ("TQQQ", "SOXL"):
        path, meta = build_path(df, tk)
        real_start = meta["real_first"]
        t = {"meta": meta, "tracking": tracking(path, df, tk), "real": {}, "full": {}, "compound_real": {}, "compound_full": {}, "stress": {}, "stress_compound": {}, "rolling": {}}
        for rn in RULES:
            r_real = run_strategy(path, tk, rn, start=real_start)
            t["real"][rn] = summarize(r_real, path, tk)
            t["compound_real"][rn] = compound(path, tk, rn, start=real_start)
            t["full"][rn] = summarize(run_strategy(path, tk, rn), path, tk)
            t["compound_full"][rn] = compound(path, tk, rn)
            for name, (s, e) in STRESS.items():
                if pd.Timestamp(s) < path.index[0]:
                    continue
                t["stress"].setdefault(name, {})[rn] = summarize(run_strategy(path, tk, rn, start=s, end=e), path, tk)
                t["stress_compound"].setdefault(name, {})[rn] = compound(path, tk, rn, start=s, end=e)
        t["rolling"]["V4.0_20"] = rolling_first_cycle(path, tk, "V4.0_20")
        t["rolling"]["V2.2_40"] = rolling_first_cycle(path, tk, "V2.2_40")
        t["hold_real"] = hold(path, real_start)
        t["hold_full"] = hold(path, path.index[0])
        t["stress_hold"] = {name: hold(path, s, e) for name, (s, e) in STRESS.items() if pd.Timestamp(s) >= path.index[0]}
        t["qqq_hold_real"] = hold(pd.DataFrame({"close": q, "fx": fx.reindex(q.index).ffill().bfill()}), real_start)
        t["qqq_dca_real"] = qqq_dca(q, fx, real_start)
        t["qqq_dca_full"] = qqq_dca(q, fx, path.index[0])
        out["tickers"][tk] = t
    out["data_end"] = str(df.index[-1].date())
    return out


def main() -> int:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else SRC
    res = run(src)
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    print(json.dumps({tk: {"real": {rn: {k: v[k] for k in ("usd_irr_fixed_seed", "krw_irr_fixed_seed", "max_eval_loss_vs_seed", "n_cycles", "exhaust_events")}
                                    for rn, v in t["real"].items()}, "hold": t["hold_real"]} for tk, t in res["tickers"].items()},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
