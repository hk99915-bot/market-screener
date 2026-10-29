"""지수·매크로 준실시간 스냅샷 → reports/live.json (텔레그램 발송 없음).

KOSPI·KOSDAQ 은 네이버 → pykrx(KRX) 순으로 받고, 나머지는 야후.
그 위에 토스(toss-live 브랜치, 노트북 수집)가 신선하면 KOSPI·KOSDAQ·USDKRW 를 덮는다 — screener/toss_live.py (항목 src='toss').
야후의 ^KS11 은 전일 종가가 틀리게 오는 경우가 있어(-5.5% 오표시 사례) 국내 지수에는 쓰지 않는다.
10/24: 장 밖(마감 뒤·개장 전) 지수는 토스로 덮지 않음(KRX 종가 우선, toss_live.overlay), 15:30~15:45 국내 지수·선물 provisional=True(종가 확정 전).
토스 1차 전환은 데이터 측정(req-dev-a4d03413: 시세 나이 중앙 5.1분·동시호가 고정값) 뒤 보류 — 겸이 결정 대기. 선물(K200F)은 토스에 없어 네이버.
토스는 GitHub Actions 에서 직접 못 부름(허용 IP 등록제 + 클라이언트당 토큰 1개 → 노트북 1대 수집, toss-live 브랜치, screener/toss_md.py).
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo

import requests

from .config import CFG, REPORT_DIR

log = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
KR_KEYS = ("KOSPI", "KOSDAQ")
ORDER = ["KOSPI", "KOSDAQ", "SPX", "NASDAQ", "RUT", "VIX", "US10Y", "DXY", "USDKRW", "USDJPY", "NIKKEI", "TOPIX", "WTI", "GOLD", "BTC"]


def _num(x) -> float:
    return float(str(x).replace(",", "").replace("%", "").strip())


def kr_naver() -> dict:
    out = {}
    for k in KR_KEYS:
        try:
            r = requests.get(f"https://m.stock.naver.com/api/index/{k}/basic", headers=UA, timeout=10)
            r.raise_for_status()
            j = r.json()
            last, ratio = _num(j["closePrice"]), abs(_num(j["fluctuationsRatio"])) / 100
            code = str((j.get("compareToPreviousPrice") or {}).get("code", ""))
            if code in ("4", "5"):        # 하한·하락
                ratio = -ratio
            elif code == "3":             # 보합
                ratio = 0.0
            elif code not in ("1", "2"):  # 코드가 없으면 원래 부호를 믿는다
                ratio = _num(j["fluctuationsRatio"]) / 100
            # 분모 = 전일 KRX 확정 종가. 네이버 fluctuationsRatio 는 소수 2자리(%)로 잘려 역산 오차가 최대 ±0.005%p
            # (코스피 5,500 기준 ±0.3pt) → 절대 변화 compareToPreviousClosePrice 로 전일 종가를 정확히 복원해 같이 싣는다.
            prev = None
            try:
                diff = abs(_num(j["compareToPreviousClosePrice"]))
                p = last - diff if ratio > 0 else last + diff if ratio < 0 else last
                if p > 0 and abs(last / p - 1 - ratio) <= 0.0001:   # 등락률과 어긋나면(반올림 0.005%p 초과) 쓰지 않음
                    prev = p
            except (KeyError, TypeError, ValueError):
                pass
            out[k] = {"last": last, "chg": ratio, "prev": prev, "src": "naver", "status": j.get("marketStatus")}
        except Exception as e:  # noqa: BLE001
            log.warning("네이버 %s 실패: %s", k, e)
    return out


def kr_krx() -> dict:
    from .flows import index_close
    return {k: {"last": v["close"], "chg": v["chg"], "src": "krx"} for k, v in index_close(date.today()).items()}


def kr_indices() -> dict:
    q = kr_naver()
    if len(q) < len(KR_KEYS):
        try:
            for k, v in kr_krx().items():
                q.setdefault(k, v)
        except Exception as e:  # noqa: BLE001
            log.warning("KRX 지수 폴백 실패: %s", e)
    return q


def yahoo(keys: list[str]) -> dict:
    import yfinance as yf
    syms = {k: CFG.macro[k] for k in keys if k in CFG.macro}
    out = {}
    if not syms:
        return out
    df = yf.download(list(syms.values()), period="7d", interval="1d", progress=False,
                     group_by="ticker", auto_adjust=False, threads=True)
    for k, s in syms.items():
        try:
            c = df[s]["Close"].dropna()
            if len(c) >= 2:
                out[k] = {"last": float(c.iloc[-1]), "chg": float(c.iloc[-1] / c.iloc[-2] - 1), "src": "yahoo",
                          "date": str(c.index[-1].date())}   # 봉 날짜 — 같은 시장 묶음과 날짜가 다르면 flag_lag 가 표시
        except Exception as e:  # noqa: BLE001
            log.warning("야후 %s 실패: %s", k, e)
    return out


# 같은 시장 묶음: 한 지표의 마지막 봉 날짜가 묶음 최신보다 이르면 '지연' 표시.
# 10/17 감사 중-5: 티커 NIKKEI −4.90% 는 야후 ^N225 에 10/16 봉이 없어 10/15 등락이었고, TOPIX(1306.T) +1.76% 는 10/16 등락 — 전일 종가 오류가 아니라 날짜 혼재.
LAG_GROUPS = {"JP": ("NIKKEI", "TOPIX"), "US": ("SPX", "NASDAQ", "RUT", "VIX"), "CMDTY": ("WTI", "GOLD")}


def flag_lag(items: list[dict]) -> list[dict]:
    """묶음 최신 봉 날짜보다 오래된 지표에 lag=True (등락률은 그 날짜 기준이라 같은 줄 다른 지표와 비교 불가)."""
    by = {d["key"]: d for d in items}
    for keys in LAG_GROUPS.values():
        ds = [by[k]["date"] for k in keys if k in by and by[k].get("date")]
        if len(ds) < 2:
            continue
        top = max(ds)
        for k in keys:
            if k in by and by[k].get("date") and by[k]["date"] < top:
                by[k]["lag"] = True
                log.warning("live %s 마지막 봉 %s < 같은 시장 %s — 지연 표시", k, by[k]["date"], top)
    return items


def session_label(items: list[dict], now: datetime) -> tuple[str, str]:
    """('LIVE'|'CLOSE', 거래일). KR 정규장 중이면 LIVE, 아니면 CLOSE + 마지막 KR 거래일 (주말·휴일 티커 'LIVE' 오표기 방지, 감사 경-2)."""
    from . import tradecal
    try:
        live = tradecal.in_session("KR", now)
        d = tradecal.session_on_or_before("KR", now.date())
        if not live and d == now.date() and now.hour < 9:   # 개장 전: 화면 값은 전 거래일 종가
            d = tradecal.prev_session("KR", d)
    except Exception:  # noqa: BLE001
        live, d = now.weekday() < 5 and (9 * 60) <= now.hour * 60 + now.minute <= (15 * 60 + 30), now.date()
    if live and any(str(x.get("status") or "").upper() == "CLOSE" for x in items if x.get("key") in KR_KEYS):
        live = False
    return ("LIVE" if live else "CLOSE"), d.isoformat()


def patch_macro(mr: list[dict]) -> list[dict]:
    """스크리너 매크로 표의 KOSPI·KOSDAQ 현재값·1D 를 국내 소스로 교체 (20D·50일선은 그대로)."""
    q = kr_indices()
    for d in mr:
        if d.get("key") in q:
            d["last"], d["chg1"] = q[d["key"]]["last"], q[d["key"]]["chg"]
    return mr


def fut_item(f: dict, fp: float, kp: float) -> dict:
    """K200F 항목. 네이버 FUT basic 은 '20분 지연' 시세(delayTime=20·localTradedAt 20분 전)인데 현물은 실시간이라
    베이시스(선물−현물)·등락 방향이 어긋난다(10/29 10:03 선물 +1.22% vs 코스피 −0.66%, req-maint-7469ad9a).
    지연이 있으면 delay(초)·ts 를 싣고 basis 는 비운다(화면은 basis None 이면 data/deriv 값으로 대체). 예외는 지연 없음으로 취급."""
    ratio = _num(f.get("fluctuationsRatio"))   # 파싱 실패는 호출부 try 가 받는다(기존 동작)
    it = {"key": "K200F", "last": fp, "chg": ratio / 100, "src": "naver",
          "basis": round(fp - kp, 2), "spot": kp, "status": f.get("marketStatus")}
    try:
        dly = int((_num(f.get("delayTime")) or 0) * 60)
        if dly > 0:
            it.update(delay=dly, ts=f.get("localTradedAt"), basis=None, note=f"{dly // 60}분 지연 시세")
    except Exception:  # noqa: BLE001
        pass
    return it


def snapshot() -> dict:
    q = kr_indices()
    try:
        q.update({k: v for k, v in yahoo([k for k in ORDER if k not in KR_KEYS]).items()})
    except Exception as e:  # noqa: BLE001
        log.warning("야후 일괄 실패: %s", e)
    items = [{"key": k, **q[k]} for k in ORDER if k in q]
    try:   # 일본 10년 금리 (재무성 일별 CSV, japan.py 가 갱신) — 야후에 없어서 저장값을 붙임
        jg = (json.loads((REPORT_DIR / "japan.json").read_text(encoding="utf-8")).get("index") or {}).get("JGB10Y") or {}
        if jg.get("last") and (date.today() - date.fromisoformat(jg["date"])).days <= 5:
            prev = jg["last"] - (jg.get("d1bp") or 0) / 100
            i = next((n + 1 for n, x in enumerate(items) if x["key"] == "US10Y"), len(items))
            items.insert(i, {"key": "JGB10Y", "last": jg["last"], "chg": (jg["last"] / prev - 1) if prev else 0.0, "src": jg.get("src")})
    except Exception:  # noqa: BLE001
        pass
    try:   # 코스피200 선물·베이시스 (선물 − 현물). 큰 마이너스 = 선물 투매(백워데이션), 공포 지표
        import requests as _rq
        ua = {"User-Agent": "Mozilla/5.0"}
        f = _rq.get("https://m.stock.naver.com/api/index/FUT/basic", headers=ua, timeout=10).json()
        k2 = _rq.get("https://m.stock.naver.com/api/index/KPI200/basic", headers=ua, timeout=10).json()
        fp, kp = _num(f.get("closePrice")), _num(k2.get("closePrice"))
        if fp and kp:
            items.insert(2, fut_item(f, fp, kp))
    except Exception as e:  # noqa: BLE001
        log.info("선물 실패: %s", e)
    now = datetime.now(KST)
    # 토스 우선(10/21): toss-live 브랜치 live.json 이 신선하면 KOSPI·KOSDAQ·USDKRW 를 토스 값으로, 아니면 위 네이버/야후 그대로
    try:
        from . import toss_live
        items, toss_blk = toss_live.overlay(items, toss_live.fetch(), now)
    except Exception as e:  # noqa: BLE001
        log.warning("토스 덮기 실패(기존 소스 유지): %s", e)
        toss_blk = {"state": "error", "reason": type(e).__name__}
    # asof = 연도 포함 KST 분 단위 (guard-rest 10/17: updated_at '10-17 09:47 KST' 는 연도가 없어 역행 비교 불가 — 화면 호환용으로 유지)
    flag_lag(items)
    sess, tday = session_label(items, now)
    # 15:30~15:45 = KRX 종가 확정 전(동시호가 체결 반영 중) → 국내 지수·선물에 잠정 표시 (req-dev-a4d03413 ①, heatmap_kr 와 같은 창)
    try:
        from . import tradecal
        if tradecal.is_session("KR", now.date()) and "15:30" <= now.strftime("%H:%M") < "15:45":
            for x in items:
                if x.get("key") in (*KR_KEYS, "K200F"):
                    x["provisional"] = True
    except Exception:  # noqa: BLE001
        pass
    out = {"asof": now.strftime("%Y-%m-%d %H:%M"), "updated_at": now.strftime("%m-%d %H:%M KST"), "items": items,
           "session": sess, "trade_date": tday, "toss": toss_blk,
           # NXT 시간대 지수(토스) — 정규장 items 와 별도 키, 없으면 빈 dict (10/24 겸이 "NXT 지수는 토스로")
           "nxt": toss_blk.get("nxt") or {}}
    from .guard import write_json
    if write_json(REPORT_DIR / "live.json", out):   # 계약 + 분 단위 역행 가드 (같은 날 더 늦은 시각은 항상 허용)
        log.info("live.json %d개 지표", len(items))
    return out
