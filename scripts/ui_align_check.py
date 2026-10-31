#!/usr/bin/env python3
"""화면 정렬·대칭 자동 검사 — HTML 하나를 여러 화면 폭으로 열어 좌우 여백·행 정렬·넘침·잘림을 잰다.

  python3 scripts/ui_align_check.py docs/uxui/2026-10-31_mockup_home.html
  python3 scripts/ui_align_check.py index.html --widths 390,1440 --query '?v=my' --shots /tmp/out
  python3 scripts/ui_align_check.py page.html --panel '.p' --edge '.top'      # 다른 화면에 붙일 때 선택자만 바꿈

10/31 겸이 "uxui는 그 어떤 화면비율에서도 대칭성이랑 정렬 유지" 뒤 UXUI 도입(docs/uxui/2026-10-31_bloomberg_redesign.md §5).
프론트가 CI 에 붙일 수 있게 대상 HTML 경로·선택자를 인자로 받는다. 실패가 하나라도 있으면 종료코드 1.

측정 정의 (재측정도 이 정의만 쓴다):
  패널    : --panel 선택자(기본 [data-panel])에 걸리는 보이는 요소. 고정 위치(position:fixed) 조상 안은 제외.
  좌우 여백: L = 패널 왼쪽 끝 최솟값, R = 화면 폭(clientWidth) − 패널 오른쪽 끝 최댓값. |L − R| ≤ tol(1px).
  공통 선  : --edge 선택자(기본 [data-edge]) 요소의 '안쪽 상자'(테두리 상자 − 좌우 padding) 좌우 끝이 L 과 (폭 − R) 에 각각 ≤ tol.
  행 정렬  : 세로 범위가 겹치는 패널끼리 한 행. 같은 행의 윗변 최대−최소, 아랫변 최대−최소 각각 ≤ tol.
  넘침    : 크기 있는 보이는 요소의 오른쪽 끝 > 화면 폭 + tol 또는 왼쪽 끝 < −tol (스크롤 상자 안쪽·고정 위치 요소는 제외)
            + 패널 안 요소가 그 패널 상자 밖으로 tol 넘게 나간 것(경보 행처럼 패널 가장자리까지 채우는 것은 허용).
  잘림    : 자기 글자를 가진 요소 중 (overflow-x ≠ visible 또는 text-overflow = ellipsis) 이고 scrollWidth > clientWidth + 1.
"""
from __future__ import annotations

import argparse
import asyncio
import glob
import json
import sys
from pathlib import Path

DEFAULT_WIDTHS = [320, 360, 390, 414, 768, 1024, 1280, 1440, 1920]
TOL = 1.0

MEASURE_JS = r"""([panelSel, edgeSel, tol])=>{
 const vw=document.documentElement.clientWidth;
 const vis=e=>{const r=e.getBoundingClientRect(); const cs=getComputedStyle(e); return r.width>0&&r.height>0&&cs.visibility!=='hidden';};
 const inFixed=e=>{for(let p=e;p&&p!==document.body;p=p.parentElement){ if(getComputedStyle(p).position==='fixed') return true;} return false;};
 const box=e=>{const r=e.getBoundingClientRect(); return {l:r.left,r:r.right,t:r.top+scrollY,b:r.bottom+scrollY};};
 const panels=[...document.querySelectorAll(panelSel)].filter(e=>vis(e)&&!inFixed(e));
 const P=panels.map(box);
 const out={vw, panels:P.length, gutterL:null, gutterR:null, gutterDiff:null, rows:[], rowTopErr:0, rowBotErr:0, edgeErr:0, overflow:[], clip:[]};
 if(P.length){
   const L=Math.min(...P.map(p=>p.l)), Rr=Math.max(...P.map(p=>p.r));
   out.gutterL=+L.toFixed(2); out.gutterR=+(vw-Rr).toFixed(2); out.gutterDiff=+Math.abs(L-(vw-Rr)).toFixed(2);
   for(const e of document.querySelectorAll(edgeSel)){ if(!vis(e)) continue; const r=e.getBoundingClientRect(), cs=getComputedStyle(e);
     const il=r.left+parseFloat(cs.paddingLeft)+parseFloat(cs.borderLeftWidth), ir=r.right-parseFloat(cs.paddingRight)-parseFloat(cs.borderRightWidth);
     out.edgeErr=Math.max(out.edgeErr,+Math.abs(il-L).toFixed(2),+Math.abs(ir-Rr).toFixed(2)); }
   const S=[...P].sort((a,b)=>a.t-b.t); const rows=[];
   for(const p of S){ const row=rows.find(rw=>rw.some(q=>p.t<q.b-tol&&q.t<p.b-tol)); if(row) row.push(p); else rows.push([p]); }
   for(const rw of rows){ const te=Math.max(...rw.map(p=>p.t))-Math.min(...rw.map(p=>p.t)), be=Math.max(...rw.map(p=>p.b))-Math.min(...rw.map(p=>p.b));
     out.rows.push({n:rw.length,top:+te.toFixed(2),bottom:+be.toFixed(2)}); out.rowTopErr=Math.max(out.rowTopErr,+te.toFixed(2)); out.rowBotErr=Math.max(out.rowBotErr,+be.toFixed(2)); }
 }
 const desc=e=>(e.tagName.toLowerCase()+(e.className&&typeof e.className==='string'?'.'+e.className.trim().split(/\s+/).join('.'):'')+' "'+(e.textContent||'').trim().slice(0,24)+'"');
 const inScroller=e=>{for(let p=e.parentElement;p&&p!==document.body;p=p.parentElement){const o=getComputedStyle(p).overflowX; if(o==='auto'||o==='scroll') return true;} return false;};
 for(const e of document.querySelectorAll('body *')){
   if(!vis(e)||inFixed(e)||inScroller(e)) continue; const r=e.getBoundingClientRect();
   if(r.right>vw+tol||r.left<-tol){ out.overflow.push(desc(e)+' '+Math.round(r.left)+'~'+Math.round(r.right)); continue; }
   const pn=e.closest(panelSel); if(pn&&pn!==e){ const q=pn.getBoundingClientRect(); if(r.right>q.right+tol||r.left<q.left-tol) out.overflow.push('패널 밖 '+desc(e)); }
   const own=[...e.childNodes].some(c=>c.nodeType===3&&c.textContent.trim()); if(!own) continue;
   const cs=getComputedStyle(e); if((cs.overflowX!=='visible'||cs.textOverflow==='ellipsis')&&e.scrollWidth>e.clientWidth+1) out.clip.push(desc(e));
 }
 out.overflow=out.overflow.slice(0,8); out.clip=out.clip.slice(0,8); return out; }"""


