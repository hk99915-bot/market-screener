"""신규 추세 진입 신호 발굴 레이어 — reports/trend_discovery_{KR,US}.json (퀀트 2026-10-24, 겸이 "신규추세진입신호를 더 발굴").

정식 '새로 켜진 추세 신호'(detail.sim_signals — Wilson 하한>0.5 · 기대값 t 하한>0, 사전등록
docs/valuation_notes/2026-10-17_trend_expectancy_prereg.md)는 **그대로 두고**, 그 옆에 '탐색' 레이어를 얹는다.
여기서 나온 것은 전부 등급 **탐색(사전등록 전) · 상한 C** · 주문표 근거 불가(not_for_orders=true).

블록
  diagnosis  정식 규칙이 왜 0건인지 깔때기 숫자(슬롯 → 보유 중 → 새로 켜짐 → 거래≥6 → 통과, fresh·창 완화 시 몇 건)
  near_miss  (a) 근접 후보: 정식 전략(이평·PSAR 롱) 중 ① Wilson 하한 0.45~0.50 ② 기대값 t 하한 −0.5%p~0
             ③ 정식 문턱 통과인데 진입 3~5거래일 전(fresh 밖). 각 띠의 귀무 우연 기대 건수 병기.
  explore    (b) 새 추세 진입 전략군 4개 — 3년(최대 756거래일) 이력, 정식과 같은 체결·비용(detail._sim_one), 같은 문턱:
               hi52 52주 신고가 돌파(종가 > 직전 252일 최고 종가) → 종가<SMA50 청산
               gcv  20/50일선 골든크로스 + 거래량(5일 평균 ≥ 50일 평균×1.2) → SMA20<SMA50 청산
               sqz  변동성 수축 뒤 돌파(직전 5일 중 밴드폭이 250일 하위 20% + 종가 > 직전 20일 최고가) → 종가<SMA20 청산
               ma3·psar3  정식 두 전략을 3년 창으로 다시 돌린 것(창 길이 진단용)
             새로 켜짐 = 보유 중 + 진입 ≤ 4거래일 전(최근 5거래일). 우연 기대 = Σ P_null(Wilson) + 0.05·m(기대값).
  chase      HF 4차 S4/S6 패턴(거래량 ≥ 20일 평균×3 · 종가 = 20일 최고 종가)이 진입~오늘 사이에 있으면 '추격 주의'.
             국장은 S4 가 F·반대 방향(검증 t −6.17, reports/studies/2026-10-21_hf_desk_signals.md) → 후보 목록에서 빼고 따로 표시.
             미장 S6 은 F(효과 없음) → 후보에 남기되 꼬리표.
  accum_x    누적매집(US us_accum hits · KR accum top 강세 태그) + 추세(정식·탐색 아무거나) 동시 켜짐 — 백테스트 없음, 목록만.
  sectors    (c) 업종(peers_{M}.json 'g')별 새로 켜짐 비율 vs 시장 전체 — 이항 위꼬리 p, Bonferroni α = 0.05/m(업종 수).

데이터: reports/detail/{M}/*.json chart(최근 260봉) + data/hist/{kr,us}_YYYY.parquet(이전 구간, 겹치는 날 종가 비율 중앙값으로
  맞춤 — 비율 흩어짐 > 2% 면 이어붙이지 않고 chart 만 사용). 생존편향(현재 구성)·같은 장세 상관·비용 0.25% 고정 가정.
"""
from __future__ import annotations

import json
import logging
import math
from datetime import date
from pathlib import Path

from .config import REPORT_DIR

log = logging.getLogger(__name__)

DATA_HIST = REPORT_DIR.parent / "data" / "hist"
YEARS = 3                    # 탐색 전략 백테스트 창(달력 연) — 최대 756거래일
MAX_BARS = 756
FRESH_EXPLORE = 4            # 진입 ≤ 4거래일 전 = 최근 5거래일
NM_WILSON = (0.45, 0.50)
NM_EXP = (-0.005, 0.0)
NM_AGE = (2, 4)              # 정식 문턱 통과인데 진입 3~5번째 거래일 전
TOP = 30
LIST_MIN_TRADES = 3        # 탐색 목록 최소 청산 거래(검정 대상은 정식과 같은 6·8회)
GRADE = "탐색(사전등록 전) · 상한 C"
NOT_FOR_ORDERS = ("주문표 근거 불가 — 규정 [4] 근거 칸에 이 파일의 신호만 적은 주문은 근거 부족. "
                  "정식 신호는 sim_signals_{M}.json(사전등록 규칙)뿐이다. 매매 지시 아님.")
