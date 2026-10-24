#!/usr/bin/env python3
"""화면 스킨 전수 측정 — 기본·엑셀(html.xl) 스킨에서 35개 화면 × 390·1300px 의 글자 대비·가로 넘침·잘림·작은 글자·어두운 배경 잔존.

  python3 scripts/skin_audit.py                    # 엑셀 스킨, 390·1300px, 전체 화면 → 표(마크다운) 출력
  python3 scripts/skin_audit.py --skin def         # 기본 스킨
  python3 scripts/skin_audit.py --views msg,rb     # 일부 화면만
  python3 scripts/skin_audit.py --detail           # 대비 미달 예시(글자색·배경·클래스·글자)도
  python3 scripts/skin_audit.py --root /tmp/before  # 다른 체크아웃(예: git worktree add /tmp/before <커밋>)을 서빙 — 전후 비교

10/24 겸이 "엑셀버전도 다 자동수정되는거지?"·"엑셀버전 톡방이 검정색"(req-dev-0d1eee58) 뒤 도입. UXUI 재검수도 같은 자로 잰다.
정의 (ui_smoke check_xl 과 같은 상수 — 여기 JS 를 ui_smoke 가 import):
  대비  : 자기 글자를 가진 보이는 요소의 글자색 vs 실제 바탕(조상 배경을 알파 합성, 없으면 흰색). 본문 4.5:1, 큰 글자(24px+ 또는 18.66px+ 굵게) 3:1,
          기호 한 글자(●■▲▼━ 등 — 그림 역할, WCAG 1.4.11)는 3:1. background-image(그라디언트·사진) 위 글자는 못 잼(한계).
  넘침  : 스크롤 상자 밖에서 오른쪽 끝 > 화면 폭+1 인 요소(팝업·상세 창·하단 시트 탭 제외).
  잘림  : ui_smoke CLIP_JS (자기 글자 + overflow≠visible 또는 ellipsis + scrollWidth > clientWidth+1).
  작은 글자: ui_smoke SMALL_JS (보이는 글자 < 11px).
  어두운 배경: 엑셀 스킨에서 상대 휘도 < 0.05 인 배경(8px 넘는 요소) — 다크 전용 색이 남은 곳. 의도된 검정 버튼(--amber 강조)도 잡힌다(참고 지표).
"""
from __future__ import annotations

import argparse
import asyncio
import glob
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import ui_smoke as u  # noqa: E402

CONTRAST_JS = r"""(sel)=>{ const P=s=>{const m=String(s).match(/rgba?\(([^)]+)\)/); if(!m) return null; const a=m[1].split(/[ ,\/]+/).filter(Boolean).map(Number); return [a[0],a[1],a[2],a.length>3?a[3]:1]};
 const L=c=>{const f=v=>{v/=255; return v<=.03928?v/12.92:Math.pow((v+.055)/1.055,2.4)}; return .2126*f(c[0])+.7152*f(c[1])+.0722*f(c[2])};
 const bgOf=e=>{ const st=[]; for(let p=e;p;p=p.parentElement){ const c=P(getComputedStyle(p).backgroundColor); if(c&&c[3]>0){ st.push(c); if(c[3]>=1) break; } }
   let r=[255,255,255]; for(let i=st.length-1;i>=0;i--){ const c=st[i]; r=[0,1,2].map(k=>c[k]*c[3]+r[k]*(1-c[3])); } return r; };
 const bad=[]; let n=0;
 for(const e of document.querySelectorAll(sel)){ if(e.closest('details:not([open])')||e.closest('canvas,svg')) continue;
   const own=[...e.childNodes].filter(c=>c.nodeType===3).map(c=>c.textContent).join('').trim(); if(!own) continue;
   const r=e.getBoundingClientRect(); if(!r.width||!r.height) continue;
   const cs=getComputedStyle(e); if(cs.visibility==='hidden'||+cs.opacity===0) continue; let fg=P(cs.color); if(!fg) continue; const bg=bgOf(e);
   fg=[0,1,2].map(k=>fg[k]*fg[3]+bg[k]*(1-fg[3]));
   const a=L(fg),b=L(bg), cr=(Math.max(a,b)+.05)/(Math.min(a,b)+.05), fs=parseFloat(cs.fontSize);
   const need=(fs>=24||(fs>=18.66&&+cs.fontWeight>=700)||/^[●○■□▲▼◆◇━─│·•★☆◀▶]$/.test(own))?3:4.5;
   n++; if(cr<need) bad.push([+cr.toFixed(2),cs.color,'rgb('+bg.map(x=>x|0).join(', ')+')',String(e.className||e.tagName).slice(0,20),own.slice(0,20)]); }
 return {n, bad}; }"""
