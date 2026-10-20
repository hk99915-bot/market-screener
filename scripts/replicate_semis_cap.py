"""독립 재현: semis_cap H1 밴드(40/45/30) vs 고정캡 CAP40M vs 보유 BH (검증 데스크)

명세: scripts/study_semis_cap.py 모듈 머리말(사전등록 0-1~0-3)만 읽음 — 함수 본문 미열람(kb:verify#8).
허용오차·뒤집힘 기준: reports/studies/replication_semis_cap.md §0 (실행 전 커밋 c7417adc).

  python scripts/replicate_semis_cap.py   → reports/studies/replication_semis_cap.{json,md}(§1 이하 갱신)
"""
from __future__ import annotations

import csv
import json
import math
import statistics as st
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
ORIG = ROOT / "reports/studies/semis_cap.json"
OUT_JSON = ROOT / "reports/studies/replication_semis_cap.json"
OUT_MD = ROOT / "reports/studies/replication_semis_cap.md"

COST, WIN, LAG, ALPHA = 0.00125, 250, 11, 0.05 / 7
IS_END = "2019-12-31"


def regime_and_rebound(kospi: list[float]) -> tuple[list[bool], list[bool], int]:
    """(하락장 여부, 반등일 여부, SMA200 첫 인덱스)."""
    n = len(kospi)
    bear, reb = [False] * n, [False] * n
    for i in range(n):
        if i >= 199:
            sma = sum(kospi[i - 199:i + 1]) / 200
            hi20 = max(kospi[max(0, i - 19):i + 1])
            bear[i] = kospi[i] < sma or kospi[i] <= hi20 * 0.85
        if i >= 1:
            reb[i] = kospi[i] / kospi[i - 1] - 1 >= 0.005
    return bear, reb, 199


def semis_returns(dates: list[date], a: list[float], b: list[float]) -> list[float]:
    """50/50 두 종목, 달 마지막 거래일 종가에 재조정. 반환 일간 수익(첫날 0)."""
    out, va, vb = [0.0], 0.5, 0.5
    for i in range(1, len(dates)):
        na, nb = va * a[i] / a[i - 1], vb * b[i] / b[i - 1]
        out.append((na + nb) / (va + vb) - 1)
        va, vb = na, nb
        if i + 1 < len(dates) and dates[i + 1].month != dates[i].month:
            t = va + vb; va = vb = t / 2
    return out


def simulate(policy: str, s: int, e: int, dates, rs, rr, bear, reb) -> dict:
    """[s, e] 구간을 40/60 으로 시작해 일별 진행. policy ∈ BH, CAP40M, BAND."""
    S, R = 0.4, 0.6
    vals, ws, traded, sells, buys = [1.0], [0.4], 0.0, 0, 0
    pend_cap = wait_sell = pend_buy = False

    def trade_to(target):
        nonlocal S, R, traded
        V = S + R
        amt = S - target * V
        S -= amt; R += amt
        R -= abs(amt) * COST
        traded += abs(amt)
        return amt

    for i in range(s + 1, e + 1):
        S *= 1 + rs[i]; R *= 1 + rr[i]
        w = S / (S + R)
        if policy == "CAP40M" and pend_cap:
            pend_cap = False
            if w > 0.40:
                trade_to(0.40); sells += 1
        if policy == "BAND":
            if wait_sell and reb[i]:
                wait_sell = False
                if w > 0.40:
                    trade_to(0.40); sells += 1
            if pend_buy:
                pend_buy = False
                if w < 0.40:
                    trade_to(0.40); buys += 1
        w = S / (S + R)
        last_m = i + 1 >= len(dates) or dates[i + 1].month != dates[i].month
        last_w = i + 1 >= len(dates) or dates[i + 1].isocalendar()[:2] != dates[i].isocalendar()[:2]
        if policy == "CAP40M" and last_m and w > 0.40:
            pend_cap = True
        if policy == "BAND" and last_w and not wait_sell:
            if w > 0.45:
                wait_sell = True
            elif w < 0.30 and not bear[i]:
                pend_buy = True
        vals.append(S + R); ws.append(w)
    peak, mdd = vals[0], 0.0
    for v in vals:
        peak = max(peak, v); mdd = min(mdd, v / peak - 1)
    return {"ret": vals[-1] / vals[0] - 1, "mdd": mdd, "sells": sells, "buys": buys,
            "turnover": traded / st.mean(vals), "w_mean": st.mean(ws), "w_max": max(ws), "vals": vals}


