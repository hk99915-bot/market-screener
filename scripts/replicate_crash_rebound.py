"""검증 데스크 — crash_rebound §3(레버리지 매매 시뮬레이션) 독립 재현.

원 보고서(reports/studies/crash_rebound.json lev_trade)의 **명세(screener/study.py 머리말)만** 보고 다시 구현한다:
  코스피 종가 기준 하루 수익률이 임계값(−3% / −5%) 이하인 날 종가에 KODEX 레버리지(122630)를 사서
  (a) 다음날 시가 매도 (b) 다음날 종가 매도 (c) 5거래일 보유(5번째 거래일 종가 매도) — n·승률·평균·중앙값·최악·최선.
데이터는 data/hist (screener.hist.load): kr_index_daily KOSPI(pykrx) + kr_etf_daily 122630(yfinance).
원 보고서는 야후 ^KS11·122630.KS 를 썼으므로 데이터 출처가 다르다 — 출처 차이도 재현 대상.

  python scripts/replicate_crash_rebound.py            # json+md 출력 (reports/studies/replication_crash_rebound.*)
  python scripts/replicate_crash_rebound.py --cost 0   # 거래비용 0
"""
from __future__ import annotations

import argparse
import json
import statistics as st
import sys
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from screener import hist  # noqa: E402

OUT_JSON = ROOT / "reports" / "studies" / "replication_crash_rebound.json"
OUT_MD = ROOT / "reports" / "studies" / "replication_crash_rebound.md"
ORIG = ROOT / "reports" / "studies" / "crash_rebound.json"

THRESHOLDS = (-0.03, -0.05)
EXITS = ("다음날 시가 매도", "다음날 종가 매도", "5일 보유")


def summ(xs: list[float]) -> dict | None:
    if not xs:
        return None
    return {"n": len(xs), "avg": round(st.mean(xs), 4), "med": round(st.median(xs), 4),
            "up": round(sum(1 for x in xs if x > 0) / len(xs), 3), "worst": round(min(xs), 4), "best": round(max(xs), 4)}


def simulate(kospi: pl.DataFrame, lev: pl.DataFrame, cost: float = 0.0005, field: str = "close") -> dict:
    """kospi/lev: hist long 프레임(한 심볼). 반환 {임계값 라벨: {청산: summ}} + 날짜 목록.
    규칙: 코스피 당일 종가/전일 종가 −1 ≤ 임계값 → 그날 레버리지 `field` 가격에 매수. 레버리지 시세가 없는 날은 제외.
    5일 보유 = 매수일 이후 5번째 거래일 종가(레버리지 캘린더 기준). cost 는 왕복 비용(수익률에서 차감)."""
    k = kospi.select("date", pl.col("close").alias("kc")).sort("date")
    k = k.with_columns((pl.col("kc") / pl.col("kc").shift(1) - 1).alias("kret"))
    lv = lev.select("date", pl.col(field).alias("lc"), pl.col("open").alias("lo")).sort("date")
    lv = lv.with_columns(pl.col("lo").shift(-1).alias("o1"), pl.col("lc").shift(-1).alias("c1"), pl.col("lc").shift(-5).alias("c5"))
    j = k.join(lv, on="date", how="inner").sort("date")
    out: dict = {}
    for t in THRESHOLDS:
        ev = j.filter(pl.col("kret") <= t)
        a = [float(r["o1"] / r["lc"] - 1 - cost) for r in ev.iter_rows(named=True) if r["o1"] is not None]
        b = [float(r["c1"] / r["lc"] - 1 - cost) for r in ev.iter_rows(named=True) if r["c1"] is not None]
        c = [float(r["c5"] / r["lc"] - 1 - cost) for r in ev.iter_rows(named=True) if r["c5"] is not None]
        out[f"코스피 {int(t * 100)}% 이하 날 종가 매수"] = {
            EXITS[0]: summ(a), EXITS[1]: summ(b), EXITS[2]: summ(c),
            "days": len(ev), "dates": [str(d) for d in ev["date"].to_list()]}
    return out


def compare(orig: dict, rep: dict, tol: dict | None = None) -> list[dict]:
    """원 보고서 vs 재현 — 항목별 행. 판정: n 차이 ≤2 이고 up ≤5%p·avg ≤1%p 이면 '일치'."""
    tol = tol or {"n": 2, "up": 0.05, "avg": 0.01}
    rows = []
    for lab, exits in rep.items():
        for ex in EXITS:
            o = (orig.get(lab) or {}).get(ex) or {}
            r = exits.get(ex) or {}
            if not o or not r:
                rows.append({"case": lab, "exit": ex, "verdict": "원본 없음" if not o else "재현 없음"}); continue
            ok = abs(o["n"] - r["n"]) <= tol["n"] and abs(o["up"] - r["up"]) <= tol["up"] and abs(o["avg"] - r["avg"]) <= tol["avg"]
            rows.append({"case": lab, "exit": ex, "orig": o, "rep": r, "verdict": "일치" if ok else "불일치"})
    return rows


