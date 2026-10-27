"""알파북 제안의 '왜 진입하나' 문장 — 기술(B1·S4·퀀트 hi52) + 기대값·리스크·뒤집힘 + 세 축(펀더·내러티브·센티).

10/24 겸이 "이 코멘트도 정리 좀, 왜 진입하는지로" · "펀더 내러 센티 다 드러나게". 규칙 문장(LLM 아님).
원칙: 파일에 있는 숫자만 쓴다. 축의 재료가 하나도 없으면 '미확인' — 지어내지 않는다. 판정 문턱은 표시용 [가정]이며 진입 규칙이 아니다
(세 축 중 − 가 2개 이상이면 끝에 '근거 약함' 표시만, 진입·크기 불변).

축별 재료(출처 키)와 점수(+1/0/−1 합 → + / 중립 / −):
- 펀더: detail.valuation.group_upside.current(현재 이익 기준 적정가 괴리, ±10%) · detail.financials 최근 분기 영업이익 전년 동기 대비(±10%)
        · docs/valuation_notes 에 종목 코드가 있으면 출처만 덧붙임.
- 내러티브: data/dart.parquet 7일 수주·계약·자사주 취득·IR·타법인 투자(있으면 +1, scripts/hf_ideas._dart_recent 와 같은 거름)
        · reports/research.json 30일 리포트 톤(긍정 > 부정 +1, 반대 −1) · reports/trend_discovery_KR.json 업종 추세 쏠림(lift ≥ 1.5·p < 0.10 +1, lift ≤ 0.67 −1).
- 센티: detail.flows 5일 외국인·기관 합(둘 다 + → +1, 둘 다 − → −1) · reports/accum.json 매집 태그(있으면 +1)
        · data/deriv/stock_fut_oi.csv 주식선물 5일 미결제 × 가격(OI ↑+가격 ↑ +1, OI ↑+가격 ↓ −1, 파일 없으면 재료 빠짐 — 10/27 req-hf-e379cf37).
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TREND_STUDY = "reports/studies/2026-10-24_trend_events.json"
DART_KEEP = ("수주·계약", "자사주", "IR·공정공시", "타법인 투자")


def _j(root: Path, rel: str):
    try:
        return json.loads((root / rel).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _sg(x: float) -> str:
    return f"{x:+.1f}".replace("-", "−")


def _verdict(score: int | None) -> str:
    return "미확인" if score is None else "+" if score > 0 else "−" if score < 0 else "중립"


def _add(acc: list, s: int | None, txt: str, src: str, short: str | None = None):
    acc.append((s, txt, src, short or txt))


def _axis(parts: list) -> dict:
    """parts = [(점수 or None, 근거 문구, 출처)] — 점수 있는 재료가 0개면 미확인."""
    have = [p for p in parts if p[0] is not None]
    if not have:
        return {"v": "미확인", "why": "재료 없음", "src": "", "score": None, "lead": "재료 없음", "lead_src": ""}
    sc = sum(p[0] for p in have)
    lead = next((p for p in have if p[0] and (p[0] > 0) == (sc > 0)), have[0]) if sc else have[0]   # 판정을 만든 재료 1개(텔레그램용)
    return {"v": _verdict(sc), "why": " · ".join(p[1] for p in have), "src": "·".join(dict.fromkeys(p[2] for p in have)), "score": sc,
            "lead": lead[3], "lead_src": lead[2].rsplit("/", 1)[-1].rsplit(".", 1)[-1] if lead[2].startswith("detail.") else lead[2].rsplit("/", 1)[-1].split(".")[0]}


# ── 펀더 ──────────────────────────────────────────────
def fund_axis(det: dict | None, code: str, root: Path = ROOT) -> dict:
    parts = []
    v = (det or {}).get("valuation") or {}
    up = (v.get("group_upside") or {}).get("current")
    if isinstance(up, (int, float)):
        _add(parts, 1 if up >= 0.10 else -1 if up <= -0.10 else 0, f"현재이익 적정가 {_sg(up * 100)}%", "detail.valuation", f"적정가 {_sg(up * 100)}%")
    qs = ((det or {}).get("financials") or {}).get("quarters") or []
    if qs:
        last = qs[-1]
        prev = next((q for q in qs if q.get("year") == (last.get("year") or 0) - 1 and q.get("q") == last.get("q")), None)
        if prev and isinstance(last.get("op"), (int, float)) and isinstance(prev.get("op"), (int, float)) and prev["op"] > 0:
            g = last["op"] / prev["op"] - 1
            _add(parts, 1 if g >= 0.10 else -1 if g <= -0.10 else 0, f"영업익 {last.get('period')} 전년비 {_sg(g * 100)}%", "detail.financials", f"영업익 YoY {_sg(g * 100)}%")
    ax = _axis(parts)
    try:
        notes = [p for p in sorted((root / "docs" / "valuation_notes").glob("*.md")) if code in p.read_text(encoding="utf-8")]
    except Exception:  # noqa: BLE001
        notes = []
    if notes and ax["score"] is not None:
        ax["src"] += f"·{notes[-1].relative_to(root)}"
    return ax


# ── 내러티브 ───────────────────────────────────────────
def _dart(code: str, today: date, root: Path, days: int = 7) -> list | None:
    try:
        import polars as pl
        d = pl.read_parquet(root / "data" / "dart.parquet").filter((pl.col("code") == code) & pl.col("category").is_in(list(DART_KEEP)))
    except Exception:  # noqa: BLE001
        return None
    out = []
    for r in d.iter_rows(named=True):
        t = r.get("title") or ""
        if "정정" in t or "안내공시" in t or (r["category"] == "자사주" and "취득" not in t):
            continue
        if 0 <= (today - date.fromisoformat(str(r["date"])[:10])).days <= days:
            out.append((str(r["date"])[:10], r["category"]))
    return out


def narr_axis(det: dict | None, code: str, market: str, today: date, root: Path = ROOT) -> dict:
    parts = []
    if market == "KR":
        dr = _dart(code, today, root)
        if dr is not None:
            _add(parts, 1 if dr else 0, (f"DART 7일 {dr[0][1]} 등 {len(dr)}건" if dr else "DART 7일 수주·자사주·IR 0건"), "data/dart.parquet", f"공시 {len(dr)}건")
    rs = _j(root, "reports/research.json")
    if rs and rs.get("items") is not None:
        lo = (today - timedelta(days=30)).isoformat()
        its = [x for x in rs["items"] if x.get("code") == code and (x.get("date") or "") >= lo]
        pos = sum("긍정" in (x.get("tone") or "") for x in its)
        neg = sum("부정" in (x.get("tone") or "") for x in its)
        txt = f"리포트 30일 {len(its)}건" + (f"(긍정 {pos}·부정 {neg}, 최근 {its[0].get('broker')})" if its else "")
        _add(parts, 1 if pos > neg else -1 if neg > pos else 0, txt, "reports/research.json", f"리포트 {len(its)}건(긍{pos}·부{neg})")
    sec = (det or {}).get("theme")
    td = _j(root, f"reports/trend_discovery_{market}.json")
    row = next((r for r in (((td or {}).get("sectors") or {}).get("rows") or []) if r.get("g") == sec), None) if sec else None
    if row and isinstance(row.get("lift"), (int, float)):
        lf = row["lift"]
        s = 1 if lf >= 1.5 and (row.get("p_upper") or 1) < 0.10 else -1 if lf <= 0.67 else 0
        _add(parts, s, f"업종 {sec} 추세 쏠림 {lf:.2f}배" + ("" if row.get("bonf_pass") else "(다중검정 미통과)"), f"reports/trend_discovery_{market}.json",
             f"업종 쏠림 {lf:.2f}배")
    return _axis(parts)


# ── 센티 ──────────────────────────────────────────────
STOCK_FUT_OI = "data/deriv/stock_fut_oi.csv"   # 금융위 주식선물(getStockFuturesPriceInfo_V2) 일별 — 열 date,code,oi,clpr (req-hf-e379cf37)
OI_MIN_CHG = 0.05                               # 5일 미결제 변화 문턱 ±5% [가정: 표시용, 검증전]


def stock_fut_oi(code: str, root: Path = ROOT, n: int = 5) -> dict | None:
    """주식선물 미결제(OI) 5일 변화 × 선물 가격 변화 → 포지셔닝 판독(교과서 OI 4분면, 검증전).

    OI ↑ + 가격 ↑ = 신규 롱 유입(+1) · OI ↑ + 가격 ↓ = 신규 숏 유입(−1) · OI ↓ = 청산(숏 커버·롱 정리, 0) · |OI 변화| < 5% = 0.
    파일이 없거나 종목 행이 n+1 개 미만이면 None(센티 축에서 재료 빠짐 → 지어내지 않음). 마지막 행이 7일보다 오래되면 None(stale).
    """
    import csv
    try:
        rows = [r for r in csv.DictReader(open(root / STOCK_FUT_OI, encoding="utf-8")) if r.get("code") == code]
    except Exception:  # noqa: BLE001
        return None
    try:
        rows = sorted(rows, key=lambda r: r["date"])[-(n + 1):]
        if len(rows) < n + 1 or (date.today() - date.fromisoformat(rows[-1]["date"][:10])).days > 7:
            return None
        o0, o1, p0, p1 = float(rows[0]["oi"]), float(rows[-1]["oi"]), float(rows[0]["clpr"]), float(rows[-1]["clpr"])
    except (KeyError, ValueError):
        return None
    if o0 <= 0 or p0 <= 0:
        return None
    oc, pc = o1 / o0 - 1, p1 / p0 - 1
    if oc >= OI_MIN_CHG:
        s, tag = (1, "신규 롱 유입") if pc > 0 else (-1, "신규 숏 유입")
    elif oc <= -OI_MIN_CHG:
        s, tag = 0, "포지션 청산"
    else:
        s, tag = 0, "미결제 변화 작음"
    return {"s": s, "txt": f"주식선물 {n}일 미결제 {_sg(oc * 100)}%·가격 {_sg(pc * 100)}% ({tag})", "short": f"선물OI {_sg(oc * 100)}% {tag}"}


def senti_axis(det: dict | None, code: str, market: str, root: Path = ROOT) -> dict:
    parts = []
    fl = ((det or {}).get("flows") or [])[-5:]
    if len(fl) >= 3 and all(isinstance(x.get("외국인"), (int, float)) and isinstance(x.get("기관"), (int, float)) for x in fl):
        f5, i5 = sum(x["외국인"] for x in fl), sum(x["기관"] for x in fl)
        s = 1 if f5 > 0 and i5 > 0 else -1 if f5 < 0 and i5 < 0 else 0
        _add(parts, s, f"{len(fl)}일 외국인 {_sg(f5)}억·기관 {_sg(i5)}억", "detail.flows", f"5일 외{_sg(f5)}·기관{_sg(i5)}억")
    if market == "KR":
        sf = stock_fut_oi(code, root)
        if sf:
            _add(parts, sf["s"], sf["txt"], STOCK_FUT_OI, sf["short"])
        ac = _j(root, "reports/accum.json")
        if ac and ac.get("status") == "ok" and isinstance(ac.get("top"), dict):
            tags = sorted({t for rows in ac["top"].values() if isinstance(rows, list) for r in rows if r.get("code") == code for t in (r.get("tags") or [])})
            _add(parts, 1 if tags else 0, ("매집 " + "·".join(tags[:3])) if tags else "매집 신호 없음", "reports/accum.json",
                 ("매집 " + "·".join(tags[:2])) if tags else "매집 없음")
    return _axis(parts)


# ── 기술·리스크 ────────────────────────────────────────
def _hi52(root: Path, market: str) -> dict | None:
    j = _j(root, TREND_STUDY)
    c = ((((j or {}).get("markets") or {}).get(market) or {}).get("cells") or {}).get("hi52")
    if not c or not c.get("oos"):
        return None
    return {"grade": c.get("grade"), "mean": c["oos"].get("mean_m"), "median": c["oos"].get("median_ev"), "hit": c["oos"].get("hit")}


def build(x: dict, market: str, grade: str | None = None, today: date | None = None, root: Path = ROOT, det: dict | None = None) -> dict:
    """x = alphabook.order() dict(+prox). 반환: tech·risk 문장, 세 축, weak, tg(4줄), long(펼침)."""
    today = today or date.today()
    det = det if det is not None else _j(root, f"reports/detail/{market}/{x['code']}.json")
    nm = x.get("name") or x["code"]
    fx = (lambda v: f"{v:,.0f}") if market == "KR" else (lambda v: f"{v:,.2f}")
    # 기술 — 왜 걸렸나·왜 지금
    t = [f"{nm} = {x.get('src', '')}" + (f" 52주 고점 근접(종가/250일 고가 {x['prox'] * 100:.1f}%)" if isinstance(x.get("prox"), (int, float)) else "")
         + (f"·사전등록 {grade}" if grade else ""), "S4 추격 아님"]
    hs = _hi52(root, market)
    if hs and hs.get("grade") and isinstance(hs.get("mean"), (int, float)):
        t.append(f"퀀트 hi52 {market} {hs['grade']}(20일 초과 {_sg(hs['mean'] * 100)}%)"
                 + (f", 단 종목 중앙값 {_sg(hs['median'] * 100)}%·분산 전제" if isinstance(hs.get("median"), (int, float)) else ""))
    tech = " · ".join(t)
    ts = [f"{nm}={x.get('src', '')}" + (f" 고점 {x['prox'] * 100:.1f}%" if isinstance(x.get("prox"), (int, float)) else "") + (f"({grade})" if grade else ""), "S4 아님"]
    if hs and hs.get("grade") and isinstance(hs.get("mean"), (int, float)):
        ts.append(f"hi52 {hs['grade']} {_sg(hs['mean'] * 100)}%/20일" + (f", 중앙값 {_sg(hs['median'] * 100)}%→분산" if isinstance(hs.get("median"), (int, float)) else ""))
    tech_s = " · ".join(ts)
    # 기대값·리스크·뒤집힘
    r = []
    if isinstance(x.get("ev_r"), (int, float)) and isinstance(x.get("base_ev_r"), (int, float)):
        r.append(f"E[R] {x['ev_r']:+.3f}R vs 기준선 {x['base_ev_r']:+.3f}R".replace("-", "−"))
    m_s = re.search(r"손절 [\d,\.]+\((−?-?[\d\.]+)%\)", x.get("line") or "")
    m_r = re.search(r"1차 [\d,\.]+\(([\d\.]+)R\)", x.get("line") or "")
    r.append(f"손절 {fx(x['stop'])}" + (f"({m_s.group(1)}%)" if m_s else "") + (f"·1차 손익비 {m_r.group(1)}R" if m_r else ""))
    if isinstance(x.get("weight"), (int, float)) and isinstance(x.get("risk_pct"), (int, float)):
        r.append(f"크기 {x['weight'] * 100:.1f}%=리스크 {x['risk_pct'] * 100:.3f}%")
    close = (det or {}).get("close")
    if isinstance(x.get("prox"), (int, float)) and x["prox"] > 0 and isinstance(close, (int, float)):
        r.append(f"뒤집힘 종가 < {fx(0.95 * close / x['prox'])}(250일 고점 95%) → B1 해제")
    else:
        r.append(f"뒤집힘 종가 < {fx(x['stop'])} → 다음 봉 시가 청산")
    risk = " · ".join(r)
    rs_ = [r[0].replace(" vs 기준선 ", ">기준 ")] if r and r[0].startswith("E[R]") else []
    rs_ += [(f"손절 {m_s.group(1)}%" if m_s else f"손절 {fx(x['stop'])}") + (f"·1차 {m_r.group(1)}R" if m_r else "")]
    if isinstance(x.get("weight"), (int, float)) and isinstance(x.get("risk_pct"), (int, float)):
        rs_.append(f"{x['weight'] * 100:.1f}%=리스크 {x['risk_pct'] * 100:.3f}%")
    rs_.append(r[-1].replace("뒤집힘 종가 ", "뒤집힘 ").split("(")[0].strip())
    risk_s = " · ".join(rs_)
    ax = {"펀더": fund_axis(det, x["code"], root), "내러": narr_axis(det, x["code"], market, today, root), "센티": senti_axis(det, x["code"], market, root)}
    weak = sum(a["v"] == "−" for a in ax.values()) >= 2

    def one(k):
        a = ax[k]
        return f"{k} {a['v']}" + (f" {a['why']} ({a['src']})" if a["score"] is not None else "")

    def short(k):
        a = ax[k]
        return f"{k} {a['v']}" + (f" {a['lead']}[{a['lead_src']}]" if a["score"] is not None else "")
    tail = " · 근거 약함" if weak else ""
    tg = ["왜: " + tech_s, "값: " + risk_s, short("펀더") + " | " + short("내러"), short("센티") + tail]
    long = ["근거 기술 — " + tech, "근거 기대값·리스크 — " + risk] + [f"근거 {one(k)}" for k in ax] + (["근거 약함 — 세 축 중 − 2개 이상(표시만, 규칙 불변)"] if weak else [])
    return {"tech": tech, "risk": risk, "tech_s": tech_s, "risk_s": risk_s, "axes": ax, "weak": weak, "tg": tg, "long": long}
