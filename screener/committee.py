"""운용회의 — 터미널에 쌓인 데이터로 매일 '센터장 회의 자료'를 만들고, 회의의 판단을 기록해 나중에 채점.

구성
1. 탑다운: 매크로 바람·시장 폭·지수 위치·이벤트(7일)
2. 업종 의견: 공급망 체인 점수 + 테마 5·20일 성과 → 비중 확대 / 중립 / 축소
3. 종목 아이디어: 이익 신호는 좋은데 과하게 빠진 종목(매수 후보) / 이익 신호가 꺾였는데 비싼 종목(회피)
4. 운용 시나리오 3개: 강세·기본·약세 — 확률(1999~ 코스피 조건부 통계), 전환 신호, 행동
5. 검증 현황: 시그널 판정·과거 회의 성적
기록 → reports/committee_hist.json, 다음 실행부터 5·20거래일 성과로 채점.
"""
from __future__ import annotations

import json
import logging
import statistics as st
from datetime import date, datetime, timedelta

from .config import DATA_DIR, REPORT_DIR

log = logging.getLogger(__name__)
OUT = REPORT_DIR / "committee.json"
HIST = REPORT_DIR / "committee_hist.json"
SEMI_G = ("반도체", "반도체 장비·소재", "디스플레이")


def _j(name: str, default=None):
    try:
        return json.loads((REPORT_DIR / name).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def _kospi_state() -> dict:
    ms = (_j("macro_series.json", {}) or {}).get("series", {}).get("KOSPI") or []
    c = [r[4] if len(r) >= 6 else r[1] for r in ms]
    lo = [r[3] if len(r) >= 6 else r[1] for r in ms]
    if len(c) < 30:
        return {}
    last = c[-1]
    return {"last": last, "ret1": last / c[-2] - 1, "dd20": last / max(c[-21:]) - 1, "from_hi": last / max(c[-250:]) - 1,
            "low_today": lo[-1], "low20": min(lo[-20:]), "hi5": max(c[-5:]), "sma20": st.mean(c[-20:]), "sma50": st.mean(c[-50:])}


def _scenarios(k: dict, stu: dict, mv: dict) -> list[dict]:
    b = (stu or {}).get("buckets20") or {}
    deep = k and k.get("dd20", 0) <= -0.15
    shock = k and k.get("ret1", 0) <= -0.05
    key = "deep" if deep and shock else "dd15" if deep else "drop5" if shock else "all"
    p = b.get(key) or b.get("all") or {"bull": 0.35, "base": 0.4, "bear": 0.25, "n": 0}
    lowt = k.get("low_today") or k.get("last")
    cond = {"deep": "20일 −15% 이상 하락 중 −5% 급락", "dd15": "20일 −15% 이상 하락 중", "drop5": "하루 −5% 급락", "all": "평상시"}[key]
    mvs = (mv or {}).get("label") or "중립"
    return [
        {"name": "강세 — 급반등·추세 회복", "prob": p.get("bull"), "def": "20거래일 뒤 코스피 +5% 초과",
         "trigger": f"외국인 현물 2일 연속 순매수 전환 + 코스피 5일 고점({k.get('hi5', 0):,.0f}) 회복",
         "action": "반도체는 상한(60%) 안에서 유지, 현금 분할 매수 2차 집행(비반도체 우선), 인버스 헷지 해제"},
        {"name": "기본 — 반등 후 박스", "prob": p.get("base"), "def": "20거래일 뒤 ±5% 이내",
         "trigger": f"오늘 저점({lowt:,.0f}) 지지, 외국인 매도 둔화(일 −1조 이내)",
         "action": "반등 때 중복·약한 고리 축소(ETF 중복, 평균이익 기준 고평가), 실적 시즌(10/21~29) 확인 전 비중 유지"},
        {"name": "약세 — 연속 급락(6월 말 패턴)", "prob": p.get("bear"), "def": "20거래일 뒤 −5% 미만 (그중 −15% 미만 " + f"{(p.get('deep_bear') or 0)*100:.0f}%)",
         "trigger": f"오늘 저점({lowt:,.0f}) 2일 연속 종가 이탈, 또는 2단계 서킷, 또는 빅테크 설비투자 가이던스 하향",
         "action": "손실 한도·가격 규칙 기계적 집행(메모리 절반 축소), 인버스 25% 헷지, 현금 비중 확대"},
    ], {"basis": cond, "n": p.get("n"), "macro": mvs}


def _ideas(peers: list[dict]) -> tuple[list, list]:
    longs = [r for r in peers if r.get("drv") is not None and r["drv"] >= 0.25 and (r.get("nor") or -9) > 0 and (r.get("r20") or 0) <= -0.10
             and (r.get("mc") or 0) >= 1e12]
    longs.sort(key=lambda r: (-(r["drv"] or 0) - min(r.get("nor") or 0, 1) * 0.3))
    avoid = [r for r in peers if r.get("drv") is not None and r["drv"] <= -0.1 and (r.get("nor") is not None and r["nor"] < -0.2)
             and (r.get("mc") or 0) >= 1e12]
    avoid.sort(key=lambda r: (r["drv"], r["nor"]))
    f = lambda r: {"s": r["s"], "n": r["n"], "g": r["g"], "semi": r["g"] in SEMI_G, "drv": r.get("drv"), "nor": r.get("nor"),  # noqa: E731
                   "r20": r.get("r20"), "per": r.get("per"), "pbr": r.get("pbr")}
    return [f(r) for r in longs[:10]], [f(r) for r in avoid[:8]]


def _sectors(chains: dict, peers: list[dict]) -> list[dict]:
    by = {}
    for r in peers:
        if r.get("r20") is not None and (r.get("mc") or 0) > 0:
            by.setdefault(r["g"], []).append(r)
    th = {g: {"r5": sum(x["mc"] * (x.get("r5") or 0) for x in a) / sum(x["mc"] for x in a),
              "r20": sum(x["mc"] * x["r20"] for x in a) / sum(x["mc"] for x in a),
              "drv": st.mean([x["drv"] for x in a if x.get("drv") is not None] or [0]), "n": len(a)} for g, a in by.items() if len(a) >= 5}
    rows = []
    for k, c in (chains or {}).items():
        sc = c.get("score")
        if sc is None:
            continue
        stance = "비중 확대" if sc >= 0.3 else "비중 축소" if sc <= -0.15 else "중립"
        rows.append({"chain": c["name"], "score": sc, "stance": stance})
    rows.sort(key=lambda r: -r["score"])
    themes = sorted([{"theme": g, **v} for g, v in th.items()], key=lambda r: -r["drv"])
    return rows, themes


def _flows2() -> list[float]:
    """최근 2거래일 코스피 외국인 순매수(억원). [0]=오늘(잠정), [1]=전일(확정)."""
    out = []
    try:
        from .flows import intraday_market_flows, investor_totals
        f = (intraday_market_flows().get("KOSPI") or {}).get("외국인")
        if f is not None:
            out.append(float(f))
        d = date.today() - timedelta(days=1)
        while len(out) < 2 and d > date.today() - timedelta(days=7):
            if d.weekday() < 5:
                v = (investor_totals(d).get("KOSPI") or {}).get("외국인")
                if v is not None:
                    out.append(float(v))
            d -= timedelta(days=1)
    except Exception as e:  # noqa: BLE001
        log.info("수급 실패: %s", e)
    return out


def _stance(k: dict, scen: list[dict], sb: dict, stu: dict, ev7: list[dict], der: dict) -> dict:
    """시나리오 확률 ≠ 행동. 확률 1등이어도 '전환 신호'가 안 나왔으면 진입하지 않는다 — 그 이유를 데이터로 적는다."""
    bull = next((s for s in scen if s["name"].startswith("강세")), {})
    pb, n = bull.get("prob") or 0, sb.get("n") or 0
    reasons = []
    if n:
        se = (pb * (1 - pb) / n) ** 0.5
        reasons.append({"t": "확률은 1등이지만 과반이 아님",
                        "d": f"강세 {pb*100:.0f}%는 '강세가 아닐 확률' {100-pb*100:.0f}%와 같은 말. 표본 {n}회라 오차 범위가 대략 {max(0,pb-1.96*se)*100:.0f}~{min(1,pb+1.96*se)*100:.0f}%로 넓음 — 동전 던지기와 통계적으로 잘 구분되지 않음."})
    fl = _flows2()
    hi5, last = k.get("hi5"), k.get("last")
    met_f = len(fl) >= 2 and fl[0] > 0 and fl[1] > 0
    met_p = bool(hi5 and last and last >= hi5)
    fs = " · ".join(f"{'오늘' if i == 0 else '전일'} {v/1e4:+.2f}조" for i, v in enumerate(fl[:2])) if fl else "수급 데이터 없음"
    reasons.append({"t": "강세 전환 신호 미충족" if not (met_f and met_p) else "강세 전환 신호 충족",
                    "d": f"규칙: 외국인 2일 연속 순매수 + 5일 고점({hi5 or 0:,.0f}) 회복. 현재 외국인 {fs} → {'충족' if met_f else '미충족'}, 지수 {last or 0:,.0f} → {'충족' if met_p else '미충족'}. 시나리오의 '행동'은 신호가 확인된 뒤에 집행하도록 정의돼 있음."})
    if k.get("ret1") is not None and k.get("low_today") and last:
        nearlow = (last / k["low_today"] - 1) < 0.01
        reasons.append({"t": "종가가 저가권" if nearlow else "장중 저가 대비 반등",
                        "d": f"하루 {k['ret1']*100:+.1f}%, 저가 {k['low_today']:,.0f} 대비 종가 {(last/k['low_today']-1)*100:+.1f}%. " +
                             ("저가 근처 마감 = 끝까지 사는 쪽이 없었다는 뜻. 바닥 확인(저가 지지) 전." if nearlow else "저가에서 받쳐주는 매수는 있었음.")})
    lv = ((stu.get("lev_trade") or {}).get("코스피 -5% 이하 날 종가 매수") or {}).get("다음날 시가 매도") or {}
    dp = ((stu.get("conditional") or {}).get("deep_(20일 −15% 이상 하락 중)") or {}).get("d1") or {}
    if lv:
        reasons.append({"t": "손익비가 대칭이 아님",
                        "d": f"레버리지 급락일 종가 매수→다음날 시가 매도: 승률 {lv.get('up',0)*100:.0f}% · 평균 {lv.get('avg',0)*100:+.1f}% · 최악 {lv.get('worst',0)*100:+.1f}% (n={lv.get('n')}). "
                             f"최악 손실이 평균 수익의 약 {abs(lv.get('worst',0))/max(lv.get('avg',0.001),0.001):.0f}배 — 한 번 틀리면 여러 번 맞춘 걸 토해냄."})
    if dp:
        reasons.append({"t": "기다리는 비용은 작음",
                        "d": f"비슷한 날 다음날 코스피 평균 {dp.get('avg',0)*100:+.1f}% (상승 {dp.get('up',0)*100:.0f}%). 하루 늦게 신호 확인 후 들어가도 놓치는 건 평균 이 정도 — 틀렸을 때 피하는 손실이 더 큼."})
    big = [e for e in ev7 if e.get("imp", 1) >= 3]
    if big:
        reasons.append({"t": "이벤트 대기",
                        "d": "7일 안 핵심 일정: " + ", ".join(f"{e['date'][5:]} {e['name']}" for e in big[:4]) + " — 결과 전 레버리지는 이벤트 도박이 됨."})
    if der.get("gex_bn") is not None and der["gex_bn"] < 0:
        reasons.append({"t": "옵션 감마 음수 구간",
                        "d": f"감마 노출 근사 {der['gex_bn']:+,.0f}억/1%" + (f", 전환점 {der['flip']:.0f}" if der.get("flip") else "") +
                             " — 딜러 헤지가 추세를 키우는 구간이라 반등도 크지만 추가 급락도 커짐. 방향 확신 없이 레버리지는 불리."})
    reasons.append({"t": "이미 걸려 있는 노출",
                    "d": "보유 포지션이 반도체·IT 위주면 반등 베팅은 이미 들어가 있음. 같은 방향 레버리지를 얹으면 분산이 아니라 같은 베팅을 두 배로 하는 것."})
    if met_f and met_p:
        st_ = "분할 매수"
    elif k.get("low20") and last and last < k["low20"] * 0.995:
        st_ = "방어"
    else:
        st_ = "관망"
    plan = {"관망": f"오늘은 현금 유지. 다음 거래일 외국인 순매수 전환 + 저점({k.get('low_today') or 0:,.0f}) 지지가 확인되면 1차 분할(비반도체 우선), 5일 고점 회복 시 2차.",
            "분할 매수": "신호 충족 — 현금 1/3씩 분할 집행, 반도체 상한 60% 안에서.",
            "방어": "20일 저점 이탈 — 가격 규칙 기계적 집행, 인버스 25% 헷지."}[st_]
    return {"stance": st_, "plan": plan, "reasons": reasons,
            "summary": (f"PB 판단: {st_} — 강세 확률이 가장 높아도 전환 신호 확인 전엔 진입 안 함 (확률 = 방향, 신호 = 타이밍)" if st_ == "관망" else f"PB 판단: {st_}")}


def build() -> dict:
    k = _kospi_state()
    mv = _j("macro_view.json", {}) or {}
    stu = (_j("studies/crash_rebound.json", {}) or {})
    peers = (_j("peers_KR.json", {}) or {}).get("rows", [])
    chains = (_j("chains_view.json", {}) or {}).get("chains", {})
    cal = (_j("calendar.json", {}) or {}).get("events", [])
    sig = (_j("signal_scores.json", {}) or {}).get("signals", {})
    dec = _j("decisions.json", {}) or {}
    scen, sb = _scenarios(k, stu, mv)
    sq = []
    try:
        from .shorts import by_code, squeeze_candidates
        sq = squeeze_candidates(by_code(), peers)
    except Exception as e:  # noqa: BLE001
        log.info("숏스퀴즈 후보 실패: %s", e)
    longs, avoid = _ideas(peers)
    sectors, themes = _sectors(chains, peers)
    today = date.today()
    ev7 = [e for e in cal if today <= date.fromisoformat(e["date"]) <= today + timedelta(days=7) and e.get("imp", 1) >= 2]
    head = []
    if k:
        head.append(f"코스피 {k['last']:,.0f} ({k['ret1']*100:+.1f}%) · 20일 고점 대비 {k['dd20']*100:+.1f}% · 52주 고점 대비 {k['from_hi']*100:+.0f}%")
    if mv.get("summary"):
        head.append(mv["summary"])
    der = {}
    try:
        from . import derivs
        der = derivs.load()
    except Exception:  # noqa: BLE001
        pass
    stance = _stance(k, scen, sb, stu, ev7, der)
    best = max(scen, key=lambda s: s.get("prob") or 0)
    verdict = (f"가장 가능성 높은 시나리오: {best['name']} ({(best['prob'] or 0)*100:.0f}%) — 근거: 1999년 이후 '{sb['basis']}' {sb['n'] or 0}회")
    out = {"asof": datetime.now().strftime("%Y-%m-%d %H:%M"), "date": str(today), "head": head, "verdict": verdict,
           "scenarios": scen, "scenario_basis": sb, "sectors": sectors, "themes": themes[:8] + themes[-5:] if len(themes) > 13 else themes,
           "ideas": {"long": longs, "avoid": avoid}, "squeeze": sq, "events": ev7[:10], "stance": stance,
           "derivs": {k3: der.get(k3) for k3 in ("date", "spot", "pcr_oi", "pcr_vol", "max_pain", "call_wall", "put_wall", "gex_bn", "flip", "atm_iv", "expiry", "dte", "notes", "oi_profile", "hist", "fut")} if der else None,
           "validation": {k2: v.get("verdict") for k2, v in sig.items()}, "scorecard": dec.get("tally", {})}
    OUT.write_text(json.dumps(out, ensure_ascii=False, default=str), encoding="utf-8")
    _record(out)
    try:
        out["track"] = score()
        OUT.write_text(json.dumps(out, ensure_ascii=False, default=str), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        log.warning("운용회의 채점 실패: %s", e)
    log.info("운용회의 자료 생성")
    return out


def _record(o: dict) -> None:
    h = json.loads(HIST.read_text(encoding="utf-8")) if HIST.exists() else {"rows": []}
    rec = {"date": o["date"], "long": [x["s"] for x in o["ideas"]["long"]], "avoid": [x["s"] for x in o["ideas"]["avoid"]],
           "probs": {s["name"].split(" —")[0]: s["prob"] for s in o["scenarios"]},
           "kospi": (o["head"] and o["head"][0]) or ""}
    h["rows"] = [r for r in h["rows"] if r["date"] != o["date"]] + [rec]
    HIST.write_text(json.dumps(h, ensure_ascii=False), encoding="utf-8")


def score() -> dict:
    """과거 회의: 매수 후보·회피 목록의 5·20거래일 시장 중앙값 대비 초과수익, 시나리오 확률의 브라이어 점수."""
    import polars as pl
    h = json.loads(HIST.read_text(encoding="utf-8")) if HIST.exists() else {"rows": []}
    p = DATA_DIR / "kr_prices.parquet"
    if not p.exists() or not h["rows"]:
        return {}
    px = (pl.read_parquet(p).with_columns(pl.col("yf").str.slice(0, 6).alias("code"), pl.col("date").cast(pl.Utf8))
            .select("code", "date", "close"))
    days = sorted(px["date"].unique().to_list())
    wide = {d: dict(zip(g["code"].to_list(), g["close"].to_list())) for (d,), g in px.group_by("date")}
    ms = (_j("macro_series.json", {}) or {}).get("series", {}).get("KOSPI") or []
    kc = {r[0]: (r[4] if len(r) >= 6 else r[1]) for r in ms}
    res = {"h5": [], "h20": [], "brier": []}
    for r in h["rows"]:
        if r["date"] not in days:
            continue
        i = days.index(r["date"])
        for n in (5, 20):
            if i + n >= len(days):
                continue
            a, b = wide[days[i]], wide[days[i + n]]
            rets = {c: b[c] / a[c] - 1 for c in a if c in b and a[c]}
            if not rets:
                continue
            med = st.median(rets.values())
            lg = [rets[c] - med for c in r["long"] if c in rets]
            av = [rets[c] - med for c in r["avoid"] if c in rets]
            res[f"h{n}"].append({"date": r["date"], "long": round(st.mean(lg), 4) if lg else None, "avoid": round(st.mean(av), 4) if av else None})
            if n == 20 and r["date"] in kc and days[i + n] in kc:
                kr = kc[days[i + n]] / kc[r["date"]] - 1
                actual = "강세" if kr > 0.05 else "약세" if kr < -0.05 else "기본"
                pr = r.get("probs", {})
                res["brier"].append({"date": r["date"], "actual": actual,
                                     "brier": round(sum(((pr.get(s) or 0) - (1 if s == actual else 0)) ** 2 for s in ("강세", "기본", "약세")), 3)})
    summ = {}
    for n in ("h5", "h20"):
        v = [x for x in res[n] if x["long"] is not None]
        if v:
            summ[n] = {"n": len(v), "long_avg": round(st.mean(x["long"] for x in v), 4),
                       "long_hit": round(sum(1 for x in v if x["long"] > 0) / len(v), 2),
                       "avoid_avg": round(st.mean(x["avoid"] for x in v if x["avoid"] is not None), 4) if any(x["avoid"] is not None for x in v) else None}
    if res["brier"]:
        summ["brier"] = {"n": len(res["brier"]), "avg": round(st.mean(x["brier"] for x in res["brier"]), 3), "naive": 0.667}
    return {"summary": summ, "recent": res["h5"][-5:]}


def telegram_text(o: dict) -> str:
    L = ["🏛 <b>운용회의</b> · " + o["date"]]
    L += [f"• {x}" for x in o["head"]]
    L += ["", "<b>[시나리오]</b> " + o["verdict"]]
    if o.get("stance"):
        L.append("<b>[" + o["stance"]["summary"] + "]</b>")
        L += [f"  · {r['t']}" for r in o["stance"]["reasons"][:5]]
        L.append("  → " + o["stance"]["plan"])
    if o.get("derivs") and o["derivs"].get("notes"):
        L.append("<b>[옵션 포지션]</b>")
        L += [f"  · {x}" for x in o["derivs"]["notes"][:4]]
    for s in o["scenarios"]:
        L.append(f"• {s['name']} {(s['prob'] or 0)*100:.0f}% — 신호: {s['trigger']}")
        L.append(f"  → {s['action']}")
    up = [r for r in o["sectors"] if r["stance"] == "비중 확대"][:4]
    dn = [r for r in o["sectors"] if r["stance"] == "비중 축소"][:4]
    L += ["", "<b>[업종]</b> 확대: " + (", ".join(f"{r['chain']}({r['score']:+.2f})" for r in up) or "—")
          + " / 축소: " + (", ".join(f"{r['chain']}({r['score']:+.2f})" for r in dn) or "—")]
    lg = o["ideas"]["long"][:5]
    if lg:
        L.append("<b>[매수 후보]</b> " + ", ".join(f"{x['n']}{'(반도체)' if x['semi'] else ''} 드라이버 {x['drv']:+.2f}" for x in lg))
    av = o["ideas"]["avoid"][:4]
    if av:
        L.append("<b>[회피]</b> " + ", ".join(f"{x['n']} 드라이버 {x['drv']:+.2f}" for x in av))
    if o.get("squeeze"):
        L.append("<b>[숏스퀴즈 후보]</b> " + ", ".join(f"{x['n']} 잔고 {x['ratio']:.1f}%" for x in o["squeeze"][:5]))
    if o.get("events"):
        L.append("<b>[7일 이벤트]</b> " + " / ".join(f"{e['date'][5:]} {e['name']}" for e in o["events"][:6]))
    tr = (o.get("track") or {}).get("summary") or {}
    if tr.get("h5"):
        L.append(f"<i>회의 성적: 매수 후보 5일 초과수익 평균 {tr['h5']['long_avg']*100:+.1f}% (적중 {tr['h5']['long_hit']*100:.0f}%, {tr['h5']['n']}회)</i>")
    else:
        L.append("<i>회의 성적: 기록 시작 — 5거래일 뒤부터 채점</i>")
    return "\n".join(L)


# ───────────── 미장 운용회의 ─────────────
OUT_US = REPORT_DIR / "committee_us.json"


def _spx_state() -> dict:
    ms = (_j("macro_series.json", {}) or {}).get("series", {})
    def cl(k):
        return [r[4] if len(r) >= 6 else r[1] for r in ms.get(k) or []]
    c = cl("SPX")
    if len(c) < 30:
        return {}
    nq, vix, tnx = cl("NASDAQ"), cl("VIX"), cl("US10Y")
    last = c[-1]
    return {"last": last, "ret1": last / c[-2] - 1, "dd20": last / max(c[-21:]) - 1, "from_hi": last / max(c[-250:]) - 1,
            "r20": last / c[-21] - 1, "hi5": max(c[-5:]), "low20": min(c[-20:]), "sma50": st.mean(c[-50:]),
            "nq20": (nq[-1] / nq[-21] - 1) if len(nq) > 21 else None, "vix": vix[-1] if vix else None,
            "tnx": tnx[-1] if tnx else None, "tnx20": (tnx[-1] - tnx[-21]) * 100 if len(tnx) > 21 else None}


def build_us() -> dict:
    k = _spx_state()
    stu = _j("studies/crash_rebound.json", {}) or {}
    b = stu.get("spx_buckets20") or {}
    dd = k.get("dd20", 0) if k else 0
    key = "correction" if dd <= -0.07 else "pullback" if dd <= -0.02 else "near_high"
    if k and k.get("ret1", 0) <= -0.02 and b.get("drop2"):
        key = "drop2"
    p = b.get(key) or b.get("all") or {"bull": 0.4, "base": 0.4, "bear": 0.2, "n": 0}
    basis = {"near_high": "고점 부근(20일 고점 대비 −2% 이내)", "pullback": "눌림(−2~−7%)", "correction": "조정(−7% 이상)", "drop2": "하루 −2% 이상 하락", "all": "전체"}[key]
    peers = (_j("peers_US.json", {}) or {}).get("rows", [])
    by = {}
    for r in peers:
        if r.get("r20") is not None and r.get("g"):
            by.setdefault(r["g"], []).append(r)
    secs = []
    for g, a in by.items():
        if len(a) < 5:
            continue
        w = [x.get("mc") or 1 for x in a]
        secs.append({"sector": g, "n": len(a), "r5": sum(wi * (x.get("r5") or 0) for wi, x in zip(w, a)) / sum(w),
                     "r20": sum(wi * x["r20"] for wi, x in zip(w, a)) / sum(w),
                     "drv": st.mean([x["drv"] for x in a if x.get("drv") is not None] or [0])})
    for x in secs:
        x["stance"] = "비중 확대" if x["drv"] >= 0.25 else "비중 축소" if x["drv"] <= 0.0 else "중립"
    secs.sort(key=lambda x: -x["drv"])
    longs = [r for r in peers if (r.get("drv") or 0) >= 0.4 and (r.get("r20") or 0) <= -0.03]
    longs.sort(key=lambda r: -(r["drv"]))
    avoid = [r for r in peers if r.get("drv") is not None and r["drv"] <= -0.2 and (r.get("r20") or 0) >= 0.05]
    avoid.sort(key=lambda r: r["drv"])
    f = lambda r: {"s": r["s"], "n": r["n"], "g": r["g"], "drv": r.get("drv"), "r20": r.get("r20"), "r5": r.get("r5")}  # noqa: E731
    cal = (_j("calendar.json", {}) or {}).get("events", [])
    today = date.today()
    ev = [e for e in cal if today <= date.fromisoformat(e["date"]) <= today + timedelta(days=10) and (e.get("market") == "US" or e["type"] == "매크로")]
    head = []
    if k:
        head.append(f"S&P500 {k['last']:,.0f} ({k['ret1']*100:+.1f}%) · 20일 {k['r20']*100:+.1f}% · 20일 고점 대비 {k['dd20']*100:+.1f}% · 52주 고점 대비 {k['from_hi']*100:+.1f}%")
        head.append(f"나스닥 20일 {(k.get('nq20') or 0)*100:+.1f}% · VIX {k.get('vix') or 0:.1f} · 미 10년 {k.get('tnx') or 0:.2f}% (20일 {k.get('tnx20') or 0:+.0f}bp)")
    lo = k.get("low20") if k else None
    scen = [
        {"name": "강세 — 고점 경신", "prob": p.get("bull"), "def": "20거래일 뒤 S&P500 +3% 초과",
         "trigger": "빅테크 실적(10/21~29)에서 설비투자·클라우드 성장 상향 + 10년 금리 하락 전환",
         "action": "미국 반도체·AI 인프라 비중 유지, 원화 강세 시 달러 자산 추가 매수 기회"},
        {"name": "기본 — 박스권", "prob": p.get("base"), "def": "20거래일 뒤 ±3% 이내",
         "trigger": "실적은 부합, 금리 5% 근처 횡보",
         "action": "종목 교체(이익 추정 상향 종목으로), 비중 유지"},
        {"name": "약세 — 금리·밸류 조정", "prob": p.get("bear"), "def": f"20거래일 뒤 −3% 미만 (그중 −10% 미만 {(p.get('deep_bear') or 0)*100:.0f}%)",
         "trigger": f"10년 금리 5.3% 돌파, 또는 빅테크 설비투자 가이던스 하향, 또는 S&P 20일 저점({lo or 0:,.0f}) 이탈",
         "action": "반도체·고PER 비중 축소, SH/PSQ 소량 헷지, 한국 메모리도 같은 신호로 축소(연결 규칙)"},
    ]
    best = max(scen, key=lambda s: s.get("prob") or 0)
    out = {"asof": datetime.now().strftime("%Y-%m-%d %H:%M"), "date": str(today), "market": "US", "head": head,
           "verdict": f"가장 가능성 높은 시나리오: {best['name']} ({(best['prob'] or 0)*100:.0f}%) — 근거: 1999년 이후 S&P500 '{basis}' {p.get('n') or 0}회",
           "scenarios": scen, "scenario_basis": {"basis": basis, "n": p.get("n")}, "sectors": secs,
           "ideas": {"long": [f(r) for r in longs[:10]], "avoid": [f(r) for r in avoid[:8]]}, "events": ev[:12],
           "kr_link": "한국 메모리 판단의 선행 지표: 빅테크 설비투자 가이던스(10/21 메타, 10/28 MSFT·구글, 10/29 아마존) · 마이크론 EPS 추정 · TSMC 가이던스"}
    OUT_US.write_text(json.dumps(out, ensure_ascii=False, default=str), encoding="utf-8")
    log.info("미장 운용회의 생성")
    return out


def telegram_text_us(o: dict) -> str:
    L = ["🗽 <b>미장 운용회의</b> · " + o["date"]] + [f"• {x}" for x in o["head"]]
    L += ["", "<b>[시나리오]</b> " + o["verdict"]]
    for s in o["scenarios"]:
        L.append(f"• {s['name']} {(s['prob'] or 0)*100:.0f}% — 신호: {s['trigger']}")
    up = [x for x in o["sectors"] if x["stance"] == "비중 확대"][:4]
    dn = [x for x in o["sectors"] if x["stance"] == "비중 축소"][:3]
    L.append("<b>[섹터]</b> 확대: " + (", ".join(f"{x['sector']}({x['drv']:+.2f})" for x in up) or "—") + " / 축소: " + (", ".join(x["sector"] for x in dn) or "—"))
    if o["ideas"]["long"]:
        L.append("<b>[매수 후보]</b> " + ", ".join(f"{x['s']} {x['drv']:+.2f}" for x in o["ideas"]["long"][:6]))
    L.append("<i>" + o["kr_link"] + "</i>")
    return "\n".join(L)
