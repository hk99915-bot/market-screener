#!/usr/bin/env python3
"""라오어 무한매수 V4.0 독립 재현 (검증 데스크, 2026-10-21).

원 코드(scripts/study_laor_ib.py) 미열람 상태에서 reports/studies/2026-10-21_laor_infinite_buy.md
§0 규칙 표·§4 비용·§5 LOC 근사만 보고 작성. 해석표는 replication_laor_ib.md §0.

  python3 scripts/replicate_laor_ib.py data/study/laor_ib_px.csv --out reports/studies/replication_laor_ib.json

연구 전용 — 실계좌 레버리지·인버스 2027-04-15까지 금지. 가상 금액, 매매 지시 아님.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

SEED_KRW = 40_000_000
FEE = 0.001
FX_SPREAD = 0.0025
REAL_END = "2026-10-20"
# 보고서 JSON assume·meta 의 합성 파라미터 (§5 공식)
SYN = {"TQQQ": dict(idx="^NDX", div=0.007, er=0.0084, spread=0.00296),
       "SOXL": dict(idx="^SOX", div=0.01, er=0.0075, spread=0.0055)}
BASE = {"TQQQ": 15.0, "SOXL": 20.0}


@dataclass(frozen=True)
class Rule:
    N: int = 20
    base: float = 15.0              # 별% 기준·목표 수익률(%)
    qty_by_order_px: bool = False   # LOC 매수 수량 = 금액 ÷ 주문가 (False면 ÷ 종가)
    lim_margin: float = 0.0         # 지정가 체결 조건: 고가 ≥ 주문가×(1+margin)
    buy_on_lim_day: bool = False    # 지정가 체결일에도 LOC 매수 체결 처리
    slip: float = 0.0               # LOC·MOC 체결 슬리피지(편도)
    rev_T: str = "prop"             # 리버스 중 T: prop(가정) | hold(고정) | unit(매수 +1, 매도 −N/10 대신 ×0.9)
    rev_exit: float | None = None   # 리버스 탈출 기준 평단×(1−x), None=base%
    post_sell_half: bool = False    # 전/후반 매수 주문 종류를 '당일 매도 반영 후 T' 로 고름(원 코드 방식 — 당일 종가 정보 누수)
    exit_day_normal: bool = False   # 리버스 탈출 다음 날은 T>N−1 이어도 일반모드 하루를 돈 뒤 재진입 판정(원 코드 방식)


@dataclass
class Cycle:
    start: str
    end: str | None = None
    days: int = 0
    ret: float = 0.0          # 원화 회수 ÷ 투입 − 1
    min_eq: float = 0.0       # 사이클 안 최대 평가손(원화, 투입 대비)
    exhaust: int = 0
    ret_usd: float = 0.0      # 달러 기준(환율 효과 제외)
    min_eq_usd: float = 0.0
    T: float = 0.0
    mode: str = "normal"


@dataclass
class Result:
    cycles: list = field(default_factory=list)
    flows: list = field(default_factory=list)   # (date, krw) 원금 고정판
    eq: list = field(default_factory=list)      # (date, krw) 복리판 일별


def load(csv: str) -> pd.DataFrame:
    d = pd.read_csv(csv, parse_dates=["date"]).set_index("date").sort_index()
    fx = d["KRW=X_close"].where(d.index >= "2003-12-01")
    fx = fx.fillna(d["dbn_DEXKOUS"].where(d.index < "2003-12-01")).ffill()
    d["fx"] = fx
    return d


def series(d: pd.DataFrame, tk: str, synthetic: bool, spread_shift: float = 0.0,
           noise_te: float = 0.0, seed: int = 0, adj: bool = False) -> pd.DataFrame:
    """실 ETF(종가·고가) 또는 실 ETF 앞에 합성을 이어붙인 시계열. adj=True 면 배당 수정종가(고가도 같은 비율)."""
    real = d[[f"{tk}_close", f"{tk}_high", "fx"]].dropna(subset=[f"{tk}_close"])
    real.columns = ["close", "high", "fx"]
    if adj:
        k = d.loc[real.index, f"{tk}_adj"] / d.loc[real.index, f"{tk}_close"]
        real = real.assign(close=real["close"] * k, high=real["high"] * k)
    real = real[real.index <= REAL_END]
    if not synthetic:
        return real
    p = SYN[tk]
    ix = d[[f"{p['idx']}_close", f"{p['idx']}_high", "^IRX_close", "fx"]].dropna(subset=[f"{p['idx']}_close"])
    ix = ix[ix.index <= REAL_END].copy()
    ix["^IRX_close"] = ix["^IRX_close"].ffill()
    c = ix[f"{p['idx']}_close"].values
    h = ix[f"{p['idx']}_high"].fillna(ix[f"{p['idx']}_close"]).values
    dd = np.r_[1, np.diff(ix.index.values).astype("timedelta64[D]").astype(int)]
    irx = ix["^IRX_close"].values / 100
    r = np.zeros(len(c)); hr = np.zeros(len(c))
    r[1:] = 3 * (c[1:] / c[:-1] - 1 + p["div"] / 252) - 2 * (irx[:-1] + p["spread"] + spread_shift) * dd[1:] / 360 - p["er"] / 252
    hr[1:] = 3 * (h[1:] / c[:-1] - 1)
    if noise_te:
        rng = np.random.default_rng(seed)
        r[1:] += rng.normal(0, noise_te / np.sqrt(252), len(c) - 1)
    first = real.index[0]
    k = ix.index.get_loc(first)
    lvl = np.empty(len(c)); lvl[k] = real["close"].iloc[0]
    for i in range(k, 0, -1):
        lvl[i - 1] = lvl[i] / (1 + r[i])
    syn = pd.DataFrame({"close": lvl[:k], "high": None, "fx": ix["fx"].values[:k]}, index=ix.index[:k])
    hi = np.r_[lvl[0], lvl[:k - 1] * (1 + hr[1:k])]
    syn["high"] = np.maximum(hi, lvl[:k])
    out = pd.concat([syn, real]).dropna(subset=["fx"])
    return out


def simulate(px: pd.DataFrame, rule: Rule, compound: bool = False, trace: list | None = None) -> Result:
    C = px["close"].values.astype(float); H = px["high"].fillna(px["close"]).values.astype(float)
    FX = px["fx"].values.astype(float); D = [t.strftime("%Y-%m-%d") for t in px.index]
    N, b = rule.N, rule.base
    res = Result()
    pool_usd = SEED_KRW / FX[1] * (1 - FX_SPREAD) if compound else None
    i = 1  # 첫 매수는 전일 종가가 있는 둘째 날부터
    cyc = None
    while i < len(C):
        # ---- 사이클 시작: 첫 매수(종가) ----
        if compound:
            cash = pool_usd
        else:
            cash = SEED_KRW / FX[i] * (1 - FX_SPREAD)
            res.flows.append((D[i], -SEED_KRW))
        seed_krw_eq = cash * FX[i] / (1 - FX_SPREAD)  # 사이클 투입 원화 기준
        cyc = Cycle(start=D[i])
        amt = cash / N
        bpx = C[i] * (1 + rule.slip)
        sh = amt / (1 + FEE) / bpx; cost = sh * bpx; cash -= amt; T = 1.0
        mode = "normal"; min_eq = 0.0; min_usd = 0.0; seed_usd = cash + amt
        eq = (sh * C[i] + cash) * FX[i]
        min_eq = min(min_eq, eq / seed_krw_eq - 1)
        if compound:
            res.eq.append((D[i], eq * (1 - FX_SPREAD)))
        j = i + 1
        closed = False
        while j < len(C):
            c, h = C[j], H[j]
            avg = cost / sh
            if T > N - 1 and (mode == "normal" or (mode == "normal_next" and not rule.exit_day_normal)):
                mode = "reverse"; cyc.exhaust += 1
                q = sh / (N / 2); spx = c * (1 - rule.slip)
                cash += q * spx * (1 - FEE); cost -= q * avg; sh -= q
                T = T * (1 - 2 / N) if rule.rev_T != "hold" else T
                if c > avg * (1 - (rule.rev_exit if rule.rev_exit is not None else b / 100)):
                    mode = "normal_next"
            elif mode == "reverse":
                star5 = C[j - 5:j].mean()
                if c >= star5:
                    q = sh / (N / 2); spx = c * (1 - rule.slip)
                    cash += q * spx * (1 - FEE); cost -= q * avg; sh -= q
                    if rule.rev_T == "prop":
                        T *= (1 - 2 / N)
                    elif rule.rev_T == "unit":
                        T = max(T - 1, 0)
                else:
                    amt = cash / 4; bpx = c * (1 + rule.slip)
                    q = amt / (1 + FEE) / bpx; sh += q; cost += q * bpx; cash -= amt
                    if rule.rev_T == "prop":
                        T += (N - T) / 4
                    elif rule.rev_T == "unit":
                        T = min(T + 1, N)
                avg = cost / sh
                if c > avg * (1 - (rule.rev_exit if rule.rev_exit is not None else b / 100)):
                    mode = "normal_next"
            else:
                mode = "normal"
                star = b - (2 * b / N) * T
                spt = avg * (1 + star / 100)
                tgt = avg * (1 + b / 100)
                unit = min(cash / (N - T), cash) if N - T > 0 else 0.0
                lim = h >= tgt * (1 + rule.lim_margin)
                loc_s = c >= spt
                q_lim, q_loc = sh * 0.75, sh * 0.25
                T0 = T
                if lim:
                    cash += q_lim * tgt * (1 - FEE); cost -= q_lim * avg; sh -= q_lim; T *= 0.25
                if loc_s:
                    spx = c * (1 - rule.slip)
                    cash += q_loc * spx * (1 - FEE); cost -= q_loc * avg; sh -= q_loc; T *= 0.75
                if (not lim) or rule.buy_on_lim_day:
                    Th = T if rule.post_sell_half else T0
                    orders = ([(unit / 2, avg), (unit / 2, spt * 0.9999)] if Th < N / 2
                              else [(unit, spt * 0.9999)])
                    for a, lp in orders:
                        if c <= lp:
                            bpx = c * (1 + rule.slip)
                            q = a / (1 + FEE) / (lp if rule.qty_by_order_px else bpx)
                            spend = q * bpx * (1 + FEE)
                            sh += q; cost += q * bpx; cash -= spend
                            T += 0.5 if Th < N / 2 else 1.0
                if sh <= 1e-12 * max(1.0, cost):
                    sh = 0.0
            if trace is not None:
                trace.append((D[j], mode, round(T, 3), sh, cash))
            eq = (sh * c + cash) * FX[j]
            if compound:
                res.eq.append((D[j], eq * (1 - FX_SPREAD)))
            min_eq = min(min_eq, eq / seed_krw_eq - 1)
            min_usd = min(min_usd, (sh * c + cash) / seed_usd - 1)
            if sh <= 0:
                cyc.ret_usd = cash / seed_usd - 1; cyc.min_eq_usd = min_usd
                out_krw = cash * FX[j] * (1 - FX_SPREAD)
                cyc.end = D[j]; cyc.ret = out_krw / seed_krw_eq - 1
                cyc.days = (date.fromisoformat(D[j]) - date.fromisoformat(cyc.start)).days
                cyc.min_eq = min_eq; cyc.T = 0; res.cycles.append(cyc)
                if compound:
                    pool_usd = cash
                else:
                    res.flows.append((D[j], out_krw))
                closed = True
                break
            j += 1
        if not closed:  # 열린 사이클: 마지막 날 평가
            j = len(C) - 1
            val = (sh * C[j] * (1 - FEE) + cash) * FX[j] * (1 - FX_SPREAD)
            cyc.ret = val / seed_krw_eq - 1; cyc.min_eq = min_eq; cyc.T = round(T, 2)
            cyc.ret_usd = (sh * C[j] + cash) / seed_usd - 1; cyc.min_eq_usd = min_usd
            cyc.days = (date.fromisoformat(D[j]) - date.fromisoformat(cyc.start)).days
            cyc.mode = mode; res.cycles.append(cyc)
            if not compound:
                res.flows.append((D[j], val))
            else:
                res.eq[-1] = (D[j], val)
            break
        i = j + 1
    return res


def xirr(flows) -> float:
    t0 = date.fromisoformat(flows[0][0])
    ts = np.array([(date.fromisoformat(d) - t0).days / 365.0 for d, _ in flows])
    cf = np.array([v for _, v in flows], dtype=float)
    lo, hi = -0.99, 5.0
    f = lambda r: (cf / (1 + r) ** ts).sum()
    for _ in range(200):
        m = (lo + hi) / 2
        if f(m) > 0:
            lo = m
        else:
            hi = m
    return m


def summarize(px: pd.DataFrame, rule: Rule) -> dict:
    fx_ = simulate(px, rule, compound=False)
    co = simulate(px, rule, compound=True)
    closed = [c for c in fx_.cycles if c.end]
    eqs = pd.Series([v for _, v in co.eq], index=pd.to_datetime([d for d, _ in co.eq]))
    yrs = (eqs.index[-1] - pd.Timestamp(px.index[1])).days / 365.25
    cagr = (eqs.iloc[-1] / SEED_KRW) ** (1 / yrs) - 1
    mdd = (eqs / eqs.cummax() - 1).min()
    eu = eqs / px["fx"].reindex(eqs.index).values          # 달러 평가(환율 제외)
    mdd_usd = (eu / eu.cummax() - 1).min()
    worst = min(fx_.cycles, key=lambda c: c.min_eq)
    longest = max(fx_.cycles, key=lambda c: c.days)
    return dict(
        start=px.index[1].strftime("%Y-%m-%d"), end=px.index[-1].strftime("%Y-%m-%d"),
        n_cycles=len(fx_.cycles), n_closed=len(closed),
        krw_irr_fixed=round(xirr(fx_.flows), 4), cagr_compound=round(cagr, 4), mdd_compound=round(mdd, 4),
        mdd_compound_usd=round(float(mdd_usd), 4),
        max_eval_loss=round(worst.min_eq, 4), worst_cycle=worst.__dict__,
        max_eval_loss_usd=round(min(c.min_eq_usd for c in fx_.cycles), 4),
        longest_cycle=longest.__dict__,
        exhaust_events=sum(c.exhaust for c in fx_.cycles),
        exhaust_cycles=sum(1 for c in fx_.cycles if c.exhaust),
        loss_cycles=sum(1 for c in closed if c.ret < 0),
        refill_seeds=round(-sum(min(c.ret, 0) for c in closed), 3),
        profit_seeds=round(sum(max(c.ret, 0) for c in closed), 3),
        open_cycle=fx_.cycles[-1].__dict__ if not fx_.cycles[-1].end else None,
        starts=[c.start for c in fx_.cycles],
        _cycles=fx_.cycles,
    )


def irr_no_refill(px: pd.DataFrame, rule: Rule) -> float:
    """원금 고정에서 '손실 재충전' 을 빼면: 사이클 결과 배수를 원금 상한으로 이어 굴림(이익만 인출)."""
    s = simulate(px, rule, compound=False)
    cap = 1.0; flows = [(s.cycles[0].start, -SEED_KRW)]
    for c in s.cycles:
        m = 1 + c.ret
        new = cap * m
        if new > 1.0:
            flows.append((c.end or px.index[-1].strftime("%Y-%m-%d"), (new - 1.0) * SEED_KRW))
            cap = 1.0
        else:
            cap = new
    flows.append((px.index[-1].strftime("%Y-%m-%d"), cap * SEED_KRW))
    return round(xirr(flows), 4)


def _r4(x):
    return round(float(x), 4)


def _cyc(c: Cycle) -> dict:
    return {"start": c.start, "end": c.end, "days": c.days, "ret_krw": _r4(c.ret), "ret_usd": _r4(c.ret_usd),
            "min_eq_krw": _r4(c.min_eq), "min_eq_usd": _r4(c.min_eq_usd), "exhaust": c.exhaust}


def brief(px: pd.DataFrame, rule: Rule, refill: bool = False) -> dict:
    s = summarize(px, rule)
    o = {k: (_r4(s[k]) if isinstance(s[k], float) else s[k]) for k in (
        "start", "end", "n_cycles", "krw_irr_fixed", "cagr_compound", "mdd_compound", "mdd_compound_usd",
        "max_eval_loss", "max_eval_loss_usd", "exhaust_events", "exhaust_cycles", "loss_cycles", "refill_seeds", "profit_seeds")}
    o["worst_cycle"] = _cyc(min(s["_cycles"], key=lambda c: c.min_eq_usd))
    o["longest_cycle"] = _cyc(max(s["_cycles"], key=lambda c: c.days))
    o["starts"] = s["starts"]
    o["_cycles"] = s["_cycles"]
    if refill:
        o["irr_no_refill"] = irr_no_refill(px, rule)
    return o


def cycle_at(cycles, day: str) -> dict | None:
    for c in cycles:
        if c.start <= day <= (c.end or "9999"):
            return _cyc(c)
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv"); ap.add_argument("--out"); ap.add_argument("--mc", type=int, default=100)
    a = ap.parse_args()
    d = load(a.csv)
    out = {"real": {}, "syn": {}, "te_mc": {}}
    variants = {
        "A_independent": {},                                   # 사전등록 해석(종가, 주문 전 T)
        "B_orig_mimic": dict(adj=True, post_sell_half=True),   # 원 코드 방식(수정종가, 매도 후 T)
        "adj_only": dict(adj=True),
        "post_sell_half_only": dict(post_sell_half=True),
        "lim_margin_0.5%": dict(lim_margin=0.005),
        "lim_margin_1%": dict(lim_margin=0.01),
        "slip_0.1%": dict(slip=0.001),
        "slip_0.3%": dict(slip=0.003),
        "qty_by_order_px": dict(qty_by_order_px=True),
        "buy_on_lim_day": dict(buy_on_lim_day=True),
        "revT_hold": dict(rev_T="hold"),
        "revT_unit": dict(rev_T="unit"),
        "rev_exit_10%": dict(rev_exit=0.10),
    }
    for tk in ("TQQQ", "SOXL"):
        out["real"][tk] = {}
        for name, kw in variants.items():
            adj = kw.pop("adj", False) if "adj" in kw else False
            px = series(d, tk, synthetic=False, adj=adj)
            b = brief(px, Rule(base=BASE[tk], **kw), refill=name in ("A_independent", "B_orig_mimic"))
            b.pop("_cycles")
            if name not in ("A_independent", "B_orig_mimic"):
                b.pop("starts")
            out["real"][tk][name] = b
            if adj:
                kw["adj"] = True
        A, B = out["real"][tk]["A_independent"], out["real"][tk]["B_orig_mimic"]
        sa, sb = set(A["starts"]), set(B["starts"])
        out["real"][tk]["start_overlap_A_vs_B"] = round(len(sa & sb) / max(len(sa), len(sb)), 3)
        A.pop("starts"); B.pop("starts")
        print(tk, "real", {k: (v["krw_irr_fixed"], v["cagr_compound"], v["max_eval_loss_usd"], v["longest_cycle"]["days"], v["exhaust_events"], v["exhaust_cycles"])
                           for k, v in out["real"][tk].items() if isinstance(v, dict)})
    # 합성 전 기간 + 2000·2002·2008 사이클
    probes = {"TQQQ": ["2000-09-01", "2008-10-01"], "SOXL": ["2002-06-03", "2008-10-01", "2000-09-01"]}
    for tk in ("TQQQ", "SOXL"):
        out["syn"][tk] = {}
        for name, kw in (("A_independent", {}), ("B_orig_mimic", dict(post_sell_half=True)),
                         ("revT_hold", dict(rev_T="hold")), ("revT_unit", dict(rev_T="unit")),
                         ("spread_+4%p", "shift"), ("lim_margin_0.5%", dict(lim_margin=0.005))):
            px = series(d, tk, synthetic=True, adj=(name == "B_orig_mimic"), spread_shift=0.04 if kw == "shift" else 0.0)
            b = brief(px, Rule(base=BASE[tk], **(kw if isinstance(kw, dict) else {})))
            b["probe_cycles"] = {p: cycle_at(b["_cycles"], p) for p in probes[tk]}
            b.pop("_cycles"); b.pop("starts")
            out["syn"][tk][name] = b
        print(tk, "syn", {k: (v["krw_irr_fixed"], v["cagr_compound"], v["max_eval_loss_usd"], v["exhaust_events"],
                              [(p, c and (c["start"], c["days"], c["ret_usd"])) for p, c in v["probe_cycles"].items()]) for k, v in out["syn"][tk].items()})
    # (6) SOXL 합성 추적오차 연 10.6% 를 iid 잡음으로 넣은 몬테카를로
    for tk, te in (("SOXL", 0.106), ("TQQQ", 0.038)):
        rows = []
        for k in range(a.mc):
            px = series(d, tk, synthetic=True, noise_te=te, seed=k)
            s = summarize(px, Rule(base=BASE[tk]))
            c02 = cycle_at(s["_cycles"], "2002-06-03"); c08 = cycle_at(s["_cycles"], "2008-10-01"); c00 = cycle_at(s["_cycles"], "2000-09-01")
            rows.append((s["krw_irr_fixed"], float(s["cagr_compound"]), float(s["max_eval_loss"]),
                         c00["ret_usd"] if c00 else np.nan, c02["ret_usd"] if c02 else np.nan, c08["ret_usd"] if c08 else np.nan))
        r = np.array(rows)
        q = lambda x: [_r4(np.nanpercentile(x, p)) for p in (5, 50, 95)]
        out["te_mc"][tk] = {"te_ann": te, "paths": a.mc, "irr_fixed_p5_50_95": q(r[:, 0]), "cagr_compound_p5_50_95": q(r[:, 1]),
                            "max_eval_loss_krw_p5_50_95": q(r[:, 2]), "cycle_2000_09_ret_usd": q(r[:, 3]),
                            "cycle_2002_06_ret_usd": q(r[:, 4]), "cycle_2008_10_ret_usd": q(r[:, 5])}
        print(tk, "te_mc", out["te_mc"][tk])
    if a.out:
        json.dump(out, open(a.out, "w"), ensure_ascii=False, indent=1, default=float)


if __name__ == "__main__":
    main()
