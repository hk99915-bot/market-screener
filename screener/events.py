"""시장 이벤트 추적 — 서킷브레이커·사이드카·급변일.

수집 (live 루프에서 10분마다)
- 네이버 주요 뉴스 헤드라인에서 '서킷브레이커'/'사이드카' 발동 기사 → 공식 발동 확인용
- 지수 등락률로 근접 경보: 코스피·코스닥 −8%(서킷 1단계 기준) / −15%(2단계) / ±5%(사이드카 근처, 실제 기준은 선물 5%·6%)
새 이벤트는 reports/events.json 에 기록하고 텔레그램으로 한 번 알림.
통계: 과거 발동일 이후 다음날·5일·20일 코스피 수익률 (reports/macro_series.json 2년 일봉으로 계산)
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from .config import REPORT_DIR

log = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")
OUT = REPORT_DIR / "events.json"
UA = {"User-Agent": "Mozilla/5.0"}
# 코스피 서킷브레이커 역대 (언론 보도 기준: 2026년 6월까지 11회)
HISTORY = [
    {"date": "2000-04-17", "market": "KOSPI", "type": "서킷브레이커", "note": "첫 발동 (미 증시 급락)"},
    {"date": "2000-09-18", "market": "KOSPI", "type": "서킷브레이커", "note": "닷컴 버블 붕괴 — 이후 253일 하락장"},
    {"date": "2001-09-12", "market": "KOSPI", "type": "서킷브레이커", "note": "9·11 테러 — 반등까지 42일"},
    {"date": "2020-03-13", "market": "KOSPI", "type": "서킷브레이커", "note": "코로나19 1차 — 다음날 반등"},
    {"date": "2020-03-19", "market": "KOSPI", "type": "서킷브레이커", "note": "코로나19 2차 — 5일 만에 회복"},
    {"date": "2024-08-05", "market": "KOSPI", "type": "서킷브레이커", "note": "엔 캐리 청산 — 직전 지수 회복 11일"},
    {"date": "2026-03-04", "market": "KOSPI", "type": "서킷브레이커", "note": "미-이란 사태, 당일 −12%"},
    {"date": "2026-03-09", "market": "KOSPI", "type": "서킷브레이커", "note": "중동발 유가 급등"},
    {"date": "2026-06-08", "market": "KOSPI", "type": "서킷브레이커", "note": "미 금리 인상 우려·반도체 급락"},
    {"date": "2026-06-23", "market": "KOSPI", "type": "서킷브레이커", "note": "미 기술주 약세"},
    {"date": "2026-06-26", "market": "KOSPI", "type": "서킷브레이커", "note": "미 빅테크 약세 (3일 만에 재발동)"},
]
PAT = [
    (r"(코스피|유가증권).{0,20}서킷\s*브레이커|서킷\s*브레이커.{0,20}(코스피|유가증권)", "KOSPI", "서킷브레이커"),
    (r"코스닥.{0,20}서킷\s*브레이커|서킷\s*브레이커.{0,20}코스닥", "KOSDAQ", "서킷브레이커"),
    (r"(코스피|유가증권).{0,20}매도\s*사이드카|매도\s*사이드카.{0,20}(코스피|유가증권)", "KOSPI", "매도 사이드카"),
    (r"코스닥.{0,20}매도\s*사이드카|매도\s*사이드카.{0,20}코스닥", "KOSDAQ", "매도 사이드카"),
    (r"(코스피|유가증권).{0,20}매수\s*사이드카|매수\s*사이드카.{0,20}(코스피|유가증권)", "KOSPI", "매수 사이드카"),
    (r"코스닥.{0,20}매수\s*사이드카|매수\s*사이드카.{0,20}코스닥", "KOSDAQ", "매수 사이드카"),
]
# 서킷·사이드카 외 굵직한 이벤트 (뉴스 제목 기준, 같은 날 같은 유형은 1회). 세 번째 값 True = '속보' 제목만 (평소에도 자주 쓰는 표현이라)
PAT_BIG = [
    (r"(한은|한국은행|금통위).{0,20}기준\s*금리.{0,15}(인상|인하|동결)", "한은 기준금리", False),
    (r"(연준|FOMC|파월).{0,25}(금리|기준금리).{0,15}(인상|인하|동결)", "FOMC 금리", True),
    (r"(워시|Warsh|연준\s*의장)", "연준 의장 발언", False),
    (r"뉴욕\s*증시|나스닥|S&P|다우|엔비디아|테슬라|애플|마이크로소프트|메타|아마존|알파벳|구글|브로드컴|마이크론|TSMC", "미장 속보", True),   # 속보만 (평소 기사 많음)   # 의장 이름·직함이 제목에 나오면 (하루 1회 기록 + 텔레그램)
    (r"공매도.{0,10}(전면\s*)?(금지|재개)|증시\s*안정\s*(펀드|기금)|증안\s*펀드|(금융|증시|시장)\s*안정\s*(조치|대책)", "정책·시장안정 조치", False),
    (r"비상\s*계엄|전쟁\s*(발발|선포)|미사일\s*발사|핵\s*실험|(북한|이란|중동).{0,10}(공습|도발|침공)", "지정학 충격", True),
    (r"(국가\s*)?신용\s*등급.{0,10}(강등|하향)|디폴트\s*선언|파산\s*보호\s*신청", "신용 충격", True),
    (r"(나스닥|S&P\s*500|다우|뉴욕\s*증시).{0,15}(폭락|급락)|블랙\s*(먼데이|프라이데이)", "미 증시 급락", True),
    (r"(원[·/]?달러\s*)?환율.{0,20}(돌파|폭등|급등|급락)", "환율 급변", True),
    (r"(국제\s*)?유가.{0,15}(폭등|급등|폭락|급락)", "유가 급변", True),
    (r"(삼성전자|SK\s*하이닉스|하이닉스|엔비디아).{0,20}(어닝|실적)\s*(쇼크|서프라이즈)", "대형주 실적 쇼크·서프", False),
    (r"(한국거래소|거래소|증권사|HTS|MTS).{0,15}(전산\s*장애|먹통|거래\s*(중단|정지))", "거래 장애", False),
]


def _valid(e: dict) -> bool:
    """뉴스로 잡은 서킷·사이드카는 제목에 '발동'이 있어야 실제 이벤트 (통계·해설 기사 오탐 제거, 10/16 '올해만 10번 멈췄다' 사례)."""
    if e.get("source") == "뉴스" and any(k in e.get("type", "") for k in ("서킷", "사이드카")):
        return "발동" in e.get("title", "")
    return True


def load() -> dict:
    try:
        st = json.loads(OUT.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"events": []}
    ev = st.get("events", [])
    st["events"] = [e for e in ev if _valid(e)]
    st["_dropped"] = len(ev) - len(st["events"])
    return st


def _news() -> list[dict]:
    out = []
    for cat in ("mainnews", "flashnews"):
        try:
            r = requests.get(f"https://m.stock.naver.com/api/news/list?category={cat}&pageSize=30&page=1", headers=UA, timeout=15)
            if r.status_code != 200:
                continue
            for it in r.json() or []:
                t = it.get("tit") or it.get("title") or ""
                dt = str(it.get("dt") or it.get("datetime") or "")
                out.append({"title": re.sub(r"<[^>]+>|&quot;", " ", t), "dt": dt,
                            "link": f"https://n.news.naver.com/mnews/article/{it.get('oid') or it.get('officeId')}/{it.get('aid') or it.get('articleId')}"})
        except Exception as e:  # noqa: BLE001
            log.info("이벤트 뉴스 %s 실패: %s", cat, e)
    return out


def check(live: dict | None = None, send: bool = True) -> list[dict]:
    """새 이벤트를 찾아 기록. 반환: 새로 추가된 이벤트."""
    now = datetime.now(KST)
    today = now.strftime("%Y-%m-%d")
    st = load()
    ev = st.get("events", [])
    have = {(e["date"], e["market"], e["type"]) for e in ev}
    new = []
    for n in _news():
        if n["dt"][:8] != now.strftime("%Y%m%d"):
            continue
        for pat, mk, ty in PAT:
            if re.search(pat, n["title"]) and "발동" in n["title"] and (today, mk, ty) not in have:
                stage = re.search(r"([123])\s*단계", n["title"])
                e = {"date": today, "time": f"{n['dt'][8:10]}:{n['dt'][10:12]}" if len(n["dt"]) >= 12 else now.strftime("%H:%M"),
                     "market": mk, "type": ty + (f" {stage.group(1)}단계" if stage and ty == "서킷브레이커" else ""),
                     "source": "뉴스", "title": n["title"][:120], "link": n["link"]}
                new.append(e)
                have.add((today, mk, ty))
        for pat, ty, flash in PAT_BIG:
            if flash and "속보" not in n["title"]:
                continue
            if re.search(pat, n["title"]) and (today, "시장", ty) not in have:
                new.append({"date": today, "time": f"{n['dt'][8:10]}:{n['dt'][10:12]}" if len(n["dt"]) >= 12 else now.strftime("%H:%M"),
                            "market": "시장", "type": ty, "source": "뉴스", "title": n["title"][:120], "link": n["link"]})
                have.add((today, "시장", ty))
    # 지수 등락률 근접 경보
    items = {i["key"]: i for i in (live or {}).get("items", [])}
    for k in ("KOSPI", "KOSDAQ"):
        it = items.get(k)
        if not it or it.get("chg") is None or it.get("status") not in (None, "OPEN"):
            continue
        c = it["chg"]
        lvl = ("서킷 2단계 기준(−15%) 도달" if c <= -0.15 else "서킷 1단계 기준(−8%) 도달" if c <= -0.08 else
               "급락 −5% (사이드카 근처)" if c <= -0.05 else "급등 +5% (매수 사이드카 근처)" if c >= 0.05 else None)
        if lvl and (today, k, "경보:" + lvl) not in have:
            new.append({"date": today, "time": now.strftime("%H:%M"), "market": k, "type": "경보:" + lvl, "source": "지수",
                        "title": f"{k} {c*100:+.2f}% ({it.get('last'):,.2f})"})
            have.add((today, k, "경보:" + lvl))
    if new or st.get("_dropped"):
        st.pop("_dropped", None)
        st["events"] = sorted(ev + new, key=lambda e: (e["date"], e.get("time", "")), reverse=True)[:300]
        st["updated_at"] = now.strftime("%Y-%m-%d %H:%M")
        OUT.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
        log.info("새 이벤트 %d건", len(new))
        if send and new:
            try:
                from .alerts import silent
                from .report import send_telegram
                send_telegram("🚨 <b>시장 이벤트</b>\n" + "\n".join(
                    f"• {e['time']} {e['market']} <b>{e['type']}</b> — {e['title']}" for e in new)
                    + "\n\n과거 서킷 다음날 통계: 웹 HOME › EVENTS",
                    disable_notification=silent(_not_yet_rung(halt_keys(new), today)))   # 결재 #9: 서킷·사이드카 실제 발동만 소리, 근접 경보·급변 뉴스는 무음
            except Exception as e:  # noqa: BLE001
                log.warning("이벤트 텔레그램 실패: %s", e)
    return new


def _not_yet_rung(keys: list[str], today: str) -> list[str]:
    """장중 이벤트 감시(event_watch, 지수 프록시)가 오늘 같은 시장 halt 를 이미 울렸으면 뉴스 확인은 무음 (소리 중복 방지)."""
    try:
        from .event_watch import halted_today
        return [k for k in keys if not halted_today(k.split(":")[1], today)]
    except Exception:  # noqa: BLE001
        return keys


def halt_keys(new: list[dict]) -> list[str]:
    """결재 #9 소리 대상 키: 서킷브레이커·사이드카 '실제 발동'(뉴스 '발동' 확인)만. '경보:'(지수 근접)는 제외."""
    return [f"halt:{e['market']}:{e['type']}" for e in new
            if not str(e.get("type", "")).startswith("경보") and any(k in str(e.get("type", "")) for k in ("서킷", "사이드카"))]


