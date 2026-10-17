"""가치평가 6모델 (KR, DART 재무 기반). 숫자 하나가 아니라 '가정과 범위'를 보여 주는 게 목적.

공통 가정 (설명 가능하게 고정, 화면에 함께 표시)
- 자기자본비용(COE) 9% (무위험 3% + 위험프리미엄 6%), 민감도 8~10%
- 영구성장률 g 2%
- 주식 수 = 시가총액 / 종가 (KRX 상장 기준)
- TTM = 최근 4개 분기 합, BPS 는 최근 분기말 지배주주 자본

모델
1. 상대 PER   : TTM EPS × 같은 업종 중앙 PER
2. 상대 PBR   : BPS × 같은 업종 중앙 PBR
3. PBR-ROE    : BPS × (ROE − g)/(COE − g)   (지속 가능 ROE 가정의 고든 모형)
4. RIM        : BPS + 초과이익(ROE−COE)×BPS 를 10년에 걸쳐 COE 로 수렴시키며 할인
5. DDM        : 주당배당 × (1+g)/(COE − g)   (배당이 있을 때만)
6. DCF(FCFE)  : (영업현금흐름 − CAPEX) TTM 을 5년간 g1(매출 성장률, −5~15% 로 제한) 성장 후 g 로 영구 할인
+ 역DCF       : 현재 주가가 정당화되려면 FCFE 가 영구히 몇 % 성장해야 하는지

금융업(은행·보험·증권·기타금융)은 현금흐름 모델이 맞지 않아 PBR·PBR-ROE·RIM·DDM 만 쓴다.
"""
from __future__ import annotations

import logging
import statistics as st

log = logging.getLogger(__name__)
COE, G = 0.09, 0.02
FIN_SECTORS = ("은행", "보험", "증권", "기타금융", "금융")


def _ttm(q, key):
    vals = [r.get(key) for r in q[-4:]]
    return sum(vals) if len(vals) == 4 and all(v is not None for v in vals) else None


def _rim(bps: float, roe: float, coe: float, years: int = 10) -> float:
    v, b = bps, bps
    for t in range(1, years + 1):
        r_t = roe + (coe - roe) * t / years            # ROE 가 COE 로 선형 수렴
        v += (r_t - coe) * b / (1 + coe) ** t
        b *= 1 + r_t * 0.6                              # 이익의 60% 유보 가정
    return v


def _dcf(fcfe: float, g1: float, coe: float = COE, g: float = G, years: int = 5) -> float:
    v, f = 0.0, fcfe
    for t in range(1, years + 1):
        f *= 1 + g1
        v += f / (1 + coe) ** t
    tv = f * (1 + g) / (coe - g)
    return v + tv / (1 + coe) ** years


TAX = 0.22   # 일회성 의심 시 핵심이익 = 영업이익 × (1 − 법인세율)


def base_metrics(q: list[dict], shares: float, tax: float = TAX) -> dict | None:
    """q: fin.quarterly(code).to_dicts() (원 단위, US 는 USD). 주당 지표. tax: 일회성 보정용 법인세율(KR 22%, US 21%)."""
    if not q or not shares or len(q) < 4:
        return None
    last = q[-1]
    ni_rep = _ttm(q, "ni_owner") or _ttm(q, "ni")
    op = _ttm(q, "op")
    eq = last.get("equity_owner") or last.get("equity")
    # 일회성 보정: 순이익이 영업이익보다 15% 넘게 크면 (지분법·처분이익 등) 핵심이익 = 영업이익×(1−세율)
    core = ni_rep
    one_off = False
    if ni_rep is not None and op is not None and op > 0 and ni_rep > op * 1.15:
        own = (_ttm(q, "ni_owner") or ni_rep) / (_ttm(q, "ni") or ni_rep) if _ttm(q, "ni") else 1.0
        core, one_off = op * (1 - tax) * min(max(own, 0), 1), True
    rev = _ttm(q, "revenue")
    rev_prev = sum(r.get("revenue") or 0 for r in q[-8:-4]) if len(q) >= 8 else None
    cfo, capex, div = _ttm(q, "cfo"), _ttm(q, "capex"), _ttm(q, "div_paid")
    hist = _roe_hist(q)
    return {"eps": core / shares if core is not None else None, "eps_reported": ni_rep / shares if ni_rep is not None else None,
            "bps": eq / shares if eq else None,
            "roe": core / eq if core is not None and eq else None,
            "roe_reported": ni_rep / eq if ni_rep is not None and eq else None, "one_off": one_off,
            "dps": abs(div) / shares if div else None,
            "fcfe": (cfo - abs(capex)) / shares if cfo is not None and capex is not None else None,
            "rev_g": (rev / rev_prev - 1) if rev and rev_prev else None, "period": last.get("period"),
            "payout": abs(div) / ni_rep if div and ni_rep and ni_rep > 0 else None,
            "ni_ttm": ni_rep, "op_ttm": op,
            "roe_norm": (sum(hist) / len(hist)) if len(hist) >= 3 else None,
            "roe_min": min(hist) if hist else None, "roe_max": max(hist) if hist else None,
            "roe_years": round((len(hist) + 3) / 4, 1),
            "fscore": _fscore(q), "dupont": _dupont(q)}


