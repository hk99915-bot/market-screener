"""변동성 타게팅 × GEX 감마 국면 — 사전등록 백테스트 (연구 전용, 매매 지시 아님).

python3 scripts/study_gex_vol_target.py   → reports/studies/2026-11-14_gex_vol_target.json

## §0 사전등록 (이 파일을 결과 보기 전에 커밋한다 — kb:quant#1)
- 요청: 겸이 2026-11-14 "꾸준히 지속가능한 성과" + "실현가능한 전략" — 장중 분봉·레버리지·옵션 없이
        K200 노출 비중(0~100%)만 조절하는 규칙을 같은 사전등록 규약으로 검정.
- 주제: `sizing`(노출 비중 조절) — 이 주제의 등록 연구 없음(N 0) + 이 연구 m 2 → α = 0.025.
        기존 `vol_premium`(옵션 매도·매수 전략, 2026-11-01_vol_strategies)·`derivs`(감마 방향)와 다른 질문이다.
- 데이터: `data/deriv/daily.csv` — `k200_close`(2010-01-04~2026-11-13, 4,151행 전 구간), `gex_bn`(**2025-08-29~ 294행**).
        `vkospi.csv` 는 2026-10-21~ 18행뿐이라 백테스트에 쓰지 않는다(참고 지표로만 언급).
- 실행: t일 종가까지의 정보로 w(t) 결정 → **t+1일** 종가-종가 수익에 적용(lag=1, 전방 누수 0).
        체결 가정 [가정]: t일 종가 동시호가, 슬리피지는 비용 bp에 포함.
- 비용: **편도 10bp 기본**(= 왕복 20bp), 민감도 5·15bp. 비용 = |Δw| × 편도bp. 현금 이자 0(보수적).
- 노트레이드 밴드: |목표 − 보유| ≤ 10%p 면 리밸런싱 스킵. H2 에서는 GEX 부호 전환일엔 밴드를 무시한다.
- 벤치마크: B1 = K200 Buy & Hold(w=1, 비용 0) · B2 = 동일 평균 노출 현금혼합(확장평균 비중, 전방 누수 없음, 같은 비용)
        · B3 = 현금 100%(참고).
- 가설 m=2, α = 0.05/2 = 0.025 (단측, 블록 부트스트랩 20일·2,000회·seed 7 — kb:quant#10 겹침 보정)
  H1 (변동성 타게팅): target_vol 13%·max_w 1.0 규칙의 **비용 후 샤프**가 B1(Buy & Hold)보다 크다.
  H2 (GEX 결합): GEX 표본(2025-08-29~)에서 `gex_bn < 0` 일 때 0.6배로 깎는 규칙이 VT 단독보다
      **MDD 를 줄이고 샤프·Calmar 를 개선**한다.
- 분할: IS ≤ 2019-12-31 / OOS ≥ 2020-01-01. **H2 는 IS 표본 0**(gex_bn 이 2025-08~) → 사전 규약대로
        채점 최소 표본(IS 250거래일)을 못 채워 **등급 상한 `검증전`**, 숫자는 서술로만 보고한다.
- 등급: scripts/study_rule_audit.py grade() 와 같은 문턱(A=Bonferroni+IS·OOS 같은 방향, B=Bonferroni·구간 불일치,
        C=방향만 p<0.10, F=현행과 구별 안 됨, 검증전=표본 부족).
- 탐색(등급 대상 아님, `exploratory`): target 12·15%, 밴드 0·5·20%p, 주 1회 리밸런싱, 비용 5·15bp, 체결 1일 추가 지연,
        현금 이자 2%, max_w 1.5(연구 전용 — 실계좌 레버리지 금지), **GEX 부호 반전**(한국 부호 가정 반대 가능성,
        docs/desk_kb/derivs.md). **결과를 본 뒤 주 가설·파라미터를 바꾸지 않는다.**
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from screener import gex_vol_target as gv  # noqa: E402
from screener.vrp_filter import TRADING_DAYS, realized_vol  # noqa: E402

CSV = ROOT / "data" / "deriv" / "daily.csv"
OUT = ROOT / "reports" / "studies" / "2026-11-14_gex_vol_target.json"

M = 2
ALPHA = 0.05 / M
IS_END = "2019-12-31"
TARGET_VOL = 13.0
MAX_W = 1.0
BAND = 0.10
COST_BP = 10.0
GEX_SCALE = 0.6
BOOT = {"block": 20, "n_boot": 2000, "seed": 7}


def grade(p, subs: dict[str, float | None], n: int, n_is: int, min_n: int = 250,
          alpha: float = ALPHA) -> tuple[str, str]:
    """등급 — scripts/study_rule_audit.grade() 와 같은 문턱 + 사전 최소 표본(IS 250거래일) 확인."""
    if p is None or n_is < min_n:
        return "검증전", f"IS 표본 {n_is} < 최소 {min_n} (전체 {n})"
    if p < alpha:
        vals = [v for v in subs.values() if v is not None]
        if vals and all(np.sign(v) >= 0 for v in vals):
            return "A", f"Bonferroni 유의(p={p:.4f}) + IS·OOS 같은 방향"
        return "B", f"Bonferroni 유의(p={p:.4f}), 하위 구간 방향 불일치"
    if p < 0.10:
        return "C", f"방향만(p={p:.3f}, Bonferroni α={alpha:.4f} 미달)"
    return "F", f"현행과 구별 안 됨(p={p:.2f})"


def _r(x, nd=6):
    return None if x is None or (isinstance(x, float) and not np.isfinite(x)) else round(float(x), nd)


def _perf(bt: dict, mask: np.ndarray) -> dict:
    """마스크 구간 성과 + 회전율·비용 부담·평균 노출. 표본이 비면 값은 None(예외 없이)."""
    m = np.asarray(mask, dtype=bool) & np.isfinite(bt["ret"])
    rets = bt["ret"][m]
    p = {"n": int(rets.size), "years": None, "total_x": None, "cagr": None, "vol": None,
         "sharpe": None, "mdd": None, "calmar": None,
         "turnover": None, "cost_pct_yr": None, "avg_w": None, "time_in_mkt": None}
    p.update(gv.perf_metrics(rets))
    if rets.size:
        years = p.get("years") or 1e-9
        p["turnover"] = _r(gv.ann_turnover(bt["trade"][m], rets), 3)
        p["cost_pct_yr"] = _r(float(np.nansum(bt["cost"][m]) / years * 100.0), 3)
        p["avg_w"] = _r(float(np.mean(bt["held"][m])), 4)
        p["time_in_mkt"] = _r(float(np.mean(bt["held"][m] > 0.02)), 3)
    return p


def _rebal_yr(bt: dict, mask: np.ndarray) -> float:
    """연 리밸런싱 횟수(회전이 0보다 큰 날) — 비용·실행 부담 확인용."""
    m = np.asarray(mask, dtype=bool) & np.isfinite(bt["ret"])
    n = int(m.sum())
    return _r(float((bt["trade"][m] > 1e-12).sum() / (n / TRADING_DAYS)), 2) if n else None


def _yearly(bt: dict, dates: pd.Series, mask: np.ndarray) -> dict:
    m = np.asarray(mask, dtype=bool) & np.isfinite(bt["ret"])
    yr = pd.Series(bt["ret"][m], index=pd.to_datetime(dates[m])).groupby(lambda d: d.year)
    out = {}
    for y, s in yr:
        out[str(y)] = _r(float(np.prod(1.0 + s.to_numpy()) - 1.0), 4)
    return out


def _window(dates: pd.Series, lo: str | None, hi: str | None) -> np.ndarray:
    m = np.ones(len(dates), dtype=bool)
    if lo:
        m &= (dates >= lo).to_numpy()
    if hi:
        m &= (dates <= hi).to_numpy()
    return m


def _freeze_weekly(w_target: np.ndarray, dates: pd.Series) -> np.ndarray:
    """주 1회 리밸런싱용 — 금요일(마지막 거래일) 값으로 그 주 목표를 고정한다."""
    dow = pd.to_datetime(dates).dt.day_of_week.to_numpy()
    last = np.where(dow == 4)[0]
    if last.size == 0:
        return w_target
    out = np.full(w_target.shape, np.nan)
    own = np.nan
    for i in range(len(dates)):
        if dow[i] == 4 and np.isfinite(w_target[i]):
            own = w_target[i]
        out[i] = own
    return out


def run(csv: Path = CSV) -> dict:
    df = pd.read_csv(csv, parse_dates=["date"]).sort_values("date").reset_index(drop=True)
    df = df[["date", "k200_close", "gex_bn"]].dropna(subset=["k200_close"]).reset_index(drop=True)
    dates = df["date"]
    px = df["k200_close"].to_numpy(dtype=float)
    ret = np.full(px.size, np.nan)
    ret[1:] = px[1:] / px[:-1] - 1.0
    rv = realized_vol(px, window=20)                       # 연율 %, 앞 20칸 NaN
    gex = df["gex_bn"].to_numpy(dtype=float)

    start = int(np.argmax(np.isfinite(rv)))                # 첫 RV 가 나온 날부터 평가(모든 계열 공통)
    w_vt = gv.vol_target_weight(rv, target_vol=TARGET_VOL, max_w=MAX_W)
    w_gex = gv.target_weight(rv, gex, target_vol=TARGET_VOL, max_w=MAX_W, scale=GEX_SCALE)
    w_gex_inv = gv.target_weight(rv, gex, target_vol=TARGET_VOL, max_w=MAX_W, scale=GEX_SCALE, invert_gex=True)
    flip = gv.regime_flip(gex)

    bh = gv.backtest(ret, np.ones(px.size), cost_bp=0.0, band=0.0)
    matched = gv.backtest(ret, gv.expanding_mean(w_vt, min_obs=20), cost_bp=COST_BP, band=BAND)
    cash = gv.backtest(ret, np.zeros(px.size), cost_bp=0.0, band=0.0)
    vt = gv.backtest(ret, w_vt, cost_bp=COST_BP, band=BAND)
    vt_gross = gv.backtest(ret, w_vt, cost_bp=0.0, band=BAND)
    gex_bt = gv.backtest(ret, w_gex, cost_bp=COST_BP, band=BAND, force=flip)
    gex_inv = gv.backtest(ret, w_gex_inv, cost_bp=COST_BP, band=BAND, force=flip)

    eval_m = np.zeros(px.size, dtype=bool)
    eval_m[start:] = True
    is_m, oos_m = eval_m & _window(dates, None, IS_END), eval_m & _window(dates, "2020-01-01", None)
    gex_dates = dates[np.isfinite(gex)]
    gex_start = str(gex_dates.iloc[0].date()) if len(gex_dates) else None
    gex_m = eval_m & _window(dates, gex_start, None) if gex_start else np.zeros(px.size, dtype=bool)

    # ── H1: 변동성 타게팅 vs Buy & Hold ──
    b_full = gv.block_bootstrap_sharpe_diff(vt["ret"], bh["ret"], **BOOT)
    b_is = gv.block_bootstrap_sharpe_diff(vt["ret"][is_m], bh["ret"][is_m], **BOOT)
    b_oos = gv.block_bootstrap_sharpe_diff(vt["ret"][oos_m], bh["ret"][oos_m], **BOOT)
    h1_subs = {"is": b_is.get("diff"), "oos": b_oos.get("diff")}
    h1_grade, h1_why = grade(b_full.get("p_one"), h1_subs, int(np.isfinite(vt["ret"][eval_m]).sum()),
                             int(np.isfinite(vt["ret"][is_m]).sum()))
    b_matched = gv.block_bootstrap_sharpe_diff(vt["ret"], matched["ret"], **BOOT)

    # ── H2: GEX 결합 vs VT 단독 (GEX 표본 안에서만) ──
    b_h2 = gv.block_bootstrap_sharpe_diff(gex_bt["ret"][gex_m], vt["ret"][gex_m], **BOOT)
    perf_gex, perf_vt_w = _perf(gex_bt, gex_m), _perf(vt, gex_m)
    h2_grade, h2_why = grade(b_h2.get("p_one"), {"is": None, "oos": b_h2.get("diff")},
                             int(np.isfinite(gex_bt["ret"][gex_m]).sum()),
                             int(np.isfinite(gex_bt["ret"][gex_m & is_m]).sum()))
    n_gex = int(np.isfinite(gex).sum())
    short_days = int((gex < 0).sum())

    # ── 탐색(등급 밖) ──
    def variant(w, **kw):
        bt = gv.backtest(ret, w, **kw)
        return {"all": _perf(bt, eval_m), "is": _perf(bt, is_m), "oos": _perf(bt, oos_m),
                "sharpe_vs_bh": gv.block_bootstrap_sharpe_diff(bt["ret"], bh["ret"], **BOOT).get("diff")}

    expl = {
        "target_12": variant(gv.vol_target_weight(rv, 12.0, MAX_W), cost_bp=COST_BP, band=BAND),
        "target_15": variant(gv.vol_target_weight(rv, 15.0, MAX_W), cost_bp=COST_BP, band=BAND),
        "band_0": variant(w_vt, cost_bp=COST_BP, band=0.0),
        "band_0.05": variant(w_vt, cost_bp=COST_BP, band=0.05),
        "band_0.20": variant(w_vt, cost_bp=COST_BP, band=0.20),
        "weekly": variant(_freeze_weekly(w_vt, dates), cost_bp=COST_BP, band=BAND),
        "cost_5bp": variant(w_vt, cost_bp=5.0, band=BAND),
        "cost_15bp": variant(w_vt, cost_bp=15.0, band=BAND),
        "lag_2": variant(w_vt, cost_bp=COST_BP, band=BAND, lag=2),
        "cash_2pct": variant(w_vt, cost_bp=COST_BP, band=BAND, cash_rate=0.02),
        "max_w_1.5": variant(gv.vol_target_weight(rv, TARGET_VOL, 1.5), cost_bp=COST_BP, band=BAND),
        "gex_scale_0.5": variant(gv.target_weight(rv, gex, target_vol=TARGET_VOL, max_w=MAX_W, scale=0.5),
                                 cost_bp=COST_BP, band=BAND, force=flip),
        "gex_scale_0.75": variant(gv.target_weight(rv, gex, target_vol=TARGET_VOL, max_w=MAX_W, scale=0.75),
                                  cost_bp=COST_BP, band=BAND, force=flip),
    }
    # GEX 부호 반전 민감도(부호 가정이 틀렸을 때) — GEX 표본 안에서만 비교
    inv_perf = _perf(gex_inv, gex_m)

    return {
        "generated": datetime.now().strftime("%Y-%m-%d"),
        "id": "gex_vol_target",
        "title": "변동성 타게팅 + GEX 감마 국면 — K200 노출 비중만 조절",
        "label": "연구 전용 — 매매 지시 아님. 실계좌 레버리지·인버스 2027-04-15까지 금지(불변).",
        "prereg": {"m": M, "alpha_bonf": round(ALPHA, 5), "is_end": IS_END, "oos_start": "2020-01-01",
                   "target_vol": TARGET_VOL, "max_w": MAX_W, "band_pctp": BAND * 100,
                   "cost_bp_oneway": COST_BP, "cash_rate": 0.0, "gex_scale": GEX_SCALE,
                   "exec": "t일 종가 신호 → t+1일 종가-종가 수익에 적용(lag 1)", "boot": BOOT,
                   "data": "data/deriv/daily.csv", "rows": int(px.size),
                   "range": [str(dates.iloc[0].date()), str(dates.iloc[-1].date())],
                   "topic": "sizing", "topic_N_before": 0},
        "coverage": {"k200_close": int(np.isfinite(px).sum()), "gex_bn": n_gex,
                     "gex_range": [gex_start, str(gex_dates.iloc[-1].date()) if len(gex_dates) else None],
                     "gex_short_gamma_days": short_days, "eval_start": str(dates[start].date()),
                     "is_days": int(is_m.sum()), "oos_days": int(oos_m.sum()), "gex_days": int(gex_m.sum()),
                     "vkospi": "2026-10-21~ 18행 — 백테스트 미사용(표본 부족)"},
        "H1": {"grade": h1_grade, "why": h1_why, "p_one": _r(b_full.get("p_one"), 4),
               "sharpe_diff": _r(b_full.get("diff"), 3),
               "boot_is": {"diff": _r(b_is.get("diff"), 3), "p_one": _r(b_is.get("p_one"), 4)},
               "boot_oos": {"diff": _r(b_oos.get("diff"), 3), "p_one": _r(b_oos.get("p_one"), 4)},
               "vs_matched_sharpe": _r(b_matched.get("diff"), 3), "vs_matched_p": _r(b_matched.get("p_one"), 4)},
        "H2": {"grade": h2_grade, "why": h2_why, "p_one": _r(b_h2.get("p_one"), 4),
               "sharpe_diff": _r(b_h2.get("diff"), 3),
               "window": ([str(dates[gex_m].iloc[0].date()), str(dates[gex_m].iloc[-1].date())] if gex_m.any() else None),
               "vt": perf_vt_w, "gex": perf_gex, "mdd_delta": _r(perf_gex["mdd"] - perf_vt_w["mdd"], 4),
               "calmar_delta": _r((perf_gex.get("calmar") or 0) - (perf_vt_w.get("calmar") or 0), 3),
               "sign_inverted": inv_perf},
        "benchmarks": {"k200_bh": _perf(bh, eval_m), "matched_exposure": _perf(matched, eval_m),
                       "cash": _perf(cash, eval_m),
                       "k200_bh_is": _perf(bh, is_m), "k200_bh_oos": _perf(bh, oos_m),
                       "matched_is": _perf(matched, is_m), "matched_oos": _perf(matched, oos_m)},
        "main": {"vt_net": _perf(vt, eval_m), "vt_net_is": _perf(vt, is_m), "vt_net_oos": _perf(vt, oos_m),
                 "vt_gross": _perf(vt_gross, eval_m), "vt_yearly": _yearly(vt, dates, eval_m),
                 "vt_rebal_yr": _rebal_yr(vt, eval_m), "gex_rebal_yr": _rebal_yr(gex_bt, gex_m),
                 "bh_yearly": _yearly(bh, dates, eval_m),
                 "target_vol_realized": _r(gv.perf_metrics(vt["ret"][eval_m]).get("vol"), 4)},
        "grades": {"H1": h1_grade, "H2": h2_grade},
        "exploratory": expl,
        "meta": {"run_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                 "engine": "screener/gex_vol_target.py", "grades_doc": "A/B/C/F/검증전 — scripts/study_rule_audit.grade() 문턱"},
    }


def main(argv=None) -> int:
    out = run()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    h1, h2, m = out["H1"], out["H2"], out["main"]
    bh, mt = out["benchmarks"]["k200_bh"], out["benchmarks"]["matched_exposure"]
    print(f"[gex_vol_target] 평가 {out['coverage']['eval_start']}~  (gex_bn {out['coverage']['gex_range'][0]}~)")
    for name, p in (("K200 B&H", bh), ("동일노출", mt), ("VT(13%)", m["vt_net"])):
        print(f"  {name:9s} CAGR {p['cagr']*100:+6.2f}%  vol {p['vol']*100:5.2f}%  샤프 {p['sharpe']:5.2f}  "
              f"MDD {p['mdd']*100:7.2f}%  Calmar {p['calmar']:5.2f}  회전 {p['turnover']:6.2f}  비용 {p['cost_pct_yr']:.2f}%/년")
    print(f"  H1 샤프차 {h1['sharpe_diff']:+.2f} (p {h1['p_one']}) → {h1['grade']} · IS {h1['boot_is']['diff']:+.2f}"
          f" / OOS {h1['boot_oos']['diff']:+.2f}")
    print(f"  H2(GEX {out['coverage']['gex_days']}일) 샤프차 {h2['sharpe_diff']:+.2f} (p {h2['p_one']}) "
          f"MDDΔ {h2['mdd_delta']*100:+.2f}%p CalmarΔ {h2['calmar_delta']:+.2f} → {h2['grade']}")
    print(f"→ {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
