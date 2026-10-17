"""장중 이벤트 감시 — 사건이 나면 1~2분 안에 텔레그램 (오너 10/17 15시대: "사건이 터지면 바로 텔레로 오게, 특정 시간이 아니라").

live.yml 루프가 백그라운드로 약 60초마다 `python -m screener.event_watch` 를 부른다 (실행 주체 = live 루프 하나, 결정 C).
장 시간 밖이면 시세를 받지 않고 바로 끝난다.

감시 항목 (키 = 상태 파일 키, 종류 = alerts.kind(키) → RING_KINDS 면 소리, 아니면 무음):
  국장 (평일 09:00–15:31 KST, 네이버 모바일 basic API)
    touch:<코드>                 MY_RULES '<코드> <가격> touch' 장중 저가(없으면 현재가) ≤ 가격 — 평생 1회 (alerts.touch_lines 재사용) · 소리
    kospi-4 / kospi-5:<날짜>     코스피·코스닥 전일 대비 ≤ CRASH_NEAR_PCT(−4%) / CRASH_PCT(−5%) — 무음 (오너 15:05 결정 유지, 15:05 종가 판단 메시지는 그대로)
    halt:<시장>:<단계>:<날짜>     서킷브레이커·사이드카 — 소리. 아래 '발동 판정' 참고
    stopx:<해시>:<날짜>          MY_RULES '<코드> <가격>'(종가 2일 손절선) 장중 이탈 — 무음 경고 (소리 나는 stop2 = 코스피 종가 2일 규칙은 그대로)
    hold5:<해시>:<날짜>          MY_HOLDINGS 국내 종목 장중 ≤ −5% — 무음
  미장 (평일 09:30–16:00 뉴욕, 야후 1분봉)
    spx-3 / ndx-3 / vix+25:<날짜>  S&P500·나스닥100 ≤ −3%, VIX ≥ +25% — 무음
    usstop:<해시>:<날짜>         MY_RULES 미국 티커 손절선 장중 이탈 — 무음

발동 판정 (halt) — 출처와 오탐 위험:
  · 거래소 규정: 서킷 1·2·3단계 = 코스피(코스닥) 전일 종가 대비 −8%·−15%·−20% 가 1분 지속 (1·2단계는 14:50 뒤 발동 안 함, 단계별 하루 1회).
    매도/매수 사이드카(코스피) = 코스피200 선물 전일 대비 ±5% 1분 지속 (09:05 전·14:50 뒤 발동 안 함, 하루 1회).
  · 프록시: 같은 조건이 연속 두 번의 시세(시각 차 ≥ 60초)에서 유지되면 '발동'으로 본다 → 실제 발동 뒤 약 0~1분.
  · 필드: 선물(FUT) basic 의 tradeStopType.name 이 TRADING 이 아니고 코스피 ≤ −7% 또는 선물 |등락| ≥ 4.5% 이면 '발동'.
  · 오탐 위험: ① 선물 등락률은 전일 '종가' 기준이라 거래소 기준가(정산가)와 수 bp 차이 — 경계(±5.0%) 근처에서 오/미탐 가능.
    ② 시세 지연·급반등으로 1분 지속이 실제론 끊겼는데 두 표본만 조건을 만족할 수 있음. ③ 코스닥 사이드카(코스닥150 선물 ±6% & 현물 ±3%)는
    시세원이 없어 감시하지 않음(뉴스 감지 events.check 가 대신). 오탐이면 ticket.py 가 그날 신규 진입을 거부하므로 events.json 엔 쓰지 않는다.
  · 뉴스 감지(events.check, 5분)와 중복 소리 방지: 오늘 같은 시장 halt 가 한쪽에서 나갔으면 다른 쪽은 무음(events.halt_keys 참고).

신선도 가드: 시세 시각(localTradedAt · 야후 마지막 1분봉)이 지금보다 KR 180초 / US 300초 넘게 오래됐거나 장 시간 밖이면 그 시세로는 알리지 않는다.
전송: 한 번에 모아 1통, 직전 전송 60초 안이면 대기열에 넣고 다음 회차에 보낸다 (≤ 1통/분). 소리는 alerts.silent(키) 하나로만 정한다
(현재 defs.TELEGRAM_ALL_SILENT=True 라 send_telegram 이 전부 무음 처리 — 표는 보존).
상태: env EVENT_STATE (루프는 /tmp 사본을 쓰고 커밋 직전에 reports/event_state.json 으로 복사) — 공개 파일이므로 금액 0, 보유 종목 코드는 해시.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import REPORT_DIR
from .defs import CRASH_NEAR_PCT, CRASH_PCT

log = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")
NY = ZoneInfo("America/New_York")
UA = {"User-Agent": "Mozilla/5.0"}

FRESH_KR_SEC = 180
FRESH_US_SEC = 300
MIN_GAP_SEC = 60              # 텔레그램 ≤ 1통/분
HALT_HOLD_SEC = 60            # 거래소 '1분 지속' 조건
CB_LEVELS = ((-0.20, "cb3", "서킷브레이커 3단계(매매 종료)"), (-0.15, "cb2", "서킷브레이커 2단계"), (-0.08, "cb1", "서킷브레이커 1단계"))
SIDECAR_PCT = 0.05
HOLD_DROP_PCT = -0.05
US_INDEX_DROP = -0.03
VIX_JUMP = 0.25
US_SYMS = {"SPX": "^GSPC", "NDX": "^NDX", "VIX": "^VIX"}
MAX_LINES = 8                 # STANDARD §4 텔레그램 8줄


# ───────────────────────── 상태 ─────────────────────────
def state_path() -> Path:
    return Path(os.environ.get("EVENT_STATE") or (REPORT_DIR / "event_state.json"))


def load_state(path: Path | None = None) -> dict:
    try:
        st = json.loads((path or state_path()).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        st = {}
    for k, v in (("sent", {}), ("pending", {}), ("queue", [])):
        st.setdefault(k, v)
    return st


def save_state(st: dict, path: Path | None = None) -> None:
    p = path or state_path()
    keep = {k: v for k, v in st["sent"].items() if k.startswith("touch:")}   # touch 는 평생 1회 — 지우지 않는다
    rest = sorted(((k, v) for k, v in st["sent"].items() if not k.startswith("touch:")), key=lambda kv: kv[1])[-300:]
    st["sent"] = dict(sorted({**keep, **dict(rest)}.items()))
    tmp = p.with_suffix(".tmp")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)   # 원자적 교체 — 커밋 단계가 반쯤 쓴 파일을 복사하지 않게


def halted_today(market: str, day: str, st: dict | None = None) -> bool:
    """events.check(뉴스 감지)가 소리 중복을 피할 때 쓴다: 오늘 이 시장 halt 가 이미 나갔나."""
    st = st if st is not None else load_state()
    mks = (market, "K200F") if market == "KOSPI" else (market,)   # 코스피 사이드카 프록시는 선물(K200F) 키
    return any(k.startswith(tuple(f"halt:{m}:" for m in mks)) and k.endswith(f":{day}") for k in st.get("sent", {}))


def _h(code: str) -> str:
    """보유 종목 코드 → 공개 상태 파일용 해시 (키는 비공개 채팅 ID — 코드 2천여 개라 소금 없으면 역산 가능)."""
    salt = (os.environ.get("TELEGRAM_CHAT_ID") or os.environ.get("EVENT_SALT") or "").encode()
    return hmac.new(salt, str(code).encode(), hashlib.sha256).hexdigest()[:10]


# ───────────────────────── 시세 ─────────────────────────
def _num(x):
    try:
        return float(str(x).replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return None


def parse_naver(j: dict) -> dict | None:
    """네이버 모바일 basic → {last, chg, ts, status, stop, name} (등락 부호는 live.kr_naver 와 같은 규칙)."""
    last = _num(j.get("closePrice"))
    ratio = _num(j.get("fluctuationsRatio"))
    if last is None or ratio is None:
        return None
    code = str((j.get("compareToPreviousPrice") or {}).get("code", ""))
    chg = ratio / 100
    if code in ("4", "5"):
        chg = -abs(chg)
    elif code in ("1", "2"):
        chg = abs(chg)
    elif code == "3":
        chg = 0.0
    low = _num(j.get("lowPrice"))
    return {"last": last, "chg": chg, "low": low, "ts": j.get("localTradedAt"), "status": j.get("marketStatus"),
            "stop": (j.get("tradeStopType") or {}).get("name"), "name": j.get("stockName") or j.get("itemCode")}


def naver(kind: str, code: str) -> dict | None:
    import requests
    try:
        r = requests.get(f"https://m.stock.naver.com/api/{kind}/{code}/basic", headers=UA, timeout=6)
        r.raise_for_status()
        return parse_naver(r.json())
    except Exception as e:  # noqa: BLE001
        log.warning("네이버 %s 시세 실패: %s", kind, type(e).__name__)   # 코드는 로그에 안 남긴다(보유 노출 방지)
        return None


def us_quotes(syms: list[str]) -> dict:
    """야후 1분봉 2일 → {sym: {last, low, chg, ts}}. chg = 오늘 마지막 / 전일 마지막 1분봉 − 1 (정규장 종가 근사)."""
    import yfinance as yf
    out = {}
    if not syms:
        return out
    df = yf.download(syms, period="2d", interval="1m", progress=False, group_by="ticker", auto_adjust=False, threads=True)
    for s in syms:
        try:
            d = (df[s] if len(syms) > 1 else df).dropna(subset=["Close"])
            if d.empty:
                continue
            idx = d.index.tz_convert(NY) if d.index.tz is not None else d.index.tz_localize("UTC").tz_convert(NY)
            today = idx[-1].date()
            cur = d[[t.date() == today for t in idx]]
            prev = d[[t.date() < today for t in idx]]
            if prev.empty:
                continue
            last, pc = float(cur["Close"].iloc[-1]), float(prev["Close"].iloc[-1])
            out[s] = {"last": last, "low": float(cur["Low"].min()), "chg": last / pc - 1,
                      "ts": (idx[-1] + timedelta(minutes=1)).isoformat(), "name": s}   # 1분봉 시각 = 시작 → 끝 시각으로
        except Exception as e:  # noqa: BLE001
            log.warning("야후 1분봉 실패: %s", type(e).__name__)
    return out


def fresh(q: dict | None, now: datetime, max_age: int) -> bool:
    """시세 시각이 있고 now 기준 max_age 초 안 (미래 60초까지 허용 — 시계 오차). 시각 없으면 신선하지 않음."""
    if not q or q.get("last") is None or not q.get("ts"):
        return False
    try:
        ts = datetime.fromisoformat(str(q["ts"]).replace("Z", "+00:00"))
    except ValueError:
        return False
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=KST)
    age = (now - ts).total_seconds()
    return -60 <= age <= max_age


def kr_open(now: datetime) -> bool:
    t = now.astimezone(KST)
    return t.weekday() < 5 and "0900" <= t.strftime("%H%M") <= "1531"


def us_open(now: datetime) -> bool:
    t = now.astimezone(NY)
    return t.weekday() < 5 and "0930" <= t.strftime("%H%M") <= "1600"


# ───────────────────────── 판정 (순수 함수 — 테스트는 여기에 가짜 시세를 넣는다) ─────────────────────────
def _ev(key, line, also=()):
    return {"key": key, "line": line, "also": list(also)}


def _news_halt_today(day: str) -> set[str]:
    """events.json 에 오늘 뉴스로 잡힌 서킷·사이드카 시장 (뉴스가 먼저 울렸으면 프록시는 조용히 표시만)."""
    try:
        ev = json.loads((REPORT_DIR / "events.json").read_text(encoding="utf-8")).get("events", [])
    except Exception:  # noqa: BLE001
        return set()
    return {e.get("market") for e in ev if e.get("date") == day and not str(e.get("type", "")).startswith("경보")
            and re.search(r"서킷|사이드카", str(e.get("type", "")))}


def _halt_candidates(now: datetime, idx: dict) -> list[tuple[str, str, dict]]:
    """지금 시세가 거래소 발동 조건(1분 지속 전)을 만족하는 (키 몸통, 설명, 시세) 목록."""
    hm = now.astimezone(KST).strftime("%H%M")
    out = []
    for k in ("KOSPI", "KOSDAQ"):
        q = idx.get(k)
        if not q:
            continue
        for thr, tag, label in CB_LEVELS:
            if q["chg"] <= thr and (tag == "cb3" or hm < "1450"):
                out.append((f"{k}:{tag}", f"{label} 조건 — {k} {q['chg']*100:+.2f}% ({q['last']:,.2f}) 1분 지속", q))
                break
    f = idx.get("FUT")
    if f and "0905" <= hm < "1450" and abs(f["chg"]) >= SIDECAR_PCT:
        side = "sell" if f["chg"] < 0 else "buy"
        out.append((f"K200F:sidecar-{side}", f"{'매도' if side == 'sell' else '매수'} 사이드카 조건 — 코스피200 선물 {f['chg']*100:+.2f}% 1분 지속", f))
    return out


def kr_events(now: datetime, idx: dict, stocks: dict, rules: dict, held: dict, st: dict,
              alerts_sent: dict | None = None) -> list[dict]:
    """idx = {'KOSPI'|'KOSDAQ'|'FUT': 시세}, stocks = {코드: 시세}, held = {코드: 이름} (국내 보유), rules = pb.rules(MY_RULES)."""
    from . import alerts
    day = now.astimezone(KST).strftime("%Y-%m-%d")
    idx = {k: q for k, q in idx.items() if fresh(q, now, FRESH_KR_SEC)}
    stocks = {c: q for c, q in stocks.items() if fresh(q, now, FRESH_KR_SEC)}
    out: list[dict] = []

    # 1) touch — alerts.touch_lines 재사용 (신선한 시세만 넘긴다). 평생 1회: 이벤트 상태 + 규정 알림 상태 둘 다 본다
    done_touch = {k.split(":", 1)[1] for k in st["sent"] if k.startswith("touch:")}
    done_touch |= {k.rsplit(":", 1)[1] for k in (alerts_sent or {}) if ":touch:" in k}
    for key, line in alerts.touch_lines(fetch=lambda c: stocks.get(c)):
        if key.split(":", 1)[1] not in done_touch:
            out.append(_ev(key, line))

    # 2) 지수 급락 −4% / −5% (무음)
    for k, nm in (("KOSPI", "코스피"), ("KOSDAQ", "코스닥")):
        q = idx.get(k)
        if not q:
            continue
        c = q["chg"]
        k4, k5 = f"{k.lower()}-4:{day}", f"{k.lower()}-5:{day}"
        if c <= CRASH_PCT:
            out.append(_ev(k5, f"📉 {nm} 장중 {c*100:+.2f}% ({q['last']:,.2f}) — 급락일 기준 {CRASH_PCT*100:.0f}% 도달 (확정은 종가 · 15:05 종가 판단 메시지 별도)", [k4]))
        elif c <= CRASH_NEAR_PCT:
            out.append(_ev(k4, f"📉 {nm} 장중 {c*100:+.2f}% ({q['last']:,.2f}) — 급락일 근접 {CRASH_NEAR_PCT*100:.0f}% (기준 {CRASH_PCT*100:.0f}%)"))

    # 3) 서킷·사이드카 (소리) — 두 표본 60초 지속 프록시 + 선물 거래정지 필드
    news = _news_halt_today(day)
    live = set()
    for body, label, q in _halt_candidates(now, idx):
        key = f"halt:{body}:{day}"
        live.add(key)
        if key in st["sent"]:
            continue
        mk = "KOSPI" if body.startswith("K200F") else body.split(":")[0]
        if mk in news:
            st["sent"][key] = now.astimezone(KST).strftime("%Y-%m-%d %H:%M") + " 뉴스먼저"
            continue
        first = st["pending"].get(key)
        if not first:
            st["pending"][key] = q["ts"]
            continue
        try:
            held_s = (datetime.fromisoformat(str(q["ts"])) - datetime.fromisoformat(str(first))).total_seconds()
        except ValueError:
            held_s = 0
        if held_s >= HALT_HOLD_SEC:
            out.append(_ev(key, f"🚨 <b>{label.split(' 조건')[0]} 발동 추정</b> — {label.split(' — ')[1]} (지수 프록시, 거래소 공지로 확인)"))
    f = idx.get("FUT")
    kp = idx.get("KOSPI")
    if f and f.get("stop") not in (None, "", "TRADING") and ((kp and kp["chg"] <= -0.07) or abs(f["chg"]) >= 0.045):
        key = f"halt:K200F:stop:{day}"
        live.add(key)
        if key not in st["sent"] and not halted_today("KOSPI", day, st) and "KOSPI" not in news:
            out.append(_ev(key, f"🚨 <b>코스피200 선물 거래 정지 표시</b> ({f['stop']}) — 서킷 발동 가능성 · 선물 {f['chg']*100:+.2f}%"))
    for k in [k for k in st["pending"] if k.startswith("halt:") and k not in live]:
        st["pending"].pop(k)   # 조건이 풀리면 '1분 지속' 다시 셈

    # 4) 보유 손절선 장중 이탈 · −5% (무음)
    for code, px in rules.get("price", {}).items():
        if not re.fullmatch(r"\d{6}", code):
            continue
        q = stocks.get(code)
        if not q:
            continue
        probe = q["low"] if q.get("low") else q["last"]
        if probe < px:
            out.append(_ev(f"stopx:{_h(code)}:{day}",
                           f"⚠️ {q.get('name') or code} 손절선 장중 이탈 · {probe:,.0f} &lt; {px:,.0f} — 종가 2일 규칙으로 최종 판정 (무음 경고)"))
    for code, name in held.items():
        q = stocks.get(code)
        if q and q["chg"] <= HOLD_DROP_PCT:
            out.append(_ev(f"hold5:{_h(code)}:{day}", f"🔻 {q.get('name') or name} 장중 {q['chg']*100:+.1f}% (보유 종목)"))
    return out


def us_events(now: datetime, q: dict, rules: dict) -> list[dict]:
    """q = {'^GSPC'|'^NDX'|'^VIX'|티커: 시세}. 날짜 = 뉴욕 거래일."""
    day = now.astimezone(NY).strftime("%Y-%m-%d")
    q = {s: v for s, v in q.items() if fresh(v, now, FRESH_US_SEC) and v.get("chg") is not None}
    out = []
    for k, nm in (("SPX", "S&P500"), ("NDX", "나스닥100")):
        v = q.get(US_SYMS[k])
        if v and v["chg"] <= US_INDEX_DROP:
            out.append(_ev(f"{k.lower()}-3:{day}", f"📉 {nm} 장중 {v['chg']*100:+.2f}% ({v['last']:,.2f}) — −3% 경계"))
    v = q.get(US_SYMS["VIX"])
    if v and v["chg"] >= VIX_JUMP:
        out.append(_ev(f"vix+25:{day}", f"😨 VIX 장중 {v['chg']*100:+.1f}% ({v['last']:.2f}) — +25% 경계"))
    for sym, px in rules.get("price", {}).items():
        if not re.fullmatch(r"[A-Z][A-Z.\-]{0,5}", sym):
            continue
        v = q.get(sym)
        if v:
            probe = v["low"] if v.get("low") else v["last"]
            if probe < px:
                out.append(_ev(f"usstop:{_h(sym)}:{day}", f"⚠️ {sym} 손절선 장중 이탈 · {probe:,.2f} &lt; {px:,.2f} — 종가 기준 최종 판정 (무음 경고)"))
    return out


# ───────────────────────── 전송 ─────────────────────────
def dispatch(evs: list[dict], st: dict, now: datetime, send=None) -> dict:
    """새 이벤트 + 대기열을 1통으로. 직전 전송 60초 안이면 대기열에만 넣는다. 반환 {sent: [키], queued: [키], ring: bool}."""
    from . import alerts
    stamp = now.astimezone(KST).strftime("%Y-%m-%d %H:%M")
    for e in evs:
        if e["key"] in st["sent"]:
            continue
        st["queue"].append([e["key"], e["line"]])
        st["sent"][e["key"]] = stamp + " 대기"
        for a in e["also"]:
            st["sent"].setdefault(a, stamp + " 상위")
    res = {"sent": [], "queued": [k for k, _ in st["queue"]], "ring": False}
    if not st["queue"]:
        return res
    last = st.get("last_send")
    if last:
        try:
            if (now - datetime.fromisoformat(last)).total_seconds() < MIN_GAP_SEC:
                return res
        except ValueError:
            pass
    keys = [k for k, _ in st["queue"]]
    lines = [ln for _, ln in st["queue"]]
    if len(lines) > MAX_LINES - 1:
        lines = lines[:MAX_LINES - 2] + [f"… 외 {len(lines) - (MAX_LINES - 2)}건"]
    text = f"⚡ <b>장중 이벤트</b> {now.astimezone(KST).strftime('%H:%M')} KST\n" + "\n".join(lines)
    quiet = alerts.silent(keys)   # 결재 #9 표 하나로만 소리 결정 (지금은 defs.TELEGRAM_ALL_SILENT 로 전부 무음)
    if send is None:
        from .report import send_telegram as send
    send(text, disable_notification=quiet)
    st["queue"] = []
    st["last_send"] = now.isoformat()
    for k in keys:
        st["sent"][k] = stamp
    return {"sent": keys, "queued": [], "ring": not quiet}


def holdings_codes(txt: str) -> tuple[dict, list[str]]:
    """MY_HOLDINGS → ({국내 6자리 코드: 이름}, [미국 티커]). 이름 키는 pb.resolve 로 코드화. 금액은 보지 않는다."""
    from . import pb
    if not txt.strip():
        return {}, []
    idx = pb._index()
    kr, us = {}, []
    for book in pb.parse_books(txt).values():
        for h in book[0]:
            r = pb.resolve(h["key"], idx)
            if r is None and re.fullmatch(r"\d{6}", h["key"]):
                r = ("KR", h["key"])
            if not r:
                continue
            if r[0] == "KR":
                kr[r[1]] = h["key"]
            else:
                us.append(r[1])
    return kr, us


def run(now: datetime | None = None, send=None) -> dict:
    from . import alerts, pb
    now = now or datetime.now(KST)
    k_open, u_open = kr_open(now), us_open(now)
    if not (k_open or u_open):
        log.info("이벤트 감시: 장 시간 밖 — 건너뜀")
        return {"skipped": True}
    rules = pb.rules(os.environ.get("MY_RULES", ""))
    try:
        held_kr, held_us = holdings_codes(os.environ.get("MY_HOLDINGS", ""))
    except Exception as e:  # noqa: BLE001
        log.warning("보유 파싱 실패: %s", type(e).__name__)
        held_kr, held_us = {}, []
    st = load_state()
    evs: list[dict] = []
    if k_open:
        idx = {k: naver("index", k) for k in ("KOSPI", "KOSDAQ", "FUT")}
        codes = set(rules.get("touch", {})) | {c for c in rules.get("price", {}) if re.fullmatch(r"\d{6}", c)} | set(held_kr)
        stocks = {c: naver("stock", c) for c in sorted(codes)}
        missing = [k for k, v in idx.items() if v is None]
        if missing:
            log.warning("이벤트 감시: 데이터 없음(네이버 지수 %s 실패)", ",".join(missing))
        stale = [k for k, v in idx.items() if v and not fresh(v, now, FRESH_KR_SEC)]
        if stale:
            log.warning("이벤트 감시: 오래된 시세 %s — 알림 보류", ",".join(stale))
        try:
            a_sent = json.loads(alerts.STATE.read_text(encoding="utf-8")).get("sent", {})
        except Exception:  # noqa: BLE001
            a_sent = {}
        evs += kr_events(now, idx, stocks, rules, held_kr, st, a_sent)
    if u_open:
        syms = list(US_SYMS.values()) + sorted({s for s in rules.get("price", {}) if re.fullmatch(r"[A-Z][A-Z.\-]{0,5}", s)})
        try:
            evs += us_events(now, us_quotes(syms), rules)
        except Exception as e:  # noqa: BLE001
            log.warning("이벤트 감시: 데이터 없음(야후 1분봉 실패 %s)", type(e).__name__)
    try:
        res = dispatch(evs, st, now, send)
    except Exception as e:  # noqa: BLE001
        log.warning("이벤트 텔레그램 실패: %s — 대기열 유지, 다음 회차 재시도", type(e).__name__)
        res = {"sent": [], "queued": [k for k, _ in st["queue"]], "error": type(e).__name__}
    save_state(st)
    log.info("이벤트 감시: 새 %d건 · 보냄 %s · 대기 %d", len(evs), [alerts.kind(k) for k in res.get("sent", [])], len(res.get("queued", [])))
    return res


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", stream=sys.stderr)
    run()
