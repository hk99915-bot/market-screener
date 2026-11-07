"""그림자(모의) 파생 북 — 다전략 · 다리 단위 정산가 마킹 → reports/views/shadow_derivs_book.json (표시 전용, 돈 0)

실계좌 아님. 목적 = 옵션·선물 전략의 보험료 녹음(세타)·급락일 손익을 KRX 실제 일 정산가로 기록해 감각 익히기 (2026-11-07 오너 승인).
사전등록: #1 미니 풋 = reports/studies/shadow_mini_put_prereg.md · 나머지 전략 = HF 데스크 reports/studies/shadow_book_prereg.md
(그 파일 안 ```json 블록에 {"shadow_strategies": [...]} 가 있으면 읽어서 등록. 같은 id 면 HF 정의 우선). 방향 신호 아님.

가격 소스 (전부 KRX 정보데이터시스템 MDCSTAT12501 '전 종목 시세', pykrx 로그인 세션 = screener.derivs._io 재사용):
  | 상품          | prodId       | 확인 상태 |
  | 코스피200 옵션 | KRDRVOPK2I   | 사용 중(derivs.py) |
  | 코스피200 선물 | KRDRVFUK2I   | 사용 중 |
  | 미니 옵션      | KRDRVOPMKI   | [확인 필요: 첫 실행 로그] — 마킹은 어차피 정규 같은 종목 정산가(src=k2i_ref, 상품명세상 기준가격 동일), 미니 값은 대조 칸 |
  | 미니 선물      | KRDRVFUMKI   | 탐침 목록에만 있음(probe_deriv_sources.py) — 같은 처리 |
  마킹 가격 = SETL_PRC(정산가)만. TDD_CLSPRC(종가 = 마지막 체결가, 증권사 앱 '현재가')는 저유동 행사가에서 낡은 값이라 마킹 금지(참고 칸만).
  미니 옵션 = 정규 같은 종목 정산가(k2i_ref) → 없으면 미니 정산가 → 없으면 전일가 유지. 선물 = 자체 정산가 → 정규(k2i_proxy). 거래량 0 인 날은 thin=true (정산가 = 거래소 이론가일 수 있음).
  호가 중간값은 KRX 일 보드에 없음 → 실시간 API 연결 전엔 쓰지 않는다.
  만기일(최종거래일): 옵션 = 내재가치 max(±(S−K),0), 선물 = S (최종결제가격 = 그날 코스피200 종가) [가정: 원문 대조 전].
손익(원) = Σ 방향(+1 매수/−1 매도) × 수량 × 승수 × (가격_t − 가격_{t−1}). 옵션 매수 프리미엄은 진입 가격으로 들어가 누적에 반영된다.
그릭스 = 정산가로 역산한 IV 의 블랙숄즈(유럽형, r=3%, 배당 0 — derivs._bs 와 같은 근사).
"""
from __future__ import annotations

import csv
import json
import logging
import math
import re
from datetime import date, datetime, timedelta
from pathlib import Path

from .config import REPORT_DIR

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]
OUT = REPORT_DIR / "views" / "shadow_derivs_book.json"
HF_PREREG = ROOT / "reports" / "studies" / "shadow_book_prereg.md"
DAILY = ROOT / "data" / "deriv" / "daily.csv"
PROD = {("mini", "O"): "KRDRVOPMKI", ("k2i", "O"): "KRDRVOPK2I", ("mini", "F"): "KRDRVFUMKI", ("k2i", "F"): "KRDRVFUK2I"}
MULT = {"mini": 50_000, "k2i": 250_000}
MULT_SRC = {"mini": "5만원/pt — KRX 미니코스피200옵션 상품명세 원문 확인(오너 붙여넣기 2026-11-07) · 12801 SETLMULT 로 재대조",
            "k2i": "25만원/pt — KRX 12801 SETLMULT 250,000 (탐침 2026-10-15)",
            "mini_fut": "5만원/pt — KRX 상품명세 원문 확인(오너 붙여넣기 2026-11-07)"}
