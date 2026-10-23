"""실적·이벤트 캘린더 → reports/calendar.json

- 미국 매크로: FOMC·CPI·고용·PCE·GDP (공식 일정 기준 수기 입력, 출처: fedratecalc.com 2026-09 확인 / 연준·BLS·BEA 일정)
- 국내 파생 만기: 매월 둘째 목요일 (3·6·9·12월은 동시만기)
- 실적 발표일: 야후 calendar (미국 빅테크·반도체, 국내 시총 상위) — 예정일은 회사 공시 전 추정치일 수 있음
"""
from __future__ import annotations

import json
import re
import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .config import REPORT_DIR

KST = ZoneInfo("Asia/Seoul")


def _today() -> date:
    """KST 오늘. 러너는 UTC 라 date.today()·datetime.now() 가 09:00 KST 전엔 전날 — 10/19·10/20 premarket(08:58 KST) 캘린더 asof 가 전날로 찍혀 신선도 '늦음' 오탐(10/21 개발)."""
    return datetime.now(KST).date()

log = logging.getLogger(__name__)
OUT = REPORT_DIR / "calendar.json"
MACRO = [   # (날짜 KST 기준, 이름, 메모, 중요도)  — 미국 발표는 한국 시간 다음날 새벽/밤
    ("2026-09-16", "FOMC 금리 결정", "9/16 14:00 ET → 한국 9/17 03:00", 3),
    ("2026-10-02", "미 고용보고서(9월)", "BLS 일정 확인 · 08:30 ET → 한국 21:30", 2),
    ("2026-10-14", "미 CPI(9월)", "BLS 일정 확인 · 08:30 ET → 한국 21:30", 3),
    ("2026-10-15", "미 PPI(9월)", "BLS 일정 확인 · 08:30 ET → 한국 21:30", 2),
    ("2026-10-15", "미 소매판매(9월)·신규 실업수당", "08:30 ET → 한국 21:30 · 소비 둔화 여부", 2),
    ("2026-10-16", "연준 의장 Warsh 연설", "통화정책 방향 단서 · 시각은 원문 확인", 3),
    ("2026-10-19", "중국 3Q GDP·산업생산·소매판매", "한국 11:00 · 한국 수출주 수요", 2),
    ("2026-10-20", "미 주택착공·건축허가", "08:30 ET → 한국 21:30", 1),
    ("2026-10-28", "FOMC 금리 결정", "10/28 14:00 ET → 한국 10/29 03:00", 3),
    ("2026-10-29", "미 PCE·GDP(3Q 속보)", "08:30 ET → 한국 21:30", 2),
    ("2026-11-06", "미 고용보고서(10월)", "08:30 ET → 한국 22:30", 2),
    ("2026-11-10", "미 CPI(10월)", "08:30 ET → 한국 22:30", 3),
    ("2026-11-25", "미 PCE·GDP(3Q 잠정)", "08:30 ET → 한국 22:30", 1),
    ("2026-12-04", "미 고용보고서(11월)", "08:30 ET → 한국 22:30", 2),
    ("2026-12-09", "FOMC 금리 결정", "12/9 14:00 ET → 한국 12/10 04:00", 3),
    ("2026-12-10", "미 CPI(11월)", "08:30 ET → 한국 22:30", 3),
    ("2026-12-23", "미 PCE·GDP(3Q 확정)", "08:30 ET → 한국 22:30", 1),
    # 일본은행(BOJ) 금융정책결정회의 — 결정 발표일(회의 둘째 날, 보통 정오 전후 KST). 출처: boj.or.jp/en/mopo/mpmsche_minu (2026-10-15 확인)
    ("2026-10-30", "BOJ 금리 결정 (+전망 보고서)", "10/29~30 회의 · 엔화·엔 캐리 변수", 3),
    ("2026-12-18", "BOJ 금리 결정", "12/17~18 회의 · 엔화·엔 캐리 변수", 2),
    ("2027-01-22", "BOJ 금리 결정 (+전망 보고서)", "1/21~22 회의 · 엔화·엔 캐리 변수", 3),
    ("2027-03-18", "BOJ 금리 결정", "3/17~18 회의 · 엔화·엔 캐리 변수", 2),
    ("2027-04-28", "BOJ 금리 결정 (+전망 보고서)", "4/27~28 회의 · 엔화·엔 캐리 변수", 3),
]
US_EARN = ["MSFT", "GOOGL", "AMZN", "META", "AAPL", "NVDA", "AVGO", "AMD", "MU", "SNDK", "TSM", "ASML", "AMAT", "LRCX", "KLAC",
           "TSLA", "INTC", "QCOM", "ORCL", "CRM", "NFLX", "WDC", "STX", "DELL", "SMCI", "ARM", "MRVL", "GEV", "VRT", "ETN"]
KR_EARN = ["005930", "000660", "009150", "373220", "207940", "005380", "000270", "068270", "035420", "035720", "105560", "055550",
           "012450", "042660", "329180", "009540", "267260", "034020", "006400", "051910", "066570", "011070", "402340", "028260"]
