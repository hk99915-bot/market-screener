"""영업이익·순이익 괴리 · 영업외손익 부담 — 순수 계산 모듈 (연구 전용, 매매 지시 아님).

무엇: 본업(영업이익)과 최종(순이익)이 **서로 다른 방향**으로 움직인 분기를 분리해 본다.
      영업이익률은 유지·개선인데 순이익률만 떨어지면 그 차이는 영업외손익(금융손익·기타·지분법)에서 나온다.
      같은 '순이익 미스'라도 ① 일회성 영업외손실(역추세 후보)과 ② 상습적 영업외·평가손 부담(경고)은
      다음 분기 주가가 다르게 반응할 수 있다는 것이 가설이다. 이 모듈은 계산만 하고 판정은 연구 스크립트가 한다.
      기존 실계좌 룰은 건드리지 않는다(호출하는 쪽이 판단).

용어 (첫 등장 정의)
  매출액 대비 이익률 = 계정값 / 매출액.  분기 단독값(3개월) 기준, 단위는 비율(0.05 = 5%).
  영업외손익 = 법인세차감전순이익 − 영업이익.  금융손익·기타영업외손익·지분법손익의 합계다.
               (주요계정에는 이 합계만 있고, 전체재무제표에만 금융/기타 구분이 있다)
  괴리(divergence) = 영업이익률 변화와 순이익률 변화의 부호가 갈리고, 그 폭이 문턱을 넘는 상태.

주의
- 모든 입력은 **당해 분기 단독값**(1Q·반기·3Q 는 DART `amount`, 4Q 는 `연간 − 3분기누적`)이어야 한다.
  누적값을 그대로 넣으면 2·3분기가 자동으로 커져 괴리가 가짜로 생긴다.
- 시점(공시 여부)은 이 모듈이 모른다. `report_due()` 는 법정 제출기한만 돌려준다 — 실제 제출일이 아니다.
"""
from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np

# 법정 제출기한: 분기·반기 말일 +45일, 사업보고서(4분기)는 연말 +90일 (자본시장법 시행령 제161조 기준 기한).
DUE_DAYS = {1: 45, 2: 45, 3: 45, 4: 90}
QUARTER_END = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}


# ── 기간·시점 ────────────────────────────────────────────────────────
def quarter_end(year: int, q: int) -> date:
    """분기 말일. q=1..4."""
    m, d = QUARTER_END[int(q)]
    return date(int(year), m, d)


def report_due(year: int, q: int) -> date:
    """법정 제출기한(그 분기 보고서가 공개됐다고 '가정'할 수 있는 가장 이른 날).

    1분기 5/15 · 반기 8/14 · 3분기 11/14 · 사업보고서 다음해 3/31.
    실제 제출일은 이보다 빠를 수 있다(잠정실적은 더 빠르다) — 그 경우 우리 진입이 늦어져
    역추세 가설의 효과는 과소평가된다(보수적). 기한을 넘겨 내는 회사는 반영되지 않는다.
    """
    return quarter_end(year, q) + timedelta(days=DUE_DAYS[int(q)])


def prev_period(year: int, q: int, back: int = 4) -> tuple[int, int]:
    """n분기 전 (기본 4 = 전년동기)의 (연도, 분기)."""
    idx = int(year) * 4 + (int(q) - 1) - int(back)
    return idx // 4, idx % 4 + 1


# ── 분기 단독값 복원 ────────────────────────────────────────────────
def standalone_quarter(q: int, amount, add_amount, prev_cum, tol: float = 0.05) -> tuple[float | None, str]:
    """DART 주요계정 한 행 → 그 분기 단독값(3개월).

    amount = 당기(thstrm_amount), add_amount = 당기누적(thstrm_add_amount),
    prev_cum = 같은 회계연도 직전 분기까지의 누적(add_amount).
    - 1~3분기: amount 가 이미 단독값이다. 누적값이 있으면 (add_amount − prev_cum) 으로 검산하고,
      두 값이 tol(기본 5%) 넘게 어긋나면 누적 차분을 쓴다(일부 회사가 amount 에 누적을 넣는다).
    - 4분기(사업보고서): add_amount 가 없고 amount 가 연간 합계 → prev_cum(3분기 누적)을 빼야 단독값이 된다.
    반환: (값, 출처) — 출처는 'amount' | 'cum_diff' | 'annual_minus_cum3' | 'missing'.
    """
    q = int(q)
    a = _f(amount)
    add = _f(add_amount)
    prev = _f(prev_cum)
    if q in (1, 2, 3):
        check = add - prev if add is not None and prev is not None else None
        if a is None and check is None:
            return None, "missing"
        if a is None:
            return check, "cum_diff"
        if check is not None and abs(a - check) > tol * max(abs(a), abs(check), 1.0):
            return check, "cum_diff"
        return a, "amount"
    if q == 4:
        if a is None or prev is None:
            return None, "missing"
        return a - prev, "annual_minus_cum3"
    raise ValueError(f"q 는 1..4: {q}")


