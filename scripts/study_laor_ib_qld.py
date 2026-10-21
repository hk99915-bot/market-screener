"""라오어 무한매수(V4.0/V2.2) QLD(나스닥100 2배) 적용 백테스트 — 연구 전용(실계좌 레버리지·인버스 2027-04-15까지 금지, 불변).

겸이 10/21 "QLD로 하면?" — scripts/study_laor_ib.py 의 규칙 엔진(step·run_strategy·summarize·compound·hold)을 그대로 쓴다.
그 파일·그 결과 JSON 은 바꾸지 않는다(검증 데스크 독립 재현 중). 여기서는 엔진을 import 해 QLD 경로만 새로 만든다.

입력(새 수집 없음):
- data/study/qld_dca_px.csv  (브랜치 study-data/qld-dca-39529898962, 10/21 QLD 적립 연구 — 검증 재현 일치)
  → QLD 일간 총수익·합성(2·NDX_TR − (rf+spread)·dt/360 − 0.95%/252, spread 2006-06~2015 보정)·원/달러는
    scripts/study_qld_dca.build_returns 를 그대로 재사용.
- data/study/laor_ib_px.csv  (브랜치 study-data/laor-ib-39536992489) — ^NDX 고가만 가져온다(QLD 고가는 수집된 적 없음).
QLD 장중 고가(지정가 매도 체결 판정용) [가정] = 전일 QLD 종가 × (1 + 2·(NDX 고가 / NDX 전일 종가 − 1)), 종가 아래면 종가.
  실 QLD 구간에도 같은 근사를 쓴다 → 근사 오차는 TQQQ 실데이터에서 '실 고가 vs 3배 근사 고가'로 돌려 크기를 잰다(high_proxy_check).

파라미터 3안 [가정 — 라오어 원 규칙엔 QLD 가 없다]:
- A '2/3 스케일': V4.0 20분할, 별% 10 − 1·T, 지정가 +10% (TQQQ 15−1.5T·+15% 를 변동성 비 2/3 로 축소)
- B 'TQQQ 그대로': V4.0 20분할, 별% 15 − 1.5·T, 지정가 +15%
- C 'V2.2': 40분할, 별% 10 − T/2, 지정가 +10%, 원금/40 매수, 소진 = 쿼터손절
출력: reports/studies/2026-10-21_laor_ib_qld.json (+ md 는 사람이 쓴다)
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
SRC_QLD = ROOT / "data/study/qld_dca_px.csv"
SRC_LAOR = ROOT / "data/study/laor_ib_px.csv"
OUT = ROOT / "reports/studies/2026-10-21_laor_ib_qld.json"
LAOR_JSON = ROOT / "reports/studies/2026-10-21_laor_infinite_buy.json"


def _load_mod(name: str):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, ROOT / f"scripts/{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod     # dataclass 가 모듈 이름으로 자기 모듈을 찾는다
    spec.loader.exec_module(mod)
    return mod


L = _load_mod("study_laor_ib")
Q = _load_mod("study_qld_dca")
_ORIG_STEP = L.step

# 안 이름 → (엔진 규칙, 별% 시작값 base). base 는 엔진 BASE 사전에 '가상 종목 키'로 넣는다(TQQQ·SOXL 키는 건드리지 않음).
PLANS = {
    "A_2/3스케일(10−T,+10%)": ("V4.0_20", 10.0),
    "B_TQQQ그대로(15−1.5T,+15%)": ("V4.0_20", 15.0),
    "C_V2.2(10−T/2,+10%,40분할)": ("V2.2_40", 10.0),
}
WINDOWS = {"real": "2006-06-22", "common_tqqq": "2010-02-12"}   # 실 QLD 구간 / TQQQ 실 구간과 같은 시작(직접 비교용)


def step_prevT(p, rule: dict, base: float, prev_close: float, close: float, high: float, last5: float, fee: float):
    """L.step 과 같되, 전반/후반 판정을 **직전 거래일 T**(장 시작 전 상태)로 한다.
    10/21 검증 재현(replication_laor_ib.md): 원 엔진은 그날 쿼터 매도로 T 가 줄면 같은 날 전반/후반을 다시 정해
    장 전엔 없던 평단 LOC 매수가 생긴다(미래 정보). 2차 출처 ①은 직전 거래일 T 로 주문을 정한다."""
    if p.qty <= 0 or p.mode == "reverse":           # 첫 매수·리버스모드는 T 재판정 문제 없음 → 원 엔진 그대로
        return _ORIG_STEP(p, rule, base, prev_close, close, high, last5, fee)
    N = rule["N"]
    T0 = p.T
    sp = L.star_pct(rule, base, T0)
    star = p.avg * (1 + sp / 100)
    tgt = p.avg * (1 + (10.0 if rule["star"] == "v22" else base) / 100)
    q4 = p.qty / 4
    q_rest = p.qty - q4
    left = N - T0
    unit = (p.cash / left if left > 0 else 0.0) if rule["unit"] == "cash" else p.seed / N
    avg0 = p.avg
    sold_tgt = high >= tgt
    if sold_tgt:
        L._sell(p, q_rest, tgt, fee)
        p.T *= 0.25
    if close >= star:
        L._sell(p, q4, close, fee)
        p.T *= 0.75
    if p.qty <= 0:
        return "end"
    if sold_tgt:
        return None
    star_buy = star - 0.01 * star / 100
    if T0 < N / 2:                                   # ← 직전 거래일 T
        if close <= avg0:
            L._buy(p, unit / 2, close, fee)
            p.T += 0.5
        if close <= star_buy:
            L._buy(p, unit / 2, close, fee)
            p.T += 0.5
    else:
        if close <= star_buy:
            L._buy(p, unit, close, fee)
            p.T += 1.0
    if p.T > N - 1 and p.mode == "normal":
        if rule["exhaust"] == "reverse":
            p.mode, p.rev_first = "reverse", True
            p.rev_entries += 1
        else:
            p.mode, p.rev_first = "qstop", True
            p.qstop += 1
    return None


class prevT_engine:
    """with prevT_engine(): 동안만 엔진의 step 을 step_prevT 로 바꾼다(파일은 안 바꿈). 끝나면 원래대로."""
    def __enter__(self):
        L.step = step_prevT
        return self

    def __exit__(self, *a):
        L.step = _ORIG_STEP


# 체결 가정 민감도(최장 사이클 범위용): 지정가 매도 판정에 쓰는 고가를 바꾼다.
FILL_SENS = {"base": 1.0, "고가−0.5%": 1 / 1.005, "고가=종가(장중 체결 없음)": 0.0}


def with_high(path: pd.DataFrame, k: float) -> pd.DataFrame:
    p = path.copy()
    p["high"] = p["close"] if k == 0.0 else np.maximum(p["high"] * k, p["close"])
    return p


def _key(plan: str) -> str:
    k = "QLD_" + plan[0]
    L.BASE[k] = PLANS[plan][1]
    return k


def build_qld_path(df_qld: pd.DataFrame, df_laor: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """study_laor_ib 엔진 입력 형식(close, high, fx, is_syn)의 QLD 경로."""
    rets, meta = Q.build_returns(df_qld)
    ndx_c = df_laor["^NDX_close"].dropna()
    ndx_h = df_laor["^NDX_high"].reindex(ndx_c.index)
    h_idx = (ndx_h / ndx_c.shift(1) - 1).reindex(rets.index)
    out = pd.DataFrame({"ret": rets["QLD"], "is_syn": rets["qld_is_syn"], "fx": rets["fx"]}).dropna(subset=["ret"])
    out["close"] = 100 * np.cumprod(1 + out["ret"].values)
    prev = out["close"].shift(1).fillna(100)
    hret = (2 * h_idx).reindex(out.index).fillna(out["ret"])
    out["high"] = np.maximum(prev * (1 + hret), out["close"])
    real_first = str(out.index[~out["is_syn"]][0].date())
    return out, {"spread": meta["spread"], "first": str(out.index[0].date()), "real_first": real_first}


def high_proxy_check(df_laor: pd.DataFrame) -> dict:
    """고가 근사의 영향: TQQQ 실 구간 V4.0 20분할을 '실 고가' vs '3·NDX 고가 근사'로 돌려 비교."""
    path, meta = L.build_path(df_laor, "TQQQ")
    s = meta["real_first"]
    ndx_c = df_laor["^NDX_close"].dropna()
    h_idx = (df_laor["^NDX_high"].reindex(ndx_c.index) / ndx_c.shift(1) - 1).reindex(path.index)
    alt = path.copy()
    prev = alt["close"].shift(1).fillna(100)
    alt["high"] = np.maximum(prev * (1 + (3 * h_idx).fillna(alt["ret"])), alt["close"])
    res = {}
    for name, p in (("real_high", path), ("proxy_high", alt)):
        sm = L.summarize(L.run_strategy(p, "TQQQ", "V4.0_20", start=s), p, "TQQQ")
        cp = L.compound(p, "TQQQ", "V4.0_20", start=s)
        res[name] = {"krw_irr": sm["krw_irr_fixed_seed"], "cagr_krw": cp["cagr_krw"], "n_cycles": sm["n_cycles"],
                     "max_eval_loss": sm["max_eval_loss_vs_seed"]}
    m = ~path["is_syn"] & h_idx.notna()
    rh = path["high"][m] / path["close"].shift(1)[m] - 1
    res["day_high_ret_gap"] = {"mean": round(float((3 * h_idx[m] - rh).mean()), 5), "mae": round(float((3 * h_idx[m] - rh).abs().mean()), 5)}
    return res


def run(src_qld: Path = SRC_QLD, src_laor: Path = SRC_LAOR) -> dict:
    dq, dl = Q.load(src_qld), L.load(src_laor)
    path, meta = build_qld_path(dq, dl)
    qqq = L.qqq_path(dl)
    fx = L.fx_series(dl)
    qqq_df = pd.DataFrame({"close": qqq, "fx": fx.reindex(qqq.index).ffill().bfill()})
    out = {"assume": {"engine": "scripts/study_laor_ib.py (불변, import)", "laor_assume": L.ASSUME,
                      "qld_assume": Q.ASSUME, "plans": {k: {"rule": v[0], "base": v[1]} for k, v in PLANS.items()},
                      "high_proxy": "QLD 고가 = 전일 종가 × (1 + 2·(NDX 고가/NDX 전일 종가 − 1)) [가정]"},
           "meta": meta, "windows": WINDOWS, "plans": {}, "stress_hold": {}, "compare": {}}
    out["assume"]["order_T"] = "직전 거래일 T 로 전반/후반 판정(step_prevT) — 원 엔진의 같은 날 T 재판정(미래 정보) 제거"
    out["assume"]["units"] = ("IRR·복리 CAGR·mult_krw = 원화(환전 포함). 사이클 수익률(cycle_ret)·원금 대비 최대 평가손(max_eval_loss_vs_seed·min_eq)"
                              "·복리 MDD(mdd_equity)·min_vs_start = 달러 기준(사이클 안 환율 변화 제외)")
    out["assume"]["fill_sens"] = FILL_SENS
    for plan, (rn, _) in PLANS.items():
        k = _key(plan)
        t = {}
        with prevT_engine():
            for w, s in WINDOWS.items():
                t[w] = L.summarize(L.run_strategy(path, k, rn, start=s), path, k)
                t[f"compound_{w}"] = L.compound(path, k, rn, start=s)
            t["full"] = L.summarize(L.run_strategy(path, k, rn), path, k)
            t["compound_full"] = L.compound(path, k, rn)
            t["stress"], t["stress_compound"] = {}, {}
            for name, (s, e) in L.STRESS.items():
                t["stress"][name] = L.summarize(L.run_strategy(path, k, rn, start=s, end=e), path, k)
                t["stress_compound"][name] = L.compound(path, k, rn, start=s, end=e)
            t["rolling"] = L.rolling_first_cycle(path, k, rn)
            t["fill_sens"] = {}
            for fname, fk in FILL_SENS.items():
                ph = with_high(path, fk)
                t["fill_sens"][fname] = {w: {kk: L.summarize(L.run_strategy(ph, k, rn, start=s), ph, k)[kk]
                                             for kk in ("krw_irr_fixed_seed", "longest_cycle", "max_eval_loss_vs_seed", "n_cycles")}
                                         for w, s in (*WINDOWS.items(), ("full", None))}
        # 참고: 누수 있는 원 엔진(같은 날 T)으로 돌린 값 — 정정 효과 크기
        t["orig_engine_ref"] = {w: {kk: L.summarize(L.run_strategy(path, k, rn, start=s), path, k)[kk]
                                    for kk in ("krw_irr_fixed_seed", "max_eval_loss_vs_seed", "n_cycles")}
                                for w, s in WINDOWS.items()}
        out["plans"][plan] = t
    for w, s in WINDOWS.items():
        out["compare"][f"qld_hold_{w}"] = L.hold(path, s)
        out["compare"][f"qqq_hold_{w}"] = L.hold(qqq_df, s)
    out["compare"]["qld_hold_full"] = L.hold(path, path.index[0])
    out["compare"]["qqq_hold_full"] = L.hold(qqq_df, path.index[0])
    for name, (s, e) in L.STRESS.items():
        out["stress_hold"][name] = {"QLD": L.hold(path, s, e), "QQQ": L.hold(qqq_df, s, e)}
    # 기존 산출물 인용(재계산 아님): QLD 매일 적립 30.9%(10/21), TQQQ 무한매수(10/21 laor JSON)
    if LAOR_JSON.exists():
        t = json.loads(LAOR_JSON.read_text())["tickers"]["TQQQ"]
        out["compare"]["tqqq_ib_v40_20_cited"] = {
            "real": {k: t["real"]["V4.0_20"][k] for k in ("start", "krw_irr_fixed_seed", "krw_irr_fixed_seed_after_tax", "max_eval_loss_vs_seed", "longest_cycle", "exhaust_events")},
            "compound_real": t["compound_real"]["V4.0_20"], "compound_full": t["compound_full"]["V4.0_20"],
            "full_irr": t["full"]["V4.0_20"]["krw_irr_fixed_seed"], "full_irr_after_tax": t["full"]["V4.0_20"]["krw_irr_fixed_seed_after_tax"],
            "stress_compound": {n: v["V4.0_20"] for n, v in t["stress_compound"].items()},
            "stress": {n: {k: v["V4.0_20"][k] for k in ("krw_irr_fixed_seed", "worst_cycle")} for n, v in t["stress"].items()}}
    out["compare"]["qld_daily_dca_cited"] = {"irr_krw_2006_06": 0.309, "loss_vs_paid_min": -0.568, "src": "reports/studies/2026-10-21_qld_daily_dca.md §1"}
    out["high_proxy_check"] = high_proxy_check(dl)            # 원 엔진(기존 TQQQ 숫자와 맞대기용)
    with prevT_engine():
        out["high_proxy_check_prevT"] = high_proxy_check(dl)  # 정정 엔진(같은 창 TQQQ 비교 기준)
    out["data_end"] = str(path.index[-1].date())
    return out


def main() -> int:
    src_q = Path(sys.argv[1]) if len(sys.argv) > 1 else SRC_QLD
    src_l = Path(sys.argv[2]) if len(sys.argv) > 2 else SRC_LAOR
    res = run(src_q, src_l)
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    keys = ("krw_irr_fixed_seed", "krw_irr_fixed_seed_after_tax", "max_eval_loss_vs_seed", "n_cycles", "exhaust_events")
    print(json.dumps({p: {w: {k: t[w][k] for k in keys} | {"cagr": t[f"compound_{w}"]["cagr_krw"], "mdd": t[f"compound_{w}"]["mdd_equity"]}
                          for w in WINDOWS} for p, t in res["plans"].items()}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
