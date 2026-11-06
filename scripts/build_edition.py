"""판(edition)별 화면 빌드 — 리팩토링 v1(11/1 결재, docs/refactor_v1_inventory.md §6 '내부 탭 숨김 · 11/7 전 필수').

  internal(내부판, 기본) = scripts/build_pages.py 결과 그대로(루트 index.html 과 바이트 동일).
  public(범용판) = 내부 탭 9개(my·life·isalab·msgr·duel·study·committee·rboard·system)를 화면에서 뺀다.
    - 다른 탭이 함수를 빌려 쓰지 않는 6개 파일은 include 자체를 빼고 Index.html 이 부르는 이름만 빈 껍데기로 둔다.
    - 빌려 쓰이는 3개(my·duel·committee — 홈·파생·부동산이 함수를 씀)는 코드는 남기고 메뉴·주소(?v=)·setView 로 못 연다
      (공용 함수 분리는 프론트 요청, 11/12 이후 include 제외로 승격).
    - 데이터가 범용판 제외 목록(§3-1 portfolios·decisions)인 뷰(pf·score)도 숨긴다.
  저장소 기본 판 = 환경변수 MS_EDITION → 루트 `.edition` 파일(범용판 스냅샷에 scripts/migrate_v1.py 가 'public' 으로 씀) → internal.
  build_pages.py 는 프론트 잠금 중(11/1 links-scale)이라 여기 따로 둔다 — build_pages 는 고치지 않고 import 만.

  python3 scripts/build_edition.py --edition public --out /tmp/pub/index.html
  python3 scripts/build_edition.py                    # 저장소 기본 판으로 루트 index.html (내부판이면 build_pages 와 같음)
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_pages as bp  # noqa: E402

ROOT = bp.ROOT
EDITIONS = ("internal", "public")
# 범용판에서 include 를 통째로 빼는 내부 탭 파일 → 그 자리에 넣는 빈 껍데기(Index.html 이 이름을 참조하는 것만)
PUBLIC_DROP_TABS = {
    "tab_life": "let LIFE=null; function lifeView(){return '';}",
    "tab_freeman": "let MYHQ=null; function freeView(){return '';} function myHqLoad(){return Promise.resolve([]);} function myHqHtml(){return '';}",
    "tab_isalab": "function ilabView(){return '';}",
    "tab_msgr": "function msgView(){return '';}",
    "tab_study": "function eduView(){return '';} function aptView(){return '';} function engView(){return '';} function opicView(){return '';}",
    "tab_rboard": "function rbView(){return '';}",
    "tab_system": "const SYSV={}; const sysNm=x=>String(x??'');",
}
# 코드는 남기되 메뉴·주소로 못 여는 탭(다른 탭이 함수를 씀 — 프론트 분리 요청)
PUBLIC_KEEP_HIDDEN_TABS = ("tab_my", "tab_duel", "tab_committee")
# 범용판에서 숨기는 뷰 키(GROUPS·SUBV)
PUBLIC_HIDE_VIEWS = ("my", "life", "free", "isa", "pf", "msg", "sysb", "sysc", "syso", "edu", "apt", "eng", "opic", "cmt", "score", "rb")
GROUPS_ANCHOR = "const SUBP={}; for(const [p,a] of Object.entries(SUBV)) for(const [k] of a) SUBP[k]=p;"


def default_edition() -> str:
    e = (os.environ.get("MS_EDITION") or "").strip()
    if not e:
        try:
            e = (ROOT / ".edition").read_text(encoding="utf-8").strip()
        except OSError:
            e = ""
    return e if e in EDITIONS else "internal"


def prune_js() -> str:
    hide = ",".join(f"'{v}'" for v in PUBLIC_HIDE_VIEWS)
    return ("\n/* 범용판(scripts/build_edition.py public): 내부 탭 숨김 — 메뉴·하위 줄·?v= 주소·setView 모두 막는다 */\n"
            "(function(){ const H=new Set([" + hide + "]);\n"
            "  for(const g of Object.keys(GROUPS)){ GROUPS[g]=GROUPS[g].flatMap(([k,n])=>{ if(!H.has(k)) return [[k,n]];\n"
            "      const kids=(SUBV[k]||[]).filter(x=>!H.has(x[0])); delete SUBV[k]; if(!kids.length) return [];\n"
            "      if(kids.length>1) SUBV[kids[0][0]]=kids; return [[kids[0][0],kids[0][1]]]; });\n"
            "    if(!GROUPS[g].length) delete GROUPS[g]; }\n"
            "  for(const k of Object.keys(SUBV)){ SUBV[k]=SUBV[k].filter(x=>!H.has(x[0])); if(!SUBV[k].length) delete SUBV[k]; }\n"
            "  for(const k of Object.keys(SUBP)) delete SUBP[k]; for(const [p,a] of Object.entries(SUBV)) for(const [k] of a) SUBP[k]=p;\n"
            "  document.querySelectorAll('.tabs button').forEach(b=>{ if(!GROUPS[b.dataset.g]) b.remove(); });\n"
            "  const sv=setView; setView=function(v){ return sv(H.has(v)?'home':v); }; window.MS_EDITION='public'; })();\n")


def build_edition(edition: str = "internal", read=None) -> str:
    """판별 빌드. internal = bp.build(bp.screen_source(read)) 와 바이트 동일. read(name) 은 build_pages 와 같은 뜻."""
    if edition not in EDITIONS:
        raise ValueError(f"edition 은 {EDITIONS} 중 하나: {edition!r}")
    if edition == "internal":
        return bp.build(bp.screen_source(read))
    base = read or (lambda n: (bp.SRC_DIR / f"{n}.html").read_text(encoding="utf-8"))

    def rd(name: str) -> str:
        if name in PUBLIC_DROP_TABS:
            return f"<!-- 범용판: {name} 제외(내부 탭) -->\n<script>{PUBLIC_DROP_TABS[name]}</script>"
        return base(name)
    src = bp.screen_source(rd)
    if GROUPS_ANCHOR not in src:
        raise RuntimeError("범용판 빌드: Index.html 의 SUBP 줄을 못 찾음 — build_edition.GROUPS_ANCHOR 갱신 필요")
    out = bp.build(src.replace(GROUPS_ANCHOR, GROUPS_ANCHOR + prune_js(), 1))
    return out.replace("<title>MARKET TERMINAL</title>", "<title>MARKET TERMINAL</title>\n<!-- edition: public (범용판) -->", 1)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--edition", choices=EDITIONS, default=default_edition())
    ap.add_argument("--out", help="출력 경로 (기본: 루트 index.html — 저장소 기본 판만 허용)")
    a = ap.parse_args(argv)
    out = Path(a.out) if a.out else ROOT / "index.html"
    if a.edition != default_edition() and out.resolve() == (ROOT / "index.html").resolve():
        print(f"루트 index.html 은 이 저장소 기본 판({default_edition()})으로만 만든다 — --out 으로 다른 곳을 지정", file=sys.stderr)
        return 2
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_edition(a.edition), encoding="utf-8")
    print(f"{out} 생성 · 판 {a.edition}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
