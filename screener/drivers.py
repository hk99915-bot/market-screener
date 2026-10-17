"""이익 지속성 드라이버 — "지금 이익이 유지되느냐"를 공급망·매크로·애널리스트·뉴스·공시로 엮는다.

비용 0, 규칙 기반 (모든 판단에 근거 문자열을 붙인다).

구성 (종목별)
1. 체인: 업종별 수요처·동종 사이클·원가 요인을 글로벌 상장사/선물/ETF 로 연결
   - 각 프록시의 애널리스트 EPS 추정치 변화(30·90일), 최근 분기 매출 YoY, 3개월 주가, (하이퍼스케일러는 CAPEX YoY)
   - relation: +1 = 같이 좋아지면 우리 이익도 좋아짐, −1 = 반대(원가·경쟁), 0 = 참고
2. 매크로: 시장(KOSPI) 영향을 뺀 잔차 수익률이 환율·유가·금리·SOX·구리에 얼마나 반응했나 (1년, t값),
   그리고 그 변수의 최근 1개월 방향 → 지금 바람이 순풍인지 역풍인지
3. 애널리스트: 최근 90일 목표가 상·하향, 톤, 리포트 본문에서 뽑은 이익 드라이버(환율·원자재·판가·물량·재고·경쟁·관세…)와 방향
4. 뉴스: 최근 7일 헤드라인을 이익 이벤트(판가 인상·수주·증설·감산·재고·관세·규제…)로 분류
5. 공시: 수주(단일판매·공급계약), 시설투자, 희석
→ 종합 점수(−1~+1) → '현재 이익 지속' 묶음 가중치 w (0.1~0.9) → 신호 가중 적정가 = w·현재이익 + (1−w)·정상화
"""
from __future__ import annotations

import json
import logging
import math
import re
import time
from datetime import date, datetime, timedelta

import polars as pl

from .config import DATA_DIR, REPORT_DIR

log = logging.getLogger(__name__)
CACHE = REPORT_DIR / "chains.json"

# ───────────── 체인 정의 ─────────────
# proxies: (티커, 이름, 역할, relation)
HYPER = [("MSFT", "마이크로소프트", "AI 인프라 CAPEX", 1), ("GOOGL", "알파벳", "AI 인프라 CAPEX", 1),
         ("AMZN", "아마존", "AI 인프라 CAPEX", 1), ("META", "메타", "AI 인프라 CAPEX", 1)]
