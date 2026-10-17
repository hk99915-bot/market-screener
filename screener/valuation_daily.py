"""반도체 밸류에이션 바스켓 — 일일 추적 (python -m screener.main --mode valuation).

공개용 '관찰 목록(watchlist)' 이다. 보유·금액은 다루지 않고 비율만 낸다. 매매 트리거가 아니라 참고 자료.

입력
- US: data/fin/us_quarterly.parquet (SEC companyfacts, screener/sec.py 가 만든 long 형식)
- KR: screener/fin.py quarterly() (DART 전체재무제표 → 단독 분기), universe/kr_shares.csv (주식 수)
- 가격: reports/detail/<KR|US>/<code>.json (close, stats.ret20)
- 금리: reports/live.json (US10Y), reports/bonds.json (美 10Y·국고 3Y 와 5일 변화)
- 이벤트: reports/calendar.json + 아래 고정 '발동선(tripwire)' 목록

지표 (모두 최근 종가 기준, 분기 4개 미만이면 '검증전')
- TTM EPS → PER, BPS → PBR, ROE(TTM), 매출 YoY(최근 분기), 영업이익률 4분기 추세, OCF/순이익, 순현금(근사), EV/EBITDA
- 금리조정 매력 = 이익수익률(E/P) − 무위험(US: 미 10Y, KR: 국고 3Y)
- PER 세 분모: TTM / 런레이트(최근 분기×4) / 가이던스(universe/fin_guidance.json 의 다음 분기 매출·EPS ×4) — 사이클 업종은 분모 선택이 결론을 가른다
- 20일 분해: ln(P1/P0) = ln(PER1/PER0) + ln(EPS1/EPS0)  (가격 변화 = 멀티플 변화 + 이익 변화)
  20일 전 EPS 는 reports/archive/valuation/ 의 과거 산출물에서 가져온다 — 없으면 EPS 변화 0 으로 두고 '검증전' 표시.

기존 screener/valuation.py(KR 6모델 적정가)와 다른 모듈이다: 그쪽은 종목 상세의 '적정가 범위', 여기는 바스켓의 '현재 배수 추적'.
"""
from __future__ import annotations

import json
import logging
import math
import statistics as st
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")

# ───────────── 바스켓 (공개용 관찰 목록) ─────────────
BASKET = [
    {"sym": "005930", "mk": "KR", "name": "삼성전자"},
    {"sym": "000660", "mk": "KR", "name": "SK하이닉스"},
    {"sym": "009150", "mk": "KR", "name": "삼성전기"},
    {"sym": "000990", "mk": "KR", "name": "DB하이텍"},
    {"sym": "042700", "mk": "KR", "name": "한미반도체"},
    {"sym": "MU", "mk": "US", "name": "Micron"},
    {"sym": "SNDK", "mk": "US", "name": "Sandisk"},
    {"sym": "NVDA", "mk": "US", "name": "NVIDIA"},
    {"sym": "AMD", "mk": "US", "name": "AMD"},
    {"sym": "INTC", "mk": "US", "name": "Intel"},
    {"sym": "TXN", "mk": "US", "name": "Texas Instr."},
    {"sym": "AMAT", "mk": "US", "name": "Applied Mat."},
    {"sym": "KLAC", "mk": "US", "name": "KLA"},
    {"sym": "ADI", "mk": "US", "name": "Analog Dev."},
    {"sym": "LRCX", "mk": "US", "name": "Lam Research"},
    {"sym": "TSM", "mk": "US", "name": "TSMC(ADR)"},
]
ETFS = [{"sym": "PSI", "mk": "US", "name": "PSI(반도체)"}, {"sym": "SOXX", "mk": "US", "name": "SOXX"},
        {"sym": "139260", "mk": "KR", "name": "TIGER 200 IT"}]

# 반도체 논지의 공개 발동선 — 날짜는 공개 일정 기준, [확인 필요] 표시는 확정 전
TRIPWIRES = [
    {"date": "2026-10-28", "name": "HBM4·LTA 관련 발표 예정", "note": "[확인 필요] 공개 보도 기준, 확정 아님"},
    {"date": "2026-10-28", "name": "SK하이닉스 실적", "note": "calendar.json 과 동일"},
    {"date": "2026-10-29", "name": "삼성전자 실적", "note": "확정 실적 (잠정치 이후 사업부별)"},
    {"date": None, "name": "FOMC 금리 결정", "note": "calendar.json 에서 날짜 읽음"},
    {"date": None, "name": "미 10년물 5.0% 상·하 돌파", "note": "현재 수준은 금리 블록 참조"},
]
MIN_Q = 4          # 이보다 적은 분기로 만든 값은 '검증전'
CUM_RATIO = 1.8    # 최근 4분기가 매 분기 이 배수 넘게 단조 증가하면 누적(YTD) 값 의심 → '검증전'
VERIFIED_PATH = "universe/fin_verified.json"   # 사람이 8-K/10-Q 원문과 대조한 분기값 — 일치하면 누적 의심 해제
VERIFIED_TOL = 0.01                              # 대조 허용 오차 1%
GUIDANCE_PATH = "universe/fin_guidance.json"     # 사람이 적는 다음 분기 가이던스(매출·EPS 범위, 공시 숫자) → '가이던스 PER'
RATE_BP = 25       # 금리 민감도 가정 ±bp


