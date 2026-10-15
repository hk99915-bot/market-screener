"""코스피200 옵션·선물 포지션 (KRX 정보데이터시스템, pykrx 세션 재사용) → reports/derivs.json

- 옵션 전 종목 시세(MDCSTAT12501, KRDRVOPK2I): 행사가별 미결제약정(OI)·거래량·종가
- 풋/콜 비율(OI·거래량), 최대 고통(max pain), 콜 벽(위 저항)·풋 벽(아래 지지)
- 감마 노출 근사(GEX): 종가로 내재변동성 역산 → 블랙숄즈 감마 × OI × 승수(25만원)
  관례: 콜 +, 풋 − (딜러가 콜은 사고 풋은 판 상태라고 가정). 한국은 외국인·개인 구성이 달라
  부호가 틀릴 수 있음 → '방향'보다 '감마가 몰린 가격대(자석·벽)' 위주로 읽을 것.
- 감마 전환점(flip): 가상의 지수 수준별로 GEX 합을 다시 계산해 부호가 바뀌는 곳
- 선물: 최근월물 종가·OI·베이시스
- 일별 요약은 reports/derivs_hist.json 에 누적 (PCR 추세)
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
RX = re.compile(r"코스피200\s+([CP])\s+(\d{6})\s+([\d.]+)")


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
        rows.append({"cp": m.group(1), "ym": m.group(2), "k": float(m.group(3)), "px": _f(r.get("TDD_CLSPRC")),
                     "oi": _f(r.get("ACC_OPNINT_QTY")) or 0.0, "vol": _f(r.get("ACC_TRDVOL")) or 0.0})
    return rows


def _summ(rows: list[dict], S: float, asof: date) -> dict:
    yms = sorted({r["ym"] for r in rows if _expiry(r["ym"]) >= asof})
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
    near = [k for k in ks if 0.85 * S <= k <= 1.15 * S] or ks
    mp = min(near, key=pain) if near else None
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
        c = [(abs(kk - k), v) for (cc, kk), v in ivs.items()]
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
        if v1 == 0 or (v1 < 0) != (v2 < 0):
            flip = x1 + (x2 - x1) * (abs(v1) / (abs(v1) + abs(v2) or 1))
            if abs(flip - S) < abs((flip if flip else 1e9) - S) + 1:
                break
    top = sorted(prof.items(), key=lambda kv: -abs(kv[1]))[:8]
    return {"front": front, "expiry": str(_expiry(front)), "dte": (_expiry(front) - asof).days, "spot": round(S, 2),
            "pcr_oi": round(poi / coi, 3) if coi else None, "pcr_vol": round(pv / cv, 3) if cv else None,
            "call_oi": coi, "put_oi": poi, "max_pain": mp,
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
    return {"name": r.get("ISU_NM"), "close": px, "spot": sp, "basis": round(px - sp, 2) if px and sp else None,
            "oi": _f(r.get("ACC_OPNINT_QTY")), "vol": _f(r.get("ACC_TRDVOL"))}


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


def interpret(o: dict) -> list[str]:
    if not o or not o.get("spot"):
        return []
    S = o["spot"]
    L = []
    if o.get("pcr_oi") is not None:
        p = o["pcr_oi"]
        L.append(f"풋/콜 미결제 비율 {p:.2f} — " + ("풋이 많이 쌓임: 하락 대비 수요 큼(역발상으론 바닥 근처 신호가 되기도)" if p >= 1.2 else
                                                 "콜 우위: 상승 기대 쏠림" if p <= 0.7 else "중립 범위"))
    if o.get("put_wall") and o.get("call_wall"):
        L.append(f"아래 풋 벽 {o['put_wall']['k']:.1f} (OI {o['put_wall']['oi']:,.0f}) · 위 콜 벽 {o['call_wall']['k']:.1f} (OI {o['call_wall']['oi']:,.0f}) — 만기({o['expiry'][5:]})까지 지지·저항 후보")
    if o.get("gex_bn") is not None:
        neg = o["gex_bn"] < 0
        L.append(f"감마 노출 근사 {o['gex_bn']:+,.0f}억/1% — " + ("음수: 딜러 헤지가 추세를 따라감 → 변동성 확대 구간(급락·급반등 모두 커짐)" if neg else
                                                         "양수: 딜러 헤지가 반대로 움직임 → 변동성 억제·박스권 경향"))
        if o.get("flip"):
            L.append(f"감마 전환점 ≈ {o['flip']:.1f} (현재 대비 {(o['flip']/S-1)*100:+.1f}%) — 이 위로 회복하면 변동성 진정 쪽")
    if o.get("atm_iv") and o.get("rv20"):
        vrp = o["atm_iv"] - o["rv20"]
        L.append(f"내재변동성(ATM) {o['atm_iv']*100:.0f}% vs 실현변동성(20일) {o['rv20']*100:.0f}% — " +
                 ("옵션이 실제 움직임보다 비쌈: 공포 프리미엄. 보험(풋) 사기엔 비싼 구간" if vrp > 0.05 else
                  "옵션이 실제 움직임보다 쌈: 시장이 변동성을 과소평가 — 헷지 사기엔 싼 구간" if vrp < -0.03 else "대체로 맞게 가격됨"))
    if o.get("skew") is not None:
        L.append(f"스큐(5% 외가 풋 IV − 콜 IV) {o['skew']*100:+.1f}%p — " + ("하락 보험 수요가 강함" if o["skew"] > 0.05 else "상방 콜 수요 쪽" if o["skew"] < 0 else "보통"))
    f = o.get("fut") or {}
    if f.get("basis") is not None:
        L.append(f"선물 베이시스 {f['basis']:+.2f}p — " + ("백워데이션: 선물이 현물보다 쌈, 매도 헤지 쏠림·차익 매수 유인" if f["basis"] < 0 else "콘탱고: 정상"))
    if o.get("max_pain"):   # 참고용 — 근거 약해 맨 뒤로 (텔레그램 상위 4줄에서 빠짐)
        L.append(f"(참고) 최대 고통 {o['max_pain']:.1f} — 옵션 매수자 손실이 최대인 만기 지수. '끌려간다'는 가설은 근거 약함, 매매 근거로 쓰지 말 것")
    return L


def build(backfill: int = 20) -> dict:
    d = date.today()
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    cur = None
    for _ in range(5):
        try:
            cur = _read(d)
        except Exception as e:  # noqa: BLE001
            log.warning("KRX 옵션 %s 실패: %s", d, e)
        if cur:
            break
        d -= timedelta(days=1)
        while d.weekday() >= 5:
            d -= timedelta(days=1)
    if not cur:
        log.warning("KRX 옵션 데이터 없음")
        return {}
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
    cur["asof"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    OUT.write_text(json.dumps(cur, ensure_ascii=False), encoding="utf-8")
    log.info("옵션 포지션: PCR %.2f GEX %s억 flip %s", cur.get("pcr_oi") or 0, cur.get("gex_bn"), cur.get("flip"))
    return cur


def load() -> dict:
    try:
        return json.loads(OUT.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
