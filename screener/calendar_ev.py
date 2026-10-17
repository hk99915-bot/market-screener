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

from .config import REPORT_DIR

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
    y = date.today().year
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
    return (date.today() - d).days <= max_days


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
    r = requests.get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}", timeout=(10, 60),
                     headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36", "Accept": "text/csv,*/*"})
    r.raise_for_status()
    out = []
    for row in list(csv.reader(io.StringIO(r.text)))[1:]:
        try:
            out.append((row[0], float(row[1])))
        except (ValueError, IndexError):
            continue
    if not _fresh(out, 200):
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
    today = str(date.today())
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
    today = date.today()
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
    today = date.today()
    end = today + timedelta(days=days)
    start = today - timedelta(days=60)
    ev = []
    # 지난 실적 일정은 야후가 다음 예정일만 주므로 이전 calendar.json 에서 이어받음
    try:
        prev = json.loads(OUT.read_text(encoding="utf-8")).get("events", [])
        ev += [e for e in prev if e.get("type") == "실적" and start <= date.fromisoformat(e["date"]) < today - timedelta(days=1)]
    except Exception:  # noqa: BLE001
        pass
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
        ev.append(e)
    seen = set()
    ev = [e for e in ev if not ((e["date"], e["name"]) in seen or seen.add((e["date"], e["name"])))]
    ev.sort(key=lambda e: (e["date"], -e["imp"]))
    try:
        _attach(ev, releases())
    except Exception as e:  # noqa: BLE001
        log.warning("지표 결과 실패: %s", e)
    out = {"asof": datetime.now().strftime("%Y-%m-%d %H:%M"), "events": ev, "moves": _moves(),
           "note": "실적일은 야후 기준 예정일(회사 확정 전 추정 포함) — '회사 확정' 표시분은 회사 발표로 확인. 매크로 일정은 연준·BLS·BEA 공식 일정 기준."}
    OUT.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    log.info("캘린더 %d건", len(ev))
    return out


def upcoming(n_days: int = 2) -> list[dict]:
    try:
        ev = json.loads(OUT.read_text(encoding="utf-8")).get("events", [])
    except Exception:  # noqa: BLE001
        return []
    t = date.today()
    return [e for e in ev if t <= date.fromisoformat(e["date"]) <= t + timedelta(days=n_days)]
