"""매크로 바람 국면(순풍·중립·역풍)별 자산 5종 월수익 → 연환산 (매크로 2026-11-08, 겸이 요청 ISA 실험실 국면 표).

방법: screener/macroview.py 의 _stats·explain·W 를 그대로 써서 매월 마지막 미국 거래일의 바람 점수를 소급 재구성
(입력 11종 yfinance 일간 종가, 각 시리즈 최근 520행) → 3구분(≥+0.15 순풍 · ≤−0.15 역풍 · 그 사이 중립, KB macro #3 라벨 문턱)
→ 월말 t−1 판정 다음 달 t 의 reports/isa_lab_returns.json 원화 월수익(비용 차감 전) 평균 ×12.
보조: 같은 달 판정(t 판정·t 수익) — 점수가 그 달 가격 변화로 만들어지므로 동행 묘사일 뿐 예측에 쓰면 안 됨.

사용: python3 scripts/studies_wind_regime_er.py [--csv 입력CSV] [--out reports/views/scenario_er_macro.json]
  --csv 없으면 yfinance 로 받는다(네트워크 필요). 2026-11 부분 월 제외.
"""
import argparse
import json
import math
import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from screener import macroview as mv  # noqa: E402

TICK = {"^GSPC": "SPX", "^IXIC": "NASDAQ", "^RUT": "RUT", "^VIX": "VIX", "^TNX": "US10Y", "DX-Y.NYB": "DXY",
        "KRW=X": "USDKRW", "JPY=X": "USDJPY", "CL=F": "WTI", "GC=F": "GOLD", "BTC-USD": "BTC"}
ASSETS = ["SP", "NDX", "KS", "KR3Y", "GOLD"]
KEYS = {"tail": "순풍", "neu": "중립", "head": "역풍"}


def lab3(s):
    return None if s is None else ("tail" if s >= 0.15 else "head" if s <= -0.15 else "neu")


def monthend_scores(df):
    spx = df["SPX"].dropna()
    me = spx.groupby(spx.index.to_period("M")).apply(lambda s: s.index[-1])
    ser = {k: df[k].dropna() for k in df.columns}
    out = {}
    for per, d in me.items():
        stats = {}
        for k, s in ser.items():
            s2 = s[s.index <= d].iloc[-520:]
            x = mv._stats([[i.strftime("%Y-%m-%d"), float(v)] for i, v in s2.items()]) if len(s2) >= 60 else None
            if x:
                stats[k] = x
        num = den = 0.0
        for k in mv.ORDER:
            if k in stats:
                _, sc = mv.explain(k, stats[k], stats)
                if sc is not None:
                    num += mv.W.get(k, 0.5) * sc
                    den += mv.W.get(k, 0.5)
        out[str(per)] = round(num / den, 4) if den else None
    return out


def prev(m):
    y, mo = map(int, m.split("-"))
    y, mo = (y - 1, 12) if mo == 1 else (y, mo - 1)
    return f"{y}-{mo:02d}"


def group(months, W, lo="0000", hi="9999", lag=True, cond=lab3):
    g = {}
    for i, m in enumerate(months):
        if not (lo <= m <= hi):
            continue
        k = cond(W.get(prev(m) if lag else m))
        if k:
            g.setdefault(k, []).append(i)
    return g


def ann(R, idx):
    return {a: round(st.mean([R[a][i] for i in idx]) * 12, 4) for a in ASSETS}