# 미니 선물 명세 — 원문 확인 (출처: KRX 상품명세, 오너 붙여넣기 2026-11-07). 미니 '옵션' 승수·위클리는 여전히 미확인.
MINI_OPT_SPEC = {"src": "KRX 상품명세(오너 붙여넣기 2026-11-07)", "mult": 50_000, "months": "매월 · 연속 6개월(분기월 2·비분기월 4) · 위클리 없음",
                 "strikes": "최근 3개 근월물 ATM±120pt 2.5pt 간격 · 4~6근월물 5pt 간격", "tick": "3pt 미만 0.01 · 3~10 0.02 · 10 이상 0.05",
                 "style": "유럽형 · 최종거래일만 행사 · 현금결제", "last_trade": "결제월 두 번째 목요일",
                 "base_px": "기준가격·증거금 기준가격 = 정규 코스피200옵션 같은 콜/풋·행사가·결제월 기준가격", "limit": "±8/15/20%(옵션이론가 기준)",
                 "position_limit_indiv": "미결제 10,000델타"}
MINI_FUT_SPEC = {"src": "KRX 상품명세(오너 붙여넣기 2026-11-07)", "mult": 50_000, "months": "매월 · 연속 6개월 상장(분기월 2·비분기월 4)",
                 "tick": "0.02pt = 1,000원", "hours": "08:45~15:45(최종거래일 ~15:20) · 야간 18:00~06:00",
                 "last_trade": "결제월 두 번째 목요일", "settle_method": "현금결제", "limit": "±8/15/20% 단계",
                 "daily_settle": "분기월 = 코스피200선물 정산가 · 비분기월 = 자체 산출 가격", "base_px": "비분기월 = 직전일 정산가",
                 "position_limit_indiv": "미결제 10,000계약"}
RX_OPT = re.compile(r"(미니)?\s*코스피200\s+([CP])\s+(\d{6})\s+([\d,]+(?:\.\d+)?)")
RX_FUT = re.compile(r"(미니)?\s*코스피200\s+F\s+(\d{6})")
MAX_DAYS = 15   # 한 번 실행에 따라잡는 최대 거래일 (KRX 과다 요청 방지)
WIRING = ("[제안-미적용] .github/workflows/deriv_hist.yml (평일 16:40, 기존 슬롯 — 새 예약 아님) '감마 레짐' 단계 뒤에 "
          "`- name: 그림자 파생 북 (표시 전용)` / `run: python -m screener.shadow_book 2>&1 | tail -5 || echo \"::warning::shadow_book 실패\"` 한 단계 + "
          "'저장' for 목록에 reports/views/shadow_derivs_book.json 추가. 붙이기 전까지는 장부가 갱신되지 않지만, "
          "진입·일별 값은 과거 거래일(trdDd)로 다시 받을 수 있어 11/10 정산가 진입 규칙은 그대로 지켜진다(따라잡기 최대 15거래일/회).")

BUILTIN = [{
    "id": "S1_mini_put_10", "no": 1, "name": "미니 K200 풋 −10% 1계약 매수 (보험료 녹음·급락 손익)", "owner": "파생",
    "prereg": "reports/studies/shadow_mini_put_prereg.md", "start": "2026-11-10", "min_dte": 20, "roll": "expiry", "min_cycles": 3,
    "legs": [{"kind": "P", "side": 1, "product": "mini", "moneyness": -0.10, "qty": 1}],
}]
# 원화 승수: 미니 선물·옵션 모두 5만 (KRX 상품명세 원문, 오너 붙여넣기 2026-11-07). 미니 위클리는 없음(월물만) — 위클리 전략은 정규(25만) 기준.