CHAINS: dict[str, dict] = {
    # 402340 SK스퀘어 = SK하이닉스 지분 가치가 대부분인 지주사 → 메모리 체인 (업종 분류 '기타금융'으로 은행 체인에 잘못 붙던 것 교정)
    "memory": {"name": "메모리 반도체", "codes": ["005930", "005935", "000660", "402340"],
               "proxies": [("NVDA", "엔비디아", "HBM 최대 수요처", 1), ("AVGO", "브로드컴", "AI ASIC 수요", 1), ("AMD", "AMD", "GPU·CPU 수요", 1),
                           *HYPER, ("MU", "마이크론", "동일 사이클(경쟁사지만 업황 동행)", 1), ("SNDK", "샌디스크", "낸드 사이클", 1),
                           ("AMAT", "어플라이드", "업계 증설 강도 (늘면 수요 신호지만 1~2년 뒤 공급 과잉 위험 — 방향 불명확)", 0),
                           ("^SOX", "필라델피아 반도체", "업황 심리 (주가만 반영)", 1)],
               "macro": {"KRW": 1, "SOX": 1}},
    "semi_equip": {"name": "반도체 장비·소재·부품",
                   "codes": ["042700", "240810", "403870", "058470", "095340", "039030", "357780", "005290", "036930", "140860", "322310", "089030", "131970", "067310"],
                   "proxies": [("TSM", "TSMC", "파운드리 CAPEX", 1), ("MU", "마이크론", "메모리 CAPEX", 1), ("AMAT", "어플라이드", "장비 수주 사이클", 1),
                               ("LRCX", "램리서치", "장비 수주 사이클", 1), ("KLAC", "KLA", "장비 수주 사이클", 1), ("ASML", "ASML", "노광 수주", 1),
                               ("^SOX", "필라델피아 반도체", "업황 심리 (주가만 반영)", 1)],
                   "macro": {"SOX": 1, "KRW": 1}},
    "battery": {"name": "2차전지", "codes": ["373220", "006400", "247540", "086520", "003670", "066970", "450080", "005070", "348370", "278280"],
                "proxies": [("TSLA", "테슬라", "EV 수요", 1), ("GM", "GM", "북미 EV 수요", 1), ("ALB", "앨버말", "리튬 가격(양극재 판가 연동)", 1),
                            ("LIT", "리튬·배터리 ETF", "업황 심리", 1), ("FLNC", "플루언스", "ESS 수요", 1)],
                "macro": {"KRW": 1, "CU": 0}},
    "autos": {"name": "완성차·부품", "codes": ["005380", "000270", "012330", "204320", "011210", "018880", "307950"],
              "proxies": [("TM", "도요타", "동종 사이클", 1), ("GM", "GM", "미국 판매 사이클", 1), ("F", "포드", "미국 판매 사이클", 1),
                          ("XLY", "미국 경기소비재", "미국 소비", 1)],
              "macro": {"KRW": 1, "WTI": -1}},
    "shipbuilding": {"name": "조선·기자재", "codes": ["009540", "329180", "010140", "042660", "010620", "077970", "082740", "443060", "014620", "033500", "071970"],
                     "proxies": [("FLNG", "FLEX LNG", "LNG선 운임·발주", 1), ("FRO", "프론트라인", "탱커 운임·발주", 1), ("BDRY", "건화물 운임 ETF", "벌크 운임", 1),
                                 ("NG=F", "천연가스", "LNG 프로젝트", 1), ("CL=F", "WTI", "해양 플랜트", 1), ("SLX", "철강 ETF", "후판 원가 (철강주 주가로 대신 봄)", -1)],
                     "macro": {"KRW": 1, "WTI": 1}},
    "defense": {"name": "방산·항공우주", "codes": ["012450", "064350", "047810", "079550", "272210", "103140", "099320"],
                "proxies": [("LMT", "록히드마틴", "글로벌 방산 사이클", 1), ("RTX", "RTX", "글로벌 방산 사이클", 1), ("GD", "제너럴다이내믹스", "지상 무기", 1),
                            ("RHM.DE", "라인메탈", "유럽 재무장", 1), ("ITA", "미국 방산 ETF", "업황 심리", 1)],
                "macro": {"KRW": 1}},
    "power_grid": {"name": "전력기기·전선", "codes": ["267260", "010120", "298040", "103590", "006260", "001440", "062040", "229640", "000500"],
                   "proxies": [("GEV", "GE 버노바", "전력기기 수주", 1), ("ETN", "이튼", "전력기기 수요", 1), ("VRT", "버티브", "데이터센터 전력", 1),
                               ("HUBB", "허벨", "송배전", 1), ("PWR", "콴타", "송전망 투자", 1), *HYPER, ("HG=F", "구리", "원가(판가 전가)", 0)],
                   "macro": {"KRW": 1, "CU": 0}},
    "nuclear": {"name": "원전·발전", "codes": ["034020", "052690", "051600", "083650", "105840"],
                "proxies": [("CCJ", "카메코", "우라늄·원전 사이클", 1), ("CEG", "컨스텔레이션", "원전 전력 수요", 1), ("BWXT", "BWXT", "원전 기기", 1),
                            ("SMR", "뉴스케일", "SMR 심리", 1), ("URA", "우라늄 ETF", "업황 심리", 1)],
                "macro": {"KRW": 1}},
    "bio": {"name": "바이오·제약", "codes": ["207940", "068270", "196170", "000100", "128940", "326030", "141080", "302440", "145020", "028300"],
            "proxies": [("XBI", "미국 바이오 ETF", "업황 심리·자금", 1), ("LLY", "일라이릴리", "빅파마 투자 여력", 1),
                        ("^TNX", "미 10년물", "할인율(높을수록 불리)", -1)],
            "macro": {"US10Y": -1, "KRW": 1}},
    "internet": {"name": "인터넷·게임", "codes": ["035420", "035720", "259960", "036570", "251270", "293490", "263750"],
                 "proxies": [("GOOGL", "알파벳", "광고 사이클", 1), ("META", "메타", "광고 사이클", 1), ("TTWO", "테이크투", "게임 사이클", 1),
                             ("EA", "EA", "게임 사이클", 1), ("^TNX", "미 10년물", "할인율", -1)],
                 "macro": {"US10Y": -1}},
    "banks": {"name": "금융(은행·보험)", "codes": ["105560", "055550", "086790", "316140", "024110", "138040", "032830", "000810", "005830", "029780"],
              "proxies": [("^TNX", "미 10년물", "글로벌 금리 방향 (국내 예대마진과는 간접 연결)", 1), ("KBE", "미국 은행 ETF", "글로벌 은행 사이클", 1), ("XLF", "미국 금융 ETF", "업황 심리", 1)],
              "macro": {"US10Y": 1}},
    # 증권: 금리↑는 채권 평가손 → 은행과 반대. 이익은 증시 거래대금·IB 사이클이 좌우
    "brokers": {"name": "증권", "codes": ["006800", "071050", "016360", "039490", "005940", "003530", "001720", "030610"],
                "proxies": [("IBKR", "인터랙티브브로커스", "개인 매매 활발도 사이클", 1), ("SCHW", "찰스슈왑", "리테일 증권 사이클", 1),
                            ("HOOD", "로빈후드", "개인 매매 열기", 1), ("^KS11", "코스피", "국내 거래대금 (지수로 대신 봄)", 1)],
                "macro": {"US10Y": -1}},
    "steel": {"name": "철강", "codes": ["005490", "004020", "001230", "460860"],
              "proxies": [("NUE", "뉴코어", "철강 가격 사이클", 1), ("STLD", "스틸다이내믹스", "철강 가격 사이클", 1), ("SLX", "철강 ETF", "업황", 1),
                          ("VALE", "발레", "철광석(원가)", -1), ("FXI", "중국 대형주", "중국 수요·공급", 1)],
              "macro": {"KRW": 1, "CU": 1}},
    "nonferrous": {"name": "비철·제련", "codes": ["010130", "103140"],
                   "proxies": [("HG=F", "구리", "금속 가격", 1), ("GC=F", "금", "귀금속 부산물", 1), ("SI=F", "은", "귀금속 부산물", 1), ("FXI", "중국 대형주", "중국 수요", 1)],
                   "macro": {"CU": 1, "KRW": 1}},
    "chem": {"name": "화학", "codes": ["051910", "011170", "011780", "009830", "298020", "120110"],
             "proxies": [("DOW", "다우", "석유화학 사이클", 1), ("LYB", "라이온델바젤", "석유화학 사이클", 1), ("CL=F", "WTI", "나프타 원가 (단기엔 재고평가 이익도 → 방향 불명확)", 0),
                         ("FXI", "중국 대형주", "중국 수요·증설", 1)],
             "macro": {"WTI": 0, "KRW": 1}},
    "refining": {"name": "정유", "codes": ["010950", "096770", "078930", "267250"],
                 "proxies": [("VLO", "발레로", "정제마진 사이클", 1), ("MPC", "마라톤", "정제마진 사이클", 1), ("PSX", "필립스66", "정제마진 사이클", 1),
                             ("CL=F", "WTI", "재고평가(단기)", 1)],
                 "macro": {"WTI": 1, "KRW": 1}},
    "cosmetics": {"name": "화장품·K소비재", "codes": ["090430", "051900", "192820", "161890", "278470", "257720", "018290", "214150"],
                  "proxies": [("ELF", "e.l.f.", "미국 인디 뷰티 수요", 1), ("EL", "에스티로더", "글로벌 화장품 사이클", 1), ("ULTA", "울타", "미국 뷰티 유통", 1),
                              ("FXI", "중국 대형주", "중국 소비", 1)],
                  "macro": {"KRW": 1}},
    "food": {"name": "음식료", "codes": ["003230", "097950", "271560", "004370", "007310"],
             "proxies": [("XLP", "미국 필수소비재", "소비 심리", 1), ("ZW=F", "소맥", "원재료", -1), ("ZC=F", "옥수수", "원재료", -1)],
             "macro": {"KRW": 0}},   # 수출주(삼양식품)는 원화 약세 +, 원재료 수입 내수주는 − → 업종 가정 없음
    "airline": {"name": "항공·여행", "codes": ["003490", "020560", "272450", "089590", "039130", "080160"],
                "proxies": [("JETS", "글로벌 항공 ETF", "여객 사이클", 1), ("CL=F", "WTI", "유류비", -1)],
                "macro": {"WTI": -1, "KRW": -1}},
    "it_hw": {"name": "IT 하드웨어·디스플레이", "codes": ["034220", "011070"],
              "proxies": [("AAPL", "애플", "스마트폰·기기 수요", 1), ("^SOX", "필라델피아 반도체", "IT 업황 (주가만 반영)", 1), ("DELL", "델", "PC·서버 수요", 1)],
              "macro": {"KRW": 1, "SOX": 1}},
    # 이름에 'IT 하드웨어'를 유지 — pb.py 반도체 비중 계산이 체인 이름으로 판별함
    "components": {"name": "IT 하드웨어 — 전자부품(MLCC·기판)", "codes": ["009150", "009155", "353200", "007660", "222800"],
                   "proxies": [("6981.T", "무라타", "MLCC 동일 사이클(1위 경쟁사)", 1), ("6976.T", "다이요유덴", "MLCC 동일 사이클", 1),
                               ("4062.T", "이비덴", "AI 서버 기판(FC-BGA) 사이클", 1), ("NVDA", "엔비디아", "AI 서버 수요", 1),
                               ("AAPL", "애플", "스마트폰 수요", 1), ("DELL", "델", "PC·서버 수요", 1)],
                   "macro": {"KRW": 1, "SOX": 1}},
    "appliance": {"name": "가전·전장·HVAC", "codes": ["066570", "066575"],
                  "proxies": [("WHR", "월풀", "가전 동일 사이클", 1), ("TT", "트레인", "HVAC·데이터센터 냉각", 1), ("VRT", "버티브", "데이터센터 냉각·전력", 1),
                              ("XLY", "미국 경기소비재", "미국 소비", 1)],
                  "macro": {"KRW": 1}},
    "shipping": {"name": "해운", "codes": ["011200", "028670"],
                 "proxies": [("ZIM", "짐", "컨테이너 운임 사이클", 1), ("BDRY", "건화물 운임 ETF", "벌크 운임", 1), ("CL=F", "WTI", "연료비", -1)],
                 "macro": {"KRW": 1}},
    "utility": {"name": "전력·가스 공기업", "codes": ["015760"],
                "proxies": [("CL=F", "WTI", "발전 연료비", -1), ("NG=F", "천연가스", "LNG 연료비", -1)],
                "macro": {"WTI": -1, "KRW": -1}},
    "telecom": {"name": "통신", "codes": ["017670", "030200", "032640"],
                "proxies": [("VZ", "버라이즌", "통신 방어주", 1), ("^TNX", "미 10년물", "할인율", -1)],
                "macro": {"US10Y": -1}},
    "entertainment": {"name": "엔터", "codes": ["352820", "041510", "035900", "122870"],
                      "proxies": [("LYV", "라이브네이션", "공연 수요", 1), ("SPOT", "스포티파이", "음원 수요", 1)],
                      "macro": {"KRW": 1}},
}
# None = 업종명만으로는 체인을 붙이지 않음 (틀린 체인보다 '판단 보류'가 낫다).
#  · 기타금융 = 지주사(SK스퀘어·LG·한국앤컴퍼니…) — 은행이 아님
#  · 기계·장비(농기계·공작기계…)는 전력기기 체인이 아님, 운송·창고(물류·해운)는 항공 체인이 아님
SECTOR_FALLBACK = [("기타금융", None), ("은행", "banks"), ("증권", "brokers"), ("보험", "banks"), ("금융", "banks"), ("의약", "bio"), ("제약", "bio"),
                   ("화학", "chem"), ("철강", "steel"), ("금속", "nonferrous"), ("통신", "telecom"), ("음식료", "food"), ("식품", "food"),
                   ("오락", "internet"), ("IT 서비스", "internet"), ("전기·전자", "it_hw"), ("반도체", "semi_equip"), ("운송장비", "autos"),
                   ("기계", None), ("전기장비", "power_grid"), ("운송·창고", None)]
