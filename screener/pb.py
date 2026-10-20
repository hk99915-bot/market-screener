"""개인 PB 아침 브리핑 — 보유 내역은 GitHub 비공개 시크릿 MY_HOLDINGS 에서만 읽는다 (저장소·로그에 남기지 않음).

MY_HOLDINGS 형식 (웹 MY 탭과 동일, 한 줄에 하나 — 위성 북, 그 뒤 `## ISA` 줄부터 ISA 코어 북):
    005930 10 70000
    TIGER 200 IT 5 30000
    MU 2 100.0
    USD 1000
    현금 1000000
    ## ISA
    360750 100 20000
    133690 20 100000
    069500 30 40000
    148070 40 110000
    132030 50 20000
    현금 500000
선택: MY_RULES — 줄마다 '종목코드 가격' (종가 2일 연속 이탈 시 경고), '종목코드 가격 touch' (장중 저가 터치 즉시 ⛔, 결재 #2 예외 조건), 'LOSS_LIMIT 0.12' (순자산 대비 손실 한도), 'SEMI_CAP 0.40', 'SEMI_BAND 0.45', 'SAVINGS <예적금 금액>' (결재 #1 분모 (b): 반도체 비중·D2 스트레스 분모에 더함, 출력은 비율만)

분모는 항상 순자산 = 위성 + ISA + 현금(원화·달러). 반도체 비중은 '반도체(전기 제외)' 를 기본으로, '반도체+전기(상관 테마)' 를 보조로 보인다.
지수 ETF(KODEX 200·S&P500·나스닥100 …) 속 반도체 룩스루는 한도 계산에서 빼고 '참고 경보' 한 줄로만 보인다 (합의 1-④).
섹터 ETF(TIGER 200 IT·KODEX 반도체·SOXX·SMH·PSI …)는 전액 반도체로 센다. 텔레그램에는 비율만 보낸다 (금액 없음).
스트레스(결재 #3): '2026-07 재현(반도체 −30%)' 손실률을 비율로 계산해 규칙 점검에 한 줄 — 분모는 evaluate(stress_denominator_code=) 로 고른다 (기본 D2).
"""
from __future__ import annotations

import json
import logging
import os
import re

from .config import REPORT_DIR
from . import sectors   # 공식 1종목1섹터(GICS/WICS) 병행 계산 — 전환 스위치 sectors.OFFICIAL_LIMITS (10/21)

log = logging.getLogger(__name__)


def _num(x):
    try:
        return float(str(x).replace(",", ""))
    except ValueError:
        return None


ISA_HEAD = re.compile(r"^#{1,3}\s*ISA\b", re.I)
from .defs import ISA_BAND, ISA_TARGET   # ISA 코어 목표 (안건 8) ±5%p — 단일 원천 screener/defs.py
SEMI_ETFS = {"139260", "091160", "PSI", "SOXX", "SMH", "SOXL", "SOXQ", "XSD", "SMHX", "396500", "395160", "449450"}   # 반도체·IT 섹터 ETF (전액 반도체)
US_SEMIS = {"MU", "SNDK", "NVDA", "AMD", "AVGO", "TSM", "INTC", "QCOM", "ARM", "MRVL", "LRCX", "AMAT", "KLAC", "ASML", "WDC", "STX"}
RE_SEMI = re.compile(r"반도체")
RE_ELEC = re.compile(r"IT 하드웨어")   # 전자부품(삼성전기 등)·디스플레이 — '상관 테마'


SAVINGS_KEYS = ("예적금", "적금", "예금", "SAVINGS")
ISA_MONTHLY_KEYS = ("ISA적립", "ISA_MONTHLY", "적립")   # 결재 #3 글라이드: 'ISA적립 <월 금액> [적립일]' — 금액은 비공개 입력에만, 출력은 비율만


def isa_monthly_in(txt: str) -> tuple[float, int]:
    """보유 텍스트/MY_RULES 의 'ISA적립 <월 금액> [일]' → (월 금액, 적립일 1~28, 기본 1). 없으면 (0, 1)."""
    amt, day = 0.0, 1
    for ln in (txt or "").splitlines():
        p = ln.strip().split()
        if len(p) >= 2 and p[0].upper() in ISA_MONTHLY_KEYS:
            amt += _num(p[1]) or 0.0
            if len(p) >= 3 and _num(p[2]):
                day = max(1, min(28, int(_num(p[2]))))
    return amt, day


def savings_in(txt: str) -> float:
    """보유 텍스트의 '예적금 <금액>' 줄 합 — 결재 #1 분모 (b). MY 탭과 같은 형식 (MY_RULES 'SAVINGS' 와 둘 중 하나만 써도 됨)."""
    tot = 0.0
    for ln in (txt or "").splitlines():
        p = ln.strip().split()
        if len(p) >= 2 and p[0].upper() in SAVINGS_KEYS:
            tot += _num(p[1]) or 0.0
    return tot


