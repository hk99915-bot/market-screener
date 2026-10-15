"""진입 타점 대결 — 매 거래일 14:55 무렵, PB 가 '지금 들어갈 자리인가'를 규칙으로 판정해 기록하고
겸이의 판단을 받아(깃허브 이슈 'pick') 다음날 실제 가격으로 채점한다.

- PB 판정 규칙(검증 스터디 기반, 단순·고정):
  · 코스피 −3% 이하 & 장중 범위에서 저점 대비 35% 이상 반등한 자리 → KODEX 200 (−5% 이하 & 외국인 매도 1조 이내면 레버리지)
  · 코스피 −3% 이하 & 저점 부근(범위 하단 20%) → 현금 ('떨어지는 칼날')
  · 그 외 → 현금 ('검증된 타점 없음')
- 기본 진입 = 당일 종가, 청산 = 다음날 시가, 금액 100만원(모의)
- 겸이 제출: 저장소에 제목 'pick YYYY-MM-DD' 이슈 → 본문 '종목코드 [금액] [시가|종가|5일]' 또는 '현금'
  (15:30 KST 이전 제출분만 인정, 저장소 주인만)
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo

from .config import REPORT_DIR

log = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")
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
    return {"pick": pick, "why": why, "lines": lines}


def issue_url_exit(code: str, body: str) -> str:
    return f"https://github.com/{REPO}/issues/new?title={quote('exit ' + code)}&body={quote(body)}"


def issue_url(date: str, body: str = "") -> str:
    return f"https://github.com/{REPO}/issues/new?title={quote('pick ' + date)}&body={quote(body)}"


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
           "  " + c["why"], "<i>PB(누나) 판단은 따로 옴</i>", "",
           "<b>겸이 판단은?</b> 15:30 전까지 제출",
           f"<a href=\"{issue_url(d, '069500 1000000 시가')}\">KODEX 200</a> · <a href=\"{issue_url(d, '122630 1000000 시가')}\">레버리지</a> · "
           f"<a href=\"{issue_url(d, '114800 1000000 시가')}\">인버스</a> · <a href=\"{issue_url(d, '현금')}\">현금</a> · <a href=\"{issue_url(d, '종목코드 금액 시가')}\">직접 입력</a>"]
    if send:
        from .report import send_telegram
        send_telegram("\n".join(msg))
    log.info("타점 판정 기록: %s", c["why"])
    return item


def apply_issue(title: str, body: str, created_at: str) -> str:
    """이슈 'pick YYYY-MM-DD' → 그날 타점 대결의 '나' 칸 채움. 반환: 이슈에 남길 답글."""
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
    if first.startswith("현금") or first.lower() == "cash":
        pick = {"cash": True}
    else:
        toks = first.replace(",", "").split()
        if not toks or not re.fullmatch(r"[0-9A-Za-z]{6}|[A-Za-z.]{1,6}", toks[0]):
            return "본문 첫 줄을 '종목코드 [금액] [시가|종가|5일]' 또는 '현금'으로 적어줘."
        amt = next((float(x) for x in toks[1:] if re.fullmatch(r"\d+(\.\d+)?", x)), NOTIONAL)
        ex = "next_close" if "종가" in first else "d5_close" if "5일" in first else "next_open"
        pick = {"ticker": toks[0], "name": NAMES.get(toks[0], toks[0]), "notional": amt, "entry": "close", "exit": ex}
    it["picks"]["나"] = pick | {"submitted": t.strftime("%H:%M")}
    decisions.OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return f"기록 완료 ✅ {d} 나: " + ("현금" if pick.get("cash") else f"{pick['name']} {pick['notional']:,.0f}원 · 종가 진입 → " + {"next_open": "다음날 시가", "next_close": "다음날 종가", "d5_close": "5일 뒤 종가"}[pick["exit"]] + " 청산") + f" (제출 {t:%H:%M})"


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



def record_pb(payload: dict, send: bool = True) -> str:
    """PB(누나) 재량 판단 기록 — 예약 세션이 데이터를 읽고 판단해 workflow_dispatch(pb_call)로 넘김.
    payload: {"pick": {"ticker","notional","exit"} | {"cash": true}, "why": str, "lines": [..], "conviction": "낮음|보통|높음"}"""
    from . import decisions
    now = datetime.now(KST)
    d = str(now.date())
    iid = f"{d}-entry"
    pk = payload.get("pick") or {"cash": True}
    if not pk.get("cash"):
        t = str(pk["ticker"])
        pk = {"ticker": t, "name": pk.get("name") or NAMES.get(t, t), "notional": float(pk.get("notional") or NOTIONAL),
              "entry": "close", "exit": pk.get("exit") or "next_open"}
    pk["by"] = "PB 재량"
    pk["at"] = now.strftime("%H:%M")
    data = decisions.load()
    it = next((x for x in data.get("items", []) if x["id"] == iid), None)
    if not it:
        it = {"id": iid, "date": d, "kind": "entry", "title": "진입 타점 대결", "note": "", "picks": {"나": {"pending": True}}}
        data["items"].append(it)
    it["picks"]["PB"] = pk
    it["pb_view"] = {"why": payload.get("why", ""), "lines": payload.get("lines") or [], "conviction": payload.get("conviction", ""), "at": pk["at"]}
    # 보유 종목 매도 타점 (누나 재량) — 금액은 모의 100만 고정 (실제 보유 수량·금액은 공개 저장소에 남기지 않음)
    ex_msgs = []
    for e in (payload.get("exits") or [])[:12]:
        code = str(e.get("ticker", "")).strip()
        if not code:
            continue
        name = e.get("name") or code
        act = "매도" if str(e.get("act", "")).startswith("매도") or "축소" in str(e.get("act", "")) else "보유"
        eid = f"{d}-exit-{code}"
        hold = _hold_pick(code, name, NOTIONAL)
        rule = None
        try:
            rc = exit_call(code, "KR" if code.isdigit() else "US")
            rule = {"cash": True, "label": "매도"} if rc["act"] == "매도" else hold
        except Exception:  # noqa: BLE001
            pass
        ei = next((x for x in data["items"] if x["id"] == eid), None)
        if not ei:
            ei = {"id": eid, "date": d, "kind": "exit", "title": f"매도 타점 대결 · {name}", "note": "채점: 5거래일 뒤 종가 (매도=현금 0%, 보유=종목 수익률)",
                  "picks": {"나": {"pending": True}}}
            data["items"].append(ei)
        ei["picks"]["PB"] = ({"cash": True, "label": "매도"} if act == "매도" else hold) | {"by": "PB 재량", "at": pk["at"]}
        if rule:
            ei["picks"]["규칙"] = rule
        ei["pb_view"] = {"why": e.get("why", ""), "lines": [], "conviction": e.get("conviction", ""), "at": pk["at"]}
        ex_msgs.append(f"• {name}: <b>{act}</b> — {e.get('why', '')} "
                       f"[<a href=\"{issue_url_exit(code, '보유')}\">나는 보유</a> · <a href=\"{issue_url_exit(code, '매도')}\">나는 매도</a>]")
    decisions.OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    ex_lbl = {"next_open": "다음날 시가", "next_close": "다음날 종가", "d5_close": "5일 뒤 종가"}
    msg = ["💬 <b>PB 판단</b> · " + now.strftime("%m/%d %H:%M") + (f" · 확신 {payload.get('conviction')}" if payload.get("conviction") else ""),
           "<b>" + ("현금 유지" if pk.get("cash") else f"{pk['name']} {pk['notional']/10000:,.0f}만 · 종가 진입 → {ex_lbl.get(pk['exit'], pk['exit'])} 청산") + "</b>",
           payload.get("why", ""), *[f"• {x}" for x in (payload.get("lines") or [])[:6]], "",
           f"겸이 판단: <a href=\"{issue_url(d, '069500 1000000 시가')}\">KODEX 200</a> · <a href=\"{issue_url(d, '122630 1000000 시가')}\">레버리지</a> · "
           f"<a href=\"{issue_url(d, '114800 1000000 시가')}\">인버스</a> · <a href=\"{issue_url(d, '현금')}\">현금</a> (15:30 전)"]
    if ex_msgs:
        msg += ["", "<b>보유 종목 매도 타점</b> (5거래일 뒤 종가 채점)", *ex_msgs]
    if send:
        from .report import send_telegram
        send_telegram("\n".join(m for m in msg if m is not None))
    return "PB 판단 기록: " + ("현금" if pk.get("cash") else pk["name"])
