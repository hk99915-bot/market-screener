"""타점 대결 '나' 픽 분류 게이트 — 겸이 10/23 18시대 결재 ①② (행동 데스크 처방 · 모의 타점 대결 한정, 실계좌 규칙 아님).

① 계획 칸 강제: '나' 종목 픽에 손절·1차 목표·R:R(≥ PICK_MIN_RR)·근거 중 하나라도 비거나 R:R 미달이면 '나🔥'(감) 칸으로 분류.
② 당일 쿨다운: 그날(KST) (a) ops/cooldown.json 의 실계좌 매도·포상 시각 뒤이거나 (b) 그날 확정된 '나' 판 손실
   (국장 픽은 직전 거래일 국장 판 포함) 뒤면, 남은 '나' 픽은 현금·비레버리지·비반도체만 '나' — 어기면 '나🔥'.
- 현금 제출은 둘 다 예외. 적용 = 제출 시각 PICK_GATE_FROM(KST) 이후분만(소급 없음). 이유는 pick['reclass'] 한 줄로 남긴다.

본문 계획 칸 형식(이슈 본문·텔레그램 텍스트 공통, 줄바꿈 또는 한 줄):
  069500 1000000 시가 손절 -2% 목표 +3% 근거: 급락 뒤 반등 확인
  손절·목표는 가격(9800) 또는 기준가 대비 %(−2%·+3%). 가격이면 기준가 = **체결 기준가**(국장 종가·미장 시가 쪽 확정 시세 — ref_price),
  본문 '매수가 N'은 참고 표시만(겸이 10/29 결재 ①, kb:behavior#34) — 체결 기준가와 ±0.5% 넘게 다르면 plan['warn'] 경고.
  R:R = (목표 − 기준가) ÷ (기준가 − 손절). 기준가를 못 구하면 'RR 2' 처럼 적은 값을 쓴다(없으면 계산 불가 → '나🔥').
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .defs import PICK_GATE_FROM, PICK_MIN_RR

KST = ZoneInfo("Asia/Seoul")
ET = ZoneInfo("America/New_York")

_KW = {"stop": r"손절가?|stop", "target": r"1차\s*목표가?|목표가?|target|tp", "why": r"근거|why",
       "entry": r"매수가|진입가|entry", "rr": r"r\s*:\s*r|rr|손익비"}
_KW_RE = re.compile("|".join(f"(?P<{k}>(?<![0-9A-Za-z가-힣])(?:{v}))" for k, v in _KW.items()), re.I)
_NUM = re.compile(r"([+\-−]?\d+(?:\.\d+)?)\s*(%)?")
_NUM_NEXT = re.compile(r"\s*[:：=]?\s*(?:1\s*:\s*)?[+\-−]?\d")


def split_head(line: str) -> tuple[str, str]:
    """본문 첫 줄 → (픽 부분 '종목 금액 청산', 계획 부분). 계획 키워드(손절·목표·근거·매수가·RR)가 처음 나오는 곳에서 자른다."""
    m = _KW_RE.search(line or "")
    return ((line or "")[:m.start()].strip(), (line or "")[m.start():].strip()) if m else ((line or "").strip(), "")


def _val(s: str) -> tuple[float | None, bool]:
    m = _NUM.search((s or "").replace(",", ""))
    if not m:
        return None, False
    return float(m.group(1).replace("−", "-")), bool(m.group(2))


def parse_plan(text: str) -> dict:
    """계획 텍스트 → {stop|stop_pct, target|target_pct, entry, rr_given, why}. 없는 칸은 키가 없다."""
    out: dict = {}
    for line in (text or "").splitlines():
        ms = list(_KW_RE.finditer(line))
        skip = -1   # 근거 문장 안에 든 키워드는 건너뜀
        for i, m in enumerate(ms):
            k = m.lastgroup
            if m.start() < skip:
                continue
            if k == "why":   # 근거는 줄 끝까지 — 단, 뒤에 '손절 -2%'처럼 숫자가 바로 붙은 계획 칸이 오면 거기까지 (근거 문장 속 '목표' 단어엔 안 잘림)
                nxt = next((n for n in ms[i + 1:] if n.lastgroup != "why" and _NUM_NEXT.match(line, n.end())), None)
                v = line[m.end():nxt.start() if nxt else len(line)].strip(" :：=-").strip()
                if v and "why" not in out:
                    out["why"] = v
                skip = nxt.start() if nxt else len(line) + 1
                continue
            v = line[m.end():ms[i + 1].start() if i + 1 < len(ms) else len(line)].strip(" :：=")
            if k == "rr":
                v = re.sub(r"^1\s*:\s*", "", v.strip())
            x, pct = _val(v)
            if x is None:
                continue
            if k == "stop":
                out.pop("stop", None), out.pop("stop_pct", None)
                out["stop_pct" if pct else "stop"] = -abs(x) / 100 if pct else x
            elif k == "target":
                out.pop("target", None), out.pop("target_pct", None)
                out["target_pct" if pct else "target"] = abs(x) / 100 if pct else x
            elif k == "entry" and not pct:
                out["entry"] = x
            elif k == "rr" and not pct and x > 0:
                out["rr_given"] = x
    return out


ENTRY_WARN = 0.005   # 본문 매수가가 체결 기준가와 이만큼(±0.5%) 넘게 다르면 경고 (결재 10/29 ①)


def entry_warn(plan: dict, ref: float | None) -> str | None:
    """본문 '매수가'(참고)와 체결 기준가 차이가 ±0.5% 를 넘으면 경고 문구, 아니면 None."""
    e = plan.get("entry")
    if not e or not ref:
        return None
    d = e / ref - 1
    if abs(d) <= ENTRY_WARN:
        return None
    return f"매수가 {e:,.2f}".rstrip("0").rstrip(".") + f" 는 체결 기준가 {ref:,.2f}".rstrip("0").rstrip(".") + f" 와 {_pct(d)} 다름(±0.5% 초과) — R:R 은 체결 기준가로 계산"


def plan_rr(plan: dict, ref: float | None, entry_fallback: bool = False) -> tuple[float | None, str]:
    """(R:R, 계산 메모). 손절·목표가 % 면 기준가 없이, 가격이면 **체결 기준가 ref** 로 계산(본문 매수가는 쓰지 않음 — 결재 10/29 ①).
    entry_fallback=True 는 옛 기록(ref 저장 전) 소급 점검용만: ref 가 없을 때 매수가로 계산. 못 하면 적은 RR, 그것도 없으면 None."""
    ref = ref or (plan.get("entry") if entry_fallback else None)
    risk = abs(plan["stop_pct"]) if "stop_pct" in plan else ((ref - plan["stop"]) / ref if "stop" in plan and ref else None)
    rew = plan["target_pct"] if "target_pct" in plan else ((plan["target"] - ref) / ref if "target" in plan and ref else None)
    if risk is not None and rew is not None:
        if risk <= 0:
            return None, "손절이 기준가 이상"
        if rew <= 0:
            return None, "목표가 기준가 이하"
        return round(rew / risk, 4), ("기준가 " + f"{ref:,.2f}".rstrip("0").rstrip(".") if ("stop" in plan or "target" in plan) else "%")
    if plan.get("rr_given"):
        return plan["rr_given"], "제출값(기준가 없음)"
    return None, "기준가 없음" if ("stop" in plan or "target" in plan) else ""


def plan_gaps(plan: dict, rr: float | None, note: str = "") -> list[str]:
    """① 위반 사유 목록(빈 목록 = 통과). R:R 은 PICK_MIN_RR 이상이면 통과(1.5 = 통과)."""
    miss = [n for n, ok in (("손절", "stop" in plan or "stop_pct" in plan), ("목표", "target" in plan or "target_pct" in plan),
                            ("근거", (plan.get("why") or "").strip() not in ("", "감")))
            if not ok]
    out = [f"계획 칸 비어 있음({'·'.join(miss)})"] if miss else []
    if rr is None:
        if not miss:
            out.append(f"R:R 계산 불가({note or '손절·목표 확인'})")
    elif rr < PICK_MIN_RR:
        out.append(f"R:R 1:{rr:.2f} < 1:{PICK_MIN_RR:g}")
    return out


def _settle_kst(it: dict, res: dict) -> datetime | None:
    """'나' 결과가 확정된 시각(KST) — detail 의 마지막 날짜 + 시가(09:00)/종가(15:30, 미장은 16:00 ET)."""
    ds = re.findall(r"(\d{4}-\d{2}-\d{2}) (시가|종가)", str(res.get("detail") or ""))
    if not ds:
        return None
    d, w = ds[-1]
    y, m, dd = map(int, d.split("-"))
    if it.get("market") == "US":
        hh, mm = (9, 30) if w == "시가" else (16, 0)
        return datetime(y, m, dd, hh, mm, tzinfo=ET).astimezone(KST)
    return datetime(y, m, dd, 9, 0, tzinfo=KST) if w == "시가" else datetime(y, m, dd, 15, 30, tzinfo=KST)


def _pct(x: float) -> str:
    return f"{x * 100:+.1f}%".replace("-", "−")


def day_cooldown(t: datetime, item: dict, items: list[dict], events: list[tuple[datetime, str]] | None = None,
                 score_fn=None) -> str | None:
    """② 그날(KST) 쿨다운 사유 한 줄(가장 이른 계기) 또는 None. t = 제출 시각(KST).
    (a) events = ops/cooldown.json (시각, 라벨) — 같은 KST 날짜·t 이전.
    (b) '나' 판 손실: 그날 t 이전에 확정된 '나' 결과 ret<0 (미장·국장 모두), 국장 픽이면 직전 국장 판(채점 전이면 score_fn 으로 확정 확인)."""
    t = t.astimezone(KST)
    day = t.date()
    hits: list[tuple[datetime, str]] = []
    if events is None:
        from .ticket import cooldown_file_events
        events = cooldown_file_events()
    for at, what in events:
        at = at.astimezone(KST)
        if at.date() == day and at <= t:
            hits.append((at, f"{at:%m/%d} {what} {at:%H:%M} 뒤"))
    mk = item.get("market") or "KR"
    ent = [x for x in items if x.get("kind") == "entry" and x.get("id") != item.get("id")]
    prev = None
    if mk == "KR":
        cand = [x for x in ent if (x.get("market") or "KR") == "KR" and x.get("date", "") < item.get("date", "")
                and not ((x.get("picks") or {}).get("나") or {"pending": True}).get("pending")]
        prev = max(cand, key=lambda x: x["date"]) if cand else None
    for x in ent:
        me = (x.get("picks") or {}).get("나") or {}
        if me.get("pending") or me.get("cash"):
            continue
        r = ((x.get("result") or {}) if not (x.get("result") or {}).get("void") else {}).get("나")
        if r is None and x is prev and score_fn:
            try:
                r = score_fn(me, x["date"])
            except Exception:  # noqa: BLE001 — 확정 확인 실패면 계기로 안 씀(대신 채점 뒤 다음 제출부터)
                r = None
        if not r or r.get("ret") is None or r["ret"] >= 0:
            continue
        st = _settle_kst(x, r)
        if not st or st > t:
            continue
        if st.date() == day or x is prev:
            lbl = ("미장" if x.get("market") == "US" else "국장") + f" {x['date'][5:].replace('-', '/')} '나' 손실 {_pct(r['ret'])}"
            hits.append((st, f"{lbl} 확정({st:%m/%d %H:%M}) 뒤"))
    if not hits:
        return None
    return "쿨다운: " + min(hits)[1]


def cooldown_violation(pick: dict, market: str, semi_fn=None) -> str | None:
    """쿨다운 중 '나'로 인정 안 되는 이유(레버리지·인버스 / 반도체) 또는 None(현금·비레버리지·비반도체)."""
    if not pick or pick.get("cash"):
        return None
    from .duel import lev_factor
    lev = lev_factor(pick.get("ticker", ""), pick.get("name", ""), market)
    if lev:
        return f"레버리지·인버스 {lev:+g}배"
    code = str(pick.get("ticker", ""))
    semi = "반도체" in str(pick.get("name") or "")
    if not semi:
        try:
            from . import pb
            semi = (semi_fn or pb.semi_code)(market, code) or code.upper() in pb.SEMI_ETFS or code.upper() in pb.US_SEMIS
        except Exception:  # noqa: BLE001 — 판정 실패는 비반도체로 두되 사유에 남기지 않음(detail 없는 종목)
            semi = False
    return "반도체" if semi else None


def gate_active(t: datetime) -> bool:
    return t.astimezone(KST).strftime("%Y-%m-%d %H:%M") >= PICK_GATE_FROM


def classify(pick: dict, plan_text: str, t: datetime, item: dict, items: list[dict], *, ref_fn=None, events=None,
             score_fn=None, semi_fn=None) -> tuple[str, dict, list[str]]:
    """'나' 제출 → (slot '나'|'나🔥', 계획이 붙은 pick, 재분류 사유 목록). 현금·적용일 이전은 그대로 '나'."""
    if pick.get("cash") or not gate_active(t):
        return "나", pick, []
    market = item.get("market") or "KR"
    plan = parse_plan(plan_text)
    ref = None
    if ("stop" in plan or "target" in plan or "entry" in plan) and ref_fn:
        try:
            ref = ref_fn(pick["ticker"], item["date"])
        except Exception:  # noqa: BLE001
            ref = None
    rr, note = plan_rr(plan, ref)
    reasons = plan_gaps(plan, rr, note)
    cd = day_cooldown(t, item, items, events, score_fn)
    if cd:
        v = cooldown_violation(pick, market, semi_fn)
        if v:
            reasons.append(f"{cd} — 현금·비레버리지·비반도체만 '나'({v})")
    keep = {k: plan[k] for k in ("stop", "stop_pct", "target", "target_pct", "entry", "why") if k in plan}
    if rr is not None:
        keep["rr"] = round(rr, 2)
    if ref:
        keep["ref"] = ref
    warn = entry_warn(plan, ref)
    if warn:
        keep["warn"] = warn
    out = pick | ({"plan": keep} if keep else {})
    if cd and not reasons:
        out["cooldown"] = cd + " — 현금·비레버리지·비반도체라 '나' 인정"
    return ("나🔥" if reasons else "나"), out, reasons


def ref_price(ticker: str, date: str) -> float | None:
    """가격형 손절·목표의 기준가 = 최근 확정 종가(결정일 포함 이전). 네트워크(decisions._bars) — 실패면 None."""
    from . import decisions
    d0 = str((datetime.fromisoformat(date) - timedelta(days=12)).date())
    bars = [b for b in decisions._bars(ticker, d0) if b.get("c") and b["d"] <= date]
    return float(bars[-1]["c"]) if bars else None


def plan_text_line(pick: dict) -> str | None:
    """확인 메시지·화면용 계획 한 줄."""
    p = pick.get("plan") or {}
    if not p:
        return None
    f = lambda k, kp: (f"{p[k]:,.2f}".rstrip("0").rstrip(".") if k in p else _pct(p[kp]) if kp in p else "—")  # noqa: E731
    return f"계획: 손절 {f('stop', 'stop_pct')} · 목표 {f('target', 'target_pct')} · R:R " + (f"1:{p['rr']:.2f}" if p.get("rr") is not None else "—") + \
        (f" · 근거 {p['why']}" if p.get("why") else "") + (f" · ⚠ {p['warn']}" if p.get("warn") else "")


def audit(items: list[dict], *, events=None, semi_fn=None) -> list[dict]:
    """소급 점검(겸이 10/24 결재 appr-pick-gate-start: '10/23 19:00 제출분부터' — 삭제 없이 표시만).
    PICK_GATE_FROM 이후 제출된 '나'·'나🔥' 픽마다 한 행: {id, slot, submitted, status, reasons}.
    status = '통과'(제출 때 게이트 통과 = plan 있음·reclass 없음) / '재분류'(게이트가 '나🔥'로 옮김) /
             '위반'(게이트를 안 거친 '나' — 버튼·수동 기록 등. 지금 기준으로 다시 판정한 사유) / '현금'.
    제출 시각 = 판 날짜 + submitted(KST HH:MM). 미장 판은 KST 저녁 제출이 대부분이라 같은 날짜로 본다(새벽 제출은 하루 늦게 잡힐 수 있음)."""
    out = []
    for it in items:
        if it.get("kind") != "entry":
            continue
        for slot in ("나", "나🔥"):
            p = (it.get("picks") or {}).get(slot) or {}
            sub = p.get("submitted")
            if p.get("pending") or not sub:
                continue
            try:
                t = datetime.fromisoformat(f"{it['date']} {sub}").replace(tzinfo=KST)
            except ValueError:
                continue
            if not gate_active(t):
                continue
            row = {"id": it["id"], "slot": slot, "submitted": f"{it['date']} {sub}", "reasons": []}
            if p.get("cash"):
                row["status"] = "현금"
            elif p.get("reclass"):
                row["status"], row["reasons"] = "재분류", [p["reclass"]]
            elif slot == "나🔥":
                row["status"] = "직접 '나🔥'"   # 처음부터 감 칸 — 게이트 대상 아님
            elif p.get("plan") and p["plan"].get("rr") is not None:
                row["status"] = "통과"
            else:
                plan = {k: v for k, v in (p.get("plan") or {}).items()}
                rr, note = plan_rr(plan, plan.get("ref"), entry_fallback=True)
                rs = plan_gaps(plan, rr, note)
                cd = day_cooldown(t, it, items, events or [], None)
                v = cooldown_violation(p, it.get("market") or "KR", semi_fn) if cd else None
                if v:
                    rs.append(f"{cd} — ({v})")
                row["status"], row["reasons"] = ("위반" if rs else "통과"), rs
            out.append(row)
    return out