def _roe_hist(q: list[dict]) -> list[float]:
    """분기 단위로 굴린 4분기 ROE 목록 (최대 5년). 사이클 평균(Damodaran 식 이익 정상화)·고저 판단용."""
    out = []
    for i in range(len(q) - 4, -1, -1):
        w = q[i:i + 4]
        ni = _sum4(w, "ni_owner") or _sum4(w, "ni")
        eq = w[-1].get("equity_owner") or w[-1].get("equity")
        if ni is not None and eq and eq > 0:
            out.append(ni / eq)
        if len(out) >= 17:   # ≈ 5년
            break
    return out


def _sum4(rows, key):
    v = [r.get(key) for r in rows]
    return sum(v) if len(v) == 4 and all(x is not None for x in v) else None


def _fscore(q: list[dict]) -> dict | None:
    """Piotroski F-score 변형 (DART 항목으로 가능한 7개). 높을수록 재무 개선."""
    if len(q) < 8:
        return None
    cur, prev = q[-4:], q[-8:-4]
    ni, ni0 = _sum4(cur, "ni"), _sum4(prev, "ni")
    cfo = _sum4(cur, "cfo")
    a, a0 = cur[-1].get("assets"), prev[-1].get("assets")
    l, l0 = cur[-1].get("liab"), prev[-1].get("liab")
    rev, rev0 = _sum4(cur, "revenue"), _sum4(prev, "revenue")
    op, op0 = _sum4(cur, "op"), _sum4(prev, "op")
    tests = {
        "ROA 흑자": ni is not None and a and ni / a > 0,
        "영업현금흐름 흑자": cfo is not None and cfo > 0,
        "ROA 개선": None not in (ni, ni0) and a and a0 and ni / a > ni0 / a0,
        "현금흐름 > 순이익(이익의 질)": None not in (cfo, ni) and cfo > ni,
        "부채비율 하락": a and a0 and l is not None and l0 is not None and l / a < l0 / a0,
        "영업이익률 개선": rev and rev0 and op is not None and op0 is not None and op / rev > op0 / rev0,
        "자산회전율 개선": rev and rev0 and a and a0 and rev / a > rev0 / a0,
    }
    tests = {k: bool(v) for k, v in tests.items()}
    return {"score": sum(tests.values()), "max": len(tests), "tests": tests}


def _dupont(q: list[dict]) -> dict | None:
    ni, rev = _sum4(q[-4:], "ni"), _sum4(q[-4:], "revenue")
    a, e = q[-1].get("assets"), q[-1].get("equity")
    if not (ni is not None and rev and a and e and e > 0):
        return None
    return {"margin": round(ni / rev, 4), "turnover": round(rev / a, 3), "leverage": round(a / e, 2)}


BPS_MODELS = ("PBR-ROE", "RIM", "정상화 PER", "정상화 PBR-ROE", "정상화 RIM", "상대 PBR")


def peer_multiples(rows: list[dict]) -> dict[str, dict]:
    """rows: [{sector, per, pbr}] → 업종별 중앙값 (표본 5개 이상, 극단값 제외)."""
    by: dict[str, dict[str, list[float]]] = {}
    for r in rows:
        d = by.setdefault(r["sector"] or "기타", {"per": [], "pbr": []})
        if r.get("per") and 2 < r["per"] < 80:
            d["per"].append(r["per"])
        if r.get("pbr") and 0.1 < r["pbr"] < 15:
            d["pbr"].append(r["pbr"])
    return {s: {"per": st.median(d["per"]) if len(d["per"]) >= 5 else None,
                "pbr": st.median(d["pbr"]) if len(d["pbr"]) >= 5 else None,
                "n": max(len(d["per"]), len(d["pbr"]))} for s, d in by.items()}


def _med(xs):
    xs = [x for x in xs if x is not None]
    return st.median(xs) if xs else None


