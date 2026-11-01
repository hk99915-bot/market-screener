"""유사 국면 경로 — 지수 −30%·반도체 대표주 −35% 하락 국면의 낙폭·기간·'−37% 도달 후' 경로 (퀀트, 2026-11-01, 기술통계·사후 탐색).

요청: 겸이 11/1 「전세계적으로 지금의 한국과 비슷한 추세가 있었는지, 그땐 어땠는지」 — 퀀트는 계산 가능한 것만.
정의(결과 보기 전 고정, 단 질문 자체가 현재 국면을 본 뒤라 사후 탐색):
  국면 = 지그재그 전환점. 하락 X%(지수 30·종목 35) 이상 → 고점·저점 확정, 저점 대비 +X% 반등하면 다음 고점 탐색 재개.
         (민감도: 엄격 정의 = 이전 고점 회복 전까지는 한 국면)
  앵커 = 국면 고점 대비 처음 종가가 −L% 이하가 된 날(L = 37 공통, 종목은 현재 낙폭 수준 추가).
  앵커 이후: 3·6·12개월(달력, 직전 거래일 종가) 수익률 · 추가 하락 = 앵커 이후 국면 저점까지 min/앵커−1
             · 회복 = 앵커 이후 처음 종가 ≥ 국면 고점인 날(없으면 미회복, 우측 절단).
  이익 선행: SEC companyfacts MU 분기 영업이익(op) 정점(±4분기 최대 & 이후 −30% 이상 감소) vs 그 전후 주가 정점.
입력: yfinance 일간 조정 종가(period=max, 실행일 다운로드) · 대조 data/hist/kr_index_daily.parquet(KOSPI 2010~)·data/kr_prices.parquet(2025-09~)
      · reports/detail/KR/{005930,000660}.json financials(2024Q3~) · SEC companyfacts(환경변수 SEC_USER_AGENT 필요, 없으면 건너뜀)
출력: reports/studies/2026-11-01_history_paths.json
사용: SEC_USER_AGENT="market-screener noreply@anthropic.com" python3 scripts/study_history_paths.py
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "reports/studies/2026-11-01_history_paths.json"

GROUPS = {
    "index": {"thr": 0.30, "tickers": {"^KS11": "코스피", "^TWII": "대만 가권", "^N225": "닛케이225"}},
    "semi": {"thr": 0.35, "tickers": {"005930.KS": "삼성전자", "000660.KS": "SK하이닉스", "2330.TW": "TSMC",
                                      "MU": "마이크론", "^SOX": "필라델피아 반도체"}},
}
ANCHORS = {"index": [0.37, 0.40], "semi": [0.37, 0.51]}   # 0.40 = 코스피 10/26 장중국면 최저(종가), 0.51 = 하이닉스 현재
SUBSETS = {
    "index": {"KR": lambda r: r["tk"] == "^KS11", "exN225": lambda r: r["tk"] != "^N225"},
    "semi": {"KR": lambda r: r["tk"] in ("005930.KS", "000660.KS"), "exMU": lambda r: r["tk"] != "MU",
             "since2000": lambda r: r["peak"] >= "2000-01-01"},
}
HORIZONS = {"3m": 3, "6m": 6, "12m": 12}
JUMP = 0.40   # |일간| ≥ 40% 는 데이터 점검 표기
CUR_START = "2026-01-01"   # 이 날 이후 고점 국면 = 현재 국면 → 과거 분포에서 제외


def load(tk: str) -> pd.Series:
    import yfinance as yf
    h = yf.Ticker(tk).history(period="max", auto_adjust=True)["Close"].dropna()
    h.index = pd.to_datetime(h.index.tz_localize(None).date)
    return h[h > 0]


def zigzag(px: pd.Series, thr: float) -> list[dict]:
    """하락 thr 이상 국면. 반등 thr 이상이면 저점 확정 후 새 고점 탐색."""
    eps, i_pk, mode, i_tr = [], 0, "up", None
    v = px.values
    for i in range(1, len(v)):
        if mode == "up":
            if v[i] > v[i_pk]:
                i_pk = i
            elif v[i] <= v[i_pk] * (1 - thr):
                mode, i_tr = "down", i
        else:
            if v[i] < v[i_tr]:
                i_tr = i
            elif v[i] >= v[i_tr] * (1 + thr):
                eps.append((i_pk, i_tr, True))
                mode, i_pk = "up", i
    if mode == "down":
        eps.append((i_pk, i_tr, False))   # 진행 중(저점 미확정)
    return [{"i_pk": a, "i_tr": b, "closed": c} for a, b, c in eps]


def strict(px: pd.Series, thr: float) -> list[dict]:
    """엄격: 이전 고점 회복 전까지 한 국면."""
    eps, i_pk, i, v = [], 0, 1, px.values
    while i < len(v):
        if v[i] >= v[i_pk]:
            i_pk = i
            i += 1
            continue
        j = i
        while j < len(v) and v[j] < v[i_pk]:
            j += 1
        seg = v[i_pk:j]
        i_tr = i_pk + int(np.argmin(seg))
        if v[i_tr] <= v[i_pk] * (1 - thr):
            eps.append({"i_pk": i_pk, "i_tr": i_tr, "closed": j < len(v)})
        if j >= len(v):
            break
        i_pk, i = j, j + 1
    return eps


def fwd(px: pd.Series, d0: pd.Timestamp, months: int):
    t = d0 + pd.DateOffset(months=months)
    if t > px.index[-1]:
        return None
    return float(px.loc[:t].iloc[-1] / px.loc[d0] - 1)


def describe(px: pd.Series, ep: dict, anchors: list[float]) -> dict:
    idx, v = px.index, px.values
    pk, tr = ep["i_pk"], ep["i_tr"]
    rec = next((k for k in range(tr, len(v)) if v[k] >= v[pk]), None)
    out = {"peak": str(idx[pk].date()), "peak_px": round(float(v[pk]), 2),
           "trough": str(idx[tr].date()), "dd": round(float(v[tr] / v[pk] - 1), 4),
           "days_to_trough": int((idx[tr] - idx[pk]).days), "closed": ep["closed"],
           "recovered": str(idx[rec].date()) if rec is not None else None,
           "months_peak_to_recover": round((idx[rec] - idx[pk]).days / 30.44, 1) if rec is not None else None,
           "left_censored": pk == 0, "anchors": {}}
    for L in anchors:
        hit = next((k for k in range(pk, tr + 1) if v[k] <= v[pk] * (1 - L)), None)
        if hit is None:
            continue
        d0 = idx[hit]
        a = {"date": str(d0.date()), "days_from_peak": int((d0 - idx[pk]).days),
             "further_dd": round(float(v[tr] / v[hit] - 1), 4),
             "days_to_trough": int((idx[tr] - d0).days),
             "months_to_recover": round((idx[rec] - d0).days / 30.44, 1) if rec is not None else None}
        for h, m in HORIZONS.items():
            r = fwd(px, d0, m)
            a[h] = None if r is None else round(r, 4)
        # 12개월 안 최대 역행(국면 저점과 별도)
        w = px.loc[d0:d0 + pd.DateOffset(months=12)]
        a["mae_12m"] = round(float(w.min() / px.loc[d0] - 1), 4)
        out["anchors"][f"{int(L * 100)}"] = a
    return out


def summarize(rows: list[dict], key: str) -> dict:
    A = [r["anchors"][key] for r in rows if key in r["anchors"] and r["closed"] and r["peak"] < CUR_START]
    s = {"n": len(A)}
    for f in ("3m", "6m", "12m", "further_dd", "mae_12m"):
        xs = [a[f] for a in A if a.get(f) is not None]
        if xs:
            s[f] = {"n": len(xs), "median": round(float(np.median(xs)), 4), "min": round(min(xs), 4),
                    "max": round(max(xs), 4), "pos_share": round(float(np.mean([x > 0 for x in xs])), 3)}
    fd = [a["further_dd"] for a in A]
    for cut in (0.10, 0.20, 0.30):
        s[f"further_le_-{int(cut * 100)}"] = sum(x <= -cut for x in fd)
    mr = [a["months_to_recover"] for a in A]
    s["months_to_recover"] = {"n_recovered": sum(x is not None for x in mr), "median": float(np.median([x for x in mr if x is not None])) if any(x is not None for x in mr) else None}
    return s


def data_checks(px: dict) -> dict:
    out = {}
    for tk, s in px.items():
        r = s.pct_change().dropna()
        big = r[r.abs() >= JUMP]
        out[tk] = {"first": str(s.index[0].date()), "last": str(s.index[-1].date()), "n": len(s),
                   "jumps_ge_40pct": {str(k.date()): round(float(x), 3) for k, x in big.items()}}
    # 저장소 대조
    try:
        k = pd.read_parquet(ROOT / "data/hist/kr_index_daily.parquet")
        k = k[k.symbol == "KOSPI"].set_index("date")["close"]
        k.index = pd.to_datetime(k.index)
        j = pd.concat([k, px["^KS11"]], axis=1, join="inner").dropna()
        out["repo_vs_yf_KOSPI"] = {"n": len(j), "max_abs_rel_diff": round(float((j.iloc[:, 0] / j.iloc[:, 1] - 1).abs().max()), 5),
                                   "range": [str(j.index[0].date()), str(j.index[-1].date())]}
        kp = pd.read_parquet(ROOT / "data/kr_prices.parquet")
        for tk in ("005930.KS", "000660.KS"):
            x = kp[kp.yf == tk].set_index("date")["close"]
            x.index = pd.to_datetime(x.index)
            j = pd.concat([x, px[tk]], axis=1, join="inner").dropna()
            rr = j.pct_change().dropna()
            out[f"repo_vs_yf_{tk}"] = {"n": len(j), "ret_corr": round(float(rr.corr().iloc[0, 1]), 4),
                                       "max_abs_rel_diff_level": round(float((j.iloc[:, 0] / j.iloc[:, 1] - 1).abs().max()), 4)}
    except Exception as e:  # noqa: BLE001
        out["repo_check_error"] = str(e)
    return out


def current(px: pd.Series) -> dict:
    i_pk = int(np.argmax(px.values[-600:])) + len(px) - min(600, len(px))
    pk = px.index[i_pk]
    w = px.iloc[i_pk:]
    return {"peak": str(pk.date()), "peak_px": round(float(px.iloc[i_pk]), 2), "last": str(px.index[-1].date()),
            "last_px": round(float(px.iloc[-1]), 2), "dd_now": round(float(px.iloc[-1] / px.iloc[i_pk] - 1), 4),
            "dd_min": round(float(w.min() / px.iloc[i_pk] - 1), 4), "min_date": str(w.idxmin().date()),
            "days_since_peak": int((px.index[-1] - pk).days)}


def placement(px: pd.Series, cur: dict, L: float, hist: list[dict]) -> dict:
    """현재 국면(최근 고점 기준)을 과거 앵커 분포에 찍는다. hist = 같은 그룹 과거 앵커 레코드."""
    pk = pd.Timestamp(cur["peak"])
    w = px.loc[pk:]
    hit = w[w <= w.iloc[0] * (1 - L)]
    if hit.empty:
        return {"reached": False}
    d0 = hit.index[0]
    after = px.loc[d0:]
    fd_now = float(after.min() / px.loc[d0] - 1)
    r3 = fwd(px, d0, 3)
    hd = [a["days_from_peak"] for a in hist]
    hf = [a["further_dd"] for a in hist]
    h3 = [a["3m"] for a in hist if a.get("3m") is not None]
    out = {"anchor_date": str(d0.date()), "days_from_peak": int((d0 - pk).days),
           "hist_days_from_peak_median": float(np.median(hd)), "faster_than_share": round(float(np.mean([x > (d0 - pk).days for x in hd])), 3),
           "further_dd_so_far": round(fd_now, 4), "ret_since_anchor": round(float(px.iloc[-1] / px.loc[d0] - 1), 4),
           "ret_3m_realized": None if r3 is None else round(r3, 4),
           "hist_3m_pct_rank": None if r3 is None else round(float(np.mean([x <= r3 for x in h3])), 3),
           "hist_further_dd_beyond_now": {f"le_{int(c * 100)}": sum(x <= -c for x in hf) for c in (0.10, 0.20, 0.30)},
           "hist_n": len(hist),
           "hist_already_exceeded_now_share": round(float(np.mean([x <= fd_now for x in hf])), 3)}
    return out


def mu_earnings_lead(px_mu: pd.Series) -> dict:
    ua = os.environ.get("SEC_USER_AGENT")
    if not ua:
        return {"skipped": "SEC_USER_AGENT 없음"}
    from screener import sec
    m = sec.ticker_map()
    rows = sec.parse(sec._get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{m['MU']:010d}.json"))
    op = pd.DataFrame(rows)
    op = op[op.item == "op"].assign(end=lambda d: pd.to_datetime(d.end)).sort_values("end").drop_duplicates("end").set_index("end")["value"]
    peaks = []
    vals = op.values
    for i in range(len(vals)):
        lo, hi = max(0, i - 4), min(len(vals), i + 5)
        if vals[i] <= 0 or vals[i] < vals[lo:hi].max():
            continue
        after = vals[i + 1:i + 7]
        if len(after) and after.min() <= vals[i] * 0.7:
            q_end = op.index[i]
            w = px_mu.loc[q_end - pd.DateOffset(months=18):q_end + pd.DateOffset(months=6)]
            p_dt = w.idxmax()
            # 이후 주가 저점 vs 이익 저점
            nxt = op.iloc[i:i + 12]
            tr_q = nxt.idxmin()
            pw = px_mu.loc[q_end:tr_q + pd.DateOffset(months=6)]
            peaks.append({"op_peak_q_end": str(q_end.date()), "op_peak_usd_bn": round(vals[i] / 1e9, 3),
                          "op_trough_q_end": str(tr_q.date()), "op_trough_usd_bn": round(float(nxt.min()) / 1e9, 3),
                          "px_peak": str(p_dt.date()), "lead_months_vs_q_end": round((q_end - p_dt).days / 30.44, 1),
                          "px_dd_peak_to_low": round(float(pw.min() / w.max() - 1), 3), "px_low": str(pw.idxmin().date()),
                          "px_low_lead_vs_op_trough_months": round((tr_q - pw.idxmin()).days / 30.44, 1)})
    return {"src": "SEC companyfacts MU OperatingIncomeLoss 분기(screener.sec.parse)", "n_quarters": len(op),
            "range": [str(op.index[0].date()), str(op.index[-1].date())],
            "rule": "op 정점 = ±4분기 최대 & 이후 6분기 안 −30% 이하, 주가 정점 = 분기말 −18개월~+6개월 창 최대",
            "latest": {str(k.date()): round(float(x) / 1e9, 3) for k, x in op.iloc[-6:].items()}, "peaks": peaks}


def kr_current_earnings() -> dict:
    out = {}
    for code in ("005930", "000660"):
        q = json.loads((ROOT / f"reports/detail/KR/{code}.json").read_text())["financials"]["quarters"]
        out[code] = {"unit": "억원", "op": {r["period"]: r["op"] for r in q}}
    return out


def main() -> None:
    px = {}
    for g in GROUPS.values():
        for tk in g["tickers"]:
            px[tk] = load(tk)
    res = {"asof": str(max(s.index[-1] for s in px.values()).date()), "run_date": str(date.today()),
           "grade": "해당 없음(기술통계·사후 탐색) — 판단 근거 상한 C",
           "grades": {"유사 국면 경로(기술통계)": "해당 없음(상한 C)"},
           "prereg": {"m": None, "alpha_bonf": None, "is_end": None, "cost": "해당 없음(기술통계, 수익률은 비용·배당 미반영 조정 종가)",
                      "definitions": {"episode": "지그재그 하락 X% → 반등 X% 시 저점 확정", "X": {"index": 0.30, "semi": 0.35},
                                      "anchors": ANCHORS, "horizons_months": HORIZONS, "sensitivity": "엄격(고점 회복 전 한 국면)"}},
           "survivorship": "생존 표본 — 오늘 살아남은 대표 지수·종목만(망한 반도체·사라진 시장 없음). 회복 통계는 낙관 쪽으로 치우침",
           "dsr_pbo": "해당 없음(전략 선택 아님)",
           "data_checks": data_checks(px), "current": {tk: current(s) for tk, s in px.items()},
           "episodes": {}, "episodes_strict": {}, "summary": {}, "summary_strict": {}}
    for gname, g in GROUPS.items():
        rows_all, rows_s = [], []
        for tk, nm in g["tickers"].items():
            for ep in zigzag(px[tk], g["thr"]):
                r = describe(px[tk], ep, ANCHORS[gname])
                r.update({"tk": tk, "name": nm})
                rows_all.append(r)
            for ep in strict(px[tk], g["thr"]):
                r = describe(px[tk], ep, ANCHORS[gname])
                r.update({"tk": tk, "name": nm})
                rows_s.append(r)
        res["episodes"][gname] = rows_all
        res["episodes_strict"][gname] = rows_s
        for L in ANCHORS[gname]:
            key = f"{int(L * 100)}"
            res["summary"][f"{gname}_{key}"] = summarize(rows_all, key)
            res["summary_strict"][f"{gname}_{key}"] = summarize(rows_s, key)
            for sub, keep in SUBSETS[gname].items():
                res["summary"][f"{gname}_{key}_{sub}"] = summarize([r for r in rows_all if keep(r)], key)
            res["summary"][f"{gname}_{key}_by_ticker"] = {tk: summarize([r for r in rows_all if r["tk"] == tk], key) for tk in g["tickers"]}
    def hist_of(gname, key, keep=lambda r: True):
        return [r["anchors"][key] for r in res["episodes"][gname] if key in r["anchors"] and r["closed"] and r["peak"] < CUR_START and keep(r)]
    res["placement"] = {}
    for tk, gname, L in (("^KS11", "index", 0.37), ("005930.KS", "semi", 0.37), ("000660.KS", "semi", 0.37), ("000660.KS", "semi", 0.51)):
        key = f"{int(L * 100)}"
        res["placement"][f"{tk}_{key}"] = {
            "pool": placement(px[tk], res["current"][tk], L, hist_of(gname, key)),
            "KR": placement(px[tk], res["current"][tk], L, hist_of(gname, key, SUBSETS[gname]["KR"]))}
    res["earnings_lead_MU"] = mu_earnings_lead(px["MU"])
    res["earnings_KR_now"] = kr_current_earnings()
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1))
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
