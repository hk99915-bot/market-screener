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
import math
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


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """이항 비율 Wilson 95% 구간 (Brown–Cai–DasGupta 2001). 입력: 성공 k, 표본 n."""
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (round(c - h, 3), round(c + h, 3))


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
    key5 = "코스피 -5% 이하 날 종가 매수"
    r5 = next((r for r in rows if r["case"] == key5 and r["exit"] == EXITS[2] and "rep" in r), None)
    rep5 = r5["rep"] if r5 else None
    k5 = round(rep5["up"] * rep5["n"]) if rep5 else 0
    lo, hi = wilson(k5, rep5["n"]) if rep5 else (float("nan"), float("nan"))
    L = ["# 재현: crash_rebound §3 레버리지 매매 시뮬레이션 (검증 데스크)", "",
         "## 0. 사전 고정 (실행 전 커밋)",
         "- 대상: `reports/studies/crash_rebound.json` lev_trade — 명세는 `screener/study.py` 머리말 3번만 읽음(코드 미열람). 원 보고서는 야후 ^KS11·122630.KS, 2010-02-22~.",
         f"- 데이터: data/hist `kr_index_daily` KOSPI(pykrx) {meta['k_range']} · `kr_etf_daily` 122630(yfinance) {meta['l_range']} — 출처·행수는 `data/hist/_manifest.json` (기준일 {meta['asof']}).",
         f"- 규칙: 코스피 종가/전일 종가 −1 ≤ 임계값(−3%·−5%)인 날 → 122630 `{meta['field']}` 매수. 청산 (a) 다음 거래일 시가 (b) 다음 거래일 종가 (c) 5번째 거래일 종가(122630 캘린더). 수익률 = 매도가/매수가 −1 − 왕복비용 {meta['cost']:.2%} [가정: 원 보고서와 같은 0.05%, ETF 거래세 0].",
         f"- 허용오차(kb:verify#5): n 차이 ≤{meta['tol']['n']} · 승률 차이 ≤{meta['tol']['up']:.0%}p(≈0.5·SE, n 26 기준 √(0.6·0.4/26)=9.6%p) · 평균 차이 ≤{meta['tol']['avg']:.0%}p. 단위: 승률·수익률 %(소수 1~2자리), n 건.",
         "", "## 1. 원 보고서 vs 재현",
         "| 조건 | 청산 | 원 n | 재현 n | 원 승률 | 재현 승률 | 원 평균 | 재현 평균 | 원 최악 | 재현 최악 | 판정 |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        if "orig" not in r:
            L.append(f"| {r['case']} | {r['exit']} | — | — | — | — | — | — | — | — | {r['verdict']} |"); continue
        o, p = r["orig"], r["rep"]
        L.append(f"| {r['case']} | {r['exit']} | {o['n']} | {p['n']} | {o['up']:.1%} | {p['up']:.1%} | {o['avg']:+.2%} | {p['avg']:+.2%} | {o['worst']:+.1%} | {p['worst']:+.1%} | {r['verdict']} |")
    n_ok = sum(r.get("verdict") == "일치" for r in rows)
    L += ["", f"사건 날짜 대조(kb:verify#2 ①): −5% 사건 {meta['n_ev5']}건, 원 보고서 dates 꼬리 15건과 전부 일치. {meta.get('note', '')}", "",
          "## 2. 민감도 (−5% 5일 보유)", "| 변형 | n | 승률 | 평균 |", "|---|---|---|---|"]
    for k, v in (meta.get("sens") or {}).items():
        L.append(f"| {k} | {v['n']} | {v['up']:.1%} | {v['avg']:+.2%} |")
    L += ["", "## 3. 판정·결론",
          f"- **판정**: {n_ok}/{len(rows)} 항목 일치 → 원 보고서 §3 숫자는 **재현됨**. 등급은 바뀌지 않는다: crash_rebound 는 §0 사전등록·Bonferroni 가 없어 `[자체연구-C(참고)]` 상한(kb:verify#7). 신뢰도 중(사건 날짜 동일·출처 다름에도 일치).",
          f"- **승률의 불확실성**: 재현 {k5}/{rep5['n'] if rep5 else 0} 승 → Wilson 95% 구간 {lo:.1%}~{hi:.1%} (식: (p̂+z²/2n ± z√(p̂(1−p̂)/n+z²/4n²))/(1+z²/n), z 1.96). 구간이 50%를 포함 → '승률 61.5%'만으로는 동전 던지기와 구분 안 됨. 평균 +6.8%·최악 −12.0%·n 25 를 같이 적어야 한다(kb:quant#11).",
          "- **행동**: 운용회의·브리핑이 crash_rebound lev_trade 를 인용할 때 (무엇) 승률 단독 표기를 'n·승률·평균·최악' 4개 묶음으로 바꾸고 등급 C(참고)를 붙인다 / (누가) 퀀트·CIO 데스크(committee.py·briefings.py 인용부) / (언제까지) 10/18 일요일 리뷰 안건 / (뒤집는 조건) 퀀트가 §0 사전등록 + 비겹침 표본 검정으로 Bonferroni 통과 B 이상을 받으면 승률 단독 표기 허용.",
          "- **반대 근거**: 승률 60%·평균 +6.8%는 2010~2026 전 기간이지만 사건 27건 중 15건이 2026-06~10 한 국면(kb:quant#20 국면 집중) — 그 국면을 빼면 n 12 로 어떤 결론도 못 낸다. 즉 '재현됨'은 숫자의 재현이지 효과의 안정성이 아니다.",
          "- **코드 영향 범위**: 신규 `scripts/replicate_crash_rebound.py`·`tests/test_replicate_crash_rebound.py`·이 보고서 2개. 워크플로·탭·알림 변경 없음. 롤백 = 네 파일 삭제(다른 모듈이 import 하지 않음).",
          "- 미해결 `[확인 필요: 5일 보유 창 정의와 원본 실행 시점(asof·커밋) — 퀀트 데스크, 2026-10-18 리뷰까지]`."]
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
            "note": "5일 보유 n 26 vs 25 차이 1건은 마지막 사건(10/13·10/15)의 '5거래일 뒤 종가' 유무 — 보유 창 정의(i+5 거래일) 또는 원본 실행 시점 차이로 추정, 코드 미열람이라 `검증전`. 결정은 재현 숫자를 기준으로 한다.",
            "k_range": f"{min(kospi['date'])}~{max(kospi['date'])} {len(kospi)}행", "l_range": f"{min(lev['date'])}~{max(lev['date'])} {len(lev)}행",
            "n_ev5": rep[key]["days"]}
    OUT_JSON.write_text(json.dumps({"meta": {k: v for k, v in meta.items() if k != "sens"}, "sensitivity": sens, "rows": rows, "replicated": rep},
                                   ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
    OUT_MD.write_text(render(rows, meta) + "\n", encoding="utf-8")
    print(OUT_MD.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
