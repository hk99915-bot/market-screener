"""외인·기관 매집 신호 이벤트 스터디 → reports/studies/accum_signals.json (+ .md 요약).

질문: (1) 매집은 언제 일어나나(국면·직전 수익률·시장 수급) (2) 어떤 매집 신호 뒤에 5/20/60일 초과수익이 있나.

§0 사전등록 (결과 보기 전 고정, 이 파일 커밋이 결과 커밋보다 앞선다)
- 데이터: data/flows/kr_inv_*.parquet (pykrx 일별 전 종목 투자자 순매수·시총·거래대금, 상폐 포함 → 생존편향 없음).
  지수: data/hist/kr_index_daily.parquet KOSPI 종가.
- 표본: 적격 = 시총 ≥300억 · 20일 평균 거래대금 ≥1억 · ETF/ETN/스팩 이름 제외 (screener.accum.eligible).
- 신호 8개 (screener.accum.SIGNALS, 단면 문턱은 날짜별 상위 10%) × 보유 3개(5·20·60거래일) → m = 24, α = 0.05/24 = 0.00208 (양측).
- 진입: 신호일 t 의 '다음 거래일 종가'(KRX 확정치가 장 마감 뒤 나오므로 t 종가 체결 불가). 수익 = t+1 → t+1+h 종가, 분할 보정.
- 이벤트: 신호 '켜진 날'(전날 꺼짐)만, 같은 종목은 직전 채택 이벤트에서 h 거래일 안이면 버림(겹침 제거).
- 지표: ① 초과(KOSPI 대비) 평균·중앙값 ② 비정상수익 = 이벤트 수익 − 같은 날 적격 전 종목 평균 수익(동일가중 기준선)
  ③ 적중 = 초과>0 비율, Wilson 95% 하한, 기준선 적중률(적격 전 종목·전 일자) ④ t = 비정상수익 평균 / 월 단위 군집 SE.
- 국면: screener.regime_tag.classify(KOSPI 종가, 신호일까지) — 상승/조정/하락.
- 분할: IS = 신호일 < 2025-01-01, OOS = 그 이후. (2025~26 강세장 집중 → 국면 분할을 같이 본다)
- 등급(kb:quant#4): 표본 n<100 또는 월<12 → 검증전. A = Bonferroni 통과 + IS·OOS·(조정+하락) 부호 일치,
  B = Bonferroni 통과, C = 보정 전 p<0.10 (방향만), F = 그 밖. 음(−) 방향 유의는 'C(역방향)'/'B(역방향)'.
- 거래비용: 미반영(왕복 ≈0.25%p 를 결과에서 빼서 읽는다). 시총 상위 10% 문턱은 소형주에 치우침 → 규모 통제 안 함(한계).
"""
from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from screener import accum  # noqa: E402
from screener.regime_tag import classify  # noqa: E402

KST = timezone(timedelta(hours=9))
OUT = ROOT / "reports" / "studies" / "accum_signals.json"
MD = ROOT / "reports" / "studies" / "accum_signals.md"
H = (5, 20, 60)
M = len(accum.SIGNALS) * len(H)
ALPHA = 0.05 / M
SPLIT = "2025-01-01"
MIN_N, MIN_MONTHS = 100, 12


def wilson_lb(k: int, n: int, z: float = 1.96) -> float | None:
    if n <= 0:
        return None
    p = k / n
    den = 1 + z * z / n
    c = p + z * z / (2 * n)
    a = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (c - a) / den


def _p2(t: float) -> float:
    return math.erfc(abs(t) / math.sqrt(2))


def cluster_t(x: np.ndarray, month: np.ndarray) -> tuple[float | None, float | None]:
    """평균 / 월 군집 SE. 군집 < 6 이면 None."""
    if len(x) < 2:
        return None, None
    s = pd.Series(x - x.mean()).groupby(month).sum()
    G = len(s)
    if G < 6:
        return None, None
    se = math.sqrt(float((s ** 2).sum()) * G / (G - 1)) / len(x)
    if se == 0:
        return None, None
    t = float(x.mean() / se)
    return t, _p2(t)