# ───────────── 순수 함수 (테스트 대상) ─────────────
def _f(x) -> float | None:
    try:
        v = float(str(x).replace(",", ""))
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def parse_board(raw: list[dict], typ: str) -> dict:
    """KRX 12501 행 → {(kind, ym, k): quote}. kind = C/P/F, 선물은 k=None. 야간·스프레드 제외."""
    out: dict = {}
    for r in raw or []:
        nm = r.get("ISU_NM") or ""
        if "야간" in nm or "스프레드" in nm or " SP " in f" {nm} ":
            continue
        if typ == "O":
            m = RX_OPT.search(nm)
            if not m:
                continue
            key = (m.group(2), m.group(3), float(m.group(4).replace(",", "")))
        else:
            m = RX_FUT.search(nm)
            if not m:
                continue
            key = ("F", m.group(2), None)
        if key in out:   # 같은 월물 선물 중복(주간·기타) → 첫 행
            continue
        st, cl = _f(r.get("SETL_PRC")), _f(r.get("TDD_CLSPRC"))
        # 마킹 = 정산가만. 종가(=마지막 체결가)는 저유동 행사가에서 낡아 내재가치보다 낮게도 찍힘(11/7 오너 화면: 미니 11월물 풋 842.5 체결가 < 내재가치)
        # → 참고 칸(close)에만 두고 마킹에 쓰지 않는다. 정산가 없으면 px=None (Day.quote 대체 순서 참조).
        out[key] = {"px": st, "px_basis": "settle" if st else None, "close": cl,
                    "vol": _f(r.get("ACC_TRDVOL")) or 0.0, "oi": _f(r.get("ACC_OPNINT_QTY")) or 0.0,
                    "spot": _f(r.get("SPOT_PRC")), "isu": r.get("ISU_CD")}
    return out


def expiry_of(ym: str, last_trade: dict | None = None) -> date:
    """월물 최종거래일 = 둘째 목요일, 휴장이면 앞당김. KRX 12801 LSTTRD_DD 를 받았으면 그 값 우선."""
    if last_trade and last_trade.get(ym):
        return date.fromisoformat(last_trade[ym])
    from .derivs import _expiry
    d = _expiry(ym)
    try:
        from .tradecal import session_on_or_before
        return session_on_or_before("KR", d)
    except Exception:  # noqa: BLE001
        return d


def pick_month(board: dict, kind: str, d: date, min_dte: int, last_trade: dict | None = None) -> str | None:
    """만기까지 달력일 min_dte 이상 남은 가장 가까운 월물."""
    yms = sorted({k[1] for k in board if k[0] == kind})
    for ym in yms:
        if (expiry_of(ym, last_trade) - d).days >= min_dte:
            return ym
    return None


def pick_strike(board: dict, kind: str, ym: str, target: float) -> float | None:
    """상장 행사가 중 target 에 가장 가까운 것. 동률이면 더 외가(풋=낮은 쪽, 콜=높은 쪽)."""
    ks = [k[2] for k in board if k[0] == kind and k[1] == ym and k[2] is not None and board[k].get("px")]
    if not ks:
        return None
    return min(ks, key=lambda k: (abs(k - target), k if kind == "P" else -k))


def intrinsic(kind: str, S: float, k: float | None) -> float:
    if kind == "F":
        return S
    return max(0.0, (S - k) if kind == "C" else (k - S))


def greeks(kind: str, px: float | None, S: float, k: float | None, T: float) -> dict:
    """정산가 → IV 역산 → 델타·하루 세타(pt, 달력일). 선물은 델타 1."""
    if kind == "F":
        return {"iv": None, "delta": 1.0, "theta_pt": 0.0}
    from .derivs import _bs, _iv, _ncdf, RATE
    if not px or not S or not k or T <= 0:
        return {"iv": None, "delta": None, "theta_pt": None}
    v = _iv(px, S, k, T, kind)
    if not v:
        return {"iv": None, "delta": None, "theta_pt": None}
    d1 = (math.log(S / k) + (RATE + v * v / 2) * T) / (v * math.sqrt(T))
    delta = _ncdf(d1) if kind == "C" else _ncdf(d1) - 1
    th = _bs(S, k, max(T - 1 / 365, 0.0), v, kind) - _bs(S, k, T, v, kind)
    return {"iv": round(v, 4), "delta": round(delta, 4), "theta_pt": round(th, 3)}