def value(m: dict, price: float, sector: str | None, peers: dict, coe: float = COE, g: float = G,
          currency: str = "KRW", fin_sectors: tuple = FIN_SECTORS, tax: float = TAX, outlier: float | None = None) -> dict:
    """모델을 '현재 이익이 지속' / '사이클 평균으로 회귀' / '자산·배당' 세 묶음으로 나눠 낸다.
    범위가 넓으면 결론은 '어느 묶음이 맞나' = 이익이 유지되느냐로 귀결되므로, 시장이 반영한 지속 ROE(역산)를 함께 준다."""
    fin = any(k in (sector or "") for k in fin_sectors)
    usd = currency == "USD"
    dec = 2 if usd else 0
    fm = (lambda x: f"${x:,.2f}") if usd else (lambda x: f"{x:,.0f}")       # 주당 금액 표기
    fw = (lambda x: f"${x:,.2f}") if usd else (lambda x: f"{x:,.0f}원")
    pc = lambda x: f"{x*100:.1f}".rstrip("0").rstrip(".")                  # 9.0→9, 10.1→10.1 (KR 표기 유지)
    COE, G = coe, g   # noqa: N806 — 아래 식은 그대로, 시장별 가정만 바꿔 끼운다
    pm = peers.get(sector or "기타", {})
    eps, bps, roe, dps, fcfe = m.get("eps"), m.get("bps"), m.get("roe"), m.get("dps"), m.get("fcfe")
    rn = m.get("roe_norm")
    out: dict[str, dict] = {}

    def put(name, v, note, grp):
        if v is not None and v > 0 and v == v:
            out[name] = {"value": round(v, dec), "upside": round(v / price - 1, 3) if price else None, "note": note, "group": grp}

    ce = " (일회성 제외 핵심이익)" if m.get("one_off") else ""
    # ① 현재 이익 지속
    if eps and eps > 0 and pm.get("per"):
        put("상대 PER", eps * pm["per"], f"EPS {fm(eps)}{ce} × 업종 PER {pm['per']:.1f}배", "current")
    if bps and roe is not None:
        put("PBR-ROE", bps * max(roe - G, 0) / (COE - G), f"ROE {roe*100:.1f}%{ce} 영구 유지 → 적정 PBR {max(roe-G,0)/(COE-G):.2f}배", "current")
        put("RIM", _rim(bps, roe, COE), f"ROE {roe*100:.1f}%{ce}가 10년간 COE {pc(COE)}%로 수렴", "current")
    if not fin and fcfe and fcfe > 0:
        g1 = max(min(m.get("rev_g") or 0.03, 0.15), -0.05)
        put("DCF(FCFE)", _dcf(fcfe, g1, COE, G), f"FCFE {fw(fcfe)}, 5년 성장 {g1*100:.0f}% 후 {pc(G)}%", "current")
    # ② 사이클 평균으로 회귀 (이익 정상화)
    if bps and rn is not None:
        yrs = m.get("roe_years")
        put("정상화 PER", bps * rn * pm["per"] if pm.get("per") and rn > 0 else None,
            f"정상 EPS {fm(bps*rn)} (BPS × 평균 ROE {rn*100:.1f}%) × 업종 PER", "normal")
        put("정상화 PBR-ROE", bps * max(rn - G, 0) / (COE - G), f"평균 ROE {rn*100:.1f}% 영구 → 적정 PBR {max(rn-G,0)/(COE-G):.2f}배", "normal")
        put("정상화 RIM", _rim(bps, rn, COE), f"최근 {yrs}년 평균 ROE {rn*100:.1f}% 기준", "normal")
    # ③ 자산·배당
    if bps and pm.get("pbr"):
        put("상대 PBR", bps * pm["pbr"], f"BPS {fm(bps)} × 업종 PBR {pm['pbr']:.2f}배", "asset")
    if dps and (m.get("payout") or 0) >= 0.25:   # 배당성향이 낮은 성장주에 DDM 은 의미 없음
        put("DDM", dps * (1 + G) / (COE - G), f"DPS {fw(dps)}, 성장 {pc(G)}%", "asset")

    flags = []
    excluded: dict[str, dict] = {}
    if outlier and price:   # 이상치 가드 (US): 자본 과소(PBR>100)면 BPS 기반 모델 전부, 그리고 현재가의 1/outlier~outlier 배 밖 모델은 범위에서 뺀다
        if bps and bps > 0 and price / bps > 100:
            for k in [k for k in out if k in BPS_MODELS]:
                excluded[k] = out.pop(k)
            flags.append(f"PBR {price/bps:.0f}배(>100) — 자본 과소(자사주 매입 등) → BPS 기반 모델 범위에서 제외")
        far = [k for k, x in out.items() if not (price / outlier <= x["value"] <= price * outlier)]
        for k in far:
            excluded[k] = out.pop(k)
        if far:
            flags.append(f"이상치 제외: {', '.join(far)} (현재가의 1/{outlier:.0f}~{outlier:.0f}배 밖)")
    grp = {g: _med([v["value"] for v in out.values() if v["group"] == g]) for g in ("current", "normal", "asset")}
    ni_t, op_t = m.get("ni_ttm"), m.get("op_ttm")
    if m.get("one_off"):
        flags.append(f"순이익이 영업이익의 {ni_t/op_t:.1f}배 → 일회성(지분법·처분이익) 의심, 영업이익×(1−{pc(tax)}%)로 바꿔 계산"
                     f" (보고 EPS {fm(m['eps_reported'])} → 핵심 EPS {fm(eps)})")
    cyc = None
    if roe is not None and rn is not None and rn > 0:
        cyc = roe / rn
        if cyc > 1.5 and roe > 0.12:
            flags.append(f"현재 ROE {roe*100:.0f}% = {m.get('roe_years')}년 평균 {rn*100:.0f}%의 {cyc:.1f}배 → 고점 이익 구간. '현재 이익 지속' 묶음은 상단으로만 볼 것")
        elif cyc < 0.6:
            flags.append(f"현재 ROE {roe*100:.0f}% < 평균 {rn*100:.0f}% → 저점 이익 구간. '정상화' 묶음이 회복 시 가치")
    if (m.get("rev_g") or 0) > 0.15 and fcfe and fcfe > 0:
        flags.append(f"매출 성장 {m['rev_g']*100:.0f}% → DCF 성장률은 15%로 제한")

    # 시장이 반영한 지속 ROE: P/B = (ROE − g)/(COE − g) 를 ROE 로 풀기
    implied_roe = (price / bps) * (COE - G) + G if price and bps and bps > 0 else None
    verdict = None
    if implied_roe is not None and roe is not None:
        where = ("현재 ROE보다 높음 — 이익이 더 늘어야 정당화" if implied_roe > roe else
                 "평균 ROE보다 낮음 — 사이클 평균만 돼도 싸다" if rn is not None and implied_roe < rn else
                 "평균과 현재 사이 — 현재 이익이 얼마나 유지되느냐에 달림")
        verdict = (f"주가는 지속 ROE {implied_roe*100:.1f}%를 반영 (현재 {roe*100:.1f}%"
                   + (f" · {m.get('roe_years')}년 평균 {rn*100:.1f}% · 범위 {m['roe_min']*100:.0f}~{m['roe_max']*100:.0f}%" if rn is not None else "")
                   + f") → {where}")
        if rn is not None and rn < implied_roe < roe:
            keep = (implied_roe - rn) / (roe - rn)   # 0 = 평균 회귀, 1 = 현재 유지
            verdict += f". 평균 대비 지금의 초과 ROE 중 {keep*100:.0f}%가 영구 유지된다고 가정하는 가격"
    vals = [v["value"] for v in out.values()]
    res = {"models": out, **({"excluded": excluded} if excluded else {}), "groups": {k: (round(v, dec) if v else None) for k, v in grp.items()},
           "group_upside": {k: (round(v / price - 1, 3) if v and price else None) for k, v in grp.items()},
           "flags": flags, "verdict": verdict, "implied_roe": round(implied_roe, 4) if implied_roe is not None else None,
           "cycle": round(cyc, 2) if cyc is not None else None,
           "fscore": m.get("fscore"), "dupont": m.get("dupont"),
           "roe": round(roe, 4) if roe is not None else None,
           "roe_reported": round(m["roe_reported"], 4) if m.get("roe_reported") is not None else None,
           "roe_norm": round(rn, 4) if rn is not None else None,
           "roe_min": round(m["roe_min"], 4) if m.get("roe_min") is not None else None,
           "roe_max": round(m["roe_max"], 4) if m.get("roe_max") is not None else None,
           "assumptions": {"coe": COE, "g": G, "period": m.get("period"), "financial_sector": fin,
                           "payout": round(m["payout"], 3) if m.get("payout") else None, "roe_years": m.get("roe_years")}}
    if vals:
        res["range"] = {"low": min(vals), "mid": st.median(vals), "high": max(vals),
                        "mid_upside": round(st.median(vals) / price - 1, 3) if price else None}
    if bps and roe is not None:
        res["rim_sens"] = {f"{pc(c)}%": round(_rim(bps, roe, c), dec) for c in (COE - 0.01, COE, COE + 0.01)}
    if not fin and fcfe and fcfe > 0 and price:
        res["implied_g"] = round((COE * price - fcfe) / (price + fcfe), 4)
    if price and eps and eps > 0:
        res["per"] = round(price / eps, 1)
    if price and m.get("eps_reported") and m["eps_reported"] > 0:
        res["per_reported"] = round(price / m["eps_reported"], 1)
    if price and bps:
        res["pbr"] = round(price / bps, 2)
    return res