# ───────────── 순수 계산 (테스트 대상) ─────────────

def _sum(rows: list[dict], key: str) -> float | None:
    vals = [r.get(key) for r in rows]
    if not vals or any(v is None for v in vals):
        return None
    return float(sum(vals))


def _last(rows: list[dict], key: str) -> float | None:
    for r in reversed(rows):
        if r.get(key) is not None:
            return float(r[key])
    return None


def _safe_div(a, b) -> float | None:
    try:
        if a is None or b is None or b == 0:
            return None
        return a / b
    except Exception:  # noqa: BLE001
        return None


def cumulative_smell(q: list[dict], keys: tuple[str, ...] = ("ni", "revenue", "op")) -> str | None:
    """최근 4분기 중 어느 항목이 매 분기 CUM_RATIO 배 넘게 단조 증가하면 그 항목 이름 — SEC/DART 분기 값에 누적치가 섞인 전형.
    (정상 고성장도 걸릴 수 있어 '검증전' 표시만, 값은 그대로 둔다.) 양수 4개가 모두 있어야 판단."""
    last4 = q[-4:]
    if len(last4) < 4:
        return None
    for k in keys:
        v = [r.get(k) for r in last4]
        if any(x is None or x <= 0 for x in v):
            continue
        if all(v[i + 1] > v[i] * CUM_RATIO for i in range(3)):
            return k
    return None


def _load_verified() -> dict:
    """{ticker: {period: {item: value, "src": url}}} — 없으면 빈 dict."""
    try:
        from pathlib import Path
        return json.loads(Path(VERIFIED_PATH).read_text(encoding="utf-8"))
    except Exception:
        return {}


def externally_verified(q: list[dict], sym: str | None, verified: dict | None = None) -> str | None:
    """최신 분기의 항목이 사람이 원문 대조해 둔 값과 1% 안에서 일치하면 출처 문자열, 아니면 None.
    누적치 의심(cumulative_smell)은 휴리스틱이라 진짜 초고성장(2026 메모리 사이클)을 오탐한다 — 원문 대조가 우선한다."""
    if not sym or not q:
        return None
    v = (verified if verified is not None else _load_verified()).get(sym) or {}
    last = q[-1]
    rec = v.get(str(last.get("end"))) or v.get(str(last.get("period")))   # 키는 분기 말일(YYYY-MM-DD), 구형은 2026Q3
    if not rec:
        return None
    hits = 0
    for k, want in rec.items():
        if k == "src" or not isinstance(want, (int, float)):
            continue
        got = last.get(k)
        if got is None or want == 0:   # 수집 안 된 항목은 대조 대상에서 뺀다 (MU 매출 태그 미수집 등)
            continue
        if abs(got - want) / abs(want) > VERIFIED_TOL:
            return None
        hits += 1
    return rec.get("src", "원문 대조") if hits else None


def run_rate(q: list[dict], shares: float | None, price: float | None) -> dict:
    """런레이트(run-rate) PER: 최근 '한' 분기 순이익 ×4 를 연간 이익으로 보고 계산.
    TTM 이 '지난 1년 평균'이라면 런레이트는 '지금 속도가 1년 계속되면'. 분기가 5→14→28→38 로 가는 회사에서 둘은 크게 벌어진다.
    최근 분기가 적자·결측이면 None."""
    out = {"eps_run_rate": None, "per_run_rate": None, "run_rate_period": None}
    if not q:
        return out
    last = q[-1]
    ni = last.get("ni_owner") if last.get("ni_owner") is not None else last.get("ni")
    if ni is None or not shares:
        return out
    eps = ni * 4 / shares
    out.update({"eps_run_rate": eps, "run_rate_period": last.get("period"),
                "per_run_rate": (price / eps) if (price and eps > 0) else None})
    return out


def _load_guidance() -> dict:
    """{ticker: {"period": "FQ1'27", "revenue_lo": .., "revenue_hi": .., "eps_lo": .., "eps_hi": .., "eps_basis": "non-GAAP", "src": url}}"""
    try:
        from pathlib import Path
        g = json.loads(Path(GUIDANCE_PATH).read_text(encoding="utf-8"))
        return {k: v for k, v in g.items() if not k.startswith("_")}
    except Exception:
        return {}


