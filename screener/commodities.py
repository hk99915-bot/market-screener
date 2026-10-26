"""원자재 트래킹 — 매크로 데스크 (10/23 겸이 "매크로누나 원자재 트래킹 더 강화, 정유 구리 알루미늄 등, 비철금속, 희토류 등").

입력: 야후 일봉(screener.data.fetch_prices, 기존 매크로 수집과 같은 경로). 출력: reports/commodities.json.
지표마다 수준 · 1주(5거래일)/1개월(21거래일) 변화 · 52주 위치(0=저점 1=고점) · 한국 업종 연결(업종 수준 설명, 종목 권유 아님).
파생: 3-2-1 크랙(정유 마진 프록시) · 브렌트−WTI · 금/은 비율 · 구리/금 비율.
못 받는 것은 지어내지 않고 status='미확인' + 이유(싱가포르 마진·희토류 산화물·코발트·리튬 현물 — 유료/거래 없음).
10/23 데이터 데스크(req-data-3dda8f42): 니켈·아연·주석 = WisdomTree ETC(LSE·밀라노), JKM = NYMEX 정산가, 우라늄 = Sprott 실물 신탁 —
일간 대용. 공식 수준(달러/톤)은 FRED IMF 월평균(MONTHLY, freq='월간')으로 따로 — 일간 대용과 월평균 변화율 상관 0.93~0.99(24개월 대조).
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
    ("JKM", "JKM=F", "아시아 LNG(JKM, NYMEX 정산가)", "$/MMBtu", "에너지", "가스공사·발전 원가 · 한국 LNG 도입가 기준 — NYMEX JKM(Platts) 선물 근월 정산가. 장내 거래량 0(장외 청산) → 정산가 참고값. FRED 월간 일본 LNG(PNGASJPUSDM)와 월평균 변화율 상관 0.97"),
    ("URANIUM", "SRUUF", "우라늄(Sprott 실물 신탁)", "$", "에너지", "원전 연료 — 실물 U3O8 보유 신탁 가격(현물 대용, 신탁 프리미엄·할인 섞임). 원전 기자재·건설 업종 심리. FRED 월간 PURANUSDM 과 월평균 변화율 상관 0.93"),
    ("NG", "NG=F", "천연가스(헨리허브)", "$/MMBtu", "에너지", "미국 LNG 수출 원가 → LNG선 발주(조선)·가스공사 도입 단가 일부"),
    ("TTF", "TTF=F", "유럽 가스(TTF)", "€/MWh", "에너지", "러-우·유럽 공급 리스크 온도계. 아시아 LNG(JKM)와 경쟁 → 한국 LNG 도입가·발전 원가"),
    ("COPPER", "HG=F", "구리(COMEX)", "$/lb", "비철", "전선·전력기기: 원가지만 판가 전가 + 송배전 투자 수요의 대리 지표 · 비철 제련"),
    ("ALUM", "ALI=F", "알루미늄(COMEX)", "$/t", "비철", "알루미늄 압연·자동차 경량화·포장재 원가. COMEX 계약은 LME 보다 거래가 얇음(참고)"),
    # 10/23 데이터 데스크(req-data-3dda8f42): ZNC=F 는 최근 20거래일 고유값 2개(거래 0) → WisdomTree 아연 ETC(LSE, $)로 교체.
    # ETC 는 블룸버그 아연 선물 지수 추종 — 수준은 $/t 가 아니라 증권 가격, 방향·변화율만 읽는다. FRED 월간(PZINCUSDM)과 월평균 변화율 상관 0.95(24개월).
    ("ZINC", "ZINC.L", "아연(WisdomTree ETC·LSE)", "$", "비철", "아연 제련(국내 대형 제련사)·강판 도금 원가 — ETC 가격(선물 지수 추종), $/t 아님"),
    ("NICKEL", "NICK.L", "니켈(WisdomTree ETC·LSE)", "$", "비철", "2차전지 양극재(하이니켈) 원가 · 판가 연동(메탈 가격 래깅) — ETC 가격(LME 선물 지수 추종), $/t 아님. FRED 월간 PNICKUSDM 과 월평균 변화율 상관 0.99 이상(24개월)"),
    ("TIN", "TINM.MI", "주석(WisdomTree ETC·밀라노)", "€", "비철", "반도체 패키징 솔더 원가 — 유로 표시·거래 얇음(호가 정체 시 미확인 처리). FRED 월간 PTINUSDM 과 월평균 변화율 상관 0.95"),
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
# 월간 대조값 — FRED 의 IMF 1차상품 가격(PCPS, 월평균, 키 불필요 fredgraph.csv). 일간이 아니므로 화면에 '월간' 표기.
# (key, FRED id, 이름, 단위, 그룹, 한국 업종 연결)
MONTHLY: list[tuple[str, str, str, str, str, str]] = [
    ("NICKEL_M", "PNICKUSDM", "니켈 월평균(IMF)", "$/t", "비철", "LME 니켈 현물 월평균에 가까운 공식 통계 — 양극재 판가 래깅 계산 기준으로 적합"),
    ("ZINC_M", "PZINCUSDM", "아연 월평균(IMF)", "$/t", "비철", "아연 제련 판가·TC 협상 배경"),
    ("TIN_M", "PTINUSDM", "주석 월평균(IMF)", "$/t", "비철", "반도체 솔더 원가"),
    ("LNG_JP_M", "PNGASJPUSDM", "일본 LNG 월평균(IMF)", "$/MMBtu", "에너지", "아시아 LNG 도입가 — 한국 LNG 도입가와 같은 권역"),
    ("URAN_M", "PURANUSDM", "우라늄 월평균(IMF)", "$/lb", "에너지", "원전 연료 현물 월평균"),
]
FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={}"

# 데이터 못 받는 지표 — 지어내지 않고 이유를 적는다 (2026-10-23 데이터 데스크 실조회, req-data-3dda8f42)
UNAVAILABLE = [
    {"key": "SG_GRM", "name": "싱가포르 복합정제마진", "group": "에너지", "status": "미확인",
     "why": "업계 기준(Platts·S&P 등 유료)이라 무료 시계열 없음 → 미 걸프 3-2-1 크랙으로 방향만 대용",
     "kr": "정유 업종 분기 실적의 1차 변수"},
    {"key": "RE_OXIDE", "name": "희토류 산화물 현물(NdPr·Dy·Tb)", "group": "희토류·전략광물", "status": "미확인",
     "why": "중국 현지 현물가(SMM·아시아금속) 유료, IMF·FRED 시리즈 없음 → REMX·MP 주가로 대용, 수출통제는 지정학 뷰 이벤트로",
     "kr": "모터 자석 원가·조달 차질(2차전지·전기차·방산)"},
    {"key": "COBALT", "name": "코발트", "group": "희토류·전략광물", "status": "미확인",
     "why": "야후 COB=F 3개월 1행(거래 없음) · FRED/IMF 코발트 시리즈 없음 · 야후 CB=F 는 코발트가 아니라 버터 선물(주의) → 무료 일간·월간 소스 없음",
     "kr": "양극재(NCM) 원가"},
    {"key": "LITHIUM_SPOT", "name": "리튬 탄산염·수산화물 현물", "group": "희토류·전략광물", "status": "미확인",
     "why": "야후 LTH=F 3개월 1행(거래 없음) · FRED/IMF 리튬 시리즈 없음 → LIT ETF 대용",
     "kr": "2차전지 소재 판가·재고평가"},
]
# 조사했지만 쓰지 않는 소스 (2026-10-23 실요청 결과 — 다시 조사하지 않도록 남김)
SOURCE_NOTES = [
    "토스증권 Open API(v1.2.24, 공개 문서 확인): 원자재·선물 없음 — 시장지표 카탈로그 8종(코스피·코스닥·국채 2~30년)뿐, 미 ETF 시세는 야후와 중복이라 추가 안 함. 웹 화면 크롤링은 약관상 금지",
    "investing.com: 403(봇 차단) + 이용약관상 스크래핑 금지",
    "westmetall(LME 공식가 표): 접속은 되나 LME 가격 재배포는 LME 라이선스 대상 → 공개 저장소에 저장 안 함",
    "EIA API: 무료지만 api_key 필요(저장소 시크릿 없음) — 필요 시 키 등록 후 추가, 현재 WTI·브렌트는 야후 선물로 충분",
    "야후 NI=F·SN=F·JJN·JJU: 데이터 없음 · ZNC=F: 호가 정체(거래 0) · LTH=F·COB=F·UX=F: 3개월 1행",
]
GROUPS = ["에너지", "비철", "희토류·전략광물", "귀금속"]
# 대용(ETC·신탁·ETF로 원자재 가격을 대신하는 것) — 검증한 건 월평균 '변화율' 상관뿐이라 52주 위치(수준)는 실물과 다를 수 있다
# (피어리뷰 2026-10-24 C1: SRUUF pos52 0.15 vs 공식 월평균 URAN_M 1.0). 화면·note 는 위치 대신 '대용 — 수준 비교 불가', 변화율만.
PROXY = {"URANIUM", "ZINC", "NICKEL", "TIN", "DBB", "LIT", "REMX"}


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


def stats_monthly(rows: list[tuple[str, float]], today: date | None = None) -> dict:
    """[(YYYY-MM-01, 월평균)] 오름차순 → 수준·전월 대비·12개월 대비·12개월 위치. 월간이라 1주 칸 없음, 100일 넘게 새 달이 없으면 '미확인'."""
    c = [(d, v) for d, v in rows if v is not None]
    if len(c) < 13:
        return {"status": "미확인", "why": f"월간 {len(c)}개 — 부족", "freq": "월간"}
    vals = [v for _, v in c]
    last, d = vals[-1], c[-1][0]
    y = vals[-12:]
    hi, lo = max(y), min(y)
    out = {"last": round(last, 4), "date": str(d)[:10], "freq": "월간", "chg1m": _r(last / vals[-2] - 1 if vals[-2] else None),
           "chg12m": _r(last / vals[-13] - 1 if vals[-13] else None), "hi52": round(hi, 4), "lo52": round(lo, 4),
           "pos52": round((last - lo) / (hi - lo), 3) if hi > lo else None, "status": "ok"}
    today = today or datetime.now(ZoneInfo("Asia/Seoul")).date()
    try:
        if (today - date.fromisoformat(str(d)[:10])).days > 100:
            out.update(status="미확인", why=f"마지막 월 {str(d)[:7]} — 3개월 넘게 새 값 없음")
    except ValueError:
        pass
    return out


def parse_fred_csv(text: str) -> list[tuple[str, float]]:
    """fredgraph.csv(observation_date,ID) → [(날짜, 값)]. 결측('.')·머리줄·HTML(없는 시리즈는 봇 확인 페이지가 옴)은 건너뛴다."""
    out = []
    for line in (text or "").splitlines()[1:]:
        p = line.strip().split(",")
        if len(p) != 2 or len(p[0]) != 10 or p[0][4] != "-":
            continue
        try:
            out.append((p[0], float(p[1])))
        except ValueError:
            continue
    return out


def fetch_fred(ids: list[str]) -> dict[str, list[tuple[str, float]]]:
    """FRED fredgraph.csv(키 불필요). 첫 타임아웃 뒤 나머지는 건너뜀 — 10/23 calendar_ev 60초×4 지연(req-data-fb0157f5) 반복 방지."""
    import requests
    res: dict = {}
    for sid in ids:
        try:
            r = requests.get(FRED_CSV.format(sid), timeout=(10, 60))   # 기본 UA — 10/23 실측: 브라우저·커스텀 UA 는 읽기 타임아웃, 기본 UA 0.5초
            r.raise_for_status()
            res[sid] = parse_fred_csv(r.text)
        except requests.Timeout as e:
            log.warning("FRED %s 타임아웃 — 나머지 월간 시리즈 건너뜀: %s", sid, e)
            break
        except Exception as e:  # noqa: BLE001
            log.warning("FRED %s 실패: %s", sid, e)
    return res


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
    if r.get("proxy"):
        return "대용 — 수준 비교 불가(변화율만)" + ("" if m is None else " · 1개월 급등(≥+10%)" if m >= 0.10 else " · 1개월 급락(≤−10%)" if m <= -0.10 else "")
    band = ("52주 고점권" if p is not None and p >= 0.9 else "52주 상단" if p is not None and p >= 0.7 else
            "52주 저점권" if p is not None and p <= 0.1 else "52주 하단" if p is not None and p <= 0.3 else "52주 중간")
    if r.get("group") == "파생":   # 스프레드·마진·비율은 % 변화가 왜곡(0 근처 분모) → 단위 차이로
        dm = r.get("d1m")
        return band + ("" if dm is None else f" · 1개월 {dm:+.2f}{r.get('unit') or ''}")
    if r.get("freq") == "월간":
        c12 = r.get("chg12m")
        return f"월간 {str(r.get('date') or '')[:7]} · 12개월 위치 " + band.replace("52주 ", "") + ("" if c12 is None else f" · 12개월 {c12*100:+.0f}%")
    mv = ("" if m is None else " · 1개월 급등(≥+10%)" if m >= 0.10 else " · 1개월 급락(≤−10%)" if m <= -0.10 else "")
    return band + mv


def build(fetch=None, fetch_monthly=None) -> dict:
    """fetch(symbols) → {심볼: [(날짜, 종가)]}. 기본은 screener.data.fetch_prices (야후, 1.1년).
    fetch_monthly(FRED ids) → {id: [(날짜, 값)]}. 기본은 fetch 도 기본일 때만 fetch_fred — 가짜 fetch 를 준 테스트는 네트워크 없이 월간 생략."""
    if fetch_monthly is None:
        fetch_monthly = fetch_fred if fetch is None else (lambda ids: {})
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
        rows.append({"key": key, "sym": sym, "name": name, "unit": unit, "group": grp, "kr": kr, **s, **({"proxy": True} if key in PROXY else {})})
    try:
        mraw = fetch_monthly([m for _, m, *_ in MONTHLY])
    except Exception as e:  # noqa: BLE001
        log.warning("월간(FRED) 수집 실패: %s", e)
        mraw, errors = {}, errors + [f"월간(FRED) 수집 실패: {e}"]
    for key, sid, name, unit, grp, kr in MONTHLY:
        rs = mraw.get(sid) or []
        s = stats_monthly(rs) if rs else {"status": "미확인", "why": f"FRED {sid} 못 받음(타임아웃·실패·빈 응답 — 실행 로그)", "freq": "월간"}
        rows.append({"key": key, "sym": f"FRED {sid}", "name": name, "unit": unit, "group": grp, "kr": kr, **s})
    rows += derived(series)
    for r in rows:
        r["note"] = note(r)
    ok = [r for r in rows if r.get("status") == "ok"]
    asof = max((str(r["date"]) for r in ok if r.get("freq") != "월간"), default=None)   # 월간 줄은 날짜 기준에서 제외
    big = sorted([r for r in ok if r.get("chg1m") is not None and abs(r["chg1m"]) >= 0.10 and r["group"] != "파생" and r.get("freq") != "월간"],
                 key=lambda r: -abs(r["chg1m"]))
    summary = ("1개월 ±10% 넘게 움직인 원자재: " + ", ".join(f"{r['name']} {r['chg1m']*100:+.0f}%" for r in big[:5])) if big else "1개월 ±10% 넘게 움직인 원자재 없음"
    out = {"asof": asof, "generated_at": datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M KST"),
           "groups": GROUPS + ["파생"], "rows": rows, "unavailable": UNAVAILABLE, "source_notes": SOURCE_NOTES, "summary": summary, "errors": errors,
           "label": "표시 전용 · 매크로 바람 점수 제외 · 업종 연결은 설명이지 매수 권유 아님",
           "src": "야후 일봉(선물 연속·ETF·ETC 종가) · 1주=5거래일 · 1개월=21거래일 · 52주 위치=(현재−저점)÷(고점−저점) · '월간' 줄 = FRED IMF 월평균(1개월=전월 대비, 위치=12개월)"}
    try:   # STANDARD 8절 상단 3칸(묶음 B, 추가만)
        from . import topline_from
        out["top"] = topline_from.commodities(out)
    except Exception:  # noqa: BLE001
        pass
    from .guard import write_json
    write_json(OUT, out)
    log.info("원자재 %d개(ok %d) · %s", len(rows), len(ok), summary)
    return out


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    build()
