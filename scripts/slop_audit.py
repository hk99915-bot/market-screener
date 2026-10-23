#!/usr/bin/env python3
"""slop 감사 — 자동 탐지 가능한 항목만 (기준서: docs/desk_kb/audit.md).

  python3 scripts/slop_audit.py                 # reports/audit/YYYY-MM-DD.md + .json, 치명 있으면 종료코드 1
  python3 scripts/slop_audit.py --ci            # GitHub Actions 주석(::warning/::error) 형식도 출력
  python3 scripts/slop_audit.py --no-git        # (g) 커밋 검사 생략 (오프라인·테스트)
  python3 scripts/slop_audit.py --paths a.md b.md   # 지정 파일만

자동 항목: (e) 원화 금액·계좌번호 / (f) 깨진 경로·kb 앵커·이슈 참조 / (b) 등급 꼬리표 없는 연구 숫자 인용
          / (c) '[확인 필요]' 방치·기한 없음 / (g) screener/*.py 변경에 tests/ 미동반 / STANDARD 4·6 (길이·헤지·중복·VOC 줄)
수동 항목(a·d 일부·h·i)은 감사 데스크가 채점표에 직접 적는다. 줄 끝에 `slop:ok` 주석이 있으면 그 줄은 건너뛴다.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN_GLOBS = ["docs/**/*.md", "reports/*.md", "content/**/*.md"]
# JSON 장부(감사 10/24 M6 — C1 미탐 원인): 요청 장부·보드·사내톡 피드(.md 지만 내용은 JSON). 문자열 값만 꺼내 (e) 금액·계좌만 본다
JSON_GLOBS = ["docs/desk_kb/rounds/*.json", "ops/board.json", "reports/msgr_feed.md"]
OUT_DIR = Path("reports/audit")
IGNORE_MARK = "slop:ok"
DUE_DAYS = {"치명": 0, "중": 3, "경": 7, "정보": 14}
TOP_DIRS = ("docs", "reports", "screener", "scripts", "tests", "data", "universe", "content", "ops", "views",
            "apps-script", "archive", ".github", "logs")
KNOWN_EXT = ("md", "py", "json", "csv", "parquet", "html", "txt", "yml", "yaml", "jsonl", "gs")

# (e) 금액 — 천 단위 쉼표+원 / 만원·억원·천만원·백만원 / 숫자+원·억 (뒤에 한글이 붙으면 '원화·원문·억제' 류이므로 제외)
AMOUNT_RE = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(만\s?원|억\s?원|천만\s?원|백만\s?원|원(?![가-힣\w/])|억(?![가-힣\w]))")
ALLOW_CTX = re.compile(r"승수|액면|비유|예시|예:|가상|환율|원/달러|달러|목표가|거래대금|순매수|순매도|차익|시가총액|영업이익|매출|순이익|"
                       r"양도세|과세|세금|공시|기준가|최소 단위|지수|포인트|캡|한도 예|월세|시세|가격\s?\(?\d|주가|종가|gex|감마|외국인|현물|선물|명목|계약|포상|"
                       r"(?:순자산|자산)\s?목표|목표\s?(?:순자산|자산|금액)")
# ↑ '종가'(ETF·종목 1주 가격, 10/24 M6 오탐 3건) · 순자산 '목표' 금액(10/24 겸이 "목표 금액 ㄱㅊ", STANDARD 5) 은 허용.
#   애널리스트·증권사 실명은 자동 탐지 대상 아님(10/24 겸이 "애널리스트 실명 ㄱㅊ").
PERSONAL_CTX = re.compile(r"보유|평단|매입가|계좌|연봉|월급|순자산|예적금|잔고|적립|투자금|원금|내 |나의|진입 금액|실제 금액")
ACCOUNT_RE = re.compile(r"(?<![\d-])(\d{3,6}-\d{2,6}-\d{4,8}|\d{10,14})(?![\d-])")

# (f) 참조
URL_RE = re.compile(r"https?://\S+")
PATH_RE = re.compile(r"(?<![\w/:.@])((?:\.\./)*(?:[\w.-]+/)+[\w.-]+/?|[\w-]+\.(?:%s))(?![\w/])" % "|".join(KNOWN_EXT))
KB_RE = re.compile(r"kb:([a-z_]+)#([\w-]+)")
ISSUE_RE = re.compile(r"(?:이슈|issue|결재|pb-private)\s*#(\d+)", re.I)

# (b) 등급 꼬리표
STUDY_RE = re.compile(r"reports/studies|rule_audit|semis_cap|entry_signals|exec_signal|derivs_signals|gamma_regime|crash_rebound|"
                      r"fib_levels|playbook_signals|replication_")
RESULT_NUM_RE = re.compile(r"\d+(?:\.\d+)?\s*%p|\bp\s*0\.\d+|\bt\s*\d\.\d|\bn\s*=?\s*\d+|승률\s*\d+")
GRADE_RE = re.compile(r"검증전|자체연구-[ABCF]|등급\s*[ABCF]|(?<![A-Za-z])[ABCF](?=[\s)/·,(\]:]|$)|\b(?:F|C|B|A)등급")

# (c)
PENDING_RE = re.compile(r"\[확인\s*필요(:?)([^\]]*)\]")
DATE_RE = re.compile(r"(20\d\d)-(\d\d)-(\d\d)")

# STANDARD 4·6
HEDGE_RE = re.compile(r"[할일]\s?수\s?있(다|음|고|으며|지만)")
BOT_COMMIT_RE = re.compile(r"^(live|briefing|logs?|lock|unlock|board|intraday|daily|archive|hist|data|reports?)\s*:", re.I)


KB_META = {"README", "LOOP", "STANDARD", "_scoreboard", "_quiz_feedback"}
REPORT_DESK = {"valuation": "analyst", "dotplot": "cio", "scorecard_week": "pb", "daily_brief": "pb", "latest_KR": "pb", "latest_US": "pb"}


def desk_of(file: str) -> str:
    """파일 경로 → 데스크 키 (round_collect 의 by_desk 집계용). 모르면 pb(감사를 만든 데스크가 떠안는다)."""
    parts = file.split("/")
    stem = Path(file).stem
    if file.startswith("git:"):
        return "dev"
    if "desk_kb/rounds/" in file:
        return stem
    if file.startswith("docs/desk_kb/"):
        return "ops" if stem in KB_META else stem
    if file.startswith("docs/valuation_notes/"):
        return "analyst"
    if file.startswith("docs/peer_reviews/"):
        return "peer"
    if file.startswith("docs/study_consults/answers/"):
        return stem
    if file.startswith("docs/study") or file.startswith("content/"):
        return "edu"
    if file.startswith("reports/"):
        return REPORT_DESK.get(stem, "pb")
    return "pb"


def finding(file: str, line: int | None, item: str, sev: str, evidence: str, action: str, today: date, desk: str | None = None) -> dict:
    due = (today + timedelta(days=DUE_DAYS[sev])).isoformat()
    return {"file": file, "line": line, "desk": desk or desk_of(file), "item": item, "severity": sev,
            "evidence": evidence[:200], "action": action, "due": due}


def _lines(text: str):
    for i, ln in enumerate(text.splitlines(), 1):
        if IGNORE_MARK in ln:
            continue
        yield i, ln


# ---------------------------------------------------------------- (e)
def scan_amounts(text: str, rel: str, today: date) -> list[dict]:
    out = []
    in_code = False
    for i, ln in _lines(text):
        if ln.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        for m in AMOUNT_RE.finditer(ln):
            ctx = ln[max(0, m.start() - 40): m.end() + 40]
            if ALLOW_CTX.search(ctx) or float(m.group(1).replace(",", "")) == 0:
                continue
            personal = PERSONAL_CTX.search(ctx)
            sev = "치명" if personal else "경"
            act = "즉시 해당 줄을 비율·단위로 치환 (감사 예외: 직접 수정, 커밋 '감사: 금액 누출 제거')" if personal \
                else "개인 금액 아님(공시·예시·모의 고정 사이즈) 확인 후 문맥에 '예시/공시' 명시 또는 비율로 치환"
            out.append(finding(rel, i, "(e) 원화 금액", sev, m.group(0) + " ← " + ctx.strip(), act, today))
        if "http" in ln or "CIK" in ln or "sec.gov" in ln:
            continue
        for m in ACCOUNT_RE.finditer(ln):
            tok = m.group(0)
            if DATE_RE.fullmatch(tok) or re.fullmatch(r"20\d\d-\d\d-\d\d", tok):
                continue
            if "-" not in tok and not re.search(r"계좌|account", ln, re.I):
                continue   # 긴 숫자열은 '계좌' 문맥일 때만
            sev = "치명" if re.search(r"계좌|account", ln, re.I) else "중"
            out.append(finding(rel, i, "(e) 계좌번호 의심", sev, tok + " ← " + ln.strip()[:120],
                               "번호를 지우고 '(비공개)'로 치환, 공개 이력 정리 여부 PB 보고", today))
    return out


def _json_strings(o, path="$", owner=None):
    """JSON → (경로, 문자열, 주인 데스크) — 주인 = 가장 가까운 dict 의 by/from/owner(데스크 키)."""
    if isinstance(o, dict):
        own = next((o[k] for k in ("by", "from", "owner") if isinstance(o.get(k), str) and re.fullmatch(r"[a-z_]+", o[k])), owner)
        for k, v in o.items():
            yield from _json_strings(v, f"{path}.{k}", own)
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from _json_strings(v, f"{path}[{i}]", owner)
    elif isinstance(o, str):
        yield path, o, owner


def _is_json_ledger(rel: str) -> bool:
    return any(Path(rel).match(g) or rel == g for g in JSON_GLOBS) or rel.endswith(".json")


def scan_json_amounts(text: str, rel: str, today: date) -> list[dict] | None:
    """JSON 장부의 문자열 값마다 scan_amounts. 파싱 실패면 None(→ 호출부가 일반 텍스트로 본다)."""
    try:
        data = json.loads(text)
    except ValueError:
        return None
    lines = text.splitlines()
    out = []
    for jp, s, own in _json_strings(data):
        hits = scan_amounts(s, rel, today)
        if not hits:
            continue
        needle = json.dumps(s, ensure_ascii=False)[1:41]
        ln = next((i for i, x in enumerate(lines, 1) if needle in x), None) if len(lines) > 1 else None
        for f in hits:
            f["line"] = ln
            f["evidence"] = (jp + " " + f["evidence"])[:200]
            f["desk"] = own or ("pb" if "desk_kb/rounds/" in rel else f["desk"])
        out += hits
    return out


# ---------------------------------------------------------------- (f)
def _kb_has_anchor(kb_text: str, n: str) -> bool:
    if n.isdigit():
        pat = re.compile(r"^\s*(?:-\s*#%s\b|%s\.\s|#%s\b)" % (n, n, n), re.M)
        return bool(pat.search(kb_text))
    return ("#" + n) in kb_text or re.search(r"^#+ .*%s" % re.escape(n), kb_text, re.M | re.I) is not None


def scan_refs(text: str, rel: str, root: Path, today: date) -> list[dict]:
    out = []
    src_dir = (root / rel).parent
    for i, ln in _lines(text):
        clean = URL_RE.sub(" ", ln)
        for m in PATH_RE.finditer(clean):
            p = m.group(1).rstrip("/").rstrip(".")
            nxt = clean[m.end(): m.end() + 1]
            if any(ch in p for ch in "*<>{}") or "YYYY" in p or p.startswith("http") or (nxt and nxt in "{*"):
                continue
            p = re.sub(r"(\.(?:%s))/.*$" % "|".join(KNOWN_EXT), r"\1", p)   # a.md/.json → a.md
            head = p.split("/")[0]
            last = p.split("/")[-1]
            if "/" not in p or p.endswith("_") or nxt == "<":
                continue   # 맨 파일명(예: committee.py)은 위치를 특정할 수 없고, `replication_<id>` 류는 템플릿
            if "." in last and not last.endswith(KNOWN_EXT):
                continue   # `study_daily.build` 같은 함수 참조
            if "." not in last and (root / (p + ".md")).exists():
                continue   # ops/LOCKS → ops/LOCKS.md 생략 표기
            if not (p.startswith("../") or head in TOP_DIRS):
                continue
            if re.fullmatch(r"[\d./-]+", p):
                continue
            cands = [root / p, src_dir / p]
            if any(c.exists() for c in cands):
                continue
            sev = "중" if "출처" in ln else "경"
            out.append(finding(rel, i, "(f) 깨진 경로", sev, p + " ← " + ln.strip()[:100],
                               "실제 경로로 고치거나 '(예정)'·'(미생성)' 표기", today))
        for m in KB_RE.finditer(clean):
            desk, n = m.group(1), m.group(2)
            kb = root / "docs" / "desk_kb" / f"{desk}.md"
            if not kb.exists():
                out.append(finding(rel, i, "(f) kb 앵커", "중", m.group(0) + " — KB 파일 없음", "데스크 키 확인 또는 KB 신설", today))
                continue
            if not _kb_has_anchor(kb.read_text(encoding="utf-8"), n):
                out.append(finding(rel, i, "(f) kb 앵커", "경", m.group(0) + f" — {desk}.md 에 #{n} 항목 없음", "항목 번호 확인", today))
        for m in ISSUE_RE.finditer(clean):
            out.append(finding(rel, i, "(f) 이슈 참조", "정보", m.group(0) + " — 비공개 저장소 이슈, 자동 확인 불가",
                               "감사 수동 확인(이슈 존재·제목 일치)", today))
    return out


# ---------------------------------------------------------------- (b)
def scan_grade_tags(text: str, rel: str, today: date) -> list[dict]:
    out = []
    for i, ln in _lines(text):
        if not STUDY_RE.search(ln) or not RESULT_NUM_RE.search(ln):
            continue
        if GRADE_RE.search(ln) or re.search(r"\[(교과서|논문|규정)\]", ln) or ln.lstrip().startswith("요청→"):
            continue
        out.append(finding(rel, i, "(b) 등급 없는 연구 인용", "중", ln.strip()[:160],
                           "같은 줄에 A/B/C/F/검증전 꼬리표 추가 (README 규칙)", today))
    return out


# ---------------------------------------------------------------- (c)
def file_date(path: Path, text: str, today: date) -> date:
    m = DATE_RE.search(path.name)
    if m:
        return date(*map(int, m.groups()))
    ds = []
    for y, mo, d in DATE_RE.findall(text):
        try:
            dd = date(int(y), int(mo), int(d))
        except ValueError:
            continue
        if dd <= today:
            ds.append(dd)
    if ds:
        return max(ds)
    return datetime.fromtimestamp(path.stat().st_mtime).date()


def scan_pending(text: str, rel: str, path: Path, today: date, max_days: int = 7) -> list[dict]:
    out = []
    tags = [(i, m) for i, ln in _lines(text) for m in PENDING_RE.finditer(ln)]
    if not tags:
        return out
    base = file_date(path, text, today)
    age = (today - base).days
    no_due = [i for i, m in tags if not re.search(r"까지|\d{1,2}/\d{1,2}|20\d\d-\d\d", m.group(2))]
    if age > max_days:
        out.append(finding(rel, tags[0][0], "(c) 확인 필요 방치", "중" if age > 30 else "경",
                           f"[확인 필요] {len(tags)}건, 기준일 {base} ({age}일 경과)", "확인해서 지우거나 기한을 적기", today))
    if no_due:
        out.append(finding(rel, no_due[0], "(c) 확인 필요 기한 없음", "경",
                           f"기한 없는 [확인 필요] {len(no_due)}/{len(tags)}건 (STANDARD §1)", "`[확인 필요: 무엇, 언제까지]` 형식으로", today))
    return out


# ---------------------------------------------------------------- (g)
def git_log_entries(root: Path, n: int = 30) -> list[dict]:
    try:
        raw = subprocess.run(["git", "log", f"-n{n}", "--name-only", "--format=%x1e%h%x1f%an%x1f%s"],
                             cwd=root, capture_output=True, text=True, check=True).stdout
    except Exception:
        return []
    entries = []
    for chunk in raw.split("\x1e"):
        if not chunk.strip():
            continue
        head, _, files = chunk.partition("\n")
        parts = head.split("\x1f")
        if len(parts) < 3:
            continue
        entries.append({"hash": parts[0], "author": parts[1], "subject": parts[2],
                        "files": [f for f in files.splitlines() if f.strip()]})
    return entries


def scan_commits(entries: list[dict], today: date) -> list[dict]:
    out = []
    for e in entries:
        if BOT_COMMIT_RE.match(e["subject"]) or "screener-bot" in e.get("author", ""):
            continue
        code = [f for f in e["files"] if re.fullmatch(r"screener/[\w/]+\.py", f)]
        if not code:
            continue
        if any(f.startswith("tests/") for f in e["files"]):
            continue
        m = re.match(r"\s*([a-z]+)\s*라운드", e["subject"])
        out.append(finding("git:" + e["hash"], None, "(g) 테스트 없는 코드 변경", "중",
                           f"{e['hash']} {e['subject'][:80]} — {', '.join(code[:3])}", "tests/ 에 회귀 테스트 1건 이상 추가", today,
                           desk=m.group(1) if m else "dev"))
    return out


# ---------------------------------------------------------------- STANDARD 4·6
def scan_style(text: str, rel: str, today: date) -> list[dict]:
    out = []
    lines = text.splitlines()
    n = len(lines)
    is_round = "/rounds/" in rel
    is_note = rel.startswith("docs/valuation_notes/") or rel.startswith("docs/peer_reviews/")
    if is_round and n > 40:
        out.append(finding(rel, n, "(d) 길이 상한", "경", f"라운드 파일 {n}줄 > 40", "부록으로 분리 (STANDARD §4)", today))
    if is_note and n > 150:
        out.append(finding(rel, n, "(d) 길이 상한", "경", f"노트 {n}줄 > 150", "부록으로 분리 (STANDARD §4)", today))
    hedges = sum(len(HEDGE_RE.findall(ln)) for _, ln in _lines(text))
    if n and hedges >= 6 and hedges / max(n, 1) > 0.08:
        out.append(finding(rel, None, "(d) 헤지 남발", "경", f"'~수 있다' {hedges}회 / {n}줄", "불확실성 수치가 있을 때만 헤지 (STANDARD §4)", today))
    seen: dict[str, int] = {}
    for i, ln in _lines(text):
        key = re.sub(r"\s+", " ", ln.strip())
        if len(key) < 40 or key.startswith("|") or key.startswith("#"):
            continue
        if key in seen:
            out.append(finding(rel, i, "(d) 중복 문장", "경", f"{seen[key]}줄과 동일: {key[:80]}", "한 번만 쓰고 참조", today))
        else:
            seen[key] = i
    if is_round:
        if not re.search(r"^VOC\s*[:：]", text, re.M) and "VOC:" not in text:
            out.append(finding(rel, None, "(6) VOC 줄 없음", "중", "라운드 파일에 `VOC:` 줄 없음", "LOOP.md 6항 — VOC 1줄 추가", today))
        if "요청→" not in text:
            out.append(finding(rel, None, "(6) 요청 줄 없음", "중", "`요청→<데스크>:` 줄 없음", "LOOP.md 8항", today))
    return out


# ---------------------------------------------------------------- 실행
def collect_paths(root: Path, paths: list[str] | None) -> list[Path]:
    if paths:
        return [root / p if not Path(p).is_absolute() else Path(p) for p in paths]
    found: list[Path] = []
    for g in SCAN_GLOBS + JSON_GLOBS:
        found += [p for p in sorted(root.glob(g)) if p not in found]
    out_abs = (root / OUT_DIR).resolve()
    return [p for p in found if p.is_file() and out_abs not in p.resolve().parents]


def audit(root: Path, today: date, paths: list[str] | None = None, git: bool = True) -> dict:
    findings: list[dict] = []
    files = collect_paths(root, paths)
    for p in files:
        try:
            rel = str(p.resolve().relative_to(root.resolve()))
        except ValueError:
            rel = str(p)
        text = p.read_text(encoding="utf-8", errors="replace")
        if _is_json_ledger(rel) or text.lstrip()[:1] in ("{", "["):
            js = scan_json_amounts(text, rel, today)
            if js is not None:            # JSON 장부: 금액·계좌만 (경로·등급·길이 검사는 md 산출물용)
                findings += js
                continue
        findings += scan_amounts(text, rel, today)
        findings += scan_refs(text, rel, root, today)
        findings += scan_grade_tags(text, rel, today)
        findings += scan_pending(text, rel, p, today)
        findings += scan_style(text, rel, today)
    if git:
        findings += scan_commits(git_log_entries(root), today)
    counts = {s: sum(f["severity"] == s for f in findings) for s in ("치명", "중", "경", "정보")}
    by_desk: dict[str, dict[str, int]] = {}
    for f in findings:
        if f["severity"] == "정보":
            continue
        by_desk.setdefault(f["desk"], {"치명": 0, "중": 0, "경": 0})[f["severity"]] += 1
    return {"date": today.isoformat(), "files": len(files), "counts": counts, "by_desk": by_desk, "findings": findings}


def render_md(res: dict) -> str:
    c = res["counts"]
    L = [f"# slop 자동 감사 — {res['date']}", "",
         f"기준서 docs/desk_kb/audit.md · 스캔 {res['files']}개 파일 · 치명 {c['치명']} / 중 {c['중']} / 경 {c['경']} / 정보 {c['정보']}", "",
         "데스크별: " + " · ".join(f"{d} 치{v['치명']}/중{v['중']}/경{v['경']}" for d, v in sorted(res["by_desk"].items())), "",
         "| 산출물 | 항목 | 심각도 | 근거(파일:줄) | 조치 | 기한 |", "|---|---|---|---|---|---|"]
    order = {"치명": 0, "중": 1, "경": 2, "정보": 3}
    for f in sorted(res["findings"], key=lambda f: (order[f["severity"]], f["file"], f["line"] or 0)):
        loc = f["file"] + (f":{f['line']}" if f["line"] else "")
        ev = f["evidence"].replace("|", "/").replace("\n", " ")
        L.append(f"| {f['file'].split('/')[-1]} | {f['item']} | {f['severity']} | `{loc}` {ev} | {f['action']} | {f['due']} |")
    if not res["findings"]:
        L.append("| — | — | — | 지적 없음 | — | — |")
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--date", default=None)
    ap.add_argument("--paths", nargs="*")
    ap.add_argument("--no-git", action="store_true")
    ap.add_argument("--ci", action="store_true", help="GitHub Actions 주석 출력")
    ap.add_argument("--out", default=None, help="출력 디렉터리 (기본 reports/audit)")
    a = ap.parse_args(argv)
    root = Path(a.root)
    today = date.fromisoformat(a.date) if a.date else date.today()
    res = audit(root, today, a.paths, git=not a.no_git)
    out_dir = Path(a.out) if a.out else root / OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{today.isoformat()}.md").write_text(render_md(res), encoding="utf-8")
    (out_dir / f"{today.isoformat()}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    c = res["counts"]
    print(f"slop audit {today}: 치명 {c['치명']} 중 {c['중']} 경 {c['경']} 정보 {c['정보']} → {out_dir / (today.isoformat() + '.md')}")
    if a.ci:
        for f in res["findings"]:
            if f["severity"] == "정보":
                continue
            kind = "error" if f["severity"] == "치명" else "warning"
            loc = f"file={f['file']}" + (f",line={f['line']}" if f["line"] and not f["file"].startswith("git:") else "")
            print(f"::{kind} {loc}::[{f['severity']}] {f['item']} — {f['evidence'][:120]}")
    return 1 if c["치명"] else 0


if __name__ == "__main__":
    sys.exit(main())
