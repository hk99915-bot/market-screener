#!/usr/bin/env python3
"""미국 매집 흔적 신호 사건연구 (퀀트, 2026-10-17) — 사전등록 reports/studies/us_accum.md §0.

  python3 scripts/study_us_accum.py          # reports/studies/us_accum.json 생성 (네트워크 없음, 1~3분)

입력  data/hist/us_20XX.parquet + reports/detail/US/*.json(2026 연장) + data/hist/us_daily.parquet(SPY·QQQ)
출력  reports/studies/us_accum.json (등급·표) — md §1~ 은 이 json 을 보고 사람이 적는다.
영향  문서·연구 전용. 일일 스캔(screener/us_accum.scan)은 json 의 grades 만 읽어 점수 가중에 쓴다.
"""
from __future__ import annotations

import glob
import json
import math
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from screener.regime_tag import DD_BEAR, DD_CORR, HI_N, MA_N, classify  # noqa: E402
from screener.us_accum import NAMES, P, SIGNALS, features, wilson_lo  # noqa: E402

HS = (5, 20, 60)
COOL = 20
COSTS = (0.0010, 0.0025)
IS_END = "2017-12-31"
M = len(SIGNALS)
ALPHA = 0.05
OUT = ROOT / "reports" / "studies" / "us_accum.json"


def load_panel() -> pd.DataFrame:
    h = pd.concat([pd.read_parquet(f) for f in sorted(glob.glob(str(ROOT / "data/hist/us_20[0-9][0-9].parquet")))])
    h["date"] = h["date"].astype(str).str[:10]
    h = h[~h["yf"].str.startswith("^")]
    h = h[~h["yf"].isin(["SPY", "QQQ", "IWM"])]
    last = h["date"].max()
    ext = []
    for f in sorted((ROOT / "reports/detail/US").glob("*.json")):
        s = f.stem
        if s not in set(h["yf"].unique()):
            continue
        ch = json.loads(f.read_text(encoding="utf-8")).get("chart") or []
        rows = [{"yf": s, "date": r["t"], "open": r.get("o"), "high": r.get("h"), "low": r.get("l"),
                 "close": r.get("c"), "volume": r.get("v")} for r in ch if r.get("t", "") > last and r.get("c")]
        ext += rows
    p = pd.concat([h, pd.DataFrame(ext)], ignore_index=True) if ext else h
    return p.drop_duplicates(["yf", "date"], keep="last").sort_values(["yf", "date"]).reset_index(drop=True)


def bench() -> pd.DataFrame:
    u = pd.read_parquet(ROOT / "data/hist/us_daily.parquet", columns=["date", "symbol", "open", "close"])
    u["date"] = u["date"].astype(str).str[:10]
    w = {}
    for s in ("SPY", "QQQ"):
        g = u[u.symbol == s].sort_values("date").set_index("date")
        for hh in HS:
            w[f"{s}_{hh}"] = g["close"].shift(-hh) / g["open"].shift(-1) - 1
        if s == "SPY":
            c = g["close"]
            dd = c / c.rolling(HI_N, min_periods=20).max() - 1
            ma = c.rolling(MA_N).mean()
            lab = np.where(dd <= DD_BEAR, "하락", np.where((dd <= DD_CORR) | (c < ma), "조정", "상승"))
            w["regime"] = pd.Series(lab, index=g.index)
            # 정의 일치 확인 (regime_tag.classify 와 같은 결과여야 함) — 표본 5일
            cl = c.tolist()
            for i in (300, 1200, 2500, 3500, len(cl) - 1):
                assert classify(cl[: i + 1])["l"] == lab[i], ("regime mismatch", g.index[i])
    return pd.DataFrame(w)


def nw_t(x: np.ndarray, lag: int) -> float:
    x = np.asarray(x, float)
    n = len(x)
    if n < 3:
        return float("nan")
    e = x - x.mean()
    s = e @ e / n
    for k in range(1, lag + 1):
        s += 2 * (1 - k / (lag + 1)) * (e[k:] @ e[:-k]) / n
    return float(x.mean() / math.sqrt(s / n)) if s > 0 else float("nan")


def p_one(t: float) -> float | None:
    return None if not math.isfinite(t) else 0.5 * math.erfc(t / math.sqrt(2))


