"""채권 화면 → reports/bonds.json (+ 일별 누적 reports/bonds_hist.json)

수집 (각 소스는 독립적으로 실패해도 됨 — 실패하면 이전 누적값을 그대로 씀, 상태는 json 의 sources 에 기록)
- 미국채 수익률 곡선: home.treasury.gov 일별 par yield CSV (올해 + 작년). 실패 시 야후 ^IRX/^FVX/^TNX/^TYX
- 한국 장외 채권수익률: KRX 정보데이터시스템 [14017] 개별추이 (국고 1~30년, 회사채 AA-·BBB-, CD) — pykrx 세션
- 채권 ETF: 야후 (TLT IEF SHY LQD HYG, 114260 KODEX 국고채3년, 148070 국고채10년) + 주식 지수(상관관계용)
- AI 인프라 신용 감시: 야후 (CRWV ORCL NBIS APLD IREN CORZ WULF CIFR + HYG JNK LQD BKLN IEF SHY + ^VIX) → 규칙 기반 신용 경보

파생: 장단기 금리차, 신용 스프레드, 한미 금리차, bp 변화, 듀레이션·볼록성·시나리오, 주식-채권 상관, 규칙 기반 해석.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import math
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .config import REPORT_DIR

log = logging.getLogger(__name__)
OUT = REPORT_DIR / "bonds.json"
HIST = REPORT_DIR / "bonds_hist.json"
KEEP_DAYS = 400
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}

US_TENORS = ["1M", "3M", "6M", "1Y", "2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y"]
US_YEARS = {"1M": 1 / 12, "3M": 0.25, "6M": 0.5, "1Y": 1, "2Y": 2, "3Y": 3, "5Y": 5, "7Y": 7, "10Y": 10, "20Y": 20, "30Y": 30}
TSY_COLS = {"1 Mo": "1M", "3 Mo": "3M", "6 Mo": "6M", "1 Yr": "1Y", "2 Yr": "2Y", "3 Yr": "3Y", "5 Yr": "5Y",
            "7 Yr": "7Y", "10 Yr": "10Y", "20 Yr": "20Y", "30 Yr": "30Y"}
YF_US = {"^IRX": "3M", "^FVX": "5Y", "^TNX": "10Y", "^TYX": "30Y"}
# KRX [14017] 장외 채권수익률 개별추이 코드
KR_CODES = {"1Y": "3006", "2Y": "3019", "3Y": "3000", "5Y": "3007", "10Y": "3013", "20Y": "3014", "30Y": "3017",
            "AA": "3009", "BBB": "3010", "CD": "4000"}
KR_YEARS = {"1Y": 1, "2Y": 2, "3Y": 3, "5Y": 5, "10Y": 10, "20Y": 20, "30Y": 30}

# ETF: (이름, 국가, 근사 듀레이션(년), 근사 만기수익률로 쓸 금리 필드, 역할)
ETFS = {
    "SHY": ("미국채 1-3년 (SHY)", "US", 1.9, "us_2Y", "단기 — 현금 대용, 금리 위험 작음"),
    "IEF": ("미국채 7-10년 (IEF)", "US", 7.5, "us_7Y", "중기 — 방어 + 금리 인하 시 차익"),
    "TLT": ("미국채 20년+ (TLT)", "US", 16.0, "us_20Y", "장기 — 금리 인하 베팅, 변동성 큼"),
    "LQD": ("미 투자등급 회사채 (LQD)", "US", 8.5, None, "수익 — 국채 + 신용 프리미엄"),
    "HYG": ("미 하이일드 (HYG)", "US", 3.5, None, "수익 — 주식과 비슷하게 움직임 (방어 아님)"),
    "114260.KS": ("KODEX 국고채3년", "KR", 2.8, "kr_3Y", "단기 — 원화 현금 대용"),
    "148070.KS": ("국고채10년 ETF (148070)", "KR", 8.0, "kr_10Y", "장기 — 원화 방어 + 금리 인하 차익"),
}
EQ = {"^GSPC": "SPX", "^KS11": "KOSPI"}

# AI 인프라 신용 감시 — 빚(하이일드·전환사채·리스)으로 데이터센터를 짓는 신용 민감 종목.
# CDS·개별 채권 가격은 무료 소스가 없어 '주가로 본 스트레스'(52주 고점 대비 낙폭, 20일 수익률, 20일 변동성)로 대신함.
AI_BASKET = {
    "CRWV": "CoreWeave (GPU 클라우드)",
    "ORCL": "Oracle (AI 데이터센터 증설)",
    "NBIS": "Nebius (GPU 클라우드)",
    "APLD": "Applied Digital (데이터센터)",
    "IREN": "IREN (채굴→AI 데이터센터)",
    "CORZ": "Core Scientific (채굴→AI 호스팅)",
    "WULF": "TeraWulf (채굴→AI 호스팅)",
    "CIFR": "Cipher Mining (채굴→AI 호스팅)",
}
CREDIT_ETFS = {
    "HYG": "미 하이일드 (HYG)",
    "JNK": "미 하이일드 (JNK)",
    "LQD": "미 투자등급 회사채 (LQD)",
    "BKLN": "레버리지론 (BKLN)",
    "IEF": "미국채 7-10년 (IEF)",
    "SHY": "미국채 1-3년 (SHY)",
}
LEVELS = ("정상", "주의", "경계")


# ───────────────────────── 공통 ─────────────────────────
def _f(x) -> float | None:
    try:
        v = float(str(x).replace(",", "").strip())
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def _load_json(p, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def _series(rows: list[dict], key: str) -> list[tuple[str, float]]:
    return [(r["date"], r[key]) for r in rows if r.get(key) is not None]


def _at(s: list[tuple[str, float]], days: int) -> float | None:
    """마지막 날짜에서 days 일 전(그 날 이전 가장 가까운 값)."""
    if not s:
        return None
    tgt = str(date.fromisoformat(s[-1][0]) - timedelta(days=days))
    v = None
    for d, x in s:
        if d <= tgt:
            v = x
        else:
            break
    return v


def _chg_bp(s: list[tuple[str, float]]) -> dict:
    if not s:
        return {}
    last = s[-1][1]
    bp = lambda a: None if a is None else round((last - a) * 100, 1)  # noqa: E731
    return {"v": round(last, 3), "date": s[-1][0], "d1": bp(s[-2][1] if len(s) > 1 else None),
            "w1": bp(_at(s, 7)), "m1": bp(_at(s, 30)), "y1": bp(_at(s, 365))}


# ───────────────────────── 미국채 ─────────────────────────
def parse_treasury_csv(text: str) -> dict[str, dict]:
    """재무부 CSV → {YYYY-MM-DD: {us_10Y: 4.1, ...}}"""
    out: dict[str, dict] = {}
    rd = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    for row in rd:
        ds = (row.get("Date") or "").strip()
        try:
            d = datetime.strptime(ds, "%m/%d/%Y").date() if "/" in ds else date.fromisoformat(ds)
        except ValueError:
            continue
        rec = {}
        for col, k in TSY_COLS.items():
            v = _f(row.get(col))
            if v is not None:
                rec["us_" + k] = v
        if rec:
            out[str(d)] = rec
    return out


def fetch_treasury() -> dict[str, dict]:
    import requests
    y = date.today().year
    out: dict[str, dict] = {}
    errs = []
    for yr in (y - 1, y):
        url = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/"
               f"{yr}/all?type=daily_treasury_yield_curve&field_tdr_date_value={yr}&page&_format=csv")
        try:
            r = requests.get(url, headers=UA, timeout=25)
            r.raise_for_status()
            out.update(parse_treasury_csv(r.text))
        except Exception as e:  # noqa: BLE001
            errs.append(f"{yr}: {type(e).__name__}: {str(e)[:150]}")
    if not out:
        raise RuntimeError("; ".join(errs) or "빈 응답")
    return out


def _yf_closes(tickers: list[str], period: str = "15mo") -> dict[str, dict[str, float]]:
    import yfinance as yf
    raw = yf.download(tickers, period=period, interval="1d", auto_adjust=True, group_by="ticker",
                      progress=False, threads=True, timeout=30)
    out = {}
    for t in tickers:
        try:
            s = (raw[t]["Close"] if len(tickers) > 1 else raw["Close"]).dropna()
            out[t] = {str(i.date()): float(v) for i, v in s.items() if float(v) > 0}
        except Exception:  # noqa: BLE001
            out[t] = {}
    return out


def fetch_us_yf() -> dict[str, dict]:
    c = _yf_closes(list(YF_US))
    out: dict[str, dict] = {}
    for t, k in YF_US.items():
        for d, v in c.get(t, {}).items():
            out.setdefault(d, {})["us_" + k] = round(v, 3)
    if not out:
        raise RuntimeError("야후 금리 빈 응답")
    return out


# ───────────────────────── 한국 (KRX) ─────────────────────────
def parse_krx_rows(rows: list[dict]) -> dict[str, float]:
    """KRX 개별추이 output → {YYYY-MM-DD: 수익률}"""
    out = {}
    for r in rows or []:
        ds = str(r.get("DISCLS_DD") or r.get("TRD_DD") or "").strip().replace("/", "-")
        if len(ds) == 8 and ds.isdigit():
            ds = f"{ds[:4]}-{ds[4:6]}-{ds[6:]}"
        v = _f(r.get("LST_ORD_BAS_YD"))
        if len(ds) == 10 and v is not None and v > 0:
            out[ds] = v
    return out


def fetch_kr(start: date, end: date) -> dict[str, dict]:
    from .derivs import _io
    out: dict[str, dict] = {}
    errs = []
    for k, code in KR_CODES.items():
        a = start
        while a <= end:
            b = min(end, a + timedelta(days=120))
            try:
                rows = _io("dbms/MDC/STAT/standard/MDCSTAT11402", inqTpCd="E", strtDd=a.strftime("%Y%m%d"),
                           endDd=b.strftime("%Y%m%d"), bndKindTpCd=code)
                for d, v in parse_krx_rows(rows).items():
                    out.setdefault(d, {})["kr_" + k] = v
            except Exception as e:  # noqa: BLE001
                errs.append(f"{k} {a}: {type(e).__name__}: {str(e)[:120]}")
            a = b + timedelta(days=1)
            time.sleep(0.3)
    if not out:
        raise RuntimeError("; ".join(errs[:4]) or "빈 응답 (로그인/휴일?)")
    if errs:
        log.warning("KRX 채권 일부 실패: %s", errs[:3])
    return out


# ───────────────────────── 듀레이션 ─────────────────────────
def par_bond(y_pct: float, years: float, freq: int = 2) -> dict:
    """액면가(쿠폰=수익률) 채권의 수정 듀레이션·볼록성, 그리고 ±50/±100bp 가격 변화 (근사식 vs 재평가)."""
    y = y_pct / 100

    def price(yy: float) -> float:
        n = max(1, round(years * freq))
        cpn = y / freq
        r = yy / freq
        if years < 1:   # 1년 미만은 할인채처럼 (만기 일시 지급)
            return 1 / (1 + yy * years)
        return sum(cpn / (1 + r) ** i for i in range(1, n + 1)) + 1 / (1 + r) ** n
    h = 1e-4
    p0, pu, pd = price(y), price(y + h), price(y - h)
    D = (pd - pu) / (2 * h * p0)
    C = (pu + pd - 2 * p0) / (h * h * p0)
    sc = {}
    for bp in (-100, -50, 50, 100):
        dy = bp / 10000
        sc[str(bp)] = round((-D * dy + 0.5 * C * dy * dy) * 100, 2)
    return {"dur": round(D, 2), "conv": round(C, 1), "scen": sc,
            "carry": round(y_pct, 2), "be_bp": round(y_pct / D * 100) if D > 0 else None}


def dur_only(D: float, y_pct: float | None) -> dict:
    sc = {str(bp): round(-D * bp / 100, 2) for bp in (-100, -50, 50, 100)}
    return {"dur": D, "conv": None, "scen": sc, "carry": None if y_pct is None else round(y_pct, 2),
            "be_bp": None if not y_pct else round(y_pct / D * 100)}


def etf_rate_label(D: float | None, name: str | None = None) -> dict:
    """채권 ETF 공통 라벨 — 결재 #15 ③ '3년 국고채 ETF = 만기 없음·금리 민감'.
    상시 만기(constant maturity) ETF는 개별 채권과 달리 만기·pull-to-par 가 없어 '만기까지 들면 원금 회복'이 성립하지 않는다.
    rate_line = 수정 듀레이션 근사 한 줄: 금리 +100bp → 가격 ≈ −D%. (D 는 운용사 공시 실효 듀레이션 근처의 근사 상수, 114260 은 2.6~3.0 사이를 오간다)"""
    if D is None:
        return {"maturity": "없음(상시 듀레이션)", "rate_line": "듀레이션 미상 — 금리 민감도 계산 불가"}
    down = round(-D * 1.0, 1)          # +100bp
    down50 = round(-D * 0.5, 1)        # +50bp
    return {"maturity": "없음(상시 듀레이션) — 만기까지 들어도 원금 확정 없음",
            "rate_line": f"금리 +100bp → 가격 약 {down:+.1f}% (+50bp {down50:+.1f}%) · D≈{D:g} 근사 · 만기 없음"}


# ───────────────────────── 상관 ─────────────────────────
def _rets(px: dict[str, float]) -> dict[str, float]:
    ds = sorted(px)
    return {ds[i]: px[ds[i]] / px[ds[i - 1]] - 1 for i in range(1, len(ds)) if px[ds[i - 1]] > 0}


def corr(a: dict[str, float], b: dict[str, float], n: int = 250) -> tuple[float | None, int]:
    """두 가격 시계열의 일간 수익률 상관 (공통 날짜 최근 n일)."""
    ra, rb = _rets(a), _rets(b)
    ds = sorted(set(ra) & set(rb))[-n:]
    if len(ds) < 30:
        return None, len(ds)
    x = [ra[d] for d in ds]
    y = [rb[d] for d in ds]
    mx, my = sum(x) / len(x), sum(y) / len(y)
    sxy = sum((p - mx) * (q - my) for p, q in zip(x, y))
    sx = math.sqrt(sum((p - mx) ** 2 for p in x))
    sy = math.sqrt(sum((q - my) ** 2 for q in y))
    return (round(sxy / (sx * sy), 2) if sx and sy else None), len(ds)


def _ret(px: dict[str, float], days: int) -> float | None:
    if not px:
        return None
    ds = sorted(px)
    if days == 1:
        return px[ds[-1]] / px[ds[-2]] - 1 if len(ds) > 1 else None
    tgt = str(date.fromisoformat(ds[-1]) - timedelta(days=days))
    base = None
    for d in ds:
        if d <= tgt:
            base = px[d]
    return px[ds[-1]] / base - 1 if base else None


# ───────────────────────── 해석 ─────────────────────────
def _s(x, d=2):
    return "—" if x is None else f"{x:+.{d}f}" if d else f"{x:+.0f}"


def interpret(o: dict) -> list[str]:
    L = []
    sp, us, kr = o["spreads"], o["us"]["chg"], o["kr"]["chg"]
    s = sp.get("us_10_2") or {}
    if s.get("v") is not None:
        v = s["v"] * 100
        mn = s.get("min1y")
        u10, u2 = (us.get("10Y") or {}).get("m1"), (us.get("2Y") or {}).get("m1")
        if v < 0:
            L.append(f"미국 장단기 금리차 역전: 10Y−2Y {v:+.0f}bp — 단기 금리가 장기보다 높음 = 시장이 앞으로 금리 인하·경기 둔화를 예상.")
        elif mn is not None and mn < 0:
            L.append(f"미국 10Y−2Y {v:+.0f}bp — 1년 내 역전({mn * 100:+.0f}bp)에서 정상화. 역사적으로 경기 둔화는 '역전 해소 무렵' 나타난 경우가 많았음.")
        else:
            L.append(f"미국 10Y−2Y {v:+.0f}bp — 정상(우상향) 곡선.")
        m1 = s.get("m1")
        if m1 is not None and abs(m1) >= 10 and u10 is not None and u2 is not None:
            kind = ("베어 스티프닝(장기 금리가 더 오름 — 재정·인플레 우려형)" if m1 > 0 and u10 > 0 else
                    "불 스티프닝(단기 금리가 더 내림 — 금리 인하 기대형)" if m1 > 0 else
                    "베어 플래트닝(단기 금리가 더 오름 — 긴축 우려형)" if u2 > 0 else
                    "불 플래트닝(장기 금리가 더 내림 — 경기 둔화 우려형)")
            L.append(f"1개월 새 금리차 {m1:+.0f}bp: 2Y {u2:+.0f}bp, 10Y {u10:+.0f}bp → {kind}.")
    t10 = us.get("10Y") or {}
    if t10.get("v") is not None:
        m1 = t10.get("m1")
        nq = o.get("ctx", {}).get("nasdaq_m1")
        tail = f" 같은 기간 나스닥 {nq * 100:+.1f}%." if nq is not None else ""
        if t10["v"] >= 4.5 or (m1 or 0) >= 20:
            L.append(f"미 10년물 {t10['v']:.2f}% (1개월 {_s(m1, 0)}bp) — 높은 할인율은 이익이 먼 미래에 몰린 성장주·반도체 밸류에이션에 부담.{tail}")
        elif (m1 or 0) <= -20:
            L.append(f"미 10년물 {t10['v']:.2f}% (1개월 {_s(m1, 0)}bp) — 금리 하락은 성장주 밸류에이션에 우호적.{tail}")
        else:
            L.append(f"미 10년물 {t10['v']:.2f}% (1개월 {_s(m1, 0)}bp) — 큰 변화 없음.{tail}")
    hy = o.get("credit_us") or {}
    if hy.get("r20") is not None:
        r = hy["r20"]
        L.append(f"미국 신용(HYG/IEF 비율) 1개월 {r * 100:+.1f}% — " + (
            "하이일드가 국채보다 약함 = 위험 회피 신호." if r < -0.015 else
            "하이일드가 국채보다 강함 = 위험 선호." if r > 0.01 else "뚜렷한 신용 스트레스 없음.")
                 + (f" 단, AI 인프라 신용 감시는 '{ac['level']}' — 지수에 안 잡히는 업종 스트레스 (아래 섹션)."
                    if (ac := ((o.get("ai_credit") or {}).get("alert") or {})).get("lv", 0) >= 1 else ""))
    aa = sp.get("kr_aa") or {}
    if aa.get("v") is not None:
        m1 = aa.get("m1")
        tag = ("확대 — 회사 자금 조달 여건 악화(위험 회피)" if (m1 or 0) >= 10 else
               "축소 — 신용 여건 개선" if (m1 or 0) <= -10 else "안정")
        L.append(f"한국 회사채 AA−(3년) − 국고 3년 = {aa['v'] * 100:.0f}bp (1개월 {_s(m1, 0)}bp): {tag}.")
    k10 = kr.get("10Y") or {}
    g = sp.get("krus_10") or {}
    if g.get("v") is not None:
        fx = o.get("ctx", {}).get("usdkrw")
        L.append(f"한국 10년 {k10.get('v', 0):.2f}% − 미국 10년 = {g['v']:+.2f}%p (1개월 {_s(g.get('m1'), 0)}bp) — "
                 + ("한국 금리가 낮으면 달러 자산 매력↑ → 원화 약세 압력" if g["v"] < 0 else "한국 금리가 더 높아 원화엔 우호적")
                 + (f" (원/달러 {fx:,.0f})." if fx else "."))
    ks = sp.get("kr_10_3") or {}
    if ks.get("v") is not None:
        L.append(f"한국 10Y−3Y {ks['v'] * 100:+.0f}bp" + (" — 역전(경기 둔화·인하 기대)." if ks["v"] < 0 else " — 정상 곡선."))
    return L


def recommend(o: dict) -> list[str]:
    """포트폴리오 편입 관점 규칙 기반 한 줄 (사실·숫자 인용)."""
    out = []
    c = (o.get("corr") or {}).get("IEF_SPX") or {}
    cr = c.get("c250")
    s = ((o["spreads"].get("us_10_2") or {}).get("v"))
    u3 = ((o["us"]["chg"].get("3M") or {}).get("v"))
    u10 = ((o["us"]["chg"].get("10Y") or {}).get("v"))
    if cr is not None:
        if cr > 0.2:
            out.append(f"주식-채권 상관 +{cr:.2f}(IEF vs S&P500, 1년) — 2022년처럼 같이 빠지는 국면: 채권이 주식 하락을 막아주지 못함 → 장기채보다 단기채·현금 비중 우선.")
        elif cr < -0.2:
            out.append(f"주식-채권 상관 {cr:.2f} — 채권이 주식 하락의 완충 역할 중 → 중장기 국채가 분산 효과 있음.")
        else:
            out.append(f"주식-채권 상관 {cr:+.2f} — 거의 무관: 분산 효과는 '수익률 낮은 대신 덜 흔들림' 정도.")
    if s is not None and u3 is not None and u10 is not None:
        if s < 0 or u3 >= u10:
            out.append(f"곡선 역전/평탄(3M {u3:.2f}% vs 10Y {u10:.2f}%) — 단기물이 듀레이션 위험 없이 비슷하거나 더 높은 이자를 줌.")
        elif s * 100 >= 50:
            out.append(f"곡선 가파름(10Y−2Y {s * 100:+.0f}bp) — 장기물이 기간 프리미엄을 줌. 물가 둔화가 확인될 때 듀레이션 늘리기 유리.")
        else:
            out.append(f"곡선 완만(10Y−2Y {s * 100:+.0f}bp) — 듀레이션을 크게 늘릴 보상은 크지 않음 → 중기(5~10년) 중심 사다리식 분할.")
    hc = o.get("hedge_cost")
    if hc is not None:
        out.append(f"환헤지 비용 ≈ 미국 3M − 한국 CD = {hc:+.2f}%p/년 — " + (
            (f"헤지하면 미국 10년물 이자({u10:.2f}%)의 약 {hc / u10:.0%}를 비용으로 냄. 비헤지는 환율이 수익을 좌우." if u10 else "헤지 비용 큼.") if hc > 1 else
            "헤지 비용 부담 작음." if hc >= 0 else "헤지 시 오히려 이득(한국 단기금리가 더 높음)."))
    return out


# ───────────────────────── 채권 읽는 법 ─────────────────────────
def guide(o: dict) -> list[dict]:
    us, kr = o["us"]["chg"], o["kr"]["chg"]
    g = lambda d, k: (d.get(k) or {}).get("v")  # noqa: E731
    u10, u2, u3m, k10, k3 = g(us, "10Y"), g(us, "2Y"), g(us, "3M"), g(kr, "10Y"), g(kr, "3Y")
    aa = g(kr, "AA")
    fx = o.get("ctx", {}).get("usdkrw")
    out = []
    if u10:
        p = par_bond(u10, 10)
        out.append({"t": "금리와 가격은 반대로 움직인다",
                    "b": f"채권은 이자가 미리 정해져 있어서, 시장 금리가 오르면 '이미 산 낮은 이자 채권'의 가치가 떨어진다. "
                         f"지금 미국 10년물({u10:.2f}%)은 금리가 +1%p 오르면 가격이 약 {p['scen']['100']:.1f}%, "
                         f"−1%p 내리면 약 +{p['scen']['-100']:.1f}% 움직인다(내릴 때 이익이 오를 때 손실보다 조금 큰 것이 '볼록성'). "
                         f"금리가 낮을수록 같은 10년물도 더 민감하다(금리 3%일 때 +1%p → 약 {par_bond(3.0, 10)['scen']['100']:.1f}%)."})
        out.append({"t": "듀레이션 = 금리 민감도(년)",
                    "b": f"듀레이션 D 는 '금리 1%p 변화당 가격 변화 %'로 읽으면 된다. 미국 10년물 D≈{p['dur']:.1f}, "
                         f"2년물 D≈{par_bond(u2, 2)['dur']:.1f}" + (f", 30년물 D≈{par_bond(g(us, '30Y'), 30)['dur']:.1f}" if g(us, "30Y") else "") +
                         ". 만기가 길수록, 이자가 낮을수록 D가 커진다. "
                         f"손익분기: 1년 이자({u10:.2f}%) ÷ D = 금리가 1년간 약 {p['be_bp']}bp 이상 오르면 이자를 받고도 손실."})
    if u2 is not None and u10 is not None:
        out.append({"t": "장단기 금리차와 역전",
                    "b": f"보통은 오래 빌려줄수록 이자가 높아 곡선이 우상향한다. 지금 미국 2년 {u2:.2f}%, 10년 {u10:.2f}% (차이 {(u10 - u2) * 100:+.0f}bp)"
                         + (f", 3개월 {u3m:.2f}%" if u3m else "") + ". "
                         "단기 금리가 장기보다 높아지는 '역전'은 시장이 '곧 경기가 식어 금리를 내릴 것'이라고 보는 신호로, "
                         "미국은 2022년 7월~2024년 9월 2년 넘게 역전됐었다. 역전 자체보다 역전이 풀리는 시점(대개 단기 금리 급락)에 경기 둔화가 겹친 경우가 많다."})
    if aa is not None and k3 is not None:
        out.append({"t": "신용 스프레드 = 떼일 위험의 값",
                    "b": f"회사채는 국채보다 이자를 더 준다. 한국 회사채 AA−(3년) {aa:.2f}% vs 국고 3년 {k3:.2f}% → 차이 {(aa - k3) * 100:.0f}bp 가 신용 위험 보상. "
                         "경기가 나빠질 것 같으면 투자자들이 회사채를 팔아 이 차이가 벌어진다(위험 회피). 하이일드(투기등급)는 주식처럼 움직여 주식 하락 방어용이 아니다."})
    out.append({"t": "국채 vs 회사채",
                "b": "국채: 정부가 갚으니 떼일 위험이 사실상 없음 → 주식이 급락할 때 '안전자산'으로 오르는 경우가 많다(단, 물가가 문제일 땐 같이 빠짐 — 2022년). "
                     "회사채: 이자가 더 높지만 경기 침체 땐 가격이 빠짐 → '수익' 자산이지 '방어' 자산이 아니다."})
    if k10 is not None and u10 is not None:
        out.append({"t": "한국 금리와 환율",
                    "b": f"한국 10년 {k10:.2f}% vs 미국 10년 {u10:.2f}% ({k10 - u10:+.2f}%p). 미국 금리가 더 높으면 돈이 달러 쪽으로 가려는 힘이 생겨 원화 약세 압력이 된다"
                         + (f" (지금 원/달러 {fx:,.0f}원)." if fx else ".") + " 다만 환율은 무역·위험 심리도 크게 작용해 금리차만으로 정해지지 않는다."})
    fxx = ""
    if fx:
        fxx = f" 예: 미국채에서 +5% 벌어도 원/달러가 10% 내리면({fx:,.0f}→{fx * 0.9:,.0f}) 원화 기준 약 −5.5%."
    out.append({"t": "사는 방법",
                "b": "① 국내 국채 ETF(예: KODEX 국고채3년 114260, 국고채10년 ETF 148070) — 주식처럼 사고팔고, 분배금은 배당소득세 15.4%. "
                     "② 개인투자용 국채 — 정부가 개인에게 직접 파는 10·20년물(5년물도 추가), 미래에셋증권에서 매달 청약, 만기까지 들고 있어야 가산금리·복리·분리과세 혜택(세부 조건은 매달 공고 확인). "
                     "③ 미국채 ETF(SHY·IEF·TLT 또는 국내 상장 미국채 ETF) — 달러 자산이라 환율 위험이 붙는다. 국내 상장 '(H)' 표시는 환헤지형." + fxx +
                     " 미국 상장 ETF 매매차익은 연 250만원 초과분 22% 양도세."})
    return out


def vehicles(o: dict) -> list[dict]:
    """포트폴리오 편입 후보 비교 (일반적 세금 메모는 간략·일반론)."""
    us, kr = o["us"]["chg"], o["kr"]["chg"]
    g = lambda d, k: (d.get(k) or {}).get("v")  # noqa: E731
    hc = o.get("hedge_cost")
    E = {e["s"]: e for e in o.get("etf", [])}
    rows = []

    def add(name, y, D, fx, tax, role, ylabel="", up100=None, maturity=None):
        is_etf = up100 != ""   # 개인투자용 국채(시가 평가 없음)는 up100="" 로 들어온다
        lab = etf_rate_label(D, name) if is_etf else {"maturity": maturity or "있음 — 만기 보유 시 원금·이자 확정(시가 평가 없음)", "rate_line": "중도 환매 전까지 가격 변동 없음(만기 보유 전제)"}
        rows.append({"name": name, "y": None if y is None else round(y, 2), "ylabel": ylabel, "dur": D,
                     "up100": (None if up100 == "" else up100) if up100 is not None else (None if D is None else round(D, 1)),   # −1%p 시 가격 변화 %
                     "fx": fx, "tax": tax, "role": role, **lab})
    k3, k10, k20 = g(kr, "3Y"), g(kr, "10Y"), g(kr, "20Y")
    add("KR 국고채 3년 ETF", k3, (E.get("114260.KS") or {}).get("dur", 2.8), "없음", "분배금 배당소득세 15.4%", "방어 · 현금 대용")
    add("KR 국고채 10년 ETF", k10, (E.get("148070.KS") or {}).get("dur", 8.0), "없음", "분배금 배당소득세 15.4%", "방어 + 금리 인하 베팅")
    if k10:
        add("개인투자용 국채 10년", k10, 10.0, "없음", "만기 보유 시 분리과세(한도 내)·가산금리",
            "만기 일시 지급(복리) — 시가 평가 없음: 금리가 내려도 차익 없고, 올라도 만기 보유 시 확정 이자", "≈국고10년+가산", "", "있음(10년) — 만기 보유 시 원금·이자 확정")
    if k20:
        add("개인투자용 국채 20년", k20, 20.0, "없음", "만기 보유 시 분리과세(한도 내)·가산금리",
            "만기 일시 지급(복리) — 시가 평가 없음: 금리가 내려도 차익 없고, 올라도 만기 보유 시 확정 이자", "≈국고20년+가산", "", "있음(20년) — 만기 보유 시 원금·이자 확정")
    for s, fxl in (("SHY", "있음(비헤지)"), ("IEF", "있음(비헤지)"), ("TLT", "있음(비헤지)")):
        e = E.get(s) or {}
        add(e.get("n", s), e.get("y"), e.get("dur"), fxl, "미국 상장: 양도세 22%(연 250만원 초과)", e.get("role", ""), "해당 만기 국채금리")
    for s, lab in (("IEF", "미국채 7-10년 환헤지형(H)"), ("TLT", "미국채 20년+ 환헤지형(H)")):
        e = E.get(s) or {}
        y = e.get("y")
        add(lab, None if (y is None or hc is None) else y - hc, e.get("dur"), "헤지(비용 반영)", "국내 상장: 매매차익·분배금 배당소득세 15.4%",
            "환율 빼고 금리만 베팅", "금리 − 헤지비용")
    for s in ("LQD", "HYG"):
        e = E.get(s) or {}
        add(e.get("n", s), e.get("dy"), e.get("dur"), "있음(비헤지)", "미국 상장: 양도세 22%(연 250만원 초과)", e.get("role", ""), "분배수익률(12개월)")
    return rows


# ───────────────────────── AI 인프라 신용 감시 ─────────────────────────
def _tail_stats(px: dict[str, float]) -> dict | None:
    """가격 시계열 → 종가·52주 고점 대비 낙폭·20거래일 수익률·20일 실현변동성(연율)."""
    ds = sorted(px)
    if len(ds) < 25:
        return None
    v = [px[d] for d in ds]
    last = v[-1]
    hi = max(v[-252:])
    lr = [math.log(v[i] / v[i - 1]) for i in range(len(v) - 20, len(v)) if v[i - 1] > 0 and v[i] > 0]
    vol = None
    if len(lr) >= 10:
        m = sum(lr) / len(lr)
        vol = math.sqrt(sum((x - m) ** 2 for x in lr) / (len(lr) - 1)) * math.sqrt(252)
    return {"close": round(last, 2), "date": ds[-1], "hi52": round(hi, 2), "dd": round(last / hi - 1, 4),
            "r1": round(last / v[-2] - 1, 4), "r20": round(last / v[-21] - 1, 4),
            "vol20": None if vol is None else round(vol, 3), "n": len(v), "short": len(v) < 240}


def _ratio(a: dict[str, float], b: dict[str, float]) -> dict | None:
    ds = sorted(set(a) & set(b))
    if len(ds) < 61:
        return None
    r = [a[d] / b[d] for d in ds]
    return {"v": round(r[-1], 4), "r20": round(r[-1] / r[-21] - 1, 4), "r60": round(r[-1] / r[-61] - 1, 4),
            "hist": [[d, round(x, 4)] for d, x in zip(ds[-260:], r[-260:])]}


def _median(xs: list[float]) -> float | None:
    xs = sorted(xs)
    n = len(xs)
    if not n:
        return None
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def credit_alert(basket: list[dict], hy_m1: float | None, vix: float | None) -> dict:
    """규칙 기반 신용 경보. 항목별 0/1/2점, 합계 0~1 정상 · 2~3 주의 · 4+ 경계 (한 항목이라도 2점이면 최소 주의)."""
    med = _median([r["dd"] for r in basket if r.get("dd") is not None])
    crash = [r["s"] for r in basket if r.get("r20") is not None and r["r20"] < -0.20]
    nb = len(basket)

    def pts(x, t1, t2, low=True):
        if x is None:
            return 0
        if low:
            return 2 if x <= t2 else 1 if x <= t1 else 0
        return 2 if x >= t2 else 1 if x >= t1 else 0
    ch = [
        {"k": "basket_dd", "name": "바스켓 52주 고점 대비 낙폭 (중앙값)", "v": None if med is None else round(med, 4), "fmt": "pct",
         "rule": "−25% 이하 1점 · −40% 이하 2점", "pt": pts(med, -0.25, -0.40),
         "why": "AI 데이터센터 회사 주가가 고점에서 얼마나 빠졌나 — 많이 빠질수록 시장이 '빚 갚을 능력'을 의심한다는 뜻"},
        {"k": "crash_n", "name": "20일 새 −20% 넘게 빠진 종목 수", "v": len(crash), "fmt": "n", "of": nb, "names": crash,
         "rule": "2개 이상 1점 · 3개 이상 2점", "pt": 2 if len(crash) >= 3 else 1 if len(crash) >= 2 else 0,
         "why": "한 달 새 급락이 여러 종목에 번지면 개별 악재가 아니라 업종 전체의 돈줄 문제일 수 있음"},
        {"k": "hy_m1", "name": "하이일드 ETF(HYG) 1개월 수익률", "v": None if hy_m1 is None else round(hy_m1, 4), "fmt": "pct",
         "rule": "−1.5% 이하 1점 · −3% 이하 2점", "pt": pts(hy_m1, -0.015, -0.03),
         "why": "투기등급 회사채 전체 가격 — 이게 빠지면 스트레스가 업종을 넘어 신용시장 전반으로 번졌다는 뜻"},
        {"k": "vix", "name": "VIX (주식 공포지수)", "v": None if vix is None else round(vix, 2), "fmt": "num",
         "rule": "22 이상 1점 · 30 이상 2점", "pt": pts(vix, 22, 30, low=False),
         "why": "옵션 가격으로 본 시장 불안 — 높을수록 투자자들이 하락 보험을 비싸게 삼"},
    ]
    score = sum(c["pt"] for c in ch)
    lv = 2 if score >= 4 else 1 if score >= 2 else 0
    if lv == 0 and any(c["pt"] == 2 for c in ch):
        lv = 1
    level = LEVELS[lv]
    worst = sorted([r for r in basket if r.get("dd") is not None], key=lambda r: r["dd"])[:2]
    fp = lambda x: "—" if x is None else f"{x * 100:+.1f}%"  # noqa: E731
    line = (f"AI 인프라 신용 {level}: 바스켓 고점 대비 중앙값 {fp(med)}, 20일 −20%↓ {len(crash)}/{nb}종목"
            + (f"({', '.join(crash)})" if crash else "") + f", HYG 1M {fp(hy_m1)}, VIX {'—' if vix is None else f'{vix:.1f}'}"
            + (" · 최약 " + ", ".join(f"{r['s']} {r['dd'] * 100:+.0f}%" for r in worst) if worst else ""))
    if lv == 0:
        expl = "AI 데이터센터 업종 주가와 신용시장 모두 평소 범위 — 특별한 경고 없음."
    elif ch[2]["pt"] == 0 and ch[3]["pt"] == 0:
        expl = ("하이일드 지수·VIX는 조용한데 AI 데이터센터 업종만 아픔 — 지수 신용 지표(HYG/IEF)에 안 잡히는 '업종 국지 스트레스'. "
                "이 회사들은 빚으로 GPU·전력·건물을 사고 소수 고객(빅테크·AI 연구소)과의 계약으로 갚는 구조라, 자금 조달이 막히면 주가가 먼저 반응함.")
    else:
        expl = "업종 스트레스가 하이일드·변동성 지표까지 번지는 중 — 신용시장 전반의 위험 회피로 커질 수 있음."
    if lv == 2:
        expl += " 경계: AI 인프라 관련(반도체·전력 장비 포함) 비중과 레버리지를 점검할 구간."
    return {"level": level, "lv": lv, "score": score, "checks": ch, "line": line, "explain": expl}


def ai_credit(px: dict[str, dict[str, float]], vix_fallback: float | None = None) -> dict:
    """AI 인프라 바스켓·신용 ETF·비율·경보. 데이터 없는 티커는 missing 으로 빠짐."""
    basket, missing = [], []
    for t, n in AI_BASKET.items():
        st = _tail_stats(px.get(t) or {})
        if st is None:
            missing.append(t)
            continue
        basket.append({"s": t, **st, "n": n, "obs": st.get("n")})   # _tail_stats 의 n(관측 수)이 이름을 덮던 버그(화면 'CIFR 316') — 이름을 뒤에 둔다
    basket.sort(key=lambda r: r["dd"])
    etfs = []
    for t, n in CREDIT_ETFS.items():
        st = _tail_stats(px.get(t) or {})
        if st:
            etfs.append({"s": t, "n": n, **{k: st[k] for k in ("close", "date", "r1", "r20", "dd", "vol20")}})
    hyp = px.get("HYG") or {}
    hds = sorted(hyp)
    hy_m1 = round(hyp[hds[-1]] / hyp[hds[-22]] - 1, 4) if len(hds) > 22 else None
    vx = px.get("^VIX") or {}
    vix = vx[max(vx)] if vx else vix_fallback
    ratios = {}
    for k, (a, b) in {"HYG_IEF": ("HYG", "IEF"), "BKLN_SHY": ("BKLN", "SHY")}.items():
        r = _ratio(px.get(a) or {}, px.get(b) or {})
        if r:
            ratios[k] = r
    return {"asof": max((r["date"] for r in basket), default=None), "basket": basket, "missing": missing,
            "kept": [r["s"] for r in basket], "etf": etfs, "ratios": ratios, "hy_m1": hy_m1,
            "vix": None if vix is None else round(vix, 2),
            "vix_src": "yahoo ^VIX" if vx else ("macro_series" if vix_fallback is not None else None),
            "alert": credit_alert(basket, hy_m1, vix)}


# ───────────────────────── 빌드 ─────────────────────────
def _merge(hist: dict[str, dict], new: dict[str, dict]) -> None:
    for d, rec in new.items():
        hist.setdefault(d, {}).update(rec)


def _stale(o: dict, block: str, got) -> None:
    """조용한 대체 금지(10/17): 이전 실행 값을 쓴 블록은 o['stale'][block] 로 표시 + reports/freshness.json 기록."""
    o.setdefault("stale", {})[block] = {"want": o.get("asof"), "got": got}
    try:
        from .guard import record_stale
        record_stale("reports/bonds.json", block, o.get("asof"), got)
    except Exception:  # noqa: BLE001
        pass


def build() -> dict:
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    H = _load_json(HIST, {"rows": []})
    hist = {r["date"]: {k: v for k, v in r.items() if k != "date"} for r in H.get("rows", [])}
    src: dict[str, str] = {}

    # 1) 미국채
    try:
        t = fetch_treasury()
        _merge(hist, t)
        src["us_treasury"] = f"ok {len(t)}일 (마지막 {max(t)})"
    except Exception as e:  # noqa: BLE001
        src["us_treasury"] = f"실패: {type(e).__name__}: {str(e)[:300]}"
        log.warning("미국채 CSV 실패: %s", e)
        try:
            y = fetch_us_yf()
            for d, rec in y.items():   # 재무부 값이 있으면 덮지 않음
                cur = hist.setdefault(d, {})
                for k, v in rec.items():
                    cur.setdefault(k, v)
            src["us_yahoo"] = f"ok {len(y)}일 (3M·5Y·10Y·30Y만)"
        except Exception as e2:  # noqa: BLE001
            src["us_yahoo"] = f"실패: {type(e2).__name__}: {str(e2)[:200]}"

    # 2) 한국 (KRX) — 누적이 충분하면 최근 15일만
    today = date.today()
    kr_dates = sorted(d for d, r in hist.items() if r.get("kr_3Y") is not None)
    start = (date.fromisoformat(kr_dates[-1]) - timedelta(days=15)) if len(kr_dates) >= 150 else today - timedelta(days=KEEP_DAYS)
    try:
        k = fetch_kr(start, today)
        _merge(hist, k)
        src["kr_krx"] = f"ok {len(k)}일 ({start}~, 마지막 {max(k)})"
    except Exception as e:  # noqa: BLE001
        src["kr_krx"] = f"실패: {type(e).__name__}: {str(e)[:300]}"
        log.warning("KRX 채권 실패: %s", e)

    cut = str(today - timedelta(days=KEEP_DAYS))
    rows = [{"date": d, **hist[d]} for d in sorted(hist) if d >= cut and hist[d]]
    HIST.write_text(json.dumps({"rows": rows}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    # 3) ETF + 주가지수
    px: dict[str, dict[str, float]] = {}
    try:
        px = _yf_closes(list(ETFS) + list(EQ))
        ok = [t for t, v in px.items() if v]
        src["etf_yahoo"] = f"ok {len(ok)}/{len(px)}" + ("" if len(ok) == len(px) else f" (빠짐: {', '.join(t for t, v in px.items() if not v)})")
    except Exception as e:  # noqa: BLE001
        src["etf_yahoo"] = f"실패: {type(e).__name__}: {str(e)[:200]}"
    ms = _load_json(REPORT_DIR / "macro_series.json", {}).get("series", {})
    ms_close = lambda k: {r[0]: r[4] for r in ms.get(k, []) if r[4]}  # noqa: E731
    for t, k in EQ.items():
        if not px.get(t):
            px[t] = ms_close(k)

    # 곡선·변화
    us_chg = {k: _chg_bp(_series(rows, "us_" + k)) for k in US_TENORS}
    kr_keys = list(KR_YEARS) + ["AA", "BBB", "CD"]
    kr_chg = {k: _chg_bp(_series(rows, "kr_" + k)) for k in kr_keys}

    def curve_at(prefix, keys, days):
        out = {}
        for k in keys:
            s = _series(rows, prefix + k)
            v = s[-1][1] if days == 0 and s else _at(s, days)
            if v is not None:
                out[k] = round(v, 3)
        return out
    us = {"asof": max((v["date"] for v in us_chg.values() if v), default=None), "chg": us_chg,
          "curve": {"now": curve_at("us_", US_TENORS, 0), "m1": curve_at("us_", US_TENORS, 30), "y1": curve_at("us_", US_TENORS, 365)}}
    kr = {"asof": max((v["date"] for v in kr_chg.values() if v), default=None), "chg": kr_chg,
          "curve": {"now": curve_at("kr_", list(KR_YEARS), 0), "m1": curve_at("kr_", list(KR_YEARS), 30), "y1": curve_at("kr_", list(KR_YEARS), 365)}}

    # 스프레드 (같은 날짜 기준) + 히스토리
    def spread(a, b):
        return [(r["date"], round(r[a] - r[b], 3)) for r in rows if r.get(a) is not None and r.get(b) is not None]
    SP = {"us_10_2": ("us_10Y", "us_2Y"), "us_10_3m": ("us_10Y", "us_3M"), "kr_10_3": ("kr_10Y", "kr_3Y"),
          "kr_aa": ("kr_AA", "kr_3Y"), "kr_bbb": ("kr_BBB", "kr_3Y")}
    spreads, hseries = {}, {}
    for k, (a, b) in SP.items():
        s = spread(a, b)
        spreads[k] = _chg_bp(s)
        if s:
            yr = [v for d, v in s if d >= str(date.fromisoformat(s[-1][0]) - timedelta(days=365))]
            spreads[k]["min1y"], spreads[k]["max1y"] = min(yr), max(yr)
        hseries[k] = s
    # 한미 10년: 날짜가 달라(시차) 각자 최신값끼리
    u10s, k10s = _series(rows, "us_10Y"), _series(rows, "kr_10Y")
    if u10s and k10s:
        um, km = dict(u10s), dict(k10s)
        gs = []
        lu = None
        for d in sorted(set(um) | set(km)):
            lu = um.get(d, lu)
            if d in km and lu is not None:
                gs.append((d, round(km[d] - lu, 3)))
        spreads["krus_10"] = _chg_bp(gs)
        hseries["krus_10"] = gs
    hist_out = {k: [[d, v] for d, v in s] for k, s in hseries.items()}
    hist_out["us_10Y"] = [[d, v] for d, v in u10s]
    hist_out["kr_10Y"] = [[d, v] for d, v in k10s]

    o = {"generated_at": now.strftime("%Y-%m-%d %H:%M"), "asof": max(filter(None, [us["asof"], kr["asof"]]), default=None),
         "sources": src, "us": us, "kr": kr, "spreads": spreads, "hist": hist_out}

    # 맥락
    fx = ms_close("USDKRW")
    nq = ms_close("NASDAQ")
    o["ctx"] = {"usdkrw": fx[max(fx)] if fx else None, "nasdaq_m1": _ret(nq, 30)}
    u3m, cd = (us_chg.get("3M") or {}).get("v"), (kr_chg.get("CD") or {}).get("v")
    o["hedge_cost"] = round(u3m - cd, 2) if u3m is not None and cd is not None else None

    # ETF
    etf = []
    yinfo = {}
    try:
        import yfinance as yf
        for t in ("LQD", "HYG"):
            try:
                inf = yf.Ticker(t).info or {}
                v = inf.get("yield") or inf.get("dividendYield")
                if v:
                    yinfo[t] = round(float(v) * (100 if float(v) < 1 else 1), 2)
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001
        pass
    for t, (n, mk, D, yk, role) in ETFS.items():
        p = px.get(t) or {}
        last = rows and yk and next((r[yk] for r in reversed(rows) if r.get(yk) is not None), None)
        e = {"s": t, "n": n, "mk": mk, "dur": D, "role": role, "y": last or None, "dy": yinfo.get(t)}
        if p:
            ds = sorted(p)
            e.update({"close": round(p[ds[-1]], 2), "date": ds[-1], "r1": _ret(p, 1), "r20": _ret(p, 30), "r250": _ret(p, 365)})
        e["calc"] = dur_only(D, e["y"] or e["dy"])
        e.update(etf_rate_label(D, n))      # 만기 없음 · 금리 +100bp → 가격 −X% 한 줄
        etf.append(e)
    o["etf"] = etf
    hy, ie = px.get("HYG") or {}, px.get("IEF") or {}
    common = sorted(set(hy) & set(ie))
    if len(common) > 60:
        ratio = {d: hy[d] / ie[d] for d in common}
        o["credit_us"] = {"v": round(ratio[common[-1]], 4), "r20": _ret(ratio, 30), "r60": _ret(ratio, 90),
                          "hist": [[d, round(ratio[d], 4)] for d in common[-260:]]}

    # 국채(액면) 듀레이션·시나리오
    dur = []
    for lab, pref, k, yrs in (("미국채 2년", "us", "2Y", 2), ("미국채 10년", "us", "10Y", 10), ("미국채 30년", "us", "30Y", 30),
                              ("국고채 3년", "kr", "3Y", 3), ("국고채 10년", "kr", "10Y", 10)):
        y = ((us_chg if pref == "us" else kr_chg).get(k) or {}).get("v")
        if y:
            dur.append({"n": lab, "kind": "액면채", **par_bond(y, yrs)})
    for e in etf:
        dur.append({"n": e["n"], "kind": "ETF 근사", **e["calc"]})
    o["duration"] = dur

    # 주식-채권 상관
    cr = {}
    for a, b in (("IEF", "^GSPC"), ("TLT", "^GSPC"), ("148070.KS", "^KS11"), ("114260.KS", "^KS11"), ("HYG", "^GSPC")):
        c250, n = corr(px.get(a) or {}, px.get(b) or {}, 250)
        c60, _ = corr(px.get(a) or {}, px.get(b) or {}, 60)
        cr[f"{a.split('.')[0]}_{EQ[b]}"] = {"a": ETFS[a][0], "b": "S&P500" if b == "^GSPC" else "코스피", "c250": c250, "c60": c60, "n": n}
    o["corr"] = cr

    prev = _load_json(OUT, {})
    # AI 인프라 신용 감시 (바스켓 + 신용 ETF + VIX) — 실패하면 이전 값 유지
    try:
        extra = [t for t in list(AI_BASKET) + list(CREDIT_ETFS) + ["^VIX"] if not px.get(t)]
        cx = _yf_closes(extra) if extra else {}
        okx = [t for t, v in cx.items() if v]
        px.update({t: v for t, v in cx.items() if v})
        src["ai_credit_yahoo"] = f"ok {len(okx)}/{len(extra)}" + ("" if len(okx) == len(extra) else f" (빠짐: {', '.join(t for t, v in cx.items() if not v)})")
    except Exception as e:  # noqa: BLE001
        src["ai_credit_yahoo"] = f"실패: {type(e).__name__}: {str(e)[:200]}"
    try:
        vxs = ms.get("VIX") or []
        vfb = next((r[4] for r in reversed(vxs) if r[4]), None)
        ac = ai_credit(px, vfb)
        if ac["basket"]:
            o["ai_credit"] = ac
        elif prev.get("ai_credit"):
            o["ai_credit"] = prev["ai_credit"]
            src["ai_credit_yahoo"] = src.get("ai_credit_yahoo", "") + " — 이전 값 유지"
            _stale(o, "ai_credit", prev.get("asof"))
    except Exception as e:  # noqa: BLE001
        src["ai_credit"] = f"실패: {type(e).__name__}: {str(e)[:200]}"
        if prev.get("ai_credit"):
            o["ai_credit"] = prev["ai_credit"]
            _stale(o, "ai_credit", prev.get("asof"))
    if not any((px.get(t) or {}) for t in ETFS) and prev.get("etf"):   # 야후 실패 → 이전 ETF·상관 유지
        for k in ("etf", "corr", "credit_us"):
            if k in prev:
                o[k] = prev[k]
        for e in o.get("etf", []):
            e.update(etf_rate_label(e.get("dur"), e.get("n")))
        o["duration"] = [d for d in dur if d["kind"] != "ETF 근사"] + [{"n": e["n"], "kind": "ETF 근사", **e["calc"]} for e in o["etf"] if e.get("calc")]
        src["etf_yahoo"] += " — 이전 값 유지"
        _stale(o, "etf", prev.get("asof"))
    o["notes"] = interpret(o)
    o["reco"] = recommend(o)
    o["guide"] = guide(o)
    o["vehicles"] = vehicles(o)
    try:   # 보고 상단 형식 top(STANDARD 8절) — 추가만
        from . import topline_from
        o["top"] = topline_from.bonds(o)
    except Exception as e:  # noqa: BLE001
        log.warning("채권 top 실패: %s", e)
    from .guard import write_json
    write_json(OUT, o, separators=(",", ":"))
    log.info("채권: US10Y %s KR10Y %s 소스 %s", (us_chg.get("10Y") or {}).get("v"), (kr_chg.get("10Y") or {}).get("v"), src)
    return o


def load() -> dict:
    return _load_json(OUT, {})


def summary(o: dict) -> str:
    g = lambda d, k: (d.get(k) or {}).get("v")  # noqa: E731
    us, kr = o.get("us", {}).get("chg", {}), o.get("kr", {}).get("chg", {})
    al = ((o.get("ai_credit") or {}).get("alert") or {}).get("line") or "AI 인프라 신용: 데이터 없음"
    return (f"US 2Y {g(us, '2Y')} 10Y {g(us, '10Y')} 30Y {g(us, '30Y')} | KR 3Y {g(kr, '3Y')} 10Y {g(kr, '10Y')} AA- {g(kr, 'AA')}\n"
            + al + "\n"
            + json.dumps(o.get("sources", {}), ensure_ascii=False))