def parse_books(txt: str) -> dict[str, tuple[list[dict], float, float]]:
    """`## ISA` 줄을 경계로 위성(sat)·ISA 두 북으로 나눠 파싱. 각 북 = (보유 목록, 원화 현금, 달러 현금)."""
    books = {"sat": ([], 0.0, 0.0), "isa": ([], 0.0, 0.0)}
    cur = "sat"
    chunks = {"sat": [], "isa": []}
    for ln in txt.splitlines():
        if ISA_HEAD.match(ln.strip()):
            cur = "isa"
            continue
        if ln.strip().startswith("#"):
            continue
        if ln.strip().split()[:1] and ln.strip().split()[0].upper() in SAVINGS_KEYS + ISA_MONTHLY_KEYS:
            continue   # 예적금·ISA 적립 계획은 보유가 아님 — savings_in()/isa_monthly_in() 이 분모·글라이드로만 쓴다
        chunks[cur].append(ln)
    for b in books:
        books[b] = _parse_lines("\n".join(chunks[b]))
    return books


def parse(txt: str) -> tuple[list[dict], float, float]:
    """위성 북만 (하위 호환). ISA 북은 parse_books(txt)["isa"]."""
    return parse_books(txt)["sat"]


def _parse_lines(txt: str) -> tuple[list[dict], float, float]:
    hs, krw, usd = [], 0.0, 0.0
    for ln in txt.splitlines():
        p = ln.strip().split()
        if not p:
            continue
        k = p[0].upper()
        if k in ("현금", "KRW", "CMA", "원화", "예수금", "RP") or k.startswith("CMA"):
            krw += _num(p[1]) or 0
            continue
        if k in ("USD", "달러", "미국달러"):
            usd += _num(p[1]) or 0
            continue
        nums = []
        i = len(p)
        while i > 1 and len(nums) < 2 and _num(p[i - 1]) is not None:
            nums.insert(0, _num(p[i - 1]))
            i -= 1
        hs.append({"key": " ".join(p[:i]), "qty": nums[0] if nums else 0, "avg": nums[1] if len(nums) > 1 else None})
    return hs, krw, usd


def _index() -> list[tuple[str, str, str]]:
    out = []
    for mk in ("KR", "US"):
        p = REPORT_DIR / "detail" / mk / "_index.json"
        if p.exists():
            j = json.loads(p.read_text(encoding="utf-8"))
            out += [(mk, s, str((j.get("names") or {}).get(s, s))) for s in j.get("symbols", [])]
    return out


def resolve(key: str, idx) -> tuple[str, str] | None:
    k = key.lower().strip()
    for mk, s, n in idx:
        if s.lower() == k or n.lower() == k:
            return mk, s
    if re.fullmatch(r"[a-z][a-z.\-]{0,5}|\d{6}", k):
        return None
    for mk, s, n in idx:
        if n.lower().startswith(k) or k.replace(" ", "") in n.lower().replace(" ", ""):
            return mk, s
    return None


def _detail(mk: str, s: str) -> dict | None:
    p = REPORT_DIR / "detail" / mk / f"{s}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def isa_bucket(s: str, name: str) -> str | None:
    """ISA 코어 종목 → 목표 바구니 (S&P500 / NDX / K200 / KTB / Gold). 못 고르면 None(기타)."""
    n = (name or "").upper()
    if s == "360750" or "S&P" in n or s in ("SPY", "IVV", "VOO", "SPLG"):
        return "S&P500"
    if s == "133690" or "나스닥" in n or "NDX" in n or s in ("QQQ", "QQQM"):
        return "NDX"
    if s in ("148070", "305080", "152380") or re.search(r"국고채|국채|KTB", n):
        return "KTB"
    if s == "132030" or re.search(r"골드|금선물|GOLD", n) or s in ("GLD", "IAU"):
        return "Gold"
    if s == "069500" or (re.search(r"(^|\s)200(\s|$)|코스피", n) and not re.search(r"IT|반도체|인버스|레버리지|선물인버스", n)):
        return "K200"
    return None


def semi_class(mk: str, s: str, name: str, chain: str, is_etf: bool, look_chains: dict) -> tuple[str | None, float]:
    """반도체 분류. 반환 (kind, look_w): kind = 'semi'(한도 산입) / 'elec'(전기·IT 하드웨어, 상관 테마) / None.
    look_w = 지수 ETF 등 한도 밖 ETF 안의 반도체·IT 하드웨어 룩스루 비중 (참고 경보용, 한도 제외)."""
    n = (name or "").upper()
    if is_etf:
        if s in SEMI_ETFS or re.search(r"반도체|SEMI|SOX|IT$|\bIT\b|테크", n):
            return "semi", 0.0
        lw = sum(w for k, w in (look_chains or {}).items() if RE_SEMI.search(k) or RE_ELEC.search(k))
        return None, lw
    if s in US_SEMIS or RE_SEMI.search(chain or ""):
        return "semi", 0.0
    if RE_ELEC.search(chain or ""):
        return "elec", 0.0
    return None, 0.0


# ---------------------------------------------------------------- 스트레스 (결재 #3: 구속 한도 = 스트레스 −15%, VaR·ES 는 계기판)
# 2026-07 재현 — 반도체 −30% 가정 (SOXX 2026-06-22 → 07-29 −29%, kb:frm#9 사건 재생). 충격은 분류별 비율:
#   semi(한도 산입 반도체·섹터 ETF 전액) −30% · elec(전기·IT 하드웨어, 상관 테마 ρ≈0.8 가정, kb:frm#8·#23) −24% · 지수 ETF 룩스루 분은 −30% × 룩스루 비중
#   그 외(코어 지수 ETF 나머지·국채·금·현금) 0 — 반도체 단일 요인 충격만 재생한다 (코스피 β 전염은 MY 탭 'β 추정' 줄이 따로 본다).
STRESS_SCENARIOS = {
    "2026-07": {"label": "2026-07 재현(반도체 −30%)", "semi": -0.30, "elec": -0.24, "look": -0.30},
}
from .defs import STRESS_LIMIT   # 0.15 — 어느 시나리오도 −15% 초과 금지 (scorecard_week [11] 스트레스 와 같은 수치)
STRESS_DENOMINATORS = ("D2", "D1", "EQ")   # docs/rules_terms.md §0: D2 전체 투자자산(기본, 결재 #1 (b) 가정) · D1 위성 북 · EQ 주식만(참고)


