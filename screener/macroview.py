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
RATE = {"US10Y", "JGB10Y"}
INDEX = {"KOSPI", "KOSDAQ", "SPX", "NASDAQ", "RUT", "NIKKEI", "TOPIX"}
NAME = {"KOSPI": "코스피", "KOSDAQ": "코스닥", "SPX": "S&P500", "NASDAQ": "나스닥", "RUT": "러셀2000(미 중소형)",
        "VIX": "VIX(미 변동성)", "US10Y": "미 10년 금리", "DXY": "달러인덱스", "USDKRW": "원/달러", "USDJPY": "엔/달러",
        "WTI": "WTI 유가", "GOLD": "금", "BTC": "비트코인", "NIKKEI": "닛케이225", "TOPIX": "TOPIX(일본 전체·ETF 1306 가격)", "JGB10Y": "일본 10년 금리"}
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
    "NIKKEI": "일본 대형 225종목(가격가중 → 도쿄일렉트론·어드반테스트 같은 반도체 비중 큼). 서울과 같은 9시 개장이라 한국 반도체와 실시간으로 같이 움직인다.",
    "TOPIX": "도쿄 프라임 전 종목 시가총액 가중. 닛케이보다 은행·내수 비중이 커서 '일본 경제 전체' 온도계.",
    "JGB10Y": "일본 10년 국채 금리. 오르면 일본 자금이 해외에서 본국으로 돌아갈 유인 → 엔 강세·세계 채권/주식 매도 압력.",
}



# 바람 라벨 (10/26 겸이 "맨날 중립이야" · 보드 dotplot-neutral-rule): 작은 점수도 부호를 버리지 않는다.
# |s| < 0.05 만 '중립'(가중 평균 점수의 일간 흔들림 수준으로 잡은 표시 구간), 0.05~0.15 = 약한 역풍/순풍,
# 0.15~0.4 = 역풍/순풍, ≥ 0.4 = 강한. 임계값은 표시 로직이며 검증전 — 매크로·퀀트 검수 대기 (docs/desk_kb/dev.md).
WIND_NEUTRAL = 0.05


def wind_label(score):
    if score is None:
        return None
    if score <= -0.4:
        return "강한 역풍"
    if score <= -0.15:
        return "역풍"
    if score >= 0.4:
        return "강한 순풍"
    if score >= 0.15:
        return "순풍"
    if score <= -WIND_NEUTRAL:
        return "약한 역풍"
    if score >= WIND_NEUTRAL:
        return "약한 순풍"
    return "중립"

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
    if key == "JGB10Y":   # 점수 제외 — 표시·해설만 (japan.py 가 재무성 CSV 로 채움)
        bp20 = (s["d20"] or 0) * 100
        return (f"{s['last']:.2f}%. 1일 {(s['d1'] or 0)*100:+.0f}bp, 20일 {bp20:+.0f}bp."
                + (" 일본 금리 급등 → 엔 강세·일본 자금 본국 회귀 압력 (위험자산 부담)." if bp20 > 15 else "")), None
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
ORDER = ["KOSPI", "KOSDAQ", "SPX", "NASDAQ", "RUT", "NIKKEI", "TOPIX", "VIX", "US10Y", "JGB10Y", "DXY", "USDKRW", "USDJPY", "WTI", "GOLD", "BTC"]


def iv_chip() -> dict | None:
    """코스피200 ATM 내재변동성 칩 (파생 요청 req-macro-e0ef2a13, 10/23) — **표시 전용, 바람 점수 제외, 검증전**.
    reports/derivs.json atm_iv(연율) ÷ √252 = 옵션 가격이 내포한 '하루 1σ'. 방향 아님, 흔들림 크기 참고."""
    try:
        d = json.loads((REPORT_DIR / "derivs.json").read_text(encoding="utf-8"))
        iv = float(d["atm_iv"])
    except Exception:  # noqa: BLE001
        return None
    if not (0 < iv < 3):
        return None
    rv = d.get("rv20")
    day = iv / 252 ** 0.5
    return {"key": "K200_ATM_IV", "name": "코스피200 ATM 내재변동성", "iv": round(iv, 4), "day_1s": round(day, 4),
            "rv20": round(float(rv), 4) if isinstance(rv, (int, float)) else None, "date": d.get("date"),
            "label": "검증전", "scored": False,
            "state": f"ATM IV {iv*100:.1f}% → 하루 1σ ≈ ±{day*100:.1f}% (연율 ÷ √252)"
                     + (f" · 실현 20일 {float(rv)*100:.0f}%" if isinstance(rv, (int, float)) else "")
                     + " — 표시 전용, 바람 점수 제외(검증전)"}


