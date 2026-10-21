"""apps-script/Index.html(공용 셸) + tab_*.html 분리 검사 — include 가 전부 풀리는지, 화면 파일 사이에 같은 최상위 이름이 없는지,
빌드된 index.html 에 탭·화면 id 가 모두 남아 있는지 (네트워크·브라우저 없이 텍스트만 검사)."""
import re
import subprocess
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from build_pages import INCLUDE, SRC_DIR, build, includes_of, resolve_includes, screen_source  # noqa: E402
from check_functions import names  # noqa: E402

SHELL = (SRC_DIR / "Index.html").read_text(encoding="utf-8")
TABS = includes_of(SHELL)
# 분리 전 화면이 갖고 있던 상단 탭(data-g)·하위 화면(view 키)·고정 요소 id — 하나라도 빠지면 탭이 조용히 사라진 것
GROUPS = ["home", "my", "life", "mkt", "daily", "res", "quant", "study", "sys"]
VIEWS = ["home", "my", "life", "kr", "us", "heat", "mdkr", "mdus", "bond", "deriv", "daily", "cmt", "score", "views", "brief",
         "rep", "val", "dart", "rb", "chain", "sig", "study", "lab", "mom", "pf", "isa", "edu", "apt", "eng", "sysb", "sysc", "syso"]
IDS = ["brand", "stb", "clock", "gen", "sq", "sres", "tape", "subt", "root", "bd", "dr", "dr-t", "dr-s", "dr-x", "dr-b"]
# 탭 파일마다 반드시 있어야 하는 대표 함수 (파일을 옮기거나 지웠을 때 바로 드러나게)
OWNS = {"tab_market": ["marketView", "heatView", "mdView"], "tab_home": ["homeView"], "tab_daily": ["dailyView", "viewsView", "briefView"],
        "tab_my": ["myView", "myRun", "myFetch", "myRender"], "tab_life": ["lifeView"], "tab_research": ["repView", "valView", "dartView"],
        "tab_quant": ["chainView", "sigView", "studyView", "labView", "momView", "pfView"], "tab_bond": ["bondView", "bondNow"], "tab_rboard": ["rbView", "rbWeek"], "tab_isalab": ["ilabView", "ilabEval", "ilabBoot"],
        "tab_study": ["eduView", "aptView", "engView"], "tab_committee": ["cmtView", "cmtUSView", "dotStripHtml"],
        "tab_duel": ["decBox", "ticketBox", "scoreView"], "tab_mkt_deriv": ["derivView"], "tab_mkt_macro": ["macroView"], "tab_system": ["sysBoardView", "sysChgView", "sysOpsView", "SYSV"],
        "tab_detail": ["openDetail", "renderDetail", "drawChart"]}


def test_every_include_resolves():
    assert len(TABS) >= 10
    for n in TABS:
        p = SRC_DIR / f"{n}.html"
        assert p.exists(), f"include('{n}') 대상 {p.name} 없음"
        assert n.startswith("tab_"), f"{n}: GAS 는 루트 파일만 → tab_ 접두사"
        body = p.read_text(encoding="utf-8")
        assert "<script>" in body and "</script>" in body, f"{n}: <script> 블록 없음"
        assert not INCLUDE.search(body), f"{n}: 탭 파일 안에 include 가 있음 (한 단계만 허용)"
    src = screen_source()
    assert not INCLUDE.search(src)
    assert len(set(TABS)) == len(TABS), "같은 탭을 두 번 include"


def test_missing_include_fails_loudly():
    with pytest.raises(FileNotFoundError):
        resolve_includes("<?!= include('tab_없는파일') ?>")
    with pytest.raises(RuntimeError):
        resolve_includes("<?!= include('a') ?>", read=lambda n: "<?!= include('a') ?>")


def test_no_duplicate_top_level_names_across_files():
    seen = {}
    for p in [SRC_DIR / "Index.html", *(SRC_DIR / f"{n}.html" for n in TABS)]:
        for nm in names(p.read_text(encoding="utf-8")):
            assert nm not in seen, f"최상위 이름 {nm} 이 {seen[nm]} 와 {p.name} 양쪽에 있음"
            seen[nm] = p.name
    for tab, fns in OWNS.items():
        for f in fns:
            assert seen.get(f) == f"{tab}.html", f"{f} 는 {tab}.html 에 있어야 함 (지금: {seen.get(f)})"
    for f in ["$", "esc", "num", "pct", "render", "setView", "GROUPS", "load", "loadLive", "tape", "shortNm", "med"]:
        assert seen.get(f) == "Index.html", f"공용 {f} 는 Index.html(셸)에 있어야 함"


def test_built_index_has_all_tabs_and_ids():
    out = build(screen_source())
    for g in GROUPS:
        assert f'data-g="{g}"' in out, f"상단 탭 {g} 없음"
    for v in VIEWS:
        assert re.search(rf"\[\s*'{v}'\s*,", out), f"GROUPS 에 화면 {v} 없음"
        if v not in ("mdus", "sysb", "sysc", "syso"):   # mdus 는 render() 의 마지막 else, sys* 는 SYSV 표로 분기
            assert f"v==='{v}'" in out, f"render() 가 화면 {v} 를 그리지 않음"
    for i in IDS:
        assert f'id="{i}"' in out, f"고정 요소 #{i} 없음"
    assert "google.script.run" in out and "window.google = { script: { run: runner() } }" in out
    assert "<?!=" not in out
    # 커밋된 index.html 이 지금 원본과 같은가 (빌드 잊음 방지)
    committed = (ROOT / "index.html").read_text(encoding="utf-8")
    assert committed == out, "index.html 이 낡음 → python scripts/build_pages.py"


@pytest.mark.skipif(not shutil.which("node"), reason="node 없음")
def test_every_tab_script_parses():
    js = "const fs=require('fs');let bad=0;for(const f of process.argv.slice(2)){const h=fs.readFileSync(f,'utf8');for(const m of h.matchAll(/<script>([\\s\\S]*?)<\\/script>/g)){try{new Function(m[1]);}catch(e){bad++;console.log(f+': '+e.message);}}}process.exit(bad?1:0);"
    files = [str(SRC_DIR / "Index.html"), *(str(SRC_DIR / f"{n}.html") for n in TABS)]
    r = subprocess.run(["node", "-e", js, *files], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
