"""규정 알림 (비율만 — 보유 수량·금액은 보내지 않는다).

(a) 손절선: 코스피 종가가 기준선 아래로 2일 연속 마감 → "⛔ 손절선 2일 연속 이탈 — 규정 [12] 즉시 집행", 1일 → "⚠️ 손절선 1일 이탈 — 내일 종가 확인".
    기준선 = env RULE_STOP_LEVEL, 없으면 reports/committee.json 의 low20, 그것도 없으면 macro_series KOSPI 20일 저점(오늘 제외).
(b) 기한: env RULE_DEADLINE (YYYY-MM-DD, 기본 2026-10-22) → D-2 · D-1 · D-day 한 줄.
(c) 발동선: MY_HOLDINGS 가 있고 반도체(전기 제외·지수 ETF 룩스루 제외) 비중 > SEMI_BAND(기본 0.45) → "📐 반도체 발동선 초과 — 다음 반등일 40%로".

같은 날 같은 알림은 한 번만 보낸다 (reports/alerts_state.json). 16:20 스크리너(KR)와 14:25 반등일 판정에서 호출.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime
from zoneinfo import ZoneInfo

from .config import REPORT_DIR

log = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")
STATE = REPORT_DIR / "alerts_state.json"
DEFAULT_DEADLINE = "2026-10-22"


def _num(x):
    try:
        return float(str(x).replace(",", ""))
    except (TypeError, ValueError):
        return None


def kospi_rows() -> list[list]:
    """macro_series KOSPI 행: [date, open, high, low, close, vol] (옛 형식은 [date, close])."""
    try:
        return json.loads((REPORT_DIR / "macro_series.json").read_text(encoding="utf-8"))["series"]["KOSPI"]
    except Exception:  # noqa: BLE001
        return []


def _close(r):
    return r[4] if len(r) >= 6 else r[1]


def _low(r):
    return r[3] if len(r) >= 6 else r[1]


def stop_level(rows: list[list] | None = None) -> tuple[float | None, str]:
    v = _num(os.environ.get("RULE_STOP_LEVEL"))
    if v:
        return v, "설정"
    # 규정 [12]는 고정선(5,451) — 시크릿이 없을 때 롤링 20일 저점으로 바꿔 울리면 선이 매일 움직여 규정과 달라짐.
    # 하락장 특칙 기간(기본 ~2026-10-22, RULE_DEADLINE)에는 고정 기본값을 쓰고, 그 뒤에만 롤링으로 넘어간다.
    dl = os.environ.get("RULE_DEADLINE", "2026-10-22")
    if datetime.now(KST).strftime("%Y-%m-%d") <= dl:
        return 5451.0, "규정 [12] 고정선"
    try:
        j = json.loads((REPORT_DIR / "committee.json").read_text(encoding="utf-8"))
        k = (j.get("kospi") or j.get("index") or {})
        if _num(k.get("low20")):
            return _num(k.get("low20")), "20일 저점"
    except Exception:  # noqa: BLE001
        pass
    rows = kospi_rows() if rows is None else rows
    if len(rows) >= 3:
        win = rows[-21:-1] if len(rows) > 21 else rows[:-1]   # 오늘 봉은 뺀 20일 저점 (오늘 신저가면 선 자체가 내려가는 모순 방지)
        return min(_low(r) for r in win), "20일 저점"
    return None, ""


def stop_streak(closes: list[float], level: float) -> int:
    """끝에서부터 기준선 아래 종가가 몇 일 연속인지 (0·1·2 …)."""
    n = 0
    for c in reversed(closes):
        if c is None or c >= level:
            break
        n += 1
    return n


def stop_line(closes: list[float], level: float) -> tuple[str | None, str]:
    """반환 (알림 키, 문장). 키 None = 알림 없음(이탈 없음)."""
    n = stop_streak(closes, level)
    last = closes[-1] if closes else None
    where = f"코스피 {last:,.0f} vs 기준 {level:,.0f} ({last/level*100-100:+.1f}%)" if last else ""
    if n >= 2:
        return f"stop2", f"⛔ <b>손절선 {n}일 연속 이탈</b> — 규정 [12] 즉시 집행 · {where}"
    if n == 1:
        return "stop1", f"⚠️ 손절선 1일 이탈 — 내일 종가 확인 · {where}"
    return None, f"손절선 {level:,.0f} 위 ✅ · {where}"


def deadline_line(today: date, deadline: str | None = None) -> tuple[str | None, str | None]:
    s = deadline or os.environ.get("RULE_DEADLINE") or DEFAULT_DEADLINE
    try:
        d = date.fromisoformat(s.strip())
    except ValueError:
        return None, None
    left = (d - today).days
    if left == 2:
        return "dl2", f"⏳ 규정 [12] 집행 기한 D-2 ({s})"
    if left == 1:
        return "dl1", f"⏳ 규정 [12] 집행 기한 D-1 ({s}) — 내일 장중 마무리"
    if left == 0:
        return "dl0", f"⏰ <b>규정 [12] 집행 기한 D-day</b> ({s}) — 오늘 안에 집행"
    return None, None


def band_line() -> tuple[str | None, str | None]:
    txt = os.environ.get("MY_HOLDINGS", "").strip()
    if not txt:
        return None, None
    from . import pb
    ev = pb.evaluate(txt, os.environ.get("MY_RULES", ""))
    if not ev:
        return None, None
    band = ev["rules"]["semi_band"]
    if ev["semi_ex"] > band + 0.005:
        return "band", f"📐 <b>반도체 발동선 초과</b> — 다음 반등일 40%로 · 반도체(전기 제외) 순자산 {ev['semi_ex']*100:.0f}% > 발동선 {band*100:.0f}%"
    return None, None


def _state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"sent": {}}


def _save(st: dict) -> None:
    st["sent"] = dict(sorted(st.get("sent", {}).items())[-200:])
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")


def build(at_close: bool = True, today: date | None = None) -> list[tuple[str, str]]:
    """(키, 문장) 목록. at_close=False(14:25) 면 종가 기반 손절선 점검은 건너뜀."""
    today = today or datetime.now(KST).date()
    out: list[tuple[str, str]] = []
    if at_close:
        rows = kospi_rows()
        level, src = stop_level(rows)
        if level and rows:
            if str(rows[-1][0]) != str(today):
                log.info("손절선 점검: 오늘 종가 아직 없음 (%s)", rows[-1][0])
            else:
                k, line = stop_line([_close(r) for r in rows], level)
                if k:
                    out.append((k, line + f" <i>(기준: {src})</i>"))
                else:
                    log.info("손절선: %s", line)
    k, line = deadline_line(today)
    if k:
        out.append((k, line))
    try:
        k, line = band_line()
        if k:
            out.append((k, line))
    except Exception as e:  # noqa: BLE001
        log.warning("발동선 점검 실패: %s", e)
    return out


def run(send: bool = True, at_close: bool = True) -> list[str]:
    today = datetime.now(KST).date()
    items = build(at_close, today)
    st = _state()
    fresh = [(k, line) for k, line in items if f"{today}:{k}" not in st.get("sent", {})]
    if not fresh:
        return []
    text = "📏 <b>규정 알림</b>\n" + "\n".join(line for _, line in fresh)
    if send:
        from .report import send_telegram
        send_telegram(text)
        now = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
        for k, _ in fresh:
            st.setdefault("sent", {})[f"{today}:{k}"] = now
        _save(st)
    log.info("규정 알림 %d건%s", len(fresh), "" if send else " (전송 안 함)")
    return [line for _, line in fresh]