# ── 이익률·괴리 ────────────────────────────────────────────────────
def margin(value, revenue) -> float | None:
    """매출액 대비 이익률(비율). 매출액이 0 이하거나 결측이면 None(음수 매출은 의미 없음)."""
    v, r = _f(value), _f(revenue)
    if v is None or r is None or r <= 0:
        return None
    return v / r


def nonop(pretax, op) -> float | None:
    """영업외손익 = 법인세차감전순이익 − 영업이익. (음수 = 영업외 순손실)"""
    p, o = _f(pretax), _f(op)
    if p is None or o is None:
        return None
    return p - o


def snapshot(revenue, op, ni, pretax) -> dict:
    """한 분기의 이익률 3종. 키: m_op(영업이익률) · m_ni(순이익률) · m_nonop(영업외손익률) · nonop(원 단위)."""
    rev = _f(revenue)
    n = nonop(pretax, op)
    return {"m_op": margin(op, rev), "m_ni": margin(ni, rev),
            "m_nonop": margin(n, rev) if n is not None else None,
            "nonop": n, "op": _f(op), "ni": _f(ni), "rev": rev}


def change(now: dict, prev: dict) -> dict:
    """두 분기 스냅샷의 차이 — d_op·d_ni·d_nonop (이익률 변화, 비율 단위 %p÷100)."""
    def d(k):
        a, b = _f(now.get(k)), _f(prev.get(k))
        return None if a is None or b is None else a - b
    return {"d_op": d("m_op"), "d_ni": d("m_ni"), "d_nonop": d("m_nonop")}


# ── 두 가설의 판정 함수 ──────────────────────────────────────────────
def divergence(now: dict, prev: dict, *, d_op_min: float = 0.0, d_ni_max: float = -0.02) -> dict:
    """가설 1 — 본업 견조 + 순이익만 악화(영업외 일회성 미스 후보).

    조건: ① 이번 분기 영업이익률 > 0(본업 흑자) ② 영업이익률이 전년동기 대비 떨어지지 않음(d_op ≥ d_op_min)
          ③ 순이익률은 전년동기 대비 d_ni_max 이상 악화(기본 −2%p).
    ④ 가격 조건(최근 단기 하락)은 여기서 보지 않는다 — 연구 스크립트가 붙인다.
    반환: {is_event, d_op, d_ni, reason}
    """
    d = change(now, prev)
    m_op = _f(now.get("m_op"))
    if m_op is None or d["d_op"] is None or d["d_ni"] is None:
        return {"is_event": False, "d_op": d["d_op"], "d_ni": d["d_ni"], "reason": "이익률 결측"}
    ok = m_op > 0 and d["d_op"] >= d_op_min and d["d_ni"] <= d_ni_max
    why = (f"영업이익률 {m_op:+.3f}·변화 {d['d_op']:+.4f}, 순이익률 변화 {d['d_ni']:+.4f}"
           if ok else f"조건 미충족(영업이익률 {m_op:+.3f}·변화 {d['d_op']:+.4f}, 순이익률 변화 {d['d_ni']:+.4f})")
    return {"is_event": bool(ok), "d_op": d["d_op"], "d_ni": d["d_ni"], "reason": why}


def warning(now: dict, prev: dict, *, d_nonop_max: float = -0.03, share_min: float = 0.5) -> dict:
    """가설 2 — 영업외(금융·기타) 손실 부담 경고 플래그.

    조건: ① 영업이익률 > 0(비교할 본업 이익이 있음) ② 영업외손익률이 전년동기 대비 d_nonop_max 이하로 악화
          ③ 이번 분기 영업외 순손실 규모가 영업이익의 share_min 배 이상(|nonop| / op ≥ share_min).
    '일회성'이 아니라 '반복·구조적 부담'을 잡으려는 쪽이라 문턱을 영업이익 규모에 묶는다.
    반환: {warn, d_nonop, share, reason}
    """
    d = change(now, prev)
    op = _f(now.get("op"))
    n = _f(now.get("nonop"))
    if op is None or n is None or op <= 0 or d["d_nonop"] is None:
        return {"warn": False, "d_nonop": d["d_nonop"], "share": None, "reason": "결측 또는 영업이익 ≤ 0"}
    share = -n / op if n < 0 else 0.0
    ok = d["d_nonop"] <= d_nonop_max and share >= share_min
    return {"warn": bool(ok), "d_nonop": d["d_nonop"], "share": share,
            "reason": f"영업외손익률 변화 {d['d_nonop']:+.4f}, 영업외손실/영업이익 {share:.2f}"}


