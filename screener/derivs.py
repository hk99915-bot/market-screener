"""코스피200 옵션·선물 포지션 (KRX 정보데이터시스템, pykrx 세션 재사용) → reports/derivs.json

- 옵션 전 종목 시세(MDCSTAT12501, KRDRVOPK2I): 행사가별 미결제약정(OI)·거래량·종가
- 풋/콜 비율(OI·거래량), 최대 고통(max pain), 콜 벽(위 저항)·풋 벽(아래 지지)
- 감마 노출 근사(GEX): 종가로 내재변동성 역산 → 블랙숄즈 감마 × OI × 승수(25만원)
  관례: 콜 +, 풋 − (딜러가 콜은 사고 풋은 판 상태라고 가정). 한국은 외국인·개인 구성이 달라
  부호가 틀릴 수 있음 → '방향'보다 '감마가 몰린 가격대(자석·벽)' 위주로 읽을 것.
- 감마 전환점(flip): 가상의 지수 수준별로 GEX 합을 다시 계산해 부호가 바뀌는 곳
- 선물: 최근월물 종가·OI·베이시스
- 일별 요약은 reports/derivs_hist.json 에 누적 (PCR 추세). 장기 일별 이력은 screener/deriv_hist.py → data/deriv/daily.csv

점검 (2026-10-16, 파생):
- 만기일 당일엔 최근월이 그날 오후 소멸 → 다음 월물로 넘김 (전엔 만기일 감마가 0·전환점이 엉뚱하게 찍힘)
- 최대 고통: 후보 범위(현물 ±15%) 끝에 걸리면 '범위 밖'(None) — 전엔 항상 0.85×현물 근처가 찍힘(깊은 내가격 OI 탓)
- 감마 전환점: 현재가에서 가장 가까운 부호 전환 (전엔 격자 맨 아래 쪽 첫 전환)
- 행사가 1,000 이상(쉼표 표기)이 정규식에서 빠지던 버그 수정 — 코스피200 이 1,000 을 넘은 구간(2026-07~10)에서
  콜 벽 없음·감마 음수 쏠림·PCR 왜곡의 원인이었음 (지수 위쪽 콜이 통째로 누락)
- 풋콜비율은 '월물 전 만기 합' (위클리 제외) — 위클리로 거래가 옮겨가 거래량 PCR 은 시장 전체를 대표하지 못함
"""
from __future__ import annotations

import json
import logging
import math
import re
from datetime import date, datetime, timedelta

from .config import REPORT_DIR

log = logging.getLogger(__name__)
OUT = REPORT_DIR / "derivs.json"
HIST = REPORT_DIR / "derivs_hist.json"
MULT = 250_000
RATE = 0.03
RX = re.compile(r"코스피200\s+([CP])\s+(\d{6})\s+([\d,]+(?:\.\d+)?)")   # 행사가 1,000 이상은 쉼표 포함


def _io(bld: str, **kw) -> list[dict]:
    from pykrx.website.krx.krxio import KrxWebIo

    class _B(KrxWebIo):
        @property
        def bld(self):
            return bld

        def fetch(self, **k):
            return self.read(**k)
    r = _B().fetch(**kw)
    return r.get("output") or []


