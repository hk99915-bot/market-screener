"""ETF 상세 — 종목처럼 검색·조회되고, 구성종목으로 풀어서(look-through) 노출·드라이버·가치평가를 합산.

KR: 네이버 ETF 목록(시총 상위) + 꼭 필요한 헷지/레버리지 ETF, 구성은 KRX PDF(pykrx), 가격은 야후(.KS)
US: 주요 ETF 목록, 구성은 야후 funds_data.top_holdings
출력: reports/detail/{KR,US}/{코드}.json (+ _index.json 에 병합)
     reports/active_etf_consensus.json — 국내 주식형 액티브 ETF 보유 합의도 (KR 빌드 때 같이, 추가 수집 없음)

액티브 ETF 보유 합의도 (10/17 겸이 지시 "액티브 etf가 비중늘리거나(주가상승일지도?) 많이담는종목 포착"):
  KR_ACTIVE 를 KR 목록에 넣어 기존 _kr_holdings(상위 20 비중)로 받고, 종목별 (a) 담은 액티브 ETF 수 (b) 비중 합·평균
  (c) 직전 스냅샷 대비 비중 변화를 낸다. 비중 증가는 주가 상승만으로도 생긴다 → 같은 기간 종목 수익률과 ETF 수익률의
  상대수익(rel)과 비교: 비중 변화율 ≈ rel 이면 '가격효과', 그보다 REAL_GAP 이상 크면 '실질 증가 추정'.
  PDF 수량(계약수)이 양쪽에 있으면 수량 변화로 바로 판정(1CU 기준이라 자금 유출입 영향 없음).
  직전 비중은 reports/active_etf_snap.json 하나(최신 1개 덮어쓰기). 텔레그램 없음·점수 합산 없음.
"""
from __future__ import annotations

import json
from .json_safe import dumps as strict_dumps
import logging
import time
from datetime import date, datetime, timedelta

import requests

from .config import REPORT_DIR

log = logging.getLogger(__name__)
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}
KR_MUST = ["114800", "252670", "122630", "069500", "102110", "139260", "091160", "091230", "396500", "229200", "233740",
           "251340", "261240", "138230", "133690", "360750", "379800", "381170", "305720", "364980", "471760", "117700",
           "132030", "305080", "148070", "114260", "153130", "261220", "475310",
           "418670", "218420", "474800", "219390"]   # 10/30 PB ISA 후보: 사이버보안(req-data-3981f7fc)·미 에너지 3종(req-data-ee93a893)
US_LIST = ["SPY", "QQQ", "DIA", "IWM", "VOO", "VTI", "SCHD", "SOXX", "SMH", "PSI", "XLK", "XLE", "XLF", "XLV", "XLY", "XLP",
           "XLI", "XLU", "XLB", "XLRE", "XLC", "TLT", "IEF", "SHY", "HYG", "JNK", "LQD", "BKLN", "BND", "GLD", "SLV", "USO", "UNG", "UUP",
           "ARKK", "TQQQ", "SQQQ", "SOXL", "SOXS", "SH", "PSQ", "SDS", "UVXY", "EEM", "EWY", "EWJ", "FXI", "KWEB", "VEA", "VWO",
           "IBIT", "JEPI", "JEPQ", "KRE", "KBE", "ITA", "URA", "LIT", "TAN", "XBI", "IBB", "MAGS", "COPX", "GDX",
           "BUG", "CIBR", "HACK"]   # 사이버보안 ETF (10/22 겸이 요청)