def stats() -> dict:
    """과거 서킷브레이커 + 기록된 이벤트 날짜별 이후 코스피 수익률, 그리고 큰 급락일(−5% 이하) 통계."""
    try:
        ser = json.loads((REPORT_DIR / "macro_series.json").read_text(encoding="utf-8"))["series"]["KOSPI"]
    except Exception:  # noqa: BLE001
        return {}
    c = {r[0]: (r[4] if len(r) >= 6 else r[1]) for r in ser}
    ds = sorted(c)

    def fwd(d):
        if d not in c:
            return None
        i = ds.index(d)
        if i == 0:
            return None
        f = lambda n: round(c[ds[i + n]] / c[d] - 1, 4) if i + n < len(ds) else None  # noqa: E731
        win = [c[ds[j]] for j in range(i, min(i + 21, len(ds)))]
        return {"day": round(c[d] / c[ds[i - 1]] - 1, 4), "d1": f(1), "d5": f(5), "d20": f(20),
                "low20": round(min(win) / c[d] - 1, 4) if len(win) > 1 else None}
    st = load()
    cb_dates = sorted({h["date"] for h in HISTORY} | {e["date"] for e in st.get("events", []) if e.get("type", "").startswith("서킷") and e["market"] == "KOSPI"})
    cb = []
    for d in cb_dates:
        h = next((x for x in HISTORY if x["date"] == d), {})
        cb.append({"date": d, "note": h.get("note", "기록된 발동"), **(fwd(d) or {})})
    big = [{"date": d, **fwd(d)} for d in ds[1:] if fwd(d) and fwd(d)["day"] <= -0.05]

    def summ(rows):
        out = {}
        for k in ("d1", "d5", "d20"):
            v = [r[k] for r in rows if r.get(k) is not None]
            if v:
                out[k] = {"n": len(v), "avg": round(sum(v) / len(v), 4), "up": round(sum(1 for x in v if x > 0) / len(v), 2)}
        return out
    now = datetime.now(KST)
    today = now.strftime("%Y-%m-%d")
    res = {"cb": cb, "cb_summary": summ(cb), "big": big[-30:], "big_summary": summ(big),
           "events": st.get("events", [])[:50], "updated_at": st.get("updated_at"),
           # 당일 기준 표시용: 기록(events)은 이벤트가 터질 때만 바뀌지만, 확인 시각은 시세 갱신마다 바뀜
           "checked_at": now.strftime("%Y-%m-%d %H:%M"),
           "today": {"date": today, "n": sum(1 for e in st.get("events", []) if e.get("date") == today)},
           "note": "다음날·5일·20일 = 그날 종가 대비 코스피 수익률(야후 일봉). 2024-09 이전 발동일은 일봉 범위 밖이라 수치 없음."}
    (REPORT_DIR / "events_stats.json").write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    return res