def kospi_series() -> pd.DataFrame:
    ix = pd.read_parquet(ROOT / "data" / "hist" / "kr_index_daily.parquet")
    k = ix[ix["symbol"] == "KOSPI"][["date", "close"]].copy()
    k["date"] = pd.to_datetime(k["date"])
    k = k.dropna().sort_values("date").reset_index(drop=True)
    closes = k["close"].astype(float).tolist()
    k["regime"] = [(classify(closes[max(0, i - 260):i + 1]) or {}).get("l") for i in range(len(closes))]
    k["k_ret20"] = k["close"] / k["close"].shift(20) - 1
    return k


def prepare(df: pd.DataFrame, names: dict) -> pd.DataFrame:
    d = accum.features(accum.add_returns(df))
    d = accum.flags(d, accum.eligible(d, names))
    g = d.groupby("code", sort=False)["lv"]
    lv1 = g.shift(-1)
    for h in H:
        d[f"fwd{h}"] = np.expm1(g.shift(-1 - h) - lv1)
    return d


def add_market(d: pd.DataFrame, k: pd.DataFrame) -> pd.DataFrame:
    kk = k.set_index("date")["close"]
    dates = pd.Index(sorted(d["date"].unique()))
    kc = kk.reindex(dates).ffill()
    for h in H:
        kf = kc.shift(-1 - h) / kc.shift(-1) - 1
        d[f"kfwd{h}"] = d["date"].map(kf)
        d[f"ex{h}"] = d[f"fwd{h}"] - d[f"kfwd{h}"]
        um = d[d["elig"]].groupby("date")[f"fwd{h}"].mean()
        d[f"ab{h}"] = d[f"fwd{h}"] - d["date"].map(um)
    d["regime"] = d["date"].map(k.set_index("date")["regime"])
    return d


def onsets(d: pd.DataFrame, sig: str, h: int) -> pd.DataFrame:
    s = d[sig].astype(bool)
    prev = s.groupby(d["code"]).shift(1, fill_value=False).astype(bool)
    on = d[s & ~prev & d[f"ab{h}"].notna()]
    # 같은 종목 h 거래일 안 재발 제거 — 날짜 순번으로 근사
    di = {x: i for i, x in enumerate(sorted(d["date"].unique()))}
    keep = []
    for code, g in on.groupby("code", sort=False):
        last = -10 ** 9
        for idx, dt in zip(g.index, g["date"]):
            p = di[dt]
            if p - last >= h:
                keep.append(idx)
                last = p
    return on.loc[keep]


def grade(res: dict) -> str:
    if res["n"] < MIN_N or res["months"] < MIN_MONTHS or res["p"] is None:
        return "검증전"
    sign = 1 if res["ab_mean"] > 0 else -1
    tag = "" if sign > 0 else "(역방향)"
    if res["p"] < ALPHA:
        sub = [res["is"].get("ab_mean"), res["oos"].get("ab_mean"), res["bear"].get("ab_mean")]
        if all(x is not None and x * sign > 0 for x in sub) and sign > 0:
            return "A"
        return "B" + tag
    if res["p"] < 0.10:
        return "C" + tag
    return "F"


def _sub(e: pd.DataFrame, h: int) -> dict:
    if not len(e):
        return {"n": 0}
    x = e[f"ab{h}"].to_numpy()
    k = int((e[f"ex{h}"] > 0).sum())
    return {"n": int(len(e)), "ab_mean": round(float(x.mean()), 4), "ex_mean": round(float(e[f"ex{h}"].mean()), 4),
            "hit": round(k / len(e), 3), "hit_lb": round(wilson_lb(k, len(e)), 3)}


