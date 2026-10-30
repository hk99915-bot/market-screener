"""종목 상세 데이터 → reports/detail_{MARKET}.json
대상: 신호 섹션 종목 + 관심종목 + 최근 리포트 종목 (수백 개). 각 종목에
  chart(60일 OHLCV + SMA20/50/200), 지표, 리포트 이력, 수급(10일, KR), 손익비, 시나리오, 코멘트(거시/개별)
"""
from __future__ import annotations

import json
from .json_safe import dumps as strict_dumps
import logging
from datetime import date, timedelta

import polars as pl

from .commentary import market_comment, stock_comment
from .config import REPORT_DIR

log = logging.getLogger(__name__)



def _asof_label(market: str, asof: str) -> str:
    """'확정 종가' vs '장중 HH:MM' — 같은 날짜라도 장중 생성분은 마감가가 아님을 표시."""
    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo as _Z
    now = _dt.now(_Z("Asia/Seoul"))
    if market == "KR":
        if asof < str(now.date()) or now.hour * 100 + now.minute >= 1535:
            return "확정 종가"
        return f"장중 {now:%H:%M}"
    ny = _dt.now(_Z("America/New_York"))
    if asof < str(ny.date()) or ny.hour * 100 + ny.minute >= 1605 or ny.weekday() >= 5:
        return "확정 종가"
    return f"장중 {ny:%H:%M} ET"

def _targets(last: pl.DataFrame, max_n: int = 220) -> list[str]:
    parts = [
        last.filter(pl.col("class") == "TREND_LONG").sort("trend_score", descending=True).head(60),
        last.filter(pl.col("class") == "PULLBACK_IN_UPTREND").sort("trend_score", descending=True).head(40),
        last.filter(pl.col("class") == "COUNTERTREND_BOUNCE").sort("momentum_score", descending=True).head(30),
        last.filter(pl.col("reversal_risk") >= 60).sort("reversal_risk", descending=True).head(30),
        last.filter(pl.col("vol_ratio") >= 3).sort("vol_ratio", descending=True).head(30),
    ]
    if "rp_last_date" in last.columns:
        parts.append(last.filter(pl.col("rp_last_date").is_not_null()).sort("rp_last_date", descending=True).head(60))
    syms = []
    for p in parts:
        for s in p["symbol"].to_list():
            if s not in syms:
                syms.append(s)
    return syms[:max_n]


def _flows_kr(codes: list[str], asof: date, days: int = 10) -> dict[str, list[dict]]:
    """종목별 투자자 순매수(억원) 최근 N일 — pykrx, 종목당 1콜."""
    out = {}
    try:
        from pykrx import stock  # type: ignore
    except Exception:  # noqa: BLE001
        return out
    s, e = (asof - timedelta(days=days * 2)).strftime("%Y%m%d"), asof.strftime("%Y%m%d")
    for c in codes:
        try:
            df = stock.get_market_trading_value_by_date(s, e, c)
            if df is None or df.empty:
                continue
            cols = {k: [x for x in df.columns if k in str(x)] for k in ("외국인", "기관", "개인")}
            rows = []
            for idx, r in df.tail(days).iterrows():
                rows.append({"date": idx.strftime("%m/%d"),
                             **{k: round(float(r[v[0]]) / 1e8, 1) for k, v in cols.items() if v}})
            out[c] = rows
        except Exception as ex:  # noqa: BLE001
            log.debug("수급 %s 실패: %s", c, ex)
    return out


COST = 0.0025   # 왕복 거래비용 가정 (수수료+세금+슬리피지 대략)


def _sim_one(c: list[float], pos: list[int], dates: list, cost: float = COST) -> dict:
    """pos[i] = i일 종가 기준 결정한 포지션(+1 롱, -1 숏, 0 무포지션) → i+1일 수익에 적용."""
    eq, peak, mdd, trades, wins = 1.0, 1.0, 0.0, 0, 0
    entry_px, entry_i, cur = None, None, 0
    rets: list[float] = []                 # 청산된 거래별 순수익(왕복비용 차감) — 기대값 하한(_fresh_exp)용
    for i in range(1, len(c)):
        p = pos[i - 1]
        if p != cur:                       # 포지션 변경 (i-1일 종가에 체결)
            if cur != 0 and entry_px:
                ret = (c[i - 1] / entry_px - 1) * cur
                trades += 1
                wins += ret > 0
                rets.append(round(ret - cost, 4))
            if p != 0:
                entry_px, entry_i = c[i - 1], i - 1
            eq *= (1 - cost / 2) ** (abs(p - cur))
            cur = p
        eq *= 1 + cur * (c[i] / c[i - 1] - 1)
        peak = max(peak, eq)
        mdd = min(mdd, eq / peak - 1)
    if pos and pos[-1] != cur:             # 마지막 거래일 종가에 바뀐 신호 — 그 종가에 체결(10/17: '오늘 켜짐'이 하루 늦게 보이던 것 수정)
        p = pos[-1]
        if cur != 0 and entry_px:
            ret = (c[-1] / entry_px - 1) * cur
            trades += 1
            wins += ret > 0
            rets.append(round(ret - cost, 4))
        entry_px, entry_i = (c[-1], len(c) - 1) if p != 0 else (None, None)
        eq *= (1 - cost / 2) ** (abs(p - cur))
        cur = p
    open_ret = (c[-1] / entry_px - 1) * cur if cur and entry_px else None
    return {"ret": round(eq - 1, 4), "mdd": round(mdd, 4), "trades": trades,
            "win": round(wins / trades, 3) if trades else None, "wins": int(wins), "pos": cur,
            "entry_date": str(dates[entry_i]) if cur and entry_i is not None else None,
            "entry_px": round(entry_px, 2) if cur and entry_px else None,
            "open_ret": round(open_ret, 4) if open_ret is not None else None, "rets": rets}


