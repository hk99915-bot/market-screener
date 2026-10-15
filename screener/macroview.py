"""매크로 해설 — 지표별 '지금 어떤 상태이고 한국 주식에 무슨 뜻인지' + 종합 매크로 바람 점수.

입력: reports/macro_series.json (2년 일봉). 출력: reports/macro_view.json, report/텔레그램용 문장.
점수(−1~+1)는 '한국 주식 전체에 대한 매크로 바람'. 종목별 영향은 drivers.py 의 민감도로 따로 본다.
"""
from __future__ import annotations

import json
import logging
import statistics as st

from .config import REPORT_DIR

log = logging.getLogger(__name__)
RATE = {"US10Y"}
INDEX = {"KOSPI", "KOSDAQ", "SPX", "NASDAQ", "RUT"}
NAME = {"KOSPI": "코스피", "KOSDAQ": "코스닥", "SPX": "S&P500", "NASDAQ": "나스닥", "RUT": "러셀2000(미 중소형)",
        "VIX": "VIX(미 변동성)", "US10Y": "미 10년 금리", "DXY": "달러인덱스", "USDKRW": "원/달러", "USDJPY": "엔/달러",
        "WTI": "WTI 유가", "GOLD": "금", "BTC": "비트코인"}
WHAT = {
    "KOSPI": "한국 대형주. 반도체 2개 종목 비중이 커서 메모리 업황과 외국인 수급에 크게 흔들린다.",
    "KOSDAQ": "한국 중소형·성장주. 개인 비중이 높고 금리·바이오·2차전지 심리에 민감.",
    "SPX": "미국 대형주. 한국 장은 전날 밤 미국 장을 따라가는 경향이 강하다.",
    "NASDAQ": "미국 기술주. 한국 반도체·IT 와 상관이 가장 높다.",
    "RUT": "미국 중소형주. 경기·신용 여건에 민감 → 위험 선호의 바로미터.",
    "VIX": "S&P500 옵션으로 본 향후 30일 예상 변동성. 15 이하 안정, 20 이상 경계, 30 이상 공포.",
    "US10Y": "세계 자산 가격의 할인율. 오르면 성장주 밸류에이션이 눌리고 신흥국에서 자금이 빠지기 쉽다.",
    "DXY": "주요 6개 통화 대비 달러. 달러 강세는 신흥국 자금 유출·원화 약세로 이어지기 쉽다.",
    "USDKRW": "오르면 원화 약세. 수출기업 원화 이익엔 +, 외국인에겐 환차손이라 매도 압력.",
    "USDJPY": "오르면 엔화 약세. 일본과 경쟁하는 자동차·기계·조선·철강엔 가격 경쟁 부담.",
    "WTI": "국제 유가. 오르면 정유·조선(해양) +, 항공·화학·운송 −, 물가→금리 경로로 시장 전체엔 부담.",
    "GOLD": "실질금리 하락·위험 회피·달러 불신 때 오른다. 주식과 같이 빠지면 현금화(디레버리징) 신호.",
    "BTC": "가장 투기적인 위험자산. 유동성·위험 선호의 선행 지표로 쓰인다.",
}


def _stats(rows: list[list]) -> dict | None:
    c = [r[4] if len(r) >= 6 else r[1] for r in rows if (r[4] if len(r) >= 6 else r[1]) is not None]
    if len(c) < 60:
        return None
    last = c[-1]

    def ch(n):
        return last / c[-1 - n] - 1 if len(c) > n and c[-1 - n] else None

    def dif(n):
        return last - c[-1 - n] if len(c) > n else None
    s50 = st.mean(c[-50:])
    s200 = st.mean(c[-200:]) if len(c) >= 200 else None
    y = c[-250:]
    hi, lo = max(y), min(y)
    # 20일 변화의 2년 분포 대비 z (이번 움직임이 얼마나 이례적인가)
    ch20s = [c[i] / c[i - 20] - 1 for i in range(20, len(c)) if c[i - 20]]
    z20 = None
    if len(ch20s) > 60 and ch(20) is not None:
        mu, sd = st.mean(ch20s), st.pstdev(ch20s)
        z20 = (ch(20) - mu) / sd if sd else None
    return {"last": last, "chg1": ch(1), "chg5": ch(5), "chg20": ch(20), "chg60": ch(60), "d1": dif(1), "d20": dif(20),
            "vs50": last / s50 - 1, "vs200": (last / s200 - 1) if s200 else None, "hi52": hi, "lo52": lo,
            "from_hi": last / hi - 1, "pct_1y": (sum(1 for v in y if v <= last) / len(y)), "z20": z20, "date": rows[-1][0]}


