"""진입 타점 대결 — 매 거래일 14:55 무렵, PB 가 '지금 들어갈 자리인가'를 규칙으로 판정해 기록하고
겸이의 판단을 받아(깃허브 이슈 'pick') 다음날 실제 가격으로 채점한다.

- PB 판정 규칙(검증 스터디 기반, 단순·고정):
  · 코스피 −3% 이하 & 장중 범위에서 저점 대비 35% 이상 반등한 자리 → KODEX 200 (−5% 이하 & 외국인 매도 1조 이내면 레버리지)
  · 코스피 −3% 이하 & 저점 부근(범위 하단 20%) → 현금 ('떨어지는 칼날')
  · 그 외 → 현금 ('검증된 타점 없음')
- 기본 진입 = 당일 종가, 청산 = 다음날 시가, 금액 100만원(모의)
- 겸이 제출: 저장소에 제목 'pick YYYY-MM-DD' 이슈 → 본문 '종목코드 [금액] [시가|종가|5일]' 또는 '현금'
  (15:30 KST 이전 제출분만 인정, 저장소 주인만)
- 미장 대결(run_us, 22:00 KST): id '<ET날짜>-entry-us', 시가 진입 → 당일 종가 청산, 규칙은 pb_call_us 참고.
  겸이 제출: 'pick-us YYYY-MM-DD' 이슈 → 본문 'TICKER [금액] [당일종가|5일]' 또는 '현금' (09:30 ET 이전만)
"""
from __future__ import annotations

import html
import json
import logging
import re
from datetime import datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo

from . import pick_gate
from .defs import PICK_MIN_RR
from .config import REPORT_DIR

log = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")
ET = ZoneInfo("America/New_York")
REPO = "hk99915-bot/market-screener"
NOTIONAL = 1_000_000
NAMES = {"069500": "KODEX 200", "122630": "KODEX 레버리지", "114800": "KODEX 인버스", "252670": "KODEX 200선물인버스2X",
         "233740": "KODEX 코스닥150레버리지", "229200": "KODEX 코스닥150"}