def _simulate(g: pl.DataFrame, days: int = 250) -> dict:
    """추세추종 백테스트 (단일 종목, 최근 days 영업일, 종가 체결, 비용 왕복 0.25% 가정).
    1) 이평 추세: 종가>SMA50 & SMA20>SMA50 이면 롱, 반대면 숏(롱숏) / 무포지션(롱온리)
    2) PSAR: 종가>PSAR 롱, 아니면 숏/무포지션"""
    g = g.drop_nulls(["close", "sma20", "sma50"]).tail(days)
    if len(g) < 60:
        return {}
    c, s20, s50 = g["close"].to_list(), g["sma20"].to_list(), g["sma50"].to_list()
    ps = g["psar"].to_list() if "psar" in g.columns else [None] * len(c)
    dates = g["date"].to_list()
    ma = [1 if (c[i] > s50[i] and s20[i] > s50[i]) else -1 if (c[i] < s50[i] and s20[i] < s50[i]) else 0 for i in range(len(c))]
    sar = [0 if ps[i] is None else (1 if c[i] > ps[i] else -1) for i in range(len(c))]
    out = {"days": len(c), "from": str(dates[0]), "bh": round(c[-1] / c[0] - 1, 4), "cost": COST,
           "last2": [str(dates[-2]), str(dates[-1])]}
    for name, sig in (("ma", ma), ("psar", sar)):
        out[name] = {"long": _sim_one(c, [max(x, 0) for x in sig], dates),
                     "ls": _sim_one(c, sig, dates)}
    out["fresh"] = _fresh(out, dates)
    out["fresh_exp"] = _fresh_exp(out, dates)
    return out


# ── 새로 켜진 추세 신호 (오너 요청 10/17: "승률 높은 지표가 켜지면 운용회의에 반영·눈에 띄게") ──
# 사전 기준(결과 보기 전 고정, reports/studies/trial_log.json trend_sim 에 등록):
#   (a) long 전략이 현재 보유(pos==1)이고 진입일이 마지막 거래일 또는 직전 거래일 (= 새로 켜짐)
#   (b) 1년(250거래일) 안 청산된 거래 수 ≥ FRESH_MIN_TRADES
#   (c) 승률 Wilson 95% 하한 > FRESH_WILSON_MIN  (kb:verify#4 — 소표본 승률은 Wilson 구간)
# 등급 상한 C(참고): 종목당 거래 6~15회 표본 + 수백 종목 동시 검색(다중검정, kb:quant#3) → 일부는 우연 통과.
FRESH_MIN_TRADES = 6
FRESH_WILSON_MIN = 0.5
FRESH_Z = 1.96          # 95% 양측
FRESH_TOP = 30          # 시장별 집계 파일 상위 N
FRESH_STRATS = {"ma": "이평 추세 롱", "psar": "PSAR 롱"}


def wilson_lo(k: int, n: int, z: float = FRESH_Z) -> float | None:
    """승률 k/n 의 Wilson 점수 구간 하한. 식: (p̂ + z²/2n − z·√(p̂(1−p̂)/n + z²/4n²)) / (1 + z²/n). 예: 7/8 → 0.529."""
    if not n:
        return None
    p = k / n
    z2 = z * z
    return (p + z2 / (2 * n) - z * ((p * (1 - p) / n + z2 / (4 * n * n)) ** 0.5)) / (1 + z2 / n)


def _fresh(sim: dict, dates: list) -> list[dict]:
    """사전 기준 (a)~(c)를 통과한 long 전략 목록. dates = 시뮬레이션에 쓴 거래일(오름차순)."""
    if len(dates) < 2:
        return []
    recent = {str(dates[-1]), str(dates[-2])}
    out = []
    for k, label in FRESH_STRATS.items():
        r = (sim.get(k) or {}).get("long") or {}
        n = int(r.get("trades") or 0)
        if r.get("pos") != 1 or str(r.get("entry_date")) not in recent or n < FRESH_MIN_TRADES:
            continue
        w = int(r["wins"]) if r.get("wins") is not None else round((r.get("win") or 0) * n)
        lo = wilson_lo(w, n)
        if lo is None or lo <= FRESH_WILSON_MIN:
            continue
        out.append({"strategy": k, "label": label, "win": round(w / n, 3), "wins": w, "trades": n,
                    "wilson_lo": round(lo, 3), "ret": r.get("ret"), "bh": sim.get("bh"), "entry_date": r.get("entry_date")})
    return out