OVER_JS = """(()=>{ const W=innerWidth, out=[]; for(const e of document.querySelectorAll('body *')){ if(!e.offsetWidth||e.closest('#mgpop,.drawer,#dr,.tabs,#xlrib,#xlfx,.tape')) continue;
  let p=e.parentElement, sc=false; while(p&&p!==document.body){ if(/(auto|scroll|hidden)/.test(getComputedStyle(p).overflowX)){ sc=true; break; } p=p.parentElement; }
  if(sc) continue; const r=e.getBoundingClientRect(); if(r.right>W+1) out.push(e.tagName+'.'+(e.className||'')+' '+(r.right|0)+' '+(e.innerText||'').slice(0,25)); } return out; })()"""
DARK_JS = """(()=>{ const P=s=>{const m=String(s).match(/rgba?\\(([^)]+)\\)/); if(!m) return null; const a=m[1].split(/[ ,\\/]+/).filter(Boolean).map(Number); return [a[0],a[1],a[2],a.length>3?a[3]:1]};
 const L=c=>{const f=v=>{v/=255; return v<=.03928?v/12.92:Math.pow((v+.055)/1.055,2.4)}; return .2126*f(c[0])+.7152*f(c[1])+.0722*f(c[2])};
 let n=0; for(const e of document.querySelectorAll('#root *')){ if(!e.offsetWidth||e.offsetWidth<=8||e.offsetHeight<=8||e.closest('details:not([open])')||e.tagName==='CANVAS'||e.tagName==='IMG') continue;
   const b=P(getComputedStyle(e).backgroundColor); if(b&&b[3]>.5&&L(b)<.05) n++; } return n; })()"""

# 컬러 이모지(엑셀 위장, req-dev-06b280d5): 보이는 글자 속 \p{Extended_Pictographic} 중 조상에 grayscale 필터가 없는 것(머리 .top 포함 안 함).
EMOJI_JS = r"""(()=>{ let n=0; const re=/\p{Extended_Pictographic}/gu; const tw=document.createTreeWalker(document.getElementById('root'),NodeFilter.SHOW_TEXT);
 while(tw.nextNode()){ const t=tw.currentNode, e=t.parentElement; if(!e||!e.offsetWidth||e.closest('details:not([open]) > :not(summary),script,style')) continue; const m=t.textContent.match(re); if(!m) continue;
   let g=false; for(let p=e;p;p=p.parentElement){ if(/grayscale/.test(getComputedStyle(p).filter)){ g=true; break; } } if(!g) n+=m.length; } return n; })()"""
# 문장 속 링크 구분(req-dev-3d26f6e6, WCAG 1.4.1 G183): 부모가 자기 글자를 가진 보이는 a 중 밑줄 없고 주변 글자와 명도 대비 3:1 미만.
LINK_JS = r"""(()=>{ const P=s=>{const m=String(s).match(/rgba?\(([^)]+)\)/); const a=m[1].split(/[ ,\/]+/).filter(Boolean).map(Number); return a;};
 const L=c=>{const f=v=>{v/=255; return v<=.03928?v/12.92:Math.pow((v+.055)/1.055,2.4)}; return .2126*f(c[0])+.7152*f(c[1])+.0722*f(c[2])};
 let n=0, bad=0; for(const a of document.querySelectorAll('#root a')){ const p=a.parentElement; if(!a.offsetWidth||!p||![...p.childNodes].some(c=>c.nodeType===3&&c.textContent.trim())) continue;
   const cs=getComputedStyle(a); if(a.classList.contains('tag')||a.classList.contains('sbtn')||/flex|block|grid/.test(cs.display)) continue; n++;
   const x=L(P(cs.color)), y=L(P(getComputedStyle(p).color)), cr=(Math.max(x,y)+.05)/(Math.min(x,y)+.05);
   if(cr<3&&!/underline/.test(cs.textDecorationLine)) bad++; } return {n, bad}; })()"""


