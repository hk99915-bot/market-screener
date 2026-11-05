"""하락일 대응 H4 정정 재계산(검증·피어 11/5 지적 반영) — 사전등록 H4 정의는 그대로, 체결·집계 보조표만 추가.
원본 scripts/study_downday.py 의 이벤트 정의를 재사용하고, 결과를 본 뒤 정의를 바꾸지 않는다(보조표=탐색, 등급 상한 C).
산출: reports/studies/2026-11-05_downday_fix.json  (야후/캐시 데이터는 data/hist 로컬, 커밋 밖)"""
from __future__ import annotations
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import study_downday as sd  # noqa: E402


def load_open():
    op = []
    for y in range(2010, 2026):
        f = sd.HIST / f"kr_{y}.parquet"
        if f.exists():
            df = pd.read_parquet(f, columns=["yf", "date", "open"])
            df["date"] = pd.to_datetime(df["date"])
            op.append(df.pivot_table(index="date", columns="yf", values="open", aggfunc="last"))
    O = pd.concat(op).sort_index()
    return O[~O.index.duplicated(keep="last")]


def events(C, V, O, K):
    kr = K.reindex(C.index).pct_change().values
    cal = C.index
    val = (C * V).rolling(60, min_periods=40).mean().shift(1)
    hi = C.rolling(sd.LOOK, min_periods=sd.LOOK).max()
    below = C <= (1 - 0.20) * hi
    prior = below.shift(1).rolling(sd.COOL, min_periods=1).max().fillna(0).astype(bool)
    ev = below & ~prior
    rows = []
    for i, d in enumerate(cal):
        if i < sd.LOOK or i + sd.HOLD >= len(cal) or not (kr[i] <= -0.02):
            continue
        cand = ev.iloc[i]
        cand = cand[cand].index
        if len(cand) == 0:
            continue
        top = val.iloc[i].dropna().nlargest(sd.TOPN).index.intersection(cand)
        s = next((j for j in range(i + 1, i + sd.HOLD + 1) if kr[j] >= sd.REB), None)
        for code in top:
            c = C[code].values
            w = c[i:i + sd.HOLD + 1]
            if np.isnan(w).any() or (np.abs(np.diff(w) / w[:-1]) > 0.40).any():
                continue
            cx = c[i + sd.HOLD] / c[i]
            b = c[s] / c[i] if s else cx
            if s and s + 1 <= i + sd.HOLD:
                o1 = O[code].values[s + 1]
                bo = o1 / c[i] if o1 == o1 and o1 > 0 else np.nan   # 반등일 다음 날 시가
            else:
                bo = cx if not s else np.nan
            # 대기 중 최악: t~t+HOLD 종가 경로 최저 / t 종가
            rows.append({"date": d, "code": code, "B": b, "Bopen": bo, "C": cx, "minpath": w.min() / c[i],
                         "waited": s is not None})
    return pd.DataFrame(rows)


def month_t(ev, col):
    ev = ev.dropna(subset=[col]).copy()
    ev["x"] = ev[col] - 1.0
    ev["ym"] = ev["date"].dt.to_period("M")
    g = (ev.groupby("ym")[col].mean() - 1.0)   # 아래서 A=1 이므로 B−A = col−1
    gi, go = g[g.index <= pd.Period(sd.IS_END, "M")], g[g.index > pd.Period(sd.IS_END, "M")]
    return {"all": sd.t1(g.values), "IS": sd.t1(gi.values), "OOS": sd.t1(go.values),
            "event_level_mean": round(float(ev[col].mean() - 1), 5), "n_events": int(len(ev))}


def main():
    K = sd.load_kospi()
    C, V = sd.load_kr_panel()
    O = load_open()
    ev = events(C, V, O, K)
    out = {"note": "정정 보조표(탐색·상한 C). 등록 정의·등급 규칙 불변.", "events": int(len(ev)),
           "B_close_minus_A": month_t(ev, "B"), "B_nextopen_minus_A": month_t(ev, "Bopen")}
    q = lambda s, p: round(float(np.percentile(s, p)), 4)  # noqa: E731
    for k in ("B", "Bopen", "C"):
        s = (ev[k].dropna() - 1).values
        out[f"tail_{k}_minus1"] = {"n": int(len(s)), "p1": q(s, 1), "p5": q(s, 5), "min": round(float(s.min()), 4)}
    mp = ev["minpath"] - 1
    out["tail_minpath_2w"] = {"n": int(len(mp)), "p1": q(mp, 1), "p5": q(mp, 5), "min": round(float(mp.min()), 4),
                              "month_cluster_worst_mean": round(float(mp.groupby(ev["date"].dt.to_period("M")).mean().min()), 4)}
    p = Path(__file__).resolve().parent.parent / "reports/studies/2026-11-05_downday_fix.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
