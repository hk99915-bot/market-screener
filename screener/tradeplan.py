"""매매 계획 표준(trade plan) — 진입 구간·스탑·1차/2차 목표·R:R·확률·기대값·분할 청산·시간 손절·매크로 필터·컨빅션·크기.

비유: 등산 계획서. 어디서 출발(진입 구간)하고, 어디서 돌아서는지(스탑), 첫 쉼터(1차 목표)와 정상(2차 목표),
해 지기 전 하산 시각(시간 손절), 날씨 예보(매크로 필터), 체력(컨빅션)에 따라 짐 무게(크기)를 정한다.
용어: R = 진입가 − 스탑(1회 위험 1단위). R:R = (목표 − 진입) ÷ (진입 − 스탑). E[R] = 계획대로 했을 때 평균 결과(R 단위, 비용 차감).

스펙 문서: reports/studies/2026-10-21_tradeplan_spec.md · 보정: reports/studies/*_tradeplan_calib.json (scripts/study_tradeplan.py).
데스크 책임: 퀀트=확률·보정(prob) · 애널=목표가·밸류(t2) · 매크로=필터(filter) · CIO=최종 채택(verdict)·TOP3 · FRM=크기·한도(size).
모든 계획은 모의 추적·표시용 — 실계좌 위성 해금(agreements §6) 전에는 실행 근거가 아니다.

순수 함수(build_plan·conviction·macro_filter·calib_lookup)는 파일·네트워크를 읽지 않는다. 파일을 읽는 건 load_calib·market_ctx·attach 뿐.
영향 범위: committee(KR·US) ideas_top·stance.exec.cands·hedges·sim_fresh·bottom_line 에 plan 필드/문구 추가, duel 규칙 픽에 plan.
롤백: committee.py·duel.py 의 tradeplan 호출(try 블록) 제거 — plan 필드는 선택 키라 소비자 호환.
"""
from __future__ import annotations

import json
import logging
import math
import re
from datetime import date, timedelta
from pathlib import Path

log = logging.getLogger(__name__)

STOP_ATR_MIN, STOP_ATR_MAX = 1.0, 2.0      # 구조적 스탑: max(20일 저점, 종가 − 2×ATR14), 최소 1×ATR (FRM #16, 보정 struct)
ZONE_ATR = 0.5                              # 진입 구간 = 종가 ± 0.5×ATR (하한은 max(스탑+0.5R, 종가−0.5ATR) — idea_tracking.entry_floor)
R1_DEFAULT, R2_DEFAULT = 1.5, 3.0           # 보정 추천(평탄 영역) — 2026-10-21 calib
R1_BAND = (1.0, 2.5)                        # 가까운 저항이 이 R 범위면 1차 목표로 채택
R2_CAP = 5.0                                # 2차 목표 상한(R) — 밸류·애널 목표가가 멀어도 20일 계획에선 5R 까지만
SCALE_FRAC = 0.5                            # 1차에서 50% 익절, 스탑 본전 이동
HOLD_DAYS = 20                              # 시간 손절(거래일)
MAX_STOP_PCT = 0.15                         # 손절폭 15% 초과 = 계획 불가(FRM #17)
WEIGHT_CAP = 0.15                           # 단일 종목 비중 상한
STAGE_RISK = {0: 0.0, 1: 0.0025, 2: 0.005, 3: 0.01}   # agreements §6 해금 단계별 1회 리스크(총자산 대비)
STAGE_NOW = 1                               # 모의 표기 기준 = 1단계(0.25%). 실계좌 위성 신규는 해금 후
MIN_RR2 = 2.0                               # 주문표 규칙 R:R ≥ 2 (defs.MIN_RR) — 2차 목표 기준
COST = {"KR": 0.0025, "US": 0.0010}
CONV_BANDS = [(70, "A", 1.0), (58, "B", 0.75), (45, "C", 0.5), (-1, "D", 0.0)]
AXES = ("fund", "narr", "sent", "tech")
AXIS_KO = {"fund": "펀더", "narr": "내러티브", "sent": "센티먼트", "tech": "기술"}
# 축 가중: 공통 이력 기간이 없어 축 간 보정 불가 → 검증전 동일가중. 기술 축 안의 하위 가중만 보정(calib axes IC).
TECH_W = {"KR": (0.66, 0.34), "US": (0.65, 0.35)}   # (50일선 괴리, 60일 수익률) — 학습 IC 비례, 52주 고점 근접은 0
BUY_RX = re.compile(r"(매수|편입)")
NEG_RX = re.compile(r"(금지|하지 말|않|추격|말 것|없는|없음|보류|제외|대기|전엔|후보)")


# ───────────── 기초 계산 ─────────────

def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def atr14(bars: list[dict]) -> float | None:
    b = [x for x in bars if _num(x.get("h")) and _num(x.get("l")) and _num(x.get("c"))]
    if len(b) < 15:
        return None
    tr = [max(b[i]["h"], b[i - 1]["c"]) - min(b[i]["l"], b[i - 1]["c"]) for i in range(len(b) - 14, len(b))]
    return sum(tr) / len(tr)