def guidance_per(g: dict | None, q: list[dict], shares: float | None, price: float | None) -> dict:
    """가이던스 PER: 회사가 제시한 '다음 분기' 숫자 ×4 로 만든 연간 이익 기준.
    1) EPS 가이던스가 있으면 중앙값 ×4 (회사가 non-GAAP 으로 주면 basis 에 그대로 표기 — GAAP 과 섞지 않는다).
    2) 매출 가이던스만 있으면 '최근 분기 순이익률이 유지된다' 가정으로 순이익을 만든다(가정을 basis 에 적는다).
    범위(lo~hi)가 있으면 PER 도 범위(hi 이익 → 낮은 PER)로 돌려준다. 가이던스가 없으면 전부 None."""
    out = {"per_guide": None, "per_guide_lo": None, "per_guide_hi": None, "guide_period": None, "guide_basis": None, "guide_src": None}
    if not g or not price or not shares:
        return out
    out["guide_period"], out["guide_src"] = g.get("period"), g.get("src")
    lo, hi = g.get("eps_lo"), g.get("eps_hi")
    if lo is not None or hi is not None:
        lo = lo if lo is not None else hi
        hi = hi if hi is not None else lo
        out["guide_basis"] = f"EPS 가이던스({g.get('eps_basis') or 'GAAP'}) ×4"
        eps_lo, eps_hi = lo * 4, hi * 4
    else:
        rlo, rhi = g.get("revenue_lo"), g.get("revenue_hi")
        if rlo is None and rhi is None or not q:
            return out
        rlo = rlo if rlo is not None else rhi
        rhi = rhi if rhi is not None else rlo
        last = q[-1]
        ni = last.get("ni_owner") if last.get("ni_owner") is not None else last.get("ni")
        rev = last.get("revenue") or g.get("last_revenue")   # 매출 미수집(MU)이면 가이던스 파일의 최근 분기 매출(공시값)로 대체
        if ni is None or not rev or ni <= 0:
            return out
        margin = ni / rev
        out["guide_basis"] = f"매출 가이던스 × 최근 분기 순이익률 {margin*100:.0f}% 유지 가정 ×4"
        eps_lo, eps_hi = rlo * margin * 4 / shares, rhi * margin * 4 / shares
    if eps_lo <= 0 or eps_hi <= 0:
        return out
    out["per_guide_lo"], out["per_guide_hi"] = price / eps_hi, price / eps_lo     # 이익 상단 → PER 하단
    out["per_guide"] = price / ((eps_lo + eps_hi) / 2)
    return out


def metrics(q: list[dict], shares: float | None, price: float | None, sym: str | None = None) -> dict:
    """q: 분기 dict 목록(오래된 → 최신). 항목 revenue/op/ni/(ni_owner)/cfo/capex/da/assets/liab/(equity_owner|equity)/cash.
    shares: 주식 수, price: 종가. 통화는 q 와 price 가 같아야 한다. 결과는 비율 중심, 데이터가 없으면 None."""
    q = [r for r in q if r]
    n = len(q)
    out: dict = {"n_quarters": n, "verified": n >= MIN_Q, "period": q[-1].get("period") if q else None}
    if n == 0:
        out["flags"] = ["재무 데이터 없음"]
        return out
    last4 = q[-4:]
    ni = _sum(last4, "ni_owner")
    if ni is None:
        ni = _sum(last4, "ni")
    op = _sum(last4, "op")
    rev = _sum(last4, "revenue")
    cfo = _sum(last4, "cfo")
    da = _sum(last4, "da")
    eq = _last(last4, "equity_owner") if _last(last4, "equity_owner") is not None else _last(last4, "equity")
    cash, liab, assets = _last(last4, "cash"), _last(last4, "liab"), _last(last4, "assets")
    if n < MIN_Q:   # 4분기 미만: TTM 대신 있는 만큼 ×(4/n) 연환산 — 검증전
        k = 4 / n
        ni, op, rev, cfo, da = [(v * k if v is not None else None) for v in (ni, op, rev, cfo, da)]
    eps = _safe_div(ni, shares)
    bps = _safe_div(eq, shares)
    out.update({
        "eps_ttm": eps, "bps": bps,
        "per": (price / eps) if (price and eps and eps > 0) else None,
        "pbr": (price / bps) if (price and bps and bps > 0) else None,
        "roe": _safe_div(ni, eq) if (eq and eq > 0) else None,
        "ocf_ni": _safe_div(cfo, ni) if (ni and ni > 0) else None,
        "op_margin_4q": [(_safe_div(r.get("op"), r.get("revenue")) if r.get("revenue") else None) for r in last4],
        "net_cash_proxy_ratio": None, "ev_ebitda": None, "rev_yoy": None, "earn_yield": None,
        "loss": bool(eps is not None and eps <= 0),
    })
    if price and eps and eps > 0:
        out["earn_yield"] = eps / price
    out.update(run_rate(q, shares, price))                                         # 최근 분기 ×4
    out.update(guidance_per(_load_guidance().get(sym) if sym else None, q, shares, price))   # 다음 분기 가이던스 ×4
    # 매출 YoY: 최신 분기 vs 4분기 전 같은 분기
    if n >= 5 and q[-1].get("revenue") and q[-5].get("revenue"):
        out["rev_yoy"] = q[-1]["revenue"] / q[-5]["revenue"] - 1
    # 순현금 근사 = 현금 − 총부채 (차입금 항목이 없어 보수적). 시가총액 대비 비율로만 낸다.
    mcap = price * shares if (price and shares) else None
    if mcap and cash is not None and liab is not None:
        out["net_cash_proxy_ratio"] = (cash - liab) / mcap
        ebitda = (op + da) if (op is not None and da is not None) else None
        if ebitda and ebitda > 0:
            out["ev_ebitda"] = (mcap + liab - cash) / ebitda
    flags = []
    if not out["verified"]:
        flags.append(f"검증전: 분기 {n}개 (연환산)")
    smell = cumulative_smell(q)
    if smell:   # 누적치 의심 — 비율은 내되 검증전으로 내린다 (10/17 SEC YTD 점검)
        src = externally_verified(q, sym)
        if src:   # 사람이 8-K/10-Q 원문과 대조한 분기 → 오탐으로 보고 해제 (10/17 MU·SNDK 웹 대조)
            flags.append(f"원문 대조 일치({src}) → 누적 의심 해제")
        else:
            out["verified"] = False
            flags.append(f"검증전: {smell} 4분기 연속 {CUM_RATIO}배↑ (누적치 의심)")
    if out["loss"]:
        flags.append("TTM 적자 → PER 없음")
    if rev is None:
        flags.append("매출 항목 없음")
    if da is None:
        flags.append("감가상각 없음 → EV/EBITDA 생략")
    out["flags"] = flags
    return out