# 회사가 발표한 실적일 (야후 추정치를 덮어씀). (날짜 KST 기준 발표일, 메모, 중요도) — 2026-10-16 애널 확인, 출처는 메모에
# 미국은 현지 장 마감 후 발표 → 한국 다음날 아침 반영
VERIFIED = {
    "000660": ("2026-10-28", "회사 확정 · 09:00 컨콜 · 컨센 영업익 약 77조(FnGuide, 10/15 기사) · 추가 주주환원 발표 여부", 3),
    "005930": ("2026-10-29", "회사 확정 · 10:00 컨콜(확정실적·사업부별) · 잠정 10/8: 매출 195조·영업익 107.4조", 3),
    "009150": ("2026-10-28", "회사 공시(10/12) · 3분기 결산 실적 · 시각은 공시 원문 확인", 2),
    "000270": ("2026-10-30", "회사 확정 · 14:10 컨콜", 2),
    "012330": ("2026-10-30", "회사 확정 · 10:10 컨콜 (10:00 자료 공시)", 1),
    "WDC": ("2026-10-22", "회사 확정 · 장 마감 후 · HDD 판가·AI 데이터센터 수요", 2),
    "STX": ("2026-10-27", "회사 확정 · 장 마감 후 · HDD 판가·AI 데이터센터 수요", 2),
    "SNDK": ("2026-10-29", "회사 확정 · 장 마감 후 컨콜 13:30 PT · 낸드 판가", 3),
    "AAPL": ("2026-11-02", "회사 확정 · 장 마감 후 · 스마트폰 부품(MLCC·카메라) 수요", 2),
    "NVDA": ("2026-11-17", "회사 일정 · 장 마감 후 · HBM 최대 수요처", 3),
}
CAPEX = {"MSFT", "GOOGL", "AMZN", "META", "ORCL"}   # 빅테크 설비투자 가이던스 — 메모리 매도 규칙과 연결
CHIP = {"NVDA", "MU", "SNDK", "AVGO", "AMD", "TSM", "ASML", "AMAT", "LRCX", "KLAC", "000660", "005930", "WDC", "STX", "ARM", "MRVL"}


# 지표 이름 → FRED 시리즈와 표시 방식 (yoy: 전년비 %, mom_k: 전월 대비 증감 천명, lvl: 수준 %)
IND = {
    "CPI": [("CPIAUCSL", "yoy", "CPI 전년비"), ("CPILFESL", "yoy", "근원 CPI 전년비")],
    "고용": [("PAYEMS", "mom_k", "비농업 고용"), ("UNRATE", "lvl", "실업률")],
    "PCE": [("PCEPI", "yoy", "PCE 물가 전년비"), ("PCEPILFE", "yoy", "근원 PCE 전년비")],
    "GDP": [("A191RL1Q225SBEA", "lvl", "GDP 성장률(연율)")],
    "FOMC": [("DFEDTARU", "lvl", "기준금리 상단")],
    "PPI": [("PPIFIS", "yoy", "PPI 최종수요 전년비")],
}
REL = REPORT_DIR / "macro_releases.json"


DBN = {"CPIAUCSL": "BLS/cu/CUSR0000SA0", "CPILFESL": "BLS/cu/CUSR0000SA0L1E", "PAYEMS": "BLS/ce/CES0000000001",
       "UNRATE": "BLS/ln/LNS14000000", "PPIFIS": "BLS/wp/WPSFD4"}


def _dbn(sid: str) -> list[tuple[str, float]]:
    import requests
    code = DBN[sid]
    r = requests.get(f"https://api.db.nomics.world/v22/series/{code}?observations=1&format=json", timeout=40)
    r.raise_for_status()
    doc = (r.json().get("series") or {}).get("docs") or []
    if not doc:
        return []
    out = []
    for per, v in zip(doc[0].get("period") or [], doc[0].get("value") or []):
        if isinstance(v, (int, float)):
            out.append((str(per), float(v)))
    return out


_BLS: dict = {}


def _bls_all() -> dict:
    """BLS 공개 API v2 (키 없이 하루 25회) — CPI·근원 CPI·고용·실업률·PPI 를 한 번에."""
    if _BLS:
        return _BLS
    import requests
    ids = {v.split("/")[-1]: k for k, v in DBN.items()}
    y = _today().year
    r = requests.post("https://api.bls.gov/publicAPI/v2/timeseries/data/", json={"seriesid": list(ids), "startyear": str(y - 2), "endyear": str(y)}, timeout=40)
    r.raise_for_status()
    for srs in (r.json().get("Results") or {}).get("series") or []:
        obs = []
        for d in srs.get("data") or []:
            if str(d.get("period", "")).startswith("M") and d.get("period") != "M13":
                try:
                    obs.append((f"{d['year']}-{d['period'][1:]}", float(d["value"])))
                except (ValueError, KeyError):
                    pass
        _BLS[ids.get(srs.get("seriesID"), srs.get("seriesID"))] = sorted(obs)
    return _BLS


def _fresh(obs: list[tuple[str, float]], max_days: int = 130) -> bool:
    if not obs:
        return False
    per = obs[-1][0][:10]
    try:
        d = date.fromisoformat(per if len(per) == 10 else per + "-01")
    except ValueError:
        return False
    return (_today() - d).days <= max_days


