#!/usr/bin/env python3
"""문헌 계층 CI 가드 (4단계) — 네트워크 없이 캐시·장부만 읽어 서지·철회·형식·길이를 본다.

  python3 scripts/paper_lit_check.py            # 사람용 출력
  python3 scripts/paper_lit_check.py --ci       # GitHub Actions 주석(::error/::warning)
  python3 scripts/paper_lit_check.py --root /tmp/x --ci   # 시험용 루트

검사(근거 `market-screener-research/PAPER_RESEARCH_AND_AUTO_UPDATE_PLAN.md` §3-6)
1. `content/papers/index.json` — 필수 필드·키 유일성·점수↔상태 일치·철회 항목은 반드시 rejected.
   (제목만 주는 소스는 `abstract_state="missing"` 로 두고 점수 <40 이라도 hold 를 허용 — 폐기 대신 재평가.)
2. `docs/desk_kb/lit/*.md` — 카드마다 출처·결론·한계·적용·뒤집힐 조건 5칸(누락은 ::warning), 카드 ≤6줄,
   인용한 DOI/arXiv 가 색인에 철회로 있으면 ::error(항목 자동 보류), `[확인 필요]` 에 기한이 없으면 ::warning,
   `적용:` 이 가리키는 저장소 경로가 없으면 ::error.
3. `content/papers/citation_cache.json` — 있으면 제목 유사도 ≥0.90 대조(색인 항목의 서지 실재). 없으면 건너뛴다(2주차 백필 전).
4. `reports/papers/digest_*.md` — 60줄 상한(::warning).

`slop_audit.py` 는 건드리지 않는다 — 여기서 보는 것은 lit 파일과 논문 장부뿐이다.
종료 코드: ::error 1건 이상 1, 그 밖 0.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX_REL = "content/papers/index.json"
CACHE_REL = "content/papers/citation_cache.json"
LIT_REL = "docs/desk_kb/lit"
CARD_MAX_LINES = 6
DIGEST_MAX_LINES = 60
LIT_MAX_LINES = 200
TITLE_SIM_MIN = 0.90
STATUSES = {"summarize", "hold", "rejected"}
REQUIRED_ITEM = ("key", "source", "title", "authors", "url", "fetched_at", "status", "score", "reasons", "withdraw_flag")
FIELDS = ("결론", "한계", "적용", "뒤집힐 조건")

PENDING_RE = re.compile(r"\[확인\s*필요(:?)([^\]]*)\]")
DATE_RE = re.compile(r"20\d\d-\d\d-\d\d")
DOI_RE = re.compile(r"10\.\d{4,9}/[^\s·,;)\]]+")
ARXIV_RE = re.compile(r"(?:arxiv[:\s]*)(\d{4}\.\d{4,5})", re.I)
SOURCE_HINT_RE = re.compile(r"doi|arxiv|https?://|NBER|FEDS|BIS|RePEc|KCMI|한국은행|Crossref|JEL|NBER|SSRN", re.I)
PATH_RE = re.compile(r"(?<![\w/.:-])((?:[\w.-]+/)+[\w.-]+\.(?:md|py|json|csv|yml|yaml|parquet))")


def _finding(level: str, rel: str, line: int | None, msg: str) -> dict:
    return {"level": level, "file": rel, "line": line, "msg": msg}


# ── 1. 색인 장부 ────────────────────────────────────────────────────
def check_index(root: Path) -> tuple[list[dict], dict]:
    out: list[dict] = []
    path = root / INDEX_REL
    if not path.exists():
        out.append(_finding("warning", INDEX_REL, None, "색인 없음 — 1주차 수집(papers_ingest.py)을 아직 돌리지 않았다"))
        return out, {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [_finding("error", INDEX_REL, None, f"JSON 해석 실패: {exc}")], {}
    for k in ("schema_version", "rules_version", "papers"):
        if k not in doc:
            out.append(_finding("error", INDEX_REL, None, f"필수 키 없음: {k}"))
    if not doc.get("rules_version"):
        out.append(_finding("error", INDEX_REL, None, "rules_version 없음 — 점수 재현 불가"))
    papers = doc.get("papers") or []
    seen: dict[str, int] = {}
    for i, p in enumerate(papers):
        where = f"papers[{i}] {p.get('key') or p.get('title') or '?'}"
        for f in REQUIRED_ITEM:
            if f not in p:
                out.append(_finding("error", INDEX_REL, None, f"{where}: 필수 필드 없음 {f}"))
        key = p.get("key")
        if not key:
            continue
        if key in seen:
            out.append(_finding("error", INDEX_REL, None, f"{where}: 키 중복 {key} (papers[{seen[key]}])"))
        seen[key] = i
        title = (p.get("title") or "").strip()
        if not title:
            out.append(_finding("error", INDEX_REL, None, f"{where}: 제목 없음"))
        if not str(p.get("url") or "").startswith("http"):
            out.append(_finding("error", INDEX_REL, None, f"{where}: url 이 http(s) 아님"))
        status, score = p.get("status"), p.get("score")
        if status not in STATUSES:
            out.append(_finding("error", INDEX_REL, None, f"{where}: status 값 이상 {status!r}"))
            continue
        if not isinstance(score, int):
            out.append(_finding("error", INDEX_REL, None, f"{where}: score 가 정수가 아님 {score!r}"))
            continue
        if not p.get("reasons"):
            out.append(_finding("error", INDEX_REL, None, f"{where}: reasons 비어 있음(폐기 사유 재현 불가)"))
        if p.get("withdraw_flag"):
            if status != "rejected":
                out.append(_finding("error", INDEX_REL, None, f"{where}: 철회 플래그가 있는데 status={status} (폐기 필수)"))
            if score > -100:
                out.append(_finding("error", INDEX_REL, None, f"{where}: 철회 항목 score {score} — −100 이하 고정 규칙 위반"))
        else:
            want = "summarize" if score >= 60 else "hold" if score >= 40 else "rejected"
            text_only_hold = status == "hold" and p.get("abstract_state") == "missing" and score < 60
            if status != want and not text_only_hold:
                out.append(_finding("error", INDEX_REL, None, f"{where}: status={status} ≠ 점수 규칙({want})"))
    return out, doc


# ── 2. lit KB 카드 ──────────────────────────────────────────────────
def parse_cards(text: str) -> list[dict]:
    """'- **…' 로 시작하는 카드 = 그 줄 + 뒤따르는 들여쓴 줄. 빈 줄·비들여쓴 줄에서 끊는다."""
    cards, cur = [], None
    for i, ln in enumerate(text.splitlines(), 1):
        if ln.startswith("- **") or ln.startswith("-**"):
            if cur:
                cards.append(cur)
            cur = {"line": i, "lines": [ln]}
        elif cur is not None:
            if not ln.strip():
                cards.append(cur)
                cur = None
            elif ln.startswith((" ", "\t")):
                cur["lines"].append(ln)
            else:
                cards.append(cur)
                cur = None
    if cur:
        cards.append(cur)
    for c in cards:
        c["text"] = "\n".join(c["lines"])
    return cards


def check_lit(root: Path, index_doc: dict) -> list[dict]:
    out: list[dict] = []
    d = root / LIT_REL
    if not d.exists():
        return out
    withdrawn: dict[str, str] = {}
    known_titles: dict[str, str] = {}
    for p in index_doc.get("papers") or []:
        if p.get("doi"):
            if p.get("withdraw_flag"):
                withdrawn[p["doi"].lower()] = p.get("withdraw_reason") or "철회"
            known_titles[p["doi"].lower()] = p.get("title") or ""
        if p.get("arxiv_id"):
            if p.get("withdraw_flag"):
                withdrawn[("arxiv:" + p["arxiv_id"]).lower()] = p.get("withdraw_reason") or "철회"
            known_titles[("arxiv:" + p["arxiv_id"]).lower()] = p.get("title") or ""
    for path in sorted(d.glob("*.md")):
        rel = str(path.relative_to(root))
        if path.name.upper().startswith("README"):
            continue
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        if len(lines) > LIT_MAX_LINES:
            out.append(_finding("warning", rel, None, f"{len(lines)}줄 — 파일 상한 {LIT_MAX_LINES}줄 초과(항목을 다른 파일로)"))
        for card in parse_cards(text):
            first = card["lines"][0]
            head = f"{rel}:{card['line']}"
            if len(card["lines"]) > CARD_MAX_LINES:
                out.append(_finding("warning", rel, card["line"], f"카드 {len(card['lines'])}줄 — 상한 {CARD_MAX_LINES}줄 ({head})"))
            missing = [f for f in FIELDS if f"{f}:" not in card["text"]]
            if missing:
                out.append(_finding("warning", rel, card["line"], f"{head}: 필수 칸 누락 {', '.join(missing)}"))
            if not SOURCE_HINT_RE.search(first):
                out.append(_finding("warning", rel, card["line"], f"{head}: 출처(DOI·arXiv·URL·기관명) 없음"))
            for m in PENDING_RE.finditer(card["text"]):
                if not DATE_RE.search(m.group(2) or ""):
                    out.append(_finding("warning", rel, card["line"], f"{head}: 기한 없는 '[확인 필요]' — STANDARD §1 위반"))
            for doi in DOI_RE.findall(first):
                w = withdrawn.get(doi.lower().rstrip("."))
                if w:
                    out.append(_finding("error", rel, card["line"],
                                        f"{head}: 철회·정정 논문 인용 DOI {doi} ({w}) — 항목 자동 보류 필요"))
            for aid in ARXIV_RE.findall(first):
                w = withdrawn.get(f"arxiv:{aid}".lower())
                if w:
                    out.append(_finding("error", rel, card["line"],
                                        f"{head}: 철회·정정 논문 인용 arXiv {aid} ({w}) — 항목 자동 보류 필요"))
            for app in [ln for ln in card["lines"] if "적용:" in ln]:
                for pth in PATH_RE.findall(app):
                    if "*" in pth:
                        continue
                    if not (root / pth).exists():
                        out.append(_finding("error", rel, card["line"], f"{head}: 적용 경로 없음 {pth}"))
    return out


# ── 3. 서지 캐시 ────────────────────────────────────────────────────
def check_citations(root: Path, index_doc: dict) -> list[dict]:
    out: list[dict] = []
    path = root / CACHE_REL
    if not path.exists():
        return out
    try:
        cache = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [_finding("error", CACHE_REL, None, f"JSON 해석 실패: {exc}")]
    entries = cache.get("entries") if isinstance(cache, dict) else None
    entries = entries if isinstance(entries, dict) else cache if isinstance(cache, dict) else {}
    for p in index_doc.get("papers") or []:
        doi = (p.get("doi") or "").lower()
        if not doi:
            continue
        got = entries.get(doi) or entries.get("doi:" + doi)
        if not got:
            out.append(_finding("warning", CACHE_REL, None, f"서지 캐시 미해석 DOI {doi} — 2주차 백필 대상(색인 항목)"))
            continue
        cache_title = got.get("title") if isinstance(got, dict) else None
        if cache_title:
            sim = SequenceMatcher(None, (p.get("title") or "").lower(), cache_title.lower()).ratio()
            if sim < TITLE_SIM_MIN:
                out.append(_finding("error", CACHE_REL, None,
                                    f"{doi}: 캐시 제목 유사도 {sim:.2f} < {TITLE_SIM_MIN} — 서지 불일치"))
    return out


# ── 4. 다이제스트 길이 ──────────────────────────────────────────────
def check_digests(root: Path) -> list[dict]:
    out: list[dict] = []
    d = root / "reports" / "papers"
    if not d.exists():
        return out
    for path in sorted(d.glob("digest_*.md")):
        n = len(path.read_text(encoding="utf-8").splitlines())
        if n > DIGEST_MAX_LINES:
            out.append(_finding("warning", str(path.relative_to(root)), None,
                                f"{n}줄 — 상한 {DIGEST_MAX_LINES}줄(STANDARD §8)"))
    return out


def check(root: Path = ROOT) -> list[dict]:
    idx_findings, index_doc = check_index(root)
    return idx_findings + check_lit(root, index_doc) + check_citations(root, index_doc) + check_digests(root)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="lit KB · 논문 장부 CI 가드")
    ap.add_argument("--ci", action="store_true", help="GitHub Actions 주석 형식(::error/::warning)")
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--today", default=date.today().isoformat())
    a = ap.parse_args(argv)
    findings = check(Path(a.root))
    errs = [f for f in findings if f["level"] == "error"]
    warns = [f for f in findings if f["level"] == "warning"]
    for f in findings:
        loc = f"{f['file']}:{f['line']}" if f["line"] else f["file"]
        if a.ci:
            print(f"::{f['level']} file={f['file']}" + (f",line={f['line']}" if f["line"] else "") + f"::{f['msg']}")
        else:
            print(f"{'ERROR' if f['level'] == 'error' else 'WARN'} {loc} {f['msg']}")
    idx = Path(a.root) / INDEX_REL
    n_papers = 0
    if idx.exists():
        try:
            n_papers = len(json.loads(idx.read_text(encoding="utf-8")).get("papers") or [])
        except json.JSONDecodeError:
            n_papers = -1
    print(f"{'FAIL' if errs else 'ok'}: 논문 장부 {n_papers}건 · error {len(errs)} · warning {len(warns)} · 기준일 {a.today}")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