# 국내 주식형 액티브 ETF (데이터 데스크 10/17 확인 명단 — 출처 등급은 git 이력 screener/active_funds.py TARGETS).
# overlay = 커버드콜(옵션 매도 섞임) — 주식 부분만 비교.
KR_ACTIVE = {"385720": "TIME 코스피액티브", "385710": "TIME K이노베이션액티브", "441800": "TIME Korea플러스배당액티브",
             "463050": "TIME K바이오액티브", "495060": "TIME 코리아밸류업액티브", "0163Y0": "KoAct 코스닥액티브",
             "476850": "KoAct 배당성장액티브", "462900": "KoAct 바이오헬스케어액티브", "494890": "KODEX 200액티브",
             "445290": "KODEX 로봇액티브", "385510": "KODEX 신재생에너지액티브", "471780": "TIGER 코리아테크액티브",
             "444200": "SOL 코리아메가테크액티브", "494330": "ACE 라이프자산주주가치액티브", "472720": "TRUSTON 주주가치액티브",
             "472150": "TIGER 배당커버드콜액티브", "0219E0": "KODEX 200커버드콜액티브", "0177R0": "TIGER 반도체TOP10커버드콜액티브"}
KR_ACTIVE_OVERLAY = {"472150", "0219E0", "0177R0"}
ACTIVE_OUT = REPORT_DIR / "active_etf_consensus.json"
ACTIVE_SNAP = REPORT_DIR / "active_etf_snap.json"
REAL_GAP = 0.05      # 비중 변화율 − 상대수익 이 이보다 크면 '실질 증가 추정' [가정]
REAL_SHARES = 0.05   # 계약수 +5% 이상 = 실질 증가 (그 아래는 반올림·현금 조정 잡음) [가정]
MIN_DW = 0.001       # 비중 변화 0.1%p 미만은 변화 없음으로 봄
INVERSE_HINT = ("인버스", "SQQQ", "SOXS", "SH", "PSQ", "SDS")


def _kr_list(n: int = 200) -> list[dict]:
    r = requests.get("https://finance.naver.com/api/sise/etfItemList.nhn?etfType=0&targetColumn=market_sum&sortOrder=desc",
                     headers=UA, timeout=30)
    items = r.json()["result"]["etfItemList"]
    items.sort(key=lambda x: -(x.get("marketSum") or 0))
    top = items[:n]
    have = {x["itemcode"] for x in top}
    top += [x for x in items if (x["itemcode"] in KR_MUST or x["itemcode"] in KR_ACTIVE) and x["itemcode"] not in have]
    return top


def _kr_info(code: str) -> dict:
    try:
        j = requests.get(f"https://m.stock.naver.com/api/stock/{code}/etfAnalysis", headers=UA, timeout=15).json()
        return {"summary": j.get("etfSummary"), "base": j.get("etfBaseIndex"), "issuer": j.get("issuerName"),
                "fee": j.get("totalFee"), "nav_total": j.get("totalNav"), "listed": j.get("listedDate")}
    except Exception:  # noqa: BLE001
        return {}


def _kr_holdings(code: str) -> list[dict]:
    try:
        from pykrx import stock  # type: ignore
        df = stock.get_etf_portfolio_deposit_file(code)
        if df is None or len(df) == 0:
            return []
        col = "금액" if "금액" in df.columns else df.columns[-1]
        tot = float(df[col].sum()) or 1.0
        sh = "계약수" if "계약수" in df.columns else None
        out = [{"code": str(k), "name": str(r.get("구성종목명", k)), "weight": float(r[col]) / tot,
                **({"shares": float(r[sh])} if sh and r[sh] == r[sh] else {})} for k, r in df.iterrows() if r[col]]
        out.sort(key=lambda x: -x["weight"])
        return out[:20]
    except Exception as e:  # noqa: BLE001
        log.info("ETF 구성 %s 실패: %s", code, e)
        return []