def judge(m: dict, tol: float = TOL) -> list[str]:
    """측정값 → 실패 사유 목록(빈 목록 = 통과). 브라우저 없이 테스트할 수 있게 분리."""
    bad = []
    if not m.get("panels"):
        bad.append("패널 0개(선택자 확인)")
        return bad
    if m["gutterDiff"] is not None and m["gutterDiff"] > tol:
        bad.append(f"좌우 여백 차 {m['gutterDiff']}px (L {m['gutterL']} / R {m['gutterR']})")
    if m.get("edgeErr", 0) > tol:
        bad.append(f"공통 세로선 어긋남 {m['edgeErr']}px")
    if m.get("rowTopErr", 0) > tol:
        bad.append(f"행 윗변 오차 {m['rowTopErr']}px")
    if m.get("rowBotErr", 0) > tol:
        bad.append(f"행 아랫변 오차 {m['rowBotErr']}px")
    if m.get("overflow"):
        bad.append(f"넘침 {len(m['overflow'])}: {m['overflow'][0]}")
    if m.get("clip"):
        bad.append(f"잘림 {len(m['clip'])}: {m['clip'][0]}")
    return bad


def _chromium() -> dict:
    exe = (glob.glob("/opt/pw-browsers/chromium-*/chrome-linux*/chrome") or [None])[0]
    return {"executable_path": exe} if exe else {}


def target_url(target: str) -> str:
    if target.startswith(("http://", "https://", "file://")):
        return target
    return Path(target).resolve().as_uri()


async def measure(target: str, sizes: list[tuple[int, int]], queries: list[str], panel: str, edge: str,
                  shots: str | None = None, tol: float = TOL, wait_ms: int = 600) -> list[dict]:
    from playwright.async_api import async_playwright
    res = []
    async with async_playwright() as p:
        b = await p.chromium.launch(args=["--no-sandbox"], **_chromium())
        for q in queries:
            for w, h in sizes:
                pg = await b.new_page(viewport={"width": w, "height": h})
                try:
                    await pg.goto(target_url(target) + q, wait_until="networkidle", timeout=30000)
                except Exception:
                    await pg.goto(target_url(target) + q, wait_until="load")
                await pg.wait_for_timeout(wait_ms)
                m = await pg.evaluate(MEASURE_JS, [panel, edge, tol])
                if shots:
                    Path(shots).mkdir(parents=True, exist_ok=True)
                    tag = (q.strip("?").replace("=", "_").replace("&", "_") + "_") if q else ""
                    await pg.screenshot(path=str(Path(shots) / f"align_{tag}{w}.png"), full_page=True)
                await pg.close()
                res.append({"query": q, "w": w, "h": h, "m": m, "bad": judge(m, tol)})
        await b.close()
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("target", help="대상 HTML 경로(또는 URL)")
    ap.add_argument("--widths", default=",".join(map(str, DEFAULT_WIDTHS)), help="쉼표 구분 폭(px)")
    ap.add_argument("--height", type=int, default=900)
    ap.add_argument("--query", action="append", default=None, help="URL 뒤에 붙일 질의(여러 번 가능, 예 '?v=my')")
    ap.add_argument("--panel", default="[data-panel]")
    ap.add_argument("--edge", default="[data-edge]")
    ap.add_argument("--shots", default=None, help="스크린샷 폴더(align_<폭>.png)")
    ap.add_argument("--tol", type=float, default=TOL)
    ap.add_argument("--json", action="store_true", help="측정 원값 JSON 출력")
    a = ap.parse_args(argv)
    sizes = [(int(w), a.height) for w in a.widths.split(",") if w.strip()]
    res = asyncio.run(measure(a.target, sizes, a.query or [""], a.panel, a.edge, a.shots, a.tol))
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
    print("| 화면 | 폭 | 패널 | 좌·우 여백 | 여백 차 | 공통선 | 행 윗/아랫변 오차 | 넘침 | 잘림 | 판정 |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    nbad = 0
    for r in res:
        m = r["m"]
        nbad += bool(r["bad"])
        print(f"| {r['query'] or '기본'} | {r['w']} | {m['panels']} | {m['gutterL']} / {m['gutterR']} | {m['gutterDiff']} | {m['edgeErr']} | "
              f"{m['rowTopErr']} / {m['rowBotErr']} | {len(m['overflow'])} | {len(m['clip'])} | {'통과' if not r['bad'] else '실패: ' + '; '.join(r['bad'])} |")
    print(f"\n{len(res) - nbad}/{len(res)} 통과")
    return 1 if nbad else 0


if __name__ == "__main__":
    sys.exit(main())