def margin_slot(strat: dict) -> dict | None:
    """매도 다리가 있으면 증거금 근사 칸 (값은 미구현 — KRX 위탁증거금률 원문 미확인)."""
    if not any(l.get("side", 1) < 0 for l in strat.get("legs", [])):
        return None
    return {"approx_krw": None, "rule": "[가정 칸] 매도 다리 증거금 근사 — 미구현(위탁증거금률·SPAN식 산출 원문 미확인). 값이 생기기 전엔 비교 금지"}


def hf_strategies(path: Path = HF_PREREG) -> tuple[list[dict], dict]:
    """HF 사전등록 md 의 ```json 블록 {"shadow_strategies": [...]} 를 읽는다. 없으면 []."""
    meta = {"path": str(path.relative_to(ROOT)) if path.is_absolute() and ROOT in path.parents else str(path), "found": path.exists(), "n": 0, "errors": []}
    if not path.exists():
        return [], meta
    out: list[dict] = []
    for blk in re.findall(r"```json\s*(.*?)```", path.read_text(encoding="utf-8"), flags=re.S):
        if "shadow_strategies" not in blk:
            continue
        try:
            arr = json.loads(blk)["shadow_strategies"]
        except Exception as e:  # noqa: BLE001
            meta["errors"].append(f"json 오류: {e}")
            continue
        for s in arr:
            ok = isinstance(s, dict) and s.get("id") and s.get("name") and s.get("legs") and all(
                l.get("kind") in ("C", "P", "F") and l.get("product") in MULT and l.get("side") in (1, -1) for l in s["legs"])
            if ok:
                s.setdefault("start", "2026-11-10"); s.setdefault("min_dte", 20); s.setdefault("roll", "expiry"); s.setdefault("min_cycles", 3)
                s.setdefault("owner", "HF"); s.setdefault("prereg", meta["path"])
                out.append(s)
            else:
                meta["errors"].append(f"형식 오류 전략 건너뜀: {str(s)[:80]}")
    meta["n"] = len(out)
    return out, meta


def registry(hf: list[dict]) -> list[dict]:
    by = {s["id"]: dict(s) for s in BUILTIN}
    for s in hf:   # 같은 id 면 HF 정의 우선 (조정자 지시 11/7)
        by[s["id"]] = dict(s)
    return list(by.values())


def leg_label(l: dict) -> str:
    side = "매수" if l.get("side", 1) > 0 else "매도"
    pr = "미니" if l.get("product") == "mini" else "정규"
    if l.get("k") is not None:
        return f"{pr} {l['kind']} {l.get('ym', '')} {l['k']:g} {side}×{l.get('qty', 1)}"
    if l.get("kind") == "F":
        return f"{pr} 선물 {l.get('ym', '')} {side}×{l.get('qty', 1)}".replace("  ", " ")
    m = l.get("moneyness")
    return f"{pr} {l['kind']} {'' if m is None else f'{m:+.0%}'} {side}×{l.get('qty', 1)}"