FACTORS = {"KOSPI": ("^KS11", "코스피"), "KRW": ("KRW=X", "원/달러(상승=원화 약세)"), "WTI": ("CL=F", "WTI 유가"),
           "US10Y": ("^TNX", "미 10년 금리"), "SOX": ("^SOX", "필라델피아 반도체"), "CU": ("HG=F", "구리"),
           "SPX": ("^GSPC", "S&P500"), "DXY": ("DX-Y.NYB", "달러인덱스")}
US_LAG = {"WTI", "US10Y", "SOX", "CU", "SPX", "DXY"}   # 미국 장은 한국 장 마감 뒤 → 전일 값으로 맞춘다


def chain_of(code: str, sector: str | None) -> str | None:
    for k, c in CHAINS.items():
        if code in c["codes"]:
            return k
    for kw, k in SECTOR_FALLBACK:
        if kw in (sector or ""):
            return k   # None 이면 '체인 없음'
    return None


# ───────────── 프록시 지표 (yfinance) ─────────────

def _num(v):
    try:
        f = float(v)
        return None if math.isnan(f) or math.isinf(f) else f
    except (TypeError, ValueError):
        return None


def _eps_trend(t) -> dict | None:
    """현재 회계연도(0y)·다음연도(+1y) EPS 추정치가 30·90일 전보다 얼마나 바뀌었나."""
    try:
        et = t.eps_trend
        if et is None or len(et) == 0:
            return None
        out = {}
        for per in ("0y", "+1y"):
            if per in et.index:
                r = et.loc[per]
                cur, d30, d90 = _num(r.get("current")), _num(r.get("30daysAgo")), _num(r.get("90daysAgo"))
                out[per] = {"cur": cur, "chg30": (cur / d30 - 1) if cur and d30 and d30 > 0 else None,
                            "chg90": (cur / d90 - 1) if cur and d90 and d90 > 0 else None}
        return out or None
    except Exception:  # noqa: BLE001
        return None


def _q_yoy(df, row: str) -> tuple[float | None, str | None]:
    try:
        if df is None or row not in df.index:
            return None, None
        s = df.loc[row].dropna().sort_index()
        if len(s) < 5:
            return None, None
        a, b = float(s.iloc[-1]), float(s.iloc[-5])
        return ((a / b - 1) if b else None), str(s.index[-1].date())
    except Exception:  # noqa: BLE001
        return None, None


def _kst_now_str() -> str:
    """캐시 asof 는 KST 로 찍는다 (CI 러너 UTC 와 혼동 방지 — 신선도 계약 kst_day 기준)."""
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M")


def _now_iso() -> str:
    from datetime import timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def cache_age_h(obj: dict) -> float:
    """캐시 나이(시간) — 파일 mtime 이 아니라 **파일 안의 generated_at/asof** 기준.
    CI checkout 은 mtime 을 '지금'으로 찍어 캐시가 영원히 신선해 보였다(감사 M1 10/17: chains·us_eps 10/15 정지).
    generated_at(ISO+시간대) 우선, 없으면 asof('YYYY-MM-DD HH:MM', KST 가정). 못 읽으면 무한대(=다시 받기)."""
    from .guard import stamp
    t = stamp((obj or {}).get("generated_at")) or stamp((obj or {}).get("asof"))
    if t is None:
        return float("inf")
    from zoneinfo import ZoneInfo
    return (datetime.now(ZoneInfo("Asia/Seoul")) - t).total_seconds() / 3600