def kr_all(prices: dict[str, float]) -> dict[str, dict]:
    """KR 전 종목 가치평가. prices: {code: 현재가}. 주식 수 = 유니버스 시총 / 유니버스 갱신 시점 종가 근사."""
    import polars as pl
    from . import fin, universe
    from .config import UNIVERSE_DIR
    u = pl.read_csv(UNIVERSE_DIR / "kr.csv", schema_overrides={"symbol": pl.Utf8})
    mcap = {r["symbol"]: r["mcap"] for r in u.select("symbol", "mcap").to_dicts() if r["mcap"]}
    try:
        sector = universe.kr_sectors() or {}
    except Exception as e:  # noqa: BLE001
        log.warning("업종 실패: %s", e)
        sector = {}
    try:
        from .shares import shares_map
        sh = shares_map()
    except Exception as e:  # noqa: BLE001
        log.warning("주식 수 실패: %s", e)
        sh = {}
    base: dict[str, dict] = {}
    src: dict[str, dict] = {}
    for code, p in prices.items():
        if not p:
            continue
        s0 = sh.get(code)
        if s0:
            n, info = s0["n"], s0
        elif code in mcap:
            n, info = mcap[code] / p, {"src": "시가총액 ÷ 종가 근사 (DART 주식 수 수집 전)"}
        else:
            continue
        q = fin.quarterly(code)
        if q is None or q.is_empty():
            continue
        m = base_metrics(q.to_dicts(), n)
        if m:
            base[code], src[code] = m, {k: v for k, v in info.items() if k != "n"} | {"shares": n}
    peers = peer_multiples([{"sector": sector.get(c), "per": prices[c] / m["eps"] if m.get("eps") and m["eps"] > 0 else None,
                             "pbr": prices[c] / m["bps"] if m.get("bps") and m["bps"] > 0 else None} for c, m in base.items()])
    out = {}
    for c, m in base.items():
        try:
            v = value(m, prices[c], sector.get(c), peers)
            v["sector"] = sector.get(c)
            v["peer"] = peers.get(sector.get(c) or "기타")
            v["shares"] = src.get(c)
            out[c] = v
        except Exception as e:  # noqa: BLE001
            log.warning("가치평가 %s 실패: %s", c, e)
    log.info("가치평가 %d종목", len(out))
    return out


