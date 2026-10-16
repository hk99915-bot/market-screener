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


def load() -> dict:
    try:
        return json.loads(OUT.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"events": []}


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
            if re.search(pat, n["title"]) and (today, mk, ty) not in have:
                stage = re.search(r"([123])\s*단계", n["title"])
                e = {"date": today, "time": f"{n['dt'][8:10]}:{n['dt'][10:12]}" if len(n["dt"]) >= 12 else now.strftime("%H:%M"),
                     "market": mk, "type": ty + (f" {stage.group(1)}단계" if stage and ty == "서킷브레이커" else ""),
                     "source": "뉴스", "title": n["title"][:120], "link": n["link"]}
                new.append(e)
                have.add((today, mk, ty))
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
    if new:
        st["events"] = sorted(ev + new, key=lambda e: (e["date"], e.get("time", "")), reverse=True)[:300]
        st["updated_at"] = now.strftime("%Y-%m-%d %H:%M")
        OUT.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
        log.info("새 이벤트 %d건", len(new))
        if send:
            try:
                from .report import send_telegram
                send_telegram("🚨 <b>시장 이벤트</b>\n" + "\n".join(
                    f"• {e['time']} {e['market']} <b>{e['type']}</b> — {e['title']}" for e in new)
                    + "\n\n과거 서킷 다음날 통계: 웹 HOME › EVENTS")
            except Exception as e:  # noqa: BLE001
                log.warning("이벤트 텔레그램 실패: %s", e)
    return new


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
