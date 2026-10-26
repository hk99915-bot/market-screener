"""보고 상단 형식 공통 모듈 — STANDARD.md 8절 '보고 상단 형식' (What · So What · Now What · 근거 · 원본).

겸이 10/26 "What so what now what 구조 … 형식통일" · 지시서 docs/desk_kb/rounds/2026-10-26/report_format_rollout.md 4절 묶음 A.
- make()       : 스키마 dict 생성 — 각 생성기 JSON 의 `top` 키 (기존 bottom_line·summary·headline 키는 그대로 둔다)
- render_tg3() : 텔레그램 3줄형(①②③ + 원본, HTML 이스케이프) — config.TOPLINE_TG 켜졌을 때만 생성기가 쓴다
- render_md()  : 상단형(①②③ 불릿) 또는 문서형(doc=True, 샘플 v3 순서 What → So What → 근거 → Now What → 원본)
- lint()       : 칸 누락·칸당 1~4줄·합계 ≤10줄·1줄 ≤90자·`습니다`/`요`/`!` 종결 금지·asof·원본 필수 → 위반 문장 목록(빈 목록 = 통과)
- fit()        : 긴 문장을 ` · ` 경계에서 90자 이하 줄로 나눔(생성기 어댑터 공용, screener/topline_from.py)
"""
from __future__ import annotations

import html
import re

FIELDS = ("what", "so_what", "now_what")
LABEL = {"what": "What", "so_what": "So What", "now_what": "Now What"}
MAX_LINE = 90
MAX_TOTAL = 10
MAX_PER = 4
GRADES = ("A", "B", "C", "F", "검증전")
# 명사형 종결 원칙 — 경어·구어 종결만 잡는다('필요'·'주요'·'중요' 같은 명사 '요'는 허용)
_BAD_END = re.compile(r"(습니다|니다|세요|어요|아요|해요|에요|예요|이죠|지요|군요|네요|거든요|는데요|!)\s*[.)]?\s*$")
_ASOF = re.compile(r"^\d{4}-\d{2}-\d{2}( \d{2}:\d{2})?")


def _lines(x) -> list[str]:
    if x is None:
        return []
    if isinstance(x, str):
        x = [x]
    return [str(s).strip() for s in x if s is not None and str(s).strip()]


def fit(text, width: int = MAX_LINE, max_lines: int = 2) -> list[str]:
    """한 문장을 ` · `·` — ` 경계에서 width 이하 줄로 묶는다. max_lines 를 넘는 나머지는 버리고 마지막 줄 끝에 '…'."""
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    if not s:
        return []
    parts = [p for p in re.split(r"(?<= ·) |(?= — )", s) if p]
    out: list[str] = []
    cur = ""
    for p in parts:
        cand = (cur + " " + p.strip()) if cur else p.strip()
        if len(cand) <= width:
            cur = cand
            continue
        if cur:
            out.append(cur)
        cur = p.strip()
        while len(cur) > width:
            out.append(cur[: width - 1].rstrip() + "…")
            cur = ""
    if cur:
        out.append(cur)
    out = [x.rstrip(" ·").strip() for x in out if x.strip(" ·")]
    if len(out) > max_lines:
        out = out[:max_lines]
        last = out[-1]
        out[-1] = (last if len(last) <= width - 1 else last[: width - 2].rstrip()) + "…"
    return out


def make(what, so_what, now_what, evidence=None, src=None, asof=None, grade=None) -> dict:
    """스키마: {"what":[..], "so_what":[..], "now_what":[..], "evidence":[..], "src":[..], "asof":"YYYY-MM-DD HH:MM", "grade":..}.
    빈 칸은 지우지 않고 그대로 둔다 — lint 가 '칸 누락'으로 잡게 (STANDARD 8절: 내용 없으면 `해당 없음(사유)`)."""
    g = grade if grade in GRADES else (None if grade is None else str(grade))
    return {"what": _lines(what), "so_what": _lines(so_what), "now_what": _lines(now_what),
            "evidence": _lines(evidence), "src": _lines(src), "asof": (str(asof).strip() if asof else None), "grade": g}


