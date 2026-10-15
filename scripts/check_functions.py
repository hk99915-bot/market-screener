"""푸시 전 필수 검사 — 동시 편집으로 함수가 사라지는 회귀(예: myRun 삭제) 방지.

1) apps-script/Index.html · *.gs 의 최상위 이름(`function NAME(`, `const/let/var NAME=`)을
   기준 리비전(기본 origin/main)과 작업 사본에서 비교 → 하나라도 사라지면 실패.
   일부러 지운 이름은 --allow-removed NAME[,NAME…] 로 명시.
2) 빌드된 index.html 과 apps-script/Index.html 의 모든 인라인 <script> 를 node `new Function` 으로 문법 검사.
3) index.html 이 Index.html 보다 낡았으면 경고 (python scripts/build_pages.py 다시 실행).
4) ops/locks.json 에서 남이 잠근 공유 파일을 내가 고쳤으면 경고 (--owner 주면 실패).

  python scripts/check_functions.py                       # 기본: origin/main 대비
  python scripts/check_functions.py --base HEAD~1 --allow-removed oldFn,LEGACY
  python scripts/check_functions.py --owner "퀀트 누나"
종료코드 0 = 통과, 1 = 실패.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WATCH = ["apps-script/Index.html", "apps-script/Code.gs", "apps-script/Scheduler.gs"]
TOP = re.compile(r"^(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)\s*\(|^(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=", re.M)
SCRIPT = re.compile(r"<script(\s[^>]*)?>(.*?)</script>", re.S | re.I)


def git(*a: str) -> str:
    return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True, check=True).stdout


def names(text: str) -> set[str]:
    out = set()
    for m in TOP.finditer(text):
        out.add(m.group(1) or m.group(2))
    # 한 줄에 여러 선언: `let A=..; let B=..;` — 줄 맨 앞 선언 뒤의 `; let X=` 도 최상위
    for line in text.splitlines():
        if re.match(r"(?:const|let|var)\s", line):
            for m in re.finditer(r";\s*(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=", line):
                out.add(m.group(1))
    return out


def at_rev(rev: str, path: str) -> str | None:
    try:
        return git("show", f"{rev}:{path}")
    except subprocess.CalledProcessError:
        return None


def syntax_check(path: Path) -> list[str]:
    if not path.exists():
        return []
    node = shutil.which("node")
    if not node:
        return [f"node 없음 — {path.name} 문법 검사 건너뜀 (node 설치 필요)"]
    html = path.read_text(encoding="utf-8")
    blocks = []
    for m in SCRIPT.finditer(html):
        attrs = m.group(1) or ""
        if "src=" in attrs or re.search(r'type\s*=\s*["\']?(?!text/javascript|module)', attrs):
            continue
        line = html.count("\n", 0, m.start(2)) + 1
        blocks.append({"line": line, "code": m.group(2)})
    js = r"""
