"""섹터 체계 단일 원천 (보드 toss-sectors, 2026-10-21 겸이 승인 🌙).

두 체계를 용도별로 나눈다:
- **공식 1종목1섹터** — 비중 한도·노출 계산용. 미장 = GICS(S&P 구성 CSV 의 GICS Sector·Sub-Industry), 국장 = WICS(universe/kr_wics.csv).
  WICS 파일이 없으면 KRX 업종(universe/kr_sector.csv)으로 대체하고 출처를 'KRX업종(WICS 대체)'로 표시한다.
- **토스 섹터(3단계, 다중 소속)** — 테마·순환매·히트맵용. toss-live 브랜치 sectors.json(노트북 수집, tools/toss_md/publish.py).

전환 스위치: OFFICIAL_LIMITS. False 동안 비중 한도 판정은 예전(체인 기반 semi_class) 그대로이고,
새 기준은 '병행 계산 필드'(pb.evaluate 의 semi_ex_new·sector_w_new 등)로만 나간다.
True 로 바꾸는 조건: 10/21 07:00 이후 + 겸이 확인(보드 toss-sectors). 롤백 = False.
**2026-10-24 07:10 KST 전환(True)** — 겸이 결재 appr-toss-sectors-switch(10/24 07시대 "싹다 ㄱㄱ"), req-dev-6f153023.
전환 전 차이(10/23 detail 기준): 국장 비ETF 1,250 중 반도체 편입 +111·제외 −1, 미장 559 중 +3·−5, 보유 기준 반도체 비중 21.9%→15.4%(밴드 판정 불변) — docs/sectors_switch_2026-10-24.md.
"""
from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path

from .config import UNIVERSE_DIR

OFFICIAL_LIMITS = True   # 전환 스위치 — True(10/24~) = 반도체 한도 판정이 공식 섹터(GICS/WICS) 기준. 롤백 = False

# GICS 11 섹터 → 화면·파일에서 쓰는 한글 짧은 이름 (universe/us_sector.csv 가 이미 이 이름을 쓴다 — valuation.US_FIN_SECTORS="금융")
GICS_KO = {"Information Technology": "IT", "Health Care": "헬스케어", "Financials": "금융", "Consumer Discretionary": "경기소비재",
           "Communication Services": "커뮤니케이션", "Industrials": "산업재", "Consumer Staples": "필수소비재", "Energy": "에너지",
           "Utilities": "유틸리티", "Real Estate": "부동산", "Materials": "소재"}
# 야후 sector 이름 → GICS 섹터 (야후는 GICS 와 이름이 다르다: Technology ≠ Information Technology 등).
# 야후 펀드 sector_weightings 의 소문자 키(technology, realestate …)도 같이 받는다.
YAHOO_TO_GICS = {
    "Technology": "Information Technology", "Healthcare": "Health Care", "Financial Services": "Financials",
    "Consumer Cyclical": "Consumer Discretionary", "Consumer Defensive": "Consumer Staples",
    "Communication Services": "Communication Services", "Industrials": "Industrials", "Energy": "Energy",
    "Utilities": "Utilities", "Real Estate": "Real Estate", "Basic Materials": "Materials",
    "technology": "Information Technology", "healthcare": "Health Care", "financial_services": "Financials",
    "consumer_cyclical": "Consumer Discretionary", "consumer_defensive": "Consumer Staples",
    "communication_services": "Communication Services", "industrials": "Industrials", "energy": "Energy",
    "utilities": "Utilities", "realestate": "Real Estate", "basic_materials": "Materials",
}
# GICS 산업그룹 4530 '반도체와 반도체장비' = 하위산업 두 개뿐 (GICS 2023 구조)
GICS_SEMI_SUBS = {"Semiconductors", "Semiconductor Materials & Equipment"}
WICS_SEMI_L2 = {"반도체와반도체장비", "반도체와 반도체장비"}
# S&P500 밖 NDX 종목(구성 CSV 에 없음) — 수동 GICS. [확인 필요: 각 사 IR·S&P/MSCI 분류표와 대조, 10/31까지]
# 확신 못 하는 종목(CRWV·MSTR·NBIS 등)은 일부러 비워 둔다 → '분류 없음'(기존 판정 사용).
US_MANUAL = {"ALAB": ("Information Technology", "Semiconductors"), "ARM": ("Information Technology", "Semiconductors"),
             "ASML": ("Information Technology", "Semiconductor Materials & Equipment"),
             "ALNY": ("Health Care", "Biotechnology"), "CCEP": ("Consumer Staples", "Soft Drinks & Non-alcoholic Beverages"),
             "FER": ("Industrials", "Construction & Engineering"), "MELI": ("Consumer Discretionary", "Broadline Retail"),
             "PDD": ("Consumer Discretionary", "Broadline Retail"), "RKLB": ("Industrials", "Aerospace & Defense"),
             "SHOP": ("Information Technology", "Application Software"), "TRI": ("Industrials", "Research & Consulting Services")}


