"""운용회의 — 터미널에 쌓인 데이터로 매일 '센터장 회의 자료'를 만들고, 회의의 판단을 기록해 나중에 채점.

구성
1. 탑다운: 매크로 바람·시장 폭·지수 위치·이벤트(7일)
2. 업종 의견: 공급망 체인 점수 + 테마 5·20일 성과 → 비중 확대 / 중립 / 축소
3. 종목 아이디어: 이익 신호는 좋은데 과하게 빠진 종목(매수 후보) / 이익 신호가 꺾였는데 비싼 종목(회피)
4. 운용 시나리오 3개: 강세·기본·약세 — 확률(1999~ 코스피 조건부 통계), 전환 신호, 행동
5. 검증 현황: 시그널 판정·과거 회의 성적
6. 판정(_stance)·실행 대본(_exec_plan): **1차 신호 = 급락일 종가**(코스피 장중/종가 ≤ −5.0%, 등급은 views/registry.json `crash_day_close` 를 그대로 인용).
   급락일엔 외국인 수급과 무관하게 '분할 매수'(1차 집행). '회복 확인'은 외국인 2일 조건을 빼고 **20일선 2일 연속 회복**(노출 상향 기준)으로 본다.
   — 10/15 복기: 외국인 2일 조건이 1등 신호(급락일 종가)를 막아 '관망'을 냈음. 모델(운용회의·알림)만 바꾸며 규정 원본(rules.txt)은 별도 결정.
기록 → reports/committee_hist.json, 다음 실행부터 5·20거래일 성과로 채점.
"""
from __future__ import annotations

import json
import logging
import statistics as st
from datetime import date, datetime, timedelta

from zoneinfo import ZoneInfo

from .config import DATA_DIR, REPORT_DIR
from .calendar_ev import capex_line, release_line

KST = ZoneInfo("Asia/Seoul")


def _kst_today() -> date:
    return datetime.now(KST).date()


from .kospi_ma import sma_streak, sma_tail
from .guard import write_json as _gw   # asof 단조 가드 (date 역행 시 쓰지 않음)
log = logging.getLogger(__name__)
OUT = REPORT_DIR / "committee.json"
HIST = REPORT_DIR / "committee_hist.json"
SEMI_G = ("반도체", "반도체 장비·소재", "디스플레이")


def _j(name: str, default=None):
    try:
        return json.loads((REPORT_DIR / name).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def _ai_credit_line() -> str | None:
    """채권 탭 'AI 인프라 신용 감시'가 주의 이상일 때만 한 줄 (5일 넘은 값은 무시). 실패해도 회의엔 영향 없음."""
    try:
        a = (_j("bonds.json", {}) or {}).get("ai_credit") or {}
        al = a.get("alert") or {}
        if int(al.get("lv") or 0) >= 1 and al.get("line") and a.get("asof") \
                and (_kst_today() - date.fromisoformat(str(a["asof"])[:10])).days <= 5:
            return str(al["line"]) + " (채권 탭)"
    except Exception as e:  # noqa: BLE001
        log.info("AI 인프라 신용 줄 실패: %s", e)
    return None


def _btc_line() -> str | None:
    """비트코인 한 줄(req-dev-54eba83d 5단계) — reports/btc.json. 24시간 시장이라 확정 UTC 일봉과 진행 중 봉을 날짜로 갈라 적는다.
    5일 넘은 값은 무시, 실패해도 회의엔 영향 없음."""
    try:
        b = _j("btc.json", {}) or {}
        if not b.get("ok") or not b.get("closed_asof") \
                or (_kst_today() - date.fromisoformat(str(b["closed_asof"])[:10])).days > 5:
            return None
        s = f"비트코인 {b['close']:,.0f}달러(UTC 일봉 {str(b['closed_asof'])[5:]} 확정, {b['chg_1d_pct']:+.1f}%)"
        if b.get("live_px") and b.get("live_date"):
            s += f" · 진행 중 {str(b['live_date'])[5:]} {b['live_px']:,.0f}달러({(b.get('chg_live_pct') or 0):+.1f}%)"
        s += f" · 추세 {b.get('trend')} · ATR {b.get('atr14_pct')}%"
        if b.get("alert"):
            s += f" · ±{b.get('alert_pct'):g}% 변동 경보"
        return s
    except Exception as e:  # noqa: BLE001
        log.info("BTC 줄 실패: %s", e)
    return None


def _kospi_state() -> dict:
    src = "야후 일봉"
    ms = (_j("macro_series.json", {}) or {}).get("series", {}).get("KOSPI") or []
    c = [r[4] if len(r) >= 6 else r[1] for r in ms]
    lo = [r[3] if len(r) >= 6 else r[1] for r in ms]
    # 야후 지수는 장중·장 마감 직후 늦게 갱신됨 → KRX 확정 일봉(또는 장중)으로 오늘 값을 덮어씀
    try:
        from pykrx import stock  # type: ignore
        t = _kst_today()
        df = stock.get_index_ohlcv((t - timedelta(days=7)).strftime("%Y%m%d"), t.strftime("%Y%m%d"), "1001")
        if df is not None and len(df):
            d0 = str(df.index[-1].date())
            cl, lw = float(df["종가"].iloc[-1]), float(df["저가"].iloc[-1])
            if ms and str(ms[-1][0]) == d0:
                c[-1], lo[-1] = cl, lw
            elif ms and str(ms[-1][0]) < d0:
                c.append(cl)
                lo.append(lw)
            now = datetime.now(KST)
            closed = d0 < str(now.date()) or now.hour * 100 + now.minute >= 1535
            src = f"KRX {'확정 종가' if closed else '장중 ' + now.strftime('%H:%M')} {d0[5:]}"
    except Exception as e:  # noqa: BLE001
        log.info("KRX 지수 덮어쓰기 실패: %s", e)
    if len(c) < 30:
        return {}
    last = c[-1]
    return {"last": last, "ret1": last / c[-2] - 1, "dd20": last / max(c[-21:]) - 1, "from_hi": last / max(c[-250:]) - 1,
            "low_today": lo[-1], "low20": min(lo[-20:]), "hi5": max(c[-5:]), "src": src, "sma20": sma_tail(c, 20), "sma50": sma_tail(c, 50),
            "prev_close": c[-2], "above20_streak": _above_sma_streak(c, 20)}


def _above_sma_streak(c: list[float], n: int = 20) -> int:
    """끝에서부터 종가가 n일 이동평균 위인 날이 몇 일 연속인지 (회복 확인 = 20일선 2일 연속 회복). 계산은 kospi_ma 단일."""
    return sma_streak(c, n)


from .defs import CRASH_NEAR_PCT, CRASH_PCT   # −5% / −4% (단일 원천 screener/defs.py)


def crash_day_grade() -> str:
    """views/registry.json `crash_day_close` 의 evidence.grade 를 그대로 반환 (없으면 '검증전')."""
    try:
        reg = json.loads((REPORT_DIR.parent / "views" / "registry.json").read_text(encoding="utf-8"))
        for l in reg.get("lenses") or []:
            if isinstance(l, dict) and l.get("id") == "crash_day_close":
                return str(((l.get("evidence") or {}).get("grade")) or "검증전")
    except Exception as e:  # noqa: BLE001
        log.info("registry 등급 읽기 실패: %s", e)
    return "검증전"


def crash_flag(k: dict) -> dict:
    """급락일 판정: 코스피 장중 저가 또는 종가가 전일 종가 대비 ≤ −5.0% → crash, ≤ −4.0% → near.
    반환 {crash, near, ret1, low_ret, grade, thr}. k 가 비면 전부 False."""
    ret1 = k.get("ret1") if k else None
    if ret1 is None:
        return {"crash": False, "near": False, "ret1": None, "low_ret": None, "grade": crash_day_grade(), "thr": CRASH_PCT}
    prev = k.get("prev_close") or ((k.get("last") or 0) / (1 + ret1) if k.get("last") else None)
    low_ret = (k["low_today"] / prev - 1) if (k.get("low_today") and prev) else None
    worst = min(x for x in (ret1, low_ret) if x is not None)
    return {"crash": worst <= CRASH_PCT, "near": worst <= CRASH_NEAR_PCT, "ret1": ret1, "low_ret": low_ret,
            "grade": crash_day_grade(), "thr": CRASH_PCT}


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
         "trigger": f"코스피 20일선({k.get('sma20') or 0:,.0f}) 2일 연속 종가 회복 (노출 상향 기준 · 외국인 조건 없음)",
         "action": "반도체는 테마 한도(40%) 넘는 만큼 반등 때 덜고, 현금 분할 매수 2차 집행(비반도체 우선), 인버스 헷지 해제"},
        {"name": "기본 — 반등 후 박스", "prob": p.get("base"), "def": "20거래일 뒤 ±5% 이내",
         "trigger": f"오늘 저점({lowt:,.0f}) 지지, 외국인 매도 둔화(일 −1조 이내)",
         "action": "반등 때 중복·약한 고리 축소(ETF 중복, 평균이익 기준 고평가), 실적 시즌(10/21~29) 확인 전 비중 유지"},
        {"name": "약세 — 연속 급락(6월 말 패턴)", "prob": p.get("bear"), "def": "20거래일 뒤 −5% 미만 (그중 −15% 미만 " + f"{(p.get('deep_bear') or 0)*100:.0f}%)",
         "trigger": f"오늘 저점({lowt:,.0f}) 2일 연속 종가 이탈, 또는 2단계 서킷, 또는 빅테크 설비투자 가이던스 하향",
         "action": "손실 한도·가격 규칙 기계적 집행(메모리 절반 축소), 인버스 25% 헷지, 현금 비중 확대"},
    ], {"basis": cond, "macro": mvs, **_basis_fields(p, (b.get("all") or {}).get("n"))}


def _basis_fields(p: dict, n_all) -> dict:
    """시나리오 근거 n(겹치는 20일 창) + 독립 20일 블록 수(n_indep 또는 범위) — 국장·미장 공용 (screener/us_committee.basis_fields)."""
    from .us_committee import basis_fields
    return basis_fields(p or {}, n_all)


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
        d = _kst_today() - timedelta(days=1)
        while len(out) < 2 and d > _kst_today() - timedelta(days=7):
            if d.weekday() < 5:
                v = (investor_totals(d).get("KOSPI") or {}).get("외국인")
                if v is not None:
                    out.append(float(v))
            d -= timedelta(days=1)
    except Exception as e:  # noqa: BLE001
        log.info("수급 실패: %s", e)
    return out