def stress_denominator(code: str, *, nav: float, tot: float, tot_sat: float, cash_sat: float) -> tuple[float, tuple[str, ...]]:
    """분모 코드 → (분모 금액, 손실을 집계할 북). D1 은 위성 북만(ISA 코어 제외), D2·EQ 는 두 북 모두."""
    code = (code or "D2").upper()
    if code not in STRESS_DENOMINATORS:
        raise ValueError(f"stress denominator must be one of {STRESS_DENOMINATORS}, got {code!r}")
    if code == "D1":
        return tot_sat + cash_sat, ("sat",)        # denominator=D1 위성 북 = 위성 주식 + 위성 현금
    if code == "EQ":
        return tot, ("sat", "isa")                 # denominator=EQ 주식 평가액 합 (참고용 — 현금 완충 제외)
    return nav, ("sat", "isa")                     # denominator=D2 전체 투자자산(NAV)


def stress_loss(rows: list[dict], denom: float, scenario: str = "2026-07", books: tuple[str, ...] = ("sat", "isa")) -> float:
    """시나리오 손실률 (비율, 손실이면 음수). rows 는 evaluate() 의 rows, denom 은 stress_denominator() 가 준 금액.
    금액은 돌려주지 않는다 — MY 탭·텔레그램엔 이 비율만 나간다."""
    sc = STRESS_SCENARIOS[scenario]
    if not denom:
        return 0.0
    pnl = 0.0
    for r in rows:
        if r["book"] not in books:
            continue
        if r.get("semi"):
            pnl += r["v"] * sc["semi"]
        elif r.get("elec"):
            pnl += r["v"] * sc["elec"]
        else:
            pnl += (r.get("look") or 0.0) * sc["look"]   # look = 평가액 × 지수 ETF 속 반도체 룩스루 비중
    return pnl / denom


def stress_line(ev: dict, scenario: str = "2026-07") -> str:
    """텔레그램 한 줄 — 비율만. 한도(−15%) 초과면 ⛔ (구속 한도), 아니면 ✅."""
    x = ev["stress"][scenario]
    sc = STRESS_SCENARIOS[scenario]
    # denominator=ev['stress_denom'] (기본 D2) — 비율은 이미 그 분모로 나눠져 있다
    tag = " ⛔ 구속 한도 초과 — 반도체 비중 축소(kb:frm#10 허용 충격 = 15 ÷ 비중)" if x < -STRESS_LIMIT - 0.0005 else " ✅"
    return f"• 스트레스 {sc['label']}: <b>{x*100:+.1f}%</b> (한도 −{STRESS_LIMIT*100:.0f}% · 분모 {ev['stress_denom']} · 비율만){tag}"


def rules(rules_txt: str) -> dict:
    from .defs import LOSS_LIMIT, SEMI_BAND, SEMI_CAP   # 기본값 단일 원천 (MY_RULES 줄이 있으면 덮어씀)
    o = {"loss_limit": LOSS_LIMIT, "semi_cap": SEMI_CAP, "semi_band": SEMI_BAND, "price": {}, "touch": {}, "savings": 0.0}
    for ln in (rules_txt or "").splitlines():
        p = ln.split()
        if len(p) < 2:
            continue
        k = p[0].upper()
        if k == "LOSS_LIMIT":
            o["loss_limit"] = _num(p[1]) or o["loss_limit"]
        elif k == "SEMI_CAP":
            o["semi_cap"] = _num(p[1]) or o["semi_cap"]
        elif k == "SEMI_BAND":
            o["semi_band"] = _num(p[1]) or o["semi_band"]
        elif k == "SAVINGS":       # 예적금(불가침) — 결재 #1 분모 (b) = 투자자산 + 예적금. 금액은 시크릿에만, 출력은 비율만
            o["savings"] = _num(p[1]) or 0.0
        elif _num(p[1]) and len(p) >= 3 and p[2].lower() in ("touch", "즉시"):
            o["touch"][k] = _num(p[1])     # '종목코드 가격 touch' — 장중 저가 터치 즉시 ⛔ (종가 2일 규칙과 별개)
        elif _num(p[1]):
            o["price"][k] = _num(p[1])
    return o


def _fx() -> float:
    try:
        ms = json.loads((REPORT_DIR / "macro_series.json").read_text(encoding="utf-8"))["series"]["USDKRW"]
        return ms[-1][4] if len(ms[-1]) >= 6 else ms[-1][1]
    except Exception:  # noqa: BLE001
        return 1400.0