def fetch_proxies(max_age_h: float = 6) -> dict:
    """모든 체인 프록시 + 매크로 팩터: 가격 1년, EPS 추정 변화, 매출·CAPEX YoY. reports/chains.json 캐시."""
    if CACHE.exists():
        try:
            c = json.loads(CACHE.read_text(encoding="utf-8"))
            if cache_age_h(c) < max_age_h and all(v[0] in c.get("series", {}) for v in FACTORS.values()):   # 팩터가 추가됐으면 다시 받기
                return c
        except Exception:  # noqa: BLE001
            pass
    import yfinance as yf
    tick = sorted({p[0] for c in CHAINS.values() for p in c["proxies"]} | {v[0] for v in FACTORS.values()})
    px = yf.download(tick, period="14mo", interval="1d", auto_adjust=True, progress=False, threads=True, group_by="column")
    close = px["Close"] if "Close" in px else px
    hyper = {h[0] for h in HYPER}
    out = {"asof": _kst_now_str(), "generated_at": _now_iso(), "tickers": {}, "series": {}}
    for t in tick:
        if t not in close:
            continue
        s = close[t].dropna()
        if len(s) < 30:
            continue
        out["series"][t] = [[str(d.date()), round(float(v), 4)] for d, v in s.items()]
        last = float(s.iloc[-1])
        rec = {"last": last, "r1m": last / float(s.iloc[-22]) - 1 if len(s) > 22 else None,
               "r3m": last / float(s.iloc[-64]) - 1 if len(s) > 64 else None,
               "above200": bool(last > s.iloc[-200:].mean()) if len(s) >= 200 else None}
        if not (t.startswith("^") or "=" in t or t in ("LIT", "ITA", "XLY", "XLF", "KBE", "SLX", "BDRY", "URA", "XBI", "FXI", "XLP", "JETS", "XLU")):
            try:
                T = yf.Ticker(t)
                rec["eps"] = _eps_trend(T)
                inc = T.quarterly_income_stmt
                rec["rev_yoy"], rec["rev_q"] = _q_yoy(inc, "Total Revenue")
                if t in hyper:
                    cf = T.quarterly_cashflow
                    y, q = _q_yoy(cf, "Capital Expenditure")
                    rec["capex_yoy"], rec["capex_q"] = y, q
                time.sleep(0.3)
            except Exception as e:  # noqa: BLE001
                log.info("프록시 %s 상세 실패: %s", t, e)
        out["tickers"][t] = rec
    from .guard import write_json
    write_json(CACHE, out, default=str)   # asof 역행 차단 (guard-rest 10/17)
    _archive("chains", {"asof": out["asof"], "tickers": out["tickers"]})   # 시점 기록 (가격 시계열은 빼고)
    log.info("체인 프록시 %d개", len(out["tickers"]))
    return out


def _archive(kind: str, obj: dict) -> None:
    """매일 덮어쓰는 캐시를 날짜별로 남긴다 (reports/archive/<kind>/YYYY-MM-DD.json, 하루 1개·마지막 실행 기준).
    나중에 '그날 화면에 떴던 값'으로 점수를 검증하려면 시점 기록이 필요하다."""
    try:
        d = REPORT_DIR / "archive" / kind
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{date.today()}.json").write_text(json.dumps(obj, ensure_ascii=False, default=str, separators=(",", ":")), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        log.info("%s 보관 실패: %s", kind, e)


def _proxy_signal(rec: dict) -> tuple[float | None, list[str]]:
    """프록시 하나의 '업황 방향' (−1~+1)과 근거."""
    parts, why = [], []
    e = (rec.get("eps") or {})
    for per, lab in (("+1y", "내년"), ("0y", "올해")):
        x = (e.get(per) or {}).get("chg90")
        if x is not None:
            parts.append(max(min(x / 0.10, 1), -1))      # 90일 ±10% 면 만점
            why.append(f"{lab} EPS 추정 90일 {x*100:+.1f}%")
            break
    if rec.get("capex_yoy") is not None:
        parts.append(max(min(rec["capex_yoy"] / 0.4, 1), -1))
        why.append(f"CAPEX YoY {rec['capex_yoy']*100:+.0f}% ({rec.get('capex_q')})")
    elif rec.get("rev_yoy") is not None:
        parts.append(max(min(rec["rev_yoy"] / 0.3, 1), -1) * 0.7)
        why.append(f"매출 YoY {rec['rev_yoy']*100:+.0f}% ({rec.get('rev_q')})")
    if rec.get("r3m") is not None:
        parts.append(max(min(rec["r3m"] / 0.25, 1), -1) * 0.6)
        why.append(f"3개월 {rec['r3m']*100:+.0f}%")
    if not parts:
        return None, why
    return sum(parts) / len(parts), why


def chain_view(key: str, prox: dict) -> dict:
    c = CHAINS[key]
    rows, sc = [], []
    for t, name, role, rel in c["proxies"]:
        rec = prox["tickers"].get(t)
        if not rec:
            continue
        s, why = _proxy_signal(rec)
        rows.append({"ticker": t, "name": name, "role": role, "relation": rel, "signal": round(s, 2) if s is not None else None,
                     "effect": round(s * rel, 2) if s is not None else None, "why": " · ".join(why)})
        if s is not None and rel:
            sc.append(s * rel)
    score = sum(sc) / len(sc) if sc else None
    return {"key": key, "name": c["name"], "score": round(score, 2) if score is not None else None, "proxies": rows}


# ───────────── 매크로 민감도 ─────────────

def _ols1(y, x):
    n = len(y)
    if n < 60:
        return None, None
    mx, my = sum(x) / n, sum(y) / n
    sxx = sum((a - mx) ** 2 for a in x)
    if sxx <= 0:
        return None, None
    b = sum((a - mx) * (c - my) for a, c in zip(x, y)) / sxx
    res = [c - my - b * (a - mx) for a, c in zip(x, y)]
    s2 = sum(r * r for r in res) / (n - 2)
    se = math.sqrt(s2 / sxx) if s2 > 0 else None
    return b, (b / se if se else None)


def _rets(series: list[list]) -> dict[str, float]:
    out, prev = {}, None
    for d, v in series:
        if prev and v and prev > 0:
            out[d] = math.log(v / prev)
        prev = v
    return out


def macro_sens(prices: pl.DataFrame, prox: dict, market: str = "KR") -> dict[str, dict]:
    """종목별: 시장 제거 잔차 수익률의 팩터 베타·t값 (최근 1년). prices: yf,date,close.
    KR: 시장=코스피, 미국 팩터는 전일 값. US: 시장=S&P500, 같은 날짜, 원화 제외."""
    mkey = "KOSPI" if market == "KR" else "SPX"
    fr = {}
    for k, (t, _) in FACTORS.items():
        if market == "US" and k in ("KOSPI", "KRW"):
            continue
        ser = prox["series"].get(t)
        if not ser:
            continue
        r = _rets(ser)
        if market == "KR" and k in US_LAG:   # 한국 날짜 d 에는 미국 d−1 거래일 값을 쓴다
            ds = sorted(r)
            r = {ds[i + 1]: r[ds[i]] for i in range(len(ds) - 1)}
        fr[k] = r
    if mkey not in fr:
        return {}
    since = str(date.today() - timedelta(days=380))
    out = {}
    p = prices.filter(pl.col("date") >= date.fromisoformat(since)).sort("yf", "date")
    for (yf_,), g in p.group_by("yf", maintain_order=True):
        ds = [str(d) for d in g["date"].to_list()]
        cl = g["close"].to_list()
        rs = {ds[i]: math.log(cl[i] / cl[i - 1]) for i in range(1, len(ds)) if cl[i] and cl[i - 1]}
        common = [d for d in rs if d in fr[mkey]]
        if len(common) < 120:
            continue
        y = [rs[d] for d in common]
        m = [fr[mkey][d] for d in common]
        bm, _ = _ols1(y, m)
        if bm is None:
            continue
        resid = {d: rs[d] - bm * fr[mkey][d] for d in common}
        rec = {"beta_mkt": round(bm, 2)}
        for k, r in fr.items():
            if k == mkey:
                continue
            cd = [d for d in common if d in r]
            b, tv = _ols1([resid[d] for d in cd], [r[d] for d in cd])
            if b is not None:
                rec[k] = {"beta": round(b, 3), "t": round(tv, 1) if tv is not None else None}
        out[yf_.split(".")[0]] = rec
    return out