# ── 기대값 하한 규칙 (오너 승인 10/17 14:09, 사전등록 docs/valuation_notes/2026-10-17_trend_expectancy_prereg.md) ──
# Wilson 승률>50% 는 6회면 6승 0패가 필요해 추세추종(승률 30~45%·손익비 큼)에선 사실상 통과 0. 기대값(거래당 평균 순수익)의
# t 단측 95% 하한 > 0 을 병기한다. 등급 상한 C(참고) · 주문표 근거 불가 · 운용회의 'C·참고' 라벨로만.
EXP_MIN_TRADES = 8
EXP_LB_MIN = 0.0
# 스튜던트 t 단측 95% 분위수 (자유도 → 값). 표에 없는 자유도는 더 작은 자유도 값을 쓴다(보수적).
T95 = {1: 6.314, 2: 2.920, 3: 2.353, 4: 2.132, 5: 2.015, 6: 1.943, 7: 1.895, 8: 1.860, 9: 1.833, 10: 1.812,
       11: 1.796, 12: 1.782, 13: 1.771, 14: 1.761, 15: 1.753, 16: 1.746, 17: 1.740, 18: 1.734, 19: 1.729, 20: 1.725,
       21: 1.721, 22: 1.717, 23: 1.714, 24: 1.711, 25: 1.708, 26: 1.706, 27: 1.703, 28: 1.701, 29: 1.699, 30: 1.697,
       40: 1.684, 60: 1.671, 120: 1.658}


def t95(df: int) -> float:
    if df <= 0:
        return float("inf")
    return T95.get(df) or T95[max(k for k in T95 if k <= df)]


def exp_lb(rets: list[float]) -> tuple[float, float, float] | None:
    """(평균, 표준편차, t 하한). 식: LB = r̄ − t₀.₉₅,ₙ₋₁·s/√n. 예: [0.1, −0.02]×4 (n 8) → r̄ 0.04, s 0.0641, LB 0.04 − 1.895·0.0227 = −0.003."""
    n = len(rets)
    if n < 2:
        return None
    m = sum(rets) / n
    sd = (sum((x - m) ** 2 for x in rets) / (n - 1)) ** 0.5
    return m, sd, m - t95(n - 1) * sd / n ** 0.5


def boot_lb(rets: list[float], b: int = 2000, seed: int = 20261017) -> float | None:
    """평균의 백분위 부트스트랩 단측 95% 하한 (보조, 표시 안 함)."""
    import random
    n = len(rets)
    if n < 2:
        return None
    rng = random.Random(seed)
    ms = sorted(sum(rng.choice(rets) for _ in range(n)) / n for _ in range(b))
    return ms[int(0.05 * b)]


def _fresh_exp(sim: dict, dates: list) -> list[dict]:
    """(a) 새로 켜짐 + (b) 청산 거래 ≥ EXP_MIN_TRADES + (c) 기대값 t 하한 > EXP_LB_MIN 인 long 전략."""
    if len(dates) < 2:
        return []
    recent = {str(dates[-1]), str(dates[-2])}
    out = []
    for k, label in FRESH_STRATS.items():
        r = (sim.get(k) or {}).get("long") or {}
        rets = r.get("rets") or []
        if r.get("pos") != 1 or str(r.get("entry_date")) not in recent or len(rets) < EXP_MIN_TRADES:
            continue
        m, sd, lb = exp_lb(rets)
        if lb <= EXP_LB_MIN:
            continue
        out.append({"strategy": k, "label": label, "trades": len(rets), "exp": round(m, 4), "exp_lb": round(lb, 4),
                    "sd": round(sd, 4), "win": round(sum(x > 0 for x in rets) / len(rets), 3), "ret": r.get("ret"),
                    "bh": sim.get("bh"), "entry_date": r.get("entry_date"), "grade": "C·참고"})
    return out


def exp_block(scanned: dict) -> dict:
    """sim_signals 의 exp 블록 — 통과 목록 + m(검정 수) + 기대 우연 통과 0.05·m + 이항 p."""
    from math import comb
    rows, m = [], 0
    for s, v in scanned.items():
        sim = v["sim"]
        last2 = set(sim.get("last2") or [])
        for k in FRESH_STRATS:
            r = (sim.get(k) or {}).get("long") or {}
            if r.get("pos") == 1 and str(r.get("entry_date")) in last2 and len(r.get("rets") or []) >= EXP_MIN_TRADES:
                m += 1
        for f in sim.get("fresh_exp") or []:
            rows.append({"s": s, "n": v.get("name"), **f})
    rows.sort(key=lambda x: (-x["exp_lb"], -x["trades"]))
    k = len(rows)
    p = sum(comb(m, i) * 0.05 ** i * 0.95 ** (m - i) for i in range(k, m + 1)) if m else None
    return {"n_eligible": m, "n_pass": k, "expected_chance": round(0.05 * m, 2), "binom_p": None if p is None else round(p, 4),
            "criteria": {"min_trades": EXP_MIN_TRADES, "lb": "t 단측 95% 하한 > 0", "cost": COST,
                         "prereg": "docs/valuation_notes/2026-10-17_trend_expectancy_prereg.md"},
            "grade": ("C·참고 — 주문표 근거 불가. 기대값 = 거래당 평균 순수익(왕복 0.25% 차감), 하한 = r̄ − t₀.₉₅·s/√n. "
                      f"검정 {m}개 중 우연 통과 기대 {0.05 * m:.1f}건" + (f", 이항 p {p:.2f}" if p is not None else "")
                      + (" — 우연과 구분 안 됨" if p is None or p >= 0.05 else "") + ". 같은 장세 거래라 독립 가정이 낙관적."),
            "formula": "exp_lb = mean(r) − t95(n−1)·sd(r)/√n, r = 청산가/진입가 − 1 − 0.0025",
            "rows": rows[:FRESH_TOP]}


