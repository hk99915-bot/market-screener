"""미장 운용회의 v2 섹션 — 국장(committee.py _v2_*)과 같은 틀을 미장 입력(S&P500·나스닥·미 금리·달러·VIX·peers_US)으로.

섹션(전부 순수 함수 + 파일 읽기 래퍼, 하나가 실패해도 나머지는 계속 — committee.build_us 가 호출):
- sector_rows    : 섹터 판정. 국장 체인 점수와 같은 구성(이익 신호 + 0.6×가격 추세) — 드라이버만 보고 가격을 무시하던 결함 수정(10/20).
- macro          : 레짐(S&P 200·50일선) · 밤사이 지표(σ) · S&P500 20일 수익률 요인 분해(금리·달러·VIX, 나스닥은 별도 줄).
- rotation       : 주도·소외(5D) · 순위 이동(20D→5D) · 드라이버 vs 가격 괴리 · 비중 확대/축소.
- hedges/asymmetry/premortem/bottom_line : 국장 로직 이식 (옵션 이론가 대신 VIX 내재 변동 — 미장 옵션 체인 미수집).
- track/scorecard/validation/idea_tracking : committee_us_hist.json 에 매 회의 기록 → 5·20거래일 뒤 S&P500 대비 초과수익·브라이어로 채점.
숫자는 모두 입력 파일(macro_series·bonds·peers_US·detail/US·studies/crash_rebound)에서 계산하고 출처·기준일을 문장에 붙인다.
"""
from __future__ import annotations

import json
import logging
import math
import statistics as st
from datetime import date, timedelta

from .config import REPORT_DIR

log = logging.getLogger(__name__)
HIST_US = REPORT_DIR / "committee_us_hist.json"

# 섹터 판정 — 국장 _sectors 와 같은 문턱(체인 점수 ≥0.3 확대 · ≤−0.15 축소)
OW, UW = 0.3, -0.15
PX_FULL = 0.14      # 20일 ±14% = 가격 성분 만점. 국장 프록시의 3개월 ±25% 를 √(20/63) 로 환산 (0.25×0.563≈0.14)
PX_W = 0.6          # 국장 drivers._proxy_signal 의 3개월 주가 가중 0.6 과 동일
HEDGE_BOOK = 0.10   # [가정: 'SH/PSQ 소량 헷지'의 소량 = 모델 북 10% 명목] — 국장 인버스 25% 보다 작게
BULL, BEAR, DEEP = 0.03, -0.03, -0.10   # 미장 시나리오 기준 (studies/crash_rebound spx_buckets20 thresholds 와 동일)