EXPLORE_STRATS = {
    "hi52": "52주 신고가 돌파 → SMA50 이탈 청산",
    "gcv": "20/50 골든크로스+거래량 → 데드크로스 청산",
    "sqz": "변동성 수축 뒤 20일 고가 돌파 → SMA20 이탈 청산",
    "ma3": "이평 추세 롱(정식 규칙, 3년 창)",
    "psar3": "PSAR 롱(정식 규칙, 3년 창)",
}
NEW_STRATS = ("hi52", "gcv", "sqz")
CHASE = {"KR": {"exclude": True, "why": "HF 4차 S4 국장 거래량 3배+20일 신고가 추격 F·반대 방향(검증 10일 −1.70%, t −6.17)"},
         "US": {"exclude": False, "why": "HF 4차 S6 미장 같은 패턴 F(검증 +0.53%, t 0.84 — 효과 없음)"}}


# ── 통계 ─────────────────────────────────────────────────────────────
def _phi(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def binom_tail(k: int, n: int, p: float) -> float:
    """P[X ≥ k | n, p]."""
    if n <= 0 or k <= 0:
        return 1.0
    return min(1.0, sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k, n + 1)))


def _wilson_band_null(n: int, lo: float, hi: float) -> float:
    """귀무(승률 0.5)에서 Wilson 하한이 [lo, hi] 에 들 확률."""
    from .detail import wilson_lo
    return sum(math.comb(n, k) * 0.5 ** n for k in range(n + 1) if lo <= (wilson_lo(k, n) or 0) <= hi)


def _exp_band_null(n: int, sd: float, lo: float) -> float:
    """귀무(평균 0)에서 t 하한이 (lo, 0] 에 들 확률 — 정규 근사: P[t > t95 + lo·√n/s] − 0.05."""
    from .detail import t95
    if not sd or n < 2:
        return 0.0
    q = t95(n - 1)
    return max(0.0, (1 - _phi(q + lo * math.sqrt(n) / sd)) - (1 - _phi(q)))