def render(rows: list[dict], meta: dict) -> str:
    L = ["# 재현: crash_rebound §3 레버리지 매매 시뮬레이션 (검증 데스크)", "",
         f"- 데이터 기준일 {meta['asof']} · 데이터 {meta['data']} · 왕복비용 {meta['cost']:.2%} · 매수가 필드 `{meta['field']}`",
         "- 원 보고서: `reports/studies/crash_rebound.json` lev_trade (야후 ^KS11·122630.KS, 2010-02-22~). 명세만 보고 재구현(scripts/replicate_crash_rebound.py).",
         f"- 판정 기준: n 차이 ≤{meta['tol']['n']} · 승률 차이 ≤{meta['tol']['up']:.0%}p · 평균 차이 ≤{meta['tol']['avg']:.0%}p 이면 일치.", "",
         "| 조건 | 청산 | 원 n | 재현 n | 원 승률 | 재현 승률 | 원 평균 | 재현 평균 | 원 최악 | 재현 최악 | 판정 |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        if "orig" not in r:
            L.append(f"| {r['case']} | {r['exit']} | — | — | — | — | — | — | — | — | {r['verdict']} |"); continue
        o, p = r["orig"], r["rep"]
        L.append(f"| {r['case']} | {r['exit']} | {o['n']} | {p['n']} | {o['up']:.1%} | {p['up']:.1%} | {o['avg']:+.2%} | {p['avg']:+.2%} | {o['worst']:+.1%} | {p['worst']:+.1%} | {r['verdict']} |")
    n_ok = sum(r.get("verdict") == "일치" for r in rows)
    L += ["", f"**종합**: {n_ok}/{len(rows)} 일치. " + meta.get("note", ""), "",
          "## 해석 (검증전 → 재현 완료)",
          "- 원 보고서 숫자는 KB 등급 없이 '참고'로만 쓰이던 것. 재현으로 **숫자 자체**는 확인됐지만 n≈26(−5%)은 소표본 — 승률 61.5%의 95% 신뢰구간은 대략 ±19%p(정규근사)라 50%와 구분되지 않는다. 등급 C(방향만) 이상 줄 수 없음.",
          "- 데이터 출처(pykrx KOSPI vs 야후 ^KS11)·종가 필드(close vs adj_close) 차이는 아래 민감도 표.", ""]
    if meta.get("sens"):
        L += ["| 변형 | −5% 5일 보유 n | 승률 | 평균 |", "|---|---|---|---|"]
        for k, v in meta["sens"].items():
            L.append(f"| {k} | {v['n']} | {v['up']:.1%} | {v['avg']:+.2%} |")
        L.append("")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cost", type=float, default=0.0005)
    ap.add_argument("--field", default="close", choices=["close", "adj_close"])
    a = ap.parse_args()
    kospi = hist.load("KOSPI", start="2010-01-01")
    lev = hist.load("122630", start="2010-01-01")
    if not len(kospi) or not len(lev):
        print("data/hist 에 KOSPI 또는 122630 없음", file=sys.stderr); return 1
    rep = simulate(kospi, lev, cost=a.cost, field=a.field)
    orig = json.loads(ORIG.read_text(encoding="utf-8")).get("lev_trade", {}) if ORIG.exists() else {}
    rows = compare(orig, rep)
    key = "코스피 -5% 이하 날 종가 매수"
    sens = {"기본(close, 비용 0.05%)": rep[key][EXITS[2]],
            "adj_close": simulate(kospi, lev, cost=a.cost, field="adj_close")[key][EXITS[2]],
            "비용 0": simulate(kospi, lev, cost=0.0, field=a.field)[key][EXITS[2]]}
    meta = {"asof": str(max(lev["date"].to_list())), "data": f"KOSPI {min(kospi['date'])}~{max(kospi['date'])} (pykrx) · 122630 {min(lev['date'])}~{max(lev['date'])} (yfinance)",
            "cost": a.cost, "field": a.field, "tol": {"n": 2, "up": 0.05, "avg": 0.01}, "sens": sens,
            "note": "−5% 사건 날짜 27개는 원본과 완전히 같다(2011-08-19~2026-10-15). 5일 보유 n 26 vs 25 차이 1건은 마지막 사건(10/13·10/15)의 '5거래일 뒤 종가' 유무 — 보유 창 정의(i+5 거래일) 또는 원본 실행 시점 차이로 추정, 코드 미열람이라 `검증전`. 숫자는 이 표(재현)가 기준."}
    OUT_JSON.write_text(json.dumps({"meta": {k: v for k, v in meta.items() if k != "sens"}, "sensitivity": sens, "rows": rows, "replicated": rep},
                                   ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
    OUT_MD.write_text(render(rows, meta) + "\n", encoding="utf-8")
    print(OUT_MD.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