def _study() -> dict:
    try:
        return json.loads((REPORT_DIR / "studies" / "crash_rebound.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def pb_call() -> dict:
    from . import flows
    from .live import kr_naver
    q = (kr_naver() or {}).get("KOSPI") or {}
    sn = (flows.intraday_snapshot() or {}).get("KOSPI") or {}
    mf = (flows.intraday_market_flows() or {}).get("KOSPI") or {}
    chg, last = q.get("chg"), q.get("last")
    hi, lo = sn.get("high"), sn.get("low")
    pos = (last - lo) / (hi - lo) if last and hi and lo and hi > lo else None
    fx = mf.get("외국인")
    stu = _study()
    lines = [f"코스피 {last:,.2f} ({chg*100:+.2f}%)" if last and chg is not None else "코스피 시세 없음"]
    if pos is not None:
        lines.append(f"장중 범위 안 위치 {pos*100:.0f}% (0=저점, 100=고점)")
    if fx is not None:
        lines.append(f"외국인 현물 {fx/1e4:+.2f}조 · 프로그램 비차익 {sn.get('prog_nonarb') or 0:+,.0f}억")
    pick, why = {"cash": True}, "검증된 타점 없음 — 기다림"
    if chg is not None and chg <= -0.03 and pos is not None:
        if pos < 0.2:
            why = "급락 중 저점 부근 — 떨어지는 칼날, 반등 확인 전"
        elif pos >= 0.35:
            lev = chg <= -0.05 and (fx is None or fx > -10000)
            t = "122630" if lev else "069500"
            pick = {"ticker": t, "name": NAMES[t], "notional": NOTIONAL, "entry": "close", "exit": "next_open"}
            key = "코스피 -5% 이하 날 종가 매수" if chg <= -0.05 else "코스피 -3% 이하 날 종가 매수"
            s = ((stu.get("lev_trade") or {}).get(key) or {}).get("다음날 시가 매도") or {}
            why = (f"급락 후 저점에서 반등한 자리 — {'레버리지(외국인 매도 둔화)' if lev else '현물 지수(레버리지는 조건 미달)'}"
                   + (f". 과거 레버리지 기준 승률 {s.get('up',0)*100:.0f}%·평균 {s.get('avg',0)*100:+.1f}%·최악 {s.get('worst',0)*100:+.1f}% (n={s.get('n')})" if s else ""))
        else:
            why = "급락 중 범위 하단 — 반등 힘 부족"
    if pick.get("ticker"):   # 매매 계획 표준 — 규칙 픽에도 진입·스탑·목표·필터 (10/21 trade plan)
        try:
            from .tradeplan import duel_plan
            pl_ = duel_plan(pick["ticker"], hold_days=1)
            if pl_:
                pick["plan"] = pl_
        except Exception as e:  # noqa: BLE001
            log.info("타점 대결 plan 실패: %s", e)
    return {"pick": pick, "why": why, "lines": lines}


def issue_url_exit(code: str, body: str) -> str:
    return f"https://github.com/{REPO}/issues/new?title={quote('exit ' + code)}&body={quote(body)}"


def issue_url(date: str, body: str = "") -> str:
    return f"https://github.com/{REPO}/issues/new?title={quote('pick ' + date)}&body={quote(body)}"


def issue_url_bold(date: str, body: str = "종목코드 1000000 시가\n근거: ") -> str:
    """🔥 공격 픽(나🔥) — 모의 전용, '나'와 별도 채점."""
    return f"https://github.com/{REPO}/issues/new?title={quote('pick🔥 ' + date)}&body={quote(body)}"


# ── 텔레그램 인라인 버튼 (보드 tg-pick-buttons, 10/20) ─────────────────────────────────────────────
# 폰 텔레그램 내장 브라우저는 깃허브 로그인이 없어 issues/new 프리필 링크가 아무것도 안 됨 → 버튼 → GAS 웹훅
# (apps-script/TelegramHook.gs)이 저장소 주인 PAT 로 같은 'pick …' 이슈를 열고, pick.yml 이 지금처럼 기록한다.
# callback_data = "p|<세션 날짜>|<K|U>|<종목코드·티커|cash>|<청산 코드>" (텔레그램 상한 64바이트). 직접 입력 안내 = "h|<K|U>".
# 청산 코드 → 이슈 본문 단어: KR o=시가(다음날 시가) c=종가(다음날 종가) 5=5일 · US s=당일 종가(빈칸) 5=5일. GAS 쪽이 같은 표를 쓴다
# (tests/test_tg_pick_buttons.py 가 node 로 두 구현을 같은 입력에 돌려 대조). 기존 이슈 링크는 버튼이 안 될 때를 위한 보조로 남긴다.
CB_MAX = 64
CB_EXIT = {"K": {"o": "시가", "c": "종가", "5": "5일"}, "U": {"s": "", "5": "5일"}}
_CB_CODE = {"K": re.compile(r"[0-9A-Za-z]{6}"), "U": re.compile(r"[A-Za-z][A-Za-z.\-]{0,5}")}
KR_BUTTONS = [("069500", "KODEX 200"), ("122630", "레버리지"), ("114800", "인버스")]
US_BUTTONS = [("SPY", "SPY"), ("QQQ", "QQQ"), ("SOXX", "SOXX"), ("SQQQ", "SQQQ")]


def pick_cb(date: str, market: str, code: str, ex: str | None = None) -> str:
    """버튼 callback_data. market 'KR'/'US'(또는 'K'/'U'), code 'cash' = 현금. 64바이트 넘으면 ValueError."""
    m = market[:1].upper()
    ex = ex or ("o" if m == "K" else "s")
    if m not in CB_EXIT or ex not in CB_EXIT[m]:
        raise ValueError(f"시장·청산 코드 오류: {market} {ex}")
    s = f"p|{date}|{m}|{code}|{ex}"
    if len(s.encode("utf-8")) > CB_MAX:
        raise ValueError(f"callback_data {len(s.encode('utf-8'))}바이트 > {CB_MAX}")
    return s


def parse_pick_cb(data: str) -> dict | None:
    """callback_data → {'title','body'} (pick.yml·apply_issue 가 받는 이슈 형식 그대로). 형식이 틀리면 None.
    KR: 'pick YYYY-MM-DD' + '069500 1000000 시가' · US: 'pick-us YYYY-MM-DD' + 'SPY 1000000' · 현금: 본문 '현금'."""
    p = (data or "").split("|")
    if len(p) != 5 or p[0] != "p" or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", p[1]) or p[2] not in CB_EXIT or p[4] not in CB_EXIT[p[2]]:
        return None
    _, d, m, code, ex = p
    title = ("pick " if m == "K" else "pick-us ") + d
    if code == "cash":
        return {"title": title, "body": "현금"}
    if not _CB_CODE[m].fullmatch(code):
        return None
    body = " ".join(x for x in (code if m == "K" else code.upper(), str(NOTIONAL), CB_EXIT[m][ex]) if x)
    return {"title": title, "body": body}


def parse_pick_text(text: str, kr_date: str, us_date_: str) -> dict | None:
    """텔레그램 텍스트 'pick 005930 시가' / 'pick 현금' / 'pick-us QQQ 5일' → {'title','body'}. 날짜는 보낸 시각 기준(KR=KST, US=ET 세션).
    'pick' 으로 시작하지 않으면 None, 'pick' 인데 내용이 틀리면 {'error': 안내문}."""
    t = (text or "").strip()
    m = re.match(r"(?i)^/?(pick-us|pick)(?=\s|$)\s*(.*)$", t, re.S)
    if not m:
        return None
    us = m.group(1).lower() == "pick-us"
    rest = m.group(2).strip().splitlines()[0].strip() if m.group(2).strip() else ""
    title = ("pick-us " + us_date_) if us else ("pick " + kr_date)
    if rest.startswith("현금") or rest.lower() == "cash":
        return {"title": title, "body": "현금"}
    toks = rest.replace(",", "").split()
    if not toks or not re.fullmatch(_CB_CODE["U"].pattern if us else r"[0-9A-Za-z]{6}|[A-Za-z.]{1,6}", toks[0]):   # apply_issue 와 같은 규칙
        return {"error": "형식: pick 종목코드 [금액] [시가|종가|5일] · pick 현금 · pick-us TICKER [금액] [5일]"}
    if us:
        toks[0] = toks[0].upper()
    return {"title": title, "body": " ".join(toks)}


def pick_keyboard(date: str, market: str = "KR") -> dict:
    """대결 메시지에 붙일 inline_keyboard (reply_markup). 후보별 버튼 + 현금 + 직접 입력 안내."""
    m = market[:1].upper()
    rows = [[{"text": n, "callback_data": pick_cb(date, m, c)} for c, n in (KR_BUTTONS if m == "K" else US_BUTTONS)]]
    rows.append([{"text": "현금", "callback_data": pick_cb(date, m, "cash")},
                 {"text": "✍️ 직접 입력 안내", "callback_data": f"h|{m}"}])
    return {"inline_keyboard": rows}


PLAN_HINT_KR = (f"<i>'나' 인정 = 손절·목표·근거 + R:R≥{PICK_MIN_RR:g} (빈 칸·미달·당일 쿨다운 위반은 '나🔥' — 버튼도 계획 칸이 없어 '나🔥'). "
                "텍스트로: pick 069500 시가 손절 -2% 목표 +3% 근거 …</i>")
PLAN_HINT_US = PLAN_HINT_KR.replace("pick 069500 시가", "pick-us QQQ")


def run(send: bool = True) -> dict | None:
    from . import decisions
    now = datetime.now(KST)
    d = str(now.date())
    iid = f"{d}-entry"
    ex = next((x for x in decisions.load().get("items", []) if x["id"] == iid), None)
    if ex and "규칙" in ex.get("picks", {}):
        log.info("오늘 규칙 판정 이미 기록됨")
        return None
    c = pb_call()
    item = {"id": iid, "date": d, "kind": "entry", "title": "진입 타점 대결",
            "note": "규칙: " + c["why"], "picks": {"나": {"pending": True}, "PB": {"pending": True}, "규칙": c["pick"]},
            "basis": {"at": now.strftime("%Y-%m-%d %H:%M"), "src": "판정 시점 스냅샷 (네이버 잠정)", "lines": c["lines"]}}
    if ex:   # PB(판단)·나 가 먼저 들어와 있으면 유지하고 규칙만 추가
        ex["picks"]["규칙"] = c["pick"]
        ex["note"] = (ex.get("note", "") + " · 규칙: " + c["why"]).strip(" ·")
        ex.setdefault("basis", item["basis"])
        item = ex
    decisions.add(item)
    p = c["pick"]
    msg = ["🎯 <b>진입 타점 대결</b> · " + now.strftime("%m/%d %H:%M"), *[f"• {x}" for x in c["lines"]], "",
           "<b>규칙</b>: " + ("현금 유지" if p.get("cash") else f"{p['name']} {NOTIONAL//10000}만 · 종가 진입 → 다음날 시가 청산"),
           "  " + c["why"], "<i>PB 판단은 따로 옴</i>", "",
           "<b>겸이 판단은?</b> 15:30 전까지 — 아래 버튼 (안 되면 링크)",
           f"<a href=\"{issue_url(d, '069500 1000000 시가')}\">KODEX 200</a> · <a href=\"{issue_url(d, '122630 1000000 시가')}\">레버리지</a> · "
           f"<a href=\"{issue_url(d, '114800 1000000 시가')}\">인버스</a> · <a href=\"{issue_url(d, '현금')}\">현금</a> · <a href=\"{issue_url(d, '종목코드 금액 시가')}\">직접 입력</a>"
           f" · <a href=\"{issue_url_bold(d)}\">🔥공격 픽</a>", PLAN_HINT_KR]
    if send:
        from .report import send_telegram
        send_telegram("\n".join(msg), reply_markup=pick_keyboard(d, "KR"))
    log.info("타점 판정 기록: %s", c["why"])
    return item


# ── 미장 진입 타점 대결: 22:00 KST(미 장 시작 전) 판정 → 그날 시가 진입, 종가 청산 ─────────────
US_NAMES = {"SPY": "SPY (S&P500)", "QQQ": "QQQ (나스닥100)", "SOXX": "SOXX (반도체)", "SQQQ": "SQQQ (나스닥 -3x)"}
US_EX_LBL = {"same_close": "당일 종가", "d5_close": "5거래일째 종가"}


# ── 레버리지 ETF 일일 리셋 비용(변동성 끌림) — 결재 #14 ① 코드 근거 ────────────────────────────
# 레버리지 ETF 는 '일일' 수익률의 L배를 목표로 매일 리셋한다. 여러 날 보유 수익 = Π(1 + L·r_i) − 1 이고,
# 지수 누적 수익의 L배와 다르다 (SEC·FINRA Investor Alert 2009 / Cheng & Madhavan 2009: 끌림 ≈ (L − L²)/2 · σ²T).
# 영향 범위: apply_issue·_apply_issue_us(pick 이슈 답글 + decisions.json picks[slot].lev_drag 필드 추가) · ticket.evaluate(reasons 한 줄). 채점·탭·스케줄 변경 없음.
# 롤백: lev_note_for_pick 호출 2곳과 ticket.py 의 notes.append 1곳을 지우면 기존 동작과 동일(필드는 선택적이라 기존 기록 호환).
from .defs import COOLDOWN_MIN, MOCK_LEV_ETFS, MOCK_LEV_HOLD_DAYS   # noqa: E402  결재 #14 목록·상한 (단일 원천 screener/defs.py)
_LEV_KR = {"253150": 2, "253160": -1, "123320": 2, "123310": -1, "130730": 2, "152500": 2} | {k: v for k, v in MOCK_LEV_ETFS.items() if k.isdigit()}
_LEV_US_3 = ("SOXL", "SOXS", "TQQQ", "SQQQ", "UPRO", "SPXU", "SPXL", "SPXS", "UDOW", "SDOW", "TNA", "TZA", "TECL", "TECS", "LABU", "LABD",
             "FNGU", "FNGD", "YINN", "YANG", "KORU", "NUGT", "DUST", "JNUG", "JDST", "TMF", "TMV", "ERX", "ERY", "DRN", "DRV", "FAS", "FAZ",
             "CURE", "WEBL", "WEBS", "BRKU", "BRKD")
_LEV_US_2 = ("QLD", "QID", "SSO", "SDS", "BOIL", "KOLD", "UCO", "SCO", "TBT", "NVDL", "TSLL", "MSTU", "MSTZ", "CONL", "AMDL", "PLTU",
             "BITU", "BITI", "ETHU", "UVIX", "SVIX")
_LEV_US_INV = ("SOXS", "SQQQ", "SPXU", "SPXS", "SDOW", "TZA", "TECS", "LABD", "FNGD", "YANG", "DUST", "JDST", "TMV", "ERY", "DRV", "FAZ",
               "WEBS", "BRKD", "QID", "SDS", "KOLD", "SCO", "TBT", "MSTZ", "BITI")


def lev_factor(code: str, name: str = "", market: str = "KR") -> int:
    """레버리지 배수(부호 포함). 일반 ETF·주식 = 0. KR: 코드표 + 이름(레버리지 2 / 인버스 −1 / 인버스2X −2). US: 티커표 + 이름(2x·3x·Bull·Bear)."""
    code, n = str(code or "").upper(), str(name or "")
    if market != "KR" and code in MOCK_LEV_ETFS:
        return MOCK_LEV_ETFS[code]
    if market == "KR":
        if code in _LEV_KR:
            return _LEV_KR[code]
        if "인버스2X" in n.replace(" ", "") or ("인버스" in n and "2X" in n.upper()):
            return -2
        if "인버스" in n:
            return -1
        return 2 if "레버리지" in n else 0
    sign = -1 if (code in _LEV_US_INV or re.search(r"\b(Bear|Inverse|Short)\b", n, re.I)) else 1
    if code in _LEV_US_3 or re.search(r"\b3x\b", n, re.I):
        return 3 * sign
    if code in _LEV_US_2 or re.search(r"\b2x\b|\bUltra\b", n, re.I):
        return 2 * sign
    return 0


def lev_drag(rets: list[float], lev: float) -> dict:
    """일일 수익률 r_i 열에 대해: etf = Π(1+L·r_i)−1 (일일 리셋 복리), index = Π(1+r_i)−1, naive = L·index(초보가 기대하는 값),
    drag = etf − naive (%p, 보통 음수 = 변동성 끌림). 전부 소수(0.01 = 1%)."""
    etf, idx = 1.0, 1.0
    for r in rets:
        etf *= 1 + lev * r
        idx *= 1 + r
    etf, idx = etf - 1, idx - 1
    return {"etf": etf, "index": idx, "naive": lev * idx, "drag": etf - lev * idx, "days": len(rets), "lev": lev}


def lev_drag_note(name: str, lev: float, days: int = 5, swing: float = 0.03) -> str:
    """결정 기록에 붙이는 한 줄 — 지수가 ±swing 을 days 일 번갈아 오갈 때(끝은 거의 제자리) 레버리지 ETF 가 얼마를 잃는지.
    예) SOXL 3배, 2일 ±3% 왕복: 지수 −0.09% · 3배 기대 −0.27% · 실제 −0.81% (끌림 −0.54%p). 홀수 보유일은 짝수로 내림."""
    days = max(2, int(days) - int(days) % 2)   # 짝수일 = 지수가 거의 제자리로 돌아오는 '왕복' 그림
    rets = [swing if i % 2 == 0 else -swing for i in range(days)]
    x = lev_drag(rets, lev)
    return (f"{name} {lev:+g}배 일일 리셋 — {days}일 보유·지수 ±{swing*100:.0f}% 왕복 가정: 지수 {x['index']*100:+.2f}% → "
            f"{lev:g}배 기대 {x['naive']*100:+.2f}% vs 실제 {x['etf']*100:+.2f}% (끌림 {x['drag']*100:+.2f}%p). 보유 길수록·흔들릴수록 커진다")


_HOLD_DAYS = {"next_open": 2, "same_close": 2, "next_close": 2, "d5_close": 5, "trail": 20}


def lev_note_for_pick(pick: dict, market: str = "KR") -> str | None:
    """pick dict 에 레버리지 ETF 가 들어 있으면 끌림 한 줄, 아니면 None. 보유일은 청산 방식에서 추정(trail 은 20일 가정)."""
    if not pick or pick.get("cash"):
        return None
    lev = lev_factor(pick.get("ticker", ""), pick.get("name", ""), market)
    if not lev:
        return None
    return lev_drag_note(pick.get("name") or pick.get("ticker"), lev, _HOLD_DAYS.get(pick.get("exit"), 5))


# ── 결재 #14 (10/17 14:09): 모의 레버리지 ETF 보유 상한 1일 + 매도·포상 후 30분 쿨다운 — 새 제출부터만(소급 없음) ──────
_CAP_EXIT = {"KR": {"d5_close": "next_close", "trail": "next_close"}, "US": {"d5_close": "same_close"}}
_EX_KO = {"next_open": "다음날 시가", "next_close": "다음날 종가", "d5_close": "5일 뒤 종가", "trail": "추세 이탈 시", "same_close": "당일 종가"}


def lev_cap(pick: dict, market: str = "KR") -> dict:
    """레버리지·인버스 ETF 모의 픽은 보유 MOCK_LEV_HOLD_DAYS(1)일 상한 — 더 긴 청산은 1일 청산으로 바꾸고 lev_cap 라벨 + 리셋 비용(lev_drag) 표시."""
    if not pick or pick.get("cash"):
        return pick
    lev = lev_factor(pick.get("ticker", ""), pick.get("name", ""), market)
    if not lev:
        return pick
    ex = pick.get("exit")
    new = _CAP_EXIT.get(market, {}).get(ex, ex)
    lbl = f"레버리지 {lev:+g}배 보유 상한 {MOCK_LEV_HOLD_DAYS}일(결재 #14)" + (f" — 청산 '{_EX_KO.get(ex, ex)}' → '{_EX_KO.get(new, new)}'로 조정" if new != ex else "")
    out = dict(pick) | {"exit": new, "lev_cap": lbl}
    out["lev_drag"] = "리셋 비용: " + lev_drag_note(pick.get("name") or pick.get("ticker"), lev, 2)
    return out


def mock_cooldown(t: datetime, minutes: int = COOLDOWN_MIN) -> str | None:
    """매도(exit 이슈 '매도')·포상(ops/cooldown.json · env COOLDOWN_LAST_AT) 뒤 minutes 분 안이면 새 모의 베팅 거부 사유(남은 분 포함). 주문표 판정은 제외."""
    from datetime import timedelta
    from .ticket import cooldown_events
    win = timedelta(minutes=minutes)
    last = None
    for at, lbl in cooldown_events():
        if lbl.startswith("주문표"):
            continue
        if at <= t < at + win and (last is None or at > last[0]):
            last = (at, lbl)
    if not last:
        return None
    until = last[0] + win
    left = int((until - t).total_seconds() // 60) + 1
    return (f"⏳ 쿨다운 — {last[0].astimezone(KST):%H:%M} {last[1]} 후 {minutes}분 동안 새 모의 베팅 금지 "
            f"({left}분 남음, {until.astimezone(KST):%H:%M} 이후 다시 제출; 결재 #14). 현금 제출은 받음.")


def us_date(now: datetime | None = None) -> str:
    """미 정규장 세션 날짜 = 지금 뉴욕 날짜 (22:00 KST = 09:00 ET 같은 날)."""
    return str((now or datetime.now(KST)).astimezone(ET).date())


def us_open_kst(d: str) -> datetime:
    """그 날짜 09:30 ET (= 정규장 시작, 제출 마감)."""
    y, m, dd = map(int, d.split("-"))
    return datetime(y, m, dd, 9, 30, tzinfo=ET)


def issue_url_us(date: str, body: str = "") -> str:
    return f"https://github.com/{REPO}/issues/new?title={quote('pick-us ' + date)}&body={quote(body)}"


def pb_call_us(d: str | None = None) -> dict:
    """미장 규칙(단순·고정, macro_series 일봉):
      dd20 = SPX 최근 종가 / 최근 21개 종가 최고치 − 1, ret1 = SPX 전일 수익률, VIX 최근값
      · dd20 ≤ −3% & ret1 ≥ 0  → SPY 롱 (눌림 후 반등 확인)
      · dd20 ≤ −7% & VIX ≥ 25  → SPY 롱 ('공포 구간 역발상')
      · 그 외 → 현금 ('검증된 타점 없음')
    진입 = 당일 시가, 청산 = 당일 종가."""
    try:
        ser = json.loads((REPORT_DIR / "macro_series.json").read_text(encoding="utf-8")).get("series") or {}
    except Exception:  # noqa: BLE001
        ser = {}

    def closes(k):   # 세션 날짜 당일(진행 중) 봉은 제외 — 판정은 전일 종가까지
        return [(b[0], float(b[4])) for b in (ser.get(k) or []) if b and b[4] and (d is None or b[0] < d)]
    spx, vix, ndx = closes("SPX"), closes("VIX"), closes("NASDAQ")
    lines, dd20, ret1, v = [], None, None, (vix[-1][1] if vix else None)
    if len(spx) >= 2:
        last = spx[-1][1]
        ret1 = last / spx[-2][1] - 1
        dd20 = last / max(c for _, c in spx[-21:]) - 1
        lines.append(f"S&P500 {last:,.2f} ({ret1*100:+.2f}%, {spx[-1][0][5:]}) · 20일 고점 대비 {dd20*100:+.1f}%")
    else:
        lines.append("S&P500 시계열 없음")
    if v is not None:
        lines.append(f"VIX {v:.2f}")
    if len(ndx) >= 2:
        lines.append(f"나스닥 {ndx[-1][1]:,.0f} ({(ndx[-1][1]/ndx[-2][1]-1)*100:+.2f}%)")
    pick, why = {"cash": True}, "검증된 타점 없음 — 기다림"
    spy = {"ticker": "SPY", "name": US_NAMES["SPY"], "notional": NOTIONAL, "entry": "open", "exit": "same_close"}
    if dd20 is not None and ret1 is not None and dd20 <= -0.03 and ret1 >= 0:
        pick, why = spy, f"20일 고점 대비 {dd20*100:.1f}% 눌린 뒤 전일 반등({ret1*100:+.2f}%) — 반등 확인 자리"
    elif dd20 is not None and v is not None and dd20 <= -0.07 and v >= 25:
        pick, why = spy | {"note": "공포 구간 역발상"}, f"공포 구간 역발상 — 20일 고점 대비 {dd20*100:.1f}%, VIX {v:.1f}"
    elif dd20 is not None and dd20 <= -0.03:
        why = f"20일 고점 대비 {dd20*100:.1f}% 눌렸지만 전일도 하락 — 반등 확인 전"
    return {"pick": pick, "why": why, "lines": lines, "dd20": dd20, "ret1": ret1, "vix": v}


def _us_links(d: str) -> str:
    return " · ".join(f"<a href=\"{issue_url_us(d, b)}\">{n}</a>" for b, n in
                      [("SPY 1000000", "SPY"), ("QQQ 1000000", "QQQ"), ("SOXX 1000000", "SOXX"), ("SQQQ 1000000", "SQQQ"),
                       ("현금", "현금"), ("TICKER 금액 [5일]", "직접 입력")])


def _us_item(d: str) -> dict:
    return {"id": f"{d}-entry-us", "date": d, "market": "US", "kind": "entry", "title": "미장 진입 타점 대결",
            "note": "", "picks": {"나": {"pending": True}, "PB": {"pending": True}}}


def run_us(send: bool = True) -> dict | None:
    from . import decisions
    now = datetime.now(KST)
    d = us_date(now)
    if datetime.fromisoformat(d).weekday() >= 5:
        log.info("미장 주말(%s) — 대결 없음", d)
        return None
    iid = f"{d}-entry-us"
    ex = next((x for x in decisions.load().get("items", []) if x["id"] == iid), None)
    if ex and "규칙" in ex.get("picks", {}):
        log.info("오늘 미장 규칙 판정 이미 기록됨")
        return None
    c = pb_call_us(d)
    item = _us_item(d) | {"note": "규칙: " + c["why"],
                          "basis": {"at": now.strftime("%Y-%m-%d %H:%M"), "src": "판정 시점 일봉 (macro_series, 전일 종가 기준)", "lines": c["lines"]}}
    item["picks"]["규칙"] = c["pick"]
    if ex:   # PB(판단)·나 가 먼저 들어와 있으면 유지하고 규칙만 추가
        ex["picks"]["규칙"] = c["pick"]
        ex["note"] = (ex.get("note", "") + " · 규칙: " + c["why"]).strip(" ·")
        ex.setdefault("basis", item["basis"])
        ex.setdefault("market", "US")
        item = ex
    decisions.add(item)
    p = c["pick"]
    dl = us_open_kst(d).astimezone(KST)
    msg = ["🗽 <b>미장 진입 타점 대결</b> · " + now.strftime("%m/%d %H:%M") + f" KST (세션 {d[5:]})", *[f"• {x}" for x in c["lines"]], "",
           "<b>규칙</b>: " + ("현금 유지" if p.get("cash") else f"{p['name']} {NOTIONAL//10000}만 · 시가 진입 → 당일 종가 청산"),
           "  " + c["why"], "<i>PB 판단은 따로 옴</i>", "",
           f"<b>겸이 판단은?</b> 미장 시작(09:30 ET = {dl:%H:%M} KST) 전까지 — 아래 버튼 (안 되면 링크)",
           _us_links(d), PLAN_HINT_US]
    if send:
        from .report import send_telegram
        send_telegram("\n".join(msg), reply_markup=pick_keyboard(d, "US"))
    log.info("미장 타점 판정 기록: %s", c["why"])
    return item


def _apply_issue_us(title: str, body: str, created_at: str) -> str:
    """이슈 'pick-us YYYY-MM-DD' → 미장 대결 '나' 칸. 마감 = 그 날짜 09:30 ET."""
    from . import decisions
    import re
    m = re.search(r"(\d{4}-\d{2}-\d{2})", title or "")
    if not m:
        return "제목에 날짜(pick-us YYYY-MM-DD)가 없어 기록하지 못했어."
    d = m.group(1)
    t = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    dl = us_open_kst(d)
    tk = t.astimezone(KST)
    if t >= dl:
        return f"{d} 미장 시작(09:30 ET = {dl.astimezone(KST):%m-%d %H:%M} KST) 이후 제출({tk:%m-%d %H:%M} KST)이라 반영하지 않았어. 시가 진입이라 개장 전에만 받아."
    first = (body or "").strip().splitlines()[0].strip() if (body or "").strip() else ""
    first, plan_tail = pick_gate.split_head(first)   # 결재 10/23 ①: 계획 칸 분리
    if first.startswith("현금") or first.lower() == "cash":
        pick = {"cash": True}
    else:
        toks = first.replace(",", "").split()
        if not toks or not re.fullmatch(r"[A-Za-z][A-Za-z.\-]{0,5}", toks[0]):
            return "본문 첫 줄을 'TICKER [금액] [당일종가|5일]' 또는 '현금'으로 적어줘. 예: QQQ 1000000"
        tk_ = toks[0].upper()
        amt = next((float(x) for x in toks[1:] if re.fullmatch(r"\d+(\.\d+)?", x)), NOTIONAL)
        ex = "d5_close" if "5일" in first else "same_close"
        pick = {"ticker": tk_, "name": US_NAMES.get(tk_, tk_), "notional": amt, "entry": "open", "exit": ex}
        cd = mock_cooldown(t.astimezone(KST))
        if cd:
            return cd
        pick = lev_cap(pick, "US")
    data = decisions.load()
    it = next((x for x in data.get("items", []) if x["id"] == f"{d}-entry-us"), None)
    if not it:
        it = _us_item(d) | {"note": "PB 판정 없음(겸이 단독 기록)"}
        it["picks"]["PB"] = {"cash": True}
        data["items"].append(it)
    slot, pick, extra = _gate(pick, plan_tail, body, tk, it, data, decisions)
    if slot == "나🔥":
        pick = pick | {"unlock_evidence": False}   # 결재 #14
    ln = pick.get("lev_drag") or lev_note_for_pick(pick, "US")
    it["picks"][slot] = pick | {"submitted": tk.strftime("%H:%M")} | ({"lev_drag": ln} if ln else {})
    decisions.OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return (f"기록 완료 ✅ 미장 {d} {slot}: " + ("현금" if pick.get("cash") else f"{pick['name']} {pick['notional']:,.0f}원 · 시가 진입 → {US_EX_LBL[pick['exit']]} 청산")
            + f" (제출 {tk:%H:%M} KST)" + _gate_lines(pick, extra) + (f"\n⏱ {pick['lev_cap']}" if pick.get("lev_cap") else "") + (f"\n⚠ {ln}" if ln else ""))


def apply_issue(title: str, body: str, created_at: str) -> str:
    """이슈 'pick YYYY-MM-DD' → 그날 타점 대결의 '나' 칸 채움. 반환: 이슈에 남길 답글.
    'pick-us YYYY-MM-DD' 는 미장 대결로 넘김.
    'pick🔥 YYYY-MM-DD' (또는 'pick-bold') → '나🔥' 칸 (공격 픽 · 모의 전용 · 별도 채점). 본문 둘째 줄 = 근거(없으면 '감')."""
    if (title or "").strip().lower().startswith("pick-us"):
        return _apply_issue_us(title, body, created_at)
    from . import decisions
    import re
    m = re.search(r"(\d{4}-\d{2}-\d{2})", title or "")
    if not m:
        return "제목에 날짜(pick YYYY-MM-DD)가 없어 기록하지 못했어."
    d = m.group(1)
    t = datetime.fromisoformat(created_at.replace("Z", "+00:00")).astimezone(KST)
    if str(t.date()) != d or t.hour * 100 + t.minute > 1530:
        return f"{d} 15:30 KST 이후 제출({t:%m-%d %H:%M})이라 반영하지 않았어. 종가 진입이라 마감 전에만 받아."
    data = decisions.load()
    it = next((x for x in data.get("items", []) if x["id"] == f"{d}-entry"), None)
    if not it:
        it = {"id": f"{d}-entry", "date": d, "kind": "entry", "title": "진입 타점 대결", "note": "PB 판정 없음(겸이 단독 기록)",
              "picks": {"나": {"pending": True}, "PB": {"cash": True}}}
        data["items"].append(it)
    first = (body or "").strip().splitlines()[0].strip() if (body or "").strip() else ""
    first, plan_tail = pick_gate.split_head(first)   # 결재 10/23 ①: 첫 줄 뒤쪽 '손절·목표·근거' 는 계획 칸 (금액·청산 판정에서 뺌)
    if first.startswith("현금") or first.lower() == "cash":
        pick = {"cash": True}
    else:
        toks = first.replace(",", "").split()
        if not toks or not re.fullmatch(r"[0-9A-Za-z]{6}|[A-Za-z.]{1,6}", toks[0]):
            return "본문 첫 줄을 '종목코드 [금액] [시가|종가|5일] [손절 −2% 목표 +3% 근거 …]' 또는 '현금'으로 적어줘."
        amt = next((float(x) for x in toks[1:] if re.fullmatch(r"\d+(\.\d+)?", x)), NOTIONAL)
        ex = "trail" if ("끌고" in first or "추세" in first or "trail" in first.lower()) else "next_close" if "종가" in first else "d5_close" if "5일" in first else "next_open"
        pick = {"ticker": toks[0], "name": NAMES.get(toks[0], toks[0]), "notional": amt, "entry": "close", "exit": ex}
        cd = mock_cooldown(t)
        if cd:
            return cd
        pick = lev_cap(pick, "KR")
    tl = (title or "").strip().lower()
    slot = "나🔥" if ("🔥" in tl or tl.startswith("pick-bold")) else "나"
    extra: dict = {}
    if slot == "나🔥":
        lines = [x.strip() for x in (body or "").strip().splitlines()[1:] if x.strip()]
        why = re.sub(r"^근거\s*[:：]\s*", "", lines[0]) if lines else ""
        pick = pick | {"why": why or "감", "basis": "판단" if why and why != "감" else "감"} | ({} if pick.get("cash") else {"notional": float(NOTIONAL)})   # 공격 픽은 100만 고정
    else:
        slot, pick, extra = _gate(pick, plan_tail, body, t, it, data, decisions)
    ln = pick.get("lev_drag") or lev_note_for_pick(pick, "KR")
    if slot == "나🔥":
        pick = pick | {"unlock_evidence": False}   # 결재 #14: 나🔥 는 레버리지 해금 근거에서 제외 (표시 라벨 · 새 기록부터)
    it["picks"][slot] = pick | {"submitted": t.strftime("%H:%M")} | ({"lev_drag": ln} if ln else {})
    decisions.OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return (f"기록 완료 ✅ {d} {slot}: " + ("현금" if pick.get("cash") else f"{pick['name']} {pick['notional']:,.0f}원 · 종가 진입 → " + {"next_open": "다음날 시가", "next_close": "다음날 종가", "d5_close": "5일 뒤 종가", "trail": "추세 이탈(20일선·−8%) 시"}[pick["exit"]] + " 청산") + f" (제출 {t:%H:%M})"
            + _gate_lines(pick, extra) + (f"\n⏱ {pick['lev_cap']}" if pick.get("lev_cap") else "") + (f"\n⚠ {ln}" if ln else ""))


def _gate(pick: dict, plan_tail: str, body: str, t: datetime, it: dict, data: dict, decisions) -> tuple[str, dict, dict]:
    """'나' 제출 → 계획 칸·당일 쿨다운 게이트(pick_gate, 겸이 10/23 결재 ①②). 어기면 '나🔥'(감)로 옮기고 이유를 pick['reclass'] 에.
    옮길 때 같은 판에 먼저 낸 '나' 가 있으면 취소(제출 대기로) — '마지막 제출이 남는다' 규칙 그대로. 반환 (slot, pick, 메시지용 덧붙임)."""
    plan_text = "\n".join([plan_tail, *(body or "").strip().splitlines()[1:]])
    slot, pick, reasons = pick_gate.classify(pick, plan_text, t, it, data.get("items") or [],
                                             ref_fn=lambda c, d: pick_gate.ref_price(c, d), score_fn=decisions._score_pick)
    extra = {}
    if reasons:
        why = (pick.get("plan") or {}).get("why") or "감"
        pick = pick | {"why": why, "basis": "감", "notional": float(NOTIONAL), "reclass": " · ".join(reasons)}   # 감 칸 = 공격 픽과 같은 100만 고정
        old = it["picks"].get("나") or {}
        if not old.get("pending"):
            extra["cancelled"] = old.get("submitted") or "?"
            it["picks"]["나"] = {"pending": True}
        if (it["picks"].get("나🔥") or {}).get("submitted"):
            extra["over_bold"] = it["picks"]["나🔥"]["submitted"]
    return slot, pick, extra


def _gate_lines(pick: dict, extra: dict) -> str:
    out = []
    if pick.get("reclass"):
        out.append(f"↪ '나'가 아니라 '나🔥'(감)로 분류 — {pick['reclass']}")
        if extra.get("cancelled"):
            out.append(f"  (앞서 낸 '나'({extra['cancelled']} 제출)는 취소 — 마지막 제출이 남음)")
        if extra.get("over_bold"):
            out.append(f"  (앞서 낸 '나🔥'({extra['over_bold']} 제출)는 이걸로 바뀜)")
    pl = pick_gate.plan_text_line(pick)
    if pl:
        out.append(pl)
    if pick.get("cooldown"):
        out.append("⏳ " + pick["cooldown"])
    return "".join("\n" + x for x in out)


# ── 매도 타점 대결: '지금 팔까(손절·익절) 말까' ─────────────────────────────
def exit_call(code: str, market: str = "KR") -> dict:
    """PB 규칙: 종가가 20일 저점(STOP) 아래 → 매도 / PSAR 하락 전환 + 50일선 아래 → 매도 / 그 외 보유."""
    p = REPORT_DIR / "detail" / market / f"{code}.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    ch = d.get("chart") or []
    b = ch[-1] if ch else {}
    c = d.get("close") or b.get("c")
    stop = ((d.get("scenarios") or {}).get("bear") or {}).get("stop")
    ps, s50 = b.get("p"), b.get("s50")
    lines = [f"{d.get('name', code)} {c:,.0f}" if c else code]
    if stop:
        lines.append(f"STOP(20일 저점) {stop:,.0f} — 현재가 대비 {(stop/c-1)*100:+.1f}%")
    if ps:
        lines.append(f"PSAR {ps:,.0f} ({'가격 위 = 하락 추세' if ps > c else '가격 아래 = 상승 추세'})" + (f" · 50일선 {s50:,.0f}" if s50 else ""))
    if stop and c < stop:
        act, why = "매도", "종가가 20일 저점 아래 — 지지 이탈, 규칙상 손절"
    elif ps and s50 and ps > c and c < s50:
        act, why = "매도", "PSAR 하락 추세 + 50일선 아래 — 추세가 꺾인 상태, 반등 때 줄이는 게 규칙"
    else:
        act, why = "보유", "아직 지지(20일 저점) 위 — 규칙상 손절 자리 아님" + (" (단, STOP까지 여유가 3% 이내)" if stop and (c / stop - 1) < 0.03 else "")
    return {"name": d.get("name", code), "close": c, "act": act, "why": why, "lines": lines}


def _hold_pick(code, name, amt):
    return {"ticker": code, "name": f"{name} 보유", "notional": amt, "entry": "close", "exit": "d5_close"}


def apply_exit_issue(title: str, body: str, created_at: str) -> str:
    """이슈 'exit 종목코드 [금액]' + 본문 '보유' 또는 '매도' → 매도 타점 대결 기록 (PB 판정 자동, 5거래일 뒤 종가로 채점).
    매도 = 현금(0%), 보유 = 그 종목 5일 수익률. 더 나은 쪽이 승."""
    import re
    from . import decisions
    m = re.search(r"exit\s+([0-9A-Za-z.]{1,8})(?:\s+(\d+))?", title or "", re.I)
    if not m:
        return "제목을 'exit 종목코드 [금액]'으로 적어줘. 예: exit 000660 1260000"
    code, amt = m.group(1).upper() if not m.group(1).isdigit() else m.group(1), float(m.group(2) or NOTIONAL)
    mk = "KR" if code.isdigit() else "US"
    t = datetime.fromisoformat(created_at.replace("Z", "+00:00")).astimezone(KST)
    try:
        c = exit_call(code, mk)
    except Exception as e:  # noqa: BLE001
        return f"{code} 상세 데이터를 찾지 못했어 ({type(e).__name__})."
    mine = "매도" if re.search(r"매도|손절|팔", body or "") else "보유"
    d = str(t.date())
    data = decisions.load()
    ex = next((x for x in data.get("items", []) if x["id"] == f"{d}-exit-{code}"), None)
    if ex and "PB" in ex.get("picks", {}):
        if t.hour * 100 + t.minute > 1530:
            return "15:30 이후 제출이라 오늘 매도 대결엔 반영하지 않았어 (종가 기준 채점)."
        ex["picks"]["나"] = ({"cash": True, "label": "매도"} if mine == "매도" else _hold_pick(code, c["name"], NOTIONAL)) | {"submitted": t.strftime("%H:%M")}
        decisions.OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        pbp = ex["picks"]["PB"]
        return f"기록 완료 ✅ {c['name']} — 나: {mine} / PB: {'매도' if pbp.get('cash') else '보유'} · 5거래일 뒤 종가로 채점"
    item = {"id": f"{d}-exit-{code}", "date": d, "kind": "exit", "title": f"매도 타점 대결 · {c['name']}",
            "note": f"PB: {c['act']} — {c['why']}. 채점: 5거래일 뒤 종가 (매도=현금 0%, 보유=종목 수익률)",
            "picks": {"나": {"cash": True, "label": "매도"} if mine == "매도" else _hold_pick(code, c["name"], amt),
                      "PB": {"cash": True, "label": "매도"} if c["act"] == "매도" else _hold_pick(code, c["name"], amt)},
            "basis": {"at": t.strftime("%Y-%m-%d %H:%M"), "src": "제출 시점 상세 데이터(전일·당일 종가 기준)", "lines": c["lines"]}}
    decisions.add(item)
    same = (mine == c["act"])
    return (f"기록 완료 ✅ {c['name']} — 나: {mine} / PB: {c['act']} ({c['why']})"
            + (" · 둘이 같은 판단이라 이번 판은 무승부" if same else " · 5거래일 뒤 종가로 채점"))



def plan_line(pl: dict | None) -> str | None:
    """🎯 목표 +x% · 손절 −y% · 손익비 1:z · 과거 승률 w% (n) · 기대값 e%"""
    if not pl:
        return None
    f = lambda v, sg=True: (f"{v*100:+.1f}%" if sg else f"{v*100:.0f}%") if isinstance(v, (int, float)) else None  # noqa: E731
    parts = []
    if pl.get("target") is not None:
        parts.append("목표 " + f(pl["target"]))
    if pl.get("stop") is not None:
        parts.append("손절 " + f(pl["stop"]))
    rr = pl.get("rr")
    if rr is None and isinstance(pl.get("target"), (int, float)) and isinstance(pl.get("stop"), (int, float)) and pl["stop"]:
        rr = abs(pl["target"] / pl["stop"])
    if rr is not None:
        parts.append(f"손익비 1:{rr:.1f}")
    if pl.get("win_rate") is not None:
        parts.append(f"과거 승률 {pl['win_rate']*100:.0f}%" + (f" (n={pl['n']})" if pl.get("n") else ""))
    if pl.get("ev") is not None:
        parts.append("기대값 " + f(pl["ev"]))
    if pl.get("basis"):
        parts.append(str(pl["basis"]))
    return "🎯 " + " · ".join(parts) if parts else None


def is_crash_day(today: str | None = None, cmt: dict | None = None, q: dict | None = None) -> bool:
    """오늘이 급락일인가 — reports/committee.json 의 crash_day 플래그(오늘 날짜)를 우선, 없으면 코스피 장중 등락률 ≤ −5% 로 계산.
    PB 책임: 급락일에 PB 가 현금이면 사유가 필수(성적표 '급락일 PB 행동률')."""
    today = today or str(datetime.now(KST).date())
    try:
        if cmt is None:
            cmt = json.loads((REPORT_DIR / "committee.json").read_text(encoding="utf-8"))
        cf = (cmt or {}).get("crash_day") or {}
        if str((cmt or {}).get("date")) == today and cf:
            return bool(cf.get("crash"))
    except Exception:  # noqa: BLE001
        pass
    try:
        if q is None:
            from .live import kr_naver
            q = (kr_naver() or {}).get("KOSPI") or {}
        chg = q.get("chg")
        return chg is not None and float(chg) <= -0.05
    except Exception:  # noqa: BLE001
        return False


CRASH_CASH_LINE = "⚠️ 급락일 현금 — 사유 필수(근거 없는 관망은 복기 대상)"


def mark_crash_day(it: dict, pk: dict, crash: bool) -> dict:
    """급락일이면 항목에 crash_day=True, PB 픽이 현금이면 pb_view.lines 에 경고 한 줄 + crash_day_cash=True (성적표 집계용)."""
    it["crash_day"] = bool(crash)
    pv = it.setdefault("pb_view", {})
    if crash and pk.get("cash"):
        pv["crash_day_cash"] = True
        if CRASH_CASH_LINE not in (pv.get("lines") or []):
            pv["lines"] = list(pv.get("lines") or []) + [CRASH_CASH_LINE]
    else:
        pv["crash_day_cash"] = False
    return it


def _h(x) -> str:
    """텔레그램 parse_mode=HTML 에 들어가는 사용자 텍스트(why/tg/lines/종목명…) 이스케이프 — '<' 가 섞이면 400 'Unsupported start tag'
    (10/30 pb_call run 41010299116). 우리가 붙이는 <b>·<a> 태그는 이 함수를 거치지 않는다. 저장본(decisions.json)은 원문 그대로."""
    return html.escape(str(x if x is not None else ""), quote=False)


def record_pb(payload: dict, send: bool = True) -> str:
    """PB 재량 판단 기록 — 예약 세션이 데이터를 읽고 판단해 workflow_dispatch(pb_call)로 넘김.
    payload: {"pick": {"ticker","notional","exit"} | {"cash": true}, "why": str(공식 기록·터미널용 중립 말투), "tg": str(선택, 텔레그램 전용 말투), "lines": [..], "conviction": "낮음|보통|높음"}"""
    from . import decisions
    now = datetime.now(KST)
    us = str(payload.get("market", "")).upper() == "US"
    d = us_date(now) if us else str(now.date())
    kd = str(now.date())   # 매도 타점 대결은 KST 날짜 기준 (기존 규약)
    iid = f"{d}-entry-us" if us else f"{d}-entry"
    pk = payload.get("pick") or {"cash": True}
    if not pk.get("cash"):
        t = str(pk["ticker"])
        if us:
            t = t.upper()
            pk = {"ticker": t, "name": pk.get("name") or US_NAMES.get(t, t), "notional": float(pk.get("notional") or NOTIONAL),
                  "entry": "open", "exit": "d5_close" if pk.get("exit") == "d5_close" else "same_close"}
        else:
            pk = {"ticker": t, "name": pk.get("name") or NAMES.get(t, t), "notional": float(pk.get("notional") or NOTIONAL),
                  "entry": "close", "exit": pk.get("exit") or "next_open"}
        pk = lev_cap(pk, "US" if us else "KR")   # 결재 #14: PB 도 모의 레버리지 1일 상한
    else:
        pk = dict(pk)
    pk["by"] = "PB 재량"
    pk["at"] = now.strftime("%H:%M")
    data = decisions.load()
    it = next((x for x in data.get("items", []) if x["id"] == iid), None)
    if not it:
        it = (_us_item(d) if us else
              {"id": iid, "date": d, "kind": "entry", "title": "진입 타점 대결", "note": "", "picks": {"나": {"pending": True}}})
        it["picks"].pop("PB", None)
        data["items"].append(it)
    it["picks"]["PB"] = pk
    it["pb_view"] = {"why": payload.get("why", ""), "lines": payload.get("lines") or [], "conviction": payload.get("conviction", ""), "at": pk["at"],
                     "plan": payload.get("plan") or None, "real": payload.get("real") or None}
    if not us:   # 급락일 PB 책임 — 현금이면 사유 필수 줄 추가 (성적표 '급락일 PB 행동률' 집계)
        try:
            mark_crash_day(it, pk, is_crash_day(d))
        except Exception as _e:  # noqa: BLE001
            log.info("급락일 표시 실패: %s", _e)
    # 판단 시점의 관점(렌즈) 상태 스냅샷 — 나중에 어느 렌즈가 맞았는지 귀속 (scripts/view_attribution.py)
    _vs = None
    try:
        from . import views as _views
        _vs = _views.compact()
        if _vs.get("lenses"):
            it["pb_view"]["views_asof"] = _vs.get("asof")
            it["pb_view"]["lenses"] = _vs["lenses"]
    except Exception as _e:  # noqa: BLE001
        log.info("관점 스냅샷 실패: %s", _e)
    # 🔥 공격 PB (매일 필수 · 모의 전용) — 별도 참가자 'PB🔥'로 채점. 현금 판단도 기록
    bold = payload.get("bold")
    if bold and (bold.get("ticker") or bold.get("cash")):
        if bold.get("cash"):
            it["picks"]["PB🔥"] = {"cash": True, "by": "공격 PB", "at": pk["at"]}
        else:
            bt = str(bold["ticker"]).upper() if us else str(bold["ticker"])
            it["picks"]["PB🔥"] = {"ticker": bt, "name": bold.get("name") or (US_NAMES.get(bt, bt) if us else NAMES.get(bt, bt)), "notional": float(bold.get("notional") or NOTIONAL),
                                  "entry": pk.get("entry", "open" if us else "close"), "exit": bold.get("exit") or pk.get("exit") or ("same_close" if us else "next_open"), "by": "공격 PB", "at": pk["at"]}
            it["picks"]["PB🔥"] = lev_cap(it["picks"]["PB🔥"], "US" if us else "KR")
        it["pb_view"]["bold"] = {"why": bold.get("why", ""), "plan": bold.get("plan") or None}
    # 보유 종목 매도 타점 (PB 재량) — 금액은 모의 100만 고정 (실제 보유 수량·금액은 공개 저장소에 남기지 않음)
    ex_msgs = []
    for e in (payload.get("exits") or [])[:12]:
        code = str(e.get("ticker", "")).strip()
        if not code:
            continue
        name = e.get("name") or code
        # 비중 조절: keep = 남길 비중 (1=보유, 0=전량 매도, 0.5=절반 축소/익절, 1.5=50% 추가). act 문구보다 keep 우선
        raw_act = str(e.get("act", ""))
        keep = e.get("keep")
        if not isinstance(keep, (int, float)):
            keep = 0.0 if raw_act.startswith("매도") else 0.5 if ("축소" in raw_act or "익절" in raw_act) else 1.5 if "추가" in raw_act else 1.0
        keep = max(0.0, min(2.0, float(keep)))
        act = "매도" if keep == 0 else ("보유" if keep == 1 else f"{'축소' if keep < 1 else '추가'} → 비중 {keep*100:.0f}%")
        code = code if code.isdigit() else code.upper()
        eid = f"{kd}-exit-{code}"
        hold = _hold_pick(code, name, NOTIONAL)
        rule = None
        try:
            rc = exit_call(code, "KR" if code.isdigit() else "US")
            rule = {"cash": True, "label": "매도"} if rc["act"] == "매도" else hold
        except Exception:  # noqa: BLE001
            pass
        ei = next((x for x in data["items"] if x["id"] == eid), None)
        if not ei:
            ei = {"id": eid, "date": kd, "kind": "exit", "title": f"매도 타점 대결 · {name}", "note": "채점: 5거래일 뒤 종가 (매도=현금 0%, 보유=종목 수익률)",
                  "picks": {"나": {"pending": True}}}
            data["items"].append(ei)
        if keep == 0:
            pbp = {"cash": True, "label": "매도"}
        else:   # 남긴 비중만큼만 수익·손실을 받음 (축소=일부 현금화)
            pbp = _hold_pick(code, name, NOTIONAL * keep) | {"name": f"{name} " + ("보유" if keep == 1 else f"비중 {keep*100:.0f}%")}
        ei["picks"]["PB"] = pbp | {"by": "PB 재량", "at": pk["at"], "keep": keep}
        if rule:
            ei["picks"]["규칙"] = rule
        ei["pb_view"] = {"why": e.get("why", ""), "lines": [], "conviction": e.get("conviction", ""), "at": pk["at"], "plan": e.get("plan") or None}
        if _vs and _vs.get("lenses"):
            ei["pb_view"]["views_asof"] = _vs.get("asof")
            ei["pb_view"]["lenses"] = _vs["lenses"]
        ex_msgs.append(f"• {_h(name)}: <b>{act}</b> — {_h(e.get('why', ''))} " + ((plan_line(e.get("plan")) or "") + " " if e.get("plan") else "") +
                       f"[<a href=\"{issue_url_exit(code, '보유')}\">나는 보유</a> · <a href=\"{issue_url_exit(code, '매도')}\">나는 매도</a>]")
    decisions.OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    ex_lbl = {"next_open": "다음날 시가", "next_close": "다음날 종가", "d5_close": "5일 뒤 종가", "trail": "추세 이탈(20일선·−8%) 시"} | ({"d5_close": "5거래일째 종가", "same_close": "당일 종가"} if us else {})
    if us:
        dl = us_open_kst(d).astimezone(KST)
        msg = ["💬 <b>PB 판단 · 미장</b> · " + now.strftime("%m/%d %H:%M") + f" KST (세션 {d[5:]})" + (f" · 확신 {payload.get('conviction')}" if payload.get("conviction") else ""),
               "<b>" + ("현금 유지" if pk.get("cash") else f"{_h(pk['name'])} {pk['notional']/10000:,.0f}만 · 시가 진입 → {ex_lbl.get(pk['exit'], pk['exit'])} 청산") + "</b>",
               _h(payload.get("why", "")), *([f"💌 {_h(payload['tg'])}"] if payload.get("tg") else []), plan_line(payload.get("plan")), *[f"• {_h(x)}" for x in (payload.get("lines") or [])[:6]], "",
               f"겸이 판단: {_us_links(d)} (미장 시작 {dl:%H:%M} KST 전)"]
    else:
        msg = ["💬 <b>PB 판단</b> · " + now.strftime("%m/%d %H:%M") + (f" · 확신 {payload.get('conviction')}" if payload.get("conviction") else ""),
               "<b>" + ("현금 유지" if pk.get("cash") else f"{_h(pk['name'])} {pk['notional']/10000:,.0f}만 · 종가 진입 → {ex_lbl.get(pk['exit'], pk['exit'])} 청산") + "</b>",
               _h(payload.get("why", "")), *([f"💌 {_h(payload['tg'])}"] if payload.get("tg") else []), *[f"• {_h(x)}" for x in (it["pb_view"].get("lines") or [])[:7]], "",
               f"겸이 판단: <a href=\"{issue_url(d, '069500 1000000 시가')}\">KODEX 200</a> · <a href=\"{issue_url(d, '122630 1000000 시가')}\">레버리지</a> · "
               f"<a href=\"{issue_url(d, '114800 1000000 시가')}\">인버스</a> · <a href=\"{issue_url(d, '현금')}\">현금</a> · <a href=\"{issue_url_bold(d)}\">🔥공격 픽</a> (15:30 전)"]
    rl = payload.get("real") or {}
    if rl:
        msg += ["", "💼 <b>실전 적용</b>: " + ("가능" if rl.get("ok") else "규칙상 비추천") + (f" · 총자산의 {rl['size_pct']*100:.0f}% 이내" if isinstance(rl.get("size_pct"), (int, float)) else "") + (" — " + _h(rl.get("note")) if rl.get("note") else "")]
    if bold and (bold.get("ticker") or bold.get("cash")):
        bp = it["picks"]["PB🔥"]
        msg += ["", "🔥 <b>공격 PB</b>: " + ("현금" if bp.get("cash") else f"{_h(bp['name'])} {bp['notional']/10000:,.0f}만 · " + ex_lbl.get(bp["exit"], bp["exit"]) + " 청산") + " (모의 전용)", _h(bold.get("why", ""))]
        pl2 = plan_line(bold.get("plan"))
        if pl2:
            msg.append(pl2)
    if ex_msgs:
        msg += ["", "<b>보유 종목 매도 타점</b> (5거래일 뒤 종가 채점)", *ex_msgs]
    sent_note = ""
    if send:
        from .report import send_telegram
        body = "\n".join(m for m in msg if m is not None)
        try:   # 기록(decisions.json)은 위에서 이미 저장 — 전송이 실패해도 워크플로 커밋 단계가 돌게 예외를 삼키고 경고만 (10/30 run 41010299116)
            send_telegram(body, disable_notification=True, reply_markup=pick_keyboard(d, "US" if us else "KR"))   # 결재 #9(최종): PB 판단·주문표 ⛔ 거부는 무음 (RING_KINDS 밖)
        except Exception as e:  # noqa: BLE001
            log.warning("PB 판단 텔레그램 전송 실패(기록은 저장됨): %s", e)
            print(f"::warning::pb_call 텔레그램 전송 실패(기록은 저장됨): {e}")
            sent_note = " (텔레그램 전송 실패)"
    return ("PB 판단 기록(미장): " if us else "PB 판단 기록: ") + ("현금" if pk.get("cash") else pk["name"]) + sent_note
