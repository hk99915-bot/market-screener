"""비트코인 트래킹 1단계 (req-dev-54eba83d ②) — macro_series 의 BTC 일봉 → reports/btc.json.

BTC-USD 는 24시간·주말 거래라 주식과 기준일 개념이 다르다(감사 M3). 그래서 기준일을 둘로 나눈다:
  closed_asof = 마지막으로 **확정된 UTC 일봉**의 날짜 (추세·ATR·SMA 는 확정 봉만으로 계산)
  live_date   = 아직 진행 중인 오늘(UTC) 봉이 있으면 그 날짜 (없으면 null) — 장중 등락(chg_live)만 여기서
둘 다 UTC 일봉 기준(야후 BTC-USD 일봉 경계 = 00:00 UTC = 09:00 KST). 주식 신선도 계약(ops/freshness.json)에는 넣지 않는다.
±5%/일 알림: alert = |chg_live 또는 chg_1d| ≥ ALERT_PCT → maybe_alert 가 무음 텔레그램 1통(같은 UTC 일봉·같은 방향은 하루 1회, 상태 reports/btc_alert.json).
  무음 = 결재 #9(소리 알림 셋뿐) — 소리 없음, 알림은 뜬다. Actions(GITHUB_ACTIONS) 에서만 보냄.
실행: python -m screener.btc   (읽기: reports/macro_series.json, 쓰기: reports/btc.json)
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone

from .config import REPORT_DIR

ALERT_PCT = 5.0
ATR_N = 14
TREND_UP, TREND_DOWN, TREND_MIX = "상승", "하락", "혼조"


def _sma(c: list[float], n: int) -> float | None:
    return sum(c[-n:]) / n if len(c) >= n else None


def _atr(rows: list[list[float]], n: int = ATR_N) -> float | None:
    """Wilder 아닌 단순 평균 TR (screener/tradeplan.atr14 와 같은 정의)."""
    if len(rows) < n + 1:
        return None
    tr = [max(rows[i][2], rows[i - 1][4]) - min(rows[i][3], rows[i - 1][4]) for i in range(len(rows) - n, len(rows))]
    return sum(tr) / n


def _pct(a: float, b: float) -> float | None:
    return round((a / b - 1) * 100, 2) if b else None


def build(series: list, now_utc: datetime | None = None) -> dict:
    """series = macro_series['series']['BTC'] 행 [날짜, 시, 고, 저, 종, 거래량]. 반환 dict (btc.json)."""
    now_utc = now_utc or datetime.now(timezone.utc)
    today = now_utc.date().isoformat()
    rows = [r for r in series if len(r) >= 5 and all(isinstance(x, (int, float)) and math.isfinite(x) for x in r[1:5])]
    if len(rows) < 3:
        return {"schema_version": 1, "ok": False, "why": f"BTC 일봉 {len(rows)}개 — 계산 불가(데이터 없음)"}
    live = rows[-1] if str(rows[-1][0])[:10] >= today else None     # 오늘(UTC) 봉 = 진행 중
    closed = rows[:-1] if live else rows
    c = [r[4] for r in closed]
    last, prev = closed[-1], closed[-2]
    atr = _atr(closed)
    s20, s50, s200 = _sma(c, 20), _sma(c, 50), _sma(c, 200)
    if s20 and s50 and last[4] > s20 > s50:
        trend = TREND_UP
    elif s20 and s50 and last[4] < s20 < s50:
        trend = TREND_DOWN
    else:
        trend = TREND_MIX
    chg_1d = _pct(last[4], prev[4])
    chg_live = _pct(live[4], last[4]) if live else None
    chg = chg_live if chg_live is not None else chg_1d
    r = lambda v, n=0: None if v is None else round(v, n)  # noqa: E731
    return {
        "schema_version": 1, "ok": True, "symbol": "BTC-USD", "unit": "USD",
        "closed_asof": str(last[0])[:10], "live_date": str(live[0])[:10] if live else None,
        "day_basis": "UTC 일봉(경계 00:00 UTC = 09:00 KST)",
        "close": r(last[4]), "live_px": r(live[4]) if live else None,
        "chg_1d_pct": chg_1d, "chg_live_pct": chg_live,
        "sma20": r(s20), "sma50": r(s50), "sma200": r(s200), "trend": trend,
        "atr14": r(atr), "atr14_pct": r(atr / last[4] * 100, 2) if atr else None,
        "support20": r(min(x[3] for x in closed[-20:])), "high20": r(max(x[2] for x in closed[-20:])),
        "alert_pct": ALERT_PCT, "alert": bool(chg is not None and abs(chg) >= ALERT_PCT),
        "src": "reports/macro_series.json BTC (야후 BTC-USD 일봉)",
    }


ALERT_STATE = "btc_alert.json"


def alert_text(o: dict) -> str:
    chg = o["chg_live_pct"] if o.get("chg_live_pct") is not None else o.get("chg_1d_pct")
    basis = (f"진행 중 UTC {o['live_date'][5:]} 봉 · {o['closed_asof'][5:]} 확정 종가 대비" if o.get("chg_live_pct") is not None
             else f"UTC {o['closed_asof'][5:]} 확정 봉 · 전일 대비")
    return (f"₿ 비트코인 {chg:+.1f}% ({basis})\n"
            f"ATR14 {o.get('atr14_pct') or 0:.1f}% · 추세 {o.get('trend')} · 20일 저점 {o.get('support20') or 0:,.0f} USD\n"
            f"±{ALERT_PCT:g}%/일 관찰 알림(무음, 하루 1회) — 매매 신호 아님 · reports/btc.json")


def maybe_alert(o: dict, state_path=None, send=None) -> bool:
    """alert 이면 (봉 날짜, 방향) 당 1회만 보냄. 보냈으면 True. send(text) 기본 = report.send_telegram(무음)."""
    if not (o.get("ok") and o.get("alert")):
        return False
    chg = o["chg_live_pct"] if o.get("chg_live_pct") is not None else o.get("chg_1d_pct")
    key = f"{o.get('live_date') or o.get('closed_asof')}:{'+' if chg > 0 else '-'}"
    sp = state_path or (REPORT_DIR / ALERT_STATE)
    try:
        st = json.loads(sp.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        st = {}
    if key in (st.get("sent") or []):
        return False
    if send is None:
        from . import report
        send = report.send_telegram          # 기본 disable_notification=True (무음)
    send(alert_text(o))
    st["sent"] = ((st.get("sent") or []) + [key])[-30:]
    st["last"] = {"key": key, "chg_pct": chg, "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")}
    sp.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    return True


def run() -> dict:
    from . import guard
    ms = json.loads((REPORT_DIR / "macro_series.json").read_text(encoding="utf-8"))
    out = build((ms.get("series") or {}).get("BTC") or [])
    out["built_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    if out.get("ok"):
        guard.write_json(REPORT_DIR / "btc.json", out, key="closed_asof", ensure_ascii=False, indent=1)
        import os
        if os.environ.get("GITHUB_ACTIONS") == "true":   # 로컬·테스트 실행에선 안 보냄
            try:
                maybe_alert(out)
            except Exception as e:  # noqa: BLE001 — 알림 실패가 매크로 갱신을 막지 않게(로그만)
                import logging
                logging.getLogger(__name__).warning("BTC 알림 실패: %s", e)
    return out


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=1))