def cooldown(mask: np.ndarray, gap: int) -> np.ndarray:
    out = np.zeros(len(mask), bool)
    nxt = -1
    for i in np.flatnonzero(mask):
        if i >= nxt:
            out[i] = True
            nxt = i + gap
    return out


def build() -> tuple[pd.DataFrame, pd.DataFrame]:
    panel = load_panel()
    parts = []
    for s, g in panel.groupby("yf", sort=False):
        g = g.reset_index(drop=True)
        if len(g) < P["min_obs"] + 5:
            continue
        f = features(g)
        f["sym"] = s
        for hh in HS:
            f[f"r{hh}"] = f["close"].shift(-hh) / f["open"].shift(-1) - 1
        f["dd52"] = f["close"] / f["close"].rolling(252, min_periods=60).max() - 1
        f = f[f["elig"]]
        for sig in SIGNALS:
            f[sig + "_e"] = cooldown(f[sig].to_numpy(), COOL) if len(f) else f[sig]
        # 쿨다운은 적격일 기준 인덱스 — 적격일이 끊기면 약간 짧아질 수 있음(보수 영향 없음)
        parts.append(f[["date", "sym", "dd52", *[f"r{h}" for h in HS], *SIGNALS, *[s + "_e" for s in SIGNALS]]])
    df = pd.concat(parts, ignore_index=True)
    b = bench()
    df = df.join(b, on="date")
    for hh in HS:
        df[f"u{hh}"] = df.groupby("date")[f"r{hh}"].transform("mean")
        df[f"x{hh}"] = df[f"r{hh}"] - df[f"u{hh}"]
    return df, panel


def stats(ev: pd.DataFrame, hh: int, cost: float, lag: int) -> dict:
    e = ev.dropna(subset=[f"x{hh}"])
    if not len(e):
        return {"n": 0}
    x = e[f"x{hh}"] - cost
    mon = x.groupby(e["date"].str[:7]).mean()
    t = nw_t(mon.to_numpy(), lag)
    k = int((x > 0).sum())
    return {"n": int(len(e)), "months": int(len(mon)), "mean_xs": round(float(x.mean()), 5), "median_xs": round(float(x.median()), 5),
            "win": round(k / len(e), 4), "wilson_lo": round(wilson_lo(k, len(e)), 4), "t_nw": None if not math.isfinite(t) else round(t, 2),
            "p": None if p_one(t) is None else round(p_one(t), 5),
            "vs_spy": round(float((e[f"r{hh}"] - cost - e[f"SPY_{hh}"]).mean()), 5),
            "vs_qqq": round(float((e[f"r{hh}"] - cost - e[f"QQQ_{hh}"]).mean()), 5),
            "raw": round(float(e[f"r{hh}"].mean() - cost), 5)}