# ── 집계 (백테스트 공용) ────────────────────────────────────────────
def forward_return(closes, horizon: int = 20) -> np.ndarray:
    """t 종가 → t+horizon 종가 수익률(끝 horizon 칸 NaN)."""
    px = np.asarray(closes, dtype=float)
    out = np.full(px.size, np.nan)
    if px.size > horizon:
        out[:-horizon] = px[horizon:] / px[:-horizon] - 1.0
    return out


def window_return(closes, window: int = 20) -> np.ndarray:
    """최근 window 거래일 누적 수익률(과거 방향, 앞 window 칸 NaN). = P_t / P_{t−window} − 1."""
    px = np.asarray(closes, dtype=float)
    out = np.full(px.size, np.nan)
    if px.size > window:
        out[window:] = px[window:] / px[:-window] - 1.0
    return out


def p_one_sided(t: float, sign: int = 1) -> float:
    """단측 정규근사 p (repo 관행: screener/vrp_filter.p_one_sided 와 같은 식)."""
    return 0.5 * math.erfc(t * sign / math.sqrt(2))


def welch(a, b) -> dict:
    """두 표본 평균차 Welch t (a−b). 반환 {n_a,n_b,mean_a,mean_b,diff,t,p_one}."""
    a = np.asarray([x for x in np.asarray(a, dtype=float) if not math.isnan(x)])
    b = np.asarray([x for x in np.asarray(b, dtype=float) if not math.isnan(x)])
    na, nb = a.size, b.size
    if na < 3 or nb < 3:
        return {"n_a": int(na), "n_b": int(nb), "mean_a": float(a.mean()) if na else None,
                "mean_b": float(b.mean()) if nb else None, "diff": None, "t": None, "p_one": None}
    se = math.sqrt(a.var(ddof=1) / na + b.var(ddof=1) / nb)
    diff = float(a.mean() - b.mean())
    t = diff / se if se > 0 else 0.0
    return {"n_a": int(na), "n_b": int(nb), "mean_a": float(a.mean()), "mean_b": float(b.mean()),
            "diff": diff, "t": t, "p_one": p_one_sided(t, +1)}


def mean_t(a) -> dict:
    """한 표본 평균이 0과 다른지(단측 양수) — 초과수익이 시장 평균 대비 유의한지 볼 때."""
    a = np.asarray([x for x in np.asarray(a, dtype=float) if not math.isnan(x)])
    n = a.size
    if n < 3 or a.std(ddof=1) == 0:
        return {"n": int(n), "mean": float(a.mean()) if n else None, "t": None, "p_one": None}
    t = float(a.mean() / (a.std(ddof=1) / math.sqrt(n)))
    return {"n": int(n), "mean": float(a.mean()), "t": t, "p_one": p_one_sided(t, +1)}


def cluster_mean(values, keys) -> dict:
    """같은 날(같은 분기 공시일)에 몰린 사건을 독립 표본으로 세지 않기 위한 검정 —
    날짜별 평균을 먼저 만든 뒤 그 평균들로 t 를 낸다(사건 수 n 이 아니라 날짜 수가 표본)."""
    vals = np.asarray(values, dtype=float)
    ks = np.asarray(keys)
    ok = ~np.isnan(vals)
    vals, ks = vals[ok], ks[ok]
    if vals.size == 0:
        return {"dates": 0, "t": None, "p_one": None, "mean": None}
    order = {}
    for k, v in zip(ks, vals):
        order.setdefault(k, []).append(v)
    means = np.array([np.mean(v) for v in order.values()], dtype=float)
    r = mean_t(means)
    return {"dates": int(means.size), "t": r["t"], "p_one": r["p_one"], "mean": r["mean"]}


def group_stats(r) -> dict:
    """수익 배열 요약 — n·평균·중앙·승률·오탐률(음수 비율)·손익비(평균이익/평균손실)."""
    r = np.asarray([x for x in np.asarray(r, dtype=float) if not math.isnan(x)])
    if r.size == 0:
        return {"n": 0}
    win, loss = r[r > 0], r[r < 0]
    payoff = float(win.mean() / abs(loss.mean())) if win.size and loss.size and abs(loss.mean()) > 0 else None
    return {"n": int(r.size), "mean": float(r.mean()), "median": float(np.median(r)),
            "win": float((r > 0).mean()), "false_rate": float((r < 0).mean()), "payoff": payoff}


def _f(x) -> float | None:
    """숫자 변환 — None·NaN·빈 문자열은 None. numpy 스칼라도 float 로."""
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) else v