def _pass_prob_null(n: int, p0: float = 0.5) -> float:
    """귀무(매 거래 승률 p0, 독립)에서 거래 n회의 Wilson 하한이 FRESH_WILSON_MIN 을 넘을 확률 = Σ_{k: lo(k,n)>기준} C(n,k)·p0^k·(1−p0)^(n−k)."""
    from math import comb
    return sum(comb(n, k) * p0 ** k * (1 - p0) ** (n - k) for k in range(n + 1)
               if (wilson_lo(k, n) or 0) > FRESH_WILSON_MIN)


def sim_signals(market: str, asof: str, stocks: dict) -> dict:
    """시장별 집계 → reports/sim_signals_{market}.json 내용. stocks = {sym: {"name", "sim"}}."""
    scanned = {s: v for s, v in stocks.items() if (v.get("sim") or {}).get("days")}
    m = len(scanned)
    rows, eligible, exp = [], 0, 0.0
    for s, v in scanned.items():
        sim = v["sim"]
        last2 = set(sim.get("last2") or [])
        for k in FRESH_STRATS:   # 기대 우연 통과: (a)·(b)만 충족한 전략마다 귀무 통과 확률을 더함
            r = (sim.get(k) or {}).get("long") or {}
            n = int(r.get("trades") or 0)
            if r.get("pos") == 1 and str(r.get("entry_date")) in last2 and n >= FRESH_MIN_TRADES:
                eligible += 1
                exp += _pass_prob_null(n)
        for f in sim.get("fresh") or []:
            rows.append({"s": s, "n": v.get("name"), **f})
    rows.sort(key=lambda x: (-x["wilson_lo"], -x["trades"]))
    return {
        "asof": asof, "market": market, "n_scanned": m, "n_pass": len(rows), "n_eligible": eligible,
        "expected_chance": round(exp, 2),
        "criteria": {"min_trades": FRESH_MIN_TRADES, "wilson_min": FRESH_WILSON_MIN, "z": FRESH_Z,
                     "fresh": "long 전략 pos==1 이고 진입일 = 마지막 또는 직전 거래일", "window": "250거래일 · 종가 체결 · 왕복비용 0.25%"},
        "grade": (f"참고(C) — 종목당 1년·거래 6~15회 표본, {m}종목 동시 검색이라 일부는 우연. "
                  f"기대 우연 통과 ≈ {exp:.1f}건 (식: Σ_(켜짐·거래≥{FRESH_MIN_TRADES}인 전략 {eligible}개) P[Wilson 하한>{FRESH_WILSON_MIN} | 승률 0.5, 거래 n] — 이항 분포 합). "
                  f"통과 {len(rows)}건이 이 숫자와 비슷하면 우연과 구분되지 않는다. 종목 간 같은 장세(상관)라 통과가 몰려 나올 수 있음."),
        "formula": "wilson_lo = (p̂ + z²/2n − z·√(p̂(1−p̂)/n + z²/4n²)) / (1 + z²/n), z=1.96",
        "rows": rows[:FRESH_TOP],
        "exp": exp_block(scanned),
    }