# ───────────── US (SEC 재무, USD) — KR 과 가정이 다르다 ─────────────
# COE = 미 10년 금리(reports/live.json US10Y, 없으면 bonds.json) + ERP. 베타 1 가정(종목별 베타 미반영).
US_ERP = 0.05            # [가정] Damodaran 2026-01 implied ERP 4.23% (BVR 2차 인용, 원문 스프레드시트 미확인) 보다 0.8%p 보수적
US_G = 0.025             # [가정] 영구 명목성장 2.5% (미 장기 실질 ~1.8% + 물가 목표 2% 의 하단 절충). KR 2% 보다 높음
US_RF_FALLBACK = 0.045   # 금리 파일이 없을 때만 — flags 에 '금리 데이터 없음' 표시
US_TAX = 0.21            # 일회성 보정 세율: 미 연방 법인세 21% [가정: 주세 제외]
US_FIN_SECTORS = ("금융",)   # universe/us_sector.csv (GICS 11섹터 한글). 은행·보험·증권 + 결제(V·MA)까지 포함 → 현금흐름 모델 제외
US_OUTLIER = 20.0        # 모델값이 현재가의 1/20~20배 밖이면 범위에서 제외
US_CYCLICAL = {"MU", "SNDK", "WDC", "STX", "NVDA", "AMD", "AVGO", "TSM", "INTC", "QCOM", "ARM", "MRVL", "TXN", "ADI",
               "MCHP", "NXPI", "ON", "MPWR", "TER", "SWKS", "QRVO", "ENTG", "AMAT", "LRCX", "KLAC", "ASML"}   # 반도체·메모리