def levels(bars: list[dict]) -> dict:
    """지지(20일 저점·52주 저점)·저항(20·60일 고점, 52주 고점, 50·200일선 중 종가 위) — 종가 기준 오름차순."""
    b = [x for x in bars if _num(x.get("c")) and _num(x.get("h")) and _num(x.get("l"))]
    c = b[-1]["c"]
    hi = lambda n: max(x["h"] for x in b[-n:])  # noqa: E731
    res = {"20일 고점": hi(20), "60일 고점": hi(min(60, len(b))), "52주 고점": hi(min(250, len(b)))}
    for k in ("s50", "s200"):
        v = b[-1].get(k)
        if _num(v):
            res[{"s50": "50일선", "s200": "200일선"}[k]] = v
    above = sorted(((v, k) for k, v in res.items() if v > c * 1.001), key=lambda t: t[0])
    return {"support20": min(x["l"] for x in b[-20:]), "low52": min(x["l"] for x in b[-min(250, len(b)):]),
            "res": [{"px": v, "what": k} for v, k in above], "hi52": res["52주 고점"]}


def median(xs):
    xs = sorted(x for x in xs if _num(x))
    if not xs:
        return None
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


# ───────────── 보정 조회 (퀀트) ─────────────

def load_calib(root: Path | None = None) -> dict | None:
    from .config import REPORT_DIR
    fs = sorted((Path(root) if root else REPORT_DIR / "studies").glob("*_tradeplan_calib.json"))
    if not fs:
        return None
    try:
        return json.loads(fs[-1].read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _grade(t: dict | None) -> str:
    if not t or (t.get("n_dates") or 0) < 30:
        return "검증전"
    ev, tt = t.get("ev_r"), t.get("t") or 0
    if ev is None or ev <= 0:
        return "F"
    return "C" if tt >= 2 else "C(방향만)" if tt >= 1.28 else "F"


def calib_lookup(calib: dict | None, group: str, r1: float, r2: float, stop: str = "struct") -> dict:
    """같은 신호 군·스탑 규칙에서 (r1, r2) 에 가장 가까운 분할 청산 칸의 검증(OOS) 성적. 없으면 검증전."""
    g = ((calib or {}).get("groups") or {}).get(group) or {}
    sc = ((g.get("grid") or {}).get(stop) or {}).get("scale") or {}
    if not sc:
        return {"group": group, "grade": "검증전", "note": "보정 없음(calib json 없음 또는 군 없음)"}
    key = min(sc, key=lambda k: abs(float(k.split("/")[0]) - r1) + 0.5 * abs(float(k.split("/")[1]) - r2))
    t = sc[key].get("test") or {}
    single = (((g.get("grid") or {}).get(stop) or {}).get("single") or {}).get(str(float(key.split("/")[0]))) or {}
    st = (single.get("test") or {})
    return {"group": group, "desc": g.get("desc"), "cell": f"{stop} {key}", "split": g.get("split"),
            "p_t1": t.get("p_t1"), "p_stop": t.get("p_s"), "p_t2": t.get("p_t2"), "p_time": st.get("p_time"),
            "ev_r": t.get("ev_r"), "t": t.get("t"), "n": t.get("n"), "n_dates": t.get("n_dates"),
            "stop_exit_r": st.get("stop_exit_r"), "grade": _grade(t), "asof": (calib or {}).get("asof"),
            **_base_cmp(calib, group, stop, key)}


def _base_cmp(calib, group, stop, key):
    """같은 칸의 '무조건 표본' 기준선 E[R] — 기준선도 양수면 그 몫은 시장 상승(베타)이지 신호·계획 엣지가 아니다."""
    base = group.split("_")[0] + "_base"
    if base == group:
        return {}
    b = ((((((calib or {}).get("groups") or {}).get(base) or {}).get("grid") or {}).get(stop) or {}).get("scale") or {}).get(key) or {}
    ev = (b.get("test") or {}).get("ev_r")
    return {} if ev is None else {"base_ev_r": ev}


def pick_group(market: str, close: float, s50: float | None, src_keys: set[str]) -> str:
    if market == "KR" and "accum" in src_keys:
        return "kr_accum"
    trend = _num(s50) and close > s50
    return f"{market.lower()}_{'trend' if trend else 'base'}"


# ───────────── 컨빅션 (펀더·내러티브·센티먼트·기술) ─────────────

def _tanh(x, s):
    return math.tanh(x / s) if _num(x) else None


def tech_axis(bars: list[dict], market: str) -> float | None:
    b = [x for x in bars if _num(x.get("c"))]
    if len(b) < 61:
        return None
    c = b[-1]["c"]
    s50 = b[-1].get("s50") if _num(b[-1].get("s50")) else sum(x["c"] for x in b[-50:]) / 50
    w1, w2 = TECH_W.get(market, (0.5, 0.5))
    return w1 * _tanh(c / s50 - 1, 0.10) + w2 * _tanh(c / b[-61]["c"] - 1, 0.25)


def axes_from_detail(det: dict | None, sources: list[dict] | None, bars: list[dict], market: str) -> dict:
    """detail json·원천 목록 → 4축 값(−1~1, 없으면 None)과 근거 문자열."""
    det = det or {}
    src = sources or []
    why = {a: [] for a in AXES}
    vals = {a: [] for a in AXES}

    def put(a, v, w):
        if _num(v):
            vals[a].append(max(-1.0, min(1.0, v)))
            why[a].append(w)
    drv = det.get("drivers") or {}
    # 펀더: 이익 추정 변화(eps)·밸류(모델 중앙 상승여력)·이익 드라이버 점수
    mods = [m.get("upside") for m in ((det.get("valuation") or {}).get("models") or {}).values() if m.get("group") == "current"]
    up = median(mods)
    put("fund", _tanh(up, 0.5), f"밸류 모델 중앙 상승여력 {up*100:+.0f}%" if _num(up) else "")
    eps = drv.get("eps") or {}
    if _num(eps.get("score")):
        put("fund", eps["score"], f"EPS 추정 점수 {eps['score']:+.2f}")
    for s in src:
        if s.get("k") in ("committee_ideas", "us_drv"):
            put("fund", 0.5 if s.get("side") == "agree" else -0.5, s.get("label", ""))
        if s.get("k") == "committee_avoid":
            put("fund", -0.5, s.get("label", ""))
    # 내러티브: 애널 톤·목표가 상승여력·리서치 목표가 상/하향·공시
    an = drv.get("analyst") or {}
    put("narr", an.get("score"), f"애널 톤 점수 {an.get('score'):+.2f}" if _num(an.get("score")) else "")
    tpu = (det.get("research") or {}).get("tp_upside")
    put("narr", _tanh(tpu, 0.3), f"목표가 상승여력 {tpu*100:+.0f}%" if _num(tpu) else "")
    for s in src:
        if s.get("k") in ("research:tp_up", "disclosure:plus"):
            put("narr", 0.5, s.get("label", ""))
        if s.get("k") in ("research:tp_down", "disclosure:dilution"):
            put("narr", -0.5, s.get("label", ""))
    # 센티먼트: 외국인+기관 10일 순매수(거래대금 대비)·공매도 잔고 변화·매집/숏스퀴즈 원천
    fl = det.get("flows") or []
    dv = ((det.get("stats") or {}).get("dollar_vol20"))
    if fl and _num(dv) and dv > 0 and market == "KR":
        net = sum((x.get("외국인") or 0) + (x.get("기관") or 0) for x in fl[-10:]) * 1e8
        put("sent", _tanh(net / (dv * 10), 0.05), f"외인+기관 10일 순매수 = 거래대금의 {net/(dv*10)*100:+.1f}%")
    sh = det.get("short") or {}
    if _num(sh.get("chg20")) and _num(sh.get("ratio")) and sh["ratio"] > 0.005:
        put("sent", _tanh(-sh["chg20"], 0.3), f"공매도 잔고 20일 변화 {sh['chg20']:+.2f} (detail.short.chg20 원값)")
    for s in src:
        if s.get("k") in ("squeeze", "us_accum", "accum"):
            put("sent", 0.4, s.get("label", ""))
    # 기술: 50일선 괴리·60일 수익률 (보정 가중) + 시그널 원천
    put("tech", tech_axis(bars, market), "50일선 괴리·60일 수익률(보정 가중)")
    for s in src:
        if s.get("k") in ("signal:trend", "momentum:12-1", "us_trend"):
            put("tech", 0.5 if s.get("side") == "agree" else -0.5, s.get("label", ""))
    out = {}
    for a in AXES:
        v = vals[a]
        out[a] = {"v": round(sum(v) / len(v), 3) if v else None, "why": [w for w in why[a] if w][:3]}
    return out


def conviction(axes: dict) -> dict:
    """4축(−1~1) → 0~100 점수·A~D 등급·리스크 배수·2차 목표 보유 여부. 가중 = 검증전 동일가중(가용 축만)."""
    av = {a: x["v"] for a, x in axes.items() if x and _num(x.get("v"))}
    if not av:
        return {"score": None, "grade": "D", "mult": 0.0, "hold_t2": False, "axes": axes, "used": 0,
                "weights": "검증전 동일가중", "note": "축 데이터 없음 → D(보류)"}
    sc = 50 + 50 * sum(av.values()) / len(av)
    g, m = next((g, m) for lo, g, m in CONV_BANDS if sc >= lo)
    note = None
    if len(av) < 2 and g in ("A", "B"):
        g, m, note = "C", 0.5, "가용 축 1개 → 상한 C"
    return {"score": round(sc, 1), "grade": g, "mult": m, "hold_t2": g in ("A", "B"), "axes": axes, "used": len(av),
            "weights": "검증전 동일가중 (축 간 공통 이력 없음 — 펀더·내러티브 2026-10~). 기술 축 내부만 보정(IC)", "note": note}


# ───────────── 매크로 필터 (매크로) ─────────────

def macro_filter(ctx: dict | None, det: dict | None = None, market: str = "KR", earn_days: int | None = None) -> dict:
    """시장 상태(레짐·바람·변동성·이벤트 D-n·금리/유가/환율 충격) × 종목 민감도 → 상태(정상·축소·보류)·배수·2차 목표 감액.
    규칙 등급: 레짐 C(macro KB #4) · 나머지 검증전."""
    ctx = ctx or {}
    mult, reasons, flags, t2_haircut, hold = 1.0, [], [], 0.0, False
    reg = ctx.get("regime")
    if reg == "하락장":
        mult *= 0.5
        reasons.append("레짐 하락장 → 크기 ½ (C)")
    wind = ctx.get("wind")
    if _num(wind) and wind <= -0.3:
        mult *= 0.75
        reasons.append(f"매크로 바람 {wind:+.2f} 역풍 → ×0.75")
    im = ctx.get("implied_move")
    if (_num(im) and im >= 0.03) or (_num(ctx.get("vix")) and ctx["vix"] >= 30):
        mult *= 0.5
        reasons.append(f"변동성 고조(내재 1일 {im*100:.1f}%)" if _num(im) else f"VIX {ctx['vix']:.0f}" + " → ×0.5")
    for ev in ctx.get("events") or []:
        d = ev.get("d")
        if d == 0:
            hold = True
            reasons.append(f"{ev['what']} 당일 — 위성 신규 진입 금지(agreements)")
        elif d == 1:
            mult *= 0.5
            reasons.append(f"{ev['what']} D-1 → ×0.5")
    # 금리·유가·환율 충격 × 종목 실측 민감도(detail.drivers.macro rows, |t|≥2 만)
    rows = (((det or {}).get("drivers") or {}).get("macro") or {}).get("rows") or []
    for sh in ctx.get("shocks") or []:
        r = next((x for x in rows if x.get("factor") in sh["factors"] and _num(x.get("beta")) and _num(x.get("t")) and abs(x["t"]) >= 2), None)
        if r and r["beta"] * sh["dir"] < 0:
            mult *= 0.75
            t2_haircut = max(t2_haircut, 0.5)
            flags.append(sh["name"])
            reasons.append(f"{sh['name']} × 민감도 {r['name']} β {r['beta']:+.2f}(t {r['t']:+.1f}) 역방향 → ×0.75·2차 목표 절반 (검증전)")
    if earn_days is not None and 0 <= earn_days <= HOLD_DAYS:
        flags.append(f"어닝 D-{earn_days}")
        if earn_days <= 2:
            hold = True
            reasons.append(f"실적 D-{earn_days} — 갭이 스탑을 무력화 → 신규 보류 (이벤트 드리븐 연구 전 임시 규칙)")
    st = "보류" if hold or mult < 0.2 else "축소" if mult < 0.999 else "정상"
    return {"state": st, "mult": 0.0 if st == "보류" else round(mult, 3), "reasons": reasons, "flags": flags,
            "t2_haircut": t2_haircut, "grade": "레짐 C · 나머지 검증전"}


def earnings_rule(earn_days: int | None) -> dict | None:
    if earn_days is None or earn_days > HOLD_DAYS:
        return None
    return {"flag": f"어닝 이벤트 D-{earn_days}", "pre": "실적 D-1 종가까지 1차 미도달이면 절반 축소 · 스탑은 넓히지 않음(갭은 스탑을 건너뜀)",
            "post": "발표 다음날 시가가 스탑 아래면 시가 청산, 1R 이상 갭 상승이면 1차 익절 후 본전 스탑",
            "grade": "검증전 — 이벤트 드리븐 연구(reports/studies/*_event_driven) 결과로 교체 예정"}


# ───────────── 계획 본체 ─────────────

def build_plan(bars: list[dict], *, market: str = "KR", det: dict | None = None, sources: list[dict] | None = None,
               ctx: dict | None = None, calib: dict | None = None, earn_days: int | None = None, stage: int = STAGE_NOW,
               hold_days: int = HOLD_DAYS, name: str | None = None, code: str | None = None) -> dict | None:
    """일봉(+상세·원천·시장 상태·보정) → plan dict. 일봉 21개 미만·스탑 계산 불가면 None."""
    b = [x for x in bars if _num(x.get("c")) and _num(x.get("h")) and _num(x.get("l"))]
    if len(b) < 21:
        return None
    c = b[-1]["c"]
    atr = atr14(b)
    if not atr or atr <= 0:
        return None
    lv = levels(b)
    # 스탑 (FRM·퀀트): 구조적 지지 vs ATR — max(20일 저점, C − 2ATR), 최소 1ATR
    d_atr = max(STOP_ATR_MIN, min(STOP_ATR_MAX, (c - lv["support20"]) / atr))
    stop = c - d_atr * atr
    R = c - stop
    stop_pct = R / c
    src_keys = {s.get("k") for s in (sources or [])}
    halted = any((x.get("v") == 0) for x in b[-60:] if "v" in x)
    # 1차 목표 (애널·퀀트): 가까운 저항이 1~2.5R 안이면 그것, 아니면 1.5R
    t1, t1_basis = c + R1_DEFAULT * R, f"{R1_DEFAULT}R (가까운 저항 없음/범위 밖)"
    for r in lv["res"]:
        rr = (r["px"] - c) / R
        if R1_BAND[0] <= rr <= R1_BAND[1]:
            t1, t1_basis = r["px"], f"저항 {r['what']} ({rr:.1f}R)"
            break
    # 2차 목표 (애널): 밸류 모델 중앙·애널 목표가(컨센서스)·52주 고점 중 1차 위 후보의 중앙값, 상한 5R
    det = det or {}
    vm = median([m.get("value") for m in ((det.get("valuation") or {}).get("models") or {}).values() if m.get("group") == "current"])
    res = det.get("research") or {}
    tp = res.get("consensus_tp") or ((det.get("scenarios") or {}).get("bull") or {}).get("target")
    cands = [(vm, "밸류 모델 중앙값"), (tp, "애널 목표가"), (lv["hi52"], "52주 고점")]
    above = [(v, w) for v, w in cands if _num(v) and v > t1]
    if above:
        mv = median([v for v, _ in above])
        t2 = min(mv, c + R2_CAP * R)
        t2_basis = "중앙값(" + "·".join(w for _, w in above) + ")" + (f" → 상한 {R2_CAP:.0f}R" if mv > t2 else "")
    else:
        t2, t2_basis = max(c + R2_DEFAULT * R, t1 + R), f"{R2_DEFAULT}R (밸류·애널·52주 고점이 1차 아래/없음)"
    filt = macro_filter(ctx, det, market, earn_days)
    if filt["t2_haircut"]:
        t2 = t1 + (t2 - t1) * (1 - filt["t2_haircut"])
        t2_basis += f" · 매크로 감액 {filt['t2_haircut']*100:.0f}%"
    rr1, rr2 = (t1 - c) / R, (t2 - c) / R
    # 확률·기대값 (퀀트 보정)
    group = pick_group(market, c, b[-1].get("s50"), src_keys)
    prob = calib_lookup(calib, group, rr1, rr2)
    se = prob.get("stop_exit_r") or -1.0
    # 컨빅션 → 크기 (FRM)
    conv = conviction(axes_from_detail(det, sources, b, market))
    risk = STAGE_RISK.get(stage, 0.0) * conv["mult"] * filt["mult"]
    weight = min(risk / stop_pct, WEIGHT_CAP) if stop_pct > 0 else 0.0
    lo = max(stop + 0.5 * R, c - ZONE_ATR * atr)
    hi = c + ZONE_ATR * atr
    reasons = []
    if stop_pct > MAX_STOP_PCT:
        reasons.append(f"손절폭 {stop_pct*100:.1f}% > 15%")
    if rr2 < MIN_RR2:
        reasons.append(f"2차 R:R {rr2:.1f} < {MIN_RR2:.0f}")
    if filt["state"] == "보류":
        reasons.append("매크로·이벤트 필터 보류")
    if conv["grade"] == "D":
        reasons.append(f"컨빅션 D({conv['score']})")
    soft = []
    if prob.get("grade") == "F":
        soft.append(f"보정 E[R] {prob.get('ev_r'):+.2f}R ≤ 0 (F, {group}) — 계획 기하만으론 기대값 없음, 신호 엣지 검증 전")
    elif prob.get("grade") == "검증전":
        soft.append("확률·기대값 검증전")
    elif _num(prob.get("base_ev_r")) and _num(prob.get("ev_r")) and prob["ev_r"] <= prob["base_ev_r"]:
        soft.append(f"E[R] {prob['ev_r']:+.2f} ≤ 무조건 기준선 {prob['base_ev_r']:+.2f} — 양수 몫은 시장 상승(베타), 신호 엣지 아님")
    verdict = "보류" if reasons else "관찰(모의)" if soft else "채택(모의)"
    plan = {
        "v": 1, "code": code, "name": name, "market": market, "side": "롱", "asof": b[-1].get("t") or b[-1].get("d"),
        "close": c, "atr": atr, "atr_pct": atr / c,
        "entry": {"lo": lo, "hi": hi, "ref": c, "cond": f"다음 거래일 시가가 {lo:,.2f}~{hi:,.2f} 안이면 시가 진입, 밖이면 미진입 만료(1일). 추격 금지"},
        "stop": {"px": stop, "pct": stop_pct, "atr_mult": round(d_atr, 2), "basis": "max(20일 저점, 종가−2×ATR14), 최소 1×ATR — 종가 이탈 시 청산",
                 "slip_r": se, "loss_eff_pct": stop_pct * abs(se),
                 "gap_note": f"갭·하한가로 스탑 아래 체결 시 평균 {se:.2f}R (보정 {prob.get('group')})" + (" · 최근 60일 거래정지/무거래일 있음" if halted else "")},
        "t1": {"px": t1, "r": round(rr1, 2), "basis": t1_basis},
        "t2": {"px": t2, "r": round(rr2, 2), "basis": t2_basis, "hold": conv["hold_t2"]},
        "rr1": round(rr1, 2), "rr2": round(rr2, 2),
        "prob": prob, "ev_r": prob.get("ev_r"), "ev_pct": (prob["ev_r"] * stop_pct) if _num(prob.get("ev_r")) else None,
        "scale_out": {"t1_frac": SCALE_FRAC, "then": "스탑을 진입가(본전)로 이동", "rest": "2차 목표·본전 스탑·시간 손절 중 먼저" if conv["hold_t2"] else "컨빅션 C 이하 → 1차에서 전량 청산"},
        "time_stop": {"days": hold_days, "rule": f"{hold_days}거래일 안 1차 미도달 → 그날 종가 청산"},
        "filter": filt, "earnings": earnings_rule(earn_days), "conviction": conv,
        "size": {"stage": stage, "risk_base": STAGE_RISK.get(stage, 0.0), "risk_pct": risk, "weight": weight, "cap": WEIGHT_CAP,
                 "formula": "비중 = 1회 리스크(해금 단계 × 컨빅션 배수 × 필터 배수) ÷ 손절폭, 상한 15%", "mock": True,
                 "note": "모의 추적·표시용 — 실계좌 위성 해금(§6 1단계 11/16 리뷰) 전 실행 근거 아님"},
        "verdict": verdict, "why_not": reasons + soft,
        "verdict_rule": "보류 = 손절폭>15%·2차 R:R<2·필터 보류·컨빅션 D 중 하나 / 관찰 = 보정 E[R] F·검증전 또는 무조건 기준선 이하 / 채택 = 그 외 (모두 모의)",
        "owners": {"quant": "prob·보정", "analyst": "t2·밸류", "macro": "filter", "cio": "verdict·TOP3", "frm": "size·stop"},
    }
    plan["line"] = plan_line(plan)
    return plan


def _px(v, market):
    return f"{v:,.0f}" if market == "KR" else f"{v:,.2f}"


def plan_line(p: dict | None) -> str | None:
    """한 줄 요약 — '진입 a~b · 손절 s(−x%) · 1차 t1(1.5R) · 2차 t2(3.0R) · 1차 확률 p/손절 q · E[R] · 20일 · 필터 · 컨빅션'."""
    if not p:
        return None
    m = p.get("market", "KR")
    pr = p.get("prob") or {}
    pt = (f"1차 선도달 {pr['p_t1']*100:.0f}% vs 손절 {pr['p_stop']*100:.0f}%" if _num(pr.get("p_t1")) and _num(pr.get("p_stop")) else "확률 검증전")
    ev = f"E[R] {pr['ev_r']:+.2f}({pr.get('grade')}" + (f", 기준선 {pr['base_ev_r']:+.2f}" if _num(pr.get("base_ev_r")) else "") + ")" if _num(pr.get("ev_r")) else "E[R] 검증전"
    cv = p.get("conviction") or {}
    return (f"진입 {_px(p['entry']['lo'], m)}~{_px(p['entry']['hi'], m)} · 손절 {_px(p['stop']['px'], m)}(−{p['stop']['pct']*100:.1f}%)"
            f" · 1차 {_px(p['t1']['px'], m)}({p['rr1']:.1f}R) · 2차 {_px(p['t2']['px'], m)}({p['rr2']:.1f}R{'' if p['t2'].get('hold') else '·미보유'})"
            f" · {pt} · {ev} · {p['time_stop']['days']}일 · 필터 {p['filter']['state']} · 컨빅션 {cv.get('grade')}({cv.get('score')})"
            f" · {p['verdict']}")


# ───────────── 시장 상태 (파일 읽기) ─────────────

def _series_chg(ser: dict, key: str, n: int = 20, diff: bool = False):
    s = [b for b in (ser.get(key) or []) if b and _num(b[4])]
    if len(s) <= n:
        return None
    a, z = s[-n - 1][4], s[-1][4]
    return (z - a) if diff else (z / a - 1)


def market_ctx(o: dict, market: str, today: date | None = None) -> dict:
    """committee 산출물 + macro_series·calendar → macro_filter 입력."""
    from .config import REPORT_DIR
    today = today or date.today()

    def j(n):
        try:
            return json.loads((REPORT_DIR / n).read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}
    mac = o.get("macro") or {}
    reg = (mac.get("regime") or {}).get("label")
    mv = j("macro_view.json")
    wind = mv.get("score") if _num(mv.get("score")) else None
    im = (((o.get("positioning") or {}).get("implied") or {}).get("pct"))
    ser = (j("macro_series.json").get("series") or {})
    vix = ((ser.get("VIX") or [[None] * 5])[-1][4]) if ser.get("VIX") else None
    shocks = []
    d10 = _series_chg(ser, "US10Y", diff=True)
    if _num(d10) and d10 >= 0.25:
        shocks.append({"name": f"금리 급등(미10Y 20일 {d10*100:+.0f}bp)", "factors": ("US10Y", "KR3Y", "KTB3Y"), "dir": 1})
    if _num(d10) and d10 <= -0.25:
        shocks.append({"name": f"금리 급락(미10Y 20일 {d10*100:+.0f}bp)", "factors": ("US10Y", "KR3Y", "KTB3Y"), "dir": -1})
    w = _series_chg(ser, "WTI")
    if _num(w) and abs(w) >= 0.15:
        shocks.append({"name": f"유가 {'급등' if w > 0 else '급락'}(WTI 20일 {w*100:+.0f}%)", "factors": ("WTI", "OIL"), "dir": 1 if w > 0 else -1})
    fx = _series_chg(ser, "USDKRW")
    if market == "KR" and _num(fx) and abs(fx) >= 0.03:
        shocks.append({"name": f"원화 {'약세' if fx > 0 else '강세'}(달러원 20일 {fx*100:+.1f}%)", "factors": ("KRW", "USDKRW"), "dir": 1 if fx > 0 else -1})
    evs = []
    for e in (j("calendar.json").get("events") or []):
        try:
            d = (date.fromisoformat(e["date"]) - today).days
        except Exception:  # noqa: BLE001
            continue
        if 0 <= d <= 1 and e.get("imp", 1) >= 3 and e.get("type") == "매크로":
            evs.append({"d": d, "what": e.get("name", "")})
    return {"regime": reg if market == "KR" else (reg or None), "wind": wind, "implied_move": im if market == "KR" else None,
            "vix": vix if market == "US" else None, "events": evs, "shocks": shocks,
            "rates": {"us10y_20d_bp": round(d10 * 100) if _num(d10) else None, "wti_20d": w, "usdkrw_20d": fx}}


def earn_days_for(code: str, cal: list[dict], today: date) -> int | None:
    best = None
    for e in cal or []:
        if e.get("type") == "실적" and str(e.get("ticker")) == str(code):
            try:
                d = (date.fromisoformat(e["date"]) - today).days
            except Exception:  # noqa: BLE001
                continue
            if d >= 0 and (best is None or d < best):
                best = d
    return best


def _detail(code: str, market: str) -> dict:
    from .config import REPORT_DIR
    try:
        return json.loads((REPORT_DIR / "detail" / market / f"{code}.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def plan_for(code: str, market: str, o: dict, ctx: dict, calib: dict | None, cal: list[dict], today: date,
             sources: list[dict] | None = None, name: str | None = None, hold_days: int = HOLD_DAYS) -> dict | None:
    det = _detail(code, market)
    return build_plan(det.get("chart") or [], market=market, det=det, sources=sources, ctx=ctx, calib=calib,
                      earn_days=earn_days_for(code, cal, today), name=name or det.get("name"), code=code, hold_days=hold_days)


def hedge_plan(h: dict, asym: dict | None) -> dict:
    """옵션·인버스 헤지 계획: 진입 = 이론가, 스탑 = 프리미엄 전액(최대 손실), 1차 = 기초 −5%, 2차 = 기초 −15% 이익, 시간 = 만기."""
    loss = h.get("cost") if _num(h.get("cost")) else None
    gain = (asym or {}).get("gain") if (asym or {}).get("name") == h.get("name") else None
    return {"v": 1, "kind": "hedge", "entry": {"cond": h.get("when") or "약세 시나리오 대비", "ref": "이론가"},
            "stop": {"pct": loss, "basis": "프리미엄 전액 = 최대 손실(옵션) — 손절 주문 없음"},
            "t1": {"basis": "기초 −5% 도달 시 절반 이익 실현"}, "t2": {"basis": "기초 −15% 시 이익 " + (f"{gain*100:.1f}%" if _num(gain) else "—")},
            "rr2": round(gain / loss, 2) if _num(gain) and _num(loss) and loss > 0 else None,
            "prob": {"p_t2": (asym or {}).get("p") if gain is not None else None, "grade": "C(과거 빈도)" if gain is not None else "검증전"},
            "time_stop": {"rule": "만기 또는 약세 시나리오 철회(20일선 2일 회복) 시 청산"},
            "size": {"formula": "북 명목의 25% 헤지 · 비용 = cost_book", "mock": True},
            "filter": {"state": "정상", "reasons": []}, "verdict": "모델 북 전용(모의)",
            "line": f"헤지 계획: 최대 손실 {loss*100:.1f}%" + (f" · −15% 시 +{gain*100:.1f}% (R:R {gain/loss:.1f})" if _num(gain) and _num(loss) and loss else "") + " · 만기 청산" if _num(loss) else "헤지 계획: 비용 미확인"}


# ───────────── 운용회의 부착 + 문구 가드 ─────────────

def attach(o: dict, market: str = "KR", today: date | None = None, calib: dict | None = None) -> dict:
    """committee 산출물 o 의 ideas_top(items·candidates)·stance.exec.cands·sim_fresh·hedges 에 plan, bottom_line '할 일' 에 계획 줄.
    반환 요약 {n_plans, n_adopt, ctx}. 실패한 종목은 plan_error 로 남긴다(조용한 누락 금지)."""
    from .config import REPORT_DIR
    today = today or date.today()
    calib = calib if calib is not None else load_calib()
    try:
        cal = json.loads((REPORT_DIR / "calendar.json").read_text(encoding="utf-8")).get("events") or []
    except Exception:  # noqa: BLE001
        cal = []
    ctx = market_ctx(o, market, today)
    n = n_ok = 0
    rows = []
    it = o.get("ideas_top") or {}
    rows += [(x, x.get("sources")) for x in (it.get("items") or []) + (it.get("candidates") or [])]
    rows += [(x, None) for x in (((o.get("stance") or {}).get("exec") or {}).get("cands") or [])]
    sf = o.get("sim_fresh") or {}
    rows += [(x, [{"k": "signal:trend", "side": "agree", "label": x.get("label", "추세 신호")}]) for x in (sf.get("items") or [])]
    for x, src in rows:
        code = str(x.get("s") or "")
        if not code:
            continue
        try:
            p = plan_for(code, market, o, ctx, calib, cal, today, src, x.get("n"))
        except Exception as e:  # noqa: BLE001
            p, x["plan_error"] = None, f"{type(e).__name__}: {e}"
        if p:
            x["plan"] = p
            n += 1
            n_ok += p["verdict"].startswith("채택")
        else:
            x.setdefault("plan_error", "일봉 부족 — 계획 없음(매수 문구 금지 대상)")
    hd = o.get("hedges") or {}
    for h in hd.get("hedges") or []:
        h["plan"] = hedge_plan(h, hd.get("asymmetry"))
    bl = o.get("bottom_line") or {}
    items = it.get("items") or []
    top = next((x for x in items if x.get("plan")), None)
    if bl.get("lines"):
        L = bl["lines"]
        add = (f" | 계획(TOP1 {top.get('n')}): " + top["plan"]["line"]) if top else " | 계획: TOP3 계획 없음 — 매수·편입 문구 없음"
        i = next((k for k, s in enumerate(L) if "할 일" in str(s)), None)
        if i is None:
            L.append(add.strip(" |"))
        elif "계획(" not in L[i] and "계획:" not in L[i]:
            L[i] = L[i] + add
    o["tradeplan"] = {"v": 1, "n_plans": n, "n_adopt": n_ok, "ctx": ctx, "calib_asof": (calib or {}).get("asof"),
                      "spec": "reports/studies/2026-10-21_tradeplan_spec.md", "mock": True}
    guard_buy_text(o)
    return o["tradeplan"]


def _texts(o: dict):
    """매수/편입 문구가 생길 수 있는 사람용 문자열 위치 (부모 dict, 키)."""
    st = o.get("stance") or {}
    if isinstance(st.get("plan"), str):
        yield st, "plan"
    for s in ((st.get("exec") or {}).get("steps") or []):
        for k in ("when", "do"):
            if isinstance(s.get(k), str):
                yield s, k
    bl = o.get("bottom_line") or {}
    for i in range(len(bl.get("lines") or [])):
        yield bl["lines"], i
    for sc in o.get("scenarios") or []:
        if isinstance(sc.get("action"), str):
            yield sc, "action"


def affirmative_buy(s: str) -> bool:
    """'매수/편입' 이 긍정(하라는) 문맥인가 — 같은 절(·,.;—) 안에 금지·추격·대기·없음 등이 있으면 부정 문맥."""
    for part in re.split(r"[·,.;—/()]", s):
        if BUY_RX.search(part) and not NEG_RX.search(part):
            return True
    return False


def has_plan(o: dict) -> bool:
    it = o.get("ideas_top") or {}
    xs = (it.get("items") or []) + (((o.get("stance") or {}).get("exec") or {}).get("cands") or [])
    return any(isinstance(x.get("plan"), dict) and x["plan"].get("stop") for x in xs)


def guard_buy_text(o: dict) -> list[str]:
    """계획(plan)이 하나도 없는데 '매수/편입' 긍정 문구가 있으면 '매수 보류 계획 없음' 으로 바꾼다. 바뀐 문구 목록 반환."""
    if has_plan(o):
        return []
    changed = []
    for parent, k in list(_texts(o)):
        s = parent[k]
        if affirmative_buy(s):
            parent[k] = BUY_RX.sub(lambda m: m.group(1) + " 보류 계획 없음", s)
            changed.append(s)
    if changed:
        log.warning("trade plan 없음 → 매수/편입 문구 %d건 보류 표기", len(changed))
    return changed


def kr_bars_local(code: str, n: int = 260) -> list[dict]:
    """data/kr_prices.parquet(조정) → chart 형식 일봉. 네트워크 없음. 없으면 []."""
    try:
        import polars as pl
        from .prices import load_kr
        px = load_kr().filter(pl.col("yf").str.starts_with(code + ".")).sort("date").tail(n)
        return [{"t": str(r["date"]), "o": r["open"], "h": r["high"], "l": r["low"], "c": r["close"], "v": r["volume"]} for r in px.iter_rows(named=True)]
    except Exception as e:  # noqa: BLE001
        log.info("kr_bars_local %s 실패: %s", code, e)
        return []


def duel_plan(code: str, hold_days: int = 1) -> dict | None:
    """타점 대결 규칙 픽(지수 ETF, 종가 진입·다음날 시가 청산)용 계획 — 확률은 crash_rebound 연구 승률(호출부 why)로, 여기선 가격선만."""
    p = build_plan(kr_bars_local(code), market="KR", hold_days=hold_days, code=code, calib=None)
    if p:
        p["prob"] = {"grade": "검증전", "note": "1일 보유 규칙 — 확률은 규칙 근거(why)의 과거 승률 참조"}
        p["ev_r"] = p["ev_pct"] = None
        p["line"] = plan_line(p)
    return p