def evaluate(d: pd.DataFrame) -> tuple[list[dict], dict]:
    el = d[d["elig"]]
    base = {}
    for h in H:
        b = el[el[f"ex{h}"].notna()]
        base[h] = {"n": int(len(b)), "ex_mean": round(float(b[f"ex{h}"].mean()), 4),
                   "hit": round(float((b[f"ex{h}"] > 0).mean()), 3),
                   "fwd_mean": round(float(b[f"fwd{h}"].mean()), 4)}
    rows = []
    for sig, doc in accum.SIGNALS.items():
        for h in H:
            e = onsets(d, sig, h)
            x = e[f"ab{h}"].to_numpy()
            mon = e["date"].dt.to_period("M").astype(str).to_numpy()
            t, p = cluster_t(x, mon) if len(e) else (None, None)
            k = int((e[f"ex{h}"] > 0).sum())
            r = {"sig": sig[4:], "doc": doc, "h": h, "n": int(len(e)), "months": int(len(set(mon))),
                 "fwd_mean": round(float(e[f"fwd{h}"].mean()), 4) if len(e) else None,
                 "ex_mean": round(float(e[f"ex{h}"].mean()), 4) if len(e) else None,
                 "ex_median": round(float(e[f"ex{h}"].median()), 4) if len(e) else None,
                 "ab_mean": round(float(x.mean()), 4) if len(e) else None,
                 "t": None if t is None else round(t, 2), "p": None if p is None else round(p, 5),
                 "hit": round(k / len(e), 3) if len(e) else None,
                 "hit_lb": round(wilson_lb(k, len(e)), 3) if len(e) else None,
                 "base_hit": base[h]["hit"], "base_ex": base[h]["ex_mean"],
                 "is": _sub(e[e["date"] < SPLIT], h), "oos": _sub(e[e["date"] >= SPLIT], h),
                 "regime": {rg: _sub(e[e["regime"] == rg], h) for rg in ("상승", "조정", "하락")},
                 "bear": _sub(e[e["regime"].isin(["조정", "하락"])], h)}
            r["grade"] = grade(r)
            rows.append(r)
    return rows, base


def when(d: pd.DataFrame, k: pd.DataFrame) -> dict:
    """매집은 언제? ① 국면별 매집 시작 빈도 vs 거래일 비중 ② 시작 시점 종목의 직전 20·60일 수익·거래대금 마름
    ③ 시장 전체 외국인 20일 순매수(%시총) 5분위 → KOSPI 다음 20일 수익 (겹침 표본, 참고)."""
    el = d[d["elig"]]
    s = el["sig_accum"].astype(bool)
    prev = s.groupby(el["code"]).shift(1, fill_value=False).astype(bool)
    on = el[s & ~prev]
    days = pd.Series(sorted(d["date"].unique()))
    rg_days = days.map(k.set_index("date")["regime"]).value_counts(normalize=True)
    per_day = on.groupby("date").size().reindex(days.values, fill_value=0)
    rg_on = per_day.groupby(days.map(k.set_index("date")["regime"]).values).mean()
    out = {"regime_share_days": {r: round(float(v), 3) for r, v in rg_days.items()},
           "onsets_per_day_by_regime": {r: round(float(v), 1) for r, v in rg_on.items()},
           "onset_prior": {"ret20_median": round(float(on["ret20"].median()), 4),
                           "ret60_median": round(float(on["ret60"].median()), 4),
                           "univ_ret20_median": round(float(el["ret20"].median()), 4),
                           "share_ret20_le0": round(float((on["ret20"] <= 0).mean()), 3),
                           "univ_share_ret20_le0": round(float((el["ret20"] <= 0).mean()), 3),
                           "tv_dry_median": round(float(on["tv_dry"].median()), 3),
                           "univ_tv_dry_median": round(float(el["tv_dry"].median()), 3),
                           "n": int(len(on))}}
    # 시장 수준
    mk = d[d["mkt"] == "K"].groupby("date")[["f", "i", "mcap", "tv"]].sum()
    mk["f20_cap"] = mk["f"].rolling(20).sum() / (mk["mcap"] * 100) * 100
    mk["i20_cap"] = mk["i"].rolling(20).sum() / (mk["mcap"] * 100) * 100
    mk["tv_x"] = mk["tv"].rolling(5).mean() / mk["tv"].shift(5).rolling(60).mean()
    kc = k.set_index("date")["close"].reindex(mk.index).ffill()
    mk["k_fwd20"] = kc.shift(-21) / kc.shift(-1) - 1
    mk = mk.dropna()
    q = {}
    for col in ("f20_cap", "i20_cap", "tv_x"):
        if len(mk) < 100:
            break
        b = pd.qcut(mk[col], 5, labels=False, duplicates="drop")
        q[col] = [{"q": int(i) + 1, "lo": round(float(g[col].min()), 3), "hi": round(float(g[col].max()), 3),
                   "k_fwd20": round(float(g["k_fwd20"].mean()), 4), "n_days": int(len(g))} for i, g in mk.groupby(b)]
    out["market_quintiles"] = q
    out["market_quintiles_note"] = "KOSPI 주식 합계 기준 · 매일 표본(20일 겹침 → 독립 표본 ≈ n/20) · 참고(등급 없음)"
    return out