def evaluate(txt: str, rules_txt: str = "", stress_denominator_code: str = "D2") -> dict | None:
    """보유 텍스트 → 비율 묶음. 금액은 반환값 안에만 있고 밖으로 보내지 않는다 (호출자는 비율만 쓴다).
    stress_denominator_code: 스트레스 손실률의 분모 (D2 전체 투자자산 기본 · D1 위성 북 · EQ 주식만) — STRESS_DENOMINATORS."""
    books = parse_books(txt)
    ru = rules(rules_txt)
    idx = _index()
    fx = _fx()
    rows, miss = [], []
    for book, (hs, krw, usd) in books.items():
        for h in hs:
            r = resolve(h["key"], idx)
            d = _detail(*r) if r else None
            if not d:
                miss.append(h["key"])
                continue
            mk, s = r
            f = fx if mk == "US" else 1.0
            v = d["close"] * h["qty"] * f
            c = h["avg"] * h["qty"] * f if h["avg"] else None
            dv = d.get("drivers") or {}
            look = ((d.get("etf") or {}).get("look") or {})
            chain = (dv.get("chain") or {}).get("name") or ("ETF" if d.get("etf") else (d.get("valuation") or {}).get("sector")) or mk
            st = d.get("stats") or {}
            c1y = d.get("c1y") or []
            name = re.sub(r",?\s+(Inc\.?|Corporation|Corp\.?)$", "", re.sub(r"\s*[-–]\s*(Common Stock|Ordinary).*$", "", d.get("name") or s))
            kind, lw = semi_class(mk, s, name, chain, bool(d.get("etf")), look.get("chains") or {})
            # 새 기준(공식 1종목1섹터: GICS/WICS, 10/21 겸이 승인) 병행 계산 — ETF·판정 불가는 예전 분류를 그대로 쓴다
            off = sectors.official(mk, s) if not d.get("etf") else {"sector": "ETF", "group": None, "src": "ETF"}
            sn = sectors.semi_official(mk, s) if not d.get("etf") else None
            semi_new = (kind == "semi") if sn is None else sn
            rows.append({"sec_new": off["sector"], "sec_src": off["src"], "semi_new": semi_new,"book": book, "mk": mk, "s": s, "name": name, "v": v, "c": c, "r1": st.get("ret1"),
                         "drv": dv.get("score") if not d.get("etf") else look.get("drv"),
                         "stop": ((d.get("scenarios") or {}).get("bear") or {}).get("stop"), "close": d["close"], "etf": bool(d.get("etf")),
                         "semi": kind == "semi", "elec": kind == "elec", "look": v * lw, "isa": isa_bucket(s, name) if book == "isa" else None,
                         "last2": [x[1] for x in c1y[-2:]], "c61": [x[1] * f for x in c1y[-(VAR_WINDOW + 1):]]})
    if not rows:
        return None
    sat = [r for r in rows if r["book"] == "sat"]
    isa = [r for r in rows if r["book"] == "isa"]
    cash_sat = books["sat"][1] + books["sat"][2] * fx
    cash_isa = books["isa"][1] + books["isa"][2] * fx
    tot_sat, tot_isa = sum(r["v"] for r in sat), sum(r["v"] for r in isa)
    # denominator=D2 전체 투자자산(NAV) = 위성 주식 + ISA + 원화·달러 현금 (docs/rules_terms.md §0) — 반도체 비중·손실 한도의 분모
    nav = tot_sat + tot_isa + cash_sat + cash_isa
    tot = tot_sat + tot_isa
    cost = sum(r["c"] for r in rows if r["c"])
    semi_old = sum(r["v"] for r in rows if r["semi"])
    semi_new = sum(r["v"] for r in rows if r["semi_new"])
    # 전환 스위치(screener/sectors.OFFICIAL_LIMITS): False = 예전 판정 유지, 새 기준은 아래 *_new 필드로만 병행
    semi = semi_new if sectors.OFFICIAL_LIMITS else semi_old
    sec_w: dict[str, float] = {}
    for r in rows:
        sec_w[r["sec_new"] or "분류 없음"] = sec_w.get(r["sec_new"] or "분류 없음", 0.0) + r["v"]
    elec = sum(r["v"] for r in rows if r["elec"])
    look = sum(r["look"] for r in rows)
    loss = cost - sum(r["v"] for r in rows if r["c"])
    isa_tot = tot_isa + cash_isa
    isa_w = {k: 0.0 for k in ISA_TARGET}
    isa_etc = 0.0
    for r in isa:
        if r["isa"]:
            isa_w[r["isa"]] += r["v"]
        else:
            isa_etc += r["v"]
    isa_w = {k: (v / isa_tot if isa_tot else 0.0) for k, v in isa_w.items()}
    # denominator=stress_denominator_code (기본 D2 nav) — 결재 #3 구속 한도 '스트레스 −15%' 의 손실률, 비율만 보관
    # 결재 #1 (b): MY_RULES 'SAVINGS <금액>' 이 있으면 반도체 비중·D2 스트레스 분모에 예적금을 더한다 (없으면 (a) 투자자산만)
    sav = (ru.get("savings") or 0.0) or savings_in(txt)
    den = nav + sav
    from .defs import DENOM_TERMS
    den_label = DENOM_TERMS["b"] if sav > 0 else DENOM_TERMS["a"] + " · 예적금 미입력"
    st_den, st_books = stress_denominator(stress_denominator_code, nav=den, tot=tot, tot_sat=tot_sat, cash_sat=cash_sat)
    stress = {k: stress_loss(rows, st_den, k, st_books) for k in STRESS_SCENARIOS}
    swing = sum(r["v"] for r in rows if r["s"] in SEMI_SWING and not r["semi"])
    reg = semi_regime()
    var99 = var99_window(rows, den)
    monthly, mday = isa_monthly_in(txt)
    if not monthly:
        monthly, mday = isa_monthly_in(rules_txt)
    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo as _Z
    today = _dt.now(_Z("Asia/Seoul")).date()
    band = {"regime": reg, "var99": var99, "var_limit": var_limit(reg["regime"]),
            "ex": band_status(semi / den if den else 0.0, reg["regime"]),
            "incl": band_status((semi + swing) / den if den else 0.0, reg["regime"]),
            "glide": glide_path(semi, den, monthly, today, day=mday), "has_monthly": monthly > 0}
    return {"band": band, "rows": rows, "stress": stress, "stress_denom": stress_denominator_code.upper(), "miss": miss, "fx": fx, "rules": ru, "nav": nav, "tot": tot, "tot_sat": tot_sat, "tot_isa": tot_isa, "isa_tot": isa_tot,
            "cash": cash_sat + cash_isa, "cost": cost, "loss": loss, "has_isa": bool(isa) or cash_isa > 0,
            "denom": den_label,
            "semi_ex": semi / den if den else 0.0,
            "semi_ex_old": semi_old / den if den else 0.0, "semi_ex_new": semi_new / den if den else 0.0,
            "sector_w_new": {k: v / den for k, v in sorted(sec_w.items(), key=lambda kv: -kv[1])} if den else {},
            "sector_basis": {"switch": sectors.OFFICIAL_LIMITS, "new": "GICS(미장)/" + sectors._kr()[1] + "(국장) 1종목1섹터",
                             "old": "체인 기반 반도체 분류(semi_class)", "using": "new" if sectors.OFFICIAL_LIMITS else "old"}, "semi_elec": (semi + elec) / den if den else 0.0, "look": look / den if den else 0.0,
            "isa_w": isa_w, "isa_etc": isa_etc / isa_tot if isa_tot else 0.0, "isa_cash": cash_isa / isa_tot if isa_tot else 0.0,
            "day": sum(r["v"] - r["v"] / (1 + r["r1"]) for r in rows if r["r1"] is not None) / nav if nav else 0.0}