def _f(x) -> float | None:
    try:
        return float(str(x).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _expiry(ym: str) -> date:
    d = date(int(ym[:4]), int(ym[4:]), 1)
    while d.weekday() != 3:
        d += timedelta(days=1)
    return d + timedelta(days=7)


def _ncdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _bs(S, K, T, v, cp):
    if T <= 0 or v <= 0:
        return max(0.0, (S - K) if cp == "C" else (K - S))
    d1 = (math.log(S / K) + (RATE + v * v / 2) * T) / (v * math.sqrt(T))
    d2 = d1 - v * math.sqrt(T)
    if cp == "C":
        return S * _ncdf(d1) - K * math.exp(-RATE * T) * _ncdf(d2)
    return K * math.exp(-RATE * T) * _ncdf(-d2) - S * _ncdf(-d1)


def _iv(px, S, K, T, cp):
    lo, hi = 0.01, 3.0
    if px <= _bs(S, K, T, lo, cp) or px >= _bs(S, K, T, hi, cp):
        return None
    for _ in range(60):
        m = (lo + hi) / 2
        if _bs(S, K, T, m, cp) > px:
            hi = m
        else:
            lo = m
    return (lo + hi) / 2


def _gamma(S, K, T, v):
    if T <= 0 or v <= 0:
        return 0.0
    d1 = (math.log(S / K) + (RATE + v * v / 2) * T) / (v * math.sqrt(T))
    return math.exp(-d1 * d1 / 2) / math.sqrt(2 * math.pi) / (S * v * math.sqrt(T))


def _day(ymd: str) -> tuple[list[dict], list[dict]]:
    opt = _io("dbms/MDC/STAT/standard/MDCSTAT12501", trdDd=ymd, prodId="KRDRVOPK2I", mktTpCd="T", rghtTpCd="T")
    fut = _io("dbms/MDC/STAT/standard/MDCSTAT12501", trdDd=ymd, prodId="KRDRVFUK2I", mktTpCd="T", rghtTpCd="T")
    return opt, fut


def _parse(opt: list[dict]) -> list[dict]:
    rows = []
    for r in opt:
        nm = r.get("ISU_NM") or ""
        if "야간" in nm:
            continue
        m = RX.search(nm)
        if not m:
            continue
        rows.append({"cp": m.group(1), "ym": m.group(2), "k": float(m.group(3).replace(",", "")), "px": _f(r.get("TDD_CLSPRC")),
                     "oi": _f(r.get("ACC_OPNINT_QTY")) or 0.0, "vol": _f(r.get("ACC_TRDVOL")) or 0.0})
    return rows


def _summ(rows: list[dict], S: float, asof: date) -> dict:
    yms = sorted({r["ym"] for r in rows if _expiry(r["ym"]) > asof})   # 만기일 당일엔 다음 월물
    if not yms:
        return {}
    front = yms[0]
    fr = [r for r in rows if r["ym"] == front]
    T = max((_expiry(front) - asof).days, 0.5) / 365
    coi = sum(r["oi"] for r in rows if r["cp"] == "C")
    poi = sum(r["oi"] for r in rows if r["cp"] == "P")
    cv = sum(r["vol"] for r in rows if r["cp"] == "C")
    pv = sum(r["vol"] for r in rows if r["cp"] == "P")
    ks = sorted({r["k"] for r in fr})
    # 최대 고통: 만기 지수가 K 일 때 매수자 총 내재가치가 최소인 K
    def pain(x):
        return sum(r["oi"] * (max(0, x - r["k"]) if r["cp"] == "C" else max(0, r["k"] - x)) for r in fr)
    mp = min(ks, key=pain) if ks else None   # 전체 행사가 중 최소 — 현물 ±15% 밖이면 의미 없음 → None
    mp_raw = mp
    if mp is not None and not (0.85 * S <= mp <= 1.15 * S):
        mp = None
    calls = [r for r in fr if r["cp"] == "C" and r["k"] >= S]
    puts = [r for r in fr if r["cp"] == "P" and r["k"] <= S]
    cw = max(calls, key=lambda r: r["oi"]) if calls else None
    pw = max(puts, key=lambda r: r["oi"]) if puts else None
    # 감마
    ivs = {}
    for r in fr:
        if r["px"] and r["px"] > 0.05 and abs(r["k"] / S - 1) < 0.2:
            v = _iv(r["px"], S, r["k"], T, r["cp"])
            if v:
                ivs[(r["cp"], r["k"])] = v
    # 행사가별 IV가 없으면 가까운 행사가 IV로 채움 (같은 쪽 우선)
    def iv_for(cp, k):
        if (cp, k) in ivs:
            return ivs[(cp, k)]
        c = [(abs(kk - k), v) for (cc, kk), v in ivs.items() if cc == cp] or [(abs(kk - k), v) for (cc, kk), v in ivs.items()]
        return min(c)[1] if c else 0.3
    atm = [v for (cp, k), v in ivs.items() if abs(k / S - 1) < 0.02]
    # 스큐: 5% 외가 풋 IV − 5% 외가 콜 IV (가장 가까운 행사가)
    def near_iv(cp, tgt):
        c = [(abs(k - tgt), v) for (cc, k), v in ivs.items() if cc == cp]
        return min(c)[1] if c else None
    p95, c105 = near_iv("P", S * 0.95), near_iv("C", S * 1.05)
    skew = (p95 - c105) if p95 and c105 else None
    def gex(at):
        tot = 0.0
        prof = {}
        for r in fr:
            if r["oi"] <= 0 or abs(r["k"] / at - 1) > 0.25:
                continue
            g = _gamma(at, r["k"], T, iv_for(r["cp"], r["k"])) * r["oi"] * MULT * at * at * 0.01
            g = g if r["cp"] == "C" else -g
            tot += g
            prof[r["k"]] = prof.get(r["k"], 0) + g
        return tot, prof
    g0, prof = gex(S)
    flip = None
    grid = [S * (1 + i / 200) for i in range(-30, 31)]
    vals = [(x, gex(x)[0]) for x in grid]
    for (x1, v1), (x2, v2) in zip(vals, vals[1:]):
        if (v1 < 0) != (v2 < 0):
            fx = x1 + (x2 - x1) * (abs(v1) / (abs(v1) + abs(v2) or 1))
            if flip is None or abs(fx - S) < abs(flip - S):   # 현재가에서 가장 가까운 전환
                flip = fx
    top = sorted(prof.items(), key=lambda kv: -abs(kv[1]))[:8]
    return {"front": front, "expiry": str(_expiry(front)), "dte": (_expiry(front) - asof).days, "spot": round(S, 2),
            "pcr_oi": round(poi / coi, 3) if coi else None, "pcr_vol": round(pv / cv, 3) if cv else None,
            "call_oi": coi, "put_oi": poi, "max_pain": mp, "max_pain_raw": mp_raw,
            "call_wall": {"k": cw["k"], "oi": cw["oi"]} if cw else None, "put_wall": {"k": pw["k"], "oi": pw["oi"]} if pw else None,
            "atm_iv": round(sum(atm) / len(atm), 4) if atm else None, "skew": round(skew, 4) if skew is not None else None,
            "iv_p95": round(p95, 4) if p95 else None, "iv_c105": round(c105, 4) if c105 else None,
            "gex_bn": round(g0 / 1e8, 1), "flip": round(flip, 1) if flip else None,
            "gex_top": [{"k": k, "g_bn": round(v / 1e8, 1)} for k, v in sorted(top)],
            "oi_profile": [{"k": k, "c": sum(r["oi"] for r in fr if r["cp"] == "C" and r["k"] == k),
                            "p": sum(r["oi"] for r in fr if r["cp"] == "P" and r["k"] == k)} for k in ks if 0.88 * S <= k <= 1.12 * S]}


def _fut(fut: list[dict]) -> dict:
    rows = [r for r in fut if "야간" not in (r.get("ISU_NM") or "") and "스프레드" not in (r.get("ISU_NM") or "") and "SP" not in (r.get("ISU_NM") or "")]
    if not rows:
        return {}
    r = rows[0]
    px, sp = _f(r.get("TDD_CLSPRC")), _f(r.get("SPOT_PRC"))
    out = {"name": r.get("ISU_NM"), "close": px, "open": _f(r.get("TDD_OPNPRC")), "spot": sp,
           "basis": round(px - sp, 2) if px and sp else None,
           "oi": _f(r.get("ACC_OPNINT_QTY")), "vol": _f(r.get("ACC_TRDVOL"))}
    # 야간 행 (유렉스 연계 시절 2009~2025-06 은 같은 보드에 '(야간)' 으로 나옴; KRX 자체 야간시장 이후엔 이 보드에 없음)
    nt = [x for x in fut if "야간" in (x.get("ISU_NM") or "") and "SP" not in (x.get("ISU_NM") or "")]
    if nt:
        n = nt[0]
        out["night"] = {"name": n.get("ISU_NM"), "close": _f(n.get("TDD_CLSPRC")), "vol": _f(n.get("ACC_TRDVOL")),
                        "oi": _f(n.get("ACC_OPNINT_QTY"))}
    return out


def _read(d: date) -> dict | None:
    ymd = d.strftime("%Y%m%d")
    opt, fut = _day(ymd)
    rows = _parse(opt)
    if not rows:
        return None
    f = _fut(fut)
    S = f.get("spot") or f.get("close")
    if not S:
        return None
    s = _summ(rows, S, d)
    return {"date": str(d), "fut": f, **s}


def _basis_split(on: str | None) -> str | None:
    """베이시스 옆에 병기할 두 값 — 외국인 선물 순매수(daily.csv fut_frgn)·원/달러 5거래일 변화(macro_series USDKRW).
    심리 요인(선물 매수·매도 쏠림)과 환 헤지 요인을 눈으로 갈라 보라는 병기일 뿐, 원인 판정은 하지 않는다. 값이 없으면 None."""
    if not on:
        return None
    parts = []
    row = next((r for r in reversed(_daily()) if r.get("date") == on), None)
    v = _f(row.get("fut_frgn")) if row else None
    if v is not None:
        parts.append(f"외국인 선물 순매수 {v:+,.0f}계약")
    try:
        ser = json.loads((REPORT_DIR / "macro_series.json").read_text(encoding="utf-8"))["series"]["USDKRW"]
        ser = [r for r in ser if r[0] <= on]
        if len(ser) > 5 and ser[-1][0] == on:
            parts.append(f"원/달러 5일 {(ser[-1][4] / ser[-6][4] - 1) * 100:+.1f}%")
    except Exception:  # noqa: BLE001
        pass
    if not parts:
        return None
    return "베이시스 병기: " + " · ".join(parts) + " — 선물 쏠림(심리)과 환 헤지 중 무엇이 큰지는 이 두 값을 나란히 보고 판단, 원인 단정 금지"


def interpret(o: dict) -> list[str]:
    """초보용 한 줄 해석. 원칙: 검증 안 된 것은 '방향 신호'로 말하지 않는다 (reports/studies/derivs_signals.md)."""
    if not o or not o.get("spot"):
        return []
    S = o["spot"]
    L = []
    if o.get("pcr_oi") is not None:
        p = o["pcr_oi"]
        L.append(f"풋/콜 미결제 비율 {p:.2f} — " + ("풋(하락 대비 보험)이 콜보다 많이 쌓임" if p >= 1.2 else
                                                 "콜(상승 베팅)이 더 많이 쌓임" if p <= 0.7 else "중립 범위") +
                 " · 방향 신호로는 검증 전")
    if o.get("put_wall") and o.get("call_wall"):
        pw, cw = o["put_wall"]["k"], o["call_wall"]["k"]
        L.append(f"미결제 최다 행사가: 아래 풋 {pw:.1f}({(pw/S-1)*100:+.0f}%) · 위 콜 {cw:.1f}({(cw/S-1)*100:+.0f}%) — "
                 f"만기({o['expiry'][5:]})까지 '벽'이 된다는 주장은 검증 전, 위치 참고만")
    if o.get("gex_bn") is not None:
        neg = o["gex_bn"] < 0
        L.append(f"감마 노출 근사 {o['gex_bn']:+,.0f}억/1% — " + ("음수: 시장이 흔들릴 때 헤지 매매가 흔들림을 키우는 쪽" if neg else
                                                         "양수: 헤지 매매가 흔들림을 누그러뜨리는 쪽") +
                 " (딜러가 콜 매수·풋 매도라는 가정 — 한국은 틀릴 수 있음. 방향 아님, 흔들림 크기 참고)")
        if o.get("flip"):
            L.append(f"감마 전환점 ≈ {o['flip']:.1f} (현재 대비 {(o['flip']/S-1)*100:+.1f}%) — 위 가정이 맞을 때만 의미")
    if o.get("atm_iv") and o.get("rv20"):
        vrp = o["atm_iv"] - o["rv20"]
        L.append(f"내재변동성(ATM) {o['atm_iv']*100:.0f}% vs 실현변동성(20일) {o['rv20']*100:.0f}% — " +
                 ("옵션 값이 최근 실제 흔들림보다 비쌈(공포 프리미엄) — 지금 보험(풋) 사기는 비싼 편" if vrp > 0.05 else
                  "옵션 값이 최근 실제 흔들림보다 쌈 — 보험 사기엔 싼 편" if vrp < -0.03 else "대체로 맞게 가격됨"))
    if o.get("skew") is not None:
        L.append(f"스큐(5% 외가 풋 IV − 콜 IV) {o['skew']*100:+.1f}%p — " + ("하락 보험 수요가 강함" if o["skew"] > 0.05 else "상방 콜 수요 쪽" if o["skew"] < 0 else "보통"))
    f = o.get("fut") or {}
    if f.get("basis") is not None:
        L.append(f"선물 베이시스 {f['basis']:+.2f}p — " + ("선물이 현물보다 쌈(백워데이션). 배당·금리 이론값 대비로 봐야 정확 — 큰 음수가 며칠 이어지면 매도 헤지 쏠림" if f["basis"] < 0 else
                                                      "선물이 현물보다 비쌈(콘탱고) — 보통 상태"))
    if f.get("basis") is not None:
        extra = _basis_split(o.get("date"))
        if extra:
            L.append(extra)
    if o.get("max_pain"):   # 참고용 — 근거 약해 맨 뒤로 (텔레그램 상위 4줄에서 빠짐)
        L.append(f"(참고) 최대 고통 {o['max_pain']:.1f} — 옵션 매수자 손실이 최대인 만기 지수. '끌려간다'는 가설은 근거 약함, 매매 근거로 쓰지 말 것")
    return L


# ───── 파생 한눈에 (10/20 겸이: "쉽고 직관적으로 파생 인사이트 따로 상단에") ─────
# 원칙(KB derivs.md): 방향(오른다/내린다)은 말하지 않는다 · 값마다 과거 대비 분위+표본 기간 · 등급 배지 · 없으면 '데이터 없음' 그대로.
SIG = REPORT_DIR / "studies" / "derivs_signals.json"
DAILY = REPORT_DIR.parent / "data" / "deriv" / "daily.csv"
_RANK = ["A", "B", "C", "F", "검증전"]


def _grades() -> dict:
    try:
        S = json.loads(SIG.read_text(encoding="utf-8")).get("signals") or []
    except Exception:  # noqa: BLE001
        return {}
    g: dict = {}
    for x in S:
        a, b = g.get(x.get("lens_id")), x.get("grade")
        if b in _RANK and (a is None or _RANK.index(b) < _RANK.index(a)):
            g[x["lens_id"]] = b
    return g


def _daily() -> list[dict]:
    import csv
    try:
        with open(DAILY, encoding="utf-8") as fh:
            return list(csv.DictReader(fh))
    except Exception:  # noqa: BLE001
        return []


def _pctl(rows: list[dict], k: str, v, scale: float = 1.0) -> dict | None:
    """v 의 과거 분위(0=가장 낮음). 표본 기간·일수를 같이 돌려준다."""
    s = [(r["date"], _f(r.get(k))) for r in rows]
    s = [(d, x * scale) for d, x in s if x is not None]
    if v is None or len(s) < 20:
        return None
    p = sum(1 for _, x in s if x <= v) / len(s)
    return {"p": round(p * 100), "from": s[0][0], "to": s[-1][0], "n": len(s)}


def _where(q: dict | None) -> str:
    if not q:
        return "과거 비교 표본 부족"
    p = q["p"]
    w = "최상단" if p >= 95 else "상위" if p >= 80 else "최하단" if p <= 5 else "하위" if p <= 20 else "중간"
    return f"최근 {q['n']}거래일({q['from']}~{q['to']}) 중 {p}% — {w}"


def basis_theo_ref(rows: list[dict], on: str | None) -> tuple[float | None, str | None]:
    """이론 베이시스 기준값 — `on` 이하 날짜 중 가장 최근 확정치(KRX THRY_BASIS). 장중엔 전일 확정치를 쓴다
    (12월물 만기 전 배당 거의 0 → 하루 사이 이론값 변화는 잔존일·금리분뿐, 보통 0.1p 안). 10/21 PB 요청 req-derivs-909b54f9."""
    for r in reversed(rows or []):
        v = _f(r.get("basis_theo"))
        if v is not None and (not on or str(r.get("date", "")) <= on):
            return v, str(r.get("date"))
    return None, None


def intraday(o: dict) -> str | None:
    """derivs.json 이 장중 스냅숏이면 'HH:MM' — 생성 시각이 거래일 15:45 KST 전. 확정(장 마감 뒤)이면 None."""
    a, d = str(o.get("asof") or ""), str(o.get("date") or "")
    if len(a) >= 16 and a[:10] == d and a[11:16] < "15:45":
        return a[11:16]
    return None


def insight(o: dict, rows: list[dict] | None = None, grades: dict | None = None, today: date | None = None) -> dict:
    """reports/derivs.json 'insight' 블록 — 한 줄 요약 · 신호등 카드 · 시사점(리스크 관점).
    rows = data/deriv/daily.csv 행(dict, 문자열 값 허용), grades = lens_id→등급. 매매 신호 아님."""
    rows = _daily() if rows is None else rows
    grades = _grades() if grades is None else grades
    today = today or date.today()
    gr = lambda lens: grades.get(lens) or "검증전"   # noqa: E731 — 등록 안 된 렌즈는 검증전
    opt = [r for r in rows if _f(r.get("pcr_oi")) is not None]
    lag = None
    if o.get("date"):
        lag = (today - date.fromisoformat(o["date"])).days
    stale = bool(o.get("stale")) or (lag is not None and lag > 4)
    tag = ("지연 " + (o["stale"]["got"] if o.get("stale") else o.get("date", ""))) if stale else None
    C = []

    def card(k, title, value, light, where, easy, grade, status=None):
        C.append({"k": k, "title": title, "value": value, "light": light, "where": where, "easy": easy,
                  "grade": grade, "status": status or tag or "정상"})

    iv, rv, gex = o.get("atm_iv"), o.get("rv20"), o.get("gex_bn")
    if iv is None and gex is None:
        card("vol", "변동성(진폭)", "—", "gray", "", "옵션 데이터 없음", "참고", "데이터 없음")
    else:
        qi = _pctl(opt, "atm_iv", iv) if iv is not None else None
        qr = _pctl(rows, "rep_iv", (iv or 0) * 100) if iv is not None else None
        big = (qi and qi["p"] >= 80) or (gex is not None and gex < 0)
        v = f"IV {iv*100:.0f}%" if iv is not None else "IV —"
        v += f" · RV {rv*100:.0f}%" if rv else " · RV —"
        easy = ("옵션 내재 일간 진폭 ≈ ±{:.1f}%".format(iv * 100 / 15.87) if iv else "")
        if gex is not None:
            easy += (" · " if easy else "") + ("감마 음수 — 급변 시 헤지 매매가 진폭 확대" if gex < 0 else "감마 양수 — 헤지 매매가 진폭 완화")
        w = _where(qi) + (f" · 대표IV {qr['n']}거래일({qr['from'][:4]}~) 중 {qr['p']}%" if qr else "")
        card("vol", "변동성(진폭)", v + (f" · 감마 {gex:+,.0f}억" if gex is not None else ""), "red" if big else "green", w, easy, gr("options_gamma"))
    p = o.get("pcr_oi")
    if p is None:
        card("fear", "경계 심리 (PCR)", "—", "gray", "", "풋/콜 데이터 없음", "참고", "데이터 없음")
    else:
        q = _pctl(opt, "pcr_oi", p)
        rel = q["p"] if q else 50   # 절대 수준(1.2)과 과거 대비 위치가 엇갈릴 수 있음 — 둘 다 말한다
        lt = "amber" if (p >= 1.2 and rel >= 50) or rel >= 80 else "green"
        easy = "풋 우위(풋/콜 {:.2f})".format(p) if p >= 1.2 else "콜 우위" if p <= 0.7 else "풋·콜 균형"
        easy += " · 과거 대비 하위 — 경계 약함" if rel <= 20 else " · 과거 대비 상위 — 경계 강함" if rel >= 80 else " · 과거 대비 중간"
        card("fear", "경계 심리 (PCR)", f"{p:.2f}", lt, _where(q), easy + " · 방향 신호 아님", gr("options_pcr"))
    b = (o.get("fut") or {}).get("basis")
    if b is None:
        card("basis", "선물 프리미엄 (베이시스)", "—", "gray", "", "선물 데이터 없음", "참고", "데이터 없음")
    else:
        q = _pctl(opt, "basis", b)
        th, th_d = basis_theo_ref(rows, o.get("date"))
        live = intraday(o)
        if th is not None:
            dev = b - th
            easy = (f"이론값 {th:+.2f}p({th_d[5:]} 확정) 대비 {dev:+.2f}p — "
                    + ("선물 저평가(매도 헤지 우위 시 출현)" if dev <= -1 else "선물 고평가" if dev >= 1 else "이론값 근처(통상)"))
            light = "amber" if dev <= -1 or b < 0 else "green"
        else:
            easy = ("선물 할인(백워데이션) — 매도 헤지 우위 시 출현" if b < 0 else "선물 프리미엄(콘탱고) · 이론값 없음 — 부호만으로 '정상' 판단 불가")
            light = "amber" if b < 0 else "green"
        if live:
            easy = "장중 값(" + live + ") · " + easy
        card("basis", "선물 프리미엄 (베이시스)", f"{b:+.2f}p", light, _where(q), easy, gr("fut_basis"))
    ff = [(r["date"], _f(r.get("fut_frgn"))) for r in rows if _f(r.get("fut_frgn")) is not None]
    if not ff:
        card("frgn", "외국인 선물", "—", "gray", "", "외국인 선물 순매수 적재 전", "참고", "데이터 없음")
    else:
        d0, v0 = ff[-1]
        s5 = sum(x for _, x in ff[-5:])
        fst = "지연 " + d0 if d0 != o.get("date") else None
        card("frgn", "외국인 선물", f"{v0:+,.0f}계약", "amber" if v0 < 0 else "green",
             f"표본 {len(ff)}거래일({ff[0][0]}~) — 분위 산출 불가" if len(ff) < 20 else f"최근 {min(5, len(ff))}거래일 합 {s5:+,.0f}계약",
             ("당일 외국인 선물 순매도" if v0 < 0 else "당일 외국인 선물 순매수") + f" · 최근 {min(5, len(ff))}거래일 합 {s5:+,.0f}계약",
             gr("fut_foreign_flow"), fst)
    if o.get("expiry"):
        dte = o.get("dte")
        card("expiry", "만기·이벤트", f"{o['expiry'][5:]} (D-{dte})", "amber" if dte is not None and dte <= 5 else "green",
             f"{o.get('front', '')}물 최근월 옵션 만기(둘째 목요일)",
             "만기 주 — 포지션 청산에 따른 진폭 확대 가능" if dte is not None and dte <= 5 else "만기 여유 — 만기 효과 해당 없음", "참고")
    else:
        card("expiry", "만기·이벤트", "—", "gray", "", "만기 정보 없음", "참고", "데이터 없음")
    qf = _pctl(opt, "pcr_oi", p) if p is not None else None
    fear = p is not None and p >= 1.2 and (qf is None or qf["p"] >= 50)
    if gex is None and p is None:
        one = "옵션 데이터 없음 — 해석 보류"
    elif gex is not None and gex < 0:
        one = ("풋 포지션 과거 대비 우위 · " if fear else "") + "변동성 확대 국면(가속페달형) — 방향 아닌 진폭 신호"
    else:
        one = ("풋 포지션 과거 대비 우위 · " if fear else "") + "변동성 완화 국면(완충형) — 방향 아닌 진폭 신호"
    rough = (gex is not None and gex < 0) or any(c["k"] == "vol" and c["light"] == "red" for c in C)
    so = ("레버리지·신용 신규 확대 자제, 분할 실행 · 파생 지표의 방향 근거 사용 금지"
          if rough else "기존 규칙 유지 · 파생 지표의 방향 근거 사용 금지")
    if stale:
        one = f"[{tag}] " + one
    return {"one_line": one, "so_what": so, "cards": C, "stale": stale, "asof": o.get("date"),
            "rule": "방향 신호 아님 · 분위 = 최근 표본 중 위치(0% = 최저) · 등급 출처 reports/studies/derivs_signals.json"}


def build(backfill: int = 20) -> dict:
    from .tradecal import is_session
    d = date.today()
    while not is_session("KR", d):   # 주말 + KRX 휴장일 (tradecal)
        d -= timedelta(days=1)
    want, cur = d, None
    for _ in range(5):
        for k in range(3 if d == want else 1):   # 목표 거래일은 KRX 가 HTML(차단·세션 만료)을 줄 때가 있어 쉬었다 재시도 (deriv_hist.board_day 와 같은 방식)
            try:
                cur = _read(d)
            except Exception as e:  # noqa: BLE001
                log.warning("KRX 옵션 %s 실패(%d): %s", d, k + 1, e)
                cur = None
            if cur:
                break
            if d == want and k < 2:
                import time
                time.sleep(10 * (k + 1))
        if cur:
            break
        d -= timedelta(days=1)
        while not is_session("KR", d):
            d -= timedelta(days=1)
    if not cur:
        log.warning("KRX 옵션 데이터 없음")
        return {}
    if d != want:   # 조용히 전일로 넘어가던 문제(10/16 화면이 10/15 로 남음) → 표시
        cur["stale"] = {"want": str(want), "got": str(d)}
        log.warning("옵션 보드: %s 수집 실패 → %s 값 사용(stale 표시)", want, d)
        try:
            from .guard import record_stale
            record_stale("reports/derivs.json", "옵션 보드", want, d)
        except Exception:  # noqa: BLE001
            pass
    try:
        h = json.loads(HIST.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        h = {"rows": []}
    have = {r["date"] for r in h["rows"]}
    keep = ("date", "spot", "pcr_oi", "pcr_vol", "max_pain", "gex_bn", "flip", "atm_iv")
    h["rows"] = [r for r in h["rows"] if r["date"] != cur["date"]] + [{k: cur.get(k) for k in keep} | {"basis": (cur.get("fut") or {}).get("basis")}]
    # 과거 백필 (최초 1회)
    if len(have) < 5 and backfill:
        dd = d
        for _ in range(backfill * 2):
            dd -= timedelta(days=1)
            if dd.weekday() >= 5 or str(dd) in have:
                continue
            try:
                x = _read(dd)
            except Exception:  # noqa: BLE001
                x = None
            if x:
                h["rows"].append({k: x.get(k) for k in keep} | {"basis": (x.get("fut") or {}).get("basis")})
            if len(h["rows"]) > backfill:
                break
    h["rows"] = sorted(h["rows"], key=lambda r: r["date"])[-260:]
    HIST.write_text(json.dumps(h, ensure_ascii=False), encoding="utf-8")
    cur["hist"] = h["rows"][-60:]
    try:
        from pykrx import stock  # type: ignore
        df = stock.get_index_ohlcv((d - timedelta(days=60)).strftime("%Y%m%d"), d.strftime("%Y%m%d"), "1028")
        c = [float(x) for x in df["종가"].tolist()]
        r = [math.log(c[i] / c[i - 1]) for i in range(len(c) - 20, len(c))] if len(c) > 21 else []
        if r:
            m = sum(r) / len(r)
            cur["rv20"] = round(math.sqrt(sum((x - m) ** 2 for x in r) / (len(r) - 1) * 252), 4)
    except Exception as e:  # noqa: BLE001
        log.info("코스피200 실현변동성 실패: %s", e)
    cur["notes"] = interpret(cur)
    try:
        cur["insight"] = insight(cur)
    except Exception as e:  # noqa: BLE001 — 인사이트 실패가 옵션 보드를 막지 않게
        log.warning("파생 인사이트 실패: %s", e)
    from zoneinfo import ZoneInfo   # 생성 시각은 KST (CI 러너 UTC 로 찍혀 화면 헤더가 9시간 어긋남 — 감사 경-3 10/17)
    cur["asof"] = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M")
    from .guard import write_json
    write_json(OUT, cur, key="date")   # asof 는 실행 시각 — 데이터일(date) 역행만 차단
    log.info("옵션 포지션: PCR %.2f GEX %s억 flip %s", cur.get("pcr_oi") or 0, cur.get("gex_bn"), cur.get("flip"))
    return cur


def load() -> dict:
    try:
        return json.loads(OUT.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