def _us_holdings(t: str) -> tuple[list[dict], dict]:
    try:
        import yfinance as yf
        fd = yf.Ticker(t).funds_data
        th = fd.top_holdings
        hold = []
        if th is not None and len(th):
            for sym, r in th.iterrows():
                hold.append({"code": str(sym).replace(".", "-"), "name": str(r.get("Name", sym)), "weight": float(r.get("Holding Percent") or 0)})
        info = {}
        try:
            info["summary"] = (fd.description or "")[:600]
        except Exception:  # noqa: BLE001
            pass
        try:
            ov = fd.fund_overview or {}
            info["category"] = ov.get("categoryName")
            info["family"] = ov.get("family")
        except Exception:  # noqa: BLE001
            pass
        try:
            info["sectors"] = {k: round(v, 3) for k, v in (fd.sector_weightings or {}).items() if v}
        except Exception:  # noqa: BLE001
            pass
        return hold, info
    except Exception as e:  # noqa: BLE001
        log.info("US ETF 구성 %s 실패: %s", t, e)
        return [], {}


def _prices(tickers: list[str]) -> dict:
    import yfinance as yf
    out = {}
    for i in range(0, len(tickers), 80):
        chunk = tickers[i:i + 80]
        px = yf.download(chunk, period="14mo", interval="1d", auto_adjust=True, progress=False, threads=True, group_by="ticker")
        for t in chunk:
            try:
                g = px[t] if len(chunk) > 1 else px
                g = g.dropna(subset=["Close"])
                if len(g) >= 20:
                    out[t] = g
            except Exception:  # noqa: BLE001
                continue
    return out


def _stats(g) -> tuple[dict, list, list]:
    c = g["Close"].astype(float).tolist()
    d = [str(x.date()) for x in g.index]
    last = c[-1]

    def r(n):
        return last / c[-1 - n] - 1 if len(c) > n and c[-1 - n] else None
    hi = max(c[-250:])
    lo = min(c[-250:])
    sma = lambda n: sum(c[-n:]) / n if len(c) >= n else None  # noqa: E731
    gains = [max(c[i] - c[i - 1], 0) for i in range(len(c) - 14, len(c))]
    losses = [max(c[i - 1] - c[i], 0) for i in range(len(c) - 14, len(c))]
    rsi = 100 - 100 / (1 + (sum(gains) / (sum(losses) or 1e-9))) if len(c) > 15 else None
    st = {"ret1": r(1), "ret5": r(5), "ret20": r(20), "ret60": r(60), "high52": hi, "low52": lo, "from_high52": last / hi - 1,
          "sma20": sma(20), "sma50": sma(50), "sma200": sma(200), "rsi14": rsi}
    rd = lambda v: None if v is None else round(float(v), 4)  # noqa: E731
    try:
        import numpy as np
        from .indicators import psar_np
        ps = psar_np(g["High"].astype(float).to_numpy(), g["Low"].astype(float).to_numpy(), np.array(c, dtype=float))
    except Exception:  # noqa: BLE001
        ps = [None] * len(c)
    s20 = [sum(c[i - 19:i + 1]) / 20 if i >= 19 else None for i in range(len(c))]
    s50 = [sum(c[i - 49:i + 1]) / 50 if i >= 49 else None for i in range(len(c))]
    s200 = [sum(c[i - 199:i + 1]) / 200 if i >= 199 else None for i in range(len(c))]
    chart = [{"d": d[i][5:], "t": d[i], "o": rd(g["Open"].iloc[i]), "h": rd(g["High"].iloc[i]), "l": rd(g["Low"].iloc[i]), "c": rd(c[i]),
              "v": int(g["Volume"].iloc[i] or 0), "s20": rd(s20[i]), "s50": rd(s50[i]), "s200": rd(s200[i]),
              "p": rd(ps[i]) if ps[i] is not None and ps[i] == ps[i] else None} for i in range(max(0, len(c) - 260), len(c))]
    c1y = [[d[i], rd(c[i])] for i in range(max(0, len(c) - 260), len(c))]
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in st.items()}, chart, c1y