def _p(x, d=1):
    return "—" if x is None else f"{x*100:+.{d}f}%"


def explain(key: str, s: dict, all_: dict) -> tuple[str, float | None]:
    """(상태 해설, 한국 주식 바람 −1~+1 또는 None=점수 제외)"""
    z = s.get("z20")
    unusual = f" (최근 2년 20일 변화 중 {'이례적으로 큰 하락' if z < -2 else '이례적으로 큰 상승' if z > 2 else '큰 편'})" if z is not None and abs(z) >= 1.5 else ""
    if key in INDEX:
        dd = s["from_hi"]
        st_ = ("약세장(고점 −20% 이상)" if dd <= -0.2 else "조정(고점 −10% 이상)" if dd <= -0.1 else "고점 부근" if dd > -0.03 else "소폭 조정")
        trend = ("200일선 아래 — 장기 추세 훼손" if s.get("vs200") is not None and s["vs200"] < 0 else
                 "50일선 아래 — 중기 약세" if s["vs50"] < 0 else "50일선 위 — 추세 유지")
        txt = f"52주 고점 대비 {_p(dd)} → {st_}. 20일 {_p(s['chg20'])}{unusual}. {trend}."
        if key == "KOSPI" and "SPX" in all_:
            gap = (s["chg20"] or 0) - (all_["SPX"]["chg20"] or 0)
            if gap < -0.08:
                txt += f" 같은 기간 S&P500 {_p(all_['SPX']['chg20'])} → 한국만 {abs(gap)*100:.0f}%p 더 빠짐: 미국발이 아니라 한국 고유 요인(반도체 쏠림·외국인 매도) 쪽."
            elif gap > 0.08:
                txt += f" 같은 기간 S&P500 {_p(all_['SPX']['chg20'])} → 한국이 {gap*100:.0f}%p 강함."
        if key in ("SPX", "NASDAQ"):
            sc = max(min((s["chg20"] or 0) / 0.06, 1), -1) * 0.6 + (0.4 if s["vs50"] > 0 else -0.4)
            return txt, round(max(min(sc, 1), -1), 2)
        if key == "RUT":
            return txt + " 중소형이 대형보다 약하면 신용·경기 우려가 깔려 있다는 뜻.", round(max(min((s["chg20"] or 0) / 0.08, 1), -1) * 0.6, 2)
        return txt, None   # 한국 지수 자체는 매크로 점수에서 제외 (결과이지 원인이 아님)
    if key == "VIX":
        v = s["last"]
        lvl = "공포 구간" if v >= 30 else "경계 구간" if v >= 20 else "보통" if v >= 15 else "안정(낙관 과다일 수도)"
        sc = -1 if v >= 30 else -0.6 if v >= 25 else -0.3 if v >= 20 else 0.2 if v < 15 else 0
        if (s["chg5"] or 0) > 0.25:
            sc -= 0.3
        return f"{v:.1f} = {lvl}. 5일 {_p(s['chg5'],0)}. 1년 중 상위 {100 - s['pct_1y']*100:.0f}% 수준.", round(max(sc, -1), 2)
    if key == "US10Y":
        bp20 = (s["d20"] or 0) * 100
        bp1 = (s["d1"] or 0) * 100
        lvl = "긴축적(5% 이상)" if s["last"] >= 5 else "높은 편(4.5~5%)" if s["last"] >= 4.5 else "중립권"
        sc = max(min(-bp20 / 40, 1), -1) * 0.7 + (-0.3 if s["last"] >= 5 else 0)
        return (f"{s['last']:.2f}% = {lvl}. 1일 {bp1:+.0f}bp, 20일 {bp20:+.0f}bp. 1년 중 {s['pct_1y']*100:.0f}번째 백분위."
                + (" 금리가 빠르게 오르는 중 → 성장주·고PER 주식과 신흥국에 역풍." if bp20 > 20 else
                   " 금리 하락 → 밸류에이션 부담 완화." if bp20 < -20 else "")), round(max(min(sc, 1), -1), 2)
    if key == "DXY":
        sc = max(min(-(s["chg20"] or 0) / 0.03, 1), -1) * 0.6
        return (f"20일 {_p(s['chg20'])}{unusual}. " + ("달러 강세 → 신흥국 자금 이탈 압력." if (s["chg20"] or 0) > 0.015 else
                                                    "달러 약세 → 신흥국 자금 유입에 우호적." if (s["chg20"] or 0) < -0.015 else "방향성 약함.")), round(sc, 2)
    if key == "USDKRW":
        c20 = s["chg20"] or 0
        sc = max(min(-c20 / 0.03, 1), -1) * 0.6
        side = ("원화 약세 진행: 수출주 원화 이익엔 +지만 외국인 환차손 → 매도 압력이 더 크게 작용하는 경우가 많다." if c20 > 0.015 else
                "원화 강세: 외국인 수급엔 우호적, 수출주 이익엔 −(달러 매출 환산 감소)." if c20 < -0.015 else "환율 안정.")
        return f"{s['last']:,.0f}원. 20일 {_p(c20)}{unusual}. {side}", round(sc, 2)
    if key == "USDJPY":
        c20 = s["chg20"] or 0
        return (f"{s['last']:.1f}엔. 20일 {_p(c20)}. " + ("엔 약세 → 일본 경쟁 업종(자동차·기계·철강·조선) 가격 경쟁 부담." if c20 > 0.02 else
                                                       "엔 강세 → 한국 경쟁 업종에 상대적 우호." if c20 < -0.02 else "큰 변화 없음.")), round(max(min(-c20 / 0.05, 1), -1) * 0.2, 2)
    if key == "WTI":
        c20 = s["chg20"] or 0
        return (f"${s['last']:.1f}. 20일 {_p(c20)}, 50일선 대비 {_p(s['vs50'])}. "
                + ("유가 급등 → 물가·금리 부담, 정유·조선 +, 항공·화학 −." if c20 > 0.1 else
                   "유가 급락 → 물가 부담 완화, 정유 재고손실·항공 +." if c20 < -0.1 else "업종 간 영향 엇갈림, 시장 전체 영향은 제한적.")), round(max(min(-c20 / 0.2, 1), -1) * 0.3, 2)
    if key == "GOLD":
        c20 = s["chg20"] or 0
        both = c20 < -0.03 and all_.get("SPX", {}).get("chg20", 0) < -0.03
        return (f"${s['last']:,.0f}. 20일 {_p(c20)}. " + ("금과 주식이 같이 하락 → 현금 확보(디레버리징) 국면 신호." if both else
                                                     "금 강세 → 위험 회피·실질금리 하락 기대." if c20 > 0.04 else "특이점 없음.")), (-0.4 if both else None)
    if key == "BTC":
        c20 = s["chg20"] or 0
        return f"20일 {_p(c20)}. " + ("투기 자산 약세 → 위험 선호 위축." if c20 < -0.1 else "투기 자산 강세 → 유동성 우호." if c20 > 0.1 else "중립."), round(max(min(c20 / 0.2, 1), -1) * 0.3, 2)
    return "", None