def _clip(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


# ───────────── 섹터 판정 (d) ─────────────
def sector_score(drv: float | None, r20: float | None) -> float | None:
    """국장 체인 점수와 같은 구성: 프록시 신호 = 평균(EPS 추정 변화, 매출/CAPEX, 0.6×주가 추세).
    미장 drv 는 이미 이익 신호(EPS·매출) 요약이라 2성분으로 세고, 가격은 1성분: (2×drv + 0.6×clip(r20/0.14)) / 3."""
    if drv is None:
        return None
    px = _clip((r20 or 0) / PX_FULL) if r20 is not None else None
    if px is None:
        return round(_clip(drv), 3)
    return round((2 * _clip(drv) + PX_W * px) / 3, 3)


def sector_stance(score: float | None) -> str:
    if score is None:
        return "중립"
    return "비중 확대" if score >= OW else "비중 축소" if score <= UW else "중립"


def sector_rows(peers: list[dict]) -> list[dict]:
    by: dict[str, list[dict]] = {}
    for r in peers:
        if r.get("r20") is not None and r.get("g"):
            by.setdefault(r["g"], []).append(r)
    secs = []
    for g, a in by.items():
        if len(a) < 5:
            continue
        w = [x.get("mc") or 1 for x in a]
        r20 = sum(wi * x["r20"] for wi, x in zip(w, a)) / sum(w)
        drv = st.mean([x["drv"] for x in a if x.get("drv") is not None] or [0])
        sc = sector_score(drv, r20)
        secs.append({"sector": g, "n": len(a), "r5": sum(wi * (x.get("r5") or 0) for wi, x in zip(w, a)) / sum(w),
                     "r20": r20, "drv": drv, "score": sc, "stance": sector_stance(sc)})
    secs.sort(key=lambda x: -(x["score"] or 0))
    return secs


SECTOR_NOTE = ("섹터 의견 = 점수 (2×드라이버 + 0.6×가격추세) ÷ 3, 가격추세 = 시총가중 20일 수익률 ÷ 14% (±1 상한). "
               "확대 ≥0.30 · 축소 ≤−0.15 — 국장 공급망 체인 점수(EPS 추정·매출·0.6×3개월 주가)와 같은 구성·문턱. 검증전.")


# ───────────── 시나리오 근거: 독립 사례 수 (e) ─────────────
def indep_range(n: int | None, n_all: int | None, h: int = 20) -> dict:
    """겹치는 20일 표본 n 개의 '독립 20일 블록' 수 범위. 하한 = ⌈n/h⌉(조건 충족일이 전부 연속일 때),
    상한 = min(n, ⌈전체 표본/h⌉)(서로 h일 이상 떨어진 날만 셀 때). 정확한 값은 study 의 n_indep(탐욕 비중첩)."""
    if not n:
        return {}
    lo = math.ceil(n / h)
    hi = min(n, math.ceil((n_all or n) / h))
    return {"lo": lo, "hi": max(lo, hi)}


def rng_txt(rg: dict) -> str:
    """{'lo','hi'} → '약 217~348' (같으면 '약 342')."""
    if not rg:
        return "—"
    return f"약 {rg['lo']}" if rg["lo"] == rg["hi"] else f"약 {rg['lo']}~{rg['hi']}"


def basis_fields(p: dict, n_all: int | None, h: int = 20) -> dict:
    n = p.get("n")
    out = {"n": n, "n_indep": p.get("n_indep"), "h": h}
    if p.get("n_indep") is None and n:
        out["n_indep_range"] = indep_range(n, n_all, h)
        rg = out["n_indep_range"]
        out["indep_note"] = (f"겹치는 {h}거래일 창 {n:,}회 = 독립 {h}일 블록 {rng_txt(rg)}개 (정확값은 다음 study 실행 때 n_indep — "
                             f"범위 하한 ⌈n/{h}⌉·상한 ⌈전체/{h}⌉). 오차 범위는 독립 블록 수로 읽을 것")
    elif n:
        out["indep_note"] = f"겹치는 {h}거래일 창 {n:,}회 중 서로 겹치지 않는 블록 {p['n_indep']}개 (탐욕 비중첩) — 오차 범위는 이 수로 읽을 것"
    return out


# ───────────── 매크로 (b) ─────────────
def _closes(ms: dict, key: str) -> dict[str, float]:
    return {str(r[0]): (r[4] if len(r) >= 6 else r[1]) for r in ms.get(key) or [] if (r[4] if len(r) >= 6 else r[1])}


def factor_decomp(ms: dict, h: int = 20, win: int = 250) -> dict | None:
    """S&P500 최근 h거래일 로그수익률 = Σ β_k × (요인 k 의 h일 변화) + 잔차.
    요인: 미 10년 금리 변화(bp) · 달러인덱스 로그수익률 · VIX 로그변화. β 는 그 직전 win 일 일간 OLS(절편 포함, 미래 정보 없음).
    나스닥은 S&P 와 상관이 너무 높아(다중공선성) 요인에서 빼고 '나스닥−S&P 격차' 줄로 따로 보인다."""
    try:
        import numpy as np
    except Exception:  # noqa: BLE001
        return None
    sp, rt, dx, vx, nq = (_closes(ms, k) for k in ("SPX", "US10Y", "DXY", "VIX", "NASDAQ"))
    days = sorted(d for d in sp if d in rt and d in dx and d in vx)
    if len(days) < h + 60:
        return None
    y = np.array([math.log(sp[days[i]] / sp[days[i - 1]]) for i in range(1, len(days))])
    X = np.array([[(rt[days[i]] - rt[days[i - 1]]) * 100, math.log(dx[days[i]] / dx[days[i - 1]]), math.log(vx[days[i]] / vx[days[i - 1]])]
                  for i in range(1, len(days))])
    est = slice(max(0, len(y) - h - win), len(y) - h)
    Xe = np.column_stack([np.ones(est.stop - est.start), X[est]])
    beta, *_ = np.linalg.lstsq(Xe, y[est], rcond=None)
    fit = Xe @ beta
    ss = float(((y[est] - y[est].mean()) ** 2).sum())
    r2 = 1 - float(((y[est] - fit) ** 2).sum()) / ss if ss else None
    tot = float(y[-h:].sum())
    names = [("금리", "미 10년 금리", "bp"), ("달러", "달러인덱스", "%"), ("VIX", "VIX", "%")]
    rows = []
    for j, (k, nm, unit) in enumerate(names):
        mv = float(X[-h:, j].sum())
        rows.append({"k": k, "name": nm, "move": mv if unit == "bp" else math.expm1(mv), "unit": unit, "beta": float(beta[j + 1]),
                     "contrib": float(beta[j + 1] * mv)})
    resid = tot - sum(r["contrib"] for r in rows)
    out = {"from": days[-h - 1], "to": days[-1], "h": h, "win": est.stop - est.start, "total": math.expm1(tot), "rows": rows,
           "resid": resid, "r2": round(r2, 2) if r2 is not None else None}
    nd = [d for d in days if d in nq]
    if len(nd) > h:
        nq_r = nq[nd[-1]] / nq[nd[-h - 1]] - 1
        sp_r = sp[nd[-1]] / sp[nd[-h - 1]] - 1
        a = np.array([math.log(nq[nd[i]] / nq[nd[i - 1]]) for i in range(1, len(nd))][-win:])
        b = np.array([math.log(sp[nd[i]] / sp[nd[i - 1]]) for i in range(1, len(nd))][-win:])
        out["nasdaq"] = {"r": nq_r, "gap": nq_r - sp_r, "corr": round(float(np.corrcoef(a, b)[0, 1]), 2)}
    out["line"] = (f"S&P500 {out['from'][5:]}→{out['to'][5:]} {out['total']*100:+.1f}% = "
                   + " · ".join(f"{r['k']} {r['contrib']*100:+.1f}%p" for r in rows) + f" · 기타(잔차) {resid*100:+.1f}%p"
                   + (f" (설명력 R² {out['r2']:.2f})" if out["r2"] is not None else ""))
    if out.get("nasdaq"):
        n_ = out["nasdaq"]
        out["nasdaq_line"] = (f"나스닥 {h}일 {n_['r']*100:+.1f}% — S&P500 대비 {n_['gap']*100:+.1f}%p "
                              f"({'기술·성장주가 끌어내림' if n_['gap'] < -0.01 else '기술·성장주가 이끎' if n_['gap'] > 0.01 else '격차 작음'}). "
                              f"일간 상관 {n_['corr']:.2f} 라 요인 분해에서는 제외(다중공선성)")
    out["note"] = (f"β = 직전 {out['win']}거래일 일간 OLS(절편 포함). 기여 = β × {h}일 누적 변화(로그). 금리는 bp, 달러·VIX 는 %. "
                   "잔차 = 실적·종목 요인 등 세 요인 밖. 인과가 아닌 동행 분해 — 검증전.")
    return out


def regime_us(mv: dict) -> dict:
    r = next((x for x in (mv or {}).get("rows", []) if x.get("key") == "SPX"), {})
    v50, v200, hi = r.get("vs50"), r.get("vs200"), r.get("from_hi")
    if v50 is None or v200 is None:
        return {}
    lab = "하락장" if (v200 < 0 and v50 < 0) else "회복" if (v200 < 0 or (hi is not None and hi <= -0.10)) else "상승"
    return {"label": lab, "line": f"레짐 {lab} — S&P500 200일선 대비 {v200*100:+.1f}%, 50일선 대비 {v50*100:+.1f}%"
            + (f", 52주 고점 대비 {hi*100:+.1f}%" if hi is not None else "") + f" ({str(r.get('date', ''))[5:]}, 규칙: 200·50일선 위치 — 국장과 동일)"}


def macro_us(ms: dict, bonds: dict, mv: dict, prev: dict | None, series_move) -> dict:
    rg = regime_us(mv)
    glob, changed = [], []
    spec = [("SPX", "S&P500", False), ("NASDAQ", "나스닥", False), ("RUT", "러셀2000", False), ("US10Y", "미 10년", True),
            ("DXY", "달러인덱스", False), ("VIX", "VIX", False), ("WTI", "WTI", False)]
    for key, nm, bp in spec:
        m = series_move(ms, key, bp)
        if not m:
            continue
        s = (f"{nm} {m['last']:.2f}% ({m['d1']:+.0f}bp)" if bp else f"{nm} {m['last']:.1f} ({m['d1']*100:+.1f}%)" if key == "VIX"
             else f"{nm} {m['last']:,.2f} ({m['d1']*100:+.1f}%)") + f" · {m['date'][5:]}"
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
                glob.append({"t": f"미 10Y−2Y {sp['v']*100:+.0f}bp (1주 {(sp.get('w1') or 0):+.0f}bp) · {str(sp.get('date', ''))[5:]}", "z": None, "big": False})
    if prev and rg.get("label"):
        pr = ((prev.get("macro") or {}).get("regime") or {}).get("label")
        if pr and pr != rg["label"]:
            changed.insert(0, f"레짐 전환 {pr}→{rg['label']}")
    dec = None
    try:
        dec = factor_decomp(ms)
    except Exception as e:  # noqa: BLE001
        log.info("미장 요인 분해 실패: %s", e)
    return {"regime": rg, "global": glob, "decomp": dec,
            "changed": changed or ["밤사이 큰 변화 없음 (모든 지표 하루 변화가 60일 평균 변동의 1.5배 미만)"],
            "note": "σ = 하루 변화 ÷ 60일 일간 변화 표준편차 (macro_series). 요인 분해는 decomp.note."}


# ───────────── 로테이션 (b) ─────────────
def rotation_us(secs: list[dict]) -> dict:
    th = [s for s in secs if s.get("r5") is not None and s.get("r20") is not None]
    lead = sorted(th, key=lambda t: -t["r5"])[:3]
    lag = sorted(th, key=lambda t: t["r5"])[:3]
    r20rank = {s["sector"]: i for i, s in enumerate(sorted(th, key=lambda t: -t["r20"]))}
    r5rank = {s["sector"]: i for i, s in enumerate(sorted(th, key=lambda t: -t["r5"]))}
    shift = sorted([{"sector": s, "from": r20rank[s] + 1, "to": r5rank[s] + 1, "d": r20rank[s] - r5rank[s]} for s in r5rank],
                   key=lambda x: -x["d"])
    into = [x for x in shift if x["d"] >= 3][:3]
    out_ = [x for x in reversed(shift) if x["d"] <= -3][:3]
    div = []
    for t in th:
        if (t.get("drv") or 0) >= 0.25 and t["r20"] <= -0.10:
            div.append({"sector": t["sector"], "kind": "드라이버 양호인데 과매도", "drv": t["drv"], "r20": t["r20"]})
        elif (t.get("drv") or 0) <= -0.05 and t["r20"] >= 0.05:
            div.append({"sector": t["sector"], "kind": "드라이버 없는 상승", "drv": t["drv"], "r20": t["r20"]})
    pick = lambda a: [{"sector": x["sector"], "score": x["score"], "drv": x["drv"], "r20": x["r20"]} for x in a]  # noqa: E731
    return {"lead": pick(lead), "lag": pick(lag), "into": into, "out": out_,
            "divergence": sorted(div, key=lambda d: -abs(d["drv"]))[:5],
            "overweight": pick([s for s in secs if s["stance"] == "비중 확대"][:3]),
            "underweight": pick(sorted([s for s in secs if s["stance"] == "비중 축소"], key=lambda s: s["score"] or 0)[:3]),
            "note": "주도/소외 = 섹터 시총가중 5일 수익률 (peers_US). 순환 = 20일 순위 → 5일 순위가 3계단 이상 바뀐 섹터. "
                    "괴리 = 드라이버 ≥0.25 인데 20일 −10% 이하 / 드라이버 ≤−0.05 인데 20일 +5% 이상 (국장과 같은 규칙). " + SECTOR_NOTE}


# ───────────── 헤지 · 비대칭 · 프리모템 (a) ─────────────
def implied_move(vix: float | None, days: int) -> float | None:
    """VIX(연율 %) → days 거래일 1σ 변동 = VIX/100 × √(days/252)."""
    return vix / 100 * (days / 252) ** 0.5 if vix else None


def hedges_us(k: dict, scen: list[dict], p: dict, bonds: dict) -> dict:
    bear = next((s for s in scen if s["name"].startswith("약세")), {})
    bull = next((s for s in scen if s["name"].startswith("강세")), {})
    H = []
    m20 = implied_move(k.get("vix"), 20)
    H.append({"name": f"SH(S&P500 인버스 1배)·PSQ(나스닥100 인버스 1배) 북 {HEDGE_BOOK*100:.0f}% 명목 (모델 북 전용 — 실계좌 적용 불가)",
              "cost": None, "cost_book": None,
              "line": (f"강세(20일 +3% 초과, 확률 {(bull.get('prob') or 0)*100:.0f}%)면 북 −{HEDGE_BOOK*3:.1f}%p 이상 기회비용 · "
                       f"약세 깊은 경로(−10% 미만, 확률 {(p.get('deep_bear') or 0)*100:.1f}%)면 북 +{HEDGE_BOOK*10:.1f}%p 이상 방어"
                       + (f" · VIX {k['vix']:.1f} 기준 20일 1σ ±{m20*100:.1f}% → 1σ 하락 시 북 +{HEDGE_BOOK*m20*100:.2f}%p" if m20 else "")),
              "when": "약세 시나리오 '반도체·고PER 축소, SH/PSQ 소량 헷지'의 실행형. 인버스는 일간 재조정이라 20일 넘게 들면 경로 손실 — 단기만"})
    shy = next((e for e in (bonds.get("etf") or []) if e.get("s") == "SHY"), None)
    if shy and shy.get("y") is not None:
        H.append({"name": "미 단기채(SHY)·현금 대기", "cost": None, "cost_book": None,
                  "line": f"SHY 수익률 {shy['y']:.2f}% · 듀레이션 {shy.get('dur')} ({str(shy.get('date', ''))[5:]}, bonds.json) — 대기 자금 비용 없음, 금리 +100bp 시 약 −{shy.get('dur') or 0:.1f}%",
                  "when": "신규 진입을 미루는 동안의 자리"})
    if k.get("low20"):
        H.append({"name": "신규 진입 중단선", "cost": None, "cost_book": None,
                  "line": f"S&P500 20일 저점 {k['low20']:,.0f} 종가 이탈 시 신규 진입 중단 — 비용은 반등 놓침뿐 (현재 대비 {(k['low20']/k['last']-1)*100:+.1f}%)",
                  "when": "약세 시나리오 전환 신호와 동일"})
    asym = None
    if k.get("last"):
        up = k["last"] / k["hi52"] - 1 if k.get("hi52") else None
        dn = k["low20"] / k["last"] - 1 if k.get("low20") else None
        asym = {"name": "S&P500 가격선 비대칭 · 시나리오 확률 비대칭",
                "up_room": -up if up is not None else None, "down_room": dn, "sigma20": m20,
                "p_up": bull.get("prob"), "p_down": bear.get("prob"), "p_deep": p.get("deep_bear"),
                "line": ((f"52주 고점까지 +{-up*100:.1f}%" if up is not None else "") + (f" vs 20일 저점까지 {dn*100:+.1f}%" if dn is not None else "")
                         + (f" (VIX 내재 20일 1σ ±{m20*100:.1f}%)" if m20 else "")
                         + f" · 강세 {(bull.get('prob') or 0)*100:.0f}% vs 약세 {(bear.get('prob') or 0)*100:.0f}% (그중 −10% 미만 {(p.get('deep_bear') or 0)*100:.1f}%)"),
                "cond": "인버스 ETF 는 선형이라 볼록성(작게 잃고 크게 버는 구조)이 없다. 볼록한 헤지(S&P 풋)는 미장 옵션 체인 미수집이라 이론가 산출 안 함 — 데이터 없음."}
    return {"hedges": H, "asymmetry": asym, "worst": bear.get("name"), "worst_p": bear.get("prob")}


def premortem_us(scen: list[dict], k: dict, p: dict) -> dict:
    """가장 확률 높은 시나리오(=회의 결론)가 틀린 경우 = 나머지 둘 중 확률 큰 쪽. 알아챌 신호·행동은 그 시나리오의 전환 신호·행동."""
    if not scen:
        return {}
    best = max(scen, key=lambda s: s.get("prob") or 0)
    alt = max([s for s in scen if s is not best], key=lambda s: s.get("prob") or 0)
    other = [s for s in scen if s is not best and s is not alt]
    cost = None
    if alt["name"].startswith("약세") and p.get("deep_bear") is not None:
        cost = f"1999~ 비슷한 상황에서 20일 −10% 미만 {p['deep_bear']*100:.1f}% — 헤지 없이 맞으면 북 손실이 시나리오 정의(−3%)보다 클 수 있음"
    elif alt["name"].startswith("강세"):
        cost = f"강세 정의 = 20일 +3% 초과 — 비중을 줄여 둔 만큼 놓침 (VIX 내재 20일 1σ ±{(implied_move(k.get('vix'), 20) or 0)*100:.1f}%)"
    return {"wrong": f"'{best['name'].split(' —')[0]}'이 틀린 경우: {alt['name']}", "p": alt.get("prob"),
            "tell": alt.get("trigger"), "cost": cost, "action": alt.get("action"),
            "other": f"{other[0]['name']} {(other[0].get('prob') or 0)*100:.0f}%" if other else None}


# ───────────── 결론 (a) ─────────────
def bottom_line_us(o: dict, k: dict, prev: dict | None, cal: list[dict], today: date, lights: dict, footer: str,
                   watch: set | None = None) -> dict:
    best = max(o.get("scenarios") or [{}], key=lambda s: s.get("prob") or 0)
    bn = str(best.get("name", "")).split(" —")[0]
    pb = None
    if prev and prev.get("scenarios"):
        pb = str(max(prev["scenarios"], key=lambda s: s.get("prob") or 0).get("name", "")).split(" —")[0]
    flip = bool(pb and bn and pb != bn)
    reg_flip = any(str(x).startswith("레짐 전환") for x in (o.get("macro") or {}).get("changed", []))
    prev_st = {x.get("sector"): x.get("stance") for x in (prev or {}).get("sectors") or []}
    st_chg = [f"{x['sector']} {prev_st[x['sector']]}→{x['stance']}" for x in o.get("sectors") or []
              if prev_st.get(x["sector"]) and prev_st[x["sector"]] != x["stance"]]
    m1 = implied_move(k.get("vix"), 1) or 0.01
    last = k.get("last")
    clock = []
    for e in cal:
        try:
            d = date.fromisoformat(e["date"])
        except Exception:  # noqa: BLE001
            continue
        if today <= d <= today + timedelta(days=1) and (e.get("market") == "US" or e.get("type") == "매크로") and e.get("imp", 1) >= 2:
            clock.append({"t": ("오늘 " if d == today else "내일 ") + e["date"][5:], "what": e["name"] + (" ★" if e.get("imp", 1) >= 3 else ""), "kind": "이벤트",
                          "hi": high_event(e, watch)})
    for lab, v in (("20일 저점(약세 전환선)", k.get("low20")), ("5일 고점", k.get("hi5")), ("52주 고점", k.get("hi52"))):
        if v and last:
            clock.append({"t": "가격선", "what": f"S&P500 {lab} {v:,.0f} (현재 대비 {(v/last-1)*100:+.1f}%)", "kind": "가격", "dist": v / last - 1})
    if k.get("vix") and last:
        clock.append({"t": "범위", "what": f"VIX 내재 하루 범위 S&P500 {last*(1-m1):,.0f}~{last*(1+m1):,.0f} (±{m1*100:.1f}%)", "kind": "가격"})
    near, big_ev = light_yellow(clock, m1)   # 10/20 보정: 범위 절반 이내·고중요 이벤트만 (섹터 의견 변경은 ① 줄에만)
    if flip or reg_flip:
        light = "red"
    elif big_ev or near:
        light = "yellow"
    else:
        light = "green"
    parts = []
    if prev:
        m = None
        try:
            import re as _re
            m = _re.search(r"S&P500 ([\d,]+)", (prev.get("head") or [""])[0])
        except Exception:  # noqa: BLE001
            pass
        if m and last:
            pv = float(m.group(1).replace(",", ""))
            parts.append(f"S&P500 {pv:,.0f}→{last:,.0f} ({(last/pv-1)*100:+.1f}%)")
        pp = {s["name"].split(" ")[0]: s.get("prob") for s in prev.get("scenarios") or []}
        for s0 in o.get("scenarios") or []:
            nm = s0["name"].split(" ")[0]
            if pp.get(nm) is not None and s0.get("prob") is not None and abs(s0["prob"] - pp[nm]) >= 0.01:
                parts.append(f"{nm} {pp[nm]*100:.0f}→{s0['prob']*100:.0f}%")
        parts.append(f"결론 {pb}→{bn}" if flip else f"결론 유지({bn})")
        if st_chg:
            parts.append("섹터 " + ", ".join(st_chg[:3]))
    l1 = (f"직전 회의({str((prev or {}).get('date', ''))[5:]}) 대비: " + " · ".join(parts)) if prev else "직전 회의 기록 없음 — 오늘부터 비교"
    evs = [f"{c['t']} {c['what']}" for c in clock if c["kind"] == "이벤트"][:3]
    l2 = "시계: " + (" · ".join(evs) + " / " if evs else "1일 안 미장 핵심 일정 없음 / ") + " · ".join(c["what"] for c in clock if c["t"] == "가격선")
    if light == "red":
        l3 = (f"할 일: {'결론 ' + str(pb) + '→' + bn if flip else '레짐 전환'} — 시나리오 '행동' 칸 재확인 후 섹터 비중 조정. "
              "하지 말 일: 전환 첫날 레버리지·추격")
    elif light == "yellow":
        why = ("고중요 일정 " + big_ev[0]["what"]) if big_ev else ("가격선 근접: " + near[0])
        l3 = f"할 일: 결론 유지 · 신규 행동 없음 — {why} 확인 후 재판정. 하지 말 일: 결과 전 방향 베팅 확대"
    else:
        l3 = "결론 유지 · 할 일 없음. 하지 말 일: 변화 없는 날의 매매(거래비용만 발생)"
    return {"light": light, "label": lights[light], "lines": [l1, l2, l3], "clock": clock, "stance": bn, "prev_stance": pb,
            "footer": footer,
            "rule": LIGHT_RULE}


# ───────────── 기록 · 채점 (c) ─────────────
def _load_hist() -> dict:
    try:
        return json.loads(HIST_US.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"rows": []}


def _ref_session(spx_days: list[str], meeting_date: str) -> str | None:
    """회의(한국 날짜) 시점에 확정된 마지막 미장 종가일 = 회의일보다 앞선 마지막 S&P500 거래일."""
    prior = [d for d in spx_days if d < meeting_date]
    return prior[-1] if prior else None


def record_row(o: dict, ref: str | None) -> dict:
    return {"date": o["date"], "ref": ref, "long": [x["s"] for x in (o.get("ideas") or {}).get("long", [])],
            "avoid": [x["s"] for x in (o.get("ideas") or {}).get("avoid", [])],
            "probs": {s["name"].split(" —")[0]: s.get("prob") for s in o.get("scenarios") or []},
            "stances": {x["sector"]: x["stance"] for x in o.get("sectors") or []}}


def backfill_from_archive(h: dict, spx_days: list[str]) -> int:
    """기록 파일이 없던 시기의 회의를 archive/committee_us 에서 복원. 반환: 추가 건수."""
    hd = REPORT_DIR / "archive" / "committee_us"
    have = {r["date"] for r in h["rows"]}
    n = 0
    for f in sorted(hd.glob("20*.json")):
        try:
            o = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if not o.get("date") or o["date"] in have or not o.get("scenarios"):
            continue
        row = record_row(o, _ref_session(spx_days, o["date"]))
        row["src"] = "archive"
        h["rows"].append(row)
        have.add(o["date"])
        n += 1
    h["rows"].sort(key=lambda r: r["date"])
    return n


def score_hist(rows: list[dict], spx: dict[str, float], px: dict[str, dict[str, float]]) -> dict:
    """rows: record_row 목록. spx: {날짜: 종가}. px: {티커: {날짜: 종가}}.
    5·20거래일 뒤 매수 후보·회피 목록의 S&P500 대비 초과수익, 20일 시나리오 브라이어(±3%·국장과 같은 3분류 무작위 0.667)."""
    days = sorted(spx)
    res = {"h5": [], "h20": [], "brier": []}
    pending = []
    for r in rows:
        ref = r.get("ref")
        if ref not in spx:
            pending.append({"date": r["date"], "why": "기준 종가 없음"})
            continue
        i = days.index(ref)
        for n in (5, 20):
            if i + n >= len(days):
                if n == 5:
                    pending.append({"date": r["date"], "ref": ref, "need": n, "have": len(days) - 1 - i})
                continue
            d1 = days[i + n]
            mk = spx[d1] / spx[ref] - 1
            ex = lambda tks: [px[t][d1] / px[t][ref] - 1 - mk for t in tks if t in px and ref in px[t] and d1 in px[t] and px[t][ref]]  # noqa: E731
            lg, av = ex(r.get("long") or []), ex(r.get("avoid") or [])
            res[f"h{n}"].append({"date": r["date"], "ref": ref, "to": d1, "spx": round(mk, 4),
                                 "long": round(st.mean(lg), 4) if lg else None, "n_long": len(lg),
                                 "avoid": round(st.mean(av), 4) if av else None, "n_avoid": len(av)})
            if n == 20:
                actual = "강세" if mk > BULL else "약세" if mk < BEAR else "기본"
                pr = r.get("probs") or {}
                res["brier"].append({"date": r["date"], "actual": actual,
                                     "brier": round(sum(((pr.get(s) or 0) - (1 if s == actual else 0)) ** 2 for s in ("강세", "기본", "약세")), 3)})
    summ = {}
    for n in ("h5", "h20"):
        v = [x for x in res[n] if x["long"] is not None]
        if v:
            av = [x["avoid"] for x in v if x["avoid"] is not None]
            summ[n] = {"n": len(v), "long_avg": round(st.mean(x["long"] for x in v), 4),
                       "long_hit": round(sum(1 for x in v if x["long"] > 0) / len(v), 2),
                       "avoid_avg": round(st.mean(av), 4) if av else None}
    if res["brier"]:
        summ["brier"] = {"n": len(res["brier"]), "avg": round(st.mean(x["brier"] for x in res["brier"]), 3), "naive": 0.667}
    return {"summary": summ, "recent": res["h5"][-5:], "h20": res["h20"][-5:], "pending": pending}


def track_lines(tr: dict, n_rows: int, first: str | None) -> list[str]:
    s = tr.get("summary") or {}
    L = []
    for n, lab in (("h5", "5거래일"), ("h20", "20거래일")):
        x = s.get(n)
        if x:
            L.append(f"매수 후보 {lab} S&P500 대비 {x['long_avg']*100:+.1f}% · 적중 {x['long_hit']*100:.0f}% (n={x['n']})"
                     + (f" · 회피 목록 {x['avoid_avg']*100:+.1f}%" if x.get("avoid_avg") is not None else ""))
    if s.get("brier"):
        L.append(f"시나리오 브라이어 {s['brier']['avg']} (무작위 {s['brier']['naive']}, 낮을수록 좋음, n={s['brier']['n']})")
    if not L:
        L.append(f"채점 전 — 기록 {n_rows}회(첫 회의 {first or '—'}), 5거래일 지난 회의 0건. 첫 채점은 첫 회의 기준 종가 + 5거래일 뒤")
    return L


def ideas_tracking(rows: list[dict], spx: dict[str, float], px: dict[str, dict[str, float]]) -> dict:
    """회의마다 낸 매수 후보·회피 종목을 처음 제안일 기준으로 추적 (같은 종목 재등장은 첫 제안만). 기준 = 그 회의의 마지막 미장 종가."""
    days = sorted(spx)
    seen, out = set(), []
    for r in rows:
        ref = r.get("ref")
        for side, tks in (("매수 후보", r.get("long") or []), ("회피", r.get("avoid") or [])):
            for t in tks:
                if (t, side) in seen:
                    continue
                seen.add((t, side))
                p = px.get(t) or {}
                row = {"date": r["date"], "ref": ref, "s": t, "side": side, "entry": p.get(ref)}
                if ref in spx and p.get(ref):
                    i = days.index(ref)
                    last = max([d for d in p if d >= ref and d in spx] or [ref])
                    held = days.index(last) - i
                    row.update({"days": held, "last_date": last, "ret": p[last] / p[ref] - 1, "spx": spx[last] / spx[ref] - 1})
                    row["excess"] = row["ret"] - row["spx"]
                    row["status"] = "20일 종료" if held >= 20 else "추적 중" if held > 0 else "대기(다음 종가부터)"
                else:
                    row["status"] = "가격 없음(detail/US 미수집)"
                out.append(row)
    live = [x for x in out if x.get("days")]
    good = lambda x: (x["excess"] > 0) if x["side"] == "매수 후보" else (x["excess"] < 0)  # noqa: E731
    summ = {"n": len(out), "tracked": len(live), "closed": sum(1 for x in out if x.get("days", 0) >= 20),
            "hit": round(sum(1 for x in live if good(x)) / len(live), 2) if live else None,
            "long_excess": round(st.mean(x["excess"] for x in live if x["side"] == "매수 후보"), 4) if any(x["side"] == "매수 후보" for x in live) else None}
    out.sort(key=lambda x: (x["date"], x["side"]), reverse=True)
    return {"summary": summ, "rows": out[:30],
            "note": "모의 추적 — 제안 회의의 마지막 미장 종가에 들어갔다고 보고 이후 종가 기준 S&P500 대비 초과수익. 적중 = 매수 후보는 초과>0, 회피는 초과<0. "
                    "비용·손절 미반영, 20거래일에 종료. 검증전."}


def load_px(tickers: set[str]) -> dict[str, dict[str, float]]:
    out = {}
    for t in tickers:
        try:
            d = json.loads((REPORT_DIR / "detail" / "US" / f"{t}.json").read_text(encoding="utf-8"))
            out[t] = {b["t"]: b["c"] for b in d.get("chart") or [] if b.get("t") and b.get("c")}
        except Exception:  # noqa: BLE001
            continue
    return out


def validation_us(basis: dict, tr: dict) -> list[dict]:
    s = tr.get("summary") or {}
    bri = s.get("brier")
    return [
        {"item": "시나리오 확률", "grade": "C" if bri and bri["n"] >= 20 and bri["avg"] < 0.667 else "검증전",
         "basis": f"1999~ S&P500 조건부 빈도 — 겹치는 표본 {basis.get('n') or 0:,}회"
                  + (f", 독립 20일 블록 {basis['n_indep']}개" if basis.get("n_indep") is not None else
                     f", 독립 20일 블록 {rng_txt(basis.get('n_indep_range') or {})}개" if basis.get("n_indep_range") else ""),
         "status": f"사후 브라이어 n={bri['n']} 평균 {bri['avg']}" if bri else "사후 채점 0건 (20거래일 지난 회의 없음)"},
        {"item": "섹터 의견", "grade": "검증전", "basis": "드라이버 + 가격추세 점수 (국장 체인 점수와 같은 구성)",
         "status": "섹터별 사후 성과 채점 미구현 — 기록(stances)만 누적"},
        {"item": "매수 후보·회피", "grade": "검증전", "basis": "드라이버 ≥0.4 + 20일 −3% 이하 / 드라이버 ≤−0.2 + 20일 +5% 이상",
         "status": (f"5일 채점 n={s['h5']['n']}" if s.get("h5") else "5일 채점 0건")},
    ]


def build_track(o: dict, ms: dict) -> dict:
    """기록(오늘 판 추가 + 없던 과거 판 archive 복원) → 채점 → track·scorecard·validation·idea_tracking."""
    spx = _closes(ms, "SPX")
    days = sorted(spx)
    h = _load_hist()
    n_back = backfill_from_archive(h, days)
    row = record_row(o, _ref_session(days, o["date"]))
    h["rows"] = [r for r in h["rows"] if r["date"] != o["date"]] + [row]
    h["rows"].sort(key=lambda r: r["date"])
    h["rows"] = h["rows"][-400:]
    HIST_US.write_text(json.dumps(h, ensure_ascii=False), encoding="utf-8")
    tks = {t for r in h["rows"] for t in (r.get("long") or []) + (r.get("avoid") or [])}
    px = load_px(tks)
    tr = score_hist(h["rows"], spx, px)
    first = h["rows"][0]["date"] if h["rows"] else None
    tr["lines"] = track_lines(tr, len(h["rows"]), first)
    sc = {"meetings": len(h["rows"]), "first": first, "backfilled": n_back,
          "scored_h5": (tr["summary"].get("h5") or {}).get("n", 0), "scored_h20": (tr["summary"].get("h20") or {}).get("n", 0),
          "pending": len(tr.get("pending") or []),
          "note": "기록 = reports/committee_us_hist.json (회의일·기준 종가일·후보·확률·섹터 의견). 같은 날 여러 번 돌면 마지막 판만."}
    return {"track": tr, "scorecard": sc, "validation": validation_us(o.get("scenario_basis") or {}, tr),
            "idea_tracking": ideas_tracking(h["rows"], spx, px)}


# ───────────── 신호등 보정 (10/20 dev: light-calibration) ─────────────
# 변동성 큰 장에서 '이벤트 있음 OR 가격선이 내재 1일 범위 안' 이 거의 매일 참 → 🟡 고착. 국장 _v2_bottom_line 과 공용.
# 🟡 = 가격선이 내재 1일 범위의 NEAR_BAND 배 이내 · 또는 고중요 이벤트(FOMC·CPI·고용·관심 종목 실적). 일반 지표 발표는 시계(clock)에만.
NEAR_BAND = 0.5
HI_EVENT_KEYS = ("FOMC", "CPI", "고용", "비농업", "NONFARM", "PAYROLL")


def high_event(e: dict, watch: set | None = None) -> bool:
    """고중요 이벤트: 이름에 FOMC·CPI·고용(비농업) — 또는 실적이면 관심 종목(watch: 운용회의 아이디어·후보) 일 때만."""
    if e.get("type") == "실적":
        return str(e.get("ticker") or "") in (watch or set())
    nm = str(e.get("name") or "").upper()
    return any(k in nm for k in HI_EVENT_KEYS)


def light_yellow(clock: list[dict], band: float) -> tuple[list[str], list[dict]]:
    """(가까운 가격선 문구들, 고중요 이벤트들). clock 이벤트는 'hi' 플래그를 미리 달아 둔다."""
    near = [c["what"] for c in clock if c.get("dist") is not None and 0 < abs(c["dist"]) <= NEAR_BAND * band]
    hi = [c for c in clock if c.get("kind") == "이벤트" and c.get("hi")]
    return near, hi


LIGHT_RULE = ("🔴 판정·결론 또는 레짐 전환(국장은 신규 실행 후보 포함) · 🟡 가격선이 내재 1일 범위의 절반 이내, 또는 고중요 이벤트"
              "(FOMC·CPI·고용·관심 종목 실적) · 🟢 그 외 — 일반 지표 발표는 시계에만 표기")


# ───────────── 미장 진입 후보 ideas_top (10/20 dev: us-entry-ideas) ─────────────
_GR_ORDER = ["A", "B", "C", "검증전", "F"]


def _best_grade(sigs: list[str], grades: dict) -> str:
    gs = [grades.get(s) or "검증전" for s in sigs] or ["검증전"]
    return min(gs, key=lambda g: _GR_ORDER.index(g) if g in _GR_ORDER else 3)


def ideas_top_us(o: dict, peers: list[dict], acc: dict, cal: list[dict], today: date, risk_box, bars_fn,
                 gate: str, gate_why: str, lens_grade: str = "검증전", grade_w: dict | None = None) -> dict:
    """국장 _v2_ideas_top 과 같은 형식. 원천 = us_accum 매집 흔적(연구 등급 가중) + 이익 신호(drv) + 추세(50일선).
    risk_box(code) → 리스크 박스(손절 max(20일 저점, 종가−2×ATR14), 목표 2R) · bars_fn(code) → chart.
    gate = 시장 진입 게이트('pass'|'fail', S&P 레짐 하락장이면 fail). 불통과·추세 미확인·촉매 없음이면 '대기'."""
    GW = grade_w or {"A": 1.0, "B": 0.8, "C": 0.6, "검증전": 0.3, "F": 0.0}
    meta = {r["s"]: r for r in peers if r.get("s")}
    S: dict = {}

    def add(code, key, label, side, grade):
        if code not in meta:
            return
        S.setdefault(code, []).append({"k": key, "label": label, "side": side, "grade": grade})
    hits = (acc.get("hits") or []) if acc.get("status") == "ok" else []
    grades = acc.get("grades") or {}
    for h in hits:
        sg = [s for s in h.get("signals") or []]
        add(h.get("symbol"), "us_accum", f"매집 흔적 {'·'.join(sg)} ({str(h.get('date', ''))[5:]})", "agree", _best_grade(sg, grades))
    for r in peers:
        d = r.get("drv")
        if d is None:
            continue
        if d >= 0.2:
            add(r["s"], "us_drv", f"이익 신호 {d:+.2f}", "agree", lens_grade)
        elif d <= -0.2:
            add(r["s"], "us_drv", f"이익 신호 {d:+.2f}", "oppose", lens_grade)
    has_acc = {c for c, ss in S.items() if any(s["k"] == "us_accum" for s in ss)}
    drv = {r["s"]: (r.get("drv") or 0) for r in peers if r.get("s")}
    # 후보 풀: 매집 흔적이 뜬 종목 ∪ 이익 신호 강한 종목(drv ≥ 0.4, 기존 매수 후보 문턱과 같음)
    pool = [c for c, ss in S.items() if any(s["side"] == "agree" for s in ss) and (c in has_acc or drv.get(c, 0) >= 0.4)]
    rows = []
    for code in pool:
        ch = bars_fn(code) or []
        last = ch[-1] if ch else {}
        s50 = last.get("s50")
        trend_ok = bool(s50 and last.get("c") and last["c"] >= s50)
        if s50 and last.get("c"):
            S[code].append({"k": "us_trend", "label": f"종가 {'≥' if trend_ok else '<'} 50일선 ({(last['c']/s50-1)*100:+.1f}%)",
                            "side": "agree" if trend_ok else "oppose", "grade": "검증전"})
        sc = 0.0
        for s in S[code]:
            s["w"] = round(GW.get(s["grade"], 0.3) * (1 if s["side"] == "agree" else -1), 3)
            sc += s["w"]
        if sc > 0:
            rows.append((sc, code, trend_ok, last.get("t")))
    # 동점 정렬: 매집 흔적 있음 → 이익 신호 큰 순 (F 등급이라 점수엔 0 이지만 '등급 상위 관찰' 우선)
    rows.sort(key=lambda x: (-x[0], x[1] not in has_acc, -drv.get(x[1], 0), x[1]))
    out, cands = [], []
    for sc, code, trend_ok, ref in rows:
        if len(out) + len(cands) >= 5:
            break
        rb = risk_box(code)
        if not rb or rb["skip"]:
            continue
        ss = S[code]
        strong = any(s["side"] == "agree" and GW.get(s["grade"], 0) >= 0.6 for s in ss)
        conv = "높음" if sc >= 1.2 else "중간" if sc >= 0.6 else "낮음"
        if conv == "높음" and not strong:
            conv = "중간"
        cm = {"높음": 1.0, "중간": 0.7, "낮음": 0.4}[conv]
        payoff = (rb["target"] - rb["close"]) / (rb["close"] - rb["stop"])
        size = min(cm * (payoff / 2) * 0.01 / rb["stop_pct"], 0.15)
        cat = [{"date": e["date"], "what": "실적 발표" + (" (회사 확정)" if e.get("confirmed") else " (예정일 추정)")}
               for e in cal if e.get("type") == "실적" and str(e.get("ticker")) == code
               and str(today) <= e.get("date", "") <= str(today + timedelta(days=14))]
        status = ("대기 — 촉매 없음" if not cat else "대기 — 확신 낮음" if conv == "낮음"
                  else "대기 — 진입 게이트 불통과" if gate == "fail" else "대기 — 추세 미확인(50일선 아래)" if not trend_ok
                  else "실행 후보")
        m = meta[code]
        row = {"s": code, "n": m.get("n"), "g": m.get("g"), "side": "롱", "conv": conv, "score": round(sc, 2), "size": size,
               "entry": rb["close"], "entry_max": rb["close"] * (1 + 0.5 * rb["atr_pct"]), "stop": rb["stop"], "stop_pct": rb["stop_pct"],
               "target": rb["target"], "payoff": payoff, "atr_pct": rb["atr_pct"], "catalyst": cat[:3], "status": status, "ref": ref,
               "kill": [f"종가 {rb['stop']:,.2f} 하회 (손절, 협상 대상 아님)", "동의 원천이 반대로 바뀜 (이익 신호 −0.2 이하·50일선 이탈)",
                        "20거래일 안 +1R 미도달 (시간 손절)"],
               "sources": [{k: s[k] for k in ("k", "label", "side", "grade", "w")} for s in ss]}
        (out if len(out) < 3 else cands).append(row)
    gr_note = ("매집 흔적 연구 등급 " + ", ".join(sorted({f'{k}:{v}' for k, v in grades.items()})) if grades else "매집 흔적 등급 미확인")
    return {"items": out, "candidates": cands, "entry_gate": gate, "entry_gate_why": gate_why, "market": "US",
            "formula": "확신 점수 = Σ 동의 원천 가중 − Σ 반대 (가중 = 등급 A1·B.8·C.6·검증전.3·F0). 원천 = 매집 흔적(us_accum, 신호별 연구 등급) · "
                       "이익 신호(peers_US drv ±0.2) · 추세(종가 vs 50일선). 높음 ≥1.2·중간 ≥0.6·낮음 >0, C 이상 동의 없으면 상한 중간. "
                       "진입·손절·목표 = 리스크 박스(손절 max(20일 저점, 종가−2×ATR14), 목표 2R), 사이즈 = 확신도 × 손익비/2 × 1% ÷ 손절폭(상한 15%). "
                       "실행 = 촉매(14일 안 실적) + 확신 중간 이상 + 시장 게이트 통과 + 종가 ≥ 50일선. 검증전.",
            "grade_note": gr_note + " — F 는 가중 0(목록에는 근거로 표시)",
            "empty": None if out else "숫자 근거 있는 미장 후보 없음 (동의 원천 > 반대이고 손절폭 15% 이하인 후보 없음) — 대기"}