def _look(hold: list[dict], market: str) -> dict:
    """구성종목 상세 파일을 읽어 가중 합산."""
    d = REPORT_DIR / "detail"
    acc = {"drv": [0.0, 0.0], "sig": [0.0, 0.0], "norm": [0.0, 0.0], "per": [0.0, 0.0]}
    chains: dict[str, float] = {}
    cov = 0.0
    for h in hold:
        mk = "KR" if h["code"].isdigit() and len(h["code"]) == 6 else "US"
        p = d / mk / f"{h['code']}.json"
        if not p.exists():
            continue
        try:
            s = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if s.get("etf"):
            continue
        w = h["weight"]
        cov += w
        dv, v = s.get("drivers") or {}, s.get("valuation") or {}
        h["drv"] = dv.get("score")
        h["sig"] = (v.get("signal_fv") or {}).get("upside")
        h["norm"] = (v.get("group_upside") or {}).get("normal")
        h["ret20"] = (s.get("stats") or {}).get("ret20")
        h["mk"] = mk
        ch = (dv.get("chain") or {}).get("name") or v.get("sector") or s.get("theme")
        if ch:
            chains[ch] = chains.get(ch, 0) + w
        for k, x in (("drv", h["drv"]), ("sig", h["sig"]), ("norm", h["norm"])):
            if x is not None:
                acc[k][0] += w * x
                acc[k][1] += w
    res = {"coverage": round(cov, 3), "chains": {k: round(v, 3) for k, v in sorted(chains.items(), key=lambda z: -z[1])}}
    for k, (num, den) in acc.items():
        if den > 0.2:
            res[k] = round(num / den, 3)
    return res


def build(market: str) -> int:
    t0 = time.time()
    d = REPORT_DIR / "detail" / market
    if not d.exists():
        return 0
    if market == "KR":
        lst = _kr_list()
        meta = {x["itemcode"]: x for x in lst}
        px = _prices([f"{c}.KS" for c in meta])
        rows = []
        for code, x in meta.items():
            g = px.get(f"{code}.KS")
            if g is None:
                continue
            hold = _kr_holdings(code)
            info = _kr_info(code)
            rows.append((code, x["itemname"], g, hold, info, {"nav": x.get("nav"), "mcap_eok": x.get("marketSum"),
                                                              "r3m": x.get("threeMonthEarnRate")}))
            time.sleep(0.15)
    else:
        px = _prices(US_LIST)
        rows = []
        for t in US_LIST:
            g = px.get(t)
            if g is None:
                continue
            hold, info = _us_holdings(t)
            rows.append((t, t, g, hold, info, {}))
            time.sleep(0.2)
    idx_p = d / "_index.json"
    idx = json.loads(idx_p.read_text(encoding="utf-8")) if idx_p.exists() else {"symbols": [], "names": {}}
    n = 0
    asof = str(date.today())
    for code, name, g, hold, info, extra in rows:
        st, chart, c1y = _stats(g)
        inv = any(h in name for h in INVERSE_HINT) or code in INVERSE_HINT
        look = _look(hold, market) if hold else {}
        rec = {"symbol": code, "name": name if market == "KR" else (info.get("category") and f"{code} · {info['category']}" or code),
               "market": "ETF", "close": round(float(g["Close"].iloc[-1]), 4), "asof": str(g.index[-1].date()),
               "etf": {**info, **extra, "inverse": inv, "holdings": hold, "look": look},
               "stats": st, "chart": chart, "c1y": c1y, "research": {"items": []}, "flows": [], "disclosures": [],
               "financials": {}, "sim": {}, "scenarios": {}, "comment": {}}
        (d / f"{code}.json").write_text(strict_dumps(rec, ensure_ascii=False, default=str), encoding="utf-8")
        if code not in idx["symbols"]:
            idx["symbols"].append(code)
        idx.setdefault("names", {})[code] = rec["name"]
        idx.setdefault("etf", [])
        if code not in idx["etf"]:
            idx["etf"].append(code)
        n += 1
    idx_p.write_text(json.dumps(idx, ensure_ascii=False), encoding="utf-8")
    log.info("ETF %s %d개 (%.0fs)", market, n, time.time() - t0)
    if market == "KR":   # 액티브 ETF 보유 합의도 — 이미 받은 구성으로만 (추가 수집 없음)
        try:
            got = {c: (h, g) for c, _, g, h, _, _ in rows if c in KR_ACTIVE}
            got.update({c: (_kr_holdings(c), None) for c in KR_ACTIVE if c not in got})   # 야후 시세 없는 신형 코드
            run_active_consensus(got, asof)
        except Exception as e:  # noqa: BLE001
            log.warning("액티브 ETF 합의도 실패: %s", e)
    return n