def _scenarios(r: dict, chart: list[dict]) -> dict:
    """규칙 기반 시나리오: 지지/저항 레벨과 조건. 예측이 아니라 '어느 레벨에서 무엇이 바뀌는가'."""
    c = r.get("close") or 0
    atr = r.get("atr14") or 0
    hi20 = max((x["h"] for x in chart[-20:]), default=c)
    lo20 = min((x["l"] for x in chart[-20:]), default=c)
    tp = r.get("consensus_tp")
    s20, s50, s200, h52, l52 = r.get("sma20"), r.get("sma50"), r.get("sma200"), r.get("high52"), r.get("low52")
    up_target = tp if tp and tp > c else (h52 if h52 and h52 > c else c + 3 * atr)
    dn_next = max([x for x in (s50, s200, l52) if x and x < lo20], default=c - 3 * atr)
    f = lambda v: None if v is None else round(v, 2)  # noqa: E731
    bull = {"trigger": f"20일 고점 {hi20:,.0f} 돌파 + 거래량 1.5배 이상", "target": f(up_target),
            "upside": f((up_target / c - 1) * 100) if c else None,
            "note": "컨센서스 목표가" if tp and tp > c else ("52주 고점" if h52 and h52 > c else "현재가+3ATR")}
    base = {"range": [f(lo20), f(hi20)], "note": f"20일 박스 {lo20:,.0f}~{hi20:,.0f}, 20일선 {s20:,.0f}" if s20 else ""}
    bear = {"trigger": f"20일 저점 {lo20:,.0f} 이탈(종가 기준)", "stop": f(lo20),
            "loss": f((lo20 / c - 1) * 100) if c else None, "next": f(dn_next),
            "note": "다음 지지: " + ("50일선" if dn_next == s50 else "200일선" if dn_next == s200 else "52주 저점" if dn_next == l52 else "현재가-3ATR")}
    rr = None
    if c > lo20 and up_target > c:
        rr = round((up_target - c) / (c - lo20), 1)
    # 급등주는 20일 저점이 너무 멀다 → PSAR(추적 손절) 기준 손익비도 함께
    psar = r.get("psar")
    rr_trail = None
    if psar and c > psar and up_target > c:
        rr_trail = round((up_target - c) / (c - psar), 1)
        bear["trail"] = f(psar)
        bear["trail_loss"] = f((psar / c - 1) * 100)
    return {"bull": bull, "base": base, "bear": bear, "rr": rr, "rr_trail": rr_trail,
            "rr_note": "손익비 = (상승목표-현재가)/(현재가-20일저점). 1.5 미만이면 진입 매력 낮음, 3 이상이어도 확률은 별개"}


def _macro_view(r: dict, mr: list[dict], regime_line: str, br: dict) -> str:
    bits = [market_comment(br)] if br else []
    if regime_line:
        bits.append(regime_line)
    m = {d["key"]: d for d in (mr or [])}
    if r.get("market") in ("KOSPI", "KOSDAQ"):
        if "USDKRW" in m and m["USDKRW"]["chg20"] > 0.02:
            bits.append("원화 약세 지속 — 외국인 수급에 부담")
        elif "USDKRW" in m and m["USDKRW"]["chg20"] < -0.02:
            bits.append("원화 강세 — 외국인 유입 우호")
    if "US10Y" in m and m["US10Y"]["chg20"] > 0.05:
        bits.append("금리 상승 구간 — 고밸류 성장주 할인율 부담")
    if "VIX" in m and m["VIX"]["last"] >= 22:
        bits.append("변동성 높음 — 포지션 크기 축소 구간")
    return " · ".join(b for b in bits if b)


def _flows_bulk(asof_dates: list[date], days: int = 10) -> dict[str, list[dict]]:
    """전 종목 투자자별 순매수(억원) — 날짜×투자자×시장 단위 일괄 조회(약 60콜)로 모든 종목을 한 번에."""
    out: dict[str, dict[str, dict]] = {}
    try:
        from pykrx import stock  # type: ignore
    except Exception:  # noqa: BLE001
        return {}
    inv = {"외국인": "외국인", "기관": "기관합계", "개인": "개인"}
    for d in asof_dates[-days:]:
        ymd = d.strftime("%Y%m%d")
        for mkt in ("KOSPI", "KOSDAQ"):
            for k, name in inv.items():
                try:
                    df = stock.get_market_net_purchases_of_equities(ymd, ymd, mkt, name)
                except Exception as e:  # noqa: BLE001
                    log.debug("일괄 수급 %s %s %s 실패: %s", ymd, mkt, k, e)
                    continue
                if df is None or df.empty:
                    continue
                col = [c for c in df.columns if "순매수거래대금" in str(c)]
                if not col:
                    continue
                for code, v in zip(df.index.astype(str), df[col[0]]):
                    out.setdefault(code.zfill(6), {}).setdefault(d.strftime("%m/%d"), {})[k] = round(float(v) / 1e8, 1)
    return {c: [{"date": dd, **vals} for dd, vals in sorted(m.items(), key=lambda x: x[0])] for c, m in out.items()}


