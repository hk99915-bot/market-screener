"""규정 알림 (비율만 — 보유 수량·금액은 보내지 않는다).

(a) 손절선: 코스피 종가가 기준선 아래로 2일 연속 마감 → "⛔ 손절선 2일 연속 이탈 — 규정 [12] 즉시 집행", 1일 → "⚠️ 손절선 1일 이탈 — 내일 종가 확인".
    기준선 = env RULE_STOP_LEVEL, 없으면 reports/committee.json 의 low20, 그것도 없으면 macro_series KOSPI 20일 저점(오늘 제외).
(b) 기한: env RULE_DEADLINE (YYYY-MM-DD, 기본 2026-10-22) → D-2 · D-1 · D-day 한 줄.
(c) 발동선: MY_HOLDINGS 가 있고 반도체(전기 제외·지수 ETF 룩스루 제외) 비중 > SEMI_BAND(기본 0.45) → "📐 반도체 발동선 초과 — 다음 반등일 40%로".
(e) 하드 바닥: [5] 개정안(사전등록 10/17, 10/31 도장 전) 반도체 보유분 평단 −30% 장중 터치 → ⛔ 한 줄(비율만, 키 floor:<해시>, 무음).
    평단은 MY_HOLDINGS 에서 런타임에만(pb.risk_ctx). MY_RULES touch 가 더 엄격하면(가짜 예: 000000 바닥 8,800 < touch 10,000) touch 가 담당.
시크릿 부재: MY_RULES·MY_HOLDINGS 가 없으면 WARNING + reports/freshness.json 'health' → 화면 배지 '알림 비활성: MY_RULES 없음' (secret_health).
(d) 급락일 종가 매수 신호: 평일 15:05 KST(--mode crash_check) 코스피 장중 ≤ −4.5% → "⚡ 급락일 종가 매수 신호 … 15:20 동시호가" (1차 신호, 등급은 registry 인용).

같은 날 같은 알림은 한 번만 보낸다 (reports/alerts_state.json). 16:20 스크리너(KR)와 14:25 반등일 판정, 15:05 급락 점검에서 호출.

소리 등급(결재 #9, 10/17 14:09 도장 — pb-private ops/agreements.md §7-3): RING_KINDS 다섯 가지만 소리, 나머지는 전부
disable_notification=True. 텔레그램을 보내는 모든 모듈이 이 표(ring/silent)를 쓴다 — 표 밖에서 소리를 켜지 않는다.
PB 회신(10/17, 감사 M1): '손절 2일' = 코스피 5,451 선 + 보유 종목 기준가 각각 → 둘 다 stop2. 손실 한도 도달('loss_limit')은 표 밖(무음).
현재 defs.TELEGRAM_ALL_SILENT=True(오너 10/17 '전체 무음') — 이 표는 그 스위치를 끌 때부터 효력.
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

# ── 결재 #9 알림 등급: 소리 나는 것은 이 다섯 종류뿐 (키 접두 = 'stop2' · 'dl0' · 'touch:<코드>' · 'halt:…' · 'fresh:<항목>') ──
RING_KINDS: dict[str, str] = {
    "stop2": "⛔ 손절선 2일 연속 종가 이탈 — 코스피 규정 [12] 5,451 선('stop2') + 보유 종목 기준가 MY_RULES price('stop2:<코드>', pb 아침 점검)",
    "dl0": "규정 [12] 집행 기한 D-day",
    "touch": "발동선 장중 터치 (MY_RULES touch — 보유 종목 결재 #2 예외 1회)",
    "halt": "서킷브레이커·사이드카 실제 발동",
    "fresh": "데이터 신선도 ⛔ (항목당 하루 1회)",
}


def kind(key: str) -> str:
    """알림 키 → 종류. 'touch:000000' → 'touch', '2026-10-20:stop2' 처럼 날짜가 붙은 상태 키도 받는다."""
    parts = str(key).split(":")
    if len(parts) > 1 and len(parts[0]) == 10 and parts[0][4] == "-":   # YYYY-MM-DD: 접두
        parts = parts[1:]
    return parts[0]


def ring(keys) -> bool:
    """키 목록 중 하나라도 RING_KINDS 면 소리."""
    return any(kind(k) in RING_KINDS for k in keys)


def silent(keys=()) -> bool:
    """send_telegram(disable_notification=silent(keys)) 로 쓴다. 인자 없으면 무음(나머지 전부)."""
    return not ring(keys)


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


def kospi_asof(rows: list[list] | None = None) -> str | None:
    """KR 시장 날짜 = macro_series asof_kr (없으면 KOSPI 끝 행). 최상위 asof 는 BTC 등 24시간 시리즈 날짜라 쓰지 않는다(감사 M3)."""
    try:
        v = json.loads((REPORT_DIR / "macro_series.json").read_text(encoding="utf-8")).get("asof_kr")
        if v:
            return str(v)[:10]
    except Exception:  # noqa: BLE001
        pass
    rows = kospi_rows() if rows is None else rows
    return str(rows[-1][0])[:10] if rows else None


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
    cap = (ev.get("band") or {}).get("ex", {}).get("cap", ev["rules"]["semi_cap"])   # 결재 #3 레짐 연동 상한
    if ev["semi_ex"] > band + 0.005:   # denominator=D2 (b)
        return "band", f"📐 <b>반도체 발동선 초과</b> — 다음 반등일 {cap*100:.0f}%로 · 반도체(전기 제외) {ev['semi_ex']*100:.0f}% > 발동선 {band*100:.0f}% (무음)"
    return None, None


def kr_quote(code: str) -> dict | None:
    """네이버 모바일 종목 basic — {'last','low','name'}; 장중 저가 키가 없으면 low=None."""
    try:
        import requests
        j = requests.get(f"https://m.stock.naver.com/api/stock/{code}/basic",
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=10).json()
        last = _num(j.get("closePrice"))
        low = _num(j.get("lowPrice")) or _num(j.get("low"))
        return {"last": last, "low": low, "name": j.get("stockName") or code}
    except Exception as e:  # noqa: BLE001
        log.warning("시세 실패 %s: %s", code, e)
        return None


def touch_lines(fetch=None) -> list[tuple[str, str]]:
    """MY_RULES '코드 가격 touch' — 장중 저가(없으면 현재가)가 가격 이하로 닿으면 ⛔ 즉시 매도 한 줄.
    결재 #2(10/17): 예외 1회의 조건은 '추가 −8% 장중 터치 즉시'라 종가 2일 규칙으로는 못 잡는다."""
    from . import pb
    rules = pb.rules(os.environ.get("MY_RULES", ""))
    out: list[tuple[str, str]] = []
    fetch = fetch or kr_quote
    for code, px in rules.get("touch", {}).items():
        q = fetch(code)
        if not q or not q.get("last"):
            continue
        probe = q["low"] if q.get("low") else q["last"]
        if probe <= px:
            how = "장중 저가" if q.get("low") else "현재가"
            out.append((f"touch:{code}", f"⛔ <b>{q.get('name', code)} 발동선 터치</b> · {how} {probe:,.0f} ≤ {px:,.0f} · 결재 #2 예외 조건 충족(사전 합의: 재협상 없음) — 실행 여부는 오너"))
    return out