def decompose(price_now: float | None, price_prev: float | None, eps_now: float | None, eps_prev: float | None) -> dict:
    """20일 분해. 로그수익률이라 세 항이 정확히 더해진다: Δ가격 = Δ멀티플 + ΔEPS.
    EPS 가 양→양이 아니면 멀티플 분해가 정의되지 않아 가격 변화만 돌려준다."""
    out = {"d_price": None, "d_multiple": None, "d_eps": None, "note": None}
    if not price_now or not price_prev or price_now <= 0 or price_prev <= 0:
        out["note"] = "가격 없음"
        return out
    dp = math.log(price_now / price_prev)
    out["d_price"] = dp
    if eps_now and eps_prev and eps_now > 0 and eps_prev > 0:
        de = math.log(eps_now / eps_prev)
        out["d_eps"], out["d_multiple"] = de, dp - de
    else:
        out["note"] = "EPS 비교 불가(적자·결측) → 멀티플 분해 생략"
    return out


def rate_sensitivity(per: float | None, bp: int = RATE_BP) -> dict:
    """일정한 주식위험프리미엄(ERP)·성장률 가정: E/P = rf + ERP − g → Δ(E/P) = Δrf.
    PER' = 1/(1/PER + Δrf) → ΔPER/PER = −PER·Δrf/(1 + PER·Δrf)."""
    if not per or per <= 0:
        return {"per": per, "bp": bp, "up": None, "down": None,
                "formula": "E/P = rf + ERP − g (ERP·g 고정) → PER' = 1/(1/PER + Δrf)"}
    d = bp / 10_000
    return {"per": per, "bp": bp,
            "up": 1 / (1 / per + d) / per - 1,       # 금리 +bp → PER 변화율 (음수)
            "down": 1 / (1 / per - d) / per - 1 if 1 / per > d else None,
            "formula": "E/P = rf + ERP − g (ERP·g 고정) → PER' = 1/(1/PER + Δrf) → ΔPER/PER = −PER·Δrf/(1+PER·Δrf)"}


def _median(xs: list) -> float | None:
    xs = [x for x in xs if x is not None and x == x]
    return st.median(xs) if xs else None


# ───────────── 데이터 적재 ─────────────

def us_quarters(ticker: str, n: int = 12, df=None) -> tuple[list[dict], float | None]:
    """SEC long → 분기 dict 목록(손익 있는 분기만, 최근 n개), 최근 주식 수. 데이터 없으면 ([], None).
    df: 미리 읽어 둔 us_quarterly 프레임(전 종목 일괄 처리 시 parquet 재읽기 방지 — valuation.us_all)."""
    try:
        import polars as pl
        from .sec import OUT
        if df is None:
            if not OUT.exists():
                return [], None
            df = pl.read_parquet(OUT)
        df = df.filter(pl.col("ticker") == ticker)
        if df.is_empty():
            return [], None
        w = df.pivot(on="item", index="end", values="value", aggregate_function="first").sort("end")
        cols = [c for c in ("op", "ni", "revenue") if c in w.columns]
        if not cols:
            return [], None
        shares = None
        if "shares" in w.columns:
            s = w.filter(pl.col("shares").is_not_null())
            shares = float(s["shares"][-1]) if len(s) else None
        w = w.filter(pl.any_horizontal([pl.col(c).is_not_null() for c in cols]))
        rows = []
        for r in w.to_dicts():
            d = date.fromisoformat(r["end"])
            rows.append({**r, "period": f"{d.year}Q{(d.month - 1) // 3 + 1}"})
        return rows[-n:], shares
    except Exception as e:  # noqa: BLE001
        log.warning("SEC 분기 %s 실패: %s", ticker, e)
        return [], None