W = {"SPX": 1.0, "NASDAQ": 1.0, "RUT": 0.5, "VIX": 1.0, "US10Y": 1.0, "DXY": 0.7, "USDKRW": 1.0, "USDJPY": 0.3, "WTI": 0.5, "GOLD": 0.4, "BTC": 0.3}
ORDER = ["KOSPI", "KOSDAQ", "SPX", "NASDAQ", "RUT", "VIX", "US10Y", "DXY", "USDKRW", "USDJPY", "WTI", "GOLD", "BTC"]


def build() -> dict:
    try:
        ms = json.loads((REPORT_DIR / "macro_series.json").read_text(encoding="utf-8"))["series"]
    except Exception as e:  # noqa: BLE001
        log.warning("매크로 시계열 없음: %s", e)
        return {}
    stats = {k: v for k, v in ((k, _stats(r)) for k, r in ms.items()) if v}
    rows, num, den = [], 0.0, 0.0
    for k in ORDER:
        s = stats.get(k)
        if not s:
            continue
        txt, sc = explain(k, s, stats)
        rows.append({"key": k, "name": NAME.get(k, k), "what": WHAT.get(k, ""), "state": txt, "impact": sc,
                     **{f: (round(s[f], 5) if isinstance(s[f], float) else s[f]) for f in
                        ("last", "chg1", "chg5", "chg20", "vs50", "vs200", "from_hi", "pct_1y", "z20", "d1", "d20", "date")}})
        if sc is not None:
            num += W.get(k, 0.5) * sc
            den += W.get(k, 0.5)
    score = num / den if den else None
    drivers = sorted([r for r in rows if r["impact"] is not None], key=lambda r: abs(r["impact"]) * W.get(r["key"], 0.5), reverse=True)[:3]
    label = (None if score is None else "강한 역풍" if score <= -0.4 else "역풍" if score <= -0.15 else
             "강한 순풍" if score >= 0.4 else "순풍" if score >= 0.15 else "중립")
    summary = (f"매크로 바람 {label} ({score:+.2f}) — 주된 요인: "
               + ", ".join(f"{r['name']} {'+' if r['impact'] > 0 else '−'}" for r in drivers)) if score is not None else ""
    kr = stats.get("KOSPI")
    us = stats.get("SPX")
    if kr and us and score is not None:
        gap = (kr["chg20"] or 0) - (us["chg20"] or 0)
        if gap < -0.08 and score > -0.15:
            summary += " · 글로벌 매크로는 심하지 않은데 한국만 크게 빠짐 → 원인은 국내·업종(반도체) 쪽, 매크로 반전만으론 회복 근거 부족"
        elif gap < -0.08:
            summary += " · 매크로 역풍 + 한국 초과 하락이 겹침"
    out = {"asof": max((r["date"] for r in rows), default=None), "score": round(score, 2) if score is not None else None,
           "label": label, "summary": summary, "rows": rows}
    (REPORT_DIR / "macro_view.json").write_text(json.dumps(out, ensure_ascii=False, default=str), encoding="utf-8")
    try:
        _track(out, stats)
    except Exception as e:  # noqa: BLE001
        log.warning("매크로 점수 기록 실패: %s", e)
    log.info("매크로 해설: %s", summary)
    return out