_FRED_DOWN: dict = {}  # 한 실행 안에서 첫 타임아웃 뒤 나머지 FRED 직접 호출 건너뜀 (releases() 시작 때 초기화)


def _fred(sid: str) -> list[tuple[str, float]]:
    """우선순위: BLS API → DBnomics → FRED. 오래된(4개월+) 값은 버림 — 미러가 멈춰 있으면 틀린 '최신값'이 됨."""
    if sid in DBN:
        try:
            o = _bls_all().get(sid) or []
            if _fresh(o):
                return o
            log.warning("BLS %s 최신 아님/없음 (%s)", sid, o[-1][0] if o else None)
        except Exception as e:  # noqa: BLE001
            log.warning("BLS %s 실패: %s", sid, e)
        try:
            o = _dbn(sid)
            if _fresh(o):
                return o
            log.warning("DBnomics %s 오래된 값 (%s) 무시", sid, o[-1][0] if o else None)
        except Exception as e:  # noqa: BLE001
            log.warning("DBnomics %s 실패: %s", sid, e)
    import csv
    import io

    import requests
    if _FRED_DOWN.get("why"):
        raise RuntimeError(f"FRED 건너뜀 — 이번 실행 앞선 실패({_FRED_DOWN['why']})")
    # UA 는 requests 기본값 — 브라우저 UA 는 FRED 가 읽기 타임아웃(10/23 실측 15초+ vs 기본 0.8초, req-data-fb0157f5)
    try:
        r = requests.get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}", timeout=(10, 20))
    except requests.Timeout as e:
        _FRED_DOWN["why"] = f"{sid} 타임아웃"
        raise RuntimeError(f"FRED {sid} 타임아웃: {e}") from e
    r.raise_for_status()
    out = []
    for row in list(csv.reader(io.StringIO(r.text)))[1:]:
        try:
            out.append((row[0], float(row[1])))
        except (ValueError, IndexError):
            continue
    # 분기 시리즈(GDP)는 날짜=분기 첫날 → 다음 속보 직전엔 ~210일 묵음이 정상 (10/23 GDP 2026-04-01 이 200일 컷에 걸림)
    q = len(out) >= 2 and out[-1][0][:7] != out[-2][0][:7] and int(out[-1][0][5:7]) % 3 == 1 and int(out[-2][0][5:7]) % 3 == 1
    if not _fresh(out, 240 if q else 200):
        raise ValueError(f"FRED {sid} 오래된 값 {out[-1][0] if out else None}")
    return out


def _calc(obs: list[tuple[str, float]], how: str) -> tuple[str, float | None, float | None]:
    if not obs:
        return "", None, None
    if how == "yoy":
        def y(i):
            return (obs[i][1] / obs[i - 12][1] - 1) * 100 if i >= 12 else None
        return obs[-1][0], y(len(obs) - 1), y(len(obs) - 2)
    if how == "mom_k":
        return obs[-1][0], obs[-1][1] - obs[-2][1], obs[-2][1] - obs[-3][1]
    if how == "lvl":
        # 일별 시리즈(기준금리)는 마지막 값과 30일 전 값
        prev = obs[-31][1] if len(obs) > 40 and len(obs[-1][0]) == 10 and obs[-1][0][8:] != "01" else obs[-2][1]
        return obs[-1][0], obs[-1][1], prev
    return obs[-1][0], obs[-1][1], None