# ───────────── 액티브 ETF 보유 합의도 ─────────────

def _is_stock(code: str) -> bool:
    c = str(code or "")
    return len(c) == 6 and c[0].isdigit() and c[:5].isalnum()


def _verdict(w0: float, w1: float, s0, s1, rel) -> str:
    """비중 증가의 성격. s0/s1 = 1CU 계약수, rel = 같은 기간 종목/ETF 상대수익."""
    if w1 - w0 < MIN_DW:
        return "변화 없음" if abs(w1 - w0) < MIN_DW else "비중 감소"
    if s0 and s1:
        return "실질 증가(수량↑)" if s1 / s0 - 1 >= REAL_SHARES else "가격효과(수량 그대로)"
    if rel is None or not w0:
        return "주가 상승 효과일 수 있음(가격 미확인)"
    return "실질 증가 추정" if (w1 / w0 - 1) - rel > REAL_GAP else "가격효과"


def active_consensus(cur: dict, prev: dict | None, stock_px: dict, top: int = 20) -> dict:
    """cur/prev = {"asof", "etfs": {etf: {"close", "holdings": {code: {"name","w","shares"?,"px"?}}}}}.
    stock_px = {code: close} (이번 기준일). prev 의 holdings.px 는 직전 기준일 종가. 순수 함수."""
    pe = (prev or {}).get("etfs") or {}
    agg: dict[str, dict] = {}
    for e, x in (cur.get("etfs") or {}).items():
        p0 = pe.get(e) or {}
        er = x["close"] / p0["close"] - 1 if x.get("close") and p0.get("close") else None
        for c, h in (x.get("holdings") or {}).items():
            if not _is_stock(c):
                continue
            a = agg.setdefault(c, {"code": c, "name": h.get("name"), "etfs": [], "w": [], "dw": [], "n_up": 0, "n_real": 0,
                                   "n_new_top20": 0, "verdicts": {}})
            a["etfs"].append(KR_ACTIVE.get(e, e))
            a["w"].append(h["w"])
            if not p0:
                continue
            h0 = (p0.get("holdings") or {}).get(c)
            if not h0:
                a["n_new_top20"] += 1   # 상위 20 진입 (상위 20만 받으므로 '신규 매수' 단정 금지)
                continue
            px0, px1 = h0.get("px"), stock_px.get(c)
            sr = px1 / px0 - 1 if px0 and px1 else None
            rel = (1 + sr) / (1 + er) - 1 if sr is not None and er is not None else None
            v = _verdict(h0["w"], h["w"], h0.get("shares"), h.get("shares"), rel)
            a["dw"].append(h["w"] - h0["w"])
            a["verdicts"][v] = a["verdicts"].get(v, 0) + 1
            a.setdefault("stock_ret", sr)
            if rel is not None:
                a.setdefault("_rel", []).append(rel)
            if h["w"] - h0["w"] >= MIN_DW:
                a["n_up"] += 1
                a["n_real"] += v.startswith("실질")
    rows = []
    r4 = lambda v: None if v is None else round(v, 4)  # noqa: E731
    for a in agg.values():
        rel = a.pop("_rel", None)
        dw = a.pop("dw")
        w = a.pop("w")
        a.update({"n_etf": len(a["etfs"]), "w_sum": r4(sum(w)), "w_avg": r4(sum(w) / len(w)),
                  "dw_sum": r4(sum(dw)) if dw else None, "rel_avg": r4(sum(rel) / len(rel)) if rel else None,
                  "stock_ret": r4(a.get("stock_ret"))})
        if a["n_up"]:
            a["note"] = ("실질 증가 추정 %d/%d개 ETF" % (a["n_real"], a["n_up"]) if a["n_real"]
                         else "비중 증가는 주가 상승 효과일 수 있음")
        rows.append(a)
    by_count = sorted(rows, key=lambda r: (-r["n_etf"], -(r["w_sum"] or 0)))[:top]
    by_inc = sorted([r for r in rows if (r["dw_sum"] or 0) >= MIN_DW], key=lambda r: (-r["n_real"], -(r["dw_sum"] or 0)))[:top]
    return {"asof": cur.get("asof"), "prev_asof": (prev or {}).get("asof"), "n_etf_total": len(KR_ACTIVE),
            "n_etf_collected": sum(1 for x in (cur.get("etfs") or {}).values() if x.get("holdings")),
            "method": "상위 20 비중(KRX PDF). 비중 증가는 주가 상승만으로도 생김 → 비중 변화율과 같은 기간 종목/ETF 상대수익 비교: "
                      f"차이 ≤ {REAL_GAP:.0%} 면 '가격효과', 초과면 '실질 증가 추정'. 계약수가 있으면 수량 +{REAL_SHARES:.0%} 이상을 실질로. "
                      "같은 운용사 여러 ETF 동시 매매는 독립 신호 아님. 컨텍스트 전용 — 점수 합산·발송 없음, 성과 검증 전.",
            "by_count": by_count, "by_increase": by_inc}


