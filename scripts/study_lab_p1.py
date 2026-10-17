"""가설 연구소 P1 — 실적 둔화 속 추세 유지 종목 백테스트 → reports/studies/lab_p1.{json,md} + lab_p1_screen.json.

§0 사전등록: docs/valuation_notes/2026-10-17_lab_p1_prereg.md (결과보다 먼저 커밋 b7ed1576). 정의를 여기서 바꾸지 않는다.
  python3 scripts/study_lab_p1.py [--data-root DIR]   # DIR = data/·universe/ 가 있는 체크아웃(기본: 이 저장소)
영향 범위: 연구 전용 — 워크플로·탭·알림은 이 파일을 import 하지 않는다. 롤백: git revert.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

KST = timezone(timedelta(hours=9))
OUT = ROOT / "reports" / "studies"
H_MAIN, H_SHORT = 60, (1, 3, 10)
COST = 0.003
MCAP_MIN = 5000.0          # 억원
SPLIT = "2024-01-01"
M = 6
ALPHA = 0.05 / M
MIN_MONTHS, MIN_EVENTS, MIN_P2 = 12, 100, 8
LEAD = {1: (5, 16, 0), 2: (8, 15, 0), 3: (11, 15, 0), 4: (4, 1, 1)}   # 분기 → 확정 시점(월, 일, +연)


def known_date(year: int, q: int) -> date:
    mo, d, dy = LEAD[q]
    return date(year + dy, mo, d)


# ───────── 통계 ─────────
def _p2(t: float) -> float:
    return math.erfc(abs(t) / math.sqrt(2))


def nw_t(x, lag: int = 2) -> tuple[float | None, float | None]:
    x = np.asarray([v for v in x if v is not None and not np.isnan(v)], float)
    n = len(x)
    if n < 6:
        return None, None
    e = x - x.mean()
    s = (e @ e) / n
    for k in range(1, lag + 1):
        s += 2 * (1 - k / (lag + 1)) * (e[k:] @ e[:-k]) / n
    se = math.sqrt(max(s, 1e-18) / n)
    t = float(x.mean() / se)
    return round(t, 2), round(_p2(t), 5)


def welch_t(a, b) -> tuple[float | None, float | None]:
    a, b = np.asarray(a, float), np.asarray(b, float)
    if len(a) < 2 or len(b) < 2:
        return None, None
    se = math.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b))
    t = float((a.mean() - b.mean()) / se)
    return round(t, 2), round(_p2(t), 5)


def simple_t(x) -> tuple[float | None, float | None]:
    return nw_t(x, lag=0)


# ───────── 데이터 ─────────
def load_fin() -> pd.DataFrame:
    from screener import fin
    q = fin.all_quarterly().to_pandas()
    q = q[["code", "year", "q", "op", "revenue"]].copy()
    q["idx"] = q["year"] * 4 + q["q"] - 1
    q = q.sort_values(["code", "idx"])
    def lagged(k: int, col: str) -> pd.Series:
        p = q[["code", "idx", col]].copy()
        p["idx"] = p["idx"] + k
        return q.merge(p, on=["code", "idx"], how="left", suffixes=("", "_x"))[f"{col}_x"].values
    q["op4"] = lagged(4, "op")
    q["op1"] = lagged(1, "op")
    q["rev4"] = lagged(4, "revenue")
    nxt = q[["code", "idx", "op", "op4"]].copy()
    nxt["idx"] = nxt["idx"] - 1
    q = q.merge(nxt.rename(columns={"op": "op_n", "op4": "op4_n"}), on=["code", "idx"], how="left")
    q["yoy"] = np.where(q["op4"].abs() > 0, (q["op"] - q["op4"]) / q["op4"].abs(), np.nan)
    q["yoy_n"] = np.where(q["op4_n"].abs() > 0, (q["op_n"] - q["op4_n"]) / q["op4_n"].abs(), np.nan)
    q["known"] = [known_date(int(y), int(k)) for y, k in zip(q["year"], q["q"])]
    return q


def latest_fin(q: pd.DataFrame, d: date) -> pd.DataFrame:
    """신호일 d 에 확정된 가장 최근 분기(종목별). 미래정보 가드: known ≤ d."""
    k = q[q["known"] <= d]
    return k.sort_values("idx").groupby("code").tail(1).set_index("code")


def load_prices(data_root: Path) -> pd.DataFrame:
    from screener import prices
    px = prices.load_kr(hist_from=2020, path=data_root / "kr_prices.parquet").to_pandas()
    px["code"] = px["yf"].str[:6]
    px = px[px["code"].str[-1] == "0"]              # 보통주
    w = px.pivot_table(index="date", columns="code", values="close", aggfunc="last").sort_index()
    w.index = pd.to_datetime(w.index)
    return w


def shares_ref(data_root: Path, uni_root: Path) -> tuple[pd.Series, pd.DataFrame]:
    from screener import accum
    fl = accum.load_store(root=data_root / "flows")
    f0 = fl.sort_values("date").groupby("code").head(1)
    s = (f0.set_index("code")["mcap"] * 1e8 / f0.set_index("code")["close"]).rename("sh")
    ks = pd.read_csv(uni_root / "kr_shares.csv", dtype={"code": str})
    ks = ks.sort_values(["year", "reprt"]).groupby("code").tail(1).set_index("code")["out_total"]
    s = s.combine_first(ks)
    return s[s > 0], fl


def kospi() -> pd.DataFrame:
    from screener.regime_tag import classify
    ix = pd.read_parquet(ROOT_DATA / "hist" / "kr_index_daily.parquet")
    k = ix[ix["symbol"] == "KOSPI"][["date", "close"]].dropna().copy()
    k["date"] = pd.to_datetime(k["date"])
    k = k.sort_values("date").set_index("date")
    c = k["close"].astype(float).tolist()
    k["regime"] = [(classify(c[max(0, i - 260):i + 1]) or {}).get("l") for i in range(len(c))]
    return k


def sox20() -> pd.Series:
    from screener import hist
    s = hist.load("^SOX", root=ROOT_DATA / "hist").to_pandas()
    s["date"] = pd.to_datetime(s["date"])
    s = s.sort_values("date").set_index("date")["close"].astype(float)
    return s / s.shift(20) - 1


# ───────── 백테스트 ─────────
def month_firsts(idx: pd.DatetimeIndex, start: str, end: str) -> list[pd.Timestamp]:
    s = pd.Series(idx, index=idx)
    s = s[(s >= start) & (s <= end)]
    return list(s.groupby([s.dt.year, s.dt.month]).first())


def fwd(w: pd.DataFrame, i: int, codes: list[str], h: int) -> pd.Series:
    """t=i 신호 → t+1 종가 진입, t+1+h 종가 청산(끊기면 마지막 종가). 왕복 비용 차감."""
    if i + 1 + h >= len(w):
        return pd.Series(dtype=float)
    ent = w.iloc[i + 1][codes]
    seg = w.iloc[i + 1:i + 2 + h][codes].ffill()
    ex = seg.iloc[-1]
    r = ex / ent - 1 - COST
    return r[ent.notna() & (ent > 0)].dropna()


def kret(k: pd.DataFrame, dates: pd.DatetimeIndex, i: int, h: int) -> float | None:
    kc = k["close"].reindex(dates).ffill()
    if i + 1 + h >= len(dates):
        return None
    return float(kc.iloc[i + 1 + h] / kc.iloc[i + 1] - 1)


def build(q, w, sh, k, sx, fl) -> tuple[pd.DataFrame, pd.DataFrame]:
    dates = w.index
    ma60 = w.rolling(60, min_periods=60).mean()
    from screener import accum
    pen = None
    if fl is not None and len(fl):
        names = accum.load_names(root=ROOT_DATA / "flows")
        d = accum.features(accum.add_returns(fl))
        d = accum.flags(d, accum.eligible(d, names))
        pen = d[["date", "code", "sig_pen", "mcap"]].copy()
        pen["date"] = pd.to_datetime(pen["date"])
    rows, evs = [], []
    for t in month_firsts(dates, "2021-06-01", str(dates[-1].date())):
        i = dates.get_loc(t)
        if i + 1 + H_MAIN >= len(dates):
            break
        px = w.iloc[i]
        mc = (px * sh.reindex(px.index)) / 1e8
        ok = px.notna() & (ma60.iloc[i].notna()) & (mc >= MCAP_MIN)
        f = latest_fin(q, t.date())
        u = f.reindex(px.index[ok])
        u = u[u["op"].notna() & u["yoy"].notna()]
        above = px.reindex(u.index) > ma60.iloc[i].reindex(u.index)
        u = u[above]
        pos = u["op"] > 0
        g = {"P1": u.index[pos & (u["yoy"] <= 0)],
             "HI": u.index[pos & (u["yoy"] > 1.0)],
             "ALLMA": u.index}   # 사후 서술용 기준선(검정 밖): 같은 유니버스·60일선 위 전체 동일가중
        p1 = u.loc[g["P1"]]
        tmask = (p1["op"] > p1["op1"]) & (p1["revenue"] > p1["rev4"])
        g["P1T"] = p1.index[tmask.fillna(False)]
        g["P1N"] = p1.index[~tmask.fillna(False)]
        g["P1O"] = p1.index[(p1["yoy_n"] > 0).fillna(False)]
        if pen is not None:
            pp = pen[(pen["date"] == t) & (pen["sig_pen"] == True) & (pen["mcap"] >= MCAP_MIN)]  # noqa: E712
            g["L2"] = pd.Index([c for c in pp["code"] if c[-1] == "0" and c in w.columns])
        sxv = sx[sx.index < t]
        row = {"date": t, "regime": k["regime"].reindex([t]).ffill().iloc[0] if t in k.index else None,
               "sox20": float(sxv.iloc[-1]) if len(sxv) else None, "universe": int(len(u))}
        km = kret(k, dates, i, H_MAIN)
        for name, codes in g.items():
            codes = list(codes)
            row[f"n_{name}"] = len(codes)
            if not codes:
                continue
            r = fwd(w, i, codes, H_MAIN)
            if len(r) == 0:
                continue
            row[f"r_{name}"] = float(r.mean())
            row[f"x_{name}"] = float(r.mean() - km)
            if name == "P1":
                for h in H_SHORT:
                    rs = fwd(w, i, codes, h)
                    row[f"r{h}_P1"] = float(rs.mean())
                for c, v in r.items():
                    evs.append({"date": t, "code": c, "r60": float(v), "x60": float(v - km), "yoy": float(u.loc[c, "yoy"])})
        rows.append(row)
    return pd.DataFrame(rows), pd.DataFrame(evs)


def sub(df: pd.DataFrame, col: str) -> dict:
    x = df[col].dropna()
    return {"months": int(len(x)), "mean": round(float(x.mean()), 4) if len(x) else None}


def grade(t, p, subs: list, months: int, events: int, cap_b: bool = False, min_m: int = MIN_MONTHS) -> str:
    if months < min_m or events < MIN_EVENTS or p is None:
        return "검증전"
    sign = 1 if t > 0 else -1
    rev = "" if sign > 0 else "(역방향)"
    if p < ALPHA:
        same = all(s is not None and np.sign(s) == sign for s in subs)
        return ("A" if same and not cap_b else "B") + rev
    if p < 0.10:
        return "C" + rev
    return "F"


def evaluate(c: pd.DataFrame) -> list[dict]:
    c = c.copy()
    c["is"] = c["date"] < SPLIT
    c["bear"] = c["regime"].isin(["조정", "하락"])
    c["d_T1"] = c["x_P1"] - c["x_HI"]
    c["d_T4"] = c["r10_P1"] - c["r3_P1"]
    c["d_T5"] = c["x_P1T"] - c["x_P1N"]
    out = []

    def pack(tid, label, col, t, p, ev, cap_b=False, extra=None):
        x = c[col].dropna()
        subs = [sub(c[c["is"]], col), sub(c[~c["is"]], col), sub(c[c["bear"]], col)]
        r = {"id": tid, "label": label, "months": int(len(x)), "events": int(ev),
             "mean": round(float(x.mean()), 4) if len(x) else None,
             "median": round(float(x.median()), 4) if len(x) else None, "t": t, "p": p,
             "is": subs[0], "oos": subs[1], "bear": subs[2]}
        r["grade"] = grade(t, p, [s["mean"] for s in subs], r["months"], ev, cap_b) if extra is None else extra
        out.append(r)

    t, p = nw_t(c["d_T1"].dropna())
    pack("T1", "P1 60일 초과 − 고성장(YoY>+100%) 60일 초과", "d_T1", t, p, min(c["n_P1"].sum(), c["n_HI"].sum()))
    t, p = nw_t(c["x_P1"].dropna())
    pack("T2", "P1 60일 KOSPI 대비 순초과", "x_P1", t, p, c["n_P1"].sum())
    hi = c[(c["sox20"] > 0.05) & c["x_P1"].notna()]["x_P1"]
    lo = c[(c["sox20"] <= 0.0) & c["x_P1"].notna()]["x_P1"]
    t, p = welch_t(hi, lo)
    g3 = "검증전" if min(len(hi), len(lo)) < MIN_P2 else grade(t, p, [t], len(hi) + len(lo), c["n_P1"].sum())
    pack("T3", "P2: SOX20>+5% 달 − SOX20≤0% 달 (P1 60일 초과)", "x_P1", t, p, c["n_P1"].sum(), extra=g3)
    out[-1].update({"sox_hi": {"months": int(len(hi)), "mean": round(float(hi.mean()), 4) if len(hi) else None},
                    "sox_lo": {"months": int(len(lo)), "mean": round(float(lo.mean()), 4) if len(lo) else None},
                    "note": "평균 = SOX>+5% 달 − SOX≤0% 달. 하위 구간 미산출(그룹당 월 수 부족) — 등급은 Welch p 와 표본만.",
                    "mean": round(float(hi.mean() - lo.mean()), 4) if len(hi) and len(lo) else None, "median": None,
                    "months": int(len(hi) + len(lo)),
                    "is": {"months": 0, "mean": None}, "oos": {"months": 0, "mean": None}, "bear": {"months": 0, "mean": None}})
    t, p = simple_t(c["d_T4"].dropna())
    pack("T4", "P3: P1 10일 순수익 − 3일 순수익", "d_T4", t, p, c["n_P1"].sum())
    out[-1]["by_h"] = {f"h{h}": round(float(c[f"r{h}_P1"].mean()), 4) for h in H_SHORT}
    t, p = nw_t(c["d_T5"].dropna())
    pack("T5", "P1-T(QoQ 개선+매출 YoY>0) − P1 비-T, 60일 초과", "d_T5", t, p, min(c["n_P1T"].sum(), c["n_P1N"].sum()))
    if "x_L2" in c:
        x = c["x_L2"].dropna()
        t, p = nw_t(x)
        pack("T6", "L2 연기금 20일 순매수 상위10%(시총≥5천억) 60일 초과", "x_L2", t, p, c.loc[x.index, "n_L2"].sum(), cap_b=True)
    return out


def scenarios(c: pd.DataFrame, ev: pd.DataFrame) -> dict:
    def q(x):
        x = pd.Series(x).dropna()
        if not len(x):
            return None
        return {"n": int(len(x)), "p10": round(float(x.quantile(.1)), 4), "median": round(float(x.median()), 4),
                "p90": round(float(x.quantile(.9)), 4), "mean": round(float(x.mean()), 4), "neg_share": round(float((x < 0).mean()), 3)}
    bear = c["regime"].isin(["조정", "하락"])
    return {"portfolio_r60": q(c["r_P1"]), "portfolio_x60": q(c["x_P1"]),
            "portfolio_r60_up": q(c.loc[~bear, "r_P1"]), "portfolio_r60_bear": q(c.loc[bear, "r_P1"]),
            "portfolio_x60_up": q(c.loc[~bear, "x_P1"]), "portfolio_x60_bear": q(c.loc[bear, "x_P1"]),
            "stock_r60": q(ev["r60"]) if len(ev) else None}


def compare(c: pd.DataFrame) -> dict:
    o = {}
    for g in ("P1", "HI", "ALLMA", "P1T", "P1N", "P1O", "L2"):
        if f"x_{g}" in c:
            x = c[f"x_{g}"].dropna()
            o[g] = {"months": int(len(x)), "x60_mean": round(float(x.mean()), 4), "x60_median": round(float(x.median()), 4),
                    "avg_names": round(float(c[f"n_{g}"].mean()), 1)}
    ov = c.dropna(subset=["x_L2", "x_P1"]) if "x_L2" in c else pd.DataFrame()
    if len(ov):
        o["overlap_L2_vs_P1"] = {"months": int(len(ov)), "from": str(ov["date"].min().date()),
                                 "P1": round(float(ov["x_P1"].mean()), 4), "L2": round(float(ov["x_L2"].mean()), 4)}
    if "x_P1O" in c:
        o["turnaround_value"] = {"oracle_minus_P1": round(float((c["x_P1O"] - c["x_P1"]).mean()), 4),
                                 "proxyT_minus_P1": round(float((c["x_P1T"] - c["x_P1"]).mean()), 4),
                                 "note": "P1-O 는 미래정보 사용·실행 불가 — 턴어라운드를 완벽히 맞혔을 때의 상한"}
    return o


def screen(q, w, fl, asof: pd.Timestamp, names: dict) -> dict:
    i = w.index.get_loc(asof)
    ma = w.rolling(60, min_periods=60).mean().iloc[i]
    px = w.iloc[i]
    f = latest_fin(q, asof.date())
    mc = fl[pd.to_datetime(fl["date"]) == asof].set_index("code")["mcap"]
    rows = []
    for c in f.index:
        if c not in px.index or pd.isna(px[c]) or pd.isna(ma.get(c)) or c not in mc.index:
            continue
        r = f.loc[c]
        if not (r["op"] > 0 and pd.notna(r["yoy"]) and r["yoy"] <= 0 and px[c] > ma[c] and mc[c] >= MCAP_MIN and c[-1] == "0"):
            continue
        rows.append({"code": c, "name": names.get(c, ""), "mcap_eok": int(mc[c]), "period": f"{int(r['year'])}Q{int(r['q'])}",
                     "op_yoy": round(float(r["yoy"]), 3), "px_vs_ma60": round(float(px[c] / ma[c] - 1), 3),
                     "p1t": bool(pd.notna(r["op1"]) and r["op"] > r["op1"] and pd.notna(r["rev4"]) and r["revenue"] > r["rev4"])})
    rows.sort(key=lambda x: -x["mcap_eok"])
    return {"id": "lab_p1_screen", "asof": str(asof.date()), "generated_at": datetime.now(KST).isoformat(timespec="minutes"),
            "rule": "보통주 · 시총(flows 실측) ≥ 5,000억 · 확정 최근 분기 영업이익 > 0 & YoY ≤ 0 · 종가 > 60일선 (사전등록 §3 P1)",
            "disclaimer": "매수 권고 아님 — 연구 신호 목록. 등급은 lab_p1.json 참조.",
            "n_total": len(rows), "top": rows[:20]}


def render_md(o: dict) -> str:
    f = lambda v: "—" if v is None else f"{v * 100:+.2f}%"  # noqa: E731
    L = [f"# 가설 연구소 P1 결과 ({o['asof']}, 퀀트)", "",
         f"사전등록: `{o['prereg_doc']}` (커밋 {o['prereg_commit']}) · m={M} · α={ALPHA:.5f}(양측) · IS<{SPLIT}≤OOS · 비용 왕복 0.3% · 매매 지시 아님.",
         f"데이터: 신호 {o['data']['first']} ~ {o['data']['last']} ({o['data']['months']}개월). 요청 2015~ 는 재무 데이터(2020Q1~) 한계로 불가.", "",
         "| id | 검정 | 개월 | 평균 | t | p | IS | OOS | 하락장 | 등급 |", "|---|---|---|---|---|---|---|---|---|---|"]
    for r in o["results"]:
        L.append(f"| {r['id']} | {r['label']} | {r['months']} | {f(r['mean'])} | {r['t']} | {r['p']} | {f(r['is']['mean'])} | "
                 f"{f(r['oos']['mean'])} | {f(r['bear']['mean'])} | {r['grade']} |")
    L += ["", "## 군 비교 (60일 KOSPI 대비 순초과, 월 코호트 평균)"]
    for g, v in o["compare"].items():
        L.append(f"- {g}: {json.dumps(v, ensure_ascii=False)}")
    L += ["", "## 예상 시나리오 (과거 P1 코호트, 미래 보장 아님)"]
    for g, v in o["scenarios"].items():
        if v:
            L.append(f"- {g}: n {v['n']} · 하위10% {f(v['p10'])} · 중앙 {f(v['median'])} · 상위10% {f(v['p90'])} · 손실 비중 {v['neg_share']}")
    L += ["", f"- 기준선: {o['baseline_note']}", "", "## L3 구루 13F", f"- {o['l3_13f']['status']} — {o['l3_13f']['reason']}",
          f"- 설계: {o['l3_13f']['design']}", f"- 다음: {o['l3_13f']['next']}"]
    L += ["", "## 한계"] + [f"- {x}" for x in o["caveats"]]
    return "\n".join(L) + "\n"


def main() -> int:
    global ROOT_DATA
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-root", default=str(ROOT))
    a = ap.parse_args()
    base = Path(a.data_root)
    ROOT_DATA = base / "data"
    from screener import fin, accum
    fin.MULTI, fin.FULL = ROOT_DATA / "fin" / "multi.parquet", ROOT_DATA / "fin" / "full.parquet"
    q = load_fin()
    w = load_prices(ROOT_DATA)
    sh, fl = shares_ref(ROOT_DATA, base / "universe")
    k, sx = kospi(), sox20()
    c, ev = build(q, w, sh, k, sx, fl)
    res = evaluate(c)
    o = {"id": "lab_p1", "asof": str(w.index[-1].date()), "generated_at": datetime.now(KST).isoformat(timespec="minutes"),
         "status": "ok", "topic": "earnings_yoy", "m": M, "alpha": round(ALPHA, 5),
         "prereg_doc": "docs/valuation_notes/2026-10-17_lab_p1_prereg.md", "prereg_commit": "b7ed1576",
         "prereg": {"m": M, "split": SPLIT, "entry": "t+1 종가", "hold": H_MAIN, "cost_roundtrip": COST, "mcap_min_eok": MCAP_MIN,
                    "lead": "1Q 5/16 · 반기 8/15 · 3Q 11/15 · 4Q 익년 4/1 (법정기한 다음 날)"},
         "data": {"first": str(c["date"].min().date()), "last": str(c["date"].max().date()), "months": int(len(c)),
                  "avg_universe": round(float(c["universe"].mean()), 1)},
         "results": res, "compare": compare(c),
         "l3_13f": {"status": "설계만(미실행)", "reason": "컨테이너에서 data.sec.gov·www.sec.gov 연결 실패(HTTP 000, 2026-10-17)",
                    "design": "Duquesne Family Office(CIK 0001536411)·국민연금 US 13F-HR 분기 보유 → 신규/증액 상위 종목을 '13F 제출일 다음 거래일 종가'(45일 지연 반영) 진입, 60거래일 보유, S&P500 대비 초과 · 같은 m 보정 틀",
                    "next": "board lab-l3-13f — GitHub Actions(ubuntu, SEC User-Agent 헤더)로 13F 수집 후 data/ 커밋, 이 스크립트에 L3 군 추가(새 사전등록 id)"},
         "baseline_note": "ALLMA = 같은 유니버스·60일선 위 전체 동일가중(사후 서술 기준선, 검정 밖). 동일가중 군은 2025~26 대형 반도체 주도 KOSPI 대비 모두 음(−) — 군 간 차이(T1·T5)가 핵심", "scenarios": scenarios(c, ev),
         "cohorts": [{k2: (str(v.date()) if isinstance(v, pd.Timestamp) else (round(v, 4) if isinstance(v, float) else v))
                      for k2, v in r.items() if not (isinstance(v, float) and math.isnan(v))} for r in c.to_dict("records")],
         "grades_doc": "A=Bonferroni 통과+IS·OOS·하락장 부호 일치 · B=Bonferroni 통과 · C=보정 전 p<0.10 · F=효과 없음 · 검증전=월<12 또는 이벤트<100(T3 각 그룹<8개월) · T6(L2) 상한 B",
         "caveats": ["재무 2020Q1~ 보유 → 신호 2021-06~ (요청 2015~ 불가). 표본 한 장세(2021~2026, 반도체 강세 포함) — kb:quant#18",
                     "시총 근사 = 2024-11 기준 주식수 × 보정 종가 → 과거 증자·자사주 변화 무시. 2024-11 이전 상폐 종목 제외(생존 편향, 비교군 공통)",
                     "재무 표본도 현재 유니버스 수집분 — 생존 편향",
                     "공시 시점 = 법정기한 근사(조기 제출 무시 → 보수적). 정정공시 반영 안 함(현재 값 사용)",
                     "P1-O 는 미래정보 사용·실행 불가 — 상한 서술만",
                     "가설 원천은 개인 원장 사후 사례 분석 — 주제 N 에 등록 전 탐색 포함"]}
    (OUT / "lab_p1.json").write_text(json.dumps(o, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "lab_p1.md").write_text(render_md(o), encoding="utf-8")
    names = accum.load_names(root=ROOT_DATA / "flows")
    try:
        import csv
        for r in csv.DictReader(open(base / "universe" / "kr.csv", encoding="utf-8")):
            names.setdefault(r["symbol"], r["name"])
    except Exception:  # noqa: BLE001
        pass
    asof = pd.Timestamp("2026-10-16")
    s = screen(q, w, fl, asof if asof in w.index else w.index[-1], names)
    (OUT / "lab_p1_screen.json").write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
    for r in res:
        print(r["id"], r["months"], r["events"], r["mean"], r["t"], r["p"], r["is"]["mean"], r["oos"]["mean"], r["bear"]["mean"], r["grade"])
    print(json.dumps(o["compare"], ensure_ascii=False))
    print(json.dumps(o["scenarios"], ensure_ascii=False))
    print("screen", s["n_total"], [x["name"] for x in s["top"][:10]])
    return 0


ROOT_DATA = ROOT / "data"

if __name__ == "__main__":
    sys.exit(main())