def _with_top(o: dict, md: str) -> str:
    """보고 상단 형식(STANDARD 8절) 문서형 요약 블록을 md 맨 앞에 — 실패하면 본문만."""
    try:
        from screener import topline, topline_from
        rs = sorted(o.get("results") or [], key=lambda r: ("A", "B", "C", "검증전", "F").index(r["grade"]) if r.get("grade") in ("A", "B", "C", "검증전", "F") else 9)
        what = [f"{r['sig']} h{r['h']}: ab {r['ab_mean'] * 100:+.2f}% · t {r['t']} · n {r['n']:,} ({r['grade']})" for r in rs[:2] if r.get("ab_mean") is not None]
        g = {}
        for r in o.get("results") or []:
            g[r.get("grade")] = g.get(r.get("grade"), 0) + 1
        so = [f"등급 분포 {' · '.join(f'{k} {v}' for k, v in g.items())} — 비용 미반영(왕복 ≈0.25%p)"] + topline.fit((o.get("caveats") or ["한계 기재 없음"])[0], max_lines=1)
        top = topline_from.study("매집 신호", what or ["결과 없음(results 비어 있음)"], so, src=["reports/studies/accum_signals.md"], asof=str(o.get("asof"))[:16])
        o["top"] = top
        return topline.render_md(top, doc=True) + md
    except Exception as e:  # noqa: BLE001
        print(f"top 실패: {e}")
        return md


