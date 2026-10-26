"""주문표 — 매수 전 필수 기록 (규정 [4]): 종목·매수가·손절가·목표가·근거·예정 보유기간을 먼저 적고, 규칙 검사 결과(통과/절반/거부)와 함께
판단 성적표(reports/decisions.json, kind "ticket")에 남긴다. 그 다음에 주문.

제출: 저장소에 이슈 제목 `ticket <종목코드>` (KR 6자리 또는 미국 티커), 본문:
    매수가 <가격>
    손절가 <가격>
    목표가 <가격>
    근거: <한 줄>
    보유 <n>일
    금액 <원>        ← 선택 (또는 `비중 <pct>%`)

검사(저장소 안 데이터만 사용, 네트워크 없음):
  · 손익비 (목표가−매수가)/(매수가−손절가) < 2 → 거부
  · 손절 = 주문표 손절가 와 매수가 −8% 중 가까운 쪽 (실효 손절)
  · 추격(RSI14 > 70 또는 전일 +5% 이상) → 절반 사이징
  · 09:00–09:30 KST(국장) / 09:30–10:00 ET(미장) 제출 → 거부
  · 레버리지·인버스 ETF(2027-04-15 까지) → 거부
    단, 코스피200 1배 인버스(국장, 헤지 전용 예외 — 겸이 10/26 결재, 비공개 rules.txt [2] 예외 줄) → 거부 대신 '🟡 헤지 예외 — 조건 확인 필요'.
    상한·레거시 평가액은 공개 코드에 넣지 않는다 → 조건은 사람이 비공개 규칙으로 확인. 2배 인버스·레버리지·미국 인버스는 그대로 거부.
  · 당일 서킷브레이커·사이드카 발동(reports/events.json) / CPI·FOMC 당일(reports/calendar.json) → 신규 진입 거부
  · 매도·판정·포상 후 30분 쿨다운(결재 #14 ③): 최근 매도(`exit` 이슈 '매도')·주문표 판정·env COOLDOWN_LAST_AT 시각 +30분 이내 제출 → 거부
    (근거: 10/16 보상 직후 레버리지 충동 — 하우스머니·면허 효과, kb:behavior#3·#8·#22)
  · 재협상 2회째: 같은 규칙(screener/defs.py 이름)이 30일 안 2번 재협상(ops/renego.json) → ⛔ '재협상 2회째' + 본문 `재협상사유: <글>` 없으면 거부.
    사유 글은 저장하지 않는다(기록엔 reason_given True/False 만).
  · 1회 리스크 = 위성 북 × r → 최대 수량 = 리스크 ÷ (매수가 − 실효 손절가)
    위성 북 = env SAT_BOOK_KRW (없으면 3,000,000 모의), r = env RISK_PCT(%) (없으면 0.25, 1단계)

공개 기록 원칙: 위성 북 크기와 100만원을 넘는 금액은 저장하지 않는다. 100만원 이하 선언 금액만 `notional`, 그 외는 `notional_pct`(위성 북 대비 %).
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
from datetime import datetime, timedelta
from urllib.parse import quote

from . import renego
from .config import REPORT_DIR
from .duel import ET, KST, NAMES, REPO, US_NAMES, lev_drag_note, lev_factor

log = logging.getLogger(__name__)

SAT_BOOK_DEFAULT = 3_000_000       # 모의 위성 북 (실제 크기는 env 로만, 기록에 남기지 않음)
PUBLIC_NOTIONAL_CAP = 1_000_000    # 이 금액 이하만 원화로 기록
from .defs import (CRASH_ALERT_PCT, ISA_CRASH_PER_YEAR, ISA_MONTHLY_DAY, RENEGO_REASON_MIN,  # noqa: E402
                   VAR_SEMI_BUY_BAN)
from .defs import COOLDOWN_MIN, HARD_STOP, MIN_RR, RISK_PCT_DEFAULT   # 단일 원천 screener/defs.py (1회 리스크 0.25% · R:R 2 · 손절 8% · 쿨다운 30분)
LEV_BAN_UNTIL = "2027-04-15"
LEV_CODES = {"122630", "252670", "114800", "233740", "251340", "253150", "253160", "123320", "123310", "130730", "152500"}
LEV_RE_KR = re.compile(r"(레버리지|인버스|2X|3X)", re.I)
# 헤지 전용 1배 인버스 예외(겸이 10/26 18:5x 결재 — 비공개 rules.txt [2] 예외 줄). 실계좌 주문표만 해당, 모의 북(HF·알파북·대결)은 무관.
# 금액 상한은 공개 저장소에 쓰지 않는다 — 조건 목록만 표시하고 판정은 '조건 확인 필요'.
HEDGE_INV1_EXC = True
HEDGE_INV1_CODES = {"114800", "123310"}            # KODEX 인버스 · TIGER 인버스 (코스피200 선물 1배)
HEDGE_INV1_OTHER = re.compile(r"코스닥|KOSDAQ|나스닥|미국|S&P|달러|국채|채권|반도체|2X|3X|레버리지|중국|일본|원유|금", re.I)
HEDGE_INV1_CONDS = ("장 전 주문표 + 스트레스(ΔS) 감소 확인", "상한 = 국장 레거시 평가액 대비 비율(비공개 rules.txt [2] — 공개 기록 금지)",
                    "보유 20거래일 상한 · 반등일·레거시 매도 시 같은 비율 축소 · 코스피 50일선 회복 시 전량 청산",
                    "조건 1회 위반 = 예외 철회(전면 금지 복귀) + [9] 최고 단계")
LEV_RE_US = re.compile(r"^(SOXL|SOXS|TQQQ|SQQQ|QLD|QID|SSO|SDS|UPRO|SPXU|SPXL|SPXS|UDOW|SDOW|TNA|TZA|TECL|TECS|LABU|LABD|FNGU|FNGD|"
                       r"TSLL|TSLS|TSLQ|TSLT|NVDL|NVDD|NVDU|NVDS|NVDX|NVD|AAPU|AAPD|AMZU|AMZD|MSFU|MSFD|GGLL|GGLS|METU|METD|CONL|CONI|"
                       r"MSTU|MSTZ|MSTX|SMCX|SMCL|AMDL|AMDS|PLTU|PLTD|COIG|COIN?L|BITU|BITI|ETHU|UVXY|SVXY|UVIX|SVIX|YINN|YANG|KORU|"
                       r"BOIL|KOLD|UCO|SCO|NUGT|DUST|JNUG|JDST|TMF|TMV|TBT|ERX|ERY|DRN|DRV|FAS|FAZ|CURE|WEBL|WEBS|BRKU|BRKD|NFLU|NFLD|AVL|AVS|HOOU|HOOD?X|BABX|ASMU|MUU|RGTU|QBTU|ARMU|CRWL|SHPU)$")
US_LEV_RE_NAME = re.compile(r"(2x|3x|Bull|Bear|Ultra|Leveraged|Inverse|Daily)", re.I)
EVT_HALT = re.compile(r"서킷|사이드카|circuit|sidecar", re.I)
EVT_HALT_NEAR = re.compile(r"경보|근처|해제", re.I)
CAL_MACRO = re.compile(r"\bCPI\b|FOMC|소비자물가", re.I)
COOLDOWN_ENV = "COOLDOWN_LAST_AT"  # 포상·장외 매도 등 기록에 없는 시각을 수동으로 — ISO 또는 'YYYY-MM-DD HH:MM'(KST)


def _j(p):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def sat_book() -> float:
    try:
        return float(os.environ.get("SAT_BOOK_KRW") or SAT_BOOK_DEFAULT)
    except ValueError:
        return float(SAT_BOOK_DEFAULT)


def risk_pct() -> float:
    """r (%) — env RISK_PCT (예: 0.25) 또는 MY_RULES 의 `RISK_PCT 0.25` 줄. 1 이상이면 % 로, 0.01 미만이면 비율로 해석."""
    v = os.environ.get("RISK_PCT")
    if not v:
        for ln in os.environ.get("MY_RULES", "").splitlines():
            p = ln.split()
            if len(p) >= 2 and p[0].upper() in ("RISK_PCT", "RISK"):
                v = p[1]
    try:
        x = float(str(v).rstrip("%")) if v else RISK_PCT_DEFAULT
    except ValueError:
        x = RISK_PCT_DEFAULT
    return x * 100 if 0 < x < 0.01 else x


def usdkrw() -> float:
    try:
        ms = _j(REPORT_DIR / "macro_series.json")["series"]["USDKRW"]
        return float(ms[-1][4] if len(ms[-1]) >= 6 else ms[-1][1])
    except Exception:  # noqa: BLE001
        return 1400.0


def _num(s: str) -> float | None:
    m = re.search(r"-?\d[\d,]*(?:\.\d+)?", s or "")
    return float(m.group(0).replace(",", "")) if m else None


def parse_ticket(title: str, body: str) -> dict:
    """제목 `ticket <코드>` + 본문 줄 → dict. 빠진 필수 항목은 ValueError."""
    m = re.search(r"ticket\s+([0-9]{6}|[A-Za-z][A-Za-z.\-]{0,5})\b", title or "", re.I)
    if not m:
        raise ValueError("제목을 `ticket <종목코드>` 로 적어 주세요. 예: ticket 000660 / ticket AAPL")
    code = m.group(1) if m.group(1).isdigit() else m.group(1).upper()
    out: dict = {"code": code, "market": "KR" if code.isdigit() else "US", "why": "", "horizon_days": None,
                 "entry": None, "stop": None, "target": None, "amount": None, "pct": None, "renego_reason": False,
                 "renego_short": False, "account": "SAT", "side": "BUY", "crash_pre": False}
    keys = {"매수가": "entry", "진입가": "entry", "손절가": "stop", "손절": "stop", "목표가": "target", "목표": "target"}
    for raw in (body or "").splitlines():
        ln = raw.strip().lstrip("-*• ").strip()
        if not ln:
            continue
        head = re.match(r"^([가-힣A-Za-z_]+)\s*[:：]?\s*(.*)$", ln)
        if not head:
            continue
        k, rest = head.group(1), head.group(2)
        if k in keys:
            out[keys[k]] = _num(rest)
        elif k in ("재협상사유", "재협상"):   # 사유 글은 저장하지 않는다 — 10자 이상 적었는지(True)만 (공개 저장소, 오너 승인 10/17)
            out["renego_reason"] = renego.reason_ok(rest)
            out["renego_short"] = bool(rest.strip()) and not out["renego_reason"]
        elif k in ("계좌",):   # 결재 #15: '계좌 ISA' → ISA 코어 매수 주문표 (월 1회·급락일 선매수 연 2회 검사)
            out["account"] = "ISA" if "ISA" in rest.upper() else "SAT"
        elif k in ("구분", "방향"):
            out["side"] = "SELL" if re.search(r"매도|sell", rest, re.I) else "BUY"
        elif k in ("급락선매수", "급락일선매수"):
            out["crash_pre"] = True
        elif k in ("근거", "이유", "why"):
            out["why"] = rest.strip()
        elif k in ("보유", "보유기간", "기간"):
            n = _num(rest)
            out["horizon_days"] = int(n) if n else None
        elif k in ("금액",):
            out["amount"] = _num(rest)
        elif k in ("비중",):
            out["pct"] = _num(rest)
    need = (("매수가", "entry"), ("근거", "why")) if out["account"] == "ISA" else \
        (("매수가", "entry"), ("손절가", "stop"), ("목표가", "target"), ("근거", "why"), ("보유 n일", "horizon_days"))   # ISA 적립은 손절·목표 없음(시장 조건 무시, 결재 #15)
    miss = [n for n, k in need if not out.get(k)]
    if miss:
        raise ValueError("주문표에 빠진 항목: " + " · ".join(miss) + "\n```\n매수가 <가격>\n손절가 <가격>\n목표가 <가격>\n근거: <한 줄>\n보유 <n>일\n금액 <원>  (선택, 또는 비중 <pct>%)\n```")
    return out


def _detail(code: str, mk: str) -> dict:
    return _j(REPORT_DIR / "detail" / mk / f"{code}.json") or {}


def is_hedge_inverse1(code: str, name: str, mk: str) -> bool:
    """코스피200 1배 인버스(헤지 예외 대상) 여부 — 국장만. 2배·다른 기초자산(코스닥·미국·채권 등)은 False."""
    if mk != "KR" or not HEDGE_INV1_EXC:
        return False
    if lev_factor(code, name, mk) != -1:
        return False
    n = str(name or "")
    if code in HEDGE_INV1_CODES:
        return True
    return "인버스" in n and bool(re.search(r"200|코스피|KOSPI", n, re.I)) and not HEDGE_INV1_OTHER.search(n.replace("200", ""))


def is_leveraged(code: str, name: str, mk: str) -> bool:
    if mk == "KR":
        return code in LEV_CODES or bool(LEV_RE_KR.search(name or ""))
    return bool(LEV_RE_US.match(code)) or bool(US_LEV_RE_NAME.search(name or "") and re.search(r"ETF|Shares|Fund|Trust", name or "", re.I))


def _halt_today(d: str, mk: str) -> list[str]:
    ev = (_j(REPORT_DIR / "events.json") or {}).get("events") or []
    out = []
    for e in ev:
        if e.get("date") != d:
            continue
        t = str(e.get("type") or "")
        if EVT_HALT.search(t) and not EVT_HALT_NEAR.search(t) and (mk == "KR" or e.get("market") in ("미국", "US")):
            out.append(f"{e.get('time', '')} {t}".strip())
    return out


def _macro_today(d: str) -> list[str]:
    cal = (_j(REPORT_DIR / "calendar.json") or {}).get("events") or []
    return [e.get("name") for e in cal if e.get("date") == d and CAL_MACRO.search(str(e.get("name") or ""))]


def _parse_kst(s: str | None) -> datetime | None:
    """'YYYY-MM-DD HH:MM'(KST 가정) 또는 ISO(Z 포함) → tz-aware datetime. 실패하면 None."""
    if not s:
        return None
    try:
        t = datetime.fromisoformat(str(s).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return t.replace(tzinfo=KST) if t.tzinfo is None else t


def cooldown_events(items: list[dict] | None = None) -> list[tuple[datetime, str]]:
    """쿨다운 기준 시각 목록 [(시각, 라벨)] — 저장소 안 데이터 + env 만.
    · kind 'exit' 이고 '나'가 매도(cash) → 매도 시각 (picks.나.submitted 'HH:MM' 또는 basis.at)
    · kind 'ticket' → 판정 시각 (submitted 'YYYY-MM-DD HH:MM')
    · env COOLDOWN_LAST_AT → 포상·장외 매도 등 수동 시각"""
    if items is None:
        from . import decisions
        items = decisions.load().get("items") or []
    out: list[tuple[datetime, str]] = []
    for it in items:
        k = it.get("kind")
        if k == "exit":
            me = (it.get("picks") or {}).get("나") or {}
            if not me.get("cash"):
                continue
            at = f"{it.get('date')} {me['submitted']}" if me.get("submitted") else (it.get("basis") or {}).get("at")
            t = _parse_kst(at)
            if t:
                out.append((t, f"매도 {it.get('name') or it.get('title', '')}".strip()))
        elif k == "ticket":
            t = _parse_kst(it.get("submitted"))
            if t:
                out.append((t, f"주문표 판정 {it.get('name') or it.get('code', '')} {it.get('verdict', '')}".strip()))
    t = _parse_kst(os.environ.get(COOLDOWN_ENV))
    if t:
        out.append((t, "수동 기록(포상·매도)"))
    for e in cooldown_file_events():
        out.append(e)
    return out


COOLDOWN_FILE = REPORT_DIR.parent / "ops" / "cooldown.json"   # 포상·장외 매도 시각(시각·라벨만 — 금액 없음). 원본은 pb-private journal 타임라인(결재 #14)


def cooldown_file_events(path=None) -> list[tuple[datetime, str]]:
    """ops/cooldown.json {"events": [{"at": "YYYY-MM-DD HH:MM", "what": "포상"}]} → [(시각, 라벨)]. 파일 없으면 빈 목록."""
    try:
        j = json.loads((path or COOLDOWN_FILE).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []
    out = []
    for e in j.get("events") or []:
        t = _parse_kst(e.get("at"))
        if t:
            out.append((t, str(e.get("what") or "포상")))
    return out


def cooldown_hit(t: datetime, items: list[dict] | None = None, minutes: int = COOLDOWN_MIN) -> str | None:
    """t 가 최근 매도·판정·포상 시각 +minutes 이내면 거부 사유 문자열, 아니면 None. 미래 시각(t 이후)은 무시."""
    win = timedelta(minutes=minutes)
    last = None
    for at, lbl in cooldown_events(items):
        if at <= t < at + win and (last is None or at > last[0]):
            last = (at, lbl)
    if not last:
        return None
    left = int(((last[0] + win) - t).total_seconds() // 60) + 1
    return f"{lbl_at(last[0])} {last[1]} 후 {minutes}분 쿨다운 — 신규 주문표 거부 ({left}분 뒤 가능; 결재 #14 ③)"


def ticket_ctx(code: str, mk: str) -> dict:
    """주문표 판정 맥락 — {'semi', 'below_backstop', 'var_over'}. 보유·VaR 는 MY_HOLDINGS(런타임 시크릿)로만, 공개 기록 안 함.
    시크릿이 없으면 var_over=None·below_backstop=False (+ 사유에 '확인 불가' 표기 — 조용한 통과 금지)."""
    from . import pb
    try:
        semi = pb.semi_code(mk, code)
    except Exception as e:  # noqa: BLE001
        log.warning("반도체 판정 실패 %s: %s", code, type(e).__name__)
        semi = False
    try:
        rc = pb.risk_ctx()
    except Exception as e:  # noqa: BLE001
        log.warning("보유 맥락 실패: %s", type(e).__name__)
        rc = None
    return {"semi": semi or bool(rc and code in rc["semi"]), "below_backstop": bool(rc and code in rc["backstop"]),
            "var_over": rc["var_over"] if rc else None, "has_holdings": rc is not None}


def renego_rows(on, ctx: dict | None = None) -> list[dict]:
    """재협상 2회째 규칙 중 이 주문표와 관련 있는 것 (ops/renego.json · renego.relates). 파일 오류는 빈 목록 + 로그."""
    try:
        return renego.active_for(on, ctx)
    except Exception as e:  # noqa: BLE001
        log.warning("재협상 카운터 읽기 실패: %s", e)
        return []


def lbl_at(t: datetime) -> str:
    return t.astimezone(KST).strftime("%H:%M")


def evaluate(tk: dict, created_at: str, now: datetime | None = None, ctx: dict | None = None) -> dict:
    """규칙 검사 → {verdict, reasons, rr, stop_eff, risk_ps, qty_max, half, ...}. 네트워크 없음. ctx 없으면 ticket_ctx()."""
    code, mk = tk["code"], tk["market"]
    ctx = ctx if ctx is not None else ticket_ctx(code, mk)
    t = datetime.fromisoformat(created_at.replace("Z", "+00:00")) if created_at else (now or datetime.now(KST))
    tk_kst, tk_et = t.astimezone(KST), t.astimezone(ET)
    d = str(tk_kst.date()) if mk == "KR" else str(tk_et.date())
    det = _detail(code, mk)
    name = det.get("name") or (NAMES if mk == "KR" else US_NAMES).get(code, code)
    st = det.get("stats") or {}
    close = det.get("close")
    e, s, g = float(tk["entry"]), float(tk["stop"]), float(tk["target"])
    reject, half, notes = [], [], []
    if s >= e or g <= e:
        reject.append("가격 구조 오류 — 손절가 < 매수가 < 목표가 여야 함")
    stop_eff = max(s, round(e * (1 - HARD_STOP), 4))
    if stop_eff != s:
        notes.append(f"실효 손절 {stop_eff:,.2f} (주문표 손절가보다 −8% 선이 가까움)")
    risk_ps = e - stop_eff
    rr = round((g - e) / (e - s), 2) if e > s else None
    rr_eff = round((g - e) / risk_ps, 2) if risk_ps > 0 else None
    if rr is None or rr < MIN_RR:
        reject.append(f"손익비 1:{rr if rr is not None else '—'} < 1:{MIN_RR:.0f} — 진입 금지")
    hedge_exc = is_hedge_inverse1(code, name, mk)
    if is_leveraged(code, name, mk) and d <= LEV_BAN_UNTIL and not hedge_exc:
        reject.append(f"레버리지·인버스 금지 (~{LEV_BAN_UNTIL})")
    elif hedge_exc and d <= LEV_BAN_UNTIL:
        notes.append("헤지 예외(코스피200 1배 인버스) — 조건 확인 필요: " + " · ".join(HEDGE_INV1_CONDS))
    if is_leveraged(code, name, mk):   # 결재 #14 ①: 금지 여부와 무관하게 리셋 비용(변동성 끌림)을 숫자로 남긴다
        lv = lev_factor(code, name, mk) or 2
        notes.append(lev_drag_note(name, lv, max(2, int(tk.get("horizon_days") or 5))))
    hm = tk_kst.hour * 60 + tk_kst.minute if mk == "KR" else tk_et.hour * 60 + tk_et.minute
    lo, hi, lbl = (540, 570, "09:00–09:30 KST") if mk == "KR" else (570, 600, "09:30–10:00 ET")
    if lo <= hm < hi:
        reject.append(f"개장 첫 30분({lbl}) 진입 금지")
    for h in _halt_today(d, mk):
        reject.append(f"당일 {h} — 장중 신규 진입 금지")
    for mname in _macro_today(d):
        reject.append(f"{mname} 당일 — 장중 신규 진입 금지")
    cd = cooldown_hit(t)
    if cd:
        reject.append(cd)
    # 결재 #3 VaR 계기판: 한도 초과면 반도체 BUY 주문표 ⛔ (매도 주문표·비반도체는 영향 없음, 강제 매도 없음)
    if tk.get("side", "BUY") == "BUY" and ctx.get("semi"):
        if ctx.get("var_over"):
            reject.append(f"⛔ {VAR_SEMI_BUY_BAN} — VaR99 계기판 한도 초과")
        elif ctx.get("var_over") is None:
            notes.append("VaR 계기판 확인 불가(MY_HOLDINGS 없음 — 알림 비활성) — 반도체 매수 전 MY 탭에서 VaR 확인")
    rn = renego_rows(tk_kst.date(), ctx)   # 같은 규칙 30일 안 2회째 재협상 + 이 주문표와 관련 → ⛔ + 사유 칸(10자 이상) 필수 (screener/renego.py)
    if rn:
        if tk.get("renego_reason"):
            notes.append(renego.banner(rn) + " — 사유 기재됨(글은 공개 기록 안 함)")
        elif tk.get("renego_short"):
            reject.append(renego.banner(rn) + f" — 사유가 {RENEGO_REASON_MIN}자 미만: 이유를 문장으로 (글은 저장·공개 안 함)")
        else:
            reject.append(renego.banner(rn) + f" — 사유 칸 필수: 본문에 `재협상사유: <{RENEGO_REASON_MIN}자 이상>` 한 줄 (글은 저장·공개 안 함)")
    rsi, ret1 = st.get("rsi14"), st.get("ret1")
    if isinstance(rsi, (int, float)) and rsi > 70:
        half.append(f"RSI14 {rsi:.0f} > 70 — 추격, 절반 사이징")
    if isinstance(ret1, (int, float)) and ret1 >= 0.05:
        half.append(f"전일 {ret1*100:+.1f}% ≥ +5% — 추격, 절반 사이징")
    if close and abs(e / close - 1) > 0.10:
        notes.append(f"매수가가 최근 종가 {close:,.2f} 와 10% 이상 차이")
    fx = usdkrw() if mk == "US" else 1.0
    # denominator=D5 매매 슬리브(sat_book, env SAT_BOOK_KRW) — 1회 리스크의 분모 (docs/rules_terms.md §0)
    risk_krw = sat_book() * risk_pct() / 100
    qty = int(math.floor(risk_krw / (risk_ps * fx))) if risk_ps > 0 else 0
    if half:
        qty //= 2
    verdict = "⛔ 거부" if reject else "🟡 헤지 예외 — 조건 확인 필요" if (hedge_exc and d <= LEV_BAN_UNTIL) else "⚠️ 절반 사이징" if half else "✅ 통과"
    out = {"hedge_exception": "조건 확인 필요" if (hedge_exc and d <= LEV_BAN_UNTIL and not reject) else None,
           "name": name, "date": d, "close": close, "rr": rr, "rr_eff": rr_eff, "stop_eff": stop_eff, "risk_ps": round(risk_ps, 4),
           "qty_max": qty, "half": bool(half), "verdict": verdict, "reasons": reject + half + notes,
           "submitted": tk_kst.strftime("%Y-%m-%d %H:%M"), "rsi14": rsi, "ret1": ret1}
    if rn:
        out["renego"] = {"rules": [r["rule"] for r in rn], "reason_given": bool(tk.get("renego_reason"))}
    # 공개 금액 규칙: 100만 이하 선언 금액만 원화, 그 외는 위성 북 대비 % (북 크기 자체는 기록하지 않음)
    amt, pct = tk.get("amount"), tk.get("pct")
    if amt and amt <= PUBLIC_NOTIONAL_CAP:
        out["notional"] = float(amt)
    elif amt:
        out["notional_pct"] = round(amt / sat_book() * 100, 1)
    elif pct:
        out["notional_pct"] = float(pct)
    if (amt or pct) and qty and e * fx > 0:
        declared = amt if amt else sat_book() * pct / 100
        if declared > qty * e * fx * 1.0001:
            out["reasons"].append(f"선언 금액이 리스크 한도 수량({qty:,}주) 환산액을 넘음 — 수량 상한 적용")
    return out


def _item(tk: dict, ev: dict) -> dict:
    it = {"id": f"{ev['date']}-ticket-{tk['code']}", "date": ev["date"], "kind": "ticket", "market": tk["market"],
          "title": f"주문표 · {ev['name']}", "code": tk["code"], "name": ev["name"],
          "entry": tk["entry"], "stop": tk["stop"], "target": tk["target"], "stop_eff": ev["stop_eff"], "rr": ev["rr"],
          "horizon_days": tk["horizon_days"], "why": tk["why"], "verdict": ev["verdict"], "reasons": ev["reasons"],
          "qty_max": ev["qty_max"], "half": ev["half"], "submitted": ev["submitted"],
          "note": f"규정 [4] 주문표 · 손익비 1:{ev['rr']} · {ev['verdict']}", "picks": {}}
    for k in ("notional", "notional_pct", "renego"):
        if k in ev:
            it[k] = ev[k]
    return it


def reply_md(tk: dict, ev: dict) -> str:
    rows = [("종목", f"{ev['name']} ({tk['code']})"), ("매수가", f"{tk['entry']:,.2f}"), ("손절가", f"{tk['stop']:,.2f}" + (f" → 실효 {ev['stop_eff']:,.2f}" if ev["stop_eff"] != tk["stop"] else "")),
            ("목표가", f"{tk['target']:,.2f}"), ("손익비", f"1:{ev['rr']}" + (f" (실효 1:{ev['rr_eff']})" if ev.get("rr_eff") not in (None, ev["rr"]) else "")),
            ("주당 리스크", f"{ev['risk_ps']:,.2f}"), ("최대 수량", f"{ev['qty_max']:,}주" + (" (절반)" if ev["half"] else "")),
            ("보유 예정", f"{tk['horizon_days']}일"), ("근거", tk["why"])]
    if "notional" in ev:
        rows.append(("선언 금액", f"{ev['notional']:,.0f}원"))
    elif "notional_pct" in ev:
        rows.append(("선언 비중", f"위성 북의 {ev['notional_pct']}%"))
    tbl = "| 항목 | 값 |\n|---|---|\n" + "\n".join(f"| {a} | {b} |" for a, b in rows)
    rs = "\n".join(f"- {r}" for r in ev["reasons"]) or "- 규칙 위반 없음"
    return f"### 주문표 {ev['verdict']}\n\n{tbl}\n\n**검사 결과**\n{rs}\n\n제출 {ev['submitted']} KST · 기록 id `{ev['date']}-ticket-{tk['code']}` · " + \
        ("기록만 남김 — 이 주문표로는 주문하지 않습니다." if ev["verdict"].startswith("⛔") else
         "헤지 예외 조건(비공개 rules.txt [2] 예외 줄) 확인 후에만 주문 · 성적표에 기록됨." if ev["verdict"].startswith("🟡") else "성적표에 기록됨 — 이제 주문 가능. 청산은 `exit <코드>` 이슈 또는 보유기간 만료로 채점.")


# ───────────── 결재 #15 ISA 코어 매수 (월 1회 · 급락일 선매수 연 2회 상한) ─────────────
ISA_FILE = REPORT_DIR.parent / "ops" / "isa_buys.json"   # 공개: 날짜·종류만 {"events":[{"date","kind":"monthly"|"crash"}]} — 금액·종목 금지
ISA_KEYS = {"date", "kind"}


def isa_load(path=None) -> dict:
    try:
        return json.loads((path or ISA_FILE).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"events": []}


def isa_counts(on, path=None) -> dict:
    """{'month': 이번 달 월 적립 기록 수, 'crash_year': 올해 급락일 선매수 수}."""
    ev = isa_load(path).get("events") or []
    ym, y = str(on)[:7], str(on)[:4]
    return {"month": sum(1 for e in ev if e.get("kind") == "monthly" and str(e.get("date", ""))[:7] == ym),
            "crash_year": sum(1 for e in ev if e.get("kind") == "crash" and str(e.get("date", ""))[:4] == y)}


def isa_monthly_day(on):
    """이번 달 적립일 = ISA_MONTHLY_DAY(1일), 휴장이면 다음 KR 거래일."""
    from . import tradecal
    d = on.replace(day=ISA_MONTHLY_DAY)
    for _ in range(10):
        if tradecal.is_session("KR", d):
            return d
        d += timedelta(days=1)
    return d


def _crash_signal(d: str) -> bool:
    """그날 15:05 급락 신호(alerts_state "<날짜>:crash") 기록이 있는가."""
    try:
        from .alerts import STATE
        if f"{d}:crash" in (json.loads(STATE.read_text(encoding="utf-8")).get("sent") or {}):
            return True
    except Exception:  # noqa: BLE001
        pass
    return False


def evaluate_isa(tk: dict, created_at: str, now: datetime | None = None, path=None, crash=None) -> dict:
    """ISA 매수 주문표: 시장 조건 무시(R:R·추격·개장 30분 검사 없음) · 월 1회(적립일) · 급락일 선매수 연 2회 · 레버리지 금지."""
    t = datetime.fromisoformat(created_at.replace("Z", "+00:00")) if created_at else (now or datetime.now(KST))
    on = t.astimezone(KST).date()
    code, mk = tk["code"], tk["market"]
    name = _detail(code, mk).get("name") or (NAMES if mk == "KR" else US_NAMES).get(code, code)
    c = isa_counts(on, path)
    reject, notes, kind = [], [], None
    if is_leveraged(code, name, mk):
        reject.append("ISA 레버리지·인버스 금지")
    if tk.get("crash_pre"):
        kind = "crash"
        if c["crash_year"] >= ISA_CRASH_PER_YEAR:
            reject.append(f"급락일 선매수 연 {ISA_CRASH_PER_YEAR}회 상한 도달 (올해 {c['crash_year']}회, 결재 #15)")
        elif not (crash if crash is not None else _crash_signal(str(on))):
            reject.append(f"오늘 급락일 신호(15:05 코스피 ≤ {CRASH_ALERT_PCT*100:.1f}%) 기록 없음 — 선매수 아님")
        else:
            notes.append(f"급락일 선매수 {c['crash_year'] + 1}/{ISA_CRASH_PER_YEAR}회째 (올해)")
    else:
        kind = "monthly"
        md = isa_monthly_day(on)
        if on != md:
            reject.append(f"ISA 월 1회 — 적립일 {md}(1일, 휴장이면 다음 거래일)만 (결재 #15 · 시장 조건 무시)")
        elif c["month"] >= 1:
            reject.append("이번 달 ISA 적립 이미 기록됨 — 월 1회")
    verdict = "⛔ 거부" if reject else "✅ 통과"
    return {"name": name, "date": str(on), "kind": kind, "verdict": verdict, "reasons": reject + notes,
            "submitted": t.astimezone(KST).strftime("%Y-%m-%d %H:%M"), "counts": c}


def isa_record(on: str, kind: str, path=None) -> dict:
    fp = path or ISA_FILE
    d = isa_load(fp)
    d.setdefault("_doc", "결재 #15 ISA 매수 카운터 — 날짜·종류(monthly|crash)만. 금액·종목 금지. screener/ticket.py evaluate_isa")
    item = {"date": on, "kind": kind}
    d["events"] = [{k: v for k, v in e.items() if k in ISA_KEYS} for e in (d.get("events") or [])] + [item]
    fp.write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return item


def apply_ticket_issue(title: str, body: str, created_at: str) -> str:
    """이슈 `ticket <코드>` → 규칙 검사 → decisions.json kind 'ticket' 기록. 반환: 이슈 답글(마크다운).
    본문 `계좌 ISA` 면 ISA 검사(evaluate_isa) → 통과 시 ops/isa_buys.json 에 날짜·종류만 기록 (성적표 채점 대상 아님)."""
    from . import decisions
    try:
        tk = parse_ticket(title, body)
    except ValueError as e:
        return f"주문표를 기록하지 못했습니다 — {e}"
    if tk.get("account") == "ISA":
        ev = evaluate_isa(tk, created_at)
        if not ev["verdict"].startswith("⛔"):
            isa_record(ev["date"], ev["kind"])
        rs = "\n".join(f"- {r}" for r in ev["reasons"]) or "- 규칙 위반 없음"
        return f"### ISA 주문표 {ev['verdict']} ({'급락일 선매수' if ev['kind'] == 'crash' else '월 적립'})\n\n{ev['name']} ({tk['code']}) · 제출 {ev['submitted']} KST\n\n**검사 결과**\n{rs}"
    ev = evaluate(tk, created_at)
    decisions.add(_item(tk, ev))
    return reply_md(tk, ev)


def issue_url_ticket(code: str = "", entry: str = "", stop: str = "", target: str = "") -> str:
    body = f"매수가 {entry}\n손절가 {stop}\n목표가 {target}\n근거: \n보유 5일\n"
    return f"https://github.com/{REPO}/issues/new?title={quote('ticket ' + code)}&body={quote(body)}"
