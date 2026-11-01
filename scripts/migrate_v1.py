"""리팩토링 v1 이전 스크립트 — 옛 저장소(내부판) HEAD 에서 새 공개 저장소(범용판)로 옮길 파일을 고르고, 경계 검사를 돌린다.

결재 11/1 18:08(겸이 「싹다승인」) · 상위 문서 docs/refactor_plan_v1.md §4·§7, 분류 근거 docs/refactor_v1_inventory.md §1·§3·§3-1.
- 기본은 **dry-run**: 아무것도 쓰지 않고 목록·검사 결과만 보고. `--apply --dest DIR` 일 때만 DIR 에 파일을 쓴다(빈 폴더 또는 새 clone).
- 원본 = git 커밋(기본 HEAD)의 블롭 — 작업 트리의 커밋 안 된 수정(다른 세션 편집 중 파일)은 섞이지 않는다.
- 이력은 옮기지 않는다(새 저장소 = 스냅샷 1커밋, 계획서 §4). 저장소 생성·이름 변경·가시성 변경·push 는 하지 않는다(겸이 직접).
- 루트 index.html 은 범용판 빌드(scripts/build_edition.py --edition public 과 같은 결과)로 바꿔 쓰고 `.edition`=public 을 남긴다.

경계 검사(자동 · 감사 기준 = 금액·이름·개인 문맥, audit_privacy 10/27):
  A 금지 경로   제외 목록(§3-1) 경로·비밀 파일 꼴(.env·token.json·*.pem)이 옮길 목록에 0건인지
  B 금액·개인   scripts/privacy_history_audit.Scanner 를 옮길 텍스트 파일 전부에(시장 데이터 제외) — 'review' 0건이어야 통과.
               --private-dir(pb-private) 를 주면 실제 금액·보유 지문까지(값은 메모리에서만, 출력은 숫자를 9로 가림)
  C 이름·호칭   '겸이'·'누나'·'사담' 줄 수(영역별) — 개인정보는 아니라 막지 않음(인벤토리 §6: 11/12 이후 문구 정리). 보고만
  D 끊긴 참조   옮길 파일이 제외 경로(ops/board.json·docs/desk_kb/…)를 문자열로 가리키는 곳 — 범용판에서 404·테스트 실패 후보
종료코드: 0 = A·B 통과, 1 = 막힘(A 또는 B review), 2 = 사용법 오류.

  python3 scripts/migrate_v1.py                                  # dry-run 요약
  python3 scripts/migrate_v1.py --report /tmp/x.md --private-dir ../pb-private
  python3 scripts/migrate_v1.py --apply --dest ../market-screener-new [--pytest]
  python3 scripts/migrate_v1.py --allow <감사 확인 오탐 JSON>          # review 를 감사가 본 뒤에만
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

PUBLIC, INTERNAL, PERSONAL, ARCHIVE = "범", "내", "제외(개인)", "보관"

# (정규식, 판, 근거) — 위에서부터 첫 일치. 일치 없으면 범(공개).
RULES: list[tuple[str, str, str]] = [
    # §3-1 개인정보 흔적(감사 10/27) — 내부판엔 남고 범용판 스냅샷에서만 뺀다
    (r"^docs/desk_kb/rounds/_requests\.json$", PERSONAL, "§3-1 이력에 개인 원값(L-1·L-3·L-7)"),
    (r"^reports/msgr_feed\.md$", PERSONAL, "§3-1 위 복사본 이력"),
    (r"^reports/audit/", PERSONAL, "§3-1 evidence 2차 누출"),
    (r"^docs/desk_kb/OKR\.md$", PERSONAL, "§3-1 개인 목표 문서"),
    (r"^reports/logs/", PERSONAL, "§3-1 애널리스트 이메일 이력"),
    (r"^ops/(cooldown|renego|isa_buys)\.json$", PERSONAL, "§3-1 개인 매매 행동"),
    (r"^reports/(decisions\.json|battle_|practice_book|portfolios)", PERSONAL, "§3-1 개인 결재·모의 북"),
    (r"^(docs/office_world/|docs/desk_kb/(CHARACTERS|PERSONAS)\.md$|docs/desk_kb/bios|assets/avatars/|assets/office_world/)",
     PERSONAL, "§3-1 캐릭터 설정(PB 11/1)"),
    # §3 내부판(데스크 운영·겸이 발언·결재)
    (r"^docs/desk_kb/(industry_onepager_template|STANDARD)\.md$", PUBLIC, "§3 산업 한 장 틀·현업급 기준"),
    (r"^docs/desk_kb/", INTERNAL, "§3 데스크 KB·라운드·결재"),
    (r"^docs/(uxui|study_consults|realestate|old)/", INTERNAL, "§3 내부 문서"),
    (r"^docs/(my_tab_holdings_plan|journal_skeleton|rules_terms|telegram_pick_buttons|refactor_|integrity_dev_plan|sectors_switch)",
     INTERNAL, "§3 내부 문서(개인 규칙·결재·이전 계획)"),
    (r"^content/", INTERNAL, "§3 학습·드릴(겸이 인용)"),
    (r"^ops/freshness[^/]*\.json$", PUBLIC, "§3 신선도 계약(범)"),
    (r"^ops/", INTERNAL, "§3 보드·팀·개인 장치"),
    (r"^(views|notes)/", INTERNAL, "§3 뷰 등록부·연구 매뉴얼"),
    (r"^\.claude/", INTERNAL, "§3 데스크 스킬"),
    (r"^CLAUDE\.md$", INTERNAL, "세션 규칙(데스크 루프)"),
    (r"^reports/(alphabook|hf_|isa_lab_returns|scorecard_week|study_|ideas_log|ideas_attrib|views_attrib|committee|"
     r"_quiz_feedback|alerts_state|event_state|watchdog|research_board|signal_tracking|dotplot_score|changelog)",
     INTERNAL, "§3 개인·데스크 산출"),
    (r"^reports/(ops|uxui|idea_tracking|english|archive/committee|archive/committee_us|battle_daily)/", INTERNAL, "§3 개인·데스크 산출"),
    # 내부 기능만 시험하는 테스트(학습·드릴·보드·스킬·ISA 실험실·개인 규칙 용어) — 대상 파일이 범용판에 없음
    (r"^tests/(test_(study_[\w]+|drill_grade|research_board|tg_quiz|onboarding_quiz|[\w]+_skill|isa_lab|rules_terms|board_approval|js_smoke)\.py|js/study_smoke\.js)$",
     INTERNAL, "내부 기능 테스트(대상 파일 내부판)"),
    # §1 워크플로 판
    (r"^\.github/workflows/(ask|msgr_feed|pb_call|pick|scorecard|study|study_daily|team)\.yml$", INTERNAL, "§1 내부판 워크플로 8"),
    (r"^\.github/workflows/(event_driven_data|laor_ib_data|qld_dca_data|us_spikes_data|us_spikes_intraday_data)\.yml$",
     ARCHIVE, "§1 연구 일회성(옮기지 않음)"),
]
_RULES = [(re.compile(rx), ed, why) for rx, ed, why in RULES]
SECRET_FILE_RX = re.compile(r"(^|/)(\.env(\..*)?|token\.json|credentials[^/]*\.json|[^/]*\.pem|id_rsa[^/]*|toss_md/env)$")
NAME_RX = re.compile(r"겸이|누나|사담")
# 끊긴 참조 후보: 문자열 안의 제외 경로(내부·개인)
REF_RX = re.compile(r"(?:ops/(?!freshness)[\w.-]+\.json|docs/desk_kb/[\w./-]+|content/[\w./-]+|reports/(?:decisions|portfolios|"
                    r"practice_book|committee|msgr_feed|alphabook|study_progress|battle_[\w]+)[\w.-]*|views/registry\.json)")
TEXT_EXT = (".py", ".md", ".json", ".yml", ".yaml", ".html", ".gs", ".js", ".txt", ".csv", ".sh", ".ini", ".toml", ".cfg", ".jsonl")


def classify(path: str) -> tuple[str, str]:
    for rx, ed, why in _RULES:
        if rx.search(path):
            return ed, why
    return PUBLIC, "기본(코드·시장 산출·공개 문서)"


@dataclass
class Plan:
    rev: str
    files: dict[str, tuple[str, str, str]] = field(default_factory=dict)   # path → (mode, sha, 판)
    why: dict[str, str] = field(default_factory=dict)

    def by(self, ed: str) -> list[str]:
        return sorted(p for p, (_, _, e) in self.files.items() if e == ed)


def git(*a: str, text: bool = True, inp: bytes | None = None):
    return subprocess.run(["git", "-C", str(ROOT), *a], capture_output=True, text=text, check=True, input=inp).stdout


def make_plan(rev: str = "HEAD") -> Plan:
    pl = Plan(rev)
    for rec in git("ls-tree", "-r", "-z", rev).split("\0"):
        if not rec:
            continue
        meta, path = rec.split("\t", 1)
        mode, typ, sha = meta.split()
        if typ != "blob":     # 서브모듈 등
            continue
        ed, why = classify(path)
        pl.files[path] = (mode, sha, ed)
        pl.why[path] = why
    return pl


def read_blobs(shas: list[str]) -> dict[str, bytes]:
    """git cat-file --batch 로 한 번에 읽는다(파일 수천 개)."""
    if not shas:
        return {}
    out = git("cat-file", "--batch", text=False, inp=("\n".join(shas) + "\n").encode())
    res, i = {}, 0
    for sha in shas:
        nl = out.index(b"\n", i)
        hdr = out[i:nl].split()
        size = int(hdr[2])
        res[sha] = out[nl + 1: nl + 1 + size]
        i = nl + 1 + size + 1
    return res


# ---------------------------------------------------------------- 검사
def check_forbidden(pl: Plan) -> list[str]:
    bad = []
    for p in pl.by(PUBLIC):
        if SECRET_FILE_RX.search(p):
            bad.append(f"{p} — 비밀 파일 꼴")
        ed, _ = classify(p)
        if ed != PUBLIC:
            bad.append(f"{p} — 제외 규칙과 모순")
    return bad


def is_text(p: str) -> bool:
    return p.lower().endswith(TEXT_EXT) or "." not in p.rsplit("/", 1)[-1]


def scan(pl: Plan, blobs: dict[str, bytes], private_dir: Path | None):
    import privacy_history_audit as pa
    sc = pa.Scanner(private_dir)
    hits, names, refs = [], Counter(), defaultdict(Counter)
    for p in pl.by(PUBLIC):
        if not is_text(p):
            continue
        try:
            body = blobs[pl.files[p][1]].decode("utf-8")
        except UnicodeDecodeError:
            continue
        area = "/".join(p.split("/")[:2]) if "/" in p else p
        for i, ln in enumerate(body.splitlines(), 1):
            if NAME_RX.search(ln):
                names[area.split("/")[0] if area.startswith(("reports/detail",)) else area] += 1
            for m in REF_RX.finditer(ln):
                refs[p][m.group(0).split("?")[0][:60]] += 1
            if not pa.skip_path(p):
                hits += sc.hits("snapshot", p, i, ln)
    return sc, hits, names, refs


def workflow_notes(pl: Plan, blobs: dict[str, bytes]) -> list[str]:
    out = []
    for p in pl.by(PUBLIC):
        if not p.startswith(".github/workflows/"):
            continue
        s = blobs[pl.files[p][1]].decode("utf-8", "replace")
        for k in ("RISK_PCT", "SAT_BOOK_KRW"):
            if k in s:
                out.append(f"{p}: 내부판 전용 시크릿 {k} 참조")
        for m in set(REF_RX.findall(s)):
            out.append(f"{p}: 제외 경로 참조 {m}")
    return out


# ---------------------------------------------------------------- 쓰기
PUBLIC_INDEX = "public-index"   # 가상 블롭 키: 범용판 index.html


def swap_public_index(pl: Plan, blobs: dict[str, bytes]) -> None:
    """루트 index.html 을 범용판 빌드(원본 커밋의 apps-script 로)로 바꿔 검사·쓰기 둘 다 같은 내용을 보게 한다."""
    import build_edition as be

    def rd(name: str) -> str:
        return git("show", f"{pl.rev}:apps-script/{name}.html")
    blobs[PUBLIC_INDEX] = be.build_edition("public", read=rd).encode("utf-8")
    mode = pl.files.get("index.html", ("100644",))[0]
    pl.files["index.html"] = (mode, PUBLIC_INDEX, PUBLIC)
    pl.why["index.html"] = "범용판 빌드(scripts/build_edition.py public)"


def write_snapshot(pl: Plan, blobs: dict[str, bytes], dest: Path) -> int:
    if dest.exists() and any(x for x in dest.iterdir() if x.name != ".git"):
        raise SystemExit(f"--dest {dest} 가 비어 있지 않음(.git 말고 파일 있음) — 새 clone 또는 빈 폴더만")
    n = 0
    for p in pl.by(PUBLIC):
        mode, sha, _ = pl.files[p]
        f = dest / p
        f.parent.mkdir(parents=True, exist_ok=True)
        if mode == "120000":
            os.symlink(blobs[sha].decode(), f)
        else:
            f.write_bytes(blobs[sha])
            if mode == "100755":
                f.chmod(0o755)
        n += 1

    (dest / ".edition").write_text("public\n", encoding="utf-8")   # build_edition 기본 판 = 범용판
    return n


def run_pytest(dest: Path) -> tuple[int, list[str]]:
    if not (dest / ".git").exists():   # git ls-tree·check-ignore 를 쓰는 테스트용
        subprocess.run(["git", "init", "-q", "-b", "main", str(dest)], check=True)
    if subprocess.run(["git", "-C", str(dest), "rev-parse", "-q", "--verify", "HEAD"], capture_output=True).returncode:
        # 커밋이 없으면 스냅샷 1커밋(로컬만 — push 는 하지 않음, 계획서 §4 '이력 없이 시작')
        subprocess.run(["git", "-C", str(dest), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(dest), "-c", "user.name=Claude", "-c", "user.email=noreply@anthropic.com", "commit", "-q",
                        "-m", "snapshot: market-screener 범용판 (scripts/migrate_v1.py)"], check=True)
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--no-header", "-rfE", "--continue-on-collection-errors"],
                       cwd=dest, capture_output=True, text=True)
    failed = sorted({ln.split("::")[0].replace("FAILED ", "").replace("ERROR ", "")
                     for ln in r.stdout.splitlines() if ln.startswith(("FAILED ", "ERROR "))})
    return r.returncode, failed


# ---------------------------------------------------------------- 보고
def report(pl: Plan, forb: list[str], sc, hits, names, refs, wf, apply_info: str, pytest_info: str, top: int = 25) -> tuple[str, int]:
    cnt = {ed: len(pl.by(ed)) for ed in (PUBLIC, INTERNAL, PERSONAL, ARCHIVE)}
    rev = git("rev-parse", "--short", pl.rev).strip()
    review = [h for h in hits if h.category == "review"]
    cat = Counter((h.kind, h.category) for h in hits)
    L = [f"# 이전 스크립트 결과 — migrate_v1 (원본 {rev})", "",
         "<!-- 자동 생성: python3 scripts/migrate_v1.py --report … — 값은 출력하지 않음(숫자는 9로 가림) -->", "",
         "## 요약",
         f"- 추적 파일 {len(pl.files)}개 → 범용판 {cnt[PUBLIC]} · 내부판 전용 {cnt[INTERNAL]} · 개인 흔적 제외 {cnt[PERSONAL]} · 보관 {cnt[ARCHIVE]}",
         f"- A 금지 경로·비밀 파일: {'통과(0건)' if not forb else f'**막힘 {len(forb)}건**'}",
         f"- B 금액·개인(비공개 지문 {'사용' if sc.vals or sc.hold else '안 씀'} — 개수·값 비공개): review {len(review)}건 "
         f"{'→ 통과' if not review else '→ **막힘**'} · 그 밖 분류 {sum(v for (k, c), v in cat.items() if c != 'review')}건(규정·시장·예시 등 허용)",
         f"- C 이름·호칭('겸이'·'누나'·'사담') 줄: {sum(names.values())} — 막지 않음(인벤토리 §6, 11/12 이후 문구 정리)",
         f"- D 제외 경로를 가리키는 범용판 파일: {len(refs)}개 — 범용판에서 404·테스트 실패 후보",
         f"- 쓰기: {apply_info}", f"- pytest(범용판 트리): {pytest_info}", ""]
    L += ["## 판별 건수(최상위 경로)", "| 경로 | 범 | 내 | 제외(개인) | 보관 |", "|---|---|---|---|---|"]
    agg: dict[str, Counter] = defaultdict(Counter)
    for p, (_, _, ed) in pl.files.items():
        agg[p.split("/")[0] if "/" in p else "(루트)"][ed] += 1
    for k in sorted(agg):
        c = agg[k]
        L.append(f"| `{k}` | {c[PUBLIC]} | {c[INTERNAL]} | {c[PERSONAL]} | {c[ARCHIVE]} |")
    L += ["", "## 제외 규칙별 건수", "| 판 | 근거 | 파일 |", "|---|---|---|"]
    for (ed, why), v in sorted(Counter((pl.files[p][2], pl.why[p]) for p in pl.files if pl.files[p][2] != PUBLIC).items()):
        L.append(f"| {ed} | {why} | {v} |")
    L += ["", "## A 금지 경로", *(f"- {x}" for x in forb[:top])] if forb else ["", "## A 금지 경로", "- 0건"]
    L += ["", "## B 금액·개인 — 분류별", "| 종류 | 분류 | 건 |", "|---|---|---|"]
    L += [f"| {k} | {c} | {v} |" for (k, c), v in sorted(cat.items())] or ["| — | — | 0 |"]
    if review:
        L += ["", f"### review {len(review)}건(앞 {top}) — 미리보기 숫자 가림"]
        L += [f"- `{h.path}:{h.line}` {h.kind}/{h.ctx} | {h.preview}" for h in review[:top]]
    L += ["", "## C 이름·호칭 줄 수(영역 상위)", "| 영역 | 줄 |", "|---|---|"]
    L += [f"| `{k}` | {v} |" for k, v in names.most_common(top)]
    L += ["", f"## D 끊긴 참조 후보(파일 상위 {top})", "| 파일 | 참조(건) |", "|---|---|"]
    for p, c in sorted(refs.items(), key=lambda x: -sum(x[1].values()))[:top]:
        L.append(f"| `{p}` | {' · '.join(f'{k}({v})' for k, v in c.most_common(3))} |")
    L += ["", "## 워크플로 메모", *(f"- {x}" for x in wf)] if wf else ["", "## 워크플로 메모", "- 없음"]
    rc = 1 if (forb or review) else 0
    L += ["", f"종료코드 {rc} ({'통과' if rc == 0 else '막힘 — 위 A·B 를 고친 뒤 다시'})"]
    return "\n".join(L) + "\n", rc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--rev", default="HEAD", help="원본 커밋(기본 HEAD)")
    ap.add_argument("--apply", action="store_true", help="실제로 --dest 에 쓴다(없으면 dry-run)")
    ap.add_argument("--dest", default="", help="범용판 스냅샷을 쓸 빈 폴더(새 저장소 clone)")
    ap.add_argument("--private-dir", default="", help="pb-private 경로 — 실제 금액·보유 지문(값은 출력 안 함)")
    ap.add_argument("--pytest", action="store_true", help="--apply 뒤 범용판 트리에서 pytest 를 돌려 실패 파일 목록")
    ap.add_argument("--report", default="", help="보고서(markdown) 저장 경로")
    ap.add_argument("--allow", default="", help="감사 데스크가 확인한 오탐 목록 JSON [{path, kind, why}] — 일치 review 를 'allowed' 로")
    ap.add_argument("--list", choices=(PUBLIC, INTERNAL, PERSONAL, ARCHIVE), help="해당 판 파일 목록만 출력")
    a = ap.parse_args(argv)
    if a.apply and not a.dest:
        print("--apply 에는 --dest 가 필요", file=sys.stderr)
        return 2
    dest = Path(a.dest).resolve() if a.dest else None
    if dest and (dest == ROOT.resolve() or ROOT.resolve() in dest.parents):
        print("--dest 는 이 저장소 밖이어야 함", file=sys.stderr)
        return 2
    pl = make_plan(a.rev)
    if a.list:
        print("\n".join(pl.by(a.list)))
        return 0
    pub = pl.by(PUBLIC)
    blobs = read_blobs(sorted({pl.files[p][1] for p in pub}))
    swap_public_index(pl, blobs)
    forb = check_forbidden(pl)
    sc, hits, names, refs = scan(pl, blobs, Path(a.private_dir) if a.private_dir else None)
    wf = workflow_notes(pl, blobs)
    if a.allow:
        import json
        allow = {(x["path"], x["kind"]) for x in json.loads(Path(a.allow).read_text(encoding="utf-8"))}
        for h in hits:
            if h.category == "review" and (h.path, h.kind) in allow:
                h.category = "allowed"
    apply_info, pytest_info = "dry-run(쓰지 않음)", "안 돌림"
    if a.apply:
        n = write_snapshot(pl, blobs, dest)
        apply_info = f"{n}개 파일(index.html = 범용판 빌드) → `{dest.name}/`"
        if a.pytest:
            code, failed = run_pytest(dest)
            pytest_info = f"종료 {code} · 실패 파일 {len(failed)}개" + (": " + ", ".join(f"`{x}`" for x in failed[:40]) if failed else "")
    text, rc = report(pl, forb, sc, hits, names, refs, wf, apply_info, pytest_info)
    if a.report:
        Path(a.report).write_text(text, encoding="utf-8")
    print(text)
    return rc


if __name__ == "__main__":
    sys.exit(main())