def tstat(R, idx):
    return {a: round(st.mean(x) / (st.stdev(x) / math.sqrt(len(x))), 2) for a in ASSETS for x in [[R[a][i] for i in idx]]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv")
    ap.add_argument("--out", default=str(ROOT / "reports/views/scenario_er_macro.json"))
    a = ap.parse_args()
    import pandas as pd
    if a.csv:
        df = pd.read_csv(a.csv, index_col=0, parse_dates=True)
    else:
        import yfinance as yf
        df = yf.download(list(TICK), start="2002-06-01", progress=False, auto_adjust=False)["Close"]
    df = df.rename(columns=TICK)
    W = monthend_scores(df)
    L = json.loads((ROOT / "reports/isa_lab_returns.json").read_text(encoding="utf-8"))
    R = L["months"], L["r"]
    months, R = R
    end = "2026-10"   # 2026-11 부분 월 제외
    fwd, same = group(months, W, hi=end), group(months, W, hi=end, lag=False)
    h1, h2 = group(months, W, hi="2014-12"), group(months, W, lo="2015-01", hi=end)
    strong = group(months, W, hi=end, cond=lambda s: None if s is None else ("sh" if s <= -0.4 else None))
    allx = [i for i, m in enumerate(months) if m <= end]
    conf = {"tail": "낮음~중 — 주식 t≈2.9~5.3·전후반 모두 양(+)이나 전체 평균 대비 초과폭은 후반 쏠림, 금 낮음",
            "neu": "낮음 — 전반(2004–14)·후반(2015–26) 주식 부호·크기 엇갈림(후반 S&P −0.8%)",
            "head": "낮음 — 역풍 판정 다음 달 주식은 평균회귀(반등)가 섞여 전반 S&P +2.6% vs 후반 +25.7%로 불안정, "
                    "역풍 판정이 다음 달에도 역풍인 비율 19/64(30%)"}
    defs = {"tail": "바람 점수 ≥ +0.15 (wind_label '순풍'+'강한 순풍')",
            "neu": "−0.15 < 점수 < +0.15 (wind_label '중립'+'약한 순풍'+'약한 역풍')",
            "head": "바람 점수 ≤ −0.15 (wind_label '역풍'+'강한 역풍')"}
    regimes = []
    for k in ("tail", "neu", "head"):
        regimes.append({
            "key": k, "name": KEYS[k], "def": defs[k],
            "def_src": "docs/desk_kb/macro.md 14행 (#3 라벨 ±0.15 역/순풍) · screener/macroview.py wind_label·W·explain",
            "n_months": len(fwd[k]), "er": ann(R, fwd[k]),
            "method": "월말 t−1 바람 점수 소급 재구성(macroview 식 그대로) → 다음 달 t 원화 월수익(isa_lab_returns.json, 비용 차감 전) 산술평균×12, 2004-01~2026-10",
            "confidence": "모델 가정(확신 " + conf[k] + ")",
            "t_stat": tstat(R, fwd[k]),
            "er_same_month": {"n": len(same[k]), **ann(R, same[k]),
                              "주의": "같은 달 판정 — 점수가 그 달 가격 변화로 만들어지는 동행 묘사, 예측·배분 입력 금지"},
            "split": {"2004-2014": {"n": len(h1.get(k, [])), **ann(R, h1.get(k, []))},
                      "2015-2026": {"n": len(h2.get(k, [])), **ann(R, h2.get(k, []))}},
        })
    regimes[2]["sub_strong_head"] = {"def": "점수 ≤ −0.4 (강한 역풍)", "n": len(strong.get("sh", [])), **ann(R, strong.get("sh", []))}
    mvj = json.loads((ROOT / "reports/macro_view.json").read_text(encoding="utf-8"))
    out = {
        "desk": "macro", "asof": "2026-11-08",
        "price_asof": mvj.get("asof"),
        "regimes": regimes,
        "now_regime": {"key": lab3(mvj.get("score")), "name": KEYS.get(lab3(mvj.get("score"))), "score": mvj.get("score"),
                       "label": mvj.get("label"), "src": "reports/macro_view.json (검증전)",
                       "kospi_spx_gap20": "코스피 20일 −23.6% vs S&P −5.6% (격차 −18.1%p) — 바람 점수는 한국 고유 충격을 못 잡음(KB macro #17)"},
        "baseline_all": {"n": len(allx), **ann(R, allx)},
        "reconstruction_check": "소급 재구성 11/6 −0.344 vs 실 macro_view −0.35, 10/16 −0.217 vs 10/17(KST) −0.21 — 10/13~11/6 19영업일 git 스냅샷과 ±0.02 내",
        "caveats": ["가중치·임계 사후 설정(KB #3) → 같은 기간 소급 = 표본 내",
                    "입력 결측: USDKRW 2004-01 월말·BTC 2014-10 월말까지는 점수에서 빠짐(분모 재가중, macroview 와 같은 처리)",
                    "월말 1점 판정 — 일간 라벨은 5일 뒤 유지율이 낮아(studies_wind_threshold_check) 월 국면으로는 거침",
                    "수익은 isa_lab_returns.json 정의(원화·비용 차감 전, 2026-10~ 일간 수정종가 재측정)"],
        "src": "scripts/studies_wind_regime_er.py · reports/isa_lab_returns.json (퀀트 97341c82a)",
        "note": "예측 아님·비중 변경 권고 아님",
    }
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({r["name"]: (r["n_months"], r["er"]) for r in regimes}, ensure_ascii=False))


if __name__ == "__main__":
    main()