class Day:
    """하루치 시세 묶음. boards[(product, typ)] = parse_board 결과."""

    def __init__(self, d: date, S: float | None, boards: dict, last_trade: dict | None = None):
        self.d, self.S, self.boards, self.last_trade = d, S, boards, last_trade or {}

    def quote(self, product: str, kind: str, ym: str, k: float | None) -> tuple[dict | None, str]:
        """마킹 가격. 미니 옵션은 **정규 코스피200옵션 같은 콜/풋·행사가·월물 정산가**가 1순위(src=k2i_ref) — KRX 상품명세상
        미니옵션 기준가격·증거금 기준가격 = 정규 같은 종목 기준가격(오너 붙여넣기 2026-11-07). 미니 자체 정산가·거래량은 대조 칸(mini_px·mini_vol).
        정규에 없으면 미니 자체 정산가(src=mini). 선물은 상품 자체 정산가 → 없으면 정규 같은 월물(k2i_proxy)."""
        typ = "F" if kind == "F" else "O"
        own = (self.boards.get((product, typ)) or {}).get((kind, ym, k))
        ref = (self.boards.get(("k2i", typ)) or {}).get((kind, ym, k)) if product != "k2i" else None
        if product == "mini" and typ == "O":
            if ref and ref.get("px"):
                return dict(ref, mini_px=(own or {}).get("px"), mini_vol=(own or {}).get("vol"), mini_oi=(own or {}).get("oi")), "k2i_ref"
            if own and own.get("px"):
                return dict(own, mini_px=own.get("px"), mini_vol=own.get("vol"), mini_oi=own.get("oi")), "mini"
            return None, "missing"
        if own and own.get("px"):
            return own, product
        if ref and ref.get("px"):
            return ref, "k2i_proxy"
        return None, "missing"

    def board_for(self, product: str, typ: str) -> dict:
        b = self.boards.get((product, typ)) or {}
        return b if b else (self.boards.get(("k2i", typ)) or {})


def open_legs(strat: dict, day: Day) -> list[dict] | None:
    legs = []
    for t in strat["legs"]:
        kind, prod = t["kind"], t["product"]
        b = day.board_for(prod, "F" if kind == "F" else "O")
        ym = t.get("ym") or pick_month(b, kind, day.d, int(strat.get("min_dte", 20)), day.last_trade)
        if not ym:
            return None
        k = None
        if kind != "F":
            k = t.get("k") or pick_strike(b, kind, ym, day.S * (1 + float(t.get("moneyness") or 0)))
            if k is None:
                return None
        q, src = day.quote(prod, kind, ym, k)
        if not q:
            return None
        legs.append({"kind": kind, "side": t["side"], "product": prod, "qty": t.get("qty", 1), "ym": ym, "k": k,
                     "expiry": str(expiry_of(ym, day.last_trade)), "entry_date": str(day.d), "entry_px": q["px"],
                     "last_px": q["px"], "src": src, "target_moneyness": t.get("moneyness")})
    return legs