# ── 데이터 ───────────────────────────────────────────────────────────
def _j(p: Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def load_detail(market: str, detail_dir: Path | None = None) -> tuple[str | None, dict]:
    dd = Path(detail_dir or REPORT_DIR / "detail" / market)
    idx = _j(dd / "_index.json", {}) or {}
    out = {}
    for f in sorted(dd.glob("*.json")):
        if f.name.startswith("_"):
            continue
        d = _j(f, {}) or {}
        ch = [b for b in d.get("chart") or [] if b.get("t") and b.get("c") is not None]
        if ch:
            out[f.stem] = {"name": d.get("name"), "sim": d.get("sim") or {}, "chart": ch,
                           "sector": (d.get("valuation") or {}).get("sector") or d.get("theme")}
    return idx.get("asof"), out


def load_hist(market: str, asof: str, hist_dir: Path | None = None) -> dict[str, list[tuple]]:
    """{sym: [(date, open, high, low, close, volume)…]} — asof 연도 기준 YEARS 년 전부터."""
    hd = Path(hist_dir or DATA_HIST)
    pre = "kr" if market == "KR" else "us"
    y0 = int(asof[:4]) - YEARS
    out: dict[str, list[tuple]] = {}
    try:
        import polars as pl
    except Exception:  # noqa: BLE001
        return out
    for y in range(y0, int(asof[:4]) + 1):
        f = hd / f"{pre}_{y}.parquet"
        if not f.exists():
            continue
        try:
            df = pl.read_parquet(f, columns=["yf", "date", "open", "high", "low", "close", "volume"]).sort("yf", "date")
        except Exception as e:  # noqa: BLE001
            log.warning("hist 읽기 실패 %s: %s", f, e)
            continue
        for row in df.iter_rows():
            s = str(row[0]).split(".")[0] if market == "KR" else str(row[0])
            out.setdefault(s, []).append((str(row[1]), row[2], row[3], row[4], row[5], row[6]))
    return out


def splice(chart: list[dict], hist: list[tuple] | None) -> tuple[dict, str]:
    """chart(최근) 앞에 hist(과거)를 비율 맞춰 붙인다. 반환 (열 사전, 상태)."""
    t = [b["t"] for b in chart]
    cols = {"t": t, "o": [b.get("o") or b["c"] for b in chart], "h": [b.get("h") or b["c"] for b in chart],
            "l": [b.get("l") or b["c"] for b in chart], "c": [b["c"] for b in chart], "v": [b.get("v") or 0 for b in chart]}
    if not hist:
        return cols, "chart_only"
    cmap = dict(zip(t, cols["c"]))
    ratios = sorted(cmap[d] / c for d, _o, _h, _l, c, _v in hist if d in cmap and c)
    if len(ratios) < 20:
        return cols, "chart_only(겹침<20일)"
    med = ratios[len(ratios) // 2]
    if max(abs(r / med - 1) for r in ratios) > 0.02:
        return cols, "chart_only(비율 흩어짐>2%)"
    old = [x for x in hist if x[0] < t[0] and x[4]]
    k = med
    pre = {"t": [x[0] for x in old], "o": [(x[1] or x[4]) * k for x in old], "h": [(x[2] or x[4]) * k for x in old],
           "l": [(x[3] or x[4]) * k for x in old], "c": [x[4] * k for x in old], "v": [x[5] or 0 for x in old]}
    return {key: (pre[key] + cols[key])[-MAX_BARS:] for key in cols}, "spliced"


# ── 지표·전략 ─────────────────────────────────────────────────────────
def _sma(x: list[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(x)
    s = 0.0
    for i, v in enumerate(x):
        s += v
        if i >= n:
            s -= x[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def signals(cols: dict) -> dict[str, list[int]]:
    """전략별 상태 열 pos[i] ∈ {0,1} (i일 종가에 결정 → detail._sim_one 과 같은 체결)."""
    from .indicators import psar_np
    import numpy as np
    c, h, l, v = cols["c"], cols["h"], cols["l"], cols["v"]
    n = len(c)
    s20, s50 = _sma(c, 20), _sma(c, 50)
    v5, v50 = _sma(v, 5), _sma(v, 50)
    bw = [None] * n
    for i in range(19, n):
        w = c[i - 19:i + 1]
        m = sum(w) / 20
        bw[i] = 4 * (sum((x - m) ** 2 for x in w) / 20) ** 0.5 / m if m else None
    import pandas as pd
    thr = pd.Series([float("nan") if x is None else x for x in bw]).shift(1).rolling(250, min_periods=120).quantile(
        0.2, interpolation="lower").to_numpy()
    out = {k: [0] * n for k in EXPLORE_STRATS}
    st = {"hi52": 0, "gcv": 0, "sqz": 0}
    for i in range(n):
        if s50[i] is None:
            continue
        # hi52
        if st["hi52"]:
            st["hi52"] = 0 if c[i] < s50[i] else 1
        elif i >= 252 and c[i] > max(c[i - 252:i]):
            st["hi52"] = 1
        # gcv
        if st["gcv"]:
            st["gcv"] = 0 if s20[i] < s50[i] else 1
        elif (s50[i - 1] is not None and s20[i] > s50[i] and s20[i - 1] <= s50[i - 1]
              and v50[i] and v5[i] is not None and v5[i] >= 1.2 * v50[i]):
            st["gcv"] = 1
        # sqz
        if st["sqz"]:
            st["sqz"] = 0 if c[i] < s20[i] else 1
        elif i >= 140 and thr[i] == thr[i]:   # 사전등록 2026-10-24_trend_events §1 과 같은 백분위(pandas rolling quantile 'lower')
            if any(x is not None and x <= thr[i] for x in bw[i - 5:i]) and c[i] > max(h[i - 20:i]):
                st["sqz"] = 1
        out["hi52"][i], out["gcv"][i], out["sqz"][i] = st["hi52"], st["gcv"], st["sqz"]
        out["ma3"][i] = 1 if (c[i] > s50[i] and s20[i] > s50[i]) else 0
    ps = psar_np(np.array(h, float), np.array(l, float), np.array(c, float))
    out["psar3"] = [0 if (s50[i] is None or math.isnan(ps[i])) else int(c[i] > ps[i]) for i in range(n)]
    return out


def chase_days(cols: dict) -> list[bool]:
    """HF S4/S6: 거래량 ≥ 20일 평균(당일 포함)×3 이고 종가 = 20일 최고 종가."""
    c, v = cols["c"], cols["v"]
    v20 = _sma(v, 20)
    return [bool(i >= 19 and v20[i] and v[i] >= 3 * v20[i] and c[i] >= max(c[i - 19:i + 1])) for i in range(len(c))]


def _stats(r: dict) -> dict:
    from .detail import exp_lb, wilson_lo
    n = int(r.get("trades") or 0)
    w = int(r.get("wins") or 0)
    rets = r.get("rets") or []
    e = exp_lb(rets) if len(rets) >= 2 else None
    return {"trades": n, "wins": w, "win": round(w / n, 3) if n else None,
            "wilson_lo": round(wilson_lo(w, n), 3) if n else None,
            "exp": None if not e else round(e[0], 4), "sd": None if not e else round(e[1], 4),
            "exp_lb": None if not e else round(e[2], 4)}


def _age(dates: list[str], entry: str | None) -> int | None:
    if not entry or entry not in dates:
        return None
    return len(dates) - 1 - dates.index(entry)


def _passes(s: dict) -> dict:
    from .detail import EXP_LB_MIN, EXP_MIN_TRADES, FRESH_MIN_TRADES, FRESH_WILSON_MIN
    return {"wilson": s["trades"] >= FRESH_MIN_TRADES and (s["wilson_lo"] or 0) > FRESH_WILSON_MIN,
            "exp": s["trades"] >= EXP_MIN_TRADES and s["exp_lb"] is not None and s["exp_lb"] > EXP_LB_MIN}


# ── 블록 ─────────────────────────────────────────────────────────────
def diagnosis(stocks: dict) -> dict:
    """정식 규칙 깔때기 — detail sim(정식 창) 그대로."""
    from .detail import FRESH_STRATS
    slots = pos = 0
    fresh = {2: 0, 5: 0, 10: 0}
    fresh6 = {2: 0, 5: 0, 10: 0}
    pass_any = {"wilson": 0, "exp": 0}
    pass_pos = {"wilson": 0, "exp": 0}
    days, wr = [], []
    for v in stocks.values():
        sim = v["sim"]
        if not sim.get("days"):
            continue
        days.append(sim["days"])
        dts = [b["t"] for b in v["chart"]]
        for k in FRESH_STRATS:
            r = (sim.get(k) or {}).get("long") or {}
            slots += 1
            s = _stats(r)
            p = _passes(s)
            if s["trades"] >= 6:
                wr.append(s["wins"] / s["trades"])
            for key in p:
                pass_any[key] += p[key]
            if r.get("pos") == 1:
                pos += 1
                for key in p:
                    pass_pos[key] += p[key]
                a = _age(dts, r.get("entry_date"))
                for t in fresh:
                    if a is not None and a < t:
                        fresh[t] += 1
                        fresh6[t] += s["trades"] >= 6
    days.sort()
    wr.sort()
    md = lambda x: x[len(x) // 2] if x else None  # noqa: E731
    return {
        "n_scanned": len(days), "slots": slots, "pos_now": pos,
        "fresh_le": {f"{t}d": fresh[t] for t in fresh}, "fresh_le_trades6": {f"{t}d": fresh6[t] for t in fresh6},
        "pass_ignoring_fresh": pass_any, "pass_pos_any_age": pass_pos,
        "sim_days_median": md(days), "sim_days_min": days[0] if days else None,
        "winrate_median_trades6": None if not wr else round(md(wr), 3),
        "winrate_p75_trades6": None if not wr else round(wr[int(0.75 * len(wr))], 3),
        "read": ("fresh(진입 ≤ 직전 거래일)를 풀어도 통과가 늘지 않으면 묶는 조건은 승률·표본(창)이다. "
                 "'pass_ignoring_fresh' = 보유·진입일 무시하고 문턱만 본 통과 슬롯 수(상한)."),
    }


def near_miss(stocks: dict) -> dict:
    from .detail import EXP_MIN_TRADES, FRESH_MIN_TRADES, FRESH_STRATS, _pass_prob_null
    rows = []
    m = {"wilson_band": 0, "exp_band": 0, "stale_pass": 0}
    exp_chance = {"wilson_band": 0.0, "exp_band": 0.0, "stale_pass": 0.0}
    for sym, v in stocks.items():
        sim = v["sim"]
        if not sim.get("days"):
            continue
        dts = [b["t"] for b in v["chart"]]
        for k, label in FRESH_STRATS.items():
            r = (sim.get(k) or {}).get("long") or {}
            if r.get("pos") != 1:
                continue
            a = _age(dts, r.get("entry_date"))
            if a is None or a > NM_AGE[1]:
                continue
            s = _stats(r)
            p = _passes(s)
            why = []
            if a <= 1:
                if s["trades"] >= FRESH_MIN_TRADES:
                    m["wilson_band"] += 1
                    exp_chance["wilson_band"] += _wilson_band_null(s["trades"], *NM_WILSON)
                    if NM_WILSON[0] <= (s["wilson_lo"] or 0) <= NM_WILSON[1]:
                        why.append(f"Wilson 하한 {s['wilson_lo']:.3f} (문턱 0.5)")
                if s["trades"] >= EXP_MIN_TRADES and s["sd"]:
                    m["exp_band"] += 1
                    exp_chance["exp_band"] += _exp_band_null(s["trades"], s["sd"], NM_EXP[0])
                    if NM_EXP[0] < s["exp_lb"] <= NM_EXP[1]:
                        why.append(f"기대값 t 하한 {s['exp_lb'] * 100:+.2f}% (문턱 0)")
            else:
                if s["trades"] >= FRESH_MIN_TRADES:
                    m["stale_pass"] += 1
                    exp_chance["stale_pass"] += _pass_prob_null(s["trades"]) + (0.05 if s["trades"] >= EXP_MIN_TRADES else 0)
                    if p["wilson"] or p["exp"]:
                        why.append(f"정식 문턱 통과·진입 {a}거래일 전(fresh 밖)")
            if why:
                rows.append({"s": sym, "n": v["name"], "sector": v.get("g"), "strategy": k, "label": label, "age": a,
                             "entry_date": r.get("entry_date"), **s, "why": " · ".join(why)})
    rows.sort(key=lambda x: (-(x["exp_lb"] if x["exp_lb"] is not None else -9), -(x["wilson_lo"] or 0)))
    return {"bands": {"wilson": list(NM_WILSON), "exp_lb": list(NM_EXP), "stale_age": list(NM_AGE)},
            "m": m, "expected_chance": {k: round(x, 2) for k, x in exp_chance.items()},
            "n": len(rows), "rows": rows[:TOP],
            "note": ("근접 = 정식 문턱 바깥. 띠마다 m = 띠 판정 대상 수, 기대 = 귀무(승률 0.5 / 평균 0)에서 띠에 우연히 들 건수"
                     "(기대값 띠는 정규 근사). 관측 건수가 기대와 비슷하면 우연과 구분 안 됨.")}


def explore(stocks: dict, hist: dict, market: str, accum_syms: set[str]) -> dict:
    from .detail import EXP_MIN_TRADES, FRESH_MIN_TRADES, _pass_prob_null, _sim_one
    cand, chase_rows, accum_rows, fresh_new = [], [], [], []
    m_w = m_e = 0
    exp_w = 0.0
    pooled: dict[str, list[float]] = {k: [] for k in EXPLORE_STRATS}
    splice_cnt: dict[str, int] = {}
    nbars = []
    fresh_any: dict[str, bool] = {}
    by_s = {k: {"fresh": 0, "eligible_w": 0, "eligible_e": 0, "pass": 0, "chase": 0} for k in EXPLORE_STRATS}
    for sym, v in stocks.items():
        cols, how = splice(v["chart"], hist.get(sym))
        splice_cnt[how.split("(")[0]] = splice_cnt.get(how.split("(")[0], 0) + 1
        if len(cols["c"]) < 120:
            continue
        nbars.append(len(cols["c"]))
        sig = signals(cols)
        ch = chase_days(cols)
        dts = cols["t"]
        on = False
        for k, label in EXPLORE_STRATS.items():
            r = _sim_one(cols["c"], sig[k], dts)
            pooled[k].extend(r.get("rets") or [])
            if r.get("pos") != 1:
                continue
            a = _age(dts, r.get("entry_date"))
            if a is None or a > FRESH_EXPLORE:
                continue
            on = True
            s = _stats(r)
            p = _passes(s)
            b = by_s[k]
            b["fresh"] += 1
            b["eligible_w"] += s["trades"] >= FRESH_MIN_TRADES
            b["eligible_e"] += s["trades"] >= EXP_MIN_TRADES
            b["pass"] += bool(p["wilson"] or p["exp"])
            if s["trades"] >= FRESH_MIN_TRADES:
                m_w += 1
                exp_w += _pass_prob_null(s["trades"])
            if s["trades"] >= EXP_MIN_TRADES:
                m_e += 1
            chased = any(ch[len(ch) - 1 - a:])
            row = {"s": sym, "n": v["name"], "sector": v.get("g"), "strategy": k, "label": label, "age": a,
                   "entry_date": r.get("entry_date"), "bars": len(dts), "splice": how, **s,
                   "pass_wilson": p["wilson"], "pass_exp": p["exp"], "chase": chased,
                   "accum": sym in accum_syms, "open_ret": r.get("open_ret")}
            if sym in accum_syms:
                accum_rows.append(row)
            if chased:
                b["chase"] += 1
                row["chase_note"] = CHASE[market]["why"]
                if CHASE[market]["exclude"]:
                    chase_rows.append(row)
                    continue
            if k in NEW_STRATS:
                fresh_new.append(row)   # 새 전략군은 종목별 거래가 적어(3년 0~5회) 종목 검정이 구조적으로 불가 → 오늘 켜진 것 전부 + 전략 합산 통계
            if s["trades"] >= LIST_MIN_TRADES:
                row["n_short"] = s["trades"] < FRESH_MIN_TRADES   # 목록엔 두되 검정(m) 밖 — 표본 부족
                cand.append(row)
        # 정식 창 sim 도 accum 동시 켜짐 판단에 포함
        for k in ("ma", "psar"):
            r = (v["sim"].get(k) or {}).get("long") or {}
            a = _age([b["t"] for b in v["chart"]], r.get("entry_date")) if r.get("pos") == 1 else None
            if a is not None and a <= FRESH_EXPLORE:
                on = True
                if sym in accum_syms:
                    accum_rows.append({"s": sym, "n": v["name"], "sector": v.get("g"), "strategy": k, "age": a,
                                       "entry_date": r.get("entry_date"), **_stats(r), "accum": True, "window": "정식 창"})
        fresh_any[sym] = on
    key = lambda x: (-(x["pass_exp"] or x["pass_wilson"]), -(x["exp_lb"] if x["exp_lb"] is not None else -9), -(x["wilson_lo"] or 0))  # noqa: E731
    cand.sort(key=key)
    n_pass = sum(1 for x in cand if x["pass_wilson"] or x["pass_exp"])
    exp_total = exp_w + 0.05 * m_e
    m_tot = m_w + m_e
    pool = {}
    for k, rs in pooled.items():
        if len(rs) >= 2:
            mu = sum(rs) / len(rs)
            sd = (sum((x - mu) ** 2 for x in rs) / (len(rs) - 1)) ** 0.5
            pool[k] = {"trades": len(rs), "exp": round(mu, 4), "win": round(sum(x > 0 for x in rs) / len(rs), 3),
                       "t_naive": round(mu / (sd / len(rs) ** 0.5), 2) if sd else None}
    nbars.sort()
    return {
        "strategies": EXPLORE_STRATS, "fresh": f"보유 중 + 진입 ≤ {FRESH_EXPLORE}거래일 전",
        "window": f"최대 {MAX_BARS}거래일(hist+chart 이어붙임 — 이어붙이지 못한 종목은 chart 260봉뿐이라 hi52 사실상 못 켜짐, splice 칸 참고) · 종가 체결 · 왕복 0.25% · 문턱은 정식과 같음(Wilson>0.5·n≥6 / t 하한>0·n≥8)",
        "bars_median": nbars[len(nbars) // 2] if nbars else None, "splice": splice_cnt,
        "m_wilson": m_w, "m_exp": m_e, "n_pass": n_pass, "expected_chance": round(exp_total, 2),
        "binom_p": round(binom_tail(n_pass, m_tot, exp_total / m_tot), 4) if m_tot else None,
        "n_candidates": len(cand), "rows": cand[:TOP], "by_strategy": by_s,
        "fresh_new": {"n": len(fresh_new), "rows": sorted(fresh_new, key=lambda x: (not x["accum"], x["age"], x["strategy"]))[:60],
                      "note": ("새 전략군(hi52·gcv·sqz) 오늘 켜짐 전부 — 종목별 표본(3년 거래 0~5회)으로는 판정 불가라 검정 없이 목록만. "
                               "근거는 전략 합산(pooled) 한 줄뿐(생존편향·상관). 국장 추격 패턴은 chase 로 빠짐.")},
        "pooled": pool,
        "pooled_note": "전략별 전 종목 3년 거래 합산(겹침·같은 장세 상관 — t_naive 는 과대, 서술용).",
        "_fresh_any": fresh_any,
        "chase": {"rule": "거래량 ≥ 20일 평균×3 · 종가 = 20일 최고 종가가 진입일~오늘 중 하루라도",
                  "exclude_from_candidates": CHASE[market]["exclude"], "why": CHASE[market]["why"],
                  "n": len(chase_rows), "rows": chase_rows[:TOP]},
        "accum_x": {"rule": "누적매집 신호 + 추세(정식·탐색) 진입 ≤ 4거래일 동시", "n": len(accum_rows), "rows": accum_rows[:TOP]},
    }


def sectors(stocks: dict, fresh_any: dict[str, bool]) -> dict:
    tot = len(fresh_any)
    on = sum(fresh_any.values())
    p0 = on / tot if tot else 0
    g: dict[str, list[bool]] = {}
    for s, f in fresh_any.items():
        g.setdefault(stocks[s].get("g") or "기타", []).append(f)
    rows = []
    for name, fl in g.items():
        if len(fl) < 5:
            continue
        k = sum(fl)
        rows.append({"g": name, "n": len(fl), "on": k, "rate": round(k / len(fl), 3), "lift": round(k / len(fl) / p0, 2) if p0 else None,
                     "p_upper": round(binom_tail(k, len(fl), p0), 4)})
    m = len(rows)
    for r in rows:
        r["bonf_pass"] = m > 0 and r["p_upper"] < 0.05 / m
    rows.sort(key=lambda x: x["p_upper"])
    return {"market_rate": round(p0, 3), "n_stocks": tot, "n_on": on, "m": m, "alpha_bonf": round(0.05 / m, 4) if m else None,
            "rows": rows, "note": "새로 켜짐(정식·탐색 아무 전략, 진입 ≤ 4거래일) 비율의 업종 쏠림. 업종 n ≥ 5 만. 이항 위꼬리 p — 같은 업종 종목은 상관이라 낙관적."}


B1_MIN_VAL, B1_MIN_PX, B1_RATIO, B1_TOP = 1e9, 1000.0, 0.95, 15


def b1_ref(stocks: dict) -> dict:
    """KR 52주 고점 근접(alpha_sources B1, B 등급) 오늘 해당 종목 — 운용회의 참고 목록(겸이 결재 10/24, req-quant-b95c828b ②).
    정의 = scripts/study_alpha_sources.py features: 종가 / 250일 최고 고가 ≥ 0.95 · 20일 평균 거래대금 ≥ 10억원 · 종가 ≥ 1,000원.
    '새로' = 직전 거래일엔 0.95 미만. 등급은 연구(진입 규칙 tradeplan·H20) 기준이지 이 목록 자체의 검증이 아님 — 주문 근거 아님."""
    rows = []
    try:   # alpha_sources 와 같게 업종 분류(universe/kr_sector.csv) 있는 종목만 — ETF·채권형 제외
        import csv
        with open(REPORT_DIR.parent / "universe" / "kr_sector.csv", encoding="utf-8") as fh:
            secs = {r["code"]: r["sector"] for r in csv.DictReader(fh)}
    except Exception:  # noqa: BLE001
        secs = None
    for sym, v in stocks.items():
        ch = v["chart"]
        if len(ch) < 251 or (secs is not None and sym not in secs):
            continue
        c = [b["c"] for b in ch]
        h = [b.get("h") or b["c"] for b in ch]
        vol = [b.get("v") or 0 for b in ch]
        val20 = sum(c[i] * vol[i] for i in range(-20, 0)) / 20
        if val20 < B1_MIN_VAL or c[-1] < B1_MIN_PX:
            continue
        hi, hi_prev = max(h[-250:]), max(h[-251:-1])
        ratio, prev = c[-1] / hi, c[-2] / hi_prev
        if ratio >= B1_RATIO:
            rows.append({"s": sym, "n": v["name"], "g": v.get("g"), "ratio": round(ratio, 3), "new": prev < B1_RATIO,
                         "val20_eok": round(val20 / 1e8)})
    rows.sort(key=lambda x: (not x["new"], -x["ratio"]))
    return {"label": "B · 참고(주문 근거 아님)", "src": "reports/studies/2026-10-21_alpha_sources.md B1",
            "rule": "종가/250일 최고 고가 ≥ 0.95 · 20일 거래대금 ≥ 10억 · 종가 ≥ 1,000원 · 업종 분류 있는 종목(ETF 제외)",
            "grade_note": ("B1 은 2010~2025 tradeplan 진입(다음날 시가·struct 손절·H20) 기준 OOS 초과 +0.098R(t 2.78) — 학습 구간 절대 E[R] 음수(−0.032R). "
                           "이 목록은 신호 해당 종목일 뿐 계획·크기 없음 → 주문표 근거 불가."),
            "n": len(rows), "n_new": sum(r["new"] for r in rows), "rows": rows[:B1_TOP]}


ADOPT_GRADES = {"hi52": "A", "gcv": "B", "sqz": "B"}   # reports/studies/2026-10-24_trend_events.json (국장, OOS 2020~25)


def _kr_secs() -> dict | None:
    try:
        import csv
        with open(REPORT_DIR.parent / "universe" / "kr_sector.csv", encoding="utf-8") as fh:
            return {r["code"]: r["sector"] for r in csv.DictReader(fh)}
    except Exception:  # noqa: BLE001
        return None


def _liq_ok(ch: list[dict]) -> bool:
    """연구와 같은 유동성: 20일 평균 거래대금 ≥ 10억원 · 종가 ≥ 1,000원."""
    if len(ch) < 20:
        return False
    val20 = sum(b["c"] * (b.get("v") or 0) for b in ch[-20:]) / 20
    return val20 >= B1_MIN_VAL and ch[-1]["c"] >= B1_MIN_PX


def adopt_pending(fresh_rows: list[dict], stocks: dict | None = None) -> dict:
    """국장 새 추세 진입(hi52·gcv·sqz) '편입 대기' 목록 — 겸이 결재 10/24 (req-quant-d5d2f400). 오늘 켜진 것(진입 ≤ 4거래일)·
    HF S4 추격 패턴 제외(chase 로 이미 빠짐)·확신도 low 고정. 판정 상태는 reports/trend_adopt.json(scripts/trend_adopt_judge.py)."""
    try:
        st = json.loads((REPORT_DIR / "studies" / "2026-10-24_trend_events.json").read_text(encoding="utf-8"))
        grades = {k: st["grades"].get(f"{k}_KR", g) for k, g in ADOPT_GRADES.items()}
    except Exception:  # noqa: BLE001
        grades = dict(ADOPT_GRADES)
    judge = _j(REPORT_DIR / "trend_adopt.json", {}) or {}
    secs = _kr_secs()   # 업종 분류 있는 종목만(ETF 제외) — 연구 유니버스와 맞춤
    rows = [{"s": r["s"], "n": r.get("n"), "g": r.get("sector"), "strategy": r["strategy"], "label": EXPLORE_STRATS[r["strategy"]],
             "grade": grades.get(r["strategy"]), "age": r["age"], "entry_date": r.get("entry_date"), "conv": "low",
             "accum": r.get("accum")}
            for r in fresh_rows if r.get("strategy") in ADOPT_GRADES and not r.get("chase")
            and (secs is None or r["s"] in secs) and (stocks is None or _liq_ok(stocks.get(r["s"], {}).get("chart") or []))]
    rows.sort(key=lambda x: (x["age"], {"A": 0, "B": 1}.get(x["grade"], 9), x["strategy"]))
    return {"label": "새 추세 진입 — 편입 대기(전진 추적 중, 11/20 판정)", "tag": "주문 근거 아님",
            "basket": "분산 전제 — 연구에서 이벤트 중앙값은 음(−0.8~−1.6%), 평균(+1.5~2.0%p/20일)은 소수 종목이 만든다. 한 종목 집중 금지.",
            "grades": grades, "conv": "low", "exclude": "HF 4차 S4 추격 패턴(거래량 3배+20일 최고 종가) 제외 · ETF 제외 · 연구와 같은 유동성(20일 거래대금 ≥ 10억·종가 ≥ 1,000원)",
            "src": "reports/studies/2026-10-24_trend_events.md", "judge": judge.get("strategies"), "judge_date": judge.get("judge_date", "2026-11-20"),
            "n": len(rows), "rows": rows[:20]}


def _accum_syms(market: str) -> set[str]:
    if market == "US":
        d = _j(REPORT_DIR / "us_accum.json", {}) or {}
        return {h["symbol"] for h in d.get("hits") or [] if h.get("symbol")}
    d = _j(REPORT_DIR / "accum.json", {}) or {}
    return {str(r["code"]) for t, rs in (d.get("top") or {}).items() if t != "distrib" for r in rs or [] if r.get("code")}


def build(market: str, write: bool = True, detail_dir: Path | None = None, hist_dir: Path | None = None) -> dict:
    asof, stocks = load_detail(market, detail_dir)
    if not stocks or not asof:
        log.warning("trend_discovery_%s: detail 파일 없음 — 이전 판 유지(stale)", market)
        try:
            from .guard import record_stale
            record_stale(f"reports/trend_discovery_{market}.json", "추세 탐색 레이어(detail 파일 없음)", str(date.today()), None)
        except Exception:  # noqa: BLE001
            pass
        return {"market": market, "status": "fail", "error": "데이터 없음(detail 파일 없음)", "grade": GRADE, "not_for_orders": True}
    peers = _j(REPORT_DIR / f"peers_{market}.json", {}) or {}
    grp = {r["s"]: r.get("g") for r in peers.get("rows") or []}
    for s, v in stocks.items():
        v["g"] = grp.get(s) or v.get("sector")
    hist = load_hist(market, asof, hist_dir)
    off = _j(REPORT_DIR / f"sim_signals_{market}.json", {}) or {}
    ex = explore(stocks, hist, market, _accum_syms(market))
    fresh_any = ex.pop("_fresh_any")
    nm = near_miss(stocks)
    out = {
        "asof": asof, "market": market, "status": "ok", "schema_version": 1,
        "generated": str(date.today()), "grade": GRADE, "not_for_orders": True,
        "use": NOT_FOR_ORDERS.replace("{M}", market),
        "official": {"file": f"reports/sim_signals_{market}.json", "asof": off.get("asof"), "n_pass": off.get("n_pass"),
                     "n_eligible": off.get("n_eligible"), "expected_chance": off.get("expected_chance"),
                     "exp_n_pass": (off.get("exp") or {}).get("n_pass"), "exp_expected": (off.get("exp") or {}).get("expected_chance"),
                     "note": "정식 규칙·문턱은 바꾸지 않음(사전등록 docs/valuation_notes/2026-10-17_trend_expectancy_prereg.md)."},
        "diagnosis": diagnosis(stocks),
        "near_miss": nm,
        "explore": ex,
        "sectors": sectors(stocks, fresh_any),
        **({"b1_ref": b1_ref(stocks), "adopt_pending": adopt_pending((ex.get("fresh_new") or {}).get("rows") or [], stocks)} if market == "KR" else {}),
        "multiple_testing": {
            "m_total": sum(nm["m"].values()) + ex["m_wilson"] + ex["m_exp"],
            "expected_chance_total": round(sum(nm["expected_chance"].values()) + ex["expected_chance"], 2),
            "observed_total": nm["n"] + ex["n_pass"],
            "note": ("근접·탐색 목록은 같은 날 수백~천여 종목 × 5전략을 동시에 본 결과. 우연 기대와 관측이 비슷하면 '우연과 구분 안 됨'. "
                     "탐색 전략 3개(hi52·gcv·sqz)는 결과를 본 뒤 정한 것이 아니라 오늘 처음 정의했지만 사전등록 전이라 상한 C · 시도 일지 trial_log 기록."),
        },
        "study": "reports/studies/2026-10-24_trend_discovery.md",
    }
    if write:
        from .guard import write_json
        write_json(REPORT_DIR / f"trend_discovery_{market}.json", out, default=str)
    return out


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    for mk in (sys.argv[1:] or ["US", "KR"]):
        o = build(mk.upper())
        print(mk, json.dumps({k: o.get(k) for k in ("asof", "status")}, ensure_ascii=False),
              "근접", (o.get("near_miss") or {}).get("n"), "탐색통과", (o.get("explore") or {}).get("n_pass"),
              "후보", (o.get("explore") or {}).get("n_candidates"), "우연기대", (o.get("explore") or {}).get("expected_chance"))