def build(market: str, last: pl.DataFrame, full: pl.DataFrame, store: pl.DataFrame | None,
          mr: list[dict], regime_line: str, br: dict, with_flows: bool = True) -> None:
    syms = [s for s in last["symbol"].to_list() if s]   # 전 종목
    asof = last["date"].max()
    from .guard import allow
    if not allow(REPORT_DIR / "detail" / market / "_index.json", str(asof)):   # asof 역행이면 상세·피어 전부 건너뜀 (10/17 detail_us)
        return
    rows = {r["symbol"]: r for r in last.filter(pl.col("symbol").is_in(syms)).to_dicts()}
    hist = (full.filter(pl.col("yf").is_in(last.filter(pl.col("symbol").is_in(syms))["yf"].implode()))
                .sort("yf", "date").group_by("yf").tail(260))   # 1년 (웹 차트에서 확대·이동)
    sims: dict[str, dict] = {}
    try:
        cols = [x for x in ("yf", "date", "close", "sma20", "sma50", "psar") if x in full.columns]
        for (yf,), g in full.select(cols).sort("yf", "date").group_by("yf", maintain_order=True):
            sims[yf] = _simulate(g)
    except Exception as e:  # noqa: BLE001
        log.warning("시뮬레이션 실패: %s", e)
    c1y: dict[str, list] = {}   # MY 탭 위험 계산용 1년 종가
    try:
        for (yf_,), g in (full.filter(pl.col("yf").is_in(last["yf"].implode())).select("yf", "date", "close")
                          .sort("yf", "date").group_by("yf", maintain_order=True)):
            g = g.tail(260)
            c1y[yf_] = [[str(d), round(float(c), 4)] for d, c in zip(g["date"].to_list(), g["close"].to_list()) if c is not None]
    except Exception as e:  # noqa: BLE001
        log.warning("1년 종가 실패: %s", e)
    charts: dict[str, list[dict]] = {}
    for (yf,), g in hist.group_by("yf", maintain_order=True):
        rd = lambda v: None if v is None else round(v, 2)  # noqa: E731
        charts[yf] = [{"d": str(x["date"])[5:], "t": str(x["date"])[:10], "o": rd(x["open"]), "h": rd(x["high"]), "l": rd(x["low"]), "c": rd(x["close"]),
                       "v": int(x["volume"] or 0), "s20": rd(x.get("sma20")), "s50": rd(x.get("sma50")), "s200": rd(x.get("sma200")), "p": rd(x.get("psar"))} for x in g.to_dicts()]
    reps: dict[str, list[dict]] = {}
    if store is not None and len(store):
        rr = (store.filter(pl.col("code").is_in(syms) & (pl.col("date") >= asof - timedelta(days=180)))
                   .sort("date", descending=True))
        for (code,), g in rr.group_by("code", maintain_order=True):
            reps[code] = [{"date": str(x["date"]), "broker": x["broker"], "opinion": x["opinion"], "target": x["target"],
                           "title": x["title"], "link": x["link"], "summary": x.get("summary") or "",
                           "analyst": x.get("analyst")}
                          for x in g.head(12).to_dicts()]
    flows: dict[str, list[dict]] = {}
    if with_flows and market == "KR":
        days = sorted(set(full["date"].to_list()))[-10:]
        flows = _flows_bulk(days)
        log.info("일괄 수급 %d종목", len(flows))
        if not flows:   # 일괄 조회가 막히면 상위 150종목만 종목별로
            flows = _flows_kr(_targets(last)[:150], asof)
    drv: dict[str, dict] = {}
    fins: dict[str, dict] = {}
    if market == "US":
        try:
            from . import drivers
            drv = drivers.build_us([s0 for s0 in syms if s0 in rows], full.select("yf", "date", "close"))
        except Exception as e:  # noqa: BLE001
            log.warning("미장 이익 드라이버 실패: %s", e)
    if market == "US":
        try:
            from . import sec
            for s0 in syms:
                v = sec.summary(s0)
                if v:
                    fins[s0] = v
            log.info("미장 재무 요약 %d종목", len(fins))
        except Exception as e:  # noqa: BLE001
            log.warning("미장 재무 요약 실패: %s", e)
    if market == "KR":
        try:
            from . import fin
            for s0 in syms:
                v = fin.summary(s0)
                if v:
                    fins[s0] = v
            log.info("재무 요약 %d종목", len(fins))
        except Exception as e:  # noqa: BLE001
            log.warning("재무 요약 실패: %s", e)
    vals: dict[str, dict] = {}
    try:   # KR: DART 6모델(원) / US: SEC 분기 6모델(USD, 가정 분리 — valuation.us_all)
        from . import valuation
        px = {s0: rows[s0]["close"] for s0 in syms if s0 in rows and rows[s0].get("close")}
        vals = valuation.kr_all(px) if market == "KR" else valuation.us_all(px)
    except Exception as e:  # noqa: BLE001
        log.warning("가치평가 실패(%s): %s", market, e)
    discl = {}
    if market == "KR":
        try:
            from . import dart
            discl = dart.by_code(dart.load(), list(syms), days=180, n=12)
        except Exception as e:  # noqa: BLE001
            log.warning("종목별 공시 실패: %s", e)

    try:   # 종목 한 줄 설명 증분(데이터 10/24) — ETF·유형·KIND 줄 + 새 종목 야후 근거 60개. 실패해도 상세 생성 계속
        import os
        if not os.environ.get("PYTEST_CURRENT_TEST"):   # 테스트에서 네트워크 금지
            from . import oneliner
            log.info("한 줄 설명: %s", oneliner.update(market, budget=60))
    except Exception as e:  # noqa: BLE001
        log.warning("한 줄 설명 갱신 실패: %s", e)

    if market == "KR":
        try:
            from . import drivers, universe
            from .config import UNIVERSE_DIR
            u = pl.read_csv(UNIVERSE_DIR / "kr.csv", schema_overrides={"symbol": pl.Utf8})
            mc = dict(zip(u["symbol"].to_list(), u["mcap"].to_list()))
            try:   # 공식 섹터 WICS 일 1회 (보드 toss-sectors) — 실패해도 상세 생성은 계속, stale 기록
                from . import sectors, wics
                log.info("WICS: %s", wics.update_if_stale())
                sectors.clear_cache()
            except Exception as e:  # noqa: BLE001
                log.warning("WICS 갱신 실패: %s", e)
            secs = universe.kr_sectors() or {}
            info = {s0: {"name": rows[s0]["name"], "sector": secs.get(s0), "mcap": mc.get(s0)} for s0 in syms if s0 in rows}
            drv = drivers.build(info, full.select("yf", "date", "close"), discl)
            for s0, d0 in drv.items():   # 가치평가에 신호 가중 적정가 연결
                v0 = vals.get(s0)
                if not v0 or d0.get("w_current") is None:
                    continue
                g = v0.get("groups") or {}
                if g.get("current") and g.get("normal"):
                    w = d0["w_current"]
                    fv = w * g["current"] + (1 - w) * g["normal"]
                    v0["signal_fv"] = {"value": round(fv, 0), "w_current": w,
                                       "upside": round(fv / rows[s0]["close"] - 1, 3) if rows[s0].get("close") else None}
            log.info("이익 드라이버 %d종목", len(drv))
        except Exception as e:  # noqa: BLE001
            log.warning("이익 드라이버 실패: %s", e)
    shorts_m: dict[str, dict] = {}
    if market == "KR":
        try:
            from . import shorts
            shorts.update()
            shorts_m = shorts.by_code()
            log.info("공매도 %d종목", len(shorts_m))
        except Exception as e:  # noqa: BLE001
            log.warning("공매도 실패: %s", e)
    themes: dict[str, dict] = {}
    if market == "KR":
        try:
            from .themes import kr_themes
            themes = kr_themes()
        except Exception as e:  # noqa: BLE001
            log.warning("테마 실패: %s", e)
    out = {"asof": str(asof), "market": market, "stocks": {}}
    for s in syms:
        r = rows.get(s)
        if not r:
            continue
        ch = charts.get(r["yf"], [])
        fl = flows.get(s, [])
        flow_note = ""
        if fl:
            f5 = sum(x.get("외국인", 0) for x in fl[-5:]); i5 = sum(x.get("기관", 0) for x in fl[-5:])
            flow_note = f"5일 외국인 {f5:+,.0f}억 · 기관 {i5:+,.0f}억 — " + (
                "쌍끌이 매수" if f5 > 0 and i5 > 0 else "동반 매도" if f5 < 0 and i5 < 0 else "엇갈림")
        out["stocks"][s] = {
            "name": r["name"], "market": r["market"], "close": r["close"],
            "theme": (themes.get(s) or {}).get("theme"), "themes": (themes.get(s) or {}).get("themes", ""),
            "stats": {k: (round(r[k], 4) if isinstance(r.get(k), float) else r.get(k)) for k in ("ret1", "ret5", "ret20", "ret60", "trend_score", "momentum_score", "reversal_risk",
                                             "class", "adx14", "rsi14", "cci20", "stoch_k", "macd", "macd_sig", "atr14",
                                             "sma20", "sma50", "sma200", "high52", "low52", "from_high52", "vol_ratio",
                                             "dollar_vol20", "dist_sma20_atr", "psar")},
            "research": {"items": reps.get(s, []), "consensus_tp": r.get("consensus_tp"), "tp_upside": r.get("tp_upside"),
                         "brokers30": r.get("rp_brokers30"), "n30": r.get("rp_n30")},
            "flows": fl, "flow_note": flow_note,
            "disclosures": discl.get(s, []),
            "financials": fins.get(s, {}),
            "valuation": vals.get(s, {}),
            "drivers": drv.get(s, {}),
            "short": shorts_m.get(s) if market == "KR" else None,
            "sim": sims.get(r["yf"], {}),
            "chart": ch,
            "c1y": c1y.get(r["yf"], []),
            "scenarios": _scenarios(r, ch),
            "comment": {"stock": stock_comment(r, max_parts=5), "macro": _macro_view(r, mr, regime_line, br)},
        }
    if market == "KR":
        try:
            from . import track
            track.backfill_tech(full)
            track.snapshot(asof, out["stocks"])
            track.score(full.select("yf", "date", "close"))
        except Exception as e:  # noqa: BLE001
            log.warning("시그널 추적 실패: %s", e)
    # 동종 비교(RV)·히트맵용 요약 — 종목별 핵심 숫자만 한 파일에
    try:
        mc = {}
        try:
            from .config import UNIVERSE_DIR
            uf = UNIVERSE_DIR / ("kr.csv" if market == "KR" else "us.csv")
            if uf.exists():
                u0 = pl.read_csv(uf, schema_overrides={"symbol": pl.Utf8})
                if "mcap" in u0.columns:
                    mc = dict(zip(u0["symbol"].to_list(), u0["mcap"].to_list()))
        except Exception:  # noqa: BLE001
            pass
        ussec = {}
        if market == "US":
            try:
                from .universe import us_sectors
                ussec = us_sectors()
            except Exception:  # noqa: BLE001
                ussec = {}
        semi = {"NVDA", "AMD", "AVGO", "TSM", "AMAT", "LRCX", "KLAC", "ASML", "INTC", "QCOM", "TXN", "ADI", "MRVL", "ARM", "MU", "SNDK",
                "MCHP", "NXPI", "ON", "MPWR", "TER", "WDC", "STX"}
        kr_w: dict[str, dict] = {}
        if market == "KR":
            try:
                from .sectors import _kr as _kr_wics
                kr_w = _kr_wics()[0] if _kr_wics()[1] == "WICS" else {}
            except Exception:  # noqa: BLE001
                kr_w = {}
        from .themes import gated_theme
        peers = []
        for s0, v0 in out["stocks"].items():
            va, dv, st0 = v0.get("valuation") or {}, v0.get("drivers") or {}, v0.get("stats") or {}
            th0 = v0.get("theme")
            if market == "KR" and th0:   # 테마가 WICS 와 양립 안 하면 WICS 중분류 버킷 (req-data-630b1bfe)
                w0 = kr_w.get(s0) or {}
                th0 = gated_theme(th0, w0.get("l1"), w0.get("l2"))
            grp = (("반도체" if s0 in semi else ussec.get(s0)) if market == "US" else None) or th0 or va.get("sector") or ((dv.get("chain") or {}).get("name")) or "기타"
            peers.append({"s": s0, "n": v0.get("name"), "g": grp, "sec": va.get("sector"),
                          "mc": mc.get(s0) or st0.get("dollar_vol20"), "r1": st0.get("ret1"), "r5": st0.get("ret5"), "r20": st0.get("ret20"),
                          "per": va.get("per"), "pbr": va.get("pbr"), "roe": va.get("roe"), "roen": va.get("roe_norm"),
                          "drv": dv.get("score"), "sig": (va.get("signal_fv") or {}).get("upside"),
                          "nor": (va.get("group_upside") or {}).get("normal"), "fs": (va.get("fscore") or {}).get("score"),
                          "cls": st0.get("class"), "sr": (v0.get("short") or {}).get("ratio"), "sr20": (v0.get("short") or {}).get("chg20")})
        from .guard import write_json
        write_json(REPORT_DIR / f"peers_{market}.json", {"asof": out["asof"], "rows": peers}, default=lambda x: None)
        if market == "US":   # 종목별 drv·r20·r1 거래일 누적(req-dev-808893e4) — 실패해도 peers 파일엔 영향 없음
            try:
                from . import peers_hist
                peers_hist.append(market, out["asof"], peers)
            except Exception as e:  # noqa: BLE001
                log.warning("peers 누적 실패: %s", e)
    except Exception as e:  # noqa: BLE001
        log.warning("동종 비교 파일 실패: %s", e)
    import shutil
    d = REPORT_DIR / "detail" / market
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True, exist_ok=True)
    size = 0
    for s, v in out["stocks"].items():
        fp = d / f"{s}.json"
        fp.write_text(strict_dumps({**v, "symbol": s, "asof": out["asof"], "asof_label": _asof_label(market, out["asof"])}, ensure_ascii=False, default=str), encoding="utf-8")
        size += fp.stat().st_size
    from .guard import write_json
    write_json(d / "_index.json", {"asof": out["asof"], "symbols": sorted(out["stocks"]),
                                   "names": {k: v.get("name") for k, v in out["stocks"].items()}})   # 계약 검사 (역행은 함수 첫머리에서 판정)
    old = REPORT_DIR / f"detail_{market}.json"
    old.unlink(missing_ok=True)   # 예전 묶음 파일 제거
    log.info("detail/%s: %d종목, %d KB", market, len(out["stocks"]), size // 1024)
    try:   # 새로 켜진 추세 신호 시장별 집계 (운용회의 sim_fresh 블록이 읽음)
        ss = sim_signals(market, out["asof"], out["stocks"])
        from .guard import write_json
        write_json(REPORT_DIR / f"sim_signals_{market}.json", ss, default=str)
        log.info("sim_signals_%s: 스캔 %d · 통과 %d · 기대 우연 %.1f", market, ss["n_scanned"], ss["n_pass"], ss["expected_chance"])
    except Exception as e:  # noqa: BLE001
        log.warning("추세 신호 집계 실패: %s", e)
    try:   # 탐색 레이어(근접·새 전략군·업종) — 정식 규칙 불변, 등급 탐색·상한 C, 주문표 근거 불가 (퀀트 10/24)
        from . import trend_discovery
        td = trend_discovery.build(market)
        log.info("trend_discovery_%s: 근접 %s · 탐색 통과 %s (우연 기대 %s)", market, (td.get("near_miss") or {}).get("n"),
                 (td.get("explore") or {}).get("n_pass"), (td.get("explore") or {}).get("expected_chance"))
    except Exception as e:  # noqa: BLE001
        log.warning("추세 탐색 레이어 실패: %s", e)
    try:
        from . import etf
        etf.build(market)
    except Exception as e:  # noqa: BLE001
        log.warning("ETF 상세 실패: %s", e)