def gics_ko(name: str | None) -> str | None:
    """GICS 영문·야후 이름·한글 짧은 이름 무엇이 와도 GICS 11 한글 짧은 이름으로. 모르면 None."""
    if not name:
        return None
    n = str(name).strip()
    if n in GICS_KO.values():
        return n
    if n in GICS_KO:
        return GICS_KO[n]
    g = YAHOO_TO_GICS.get(n) or YAHOO_TO_GICS.get(n.lower().replace(" ", "_"))
    return GICS_KO.get(g) if g else None


def _read(p: Path) -> list[dict]:
    if not p.exists():
        return []
    with p.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


@lru_cache(maxsize=1)
def _us() -> dict[str, dict]:
    out = {}
    for r in _read(UNIVERSE_DIR / "us_sector.csv"):
        out[r["yf"]] = {"l1": gics_ko(r.get("sector")), "sub": r.get("gics_sub") or None, "src": "GICS(S&P 구성)"}
    for t, (sec, sub) in US_MANUAL.items():
        out.setdefault(t, {"l1": GICS_KO[sec], "sub": sub, "src": "GICS(수동)"})
    return out


@lru_cache(maxsize=1)
def _kr() -> tuple[dict[str, dict], str]:
    w = _read(UNIVERSE_DIR / "kr_wics.csv")
    if w:
        return {r["code"].zfill(6): {"l1": r.get("wics_l1") or None, "l2": r.get("wics_l2") or None, "asof": r.get("asof")} for r in w}, "WICS"
    k = _read(UNIVERSE_DIR / "kr_sector.csv")
    return {r["code"].zfill(6): {"l1": r.get("sector") or None, "l2": None} for r in k}, "KRX업종(WICS 대체)"


def clear_cache() -> None:
    _us.cache_clear()
    _kr.cache_clear()


def official(mk: str, code: str) -> dict:
    """공식 1종목1섹터 → {sector, group, src}. 모르면 sector None. group = 미장 GICS 하위산업 / 국장 WICS 중분류."""
    if mk == "US":
        r = _us().get(code)
        return {"sector": r["l1"], "group": r["sub"], "src": r["src"]} if r else {"sector": None, "group": None, "src": "없음"}
    m, src = _kr()
    r = m.get(str(code).zfill(6))
    return {"sector": r["l1"], "group": r.get("l2"), "src": src} if r else {"sector": None, "group": None, "src": "없음"}


def semi_official(mk: str, code: str) -> bool | None:
    """공식 섹터 기준 반도체(GICS 4530 / WICS 반도체와반도체장비)인가. 판정 불가(분류 없음·KRX 대체)면 None."""
    o = official(mk, code)
    if mk == "US":
        return (o["group"] in GICS_SEMI_SUBS) if o["group"] else None
    if o["src"] != "WICS" or not o["group"]:
        return None   # KRX 업종은 '전기·전자' 401종목이 한 덩어리라 반도체를 가를 수 없다
    return o["group"].replace(" ", "") in {x.replace(" ", "") for x in WICS_SEMI_L2}
