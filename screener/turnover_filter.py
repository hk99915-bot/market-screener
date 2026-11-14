"""거래대금 과열 페널티 — '조용한 강세주' vs '거래대금 폭발 급등주' 판별 (순수 계산 모듈, 연구 전용).

무엇: 단기 강세(예: 5일 +10% 이상) 종목 안에서 **그 상승이 거래대금 폭발과 함께 왔는지**로 갈라
      이후 5·10일 초과수익을 비교한다. 실계좌 룰은 건드리지 않는다 — 이 모듈은 계산기다.

정의 (모두 t일 종가 시점 정보만 사용 · 전방 정보 없음)
  tv(t)     = 조정 종가 × 조정 거래량          ← 거래대금 근사(KRW·USD). 데이터에 대금 열이 없어 이 근사를 쓴다
  tv5(t)    = tv 의 최근 5거래일 평균 (t−4~t)
  base20(t) = tv 의 직전 20거래일 평균 (t−24~t−5)   ← 오늘·최근 5일을 뺀 기준선(과열 배수의 분모)
  ratio(t)  = tv5 / base20                     ← '과열 배수'. 2.0 이면 최근 5일 대금이 직전 20일의 2배
  r5(t)     = 종가(t) / 종가(t−5) − 1
  강세      = r5 ≥ +10%
  과열(hot) = ratio ≥ 2.0 · 조용(quiet) = ratio ≤ 1.2 · 그 사이(mid)는 대조에서 뺀다
  성과      = t+1 시가 매수 → t+H 종가 매도(H = 5 또는 10) − 같은 날 유동성 유니버스 평균(초과수익)

기업행위(분할·병합·무상증자) 처리
  KRX 가격제한폭 ±30% 이므로 **시가와 종가가 모두** 같은 방향으로 ±31% 밖이면 기준가가 다시 정해진 날로 본다
  (`screener.prices.detect_events` 와 같은 규칙). 그 날의 시가 비율을 배수로 삼아 이전 구간을 조정한다.
  정리매매(가격제한 없음)로 보이는 하락은 조정하지 않고 '데이터 오류일'로 남겨 창에서 제외한다.

주의
- 데이터(`data/hist/*_YYYY.parquet`)에 조정 종가가 없어 기업행위를 위 규칙으로 추정한다 — 배수는 실제 분할비와
  재개일 시가 변동만큼(최대 ±30%) 다를 수 있다.
- 등급·판정은 연구 스크립트(`scripts/study_turnover_overheat.py`)가 매긴다. 여기는 계산만 한다.
"""
from __future__ import annotations

import math

import numpy as np

BAD = 0.32          # 일간 ±32% 초과 = 데이터 오류(가격제한 30% + 여유)
BAND = 0.31         # 기업행위 추정 밴드


# ── 기업행위 조정 ────────────────────────────────────────────────────
def split_factors(open_, close, band: float = BAND, liquidation_tail: int = 7,
                  delisted: bool = False) -> tuple[np.ndarray, np.ndarray]:
    """기업행위 추정 → (행별 조정 배수, 이벤트 행 인덱스).

    배수[i] = i **이후** 이벤트들의 시가 비율 곱 — 과거 가격에 곱하고 거래량은 나눈다.
    부호가 반대(하락)인 이벤트가 마지막 `liquidation_tail` 행 안에 있고 종목이 시장 마지막 날 전에 끝났으면
    정리매매로 보고 조정하지 않는다(그 행은 이후 '데이터 오류일'로 창에서 빠진다).
    """
    o = np.asarray(open_, dtype=float)
    c = np.asarray(close, dtype=float)
    n = c.size
    fac = np.ones(n)
    if n < 2:
        return fac, np.array([], dtype=int)
    pc = c[:-1]
    ok = (o[1:] > 0) & (pc > 0)
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.where(ok, o[1:] / pc, np.nan)
        rc = np.where(ok, c[1:] / pc, np.nan)
    lo, hi = 1 - band, 1 + band
    cand = ((r < lo) & (rc < lo)) | ((r > hi) & (rc > hi))
    idx = np.flatnonzero(np.nan_to_num(cand, nan=False)) + 1
    if idx.size == 0:
        return fac, idx
    keep = []
    for i in idx:
        if delisted and r[i - 1] < 1 and (n - 1 - i) <= liquidation_tail:
            continue          # 정리매매 하락 — 조정 대상 아님
        keep.append(i)
    idx = np.array(keep, dtype=int)
    if idx.size == 0:
        return fac, idx
    evf = np.ones(n)
    evf[idx] = r[idx - 1]
    # fac[i] = prod_{j>i} evf[j]
    tail = np.cumprod(evf[::-1])[::-1]          # prod_{j>=i}
    fac = np.concatenate([tail[1:], np.ones(1)])
    return fac, idx