US_CYCLICAL_SECTORS = ("소재", "에너지")
NORM_MIN_Q = 20          # 데이터로 평균 순이익률을 낼 최소 분기(5년). 미달이면 아래 수기 값 → 없으면 ROE 정상화
NORM_MARGIN = {          # 사람이 10-K 로 모은 장기 평균 순이익률 (docs/valuation_notes/2026-10-17_memory.md §2)
    "MU": (0.188, "FY2016~FY2025 10년 평균 순이익률 (메모리 노트 §2, 공시·검증전)"),
    "SNDK": (0.138, "구 SanDisk FY2012~2014 3년 평균 (메모리 노트 §2, 검증전 — 가장 약한 숫자)"),
}
COMMON_ASSUMPTION = ("상대 PER·PBR-ROE·RIM·DCF 는 모두 '최근 TTM 이익(ROE)이 지속된다'는 같은 전제를 공유 — 서로 독립된 확인이 아니다."
                     " 반대 전제는 '정상화' 묶음과 cycle_view")


def us_rf() -> tuple[float, str]:
    """미 10년 금리(소수)와 출처. 실패하면 (US_RF_FALLBACK, '데이터 없음(…)')."""
    try:
        from . import valuation_daily as vd
        r = vd.rates()
        if r.get("us10y") is not None:
            return float(r["us10y"]) / 100, f"US10Y {float(r['us10y']):.2f}% ({'live.json' if r.get('us10y_live') else 'bonds.json'} {r.get('us10y_date') or ''})".strip()
    except Exception as e:  # noqa: BLE001
        log.warning("미 10Y 실패: %s", e)
        return US_RF_FALLBACK, f"데이터 없음({e}) → {US_RF_FALLBACK*100:.1f}% 가정"
    return US_RF_FALLBACK, f"데이터 없음(US10Y 미수집) → {US_RF_FALLBACK*100:.1f}% 가정"


def _contiguous(q: list[dict], max_days: int = 300) -> bool:
    """최근 4분기의 첫·끝 분기말 간격이 max_days 이하 = 분기가 빠지지 않음 (TTM 이 진짜 12개월)."""
    from datetime import date
    try:
        a, b = date.fromisoformat(str(q[-4]["end"])), date.fromisoformat(str(q[-1]["end"]))
        return (b - a).days <= max_days
    except Exception:  # noqa: BLE001
        return True   # end 가 없는 합성 데이터 등은 판단 보류


def cycle_view(q: list[dict], m: dict, price: float, shares: float, ticker: str | None = None) -> dict | None:
    """사이클 업종: '최근 이익률 지속' vs '정규화(장기 평균 순이익률 × 현재 매출)' PER 을 나란히.
    정규화 이익 = 평균 순이익률 × TTM 매출(범위 위쪽 PER) / × 최근 분기 매출×4(아래쪽). 매출이 없으면 BPS × 평균 ROE 로 대체."""
    if not price or not shares:
        return None
    mcap = price * shares
    l4 = q[-4:]
    ni_t = _sum4(l4, "ni")
    rev_t = _sum4(l4, "revenue")
    ni_l, rev_l = q[-1].get("ni"), q[-1].get("revenue")
    per = lambda e: round(mcap / e, 1) if e and e > 0 else None   # noqa: E731
    cur = {"per_ttm": per(ni_t), "per_runrate": per(ni_l * 4 if ni_l is not None else None),
           "margin_ttm": round(ni_t / rev_t, 4) if ni_t is not None and rev_t else None,
           "margin_last": round(ni_l / rev_l, 4) if ni_l is not None and rev_l else None}
    hist = [r for r in q if r.get("ni") is not None and r.get("revenue")]
    norm: dict = {}
    if rev_t and len(hist) >= NORM_MIN_Q:
        h = hist[-40:]
        mg = sum(r["ni"] for r in h) / sum(r["revenue"] for r in h)
        norm = {"method": "margin", "margin": round(mg, 4), "src": f"SEC 분기 {len(h)}개 순이익 합 ÷ 매출 합 ({h[0].get('period')}~{h[-1].get('period')})"}
    elif rev_t and ticker in NORM_MARGIN:
        mg, src = NORM_MARGIN[ticker]
        norm = {"method": "margin", "margin": mg, "src": src}
    if norm:
        mg = norm["margin"]
        norm["per_high"] = per(mg * rev_t)                                    # TTM 매출 기준 → PER 높게
        norm["per_low"] = per(mg * rev_l * 4) if rev_l else None              # 최근 분기×4 매출 → PER 낮게
    elif m.get("bps") and m.get("roe_norm") and m["roe_norm"] > 0:   # 매출 없음 → ROE 정상화 (수기 이익률은 매출이 있어야 적용)
        e = m["bps"] * m["roe_norm"]
        norm = {"method": "roe", "roe_norm": round(m["roe_norm"], 4), "per_high": round(price / e, 1), "per_low": None,
                "src": f"매출 항목 없음 → BPS × {m.get('roe_years')}년 평균 ROE {m['roe_norm']*100:.1f}% (SEC 분기)"}
    if not any(cur.values()) and not norm:
        return None
    P = lambda x: "—" if x is None else f"{x*100:.0f}%"   # noqa: E731
    rng = lambda a, b: "—" if a is None and b is None else (f"{a}" if b is None else f"{b} ~ {a}" if a is not None else f"{b}")   # noqa: E731
    lines = [f"최근 이익률 지속 가정: PER {rng(cur['per_ttm'], cur['per_runrate'])} (최근 분기×4 ~ TTM)"
             f" · 순이익률 TTM {P(cur['margin_ttm'])} / 최근 분기 {P(cur['margin_last'])}"]
    if norm.get("method") == "margin":
        lines.append(f"정규화 가정: PER {rng(norm['per_high'], norm.get('per_low'))} (평균 순이익률 {P(norm['margin'])} × 현재 매출) — {norm['src']}")
    elif norm:
        lines.append(f"정규화 가정: PER {norm['per_high']} — {norm['src']}")
        if ticker in NORM_MARGIN:
            norm["manual_margin"] = NORM_MARGIN[ticker][0]
            lines.append(f"수기 평균 순이익률 {NORM_MARGIN[ticker][0]*100:.1f}%({NORM_MARGIN[ticker][1]})는 SEC 매출 태그가 없어 자동 적용 못 함 — 노트 수동 계산값 참고")
    return {"current": cur, "normal": norm or None, "lines": lines}