# ── 시크릿 부재 경고 (감사 10/17 #26: MY_RULES·MY_HOLDINGS 가 없으면 touch·발동선이 경고 없이 꺼졌음) ──
SECRETS = ("MY_RULES", "MY_HOLDINGS")
HEALTH_FILE = REPORT_DIR / "freshness.json"   # 'health' 목록 — 화면 신선도 배지가 '알림 비활성: <시크릿> 없음' 으로 표시


# 의도된 비활성 (10/21 겸이 결정: 알림용 secret MY_RULES·MY_HOLDINGS 를 만들지 않는다).
# 없어도 경보(배지 BAD·⛔ WARNING)가 아니라 'health_info'(정보)로만 남긴다 — 화면 배지는 FR.health 만 BAD 로 센다.
# 되돌리기: 이 표에서 이름을 빼면 다시 '알림 비활성' 경보.
INTENDED_OFF = {"MY_RULES": "2026-10-21", "MY_HOLDINGS": "2026-10-21"}


def secret_health(source: str = "", names=SECRETS, path=None, intended=None) -> list[str]:
    """없는 시크릿마다 WARNING 로그 + reports/freshness.json 'health' 항목, 생기면 항목 삭제. 반환: 없는 이름 목록.
    INTENDED_OFF(의도된 비활성)에 있는 이름은 INFO 로그 + 'health_info' 항목(배지 경보 아님).
    공개 파일에는 '있다/없다'만 — 값·길이는 쓰지 않는다."""
    fp = path or HEALTH_FILE
    off = INTENDED_OFF if intended is None else intended
    missing = [n for n in names if not os.environ.get(n, "").strip()]
    for n in missing:
        if n in off:
            log.info("알림 의도된 비활성: %s 없음 (%s, %s 결정)", n, source or "?", off[n])
        else:
            log.warning("⛔ 알림 비활성: %s 없음 (%s) — touch·발동선·하드 바닥 감시가 꺼져 있음", n, source or "?")
    try:
        cur = json.loads(fp.read_text(encoding="utf-8")) if fp.exists() else {}
    except Exception:  # noqa: BLE001
        cur = {}
    mine = lambda h: str(h.get("id", "")).startswith("secret:") and h["id"][7:] in names  # noqa: E731
    rows = [h for h in (cur.get("health") or []) if not mine(h)]
    info = [h for h in (cur.get("health_info") or []) if not mine(h)]
    prev = {h["id"]: h for h in (cur.get("health") or []) + (cur.get("health_info") or [])}
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    for n in missing:
        hid = f"secret:{n}"
        if n in off:
            info.append({"id": hid, "what": f"의도된 비활성: {n} 없음 ({off[n][5:].replace('-', '/')} 결정)",
                         "since": (prev.get(hid) or {}).get("since") or now, "by": source, "fix": "조치 불필요(오너 결정)"})
        else:
            rows.append({"id": hid, "what": f"알림 비활성: {n} 없음", "since": (prev.get(hid) or {}).get("since") or now,
                         "by": source, "fix": f"GitHub Settings → Secrets → {n} 생성"})
    if rows != (cur.get("health") or []) or info != (cur.get("health_info") or []):
        cur["health"] = rows
        if info or "health_info" in cur:
            cur["health_info"] = info
        try:
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(json.dumps(cur, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            log.warning("health 기록 실패: %s", e)
    return missing


# ── [5] 개정안 하드 바닥 (사전등록 10/17, 10/31 도장 전): 반도체 보유분 평단 −30% 장중 터치 ──
def floor_hits(ctx: dict | None, rules: dict | None, quote, mk: str = "KR") -> list[tuple[str, str, str]]:
    """ctx = pb.risk_ctx() (평단은 런타임 메모리에만), quote(code) → {'last','low','name'}. 반환 [(코드, 표시 이름, 문장)].
    MY_RULES touch 줄이 있고 그 가격이 하드 바닥 이상이면(더 엄격 — 가짜 예: 000000 touch 10,000) touch 가 담당, 하드 바닥은 건너뜀.
    문장은 비율만(평단·가격 없음)."""
    from .defs import SEMI_HARD_FLOOR, SEMI_HARD_FLOOR_STATE
    out = []
    touch = (rules or {}).get("touch", {})
    for code, f in ((ctx or {}).get("floors") or {}).items():
        if f["mk"] != mk:
            continue
        if code in touch and touch[code] >= f["floor"]:
            continue
        q = quote(code)
        if not q or not q.get("last"):
            continue
        probe = q["low"] if q.get("low") else q["last"]
        if probe <= f["floor"]:
            how = "장중 저가" if q.get("low") else "현재가"
            nm = q.get("name") or f.get("name") or code
            out.append((code, nm, f"⛔ <b>{nm} 하드 바닥 터치</b> · {how} 평단 대비 {probe / f['avg'] * 100 - 100:+.1f}% ≤ −{SEMI_HARD_FLOOR*100:.0f}% · "
                                  f"[5] 개정안 {SEMI_HARD_FLOOR_STATE} — 장중 터치 즉시(실행 여부는 오너)"))
    return out


def _hash(code: str) -> str:
    from .event_watch import _h
    return _h(code)


def floor_lines(fetch=None, ctx=None) -> list[tuple[str, str]]:
    """규정 알림용 하드 바닥 — 키 'floor:<해시>' (공개 상태 파일에 보유 코드 노출 금지)."""
    from . import pb
    ctx = pb.risk_ctx() if ctx is None else ctx
    rules = pb.rules(os.environ.get("MY_RULES", ""))
    return [(f"floor:{_hash(c)}", line) for c, _, line in floor_hits(ctx, rules, fetch or kr_quote, "KR")]


def _state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"sent": {}}


def _save(st: dict) -> None:
    st["sent"] = dict(sorted(st.get("sent", {}).items())[-200:])
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")


def _stop_stale(today: date, kd: str | None) -> None:
    """16:20 손절선 점검을 KOSPI 오늘 종가 없이 못 한 경우 — KR 거래일이면 조용히 넘기지 않는다(감사 M3):
    경고 로그 + reports/freshness.json stale 기록 → 신선도 배지·⛔ 알림(fresh, 지금은 전체 무음)이 잡는다."""
    from . import tradecal
    if not tradecal.is_session("KR", today):
        log.info("손절선 점검: 오늘 KR 휴장 — 건너뜀 (KOSPI 끝 행 %s)", kd)
        return
    log.warning("⛔ 손절선 점검 못 함: macro_series KOSPI 끝 행 %s ≠ 오늘 %s (KR 거래일) — 규정 [12] 점검 누락", kd, today)
    try:
        from .guard import record_stale
        record_stale("reports/macro_series.json", "KOSPI(16:20 손절선 점검)", str(today), kd)
    except Exception as e:  # noqa: BLE001
        log.warning("stale 기록 실패: %s", e)


def build(at_close: bool = True, today: date | None = None) -> list[tuple[str, str]]:
    """(키, 문장) 목록. at_close=False(14:25) 면 종가 기반 손절선 점검은 건너뜀."""
    today = today or datetime.now(KST).date()
    out: list[tuple[str, str]] = []
    if at_close:
        rows = kospi_rows()
        level, src = stop_level(rows)
        kd = kospi_asof(rows)
        if level and rows:
            if kd != str(today) or str(rows[-1][0])[:10] != str(today):
                _stop_stale(today, kd)
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
    ew: dict = {}
    try:
        from .event_watch import load_state as _ew_state   # event_watch 가 장중에 이미 보낸 touch:<코드> 는 다시 안 보냄 (평생 1회)
        ew = _ew_state()["sent"]
        out.extend(t for t in touch_lines() if t[0] not in ew)   # 장중·마감 슬롯 모두 — 터치는 시각을 가리지 않는다
    except Exception as e:  # noqa: BLE001
        log.warning("터치 점검 실패: %s", e)
    try:
        ew_day = {k for k in ew if k.startswith("floor:") and k.endswith(str(today))}
        out.extend(t for t in floor_lines() if f"{t[0]}:{today}" not in ew_day)   # event_watch 가 오늘 보낸 것은 건너뜀
    except Exception as e:  # noqa: BLE001
        log.warning("하드 바닥 점검 실패: %s", e)
    return out


def run(send: bool = True, at_close: bool = True) -> list[str]:
    secret_health("alerts")
    today = datetime.now(KST).date()
    items = build(at_close, today)
    st = _state()
    fresh = [(k, line) for k, line in items if f"{today}:{k}" not in st.get("sent", {})]
    if not fresh:
        return []
    text = "📏 <b>규정 알림</b>\n" + "\n".join(line for _, line in fresh)
    if send:
        from .report import send_telegram
        send_telegram(text, disable_notification=silent(k for k, _ in fresh))   # 결재 #9: stop2·dl0·touch 만 소리, ⚠️·D-2·D-1·반도체 밴드는 무음
        now = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
        for k, _ in fresh:
            st.setdefault("sent", {})[f"{today}:{k}"] = now
        _save(st)
    log.info("규정 알림 %d건%s", len(fresh), "" if send else " (전송 안 함)")
    return [line for _, line in fresh]


# ───────────────────────────── (d) 급락일 종가 매수 신호 (15:05) ─────────────────────────────
from .defs import CRASH_ALERT_PCT   # (단일 원천 screener/defs.py) −0.045 — 15:05 장중 기준. 확정 판정(−5.0%)보다 느슨하게 울려 15:20 동시호가 전에 준비하게 한다
CRASH_STUDY = "20일 +7.5%·승률 81%·n16"   # reports/studies/entry_signals.md 급락일 종가


def crash_text(chg: float, grade: str, today: date | None = None, last: float | None = None) -> str:
    """급락일 종가 매수 신호 문장 (지수 비율만). issue_url 은 모의 '나' 픽 등록 링크(069500 1000000 종가 선입력)."""
    from .duel import issue_url
    today = today or datetime.now(KST).date()
    link = issue_url(str(today), "069500 1000000 종가\n근거: 급락일 종가(1차 신호)")
    L = [f"⚡ <b>급락일 종가 매수 신호</b> (등급 {grade}, {CRASH_STUDY}) — 15:20 동시호가",
         f"코스피 {last:,.2f} ({chg*100:+.2f}%)" if last else f"코스피 {chg*100:+.2f}%",
         f"할 일: ① 모의 pick 등록(<a href=\"{link}\">링크</a>) ② ISA 선매수(결재 #15 · " + isa_crash_note(today) + ") ③ 위성 실계좌는 해금 후.",
         "하지 말 일: 레버리지. 안 할 거면 사유를 기록."]
    return "\n".join(L)


def isa_crash_note(today: date | None = None) -> str:
    """'올해 n/2회' — ops/isa_buys.json 급락일 선매수 카운터 (screener/ticket.py isa_*)."""
    from .defs import ISA_CRASH_PER_YEAR
    try:
        from .ticket import isa_counts
        n = isa_counts(today or datetime.now(KST).date())["crash_year"]
    except Exception:  # noqa: BLE001
        n = None
    return f"연 {ISA_CRASH_PER_YEAR}회 상한 · 올해 {'?' if n is None else n}/{ISA_CRASH_PER_YEAR}회" + (" — 상한 도달, 이번엔 안 함" if n is not None and n >= ISA_CRASH_PER_YEAR else "")


def crash_check(q: dict | None = None, send: bool = True, today: date | None = None) -> dict | None:
    """15:05 KST: 코스피 장중 등락률 ≤ CRASH_ALERT_PCT 면 텔레그램 1회(alerts_state 'crash'). 반환 {chg, last, fired, text}."""
    today = today or datetime.now(KST).date()
    if q is None:
        try:
            from .live import kr_naver
            q = (kr_naver() or {}).get("KOSPI") or {}
        except Exception as e:  # noqa: BLE001
            log.warning("급락 점검: 코스피 시세 실패 %s", e)
            q = {}
    chg, last = q.get("chg"), q.get("last")
    if chg is None:
        log.warning("급락 점검: 코스피 시세 없음")
        return None
    out = {"date": str(today), "chg": round(float(chg), 4), "last": last, "thr": CRASH_ALERT_PCT, "fired": False, "text": None}
    if chg > CRASH_ALERT_PCT:
        log.info("급락 점검 %s: 코스피 %+.2f%% — 신호 없음", today, chg * 100)
        return out
    try:
        from .committee import crash_day_grade
        grade = crash_day_grade()
    except Exception:  # noqa: BLE001
        grade = "검증전"
    out["text"] = crash_text(float(chg), grade, today, last)
    st = _state()
    key = f"{today}:crash"
    if key in st.get("sent", {}):
        log.info("급락 신호 이미 전송 (%s)", key)
        return out
    out["fired"] = True
    if send:
        from .report import send_telegram
        send_telegram(out["text"], disable_notification=silent(["crash"]))   # 결재 #9(최종): ⚡ 급락 신호는 무음 (RING_KINDS 밖)
        st.setdefault("sent", {})[key] = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
        _save(st)
    return out