def mark(strat: dict, day: Day) -> dict:
    """한 전략의 하루: 대기면 진입 시도, 보유면 다리별 정산가 마킹, 만기면 청산 후 롤. 기록 행을 돌려준다."""
    d, S = day.d, day.S
    row: dict = {"date": str(d), "S": S}
    prevS = strat.get("_lastS")
    if strat.get("status") in (None, "waiting"):
        if d < date.fromisoformat(strat["start"]):
            return {}
        legs = open_legs(strat, day)
        if not legs:
            row.update(status="진입 실패(시세 없음)")
            return row
        strat.update(status="open", legs_open=legs, cum=0.0, cycle_start=str(d))
        row.update(status="진입", pnl_day=0.0, pnl_cum=round(strat.get("pnl_total", 0.0), 0))
    elif strat.get("status") == "open":
        pnl, legrows, expired = 0.0, [], False
        for l in strat["legs_open"]:
            mult = MULT[l["product"]]
            exp = date.fromisoformat(l["expiry"])
            if d >= exp:
                px, src, q = intrinsic(l["kind"], S, l["k"]), "final", {}
                expired = True
            else:
                q, src = day.quote(l["product"], l["kind"], l["ym"], l["k"])
                px = q["px"] if q else l["last_px"]
            pnl += l["side"] * l["qty"] * mult * (px - l["last_px"])
            l["last_px"] = px
            q = q or {}
            mv = q.get("mini_vol", q.get("vol"))   # thin = 내가 실제로 들고 있는 상품(미니) 거래량 0
            legrows.append({"px": px, "src": src, "vol": q.get("vol"), "oi": q.get("oi"), "mini_px": q.get("mini_px"),
                            "mini_vol": q.get("mini_vol"), "mini_oi": q.get("mini_oi"), "close": q.get("close"),
                            "thin": bool(q) and not mv, "basis": q.get("px_basis")})
        strat["cum"] = strat.get("cum", 0.0) + pnl
        strat["pnl_total"] = strat.get("pnl_total", 0.0) + pnl
        row.update(status="만기 청산" if expired else ("마킹" if all(x["src"] != "missing" for x in legrows) else "일부 시세 없음(전일가 유지)"),
                   legs=legrows, pnl_day=round(pnl, 0), pnl_cum=round(strat["pnl_total"], 0))
        if expired:
            prem = sum(l["side"] * l["qty"] * MULT[l["product"]] * l["entry_px"] for l in strat["legs_open"])
            strat.setdefault("cycles", []).append({"entry": strat.get("cycle_start"), "exit": str(d), "legs": [leg_label(l) for l in strat["legs_open"]],
                                                   "premium_krw": round(prem, 0), "pnl_krw": round(strat["cum"], 0)})
            strat.update(status="waiting", legs_open=[], cum=0.0)
            if strat.get("roll") == "expiry":
                legs = open_legs(strat, day)
                if legs:
                    strat.update(status="open", legs_open=legs, cycle_start=str(d))
                    row["status"] = "만기 청산 → 롤"
    else:
        return {}
    # 그릭스·상쇄율 (보유 다리 기준, 이 날 가격)
    dl = th = 0.0
    ok = True
    for l in strat.get("legs_open", []):
        T = max((date.fromisoformat(l["expiry"]) - d).days, 0) / 365
        g = greeks(l["kind"], l["last_px"], S, l["k"], T)
        if g["delta"] is None:
            ok = False
            continue
        w = l["side"] * l["qty"] * MULT[l["product"]]
        dl += w * g["delta"]
        th += w * g["theta_pt"]
        l["iv"] = g["iv"]
    if strat.get("legs_open"):
        row.update(delta_krw_per_pt=round(dl, 0) if ok else None, theta_krw_day=round(th, 0) if ok else None,
                   iv=[l.get("iv") for l in strat["legs_open"]])
    if prevS and S:
        r = S / prevS - 1
        row["r_s"] = round(r, 5)
        if abs(r) >= 0.003 and row.get("pnl_day") is not None:   # 미니 1계약 명목 K200 롱이 잃은 돈 대비 이 전략이 번 돈
            row["offset_vs_1mini"] = round(row["pnl_day"] / (-(prevS * MULT["mini"]) * r), 3)
    strat["_lastS"] = S
    return row


def summary(strat: dict) -> dict:
    rows = [r for r in strat.get("rows", []) if r.get("pnl_day") is not None]
    last = strat["rows"][-1] if strat.get("rows") else {}
    big = [r for r in rows if (r.get("r_s") or 0) <= -0.03]
    return {"status": strat.get("status"), "legs": [leg_label(l) for l in (strat.get("legs_open") or strat.get("legs") or [])],
            "last_date": last.get("date"), "last_status": last.get("status"), "pnl_cum": last.get("pnl_cum"), "pnl_day": last.get("pnl_day"),
            "theta_krw_day": last.get("theta_krw_day"), "cycles": len(strat.get("cycles", [])), "min_cycles": strat.get("min_cycles", 3),
            "n_days": len(rows), "n_thin": sum(1 for r in rows for x in r.get("legs", []) if x.get("thin")),
            "n_proxy": sum(1 for r in rows for x in r.get("legs", []) if x.get("src") in ("k2i_proxy", "mini")),   # 1순위 소스가 아닌 날
            "n_mini_gap": sum(1 for r in rows for x in r.get("legs", []) if x.get("mini_px") and x.get("px") and abs(x["mini_px"] - x["px"]) > 0.005),
            "crash_days": [{"date": r["date"], "r_s": r["r_s"], "pnl_day": r["pnl_day"]} for r in big][-5:]}