def adjust_series(open_, high, low, close, volume, delisted: bool = False) -> dict:
    """한 종목 시계열의 기업행위 조정 — 가격은 곱하고 거래량은 나눈다. 이벤트 수를 함께 돌려준다.

    delisted=True 면 마지막 7행 안의 하락 점프를 정리매매로 보고 조정하지 않는다(그 종목의 창은 오류일로 제외된다).
    """
    o = np.asarray(open_, dtype=float)
    h = np.asarray(high, dtype=float)
    lo_ = np.asarray(low, dtype=float)
    c = np.asarray(close, dtype=float)
    v = np.asarray(volume, dtype=float)
    fac, idx = split_factors(o, c, delisted=delisted)
    with np.errstate(divide="ignore", invalid="ignore"):
        return {"open": o * fac, "high": h * fac, "low": lo_ * fac, "close": c * fac,
                "volume": np.where(fac > 0, v / fac, v), "events": int(idx.size)}


# ── 기본 지표 ────────────────────────────────────────────────────────
def turnover(close, volume) -> np.ndarray:
    """거래대금 근사 = 종가 × 거래량."""
    return np.asarray(close, dtype=float) * np.asarray(volume, dtype=float)


def rolling_mean(x, window: int) -> np.ndarray:
    """뒤로 window 칸 평균(오늘 포함). 창 안에 결측이 있거나 앞부분이면 NaN."""
    a = np.asarray(x, dtype=float)
    n = a.size
    out = np.full(n, np.nan)
    if n == 0 or window < 1 or n < window:
        return out
    if np.isnan(a).any():
        for i in range(window - 1, n):
            seg = a[i - window + 1:i + 1]
            if not np.isnan(seg).any():
                out[i] = seg.mean()
        return out
    cs = np.concatenate([[0.0], np.cumsum(a)])
    out[window - 1:] = (cs[window:] - cs[:-window]) / window
    return out


def prior_mean(x, window: int, skip: int) -> np.ndarray:
    """x 의 [t−skip−window+1, t−skip] 평균 — 최근 skip 칸을 뺀 기준선(누수 없음)."""
    a = np.asarray(x, dtype=float)
    n = a.size
    out = np.full(n, np.nan)
    first = skip + window - 1
    if n <= first:
        return out
    if np.isnan(a).any():
        for i in range(first, n):
            seg = a[i - skip - window + 1:i - skip + 1]
            if not np.isnan(seg).any():
                out[i] = seg.mean()
        return out
    cs = np.concatenate([[0.0], np.cumsum(a)])
    idx = np.arange(first, n)
    out[idx] = (cs[idx - skip + 1] - cs[idx - skip - window + 1]) / window
    return out


def intensity(tv, fast: int = 5, slow: int = 20) -> np.ndarray:
    """과열 배수 = 최근 fast일 평균 대금 ÷ 직전 slow일 평균 대금."""
    a = np.asarray(tv, dtype=float)
    base = prior_mean(a, slow, fast)
    fast_m = rolling_mean(a, fast)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(base > 0, fast_m / base, np.nan)


def ret(px, lookback: int = 5) -> np.ndarray:
    """종가 수익률 — px[t] / px[t−lookback] − 1."""
    a = np.asarray(px, dtype=float)
    out = np.full(a.size, np.nan)
    if a.size > lookback and lookback > 0:
        out[lookback:] = a[lookback:] / a[:-lookback] - 1.0
    return out


def daily_return(px) -> np.ndarray:
    a = np.asarray(px, dtype=float)
    out = np.full(a.size, np.nan)
    out[1:] = a[1:] / a[:-1] - 1.0
    return out


def bad_days(open_, close, band: float = BAD) -> np.ndarray:
    """데이터 오류일(조정 후에도 ±band 넘는 일간 변동·갭·장중) 표시."""
    o = np.asarray(open_, dtype=float)
    c = np.asarray(close, dtype=float)
    r1 = daily_return(c)
    prev = np.concatenate([[np.nan], c[:-1]])
    gap = o / prev - 1.0
    intra = c / o - 1.0
    m = (np.abs(r1) > band) | (np.abs(gap) > band) | (np.abs(intra) > band)
    return np.nan_to_num(m, nan=False).astype(bool)


def classify(ratio, hot: float = 2.0, quiet: float = 1.2) -> np.ndarray:
    """과열 배수 → 1=과열(hot), −1=조용(quiet), 0=중간, 9=결측."""
    a = np.asarray(ratio, dtype=float)
    out = np.full(a.size, 9, dtype=np.int8)
    ok = ~np.isnan(a)
    out[ok] = 0
    out[ok & (a >= hot)] = 1
    out[ok & (a <= quiet)] = -1
    return out