# ---------------------------------------------------------------- 결재 #3 (10/17 14:09): 레짐 연동 밴드 · 적립 글라이드 · VaR 계기판
from .defs import (SEMI_BAND, SEMI_FLOOR, SEMI_GLIDE_BY, SEMI_GLIDE_TARGET, SEMI_REGIME_CAP, SEMI_SWING,  # noqa: E402
                   VAR99_LIMIT, VAR99_LIMIT_BEAR, VAR99_Z, VAR_WINDOW)


def semi_regime(closes: list[float] | None = None) -> dict:
    """반도체 밴드용 레짐 — 코스피 종가(오래된→최신)로:
    상승장 = regime_tag '상승'(52주 고점 −10% 이내 & 200일선 위) · 회복확인 = 그 밖이면서 20일선 위 2일 연속(committee 회복 확인과 같은 정의)
    · 하락장 = 나머지(조정 포함 — 보수적으로 35%). 데이터 없으면 하락장으로 본다 [가정: 모르면 가장 낮은 상한]."""
    from .regime_tag import classify
    if closes is None:
        try:
            from .alerts import _close, kospi_rows
            closes = [_close(r) for r in kospi_rows()]
        except Exception:  # noqa: BLE001
            closes = []
    c = [x for x in (closes or []) if x]
    t = classify(c) if c else None
    streak = 0
    for i in range(len(c) - 1, 19, -1):
        if c[i] > sum(c[i - 19:i + 1]) / 20:
            streak += 1
        else:
            break
    if t and t["l"] == "상승":
        lab = "상승장"
    elif streak >= 2:
        lab = "회복확인"
    else:
        lab = "하락장"
    return {"regime": lab, "tag": (t or {}).get("l"), "dd": (t or {}).get("dd"), "above20": streak, "n": len(c),
            "src": "macro_series KOSPI (regime_tag.classify + 20일선 2일)" if c else "데이터 없음 → 하락장 가정"}


def band_status(x: float, regime: str) -> dict:
    """비중 x(denominator=D2 (b)) → 밴드 판정. 위에서부터: 발동선 45 초과 / 레짐 상한 초과 / 하단 30 미만 / 밴드 안."""
    cap = SEMI_REGIME_CAP.get(regime, min(SEMI_REGIME_CAP.values()))
    if x > SEMI_BAND + 0.005:   # denominator=D2
        st, tag = "trigger", f"⛔ 발동선 {SEMI_BAND*100:.0f}% 초과 — 다음 반등일 {cap*100:.0f}%로"
    elif x > cap + 0.005:       # denominator=D2
        st, tag = "over", f"상한 {cap*100:.0f}%({regime}) 초과 — 반도체 신규 매수 금지"
    elif x < SEMI_FLOOR - 0.005:   # denominator=D2
        st, tag = "floor", f"하단 {SEMI_FLOOR*100:.0f}% 미만 — 재매수 허용(의무 아님)"
    else:
        st, tag = "ok", "밴드 안 ✅"
    return {"x": x, "cap": cap, "trigger": SEMI_BAND, "floor": SEMI_FLOOR, "status": st, "tag": tag}