def releases() -> dict:
    """FRED 최신값을 받아 '새 값이 처음 보인 날'을 기록 → 캘린더의 발표 이벤트에 결과로 붙임."""
    try:
        old = json.loads(REL.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        old = {"series": {}, "log": []}
    today = str(_today())
    _FRED_DOWN.clear()
    for grp, lst in IND.items():
        for sid, how, label in lst:
            try:
                per, v, pv = _calc(_fred(sid), how)
            except Exception as e:  # noqa: BLE001
                log.warning("FRED %s 실패: %s", sid, e)
                old.setdefault("errors", {})[sid] = str(e)[:200]
                continue
            if v is None:
                continue
            old.get("errors", {}).pop(sid, None)
            o = old["series"].get(sid) or {}
            if o.get("period") != per or o.get("value") != round(v, 3):
                old["log"].append({"sid": sid, "grp": grp, "label": label, "period": per, "value": round(v, 3),
                                   "prev": round(pv, 3) if pv is not None else None, "seen": today, "how": how})
            old["series"][sid] = {"grp": grp, "label": label, "period": per, "value": round(v, 3), "prev": round(pv, 3) if pv is not None else None, "how": how,
                                  "seen": o.get("seen") if o.get("period") == per else today}
    old["log"] = old["log"][-300:]
    REL.write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
    return old


# 결재 #9 (2026-10-17): 컨센서스(예상치)를 수집하지 않으므로 '서프라이즈·예상 대비·상회·하회' 표기 금지.
# 지표 발표 문장은 전부 아래 한 함수로 만든다 — '전월 대비' 변화(±%p / ±천명)만 적고, 개정 전 잠정치임을 전제한다.
BANNED_WORDS = ("서프라이즈", "컨센서스", "컨센", "예상 대비", "예상치", "상회", "하회", "깜짝")

_SURP = re.compile(r"서프라이즈|깜짝\s*실적")
_CONS = re.compile(r"컨센(서스)?|예상치|기대치|시장\s*예상")
SURP_NOTE = " (증권사 표현 인용 · 컨센서스 수치 없음)"


def surprise_guard(s):
    """'서프라이즈' 는 같은 줄에 컨센서스(예상치) 기준이 있을 때만 그대로 둔다. 없으면 '증권사 표현 인용' 꼬리표를 붙인다
    (감사 경-7 10/17 — 인용문이라 지우지 않고 근거 없음을 표시). 문자열이 아니면 그대로."""
    if not isinstance(s, str) or not _SURP.search(s) or _CONS.search(s) or SURP_NOTE.strip() in s:
        return s
    return s + SURP_NOTE


def release_line(x: dict, period: bool = False, seen: bool = False) -> str:
    """지표 발표 한 줄: '<지표> <값> (전월 <직전> → <차이>)'. prev 는 직전 발표치(월 지표면 전월, 일별 수준은 30일 전).

    예) CPI 전년비 4.02% (전월 3.71% → +0.31%p) · 비농업 고용 +29천명 (전월 +133천명 → −104천명)
    """
    v, p = x["value"], x.get("prev")
    label = x.get("label", "")
    if x.get("how") == "mom_k":
        s = f"{label} {v:+,.0f}천명"
        if p is not None:
            s += f" (전월 {p:+,.0f}천명 → {v - p:+,.0f}천명)"
    else:
        s = f"{label} {v:.2f}%"
        if p is not None:
            s += f" (전월 {p:.2f}% → {v - p:+.2f}%p)"
    if period and x.get("period"):
        s += f" · {str(x['period'])[:7]} 기준"
    if seen and x.get("seen"):
        s += f" · 발표 확인 {str(x['seen'])[5:10]}"
    return s


def _fmt(x: dict) -> str:
    return release_line(x)


def _attach(ev: list[dict], rel: dict) -> None:
    """지난 매크로 이벤트에 결과 붙이기: 발표일~+4일 사이에 처음 보인 새 값 우선, 없으면 그 지표의 가장 최근 이벤트에 현재 최신값."""
    today = _today()
    keymap = [("CPI", "CPI"), ("고용", "고용"), ("PCE", "PCE"), ("GDP", "GDP"), ("FOMC", "FOMC"), ("PPI", "PPI")]
    last_ev = {}
    for e in ev:
        if e["type"] != "매크로" or date.fromisoformat(e["date"]) >= today:   # 당일 미국 발표는 한국 밤 → 다음날부터 결과
            continue
        g = next((g for k, g in keymap if k in e["name"]), None)
        if not g:
            continue
        d0 = date.fromisoformat(e["date"])
        def ok_period(x):
            try:
                pd = date.fromisoformat(x["period"][:10] if len(x["period"]) >= 10 else x["period"] + "-01")
            except ValueError:
                return False
            return 0 <= (d0 - pd).days <= 125
        hits = [x for x in rel.get("log", []) if x["grp"] == g and ok_period(x) and d0 <= date.fromisoformat(x["seen"]) <= d0 + timedelta(days=4)]
        if hits:
            e["result"] = [_fmt(x) for x in hits]
        if g not in last_ev or e["date"] > last_ev[g]["date"]:
            last_ev[g] = e
    for g, e in last_ev.items():
        if not e.get("result"):
            d0 = date.fromisoformat(e["date"])
            cur = [x for x in rel.get("series", {}).values() if x["grp"] == g
                   and 0 <= (d0 - date.fromisoformat(x["period"][:10] if len(x["period"]) >= 10 else x["period"] + "-01")).days <= 125]
            if cur:
                e["result"] = [_fmt(x) + f" · 기준 {x['period'][:7]}" for x in cur]


def _moves(days: int = 130) -> dict:
    try:
        ser = json.loads((REPORT_DIR / "macro_series.json").read_text(encoding="utf-8")).get("series", {})
    except Exception:  # noqa: BLE001
        return {}
    out = {}
    for k in ("KOSPI", "KOSDAQ", "SPX", "NASDAQ"):
        rows = ser.get(k) or []
        c = [(str(r[0])[:10], r[4] if len(r) >= 6 else r[1]) for r in rows]
        for i in range(max(1, len(c) - days), len(c)):
            if c[i - 1][1]:
                out.setdefault(c[i][0], {})[k] = round(c[i][1] / c[i - 1][1] - 1, 4)
    return out


def _second_thursday(y: int, m: int) -> date:
    d = date(y, m, 1)
    while d.weekday() != 3:
        d += timedelta(days=1)
    return d + timedelta(days=7)


def _earn_dates(tickers: list[str], suffix: str = "") -> dict[str, str]:
    from concurrent.futures import ThreadPoolExecutor

    import yfinance as yf

    def one(t):
        try:
            cal = yf.Ticker(t + suffix).calendar
            ds = (cal or {}).get("Earnings Date") if isinstance(cal, dict) else None
            if ds:
                d = ds[0] if isinstance(ds, list) else ds
                return t, str(d)[:10]
        except Exception:  # noqa: BLE001
            pass
        return t, None
    with ThreadPoolExecutor(max_workers=8) as ex:
        return {t: d for t, d in ex.map(one, tickers) if d}


def build(days: int = 75) -> dict:
    today = _today()
    end = today + timedelta(days=days)
    start = today - timedelta(days=60)
    ev = []
    # 지난 실적 일정은 야후가 다음 예정일만 주므로 이전 calendar.json 에서 이어받음
    try:
        prev = json.loads(OUT.read_text(encoding="utf-8")).get("events", [])
        # 10/23 개발: 예전엔 '< 오늘-1' 만 이어받아, 발표 다음날 야후가 다음 분기 날짜로 넘어가면 그 이벤트가 사라졌다
        # (META·LRCX·TSLA 10/21 → 10/22 19:20 실행에서 소실). 지난 실적은 전부 이어받고, 같은 종목의 새 날짜가 30일 안이면(일정 변경) 뒤에서 버린다.
        carried = [e for e in prev if e.get("type") == "실적" and start <= date.fromisoformat(e["date"]) < today]
        ev += carried
    except Exception:  # noqa: BLE001
        prev = []
    keep = {(e.get("ticker"), e["date"]): e for e in prev if e.get("type") == "실적"}   # 발표 전 저장한 컨센·결과를 새 판으로 넘김
    for d, n, note, imp in MACRO:
        if start <= date.fromisoformat(d) <= end:
            ev.append({"date": d, "type": "매크로", "name": n, "note": note, "imp": imp})
    for k in range(-2, 4):
        y, m = (today.year + (today.month - 1 + k) // 12), ((today.month - 1 + k) % 12) + 1
        d = _second_thursday(y, m)
        if start <= d <= end:
            dual = m in (3, 6, 9, 12)
            ev.append({"date": str(d), "type": "만기", "name": "국내 " + ("선물·옵션 동시만기" if dual else "옵션 만기"),
                       "note": "장 막판 프로그램 물량 출렁임", "imp": 2 if dual else 1})
    # 서킷브레이커·사이드카 발동일 (실제 발동만: events.load() 가 오탐 정리) — 달력에 '시장 이벤트'로 표시
    try:
        from . import events as _evm
        for e in _evm.load().get("events", []):
            ty = e.get("type", "")
            if (ty.startswith("서킷") or "사이드카" in ty) and start <= date.fromisoformat(e["date"]) <= end:
                ev.append({"date": e["date"], "type": "시장 이벤트", "name": f"{e.get('market', '')} {ty} 발동",
                           "note": e.get("title", "")[:80], "imp": 3})
        for h in _evm.HISTORY:
            if start <= date.fromisoformat(h["date"]) <= end:
                ev.append({"date": h["date"], "type": "시장 이벤트", "name": "KOSPI 서킷브레이커 발동", "note": h.get("note", ""), "imp": 3})
    except Exception as e:  # noqa: BLE001
        log.warning("시장 이벤트(서킷) 달력 반영 실패: %s", e)
    names = {}
    for mk in ("KR", "US"):
        p = REPORT_DIR / "detail" / mk / "_index.json"
        if p.exists():
            names.update((json.loads(p.read_text(encoding="utf-8")).get("names") or {}))
    try:
        us = _earn_dates(US_EARN)
    except Exception as e:  # noqa: BLE001
        log.warning("미장 실적일 실패: %s", e)
        us = {}
    try:
        kr = _earn_dates(KR_EARN, ".KS")
    except Exception as e:  # noqa: BLE001
        log.warning("국장 실적일 실패: %s", e)
        kr = {}
    merged = {**us, **kr}
    for t, (vd, _n, _i) in VERIFIED.items():
        merged[t] = vd
    for t, d in merged.items():
        try:
            dd = date.fromisoformat(d)
        except ValueError:
            continue
        if not (today - timedelta(days=1) <= dd <= end):
            continue
        tags = []
        if t in CAPEX:
            tags.append("설비투자 가이던스 — 메모리 매도 규칙 체크")
        if t in CHIP:
            tags.append("반도체")
        nm = str(names.get(t, t))
        for cut in (" - ", ", Inc", ", LLC", " Inc.", " Corporation", " Corp.", " Holdings", " Holding", " PLC", " N.V.", ".com"):
            nm = nm.split(cut)[0]
        nm = nm.strip()
        vf = VERIFIED.get(t)
        imp = 3 if t in CAPEX or t in ("NVDA", "MU", "000660", "005930") else 2 if t in CHIP else 1
        e = {"date": d, "type": "실적", "name": f"{nm} 실적", "ticker": t, "market": "KR" if t.isdigit() else "US",
             "note": " · ".join(([vf[1]] if vf else []) + tags) + (" · 미국 장후 발표가 많음 → 한국 다음날 반영" if not t.isdigit() else ""),
             "imp": max(imp, vf[2]) if vf else imp}
        if vf:
            e["confirmed"] = True
        for k in ("cons", "res", "result"):
            if (keep.get((t, d)) or {}).get(k):
                e[k] = keep[(t, d)][k]
        ev.append(e)
    ev = drop_moved(ev)
    seen = set()
    ev = [e for e in ev if not ((e["date"], e["name"]) in seen or seen.add((e["date"], e["name"])))]
    ev.sort(key=lambda e: (e["date"], -e["imp"]))
    try:
        _attach(ev, releases())
    except Exception as e:  # noqa: BLE001
        log.warning("지표 결과 실패: %s", e)
    try:
        attach_earn(ev, today)
    except Exception as e:  # noqa: BLE001
        log.warning("실적 결과 첨부 실패: %s", e)
    out = {"asof": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "events": ev, "moves": _moves(),
           "note": "실적일은 야후 기준 예정일(회사 확정 전 추정 포함) — '회사 확정' 표시분은 회사 발표로 확인. 매크로 일정은 연준·BLS·BEA 공식 일정 기준."}
    OUT.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    log.info("캘린더 %d건", len(ev))
    return out


# ───────────── 실적 결과 자동 첨부 (req-dev-4f89d244, 10/23 개발) ─────────────
# 지난 실적 이벤트(발표일~+5일)에 ① 미장 EPS 실제 vs 컨센·서프라이즈(야후 earnings_dates), 매출 실제(야후 분기 손익) vs 발표 전 저장한 컨센
# ② 국장 DART 잠정실적 공시 연결(수치 파싱은 다음 단계) ③ 다음 거래일 종목 반응 %. 가이던스는 출처 있는 수집원이 없어 아직 안 붙인다(지어내지 않음).
# 실패는 조용히 넘기지 않는다: e["result"] 에 "데이터 없음(원인)" 한 줄.
EARN_WINDOW = 5      # 발표일 뒤 며칠까지 결과를 다시 찾나 (미장은 KST 다음날 아침 반영이라 +1 여유)
CONS_AHEAD = 7       # 발표 며칠 전부터 컨센(EPS·매출)을 저장하나 — 발표 뒤엔 야후 '0q' 가 다음 분기로 넘어가 사라짐
KNAME = {"META": "메타", "MSFT": "MSFT", "GOOGL": "구글", "AMZN": "아마존", "ORCL": "오라클"}


def drop_moved(ev: list[dict]) -> list[dict]:
    """이어받은 지난 실적 중, 같은 종목의 다른 날짜가 1~30일 뒤에 있으면(야후 추정일 → 정정) 지난 쪽을 버린다."""
    by = {}
    for e in ev:
        if e.get("type") == "실적" and e.get("ticker"):
            by.setdefault(e["ticker"], set()).add(e["date"])
    out = []
    for e in ev:
        if e.get("type") == "실적" and e.get("ticker") and not e.get("res"):
            d0 = date.fromisoformat(e["date"])
            if any(0 < (date.fromisoformat(d) - d0).days <= 30 for d in by[e["ticker"]]):
                continue
        out.append(e)
    return out


def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if v != v else v   # NaN


def _big(v: float | None, cur: str = "$") -> str:
    if v is None:
        return "—"
    a = abs(v)
    if cur == "$":
        return f"${v/1e9:,.1f}B" if a >= 1e9 else f"${v/1e6:,.0f}M"
    return f"{v/1e12:,.1f}조" if a >= 1e12 else f"{v/1e8:,.0f}억"


def surprise_pct(act: float | None, est: float | None) -> float | None:
    """서프라이즈 % = (실제 − 컨센) / |컨센|. 컨센 0·없음이면 None."""
    if act is None or est is None or est == 0:
        return None
    return (act - est) / abs(est)


def reaction(closes: list[tuple[str, float]], d0: str, timing: str) -> tuple[float | None, str | None]:
    """발표 반응 % — 장 마감 후(amc) 발표: 발표일 종가 → 다음 거래일 종가, 장 전(bmo): 전 거래일 종가 → 발표일 종가.
    closes = [(YYYY-MM-DD, 종가)] 오름차순. 반응일 종가가 아직 없으면 (None, None)."""
    days = [d for d, _ in closes]
    px = dict(closes)
    if timing == "bmo":
        if d0 not in px:
            return None, None
        i = days.index(d0)
        if i == 0:
            return None, None
        return px[d0] / px[days[i - 1]] - 1, d0
    base = [d for d in days if d <= d0]
    nxt = [d for d in days if d > d0]
    if not base or not nxt:
        return None, None
    return px[nxt[0]] / px[base[-1]] - 1, nxt[0]


def us_line(r: dict) -> list[str]:
    """미장 결과 dict → 표시 줄. r: eps_act·eps_est·eps_sur(%)·rev_act·rev_est·react·react_day·date_fix."""
    L = []
    if r.get("eps_act") is not None:
        sur = r.get("eps_sur")
        if sur is None:
            sur = surprise_pct(r["eps_act"], r.get("eps_est"))
        L.append(f"EPS {r['eps_act']:.2f} vs 컨센 {r['eps_est']:.2f}" if r.get("eps_est") is not None else f"EPS {r['eps_act']:.2f} (컨센 없음)")
        if sur is not None:
            L[-1] += f" ({sur*100:+.1f}%)"
    if r.get("rev_act") is not None:
        rs = surprise_pct(r["rev_act"], r.get("rev_est"))
        L.append(f"매출 {_big(r['rev_act'])}" + (f" vs 컨센 {_big(r['rev_est'])} ({rs*100:+.1f}%)" if rs is not None else " (발표 전 컨센 미저장)"))
    elif r.get("eps_act") is not None:
        L.append("매출 실제 미반영(야후 분기 손익 갱신 대기)")
    if r.get("react") is not None:
        L.append(f"주가 반응 {r['react']*100:+.1f}% ({r['react_day'][5:]} 종가)")
    elif r.get("eps_act") is not None:
        L.append("주가 반응 대기(다음 거래일 종가 전)")
    if r.get("date_fix"):
        L.append(f"발표일 정정 {r['date_fix']} (야후 earnings_dates)")
    return [" · ".join(L)] if L else []


def short(e: dict) -> str:
    """운용회의 한 줄용 짧은 결과: 'EPS +5.1% · 반응 −3.2%'."""
    r = e.get("res") or {}
    p = []
    sur = r.get("eps_sur") if r.get("eps_sur") is not None else surprise_pct(r.get("eps_act"), r.get("eps_est"))
    if sur is not None:
        p.append(f"EPS {sur*100:+.0f}%")
    if r.get("react") is not None:
        p.append(f"반응 {r['react']*100:+.1f}%")
    if r.get("dart"):
        p.append("잠정 공시")
    return "·".join(p)


def capex_line(events: list[dict], today: date) -> str:
    """미장 운용회의 '한국 메모리 판단의 선행 지표' 줄 — 날짜는 캘린더에서(하드코딩 금지, 10/23 META 불일치 재발 방지)."""
    xs = [e for e in events if e.get("type") == "실적" and e.get("ticker") in CAPEX
          and today - timedelta(days=10) <= date.fromisoformat(e["date"]) <= today + timedelta(days=21)]
    xs.sort(key=lambda e: e["date"])
    parts = []
    for e in xs:
        s = short(e)
        parts.append(f"{e['date'][5:].replace('-', '/')} {KNAME.get(e['ticker'], e['ticker'])}"
                     + ("" if e.get("confirmed") or e.get("res") else "(추정일)") + (f" {s}" if s else ""))
    cap = "빅테크 설비투자 가이던스(" + (", ".join(parts) if parts else "캘린더에 3주 안 일정 없음") + ")"
    return "한국 메모리 판단의 선행 지표: " + cap + " · 마이크론 EPS 추정 · TSMC 가이던스"


def _yf_closes(sym: str, d0: date) -> list[tuple[str, float]]:
    import yfinance as yf
    h = yf.Ticker(sym).history(start=str(d0 - timedelta(days=10)), end=str(d0 + timedelta(days=10)), auto_adjust=False)
    return [(str(i)[:10], float(c)) for i, c in zip(h.index, h["Close"]) if c == c]


def _us_cons(t: str) -> dict:
    import yfinance as yf
    tk = yf.Ticker(t)
    out = {}
    try:
        out["eps"] = _num(tk.earnings_estimate.loc["0q", "avg"])
    except Exception:  # noqa: BLE001
        pass
    try:
        out["rev"] = _num(tk.revenue_estimate.loc["0q", "avg"])
    except Exception:  # noqa: BLE001
        pass
    return {k: v for k, v in out.items() if v is not None}


def _us_fetch(t: str, d0: date, cons: dict | None) -> dict:
    """야후: earnings_dates(실제 EPS·컨센·서프라이즈·발표 시각) + 분기 손익(매출) + 종가(반응)."""
    import yfinance as yf
    tk = yf.Ticker(t)
    r: dict = {}
    ed = tk.get_earnings_dates(limit=8)
    row, when = None, None
    if ed is not None and len(ed):
        for ts, x in ed.iterrows():
            dd = ts.date() if hasattr(ts, "date") else date.fromisoformat(str(ts)[:10])
            if abs((dd - d0).days) <= 3 and _num(x.get("Reported EPS")) is not None:
                row, when = x, ts
                break
    if row is None:
        return {"err": "야후 earnings_dates 에 실제 EPS 없음(발표 전이거나 미반영)"}
    ad = when.date()
    if ad != d0:
        r["date_fix"] = str(ad)
    r["eps_act"] = _num(row.get("Reported EPS"))
    r["eps_est"] = _num(row.get("EPS Estimate"))
    sp = _num(row.get("Surprise(%)"))
    r["eps_sur"] = sp / 100 if sp is not None else None
    hr = getattr(when, "hour", 16)
    timing = "bmo" if hr < 10 else "amc"
    r["timing"] = timing
    try:
        qi = tk.quarterly_income_stmt
        if qi is not None and "Total Revenue" in qi.index:
            for col in qi.columns:
                pe = col.date() if hasattr(col, "date") else date.fromisoformat(str(col)[:10])
                if 0 < (ad - pe).days <= 100:
                    r["rev_act"] = _num(qi.loc["Total Revenue", col])
                    r["rev_period"] = str(pe)
                    break
    except Exception as e:  # noqa: BLE001
        log.info("%s 분기 매출 실패: %s", t, e)
    if cons and cons.get("rev") is not None:
        r["rev_est"] = cons["rev"]
    try:
        r["react"], r["react_day"] = reaction(_yf_closes(t, ad), str(ad), timing)
    except Exception as e:  # noqa: BLE001
        log.info("%s 반응 종가 실패: %s", t, e)
    return r


def _kr_fetch(code: str, d0: date) -> dict:
    """국장: DART 잠정실적 공시 연결(data/dart.parquet) + 발표일 반응(장 전 공시가 보통 → 전일 종가 → 발표일 종가)."""
    r: dict = {}
    try:
        import polars as pl
        from . import dart
        df = dart.load()
        if len(df):
            hit = df.filter((pl.col("code") == code) & (pl.col("date") >= d0 - timedelta(days=1)) & (pl.col("date") <= d0 + timedelta(days=4))
                            & pl.col("title").str.contains("잠정|손익구조"))
            if len(hit):
                x = hit.sort("date").row(0, named=True)
                r["dart"] = {"title": x["title"], "rcept_no": x["rcept_no"], "date": str(x["date"]), "link": dart.link(x["rcept_no"])}
    except Exception as e:  # noqa: BLE001
        log.info("%s DART 조회 실패: %s", code, e)
    try:
        r["react"], r["react_day"] = reaction(_yf_closes(code + ".KS", d0), str(d0), "bmo")
    except Exception as e:  # noqa: BLE001
        log.info("%s 반응 종가 실패: %s", code, e)
    return r


def kr_line(r: dict, note: str = "") -> list[str]:
    L = []
    if r.get("dart"):
        L.append(f"DART {r['dart']['date'][5:]} {r['dart']['title'][:30]} — 수치는 공시 원문(영업익·매출 파싱 준비 중)")
    m = re.search(r"컨센[^·]*?영업익[^·0-9]*([0-9.,]+)\s*조", note or "")
    if m:
        L.append(f"컨센 영업익 {m.group(1)}조(캘린더 메모)")
    if r.get("react") is not None:
        L.append(f"주가 반응 {r['react']*100:+.1f}% ({r['react_day'][5:]} 종가)")
    return [" · ".join(L)] if L else []


def attach_earn(ev: list[dict], today: date, fetch_us=None, fetch_kr=None, fetch_cons=None) -> int:
    """실적 이벤트: 발표 전 CONS_AHEAD 일 안이면 컨센 저장, 발표일~+EARN_WINDOW 일이면 결과 첨부(이미 반응까지 있으면 건너뜀)."""
    fetch_us = fetch_us or _us_fetch
    fetch_kr = fetch_kr or _kr_fetch
    fetch_cons = fetch_cons or _us_cons
    todo_c, todo_r = [], []
    for e in ev:
        if e.get("type") != "실적" or not e.get("ticker"):
            continue
        d0 = date.fromisoformat(e["date"])
        if e.get("market") == "US" and today <= d0 <= today + timedelta(days=CONS_AHEAD) and (e.get("cons") or {}).get("asof") != str(today):
            todo_c.append(e)
        if d0 <= today <= d0 + timedelta(days=EARN_WINDOW) and not ((e.get("res") or {}).get("react") is not None):
            todo_r.append(e)
    from concurrent.futures import ThreadPoolExecutor

    def cons(e):
        try:
            c = fetch_cons(e["ticker"])
            if c:
                e["cons"] = {**c, "asof": str(today)}
        except Exception as x:  # noqa: BLE001
            log.info("%s 컨센 저장 실패: %s", e["ticker"], x)

    def res(e):
        d0 = date.fromisoformat(e["date"])
        try:
            if e.get("market") == "US":
                r = fetch_us(e["ticker"], d0, e.get("cons"))
            else:
                r = fetch_kr(e["ticker"], d0)
        except Exception as x:  # noqa: BLE001
            r = {"err": f"{type(x).__name__}: {str(x)[:80]}"}
        if r.get("err") and not e.get("res"):
            e["result"] = [f"데이터 없음({r['err']})"]
            return
        if r.get("err"):
            return
        e["res"] = {k: v for k, v in r.items() if v is not None}
        e["result"] = us_line(r) if e.get("market") == "US" else kr_line(r, e.get("note", ""))
        if not e["result"]:
            e["result"] = ["데이터 없음(결과 수집원에 아직 없음)"]
    with ThreadPoolExecutor(max_workers=6) as ex:
        list(ex.map(cons, todo_c))
        list(ex.map(res, todo_r))
    for e in todo_r:   # 발표일 정정 — 실제 발표 시각 기준으로 옮긴다
        fx = (e.get("res") or {}).get("date_fix")
        if fx:
            e["date_orig"] = e["date"]
            e["date"] = fx
            e.setdefault("res", {}).pop("date_fix", None)
            e["note"] = (e.get("note") or "") + f" · 발표일 정정 {e['date_orig']}→{fx}(야후 earnings_dates)"
    return len(todo_r)


def upcoming(n_days: int = 2) -> list[dict]:
    try:
        ev = json.loads(OUT.read_text(encoding="utf-8")).get("events", [])
    except Exception:  # noqa: BLE001
        return []
    t = _today()
    return [e for e in ev if t <= date.fromisoformat(e["date"]) <= t + timedelta(days=n_days)]
