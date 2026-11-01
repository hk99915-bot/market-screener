"""리포트 서고(RESEARCH › 서고) 색인 — 흩어진 분석 문서를 reports/library.json 한 장으로 (req-dev-16bbc8e5 ①, 11/1 겸이
「분석 리포트들 쌓인거 좀 잘 볼수있게 만드는법 없나」 + 「퀀트 전략보고서들도」).

  python3 scripts/build_library.py            # reports/library.json 갱신
  python3 scripts/build_library.py --check    # 쓰지 않고 건수만

대상 (공개 저장소 문서만 — 비공개 pb-private 은 범위 밖, 요청 ②):
  docs/desk_kb/rounds/<날짜>/*.md · docs/desk_kb/rounds/<날짜>-<종류>-*.md · docs/desk_kb/rounds/<날짜>.md   → cat=round
  reports/studies/*.md + md 없는 *.json(json-only 연구)                                                     → cat=study (퀀트 연구)
  docs/valuation_notes/*.md → cat=valuation · docs/peer_reviews/*.md → cat=peer

항목: path·date·desk·desk_ko·cat·topic·title(첫 # 제목)·summary(What 첫 줄 또는 첫 문단 120자)·grade(A/B/C/F)·size
  + 연구 묶음: series(같은 연구 줄기 키)·stage(0 사전등록 → 1 본연구 → 2 후속 라운드 → 3 재현·검증)
  + json-only 연구: body_md(키 표 마크다운, 화면에서 그대로 렌더) · json(원본 경로)
본문은 묶지 않는다(전체 md ≈ 4MB) — 화면이 path 로 그때그때 읽는다(Pages = 정적 파일, GAS = Code.gs getLibraryDoc 허용 목록).
최신순(date 내림차순, 같은 날은 path) 정렬. 개인 금액·보유는 원문이 공개 저장소 규칙(비율만)을 이미 따른다 — 여기서 새 숫자를 만들지 않는다.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from screener.redact import AMOUNT_RX, personal_amount_hits  # noqa: E402  (공개 저장소 개인 금액 가드 — prepush 4a 와 같은 판정)

OUT = ROOT / "reports" / "library.json"
KST = timezone(timedelta(hours=9))
SUMMARY_MAX = 120
BODY_ROWS_MAX = 60

# 파일명 접두(영문 키) → 화면 이름. round_collect.DESKS 와 같은 키 + 서고에만 쓰는 묶음(메신저·라운드 종합·오너 자료).
DESK_KO = {
    "pb": "PB", "quant": "퀀트", "bonds": "채권", "frm": "리스크", "backtest": "백테스트", "life": "LIFE",
    "alloc": "자산배분", "macro": "매크로", "ops": "운영", "pm": "PM", "health": "헬스", "cio": "CIO",
    "derivs": "파생", "analyst": "애널", "dev": "개발", "edu": "교육", "data": "데이터", "verify": "검증",
    "eval": "평가", "peer": "피어리뷰", "behavior": "행동", "audit": "감사", "maint": "유지보수", "uxui": "UXUI",
    "realestate": "부동산", "scribe": "기록", "household": "내무", "compliance": "컴플라이언스",
    "posrisk": "포지션리스크", "front": "프론트", "hf": "HF",
    "msg": "사내톡", "round": "라운드 종합", "owner": "오너 자료", "etc": "기타",
}
# 접두 별칭 (파일명에 쓰인 줄임말 → 키)
ALIAS = {"re": "realestate", "brief": "pb", "allocation": "alloc", "valuation": "analyst", "bond": "bonds", "deriv": "derivs"}
# '<행사>_<데스크>' 꼴(okr_edu·event_cio·review_verify) — 첫 토큰이 행사면 두 번째 토큰이 데스크, 행사는 topic
EVENT_PREFIX = {"okr", "event", "review"}
# 데스크가 아닌 운영 문서 접두 → 데스크 키
MISC_PREFIX = {"owner": "owner", "agenda": "pb", "request": "pb", "report": "pb", "postmortem": "pb", "s1": "frm", "research": "derivs"}
CAT_KO = {"round": "라운드", "study": "퀀트 연구", "valuation": "밸류에이션 노트", "peer": "피어리뷰"}

DATE_RE = re.compile(r"(20\d\d-\d\d-\d\d)")
GRADE_RE = re.compile(r"등급\s*[:：]?\s*\**\s*([ABCF])(?![A-Za-z0-9])")
WHAT_INLINE = re.compile(r"^\s*(?:[-*]\s*)?\**What\**\s*\**\s*[:：]\s*\**\s*(.+)$")
META_LINE = re.compile(r"^((자료|출처|발행|대상|요청|기준|근거|작성|상태|범위|입력|데이터|원본)\s*[:：]|연구 전용)")   # 머리말·면책 줄
WHAT_HEAD = re.compile(r"^\s*(?:#{1,6}\s*)?\**What\**\s*$")


def desk_of_name(stem: str) -> tuple[str, str]:
    """파일 이름(확장자·날짜 뺀) → (데스크 키, 주제). 예: macro_gold → (macro, gold) · okr_edu → (edu, okr) · hf-1155 → (hf, 1155)."""
    toks = [t for t in re.split(r"[_\-]", stem) if t]
    if not toks:
        return "etc", ""
    a = ALIAS.get(toks[0], toks[0])
    if a in EVENT_PREFIX and len(toks) > 1 and ALIAS.get(toks[1], toks[1]) in DESK_KO:
        return ALIAS.get(toks[1], toks[1]), "_".join([toks[0]] + toks[2:])
    if a in MISC_PREFIX:
        return MISC_PREFIX[a], "_".join(toks)
    if a in DESK_KO:
        return a, "_".join(toks[1:])
    return "etc", "_".join(toks)


def study_desk(stem: str) -> str:
    """reports/studies 파일 → 데스크. 접두가 다른 데스크(hf_·bonds_·frm_·re_·cio_·derivs_)면 그 데스크, 재현·검증은 검증, 나머지 퀀트."""
    s = re.sub(r"^20\d\d-\d\d-\d\d_", "", stem)
    if s.startswith(("replication_", "verify_")):
        return "verify"
    k, _ = desk_of_name(s)
    return k if k in {"hf", "bonds", "frm", "realestate", "cio", "derivs", "macro", "analyst"} else "quant"


# ── 연구 묶음 (퀀트 10/31 PB 추가): X ↔ X_preregistration ↔ 날짜_X_round2 ↔ replication_X ↔ verify_X
_SER_PRE = re.compile(r"^(replication|verify)_")
_SER_SUF = re.compile(r"_(preregistration|prereg|round\d+|verify|rerun\w*|screen|forward|calib|spec)$")


def series_of(stem: str) -> tuple[str, int]:
    """파일 stem → (묶음 키, 단계). 단계 0 사전등록 · 1 본연구 · 2 후속 라운드·재실행 · 3 재현·검증."""
    s = re.sub(r"^20\d\d-\d\d-\d\d_", "", stem)
    stage = 1
    m = _SER_PRE.match(s)
    if m:
        s, stage = s[m.end():], 3
    while True:
        m = _SER_SUF.search(s)
        if not m:
            break
        suf = m.group(1)
        s = s[:m.start()]
        if suf.startswith("prereg"):
            stage = 0
        elif suf == "verify":
            stage = 3
        elif suf.startswith(("round", "rerun")) and stage == 1:
            stage = 2
    return s, stage


def strip_md(t: str) -> str:
    t = re.sub(r"`([^`]*)`", r"\1", t)
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"\*\*|__|~~", "", t)
    t = re.sub(r"(?<!\w)[*_](\S[^*_]*)[*_](?!\w)", r"\1", t)
    return re.sub(r"\s+", " ", t).strip()


def cut(t: str, n: int = SUMMARY_MAX) -> str:
    t = strip_md(t)
    return t if len(t) <= n else t[: n - 1].rstrip() + "…"


def md_title(lines: list[str]) -> str:
    for ln in lines[:40]:
        m = re.match(r"^#\s+(.+)", ln)
        if m:
            return strip_md(m.group(1))
    for ln in lines[:40]:
        m = re.match(r"^#{2,6}\s+(.+)", ln)
        if m:
            return strip_md(m.group(1))
    return ""


def md_summary(lines: list[str]) -> str:
    """'What' 첫 줄(인라인 `- **What:** …` · 머리 `## What`/`**What**` 다음 첫 내용 줄) → 없으면 첫 문단 첫 줄."""
    for i, ln in enumerate(lines):
        m = WHAT_INLINE.match(ln)
        if m and m.group(1).strip():
            return cut(m.group(1))
        if WHAT_HEAD.match(ln):
            for nx in lines[i + 1:i + 8]:
                if nx.strip() and not nx.lstrip().startswith(("#", "|", "---")):
                    return cut(re.sub(r"^\s*(?:[-*]\s+|>\s*|\d+[.)]\s+)", "", nx))
    first = ""
    for ln in lines:
        s = ln.strip()
        if not s or s.startswith(("#", "|", "---", "```", "<!--")):
            continue
        s = re.sub(r"^(?:[-*]\s+|>\s*|\d+[.)]\s+)", "", s).lstrip("> ").strip()
        if len(strip_md(s)) < 8:
            continue
        if META_LINE.match(strip_md(s)):   # '자료:'·'발행:' 같은 머리말 줄은 건너뛰고 본문 첫 줄 — 없으면 머리말이라도
            first = first or s
            continue
        return cut(s)
    return cut(first) if first else ""


def md_grade(text: str) -> str:
    m = GRADE_RE.search(text)
    return m.group(1) if m else ""


_GIT_DATES: dict[str, str] | None = None
_BASE = ROOT   # build(root) 가 바꾼다 — 항목 path 는 이 기준 상대 경로


def git_dates(root: Path = ROOT) -> dict[str, str]:
    """경로 → 마지막 커밋일(YYYY-MM-DD). git log 한 번으로 (파일마다 부르면 15초). 얕은 체크아웃·git 없음이면 빈 표."""
    global _GIT_DATES
    if _GIT_DATES is None:
        _GIT_DATES = {}
        try:
            r = subprocess.run(["git", "log", "--format=@%cs", "--name-only", "--", "reports/studies", "docs/valuation_notes",
                                "docs/peer_reviews"], cwd=root, capture_output=True, text=True, timeout=60)
            cur = ""
            for ln in r.stdout.splitlines() if r.returncode == 0 else []:
                if ln.startswith("@"):
                    cur = ln[1:11]
                elif ln and ln not in _GIT_DATES:
                    _GIT_DATES[ln] = cur
        except Exception:
            pass
    return _GIT_DATES


def git_date(path: Path) -> str:
    try:
        return git_dates(_BASE).get(path.relative_to(_BASE).as_posix(), "")
    except ValueError:
        return ""


def date_of(path: Path, head: str = "", meta: dict | None = None) -> str:
    """파일명/폴더 날짜 → json generated·asof → 본문 앞부분 첫 날짜 → git 마지막 커밋일."""
    m = DATE_RE.search(path.name) or DATE_RE.search(path.parent.name)
    if m:
        return m.group(1)
    for k in ("generated", "generated_at", "asof", "registered", "computed", "updated", "run_at_utc"):
        v = (meta or {}).get(k) if isinstance(meta, dict) else None
        if isinstance(v, str) and DATE_RE.search(v):
            return DATE_RE.search(v).group(1)
    if isinstance(meta, dict) and isinstance(meta.get("meta"), dict):
        for k in ("run_at_utc", "generated"):
            v = meta["meta"].get(k)
            if isinstance(v, str) and DATE_RE.search(v):
                return DATE_RE.search(v).group(1)
    g = git_date(path)
    if g:
        return g
    today = datetime.now(KST).strftime("%Y-%m-%d")   # 본문 날짜는 규칙 문장('2027-04-15까지 금지')일 수 있어 오늘 이후는 버림
    ds = [x for x in DATE_RE.findall(head) if "2020" <= x <= today]
    return ds[0] if ds else ""


# ── json-only 연구: 등급·판정·N·기간 → 요약, 키 표 → body_md
_GRADE_ORDER = "ABCF"


def _first_grade(v) -> str:
    if isinstance(v, str):
        m = re.match(r"\s*([ABCF])(?![A-Za-z0-9])", v) or GRADE_RE.search(v)
        return m.group(1) if m else ""
    return ""


def json_grade(d) -> tuple[str, str]:
    """(대표 등급, 설명). grade/grade_cap 문자열 우선, grades{가설: 등급} 이면 최고 등급 + 분포."""
    if not isinstance(d, dict):
        return "", ""
    for k in ("grade", "grade_cap"):
        g = _first_grade(d.get(k))
        if g:
            return g, strip_md(str(d[k]))[:60]
    for k in ("verdict", "result", "summary"):
        v = d.get(k)
        if isinstance(v, dict):
            g = _first_grade(v.get("grade"))
            if g:
                return g, strip_md(str(v["grade"]))[:60]
    gs = d.get("grades")
    if isinstance(gs, dict):
        ls = [_first_grade(v if isinstance(v, str) else (v or {}).get("grade") if isinstance(v, dict) else "") for v in gs.values()]
        ls = [x for x in ls if x]
        if ls:
            best = min(ls, key=_GRADE_ORDER.index)
            dist = " ".join(f"{g}{ls.count(g)}" for g in _GRADE_ORDER if g in ls)
            return best, f"가설 {len(ls)}개 · {dist}"
    return "", ""


def _find(d, keys: tuple, depth: int = 2):
    if not isinstance(d, dict) or depth < 0:
        return None
    for k in keys:
        if k in d and not isinstance(d[k], (dict, list)) and d[k] not in (None, ""):
            return d[k]
    for v in d.values():
        if isinstance(v, dict):
            r = _find(v, keys, depth - 1)
            if r is not None:
                return r
    return None


def json_summary(d) -> str:
    if not isinstance(d, dict):
        return ""
    parts = []
    v = d.get("verdict")
    if isinstance(v, dict):
        v = v.get("verdict") or v.get("label")
    if isinstance(v, str) and v:
        parts.append("판정 " + v)
    rec = d.get("recommendation") or d.get("label") or d.get("question")
    if isinstance(rec, str) and rec and not parts:
        parts.append(rec)
    g, why = json_grade(d)
    if g:
        parts.append(f"등급 {g}" + (f"({why})" if why and why[0] != g else (f"({why[1:].strip(' ()·')})" if len(why) > 2 else "")))
    per = d.get("period") if isinstance(d.get("period"), str) else None
    if not per:
        a, b = _find(d, ("start", "from", "kospi_from", "first")), _find(d, ("end", "until", "last", "is_end"))
        per = f"{a}~{b}" if a and b else None
    if per:
        parts.append("기간 " + str(per))
    n = _find(d, ("n", "N", "n_total", "months", "windows", "days"), 1)
    if n is not None:
        parts.append(f"표본 N {n}")
    m = d.get("m")
    if isinstance(m, (int, float)) and not isinstance(m, bool):
        parts.append(f"가설 m {m}")
    return cut(" · ".join(parts)) if parts else ""


def _cell(v) -> str:
    if isinstance(v, float):
        s = f"{v:.4g}"
    elif isinstance(v, list):
        s = f"목록 {len(v)}개" if any(isinstance(x, (dict, list)) for x in v) or len(v) > 6 else ", ".join(map(str, v))
    elif isinstance(v, dict):
        s = f"묶음 {len(v)}키"
    else:
        s = str(v)
    s = s.replace("|", "/").replace("\n", " ")
    return s if len(s) <= 160 else s[:159] + "…"


def json_body(d, rel: str) -> str:
    """키 표 마크다운 — 최상위 값 + 한 단계 아래 값(점 경로). 큰 목록은 개수만. 행 BODY_ROWS_MAX 개까지."""
    rows: list[tuple[str, str]] = []
    if isinstance(d, dict):
        for k, v in d.items():
            if isinstance(v, dict):
                rows.append((k, _cell(v)))
                for k2, v2 in list(v.items())[:12]:
                    rows.append((f"{k}.{k2}", _cell(v2)))
            else:
                rows.append((k, _cell(v)))
    else:
        rows.append(("(최상위)", _cell(d)))
    more = len(rows) - BODY_ROWS_MAX
    rows = rows[:BODY_ROWS_MAX]
    out = [f"원본 `{rel}` 의 키 표 (md 보고서 없음 — json 값을 그대로 옮김, 해석 없음)", "", "| 키 | 값 |", "|---|---|"]
    out += [f"| `{k}` | {v} |" for k, v in rows]
    if more > 0:
        out += ["", f"… 이하 {more}행 생략 — 원본 json 참조"]
    return "\n".join(out)


def _item(path: Path, cat: str, desk: str, topic: str, text: str, meta=None) -> dict:
    lines = text.splitlines()
    rel = path.relative_to(_BASE).as_posix()
    return {
        "path": rel, "date": date_of(path, "\n".join(lines[:15]), meta), "cat": cat, "desk": desk,
        "desk_ko": DESK_KO.get(desk, desk), "topic": topic, "title": md_title(lines) or topic or path.stem,
        "summary": md_summary(lines), "grade": md_grade(text), "size": path.stat().st_size,
    }


def scan_rounds(root: Path) -> list[dict]:
    rd = root / "docs" / "desk_kb" / "rounds"
    out = []
    if not rd.exists():
        return out
    for p in sorted(rd.glob("*/*.md")):
        if p.name.startswith("_") or not DATE_RE.fullmatch(p.parent.name):
            continue
        desk, topic = desk_of_name(p.stem)
        out.append(_item(p, "round", desk, topic, p.read_text(encoding="utf-8", errors="replace")))
    for p in sorted(rd.glob("*.md")):
        if p.name.startswith("_"):
            continue
        m = re.match(r"^(20\d\d-\d\d-\d\d)(?:-(.+))?$", p.stem)
        if not m:
            continue
        rest = m.group(2) or ""
        desk, topic = desk_of_name(rest) if rest else ("round", "라운드 종합")
        if rest.startswith("msg"):
            desk, topic = "msg", rest
        out.append(_item(p, "round", desk, topic, p.read_text(encoding="utf-8", errors="replace")))
    return out


def scan_studies(root: Path) -> list[dict]:
    sd = root / "reports" / "studies"
    out = []
    if not sd.exists():
        return out
    mds = {p.stem: p for p in sd.glob("*.md")}
    jss = {p.stem: p for p in sd.glob("*.json")}
    for stem in sorted(set(mds) | set(jss)):
        meta = None
        jp = jss.get(stem)
        if jp is not None:
            try:
                meta = json.loads(jp.read_text(encoding="utf-8"))
            except Exception:
                meta = None
        ser, stage = series_of(stem)
        topic = re.sub(r"^20\d\d-\d\d-\d\d_", "", stem)
        if stem in mds:
            p = mds[stem]
            it = _item(p, "study", study_desk(stem), topic, p.read_text(encoding="utf-8", errors="replace"), meta)
            if jp is not None:
                it["json"] = jp.relative_to(_BASE).as_posix()
                it["grade"] = json_grade(meta)[0] or it["grade"]   # json grade(구조화 — 가설 여럿이면 최고 등급) 우선, 없으면 본문 첫 표기
        else:
            rel = jp.relative_to(_BASE).as_posix()
            title = (meta.get("title") if isinstance(meta, dict) else None) or topic
            it = {"path": rel, "date": date_of(jp, "", meta), "cat": "study", "desk": study_desk(stem),
                  "desk_ko": DESK_KO.get(study_desk(stem)), "topic": topic, "title": f"{title} (json)",
                  "summary": json_summary(meta) or "md 보고서 없음 — 키 표로 보기", "grade": json_grade(meta)[0],
                  "size": jp.stat().st_size, "json": rel, "body_md": json_body(meta, rel)}
        it["series"], it["stage"] = ser, stage
        pre = meta.get("prereg") if isinstance(meta, dict) else None
        if isinstance(pre, str):
            m = re.search(r"((?:docs|reports)/[\w./-]+\.md)", pre)
            if m and (root / m.group(1)).exists():
                it["prereg"] = m.group(1)
        if stem == "trial_log":   # 시도 N 원장 — 연구가 아니라 등급 없음 (서고 상단 고정)
            it["grade"] = ""
        out.append(it)
    return out


def scan_dir(root: Path, sub: str, cat: str, default_desk: str) -> list[dict]:
    d = root / sub
    out = []
    if not d.exists():
        return out
    for p in sorted(d.glob("*.md")):
        stem = re.sub(r"^20\d\d-\d\d-\d\d_", "", p.stem)
        text = p.read_text(encoding="utf-8", errors="replace")
        desk = default_desk
        if cat == "valuation":   # 밸류에이션 노트는 여러 데스크가 쓴다 — 머리말 괄호 '(자산배분, …)' 에서 데스크 추정
            head = "\n".join(text.splitlines()[:6])
            for k, ko in DESK_KO.items():
                if k not in ("etc", "round", "msg", "owner") and re.search(rf"[(（\s·]{re.escape(ko)}[,)·\s]", head):
                    desk = k
                    break
        it = _item(p, cat, desk, stem, text)
        if cat == "valuation":
            it["series"], it["stage"] = series_of(p.stem)
        out.append(it)
    return out


def link_series(items: list[dict]) -> dict:
    """같은 series 키가 2개 이상인 묶음만 남긴다 → {키: [path …] 단계·날짜 순}. 외부 prereg(json 'prereg' 필드)도 단계 0 으로 넣는다."""
    by: dict[str, list[tuple[int, str, str]]] = {}
    for it in items:
        s = it.get("series")
        if s:
            by.setdefault(s, []).append((it.get("stage", 1), it["date"], it["path"]))
        if it.get("prereg") and s and it["prereg"] != it["path"] and not it["prereg"].startswith("reports/studies/"):
            by.setdefault(s, []).append((0, "", it["prereg"]))
    out = {}
    for k, v in by.items():
        seen, chain = set(), []
        for st, dt, p in sorted(v):
            if p not in seen:
                seen.add(p)
                chain.append({"path": p, "stage": st})
        if len(chain) >= 2:
            out[k] = chain
    for it in items:
        if it.get("series") not in out:
            it.pop("series", None)
            it.pop("stage", None)
    return out


def mask_amounts(text: str) -> str:
    """색인 문구(제목·요약·키 표)에 '금액 + 개인 문맥어'(prepush 4a 판정)가 걸리면 그 금액만 '[금액]'으로 가린다.
    원문은 그대로 두고 서고 색인만 — 색인은 한 줄 JSON 이라 이웃 항목 문맥까지 엮여 가드에 걸리기 쉽다(11/1 QLD '매일 N원 적립' 가상 예시)."""
    if not text or not personal_amount_hits(text):
        return text
    return AMOUNT_RX.sub(lambda m: "[금액]" if re.search(r"[,원억만M]", m.group(0)) else m.group(0), text)


def build(root: Path = ROOT, now: datetime | None = None) -> dict:
    global _BASE, _GIT_DATES
    if root != _BASE:
        _BASE, _GIT_DATES = root, None
    items = scan_rounds(root) + scan_studies(root) + scan_dir(root, "docs/valuation_notes", "valuation", "analyst") \
        + scan_dir(root, "docs/peer_reviews", "peer", "peer")
    for it in items:
        for k in ("title", "summary", "body_md"):
            if it.get(k):
                it[k] = mask_amounts(it[k])
    series = link_series(items)
    items.sort(key=lambda x: (x["date"] or "0000", x["path"]), reverse=True)
    desks: dict[str, int] = {}
    cats: dict[str, int] = {}
    grades: dict[str, int] = {}
    for it in items:
        desks[it["desk"]] = desks.get(it["desk"], 0) + 1
        cats[it["cat"]] = cats.get(it["cat"], 0) + 1
        if it["grade"]:
            grades[it["grade"]] = grades.get(it["grade"], 0) + 1
    pinned = [p for p in ("reports/studies/trial_log.md",) if (root / p).exists()]
    now = now or datetime.now(KST)
    return {
        "generated_at": now.strftime("%Y-%m-%d %H:%M"), "n": len(items), "cats": cats, "cat_ko": CAT_KO,
        "desks": dict(sorted(desks.items(), key=lambda kv: -kv[1])), "desk_ko": DESK_KO, "grades": grades,
        "pinned": [{"path": p, "title": "시도 일지 — 시도 N 원장 (trial log)"} for p in pinned],
        "series": series, "items": items,
        "note": "공개 저장소 문서 색인 — 요약은 원문 What 첫 줄/첫 문단(120자), 등급은 본문 '등급 A/B/C/F' 첫 출현 또는 json grade. 해석 추가 없음.",
    }


def dump(d: dict) -> str:
    """항목 하나 = 한 줄 (diff·prepush 줄 단위 검사가 항목 경계를 넘지 않게). 나머지 키는 앞쪽 한 줄."""
    head = {k: v for k, v in d.items() if k != "items"}
    rows = ",\n".join(json.dumps(x, ensure_ascii=False, separators=(",", ":")) for x in d["items"])
    return json.dumps(head, ensure_ascii=False, separators=(",", ":"))[:-1] + ',"items":[\n' + rows + "\n]}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="쓰지 않고 건수만")
    a = ap.parse_args()
    d = build()
    txt = dump(d)
    print(f"서고 {d['n']}건 · {d['cats']} · 묶음 {len(d['series'])} · {len(txt) // 1024}KB")
    if not a.check:
        OUT.write_text(txt + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