def var_limit(regime: str) -> float:
    return VAR99_LIMIT_BEAR if regime == "하락장" else VAR99_LIMIT


def var99_window(rows: list[dict], den: float, window: int = VAR_WINDOW) -> dict | None:
    """60거래일 실현 변동성 1일 VaR99 = VAR99_Z × σ(포트 일수익) ÷ 분모 — 계기판(강제 매도 없음).
    포트 일수익 = Σ 평가액_i × 수익률_i,t (현금·예적금 0). 종목 간 날짜는 끝에서부터 위치로 맞춘다 [가정: 한·미 시차 무시 — 상관 과소 가능]."""
    series = []
    for r in rows:
        c = [x for x in (r.get("c61") or []) if x]
        if len(c) >= 21:
            series.append((r["v"], [c[i] / c[i - 1] - 1 for i in range(1, len(c))]))
    if not series or not den:
        return None
    n = min(window, min(len(s) for _, s in series))
    pnl = [sum(v * s[-n + t] for v, s in series) for t in range(n)]
    mu = sum(pnl) / n
    sd = (sum((x - mu) ** 2 for x in pnl) / (n - 1)) ** 0.5 if n > 1 else 0.0
    return {"var99": VAR99_Z * sd / den, "n": n, "window": window}   # denominator=D2 (b)


def _month_days(today, by, day: int):
    from datetime import date
    out, y, m = [], today.year, today.month
    while True:
        d = date(y, m, day)
        if d > by:
            return out
        if d > today:
            out.append(d)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def glide_path(semi: float, den: float, monthly: float, today, by: str = SEMI_GLIDE_BY, day: int = 1,
               target: float = SEMI_GLIDE_TARGET) -> dict:
    """11월 말 35% 글라이드 — ISA 월 적립(비반도체)이 분모만 키운다고 보고 날짜별 예상 비중(비율만).
    [가정: 가격 불변 · 반도체 매도 없음 · 적립일 = 매월 day일]. need = 11월 말 35% 에 필요한 추가 축소(분모 대비 %p)."""
    from datetime import date
    end = date.fromisoformat(by)
    if not den:
        return {"points": [], "need": 0.0, "target": target, "by": by}
    x0 = semi / den   # denominator=D2 (b)
    pts = [{"d": str(today), "x": x0, "line": x0, "what": "지금"}]
    span = max((end - today).days, 1)
    k = 0
    for d in _month_days(today, end, day):
        k += 1
        pts.append({"d": str(d), "x": semi / (den + k * monthly), "line": x0 + (target - x0) * (d - today).days / span, "what": f"ISA 적립 {k}회"})
    den_end = den + k * monthly
    pts.append({"d": by, "x": semi / den_end, "line": target, "what": "목표일"})
    need = max(semi - target * den_end, 0.0) / den   # denominator=D2 (b) — 지금 분모 대비 추가 축소 %p
    return {"points": pts, "need": need, "target": target, "by": by, "n_contrib": k, "contrib_ratio": monthly / den}


def band_lines(ev: dict) -> list[str]:
    """아침 점검(무음) — 레짐 밴드 · 삼성전기 포함/제외 병기 · 글라이드 · VaR 계기판. 비율만."""
    b = ev.get("band")
    if not b:
        return []
    rg, ex, inc, g, v = b["regime"], b["ex"], b["incl"], b["glide"], b["var99"]
    L = [f"• 반도체 밴드(결재 #3) 레짐 <b>{rg['regime']}</b> → 상한 {ex['cap']*100:.0f}% · 발동선 {ex['trigger']*100:.0f}% · 하단 {ex['floor']*100:.0f}%",
         f"  삼성전기 제외 {ex['x']*100:.0f}% ({ex['tag']}) | 포함 {inc['x']*100:.0f}% ({inc['tag']}) — 포함 여부 11/15 결정"]
    if g.get("points"):
        L.append(f"  글라이드 {g['by'][5:]} {g['target']*100:.0f}%: 적립 {g.get('n_contrib', 0)}회 반영 시 {g['points'][-1]['x']*100:.0f}%"
                 + (f" · 추가 축소 필요 {g['need']*100:.1f}%p" if g["need"] > 0.0005 else " · 적립만으로 도달 ✅")
                 + ("" if b.get("has_monthly") else " (ISA적립 줄 없음 — 적립 0 가정)"))
    if v:
        over = v["var99"] > b["var_limit"]
        L.append(f"  VaR99 1일(60일 실현) {v['var99']*100:.1f}% / 한도 {b['var_limit']*100:.1f}%"
                 + (" — <b>반도체 신규 매수 금지</b>(강제 매도 없음)" if over else " ✅"))
    return L


def semi_line(ev: dict) -> str:
    cap, band = ev["rules"]["semi_cap"], ev["rules"]["semi_band"]
    if ev.get("band"):
        cap = ev["band"]["ex"]["cap"]   # 결재 #3: 상한은 레짐 연동(하락장 35 · 회복확인 40 · 상승장 40)
    x = ev["semi_ex"]
    # denominator=ev['denom'] (D2 (b))
    tag = f" ⛔ 발동선 초과 — 다음 반등일 {cap*100:.0f}%로" if x > band + 0.005 else " ⛔ 상한 초과 — 추가 매수 금지" if x > cap + 0.005 else " ✅"
    return (f"• 반도체(전기 제외) <b>{x*100:.0f}%</b> · 분모 {ev.get('denom', '(a)')} (상한 {cap*100:.0f}% · 발동선 {band*100:.0f}%){tag}\n"
            f"  반도체+전기(상관 테마) {ev['semi_elec']*100:.0f}% · 참고: 지수 ETF 속 반도체 ≈ {ev['look']*100:.0f}% 추가 (한도 제외)")