def kr_quarters(code: str) -> tuple[list[dict], float | None]:
    try:
        from . import fin, shares
        q = fin.quarterly(code)
        rows = q.to_dicts()[-12:] if q is not None and not q.is_empty() else []
        n = None
        try:   # 종목 상세(valuation.kr_all)와 같은 분모 — shares_map (자사주 제외·우선주 포함, 보고서 이후 변동 반영). 감사 M3 10/17
            m0 = shares.shares_map().get(code)
            n = m0["n"] if m0 else None
        except Exception as e:  # noqa: BLE001
            log.warning("주식 수 %s: %s", code, e)
        rows = [r for r in rows if any(r.get(k) is not None for k in ("op", "ni", "revenue"))]
        return rows, (float(n) if n else None)
    except Exception as e:  # noqa: BLE001
        log.warning("DART 분기 %s 실패: %s", code, e)
        return [], None


def _detail(mk: str, sym: str) -> dict:
    from .config import REPORT_DIR
    p = REPORT_DIR / "detail" / mk / f"{sym}.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _json(path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def rates() -> dict:
    """US10Y(live 우선, 없으면 bonds) · 국고3Y 와 5일 변화(bp)."""
    from .config import REPORT_DIR
    live = _json(REPORT_DIR / "live.json")
    bonds = _json(REPORT_DIR / "bonds.json")
    us10 = next((i.get("last") for i in live.get("items", []) if i.get("key") == "US10Y"), None)
    b_us = ((bonds.get("us") or {}).get("chg") or {}).get("10Y") or {}
    b_kr = ((bonds.get("kr") or {}).get("chg") or {}).get("3Y") or {}
    return {"us10y": us10 if us10 is not None else b_us.get("v"), "us10y_w1_bp": b_us.get("w1"), "us10y_date": b_us.get("date") or live.get("updated_at"),
            "kr3y": b_kr.get("v"), "kr3y_w1_bp": b_kr.get("w1"), "kr3y_date": b_kr.get("date"),
            "us10y_live": us10 is not None}


def events(today: date, days: int = 14) -> dict:
    from .config import REPORT_DIR
    cal = _json(REPORT_DIR / "calendar.json")
    end = today + timedelta(days=days)
    ev = [e for e in cal.get("events", []) if today.isoformat() <= str(e.get("date", "")) <= end.isoformat()]
    ev = sorted(ev, key=lambda e: (e["date"], -(e.get("imp") or 0)))
    fomc = next((e["date"] for e in cal.get("events", []) if "FOMC" in str(e.get("name", "")) and str(e.get("date", "")) >= today.isoformat()), None)
    trips = []
    for t in TRIPWIRES:
        d = t["date"] or (fomc if "FOMC" in t["name"] else None)
        trips.append({**t, "date": d})
    return {"window_days": days, "next": [{"date": e["date"], "name": e.get("name"), "type": e.get("type"), "imp": e.get("imp")} for e in ev[:20]],
            "tripwires": trips, "fomc": fomc}


def _prev_archive(today: date, lag: int = 20) -> dict | None:
    """약 20일(달력) 전 산출물 — 분해의 EPS₀. 20일 전에서 ±5일 안의 가장 가까운 것."""
    from .config import REPORT_DIR
    hd = REPORT_DIR / "archive" / "valuation"
    if not hd.exists():
        return None
    target = today - timedelta(days=lag)
    best, best_d = None, 99
    for p in hd.glob("20??-??-??.json"):
        try:
            d = abs((date.fromisoformat(p.stem) - target).days)
        except ValueError:
            continue
        if d <= 5 and d < best_d:
            best, best_d = p, d
    return _json(best) if best else None


# ───────────── 조립 ─────────────

PER_BASIS = "보고 순이익(지배주주) 최근 4분기 합 ÷ 주식 수(DART 자사주 제외·우선주 포함) · 가격 = 종목 상세 종가(price_date)"


def price_asof(rows: list[dict], etfs: list[dict] | None = None) -> tuple[str | None, dict]:
    """산출물 asof = **가격 기준일**(실행일 아님, 감사 M4 10/17). KR 행 가격일 중 최신(계약 market=KR) → 없으면 전체 최신.
    시장별 가격일은 price_asof 로 따로 남긴다."""
    by: dict[str, set] = {}
    for r in list(rows) + list(etfs or []):
        if r.get("price_date"):
            by.setdefault(r.get("mk") or "?", set()).add(str(r["price_date"])[:10])
    pa = {k: max(v) for k, v in by.items()}
    kr = pa.get("KR")
    return (kr or (max(pa.values()) if pa else None)), pa