def factor_moves(prox: dict) -> dict[str, dict]:
    out = {}
    for k, (t, name) in FACTORS.items():
        rec = prox["tickers"].get(t)
        if rec:
            out[k] = {"name": name, "r1m": rec.get("r1m"), "r3m": rec.get("r3m"), "last": rec.get("last")}
    return out


# ───────────── 애널리스트 본문 드라이버 ─────────────
DRV = {   # 드라이버: 키워드
    "환율": r"환율|원화|달러|원/달러|원달러",
    "원자재·원가": r"원자재|원재료|원가|재료비|유가|납사|나프타|철광석|리튬|구리|전력비|인건비",
    "판가·ASP": r"판가|ASP|가격 인상|가격인상|단가|가격 상승|가격 하락|가격 인하|계약가|고정거래가격",
    "물량·수요": r"물량|출하|판매량|수요|주문|수주|가동률|선적|bit growth|빗그로스",
    "재고": r"재고",
    "경쟁·점유율": r"경쟁|점유율|중국 업체|중국업체|추격|신규 진입",
    "관세·규제": r"관세|규제|제재|IRA|보조금|수출 통제|반덤핑",
    "믹스·제품": r"믹스|HBM|고부가|프리미엄|신제품|EV|HEV|ESS",
    "일회성": r"일회성|충당금|환입|성과급|손상|처분이익",
    "CAPEX·증설": r"증설|투자|CAPEX|캐파|설비",
}
UP = r"상승|증가|개선|확대|호조|강세|상향|회복|인상|타이트|부족|서프라이즈|상회|성장|견조"
DN = r"하락|감소|악화|축소|부진|약세|하향|둔화|인하|부담|과잉|쇼크|하회|역성장|우려|리스크|희석"


def text_drivers(texts: list[str]) -> dict[str, dict]:
    """문장 단위로 드라이버 키워드와 방향 단어가 함께 나오면 집계. {드라이버: {up, dn, ex}}"""
    out: dict[str, dict] = {}
    for t in texts:
        for sent in re.split(r"(?<=[다요])\.\s*|\n|(?<=[.!?])\s+", t or ""):
            if len(sent) < 8:
                continue
            for d, pat in DRV.items():
                if not re.search(pat, sent):
                    continue
                u, n = len(re.findall(UP, sent)), len(re.findall(DN, sent))
                if not (u or n):
                    continue
                o = out.setdefault(d, {"up": 0, "dn": 0, "ex": []})
                if u > n:
                    o["up"] += 1
                elif n > u:
                    o["dn"] += 1
                if len(o["ex"]) < 2:
                    o["ex"].append(sent.strip()[:140])
    return out


def analyst_view(code: str, store: pl.DataFrame | None, rjson: dict) -> dict | None:
    """최근 90일 리포트: 목표가 변화·톤·본문 드라이버."""
    items = [x for x in rjson.get("items", []) if x.get("code") == code]
    if not items:
        return None
    cut = str(date.today() - timedelta(days=90))
    items = [x for x in items if x.get("date", "") >= cut]
    if not items:
        return None
    ups = sum(1 for x in items if (x.get("tp_chg") or 0) > 0.001)
    dns = sum(1 for x in items if (x.get("tp_chg") or 0) < -0.001)
    opu = sum(1 for x in items if (x.get("op_chg") or 0) > 0.001)
    opd = sum(1 for x in items if (x.get("op_chg") or 0) < -0.001)
    tones = {}
    for x in items:
        tones[x.get("tone") or "—"] = tones.get(x.get("tone") or "—", 0) + 1
    texts = [" ".join(filter(None, [x.get("title"), x.get("thesis"), x.get("view"), x.get("risk"), x.get("summary"),
                                   " ".join(x.get("evidence") or [])])) for x in items]
    td = text_drivers(texts)
    cons = sum(1 for t in texts if re.search(r"컨센서스\s*(를|을)?\s*(상회|웃돌)|서프라이즈", t))
    miss = sum(1 for t in texts if re.search(r"컨센서스\s*(를|을)?\s*(하회|밑돌)|쇼크", t))
    score_parts = []
    if ups + dns:
        score_parts.append((ups - dns) / (ups + dns))
    if opu + opd:
        score_parts.append((opu - opd) / (opu + opd))
    if cons + miss:
        score_parts.append((cons - miss) / (cons + miss))
    tone_s = {"낙관": 1, "긍정(유지)": 0.5, "신중한 매수": 0, "사실상 중립": -0.5, "중립": -0.5, "매도": -1}
    tv = [tone_s[x.get("tone")] for x in items if x.get("tone") in tone_s]
    if tv:
        score_parts.append(sum(tv) / len(tv))
    return {"n": len(items), "tp_up": ups, "tp_dn": dns, "op_up": opu, "op_dn": opd, "beat": cons, "miss": miss,
            "tones": tones, "drivers": td,
            "score": round(sum(score_parts) / len(score_parts), 2) if score_parts else None,
            "latest": [{"date": x["date"], "broker": x.get("broker"), "tone": x.get("tone"), "view": x.get("view") or x.get("thesis") or x.get("title")}
                       for x in sorted(items, key=lambda z: z["date"], reverse=True)[:4]]}