def windows(dates, first: int) -> list[int]:
    out = []
    for i in range(first, len(dates)):
        if (i == 0 or dates[i].month != dates[i - 1].month) and i + WIN < len(dates):
            out.append(i)
    return out


def nw_test(d: list[float], lag: int = LAG) -> dict:
    n = len(d); m = st.mean(d); x = [a - m for a in d]
    g = lambda k: sum(x[t] * x[t - k] for t in range(k, n)) / n
    var = g(0) + 2 * sum((1 - k / (lag + 1)) * g(k) for k in range(1, min(lag, n - 1) + 1))
    se = math.sqrt(max(var, 0) / n)
    t = m / se if se else 0.0
    p = math.erfc(abs(t) / math.sqrt(2))
    return {"n": n, "mean": m, "se": se, "t": t, "p": p}


def grade(all_, is_, oos) -> str:
    if all_["p"] < ALPHA:
        same = (all_["mean"] > 0) == (is_["mean"] > 0) == (oos["mean"] > 0)
        return "A" if same else "B"
    return "C" if all_["p"] < 0.10 else "F"


def run(dates, rs, rr, kospi) -> dict:
    bear, reb, first = regime_and_rebound(kospi)
    W = windows(dates, first)
    res = {p: [simulate(p, s, s + WIN, dates, rs, rr, bear, reb) for s in W] for p in ("BH", "CAP40M", "BAND")}
    is_mask = [dates[s].isoformat() <= IS_END for s in W]
    tests = {}
    for a, b in (("BAND", "CAP40M"), ("BAND", "BH"), ("CAP40M", "BH")):
        d = [x["ret"] - y["ret"] for x, y in zip(res[a], res[b])]
        al, i_, o_ = nw_test(d), nw_test([v for v, m in zip(d, is_mask) if m]), nw_test([v for v, m in zip(d, is_mask) if not m])
        tests[f"{a}-{b}"] = {"all": al, "is": i_, "oos": o_, "grade": grade(al, i_, o_),
                             "mdd_diff": st.mean(x["mdd"] for x in res[a]) - st.mean(y["mdd"] for y in res[b])}
    summ = {p: {"ret12_mean": st.mean(x["ret"] for x in v), "ret12_sd": st.pstdev([x["ret"] for x in v]),
                "mdd_mean": st.mean(x["mdd"] for x in v), "sells_mean": st.mean(x["sells"] for x in v),
                "w_mean": st.mean(x["w_mean"] for x in v)} for p, v in res.items()}
    hit = [x["w_max"] >= 0.45 for x in res["BH"]]
    full = {p: simulate(p, first, len(dates) - 1, dates, rs, rr, bear, reb) for p in ("BH", "CAP40M", "BAND")}
    return {"windows": {"n": len(W), "is": sum(is_mask), "oos": len(W) - sum(is_mask),
                        "first": dates[W[0]].isoformat(), "last": dates[W[-1]].isoformat(), "path_start": dates[first].isoformat()},
            "summary": summ, "tests": tests, "hit45": {"all": sum(hit) / len(hit)},
            "full_path": {p: {"n_sell": v["sells"], "n_buy": v["buys"], "mdd": v["mdd"]} for p, v in full.items()}}


