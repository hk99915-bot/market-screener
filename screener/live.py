"""지수·매크로 준실시간 스냅샷 → reports/live.json (텔레그램 발송 없음).

KOSPI·KOSDAQ 은 네이버 → pykrx(KRX) 순으로 받고, 나머지는 야후.
야후의 ^KS11 은 전일 종가가 틀리게 오는 경우가 있어(-5.5% 오표시 사례) 국내 지수에는 쓰지 않는다.
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
ORDER = ["KOSPI", "KOSDAQ", "SPX", "NASDAQ", "RUT", "VIX", "US10Y", "DXY", "USDKRW", "USDJPY", "WTI", "GOLD", "BTC"]


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
            out[k] = {"last": last, "chg": ratio, "src": "naver", "status": j.get("marketStatus")}
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
                out[k] = {"last": float(c.iloc[-1]), "chg": float(c.iloc[-1] / c.iloc[-2] - 1), "src": "yahoo"}
        except Exception as e:  # noqa: BLE001
            log.warning("야후 %s 실패: %s", k, e)
    return out


def patch_macro(mr: list[dict]) -> list[dict]:
    """스크리너 매크로 표의 KOSPI·KOSDAQ 현재값·1D 를 국내 소스로 교체 (20D·50일선은 그대로)."""
    q = kr_indices()
    for d in mr:
        if d.get("key") in q:
            d["last"], d["chg1"] = q[d["key"]]["last"], q[d["key"]]["chg"]
    return mr


def snapshot() -> dict:
    q = kr_indices()
    try:
        q.update({k: v for k, v in yahoo([k for k in ORDER if k not in KR_KEYS]).items()})
    except Exception as e:  # noqa: BLE001
        log.warning("야후 일괄 실패: %s", e)
    items = [{"key": k, **q[k]} for k in ORDER if k in q]
    try:   # 코스피200 선물·베이시스 (선물 − 현물). 큰 마이너스 = 선물 투매(백워데이션), 공포 지표
        import requests as _rq
        ua = {"User-Agent": "Mozilla/5.0"}
        f = _rq.get("https://m.stock.naver.com/api/index/FUT/basic", headers=ua, timeout=10).json()
        k2 = _rq.get("https://m.stock.naver.com/api/index/KPI200/basic", headers=ua, timeout=10).json()
        fp, kp = _num(f.get("closePrice")), _num(k2.get("closePrice"))
        if fp and kp:
            items.insert(2, {"key": "K200F", "last": fp, "chg": _num(f.get("fluctuationsRatio")) / 100, "src": "naver",
                             "basis": round(fp - kp, 2), "spot": kp, "status": f.get("marketStatus")})
    except Exception as e:  # noqa: BLE001
        log.info("선물 실패: %s", e)
    out = {"updated_at": datetime.now(KST).strftime("%m-%d %H:%M KST"), "items": items}
    (REPORT_DIR / "live.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    log.info("live.json %d개 지표", len(items))
    return out