def build(send: bool = False) -> dict:
    from .config import REPORT_DIR
    today = datetime.now(KST).date()
    rt = rates()
    prev = _prev_archive(today)
    prev_rows = {r["sym"]: r for r in (prev or {}).get("rows", [])}
    rows = []
    for b in BASKET:
        det = _detail(b["mk"], b["sym"])
        price = det.get("close")
        asof = det.get("asof")
        ret20 = (det.get("stats") or {}).get("ret20")
        q, sh = (us_quarters if b["mk"] == "US" else kr_quarters)(b["sym"])
        m = metrics(q, sh, price, sym=b["sym"])
        rf = rt["us10y"] if b["mk"] == "US" else rt["kr3y"]
        m["rate_adj"] = (m["earn_yield"] - rf / 100) if (m.get("earn_yield") is not None and rf is not None) else None
        p0 = price / (1 + ret20) if (price and ret20 is not None and ret20 > -1) else None
        pr = prev_rows.get(b["sym"])
        eps0 = pr.get("eps_ttm") if pr else None
        dec = decompose(price, p0, m.get("eps_ttm"), eps0 if eps0 is not None else m.get("eps_ttm"))
        if pr is None and dec["d_multiple"] is not None:
            dec["note"] = "검증전: 20일 전 EPS 기록 없음 → EPS 변화 0 가정"
        r = {**b, "price": price, "price_date": asof, "shares": sh, "rf": rf, "decomp20": dec, "per_basis": "보고",
             "data_date": m.get("period"), "src": "SEC" if b["mk"] == "US" else "DART", **m}
        if price is None:
            r["flags"] = (r.get("flags") or []) + ["가격 없음(detail 미생성)"]
        rows.append(r)
    etfs = []
    for e in ETFS:
        det = _detail(e["mk"], e["sym"])
        etfs.append({**e, "price": det.get("close"), "price_date": det.get("asof"), "ret20": (det.get("stats") or {}).get("ret20")})

    ok = [r for r in rows if r.get("verified") and not r.get("loss")]
    med_per, med_pbr = _median([r.get("per") for r in ok]), _median([r.get("pbr") for r in rows if r.get("verified")])
    adj = sorted([r for r in rows if r.get("rate_adj") is not None], key=lambda r: r["rate_adj"], reverse=True)
    dm = [r["decomp20"]["d_multiple"] for r in rows if r["decomp20"].get("d_multiple") is not None]
    de = [r["decomp20"]["d_eps"] for r in rows if r["decomp20"].get("d_eps") is not None]
    dp = [r["decomp20"]["d_price"] for r in rows if r["decomp20"].get("d_price") is not None]
    basket = {"n": len(rows), "n_verified": sum(1 for r in rows if r.get("verified")), "n_priced": sum(1 for r in rows if r.get("price")),
              "median_per": med_per, "median_pbr": med_pbr,
              "median_per_run_rate": _median([r.get("per_run_rate") for r in ok]),
              "n_guided": sum(1 for r in rows if r.get("per_guide") is not None),
              "cheapest": [{"sym": r["sym"], "name": r["name"], "rate_adj": r["rate_adj"], "per": r.get("per")} for r in adj[:3]],
              "richest": [{"sym": r["sym"], "name": r["name"], "rate_adj": r["rate_adj"], "per": r.get("per")} for r in adj[-3:][::-1]],
              # 바스켓 분해: 가격·EPS 는 중앙값, 멀티플은 차로 정의해 세 항이 더해지게 한다
              "decomp20": {"d_price": _median(dp), "d_eps": _median(de),
                           "d_multiple": (_median(dp) - (_median(de) or 0.0)) if _median(dp) is not None else None,
                           "n": len(dm), "basis": "20일 전 산출물 EPS" if prev else "검증전(EPS 변화 0 가정)"},
              "rate_sens": rate_sensitivity(med_per)}
    pa_day, pa = price_asof(rows, etfs)
    out = {"asof": pa_day or today.isoformat(), "price_asof": pa, "run_date": today.isoformat(),
           "generated_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"),
           "grade": "참고(검증전) — 매매 트리거 아님", "unit": "비율만 (보유·금액 없음)",
           "rates": rt, "basket": basket, "rows": rows, "etfs": etfs, "events": events(today),
           "definitions": {"TTM": "최근 4개 분기 합", "per": PER_BASIS,
                           "per_vs_detail": "종목 상세 PER 은 일회성(순이익>영업이익×1.2) 제외 '핵심 EPS' 기준일 수 있음 — 상세의 per_reported 가 이 표의 PER 과 같은 기준",
                           "asof": "가격 기준일(KR 종가일). 실행 시각은 generated_at", "rate_adj": "E/P − 무위험(US 미10Y, KR 국고3Y)",
                           "decomp20": "ln(P1/P0) = ln(PER1/PER0) + ln(EPS1/EPS0)",
                           "per_run_rate": "최근 분기 순이익×4 기준 PER", "per_guide": "다음 분기 가이던스×4 기준 PER (universe/fin_guidance.json)", "검증전": f"분기 {MIN_Q}개 미만 또는 20일 전 EPS 기록 없음"}}
    REPORT_DIR.mkdir(exist_ok=True)
    from .guard import allow, write_json
    if not allow(REPORT_DIR / "valuation.json", out.get("asof")):   # asof 역행이면 json·md·이력 모두 건너뜀
        return out
    write_json(REPORT_DIR / "valuation.json", out, default=str)
    _archive(out)
    (REPORT_DIR / "valuation.md").write_text(markdown(out), encoding="utf-8")
    msg = telegram_text(out)
    if send:
        try:
            from .report import send_telegram
            send_telegram(msg)
        except Exception as e:  # noqa: BLE001
            log.warning("밸류에이션 텔레그램 실패: %s", e)
    return out