def _stance(k: dict, scen: list[dict], sb: dict, stu: dict, ev7: list[dict], der: dict) -> dict:
    """시나리오 확률 ≠ 행동. 1차 신호는 '급락일 종가'(장중/종가 ≤ −5%): 그날은 외국인 수급과 무관하게 '분할 매수'(1차 집행).
    급락일이 아니면 '회복 확인'(20일선 2일 연속 회복)에만 분할 매수, 20일 저점 이탈이면 방어, 그 외 관망 — 이유는 데이터로 적는다."""
    bull = next((s for s in scen if s["name"].startswith("강세")), {})
    pb, n = bull.get("prob") or 0, sb.get("n") or 0
    reasons = []
    cf = crash_flag(k)
    if cf["crash"]:
        reasons.append({"t": f"급락일 종가 — 1차 신호 충족 (등급 {cf['grade']})",
                        "d": f"코스피 종가 {cf['ret1']*100:+.1f}%" + (f" · 장중 저가 {cf['low_ret']*100:+.1f}%" if cf.get("low_ret") is not None else "")
                             + f" ≤ {CRASH_PCT*100:.1f}%. 급락일 종가 매수: 20일 +7.5%·승률 81%(n=16, entry_signals) — 저점 지지·5일 고점 기다리기보다 우월. 외국인 수급은 조건이 아님(10/15 복기)."})
    elif cf["near"]:
        reasons.append({"t": "급락일 근접 (−4% 이하)", "d": f"코스피 {cf['ret1']*100:+.1f}% — 15:05 재점검, 종가/저가 −5% 도달 시 1차 신호."})
    if n:
        se = (pb * (1 - pb) / n) ** 0.5
        reasons.append({"t": "확률은 1등이지만 과반이 아님",
                        "d": f"강세 {pb*100:.0f}%는 '강세가 아닐 확률' {100-pb*100:.0f}%와 같은 말. 표본 {n}회라 오차 범위가 대략 {max(0,pb-1.96*se)*100:.0f}~{min(1,pb+1.96*se)*100:.0f}%로 넓음 — 동전 던지기와 통계적으로 잘 구분되지 않음."})
    last, sma20 = k.get("last"), k.get("sma20")
    streak = int(k.get("above20_streak") or 0)
    met_rec = streak >= 2
    reasons.append({"t": "회복 확인 충족 (20일선 2일 연속)" if met_rec else "회복 확인 미충족",
                    "d": f"규칙: 코스피 종가가 20일선({sma20 or 0:,.0f}) 위 2일 연속 → 노출 상향(2차). 현재 {last or 0:,.0f}, 20일선 위 {streak}일. "
                         "외국인 2일 순매수 조건은 삭제(entry_signals F — 10/15 급락일 1차 신호를 막은 조건)."})
    if k.get("ret1") is not None and k.get("low_today") and last:
        nearlow = (last / k["low_today"] - 1) < 0.01
        reasons.append({"t": "종가가 저가권" if nearlow else "장중 저가 대비 반등",
                        "d": f"하루 {k['ret1']*100:+.1f}%, 저가 {k['low_today']:,.0f} 대비 {'현재' if '장중' in str(k.get('src', '')) else '종가'} {(last/k['low_today']-1)*100:+.1f}%. " +
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
    if cf["crash"]:
        st_ = "분할 매수"   # 1차 신호: 급락일 종가 — 외국인 수급·20일 저점 여부와 무관하게 1차 집행
        plan = (f"급락일 종가 1차 매수(등급 {cf['grade']}) — 15:20 동시호가. 크기 = 해금 단계 리스크(1단계 0.25%). "
                "실계좌 신규는 해금 후(11/16), 그 전엔 모의 '나' 픽 + ISA 선매수(승인 시). 반도체 테마 한도 40% 안에서(신규는 비반도체). 레버리지 없음.")
    elif met_rec:
        st_ = "분할 매수"
        plan = "회복 확인(20일선 2일 연속) — 노출 상향: 현금 1/3씩 분할 집행, 반도체 테마 한도 40% 안에서(신규는 비반도체)."
    elif k.get("low20") and last and last < k["low20"] * 0.995:
        st_ = "방어"
        plan = "20일 저점 이탈 — 가격 규칙 기계적 집행, 인버스 25% 헷지. 단 하루 −5% 급락이 오면 그날 종가는 1차 신호(위 규칙 우선)."
    else:
        st_ = "관망"
        plan = (f"오늘은 현금 유지. 1차 신호 = 급락일 종가(코스피 −5%, 15:05 점검) · 2차 = 20일선({sma20 or 0:,.0f}) 2일 연속 회복 시 노출 상향. "
                "외국인 수급은 조건이 아님.")
    return {"stance": st_, "plan": plan, "reasons": reasons, "crash_day": cf,
            "summary": (f"PB 판단: {st_} — 1차 신호(급락일 종가)·2차 신호(20일선 2일 회복) 모두 미충족 (확률 = 방향, 신호 = 타이밍)" if st_ == "관망"
                        else f"PB 판단: {st_}" + (f" — 급락일 종가 1차 집행 (등급 {cf['grade']})" if cf["crash"] else ""))}


def _bars(code: str, market: str = "KR") -> list[dict]:
    try:
        return json.loads((REPORT_DIR / "detail" / market / f"{code}.json").read_text(encoding="utf-8")).get("chart") or []
    except Exception:  # noqa: BLE001
        return []


def _risk_box(code: str, market: str = "KR") -> dict | None:
    """리스크 프레임 [1][2][3]: 손절 = max(20일 저점, 종가−2×ATR14), 목표 = 2R, 비중 = 1% 리스크 ÷ 손절폭 (단일 15% 상한). market=US 면 detail/US chart."""
    b = [x for x in _bars(code, market) if x.get("c") and x.get("h") and x.get("l")]
    if len(b) < 21:
        return None
    c = b[-1]["c"]
    tr = [max(b[i]["h"], b[i - 1]["c"]) - min(b[i]["l"], b[i - 1]["c"]) for i in range(len(b) - 14, len(b))]
    atr = sum(tr) / len(tr)
    stop = max(min(x["l"] for x in b[-20:]), c - 2 * atr)
    stop = min(stop, c - atr)   # 최소 1×ATR 여유 — 하루 소음에 털리지 않게
    sp = (c - stop) / c
    if sp <= 0:
        return None
    full = min(0.01 / sp, 0.15)
    return {"close": c, "atr_pct": atr / c, "stop": stop, "stop_pct": sp, "target": c + 2 * (c - stop),
            "size_full": full, "size_1st": full / 2, "skip": sp > 0.15}


def _exec_plan(k: dict, stance: dict, der: dict, longs: list[dict]) -> dict:
    """운용회의 → 실행 대본 (PB 북 = 기관처럼 매일 시장 참여한다는 가정의 모델 포트폴리오).
    언제·무슨 조건이면·무엇을·얼마나·어디서 손절/익절. 비중은 총자산 % (금액·개인 보유 내역은 공개 파일에 안 씀)."""
    lowt, hi5, last = k.get("low_today") or 0, k.get("hi5") or 0, k.get("last") or 0
    neg = der.get("gex_bn") is not None and der["gex_bn"] < 0
    cf = (stance or {}).get("crash_day") or crash_flag(k)
    g = cf.get("grade") or crash_day_grade()
    # 2026-10-16 백테스트(reports/studies/playbook_signals.md, 2010~2026 코스피 급락 55건): 저점 지지·5일 고점 2차·약세 경로 청산은
    # 전부 '급락일 종가 매수'보다 나빴음 → 1차 신호 = 급락일 종가(등급은 registry 인용). 외국인 수급은 이력이 없어 검증 불가 → 신호에서 제외.
    sig = [{"t": f"급락일 종가 — 1차 신호 (등급 {g}, 코스피 장중/종가 ≤ −5%)",
            "now": (f"{cf['ret1']*100:+.1f}%" + (f" · 저가 {cf['low_ret']*100:+.1f}%" if cf.get("low_ret") is not None else "")) if cf.get("ret1") is not None else "데이터 없음",
            "ok": bool(cf.get("crash"))},
           # 10/16 재검증(reports/studies/exec_signal.md): 'last >= lowt'는 종가 ≥ 저가라 항상 참(결함) → 저가 +1% 위 마감(C등급)으로 교정. 2차 참고.
           {"t": f"오늘 저점 {lowt:,.0f} +1% 위 마감 (C — 2차 참고)", "now": f"{last:,.0f}", "ok": bool(last and lowt and last >= lowt * 1.01)},
           {"t": f"20일선({k.get('sma20') or 0:,.0f}) 2일 연속 회복 (노출 상향 기준)", "now": f"{last:,.0f} · 위 {int(k.get('above20_streak') or 0)}일", "ok": int(k.get("above20_streak") or 0) >= 2},
           {"t": f"5일 고점 {hi5:,.0f} (참고 — 2차 조건에서 제외)", "now": f"{last:,.0f}", "ok": bool(last and hi5 and last >= hi5)}]
    cands = []
    for x in longs:
        if x.get("semi"):
            continue
        rb = _risk_box(x["s"])
        if not rb or rb["skip"]:
            continue
        cands.append({"s": x["s"], "n": x["n"], "g": x.get("g"), "drv": x.get("drv"),
                      **{kk: rb[kk] for kk in ("close", "atr_pct", "stop", "stop_pct", "target", "size_1st", "size_full")}})
        if len(cands) >= 3:
            break
    steps = [
        {"when": f"급락일 종가 1차 매수 — 15:20 동시호가 (1차 신호 · 등급 {g})" + (" · 오늘 충족" if cf.get("crash") else " · 오늘 미충족"),
         "do": "크기 = 해금 단계 리스크(1단계 0.25%) · 실계좌 신규는 해금 후(11/16), 그 전엔 모의 '나' 픽 + ISA 선매수(승인 시)",
         "why": "급락일 종가: 20일 +7.5%·승률 81%(n=16, entry_signals). 신호 기다리기(저점 지지·5일 고점)는 20일 −2.2~−5.7%p 나빴음. 10/15 외국인 2일 조건이 이 신호를 막음 → 조건 삭제"},
        {"when": "장 시작 직후", "do": "급하게 안 사도 됨 — 시초가 호가가 얇으면 30분 뒤" + (" (옵션 감마 음수: 장 초반 흔들림 큼)" if neg else ""),
         "why": "체결 품질 때문이지 엣지는 아님 (다음 날 시가 vs 종가 차이 +0.1%p, 유의하지 않음)"},
        {"when": "2차 (참고)", "do": "저가 +1% 위 마감(C)은 참고만 · 노출 상향은 20일선 2일 연속 회복 시",
         "why": "'5일 고점 회복 시 추가'는 반등 대부분을 놓쳐서 −3.9%p(20일). 대안(10일 내 추가 −5% 시 같은 크기)은 사전등록 후 재검증"},
        {"when": "익절", "do": "+1R에서 1/3, +2R에서 1/3, 나머지는 최고가−3×ATR 트레일링",
         "why": "손익비 1:2 이상 확보 후 추세는 끌고 감"},
        {"when": "반등 구간 (어느 날이든)", "do": "반도체 비중을 테마 한도 40%까지 단계적 축소",
         "why": "진입보다 쏠림 해소가 먼저. 반등은 비싼 쪽을 덜 기회"},
        {"when": f"약세 경로 (저점 {lowt:,.0f} 2일 연속 종가 이탈)", "do": "경보: 신규 진입 중단 + 레버리지·인버스 노출 점검. 청산은 종목별 손절선만",
         "why": "지수 기준 일괄 청산은 급락 55건 중 53%에서 발동해 −4.0%p(20일). 계획한 종목 손절은 협상 대상 아님"},
    ]
    dont = ["레버리지 (급락일에도)", "반도체 물타기", "장중 −3%에 손절선 옮기기", "손절선 없는 매수", "급락일 근거 없는 관망(안 하면 사유 기록)"]
    return {"book": "PB 북 — 기관처럼 매일 시장 참여 가정 (겸이 실계좌 적용은 성적표 '실전 적용'에서)",
            "signals": sig, "steps": steps, "cands": cands, "dont": dont, "crash_day": cf, "primary": "crash_day_close",
            "note": "비중 = 총자산 대비 %. 1차 비중 = min(1% ÷ 손절폭, 15%) ÷ 2. 손절 = max(20일 저점, 종가 − 2×ATR14). 목표 = 2R. 손절폭 15% 초과 종목 제외."}


SIM_FRESH_TOP = 5       # 운용회의 화면 상위 N
SIM_FRESH_TG = 3        # 텔레그램 최대 줄 수
SIM_FRESH_MAX_AGE = 5   # 일 — 이보다 오래된 집계는 쓰지 않음


def _sim_fresh(market: str = "KR") -> dict | None:
    """종목 상세 TREND SIMULATION 의 '새로 켜진 추세 신호' 집계(reports/sim_signals_{market}.json, detail.build 산출) → 운용회의 블록.
    보유·관심 종목 우선 표시는 하지 않는다(개인 보유는 공개 파일 금지). 파일이 없거나 오래되면 None + 로그 1줄."""
    d = _j(f"sim_signals_{market}.json")
    ex = _sim_exp(market, d)
    if not d or not d.get("asof"):
        log.info("sim_fresh 생략: sim_signals_%s.json 없음", market)
        return {"asof": ex["asof"], "market": market, "items": [], "wilson_missing": True, "exp": ex} if ex else None
    if not _fresh_age_ok(d["asof"]):
        log.info("sim_fresh 생략: sim_signals_%s.json 기준일 %s (%s일 초과)", market, d.get("asof"), SIM_FRESH_MAX_AGE)
        return {"asof": ex["asof"], "market": market, "items": [], "wilson_missing": True, "exp": ex} if ex else None
    items = []
    for r in (d.get("rows") or [])[:SIM_FRESH_TOP]:
        vs = (f"1년 전략 {r['ret']*100:+.0f}% vs 보유 {r['bh']*100:+.0f}%"
              if r.get("ret") is not None and r.get("bh") is not None else "1년 성과 —")
        items.append({"s": r["s"], "n": r.get("n") or r["s"], "label": r.get("label") or r.get("strategy"),
                      "wins": r.get("wins"), "trades": r.get("trades"), "wilson_lo": r.get("wilson_lo"),
                      "ret": r.get("ret"), "bh": r.get("bh"), "entry_date": r.get("entry_date"),
                      "line": f"{r.get('n') or r['s']} · {r.get('label') or r.get('strategy')} · 승률 {r.get('wins')}/{r.get('trades')}"
                              f"(하한 {(r.get('wilson_lo') or 0)*100:.0f}%) · {vs}"})
    b1 = _b1_ref(market)
    ad = _adopt_pending(market)
    return {"asof": d["asof"], "market": market, "n_scanned": d.get("n_scanned"), "n_pass": d.get("n_pass", len(d.get("rows") or [])),
            "n_eligible": d.get("n_eligible"), "expected_chance": d.get("expected_chance"), "grade": d.get("grade"),
            "criteria": d.get("criteria"), "items": items, **({"exp": ex} if ex else {}), **({"b1": b1} if b1 else {}), **({"adopt": ad} if ad else {})}


def _b1_ref(market: str) -> dict | None:
    """KR 52주 고점 근접(alpha_sources B1) 참고 목록 — reports/trend_discovery_KR.json b1_ref (겸이 결재 10/24 ②). 표시 전용·주문 근거 아님."""
    if market != "KR":
        return None
    td = _j("trend_discovery_KR.json", {}) or {}
    b = td.get("b1_ref")
    if not b or not _fresh_age_ok(td.get("asof")):
        return None
    return {**b, "asof": td.get("asof")}


def _adopt_pending(market: str) -> dict | None:
    """국장 새 추세 진입(hi52 A·gcv/sqz B) '편입 대기' 목록 — reports/trend_discovery_KR.json adopt_pending (겸이 결재 10/24, req-quant-d5d2f400).
    분산 전제·확신도 low·추격 제외·주문 근거 아님. 미장 없음. 판정(11/20~)은 scripts/trend_adopt_judge.py → 보드 결재, 자동 승격 없음."""
    if market != "KR":
        return None
    td = _j("trend_discovery_KR.json", {}) or {}
    b = td.get("adopt_pending")
    if not b or not _fresh_age_ok(td.get("asof")):
        return None
    return {**b, "asof": td.get("asof")}


def _trend_off(sym: str, market: str = "US") -> bool | None:
    """정식 이평 추세 롱(detail sim ma.long) 이 지금 보유 아님 = '추세 꺼짐'. 파일·시뮬 없으면 None (겸이 결재 10/24 ③, 표시만·규칙 불변)."""
    try:
        d = json.loads((REPORT_DIR / "detail" / market / f"{sym}.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    r = ((d.get("sim") or {}).get("ma") or {}).get("long") or {}
    return None if not r else r.get("pos") != 1


def _fresh_age_ok(asof) -> bool:
    try:
        return (_kst_today() - date.fromisoformat(str(asof)[:10])).days <= SIM_FRESH_MAX_AGE
    except ValueError:
        return False


def _sim_exp(market: str, d: dict | None) -> dict | None:
    """기대값 t 하한 규칙(사전등록 2026-10-17, 오너 승인 14:09) — 'C·참고' 표시 전용, 주문표 근거 불가, 텔레그램 미발송.
    원천: sim_signals_{market}.json 의 exp 블록(파이프라인) → 없으면 reports/studies/trend_expectancy.json(연구 스크립트) 같은 시장."""
    ex, asof, src = (d or {}).get("exp"), (d or {}).get("asof"), f"sim_signals_{market}.json"
    if not ex or not _fresh_age_ok(asof):
        st = _j("studies/trend_expectancy.json", {}) or {}
        m = next((x for x in st.get("markets") or [] if x.get("market") == market), None)
        if not m or not _fresh_age_ok(m.get("asof")):
            return None
        ex, asof, src = m.get("exp") or {}, m.get("asof"), "studies/trend_expectancy.json"
    items = [{"s": r["s"], "n": r.get("n") or r["s"], "label": r.get("label") or r.get("strategy"), "trades": r.get("trades"),
              "exp": r.get("exp"), "exp_lb": r.get("exp_lb"), "win": r.get("win"), "entry_date": r.get("entry_date")}
             for r in (ex.get("rows") or [])[:SIM_FRESH_TOP]]
    return {"label": "C·참고", "asof": asof, "src": src, "n_eligible": ex.get("n_eligible"), "n_pass": ex.get("n_pass", len(items)),
            "expected_chance": ex.get("expected_chance"), "binom_p": ex.get("binom_p"), "grade": ex.get("grade"),
            "criteria": ex.get("criteria"), "items": items}


def _sim_fresh_lines(o: dict) -> list[str]:
    """텔레그램용: 머리 1줄 + 최대 SIM_FRESH_TG 줄. 통과 0건이면 빈 목록."""
    b = o.get("sim_fresh") or {}
    it = (b.get("items") or [])[:SIM_FRESH_TG]
    if not it:
        return []
    return ([f"<b>[새로 켜진 추세 신호 · 참고 C]</b> 스캔 {b.get('n_scanned')}종목 · 통과 {b.get('n_pass')} · 기대 우연 {b.get('expected_chance')}"]
            + [f"  · {x['line']}" for x in it])


def build(session: str = "장후") -> dict:
    """session: 장전(08:50) · 장중(10:30·13:30) · 장후(15:45 마감·19:10 저녁). 같은 날 같은 세션은 마지막 실행본이 남음."""
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
    today = _kst_today()
    ev7 = [e for e in cal if today <= date.fromisoformat(e["date"]) <= today + timedelta(days=7) and e.get("imp", 1) >= 2]
    head = []
    if k:
        head.append(f"코스피 {k['last']:,.2f} ({k['ret1']*100:+.1f}%, {k.get('src', '')}) · 20일 고점 대비 {k['dd20']*100:+.1f}% · 52주 고점 대비 {k['from_hi']*100:+.0f}%")
    if mv.get("summary"):
        head.append(mv["summary"])
    _acl = _ai_credit_line()
    if _acl:
        head.append(_acl)
    _btc = _btc_line()
    if _btc:
        head.append(_btc)
    try:   # 일본: 닛케이·일본 피어 그룹·엔 캐리 — 규칙에 걸릴 때만 한 줄
        from . import japan
        _jl = japan.committee_line()
        if _jl:
            head.append(_jl)
    except Exception as e:  # noqa: BLE001
        log.info("일본 줄 실패: %s", e)
    der = {}
    try:
        from . import derivs
        der = derivs.load()
    except Exception:  # noqa: BLE001
        pass
    stance = _stance(k, scen, sb, stu, ev7, der)
    # 판단 시점 기록: 오늘 장중 브리핑 스냅샷(시각 포함)을 함께 남김 — 마감 후 숫자가 바뀌어도 '그때 무엇을 보고 결정했나'가 보이게
    try:
        import re as _re
        _st = (_j("dashboard_state.json", {}) or {}).get("intraday_snapshot") or {}
        if str(_st.get("at", "")).startswith(str(_kst_today())):
            stance["basis"] = {"at": _st["at"], "src": "장중 브리핑 스냅샷 (네이버 잠정)",
                               "lines": [_re.sub(r"<[^>]+>", "", x) for x in (_st.get("value") or {}).get("notes", [])[:5]]}
    except Exception:  # noqa: BLE001
        pass
    try:
        stance["exec"] = _exec_plan(k, stance, der, longs)
    except Exception as e:  # noqa: BLE001
        log.warning("실행 대본 실패: %s", e)
    try:   # VIEW 레지스트리 요약 (views/registry.json → reports/views.json): 진입·자산배분 게이트/기울기/주의
        from . import views as _views
        stance["views"] = _views.committee_summary(_views.build())
    except Exception as e:  # noqa: BLE001
        log.info("VIEW 요약 실패: %s", e)
    _dl = None
    try:
        _dl = _delta_line(k, scen, stance, der, session)
        if _dl:
            head.insert(1, _dl)
    except Exception as e:  # noqa: BLE001
        log.info("직전 회의 대비 줄 실패: %s", e)
    try:   # 매 회의 같은 근거 8개가 반복된다는 피드백(10/16): 직전 회의와 제목·문장(숫자 제외)이 같은 근거는 한 줄로 접는다
        import re as _re2
        _prev = _prev_meeting(session)
        if _prev:
            _norm = lambda r: (r.get("t"), _re2.sub(r"[-−+]?[\d,.]+", "#", r.get("d", "")))  # noqa: E731
            _old = {_norm(r) for r in ((_prev.get("stance") or {}).get("reasons") or [])}
            rs = stance.get("reasons") or []
            new_r = [r for r in rs if _norm(r) not in _old]
            same = [r for r in rs if _norm(r) in _old]
            if same:
                stance["reasons_same"] = same
                stance["reasons"] = new_r + [{"t": f"직전 회의와 같은 근거 {len(same)}개", "d": " · ".join(r["t"] for r in same) + " (숫자만 갱신, 결론 동일)"}]
    except Exception as e:  # noqa: BLE001
        log.info("근거 반복 접기 실패: %s", e)
    best = max(scen, key=lambda s: s.get("prob") or 0)
    verdict = (f"가장 가능성 높은 시나리오: {best['name']} ({(best['prob'] or 0)*100:.0f}%) — 근거: 1999년 이후 '{sb['basis']}' {sb['n'] or 0}회")
    if session == "장후":
        cd = close_delta()
        if cd:
            head.append("장 막판: " + " · ".join(cd[:3]))
    out = {"asof": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "date": str(today), "session": session, "head": head, "verdict": verdict,
           "scenarios": scen, "scenario_basis": sb, "sectors": sectors, "themes": themes[:8] + themes[-5:] if len(themes) > 13 else themes,
           "ideas": {"long": longs, "avoid": avoid}, "squeeze": sq, "events": ev7[:10], "stance": stance,
           "derivs": {k3: der.get(k3) for k3 in ("date", "spot", "pcr_oi", "pcr_vol", "max_pain", "call_wall", "put_wall", "gex_bn", "flip", "atm_iv", "rv20", "skew", "expiry", "dte", "notes", "oi_profile", "hist", "fut")} if der else None,
           "validation": {k2: v.get("verdict") for k2, v in sig.items()}, "scorecard": dec.get("tally", {}),
           "crash_day": stance.get("crash_day") or crash_flag(k)}
    try:   # 매수 후보 '연속 N일째'·신규 표시 (표시만, 산식 불변 — req-dev-42019d08)
        from . import streak as _stk
        _hr = (json.loads(HIST.read_text(encoding="utf-8")) if HIST.exists() else {}).get("rows") or []
        out["ideas_streak"] = _stk.mark(out["ideas"]["long"], _hr, out["date"])
    except Exception as e:  # noqa: BLE001
        log.warning("매수 후보 연속일 표시 실패: %s", e)
    try:   # 새로 켜진 추세 신호 (종목 상세 TREND SIMULATION, 참고 C) — 없으면 키 자체를 뺀다
        _sf = _sim_fresh("KR")
        if _sf:
            out["sim_fresh"] = _sf
    except Exception as e:  # noqa: BLE001
        log.warning("sim_fresh 실패: %s", e)
    try:   # 모닝 미팅 v2 섹션 (기존 키는 유지, 새 키만 추가)
        _v2_build(out, k, der, chains, themes, peers, cal, stu, _bucket(k, stu), _dl, session)
    except Exception as e:  # noqa: BLE001
        log.warning("운용회의 v2 실패: %s", e)
    _gw(OUT, out, key="date", default=str)
    _record(out)
    try:
        out["track"] = score()
        _gw(OUT, out, key="date", default=str)
    except Exception as e:  # noqa: BLE001
        log.warning("운용회의 채점 실패: %s", e)
    try:
        out["track"] = {**(out.get("track") or {}), **_v2_track(out)}
        _gw(OUT, out, key="date", default=str)
    except Exception as e:  # noqa: BLE001
        log.info("운용회의 v2 성적 실패: %s", e)
    _archive("committee", out)
    log.info("운용회의 자료 생성")
    return out


def close_delta() -> list[str]:
    """판단 시점(장중 스냅샷) → 마감 스냅샷 사이 변화: 막판에 누가 샀나/팔았나. 둘 다 오늘 것일 때만."""
    st = _j("dashboard_state.json", {}) or {}
    a, b = st.get("intraday_snapshot") or {}, st.get("close_snapshot") or {}
    t = str(_kst_today())
    if not (str(a.get("at", "")).startswith(t) and str(b.get("at", "")).startswith(t)):
        return []
    va, vb = a.get("value") or {}, b.get("value") or {}
    fa, fb = (va.get("flows") or {}).get("KOSPI") or {}, (vb.get("flows") or {}).get("KOSPI") or {}
    sa, sb = (va.get("snap") or {}).get("KOSPI") or {}, (vb.get("snap") or {}).get("KOSPI") or {}
    L = []
    tm = str(a["at"])[11:16]
    if va.get("kospi_chg") is None:   # 예전 스냅샷: 해석 첫 줄에서 등락률 복원
        import re as _re
        m = _re.search(r"코스피 ([+-−]?\d+\.\d+)%", " ".join(va.get("notes") or []))
        if m:
            va = {**va, "kospi_chg": float(m.group(1).replace("−", "-")) / 100}
    if va.get("kospi_chg") is not None and vb.get("kospi_chg") is not None:
        L.append(f"코스피 {tm} {va['kospi_chg']*100:+.2f}% → 마감 {vb['kospi_chg']*100:+.2f}% ({(vb['kospi_chg']-va['kospi_chg'])*100:+.1f}%p)")
    who = [(w, fb[w] - fa[w]) for w in ("외국인", "기관", "개인") if fa.get(w) is not None and fb.get(w) is not None]
    if who:
        L.append(f"{tm} 이후 순매수 변화: " + " · ".join(f"{w} {v:+,.0f}억" for w, v in who))
    if sa.get("prog_total") is not None and sb.get("prog_total") is not None:
        dn = (sb.get("prog_nonarb") or 0) - (sa.get("prog_nonarb") or 0)
        L.append(f"프로그램 {sb['prog_total']-sa['prog_total']:+,.0f}억 (비차익 {dn:+,.0f}억)" + (" — 막판 바스켓 매수가 반등을 끌어올림" if dn > 1000 else " — 막판 바스켓 매도" if dn < -1000 else ""))
    ta, tb = (sa.get("up") or 0) + (sa.get("down") or 0), (sb.get("up") or 0) + (sb.get("down") or 0)
    if ta and tb:
        L.append(f"하락 종목 비율 {sa['down']/ta*100:.0f}% → {sb['down']/tb*100:.0f}%")
    if L:
        L.append("주의: 장중 값은 잠정치·마감은 확정치라 차이 일부는 집계 보정, 동시호가엔 패시브·차익 정리 물량도 섞임")
    return L


def _prev_meeting(session: str) -> dict | None:
    """직전 운용회의(_index.json 순서상 지금 세션 다음 항목)."""
    hd = REPORT_DIR / "archive" / "committee"
    me = f"{_kst_today()}_{session}"
    try:
        days = json.loads((hd / "_index.json").read_text(encoding="utf-8")).get("days", [])
    except Exception:  # noqa: BLE001
        return None
    days = sorted(days, key=lambda x: str(x.get("asof") or x.get("date") or ""), reverse=True)   # 실제 생성 시각 순
    for x in days:
        fid = x.get("id") or x.get("date")
        if fid == me:
            continue
        try:
            return json.loads((hd / f"{fid}.json").read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
    return None


def _delta_line(k: dict, scen: list[dict], stance: dict, der: dict, session: str) -> str | None:
    """직전 운용회의(다른 세션·이전 날) 대비 무엇이 바뀌었나 — 같은 문장이 반복돼 보이는 문제를 한 줄로 해소."""
    import re as _re
    prev = _prev_meeting(session)
    if not prev:
        return None
    parts = []
    m = _re.search(r"코스피 ([\d,]+\.\d+)", (prev.get("head") or [""])[0])
    if m and k.get("last"):
        pv = float(m.group(1).replace(",", ""))
        parts.append(f"코스피 {pv:,.0f}→{k['last']:,.0f} ({(k['last']/pv-1)*100:+.1f}%)")
    pp = {s["name"].split(" ")[0]: s.get("prob") for s in prev.get("scenarios", [])}
    for s0 in scen:
        nm = s0["name"].split(" ")[0]
        if pp.get(nm) is not None and s0.get("prob") is not None and abs(s0["prob"] - pp[nm]) >= 0.01:
            parts.append(f"{nm} {pp[nm]*100:.0f}→{s0['prob']*100:.0f}%")
    ps, cs = (prev.get("stance") or {}).get("stance"), stance.get("stance")
    parts.append(f"판정 {ps}→{cs}" if ps and ps != cs else f"판정 유지({cs})")
    pd = prev.get("derivs") or {}
    if der.get("pcr_oi") is not None and pd.get("pcr_oi") is not None and abs(der["pcr_oi"] - pd["pcr_oi"]) >= 0.02:
        parts.append(f"PCR {pd['pcr_oi']:.2f}→{der['pcr_oi']:.2f}")
    if der.get("gex_bn") is not None and pd.get("gex_bn") is not None and abs(der["gex_bn"] - pd["gex_bn"]) >= 50:
        parts.append(f"감마 {pd['gex_bn']:,.0f}→{der['gex_bn']:,.0f}억")
    when = f"{str(prev.get('date', ''))[5:]} {prev.get('session', '')} {str(prev.get('asof', ''))[11:16]}".strip()
    return f"직전 회의({when}) 대비: " + " · ".join(parts)


def _archive(kind: str, o: dict) -> None:
    """날짜·세션별 누적: reports/archive/<kind>/YYYY-MM-DD[_세션].json + _index.json. 같은 날 같은 세션은 마지막 실행본."""
    d = str(o.get("date") or o.get("asof", ""))[:10]
    ses = o.get("session") or ""
    fid = f"{d}_{ses}" if ses else d
    hd = REPORT_DIR / "archive" / kind
    hd.mkdir(parents=True, exist_ok=True)
    (hd / f"{fid}.json").write_text(json.dumps(o, ensure_ascii=False, default=str), encoding="utf-8")
    try:
        idx = json.loads((hd / "_index.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        idx = {"days": []}
    head = ((o.get("stance") or {}).get("stance") or "") + " · " + str(o.get("verdict", ""))[:60]
    order = {"장전": 1, "점심": 2, "장중": 3, "장후": 4}
    idx["days"] = sorted([x for x in idx["days"] if x.get("id", x["date"]) != fid] +
                         [{"id": fid, "date": d, "session": ses, "asof": o.get("asof"), "headline": head.strip(" ·")}],
                         key=lambda x: (x["date"], order.get(x.get("session", ""), 0), x.get("asof") or ""), reverse=True)
    (hd / "_index.json").write_text(json.dumps(idx, ensure_ascii=False), encoding="utf-8")


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
    from .prices import load_kr   # 공통 로더 = 기업행위 조정 (px-adjust-unify)
    px = (load_kr(path=p).with_columns(pl.col("yf").str.slice(0, 6).alias("code"), pl.col("date").cast(pl.Utf8))
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


def _hf_attach(out: dict, market: str) -> None:
    """HF 데스크 알파북(모의) 갱신 + 운용회의 개입 4줄(out['hf']) — screener/alphabook.py. 실패는 out['hf'].error."""
    try:
        from . import alphabook
        alphabook.update(out, market)
    except Exception as e:  # noqa: BLE001
        out["hf"] = {"error": f"{type(e).__name__}: {e}"}
        log.warning("HF 알파북 실패(%s): %s", market, e)


def _hf_tail(txt: str, o: dict) -> str:
    tail = list(((o.get("hf") or {}).get("tg") or [])[:6])     # 머리 1 + 진입 근거 4(10/24 겸이 "왜 진입하는지로") + 재량 1
    return txt + ("\n" + "\n".join(tail) if tail else "")


def telegram_text(o: dict) -> str:
    """v2(bottom_line 있음)면 모닝 미팅 요약(25줄 이내), 아니면 예전 전체본. 끝에 HF 알파북 1~2줄 + 재량 북 1줄."""
    if o.get("bottom_line"):
        try:
            return _hf_tail(_telegram_v2(o), o)
        except Exception as e:  # noqa: BLE001
            log.warning("텔레그램 v2 실패 → 예전 형식: %s", e)
    return _hf_tail(_telegram_text_v1(o), o)


def _telegram_text_v1(o: dict) -> str:
    L = ["🏛 <b>운용회의 · " + o.get("session", "") + "</b> · " + o["date"]]
    L += [f"• {x}" for x in o["head"]]
    L += ["", "<b>[시나리오]</b> " + o["verdict"]]
    if o.get("stance"):
        L.append("<b>[" + o["stance"]["summary"] + "]</b>")
        L += [f"  · {r['t']}" for r in o["stance"]["reasons"][:5]]
        L.append("  → " + o["stance"]["plan"])
        ex = o["stance"].get("exec") or {}
        if ex:
            L.append("<b>[실행 대본 — PB 북 기준]</b>")
            L += ["  " + ("✅" if g["ok"] else "⬜") + f" {g['t']} — 현재 {g['now']}" for g in ex["signals"]]
            L += [f"  {i+1}. {st_['when']}: {st_['do']}" for i, st_ in enumerate(ex["steps"])]
            for c in ex.get("cands", []):
                L.append(f"  · {c['n']} 종가 {c['close']:,.0f} · 손절 {c['stop']:,.0f}({-c['stop_pct']*100:.1f}%) · 목표 {c['target']:,.0f}(2R) · 1차 비중 {c['size_1st']*100:.1f}%")
            L.append("  ✖ " + " / ".join(ex["dont"]))
    _vw = (o.get("stance") or {}).get("views") or {}
    if _vw.get("changes"):   # 게이트가 뒤집혔거나 새 주의가 떴을 때만 한 줄
        L.append("🔭 관점 변화: " + " · ".join(_vw["changes"][:4]) + (f" 외 {len(_vw['changes'])-4}건" if len(_vw["changes"]) > 4 else ""))
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
        from .streak import tag as _stag
        L.append("<b>[매수 후보]</b> " + ", ".join(f"{x['n']}{_stag(x)}{'(반도체)' if x['semi'] else ''} 드라이버 {x['drv']:+.2f}" for x in lg))
        if (o.get("ideas_streak") or {}).get("line"):
            L.append("  · " + o["ideas_streak"]["line"])
    av = o["ideas"]["avoid"][:4]
    if av:
        L.append("<b>[회피]</b> " + ", ".join(f"{x['n']} 드라이버 {x['drv']:+.2f}" for x in av))
    if o.get("squeeze"):
        L.append("<b>[숏스퀴즈 후보]</b> " + ", ".join(f"{x['n']} 잔고 {x['ratio']:.1f}%" for x in o["squeeze"][:5]))
    if o.get("events"):
        L.append("<b>[7일 이벤트]</b> " + " / ".join(f"{e['date'][5:]} {e['name']}" for e in o["events"][:6]))
    L += _sim_fresh_lines(o)
    tr = (o.get("track") or {}).get("summary") or {}
    if tr.get("h5"):
        L.append(f"<i>회의 성적: 매수 후보 5일 초과수익 평균 {tr['h5']['long_avg']*100:+.1f}% (적중 {tr['h5']['long_hit']*100:.0f}%, {tr['h5']['n']}회)</i>")
    else:
        L.append("<i>회의 성적: 기록 시작 — 5거래일 뒤부터 채점</i>")
    return "\n".join(L)


# ───────────── 모닝 미팅 v2 (cmt-v2) ─────────────
# 멀티매니저 헤지펀드 데일리 모닝 미팅 형식: 결론(bottom_line) → 탑다운(macro) → 크로스에셋·포지셔닝 → 섹터 → 종목(bottom_up)
# → 트레이드 아이디어(ideas_top) → 헤지·비대칭 → 프리모템 → 성적(track). 숫자는 reports/*.json 에 있는 것만 쓰고, 없으면 그 줄을 뺀다.
# 기존 키(stance·scenarios·ideas·derivs …)는 그대로 두고 새 키만 더한다 (14:42 PB 예약 작업이 기존 키를 읽음).
V2_FOOTER = "실계좌 적용: VIEW 게이트 통과 항목만 (개인 북은 비공개 PB 판단 참조)"
LIGHTS = {"red": "🔴 오늘 행동 필요", "yellow": "🟡 지켜보기", "green": "🟢 할 일 없음"}
BUY_STANCES = ("분할 매수", "비중 확대", "매수")   # 신호등 🔴(후보 기준)을 허용하는 판정 — 관망·중립·방어·비중 축소는 아님


def _live_buy(stance) -> bool:
    from .config import SATELLITE_LIVE
    return bool(SATELLITE_LIVE) and stance in BUY_STANCES


def _mock_gate(bl: dict, ideas: dict) -> dict:
    """B1(10/21): 실계좌 위성 해금 전(또는 판정이 매수 쪽 아님)이면 TOP3 '실행 후보'는 행동이 아니라 모의 추적 —
    🔴 이 아닌 신호등을 🟡 '모의 추적 후보 n개(…)' 로. 텔레그램·화면 모두 bl['label'] 을 그대로 쓴다."""
    n = sum(1 for x in (ideas or {}).get("items", []) if str(x.get("status", "")).startswith("실행"))
    if not n or bl.get("light") == "red" or _live_buy(bl.get("stance")):
        return bl
    from .config import SATELLITE_LIVE
    why = "실계좌 위성 해금 전" if not SATELLITE_LIVE else f"판정 {bl.get('stance') or '—'} — 실계좌 신규 없음"
    note = f"TOP3 실행 후보 {n}개는 모의 추적만({why}) — 실계좌로 옮기지 않음"
    lines = list(bl.get("lines") or [])
    if bl.get("light") == "green" and len(lines) >= 3:
        lines[2] = f"할 일: 판정 유지 · {note}. 하지 말 일: 모의 후보 추격 매수"
    elif len(lines) >= 3:
        lines[2] = lines[2] + f" · {note}"
    return {**bl, "light": "yellow", "label": f"🟡 모의 추적 후보 {n}개({why})", "lines": lines, "mock_n": n}


def _ev_time(e: dict) -> str | None:
    """캘린더 메모에서 한국 시각 추출 ('… → 한국 21:30', '한국 11:00'). 없으면 None."""
    import re as _re
    m = _re.search(r"한국\s*(?:\d{1,2}/\d{1,2}\s*)?(\d{1,2}:\d{2})", str(e.get("note") or ""))
    return m.group(1).zfill(5) if m else None


def _ev_kst_date(e: dict) -> str:
    """이벤트의 한국 날짜(YYYY-MM-DD). 캘린더 date 는 현지(미국) 날짜라 메모 '한국 M/D' 가 있으면 그 날짜를 쓴다
    (예: FOMC date 10-28, 메모 '10/28 14:00 ET → 한국 10/29 03:00' → 10-29). 없으면 date 그대로. req-dev-d624b9cc"""
    import re as _re
    d = str(e.get("date") or "")
    m = _re.search(r"한국\s*(\d{1,2})/(\d{1,2})", str(e.get("note") or ""))
    if not m or len(d) < 10:
        return d
    y, mo = int(d[:4]), int(m.group(1))
    if mo < int(d[5:7]):   # 12/31 ET → 한국 1/1
        y += 1
    return f"{y:04d}-{mo:02d}-{int(m.group(2)):02d}"


def _series_move(ms: dict, key: str, bp: bool = False) -> dict | None:
    """macro_series 마지막 하루 변화와 60일 일간 변화 표준편차 대비 크기(z). bp=True 면 금리(%) 차이를 bp 로."""
    rows = ms.get(key) or []
    c = [r[4] if len(r) >= 6 else r[1] for r in rows]
    c = [x for x in c if x]
    if len(c) < 25:
        return None
    ch = [(c[i] - c[i - 1]) * 100 if bp else c[i] / c[i - 1] - 1 for i in range(max(1, len(c) - 61), len(c))]
    sd = st.pstdev(ch[:-1]) if len(ch) > 5 else 0
    return {"last": c[-1], "d1": ch[-1], "z": (ch[-1] / sd) if sd else None, "date": str(rows[-1][0])}


def _regime(mv: dict) -> dict:
    r = next((x for x in (mv or {}).get("rows", []) if x.get("key") == "KOSPI"), {})
    v50, v200, hi = r.get("vs50"), r.get("vs200"), r.get("from_hi")
    if v50 is None or v200 is None:
        return {}
    if v200 < 0 and v50 < 0:
        lab = "하락장"
    elif v200 < 0 or (hi is not None and hi <= -0.10):
        lab = "회복"
    else:
        lab = "상승"
    return {"label": lab, "line": f"레짐 {lab} — 코스피 200일선 대비 {v200*100:+.1f}%, 50일선 대비 {v50*100:+.1f}%"
            + (f", 52주 고점 대비 {hi*100:+.0f}%" if hi is not None else "") + " (규칙: 200·50일선 위치)"}


def _v2_macro(mv: dict, prev: dict | None) -> dict:
    ms = (_j("macro_series.json", {}) or {}).get("series", {})
    bonds = _j("bonds.json", {}) or {}
    rg = _regime(mv)
    glob, dom, changed = [], [], []
    spec = [("SPX", "S&P500", False), ("NASDAQ", "나스닥", False), ("US10Y", "미 10년", True), ("DXY", "달러인덱스", False),
            ("WTI", "WTI", False), ("VIX", "VIX", False), ("USDJPY", "엔/달러", False), ("NIKKEI", "닛케이", False)]
    for key, nm, bp in spec:
        m = _series_move(ms, key, bp)
        if not m:
            continue
        if bp:
            s = f"{nm} {m['last']:.2f}% ({m['d1']:+.0f}bp)"
        elif key == "VIX":
            s = f"{nm} {m['last']:.1f} ({m['d1']*100:+.1f}%)"
        else:
            s = f"{nm} {m['last']:,.2f} ({m['d1']*100:+.1f}%)"
        s += f" · {m['date'][5:]}"
        big = m["z"] is not None and abs(m["z"]) >= 1.5
        glob.append({"t": s, "z": round(m["z"], 1) if m["z"] is not None else None, "big": big})
        if big:
            changed.append(f"{nm} 하루 변화가 60일 평균 변동의 {abs(m['z']):.1f}배 ({'상승' if m['d1'] > 0 else '하락'})")
        if key == "US10Y":
            u2 = ((bonds.get("us") or {}).get("chg") or {}).get("2Y") or {}
            if u2.get("v") is not None:
                glob.append({"t": f"미 2년 {u2['v']:.2f}% ({(u2.get('d1') or 0):+.0f}bp) · {str(u2.get('date', ''))[5:]}", "z": None, "big": False})
            sp = (bonds.get("spreads") or {}).get("us_10_2") or {}
            if sp.get("v") is not None:
                glob.append({"t": f"미 10Y−2Y {sp['v']*100:+.0f}bp (1주 {(sp.get('w1') or 0):+.0f}bp)", "z": None, "big": False})
    jp = _j("japan.json", {}) or {}
    if (jp.get("carry") or {}).get("flag"):
        changed.append("엔 캐리 청산 경계 규칙 발동 (엔/달러 5일 −3% 이하)")
    m = _series_move(ms, "USDKRW")
    if m:
        dom.append(f"원/달러 {m['last']:,.1f} ({m['d1']*100:+.2f}%) · {m['date'][5:]}")
        if m["z"] is not None and abs(m["z"]) >= 1.5:
            changed.append(f"원/달러 하루 변화가 60일 평균 변동의 {abs(m['z']):.1f}배")
    kr = (bonds.get("kr") or {}).get("chg") or {}
    for t in ("3Y", "10Y"):
        x = kr.get(t) or {}
        if x.get("v") is not None:
            dom.append(f"국고 {t.replace('Y', '년')} {x['v']:.3f}% (하루 {(x.get('d1') or 0):+.1f}bp · 1주 {(x.get('w1') or 0):+.1f}bp) · {str(x.get('date', ''))[5:]}")
    kus = (bonds.get("spreads") or {}).get("krus_10") or {}
    if kus.get("v") is not None:
        dom.append(f"한·미 10년 금리차 {kus['v']*100:+.0f}bp (1개월 {(kus.get('m1') or 0):+.0f}bp)")
    _acl = _ai_credit_line()
    if _acl:
        dom.append(_acl)
    # 지표 발표: 전월 대비만 (결재 #9 — 컨센서스를 수집하지 않으므로 '서프라이즈·예상 대비' 표기 금지, 문장은 calendar_ev.release_line 한 곳에서)
    today = _kst_today()
    rel = []
    for sid, x in ((_j("macro_releases.json", {}) or {}).get("series") or {}).items():
        try:
            if (today - date.fromisoformat(str(x.get("seen"))[:10])).days > 7:
                continue
        except Exception:  # noqa: BLE001
            continue
        rel.append(release_line(x, period=True, seen=True))
    gap = _kr_us_gap(mv)
    cal = (_j("calendar.json", {}) or {}).get("events", [])
    up = []
    for e in cal:
        try:
            d = date.fromisoformat(e["date"])
        except Exception:  # noqa: BLE001
            continue
        if ((e.get("type") == "매크로" and e.get("imp", 1) >= 2) or e.get("type") == "만기") and today <= d <= today + timedelta(days=7):   # 만기 D-7 포함(req-dev-d624b9cc)
            tm = _ev_time(e)
            up.append(f"{_ev_kst_date(e)[5:]}{' ' + tm if tm else ''} {e['name']}" + (" ★" if e.get("imp", 1) >= 3 else ""))
    if prev and rg.get("label"):
        pr = ((prev.get("macro") or {}).get("regime") or {}).get("label")
        if pr and pr != rg["label"]:
            changed.insert(0, f"레짐 전환 {pr}→{rg['label']}")
    return {"regime": rg, "global": glob, "domestic": dom, "releases": rel, "upcoming": up[:6],
            "changed": changed or ["밤사이 큰 변화 없음 (모든 지표 하루 변화가 60일 평균 변동의 1.5배 미만)"],
            "summary": (mv or {}).get("summary"), "gap": gap,
            "note": "지표는 전월(직전 발표치) 대비 변화만 표시 (시장 예상 자료 없음 · 개정 전 잠정치). "
                    + (f"{gap} · " if gap else "") + "★ = 핵심 이벤트"}


def _kr_us_gap(mv: dict | None) -> str | None:
    """코스피−S&P500 20일 격차 한 줄 (결재 #9: 매크로 지표 문장에 병기). macro_view rows 의 chg20 사용."""
    st_ = {r.get("key"): r for r in ((mv or {}).get("rows") or []) if isinstance(r, dict)}
    kr, us = (st_.get("KOSPI") or {}).get("chg20"), (st_.get("SPX") or {}).get("chg20")
    if kr is None or us is None:
        return None
    g = kr - us
    tag = " — 한국 고유 요인(반도체 쏠림·외국인) 쪽" if g < -0.08 else (" — 한국이 강함" if g > 0.08 else "")
    return f"코스피−S&P500 20일 격차 {g*100:+.1f}%p (코스피 {kr*100:+.1f}% / S&P500 {us*100:+.1f}%){tag}"


def _v2_flows_snapshot() -> dict:
    """대시보드 스냅샷(장중 잠정·마감 확정)에서 코스피 현물 수급·프로그램·등락 종목."""
    s = _j("dashboard_state.json", {}) or {}
    a, b = s.get("intraday_snapshot") or {}, s.get("close_snapshot") or {}
    t = str(_kst_today())
    cur = a if str(a.get("at", "")).startswith(t) and str(a.get("at", "")) >= str(b.get("at", "")) else b
    if not cur.get("at"):
        return {}
    v = cur.get("value") or {}
    out = {"at": str(cur["at"]), "kind": "장중 잠정" if cur is a else "마감 확정"}
    out["flows"] = (v.get("flows") or {}).get("KOSPI") or {}
    out["snap"] = (v.get("snap") or {}).get("KOSPI") or {}
    if cur is a and b.get("at") and not str(b["at"]).startswith(t):
        out["prev_flows"] = ((b.get("value") or {}).get("flows") or {}).get("KOSPI") or {}
        out["prev_at"] = str(b["at"])
    return out


def _v2_positioning(der: dict, k: dict, peers: list[dict]) -> dict:
    L, worry = [], []
    fs = _v2_flows_snapshot()
    if fs.get("flows"):
        f = fs["flows"]
        L.append(f"현물 수급(코스피, {fs['at'][5:16]} {fs['kind']}): " + " · ".join(f"{w} {f[w]:+,.0f}억" for w in ("외국인", "기관", "개인") if f.get(w) is not None))
        if fs.get("prev_flows", {}).get("외국인") is not None:
            L.append(f"전일 외국인 {fs['prev_flows']['외국인']/1e4:+.2f}조 ({fs['prev_at'][5:10]} 확정)")
        if (f.get("외국인") or 0) < 0:
            worry.append("외국인 현물 순매도 지속")
    sn = fs.get("snap") or {}
    if sn.get("prog_total") is not None:
        L.append(f"프로그램 {sn['prog_total']:+,.0f}억 (차익 {sn.get('prog_arb', 0):+,.0f} · 비차익 {sn.get('prog_nonarb', 0):+,.0f})")
    if sn.get("up") is not None and sn.get("down") is not None and (sn["up"] + sn["down"]):
        L.append(f"상승 {sn['up']:.0f} · 하락 {sn['down']:.0f} 종목 (상승 비율 {sn['up']/(sn['up']+sn['down'])*100:.0f}%)")
    fut = (der or {}).get("fut") or {}
    if fut.get("basis") is not None:
        L.append(f"선물 {fut.get('name', '')} 베이시스 {fut['basis']:+.2f} · 미결제 {fut.get('oi', 0):,.0f}계약")
    im = None
    if der and der.get("atm_iv") and der.get("spot"):
        mv1 = der["atm_iv"] / 252 ** 0.5
        im = {"pct": mv1, "k200": der["spot"] * mv1, "kospi": (k.get("last") or 0) * mv1 if k.get("last") else None}
        L.append(f"옵션 내재 하루 예상 변동폭 ±{mv1*100:.1f}% (ATM IV {der['atm_iv']*100:.0f}% ÷ √252) = 코스피200 ±{im['k200']:.1f}pt"
                 + (f" · 코스피 ±{im['kospi']:,.0f}pt" if im["kospi"] else ""))
        if der.get("rv20"):
            prem = der["atm_iv"] / der["rv20"] - 1
            L.append(f"내재 vs 실현(20일 {der['rv20']*100:.0f}%) {prem*100:+.0f}% — " + ("옵션이 실현보다 비쌈: 보험 수요 우위" if prem > 0.1 else "옵션이 실현보다 쌈: 헤지 비용 유리" if prem < -0.1 else "대체로 실현 수준"))
        worry.append(f"하루 ±{mv1*100:.1f}% 변동")
    if der and der.get("pcr_oi") is not None:
        L.append(f"풋/콜 미결제 {der['pcr_oi']:.2f} · 거래량 {der.get('pcr_vol') or 0:.2f}" + (f" · 감마 {der['gex_bn']:+,.0f}억/1%" if der.get("gex_bn") is not None else "")
                 + (f" · 감마 전환점 {der['flip']:.1f}" if der.get("flip") else "") + " (방향 신호로는 검증 전)")
        if der["pcr_oi"] >= 1.2:
            worry.append(f"풋 우위(PCR {der['pcr_oi']:.2f})")
        if (der.get("gex_bn") or 0) < 0:
            worry.append("음수 감마(딜러 헤지가 변동 증폭)")
    shorts = []
    try:
        from .shorts import by_code
        sh = by_code()
        mc = {r["s"]: r for r in peers if (r.get("mc") or 0) >= 1e12}
        rows = sorted([(c, v) for c, v in sh.items() if c in mc and v.get("ratio") is not None], key=lambda x: -x[1]["ratio"])[:5]
        shorts = [{"s": c, "n": mc[c]["n"], "g": mc[c].get("g"), "ratio": v["ratio"], "chg20": v.get("chg20"), "asof": v.get("asof")} for c, v in rows]
    except Exception as e:  # noqa: BLE001
        log.info("공매도 상위 실패: %s", e)
    line = ("시장이 가격에 넣은 걱정: " + " · ".join(worry)) if worry else None
    return {"lines": L, "implied": im, "shorts": shorts, "worry": line,
            "note": "선물 외국인 순매수는 수집하지 않음. 공매도 잔고 = 시총 1조 이상 상위, KRX 공시 지연(T+2)."}


def _v2_sectors(sectors: list[dict], themes_all: list[dict], chains: dict) -> dict:
    th = [t for t in themes_all if t.get("r5") is not None]
    lead = sorted(th, key=lambda t: -t["r5"])[:3]
    lag = sorted(th, key=lambda t: t["r5"])[:3]
    div = []
    for t in th:
        if (t.get("drv") or 0) >= 0.25 and (t.get("r20") or 0) <= -0.10:
            div.append({"theme": t["theme"], "kind": "드라이버 양호인데 과매도", "drv": t["drv"], "r20": t["r20"]})
        elif (t.get("drv") or 0) <= -0.05 and (t.get("r20") or 0) >= 0.05:
            div.append({"theme": t["theme"], "kind": "드라이버 없는 상승", "drv": t["drv"], "r20": t["r20"]})

    def why(name: str) -> str:
        c = next((v for v in (chains or {}).values() if v.get("name") == name), {})
        px = sorted([p for p in c.get("proxies", []) if p.get("effect") is not None], key=lambda p: -abs(p["effect"]))[:2]
        return " / ".join(f"{p.get('name')} {p['effect']:+.2f}: {str(p.get('why') or '')[:40]}" for p in px)
    ow = [{"chain": r["chain"], "score": r["score"], "why": why(r["chain"])} for r in sectors if r.get("stance") == "비중 확대"][:3]
    uw = [{"chain": r["chain"], "score": r["score"], "why": why(r["chain"])} for r in sorted(sectors, key=lambda r: r["score"]) if r.get("stance") == "비중 축소"][:3]
    return {"lead": lead, "lag": lag, "divergence": sorted(div, key=lambda d: -abs(d["drv"]))[:5], "overweight": ow, "underweight": uw,
            "note": "주도/소외 = 테마 시총가중 5일 수익률. 비중 의견 = 공급망 체인 점수(검증 전) — 이유는 체인 내 영향 큰 프록시 2개."}


def _v2_research(today: date) -> dict:
    r = _j("research.json", {}) or {}
    items = r.get("items") or []
    close = r.get("close") or {}
    ds = sorted({i["date"] for i in items if i.get("date") and i["date"] <= str(today)}, reverse=True)[:2]
    out, up, dn = [], 0, 0
    for i in items:
        if i.get("date") not in ds:
            continue
        prev = [p for p in items if p.get("code") == i.get("code") and p.get("date", "") < i["date"] and p.get("target")]
        same = [p for p in prev if p.get("broker") == i.get("broker")]
        pv = (sorted(same, key=lambda p: p["date"]) or sorted(prev, key=lambda p: p["date"]) or [None])[-1]
        chg = i.get("tp_chg")
        if chg is None and pv and i.get("target") and pv.get("target") and pv.get("broker") == i.get("broker"):
            chg = i["target"] / pv["target"] - 1
        cl = close.get(i.get("code") or "")
        if chg is not None and chg > 0.001:
            up += 1
        elif chg is not None and chg < -0.001:
            dn += 1
        out.append({"date": i["date"], "s": i.get("code"), "n": i.get("name"), "broker": i.get("broker"), "opinion": i.get("opinion"),
                    "target": i.get("target"), "tp_chg": chg, "upside": (i["target"] / cl - 1) if i.get("target") and cl else None,
                    "prev": ({"date": pv["date"], "broker": pv.get("broker"), "target": pv.get("target")} if pv else None),
                    "title": i.get("thesis") or i.get("title"), "tone": i.get("tone"), "link": i.get("link")})
    out.sort(key=lambda x: (abs(x["tp_chg"] or 0) <= 0.001, x["date"] != ds[0], -abs(x["tp_chg"] or 0), -(x["upside"] or -9)))
    return {"dates": ds, "n": len(out), "up": up, "down": dn, "items": out[:10],
            "note": "목표가 변화 = 같은 증권사 직전 리포트 대비 (없으면 표시 안 함). 상승여력 = 목표가 ÷ 수집 시점 종가."}


def _v2_bottom_up(o: dict, peers: list[dict], cal: list[dict], today: date) -> dict:
    mc = {r["s"]: r.get("mc") or 0 for r in peers}
    dis = (_j("disclosures.json", {}) or {}).get("items") or []
    pri = ("수주·계약", "자사주", "유상증자", "CB·BW·EB", "합병·분할", "최대주주", "실적", "배당")
    dd = sorted({x["date"] for x in dis if x.get("date") and x["date"] <= str(today)}, reverse=True)[:2]
    dl = [x for x in dis if x.get("date") in dd and x.get("category") in pri and mc.get(x.get("code"), 0) >= 3e11]
    dl.sort(key=lambda x: (x["date"] != (dd[0] if dd else ""), pri.index(x["category"]), -mc.get(x.get("code"), 0)))
    earn = [e for e in cal if e.get("type") == "실적" and str(today) <= e.get("date", "") <= str(today + timedelta(days=7))]
    earn.sort(key=lambda e: (e["date"], -(e.get("imp") or 1)))
    return {"research": _v2_research(today),
            "disclosures": [{"date": x["date"], "s": x.get("code"), "n": x.get("name"), "cat": x.get("category"), "flag": x.get("flag"),
                             "title": str(x.get("title") or "").strip()[:60], "link": x.get("link"), "mc": mc.get(x.get("code"))} for x in dl[:8]],
            "earnings": [{"date": e["date"], "n": e.get("name"), "ticker": e.get("ticker"), "market": e.get("market"), "imp": e.get("imp", 1),
                          "confirmed": bool(e.get("confirmed")), "note": e.get("note")} for e in earn[:10]],
            "long": [x["n"] for x in (o.get("ideas") or {}).get("long", [])[:5]],
            "avoid": [x["n"] for x in (o.get("ideas") or {}).get("avoid", [])[:5]],
            "squeeze": [x["n"] for x in (o.get("squeeze") or [])[:5]],
            "note": "공시 = 최근 2일, 시총 3천억 이상, 수주·자사주·증자·CB·합병·최대주주·실적·배당만."}


def _lens(views: dict, lid: str) -> dict:
    L = next((x for x in (views or {}).get("lenses", []) if x.get("id") == lid), {})
    return {"id": lid, "name": L.get("name_ko") or lid, "grade": L.get("grade") or "검증전", "status": L.get("status")}


IDEAS_LOG = REPORT_DIR / "ideas_log.json"
IDEAS_ATTRIB = REPORT_DIR / "ideas_attrib.json"
GRADE_W = {"A": 1.0, "B": 0.8, "C": 0.6, "검증전": 0.3, "F": 0.0}
ATTRIB_MIN_N = 10


def _signals_kr() -> dict:
    """reports/signals/<최근>_KR.csv → {code: {class, trend, mom, rev}}."""
    import csv
    fs = sorted((REPORT_DIR / "signals").glob("*_KR.csv"))
    if not fs:
        return {}
    out = {}
    with fs[-1].open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            out[str(r.get("symbol", "")).zfill(6)] = {"class": r.get("class"), "asof": fs[-1].name[:10],
                                                      "trend": r.get("trend_score"), "mom": r.get("momentum_score"), "rev": r.get("reversal_risk")}
    return out


def _attrib_weight(attrib: dict, key: str) -> tuple[float, str]:
    """원천별 실제 성적으로 가중 보정 — n<10 이면 1.0('검증 전'), 이상이면 평균 R 을 표본 크기로 수축해 0.5~1.5배."""
    a = ((attrib or {}).get("sources") or {}).get(key) or {}
    n, r = a.get("n") or 0, a.get("avgR")
    if n < ATTRIB_MIN_N or r is None:
        return 1.0, f"성적 n={n} (검증 전)"
    m = max(0.5, min(1.5, 1 + r * n / (n + 20)))
    return m, f"성적 n={n} 평균 {r:+.2f}R → ×{m:.2f}"


def _v2_sources(o: dict, peers: list[dict], today: date) -> tuple[dict, dict]:
    """후보 종목별 원천(동의/반대) 수집. 반환: ({code: [source…]}, {code: 이름·테마})."""
    views = _j("views.json", {}) or {}
    lab = _j("lab.json", {}) or {}
    lg = lambda lid: _lens(views, lid)["grade"]  # noqa: E731
    S, meta = {}, {r["s"]: {"n": r["n"], "g": r.get("g"), "semi": r.get("g") in SEMI_G} for r in peers}

    def add(code, key, label, side, grade, src):
        if code not in meta:
            return
        cur = S.setdefault(code, [])
        dup = next((x for x in cur if x["k"] == key and x["side"] == side), None)
        if dup:   # 같은 원천은 한 표 — 근거만 덧붙임 (공시 3건이 3표가 되지 않게)
            if label not in dup["label"]:
                dup["label"] += " · " + label
            return
        cur.append({"k": key, "label": label, "side": side, "grade": grade or "검증전", "src": src})
    ex = ((o.get("stance") or {}).get("exec") or {}).get("cands") or []
    for c in ex:
        add(c["s"], "exec_plan", "실행 대본 후보 (손절 20일 저점·2×ATR)", "agree", lg("atr_stop"), "committee._exec_plan")
    for x in (o.get("ideas") or {}).get("long", []):
        add(x["s"], "committee_ideas", f"이익 신호 {x.get('drv') or 0:+.2f} · 20D {(x.get('r20') or 0)*100:+.0f}%", "agree", lg("committee_ideas"), "peers_KR")
    for x in (o.get("ideas") or {}).get("avoid", []):
        add(x["s"], "committee_avoid", f"회피 목록 (이익 신호 {x.get('drv') or 0:+.2f})", "oppose", lg("committee_ideas"), "peers_KR")
    for x in o.get("squeeze") or []:
        add(x["s"], "squeeze", f"숏스퀴즈 후보 (잔고 {x['ratio']:.1f}%)", "agree", "검증전", "shorts")
    sig = _signals_kr()
    sg = lg("stock_trend_score")
    for code in list(meta):
        c = (sig.get(code) or {}).get("class")
        if c in ("TREND_LONG", "PULLBACK_IN_UPTREND"):
            add(code, "signal:trend", f"시그널 {c}", "agree", sg, "signals")
        elif c in ("TREND_SHORT", "TREND_OVEREXTENDED"):
            add(code, "signal:trend", f"시그널 {c}", "oppose", sg, "signals")
    mk = _j("momentum_KR.json", {}) or {}
    mg = ((lab.get("results") or {}).get("TREND_12_1") or {}).get("grade") or "검증전"
    for x in mk.get("top") or []:
        add(str(x.get("symbol")), "momentum:12-1", f"12-1 모멘텀 상위 (점수 {x.get('score')})", "agree", mg, "momentum_KR")
    for x in mk.get("bottom") or []:
        add(str(x.get("symbol")), "momentum:12-1", f"12-1 모멘텀 하위 (점수 {x.get('score')})", "oppose", mg, "momentum_KR")
    for hid, v in (lab.get("results") or {}).items():
        ls = v.get("last_signals") or {}
        for p in ls.get("picks") or []:
            add(str(p.get("s")), f"lab:{hid}", f"전략 연구소 {hid} 신호 {str(ls.get('date', ''))[5:]}", "agree", v.get("grade") or "검증전", "lab")
    rs = (_j("research.json", {}) or {}).get("items") or []
    cut = str(today - timedelta(days=30))
    tp = {}
    for i in rs:
        if i.get("date", "") >= cut and i.get("tp_chg") is not None and abs(i["tp_chg"]) > 0.001:
            tp.setdefault(i.get("code"), []).append(i["tp_chg"])
    for code, a in tp.items():
        u, d = sum(1 for x in a if x > 0), sum(1 for x in a if x < 0)
        if u:
            add(code, "research:tp_up", f"목표가↑ {u}건 (30일)", "agree", "검증전", "research")
        if d:
            add(code, "research:tp_down", f"목표가↓ {d}건 (30일)", "oppose", "검증전", "research")
    dis = (_j("disclosures.json", {}) or {}).get("items") or []
    cut3 = str(today - timedelta(days=3))
    mc = {r["s"]: r.get("mc") or 0 for r in peers}
    for x in dis:
        if x.get("date", "") < cut3 or mc.get(x.get("code"), 0) < 3e11:
            continue
        if x.get("category") in ("수주·계약", "자사주"):
            add(x.get("code"), "disclosure:plus", f"공시 {x['category']} {str(x['date'])[5:]}", "agree", "검증전", "disclosures")
        elif x.get("category") in ("유상증자", "CB·BW·EB"):
            add(x.get("code"), "disclosure:dilution", f"공시 {x['category']} {str(x['date'])[5:]}", "oppose", "검증전", "disclosures")
    return S, meta


def _v2_ideas_top(o: dict, cal: list[dict], bu: dict, today: date, peers: list[dict] | None = None) -> dict:
    """여러 원천(실행 대본·이익 신호·시그널·모멘텀·연구소·리서치·공시·숏스퀴즈)이 겹치는 종목을 고른다.
    원천 가중 = 검증 등급(A 1·B .8·C .6·검증 전 .3·F 0) × 실제 성적 보정(ideas_attrib, n≥10). 숫자(진입·손절·목표)는 리스크 박스 규칙."""
    peers = peers or (_j("peers_KR.json", {}) or {}).get("rows", [])
    attrib = _j("ideas_attrib.json", {}) or {}
    S, meta = _v2_sources(o, peers, today)
    views = _j("views.json", {}) or {}
    gate = (((o.get("stance") or {}).get("views") or {}).get("entry") or {}).get("gate")
    from .idea_tracking import v2_on, v2_score, entry_floor, pick_top3, VALID
    v2 = v2_on()   # 스위치 screener/config.CIO_TOP3_V2 (기본 OFF — OFF 면 아래 결과는 10/21 이전과 같다)
    rows = []
    for code, ss in S.items():
        agree = [s for s in ss if s["side"] == "agree"]
        if not agree or meta.get(code, {}).get("semi"):
            continue   # 반도체는 테마 한도 때문에 실행 대본과 같이 제외
        sc = 0.0
        for s in ss:
            m, note = _attrib_weight(attrib, s["k"])
            s["w"] = round(GRADE_W.get(s["grade"], 0.3) * m * (1 if s["side"] == "agree" else -1), 3)
            s["perf"] = note
            sc += s["w"]
        if v2:
            sc = v2_score([(s["k"], s["w"]) for s in ss])
        if sc <= 0:
            continue
        rows.append((sc, code, ss))
    if v2:   # D4 동점 정렬: 점수 → 촉매 있음 우선 → 코드
        def _has_cat(code, ss):
            return any(s["k"] in ("research:tp_up", "disclosure:plus") for s in ss) or any(
                e.get("type") == "실적" and str(e.get("ticker")) == code and str(today) <= e.get("date", "") <= str(today + timedelta(days=14))
                for e in cal)
        rows.sort(key=lambda x: (-x[0], not _has_cat(x[1], x[2]), x[1]))
    else:
        rows.sort(key=lambda x: -x[0])
    out, cands = [], []
    allr = []
    for sc, code, ss in rows:
        if len(allr) >= 10:
            break
        rb = _risk_box(code)
        if not rb or rb["skip"]:
            continue
        strong = any(s["side"] == "agree" and GRADE_W.get(s["grade"], 0) >= 0.6 for s in ss)
        conv = "높음" if sc >= 1.2 else "중간" if sc >= 0.6 else "낮음"
        if conv == "높음" and not strong:
            conv = "중간"   # C 이상 원천의 동의 없으면 상한 '중간'
        cm = {"높음": 1.0, "중간": 0.7, "낮음": 0.4}[conv]
        payoff = (rb["target"] - rb["close"]) / (rb["close"] - rb["stop"])
        size = min(cm * (payoff / 2) * 0.01 / rb["stop_pct"], 0.15)
        cat = [{"date": e["date"], "what": "실적 발표" + (" (회사 확정)" if e.get("confirmed") else " (예정일 추정)")}
               for e in cal if e.get("type") == "실적" and str(e.get("ticker")) == code and str(today) <= e.get("date", "") <= str(today + timedelta(days=14))]
        cat += [{"date": str(today), "what": s["label"]} for s in ss if s["k"] in ("research:tp_up", "disclosure:plus")]
        status = ("대기 — 촉매 없음" if not cat else "대기 — 확신 낮음" if conv == "낮음"
                  else "대기 — 판정 방어" if (o.get("stance") or {}).get("stance") == "방어"
                  else "대기 — 진입 게이트 불통과" if gate == "fail" else "실행 후보")
        row = {"s": code, "n": meta[code]["n"], "g": meta[code].get("g"), "side": "롱", "conv": conv, "score": round(sc, 2), "size": size,
               "entry": rb["close"], "entry_max": rb["close"] * (1 + 0.5 * rb["atr_pct"]), "stop": rb["stop"], "stop_pct": rb["stop_pct"],
               "target": rb["target"], "payoff": payoff, "atr_pct": rb["atr_pct"], "catalyst": cat[:3], "status": status,
               "kill": [f"종가 {rb['stop']:,.0f} 하회 (손절, 협상 대상 아님)", "동의 원천이 반대로 바뀜 (예: 이익 신호 0 이하·회피 목록 편입)",
                        "20거래일 안 +1R 미도달 (시간 손절)"],
               "sources": [{k: s[k] for k in ("k", "label", "side", "grade", "w", "perf")} for s in ss],
               "lens": [_lens(views, "atr_stop")]}
        if v2:
            row["entry"] = entry_floor(rb["close"], rb["stop"], rb["atr_pct"])   # P3/D5
            row["valid"] = dict(VALID)
            if not cat:
                row["catalyst_note"] = "없음"
        allr.append(row)
    exec_zero = None
    if v2:
        out, cands, exec_zero = pick_top3(allr, "KR")
    else:
        out, cands = allr[:3], allr[3:]
    extra = {"rule": "v2", "exec_zero": exec_zero} if v2 else {}
    return {**extra, "items": out, "candidates": cands, "entry_gate": gate,
            "formula": "확신 점수 = Σ 동의 원천 가중 − Σ 반대 원천 가중 (가중 = 검증 등급 A1·B.8·C.6·검증전.3·F0 × 원천 실제 성적 보정). "
                       "높음 ≥1.2·중간 ≥0.6·낮음 >0, C 이상 원천 동의 없으면 상한 중간. 사이즈(모델 북 %) = 확신도(1·.7·.4) × 손익비/2 × 1% ÷ 손절폭, 상한 15%. "
                       "진입·손절·목표 = 리스크 박스 규칙(손절 max(20일 저점, 종가−2×ATR14), 목표 2R).",
            "empty": None if out else "숫자 근거 있는 아이디어 없음 (동의 원천 > 반대이고 손절폭 15% 이하인 비반도체 후보 없음) — 대기"}


def _ideas_log_score() -> dict:
    """ideas_log.json 의 지난 아이디어를 실제 일봉으로 채점 → 원천별 성적 ideas_attrib.json. 반환: attrib."""
    import polars as pl
    log_ = json.loads(IDEAS_LOG.read_text(encoding="utf-8")) if IDEAS_LOG.exists() else {"rows": []}
    p = DATA_DIR / "kr_prices.parquet"
    if not log_["rows"] or not p.exists():
        return _j("ideas_attrib.json", {}) or {}
    codes = list({r["ticker"] for r in log_["rows"]})
    since = min(r["date"] for r in log_["rows"])
    from .prices import load_kr   # 공통 로더 = 기업행위 조정 (px-adjust-unify)
    px = (load_kr(path=p).with_columns(pl.col("yf").str.slice(0, 6).alias("code"), pl.col("date").cast(pl.Utf8))
            .filter(pl.col("code").is_in(codes) & (pl.col("date") > since)).sort("date"))
    by = {c: g.select("date", "high", "low", "close").rows() for (c,), g in px.group_by("code")}
    for r in log_["rows"]:
        if (r.get("score") or {}).get("final"):
            continue
        bars = [b for b in by.get(r["ticker"], []) if b[0] > r["date"]][:20]
        R = r["entry"] - r["stop"]
        if not bars or R <= 0:
            continue
        sc = {"days": len(bars), "hit1R": False, "stopped": False}
        for i, (d, h, lo, c) in enumerate(bars):
            if lo is not None and lo <= r["stop"]:
                sc["stopped"], sc["exitR"], sc["exit_date"] = True, -1.0, d
                break
            if h is not None and h >= r["entry"] + R and not sc["hit1R"]:
                sc["hit1R"], sc["hit_date"] = True, d
        if len(bars) >= 5:
            sc["ret5"] = bars[4][3] / r["entry"] - 1
        if len(bars) >= 20:
            sc["ret20"] = bars[19][3] / r["entry"] - 1
        sc["R"] = sc.get("exitR", (bars[-1][3] - r["entry"]) / R)
        sc["final"] = sc["stopped"] or len(bars) >= 20
        r["score"] = sc
    IDEAS_LOG.write_text(json.dumps(log_, ensure_ascii=False), encoding="utf-8")
    agg = {}
    for r in log_["rows"]:
        sc = r.get("score") or {}
        if sc.get("days", 0) < 5:   # 5거래일 지나야 채점
            continue
        for k in {s["k"] for s in r.get("sources", []) if s.get("side") == "agree"}:
            agg.setdefault(k, []).append(sc)
    src = {}
    for k, a in agg.items():
        n = len(a)
        src[k] = {"n": n, "hit1R": round(sum(1 for x in a if x.get("hit1R")) / n, 2), "stop": round(sum(1 for x in a if x.get("stopped")) / n, 2),
                  "avgR": round(st.mean(x["R"] for x in a), 2), "ret5": round(st.mean(x["ret5"] for x in a if "ret5" in x), 4) if any("ret5" in x for x in a) else None,
                  "ret20": round(st.mean(x["ret20"] for x in a if "ret20" in x), 4) if any("ret20" in x for x in a) else None,
                  "status": "검증 전" if n < ATTRIB_MIN_N else "반영"}
    at = {"asof": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "min_n": ATTRIB_MIN_N, "n_ideas": len(log_["rows"]), "sources": src,
          "note": "아이디어 기록 후 5거래일 지난 것만 채점. 1R 도달·손절은 일중 고가·저가(같은 날 둘 다면 손절로), R = 손절 시 −1, 아니면 마지막 종가 기준. "
                  "원천 = 그 아이디어에 '동의'한 원천. n<10 은 확신도 가중에 반영 안 함."}
    IDEAS_ATTRIB.write_text(json.dumps(at, ensure_ascii=False), encoding="utf-8")
    return at


def _ideas_log_append(o: dict) -> None:
    """이번 회의의 ideas_top(+후보) 기록. 같은 날 같은 종목은 첫 기록만 (세션 반복으로 표본이 부풀지 않게)."""
    log_ = json.loads(IDEAS_LOG.read_text(encoding="utf-8")) if IDEAS_LOG.exists() else {"rows": []}
    have = {(r["date"], r["ticker"]) for r in log_["rows"]}
    it = o.get("ideas_top") or {}
    for rank, a in (("top", it.get("items") or []), ("cand", it.get("candidates") or [])):
        for x in a:
            if (o["date"], x["s"]) in have:
                continue
            log_["rows"].append({"date": o["date"], "session": o.get("session"), "asof": o.get("asof"), "ticker": x["s"], "name": x["n"],
                                 "side": x["side"], "entry": x["entry"], "stop": x["stop"], "target": x["target"], "conviction": x["conv"],
                                 "score_in": x.get("score"), "rank": rank,
                                 "sources": [{"k": s["k"], "side": s["side"], "grade": s["grade"]} for s in x.get("sources", [])]})
    cut = str(_kst_today() - timedelta(days=400))
    log_["rows"] = [r for r in log_["rows"] if r["date"] >= cut]
    IDEAS_LOG.write_text(json.dumps(log_, ensure_ascii=False), encoding="utf-8")


def _v2_hedges(der: dict, k: dict, scen: list[dict], sb_probs: dict) -> dict:
    H, asym = [], None
    bear = next((s for s in scen if s["name"].startswith("약세")), {})
    bull = next((s for s in scen if s["name"].startswith("강세")), {})
    if der and der.get("spot") and der.get("atm_iv") and der.get("dte"):
        try:
            from .derivs import _bs
            S, T = der["spot"], der["dte"] / 365
            K = round(S * 0.95 / 2.5) * 2.5
            v = der.get("iv_p95") or der["atm_iv"]
            prem = _bs(S, K, T, v, "P")
            pay15 = max(K - S * 0.85, 0) - prem
            H.append({"name": f"코스피200 풋 {K:.1f} ({(K/S-1)*100:+.0f}% OTM, {str(der.get('expiry', ''))[5:]} 만기)",
                      "cost": prem / S, "cost_book": 0.25 * prem / S,
                      "line": f"이론가 ≈ {prem:.1f}pt (기초 대비 {prem/S*100:.1f}%, IV {v*100:.0f}% · 블랙숄즈) — 북 25% 명목 헤지 비용 {0.25*prem/S*100:.2f}%p. 코스피200 −15%면 북 기준 +{0.25*pay15/S*100:.1f}%p",
                      "when": f"약세 시나리오 {(bear.get('prob') or 0)*100:.0f}% 대비 · 만기 D-{der['dte']}"})
            if prem > 0:
                asym = {"name": H[-1]["name"], "loss": prem / S, "gain": pay15 / S, "ratio": pay15 / prem,
                        "p": sb_probs.get("deep_bear"),
                        "line": f"최대 손실 = 프리미엄 {prem/S*100:.1f}% · 코스피200 −15% 시 이익 {pay15/S*100:.1f}% (손익비 {pay15/prem:.1f}배)"
                                + (f" · 1999~ 비슷한 상황 20일 −15% 미만 빈도 {sb_probs['deep_bear']*100:.1f}%" if sb_probs.get("deep_bear") is not None else ""),
                        "cond": "변동성 상승 국면 진입 전이 유리 — 내재변동성이 이미 높으면 비용 큼 (모델 북 전용)"}
        except Exception as e:  # noqa: BLE001
            log.info("헤지 이론가 실패: %s", e)
    H.append({"name": "인버스 1배 ETF 25% (모델 북 전용 — 실계좌 적용 불가)", "cost": None, "cost_book": None,
              "line": "시간가치 비용 없음, 대신 강세 시나리오(20일 +5% 초과)면 북 기준 −1.25%p 이상 기회비용"
                      + (f" · 강세 확률 {(bull.get('prob') or 0)*100:.0f}%" if bull.get("prob") is not None else ""),
              "when": "레버리지·인버스는 모델 북 아이디어에서만 언급 — 실계좌 상품 금지 게이트(비공개)"})
    if k.get("low20"):
        H.append({"name": "현금 비중 (신규 진입 중단)", "cost": None, "cost_book": None,
                  "line": f"코스피 20일 저점 {k['low20']:,.0f} 종가 이탈 시 신규 진입 중단 — 비용은 반등 놓침뿐", "when": "약세 경로 경보"})
    return {"hedges": H, "asymmetry": asym, "worst": bear.get("name"), "worst_p": bear.get("prob")}


def _v2_premortem(stance: dict, scen: list[dict], k: dict, stu: dict) -> dict:
    s = (stance or {}).get("stance")
    bull = next((x for x in scen if x["name"].startswith("강세")), {})
    bear = next((x for x in scen if x["name"].startswith("약세")), {})
    dp = ((stu.get("conditional") or {}).get("deep_(20일 −15% 이상 하락 중)") or {}).get("d1") or {}
    if s in ("관망", None):
        return {"wrong": "관망이 틀린 경우: V자 반등 — 신호 확인 전에 반등 대부분이 지나감",
                "p": bull.get("prob"),
                "tell": f"코스피 20일선 {k.get('sma20') or 0:,.0f} 2일 연속 회복 (또는 하루 −5% 급락 → 그날 종가가 1차 신호)",
                "cost": (f"1999~ 비슷한 날 다음날 평균 {dp.get('avg', 0)*100:+.1f}% (상승 {dp.get('up', 0)*100:.0f}%)" if dp else None),
                "action": "추격 매수 금지 — 1차 비중만 집행, 손절선은 20일 저점·2×ATR 그대로. 2차 진입은 검증 대기"}
    if s == "분할 매수":
        return {"wrong": "분할 매수가 틀린 경우: 반등 실패 후 연속 급락", "p": bear.get("prob"),
                "tell": f"코스피 20일 저점 {k.get('low20') or 0:,.0f} 종가 이탈",
                "cost": None, "action": "신규 진입 중단, 종목별 손절선 기계적 집행 — 지수 기준 일괄 청산은 하지 않음(백테스트 열위)"}
    return {"wrong": "방어가 틀린 경우: 저점 이탈이 속임수(베어 트랩)", "p": bull.get("prob"),
            "tell": f"이탈 후 3거래일 안 20일 저점 {k.get('low20') or 0:,.0f} 재회복",
            "cost": None, "action": "헤지(인버스·풋) 절반 해제, 신규 진입은 1차 비중부터"}


def _v2_track(o: dict) -> dict:
    tr = (o.get("track") or {}).get("summary") or {}
    pb = ((o.get("scorecard") or {}).get("PB")) or {}
    L = []
    for n, lab in (("h5", "5거래일"), ("h20", "20거래일")):
        x = tr.get(n)
        if x:
            L.append(f"매수 후보 {lab} 시장 중앙값 대비 {x['long_avg']*100:+.1f}% · 적중 {x['long_hit']*100:.0f}% (n={x['n']})"
                     + (f" · 회피 목록 {x['avoid_avg']*100:+.1f}%" if x.get("avoid_avg") is not None else ""))
    if tr.get("brier"):
        L.append(f"시나리오 브라이어 {tr['brier']['avg']} (무작위 {tr['brier']['naive']}, 낮을수록 좋음, n={tr['brier']['n']})")
    if pb.get("n") and pb.get("hit") is not None:
        L.append(f"PB 모델 북 판정 {pb['n']}건 · 적중 {('%.0f%%' % (pb['hit']*100)) if pb.get('hit') is not None else '—'} · 손익비 {pb['payoff'] if pb.get('payoff') is not None else '—'}")
    at = _j("ideas_attrib.json", {}) or {}
    bys = sorted([{"k": k, **v} for k, v in (at.get("sources") or {}).items()], key=lambda x: -x["n"])
    return {"lines": L or ["기록 시작 — 5거래일 뒤부터 채점"], "by_source": bys, "ideas_n": at.get("n_ideas"),
            "by_source_note": at.get("note") or "아이디어 원천별 성적 — 첫 기록 후 5거래일 뒤부터 채점"}


def _v2_clock(o: dict, k: dict, der: dict, cal: list[dict], today: date, im: dict | None) -> list[dict]:
    from .us_committee import high_event
    it = o.get("ideas_top") or {}
    watch = {str(x.get("s")) for x in (it.get("items") or []) + (it.get("candidates") or [])}
    C = []
    for e in cal:
        if _ev_kst_date(e) == str(today) and e.get("type") not in ("시장 이벤트",):   # 한국 날짜 기준(req-dev-d624b9cc)
            C.append({"t": _ev_time(e) or "시각 미정", "what": e["name"] + (" ★" if e.get("imp", 1) >= 3 else ""), "kind": "이벤트",
                      "hi": high_event(e, watch)})
    tm = today + timedelta(days=1)
    for e in cal:   # 내일 새벽(한국 00:00~08:59) 미국 이벤트도 오늘 밤 시계에 포함
        t = _ev_time(e)
        if _ev_kst_date(e) == str(tm) and t and t < "09:00":
            C.append({"t": "내일 " + t, "what": e["name"], "kind": "이벤트", "hi": high_event(e, watch)})
    C.sort(key=lambda x: x["t"])
    last = k.get("last")
    for lab, v in (("오늘 저점", k.get("low_today")), ("20일 저점(약세 경보선)", k.get("low20")), ("5일 고점(강세 전환선)", k.get("hi5"))):
        if v:
            C.append({"t": "가격선", "what": f"코스피 {lab} {v:,.0f}" + (f" (현재 대비 {(v/last-1)*100:+.1f}%)" if last else ""), "kind": "가격",
                      "dist": (v / last - 1) if last else None})
    if der and der.get("flip"):
        C.append({"t": "가격선", "what": f"코스피200 감마 전환점 {der['flip']:.1f} (현물 {der.get('spot', 0):.1f}, 검증 전)", "kind": "가격"})
    if im and im.get("kospi") and last:
        C.append({"t": "범위", "what": f"내재 하루 범위 코스피 {last-im['kospi']:,.0f}~{last+im['kospi']:,.0f} (±{im['pct']*100:.1f}%)", "kind": "가격"})
    return C


def _v2_bottom_line(o: dict, k: dict, prev: dict | None, delta: str | None, clock: list[dict], ideas: dict, macro: dict, session: str) -> dict:
    st_ = (o.get("stance") or {}).get("stance")
    ps = ((prev or {}).get("stance") or {}).get("stance")
    flip = bool(ps and st_ and ps != st_)
    prev_ids = {x.get("s") for x in ((prev or {}).get("ideas_top") or {}).get("items", []) if str(x.get("status", "")).startswith("실행")}
    new_go = [x for x in ideas.get("items", []) if x["status"].startswith("실행") and x["s"] not in prev_ids]
    im = (o.get("positioning") or {}).get("implied") or {}
    band = (im.get("pct") or 0.01)
    from .us_committee import LIGHT_RULE, light_yellow
    near, hi_ev = light_yellow(clock, band)   # 10/20 보정: 범위 절반 이내·고중요 이벤트만 🟡 (일반 지표는 시계에만)
    ev_today = [c for c in clock if c["kind"] == "이벤트"]
    gate_fail = (ideas.get("entry_gate") == "fail")
    reg_flip = any(str(x).startswith("레짐 전환") for x in macro.get("changed", []))
    if flip or reg_flip or (new_go and not gate_fail and _live_buy(st_)):   # B1: 후보 기준 🔴 은 위성 해금 + 매수 쪽 판정일 때만
        light = "red"
    elif hi_ev or near:
        light = "yellow"
    else:
        light = "green"
    l1 = delta or "직전 회의 기록 없음 — 오늘부터 비교"
    evs = [f"{c['t']} {c['what']}" for c in ev_today[:2]]
    pls = [c["what"] for c in clock if c["t"] == "가격선"][:3]
    l2 = "오늘의 시계: " + (" · ".join(evs) + " / " if evs else "시각 정해진 이벤트 없음 / ") + " · ".join(pls)
    if light == "red":
        why = ("판정 " + f"{ps}→{st_}") if flip else ("레짐 전환" if reg_flip else "신규 실행 후보 " + ", ".join(x["n"] for x in new_go[:2]))
        l3 = f"할 일: {why} — 섹션 5 아이디어의 진입·손절·촉매 확인 후 집행. 하지 말 일: 손절선 없는 진입·추격 매수"
    elif light == "yellow":
        l3 = ("할 일: 판정 유지 · 신규 행동 없음 — " + ("가격선 근접: " + near[0] if near else f"고중요 이벤트({hi_ev[0]['what']}) 결과 확인 후 재판정")
              + ". 하지 말 일: 이벤트 결과 전 레버리지·방향 베팅 확대")
    else:
        l3 = "판정 유지 · 할 일 없음. 하지 말 일: 변화 없는 날의 매매(거래비용만 발생)"
    return {"light": light, "label": LIGHTS[light], "lines": [l1, l2, l3], "clock": clock, "stance": st_, "prev_stance": ps,
            "session": session, "footer": V2_FOOTER, "rule": LIGHT_RULE}


def _v2_build(out: dict, k: dict, der: dict, chains: dict, themes_all: list[dict], peers: list[dict], cal: list[dict],
              stu: dict, sb_probs: dict, delta: str | None, session: str) -> None:
    """모닝 미팅 v2 키를 out 에 추가. 섹션 하나가 실패해도 나머지는 계속."""
    today = _kst_today()
    prev = _prev_meeting(session)
    mv = _j("macro_view.json", {}) or {}
    steps = [("macro", lambda: _v2_macro(mv, prev)),
             ("positioning", lambda: _v2_positioning(der, k, peers)),
             ("rotation", lambda: _v2_sectors(out.get("sectors") or [], themes_all, chains)),
             ("bottom_up", lambda: _v2_bottom_up(out, peers, cal, today)),
             ("ideas_top", lambda: _v2_ideas_top(out, cal, out.get("bottom_up") or {}, today, peers)),
             ("hedges", lambda: _v2_hedges(der, k, out.get("scenarios") or [], sb_probs)),
             ("premortem", lambda: _v2_premortem(out.get("stance") or {}, out.get("scenarios") or [], k, stu))]
    try:   # 지난 아이디어 채점 → 원천별 성적 (확신도 가중에 반영)
        _ideas_log_score()
    except Exception as e:  # noqa: BLE001
        log.info("아이디어 채점 실패: %s", e)
    for key, fn in steps:
        try:
            out[key] = fn()
        except Exception as e:  # noqa: BLE001
            log.warning("운용회의 v2 %s 실패: %s", key, e)
    if isinstance(out.get("hedges"), dict):
        out["asymmetry"] = out["hedges"].get("asymmetry")
    try:
        clock = _v2_clock(out, k, der, cal, today, (out.get("positioning") or {}).get("implied"))
        out["bottom_line"] = _mock_gate(_v2_bottom_line(out, k, prev, delta, clock, out.get("ideas_top") or {}, out.get("macro") or {}, session),
                                        out.get("ideas_top") or {})
    except Exception as e:  # noqa: BLE001
        log.warning("운용회의 v2 bottom_line 실패: %s", e)
    try:   # 매매 계획 표준(trade plan) — TOP3·실행 대본·시그널 카드·헤지·'할 일' 줄 (10/21 겸이 상시 규칙, screener/tradeplan.py)
        from . import tradeplan
        tradeplan.attach(out, "KR", today)
    except Exception as e:  # noqa: BLE001
        out["tradeplan"] = {"error": f"{type(e).__name__}: {e}"}
        log.warning("trade plan 부착 실패: %s", e)
    _top_attach(out, "KR")
    _hf_attach(out, "KR")
    try:
        _ideas_log_append(out)
        from .idea_tracking import run as track_ideas
        out["idea_tracking"] = track_ideas(out)   # 확정판(장 마감 뒤 마지막 판) 캡처 — idea_tracking.capture (D1)
    except Exception as e:  # noqa: BLE001
        out["idea_tracking"] = {"error": f"{type(e).__name__}: {e}"}   # 0건 원인이 결과에 보이게 (D3)
        log.warning("아이디어 기록 실패: %s", e)
    try:   # 신호 종목 forward 성과 누적 (accum·us_accum·sim_signals → reports/signal_tracking.json, 10/20)
        from . import signal_tracking
        st_ = signal_tracking.build()
        out["signal_tracking"] = {"asof": st_.get("asof"), "first": st_.get("first"), "by_src": st_.get("by_src")}
    except Exception as e:  # noqa: BLE001
        log.warning("신호 추적 실패: %s", e)
    out["footer"] = V2_FOOTER
    out["v"] = 2


def _bucket(k: dict, stu: dict) -> dict:
    """_scenarios 와 같은 조건 버킷 (deep_bear 등 원자료 확률을 v2 섹션에서 쓰려고)."""
    b = (stu or {}).get("buckets20") or {}
    deep = k and k.get("dd20", 0) <= -0.15
    shock = k and k.get("ret1", 0) <= -0.05
    key = "deep" if deep and shock else "dd15" if deep else "drop5" if shock else "all"
    return b.get(key) or b.get("all") or {}


def _top_attach(out: dict, market: str) -> None:
    """보고 상단 형식 `top` 키(STANDARD.md 8절) — bottom_line 은 그대로 두고 추가만. 실패해도 회의는 계속."""
    try:
        from . import topline_from
        out["top"] = topline_from.committee(out, market)
    except Exception as e:  # noqa: BLE001
        log.warning("운용회의 top(%s) 실패: %s", market, e)


def _tg_top3(o: dict, bl: dict) -> list[str]:
    """텔레그램 ①②③ 줄 — config.TOPLINE_TG 켜지면 topline 3줄형, 꺼지면 기존 bottom_line 3줄 그대로."""
    from . import config
    if getattr(config, "TOPLINE_TG", False) and o.get("top"):
        from .topline import render_tg3
        return render_tg3(o["top"]).split("\n")
    return [f"{'①②③'[i]} {x}" for i, x in enumerate((bl.get("lines") or [])[:3])]


def _telegram_v2(o: dict) -> str:
    """모닝 미팅 v2 텔레그램 — 25줄 이내. 점심·장중 세션은 bottom_line + 시계 + ideas_top 만."""
    bl = o.get("bottom_line") or {}
    lunch = o.get("session") in ("점심", "장중")   # 장중(10:30·13:30·14:15)도 짧은 판
    L = [f"🏛 <b>운용회의 · {o.get('session', '')}</b> · {o['date']}  {bl.get('label', '')}"]
    L += _tg_top3(o, bl)
    if not lunch:
        mc = o.get("macro") or {}
        if (mc.get("regime") or {}).get("line"):
            L.append("<b>[탑다운]</b> " + mc["regime"]["line"])
        if mc.get("changed"):
            L.append("  · 바뀐 것: " + " / ".join(mc["changed"][:2]))
        ps = o.get("positioning") or {}
        if ps.get("worry"):
            L.append("<b>[포지셔닝]</b> " + ps["worry"])
        rt = o.get("rotation") or {}
        if rt.get("overweight") or rt.get("underweight"):
            L.append("<b>[섹터]</b> 확대 " + (", ".join(x["chain"] for x in rt.get("overweight", [])) or "—")
                     + " / 축소 " + (", ".join(x["chain"] for x in rt.get("underweight", [])) or "—"))
        rs = ((o.get("bottom_up") or {}).get("research") or {})
        if rs.get("n"):
            L.append(f"<b>[리서치]</b> {len(rs.get('dates', []))}일 {rs['n']}건 · 목표가 상향 {rs.get('up', 0)} · 하향 {rs.get('down', 0)}")
    it = (o.get("ideas_top") or {}).get("items") or []
    L.append("<b>[트레이드 아이디어 · 모델 북]</b>" + ("" if it else " " + str((o.get("ideas_top") or {}).get("empty") or "없음")))
    for i, x in enumerate(it[:3]):
        cat = ", ".join(f"{c['date'][5:]} {c['what']}" for c in x.get("catalyst", [])[:1]) or "촉매 없음"
        L.append(f" {i+1}. {x['n']} {x['side']} · 확신 {x['conv']} · {x['size']*100:.1f}% · 진입 {x['entry']:,.0f} 손절 {x['stop']:,.0f} 목표 {x['target']:,.0f} ({x['payoff']:.1f}R) · {cat} · {x['status']}")
    clk = bl.get("clock") or []
    if clk:   # ②에 이미 나온 3개 가격선(저점·20일 저점·5일 고점)은 빼고 시각·감마·내재 범위만
        ev = [f"{c['t']} {c['what']}" for c in clk if c["kind"] == "이벤트"]
        L.append("<b>[시계]</b> " + (" · ".join(ev[:4]) if ev else "시각 정해진 이벤트 없음"))
        L += ["  · " + c["what"] for c in clk if c["kind"] == "가격" and c.get("dist") is None][:3]
    if not lunch:
        hd = o.get("hedges") or {}
        if hd.get("hedges"):
            L.append("<b>[헤지]</b> " + hd["hedges"][0]["name"] + " — " + hd["hedges"][0]["line"])
        pm = o.get("premortem") or {}
        if pm.get("wrong"):
            L.append(f"<b>[프리모템]</b> {pm['wrong']} → 신호: {pm.get('tell', '')} → {pm.get('action', '')}")
        tl = ((o.get("track") or {}).get("lines") or [])[:1]
        if tl:
            L.append("<i>성적: " + tl[0] + "</i>")
        L += _sim_fresh_lines(o)
    L.append("<i>" + V2_FOOTER + "</i>")
    import html as _h
    tags = {"&lt;b&gt;": "<b>", "&lt;/b&gt;": "</b>", "&lt;i&gt;": "<i>", "&lt;/i&gt;": "</i>"}
    out = []
    for x in L[:25]:   # 텔레그램 HTML 모드: & < > 이스케이프 후 b·i 태그만 복원
        y = _h.escape(x, quote=False)
        for a, b in tags.items():
            y = y.replace(a, b)
        out.append(y)
    return "\n".join(out)


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
    return {"last": last, "date": str((ms.get("SPX") or [[None]])[-1][0]), "hi52": max(c[-250:]), "ret1": last / c[-2] - 1, "dd20": last / max(c[-21:]) - 1, "from_hi": last / max(c[-250:]) - 1,
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
    from . import us_committee as U
    secs = U.sector_rows(peers)   # 10/20 수정: 드라이버만 보던 판정 → 드라이버+가격추세 (국장 체인 점수와 같은 구성)
    longs = [r for r in peers if (r.get("drv") or 0) >= 0.4 and (r.get("r20") or 0) <= -0.03]
    longs.sort(key=lambda r: -(r["drv"]))
    avoid = [r for r in peers if r.get("drv") is not None and r["drv"] <= -0.2 and (r.get("r20") or 0) >= 0.05]
    avoid.sort(key=lambda r: r["drv"])
    f = lambda r: {"s": r["s"], "n": r["n"], "g": r["g"], "drv": r.get("drv"), "r20": r.get("r20"), "r5": r.get("r5")}  # noqa: E731
    cal = (_j("calendar.json", {}) or {}).get("events", [])
    fl = lambda r: {**f(r), "trend_off": _trend_off(r["s"], "US")}  # noqa: E731  # 매수 후보 '추세 꺼짐' 꼬리표(10/24 ③, 선정 규칙 불변)
    today = _kst_today()
    ev = [e for e in cal if today <= date.fromisoformat(e["date"]) <= today + timedelta(days=10) and (e.get("market") == "US" or e["type"] == "매크로")]
    head = []
    if k:
        head.append(f"S&P500 {k['last']:,.0f} ({k['ret1']*100:+.1f}%) · 20일 {k['r20']*100:+.1f}% · 20일 고점 대비 {k['dd20']*100:+.1f}% · 52주 고점 대비 {k['from_hi']*100:+.1f}%")
        head.append(f"나스닥 20일 {(k.get('nq20') or 0)*100:+.1f}% · VIX {k.get('vix') or 0:.1f} · 미 10년 {k.get('tnx') or 0:.2f}% (20일 {k.get('tnx20') or 0:+.0f}bp)")
    _acl = _ai_credit_line()
    if _acl:
        head.append(_acl)
    _btc = _btc_line()
    if _btc:
        head.append(_btc)
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
    sbf = _basis_fields(p, (b.get("all") or {}).get("n"))
    out = {"asof": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "date": str(today), "market": "US", "head": head,
           "verdict": f"가장 가능성 높은 시나리오: {best['name']} ({(best['prob'] or 0)*100:.0f}%) — 근거: 1999년 이후 S&P500 '{basis}' {p.get('n') or 0}회"
                      + _indep_suffix(sbf),
           "scenarios": scen, "scenario_basis": {"basis": basis, **sbf}, "sectors": secs, "sector_note": U.SECTOR_NOTE,
           "ideas": {"long": [fl(r) for r in longs[:10]], "avoid": [f(r) for r in avoid[:8]],
                     "trend_off_note": "추세 꺼짐 = 정식 이평 추세 롱(종가>SMA50·SMA20>SMA50) 미보유 — 10/14~23 매수 후보 70건 중 69건(reports/studies/2026-10-24_trend_discovery.md §6). 표시만, 선정 규칙 불변."},
           "events": ev[:12],
           "kr_link": capex_line(cal, today)}   # 날짜·결과는 캘린더에서 (10/23 '10/21 메타' 하드코딩 불일치 제거, req-dev-4f89d244)
    try:   # 매수 후보 '연속 N일째'·신규 표시 (표시만, 산식 불변 — req-dev-42019d08)
        from . import streak as _stk
        _hr = (json.loads(U.HIST_US.read_text(encoding="utf-8")) if U.HIST_US.exists() else {}).get("rows") or []
        out["ideas_streak"] = _stk.mark(out["ideas"]["long"], _hr, out["date"])
    except Exception as e:  # noqa: BLE001
        log.warning("미장 매수 후보 연속일 표시 실패: %s", e)
    try:
        _v2_build_us(out, k, p, cal, today)
    except Exception as e:  # noqa: BLE001
        log.warning("미장 운용회의 v2 실패: %s", e)
    _gw(OUT_US, out, key="date", default=str)
    _archive("committee_us", out)
    log.info("미장 운용회의 생성")
    return out


def _indep_suffix(sbf: dict) -> str:
    if sbf.get("n_indep") is not None:
        return f" (겹치지 않는 20일 블록 {sbf['n_indep']}개)"
    rg = sbf.get("n_indep_range") or {}
    from .us_committee import rng_txt
    return f" (겹치지 않는 20일 블록 {rng_txt(rg)}개)" if rg else ""


def _prev_us(today_s: str) -> dict | None:
    """직전 미장 회의(오늘보다 앞선 날짜의 archive/committee_us)."""
    hd = REPORT_DIR / "archive" / "committee_us"
    for f in sorted(hd.glob("20*.json"), reverse=True):
        if f.stem[:10] >= today_s:
            continue
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
    return None


def _v2_build_us(out: dict, k: dict, p: dict, cal: list[dict], today: date) -> None:
    """미장 v2 섹션 (국장 _v2_build 와 같은 키). 섹션 하나가 실패해도 나머지는 계속."""
    from . import us_committee as U
    ms = (_j("macro_series.json", {}) or {}).get("series", {})
    bonds = _j("bonds.json", {}) or {}
    mv = _j("macro_view.json", {}) or {}
    prev = _prev_us(str(today))
    steps = [("macro", lambda: U.macro_us(ms, bonds, mv, prev, _series_move)),
             ("rotation", lambda: U.rotation_us(out.get("sectors") or [])),
             ("hedges", lambda: U.hedges_us(k, out.get("scenarios") or [], p, bonds)),
             ("premortem", lambda: U.premortem_us(out.get("scenarios") or [], k, p))]
    for key, fn in steps:
        try:
            out[key] = fn()
        except Exception as e:  # noqa: BLE001
            log.warning("미장 v2 %s 실패: %s", key, e)
    if isinstance(out.get("hedges"), dict):
        out["asymmetry"] = out["hedges"].get("asymmetry")
    try:   # 미장 진입 후보 (국장 ideas_top 형식, 10/20 us-entry-ideas)
        reg = U.regime_us(mv)
        gate = "fail" if reg.get("label") == "하락장" else "pass" if reg else "n/a"
        out["ideas_top"] = U.ideas_top_us(
            out, (_j("peers_US.json", {}) or {}).get("rows", []), _j("us_accum.json", {}) or {}, cal, today,
            lambda c: _risk_box(c, "US"), lambda c: _bars(c, "US"), gate,
            reg.get("line") or "레짐 데이터 없음", _lens(_j("views.json", {}) or {}, "committee_ideas")["grade"], GRADE_W)
    except Exception as e:  # noqa: BLE001
        log.warning("미장 ideas_top 실패: %s", e)
    try:
        it = out.get("ideas_top") or {}
        watch = {str(x.get("s")) for x in (it.get("items") or []) + (it.get("candidates") or [])} | {x["s"] for x in (out.get("ideas") or {}).get("long", [])}
        out["bottom_line"] = _mock_gate(U.bottom_line_us(out, k, prev, cal, today, LIGHTS, V2_FOOTER_US, watch), it)
    except Exception as e:  # noqa: BLE001
        log.warning("미장 v2 bottom_line 실패: %s", e)
    try:   # 매매 계획 표준(trade plan) — 미장 TOP3·시그널 카드·헤지·'할 일' 줄
        from . import tradeplan
        tradeplan.attach(out, "US", today)
    except Exception as e:  # noqa: BLE001
        out["tradeplan"] = {"error": f"{type(e).__name__}: {e}"}
        log.warning("미장 trade plan 부착 실패: %s", e)
    _top_attach(out, "US")
    _hf_attach(out, "US")
    try:
        _sf = _sim_fresh("US")
        if _sf:
            out["sim_fresh"] = _sf
    except Exception as e:  # noqa: BLE001
        log.info("미장 sim_fresh 실패: %s", e)
    try:
        out.update(U.build_track(out, ms))
    except Exception as e:  # noqa: BLE001
        log.warning("미장 v2 기록·채점 실패: %s", e)
    try:   # 미장 후보도 국장과 같은 진입 규칙 모의추적에 편입 (idea_tracking.json, market=US)
        from .idea_tracking import run as track_ideas
        out["idea_tracking_top"] = track_ideas(out, market="US")
    except Exception as e:  # noqa: BLE001
        out["idea_tracking_top"] = {"error": f"{type(e).__name__}: {e}"}   # 0건 원인이 결과에 보이게 (D3)
        log.warning("미장 아이디어 추적 실패: %s", e)
    out["footer"] = V2_FOOTER_US
    out["v"] = 2


V2_FOOTER_US = "미장 회의 = 모델 북·규칙 기반·검증전. 실계좌 적용은 VIEW 게이트 통과 항목만 (개인 북은 비공개 PB 판단 참조)"


def telegram_text_us(o: dict) -> str:
    bl = o.get("bottom_line") or {}
    L = ["🗽 <b>미장 운용회의</b> · " + o["date"] + (f"  {bl['label']}" if bl.get("label") else "")] + [f"• {x}" for x in o["head"]]
    L += _tg_top3(o, bl)
    L += ["", "<b>[시나리오]</b> " + o["verdict"]]
    for s in o["scenarios"]:
        L.append(f"• {s['name']} {(s['prob'] or 0)*100:.0f}% — 신호: {s['trigger']}")
    up = [x for x in o["sectors"] if x["stance"] == "비중 확대"][:4]
    dn = [x for x in o["sectors"] if x["stance"] == "비중 축소"][:3]
    L.append("<b>[섹터]</b> 확대: " + (", ".join(f"{x['sector']}({x.get('score', x['drv']):+.2f})" for x in up) or "—") + " / 축소: " + (", ".join(x["sector"] for x in dn) or "—"))
    pm = o.get("premortem") or {}
    if pm.get("wrong"):
        L.append(f"<b>[프리모템]</b> {pm['wrong']} → 신호: {pm.get('tell', '')}")
    tl = ((o.get("track") or {}).get("lines") or [])[:1]
    if tl:
        L.append("<i>성적: " + tl[0] + "</i>")
    if o["ideas"]["long"]:
        from .streak import tag as _stag
        L.append("<b>[매수 후보]</b> " + ", ".join(f"{x['s']}{_stag(x)} {x['drv']:+.2f}" for x in o["ideas"]["long"][:6]))
        if (o.get("ideas_streak") or {}).get("line"):
            L.append("  · " + o["ideas_streak"]["line"])
    L.append("<i>" + o["kr_link"] + "</i>")
    return _hf_tail("\n".join(L), o)