def load() -> tuple:
    from screener.lab import load_kr
    import polars as pl
    px = load_kr().filter(pl.col("yf").is_in(["005930.KS", "000660.KS"])).select("yf", "date", "c")
    a = {d: c for d, c in px.filter(pl.col("yf") == "005930.KS").select("date", "c").iter_rows()}
    b = {d: c for d, c in px.filter(pl.col("yf") == "000660.KS").select("date", "c").iter_rows()}
    k, k2 = {}, {}
    with open(ROOT / "data/deriv/daily.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["kospi_close"] and r["k200_close"]:
                d = date.fromisoformat(r["date"]); k[d] = float(r["kospi_close"]); k2[d] = float(r["k200_close"])
    dates = sorted(set(a) & set(b) & set(k))
    end = date.fromisoformat(json.loads(ORIG.read_text(encoding="utf-8"))["data"]["end"])  # 원 연구 데이터 기준일에 맞춤(판 차이 제거)
    dates = [d for d in dates if date(2010, 1, 4) <= d <= end]
    sa, sb = [a[d] for d in dates], [b[d] for d in dates]
    rs = semis_returns(dates, sa, sb)
    rr = [0.0] + [k2[dates[i]] / k2[dates[i - 1]] - 1 for i in range(1, len(dates))]
    return dates, rs, rr, [k[d] for d in dates]


def compare(orig: dict, rep: dict) -> list[dict]:
    rows = []
    od, rw = orig["data"], rep["windows"]
    for key, rk in (("windows", "n"), ("windows_is", "is"), ("windows_oos", "oos")):
        rows.append({"item": key, "orig": od[key], "rep": rw[rk], "ok": abs(od[key] - rw[rk]) <= 1})
    rows.append({"item": "start", "orig": od["start"], "rep": rw["path_start"], "ok": od["start"] == rw["path_start"]})
    osm, n_eff = orig["results"]["H1"]["summary"], rw["n"] / 12
    for p, v in rep["summary"].items():
        tol = max(1e-4, 0.5 * v["ret12_sd"] / math.sqrt(n_eff))
        rows.append({"item": f"{p} 12개월 수익 평균", "orig": osm[p]["ret12_mean"], "rep": v["ret12_mean"], "ok": abs(osm[p]["ret12_mean"] - v["ret12_mean"]) <= tol, "tol": tol})
        rows.append({"item": f"{p} 윈도 MDD 평균", "orig": osm[p]["mdd_mean"], "rep": v["mdd_mean"], "ok": None})
        rows.append({"item": f"{p} 매도 횟수/윈도", "orig": osm[p]["sells_mean"], "rep": v["sells_mean"], "ok": None})
    ot = orig["results"]["H1"]["tests"]
    for k, v in rep["tests"].items():
        o = ot.get(k, {})
        for part in ("all", "is", "oos"):
            tol = max(1e-4, 0.5 * v[part]["se"])
            rows.append({"item": f"{k} d {part}", "orig": o.get(part, {}).get("mean"), "rep": v[part]["mean"],
                         "orig_p": o.get(part, {}).get("p"), "rep_p": v[part]["p"],
                         "ok": o.get(part) is not None and abs(o[part]["mean"] - v[part]["mean"]) <= tol, "tol": tol})
        rows.append({"item": f"{k} 등급", "orig": o.get("grade"), "rep": v["grade"], "ok": o.get("grade") == v["grade"]})
    oh = orig["claims"]["band45_rare"]["share_12m_windows_hit"]; rh_ = rep["hit45"]["all"]
    tol = max(1e-3, 0.5 * math.sqrt(rh_ * (1 - rh_) / n_eff))
    rows.append({"item": "45% 도달 윈도 비율", "orig": oh, "rep": rh_, "ok": abs(oh - rh_) <= tol, "tol": tol})
    for p in ("CAP40M", "BAND"):
        o = orig["results"]["full_path"][p]["n_sell"]; r = rep["full_path"][p]["n_sell"]
        rows.append({"item": f"{p} 전체 경로 매도 횟수", "orig": o, "rep": r, "ok": abs(o - r) <= max(1, 0.1 * o)})
    return rows


def _f(x):
    if isinstance(x, float):
        return f"{x * 100:+.2f}%" if abs(x) < 5 else f"{x:.2f}"
    return "—" if x is None else str(x)


def render(rows, rep) -> str:
    L = ["", "## 1. 실행", f"- 실행 {date.today().isoformat()} · §0 커밋 `c7417adc` · 원 함수 본문 미열람.",
         f"- 윈도 {rep['windows']['n']}개(IS {rep['windows']['is']} / OOS {rep['windows']['oos']}), 시작 {rep['windows']['first']}~{rep['windows']['last']}, 경로 시작 {rep['windows']['path_start']}.",
         "", "## 2. 원 vs 재현", "| 항목 | 원 | 재현 | p 원 / 재현 | 판정 |", "|---|---|---|---|---|"]
    for r in rows:
        pp = f"{r['orig_p']:.3f} / {r['rep_p']:.3f}" if r.get("orig_p") is not None else ""
        v = "서술" if r["ok"] is None else ("일치" if r["ok"] else "**불일치**")
        L.append(f"| {r['item']} | {_f(r['orig'])} | {_f(r['rep'])} | {pp} | {v} |")
    return "\n".join(L) + "\n"


VERDICT = """
## 3. 판정 (§0.4 기준)
- **H1 재현 일치 — 원 결론 유지.** 윈도 집합 180/110/70 일치, 안별 12개월 수익 3/3·d 평균 9/9 허용오차 안, 등급 3/3(C·F·F) 일치, 45% 도달 45.6% 일치(PB 주장 ① '틀림(자주 걸림)' 그대로).
- 핵심: BAND−CAP40M 원 +0.35%p(p 0.029) vs 재현 +0.32%p(p 0.026) → 둘 다 Bonferroni 0.00714 미달 **C**. '채택 후보' 문구의 숫자 근거는 재현됐다. 재현 숫자 기준 인용 제안: "+0.3%p/년, p 0.03, C".
- 불일치 2건(결론 불변, 원인 분류 kb:verify#2 ③):
  - 경로 시작 2010-10-20 vs 원 2010-10-21 — SMA200 을 '오늘 포함 200일'로 셌다(원은 하루 뒤). **창 정의**, 윈도 시작(월 첫 거래일)에는 영향 없음.
  - CAP40M 매도 횟수 전체 경로 52 vs 58, 윈도당 4.34 vs 4.82 — 재현은 체결일(다음 거래일)에 w ≤ 40% 로 내려와 있으면 매도하지 않는다(§0.2). 원은 판정일 초과분을 그대로 체결한 것으로 보임. **체결 정의**, 수익 차이 허용오차 안. 원 코드 미열람이라 `검증전`. → BAND 의 '매도 횟수 1/9' 은 재현 기준 **약 1/8**(0.53 vs 4.34/윈도)로 인용하자는 제안.
- 데이터 판 주의: 처음 실행은 로컬에 `data/kr_prices.parquet`(2026분)가 없어 윈도 170개로 ① 불일치 → `data_store.py pull --groups prices` 후 원 기준일(2026-10-16)로 잘라 재실행. 기준일 자르기는 §0 에 없던 조치 — 데이터 판 맞춤이라 정의 변경 아님(원·재현 같은 창고, kb:verify#6 공통 오류 가능).
- 반대 근거: 표본 전체가 반도체가 코스피200을 크게 이긴 16년(원 §1-1) — 이 재현은 계산만 확인한다. 방식 간 차이(+0.3%p)는 이 국면 의존일 수 있다.
- 범위 밖: **H2(원 등급 A)·H3 미재현** — A 등급이 걸린 H2 가 다음 재현 1순위(보드 rep-semis-cap).
- 🌙 22시 이후: 등급·규칙 변경 없음. 위 인용 문구 2개는 제안이며 반영은 퀀트·PB 확인 뒤.
- 코드 영향 범위: 신규 `scripts/replicate_semis_cap.py`·`tests/test_replicate_semis_cap.py`·이 보고서 2개. 롤백 = 네 파일 삭제.
"""


def main() -> int:
    dates, rs, rr, kospi = load()
    rep = run(dates, rs, rr, kospi)
    orig = json.loads(ORIG.read_text(encoding="utf-8"))
    rows = compare(orig, rep)
    OUT_JSON.write_text(json.dumps({"study": "replication_semis_cap", "orig": "reports/studies/semis_cap.json", "rep": rep, "rows": rows},
                                   ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    head = OUT_MD.read_text(encoding="utf-8").split("\n## 1. 실행")[0].rstrip() + "\n"
    OUT_MD.write_text(head + render(rows, rep) + VERDICT, encoding="utf-8")
    print(render(rows, rep))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