def isa_lines(ev: dict) -> list[str]:
    if not ev.get("has_isa"):
        return []
    parts = []
    for k, t in ISA_TARGET.items():
        w = ev["isa_w"].get(k, 0.0)
        d = w - t
        mark = "✅" if abs(d) <= ISA_BAND else ("▲" if d > 0 else "▼")
        parts.append(f"{k} {w*100:.0f}/{t*100:.0f}{mark}")
    L = [f"• ISA 코어 순자산 {ev['isa_tot']/ev['nav']*100:.0f}% · 밴드 ±{ISA_BAND*100:.0f}%p: " + " · ".join(parts)]
    if ev["isa_cash"] > 0.005 or ev["isa_etc"] > 0.005:
        L.append(f"  ISA 현금 {ev['isa_cash']*100:.0f}% · 기타 {ev['isa_etc']*100:.0f}%")
    return L


def brief() -> str | None:
    return brief_keys()[0]


def brief_keys() -> tuple[str | None, list[str]]:
    """(본문, 알림 키). 키는 결재 #9 등급표(alerts.RING_KINDS)로 소리를 정한다 — PB 회신 10/17(감사 M1):
    '손절 2일' = 보유 종목 기준가(MY_RULES price) 2일 연속 종가 이탈 + 코스피 5,451 선 → 'stop2:<코드>'(소리).
    1일 이탈 'stop1:<코드>'·손실 한도 'loss_limit' 은 표 밖(무음). 지금은 TELEGRAM_ALL_SILENT 로 전부 무음."""
    txt = os.environ.get("MY_HOLDINGS", "").strip()
    if not txt:
        return None, []
    ev = evaluate(txt, os.environ.get("MY_RULES", ""))
    if not ev:
        return None, []
    keys: list[str] = []
    rows, nav, tot, cost, loss, miss = ev["rows"], ev["nav"], ev["tot"], ev["cost"], ev["loss"], ev["miss"]
    loss_limit, price_rules = ev["rules"]["loss_limit"], ev["rules"]["price"]
    cash = ev["cash"]
    # denominator=D2 nav (누적 손실 한도 LOSS_LIMIT · 반도체 비중 모두 같은 분모 — docs/rules_terms.md)
    room = loss_limit * nav - loss
    from .defs import DENOM_TERMS
    L = [f"🧑‍💼 <b>PB 아침 점검</b> <i>분모: {DENOM_TERMS['a']}(위성+ISA+현금) · 반도체·스트레스는 {ev.get('denom', DENOM_TERMS['a'])}</i>",
         f"주식 {tot/nav*100:.0f}% (위성 {ev['tot_sat']/nav*100:.0f}% · ISA {ev['tot_isa']/nav*100:.0f}%) · 현금 {cash/nav*100:.0f}% (금액은 터미널 MY 탭에서만)",
         f"주식 손익 {(-loss)/cost*100 if cost else 0:+.1f}% · 최근일 {ev['day']*100:+.2f}%"]
    L.append("")
    L.append("<b>규칙 점검</b>")
    # denominator=D2 nav — 규정 원문엔 없는 구 규칙(LOSS_LIMIT), 용어집 '누적 손실 한도' 참조
    L.append(f"• 손실 한도(순자산 −{loss_limit*100:.0f}%)까지 " + (f"순자산 <b>{room/nav*100:.1f}%</b> 남음 (주식 −{room/tot*100:.1f}% 추가 하락 여유)" if room > 0 else "<b>⛔ 한도 도달 — 메모리 절반 축소 실행</b>"))
    if room <= 0:
        keys.append("loss_limit")   # 결재 #9 표 밖 → 무음 (PB 회신 10/17)
    L.append(semi_line(ev))
    L += band_lines(ev)
    L.append(stress_line(ev))   # 비율만 (금액 금지)
    L += isa_lines(ev)
    for code, px in price_rules.items():
        r = next((x for x in rows if x["s"].upper() == code), None)
        if not r:
            continue
        below = [p for p in r["last2"] if p is not None and p < px]
        tag = "⛔ 2일 연속 이탈 — 실행" if len(below) == 2 else "⚠️ 1일 이탈" if len(below) == 1 else "✅"
        if below:
            keys.append(f"stop{min(len(below), 2)}:{code}")   # stop2 = 결재 #9 '손절 2일'(소리) · stop1 = 무음
        L.append(f"• {r['name']} 기준 {px:,.0f} · 최근 종가 {r['close']:,.0f} ({r['close']/px*100-100:+.1f}%) {tag}")
    L.append("")
    L.append("<b>보유</b>")
    for r in sorted(rows, key=lambda x: -x["v"]):
        drv = f" · 드라이버 {r['drv']:+.2f}" if r["drv"] is not None else ""
        pnl = f" · 손익 {(r['v']/r['c']-1)*100:+.1f}%" if r["c"] else ""
        L.append(f"• {r['name']}{' (ETF)' if r['etf'] else ''}{' [ISA]' if r['book'] == 'isa' else ''} {r['v']/nav*100:.0f}% · 1D {(r['r1'] or 0)*100:+.1f}%{pnl}{drv}")
    try:   # 보유 종목·규칙 관련 이벤트 7일 내
        from .calendar_ev import upcoming
        mine = {r["s"] for r in rows}
        up = [e for e in upcoming(7) if e.get("ticker") in mine or e.get("imp", 1) >= 3]
        if up:
            L.append("")
            L.append("<b>7일 내 이벤트</b>")
            L += [f"• {e['date'][5:]} {'📌 ' if e.get('ticker') in mine else ''}{e['name']}" + (f" — {e['note']}" if e.get("note") else "") for e in up[:8]]
    except Exception:  # noqa: BLE001
        pass
    try:
        ev = json.loads((REPORT_DIR / "events_stats.json").read_text(encoding="utf-8"))
        rec = [e for e in ev.get("events", [])[:5] if not e.get("type", "").startswith("경보")]
        if rec:
            L.append("")
            L.append("<b>최근 이벤트</b> " + " / ".join(f"{e['date'][5:]} {e['market']} {e['type']}" for e in rec[:3]))
    except Exception:  # noqa: BLE001
        pass
    try:
        mv = json.loads((REPORT_DIR / "macro_view.json").read_text(encoding="utf-8"))
        if mv.get("summary"):
            L.append("")
            L.append("<b>매크로</b> " + mv["summary"])
    except Exception:  # noqa: BLE001
        pass
    if miss:
        L.append("")
        L.append("인식 못 한 종목: " + ", ".join(miss))
    return "\n".join(L), keys