# ───────────── 뉴스 ─────────────
NEWS_RULES = [   # (패턴, 이벤트, 방향) — 첫 번째로 맞는 규칙만 쓰므로 '감소·취소·완화' 같은 반대말 규칙을 먼저 둔다
    (r"수주\s*(감소|부진|급감|가뭄|절벽|취소|해지|무산)|계약\s*(해지|취소|해제|무산)", "수주 부진·계약 해지", -1),
    (r"관세\s*(인하|완화|철폐|면제|유예|타결|합의)|관세\s*협상\s*타결", "관세 완화", 1),
    (r"감산\s*(종료|철회|완화)", "감산 종료", 0),
    (r"가격\s*인상|판가\s*(인상|상승)|가격\s*상승|값\s*(올|상승)|계약가\s*상승", "판가 상승", 1),
    (r"가격\s*(인하|하락)|판가\s*(인하|하락)|값\s*(내|하락)|덤핑", "판가 하락", -1),
    (r"수주|공급\s*계약|계약\s*체결|납품\s*계약|낙찰", "수주·계약", 1),
    (r"증설|공장\s*(신설|착공)|생산능력\s*확대|캐파", "증설", 1),
    (r"감산", "감산", 0),
    (r"재고\s*(증가|누적|과잉)", "재고 증가", -1),
    (r"재고\s*(감소|소진|정상화)", "재고 감소", 1),
    (r"공급\s*(부족|난)|품귀|쇼티지|완판", "공급 부족", 1),
    (r"공급\s*과잉|수요\s*(둔화|부진|감소)|주문\s*(감소|취소)", "수요 둔화", -1),
    (r"수요\s*(증가|급증|확대)|주문\s*(증가|급증)", "수요 증가", 1),
    (r"관세|반덤핑|수출\s*(통제|규제)|제재", "관세·규제", -1),
    (r"어닝\s*서프라이즈|깜짝\s*실적|사상\s*최대|최대\s*실적|컨센서스\s*상회|호실적|실적\s*(개선|호조|기대|성장)|흑자\s*전환|이익\s*(급증|증가)", "실적 개선", 1),
    (r"어닝\s*쇼크|실적\s*(부진|악화|우려|둔화|감소)|적자\s*(전환|확대|지속)|컨센서스\s*하회|이익\s*(급감|감소)", "실적 악화", -1),
    (r"수출\s*(증가|호조|급증|최대)|판매\s*(증가|호조|급증)|출하\s*(증가|확대)|점유율\s*(확대|상승|1위)", "판매·수출 호조", 1),
    (r"수출\s*(감소|부진|급감)|판매\s*(감소|부진|급감)|출하\s*(감소|부진)|점유율\s*(하락|축소)", "판매·수출 부진", -1),
    (r"투자\s*(확대|늘|증액)|CAPEX\s*(확대|증가)|발주\s*(확대|증가|재개)", "고객 투자 확대", 1),
    (r"투자\s*(축소|삭감|보류|연기)|발주\s*(감소|취소|지연)", "고객 투자 축소", -1),
    (r"목표가\s*(상향|올)", "목표가 상향", 1),
    (r"목표가\s*(하향|내)", "목표가 하향", -1),
    (r"유상\s*증자|전환사채|CB\s*발행|블록딜|오버행", "희석·오버행", -1),
    (r"소송|리콜|파업|화재|사고|과징금", "소송·사고", -1),
    (r"인수|합병|M&A", "M&A", 0),
]
CHAIN_OVERRIDE = {"memory": {"감산": 1}, "chem": {"감산": 1}, "steel": {"감산": 1}}


def news_events(titles: list[dict], chain: str | None) -> dict:
    ov = CHAIN_OVERRIDE.get(chain or "", {})
    ev, sc = [], []
    for it in titles:
        t = it.get("title", "")
        for pat, name, d in NEWS_RULES:
            if re.search(pat, t):
                d = ov.get(name, d)
                ev.append({"date": it.get("date"), "title": t[:120], "event": name, "dir": d, "link": it.get("link")})
                if d:
                    sc.append(d)
                break
    # 헤드라인 1~2건이 점수를 ±1로 만들지 않게 건수가 적으면 0 쪽으로 줄임 (3건 이상에서 온전히 반영)
    score = sum(sc) / len(sc) * min(1.0, len(sc) / 3) if sc else None
    return {"n": len(titles), "events": ev[:12], "score": round(score, 2) if score is not None else None, "n_scored": len(sc),
            "recent": [{"date": x.get("date"), "title": x.get("title", "")[:110], "link": x.get("link")} for x in titles[:8]]}


