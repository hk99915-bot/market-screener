#!/usr/bin/env python3
"""HF 재량 북 — 회의 때 시그널 보고 그때그때 롱·숏·선물·옵션을 거는 모의 장부 (겸이 10/21 20시 "그때그때 시그널 보고 결정").

  python3 scripts/hf_book.py add --kind us_stock --code LRCX --side 롱 --stop 216 --t1 310 --conv mid \\
      --fund "..." --narrative "..." --positioning "..." --macro "..." --scenarios "..." --hedge "..." \\
      --kill "..." --catalyst 2026-10-28 --p-win 0.55 --p-src "유사 사례 n=40" --why "..." --src "<데이터 경로>"
  python3 scripts/hf_book.py add --kind nq --side 숏 ... --hedge-of 2026-10-21-4     # 헤지 다리(순 리스크로 한도 계산)
  python3 scripts/hf_book.py mark      # 최신 종가로 평가 · 손절/목표/만기/시간 손절 · 북 손실 한도
  python3 scripts/hf_book.py show      # 라운드 기록용 요약 + 포트폴리오 위험 보고(scripts/hf_risk.py)

상태 reports/hf_discretion.json. 가상 1단위 모의 — 실계좌 주문 아님. 체계 북(screener/alphabook.py)과 따로 채점.
가격: 종목 = reports/detail/{KR,US}/<코드>.json 차트(o·h·l·c·v), 코스피200 선물 = data/deriv/daily.csv fut_close(없으면 k200_close),
코스피200 옵션 = 블랙숄즈(σ = atm_iv, 없으면 VKOSPI/100, r 2.5%), es/nq = macro_series SPX·NASDAQ 종합(NQ 근사),
S&P 옵션 = 블랙숄즈(σ = VIX/100) — 옵션은 실제 호가 아님(근사 표기). 가상 AUM 1,000억(수량 표기용).

진입 규칙(10/22 07시 — 겸이 10/21 밤 "실무급, 헤지펀드 운용 10년차"):
- 체크리스트 10칸 필수(재무·내러티브·포지셔닝·매크로·시나리오·헤지·논지 붕괴·촉매·주관 승률·승률 근거) — 비면 거부.
- R:R(1차 목표)·손익분기 승률 1/(1+R:R)·E[R] = p×RR − (1−p) 자동 계산, E[R] ≤ 0 거부. 청산 때 승률 보정(Brier) 기록.
- 크기 = 컨빅션 리스크(low 0.15% · mid 0.25% · high 0.40%, 승률 근거 '주관'이면 low) × 변동성 조정(일 변동성 2% 기준, 0.5~1배),
  종목 명목 ≤ 20일 평균 거래대금 10%(넘으면 자동 축소). 열린 리스크 합 2.0%(국장·미장 합산, 10/22 겸이 "기관이면 어떤 장에서도 돈 버는 게 역할"), 가동률 50% 하한, 헤지 다리(--hedge-of)는 0으로 계산.
- 국장 '거래량 3배 + 20일 신고가' 신호 0~2일 안 종목 추격 롱 금지(reports/studies/2026-10-21_hf_desk_signals.md S4).
- 북 손실 한도: 고점 대비 −3% → 신규 금지(총노출 절반 권고), −5% → 전량 정리·14일 정지, 최근 5거래일 −2% → 신규 금지.
- 손절은 종가 기준, 갭(시가가 이미 손절 밖)이면 시가 체결로 기록. 옵션 매도 금지.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
STATE = ROOT / "reports" / "hf_discretion.json"
KST = timezone(timedelta(hours=9))
RISK_ALL, MAX_OPEN = 0.02, 12
UTIL_MIN = 0.5                     # 가동률 하한(열린 리스크 ÷ 한도) — 미만이면 회의에서 롱·숏 양쪽으로 채우거나 '없음 이유' 기록
RISK_1 = 0.004                     # 1건 상한 = high 컨빅션
CONV = {"low": 0.0015, "mid": 0.0025, "high": 0.0040}
VOL_REF = 0.02                     # 변동성 조정 기준 일 변동성
LIQ_FRAC = 0.10                    # 명목 ≤ 20일 평균 거래대금 10%
DD_BAN, DD_FLAT, WEEK_BAN = -0.03, -0.05, -0.02
HALT_DAYS = 14
AUM = 100_000_000_000      # 가상 AUM 1,000억원(겸이 10/21 지정 — 계약 수 감 잡기용, 실제 돈 아님)
MULT = 250_000             # 코스피200 선물·옵션 승수(원/pt)
RATE = 0.025
COST = {"stock": 0.0045, "fut": 0.0004, "put": 0.02, "call": 0.02,      # 왕복(옵션은 프리미엄 대비 호가 폭 가정)
        "us_stock": 0.002, "es": 0.0002, "nq": 0.0002, "spx_put": 0.01, "spx_call": 0.01}
HOLD = {"stock": 20, "fut": 10, "us_stock": 20, "es": 10, "nq": 10}
OPT = ("put", "call", "spx_put", "spx_call")
US = ("us_stock", "es", "nq", "spx_put", "spx_call")
US_MULT = {"es": 50, "nq": 20, "spx_put": 100, "spx_call": 100}   # 달러/pt (NQ 는 나스닥 종합으로 근사)
CHECK = ("fund", "narrative", "positioning", "macro", "scenarios", "hedge", "kill", "catalyst", "p_win", "p_src")
CHECK_KO = {"fund": "재무·추정치", "narrative": "뉴스·촉매", "positioning": "거래량·수급·공매도·옵션 내재", "macro": "매크로 관계",
            "scenarios": "시나리오 손익(최악 포함)", "hedge": "헤지", "kill": "논지 붕괴 조건", "catalyst": "다음 촉매",
            "p_win": "주관 승률", "p_src": "승률 근거"}


def ncdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs(kind: str, s: float, k: float, t: float, sig: float, r: float = RATE) -> float:
    if t <= 0:
        return max(0.0, (s - k) if kind == "call" else (k - s))
    d1 = (math.log(s / k) + (r + sig * sig / 2) * t) / (sig * math.sqrt(t))
    d2 = d1 - sig * math.sqrt(t)
    if kind == "call":
        return s * ncdf(d1) - k * math.exp(-r * t) * ncdf(d2)
    return k * math.exp(-r * t) * ncdf(-d2) - s * ncdf(-d1)


def bs_delta(kind: str, s: float, k: float, t: float, sig: float, r: float = RATE) -> float:
    if t <= 0:
        return (1.0 if s > k else 0.0) if kind == "call" else (-1.0 if s < k else 0.0)
    d1 = (math.log(s / k) + (r + sig * sig / 2) * t) / (sig * math.sqrt(t))
    return ncdf(d1) if kind == "call" else ncdf(d1) - 1


def _today_kst() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d")


def live_k200() -> dict | None:
    """장중 코스피200(reports/live.json K200F last·spot — 약 5~10분 간격, 1분봉 아님). 오늘 값이 아니면 None."""
    try:
        lj = json.loads((ROOT / "reports" / "live.json").read_text(encoding="utf-8"))
        if not str(lj.get("asof", "")).startswith(_today_kst()):
            return None
        it = next(x for x in lj.get("items", []) if x.get("key") == "K200F")
        if it.get("last") and it.get("spot"):
            return {"fut": float(it["last"]), "k200": float(it["spot"]), "asof": lj["asof"]}
    except Exception:  # noqa: BLE001
        return None
    return None


def live_kr_stock(code: str) -> tuple[str, float] | None:
    """장중 종목가(reports/heatmap_KR.json — 약 5~10분 간격). 오늘 값이 아니면 None."""
    try:
        h = json.loads((ROOT / "reports" / "heatmap_KR.json").read_text(encoding="utf-8"))
        if not str(h.get("asof", "")).startswith(_today_kst()):
            return None
        r = next((x for x in h.get("rows", []) if x.get("s") == code), None)
        return (h["asof"], float(r["close"])) if r and r.get("close") else None
    except Exception:  # noqa: BLE001
        return None


def deriv_last() -> dict:
    """코스피200·선물·IV — data/deriv/daily.csv 마지막 행, 오늘 장중이면 live.json 값으로 덮음(날짜 = 오늘)."""
    d = _deriv_close()
    lv = live_k200()
    if lv and _today_kst() > d["date"]:
        d.update(date=_today_kst(), k200=lv["k200"], fut=lv["fut"], live=lv["asof"])
    return d


def _deriv_close() -> dict:
    import csv
    rows = list(csv.DictReader(open(ROOT / "data" / "deriv" / "daily.csv", encoding="utf-8")))
    last = rows[-1]
    f = lambda k: float(last[k]) if last.get(k) not in (None, "") else None  # noqa: E731
    iv = f("atm_iv") or ((f("rep_iv") or 0) / 100 or None)
    if iv is None:
        iv = next(float(r["rep_iv"]) / 100 for r in reversed(rows) if r.get("rep_iv"))
    return {"date": last["date"], "k200": f("k200_close"), "fut": f("fut_close") or f("k200_close"), "iv": iv}


def bars(market: str, code: str) -> list[dict]:
    """종목 일봉 — reports/detail/{KR,US}/<코드>.json 차트 [{t,o,h,l,c,v}] (없으면 [])."""
    try:
        ch = json.loads((ROOT / "reports" / "detail" / market / f"{code}.json").read_text(encoding="utf-8")).get("chart") or []
    except Exception:  # noqa: BLE001
        return []
    return [b for b in ch if b.get("t") and b.get("c")]


def detail_name(market: str, code: str) -> str | None:
    try:
        return json.loads((ROOT / "reports" / "detail" / market / f"{code}.json").read_text(encoding="utf-8")).get("name")
    except Exception:  # noqa: BLE001
        return None


def stock_last(code: str) -> tuple[str, float, str]:
    lv = live_kr_stock(code)
    if lv:
        return _today_kst(), lv[1], detail_name("KR", code) or code
    bs_ = bars("KR", code)
    if not bs_:
        raise SystemExit(f"가격 없음: {code} (reports/detail/KR/{code}.json)")
    return bs_[-1]["t"][:10], float(bs_[-1]["c"]), detail_name("KR", code) or code


def live_us() -> dict | None:
    """미장 장중값 — reports/live.json SPX·NASDAQ·VIX·USDKRW(야후, 22:20 KST 미장 루프 약 5~10분). 항목 date = 미장 거래일."""
    try:
        lj = json.loads((ROOT / "reports" / "live.json").read_text(encoding="utf-8"))
        it = {x.get("key"): x for x in lj.get("items", [])}
        spx, ndx = it.get("SPX") or {}, it.get("NASDAQ") or {}
        if not (spx.get("last") and ndx.get("last") and spx.get("date")):
            return None
        out = {"date": spx["date"], "spx": float(spx["last"]), "ndx": float(ndx["last"]), "live": lj.get("asof")}
        if (it.get("VIX") or {}).get("last"):
            out["iv"] = float(it["VIX"]["last"]) / 100
        if (it.get("USDKRW") or {}).get("last"):
            out["usdkrw"] = float(it["USDKRW"]["last"])
        return out
    except Exception:  # noqa: BLE001
        return None


def us_last() -> dict:
    """미장 기준값 — reports/macro_series.json 마지막 봉, live.json 미장 값이 더 새 거래일이면 그걸로 덮음(10/23 — 장중 미장 반영)."""
    s = json.loads((ROOT / "reports" / "macro_series.json").read_text(encoding="utf-8"))["series"]
    c = lambda k: s[k][-1][4]  # noqa: E731
    d = {"date": s["SPX"][-1][0], "spx": c("SPX"), "ndx": c("NASDAQ"), "iv": c("VIX") / 100, "usdkrw": c("USDKRW")}
    lv = live_us()
    if lv and lv["date"] > d["date"]:
        d.update(lv)
    return d


def live_us_stock(t: str) -> tuple[str, float] | None:
    """미장 종목 장중가 — reports/heatmap_US.json(약 15분, 행 date = 미장 거래일)."""
    try:
        h = json.loads((ROOT / "reports" / "heatmap_US.json").read_text(encoding="utf-8"))
        r = next((x for x in h.get("rows", []) if x.get("s") == t), None)
        return (r["date"], float(r["close"])) if r and r.get("close") and r.get("date") else None
    except Exception:  # noqa: BLE001
        return None


def us_stock_last(t: str) -> tuple[str, float]:
    bs_ = bars("US", t)
    lv = live_us_stock(t)
    if lv and (not bs_ or lv[0] > bs_[-1]["t"][:10]):
        return lv
    if not bs_:
        raise SystemExit(f"가격 없음: {t} (reports/detail/US/{t}.json)")
    return bs_[-1]["t"][:10], float(bs_[-1]["c"])


def mkt(p: dict) -> str:
    return "US" if p["kind"] in US else "KR"


def last_bar(p: dict) -> dict | None:
    """주식은 차트 마지막 봉(o·c), 그 외 None(종가만)."""
    if p["kind"] in ("stock", "us_stock"):
        bs_ = bars(mkt(p), p["code"])
        return bs_[-1] if bs_ else None
    return None


def next_open(p: dict, after: str) -> tuple[str, float] | None:
    """after(포함하지 않음) 다음 첫 봉의 (날짜, 시가). 주식 = 상세 차트, es/nq = macro_series SPX·NASDAQ 시가. 그 외 None."""
    if p["kind"] in ("stock", "us_stock"):
        bs_ = [x for x in bars(mkt(p), p["code"]) if x["t"][:10] > after and x.get("o")]
        return (bs_[0]["t"][:10], float(bs_[0]["o"])) if bs_ else None
    if p["kind"] in ("es", "nq"):
        s = json.loads((ROOT / "reports" / "macro_series.json").read_text(encoding="utf-8"))["series"]["SPX" if p["kind"] == "es" else "NASDAQ"]
        xs = [x for x in s if x[0] > after]
        return (xs[0][0], float(xs[0][1])) if xs else None
    return None


def price(p: dict, d: dict) -> float:
    if p["kind"] in US:
        u = us_last()
        if p["kind"] == "us_stock":
            return us_stock_last(p["code"])[1]
        if p["kind"] in ("es", "nq"):
            return u["spx"] if p["kind"] == "es" else u["ndx"]
        t = (date.fromisoformat(p["expiry"]) - date.fromisoformat(u["date"])).days / 365
        return bs(p["kind"][4:], u["spx"], p["strike"], t, u["iv"])
    if p["kind"] == "stock":
        return stock_last(p["code"])[1]
    if p["kind"] == "fut":
        return d["fut"]
    t = (date.fromisoformat(p["expiry"]) - date.fromisoformat(d["date"])).days / 365
    return bs(p["kind"], d["k200"], p["strike"], t, d["iv"])


def load() -> dict:
    b = json.loads(STATE.read_text()) if STATE.exists() else {"v": 2, "note": "HF 재량 북 — 가상 1단위 모의, 실계좌 주문 아님. 옵션 가격 = BS 근사.", "open": [], "closed": []}
    b.setdefault("nav", [])
    b.setdefault("limits", {})
    return b


def save(b: dict):
    b["asof"] = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    STATE.write_text(json.dumps(b, ensure_ascii=False, indent=1))


def _open_ids(b: dict) -> set:
    return {p["id"] for p in b["open"]}


def counted_risk(p: dict, ids: set) -> float:
    """헤지 다리(부모가 열려 있음)는 순 리스크 0으로 본다."""
    par = p.get("hedge_of") or []
    return 0.0 if par and any(x in ids for x in par) else p["risk"]


def open_risk(b: dict) -> float:
    ids = _open_ids(b)
    return sum(counted_risk(p, ids) for p in b["open"]) + sum(x["risk"] for x in (b.get("baskets") or {}).get("open") or [])


def _basket():
    import hf_basket
    return hf_basket


# ── 변동성·유동성·S4 ─────────────────────────────────────────────
def _closes_for(kind: str, code: str | None) -> list[float]:
    if kind in ("stock", "us_stock"):
        return [float(x["c"]) for x in bars("KR" if kind == "stock" else "US", code)]
    try:
        if kind in ("fut", "put", "call"):
            import csv
            return [float(r["k200_close"]) for r in csv.DictReader(open(ROOT / "data" / "deriv" / "daily.csv", encoding="utf-8")) if r.get("k200_close")]
        s = json.loads((ROOT / "reports" / "macro_series.json").read_text(encoding="utf-8"))["series"]
        return [x[4] for x in s["SPX" if kind in ("es", "spx_put", "spx_call") else "NASDAQ"]]
    except Exception:  # noqa: BLE001
        return []


def daily_vol(kind: str, code: str | None, n: int = 20) -> float | None:
    c = _closes_for(kind, code)[-(n + 1):]
    if len(c) < n // 2:
        return None
    r = [math.log(c[i] / c[i - 1]) for i in range(1, len(c)) if c[i - 1] > 0 and c[i] > 0]
    if len(r) < 5:
        return None
    m = sum(r) / len(r)
    return (sum((x - m) ** 2 for x in r) / (len(r) - 1)) ** 0.5


def vol_factor(vol: float | None) -> float:
    return 1.0 if not vol else max(0.5, min(1.0, VOL_REF / vol))


def adv_krw(kind: str, code: str, usdkrw: float | None = None) -> float | None:
    """20일 평균 거래대금(원)."""
    bs_ = bars("KR" if kind == "stock" else "US", code)[-20:]
    if len(bs_) < 10:
        return None
    v = sum(float(x["c"]) * float(x.get("v") or 0) for x in bs_) / len(bs_)
    return v * (usdkrw or 1.0) if kind == "us_stock" else v


def s4_hit(code: str, lookback: int = 3) -> str | None:
    """국장 '거래량 ≥ 직전 20일 평균×3 + 종가 = 20일 최고' 신호가 최근 0~2일 안이면 그 날짜."""
    bs_ = bars("KR", code)
    for k in range(1, lookback + 1):
        if len(bs_) < 21 + k - 1:
            break
        i = len(bs_) - k
        prev = bs_[i - 20:i]
        v20 = sum(float(x.get("v") or 0) for x in prev) / 20
        hi = max(float(x["c"]) for x in bs_[i - 19:i + 1])
        if v20 > 0 and float(bs_[i].get("v") or 0) >= 3 * v20 and float(bs_[i]["c"]) >= hi:
            return bs_[i]["t"][:10]
    return None


def beta_of(kind: str, code: str | None, n: int = 60) -> float:
    """종목 60일 베타(국장 vs 코스피200, 미장 vs 나스닥 종합). 지수 상품 = 1(ES = SPX/나스닥 베타)."""
    if kind in ("fut", "put", "call", "nq", "spx_put", "spx_call"):
        return 1.0
    try:
        if kind == "stock":
            import csv
            idx = {r["date"]: float(r["k200_close"]) for r in csv.DictReader(open(ROOT / "data" / "deriv" / "daily.csv", encoding="utf-8")) if r.get("k200_close")}
            px = {x["t"][:10]: float(x["c"]) for x in bars("KR", code)}
        else:
            s = json.loads((ROOT / "reports" / "macro_series.json").read_text(encoding="utf-8"))["series"]
            idx = {x[0]: x[4] for x in s["NASDAQ"]}
            px = ({x[0]: x[4] for x in s["SPX"]} if kind == "es" else {x["t"][:10]: float(x["c"]) for x in bars("US", code)})
        ds = sorted(set(idx) & set(px))[-(n + 1):]
        if len(ds) < 30:
            return 1.0
        ra = [px[ds[i]] / px[ds[i - 1]] - 1 for i in range(1, len(ds))]
        ri = [idx[ds[i]] / idx[ds[i - 1]] - 1 for i in range(1, len(ds))]
        ma, mi = sum(ra) / len(ra), sum(ri) / len(ri)
        cov = sum((a - ma) * (b - mi) for a, b in zip(ra, ri)) / (len(ra) - 1)
        var = sum((b - mi) ** 2 for b in ri) / (len(ri) - 1)
        return round(cov / var, 2) if var > 0 else 1.0
    except Exception:  # noqa: BLE001
        return 1.0


# ── 진입 ──────────────────────────────────────────────────────
def checklist(a) -> dict:
    miss = [CHECK_KO[k] for k in CHECK if getattr(a, k, None) in (None, "")]
    if miss:
        raise SystemExit("체크리스트 빈 칸 — " + ", ".join(miss) + " (scripts/hf_book.py 머리말)")
    if not 0 < float(a.p_win) < 1:
        raise SystemExit("주관 승률은 0~1 사이")
    return {k: (float(getattr(a, k)) if k == "p_win" else getattr(a, k)) for k in CHECK}


def plan_math(rr: float, p: float) -> dict:
    return {"rr": round(rr, 2), "p_win": round(p, 3), "p_be": round(1 / (1 + rr), 3), "ev_r": round(p * rr - (1 - p), 3)}


def add(b: dict, a) -> dict:
    lim = b.get("limits") or {}
    if lim.get("halt_until") and lim["halt_until"] >= datetime.now(KST).strftime("%Y-%m-%d"):
        raise SystemExit(f"재량 북 정지 중(~{lim['halt_until']}) — {lim.get('why', '')}")
    if lim.get("ban_new"):
        raise SystemExit(f"신규 금지 — {lim.get('why', '북 손실 한도')}")
    if len(b["open"]) >= MAX_OPEN:
        raise SystemExit(f"동시 {MAX_OPEN}건 한도 — 하나 자르고 와")
    chk = checklist(a)
    conv = getattr(a, "conv", None) or "mid"
    if "주관" in str(chk["p_src"]):
        conv = "low"
    d = deriv_last()
    sgn = 1 if a.side == "롱" else -1
    ids = _open_ids(b)
    par = [x for x in (getattr(a, "hedge_of", None) or "").split(",") if x]
    if par and not all(x in ids for x in par):
        raise SystemExit(f"헤지 대상 id 가 열린 포지션에 없음: {par}")
    p = {"id": f"{d['date']}-{len(b['open']) + len(b['closed']) + 1}", "kind": a.kind, "side": a.side, "why": a.why, "src": a.src,
         "check": chk, "conv": conv, "hedge_of": par or None}
    if a.kind == "stock":
        if a.side == "롱":
            hit = s4_hit(a.code)
            if hit:
                raise SystemExit(f"추격 롱 금지 — {a.code} {hit} 거래량 3배+20일 신고가(S4: 10일 −1.3~−1.7%, reports/studies/2026-10-21_hf_desk_signals.md)")
        dt, px, nm = stock_last(a.code)
        p.update(code=a.code, name=a.name or nm, asof=dt, market="KR")
    elif a.kind == "fut":
        px = d["fut"]
        p.update(code="K200F", name="코스피200 선물", asof=d["date"], market="KR")
    elif a.kind == "us_stock":
        dt, px = us_stock_last(a.code)
        p.update(code=a.code, name=a.name or detail_name("US", a.code) or a.code, asof=dt, market="US")
    elif a.kind in ("es", "nq"):
        u = us_last()
        px = u["spx"] if a.kind == "es" else u["ndx"]
        p.update(code=a.kind.upper(), name="S&P500 선물(ES)" if a.kind == "es" else "나스닥 선물(NQ, 종합지수 근사)", asof=u["date"], market="US")
    elif a.kind in ("spx_put", "spx_call"):
        if a.side != "롱":
            raise SystemExit("옵션 매도는 금지 — 꼬리 위험 (reports/studies/2026-10-21_hf_ls_vol.md V1)")
        u = us_last()
        p.update(code="SPXO", name=f"S&P500 {'풋' if a.kind == 'spx_put' else '콜'} {a.strike:g} ({a.expiry})",
                 strike=a.strike, expiry=a.expiry, asof=u["date"], iv=round(u["iv"], 4), spot=u["spx"], market="US")
        px = price(p, d)
    else:
        if a.side != "롱":
            raise SystemExit("옵션 매도는 금지 — 국장 VRP ≈ 0 (reports/studies/2026-10-21_hf_ls_vol.md V1)")
        p.update(code="K200O", name=f"코스피200 {'풋' if a.kind == 'put' else '콜'} {a.strike:g} ({a.expiry})",
                 strike=a.strike, expiry=a.expiry, asof=d["date"], iv=round(d["iv"], 4), spot=d["k200"], market="KR")
        px = price(p, d)
    p["entry"] = round(px, 4)
    # 손익비·승률·기대값
    if a.kind in OPT:
        rr = 1.0                                       # 익절 = 프리미엄 2배, 최대손실 = 프리미엄
        t1 = round(px * 2, 4)
    else:
        if a.stop is None or (a.stop - px) * sgn >= 0:
            raise SystemExit("손절가 없거나 방향이 틀림 — 손절 없는 계획은 안 받아")
        if a.t1 is None or (a.t1 - px) * sgn <= 0:
            raise SystemExit("1차 목표 없거나 방향이 틀림 — 손익비를 못 잰다")
        rr = abs(a.t1 - px) / abs(px - a.stop)
        t1 = a.t1
    pm = plan_math(rr, chk["p_win"])
    pm["p_src"] = chk["p_src"]
    if pm["ev_r"] <= 0 and not par:
        raise SystemExit(f"기대값 {pm['ev_r']:+.2f}R ≤ 0 (R:R {pm['rr']:.2f}, 승률 {pm['p_win']:.0%} < 손익분기 {pm['p_be']:.0%}) — 안 들어간다")
    p["plan"] = pm
    # 크기
    vol = None if a.kind in OPT else daily_vol(a.kind, getattr(a, "code", None))
    vf = vol_factor(vol)
    room = RISK_ALL - open_risk(b)
    risk_t = CONV[conv] * vf
    if not par:
        risk_t = min(risk_t, getattr(a, "risk", None) or RISK_1, RISK_1, room)
        if risk_t <= 0:
            raise SystemExit(f"열린 리스크 합 {RISK_ALL * 100:.1f}% 한도 꽉 참")
    p["sizing"] = {"conv": conv, "risk_conv": CONV[conv], "daily_vol": round(vol, 4) if vol else None, "vol_factor": round(vf, 2)}
    if a.kind in OPT:
        w = risk_t
        p.update(stop=None, t1=t1, r_unit=px, weight=round(w, 5), risk=round(w, 5), hold=None)
    else:
        stop_pct = abs(px - a.stop) / px
        w = min(risk_t / stop_pct, 0.15)
        p.update(stop=a.stop, t1=t1, t2=a.t2, r_unit=abs(px - a.stop), hold=a.hold or HOLD[a.kind], stop_pct=round(stop_pct, 4))
        if a.kind in ("stock", "us_stock"):
            adv = adv_krw(a.kind, a.code, us_last()["usdkrw"] if a.kind == "us_stock" else None)
            if adv and AUM * w > LIQ_FRAC * adv:
                w2 = LIQ_FRAC * adv / AUM
                p["sizing"]["liq_cut"] = f"명목 {AUM * w / 1e8:,.0f}억 > 20일 평균 거래대금 10% {LIQ_FRAC * adv / 1e8:,.0f}억 → {w * 100:.2f}%→{w2 * 100:.2f}%"
                w = w2
        if par:                                       # 헤지 다리 = 부모 베타가중 명목(리스크 기준 크기 무시), --risk 로 지정 시 그 명목 상한 1.5배
            pw = sum(x["weight"] * abs(x.get("beta") or 1.0) for x in b["open"] if x["id"] in par)
            w = min(w, 1.5 * pw) if getattr(a, "risk", None) else pw
            p["sizing"]["hedge"] = f"부모 베타가중 명목 {pw * 100:.2f}%"
        p.update(weight=round(w, 4), risk=round(w * stop_pct, 5))
    p["beta"] = beta_of(a.kind, getattr(a, "code", None))
    p["days"] = 0
    p["last"] = p["entry"]
    b["open"].append(p)
    return p


def r_of(p: dict, px: float) -> float:
    sgn = 1 if p["side"] == "롱" else -1
    return (px - p["entry"]) * sgn / p["r_unit"] - COST[p["kind"]] * p["entry"] / p["r_unit"]


def pnl_book(p: dict, px: float | None = None) -> float:
    """장부 대비 손익(소수) = R × 리스크."""
    return r_of(p, p["last"] if px is None else px) * p["risk"]


def _idx_ret(market: str, d0: str, d1: str) -> float | None:
    try:
        if market == "KR":
            import csv
            s = {r["date"]: float(r["k200_close"]) for r in csv.DictReader(open(ROOT / "data" / "deriv" / "daily.csv", encoding="utf-8")) if r.get("k200_close")}
        else:
            s = {x[0]: x[4] for x in json.loads((ROOT / "reports" / "macro_series.json").read_text(encoding="utf-8"))["series"]["NASDAQ"]}
        if d1 not in s:                              # 청산일 지수 종가가 아직 없으면 귀속 보류(0으로 잡으면 전부 알파로 오기록)
            return None
        a = [v for k, v in sorted(s.items()) if k <= d0]
        return s[d1] / a[-1] - 1 if a else None
    except Exception:  # noqa: BLE001
        return None


def close_pos(b: dict, p: dict, px: float, d: str, why: str):
    sgn = 1 if p["side"] == "롱" else -1
    p.update(exit=round(px, 4), exit_d=d, exit_why=why, r=round(r_of(p, px), 3))
    if p["kind"] not in OPT:
        ar = px / p["entry"] - 1
        ir = ar if p["kind"] in ("fut", "es", "nq") else _idx_ret(mkt(p), p.get("asof", d), d)   # 지수 선물 = 전부 베타
        if ir is not None:
            be = p.get("beta") or 1.0
            p["attr"] = {"asset_ret": round(ar, 4), "idx_ret": round(ir, 4), "beta": be,
                         "alpha_book": round(sgn * (ar - be * ir) * p["weight"], 5), "beta_book": round(sgn * be * ir * p["weight"], 5)}
    if p.get("plan"):
        o = 1.0 if p["r"] > 0 else 0.0
        p["plan"]["brier"] = round((p["plan"]["p_win"] - o) ** 2, 4)
    b["closed"].append(p)


def book_limits(b: dict, today: str) -> dict:
    """장부 손익 곡선(nav: 거래일별 마지막 값) → 고점 대비·5거래일 손실로 한도 판정."""
    bk = b.get("baskets") or {}
    pnl = (sum(x["r"] * x["risk"] for x in b["closed"]) + sum(pnl_book(x) for x in b["open"])
           + sum(x["pnl"] for x in (bk.get("open") or []) + (bk.get("closed") or [])))       # 바스켓(hf_basket) 손익 포함
    nav = [x for x in b["nav"] if x["d"] != today] + [{"d": today, "pnl": round(pnl, 5)}]
    b["nav"] = nav[-400:]
    peak = max(0.0, max(x["pnl"] for x in nav))
    dd = pnl - peak
    wk = pnl - (nav[-6]["pnl"] if len(nav) >= 6 else 0.0)
    lim = {"pnl": round(pnl, 5), "peak": round(peak, 5), "dd": round(dd, 5), "week": round(wk, 5), "ban_new": False, "why": None,
           "halt_until": (b.get("limits") or {}).get("halt_until")}
    if dd <= DD_FLAT:
        lim.update(ban_new=True, why=f"고점 대비 {dd * 100:+.2f}% ≤ −5% — 전량 정리·{HALT_DAYS}일 정지",
                   halt_until=(date.fromisoformat(today) + timedelta(days=HALT_DAYS)).isoformat(), flat=True)
    elif dd <= DD_BAN:
        lim.update(ban_new=True, why=f"고점 대비 {dd * 100:+.2f}% ≤ −3% — 신규 금지, 총노출 절반 권고")
    elif wk <= WEEK_BAN:
        lim.update(ban_new=True, why=f"5거래일 {wk * 100:+.2f}% ≤ −2% — 신규 금지")
    b["limits"] = lim
    return lim


def mark(b: dict) -> list[dict]:
    d = deriv_last()
    out, keep = [], []
    if (b.get("baskets") or {}).get("open"):
        out += _basket().mark(b)
    for p in b["open"]:
        px = price(p, d)
        p["last"] = round(px, 4)
        md = us_last()["date"] if p["kind"] in US else d["date"]
        if md != p.get("mark_d", p.get("asof")):     # 보유일 = 거래일 수(회의 횟수 아님)
            p["days"] += 1
            p["mark_d"] = md
        sgn = 1 if p["side"] == "롱" else -1
        why, fill = None, px
        xo = p.get("exit_next_open")                 # 사전 결정: 결정일 이후 첫 봉 시가에 청산
        if xo:
            ob = next_open(p, xo["after"])
            if ob:
                close_pos(b, p, ob[1], ob[0], "사전 결정 시가 청산 — " + xo["why"])
                out.append(p)
                continue
            keep.append(p)
            continue
        if p["kind"] in OPT:
            if md >= p["expiry"]:
                why = "만기"
            elif px >= p["t1"]:
                why = "프리미엄 2배 — 전량 익절(재량 북 단순화)"
        else:
            bar = last_bar(p)
            gap = bar is not None and bar["t"][:10] == md and md != p.get("asof") and (float(bar["o"]) - p["stop"]) * sgn <= 0
            if gap:
                why, fill = "손절 — 갭(시가가 이미 손절 밖) → 시가 체결", float(bar["o"])
            elif (px - p["stop"]) * sgn <= 0:
                why = "손절 — 묻지도 따지지도 않음"
            elif p.get("t1") and (px - p["t1"]) * sgn >= 0:
                why = "1차 목표"
            elif p["days"] >= p["hold"]:
                why = "시간 손절"
        if why:
            close_pos(b, p, fill, md, why)
            out.append(p)
        else:
            keep.append(p)
    b["open"] = keep
    today = datetime.now(KST).strftime("%Y-%m-%d")
    lim = book_limits(b, today)
    if lim.get("flat") and b["open"]:
        for p in list(b["open"]):
            md = us_last()["date"] if p["kind"] in US else d["date"]
            close_pos(b, p, p["last"], md, "북 손실 한도 −5% — 전량 정리")
            out.append(p)
        b["open"] = []
    if lim.get("flat") and (b.get("baskets") or {}).get("open"):
        out += _basket().close_all(b, "북 손실 한도 −5% — 전량 정리")
    return out


def qty(p: dict) -> str:
    """가상 AUM 기준 수량 — 선물·옵션 계약, 주식 주."""
    notional = AUM * p["weight"]
    if p["kind"] in US:
        usd = notional / us_last()["usdkrw"]
        if p["kind"] == "us_stock":
            return f"{usd / p['entry']:,.0f}주"
        return f"{usd / (p['entry'] * US_MULT[p['kind']]):,.0f}계약"
    if p["kind"] == "stock":
        return f"{notional / p['entry']:,.0f}주"
    return f"{notional / (p['entry'] * MULT):,.0f}계약"


def perf_lines(b: dict) -> list[str]:
    cl = b["closed"]
    if not cl:
        return []
    ls = []
    for nm, sel in (("롱", lambda x: x["side"] == "롱"), ("숏", lambda x: x["side"] == "숏"),
                    ("국장", lambda x: mkt(x) == "KR"), ("미장", lambda x: mkt(x) == "US")):
        xs = [x["r"] for x in cl if sel(x)]
        if not xs:
            continue
        w = [r for r in xs if r > 0]
        lo = [r for r in xs if r <= 0]
        slug = (sum(w) / len(w)) / abs(sum(lo) / len(lo)) if w and lo and sum(lo) else None
        ls.append(f"{nm} {len(xs)}건 적중 {len(w)}/{len(xs)} 평균 {sum(xs) / len(xs):+.2f}R" + (f" 손익비(평균 이익/평균 손실) {slug:.2f}" if slug else ""))
    at = [x["attr"] for x in cl if x.get("attr")]
    if at:
        ls.append(f"귀속: 알파 {sum(x['alpha_book'] for x in at) * 100:+.3f}% · 베타 {sum(x['beta_book'] for x in at) * 100:+.3f}% (장부 대비, {len(at)}건)")
    br = [x["plan"]["brier"] for x in cl if (x.get("plan") or {}).get("brier") is not None]
    if br:
        bk = {}
        for x in cl:
            pl = x.get("plan") or {}
            if pl.get("brier") is None:
                continue
            k = "<40%" if pl["p_win"] < 0.4 else ("40~60%" if pl["p_win"] <= 0.6 else ">60%")
            bk.setdefault(k, []).append(1 if x["r"] > 0 else 0)
        ls.append(f"승률 보정: Brier {sum(br) / len(br):.3f}(n={len(br)}, 0.25 = 동전) · " + " · ".join(f"{k} 적중 {sum(v)}/{len(v)}" for k, v in sorted(bk.items())))
    return ["성과: " + " | ".join(ls)]


def show(b: dict) -> list[str]:
    d = deriv_last()
    lim = b.get("limits") or {}
    util = open_risk(b) / RISK_ALL
    nbk = len((b.get("baskets") or {}).get("open") or [])
    ls = [f"재량 북: 열린 {len(b['open'])}건" + (f" + 바스켓 {nbk}" if nbk else "") + f" · 열린 리스크(헤지 순) {open_risk(b) * 100:.2f}% (한도 {RISK_ALL * 100:.2f}%, 가동률 {util:.0%}) · 청산 {len(b['closed'])}건"
          + (f" · 평균 {sum(x['r'] for x in b['closed']) / len(b['closed']):+.2f}R · 적중 {sum(x['r'] > 0 for x in b['closed'])}/{len(b['closed'])}" if b["closed"] else "")
          + (f" · 손익 {lim['pnl'] * 100:+.3f}% (고점 대비 {lim['dd'] * 100:+.3f}%)" if lim.get("pnl") is not None else "")]
    if util < UTIL_MIN and not lim.get("ban_new"):
        ls.append(f"⚠️ 가동률 {util:.0%} < {UTIL_MIN:.0%} — 이번 회의에서 롱·숏 양쪽 아이디어로 E[R] > 0 포지션을 채우거나 '없음 이유'를 기록(쉬는 건 자리 값 못 함)")
    if lim.get("ban_new") or lim.get("halt_until"):
        ls.append(f"⛔ 한도: {lim.get('why') or ''}" + (f" · 정지 ~{lim['halt_until']}" if lim.get("halt_until") else ""))
    for p in b["open"]:
        cur = r_of(p, p["last"])
        lv = f"손절 {p['stop']:,.2f} · 1차 {p['t1']:,.2f}" if p["stop"] is not None else f"최대손실 = 프리미엄 · 익절 {p['t1']:,.2f}"
        pl = p.get("plan") or {}
        pm = f" · R:R {pl['rr']:.2f} 승률 {pl['p_win']:.0%}(손익분기 {pl['p_be']:.0%}) E[R] {pl['ev_r']:+.2f}" if pl.get("rr") is not None else ""
        hg = f" · 헤지({','.join(p['hedge_of'])})" if p.get("hedge_of") else ""
        ck = p.get("check") or {}
        kl = f" · 논지 붕괴: {ck['kill']}" if ck.get("kill") else ""
        ct = f" · 촉매 {ck['catalyst']}" if ck.get("catalyst") else ""
        ls.append(f"- {p['side']} {p['name']} 진입 {p['entry']:,.2f} → {p['last']:,.2f} ({cur:+.2f}R) · {lv} · 크기 {p['weight'] * 100:.2f}% ({qty(p)}){pm}{hg}{ct}{kl} · 근거: {p['why']}")
    if b.get("baskets"):
        ls += _basket().lines(b)
    for p in b["closed"][-3:]:
        ls.append(f"- 청산 {p['side']} {p['name']} {p['r']:+.2f}R ({p['exit_why']}, {p['exit_d']})")
    ls += perf_lines(b)
    try:
        import hf_risk
        ls += hf_risk.report_lines(b)
    except Exception as e:  # noqa: BLE001
        ls.append(f"(위험 보고 실패: {type(e).__name__}: {e})")
    ls.append(f"(가격 기준 KR {d['date']} · US {us_last()['date']} · 옵션 = BS 근사 · 가상 AUM {AUM / 1e8:,.0f}억 · 모의)")
    return ls


def main(argv=None):
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    a1 = sp.add_parser("add")
    a1.add_argument("--kind", choices=["stock", "fut", "put", "call", "us_stock", "es", "nq", "spx_put", "spx_call"], required=True)
    a1.add_argument("--side", choices=["롱", "숏"], default="롱")
    a1.add_argument("--code")
    a1.add_argument("--name")
    a1.add_argument("--stop", type=float)
    a1.add_argument("--t1", type=float)
    a1.add_argument("--t2", type=float)
    a1.add_argument("--strike", type=float)
    a1.add_argument("--expiry")
    a1.add_argument("--hold", type=int)
    a1.add_argument("--risk", type=float)
    a1.add_argument("--conv", choices=list(CONV), default="mid")
    a1.add_argument("--hedge-of", dest="hedge_of", help="헤지 대상 포지션 id(쉼표 구분)")
    for k in CHECK:
        a1.add_argument("--" + k.replace("_", "-"), dest=k, type=float if k == "p_win" else str)
    a1.add_argument("--why", required=True)
    a1.add_argument("--src", required=True)
    a2 = sp.add_parser("exit-open", help="다음 봉 시가 청산 예약(주식·es·nq)")
    a2.add_argument("--id", required=True)
    a2.add_argument("--after", required=True, help="이 날짜(시장 현지 거래일) 다음 첫 봉")
    a2.add_argument("--why", required=True)
    a3 = sp.add_parser("close-now", help="장중 수동 청산(재량) — 가격 근거 필수")
    a3.add_argument("--id", required=True)
    a3.add_argument("--px", type=float, required=True)
    a3.add_argument("--d", required=True)
    a3.add_argument("--why", required=True)
    sp.add_parser("mark")
    sp.add_parser("show")
    a = ap.parse_args(argv)
    b = load()
    if a.cmd == "add":
        p = add(b, a)
        save(b)
        print(json.dumps(p, ensure_ascii=False))
    elif a.cmd == "exit-open":
        p = next(x for x in b["open"] if x["id"] == a.id)
        if next_open(p, a.after) is None and p["kind"] not in ("stock", "us_stock", "es", "nq"):
            raise SystemExit("시가 청산은 주식·es·nq 만 — 나머지는 close-now")
        p["exit_next_open"] = {"after": a.after, "why": a.why, "at": datetime.now(KST).strftime("%Y-%m-%d %H:%M")}
        save(b)
    elif a.cmd == "close-now":
        p = next(x for x in b["open"] if x["id"] == a.id)
        b["open"] = [x for x in b["open"] if x["id"] != a.id]
        close_pos(b, p, a.px, a.d, "장중 재량 청산 — " + a.why)
        book_limits(b, datetime.now(KST).strftime("%Y-%m-%d"))
        save(b)
        print(f"청산 {p['name']} {p['r']:+.2f}R")
    elif a.cmd == "mark":
        for p in mark(b):
            print(f"청산 {p['name']} {p['r']:+.2f}R — {p['exit_why']}")
        save(b)
    print("\n".join(show(b)))


if __name__ == "__main__":
    main()