async def page(b, port: int, w: int, skin: str):
    ctx = await b.new_context(viewport={"width": w, "height": 844}, has_touch=w < 700, is_mobile=w < 700)
    await ctx.add_init_script(f"try{{localStorage.setItem('mt_skin','{'xl' if skin == 'xl' else ''}')}}catch(e){{}}")
    pg = await ctx.new_page()
    await pg.goto(f"http://127.0.0.1:{port}/index.html", wait_until="load")
    await pg.wait_for_timeout(2000)
    return ctx, pg


async def measure(pg, w: int) -> dict:
    c = await pg.evaluate(f"({CONTRAST_JS})('#root *')")
    lk = await pg.evaluate(LINK_JS)
    return {"contrast": len(c["bad"]), "n": c["n"], "ex": c["bad"][:3], "over": len(await pg.evaluate(OVER_JS)),
            "emoji": await pg.evaluate(EMOJI_JS), "link": lk["bad"], "links": lk["n"],
            "clip": len(await pg.evaluate(u.CLIP_JS)), "small": await pg.evaluate(u.SMALL_JS), "dark": await pg.evaluate(DARK_JS)}


async def main(a) -> int:
    from playwright.async_api import async_playwright
    exe = (glob.glob("/opt/pw-browsers/chromium-*/chrome-linux*/chrome") or [None])[0]
    srv = u._serve(0)
    port = srv.server_address[1]
    rows: dict = {}
    async with async_playwright() as p:
        b = await p.chromium.launch(args=["--no-sandbox"], **({"executable_path": exe} if exe else {}))
        for w in a.widths:
            ctx, pg = await page(b, port, w, a.skin)
            hc = await pg.evaluate(f"({CONTRAST_JS})('.top *,.tape *,#subt *,.tabs *,#xlrib *,#xlfx *')")
            rows.setdefault("(머리·탭)", {})[w] = {"contrast": len(hc["bad"]), "n": hc["n"], "ex": hc["bad"][:3], "over": 0, "clip": 0, "small": 0, "dark": 0, "emoji": 0, "link": 0, "links": 0}
            for v in a.views or await pg.evaluate(u.ALL_JS):
                await pg.evaluate(f"setView({v!r})")
                await pg.wait_for_timeout(1800)
                rows.setdefault(v, {})[w] = await measure(pg, w)
            await ctx.close()
    srv.shutdown()
    W = a.widths
    print(f"| 화면 | " + " | ".join(f"대비 미달 {w}" for w in W) + " | " + " | ".join(f"넘침 {w}" for w in W) + " | "
          + " | ".join(f"잘림 {w}" for w in W) + " | 11px미만 | 어두운 배경 | 컬러 이모지 | 링크 구분 미달 |")
    print("|" + "---|" * (3 * len(W) + 5))
    tot = {k: 0 for k in ("contrast", "over", "clip", "small", "dark", "emoji", "link")}
    for v, r in rows.items():
        for x in r.values():
            for k in tot:
                tot[k] += x[k]
        print(f"| {v} | " + " | ".join(f"{r[w]['contrast']}/{r[w]['n']}" for w in W) + " | " + " | ".join(str(r[w]["over"]) for w in W) + " | "
              + " | ".join(str(r[w]["clip"]) for w in W) + f" | {sum(r[w]['small'] for w in W)} | {sum(r[w]['dark'] for w in W)} | {'/'.join(str(r[w]['emoji']) for w in W)} | {'/'.join(str(r[w]['link']) for w in W)} |")
    print(f"\n합계({a.skin}, {'·'.join(map(str, W))}px): 대비 미달 {tot['contrast']} · 넘침 {tot['over']} · 잘림 {tot['clip']} · 11px미만 {tot['small']} · 어두운 배경 {tot['dark']} · 컬러 이모지 {tot['emoji']} · 링크 구분 미달 {tot['link']}")
    if a.detail:
        for v, r in rows.items():
            for w in W:
                if r[w]["ex"]:
                    print(f"  {v}@{w}: {r[w]['ex']}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--skin", choices=["xl", "def"], default="xl")
    ap.add_argument("--widths", type=lambda s: [int(x) for x in s.split(",")], default=[390, 1300])
    ap.add_argument("--views", type=lambda s: [x for x in s.split(",") if x], default=None)
    ap.add_argument("--detail", action="store_true")
    ap.add_argument("--root", default=None, help="서빙할 폴더(index.html 이 있는 체크아웃)")
    args = ap.parse_args()
    if args.root:
        u.SERVE = Path(args.root).resolve()
    sys.exit(asyncio.run(main(args)))