def _one(top: dict, k: str) -> str:
    out = ""
    for x in _lines((top or {}).get(k)):
        out = x if not out else out + (" " if x.startswith("—") else " · ") + x
    return out


def render_tg3(top: dict) -> str:
    """텔레그램·알림 상단 3줄형: ① What / ② So What / ③ Now What / 원본. HTML parse_mode 용 이스케이프."""
    t = top or {}
    e = lambda s: html.escape(s, quote=False)  # noqa: E731
    L = [f"{'①②③'[i]} {LABEL[k]}: {e(_one(t, k) or '해당 없음(내용 없음)')}" for i, k in enumerate(FIELDS)]
    src = " · ".join(_lines(t.get("src")))
    tail = (f"기준 {t['asof']} · " if t.get("asof") else "") + (f"원본: {src}" if src else "원본 없음")
    L.append(e(tail))
    return "\n".join(L)


def render_md(top: dict, doc: bool = False) -> str:
    """doc=False: 상단형(What·So What·Now What 먼저, 근거·원본 아래). doc=True: 문서형(샘플 v3 순서) — 연구 md 맨 앞 요약 블록."""
    t = top or {}
    head = "> 기준 " + (t.get("asof") or "미확인(asof 없음)") + (f" · 등급 {t['grade']}" if t.get("grade") else "")
    bl = lambda k: [f"- {x}" for x in _lines(t.get(k))] or ["- 해당 없음(내용 없음)"]  # noqa: E731
    ev = [f"- {x}" for x in _lines(t.get("evidence"))]
    src = [f"- {x}" for x in _lines(t.get("src"))] or ["- 원본 없음"]
    if doc:
        L = ["## 요약 (What · So What · Now What)", "", head, "", "**What**", *bl("what"), "", "**So What**", *bl("so_what")]
        if ev:
            L += ["", "**근거 데이터 발췌**", *ev]
        L += ["", "**Now What**", *bl("now_what"), "", "**원본**", *src, "", "---", ""]
        return "\n".join(L) + "\n"
    L = [head, ""]
    for i, k in enumerate(FIELDS):
        xs = _lines(t.get(k)) or ["해당 없음(내용 없음)"]
        L.append(f"{'①②③'[i]} **{LABEL[k]}**: {xs[0]}")
        L += [f"  - {x}" for x in xs[1:]]
    if ev:
        L += ["", "근거: " + " · ".join(_lines(t.get("evidence")))]
    L.append("원본: " + (" · ".join(_lines(t.get("src"))) or "원본 없음"))
    return "\n".join(L) + "\n"


def lint(top) -> list[str]:
    """STANDARD 8절 형식 위반 목록 (빈 목록 = 통과)."""
    if not isinstance(top, dict):
        return ["top 없음"]
    v: list[str] = []
    total = 0
    for k in FIELDS:
        xs = _lines(top.get(k))
        if not xs:
            v.append(f"{LABEL[k]} 칸 누락")
            continue
        if len(xs) > MAX_PER:
            v.append(f"{LABEL[k]} {len(xs)}줄 > {MAX_PER}")
        total += len(xs)
        for x in xs:
            if len(x) > MAX_LINE:
                v.append(f"{LABEL[k]} 1줄 {len(x)}자 > {MAX_LINE}: {x[:30]}…")
            if _BAD_END.search(x):
                v.append(f"{LABEL[k]} 종결어미 위반(명사형 종결): …{x[-15:]}")
    if total > MAX_TOTAL:
        v.append(f"상단 합계 {total}줄 > {MAX_TOTAL}")
    if not top.get("asof") or not _ASOF.match(str(top.get("asof"))):
        v.append("asof(기준 시각) 없음 또는 형식 오류")
    if not _lines(top.get("src")):
        v.append("원본 링크 없음")
    return v