def _archive(o: dict) -> None:
    from .config import REPORT_DIR
    hd = REPORT_DIR / "archive" / "valuation"
    hd.mkdir(parents=True, exist_ok=True)
    (hd / f"{o['asof']}.json").write_text(json.dumps(o, ensure_ascii=False, default=str), encoding="utf-8")
    idx = _json(hd / "_index.json") or {"days": []}
    b = o["basket"]
    head = f"PER {_f(b.get('median_per'), 1)} · PBR {_f(b.get('median_pbr'), 2)} · 검증 {b['n_verified']}/{b['n']}"
    idx["days"] = sorted([x for x in idx["days"] if x.get("id") != o["asof"]] + [{"id": o["asof"], "date": o["asof"], "headline": head}],
                         key=lambda x: x["date"], reverse=True)[:120]
    (hd / "_index.json").write_text(json.dumps(idx, ensure_ascii=False), encoding="utf-8")


# ───────────── 표현 ─────────────

def _f(x, d=1, suf="") -> str:
    return "—" if x is None or x != x else f"{x:,.{d}f}{suf}"


def _pct(x, d=1) -> str:
    return "—" if x is None or x != x else f"{x*100:+.{d}f}%"


def _trend(r: dict) -> str:
    """이익추세 한 칸: 매출 YoY · 영업이익률 4분기 방향 · OCF/NI."""
    if not r.get("n_quarters"):
        return "재무 없음 (SEC/DART 수집 대기)"
    om = [x for x in (r.get("op_margin_4q") or []) if x is not None]
    arrow = "—"
    if len(om) >= 2:
        arrow = "↑" if om[-1] > om[0] + 0.01 else "↓" if om[-1] < om[0] - 0.01 else "→"
    parts = [f"매출 {_pct(r.get('rev_yoy'), 0)}" if r.get("rev_yoy") is not None else "매출 —",
             f"OPM {arrow}" + (f"{om[-1]*100:.0f}%" if om else ""),
             f"OCF/NI {_f(r.get('ocf_ni'), 1)}" if r.get("ocf_ni") is not None else ""]
    return " · ".join(p for p in parts if p)


def _per3(r: dict) -> str:
    """PER 세 분모 한 칸: TTM / 런레이트(최근 분기×4) / 가이던스(다음 분기×4, 범위). 없으면 —."""
    ttm = "적자" if r.get("loss") else _f(r.get("per"), 1)
    rr = _f(r.get("per_run_rate"), 1)
    if r.get("per_guide") is None:
        gd = "—"
    elif r.get("per_guide_lo") is not None and r.get("per_guide_hi") is not None and abs(r["per_guide_hi"] - r["per_guide_lo"]) > 0.05:
        gd = f"{_f(r['per_guide_lo'], 1)}~{_f(r['per_guide_hi'], 1)}"
    else:
        gd = _f(r.get("per_guide"), 1)
    return f"{ttm} / {rr} / {gd}"


def _mark(r: dict) -> str:
    return "" if r.get("verified") else " ⚠검증전"