def render_md(o: dict) -> str:
    L = [f"# 외인·기관 매집 신호 이벤트 스터디 ({o['asof']})", "",
         f"데이터 {o['data']['first']}~{o['data']['last']} · 거래일 {o['data']['days']} · 종목 {o['data']['codes']} · m={M} · α={ALPHA:.5f}",
         "진입 = 신호 다음 거래일 종가. ab = 같은 날 적격 전 종목 평균 대비. ex = KOSPI 대비. 비용 미반영(왕복 ≈0.25%p).", "",
         "| 신호 | h | n | ex 평균 | ab 평균 | t | 적중(하한) | 기준 적중 | IS ab | OOS ab | 조정+하락 ab | 등급 |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    f = lambda x: "-" if x is None else f"{x*100:+.2f}%"  # noqa: E731
    for r in o["results"]:
        L.append(f"| {r['sig']} | {r['h']} | {r['n']} | {f(r['ex_mean'])} | {f(r['ab_mean'])} | {r['t']} | "
                 f"{r['hit']} ({r['hit_lb']}) | {r['base_hit']} | {f(r['is'].get('ab_mean'))} | {f(r['oos'].get('ab_mean'))} | "
                 f"{f(r['bear'].get('ab_mean'))} | {r['grade']} |")
    w = o["when"]
    L += ["", "## 매집은 언제", f"- 국면별 거래일 비중 {w['regime_share_days']} · 하루 평균 매집 시작 종목 수 {w['onsets_per_day_by_regime']}",
          f"- 매집 시작 종목 직전 20일 수익 중앙값 {w['onset_prior']['ret20_median']} (적격 전체 {w['onset_prior']['univ_ret20_median']}), "
          f"20일 수익 ≤0 비중 {w['onset_prior']['share_ret20_le0']} (전체 {w['onset_prior']['univ_share_ret20_le0']})",
          f"- 시장 5분위: {json.dumps(w['market_quintiles'], ensure_ascii=False)}", "", "## 한계", *[f"- {x}" for x in o["caveats"]]]
    return "\n".join(L) + "\n"


def main() -> int:
    df = accum.load_store()
    if df.empty:
        print("저장소 비어 있음 — data/flows 백필 필요")
        return 1
    names = accum.load_names()
    k = kospi_series()
    d = add_market(prepare(df, names), k)
    rows, base = evaluate(d)
    o = {"id": "accum_signals", "asof": datetime.now(KST).strftime("%Y-%m-%d"),
         "generated_at": datetime.now(KST).isoformat(timespec="minutes"), "source": "data/flows/kr_inv_*.parquet (pykrx/KRX) · data/hist/kr_index_daily.parquet",
         "status": "ok", "topic": "kr_accum", "m": M, "alpha": round(ALPHA, 5),
         "prereg": {"m": M, "alpha": ALPHA, "split": SPLIT, "min_n": MIN_N, "min_months": MIN_MONTHS, "entry": "t+1 종가",
                    "horizons": list(H), "signals": accum.SIGNALS},
         "data": {"first": str(df["date"].min().date()), "last": str(df["date"].max().date()),
                  "days": int(df["date"].nunique()), "codes": int(df["code"].nunique())},
         "base": {str(h): v for h, v in base.items()}, "results": rows, "when": when(d, k),
         "grades_doc": "A=Bonferroni 통과+IS·OOS·조정/하락 부호 일치 · B=Bonferroni 통과 · C=보정 전 p<0.10 · F=효과 없음 · 검증전=n<100 또는 월<12",
         "caveats": ["거래비용·슬리피지 미반영 — 5일 보유 신호는 왕복 0.25%p 를 빼면 대부분 사라질 수 있다",
                     "데이터 기간이 짧고 2025~26 강세장 비중이 커서 '하락' 국면 표본이 적다 → 국면별 결과는 참고",
                     "상위 10% 문턱(%시총)은 소형주 쪽으로 치우친다 — 규모·유동성 통제 안 함",
                     "기관합계에는 금융투자(차익·LP·헤지) 매매가 섞인다 — 연기금·투신을 따로 본 이유",
                     "ETF·ETN 제외: ETF 의 '기관' 순매수는 LP 가 개인 매매를 받아주는 거울이라 매집으로 읽지 않는다",
                     "월 군집 SE 는 같은 달 이벤트 상관을 고치지만 국면 집중(강세장 몇 달)은 못 고친다(kb:quant#20)"]}
    OUT.write_text(json.dumps(o, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    MD.write_text(_with_top(o, render_md(o)), encoding="utf-8")
    for r in rows:
        print(f"{r['sig']:<10} h{r['h']:<3} n{r['n']:<6} ex {r['ex_mean']} ab {r['ab_mean']} t {r['t']} hit {r['hit']}/{r['hit_lb']} base {r['base_hit']} {r['grade']}")
    print(json.dumps(o["when"], ensure_ascii=False)[:1500])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
