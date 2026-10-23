"""원자재 트래킹 — 매크로 데스크 (10/23 겸이 "매크로누나 원자재 트래킹 더 강화, 정유 구리 알루미늄 등, 비철금속, 희토류 등").

입력: 야후 일봉(screener.data.fetch_prices, 기존 매크로 수집과 같은 경로). 출력: reports/commodities.json.
지표마다 수준 · 1주(5거래일)/1개월(21거래일) 변화 · 52주 위치(0=저점 1=고점) · 한국 업종 연결(업종 수준 설명, 종목 권유 아님).
파생: 3-2-1 크랙(정유 마진 프록시) · 브렌트−WTI · 금/은 비율 · 구리/금 비율.
못 받는 것은 지어내지 않고 status='미확인' + 이유(LME 니켈 무료 소스 없음 · JJN 단종 · 호가 정체 등).
표시 전용 — 매크로 바람 점수(macroview.W)에 넣지 않는다(검증전). 화면: MARKET › MACRO '원자재' 패널(getCommodities).
실행: write_macro_series(장 마감 15:45·16:20 스크리너·06:52 미장 마감) 끝에 같이, 수동 `python -m screener.commodities`.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .config import REPORT_DIR

log = logging.getLogger(__name__)
OUT = REPORT_DIR / "commodities.json"
BBL_GAL = 42   # 1배럴 = 42갤런 (RB·HO 선물은 $/갤런 호가)

# (key, 야후 심볼, 이름, 단위, 그룹, 한국 업종 연결)
SPEC: list[tuple[str, str, str, str, str, str]] = [
    ("WTI", "CL=F", "WTI 원유", "$/bbl", "에너지", "정유: 오르면 재고평가 이익(단기)·내리면 재고손실 · 항공·해운 연료비 − · 화학 나프타 원가 −"),
    ("BRENT", "BZ=F", "브렌트 원유", "$/bbl", "에너지", "한국 도입 원유(두바이 연동)와 같이 움직임 → 무역수지·원화·물가 경로. 중동 리스크가 가장 먼저 붙는 가격"),
    ("RBOB", "RB=F", "가솔린(RBOB)", "$/gal", "에너지", "제품 가격 — 원유보다 강하면 정제마진 확대(정유 업종 +)"),
    ("HO", "HO=F", "난방유(디젤 프록시)", "$/gal", "에너지", "중간유분(경유·항공유) 가격 — 한국 정유 수출 주력 제품군과 가까움"),
    ("NG", "NG=F", "천연가스(헨리허브)", "$/MMBtu", "에너지", "미국 LNG 수출 원가 → LNG선 발주(조선)·가스공사 도입 단가 일부"),
    ("TTF", "TTF=F", "유럽 가스(TTF)", "€/MWh", "에너지", "러-우·유럽 공급 리스크 온도계. 아시아 LNG(JKM)와 경쟁 → 한국 LNG 도입가·발전 원가"),
    ("COPPER", "HG=F", "구리(COMEX)", "$/lb", "비철", "전선·전력기기: 원가지만 판가 전가 + 송배전 투자 수요의 대리 지표 · 비철 제련"),
    ("ALUM", "ALI=F", "알루미늄(COMEX)", "$/t", "비철", "알루미늄 압연·자동차 경량화·포장재 원가. COMEX 계약은 LME 보다 거래가 얇음(참고)"),
    ("ZINC", "ZNC=F", "아연(COMEX)", "$/t", "비철", "아연 제련(국내 대형 제련사)·강판 도금 원가"),
    ("DBB", "DBB", "비철 바스켓 ETF(DBB)", "$", "비철", "구리·알루미늄·아연 선물 1/3씩 — 비철 전반 방향"),
    ("COPX", "COPX", "구리 광산주 ETF(COPX)", "$", "비철", "구리 가격의 주식 쪽 레버리지 — 전선·제련 업종 심리와 같이 봄"),
    ("PICK", "PICK", "글로벌 금속·광산주 ETF(PICK)", "$", "비철", "철광석·구리·니켈 등 광산 전반 — 중국 수요 기대"),
    ("LIT", "LIT", "리튬·배터리 ETF(LIT)", "$", "희토류·전략광물", "2차전지 소재(리튬·니켈 양극재) 업황 심리 — 리튬 현물 무료 소스 없어 ETF 대용"),
    ("REMX", "REMX", "희토류·전략금속 ETF(REMX)", "$", "희토류·전략광물", "영구자석(전기차 모터·풍력)·방산 유도무기 소재 → 2차전지·방산·전력기기 공급망. 중국 수출통제 뉴스에 가장 먼저 반응"),
    ("MP", "MP", "MP Materials(미 희토류)", "$", "희토류·전략광물", "중국 밖 희토류 공급 대표 — 미 정부 지원·중국 통제 강화 때 강세(탈중국 공급망 프리미엄)"),
    ("GOLD", "GC=F", "금", "$/oz", "귀금속", "실질금리·달러·준비자산 수요(매크로 KB #19~21). 원화 금 = 달러 금 × 원/달러"),
    ("SILVER", "SI=F", "은", "$/oz", "귀금속", "귀금속 + 산업용(태양광 페이스트) 이중 성격 — 아연·연 제련 부산물"),
    ("PLAT", "PL=F", "백금", "$/oz", "귀금속", "자동차 배기 촉매·수소 연료전지 소재"),
]
# 데이터 못 받는 지표 — 지어내지 않고 이유를 적는다 (2026-10-23 야후 확인: NI=F·JJN·JJU 데이터 없음)
UNAVAILABLE = [
    {"key": "NICKEL", "name": "니켈", "group": "비철", "status": "미확인",
     "why": "LME 니켈 무료 시세 소스 없음 · 야후 NI=F 없음 · 니켈 ETN JJN 단종(2026-10-23 조회 데이터 없음) → PICK·LIT 로 간접만",
     "kr": "2차전지 양극재(하이니켈) 원가 · 판가 연동(메탈 가격 래깅)"},
    {"key": "SG_GRM", "name": "싱가포르 복합정제마진", "group": "에너지", "status": "미확인",
     "why": "한국 정유 마진의 업계 기준이지만 무료 시계열 없음 → 미 걸프 3-2-1 크랙으로 방향만 대용",
     "kr": "정유 업종 분기 실적의 1차 변수"},
    {"key": "JKM", "name": "아시아 LNG(JKM)", "group": "에너지", "status": "미확인",
     "why": "무료 시계열 없음 → TTF(유럽)·헨리허브로 대용", "kr": "가스공사·발전 원가"},
    {"key": "RE_OXIDE", "name": "희토류 산화물 현물(NdPr·Dy·Tb)", "group": "희토류·전략광물", "status": "미확인",
     "why": "중국 현지 현물가(SMM·아시아금속) 유료 → REMX·MP 주가로 대용, 수출통제는 지정학 뷰(reports/views/geopolitics.json) 이벤트로",
     "kr": "모터 자석 원가·조달 차질(2차전지·전기차·방산)"},
]
GROUPS = ["에너지", "비철", "희토류·전략광물", "귀금속"]


def stats(rows: list[tuple[str, float]], today: date | None = None) -> dict:
    """[(날짜, 종가)] 오름차순 → 수준·1주/1개월·52주 위치. 호가 정체(최근 20개 중 고유값 ≤3)·7일 넘게 묵은 값은 '미확인'."""
    c = [v for _, v in rows if v is not None]
    if len(c) < 30:
        return {"status": "미확인", "why": f"일봉 {len(c)}개 — 부족"}
    last, d = c[-1], rows[-1][0]
    y = c[-252:]
    hi, lo = max(y), min(y)
    ch = lambda n: (last / c[-1 - n] - 1) if len(c) > n and c[-1 - n] else None  # noqa: E731
    dif = lambda n: round(last - c[-1 - n], 4) if len(c) > n else None  # noqa: E731 — 스프레드·마진은 % 보다 차이(단위)로 읽는다
    out = {"last": round(last, 4), "date": d, "chg1w": _r(ch(5)), "chg1m": _r(ch(21)), "chg3m": _r(ch(63)), "d1w": dif(5), "d1m": dif(21),
           "hi52": round(hi, 4), "lo52": round(lo, 4), "pos52": round((last - lo) / (hi - lo), 3) if hi > lo else None,
           "status": "ok"}
    if len(set(c[-20:])) <= 3:
        out.update(status="미확인", why="최근 20거래일 호가 정체(고유값 ≤3) — 거래 없는 계약, 값 신뢰 불가")
    today = today or datetime.now(ZoneInfo("Asia/Seoul")).date()
    try:
        if (today - date.fromisoformat(str(d)[:10])).days > 7:
            out.update(status="미확인", why=f"마지막 값 {d} — 7일 넘게 갱신 없음")
    except ValueError:
        pass
    return out


def _r(x):
    return None if x is None else round(x, 4)


def crack321(cl: float, rb: float, ho: float) -> float:
    """3-2-1 크랙($/bbl) = (2×가솔린 + 1×난방유 − 3×원유) ÷ 3, 제품은 $/gal × 42. 미 걸프 정제마진 프록시."""
    return (2 * rb * BBL_GAL + ho * BBL_GAL - 3 * cl) / 3


def _align(a: list, b: list) -> list[tuple[str, float, float]]:
    db = dict(b)
    return [(d, v, db[d]) for d, v in a if d in db and v is not None and db[d] is not None]


def derived(series: dict[str, list[tuple[str, float]]], today: date | None = None) -> list[dict]:
    """파생 지표 시계열을 만들어 같은 stats 로 요약."""
    out = []

    def add(key, name, unit, rows, what, kr):
        s = stats(rows, today) if rows else {"status": "미확인", "why": "구성 시계열 없음"}
        out.append({"key": key, "name": name, "unit": unit, "group": "파생", "what": what, "kr": kr, **s})
    cl, rb, ho = series.get("WTI") or [], series.get("RBOB") or [], series.get("HO") or []
    drb, dho = dict(rb), dict(ho)
    crk = [(d, round(crack321(v, drb[d], dho[d]), 3)) for d, v in cl if d in drb and d in dho]
    add("CRACK321", "3-2-1 크랙(정유 마진 프록시)", "$/bbl", crk,
        "원유 3배럴 → 가솔린 2·난방유 1배럴 만들 때 남는 마진. (2×RB×42 + HO×42 − 3×WTI) ÷ 3",
        "정유 업종 이익 방향(미 걸프 기준 — 한국 기준 싱가포르 마진은 미확인). 마진↑ + 유가 안정이 정유엔 가장 좋은 조합")
    add("BRENT_WTI", "브렌트−WTI 스프레드", "$/bbl", [(d, round(b - w, 3)) for d, b, w in _align(series.get("BRENT") or [], cl)],
        "중동·해상 운송 리스크가 브렌트에 먼저 붙는 만큼 벌어짐 (호르무즈·홍해 축 관찰 지표)",
        "넓어질수록 중동산 도입 비중 큰 한국 정유·화학 원가 부담, 미국산 원유 대체 유인")
    add("GOLD_SILVER", "금/은 비율", "배", [(d, round(g / s, 3)) for d, g, s in _align(series.get("GOLD") or [], series.get("SILVER") or []) if s],
        "높을수록 위험 회피(금 선호), 낮을수록 경기·산업 수요 기대", "귀금속 내 상대 강도 — 업종 직접 연결 약함")
    add("CU_AU", "구리/금 비율(×1000)", "", [(d, round(cu / g * 1000, 4)) for d, cu, g in _align(series.get("COPPER") or [], series.get("GOLD") or []) if g],
        "경기 기대(구리) ÷ 안전 선호(금). 미 10년 금리와 같이 움직이는 경향 [교과서·현업 관행, 검증전]",
        "내리면 경기 민감 업종(전선·화학·철강) 심리 약화 신호")
    return out


def note(r: dict) -> str:
    """규칙 기반 한 줄 상태 — 52주 위치·1개월 변화 크기. 해석 추정 없음."""
    if r.get("status") != "ok":
        return f"미확인 — {r.get('why', '')}"
    p, m = r.get("pos52"), r.get("chg1m")
    band = ("52주 고점권" if p is not None and p >= 0.9 else "52주 상단" if p is not None and p >= 0.7 else
            "52주 저점권" if p is not None and p <= 0.1 else "52주 하단" if p is not None and p <= 0.3 else "52주 중간")
    if r.get("group") == "파생":   # 스프레드·마진·비율은 % 변화가 왜곡(0 근처 분모) → 단위 차이로
        dm = r.get("d1m")
        return band + ("" if dm is None else f" · 1개월 {dm:+.2f}{r.get('unit') or ''}")
    mv = ("" if m is None else " · 1개월 급등(≥+10%)" if m >= 0.10 else " · 1개월 급락(≤−10%)" if m <= -0.10 else "")
    return band + mv


def build(fetch=None) -> dict:
    """fetch(symbols) → {심볼: [(날짜, 종가)]}. 기본은 screener.data.fetch_prices (야후, 1.1년)."""
    syms = [s for _, s, *_ in SPEC]
    errors = []
    if fetch is None:
        def fetch(ss):
            from . import data
            df = data.fetch_prices(ss, "MACRO", lookback_days=400)
            res: dict = {}
            for x in df.sort("date").select("yf", "date", "close").iter_rows():
                res.setdefault(x[0], []).append((str(x[1]), float(x[2]) if x[2] is not None else None))
            return res
    try:
        raw = fetch(syms)
    except Exception as e:  # noqa: BLE001 — 실패는 산출물에 원인으로 남긴다 (STANDARD §3)
        log.warning("원자재 수집 실패: %s", e)
        raw, errors = {}, [f"수집 실패: {e}"]
    series, rows = {}, []
    for key, sym, name, unit, grp, kr in SPEC:
        rs = raw.get(sym) or []
        series[key] = rs
        s = stats(rs) if rs else {"status": "미확인", "why": f"야후 {sym} 데이터 없음"}
        rows.append({"key": key, "sym": sym, "name": name, "unit": unit, "group": grp, "kr": kr, **s})
    rows += derived(series)
    for r in rows:
        r["note"] = note(r)
    ok = [r for r in rows if r.get("status") == "ok"]
    asof = max((str(r["date"]) for r in ok), default=None)
    big = sorted([r for r in ok if r.get("chg1m") is not None and abs(r["chg1m"]) >= 0.10 and r["group"] != "파생"],
                 key=lambda r: -abs(r["chg1m"]))
    summary = ("1개월 ±10% 넘게 움직인 원자재: " + ", ".join(f"{r['name']} {r['chg1m']*100:+.0f}%" for r in big[:5])) if big else "1개월 ±10% 넘게 움직인 원자재 없음"
    out = {"asof": asof, "generated_at": datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M KST"),
           "groups": GROUPS + ["파생"], "rows": rows, "unavailable": UNAVAILABLE, "summary": summary, "errors": errors,
           "label": "표시 전용 · 매크로 바람 점수 제외 · 업종 연결은 설명이지 매수 권유 아님",
           "src": "야후 일봉(선물 연속·ETF 종가) · 1주=5거래일 · 1개월=21거래일 · 52주 위치=(현재−저점)÷(고점−저점)"}
    from .guard import write_json
    write_json(OUT, out)
    log.info("원자재 %d개(ok %d) · %s", len(rows), len(ok), summary)
    return out


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    build()