def _stock_closes(codes: set[str]) -> dict[str, float]:
    d = REPORT_DIR / "detail" / "KR"
    out = {}
    for c in codes:
        try:
            out[c] = float(json.loads((d / f"{c}.json").read_text(encoding="utf-8"))["close"])
        except Exception:  # noqa: BLE001
            continue
    return out


def run_active_consensus(got: dict, asof: str) -> dict | None:
    """got = {etf: (holdings, price_df)}. 빈 구성 = 미수집(이전 스냅샷 유지). 같은 날 재실행이면 기존 결과 유지."""
    from .guard import write_json
    prev = json.loads(ACTIVE_SNAP.read_text(encoding="utf-8")) if ACTIVE_SNAP.exists() else None
    if prev and prev.get("asof") == asof and ACTIVE_OUT.exists():
        log.info("액티브 ETF 합의도: 오늘(%s) 이미 집계 — 유지", asof)
        return None
    if prev and prev.get("asof", "") > asof:
        prev = None
    etfs = {}
    for e, (hold, g) in got.items():
        if hold:
            etfs[e] = {"asof": asof, "close": round(float(g["Close"].iloc[-1]), 4) if g is not None else None,
                       "holdings": {h["code"]: {"name": h["name"], "w": round(h["weight"], 5),
                                                **({"shares": h["shares"]} if h.get("shares") else {})} for h in hold}}
    px = _stock_closes({c for x in etfs.values() for c in x["holdings"]})
    for x in etfs.values():
        for c, h in x["holdings"].items():
            if c in px:
                h["px"] = px[c]
    if not etfs:
        log.warning("액티브 ETF 합의도: 구성 수집 0/%d (KRX 로그인·접속 확인) — 스냅샷 유지", len(KR_ACTIVE))
        return None
    cur = {"asof": asof, "etfs": {**((prev or {}).get("etfs") or {}), **etfs}}   # 미수집 ETF 는 직전 값 유지
    res = active_consensus({"asof": asof, "etfs": etfs}, prev, px)
    write_json(ACTIVE_OUT, res, default=str)
    write_json(ACTIVE_SNAP, cur, default=str)
    log.info("액티브 ETF 합의도: ETF %d/%d · 종목 %d", res["n_etf_collected"], len(KR_ACTIVE), len(res["by_count"]))
    return res