# ── 성과 ────────────────────────────────────────────────────────────
def forward_open_return(open_, close, horizon: int = 5) -> np.ndarray:
    """t+1 시가 매수 → t+horizon 종가 매도 수익률(창이 모자라면 NaN). 신호일 t 에 기록."""
    o = np.asarray(open_, dtype=float)
    c = np.asarray(close, dtype=float)
    n = c.size
    out = np.full(n, np.nan)
    if horizon >= 1 and n > horizon:
        e = o[1:n - horizon + 1]
        x = c[horizon:]
        with np.errstate(divide="ignore", invalid="ignore"):
            out[:n - horizon] = np.where((e > 0) & (x > 0), x / e - 1.0, np.nan)
    return out


def group_stats(r) -> dict:
    """수익 배열 요약 — n·평균·중앙·표준편차·승률·하락 꼬리(≤−10%·≤−20%)·최악·5% 분위."""
    x = np.asarray([v for v in np.asarray(r, dtype=float) if not math.isnan(v)])
    if x.size == 0:
        return {"n": 0}
    return {"n": int(x.size), "mean": float(x.mean()), "median": float(np.median(x)),
            "sd": float(x.std(ddof=1)) if x.size > 1 else None,
            "win": float((x > 0).mean()), "tail10": float((x <= -0.10).mean()),
            "tail20": float((x <= -0.20).mean()), "worst": float(x.min()), "p05": float(np.percentile(x, 5))}


def p_one_sided(t: float, sign: int = 1) -> float:
    """단측 정규 근사 p (repo 관행 — scripts/study_us_r20_reversal.p_one 과 같은 식)."""
    return 0.5 * math.erfc(t * sign / math.sqrt(2))


def welch(a, b) -> dict:
    """두 표본 평균차 Welch t (a−b) 단측(+). 반환 {n_a, n_b, mean_a, mean_b, diff, t, p_one}."""
    a = np.asarray([x for x in np.asarray(a, dtype=float) if not math.isnan(x)])
    b = np.asarray([x for x in np.asarray(b, dtype=float) if not math.isnan(x)])
    if a.size < 3 or b.size < 3:
        return {"n_a": int(a.size), "n_b": int(b.size), "diff": None, "t": None, "p_one": None,
                "mean_a": float(a.mean()) if a.size else None, "mean_b": float(b.mean()) if b.size else None}
    se = math.sqrt(a.var(ddof=1) / a.size + b.var(ddof=1) / b.size)
    diff = float(a.mean() - b.mean())
    t = diff / se if se > 0 else 0.0
    return {"n_a": int(a.size), "n_b": int(b.size), "mean_a": float(a.mean()), "mean_b": float(b.mean()),
            "diff": diff, "t": float(t), "p_one": p_one_sided(t, +1)}


def month_cluster(diffs, dates) -> dict:
    """날짜별 차이 → 월별 평균 → 월 평균들의 단측 t (겹치는 창·같은 날 군집 완화).

    diffs: 날짜별 (조용 − 과열) 평균 초과수익, dates: 'YYYY-MM-DD' 배열.
    """
    d = np.asarray(diffs, dtype=float)
    if d.size == 0:
        return {"n_dates": 0, "n_months": 0, "mean": None, "t": None, "p_one": None}
    mon = np.array([str(x)[:7] for x in dates])
    keys = sorted(set(mon.tolist()))
    mv = np.array([d[mon == k].mean() for k in keys])
    if mv.size < 3 or mv.std(ddof=1) == 0:
        return {"n_dates": int(d.size), "n_months": int(mv.size), "mean": float(mv.mean()) if mv.size else None,
                "t": None, "p_one": None, "months": keys}
    t = float(mv.mean() / (mv.std(ddof=1) / math.sqrt(mv.size)))
    return {"n_dates": int(d.size), "n_months": int(mv.size), "mean": float(mv.mean()), "t": t,
            "p_one": p_one_sided(t, +1), "months": keys, "month_means": mv.tolist()}


def grade(p, subs: dict, n_events: int, n_months: int, alpha: float = 0.025,
          min_events: int = 30, min_months: int = 12) -> tuple[str, str]:
    """등급 규칙 — scripts/study_rule_audit.grade() 와 같은 문턱(표본 하한만 이 연구 기준으로 명시).

    A = Bonferroni α 통과 + IS·OOS 같은 방향 · B = Bonferroni 통과, 하위 구간 방향 불일치
    C = 방향만(p < 0.10) · F = 구별 안 됨 · 검증전 = 표본 부족(사건 <30 또는 월 <12)
    """
    if p is None or n_events < min_events or n_months < min_months:
        return "검증전", f"표본 부족(사건 {n_events}·월 {n_months}, 기준 {min_events}/{min_months})"
    if p < alpha:
        vals = [v for v in subs.values() if v is not None]
        if vals and all(np.sign(v) > 0 for v in vals):
            return "A", f"Bonferroni 유의(p={p:.4f}) + IS·OOS 같은 방향"
        return "B", f"Bonferroni 유의(p={p:.4f}), 하위 구간 방향 불일치"
    if p < 0.10:
        return "C", f"방향만(p={p:.3f}, Bonferroni α={alpha:.4f} 미달)"
    return "F", f"현행과 구별 안 됨(p={p:.2f})"
