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


def base_metrics(q: list[dict], shares: float) -> dict | None:
    """q: fin.quarterly(code).to_dicts() (원 단위). 주당 지표."""
    if not q or not shares or len(q) < 4:
        return None
    last = q[-1]
    ni = _ttm(q, "ni_owner") or _ttm(q, "ni")
    eq = last.get("equity_owner") or last.get("equity")
    rev = _ttm(q, "revenue")
    rev_prev = sum(r.get("revenue") or 0 for r in q[-8:-4]) if len(q) >= 8 else None
    cfo, capex, div = _ttm(q, "cfo"), _ttm(q, "capex"), _ttm(q, "div_paid")
    return {"eps": ni / shares if ni is not None else None, "bps": eq / shares if eq else None,
            "roe": ni / eq if ni is not None and eq else None,
            "dps": abs(div) / shares if div else None,
            "fcfe": (cfo - abs(capex)) / shares if cfo is not None and capex is not None else None,
            "rev_g": (rev / rev_prev - 1) if rev and rev_prev else None, "period": last.get("period"),
            "payout": abs(div) / ni if div and ni and ni > 0 else None,
            "ni_ttm": ni, "op_ttm": _ttm(q, "op"),
            "roe_norm": _roe_norm(q), "fscore": _fscore(q), "dupont": _dupont(q)}


def _sum4(rows, key):
    v = [r.get(key) for r in rows]
    return sum(v) if len(v) == 4 and all(x is not None for x in v) else None


def _roe_norm(q: list[dict]) -> float | None:
    """사이클 평균 ROE (Damodaran 식 이익 정상화): 가능한 모든 4분기 구간 ROE 의 평균 (최대 3년)."""
    out = []
    for i in range(len(q) - 4, -1, -1):
        w = q[i:i + 4]
        ni = _sum4(w, "ni_owner") or _sum4(w, "ni")
        eq = w[-1].get("equity_owner") or w[-1].get("equity")
        if ni is not None and eq and eq > 0:
            out.append(ni / eq)
        if len(out) >= 9:   # 분기 단위 이동 9개 ≈ 3년
            break
    return sum(out) / len(out) if len(out) >= 3 else None


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


def value(m: dict, price: float, sector: str | None, peers: dict) -> dict:
    fin = any(k in (sector or "") for k in FIN_SECTORS)
    pm = peers.get(sector or "기타", {})
    eps, bps, roe, dps, fcfe = m.get("eps"), m.get("bps"), m.get("roe"), m.get("dps"), m.get("fcfe")
    out: dict[str, dict] = {}

    def put(name, v, note):
        if v is not None and v > 0 and v == v:
            out[name] = {"value": round(v, 0), "upside": round(v / price - 1, 3) if price else None, "note": note}

    if eps and eps > 0 and pm.get("per"):
        put("상대 PER", eps * pm["per"], f"EPS {eps:,.0f} × 업종 PER {pm['per']:.1f}배")
    if bps and pm.get("pbr"):
        put("상대 PBR", bps * pm["pbr"], f"BPS {bps:,.0f} × 업종 PBR {pm['pbr']:.2f}배")
    if bps and roe is not None:
        put("PBR-ROE", bps * max(roe - G, 0) / (COE - G), f"ROE {roe*100:.1f}% → 적정 PBR {max(roe-G,0)/(COE-G):.2f}배")
        put("RIM", _rim(bps, roe, COE), f"ROE {roe*100:.1f}%가 10년간 COE {COE*100:.0f}%로 수렴")
    rn = m.get("roe_norm")
    if bps and rn is not None and roe is not None and abs(rn - roe) > 0.02:
        put("정상화 RIM", _rim(bps, rn, COE), f"사이클 평균 ROE {rn*100:.1f}% 기준 (현재 {roe*100:.1f}%)")
    if dps and (m.get("payout") or 0) >= 0.25:   # 배당성향이 낮은 성장주에 DDM 은 의미 없음
        put("DDM", dps * (1 + G) / (COE - G), f"DPS {dps:,.0f}원, 성장 {G*100:.0f}%")
    if not fin and fcfe and fcfe > 0:
        g1 = max(min(m.get("rev_g") or 0.03, 0.15), -0.05)
        put("DCF(FCFE)", _dcf(fcfe, g1), f"FCFE {fcfe:,.0f}원, 5년 성장 {g1*100:.0f}% 후 {G*100:.0f}%")
    vals = [v["value"] for v in out.values()]
    flags = []
    ni_t, op_t = m.get("ni_ttm"), m.get("op_ttm")
    if not fin and ni_t and op_t and op_t > 0 and ni_t > op_t * 1.15:
        flags.append(f"순이익이 영업이익의 {ni_t/op_t:.1f}배 — 일회성(지분법·처분이익) 가능성, PER·RIM 과대 주의")
    rn0 = m.get("roe_norm")
    if roe is not None and roe > 0.15 and (rn0 is None or roe > rn0 * 1.5):
        flags.append(f"ROE {roe*100:.0f}%" + (f" (사이클 평균 {rn0*100:.0f}%)" if rn0 is not None else "")
                     + " — 고점 이익일 수 있음. 지금 이익이 유지된다고 가정하는 상대 PER·PBR-ROE·DCF 는 상단, 정상화 RIM 을 하단으로 볼 것")
    if (m.get("rev_g") or 0) > 0.15 and fcfe and fcfe > 0:
        flags.append(f"매출 성장 {m['rev_g']*100:.0f}% → DCF 성장률은 15%로 제한")
    res = {"models": out, "flags": flags, "fscore": m.get("fscore"), "dupont": m.get("dupont"),
           "roe": round(roe, 4) if roe is not None else None,
           "roe_norm": round(m["roe_norm"], 4) if m.get("roe_norm") is not None else None,
           "assumptions": {"coe": COE, "g": G, "period": m.get("period"), "financial_sector": fin,
                           "payout": round(m["payout"], 3) if m.get("payout") else None}}
    if vals:
        res["range"] = {"low": min(vals), "mid": st.median(vals), "high": max(vals),
                        "mid_upside": round(st.median(vals) / price - 1, 3) if price else None}
    # RIM 민감도 (COE 8/9/10%)
    if bps and roe is not None:
        res["rim_sens"] = {f"{c*100:.0f}%": round(_rim(bps, roe, c), 0) for c in (0.08, 0.09, 0.10)}
    # 역DCF: 가격 = FCFE(1+g)/(COE−g) → g
    if not fin and fcfe and fcfe > 0 and price:
        res["implied_g"] = round((COE * price - fcfe) / (price + fcfe), 4)
    if price and eps and eps > 0:
        res["per"] = round(price / eps, 1)
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
    base: dict[str, dict] = {}
    for code, p in prices.items():
        if not p or code not in mcap:
            continue
        q = fin.quarterly(code)
        if q is None or q.is_empty():
            continue
        m = base_metrics(q.to_dicts(), mcap[code] / p)
        if m:
            base[code] = m
    peers = peer_multiples([{"sector": sector.get(c), "per": prices[c] / m["eps"] if m.get("eps") and m["eps"] > 0 else None,
                             "pbr": prices[c] / m["bps"] if m.get("bps") and m["bps"] > 0 else None} for c, m in base.items()])
    out = {}
    for c, m in base.items():
        try:
            v = value(m, prices[c], sector.get(c), peers)
            v["sector"] = sector.get(c)
            v["peer"] = peers.get(sector.get(c) or "기타")
            out[c] = v
        except Exception as e:  # noqa: BLE001
            log.warning("가치평가 %s 실패: %s", c, e)
    log.info("가치평가 %d종목", len(out))
    return out