def skeleton(today: date) -> dict:
    hf, meta = hf_strategies()
    strats = []
    for s in registry(hf):
        st = dict(s, status="waiting", rows=[{"date": str(today), "status": f"진입 대기({int(s['start'][5:7])}/{int(s['start'][8:])} 정산가)"}], cycles=[])
        st["margin"] = margin_slot(st)
        strats.append(st)
    return {"schema": "shadow_derivs_book/1", "asof": str(today), "title": "그림자 파생 북 (모의 · 돈 0 · 표시 전용)",
            "note": "실계좌 아님. KRX 일 정산가 마킹. 방향 신호·매매 권고 아님. 등급 = 검증전(학습 장부).",
            "spec": {"mult": MULT, "mult_src": MULT_SRC, "prod_id": {f"{a}_{b}": v for (a, b), v in PROD.items()},
                     "price": "정산가만(종가=마지막 체결가 마킹 금지) · 미니 옵션 = 정규 코스피200옵션 같은 종목 정산가(k2i_ref, KRX 상품명세: 미니 기준가격 = 정규 같은 종목 기준가격) → 없으면 미니 정산가 → 없으면 전일가 유지 · 선물 = 자체 정산가",
                     "greeks": "정산가 역산 IV · 블랙숄즈 r=3% 배당 0 (근사)", "realtime": "없음 — 장중 실시간은 증권사 Open API 필요(미연결)"},
            "spec_mini_opt": MINI_OPT_SPEC, "spec_mini_fut": MINI_FUT_SPEC, "wiring": WIRING, "hf_prereg": meta, "strategies": strats}


def _merge_registry(book: dict) -> None:
    hf, meta = hf_strategies()
    book["hf_prereg"] = meta
    have = {s["id"]: s for s in book.get("strategies", [])}
    for s in registry(hf):
        if s["id"] in have:
            cur = have[s["id"]]
            if cur.get("status") in (None, "waiting") and not cur.get("cycles"):   # 진입 전이면 정의 갱신 허용, 진입 후엔 고정(사전등록)
                cur.update({k: v for k, v in s.items() if k not in ("status", "rows", "cycles")})
        else:
            book["strategies"].append(dict(s, status="waiting", rows=[], cycles=[], margin=margin_slot(s)))