def _us_stub(flags: list[str], sector: str | None) -> dict:
    return {"models": {}, "flags": flags, "currency": "USD", "sector": sector, "quality": {"verified": False}}


def us_all(prices: dict[str, float], verified: dict | None = None, rf: tuple[float, str] | None = None) -> dict[str, dict]:
    """US 전 종목 가치평가 (USD 그대로, 원화 환산 없음). prices: {ticker: 종가 USD}.
    재무 = data/fin/us_quarterly.parquet (SEC companyfacts) → valuation_daily.us_quarters 로 분기 dict.
    주식 수 = SEC 최근 shares 우선, 없거나 시총/종가와 2배 넘게 어긋나면 universe/us.csv 시총 ÷ 종가."""
    import json
    import polars as pl
    from . import valuation_daily as vd
    from .config import UNIVERSE_DIR
    from .sec import OUT
    if not OUT.exists():
        log.warning("US 가치평가: %s 없음 (데이터 없음)", OUT)
        return {}
    df = pl.read_parquet(OUT)
    parts = {k[0] if isinstance(k, tuple) else k: g for k, g in df.partition_by("ticker", as_dict=True).items()}
    try:
        sec_map = dict(pl.read_csv(UNIVERSE_DIR / "us_sector.csv").select("yf", "sector").iter_rows())
    except Exception as e:  # noqa: BLE001
        log.warning("US 업종 실패: %s", e)
        sec_map = {}
    try:
        u = pl.read_csv(UNIVERSE_DIR / "us.csv", infer_schema_length=0)
        mcap = {r["symbol"]: float(r["mcap"]) for r in u.select("symbol", "mcap").to_dicts() if r["mcap"]}
    except Exception as e:  # noqa: BLE001
        log.warning("US 시총 실패: %s", e)
        mcap = {}
    if verified is None:
        try:
            verified = json.loads((UNIVERSE_DIR / "fin_verified.json").read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            verified = {}
    rf_v, rf_src = rf or us_rf()
    coe = rf_v + US_ERP
    base: dict[str, tuple] = {}
    out: dict[str, dict] = {}
    for t, p in prices.items():
        if not p or t not in parts:
            continue
        sector = sec_map.get(t)
        q, sh = vd.us_quarters(t, n=40, df=parts[t])
        flags: list[str] = []
        ok = True
        n_mc = mcap[t] / p if mcap.get(t) else None
        if sh and n_mc and not 0.5 <= sh / n_mc <= 2:
            flags.append(f"SEC 주식 수 {sh/1e6:,.0f}M 이 시총÷종가 {n_mc/1e6:,.0f}M 와 2배 넘게 어긋남(주식 분할·종류주) → 시총÷종가 사용")
            sh = None
        if sh:
            n, info = sh, {"src": "SEC CommonStockSharesOutstanding 최근값", "shares": sh}
        elif n_mc:
            n, info = n_mc, {"src": "시가총액 ÷ 종가 근사 (SEC 주식 수 없음)", "shares": n_mc}
        else:
            out[t] = _us_stub(["주식 수 없음(SEC·시총 모두 없음) → 가치평가 생략"], sector)
            continue
        if len(q) < 4:
            out[t] = _us_stub([f"검증전: SEC 분기 {len(q)}개 (4개 미만) → TTM 불가, 모델 생략"], sector)
            continue
        if not _contiguous(q):
            ok = False
            flags.append(f"검증전: 최근 4분기 불연속({q[-4].get('end')}~{q[-1].get('end')}) → TTM 이 12개월이 아닐 수 있음")
        smell = vd.cumulative_smell(q)
        if smell:
            src = vd.externally_verified(q, t, verified)
            if src:
                flags.append(f"{smell} 4분기 급증 = 누적치 의심이었으나 원문 대조 일치({src}) → 해제")
            else:
                ok = False
                flags.append(f"검증전: {smell} 4분기 연속 {vd.CUM_RATIO}배↑ (누적치 의심, universe/fin_verified.json 대조 전)")
        eq = q[-1].get("equity")
        if eq is not None and eq <= 0:
            ok = False
            flags.append("검증전: 자본 음수 → BPS·ROE 기반 모델 의미 없음")
        if all(r.get("revenue") is None for r in q[-4:]):
            flags.append("매출 태그 미수집(SEC) → 매출 성장·듀폰·정규화 이익률 생략")
        m = base_metrics(q, n, tax=US_TAX)
        if not m:
            out[t] = _us_stub(flags + ["검증전: 기본 지표 계산 불가"], sector)
            continue
        base[t] = (m, info, flags, ok, q, n, sector)
    # 업종 중앙 배수: 검증 통과 종목만 (오염 방지)
    peers = peer_multiples([{"sector": b[6], "per": prices[t] / b[0]["eps"] if b[0].get("eps") and b[0]["eps"] > 0 else None,
                             "pbr": prices[t] / b[0]["bps"] if b[0].get("bps") and b[0]["bps"] > 0 else None}
                            for t, b in base.items() if b[3]])
    for t, (m, info, flags, ok, q, n, sector) in base.items():
        try:
            v = value(m, prices[t], sector, peers, coe=coe, g=US_G, currency="USD", fin_sectors=US_FIN_SECTORS,
                      tax=US_TAX, outlier=US_OUTLIER)
        except Exception as e:  # noqa: BLE001
            log.warning("US 가치평가 %s 실패: %s", t, e)
            continue
        fin = v["assumptions"]["financial_sector"]
        extra = []
        if m.get("eps") is not None and m["eps"] <= 0:
            extra.append("TTM 적자(PER<0) → 이익 기반 모델(상대 PER·DCF) 제외")
        if fin:
            extra.append("금융업: DCF(FCFE)·역DCF 제외. 순이익은 우선주 배당 미차감 [가정] → EPS 소폭 과대")
        elif m.get("fcfe") is None:
            extra.append("영업현금흐름·CAPEX 분기 누락(SEC) → DCF(FCFE)·역DCF 생략")
        if m.get("dps") is None and any(r.get("div_paid") for r in q[-4:]):
            extra.append("배당 지급 분기 누락(SEC) → DDM 생략")
        v["flags"] = flags + extra + v["flags"] + [COMMON_ASSUMPTION]
        if not ok and v.get("verdict"):
            v["verdict"] = "(검증전) " + v["verdict"]
        v["currency"] = "USD"
        v["quality"] = {"verified": ok, "n_quarters": len(q), "last_end": q[-1].get("end")}
        v["assumptions"].update({"rf": round(rf_v, 4), "rf_src": rf_src, "erp": US_ERP, "beta": 1.0, "tax": US_TAX,
                                 "erp_src": "[가정] 5.0% — Damodaran 2026-01 implied 4.23%(2차 인용)보다 보수적"})
        v["sector"] = sector
        v["peer"] = peers.get(sector or "기타")
        v["shares"] = info
        if (t in US_CYCLICAL or any(s in (sector or "") for s in US_CYCLICAL_SECTORS)) and not fin:
            cv = cycle_view(q, m, prices[t], n, t)
            if cv:
                v["cycle_view"] = cv
        out[t] = v
    log.info("US 가치평가 %d종목 (검증전 %d)", len(out), sum(1 for x in out.values() if not (x.get("quality") or {}).get("verified")))
    return out