const fs=require('fs'); const B=JSON.parse(fs.readFileSync(process.argv[2],'utf8')); let bad=0;
for(const b of B){ try{ new Function(b.code); }catch(e){ bad++; console.log(`  <script> @${b.line}행: ${e.name}: ${e.message}`); } }
process.exit(bad?1:0);"""
    with tempfile.TemporaryDirectory() as td:
        bj = Path(td) / "b.json"; bj.write_text(json.dumps(blocks), encoding="utf-8")
        cj = Path(td) / "c.js"; cj.write_text(js, encoding="utf-8")
        r = subprocess.run([node, str(cj), str(bj)], capture_output=True, text=True)
    if r.returncode:
        return [f"{path.relative_to(ROOT)} 문법 오류:\n{r.stdout.rstrip()}{r.stderr.rstrip()}"]
    print(f"  ✓ {path.relative_to(ROOT)} <script> {len(blocks)}개 문법 OK")
    return []


def stale_build() -> str | None:
    src, out = ROOT / "apps-script" / "Index.html", ROOT / "index.html"
    if not out.exists():
        return "index.html 없음"
    s = src.read_text(encoding="utf-8")
    o = out.read_text(encoding="utf-8")
    # 빌드 산출물에서 심(shim)과 머리 주석을 걷어내면 원본과 같아야 함
    o2 = re.sub(r"<!-- 자동 생성:.*?-->\n", "", o, count=1)
    o2 = re.sub(r"(<title>MARKET TERMINAL</title>)\n<script>\n/\* GitHub Pages 용.*?</script>\n", r"\1", o2, count=1, flags=re.S)
    return None if o2 == s else "index.html 이 apps-script/Index.html 과 다름 → python scripts/build_pages.py 실행 후 커밋"


def lock_conflicts(base: str, owner: str | None) -> list[str]:
    p = ROOT / "ops" / "locks.json"
    if not p.exists():
        return []
    try:
        locks = json.loads(p.read_text(encoding="utf-8")).get("locks", [])
    except ValueError:
        return []   # 깨진 JSON 은 [5] 에서 실패 처리
    try:
        changed = set(git("diff", "--name-only", base).split()) | set(git("diff", "--name-only", "--cached", base).split())
    except subprocess.CalledProcessError:
        return []
    out = []
    for lk in locks:
        if owner and lk.get("owner") == owner:
            continue
        for f in changed:
            if fnmatch.fnmatch(f, lk["file"]):
                out.append(f"{f} 는 {lk['owner']} 잠금 중 ({lk.get('task')}, {lk.get('since')})")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="origin/main")
    ap.add_argument("--allow-removed", default="", help="일부러 지운 이름, 쉼표 구분")
    ap.add_argument("--owner", help="내 이름 (주면 남의 잠금 파일 수정 시 실패)")
    a = ap.parse_args()
    allow = {x.strip() for x in a.allow_removed.split(",") if x.strip()}
    fails, warns = [], []

    try:
        git("rev-parse", "--verify", a.base)
    except subprocess.CalledProcessError:
        print(f"✗ 기준 리비전 {a.base} 없음 — git fetch origin 먼저"); return 1

    print(f"[1] 최상위 이름 비교 ({a.base} → 작업 사본)")
    for path in WATCH:
        old = at_rev(a.base, path)
        cur_p = ROOT / path
        if old is None:
            continue
        if not cur_p.exists():
            fails.append(f"{path} 파일이 사라짐"); continue
        o, c = names(old), names(cur_p.read_text(encoding="utf-8"))
        gone = sorted(o - c - allow)
        added = sorted(c - o)
        ok_gone = sorted((o - c) & allow)
        print(f"  {path}: {len(o)} → {len(c)}" + (f"  +{', '.join(added)}" if added else "")
              + (f"  (허용된 삭제: {', '.join(ok_gone)})" if ok_gone else ""))
        if gone:
            fails.append(f"{path} 에서 사라진 이름: {', '.join(gone)}\n"
                         f"    → 머지/리베이스 중 남의 코드를 지운 것일 수 있음. 일부러 지웠다면 --allow-removed {','.join(gone)}")

    print("[2] <script> 문법 검사 (node new Function)")
    for p in (ROOT / "index.html", ROOT / "apps-script" / "Index.html"):
        fails += syntax_check(p)

    print("[3] 빌드 최신 여부")
    s = stale_build()
    if s:
        warns.append(s)
    else:
        print("  ✓ index.html 최신")

    print("[4] 잠금")
    lc = lock_conflicts(a.base, a.owner)
    (fails if a.owner else warns).extend(lc)
    if not lc:
        print("  ✓ 충돌 없음")

    print("[5] 충돌 표시·JSON")
    bad = []
    try:
        changed = set(git("diff", "--name-only", a.base).split())
    except subprocess.CalledProcessError:
        changed = set()
    for f in sorted(changed | {"ops/board.json", "ops/locks.json"}):
        p = ROOT / f
        if not p.is_file() or p.stat().st_size > 5_000_000:
            continue
        try:
            t = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if re.search(r"^(<{7}|>{7}) ", t, re.M) or re.search(r"^={7}$", t, re.M):
            bad.append(f"{f} 에 머지 충돌 표시(<<<<<<< / >>>>>>>)가 남아 있음")
        elif f.endswith(".json"):
            try:
                json.loads(t)
            except ValueError as e:
                bad.append(f"{f} JSON 깨짐: {e}")
    fails += bad
    if not bad:
        print("  ✓ 없음")

    for w in warns:
        print("⚠", w)
    for f in fails:
        print("✗", f)
    print("통과" if not fails else f"실패 {len(fails)}건 — 푸시 금지")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