def send() -> bool:
    from .alerts import secret_health
    secret_health("pb")   # 시크릿 부재는 조용히 넘기지 않는다(감사 10/17 #26) — 경고 로그 + 신선도 배지 '알림 비활성'
    t, keys = brief_keys()
    if not t:
        log.warning("PB: MY_HOLDINGS 없음 — 아침 점검 비활성 (신선도 health 기록)")
        return False
    from .alerts import silent
    from .report import send_telegram
    # 결재 #9 등급표 경유(감사 M1): 보유 종목 기준가 2일 이탈(stop2:<코드>)만 소리, 나머지(1일 이탈·손실 한도·정보)는 무음.
    # 현재는 defs.TELEGRAM_ALL_SILENT(오너 10/17 전체 무음)가 send_telegram 에서 전부 무음으로 덮는다.
    send_telegram(t, disable_notification=silent(keys))
    log.info("PB 아침 점검 전송")   # 내용은 로그에 남기지 않음
    return True


# ---------------------------------------------------------------- 규칙 집행 맥락 (감사 10/17 #12·#17·#24) — 런타임 전용, 공개 기록 금지
def semi_code(mk: str, code: str) -> bool:
    """종목 코드가 반도체(전기 제외)인가 — detail 파일의 체인으로 판정, 없으면 SEMI_ETFS·US_SEMIS 표."""
    d = _detail(mk, code) or {}
    if not d:
        return code in SEMI_ETFS or code in US_SEMIS
    dv = d.get("drivers") or {}
    look = (d.get("etf") or {}).get("look") or {}
    chain = (dv.get("chain") or {}).get("name") or ("ETF" if d.get("etf") else (d.get("valuation") or {}).get("sector")) or mk
    kind, _ = semi_class(mk, code, d.get("name") or code, chain, bool(d.get("etf")), look.get("chains") or {})
    return kind == "semi"


def risk_ctx(txt: str | None = None, rules_txt: str | None = None) -> dict | None:
    """MY_HOLDINGS(+MY_RULES) → 주문표·감시가 쓰는 판정 묶음. 금액·평단은 반환값 안에서만 쓰고 파일·로그에 남기지 않는다.
    {'var_over': bool|None, 'semi': {코드}, 'backstop': {−20% 아래 보유 코드}, 'floors': {코드: {mk, name, floor, avg}}} — 보유 없으면 None.
    floors = 위성 북 반도체 보유분 평단 × (1 − SEMI_HARD_FLOOR) (사전등록, 10/31 도장 전). 평단 = 종가 × 원가 ÷ 평가액 (현지 통화)."""
    from .defs import POS_BACKSTOP, SEMI_HARD_FLOOR
    txt = os.environ.get("MY_HOLDINGS", "") if txt is None else txt
    rules_txt = os.environ.get("MY_RULES", "") if rules_txt is None else rules_txt
    if not txt.strip():
        return None
    ev = evaluate(txt, rules_txt)
    if not ev:
        return None
    b = ev.get("band") or {}
    v = b.get("var99")
    out = {"var_over": (v["var99"] > b["var_limit"]) if v else None, "semi": set(), "backstop": set(), "floors": {}}
    for r in ev["rows"]:
        if r["semi"]:
            out["semi"].add(r["s"])
        if not r.get("c") or not r.get("v"):
            continue
        if r["v"] / r["c"] - 1 <= -POS_BACKSTOP:
            out["backstop"].add(r["s"])
        if r["semi"] and r["book"] == "sat":
            avg = r["close"] * r["c"] / r["v"]
            out["floors"][r["s"]] = {"mk": r["mk"], "name": r["name"], "avg": avg, "floor": avg * (1 - SEMI_HARD_FLOOR)}
    return out