def main() -> None:
    df, panel = build()
    base = {}
    for hh in HS:
        d = df.dropna(subset=[f"x{hh}"])
        base[str(hh)] = {"n_days": int(len(d)), "univ_mean": round(float(d[f"r{hh}"].mean()), 5),
                         "spy_mean": round(float(d.drop_duplicates("date")[f"SPY_{hh}"].mean()), 5),
                         "qqq_mean": round(float(d.drop_duplicates("date")[f"QQQ_{hh}"].mean()), 5),
                         "win_xs_gt0": round(float((d[f"x{hh}"] > 0).mean()), 4)}
    alpha_b = ALPHA / M
    res, grades = {}, {}
    is_m = df["date"] <= IS_END
    bear = df["regime"].isin(["조정", "하락"])
    for sig in SIGNALS:
        ev = df[df[sig + "_e"]]
        r = {"n_events": int(len(ev)), "all": {}, "is": {}, "oos": {}, "regime": {}, "when": {}}
        for hh in HS:
            lag = max(1, math.ceil(hh / 21))
            for c in (0.0, *COSTS):
                r["all"][f"h{hh}_c{int(c*10000)}"] = stats(ev, hh, c, lag)
        r["is"] = stats(ev[is_m[ev.index]], 20, 0.0025, 1)
        r["oos"] = stats(ev[~is_m[ev.index]], 20, 0.0025, 1)
        r["bear"] = stats(ev[bear[ev.index]], 20, 0.0025, 1)
        # 보조(탐색, 등급 밖): 60일·비용 0.25% IS/OOS/약세장 — 결과 본 뒤 추가한 표라 exploratory (kb:quant#3, 상한 C)
        r["sec60"] = {"exploratory": True, "is": stats(ev[is_m[ev.index]], 60, 0.0025, 3),
                      "oos": stats(ev[~is_m[ev.index]], 60, 0.0025, 3), "bear": stats(ev[bear[ev.index]], 60, 0.0025, 3)}
        for lab in ("상승", "조정", "하락"):
            r["regime"][lab] = stats(ev[ev["regime"] == lab], 20, 0.0025, 1)
        # 언제 뜨나: 사건 비중 / 적격일 비중 (>1 = 그 구간에 몰림)
        for lab in ("상승", "조정", "하락"):
            sh_e = float((ev["regime"] == lab).mean()) if len(ev) else 0
            sh_d = float((df["regime"] == lab).mean())
            r["when"][f"spy_{lab}"] = round(sh_e / sh_d, 2) if sh_d else None
        bins = [(-1.01, -0.30), (-0.30, -0.15), (-0.15, -0.05), (-0.05, 0.001)]
        for lo, hi in bins:
            sh_e = float(((ev["dd52"] > lo) & (ev["dd52"] <= hi)).mean()) if len(ev) else 0
            sh_d = float(((df["dd52"] > lo) & (df["dd52"] <= hi)).mean())
            r["when"][f"dd52_{int(lo*100)}_{int(hi*100)}"] = round(sh_e / sh_d, 2) if sh_d else None
        I, O, B = r["is"], r["oos"], r["bear"]
        if I.get("n", 0) < 100:
            g, why = "검증전", f"IS 사건 {I.get('n', 0)} < 100"
        elif I.get("p") is not None and I["p"] < alpha_b and I["mean_xs"] > 0:
            if O.get("mean_xs", -1) > 0 and B.get("mean_xs", -1) > 0:
                g, why = "B", (f"A 조건 충족(IS p={I['p']:.4f}<{alpha_b:.4f}, OOS {O['mean_xs']*100:+.2f}%p, 약세장 {B['mean_xs']*100:+.2f}%p) "
                               "— 현재 구성 유니버스 생존편향으로 B 상한")
            else:
                g, why = "B", f"IS p={I['p']:.4f} 통과, OOS {O.get('mean_xs', 0)*100:+.2f}%p / 약세장 {B.get('mean_xs', 0)*100:+.2f}%p 부호 불일치"
        elif I.get("p") is not None and I["p"] < 0.10 and I["mean_xs"] > 0:
            g, why = "C", f"방향만(IS p={I['p']:.3f}, Bonferroni {alpha_b:.4f} 미달)"
        else:
            g, why = "F", f"IS 20일 초과 {I.get('mean_xs', 0)*100:+.2f}%p (비용 0.25%), p={I.get('p')}"
        grades[sig] = {"grade": g, "why": why}
        res[sig] = r
    out = {"generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
           "data": {"files": "data/hist/us_2010.parquet~us_2025.parquet + reports/detail/US chart(2026) + data/hist/us_daily.parquet(SPY·QQQ)",
                    "from": str(df["date"].min()), "to": str(df["date"].max()), "symbols": int(df["sym"].nunique()),
                    "eligible_days": int(len(df))},
           "prereg": {"doc": "reports/studies/us_accum.md §0", "m": M, "alpha_bonf": round(alpha_b, 5),
                      "primary": "20d excess vs same-day universe mean, net 0.25% roundtrip, monthly NW t, one-sided", "is_end": IS_END},
           "params": {**P, "cooldown": COOL, "costs": list(COSTS), "entry": "t+1 open", "exit": "t+h close"},
           "survivorship": "유니버스 = 2026년 현재 거래대금 상위 300(상폐 없음). 수익 수준 과대, 횡단면 차감으로 일부만 완화. 등급 상한 B.",
           "names": NAMES, "base": base, "grades": grades, "results": res}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    for s in SIGNALS:
        a = res[s]["all"]["h20_c25"]
        print(s, NAMES[s], grades[s]["grade"], "n", a.get("n"), "xs20", a.get("mean_xs"), "p", a.get("p"), "|", grades[s]["why"])


if __name__ == "__main__":
    main()