def _track(out: dict, stats: dict) -> None:
    """매크로 바람 점수를 날짜별로 기록하고, 이후 코스피 5·20일 수익률과의 상관으로 채점 (시계열 시그널)."""
    p = REPORT_DIR / "macro_hist.json"
    h = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"rows": []}
    d = out.get("asof")
    if d and out.get("score") is not None:
        h["rows"] = [r for r in h["rows"] if r["date"] != d] + [{"date": d, "score": out["score"]}]
        h["rows"].sort(key=lambda r: r["date"])
    try:
        ser = json.loads((REPORT_DIR / "macro_series.json").read_text(encoding="utf-8"))["series"]["KOSPI"]
        c = {r[0]: (r[4] if len(r) >= 6 else r[1]) for r in ser}
        ds = sorted(c)
        res = {}
        for n in (5, 20):
            xs, ys = [], []
            for r in h["rows"]:
                if r["date"] in c:
                    i = ds.index(r["date"])
                    if i + n < len(ds):
                        xs.append(r["score"])
                        ys.append(c[ds[i + n]] / c[r["date"]] - 1)
            if len(xs) >= 10:
                mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
                cov = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
                vx = sum((a - mx) ** 2 for a in xs) ** 0.5
                vy = sum((b - my) ** 2 for b in ys) ** 0.5
                res[f"h{n}"] = {"corr": round(cov / (vx * vy), 3) if vx and vy else None, "n": len(xs), "n_eff": round(len(xs) / n, 1)}
        h["score"] = res
        h["verdict"] = ("검증 중 (표본 부족)" if not res or max(v["n_eff"] for v in res.values()) < 8 else
                        "유효" if (res.get("h20") or res.get("h5"))["corr"] and (res.get("h20") or res.get("h5"))["corr"] > 0.2 else "효과 불분명")
    except Exception:  # noqa: BLE001
        pass
    p.write_text(json.dumps(h, ensure_ascii=False), encoding="utf-8")