def _jload(name: str):
    try:
        return json.loads((REPORT_DIR / name).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _md(ds) -> str:
    s = str(ds or "")
    return f"{int(s[5:7])}/{int(s[8:10])}" if len(s) >= 10 and s[4] == "-" else (s or "—")


def _foreign20(n: int = 20) -> dict | None:
    """data/deriv/daily.csv(KRX 확정, 억원) 최근 n거래일 외국인·기관·개인 현물 순매수 합."""
    import csv
    from .config import DATA_DIR
    try:
        with open(DATA_DIR / "deriv" / "daily.csv", encoding="utf-8") as f:
            rows = [r for r in csv.DictReader(f) if r.get("spot_frgn") not in (None, "")]
    except Exception:  # noqa: BLE001
        return None
    if len(rows) < n:
        return None
    t = rows[-n:]
    s = lambda k: sum(float(r[k] or 0) for r in t)   # noqa: E731
    return {"frgn": s("spot_frgn"), "inst": s("spot_inst"), "indiv": s("spot_indiv"), "from": t[0]["date"], "to": t[-1]["date"]}


def _jo(x_eok: float) -> str:
    return f"{x_eok / 10000:+.1f}조"


GEO_SHORT = {"hormuz": "호르무즈", "redsea": "홍해", "ruukr": "러-우 가스", "rare_earth": "희토류 통제", "chips": "반도체 통제",
             "taiwan": "대만해협", "korea": "한반도", "tariff": "관세 232"}


def glance(stats: dict, today: str | None = None) -> list[dict]:
    """'MACRO 한눈에' 층별 한 줄 (10/24 겸이 "추가된 데이터 기반으로 더 자세해야") — **표시 전용, 바람 점수·규칙 불변**.
    숫자 = 산출물에서 자동(각 줄 src·asof), 해석 = reports/views/macro_glance.json(데스크 작성, desk 필드로 복사).
    한 층이라도 재료가 없으면 그 층 line 에 '데이터 없음(파일)'을 쓰고 빠뜨리지 않는다(조용한 대체 금지)."""
    from datetime import datetime, timedelta, timezone
    import re
    today = today or datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")
    V = _jload("views/macro_glance.json") or {}
    L = V.get("layers") or {}

    def row(i, t, line, src, asof, verified="검증전", short=None):
        d = L.get(i) or {}
        return {"id": i, "title": t, "short": short or line, "line": line, "src": src, "asof": asof, "label": verified,
                "desk": ({"take": d.get("take"), "flip": d.get("flip"), "grade": d.get("grade"), "asof": V.get("updated")}
                         if d.get("take") else None)}
    out = []
    # ① 금리·통화 — bonds(국고3Y·미2Y) + realestate(ECOS 기준금리) + 데스크 입력 FF 상단(digest 근거)
    bd = _jload("bonds.json") or {}
    k3 = ((bd.get("kr") or {}).get("chg") or {}).get("3Y") or {}
    u2 = ((bd.get("us") or {}).get("chg") or {}).get("2Y") or {}
    base = next((r for r in ((_jload("realestate.json") or {}).get("rates") or []) if r.get("key") == "BOK_BASE" and r.get("status") == "ok"), None)
    fed = (V.get("policy") or {}).get("fed_upper")
    parts = []
    if k3.get("v") is not None:
        parts.append(f"국고3Y {k3['v']:.2f}%" + (f"(기준 {base['last']:.2f}% {(k3['v'] - base['last']) * 100:+.0f}bp" if base else "(기준금리 미확인")
                     + (f"·1M {k3['m1']:+.0f}bp)" if k3.get("m1") is not None else ")"))
    if u2.get("v") is not None:
        parts.append(f"미2Y {u2['v']:.2f}%" + (f"(FF상단 {fed:.2f}% {(u2['v'] - fed) * 100:+.0f}bp≈인상 {(u2['v'] - fed) / 0.25:.1f}회분" if fed else "(FF상단 미확인")
                     + (f"·1M {u2['m1']:+.0f}bp)" if u2.get("m1") is not None else ")"))
    sh = []
    if k3.get("v") is not None:
        sh.append(f"국고3Y {k3['v']:.2f}%" + (f"(기준{(k3['v'] - base['last']) * 100:+.0f}bp)" if base else ""))
    if u2.get("v") is not None:
        sh.append(f"미2Y {u2['v']:.2f}%" + (f"(FF상단{(u2['v'] - fed) * 100:+.0f}bp≈{(u2['v'] - fed) / 0.25:.1f}회)" if fed else ""))
    out.append(row("rates", "금리", " · ".join(parts) or "데이터 없음(bonds.json)",
                   "bonds.json · realestate.json(ECOS) · views/digest.json",
                   f"국고 {_md(k3.get('date'))} · 미 {_md(u2.get('date'))}" + (f" · 기준 {base['month']}" if base else ""), short=" · ".join(sh) or None))
    # ② 원자재 압력 — commodities(브렌트·TTF·구리/금), 52주 위치
    cm = _jload("commodities.json") or {}
    C = {r["key"]: r for r in (cm.get("rows") or []) if r.get("status") == "ok"}

    def cl(k, nm, dg=1, unit=""):
        r = C.get(k)
        if not r or r.get("last") is None:
            return f"{nm} 미확인"
        m1 = f"1M {r['chg1m'] * 100:+.0f}%" if r.get("chg1m") is not None else ""
        p = f"52주 {r['pos52'] * 100:.0f}%" if r.get("pos52") is not None else ""
        return f"{nm} {unit}{r['last']:,.{dg}f}(" + "·".join(x for x in (m1, p) if x) + ")"
    cp = [cl("BRENT", "브렌트", 1, "$"), cl("TTF", "TTF", 1, "€")]
    cu, au, ca = C.get("COPPER"), C.get("GOLD"), C.get("CU_AU")
    if ca and ca.get("last") is not None:
        why = ""
        if cu and au and cu.get("chg1m") is not None and au.get("chg1m") is not None and (ca.get("d1m") or 0) > 0:
            how = f"구리 1M {cu['chg1m'] * 100:+.0f}%·금 {au['chg1m'] * 100:+.0f}%"
            why = (f" ← 금이 더 빠진 몫({how}), 구리 강세 아님" if cu["chg1m"] < 0 and au["chg1m"] < 0 else
                   f" ← 구리 강세({how})" if cu["chg1m"] > 0 else f" ({how})")
        cp.append(f"구리/금 {ca['last']:.2f}(52주 {ca['pos52'] * 100:.0f}%){why}" if ca.get("pos52") is not None else f"구리/금 {ca['last']:.2f}")
    else:
        cp.append("구리/금 미확인")
    def cs(k, nm, unit=""):
        r = C.get(k)
        return (f"{nm} {unit}{r['last']:,.0f}(52주 {r['pos52'] * 100:.0f}%)" if r and r.get("last") is not None and r.get("pos52") is not None else f"{nm} 미확인")
    sh = [cs("BRENT", "브렌트", "$"), cs("TTF", "TTF", "€")]
    if ca and ca.get("pos52") is not None:
        sh.append(f"구리/금 52주 {ca['pos52'] * 100:.0f}%" + ("=금 하락 몫" if "금이 더 빠진" in cp[-1] else ""))
    out.append(row("cmd", "원자재", " · ".join(cp) if C else "데이터 없음(commodities.json)",
                   "commodities.json", _md(cm.get("asof")), short=" · ".join(sh) if C else None))
    # ③ 지정학 상위 2축 — views/geopolitics(수준) + geo_news(최근 헤드라인 1줄, 자동)
    G = _jload("views/geopolitics.json") or {}
    GN = _jload("geo_news.json") or {}
    NA = {a.get("id"): a for a in (GN.get("axes") or [])}
    rank = {"높음": 0, "중간": 1, "낮음": 2}
    ax = sorted(G.get("axes") or [], key=lambda a: rank.get(a.get("level"), 3))[:2]
    gl, gs = [], []
    def pick_news(aid):
        # geo_news 는 Google News 경유 항목을 title=None(+title_withheld, 피드 약관)으로 싣는다 — 제목 있는 항목 우선,
        # 전부 비공개면 매체·시각만(10/24 TypeError: None[:90] 로 한눈에 전체가 '생성 실패' 1줄이 됐던 원인)
        its = [n for n in ((NA.get(aid) or {}).get("items") or []) if isinstance(n, dict)]
        return next((n for n in its if n.get("title")), its[0] if its else None)

    def ttl(n, k=90):
        t = n.get("title") or ""
        return (t[:k] + ("…" if len(t) > k else "")) if t else "제목 비공개(피드 약관)"
    for a in ax:
        n = pick_news(a.get("id"))
        nt = (f" — 뉴스(자동): {ttl(n)} ({n.get('src') or ''} {_md(n.get('time'))})" if n else " — 최근 매칭 뉴스 없음")
        gl.append(f"{a.get('name')}[{a.get('level')}]{nt}")
        gs.append(f"{GEO_SHORT.get(a.get('id'), a.get('name'))}[{a.get('level')}]")
    n0 = next((n for n in (pick_news(a.get("id")) for a in ax) if n), None)
    out.append(row("geo", "지정학", " / ".join(gl) or "데이터 없음(views/geopolitics.json)",
                   "views/geopolitics.json · geo_news.json(자동 RSS)", f"축 {str(G.get('updated') or '—')[:10]} · 뉴스 {str(GN.get('generated_at') or '—')[:16]}",
                   short=(" · ".join(gs) + (f" — 자동: {ttl(n0, 200) if n0.get('title') else (n0.get('src') or '') + ' 제목 비공개'} ({_md(n0.get('time'))})" if n0 else "")) if gs else None))
    # ④ 한국 고유 요인 — 격차(규칙 #5 그대로) + 원인 후보를 데이터로 확인되는 것만 (반도체 2종목·외국인 20일·환율)
    kr, us = stats.get("KOSPI"), stats.get("SPX")
    kl, f20, ks = [], None, []
    if kr and us and kr.get("chg20") is not None and us.get("chg20") is not None:
        gap = kr["chg20"] - us["chg20"]
        kl.append(f"격차 {gap * 100:+.1f}%p")
        ks.append(f"격차 {gap * 100:+.1f}%p ←")
        sem = []
        for code, nm in (("005930", "삼성전자"), ("000660", "SK하이닉스")):
            d = _jload(f"detail/KR/{code}.json") or {}
            r20 = (d.get("stats") or {}).get("ret20")
            if isinstance(r20, (int, float)):
                sem.append((nm, r20, d.get("asof")))
        if len(sem) == 2:
            avg = sum(s[1] for s in sem) / 2
            ks.append(f"반도체 {'○' if avg <= kr['chg20'] else '✕'}(2종목 평균 {avg * 100:+.0f}%)")
            kl.append(("반도체 쏠림 ○" if avg <= kr["chg20"] else "반도체 쏠림 ✕") + f"({'·'.join(f'{s[0]} {s[1] * 100:+.0f}%' for s in sem)} vs 코스피 {kr['chg20'] * 100:+.0f}%"
                      + (f"·코스닥 {stats['KOSDAQ']['chg20'] * 100:+.0f}%" if stats.get("KOSDAQ") and stats["KOSDAQ"].get("chg20") is not None else "") + ")")
        else:
            kl.append("반도체 쏠림 미확인(detail 없음)")
        f20 = _foreign20()
        ks.append(f"외국인 {'○' if f20['frgn'] < 0 else '✕'}(20일 {_jo(f20['frgn'])})" if f20 else "외국인 미확인")
        kl.append((("외국인 매도 ○" if f20["frgn"] < 0 else "외국인 매도 ✕") + f"(20일 현물 외국인 {_jo(f20['frgn'])}·기관 {_jo(f20['inst'])}·개인 {_jo(f20['indiv'])})")
                  if f20 else "외국인 수급 미확인(deriv/daily.csv 없음)")
        fx = stats.get("USDKRW")
        if fx and fx.get("chg20") is not None:
            ks.append(f"환율 {'○' if fx['chg20'] > 0.015 else '✕'}(원/달러 {fx['chg20'] * 100:+.1f}%)")
            kl.append(("환율 ○" if fx["chg20"] > 0.015 else "환율 ✕") + f"(원/달러 20일 {fx['chg20'] * 100:+.1f}%" + (", 원화 강세라 원인 아님)" if fx["chg20"] < -0.015 else ")"))
        kl.append("반도체 지수 기여도 미확인(시총 비중 산출물 없음)")
    src_dt = f20["to"] if f20 else None
    out.append(row("kr", "한국 고유", " · ".join(kl) or "데이터 없음(macro_series KOSPI·SPX)",
                   "macro_view(macro_series) · detail/KR/005930·000660 · data/deriv/daily.csv(KRX)",
                   f"코스피 {_md(kr.get('date') if kr else None)} · 수급 {_md(src_dt)}", short=" ".join(ks) or None))
    # ⑤ 다음 1주 이벤트 3개 — calendar(매크로 ★3 → 한국 반도체 실적 ★3 묶음 → 매크로 ★2)
    cal = _jload("calendar.json") or {}
    end = (datetime.strptime(today, "%Y-%m-%d") + timedelta(days=7)).strftime("%Y-%m-%d")
    ev = [e for e in (cal.get("events") or []) if today <= str(e.get("date", "")) <= end]

    def kst(e):
        m = re.search(r"한국\s*(\d{1,2}/\d{1,2}\s*)?(\d{1,2}:\d{2})", str(e.get("note") or ""))
        return (f"{(m.group(1) or _md(e['date'])).strip()} {m.group(2)}" if m else _md(e["date"]))
    mac = sorted([e for e in ev if e.get("type") == "매크로"], key=lambda e: (-(e.get("imp") or 0), e["date"]))
    pick = [f"{kst(e)} {e['name'].replace(' 금리 결정', '')}{'★' if (e.get('imp') or 0) >= 3 else ''}" for e in mac if (e.get("imp") or 0) >= 3]
    semi = sorted([e for e in ev if e.get("type") == "실적" and (e.get("imp") or 0) >= 3 and e.get("name", "").startswith(("SK하이닉스", "삼성전자"))], key=lambda e: e["date"])
    if semi:
        pick.insert(1, "반도체 실적 " + "·".join(f"{e['name'].replace(' 실적', '')} {_md(e['date'])}" for e in semi) + "★")
    pick += [f"{kst(e)} {e['name']}" for e in mac if (e.get("imp") or 0) == 2]
    out.append(row("events", "다음 1주", " · ".join(pick[:3]) or "7일 안 ★ 일정 없음",
                   "calendar.json", f"{_md(today)}~{_md(end)} · 생성 {str(cal.get('asof') or '—')[:16]}", verified="일정(공식·회사 확정)",
                   short=" · ".join(re.sub(r"\s*\(.*?\)", "", x).replace("반도체 실적 ", "").replace("SK하이닉스", "하이닉스") for x in pick[:3]) or None))
    return out


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
    label = wind_label(score)
    summary = (f"매크로 바람 {label} ({score:+.2f}) — 주된 요인: "
               + ", ".join(f"{r['name']} {'+' if r['impact'] > 0 else '−'}" for r in drivers)) if score is not None else ""
    kr = stats.get("KOSPI")
    us = stats.get("SPX")
    if kr and us and score is not None:
        gap = (kr["chg20"] or 0) - (us["chg20"] or 0)
        g20 = f"20일 코스피 {(kr['chg20'] or 0)*100:+.1f}% vs S&P {(us['chg20'] or 0)*100:+.1f}% (격차 {gap*100:+.1f}%p)"
        if gap < -0.08 and score > -0.15:
            summary += f" · {g20} → 매크로보다 업종 쏠림(반도체) 문제, 매크로 반전만으론 회복 근거 부족"
        elif gap < -0.08:
            summary += f" · 매크로 역풍 + 한국 초과 하락 겹침 ({g20})"
    try:   # 직전 해설과 같은 결론이면 반복 문장 대신 '변화 없음' 표시 (매일 같은 문장이 반복된다는 피드백, 10/16)
        prev = json.loads((REPORT_DIR / "macro_view.json").read_text(encoding="utf-8"))
        if summary and prev.get("label") == label and prev.get("score") is not None and score is not None \
                and abs(prev["score"] - score) < 0.05 and str(prev.get("asof")) != str(max((r["date"] for r in rows), default=None)):
            summary = f"매크로 바람 {label} ({score:+.2f}, 전일 {prev['score']:+.2f}) — 변화 없음" + (summary[summary.index(" · "):] if " · " in summary else "")
    except Exception:  # noqa: BLE001
        pass
    out = {"asof": max((r["date"] for r in rows), default=None), "score": round(score, 2) if score is not None else None,
           "label": label, "summary": summary, "rows": rows}
    chip = iv_chip()   # 표시 전용 칩 — rows 에 넣지 않음(점수·rows 소비처 영향 0)
    if chip:
        out["chips"] = [chip]
    try:   # 한눈에 층별 줄 — 표시 전용(점수·rows 영향 0). 실패해도 바람 산출은 막지 않는다
        out["glance"] = glance(stats)
    except Exception as e:  # noqa: BLE001
        log.warning("한눈에 층별 줄 실패: %s", e)
        out["glance"] = [{"id": "err", "title": "층별 요약", "line": f"데이터 없음(생성 실패: {type(e).__name__})", "src": "screener/macroview.py",
                          "asof": None, "label": "검증전", "desk": None}]
    try:   # 보고 상단 형식 top(STANDARD 8절) — summary 는 그대로, 추가만
        from . import topline_from
        out["top"] = topline_from.macro(out)
    except Exception as e:  # noqa: BLE001
        log.warning("매크로 top 실패: %s", e)
    from .guard import write_json
    write_json(REPORT_DIR / "macro_view.json", out, default=str)
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
