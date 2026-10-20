"""리포트 종류 분류기 (순수 함수 — 네트워크·파일 없음).

kind ∈ KINDS = 종목 · 섹터 · 전략 · 매크로 · 채권 · 외환 · 파생 · 인뎁스
  1차: 출처 카테고리 (네이버 리서치 목록 이름·한경 컨센서스 탭 이름 등)
  2차: 제목(+선택 본문) 키워드 — 인뎁스 > 파생 > 외환 순으로 덮어쓰고, 카테고리가 없으면 키워드로 정한다.
반환: (kind, kind_reason) — reason 은 '어떤 근거로 정했나' 한 줄 (예: "cat:산업분석→섹터", "kw:환율→외환").

누가 쓰나: screener/research_views.py(네이버·한경 비종목 리포트), 이후 노트북 텔레그램 PDF 수집기
(입력: title, source_category=None, text=None, pages=None). 다른 모듈을 import 하지 않는다.
"""
from __future__ import annotations

import re

KINDS = ("종목", "섹터", "전략", "매크로", "채권", "외환", "파생", "인뎁스")

# 1차 — 출처 카테고리 이름(부분 일치, 대소문자 무시). 위에서부터 먼저 맞는 것.
CATEGORY_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"종목|기업|company", re.I), "종목"),
    (re.compile(r"산업|업종|industry|sector", re.I), "섹터"),
    (re.compile(r"채권|debenture|bond|fixed", re.I), "채권"),
    (re.compile(r"경제|economy|macro", re.I), "매크로"),
    (re.compile(r"외환|환율|\bfx\b|currency", re.I), "외환"),
    (re.compile(r"퀀트|펀드|해외|quant|fund", re.I), "전략"),   # 한경 '[파생]퀀트·펀드·해외' — 사이트는 파생 묶음이지만 내용은 전략
    (re.compile(r"파생|derivative", re.I), "파생"),
    (re.compile(r"시황|시장|투자정보|전략|market|invest|strategy", re.I), "전략"),
]

# 2차 — 제목·본문 키워드
KW_INDEPTH = re.compile(r"심층|인뎁스|deep[\s\-]*dive|in[\s\-]*depth|\bdeep\b|장기\s*전망\s*보고서", re.I)
KW_DERIV_STRONG = re.compile(r"파생|옵션|\bELS\b|\bELW\b|\bVIX\b|베이시스|쿼드러플|네\s*마녀|변동성\s*지수|선물\s*옵션", re.I)
KW_DERIV_WEAK = re.compile(r"선물|만기|변동성", re.I)        # 채권·섹터 리포트에도 흔해 카테고리 없음/전략일 때만
KW_FX = re.compile(r"환율|달러|원화|원/달러|엔화|위안|외환|\bFX\b|forex|\bDXY\b", re.I)
KW_BOND = re.compile(r"채권|국고채|국채|회사채|크레딧|credit|듀레이션|금리\s*전망|\bbond", re.I)
KW_MACRO = re.compile(r"경제|경기|GDP|물가|CPI|PCE|고용|FOMC|연준|\bFed\b|금통위|성장률|macro|매크로", re.I)
KW_SECTOR = re.compile(r"산업|업종|섹터|sector|industry", re.I)
KW_STRATEGY = re.compile(r"전략|시황|strategy|주간|weekly|포트폴리오|투자\s*아이디어|코스피\s*전망", re.I)
KW_STOCK = re.compile(r"\(\d{6}\)|\b\d{6}\b|목표주가")
INDEPTH_PAGES = 30          # 장문(쪽수) 기준 — 쪽수를 아는 입력(PDF)만


def _cat_kind(cat: str | None) -> str | None:
    if not cat:
        return None
    for rx, k in CATEGORY_RULES:
        if rx.search(cat):
            return k
    return None


def classify(title: str, source_category: str | None = None, text: str | None = None,
             pages: int | None = None) -> tuple[str, str]:
    """리포트 1건의 kind 와 근거. 순수 함수 — 같은 입력이면 같은 출력."""
    title = title or ""
    blob = title + " " + (text or "")[:2000]
    base = _cat_kind(source_category)
    why = f"cat:{source_category}→{base}" if base else ""

    m = KW_INDEPTH.search(title)
    if m:
        return "인뎁스", f"kw:{m.group(0).strip()}→인뎁스" + (f" ({why})" if why else "")
    if pages is not None and pages >= INDEPTH_PAGES:
        return "인뎁스", f"pages:{pages}≥{INDEPTH_PAGES}→인뎁스" + (f" ({why})" if why else "")
    if base == "종목":
        return "종목", why
    if base in (None, "전략", "매크로", "채권", "파생", "외환"):
        m = KW_DERIV_STRONG.search(title) or (KW_DERIV_WEAK.search(title) if base in (None, "전략", "파생") else None)
        if m:
            return "파생", f"kw:{m.group(0).strip()}→파생" + (f" ({why})" if why else "")
    if base in (None, "전략", "매크로", "외환"):
        m = KW_FX.search(title)
        if m:
            return "외환", f"kw:{m.group(0).strip()}→외환" + (f" ({why})" if why else "")
    if base:
        return base, why
    # 카테고리 없음 → 키워드(제목 우선, 다음 본문 앞부분)
    for src, s in (("title", title), ("text", blob)):
        for rx, k in ((KW_STOCK, "종목"), (KW_BOND, "채권"), (KW_SECTOR, "섹터"), (KW_MACRO, "매크로"), (KW_STRATEGY, "전략")):
            m = rx.search(s)
            if m:
                return k, f"kw[{src}]:{m.group(0).strip()}→{k}"
    return "전략", "default:근거 없음→전략"
