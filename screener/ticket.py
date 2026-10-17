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
  · 당일 서킷브레이커·사이드카 발동(reports/events.json) / CPI·FOMC 당일(reports/calendar.json) → 신규 진입 거부
  · 매도·판정·포상 후 30분 쿨다운(결재 #14 ③): 최근 매도(`exit` 이슈 '매도')·주문표 판정·env COOLDOWN_LAST_AT 시각 +30분 이내 제출 → 거부
    (근거: 10/16 보상 직후 레버리지 충동 — 하우스머니·면허 효과, kb:behavior#3·#8·#22)
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

from .config import REPORT_DIR
from .duel import ET, KST, NAMES, REPO, US_NAMES, lev_drag_note, lev_factor

log = logging.getLogger(__name__)

SAT_BOOK_DEFAULT = 3_000_000       # 모의 위성 북 (실제 크기는 env 로만, 기록에 남기지 않음)
RISK_PCT_DEFAULT = 0.25            # 1단계: 1회 리스크 = 위성 북의 0.25%
PUBLIC_NOTIONAL_CAP = 1_000_000    # 이 금액 이하만 원화로 기록
MIN_RR = 2.0
HARD_STOP = 0.08
LEV_BAN_UNTIL = "2027-04-15"
LEV_CODES = {"122630", "252670", "114800", "233740", "251340", "253150", "253160", "123320", "123310", "130730", "152500"}
LEV_RE_KR = re.compile(r"(레버리지|인버스|2X|3X)", re.I)
LEV_RE_US = re.compile(r"^(SOXL|SOXS|TQQQ|SQQQ|QLD|QID|SSO|SDS|UPRO|SPXU|SPXL|SPXS|UDOW|SDOW|TNA|TZA|TECL|TECS|LABU|LABD|FNGU|FNGD|"
                       r"TSLL|TSLS|TSLQ|TSLT|NVDL|NVDD|NVDU|NVDS|NVDX|NVD|AAPU|AAPD|AMZU|AMZD|MSFU|MSFD|GGLL|GGLS|METU|METD|CONL|CONI|"
                       r"MSTU|MSTZ|MSTX|SMCX|SMCL|AMDL|AMDS|PLTU|PLTD|COIG|COIN?L|BITU|BITI|ETHU|UVXY|SVXY|UVIX|SVIX|YINN|YANG|KORU|"
                       r"BOIL|KOLD|UCO|SCO|NUGT|DUST|JNUG|JDST|TMF|TMV|TBT|ERX|ERY|DRN|DRV|FAS|FAZ|CURE|WEBL|WEBS|BRKU|BRKD|NFLU|NFLD|AVL|AVS|HOOU|HOOD?X|BABX|ASMU|MUU|RGTU|QBTU|ARMU|CRWL|SHPU)$")
US_LEV_RE_NAME = re.compile(r"(2x|3x|Bull|Bear|Ultra|Leveraged|Inverse|Daily)", re.I)
EVT_HALT = re.compile(r"서킷|사이드카|circuit|sidecar", re.I)
EVT_HALT_NEAR = re.compile(r"경보|근처|해제", re.I)
CAL_MACRO = re.compile(r"\bCPI\b|FOMC|소비자물가", re.I)
COOLDOWN_MIN = 30                  # 매도·판정·포상 후 신규 주문표 금지 (결재 #14 ③)
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
                 "entry": None, "stop": None, "target": None, "amount": None, "pct": None}
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
        elif k in ("근거", "이유", "why"):
            out["why"] = rest.strip()
        elif k in ("보유", "보유기간", "기간"):
            n = _num(rest)
            out["horizon_days"] = int(n) if n else None
        elif k in ("금액",):
            out["amount"] = _num(rest)
        elif k in ("비중",):
            out["pct"] = _num(rest)
    miss = [n for n, k in (("매수가", "entry"), ("손절가", "stop"), ("목표가", "target"), ("근거", "why"), ("보유 n일", "horizon_days")) if not out.get(k)]
    if miss:
        raise ValueError("주문표에 빠진 항목: " + " · ".join(miss) + "\n```\n매수가 <가격>\n손절가 <가격>\n목표가 <가격>\n근거: <한 줄>\n보유 <n>일\n금액 <원>  (선택, 또는 비중 <pct>%)\n```")
    return out


def _detail(code: str, mk: str) -> dict:
    return _j(REPORT_DIR / "detail" / mk / f"{code}.json") or {}


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


def lbl_at(t: datetime) -> str:
    return t.astimezone(KST).strftime("%H:%M")


def evaluate(tk: dict, created_at: str, now: datetime | None = None) -> dict:
    """규칙 검사 → {verdict, reasons, rr, stop_eff, risk_ps, qty_max, half, ...}. 네트워크 없음."""
    code, mk = tk["code"], tk["market"]
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
    if is_leveraged(code, name, mk) and d <= LEV_BAN_UNTIL:
        reject.append(f"레버리지·인버스 금지 (~{LEV_BAN_UNTIL})")
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
    verdict = "⛔ 거부" if reject else "⚠️ 절반 사이징" if half else "✅ 통과"
    out = {"name": name, "date": d, "close": close, "rr": rr, "rr_eff": rr_eff, "stop_eff": stop_eff, "risk_ps": round(risk_ps, 4),
           "qty_max": qty, "half": bool(half), "verdict": verdict, "reasons": reject + half + notes,
           "submitted": tk_kst.strftime("%Y-%m-%d %H:%M"), "rsi14": rsi, "ret1": ret1}
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
    for k in ("notional", "notional_pct"):
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
        ("기록만 남김 — 이 주문표로는 주문하지 않습니다." if ev["verdict"].startswith("⛔") else "성적표에 기록됨 — 이제 주문 가능. 청산은 `exit <코드>` 이슈 또는 보유기간 만료로 채점.")


def apply_ticket_issue(title: str, body: str, created_at: str) -> str:
    """이슈 `ticket <코드>` → 규칙 검사 → decisions.json kind 'ticket' 기록. 반환: 이슈 답글(마크다운)."""
    from . import decisions
    try:
        tk = parse_ticket(title, body)
    except ValueError as e:
        return f"주문표를 기록하지 못했습니다 — {e}"
    ev = evaluate(tk, created_at)
    decisions.add(_item(tk, ev))
    return reply_md(tk, ev)


def issue_url_ticket(code: str = "", entry: str = "", stop: str = "", target: str = "") -> str:
    body = f"매수가 {entry}\n손절가 {stop}\n목표가 {target}\n근거: \n보유 5일\n"
    return f"https://github.com/{REPO}/issues/new?title={quote('ticket ' + code)}&body={quote(body)}"
