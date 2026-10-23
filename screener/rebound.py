"""반등일 판정 알림 — 평일 14:25 KST (규정 [12]: 14:30 기준 코스피가 전일 종가 대비 +0.5% 이상이면 '반등일').

지수 비율만 다룬다 — 보유 종목·금액은 읽지도 쓰지도 않는다. 결과는 reports/rebound.json 에 날짜별로 남겨 일요일 성적표가 쓴다.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from .config import REPORT_DIR

log = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")
OUT = REPORT_DIR / "rebound.json"
from .defs import REBOUND_THRESHOLD as THRESHOLD   # 전일 종가 대비 +0.5% (단일 원천 screener/defs.py)


def judge(q: dict | None = None) -> dict | None:
    """코스피 현재가·전일 대비 등락률로 판정. 반환: {date, time, last, prev, thr, chg, ok}"""
    if q is None:
        from .live import kr_naver
        q = (kr_naver() or {}).get("KOSPI") or {}
    last, chg = q.get("last"), q.get("chg")
    if not last or chg is None:
        return None
    # denominator: 전일 KRX 확정 종가(prev) — 반등일 = 14:30 현재가 ≥ prev × (1 + THRESHOLD).
    # 네이버 basic 의 compareToPreviousClosePrice 로 복원한 prev 가 있으면 그것(정확), 없으면 반올림된 등락률 역산.
    if q.get("prev"):
        prev, prev_src = float(q["prev"]), "diff"
        chg = last / prev - 1
    else:
        prev, prev_src = last / (1 + chg), "ratio"
    now = datetime.now(KST)
    return {"date": now.strftime("%Y-%m-%d"), "time": now.strftime("%H:%M"), "last": round(last, 2), "prev": round(prev, 2),
            "thr": round(prev * (1 + THRESHOLD), 2), "chg": round(chg, 4), "ok": chg >= THRESHOLD, "src": q.get("src"), "prev_src": prev_src, "status": q.get("status")}


def text(j: dict) -> str:
    mark = "반등일 ✅" if j["ok"] else "반등일 ❌"
    L = [f"📐 <b>{mark}</b> ({j['time']} 판정)",
         f"코스피 {j['last']:,.2f} ({j['chg']*100:+.2f}%) · 기준 {j['thr']:,.2f} = 전일 종가 {j['prev']:,.2f} +{THRESHOLD*100:.1f}%",
         "→ " + ("규정 [12] 축소 계획: 14:30~15:20 안에 집행 (지표는 '일찍 팔기'에만)" if j["ok"] else "축소 대기 — 집행 기한·종가선 2일 이탈 조건은 별도 (재량 없음)"),
         "<i>14:30 확정치가 다르면 14:30 값이 우선</i>"]
    return "\n".join(L)


def run(send: bool = True) -> dict | None:
    j = judge()
    if not j:
        log.warning("반등일 판정: 코스피 시세 없음")
        return None
    try:
        st = json.loads(OUT.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        st = {"days": []}
    st["days"] = [x for x in st.get("days", []) if x.get("date") != j["date"]] + [j]
    st["days"] = st["days"][-120:]
    st["updated_at"] = j["date"] + " " + j["time"]
    OUT.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    log.info("반등일 판정 %s: %s", j["date"], "✅" if j["ok"] else "❌")
    if send:
        from .report import send_telegram
        send_telegram(text(j), disable_notification=True)   # 결재 #9(최종): 14:25 반등일 판정은 무음 (RING_KINDS 밖)
    try:   # 기한 D-n · 반도체 발동선 (종가 전이라 손절선 점검은 16:20 에서)
        from . import alerts
        alerts.run(send=send, at_close=False)
    except Exception as e:  # noqa: BLE001
        log.warning("규정 알림 실패: %s", e)
    return j