def markdown(o: dict) -> str:
    b, rt = o["basket"], o["rates"]
    L = [f"# 반도체 밸류에이션 바스켓 — {o['asof']}", "",
         f"등급: {o['grade']} · {o['unit']} · 생성 {o['generated_at']}", "",
         f"미 10Y {_f(rt.get('us10y'), 2, '%')} (5일 {_f(rt.get('us10y_w1_bp'), 0, 'bp')}) · 국고 3Y {_f(rt.get('kr3y'), 2, '%')} (5일 {_f(rt.get('kr3y_w1_bp'), 0, 'bp')})", "",
         "| 종목 | PER/PBR | 이익추세 | 금리조정 매력 | PER(TTM/런레이트/가이던스) |", "|---|---|---|---|---|"]
    for r in o["rows"]:
        per = "적자" if r.get("loss") else _f(r.get("per"), 1)
        L.append(f"| {r['name']}{_mark(r)} | {per} / {_f(r.get('pbr'), 2)} | {_trend(r)} | {_pct(r.get('rate_adj'))} | {_per3(r)} |")
    L += ["", f"바스켓 중앙 PER {_f(b.get('median_per'), 1)} (런레이트 {_f(b.get('median_per_run_rate'), 1)}) · PBR {_f(b.get('median_pbr'), 2)} "
          f"(검증 {b['n_verified']}/{b['n']}, 가격 {b['n_priced']}/{b['n']}, 가이던스 {b.get('n_guided', 0)}종)"]
    d = b["decomp20"]
    L.append(f"20일 분해(중앙값): 가격 {_pct(d.get('d_price'))} = 멀티플 {_pct(d.get('d_multiple'))} + EPS {_pct(d.get('d_eps'))} · 기준 {d['basis']}")
    s = b["rate_sens"]
    L.append(f"금리 민감도: 중앙 PER {_f(s.get('per'), 1)} 기준 금리 +{s['bp']}bp → PER {_pct(s.get('up'))}, −{s['bp']}bp → {_pct(s.get('down'))}  \n  공식: {s['formula']}")
    L += ["", "## 참고 ETF (가격만)"]
    for e in o["etfs"]:
        L.append(f"- {e['name']} {_f(e.get('price'), 2)} · 20일 {_pct(e.get('ret20'))} ({e.get('price_date') or '—'})")
    ev = o["events"]
    L += ["", f"## 이벤트 (다음 {ev['window_days']}일)"]
    for e in ev["next"][:10]:
        L.append(f"- {e['date']} {e['name']} (중요도 {e.get('imp') or '-'})")
    L += ["", "## 발동선 (공개 일정 기준)"]
    for t in ev["tripwires"]:
        L.append(f"- {t.get('date') or '날짜 미정'} {t['name']} — {t['note']}")
    L += ["", "## 항목 설명", "- TTM: 최근 4개 분기 합. 분기 4개 미만이면 연환산 + ⚠검증전.",
          "- PER(TTM/런레이트/가이던스): 같은 주가를 세 가지 '이익'으로 나눈 값. TTM=지난 1년 합, 런레이트=최근 분기×4(지금 속도가 1년 계속되면), "
          "가이던스=회사가 제시한 다음 분기 숫자×4 (universe/fin_guidance.json, 사람이 적음; EPS 가이던스가 non-GAAP 이면 그 기준, 매출만 있으면 최근 분기 순이익률 유지 가정). "
          "사이클 업종은 세 값이 크게 벌어진다 — 어느 분모를 믿느냐가 결론을 가른다 (docs/valuation_notes/).",
          "- 금리조정 매력 = 이익수익률(TTM EPS ÷ 종가) − 무위험금리(US: 미 10Y, KR: 국고 3Y). 높을수록 금리 대비 싸다.",
          "- 20일 분해: ln(P₁/P₀) = ln(PER₁/PER₀) + ln(EPS₁/EPS₀). 20일 전 EPS 는 archive/valuation 의 과거 산출물.",
          "- 순현금 근사 = 현금 − 총부채 (차입금 항목 미수집, 보수적). EV/EBITDA 는 감가상각 항목이 있을 때만.",
          "- 데이터 날짜: 가격은 detail asof, 재무는 각 행의 최근 분기(period)."]
    return "\n".join(L) + "\n"


def telegram_text(o: dict) -> str:
    """8줄 이내. 비율만."""
    b, rt = o["basket"], o["rates"]
    def nm(x):
        return f"{x['name']} {_pct(x['rate_adj'])}"
    d, s = b["decomp20"], b["rate_sens"]
    ev = next(iter(o["events"]["next"]), None)
    nxt = f"{ev['date'][5:]} {ev['name']}" if ev else "—"
    trip = next((t for t in o["events"]["tripwires"] if t.get("date")), None)
    lines = [f"📊 반도체 밸류에이션 바스켓 {o['asof']} (검증 {b['n_verified']}/{b['n']})",
             f"중앙 PER {_f(b.get('median_per'), 1)}(런레이트 {_f(b.get('median_per_run_rate'), 1)}) · PBR {_f(b.get('median_pbr'), 2)} · 미10Y {_f(rt.get('us10y'), 2, '%')} 국고3Y {_f(rt.get('kr3y'), 2, '%')}",
             "금리조정 매력 상위: " + (" / ".join(nm(x) for x in b["cheapest"]) or "—"),
             "하위: " + (" / ".join(nm(x) for x in b["richest"]) or "—"),
             f"20일 분해(중앙): 가격 {_pct(d.get('d_price'))} = 멀티플 {_pct(d.get('d_multiple'))} + EPS {_pct(d.get('d_eps'))} [{d['basis']}]",
             f"금리 ±{s['bp']}bp → 중앙 PER {_pct(s.get('up'))}/{_pct(s.get('down'))} (ERP 고정 가정)",
             f"다음 이벤트: {nxt}" + (f" · 발동선 {trip['date'][5:]} {trip['name']}" if trip else ""),
             "📎 등급: 밸류에이션은 참고(검증전) — 매매 트리거 아님"]
    return "\n".join(lines)


def summary(o: dict) -> str:
    return telegram_text(o)