def fetch_news(name: str, code: str, days: int = 7) -> list[dict]:
    """네이버 종목 뉴스(모바일 API) 최근 n일, 실패하면 Google News RSS."""
    import requests
    cut = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
    try:
        r = requests.get(f"https://m.stock.naver.com/api/news/stock/{code}?pageSize=30&page=1",
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        if r.status_code == 200:
            out, seen = [], set()
            for grp in r.json() or []:
                for it in grp.get("items", []) if isinstance(grp, dict) else []:
                    dt = str(it.get("datetime") or "")
                    t = re.sub(r"<[^>]+>|&quot;|&amp;|&lt;|&gt;", " ", it.get("title") or "").strip()
                    if not t or dt[:8] < cut or t in seen:
                        continue
                    seen.add(t)
                    out.append({"title": t, "date": f"{dt[:4]}-{dt[4:6]}-{dt[6:8]}" if len(dt) >= 8 else None,
                                "link": f"https://n.news.naver.com/mnews/article/{it.get('officeId')}/{it.get('articleId')}",
                                "src": it.get("officeName")})
            if out:
                return out
    except Exception:  # noqa: BLE001
        pass
    return _google_news(name, days)


def _google_news(name: str, days: int = 7) -> list[dict]:
    """Google News RSS (한국어) 최근 n일. 실패 시 []."""
    import html
    import urllib.parse

    import requests
    q = urllib.parse.quote(f"\"{name}\" when:{days}d")
    try:
        r = requests.get(f"https://news.google.com/rss/search?q={q}&hl=ko&gl=KR&ceid=KR:ko",
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        if r.status_code != 200:
            return []
        out = []
        for m in re.finditer(r"<item>(.*?)</item>", r.text, re.S):
            body = m.group(1)
            t = re.search(r"<title>(.*?)</title>", body, re.S)
            ln = re.search(r"<link>(.*?)</link>", body, re.S)
            pd = re.search(r"<pubDate>(.*?)</pubDate>", body, re.S)
            title = html.unescape(re.sub(r"<!\[CDATA\[|\]\]>", "", t.group(1))) if t else ""
            title = re.sub(r"\s+-\s+[^-]+$", "", title)   # " - 언론사" 제거
            d = None
            if pd:
                try:
                    d = datetime.strptime(pd.group(1).strip()[:25], "%a, %d %b %Y %H:%M:%S").strftime("%Y-%m-%d")
                except ValueError:
                    pass
            out.append({"title": title, "link": ln.group(1).strip() if ln else None, "date": d})
        return out[:40]
    except Exception:  # noqa: BLE001
        return []


# ───────────── 공시 ─────────────

def dart_view(items: list[dict]) -> dict | None:
    if not items:
        return None
    ev, sc = [], []
    for x in items[:12]:
        t = (x.get("title") or x.get("report_nm") or "") + " " + (x.get("type") or "")
        if re.search(r"해지|취소|해제", t) and re.search(r"단일판매|공급계약", t):
            ev.append(("공급계약 해지", -1, x))
        elif re.search(r"단일판매|공급계약", t):
            ev.append(("수주·공급계약", 1, x))
        elif re.search(r"신규시설투자|시설투자", t):
            ev.append(("시설투자", 1, x))
        elif re.search(r"유상증자|전환사채|신주인수권|교환사채", t):
            ev.append(("희석", -1, x))
        elif re.search(r"자기주식.*(취득|소각)", t):
            ev.append(("자사주 매입·소각", 0, x))
        elif re.search(r"영업\(잠정\)실적|잠정실적", t):
            ev.append(("잠정실적", 0, x))
    for _, d, _x in ev:
        if d:
            sc.append(d)
    return {"events": [{"event": e, "dir": d, "date": x.get("date"), "title": x.get("title") or x.get("report_nm")} for e, d, x in ev],
            "score": round(sum(sc) / len(sc), 2) if sc else None}


# ───────────── 종합 ─────────────
SIG_T = 3.0   # 매크로 '실측 민감도' 인정 기준 (다중검정 보정 대신 보수적 문턱)
W = {"chain": 0.35, "analyst": 0.25, "news": 0.15, "macro": 0.15, "dart": 0.10}


def macro_view(sens: dict | None, moves: dict, prior: dict, mkey: str = "KOSPI") -> dict | None:
    if not sens and not prior:
        return None
    rows, sc = [], []
    for k, mv in moves.items():
        if k in ("KOSPI", mkey) or mv.get("r1m") is None or (mkey == "SPX" and k == "KRW"):
            continue
        s = (sens or {}).get(k) or {}
        b, tv = s.get("beta"), s.get("t")
        # 약 1,000종목 × 7팩터를 한꺼번에 거르므로 |t|≥2 는 우연 통과가 많다 → 3 이상만 '실측'으로 인정
        sig = tv is not None and abs(tv) >= SIG_T
        pr = prior.get(k)
        if not sig and pr is None:
            continue
        sign = (1 if b > 0 else -1) if sig else pr
        if not sign:
            rows.append({"factor": k, "name": mv["name"], "r1m": mv["r1m"], "beta": b, "t": tv, "effect": 0,
                         "why": "참고 (방향 가정 없음)"})
            continue
        shrink, tag = 1.0, "실측 민감도"
        if not sig:
            if b is not None and tv is not None and b * pr < 0 and abs(tv) >= 1:
                # 업종 가정과 실측 방향이 반대 → 가정으로 덮어쓰지 않음
                rows.append({"factor": k, "name": mv["name"], "r1m": mv["r1m"], "beta": b, "t": tv, "effect": 0,
                             "why": "업종 가정과 실측 방향이 반대 → 반영 안 함"})
                continue
            shrink, tag = 0.5, "업종 가정(실측 약함 → 절반만)"
        if k == "US10Y" and mv.get("last"):
            # 금리는 수준의 %변화가 아니라 bp 변화로 (4.8%→5.04% 는 +24bp, '+5%' 가 아님). 25bp = 만점
            bp = (mv["last"] - mv["last"] / (1 + mv["r1m"])) * 100
            eff = max(min(sign * bp / 25, 1), -1) * shrink
            mv_txt = f"1개월 {bp:+.0f}bp"
        else:
            eff = max(min(sign * mv["r1m"] / 0.05, 1), -1) * shrink
            mv_txt = f"1개월 {mv['r1m']*100:+.1f}%"
        sc.append(eff)
        rows.append({"factor": k, "name": mv["name"], "r1m": mv["r1m"], "beta": b, "t": tv, "effect": round(eff, 2),
                     "why": f"{tag} · {mv_txt}"})
    return {"rows": rows, "score": round(sum(sc) / len(sc), 2) if sc else None,
            "beta_mkt": (sens or {}).get("beta_mkt")}


W_US = {"chain": 0.25, "eps": 0.45, "rev": 0.15, "macro": 0.15}


def combine(parts: dict[str, float | None], weights: dict | None = None) -> tuple[float | None, dict]:
    num = den = 0.0
    used = {}
    for k, w in (weights or W).items():
        v = parts.get(k)
        if v is None:
            continue
        num += w * v
        den += w
        used[k] = round(w, 2)
    if den < 0.3:   # 근거가 너무 적으면 판단 보류
        return None, used
    return num / den, used


def build(codes_info: dict[str, dict], prices: pl.DataFrame, discl: dict, news_limit: int = 400) -> dict[str, dict]:
    """codes_info: {code: {name, sector, mcap}} → {code: drivers}"""
    try:
        prox = fetch_proxies()
    except Exception as e:  # noqa: BLE001
        log.warning("체인 프록시 실패: %s", e)
        prox = {"tickers": {}, "series": {}}
    chains = {k: chain_view(k, prox) for k in CHAINS}
    moves = factor_moves(prox)
    try:
        sens = macro_sens(prices, prox)
    except Exception as e:  # noqa: BLE001
        log.warning("매크로 민감도 실패: %s", e)
        sens = {}
    try:
        rjson = json.loads((REPORT_DIR / "research.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        rjson = {"items": []}
    # 뉴스: 체인 지정 종목 + 시총 상위
    news_targets = {c for ch in CHAINS.values() for c in ch["codes"]}
    top = sorted(codes_info, key=lambda c: -(codes_info[c].get("mcap") or 0))[:news_limit]
    news_targets = [c for c in codes_info if c in news_targets or c in set(top)]
    news: dict[str, list] = {}
    for i, c in enumerate(news_targets):
        news[c] = fetch_news(codes_info[c]["name"], c)
        time.sleep(0.4)
    log.info("뉴스 %d종목 (헤드라인 %d건)", len(news), sum(len(v) for v in news.values()))
    # 셀사이드는 구조적으로 낙관적 → 전 종목 평균 대비 상대 점수로 쓴다
    avs = {c: analyst_view(c, None, rjson) for c in codes_info}
    base_a = [v["score"] for v in avs.values() if v and v.get("score") is not None]
    a_mean = sum(base_a) / len(base_a) if len(base_a) >= 10 else 0.0
    out = {}
    for c, info in codes_info.items():
        ck = chain_of(c, info.get("sector"))
        ch = chains.get(ck) if ck else None
        prior = dict(CHAINS[ck]["macro"]) if ck else {"KRW": 0}
        mv = macro_view(sens.get(c), moves, prior)
        av = avs.get(c)
        if av and av.get("score") is not None:
            av["score_raw"] = av["score"]
            av["score"] = round(max(min(av["score"] - a_mean, 1), -1), 2)
            av["base"] = round(a_mean, 2)
        nv = news_events(news.get(c, []), ck) if c in news else None
        dv = dart_view(discl.get(c, []))
        parts = {"chain": ch.get("score") if ch else None, "analyst": av.get("score") if av else None,
                 "news": nv.get("score") if nv and nv.get("n_scored", 0) >= 1 else None,
                 "macro": mv.get("score") if mv else None, "dart": dv.get("score") if dv else None}
        score, used = combine(parts)
        out[c] = {"chain": ch, "macro": mv, "analyst": av, "news": nv, "dart": dv, "parts": parts, "weights": used,
                  "score": round(score, 2) if score is not None else None,
                  "w_current": round(min(max(0.5 + 0.4 * score, 0.1), 0.9), 2) if score is not None else None}
    usmap = {}   # 미국 종목 → 체인 (같은 사이클로 묶이는 프록시만)
    for k, c in CHAINS.items():
        for t, _n, role, rel in c["proxies"]:
            if rel == 1 and not t.startswith("^") and "=" not in t and t not in usmap and ("사이클" in role or "동일" in role):
                usmap[t] = c["name"]
    for t in ("NVDA", "AMD", "AVGO", "TSM", "AMAT", "LRCX", "KLAC", "ASML", "INTC", "QCOM", "TXN", "ADI", "MRVL", "ARM", "SMH", "SOXX", "PSI", "SOXL"):
        usmap.setdefault(t, "미국 반도체")
    (REPORT_DIR / "chains_view.json").write_text(json.dumps({"asof": prox.get("asof"), "chains": chains, "factors": moves, "us_map": usmap},
                                                            ensure_ascii=False, default=str), encoding="utf-8")
    return out


# ───────────── 미장 종목 ─────────────
US_EPS = REPORT_DIR / "us_eps.json"
US_SEMI = {"NVDA", "AMD", "AVGO", "TSM", "AMAT", "LRCX", "KLAC", "ASML", "INTC", "QCOM", "TXN", "ADI", "MRVL", "ARM",
           "MCHP", "NXPI", "ON", "MPWR", "TER", "SWKS", "QRVO", "ENTG", "SNPS", "CDNS", "WDC", "STX"}


def fetch_us_eps(tickers: list[str], max_age_h: float = 6) -> dict:
    """미장 종목별 EPS 추정 변화·매출 YoY (yfinance, 병렬). reports/us_eps.json 캐시."""
    old = {}
    if US_EPS.exists():
        try:
            old = json.loads(US_EPS.read_text(encoding="utf-8"))
            if cache_age_h(old) < max_age_h and len(old.get("data", {})) >= len(tickers) * 0.8:
                return old["data"]
        except Exception:  # noqa: BLE001
            old = {}
    from concurrent.futures import ThreadPoolExecutor

    import yfinance as yf

    def one(t):
        try:
            T = yf.Ticker(t)
            rec = {"eps": _eps_trend(T)}
            y, q = _q_yoy(T.quarterly_income_stmt, "Total Revenue")
            rec["rev_yoy"], rec["rev_q"] = y, q
            try:
                rv = T.eps_revisions
                if rv is not None and len(rv) and "+1y" in rv.index:
                    r = rv.loc["+1y"]
                    rec["rev_up30"], rec["rev_dn30"] = _num(r.get("upLast30days")), _num(r.get("downLast30days"))
            except Exception:  # noqa: BLE001
                pass
            return t, rec
        except Exception:  # noqa: BLE001
            return t, None
    data = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        for t, rec in ex.map(one, tickers):
            if rec:
                data[t] = rec
    _now = _kst_now_str()
    from .guard import write_json
    write_json(US_EPS, {"asof": _now, "generated_at": _now_iso(), "data": data}, default=str)   # asof 역행 차단
    _archive("us_eps", {"asof": _now, "data": data})
    log.info("미장 EPS 추정 %d종목", len(data))
    return data


def _eps_view(rec: dict | None) -> tuple[dict | None, float | None, float | None]:
    if not rec:
        return None, None, None
    e = rec.get("eps") or {}
    parts, why = [], []
    for per, lab in (("+1y", "내년"), ("0y", "올해")):
        x = e.get(per) or {}
        if x.get("chg90") is not None:
            parts.append(max(min(x["chg90"] / 0.10, 1), -1))
            why.append(f"{lab} EPS 추정 90일 {x['chg90']*100:+.1f}%" + (f" (30일 {x['chg30']*100:+.1f}%)" if x.get("chg30") is not None else ""))
    up, dn = rec.get("rev_up30"), rec.get("rev_dn30")
    if up is not None and dn is not None and (up + dn) > 0:
        parts.append((up - dn) / (up + dn))
        why.append(f"최근 30일 내년 추정 상향 {up:.0f}건 / 하향 {dn:.0f}건")
    eps_s = sum(parts) / len(parts) if parts else None
    ry = rec.get("rev_yoy")
    rev_s = max(min(ry / 0.3, 1), -1) * 0.7 if ry is not None else None
    view = {"why": why, "rev_yoy": ry, "rev_q": rec.get("rev_q"), "up30": up, "dn30": dn,
            "eps": {k: v for k, v in e.items()}}
    return view, (round(eps_s, 2) if eps_s is not None else None), (round(rev_s, 2) if rev_s is not None else None)


def build_us(codes: list[str], prices: pl.DataFrame) -> dict[str, dict]:
    try:
        prox = fetch_proxies()
    except Exception as e:  # noqa: BLE001
        log.warning("체인 프록시 실패: %s", e)
        prox = {"tickers": {}, "series": {}}
    chains = {k: chain_view(k, prox) for k in CHAINS}
    moves = factor_moves(prox)
    try:
        sens = macro_sens(prices, prox, "US")
    except Exception as e:  # noqa: BLE001
        log.warning("미장 매크로 민감도 실패: %s", e)
        sens = {}
    usmap = {}
    for k, c in CHAINS.items():
        for t, _n, role, rel in c["proxies"]:
            if rel == 1 and ("사이클" in role or "동일" in role) and t not in usmap and not t.startswith("^") and "=" not in t:
                usmap[t] = k
    for t in US_SEMI:
        usmap.setdefault(t, "semi_equip")
    try:
        eps = fetch_us_eps(codes)
    except Exception as e:  # noqa: BLE001
        log.warning("미장 EPS 실패: %s", e)
        eps = {}
    out = {}
    for c in codes:
        ck = usmap.get(c)
        ch = chains.get(ck) if ck else None
        if ch and ck == "semi_equip" and c in US_SEMI:
            ch = {**ch, "name": "미국 반도체 (장비·파운드리 사이클)"}
        prior = {"US10Y": -1} if c in US_SEMI or ck else {}
        mv = macro_view(sens.get(c), moves, prior, "SPX")
        ev, eps_s, rev_s = _eps_view(eps.get(c))
        parts = {"chain": ch.get("score") if ch else None, "eps": eps_s, "rev": rev_s, "macro": mv.get("score") if mv else None}
        score, used = combine(parts, W_US)
        out[c] = {"market": "US", "chain": ch, "macro": mv, "eps": ev, "parts": parts, "weights": used,
                  "score": round(score, 2) if score is not None else None,
                  "w_current": round(min(max(0.5 + 0.4 * score, 0.1), 0.9), 2) if score is not None else None}
    log.info("미장 이익 드라이버 %d종목", len(out))
    return out
