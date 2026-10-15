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


def base_metrics(q: list[dict], shares: float) -> dict | None:
    """q: fin.quarterly(code).to_dicts() (원 단위). 주당 지표."""
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
        core, one_off = op * (1 - TAX) * min(max(own, 0), 1), True
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


def value(m: dict, price: float, sector: str | None, peers: dict) -> dict:
    """모델을 '현재 이익이 지속' / '사이클 평균으로 회귀' / '자산·배당' 세 묶음으로 나눠 낸다.
    범위가 넓으면 결론은 '어느 묶음이 맞나' = 이익이 유지되느냐로 귀결되므로, 시장이 반영한 지속 ROE(역산)를 함께 준다."""
    fin = any(k in (sector or "") for k in FIN_SECTORS)
    pm = peers.get(sector or "기타", {})
    eps, bps, roe, dps, fcfe = m.get("eps"), m.get("bps"), m.get("roe"), m.get("dps"), m.get("fcfe")
    rn = m.get("roe_norm")
    out: dict[str, dict] = {}

    def put(name, v, note, grp):
        if v is not None and v > 0 and v == v:
            out[name] = {"value": round(v, 0), "upside": round(v / price - 1, 3) if price else None, "note": note, "group": grp}

    ce = " (일회성 제외 핵심이익)" if m.get("one_off") else ""
    # ① 현재 이익 지속
    if eps and eps > 0 and pm.get("per"):
        put("상대 PER", eps * pm["per"], f"EPS {eps:,.0f}{ce} × 업종 PER {pm['per']:.1f}배", "current")
    if bps and roe is not None:
        put("PBR-ROE", bps * max(roe - G, 0) / (COE - G), f"ROE {roe*100:.1f}%{ce} 영구 유지 → 적정 PBR {max(roe-G,0)/(COE-G):.2f}배", "current")
        put("RIM", _rim(bps, roe, COE), f"ROE {roe*100:.1f}%{ce}가 10년간 COE {COE*100:.0f}%로 수렴", "current")
    if not fin and fcfe and fcfe > 0:
        g1 = max(min(m.get("rev_g") or 0.03, 0.15), -0.05)
        put("DCF(FCFE)", _dcf(fcfe, g1), f"FCFE {fcfe:,.0f}원, 5년 성장 {g1*100:.0f}% 후 {G*100:.0f}%", "current")
    # ② 사이클 평균으로 회귀 (이익 정상화)
    if bps and rn is not None:
        yrs = m.get("roe_years")
        put("정상화 PER", bps * rn * pm["per"] if pm.get("per") and rn > 0 else None,
            f"정상 EPS {bps*rn:,.0f} (BPS × 평균 ROE {rn*100:.1f}%) × 업종 PER", "normal")
        put("정상화 PBR-ROE", bps * max(rn - G, 0) / (COE - G), f"평균 ROE {rn*100:.1f}% 영구 → 적정 PBR {max(rn-G,0)/(COE-G):.2f}배", "normal")
        put("정상화 RIM", _rim(bps, rn, COE), f"최근 {yrs}년 평균 ROE {rn*100:.1f}% 기준", "normal")
    # ③ 자산·배당
    if bps and pm.get("pbr"):
        put("상대 PBR", bps * pm["pbr"], f"BPS {bps:,.0f} × 업종 PBR {pm['pbr']:.2f}배", "asset")
    if dps and (m.get("payout") or 0) >= 0.25:   # 배당성향이 낮은 성장주에 DDM 은 의미 없음
        put("DDM", dps * (1 + G) / (COE - G), f"DPS {dps:,.0f}원, 성장 {G*100:.0f}%", "asset")

    grp = {g: _med([v["value"] for v in out.values() if v["group"] == g]) for g in ("current", "normal", "asset")}
    flags = []
    ni_t, op_t = m.get("ni_ttm"), m.get("op_ttm")
    if m.get("one_off"):
        flags.append(f"순이익이 영업이익의 {ni_t/op_t:.1f}배 → 일회성(지분법·처분이익) 의심, 영업이익×(1−22%)로 바꿔 계산"
                     f" (보고 EPS {m['eps_reported']:,.0f} → 핵심 EPS {eps:,.0f})")
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
    res = {"models": out, "groups": {k: (round(v, 0) if v else None) for k, v in grp.items()},
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
        res["rim_sens"] = {f"{c*100:.0f}%": round(_rim(bps, roe, c), 0) for c in (0.08, 0.09, 0.10)}
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