# ───────────── KRX 수집 (실행 환경: GitHub Actions deriv_hist, KRX 로그인 필요) ─────────────
def _spot_csv(d: date) -> float | None:
    try:
        with DAILY.open(encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if r.get("date") == str(d):
                    return _f(r.get("k200_close"))
    except Exception:  # noqa: BLE001
        pass
    return None


def _last_trade(product: str, d: date) -> tuple[dict, float | None]:
    """KRX 12801 종목 기본정보 → {ym: 최종거래일}, 승수(SETLMULT). 실패하면 ({}, None)."""
    from .derivs import _io
    out, mult = {}, None
    try:
        for r in _io("dbms/MDC/STAT/standard/MDCSTAT12801", trdDd=d.strftime("%Y%m%d"), prodId=PROD[(product, "O")]):
            m = RX_OPT.search(r.get("ISU_NM") or "") or RX_FUT.search(r.get("ISU_NM") or "")
            lt = (r.get("LSTTRD_DD") or "").replace("/", "-")
            if m and lt:
                out.setdefault(m.group(3) if m.re is RX_OPT else m.group(2), lt)
            mult = mult or _f(r.get("SETLMULT"))
    except Exception as e:  # noqa: BLE001
        log.info("12801 %s 실패: %s", product, e)
    return out, mult


def fetch_day(d: date, need: set[tuple[str, str]]) -> Day | None:
    from .derivs import _io
    boards = {}
    for prod, typ in sorted(need | {("k2i", "O"), ("k2i", "F")}):
        try:
            boards[(prod, typ)] = parse_board(_io("dbms/MDC/STAT/standard/MDCSTAT12501", trdDd=d.strftime("%Y%m%d"),
                                                  prodId=PROD[(prod, typ)], mktTpCd="T", rghtTpCd="T"), typ)
        except Exception as e:  # noqa: BLE001
            log.info("보드 %s %s %s 실패: %s", d, prod, typ, e)
            boards[(prod, typ)] = {}
        log.info("보드 %s %s/%s 종목 %d", d, prod, typ, len(boards[(prod, typ)]))
    if not boards.get(("k2i", "O")) and not boards.get(("k2i", "F")):
        return None
    S = _spot_csv(d) or next((q["spot"] for q in boards.get(("k2i", "F"), {}).values() if q.get("spot")), None)
    if not S:
        return None
    return Day(d, S, boards)


def update(today: date | None = None, fetch=fetch_day, write: bool = True) -> dict:
    from .tradecal import is_session
    today = today or date.today()
    try:
        book = json.loads(OUT.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        book = skeleton(today)
    _merge_registry(book)
    S_ = book["strategies"]
    need = {(l["product"], "F" if l["kind"] == "F" else "O") for s in S_ for l in s["legs"]}
    start = min(date.fromisoformat(s["start"]) for s in S_)
    done = book.get("last_marked")
    d = max(start, date.fromisoformat(done) + timedelta(days=1)) if done else start
    lt_cache: dict = {}
    n = 0
    while d <= today and n < MAX_DAYS:
        if not is_session("KR", d):
            d += timedelta(days=1)
            continue
        day = fetch(d, need)
        if day is None:
            if d < today:   # 과거 거래일 수집 실패 → 행을 만들지 않고 멈춤(다음 실행이 같은 날부터 재시도) + stale 기록
                book["stale"] = {"want": str(d), "got": book.get("last_marked")}
                try:
                    from .guard import record_stale
                    record_stale(str(OUT.relative_to(ROOT)), "그림자 파생 북", d, book.get("last_marked"))
                except Exception:  # noqa: BLE001
                    pass
            break
        if not lt_cache:
            for prod in {p for p, _ in need}:
                lt, mult = _last_trade(prod, d)
                lt_cache.update(lt)
                if mult:
                    book["spec"].setdefault("mult_krx", {})[prod] = mult
                    if prod == "mini" and mult != MULT["mini"]:
                        log.warning("⛔ 미니 승수 KRX %s ≠ 가정 %s — 장부 원화값 재확인 필요", mult, MULT["mini"])
        day.last_trade = lt_cache
        for s in S_:
            row = mark(s, day)
            if row:
                rows = s.setdefault("rows", [])
                if rows and rows[-1].get("status", "").startswith("진입 대기"):
                    rows.pop()
                rows.append(row)
        book["last_marked"] = str(d)
        book.pop("stale", None)
        n += 1
        d += timedelta(days=1)
    for s in S_:
        s["summary"] = summary(s)
    from zoneinfo import ZoneInfo
    book["asof"] = book.get("last_marked") or str(today)
    book["generated_at"] = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M")
    if write:
        from .guard import write_json
        OUT.parent.mkdir(parents=True, exist_ok=True)
        write_json(OUT, book, key="asof", indent=1)
    return book


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="그림자 파생 북 갱신 (표시 전용)")
    ap.add_argument("--init", action="store_true", help="수집 없이 진입 대기 장부만 새로 쓴다")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if a.init:
        book = skeleton(date.today())
        for s in book["strategies"]:
            s["summary"] = summary(s)
        from zoneinfo import ZoneInfo
        book["generated_at"] = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M")
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(book, ensure_ascii=False, indent=1), encoding="utf-8")
        print("init", OUT)
        return
    b = update()
    for s in b["strategies"]:
        print(s["id"], s["summary"]["status"], s["summary"]["last_status"], s["summary"]["pnl_cum"])


if __name__ == "__main__":
    main()
