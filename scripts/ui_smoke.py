"""화면 렌더 스모크 — 빌드된 index.html 을 로컬 서버 + 헤드리스 크롬으로 열어 탭별 렌더·콘솔 에러 확인.
사용: python3 scripts/ui_smoke.py [--root DIR] [view ...]   (기본: Index.html GROUPS 의 전체 뷰 29개 — 감사 경-1 10/17, 예전 기본 7뷰는 QUICK)
  --root: 저장소 대신 다른 폴더를 서빙 (A1 시범: `python3 scripts/data_branch.py site --out _site reports/detail/US` 로 만든 Pages 산출물 검사)
필요: playwright(파이썬) + 크로미움. 클라우드 세션은 /opt/pw-browsers/chromium-*/chrome-linux*/chrome 사용.
10/17 PB 화면 수정 사고 4건(STUDY 멈춤 등) 뒤 도입 — 화면을 고치면 커밋 전에 돌린다."""
from __future__ import annotations

import asyncio
import glob
import http.server
import socketserver
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUICK = ["home", "edu", "apt", "rep", "deriv", "bond", "my"]
VIEWS: list[str] = []   # 비우면 페이지의 GROUPS 에서 전체 뷰를 읽는다 (탭이 늘면 자동 포함)
ALL_JS = "[...new Set([...Object.values(GROUPS).flat(),...Object.values(typeof SUBV==='object'?SUBV:{}).flat()].map(x=>x[0]))]"   # SUBV = QUANT 두 번째 줄(10/21)
MIN_ALL = 29   # 10/17 기준 전체 뷰 수 — 이보다 적게 읽히면 GROUPS 파싱 실패로 보고 BAD
SERVE = ROOT


def _serve(port: int) -> socketserver.TCPServer:
    class Q(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):  # 요청 로그 숨김
            pass
    h = lambda *a, **k: Q(*a, directory=str(SERVE), **k)  # noqa: E731
    socketserver.TCPServer.allow_reuse_address = True
    s = socketserver.TCPServer(("127.0.0.1", port), h)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s


async def run(views: list[str], port: int) -> int:
    from playwright.async_api import async_playwright
    exe = (glob.glob("/opt/pw-browsers/chromium-*/chrome-linux*/chrome") or [None])[0]
    bad = 0
    async with async_playwright() as p:
        b = await p.chromium.launch(args=["--no-sandbox"], **({"executable_path": exe} if exe else {}))
        pg = await b.new_page(viewport={"width": 1300, "height": 900})
        errs: list[str] = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(f"http://127.0.0.1:{port}/index.html", wait_until="load")
        await pg.wait_for_timeout(2000)
        if not views:
            views = await pg.evaluate(ALL_JS)
            print(f"전체 뷰 {len(views)}개: {' '.join(views)}")
            if len(views) < MIN_ALL:
                print(f"BAD 뷰 목록 {len(views)}개 < {MIN_ALL} (GROUPS 읽기 실패?)")
                bad += 1
        for v in views:
            errs.clear()
            await pg.evaluate(f"setView({v!r})")
            await pg.wait_for_timeout(2500)
            txt = await pg.evaluate("document.querySelector('#root').innerText")
            stuck = txt.strip().startswith("LOADING") or len(txt.strip()) < 40
            ok = not errs and not stuck
            bad += not ok
            print(f"{'OK ' if ok else 'BAD'} {v:6s} {len(txt):6d}자" + (f" · 에러: {errs[0][:160]}" if errs else "") + (" · LOADING/빈 화면" if stuck else ""))
        bad += await check_fresh(b, port)
        bad += await check_us_detail(b, port)
        bad += await check_oneliner(b, port)
        bad += await check_my_ledger(b, port)
        bad += await check_my_first_screen(b, port)
        bad += await check_re_private(b, port)
        bad += await check_re_drill(b, port)
        bad += await check_re_zoom(b, port)
        bad += await check_cmt_us(b, port)
        bad += await check_dotplot_lean(b, port)
        bad += await check_score(b, port)
        bad += await check_eng(b, port)
        bad += await check_macro_popup(b, port)
        bad += await check_syn(b, port)
        bad += await check_deriv_top(b, port)
        bad += await check_duel_toggle(b, port)
        bad += await check_macro_bond_top(b, port)
        bad += await check_research_board(b, port)
        bad += await check_msg_popup(b, port)
        bad += await check_msg_thread(b, port)
        bad += await check_uxui_rest(b, port)
        bad += await check_head_clip(b, port)
        bad += await check_xl(b, port)
        bad += await check_xl_beyond(b, port)
        bad += await check_links_pcr(b, port)
        bad += await check_hf_why(b, port)
        # bad += await check_all_top(b, port)   # 10/26 롤백(TOP_ALL_TABS=false) — 다시 켜면 복구
        bad += await check_re_ga(b, port)
        bad += await check_intraday_bar(b, port)
        bad += await check_btc_detail(b, port)
        bad += await check_deriv_tv(b, port)
        await b.close()
    return bad


LATE = {"checked_at": "2026-10-16 18:00", "n": 21, "regress_today": [{"at": "2026-10-16 17:00", "path": "reports/detail/US/_index.json", "existing": "2026-10-16", "new": "2026-10-15", "mode": "detail_us"}],
        "late": [{"id": "derivs", "path": "reports/derivs.json", "expected": "2026-10-16", "actual": "2026-10-15", "mode": "briefing reports", "fix": "gh workflow run briefing.yml -f mode=derivs", "desc": "옵션 보드"}]}


async def check_fresh(b, port: int) -> int:
    """상단 신선도 배지: 실제 파일로 '데이터 정상'/'⚠ 늦은 데이터' 중 하나가 보이는지 + 가짜 late 2건 주입 시 빨간 배지·팝업 목록."""
    import json as _json
    bad = 0
    for label, body in (("실파일", None), ("늦음 주입", _json.dumps(LATE, ensure_ascii=False))):
        pg = await b.new_page(viewport={"width": 1300, "height": 900})
        errs: list[str] = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        if body:
            await pg.route("**/reports/freshness.json*", lambda r: r.fulfill(status=200, content_type="application/json", body=body))
        await pg.goto(f"http://127.0.0.1:{port}/index.html", wait_until="load")
        await pg.wait_for_timeout(2500)
        txt = (await pg.evaluate("(document.querySelector('#fresh')||{}).textContent||''")).strip()
        cls = await pg.evaluate("(document.querySelector('#fresh')||{}).className||''")
        ok = (txt.startswith("데이터 정상") or txt.startswith("⚠ 늦은 데이터")) if not body else (txt == "⚠ 늦은 데이터 2" and "bad" in cls)
        if body and ok:
            await pg.click("#fresh")
            await pg.wait_for_timeout(300)
            pop = await pg.evaluate("document.querySelector('#dr-b').innerText")
            ok = "reports/derivs.json" in pop and "mode=derivs" in pop and "역행 차단" in pop
        ok = ok and not errs
        bad += not ok
        print(f"{'OK ' if ok else 'BAD'} 신선도배지({label}) '{txt}'" + (f" · 에러: {errs[0][:160]}" if errs else ""))
        await pg.close()
    return bad


async def check_deriv_top(b, port: int) -> int:
    """파생 탭 맨 위 '파생 한눈에'(10/20 겸이): 390px 에서 첫 패널 · 카드 4개+ · '시사점(리스크 관점)' · 버튼 44px · 가로 넘침 없음."""
    pg = await b.new_page(viewport={"width": 390, "height": 844})
    errs: list[str] = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    await pg.goto(f"http://127.0.0.1:{port}/index.html", wait_until="load")
    await pg.wait_for_timeout(1500)
    await pg.evaluate("setView('deriv')")
    await pg.wait_for_timeout(2500)
    r = await pg.evaluate("""(()=>{ const t=document.getElementById('dvTop'), f=document.querySelector('#root .p'); if(!t) return null;
      const bt=t.querySelector('button'); return {first:f===t, n:t.querySelectorAll('.dvtc').length, so:t.innerText.includes('시사점(리스크 관점)'),
      h:bt?bt.getBoundingClientRect().height:0, over:document.documentElement.scrollWidth-document.documentElement.clientWidth}; })()""")
    ok = bool(r) and r["first"] and r["n"] >= 4 and r["so"] and r["h"] >= 44 and r["over"] <= 1 and not errs
    print(f"{'OK ' if ok else 'BAD'} 파생 한눈에(390px) {r}" + (f" · 에러: {errs[0][:160]}" if errs else ""))
    await pg.close()
    return not ok


async def check_research_board(b, port: int) -> int:
    """QUANT › 연구 보드(UXUI·퀀트 10/21, 7→4 탭): QUANT 기본 화면 = 연구 보드 · 390px 첫 화면(844px) 안에 단계 5칸(44px)·판정 개수·
    이번 주 할 일·도전(ask 퀀트) · 가로 넘침 없음 · 두 번째 줄로 옛 화면(검증 스터디·전략 연구소·모멘텀·ISA) 이동 시 상위 탭 강조 유지."""
    bad = 0
    for w, h in ((390, 844), (1300, 900)):
        pg = await b.new_page(viewport={"width": w, "height": h})
        errs: list[str] = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(f"http://127.0.0.1:{port}/index.html", wait_until="load")
        await pg.wait_for_timeout(1500)
        await pg.evaluate("document.querySelector('.tabs button[data-g=quant]').click()")
        await pg.wait_for_timeout(2500)
        r = await pg.evaluate("""(()=>{ const t=document.getElementById('rbTop'), f=document.querySelector('#root .p'); if(!t) return {v:view};
          const st=[...t.querySelectorAll('.rbst button')], ch=t.querySelector('.rbch'), W=innerWidth;
          const over=[...document.querySelectorAll('#root *, #subt *')].filter(e=>{const b=e.getBoundingClientRect(); return b.width&&b.right>W+1;}).length;
          return {v:view, first:f===t, n:st.length, h:Math.min(...st.map(x=>x.getBoundingClientRect().height)), txt:t.innerText.includes('이번 주 할 일')&&t.innerText.includes('겸이 할 일'),
            ask:!!ch&&ch.innerText.includes('ask 퀀트'), bottom:Math.round(ch?ch.getBoundingClientRect().bottom:9999), over,
            cards:document.querySelectorAll('#root .rbc').length, sub2:[...document.querySelectorAll('#subt .subt2 button')].map(x=>x.textContent+':'+Math.round(x.getBoundingClientRect().height))}; })()""")
        nav = []
        for v, top, chip in (("lab", "연구 보드", "전략 연구소"), ("mom", "시그널·모멘텀", "모멘텀"), ("isa", "모의·ISA", "ISA 실험실"), ("study", "연구 보드", "검증 스터디")):
            await pg.evaluate(f"(([...document.querySelectorAll('#subt .subt2 button')].find(x=>x.dataset.v==={v!r}))||{{click:()=>setView({v!r})}}).click()")
            await pg.wait_for_timeout(1200)
            on = await pg.evaluate("[[...document.querySelectorAll('#subt > button.on')].map(x=>x.textContent).join(), [...document.querySelectorAll('#subt .subt2 button.on')].map(x=>x.textContent).join(), view, document.querySelector('.tabs button.on').dataset.g]")
            if on != [top, chip, v, "quant"]:
                nav.append(f"{v}:{on}")
        ok = (r.get("first") and r["n"] == 5 and r["h"] >= 44 and r["txt"] and r["ask"] and r["bottom"] <= h and r["over"] == 0
              and r["cards"] >= 15 and len(r["sub2"]) == 3 and all(int(x.rsplit(":", 1)[1]) >= 44 for x in r["sub2"]) and not nav and not errs)
        print(f"{'OK ' if ok else 'BAD'} 연구 보드 {w}px {r}" + (f" · 이동 {nav}" if nav else "") + (f" · 에러: {errs[0][:160]}" if errs else ""))
        bad += not ok
        await pg.close()
    return bad


async def check_dotplot_lean(b, port: int) -> int:
    """운용회의 › 국장 기명 점도표 띠: 5단 기울기 색(data-lean)·툴팁(기본 시나리오·▲▼ 전환 조건)·상단 ①②③ (dotplot-neutral-rule)."""
    pg = await b.new_page(viewport={"width": 1300, "height": 900})
    errs: list[str] = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    await pg.goto(f"http://127.0.0.1:{port}/index.html", wait_until="load")
    await pg.wait_for_timeout(1500)
    await pg.evaluate("setView('cmt')")
    await pg.wait_for_timeout(2500)
    r = await pg.evaluate("""(()=>{const xs=[...document.querySelectorAll('.dpdot')];
      return {n:xs.length, leans:[...new Set(xs.map(x=>x.dataset.lean))], tip:xs.filter(x=>/▲/.test(x.title)&&/▼/.test(x.title)).length,
              top:/① .*데스크 점/.test(document.querySelector('#root').innerText)};})()""")
    ok = not errs and r["n"] >= 16 and any(l in r["leans"] for l in ("약매수", "약매도")) and r["tip"] > 0 and r["top"]
    print(f"{'OK ' if ok else 'BAD'} 점도표 기울기 띠 점 {r['n']}개 · 단계 {r['leans']} · 전환 툴팁 {r['tip']} · 상단 {r['top']}"
          + (f" · 에러: {errs[0][:160]}" if errs else ""))
    await pg.close()
    return 0 if ok else 1


async def check_cmt_us(b, port: int) -> int:
    """운용회의 › 미장 탭: v2 섹션(결론·탑다운·로테이션·헤지·프리모템·성적)이 실파일 committee_us.json 으로 그려지는지 (us-committee-v2)."""
    pg = await b.new_page(viewport={"width": 1300, "height": 900})
    errs: list[str] = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    await pg.goto(f"http://127.0.0.1:{port}/index.html", wait_until="load")
    await pg.wait_for_timeout(1500)
    await pg.evaluate("setView('cmt')")
    await pg.wait_for_timeout(1500)
    await pg.evaluate("CMK='US'; render()")
    await pg.wait_for_timeout(2500)
    await pg.evaluate("document.querySelectorAll('#root details').forEach(d=>d.open=true)")
    txt = await pg.evaluate("document.querySelector('#root').innerText")
    need = ["운용회의 미장", "탑다운", "섹터 로테이션", "헤지", "프리모템", "성적"]
    miss = [w for w in need if w not in txt.replace(" · ", " ")]
    ok = not errs and not miss
    print(f"{'OK ' if ok else 'BAD'} 운용회의 미장 v2 {len(txt)}자" + (f" · 에러: {errs[0][:160]}" if errs else "") + (f" · 빠짐: {miss}" if miss else ""))
    await pg.close()
    return 0 if ok else 1


async def check_score(b, port: int) -> int:
    """DAILY › 성적표 하위 탭 (10/20 겸이: 판단 성적표 분리): 요약 카드·누적 곡선·대결 누적 성과판·판단 기록이 그려지고,
    폰 폭(390px)에서 가로 스크롤 없음 · DAILY 상단 대결 박스는 짧게(성적표 링크) — battle-scoreboard."""
    bad = 0
    for w in (1300, 390):
        pg = await b.new_page(viewport={"width": w, "height": 850})
        errs: list[str] = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(f"http://127.0.0.1:{port}/index.html", wait_until="load")
        await pg.wait_for_timeout(1500)
        await pg.evaluate("setView('score')")
        await pg.wait_for_timeout(2500)
        txt = await pg.evaluate("document.querySelector('#root').innerText")
        sw, iw = await pg.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
        svg = await pg.evaluate("document.querySelectorAll('#root svg polyline').length")
        sub = await pg.evaluate("[...document.querySelectorAll('#subt button')].map(x=>x.textContent).join(',')")
        await pg.evaluate("setView('daily')")
        await pg.wait_for_timeout(2500)
        dl = await pg.evaluate("document.querySelector('#root').textContent")   # textContent: 대결 박스가 접혀 있어도(UXUI 10/21) 링크가 있는지 본다
        need = ["성적표", "대결 누적 성과판", "판단 기록"]
        miss = [x for x in need if x not in txt] + ([] if "성적표" in sub else ["하위 탭"]) + ([] if "성적표에서 열기" in dl else ["DAILY 대결 박스 링크"])
        ok = not errs and not miss and sw <= iw + 1 and "원 (" not in txt
        print(f"{'OK ' if ok else 'BAD'} 성적표 {w}px {len(txt)}자 · 곡선 {svg} · 가로 {sw}/{iw}" + (f" · 에러: {errs[0][:160]}" if errs else "") + (f" · 빠짐: {miss}" if miss else ""))
        bad += not ok
        await pg.close()
    return bad


FIX = ROOT / "tests" / "fixtures"
ENG_ORDER = ["오늘의 단어", "오늘의 영어", "문법 포인트", "시제 읽기", "복습 퀴즈", "독해 퀴즈", "시사 회화", "일상 회화", "OPIc 실전", "오늘의 인적성"]
# 폰 폭에서 넘친 요소 · 44px 미만 터치 대상(보이는 버튼·select·summary)
OVER_JS = """(()=>{const W=innerWidth, r=document.querySelector('#engv'); if(!r) return {over:['#engv 없음'],small:[]};
 const over=[...r.querySelectorAll('*')].filter(e=>{const b=e.getBoundingClientRect(); return b.width&&b.right>W+1;}).slice(0,3).map(e=>e.tagName+'.'+e.className+' '+(e.textContent||'').slice(0,30));
 const small=[...r.querySelectorAll('button,select,summary')].filter(e=>{const b=e.getBoundingClientRect(); return b.width&&b.height<44;}).slice(0,3).map(e=>e.tagName+' '+(e.textContent||'').slice(0,20)+' '+Math.round(e.getBoundingClientRect().height));
 return {over,small};})()"""


async def check_eng(b, port: int) -> int:
    """STUDY › 오늘의 영어 (english-v2-ui, 10/21 스키마): 새 스키마 픽스처(390·1300px) + 옛 스키마(10/15, 390px).
    순서(단어→본문→문법·시제→복습→독해→시사·일상 회화→OPIc→인적성) · 가로 넘침 없음 · 터치 44px · 고르기 전 해설 비공개 ·
    첫 응답만 mt_eng_score_v1 · 사용 기록 eng_quiz · OPIc 타이머·자기평가 mt_opic_v1. 데이터는 tests/fixtures 를 route 로 주입(reports/ 무변경)."""
    import json as _json
    bad = 0
    v2 = (FIX / "english_v2_sample.json").read_text(encoding="utf-8")
    v1 = (FIX / "english_v1_2026-10-15.json").read_text(encoding="utf-8")
    E2 = _json.loads(v2)
    prof = _json.dumps({"survey_topics": ["카페 가기", "집에서 보내는 휴가"]}, ensure_ascii=False)
    for label, body, w in (("새 스키마", v2, 390), ("새 스키마", v2, 1300), ("옛 스키마", v1, 390)):
        # 390px = 폰(손가락) 에뮬 — 10/24 UXUI 결정: 44px 는 any-pointer:coarse 기기, 마우스 PC 는 28px(docs/uxui/2026-10-24_pc44_decision.md)
        pg = await b.new_page(viewport={"width": w, "height": 850}, has_touch=w < 700)
        errs: list[str] = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        def _ok(txt):   # route 핸들러는 인자 1개(route)만 — 기본값 인자를 두면 request 가 들어감
            return lambda r: r.fulfill(status=200, content_type="application/json", body=txt)
        await pg.route("**/reports/english/latest.json*", _ok(body))
        await pg.route("**/reports/english/opic_profile.json*", _ok(prof) if body is v2 else (lambda r: r.fulfill(status=404, body="")))
        await pg.goto(f"http://127.0.0.1:{port}/index.html", wait_until="load")
        await pg.wait_for_timeout(1500)
        await pg.evaluate("setView('eng')")
        await pg.wait_for_timeout(2500)
        txt = await pg.evaluate("document.querySelector('#root').innerText")
        sw, iw = await pg.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
        geo = await pg.evaluate(OVER_JS)
        miss: list[str] = []
        if body is v2:
            pos = [txt.find(h) for h in ENG_ORDER]
            if -1 in pos or pos != sorted(pos):
                miss.append("순서 " + ",".join(f"{h}:{p}" for h, p in zip(ENG_ORDER, pos)))
            q0 = E2["quiz"][0]
            if q0["exp_ko"] in txt or E2["opic"]["combo"][0]["model_answer"] in txt:
                miss.append("고르기 전 해설/모범답안 노출")
            if "내 서베이 주제: 카페 가기" not in txt or "14일 정답률" not in txt:
                miss.append("서베이 주제/배지")
            await pg.click(f'[data-ch="EQ{E2["date"]}-0"][data-i="{q0["a"]}"]')
            await pg.wait_for_timeout(200)
            await pg.click(f'[data-ch="EQ{E2["date"]}-0"][data-i="0"]', force=True)   # 두 번째 응답은 무시(비활성)
            await pg.wait_for_timeout(200)
            st = await pg.evaluate("[JSON.parse(localStorage.getItem('mt_eng_score_v1')||'[]'), JSON.parse(localStorage.getItem('mt_usage_v1')||'{}')]")
            sc, us = st
            day = (list((us.get("d") or {}).values()) or [{}])[-1].get("e", {})
            txt2 = await pg.evaluate("document.querySelector('#root').innerText")
            if not (len(sc) == 1 and sc[0].get("ok") is True and sc[0].get("kind") == "quiz" and {"date", "idx", "choice", "ts"} <= set(sc[0])):
                miss.append(f"채점 저장 {sc}")
            if q0["exp_ko"] not in txt2:
                miss.append("고른 뒤 해설 없음")
            if day.get("eng_quiz") != 1 or day.get("eng_quiz_ok") != 1 or day.get("quiz", 0) < 1:
                miss.append(f"사용 기록 {day}")
            await pg.click('[data-otm="prep"]')
            await pg.wait_for_timeout(1300)
            clk = await pg.evaluate("(document.querySelector('#opclock')||{}).textContent||''")
            await pg.click('[data-oself="ok"]')
            op = await pg.evaluate("JSON.parse(localStorage.getItem('mt_opic_v1')||'[]')")
            if not clk.startswith("준비") or len(op) != 1 or op[0].get("result") != "ok":
                miss.append(f"OPIc 타이머/자기평가 '{clk}' {op}")
        else:
            if "오늘의 단어" not in txt or "독해 퀴즈" not in txt or "복습 퀴즈" in txt or "기본 주제" not in txt:
                miss.append("옛 스키마 화면")
        if w <= 400 and geo["small"]:
            miss.append(f"터치<44px {geo['small']}")
        ok = not errs and not miss and sw <= iw + 1 and not geo["over"]
        print(f"{'OK ' if ok else 'BAD'} 영어({label}) {w}px {len(txt)}자 · 가로 {sw}/{iw}" + (f" · 넘침 {geo['over']}" if geo["over"] else "")
              + (f" · 에러: {errs[0][:160]}" if errs else "") + (f" · {miss}" if miss else ""))
        bad += not ok
        await pg.close()
    return bad


async def check_us_detail(b, port: int, sym: str = "AAPL") -> int:
    """US 종목 검색(색인 reports/detail/US/_index.json) + 상세 팝업(reports/detail/US/<sym>.json 200) — A1 시범 fetch 경로 검사."""
    pg = await b.new_page(viewport={"width": 1300, "height": 900})
    errs: list[str] = []
    got: dict[str, int] = {}
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("response", lambda r: got.__setitem__(r.url.split("/reports/detail/US/")[-1].split("?")[0], r.status) if "/reports/detail/US/" in r.url else None)
    await pg.goto(f"http://127.0.0.1:{port}/index.html", wait_until="load")
    await pg.wait_for_timeout(1500)
    await pg.fill("#sq", sym)
    await pg.wait_for_timeout(1500)
    res = await pg.evaluate("(document.querySelector('#sres')||{}).innerText||''")
    found = f"{sym} · US" in res
    await pg.evaluate(f"openDetail({sym!r}, 'US')")
    await pg.wait_for_timeout(2500)
    body = (await pg.evaluate("(document.querySelector('#dr-b')||{}).innerText||''")).strip()
    ok = found and got.get("_index.json") == 200 and got.get(f"{sym}.json") == 200 and len(body) > 200 \
        and not body.startswith("LOADING") and "상세 데이터가 없습니다" not in body and not errs
    print(f"{'OK ' if ok else 'BAD'} US상세 검색={'O' if found else 'X'} 색인={got.get('_index.json')} {sym}={got.get(sym + '.json')} 팝업 {len(body)}자"
          + (f" · 에러: {errs[0][:160]}" if errs else ""))
    await pg.close()
    return not ok


async def check_oneliner(b, port: int) -> int:
    """종목 상세 머리 한 줄 설명(데이터 10/24, reports/company_oneliner.json): 390px 에서 US 주식·KR 주식·KR ETF 상세 열면
    #dr-o 에 한 줄(또는 '설명 대기') · 가로 넘침 없음 · 페이지 에러 없음."""
    pg = await b.new_page(viewport={"width": 390, "height": 844})
    errs: list[str] = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    await pg.goto(f"http://127.0.0.1:{port}/index.html", wait_until="load")
    await pg.wait_for_timeout(1500)
    res = []
    for sym, mk in (("AAPL", "US"), ("005930", "KR"), ("069500", "KR")):
        await pg.evaluate(f"openDetail({sym!r}, {mk!r})")
        await pg.wait_for_timeout(2500)
        r = await pg.evaluate("""(()=>{const o=document.querySelector('#dr-o'), d=document.querySelector('#dr');
          return {t:(o&&o.innerText||'').trim(), over: d? d.scrollWidth-d.clientWidth : -1,
                  ow: o? o.scrollWidth-o.clientWidth : -1};})()""")
        res.append((sym, r))
        await pg.evaluate("closeDetail()")
    ok = not errs and all(r["t"] and r["over"] <= 0 and r["ow"] <= 0 for _, r in res)
    print(f"{'OK ' if ok else 'BAD'} 한줄설명(390px) " + " · ".join(f"{s}='{r['t'][:24]}' 넘침{r['over']}" for s, r in res)
          + (f" · 에러: {errs[0][:160]}" if errs else ""))
    await pg.close()
    return not ok


# 가짜 보유(개인 값 아님) — 원장 대조 스모크용
FAKE_LOCAL = "005930 1 1000\nAAPL 1 100"
FAKE_LEDGER = "# 주석\n005930 2 1000\nAAPL 1 100\n"


async def check_my_ledger(b, port: int) -> int:
    """MY 탭 '브라우저 주 + 원장 대조' (docs/my_tab_holdings_plan.md): 토큰으로 받은 holdings.txt 가 브라우저 값과 다르면
    덮어쓰지 않고 확인창 → '원장 값으로 바꾸기' 를 눌러야 바뀜 · 배지(원장 같음/다름 · 백업) · 파일로 저장 시 백업 배지 갱신. API 는 가짜 응답."""
    import json as _json
    pg = await b.new_page(viewport={"width": 1300, "height": 900}, accept_downloads=True)
    errs: list[str] = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    await pg.add_init_script(f"try{{ if(!sessionStorage.getItem('_sm')){{ sessionStorage.setItem('_sm','1'); localStorage.clear();"
                             f" localStorage.setItem('mt_gh_tok','smoke'); localStorage.setItem('mt_holdings_v1',{_json.dumps(FAKE_LOCAL)}); }} }}catch(e){{}}")
    await pg.route("https://api.github.com/**", lambda r: r.fulfill(status=200, content_type="text/plain", body=FAKE_LEDGER)
                   if "/contents/holdings.txt" in r.request.url else r.fulfill(status=404, body="{}"))
    await pg.goto(f"http://127.0.0.1:{port}/index.html", wait_until="load")
    await pg.wait_for_timeout(1500)
    await pg.evaluate("setView('my')")
    await pg.wait_for_timeout(2500)
    ls = "localStorage.getItem('mt_holdings_v1')"
    kept = await pg.evaluate(ls) == FAKE_LOCAL
    ask = await pg.evaluate("!!document.querySelector('#myasktake')")
    led = await pg.evaluate("(document.querySelector('#myledb')||{}).textContent||''")
    bak = await pg.evaluate("(document.querySelector('#mybakb')||{}).textContent||''")
    step1 = kept and ask and led == "원장과 다름 2줄" and bak == "백업: 없음"
    await pg.evaluate("document.querySelector('#mydl').click()")
    await pg.wait_for_timeout(300)
    bak2 = await pg.evaluate("(document.querySelector('#mybakb')||{}).textContent||''")
    await pg.evaluate("document.querySelector('#myasktake').click()")
    await pg.wait_for_timeout(800)
    took = (await pg.evaluate(ls)).strip() == "005930 2 1000\nAAPL 1 100"
    led2 = await pg.evaluate("(document.querySelector('#myledb')||{}).textContent||''")
    meta = await pg.evaluate("localStorage.getItem('mt_holdings_meta')||''")
    ok = step1 and bak2.startswith("마지막 백업 오늘") and took and led2 == "원장과 같음" and "1000" not in meta and not errs
    print(f"{'OK ' if ok else 'BAD'} MY원장대조 유지={'O' if kept else 'X'} 확인창={'O' if ask else 'X'} 배지='{led}'/'{bak}' → 백업='{bak2}' 바꾸기={'O' if took else 'X'} '{led2}'"
          + (f" · 에러: {errs[0][:160]}" if errs else ""))
    await pg.close()
    return not ok


def _toss_fixture() -> str:
    """합성 토스 live.json (실제 시세 아님) — 지금 시각 기준 1분봉 90개, 미장 세션 진행 중."""
    import json as _json
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone(timedelta(hours=9)))
    iso = now.isoformat(timespec="seconds")

    def bars(base: float, n: int = 90) -> list:
        out, v = [], base
        for i in range(n):
            c = round(v * (1 + ((i * 37) % 11 - 5) / 2000), 2)
            out.append([(now - timedelta(minutes=n - i)).strftime("%H:%M"), v, round(max(v, c) * 1.0005, 2), round(min(v, c) * 0.9995, 2), c])
            v = c
        return out
    idx = {k: {"bars": bars(b), "asof": iso, "n": 90, "last": 0} for k, b in (("KOSPI", 1000.0), ("KOSDAQ", 500.0))}
    us = {"asof": iso, "session": {"start": (now - timedelta(hours=1)).isoformat(), "end": (now + timedelta(hours=5)).isoformat()},
          "spark": {k: {"bars": bars(b)} for k, b in (("SPY", 100.0), ("QQQ", 200.0), ("SOXX", 50.0))},
          "quotes": {k: {"asof": iso, "last": 1.0} for k in ("SPY", "QQQ", "SOXX")}}
    return _json.dumps({"source": "toss", "date": now.strftime("%Y-%m-%d"), "asof": iso, "indices": idx,
                        "fx": {"USDKRW": {"asof": iso, "mid": 1000.0}}, "quotes": {}, "us": us})


# 가짜 부동산 비공개 목록·문서(개인 값 아님) — '🔒 내 계획(비공개)' 스모크용
FAKE_REPV_MAN = '{"updated":"2000-01-01","items":[{"path":"realestate/b.md","title":"두번째 가짜","note":"n2","order":2},{"path":"realestate/a.md","title":"첫번째 가짜","note":"n1","order":1},{"path":"../evil.md","title":"나쁜 경로","order":0}]}'
FAKE_REPV_DOC = ("# 가짜 제목\n\n본문 **강조** <img src=x onerror=\"window.__xss=1\"> <script>window.__xss=2</script>\n\n- 항목 하나\n- 항목 둘\n\n"
                 "| 열A | 열B | 열C | 열D | 열E | 열F |\n|---|---|---|---|---|---|\n| " + " | ".join(["가나다라마바사아자차카타파하" * 2] * 6) + " |\n")


async def check_re_private(b, port: int) -> int:
    """부동산 탭 '🔒 내 계획(비공개)': 토큰 없으면 잠금 안내만(pb-private 호출 0) · 있으면 manifest order 순 목록(../ 경로 제외) → 눌러 md 렌더(HTML 이스케이프, 표 감싸기) · 404 는 사람 말. 390px 가로 스크롤 없음. API 는 가짜 응답."""
    res = {}
    for mode in ("none", "ok", "nofile"):
        pg = await b.new_page(viewport={"width": 390, "height": 800})
        errs: list[str] = []
        calls: list[str] = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        tok = "" if mode == "none" else "localStorage.setItem('mt_gh_tok','smoke');"
        await pg.add_init_script(f"try{{ if(!sessionStorage.getItem('_sm')){{ sessionStorage.setItem('_sm','1'); localStorage.clear(); {tok} }} }}catch(e){{}}")

        def mk(mode, calls):   # route 핸들러는 인자 1개짜리여야 한다(기본값 인자는 Playwright 가 request 로 채움)
          def h(r):
            u = r.request.url
            calls.append(u)
            if mode == "nofile" or "/contents/" not in u:
                return r.fulfill(status=404, body="{}")
            if "web_manifest.json" in u:
                return r.fulfill(status=200, content_type="text/plain", body=FAKE_REPV_MAN)
            if "realestate/a.md" in u:
                return r.fulfill(status=200, content_type="text/plain", body=FAKE_REPV_DOC)
            return r.fulfill(status=404, body="{}")
          return h
        await pg.route("https://api.github.com/**", mk(mode, calls))
        await pg.goto(f"http://127.0.0.1:{port}/index.html", wait_until="load")
        await pg.wait_for_timeout(1200)
        await pg.evaluate("setView('re')")
        await pg.wait_for_timeout(2200)
        txt = await pg.evaluate("(document.querySelector('#repvb')||{}).textContent||''")
        out = {"txt": txt, "calls": len(calls)}
        if mode == "ok":
            out["items"] = await pg.evaluate("[...document.querySelectorAll('.repvit')].map(e=>e.firstChild.textContent)")
            await pg.evaluate("document.querySelectorAll('.repvit')[0].click()")
            await pg.wait_for_timeout(800)
            out["md"] = await pg.evaluate("(document.querySelector('.repvmd')||{}).innerHTML||''")
            out["xss"] = await pg.evaluate("!!window.__xss")
            out["imgs"] = await pg.evaluate("document.querySelectorAll('.repvmd img,.repvmd script').length")
            out["wrap"] = await pg.evaluate("!!document.querySelector('.repvmd .repvtw table')")
            out["hs"] = await pg.evaluate("document.documentElement.scrollWidth>window.innerWidth+1")
            out["over"] = await pg.evaluate("[...document.querySelectorAll('.repvmd *')].filter(e=>!e.closest('.repvtw')&&e.getBoundingClientRect().right>window.innerWidth+1).length")
        res[mode] = (out, errs)
        await pg.close()
    n, nerr = res["none"][0], res["none"][1]
    o, oerr = res["ok"][0], res["ok"][1]
    f, ferr = res["nofile"][0], res["nofile"][1]
    pbcalls = lambda d: d["calls"]
    ok = ("잠겨" in n["txt"] and n["calls"] == 0 and o["items"] == ["첫번째 가짜", "두번째 가짜"] and "가짜 제목" in o["md"] and "<b>강조</b>" in o["md"]
          and not o["xss"] and o["imgs"] == 0 and o["wrap"] and not o["hs"] and o["over"] == 0 and "목록 파일 없음" in f["txt"] and not (nerr or oerr or ferr))
    print(f"{'OK ' if ok else 'BAD'} 부동산비공개 토큰없음='{n['txt'][:14]}'(호출 {n['calls']}) 목록={o['items']} 이스케이프={'O' if not o['xss'] and o['imgs']==0 else 'X'} 표감쌈={'O' if o['wrap'] else 'X'} 가로스크롤={'있음' if o['hs'] or o['over'] else '없음'} 404='{f['txt'][:12]}'"
          + (f" · 에러: {(nerr or oerr or ferr)[0][:160]}" if (nerr or oerr or ferr) else ""))
    return not ok


FAKE_RE_GU = {"schema": 1, "asof": "2026-10-26", "period": "202607~202609", "gu": "강남구", "code": "11680", "label": "표시 전용 · 매매 신호 아님",
              "dongs": [{"name": "가짜동", "n": 3, "n_cancel": 1, "n_jeonse": 2, "med": 20.0, "p59": 15.0, "n59": 1, "p84": 25.0, "n84": 2, "n_cx": 2},
                        {"name": "나짜동", "n": 1, "n_cancel": 0, "n_jeonse": 0, "med": 9.0, "p59": None, "n59": 0, "p84": None, "n84": 0, "n_cx": 1}],
              "complexes": [{"dong": "가짜동", "name": "많이팔린<b>단지</b>", "by": 1999, "n": 2, "n_cancel": 1, "n_jeonse": 1, "med": 15.0, "last_d": "2026-09-20",
                             "areas": [{"a": 59, "n": 2, "med": 15.0, "last": 16.0, "last_d": "2026-09-20"}],
                             "recent": [{"d": "2026-09-20", "fl": "12", "a": 59.9, "p": 16.0}, {"d": "2026-08-01", "fl": "3", "a": 59.8, "p": 14.0}]},
                            {"dong": "가짜동", "name": "비싼단지", "by": 2020, "n": 1, "n_cancel": 0, "n_jeonse": 1, "med": 30.0, "last_d": "2026-07-02",
                             "areas": [{"a": 84, "n": 1, "med": 30.0, "last": 30.0, "last_d": "2026-07-02"}], "recent": [{"d": "2026-07-02", "fl": "20", "a": 84.9, "p": 30.0}]},
                            {"dong": "나짜동", "name": "다른동단지", "by": 2010, "n": 1, "n_cancel": 0, "n_jeonse": 0, "med": 9.0, "last_d": "2026-09-01", "areas": [], "recent": []}]}


async def check_re_drill(b, port: int) -> int:
    """부동산 드릴다운(10/26 겸이 '구 클릭→동, 동 클릭→단지'): 구 선택 → 구 파일 lazy(1회) → 동 목록(거래 많은 순) → 단지(거래 수/가격 정렬) → 최근 거래 표,
    빵부스러기 뒤로(동→구→서울), 이스케이프, 390px 가로 넘침 없음, 권역 배지. 데이터는 가짜(route)."""
    import json as _j
    J = _j.loads((ROOT / "reports/realestate.json").read_text(encoding="utf-8"))
    T = J.setdefault("seoul_trades", {})
    T.update(status="ok", detail_dir="reports/realestate_trades")
    T.setdefault("districts", {}).setdefault("강남구", {"code": "11680", "n": 4, "p59": 15.0})
    T["districts"]["강남구"].update(code="11680", detail="reports/realestate_trades/11680.json", n_dong=2, n_cx=3)
    bad, out = 0, {}
    for w in (390, 1300):
        pg = await b.new_page(viewport={"width": w, "height": 900})
        errs: list[str] = []
        calls: list[str] = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        body = _j.dumps(J, ensure_ascii=False)

        def h_main(r):
            return r.fulfill(status=200, content_type="application/json", body=body)

        def h_gu(r):
            calls.append(r.request.url)
            return r.fulfill(status=200, content_type="application/json", body=_j.dumps(FAKE_RE_GU, ensure_ascii=False))
        await pg.route("**/reports/realestate.json*", h_main)
        await pg.route("**/reports/realestate_trades/*", h_gu)
        await pg.goto(f"http://127.0.0.1:{port}/index.html", wait_until="load")
        await pg.wait_for_timeout(1200)
        await pg.evaluate("setView('re')")
        await pg.wait_for_timeout(1800)
        r: dict = {"none": await pg.evaluate("!document.getElementById('redr')")}
        await pg.evaluate("reSel('강남구')")
        await pg.wait_for_timeout(900)
        q = "(()=>{const d=document.getElementById('redr');return d?{t:d.innerText,crumb:[...d.querySelectorAll('.recrumb button,.recrumb b')].map(e=>e.textContent),it:[...d.querySelectorAll('.redit .v')].map(e=>e.textContent)}:null})()"
        g = await pg.evaluate(q)
        r["dongs"] = bool(g) and g["it"] == ["가짜동", "나짜동"] and "상급지" in g["t"] and g["crumb"][:2] == ["서울", "강남구"]
        await pg.evaluate("document.querySelectorAll('#redr .redit')[0].click()")
        await pg.wait_for_timeout(500)
        d = await pg.evaluate(q)
        r["cx"] = bool(d) and d["it"] == ["많이팔린<b>단지</b>", "비싼단지"] and d["crumb"][:3] == ["서울", "강남구", "가짜동"]
        r["esc"] = await pg.evaluate("!document.querySelector('#redr .redit b')")
        await pg.evaluate("reCxSort('p')")
        await pg.wait_for_timeout(300)
        r["sort"] = (await pg.evaluate(q))["it"][0] == "비싼단지"
        await pg.evaluate("reCxSort('n')")
        await pg.evaluate("document.querySelectorAll('#redr .recxl > .redit')[0].click()")
        await pg.wait_for_timeout(400)
        r["recent"] = await pg.evaluate("(()=>{const x=document.querySelector('#redr .recxd');return !!x&&x.innerText.includes('2026-09-20')&&x.innerText.includes('12층')&&x.querySelectorAll('table').length===2})()")
        r["over"] = await pg.evaluate("document.documentElement.scrollWidth>innerWidth+1||[...document.querySelectorAll('#redr *')].some(e=>!e.closest('.retw')&&e.getBoundingClientRect().right>innerWidth+1)")
        await pg.evaluate("[...document.querySelectorAll('.recrumb button')].find(e=>e.textContent==='강남구').click()")
        await pg.wait_for_timeout(400)
        r["back_gu"] = (await pg.evaluate(q))["it"] == ["가짜동", "나짜동"]
        await pg.evaluate("[...document.querySelectorAll('.recrumb button')].find(e=>e.textContent==='서울').click()")
        await pg.wait_for_timeout(400)
        r["back_seoul"] = await pg.evaluate("!document.getElementById('redr')")
        r["lazy1"] = len(calls) == 1
        ok = all(v for k, v in r.items() if k != "over") and not r["over"] and not errs
        bad += not ok
        print(f"{'OK ' if ok else 'BAD'} 부동산드릴다운({w}px) " + " ".join(f"{k}={'O' if (not v if k == 'over' else v) else 'X'}" for k, v in r.items())
              + (f" · 에러: {errs[0][:160]}" if errs else ""))
        await pg.close()
    return bad


FAKE_RE_ZOOM_GU = {"schema": 1, "gu": "강남구", "code": "11680", "period": "2026-07~2026-09",
                   "dongs": [{"name": "역삼동", "n": 20, "n_cancel": 0, "n_jeonse": 5, "med": 18.5, "p59": 15.0, "n59": 6, "p84": 21.0, "n84": 9, "n_cx": 4},
                             {"name": "대치동", "n": 2, "n_cancel": 0, "n_jeonse": 1, "med": 30.0, "p59": None, "n59": 0, "p84": 30.0, "n84": 2, "n_cx": 1}],
                   "complexes": [{"dong": "역삼동", "name": "가짜단지", "by": 2005, "n": 3, "n_cancel": 0, "n_jeonse": 1, "med": 18.0, "last_d": "2026-09-10",
                                  "areas": [], "recent": [{"d": "2026-09-10", "fl": "7", "a": 84.9, "p": 19.0}]}]}


async def check_re_zoom(b, port: int) -> int:
    """부동산 지도 줌(10/26 겸이 "지도 자체가 점점 확대, 한강도"): 서울(구 25·하천 선 또는 10/27 배경 지도 타일) → 구 클릭 뷰박스 확대 + 법정동 경계(강남 14)
    → 동 색(n<3 회색·'2건' 표시) → 동 클릭 더 확대·동 카드 → 빵부스러기/뒤로 원복. 실거래 없음(수집 전)에서도 경계·줌 동작. 390px 터치 · 1300px, 가로 넘침 없음."""
    import json as _j
    J0 = _j.loads((ROOT / "reports/realestate.json").read_text(encoding="utf-8"))
    G = _j.loads((ROOT / "assets/realestate_geo/seoul.json").read_text(encoding="utf-8"))["pp"]
    ys = next(d for d in _j.loads((ROOT / "assets/realestate_geo/11680.json").read_text(encoding="utf-8"))["dongs"] if d["name"] == "역삼동")
    FAKE_RE_ZOOM_GU["complexes"][0].update(lon=round((ys["cx"] / G["s"] + G["x0"]) / G["k"], 5), lat=round(-(ys["cy"] / G["s"] + G["y0"]), 5))
    bad = 0
    for live in (True, False):
        J = _j.loads(_j.dumps(J0))
        T = J.setdefault("seoul_trades", {})
        if live:
            T.update(status="ok", detail_dir="reports/realestate_trades", period="2026-07~2026-09")
            T.setdefault("districts", {}).setdefault("강남구", {"n": 22, "p59": 15.0})
            T["districts"]["강남구"].update(code="11680", detail="reports/realestate_trades/11680.json")
        else:
            J["seoul_trades"] = {"status": "키 필요"}
        for w in ((390, 1300) if live else (390,)):
            ctx = await b.new_context(viewport={"width": w, "height": 900}, has_touch=w < 700, is_mobile=w < 700)
            pg = await ctx.new_page()
            errs: list[str] = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            body = _j.dumps(J, ensure_ascii=False)

            def h_geo(r):
                f = ROOT / "assets/realestate_geo" / r.request.url.split("?")[0].rsplit("/", 1)[-1]
                return r.fulfill(status=200, content_type="application/json", body=f.read_text(encoding="utf-8")) if f.exists() else r.fulfill(status=404, body="")
            await pg.route("**/reports/realestate.json*", lambda r: r.fulfill(status=200, content_type="application/json", body=body))
            await pg.route("**/reports/realestate_trades/*", lambda r: r.fulfill(status=200, content_type="application/json", body=_j.dumps(FAKE_RE_ZOOM_GU, ensure_ascii=False)))
            await pg.route("**/assets/realestate_geo/*", h_geo)
            await pg.goto(f"http://127.0.0.1:{port}/index.html", wait_until="load")
            await pg.wait_for_timeout(1200)
            await pg.evaluate("setView('re')")
            await pg.wait_for_timeout(1500)
            vbw = "(()=>{const s=document.getElementById('rezsvg');return s?s.viewBox.baseVal.width:0})()"
            r: dict = {}
            r["seoul"] = await pg.evaluate("(()=>{const s=document.getElementById('rezsvg');return !!s&&s.dataset.lv==='seoul'&&s.querySelectorAll('path[role=button]').length===25&&(s.querySelectorAll('path.reriv').length>=1||s.querySelectorAll('image.retile').length>=1)})()")   # 10/27 배경 지도 타일이 있으면 한강은 타일에(하천 선 생략)
            w0 = await pg.evaluate(vbw)
            await pg.locator("#rezsvg path[aria-label^='강남구']").first.dispatch_event("click")
            await pg.wait_for_timeout(1200)
            w1 = await pg.evaluate(vbw)
            r["gu_zoom"] = 0 < w1 < w0 / 3
            r["dongs"] = await pg.evaluate("document.querySelectorAll('#rezsvg path.redg').length") == 14
            if live:
                r["few_gray"] = await pg.evaluate("(()=>{const p=document.querySelector('#rezsvg path[data-dong=\"대치동\"]'), t=[...document.querySelectorAll('#rezsvg text')].find(e=>e.textContent.startsWith('대치'));return !!p&&p.getAttribute('fill')==='var(--bg2)'&&!!t&&t.textContent.includes('2건')})()")
                r["color"] = await pg.evaluate("(()=>{const p=document.querySelector('#rezsvg path[data-dong=\"역삼동\"]');return !!p&&p.getAttribute('fill').startsWith('color-mix')})()")
            path = "#rezsvg path[data-dong='역삼동']"
            if w < 700:
                await pg.locator(path).scroll_into_view_if_needed()
                pt = await pg.evaluate("""(()=>{const p=document.querySelector("#rezsvg path[data-dong='역삼동']"), b=p.getBoundingClientRect();
                  for(let i=1;i<10;i++) for(let j=1;j<10;j++){ const x=b.left+b.width*i/10, y=b.top+b.height*j/10; if(document.elementFromPoint(x,y)===p) return [x,y]; } return null})()""")
                if pt:
                    await pg.touchscreen.tap(pt[0], pt[1])
            else:
                await pg.locator(path).dispatch_event("click")
            await pg.wait_for_timeout(1000)
            w2 = await pg.evaluate(vbw)
            r["dong_zoom"] = 0 < w2 < w1 and await pg.evaluate("document.getElementById('rezsvg').dataset.lv==='dong'")
            card = await pg.evaluate("(()=>{const c=document.querySelector('.remap .regu');return c?c.innerText:''})()")
            r["card"] = "역삼동" in card and (("20건" in card) if live else ("자료 없음" in card))
            if live:   # 단지 점(브이월드 좌표 캐시 lon·lat 있는 단지만) → 누르면 아래 최근 거래
                await pg.evaluate("document.querySelector('#rezsvg circle.recx').dispatchEvent(new MouseEvent('click',{bubbles:true}))")
                await pg.wait_for_timeout(500)
                r["cx_dot"] = await pg.evaluate("(()=>{const x=document.querySelector('#redr .recxd');return document.querySelectorAll('#rezsvg circle.recx').length===1&&!!x&&x.innerText.includes('2026-09-10')})()")
            else:
                r["no_dot"] = await pg.evaluate("!document.querySelector('#rezsvg circle.recx')")
            r["label"] = "매매 신호 아님" in await pg.evaluate("document.querySelector('#rezsvg').getAttribute('aria-label')")
            r["over"] = await pg.evaluate("document.documentElement.scrollWidth>innerWidth+1||[...document.querySelectorAll('.remap *')].some(e=>!e.closest('svg')&&!e.closest('.retw')&&e.getBoundingClientRect().right>innerWidth+1)")
            await pg.evaluate("[...document.querySelectorAll('.recrumb button')].find(e=>e.textContent.includes('뒤로')).click()")
            await pg.wait_for_timeout(900)
            r["back_gu"] = await pg.evaluate("document.getElementById('rezsvg').dataset.lv==='gu'")
            await pg.evaluate("[...document.querySelectorAll('.recrumb button')].find(e=>e.textContent==='서울').click()")
            await pg.wait_for_timeout(900)
            r["back_seoul"] = await pg.evaluate("document.getElementById('rezsvg').dataset.lv==='seoul'") and abs(await pg.evaluate(vbw) - w0) < 0.5
            import os as _os
            if live and _os.environ.get("SMOKE_SHOT_DIR"):   # 눈 확인용(선택): 서울 단계 스크린샷
                await pg.evaluate("reGo('seoul')")
                await pg.wait_for_timeout(700)
                await pg.locator(".remapbox").screenshot(path=str(Path(_os.environ["SMOKE_SHOT_DIR"]) / f"re_zoom_{w}_seoul.png"))
                await pg.locator("#rezsvg path[aria-label^='송파구']").first.dispatch_event("click")
                await pg.wait_for_timeout(900)
                await pg.locator(".remapbox").screenshot(path=str(Path(_os.environ["SMOKE_SHOT_DIR"]) / f"re_zoom_{w}_gu.png"))
            ok = all(v for k, v in r.items() if k != "over") and not r["over"] and not errs
            bad += not ok
            print(f"{'OK ' if ok else 'BAD'} 부동산지도줌({w}px{'' if live else '·수집 전'}) " + " ".join(f"{k}={'O' if (not v if k == 'over' else v) else 'X'}" for k, v in r.items())
                  + (f" · 에러: {errs[0][:160]}" if errs else ""))
            await ctx.close()
    return bad


async def check_macro_popup(b, port: int) -> int:
    """상단 지표 팝업(openMacro) 390px 터치: 봉 단위 토글(1분↔일봉)·크로스헤어 툴팁·대용(ETF)/토스 미제공 배지·가로 넘침 없음·닫으면 60초 타이머 해제.
    토스 live.json 은 합성 픽스처를 route 로 주입, daily_bars.json 은 404(아직 없을 때 야후 폴백 검사)."""
    ctx = await b.new_context(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True)
    pg = await ctx.new_page()
    errs: list[str] = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    body = _toss_fixture()
    await pg.route("**/toss-live/*.json*", lambda r: r.fulfill(status=404, body=""))
    await pg.route("**/toss-live/live.json*", lambda r: r.fulfill(status=200, content_type="application/json", body=body))   # 나중에 등록한 route 가 먼저 — live.json 만 픽스처
    await pg.add_init_script("try{ localStorage.removeItem('mt_mac_unit'); }catch(e){}")
    await pg.goto(f"http://127.0.0.1:{port}/index.html", wait_until="load")
    await pg.wait_for_timeout(1500)
    J = lambda js: pg.evaluate(js)
    tt = "(()=>{const t=document.querySelector('#dr-b .mxt'); return t&&t.style.display==='block'?t.innerText:'';})()"   # 보이는 툴팁만

    async def tap(sel: str) -> None:
        bb = await (await pg.query_selector(sel)).bounding_box()
        await pg.touchscreen.tap(bb["x"] + bb["width"] * 0.6, bb["y"] + bb["height"] / 2)
        await pg.wait_for_timeout(200)
    res = {}
    await J("openMacro('KOSPI')")
    await pg.wait_for_timeout(1500)
    await pg.click("#mcunit button[data-u='1']")
    await pg.wait_for_timeout(300)
    res["1분"] = "분봉 기준" in await J("$('#mcinfo').innerText") and "토스" in await J("$('#macbadge').innerText")
    await tap("#mcv")
    res["툴팁1분"] = "시가 대비" in await J(tt)
    res["타이머"] = await J("MAC_TIMER!==null")
    await pg.click("#mcunit button[data-u='D']")
    await pg.wait_for_timeout(300)
    await tap("#mcv")
    res["일봉"] = "일봉 기준" in await J("$('#mcinfo').innerText") and "전일비" in await J(tt) and await J("!!document.querySelector('#mcrng')")
    await J("openMacro('SPX')")
    await pg.wait_for_timeout(800)
    await pg.click("#mcunit button[data-u='5']")
    await pg.wait_for_timeout(300)
    res["대용ETF"] = "대용(ETF SPY)" in await J("$('#macbadge').innerText")
    await J("openMacro('VIX')")
    await pg.wait_for_timeout(800)
    res["미제공"] = "토스 미제공" in await J("$('#macbadge').innerText") and await J("document.querySelector(\"#mcunit button[data-u='1']\").disabled")
    # 토스 일봉(daily_bars) 100봉 주입 → 3M 은 토스 일봉, 1Y 버튼엔 '야후'(봉 부족 — 이어붙이지 않음)
    await J("MAC_DB={past:{source:'toss',keys:{KOSPI:{mk:'KR',n:99,bars:Array.from({length:99},(_,i)=>{const d=new Date(Date.UTC(2026,0,1+i)).toISOString().slice(0,10),v=1000+i;return [d,v,v+5,v-5,v+1,10];})}}},"
            "today:{source:'toss',asof:new Date().toISOString(),keys:{KOSPI:{bars:[['2026-12-30',1099,1104,1094,1100,10],['2026-12-31',1100,1105,1095,1101,10]],bar:['2026-12-31',1100,1105,1095,1101,10],updated:new Date().toISOString()}}}};"
            "MAC_DB_T=Date.now(); MRNG=63; openMacro('KOSPI')")
    await pg.wait_for_timeout(800)
    await pg.click("#mcunit button[data-u='D']")
    await pg.wait_for_timeout(300)
    res["토스일봉"] = "토스 일봉" in await J("$('#macbadge').innerText") and "야후" in await J("$('#mcrng button[data-r=\"252\"]').innerText")
    res["넘침없음"] = await J("[...document.querySelectorAll('#dr, #dr *')].every(e=>e.getBoundingClientRect().right<=innerWidth+1)")   # overflow-x:hidden 이라 scrollWidth 대신 요소 오른쪽 끝
    await J("closeDetail()")
    res["닫으면해제"] = await J("MAC_TIMER===null")
    ok = all(res.values()) and not errs
    print(f"{'OK ' if ok else 'BAD'} 지표팝업 " + " ".join(f"{k}={'O' if v else 'X'}" for k, v in res.items()) + (f" · 에러: {errs[0][:160]}" if errs else ""))
    await ctx.close()
    return not ok


async def check_syn(b, port: int) -> int:
    """RESEARCH 맨 위 '리서치 종합'(애널 research-synthesis·public-reports): 390px 폭에서 카드 9장(공공 리포트·지정학 뷰 포함)·요약 펼침(digest 세 칸)·라벨·가로 넘침 없음·리포트 목록이 아래에."""
    pg = await b.new_page(viewport={"width": 390, "height": 844})
    errs: list[str] = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    await pg.goto(f"http://127.0.0.1:{port}/index.html", wait_until="load")
    await pg.wait_for_timeout(1500)
    await pg.evaluate("try{localStorage.removeItem('mt_syn_open')}catch(e){}; RV.k='종목'; setView('rep')")
    await pg.wait_for_timeout(3000)
    J = pg.evaluate
    syn_txt = await J("(document.querySelector('#syn')||{}).innerText||''")
    res = {
        "카드9": await J("document.querySelectorAll('#syn .syn').length") == 9,
        "공공·지정학": all(k in syn_txt for k in ("공공 리포트", "지정학 뷰", "참고 뷰")),
        # STANDARD §4(10/23 겸이 '링크만 말고 내용·해석까지'): digest 가 있으면 펼침 항목이 있고, 펼치면 세 칸이 보인다
        # 10/28: '요약 대기'는 4번째 줄부터 접힌 #pubMore(7e1c2b3c4) 안에 있어 innerText 로는 안 셈 → 배지 span 을 DOM 에서 정확히 '대기 행 수와 같게' 셈(이전 '이상' 보다 엄격)
        # 공공 리포트(10/23 겸이 "우리 요약/뷰를 더 앞으로"): items30 중 요약 있는 것 = 펼침(첫 줄 = 한 줄 뷰, 펼치면 3종 + 맨 아래 '링크 깨질 수 있음'), 없는 것 = '요약 대기'
        "요약펼침": await J("(()=>{const P=((SYN||{}).public||{}), n=((SYN||{}).digest||{}), rows=P.items30||null, okN=rows?rows.filter(r=>r.status==='ok').length:(n.public||[]).length,"
                         " k=okN+(n.geo||[]).length, d=[...document.querySelectorAll('#syn details.dg')]; if(d.length!==k) return false; if(!k) return true;"
                         " if(!rows) {d[0].open=true; return ['① 내용','② 뷰','③ 우리 해석'].every(w=>d[0].innerText.includes(w));}"
                         " const w=[...document.querySelectorAll('#syn .syn')].find(c=>c.querySelector('h2').innerText.startsWith('공공 리포트')); if(!w) return false;"
                         " const ds=w.querySelectorAll('details.dg'); if(ds.length!==okN) return false; if([...w.querySelectorAll('span')].filter(s=>s.textContent.trim()==='요약 대기').length!==rows.length-okN) return false;"
                         " if(!okN) return true; const f=ds[0]; const first=rows.find(r=>r.status==='ok'); if(!f.querySelector('summary').innerText.trim().startsWith(first.one_line.slice(0,12))) return false;"
                         " f.open=true; const t=f.innerText; return ['① 핵심 내용','③ 우리 해석','링크 깨질 수 있음'].every(x=>t.includes(x)) && t.indexOf('링크 깨질 수 있음')>t.indexOf('③ 우리 해석');})()"),
        "라벨": "증권가 집계" in syn_txt,
        "목록아래": await J("(()=>{const s=document.querySelector('#syn'),r=document.querySelector('#rbody');return !!(s&&r&&(s.compareDocumentPosition(r)&Node.DOCUMENT_POSITION_FOLLOWING));})()"),
        "넘침없음": await J("[...document.querySelectorAll('#syn, #syn *')].every(e=>e.getBoundingClientRect().right<=innerWidth+1)"),
    }
    ok = all(res.values()) and not errs
    print(f"{'OK ' if ok else 'BAD'} 리서치종합(390px) " + " ".join(f"{k}={'O' if v else 'X'}" for k, v in res.items()) + (f" · 에러: {errs[0][:160]}" if errs else ""))
    await pg.close()
    return not ok


async def check_duel_toggle(b, port: int) -> int:
    """DAILY 상단 '진입 타점 대결' 1줄(UXUI 재진단 Top10 #5, 10/23 — 10/21 접기 토글 대체): 390px 에서 1줄 바 44px 이상·100px 이하·요약 보임·
    브리프가 첫 화면(844px) 안·가로 넘침 없음 · 누르면 DAILY › 성적표로 가고 거기 대결 본문(#duelbody)이 있음."""
    pg = await b.new_page(viewport={"width": 390, "height": 844})
    errs: list[str] = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    J = pg.evaluate
    await pg.goto(f"http://127.0.0.1:{port}/index.html", wait_until="load")
    await pg.wait_for_timeout(1500)
    await J("setView('daily')")
    await pg.wait_for_timeout(3500)
    h = await J("(document.querySelector('#duelbox')||{offsetHeight:0}).offsetHeight")
    res = {
        "1줄": 44 <= h <= 100,
        "요약": "나:" in await J("(document.querySelector('#duelsum')||{}).innerText||''") or "대결 없음" in await J("(document.querySelector('#duelsum')||{}).innerText||''"),
        "넘침없음": await J("[...document.querySelectorAll('#duelbox, #duelbox *')].every(e=>e.getBoundingClientRect().right<=innerWidth+1)"),
        "브리프첫화면": await J("(()=>{const e=[...document.querySelectorAll('#root *')].find(x=>/DAILY RESEARCH BRIEF/.test(x.textContent)&&x.children.length<3); return !!e&&e.getBoundingClientRect().top<844;})()"),
    }
    await pg.click("#dueltog")
    await pg.wait_for_timeout(3000)
    res["성적표본문"] = await J("view==='score'&&!!document.querySelector('#duelbody')")
    ok = all(res.values()) and not errs
    print(f"{'OK ' if ok else 'BAD'} 대결1줄(390px) 높이={h}px " + " ".join(f"{k}={'O' if v else 'X'}" for k, v in res.items()) + (f" · 에러: {errs[0][:160]}" if errs else ""))
    await pg.close()
    return not ok


async def check_msg_popup(b, port: int) -> int:
    """💬 사내톡 팝업 폰(390px): 본문(.mgpb) 높이 ≥ 300px · 머리(.mgph) ≤ 80px · 가로 넘침 없음.
    req-dev-bb56cd85(검증 10/24): 프로필 카드가 .mgph 클래스를 재사용해 폰에서 머리가 100dvh 를 먹고 본문이 12px 로 눌린 회귀."""
    pg = await b.new_page(viewport={"width": 390, "height": 844})
    errs: list[str] = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    J = pg.evaluate
    await pg.goto(f"http://127.0.0.1:{port}/index.html", wait_until="load")
    await pg.wait_for_timeout(1500)
    await J("setView('home')")
    await pg.wait_for_timeout(1500)
    await J("mgPop(true)")
    await pg.wait_for_timeout(2000)
    body = await J("(document.querySelector('#mgpop .mgpb')||{offsetHeight:0}).offsetHeight")
    head = await J("(document.querySelector('#mgpop .mgph')||{offsetHeight:9999}).offsetHeight")
    res = {"본문300+": body >= 300, "머리80-": head <= 80,
           "넘침없음": await J("[...document.querySelectorAll('#mgpop, #mgpop *')].every(e=>e.getBoundingClientRect().right<=innerWidth+1)")}
    ok = all(res.values()) and not errs
    print(f"{'OK ' if ok else 'BAD'} 💬팝업(390px) 본문={body}px 머리={head}px " + " ".join(f"{k}={'O' if v else 'X'}" for k, v in res.items())
          + (f" · 에러: {errs[0][:160]}" if errs else ""))
    await pg.close()
    return not ok


MSG_FIX = {"asof": "2026-10-26 23:00", "status": {"done": 1, "open": 1}, "profiles": [], "items": [
    {"id": "req-dev-0000000a", "from": "pb", "to": "dev", "text": "옛 요청인데 답이 최근에 옴 " + "가나다 " * 30, "opened_at": "2026-10-20T09:00+09:00",
     "status": "done", "done_at": "2026-10-26T21:00+09:00", "done_by": "개발", "resolution": "RESO-OK", "last_at": "2026-10-26T21:00+09:00",
     "replies": [{"by": "dev", "at": "2026-10-20T10:00+09:00", "text": "진행자 메모 1", "voc": False, "sec": "보류"},
                 {"by": "dev", "at": "2026-10-20T11:00+09:00", "text": "진행자 메모 2", "voc": False, "sec": "보류"},
                 {"by": "dev", "at": "2026-10-26T20:00+09:00", "text": "VOC 본인 답", "voc": True, "sec": "회신"}]},
    {"id": "req-data-0000000b", "from": "quant", "to": "data", "text": "새 요청", "opened_at": "2026-10-25T09:00+09:00", "due": "2026-10-24",
     "status": "open", "last_at": "2026-10-25T09:00+09:00", "replies": []}]}
# 🔒 사담 = pb-private chat/private_chat.json 하나(10/28 통합) — 한글 이름 표기, 가짜 값(개인 수치 아님)
PRIV_FIX = {"chat": [{"by": "퀀트", "to": "데이터", "at": "2026-10-26T10:00+09:00", "text": "원 사담", "src": "public"},
                     {"by": "매크로", "at": "2026-10-26T10:30+09:00", "text": "딴 얘기"},
                     {"by": "데이터", "to": "퀀트", "at": "2026-10-26T11:00+09:00", "text": "답장 사담", "re": {"by": "퀀트", "at": "2026-10-26T10:00+09:00", "text": "원 사담"}}]}


async def check_msg_thread(b, port: int) -> int:
    """사내톡 쓰레드형(10/26 겸이 "쓰레드형으로", 390px, 고정 피드 주입):
    기본 '진행 중' = 열린 요청만 · '전체' = 카드 2개, 마지막 활동순(옛 요청+최근 답이 위) · 카드·세그 높이 40px+ · 가로 넘침 0 ·
    펼치면 VOC 답글 1·대행 묶음 1(접힘, '데스크 발언 아님')·'✅ 완료 — resolution' · 기한 지난 열린 요청 = '기한 지남' ·
    🔒 사담 세그(10/28 통합 — 공개 💬 사담 칸 없음) = 토큰 없으면 '비공개 — 토큰 필요', 있으면 요청 카드와 분리·re 답장이 원 사담 아래 들여쓰기 · 💬 팝업에서도 카드 렌더."""
    import json as _json
    pg = await b.new_page(viewport={"width": 390, "height": 844}, has_touch=True)
    errs: list[str] = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    J = pg.evaluate
    await pg.route("**/reports/msgr_feed.md*", lambda r: r.fulfill(status=200, content_type="text/plain", body=_json.dumps(MSG_FIX, ensure_ascii=False)))
    await pg.goto(f"http://127.0.0.1:{port}/index.html", wait_until="load")
    await pg.wait_for_timeout(1500)
    await J("setView('msg')")
    await pg.wait_for_timeout(2000)
    OVER = "[...document.querySelectorAll('#root *, #mgpop *')].filter(e=>e.offsetWidth&&e.getBoundingClientRect().right>innerWidth+1).length"
    res: dict = {}
    live = await J("[...document.querySelectorAll('#mgbox .mgth')].map(d=>d.dataset.id)")
    res["기본진행중"] = live == ["req-data-0000000b"] and "기한 지남" in await J("document.querySelector('#mgbox .mgst').textContent")
    await pg.click("#root [data-mgs='all']")
    await pg.wait_for_timeout(500)
    ids = await J("[...document.querySelectorAll('#mgbox .mgth')].map(d=>d.dataset.id)")
    res["활동순"] = ids == ["req-dev-0000000a", "req-data-0000000b"]
    res["터치40+"] = await J("[...document.querySelectorAll('#mgbox .mgth>summary, #root .mgseg button, #mgsel')].every(e=>e.getBoundingClientRect().height>=40)")
    res["넘침없음"] = await J(OVER) == 0
    await pg.click("#mgbox .mgth >> nth=0 >> summary >> .mgone")
    await pg.wait_for_timeout(300)
    th = await J("""(()=>{ const d=document.querySelector('#mgbox .mgth'); const px=d.querySelector('.mgproxy');
      return {open:d.open, voc:d.querySelectorAll('.mgr').length, px:d.querySelectorAll('.mgproxy').length, pxClosed:!!px&&!px.open,
        pxLabel:!!px&&/데스크 발언 아님/.test(px.querySelector('summary').textContent), done:((d.querySelector('.mgdone')||{}).textContent||'')}; })()""")
    res["펼침"] = th["open"] and th["voc"] == 1 and th["px"] == 1 and th["pxClosed"] and th["pxLabel"] and "✅ 완료 — RESO-OK" in th["done"]
    res["펼침넘침없음"] = await J(OVER) == 0
    res["공개사담칸없음"] = await J("document.querySelectorAll(\"#root [data-mgs='chat']\").length") == 0
    await pg.route("https://api.github.com/repos/*/pb-private/contents/chat/private_chat.json*",
                   lambda r: r.fulfill(status=200, content_type="text/plain", body=_json.dumps(PRIV_FIX, ensure_ascii=False)))
    await J("try{localStorage.removeItem('pbPrivTok')}catch(e){}; MGP=null")
    await pg.click("#root [data-mgs='priv']")
    await pg.wait_for_timeout(800)
    res["토큰안내"] = "비공개 — 토큰 필요" in await J("document.getElementById('mgbox').textContent")
    await J("localStorage.setItem('pbPrivTok','smoke-fake'); MGP=null; mgRe()")
    await pg.wait_for_timeout(1000)
    ch = await J("""(()=>{ const b=document.getElementById('mgbox'); const t=[...b.querySelectorAll('.mgbub')].map(e=>e.textContent);
      const k=b.querySelector('.mgch'); return {req:b.querySelectorAll('.mgth[data-id^="req-"]').length, order:t, nested:!!k&&/답장 사담/.test(k.textContent)}; })()""")
    await J("try{localStorage.removeItem('pbPrivTok')}catch(e){}; MGP=null")
    res["사담분리"] = ch["req"] == 0 and ch["order"] == ["원 사담", "답장 사담", "딴 얘기"] and ch["nested"]
    await J("MGS='live'; setView('home')")
    await pg.wait_for_timeout(1200)
    await J("mgPop(true)")
    await pg.wait_for_timeout(800)
    pop = await J("[document.querySelectorAll('#mgpop .mgth').length, [...document.querySelectorAll('#mgpop *')].filter(e=>e.offsetWidth&&e.getBoundingClientRect().right>innerWidth+1).length]")
    res["팝업카드"] = pop == [1, 0]
    ok = all(res.values()) and not errs
    print(f"{'OK ' if ok else 'BAD'} 사내톡 쓰레드(390px) " + " ".join(f"{k}={'O' if v else 'X'}" for k, v in res.items())
          + ("" if ok else f" · live={live} ids={ids} th={th} ch={ch}") + (f" · 에러: {errs[0][:160]}" if errs else ""))
    await pg.close()
    return not ok


SMALL_JS = """(()=>{ let n=0; for(const e of document.querySelectorAll('body *')){ if(e.closest('details:not([open])')||e.closest('canvas,svg')) continue;
  if(![...e.childNodes].some(c=>c.nodeType===3&&c.textContent.trim())) continue; const r=e.getBoundingClientRect(); if(!r.width||!r.height) continue;
  if(parseFloat(getComputedStyle(e).fontSize)<11) n++; } return n; })()"""


def _my_fs_fixture(mode: str) -> dict:
    """MY 첫 화면 가짜 pb-private 응답(개인 값 아님 — 스펙 docs/uxui/2026-10-28_my_tab_spec.md 의 가상값). mode: ok | none | stale | future.
    반환: {경로 끝: 본문}. 날짜는 오늘(KST) 기준으로 만든다 — ok = 결론이 숫자보다 1일 뒤, stale = 4일 앞, future = 결론 날짜가 3일 뒤."""
    import json as _json
    from datetime import datetime, timedelta, timezone
    today = datetime.now(timezone(timedelta(hours=9))).date()
    d = lambda n: (today + timedelta(days=n)).isoformat()  # noqa: E731
    la = d(-1)
    latest = {"date": la, "dir": "analysis/fake-weekly", "asof": la, "comment": None, "report": "r.md", "images": [],
              "kpis": [["주간 위성 북 vs 코스피", "+1.8% vs +1.2% (초과 +0.6%p)"], ["전주 대비", "평가액 +1,000원 · 수익률 −2.5% → +1.8%"],
                       ["10월 누적 vs 코스피", "−12.0% vs −10.0%"], ["9/30 기초 이후 vs 코스피", "−12.0% vs −10.0% (초과 −2.0%p)"],
                       ["위성 북 평가액", "1.00M (주간 손익 +1,000원)"], ["구속 스트레스", "−16.0% ⛔ (한도 −15%, 함의 상한 25.0% vs 현재 28.0%)"],
                       ["위반 / 벌금 누적 / 매매 금지", "1건 (적용 0 · 경고 1) / 0원 / 없음"],
                       ["FRM (b) 베타·스트레스 / 계기판 VaR·ES", "초과 1/4 · VaR 1.0% · 베타 1.00 · 스트레스 −16.0%"]],
              "desks": [{"desk": "pb", "file": "analysis/fake-weekly/desk/pb.md"}, {"desk": "cio", "file": "analysis/fake-weekly/desk/cio.md"},
                        {"desk": "frm", "file": "analysis/fake-weekly/desk/frm.md"}, {"desk": "behavior", "file": None},
                        {"desk": "alloc", "file": "analysis/fake-weekly/desk/alloc.md"}, {"desk": "household", "file": None}],
              "stats": {"asof": la, "wk_r": 0.018, "kospi": 0.012, "excess": 0.006, "viol": 1, "viol_live": 0, "stress": -0.16, "stress_ok": False,
                        "semi_in": 0.28, "semi_ex": 0.20, "wk_r_prev": -0.025, "semi_cap_implied": 0.25}}
    desk = {"frm": "# FRM\n\n- **구속 스트레스 ⛔ 초과 지속.** 가짜 한도 초과 문장이다. 둘째 문장은 더보기에만.\n- **둘째 줄:** 안 보임\n",
            "cio": "# CIO\n\n- **성적 해석:** 가짜로 코스피를 앞섰다. 둘째 문장.\n",
            "alloc": "# 자산배분\n\n- **적립:** 가상 예시 적립 12만원은 가려진다. 둘째 문장.\n"}
    out = {"analysis/latest.json": _json.dumps(latest, ensure_ascii=False)}
    out.update({f"analysis/fake-weekly/desk/{k}.md": v for k, v in desk.items()})
    if mode == "ok":   # 무행동 vs 실제(#mydn) — 가짜 지수 3행, 금액 없음
        rw = lambda dt, a, dn, gd, gc: {"date": dt, "dn_total": dn, "act_total": a, "dn_kr": dn, "act_kr": a + 1, "dn_us": dn, "act_us": a - 1,  # noqa: E731
                                         "gap_day_pp": gd, "gap_cum_pp": gc, "mk": "KR+US", "attr": {}}
        out["analysis/donothing.json"] = _json.dumps({"asof_kr": d(-1), "asof_us": d(-1), "base": d(-3), "notes": [], "sources": [],
                                                       "series": [rw(d(-3), 100, 100, 0, 0), rw(d(-2), 99, 98, 1.0, 1.0), rw(d(-1), 98.5, 97, 0.5, 1.5)]})
    if mode != "none":
        h = {"date": d(0), "asof": d(0), "text": "가짜 결론: 주간은 앞섰지만 스트레스 한도 초과 — 반도체 희석이 먼저", "by": "PB", "sources": [],
             "next": ["가짜 행동 하나", "가짜 행동 둘"]}
        if mode == "stale":
            h.update(date=d(-5), asof=d(-5))
        if mode == "future":
            h.update(date=d(3))
        out["analysis/headline.json"] = _json.dumps(h, ensure_ascii=False)
    return out


async def _my_fs_page(b, port: int, mode: str):
    """390×844 터치 기기로 MY 탭을 열고(가짜 토큰·가짜 pb-private) 페이지·에러 목록을 돌려준다. 스크린샷 스크립트도 이걸 쓴다."""
    fx = _my_fs_fixture(mode)
    ctx = await b.new_context(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True)
    pg = await ctx.new_page()
    errs: list[str] = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    await pg.add_init_script("try{ if(!sessionStorage.getItem('_sm')){ sessionStorage.setItem('_sm','1'); localStorage.clear(); localStorage.setItem('mt_gh_tok','smoke'); } }catch(e){}")

    def h(r):
        u = r.request.url.split("?")[0]
        key = u.split("/contents/", 1)[-1] if "/contents/" in u else ""
        if key in fx:
            return r.fulfill(status=200, content_type="text/plain", body=fx[key])
        return r.fulfill(status=404, body="{}")
    await pg.route("https://api.github.com/**", h)
    await pg.goto(f"http://127.0.0.1:{port}/index.html", wait_until="load")
    await pg.wait_for_timeout(1200)
    await pg.evaluate("setView('my')")
    await pg.wait_for_timeout(2200)
    return ctx, pg, errs


async def check_my_first_screen(b, port: int) -> int:
    """MY 첫 화면(UXUI 스펙 2026-10-28 §3·§6): 390×844 에서 ①결론 ②KPI 2×2 ③원인 ④다음 행동이 모두 844px 안 · 가로 스크롤 없음 ·
    첫 화면 원화 금액 0 · '누나' 0 · 색 의미 2개(빨강 ⛔ 한도 초과, 앰버 확인 필요) · headline 없음/오래됨/미래 3상태 표시. 데이터는 가짜(route)."""
    res = {}
    for mode in ("ok", "none", "stale", "future"):
        ctx, pg, errs = await _my_fs_page(b, port, mode)
        r = await pg.evaluate("""(()=>{ const q=s=>document.querySelector(s), bt=s=>{const e=q(s); return e?Math.round(e.getBoundingClientRect().bottom+window.scrollY):9999;};
          const f=q('#myfirst'), t=f?f.innerText:'';
          return {t, b1:bt('#myfs1'), b2:bt('#myfs2'), b4:bt('#myfs4'), k:f?f.querySelectorAll('.myfs-k').length:0,
            hs:document.documentElement.scrollWidth>window.innerWidth+1, desk:f?f.querySelectorAll('.myfs-d').length:0,
            am:f?[...f.querySelectorAll('.am')].filter(e=>!e.closest('summary')).map(e=>e.textContent).join('|'):'', dn:f?f.querySelectorAll('.v-alarm').length:0,   /* 10/31 PB: ⛔ 한도 초과 = .v-alarm 반전 블록(시장 .dn 과 분리) */
            dnt:(q('#mydn')||{}).innerText||'', dnsvg:!!(q('#mydn')&&q('#mydn svg path')),
            corr:!!q('#mycorr'), order:(()=>{const a=q('#myfirst'), c=q('#mycorr'), i=q('#myin'); return !!(a&&c&&i&&(a.compareDocumentPosition(c)&4)&&(c.compareDocumentPosition(i)&4));})()}; })()""")
        res[mode] = (r, errs)
        await ctx.close()
    o = res["ok"][0]
    import re as _re
    won = _re.findall(r"\d[\d,.]*\s*(?:만|억)?\s*원", o["t"])
    ok_ok = (o["b4"] <= 844 and o["k"] == 4 and not o["hs"] and not won and "누나" not in o["t"] and o["desk"] == 3 and o["order"]
             and "가짜 결론" in o["t"] and "앞섬 +0.6%p" in o["t"] and "뒤짐 −2.0%p" in o["t"] and "⛔ 초과 1.0%p" in o["t"]
             and "−2.5% → +1.8%" in o["t"] and "28.0% > 함의 상한 25.0%" in o["t"] and "가짜 행동 둘" in o["t"] and "1일 차이" in o["t"] and o["dn"] >= 1 and not o["am"]
             and "누적 갭 +1.50%p" in o["dnt"] and "오늘 +0.50%p" in o["dnt"] and o["dnsvg"])
    n, s, f = res["none"][0], res["stale"][0], res["future"][0]
    ok_none = "PB 결론 미갱신(읽기 실패)" in n["am"] and "오늘 PB 미작성" in n["t"] and n["b4"] <= 844
    ok_stale = "PB 결론 미갱신(마지막" in s["am"] and "4일 차이" in s["am"] and s["b4"] <= 844
    ok_fut = "날짜 확인 필요" in f["am"] and f["b4"] <= 844
    errs = [e for m in res.values() for e in m[1]]
    ok = ok_ok and ok_none and ok_stale and ok_fut and not any(r[0]["hs"] for r in res.values()) and not errs
    print(f"{'OK ' if ok else 'BAD'} MY첫화면(390×844) 결론↓{o['b1']} KPI↓{o['b2']} 행동↓{o['b4']}px KPI칸={o['k']} 데스크줄={o['desk']} 금액={len(won)} 가로스크롤={'있음' if o['hs'] else '없음'}"
          f" · 없음={'O' if ok_none else 'X'}({n['b4']}) 오래됨={'O' if ok_stale else 'X'}({s['b4']}) 미래={'O' if ok_fut else 'X'}({f['b4']}) 순서={'O' if o['order'] else 'X'}"
          + (f" · 에러: {errs[0][:160]}" if errs else "") + ("" if ok else f" · 본문: {o['t'][:300]!r} · 앰버: {o['am']!r}"))
    return not ok


async def check_uxui_rest(b, port: int) -> int:
    """UXUI Top10 남은 3건(10/24 결재 appr-uxui-top10-next), 390px:
    ① 💬 = 머리(.top) 안 버튼(떠 있지 않음) → 본문을 가리는 고정 요소 0 · 누르면 팝업 · 머리 가로 넘침 없음
    ② 가로 스크롤 표(KR·운용회의)를 오른쪽으로 밀어도 첫 열이 상자 왼쪽에 붙어 있음(sticky)
    ③ 글자 4단계: 보이는 글자 중 11px 미만 0 (home·kr·daily·score·cmt·sysb·msg)."""
    pg = await b.new_page(viewport={"width": 390, "height": 844}, has_touch=True)
    errs: list[str] = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    J = pg.evaluate
    await pg.goto(f"http://127.0.0.1:{port}/index.html", wait_until="load")
    await pg.wait_for_timeout(1500)
    res: dict = {}
    fab = await J("""(()=>{ const f=document.getElementById('mgfab'); if(!f) return null; const r=f.getBoundingClientRect();
      return {inTop:!!f.closest('.top'), pos:getComputedStyle(f).position, w:r.width, h:r.height,
        floats:[...document.querySelectorAll('body *')].filter(e=>getComputedStyle(e).position==='fixed'&&e.offsetWidth&&e.offsetHeight&&!e.closest('#mgpop,.drawer,.backdrop,#dr,#bd')).length,
        over:[...document.querySelectorAll('.top *')].some(e=>e.offsetWidth&&e.getBoundingClientRect().right>innerWidth+1&&!e.closest('.tabs'))}; })()""")
    res["💬머리안"] = bool(fab) and fab["inTop"] and fab["pos"] != "fixed" and fab["w"] >= 44 and fab["floats"] == 0 and not fab["over"]
    await pg.click("#mgfab")
    await pg.wait_for_timeout(1500)
    res["💬팝업"] = await J("!!document.getElementById('mgpop')")
    await J("mgPop(false)")
    small = {}
    stick = {}
    for v in ("home", "kr", "daily", "score", "cmt", "sysb", "msg"):
        await J(f"setView({v!r})")
        await pg.wait_for_timeout(2500)
        small[v] = await J(SMALL_JS)
        if v in ("kr", "cmt"):
            stick[v] = await J("""(()=>{ const box=[...document.querySelectorAll('#root .hscr')].find(e=>e.querySelector('table td')); if(!box) return 'no-hscr';
              const td=[...box.querySelectorAll('table tr>:first-child')].find(c=>!c.hasAttribute('colspan')&&c.offsetWidth); if(!td) return 'no-td';
              box.scrollLeft=400; const bl=box.getBoundingClientRect().left, tl=td.getBoundingClientRect().left;
              return box.scrollLeft>0&&Math.abs(tl-bl)<=12 ? 'ok' : `td ${tl|0} box ${bl|0} sl ${box.scrollLeft}`; })()""")
    res["첫열고정"] = all(x == "ok" for x in stick.values())
    res["작은글자0"] = not any(small.values())
    ok = all(res.values()) and not errs
    print(f"{'OK ' if ok else 'BAD'} UXUI남은3건(390px) " + " ".join(f"{k}={'O' if v else 'X'}" for k, v in res.items())
          + f" · 11px미만 {small} · 첫열 {stick}" + ("" if res["💬머리안"] else f" · 💬={fab}") + (f" · 에러: {errs[0][:160]}" if errs else ""))
    await pg.close()
    return not ok


# 잘림 기준선(UXUI 10/24 재검수 정의: 자기 글자를 가진 요소가 overflow≠visible 또는 ellipsis 인데 scrollWidth > clientWidth+1, 팝업·상세 창 제외).
# 10/24 R1~R4 고친 뒤 실측(main + req-dev-26f063bc). 뷰별로 이보다 늘면 BAD — 줄여서 고쳤으면 숫자도 같이 내린다. 없는 뷰 = 0.
CLIP_BASE = {390: {"re": 4}, 1300: {"home": 2}}   # sysb 1→0: 10/24 UXUI 결재 칩 P2 배지 flex:none
CLIP_1300 = ("home", "rb", "kr", "eng")      # PC 는 UXUI 가 회귀를 본 화면만 (시간 절약)
CLIP_JS = """(()=>{ const out=[]; for(const e of document.querySelectorAll('#root *')){ if(!e.offsetWidth||e.closest('#mgpop,.drawer,#dr')) continue;
  if(![...e.childNodes].some(c=>c.nodeType===3&&c.textContent.trim())) continue; const cs=getComputedStyle(e);
  if((cs.overflowX!=='visible'||cs.textOverflow==='ellipsis')&&e.scrollWidth>e.clientWidth+1) out.push((e.innerText||'').trim().slice(0,30)); } return out; })()"""
HEAD_MAX = 110   # 390px 머리(.top) 높이 상한 — 10/24 R1: 💬 44px 들어오며 105→151px


async def check_head_clip(b, port: int) -> int:
    """UXUI 10/24 재검수(req-dev-26f063bc): ① 390px 머리 .top ≤110px · 💬·🔍 44px·같은 줄 — 실파일과 늦음 주입(빨간 배지) 둘 다
    ② 연구 보드 단계 카드 ≤60px(R4: 56→71) ③ 잘림 기준선 CLIP_BASE 보다 늘어난 뷰 0 (390px 전체 뷰 + 1300px CLIP_1300)."""
    import json as _json
    bad = 0
    for label, body in (("실파일", None), ("늦음 주입", _json.dumps(LATE, ensure_ascii=False))):
        pg = await b.new_page(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True)
        if body:
            await pg.route("**/reports/freshness.json*", lambda r: r.fulfill(status=200, content_type="application/json", body=body))
        await pg.goto(f"http://127.0.0.1:{port}/index.html", wait_until="load")
        await pg.wait_for_timeout(2500)
        h = await pg.evaluate("""(()=>{ const g=id=>{const e=document.getElementById(id); if(!e||!e.offsetWidth) return null; const r=e.getBoundingClientRect(); return {t:r.top|0,h:r.height|0}};
          return {top:document.querySelector('.top').getBoundingClientRect().height|0, fab:g('mgfab'), sqb:g('sqb'), fresh:(document.getElementById('fresh')||{}).textContent||''}; })()""")
        ok = h["top"] <= HEAD_MAX and all(h[k] and h[k]["h"] >= 44 for k in ("fab", "sqb")) and h["fab"]["t"] == h["sqb"]["t"] \
            and (("bad" in await pg.evaluate("document.getElementById('fresh').className")) if body else True)
        bad += not ok
        print(f"{'OK ' if ok else 'BAD'} 머리높이(390px, {label}) .top {h['top']}px ≤{HEAD_MAX} · 💬 {h['fab']} · 🔍 {h['sqb']} · 배지 '{h['fresh']}'")
        await pg.close()
    over: dict = {}
    for w, views in ((390, None), (1300, CLIP_1300)):
        pg = await b.new_page(viewport={"width": w, "height": 844}, has_touch=w < 700, is_mobile=w < 700)
        await pg.goto(f"http://127.0.0.1:{port}/index.html", wait_until="load")
        await pg.wait_for_timeout(2000)
        for v in views or await pg.evaluate(ALL_JS):
            await pg.evaluate(f"setView({v!r})")
            await pg.wait_for_timeout(1800)
            got = await pg.evaluate(CLIP_JS)
            if len(got) > CLIP_BASE[w].get(v, 0):
                over[f"{v}@{w}"] = f"{len(got)}>{CLIP_BASE[w].get(v, 0)} {got[:3]}"
            if v == "rb" and w == 390:
                ch = await pg.evaluate("Math.max(0,...[...document.querySelectorAll('.rbst button')].map(x=>x.getBoundingClientRect().height|0))")
                if ch > 60:
                    over["rb 단계 카드"] = f"{ch}px > 60"
        await pg.close()
    bad += bool(over)
    print(f"{'OK ' if not over else 'BAD'} 잘림 기준선(390 전체·1300 {'/'.join(CLIP_1300)}) 증가 {len(over)}" + (f" · {over}" if over else ""))
    return bad


# HF 진입 근거 펼침 줄(screener/entry_why.py build().long 형식 — tests/test_hf_why_labels.py 가 형식을 고정). 실데이터에 제안이 없는 날도 검사되게 주입.
HF_WHY_FIX = ["근거 기술 — 테스트 = B1 52주 고점 근접(종가/250일 고가 95.0%)·사전등록 B · S4 추격 아님 · 퀀트 hi52 KR B(20일 초과 +1.2%), 단 종목 중앙값 −0.4%·분산 전제",
              "근거 기대값·리스크 — E[R] +0.083R vs 기준선 −0.015R · 손절 86(−13.8%)·1차 손익비 1.5R · 크기 0.9%=리스크 0.125% · 뒤집힘 종가 < 100(250일 고점 95%) → B1 해제",
              "근거 펀더 − 적정가 −25.0% · 2026Q2 영업이익 전년비 −30.0% (detail.valuation·detail.financials)",
              "근거 내러 미확인", "근거 센티 + 외국인·기관 5일 순매수 (detail.flows)", "근거 펀더 중립 실적 변화 없음 (detail.financials)",
              "근거 약함 — 세 축 중 − 2개 이상(표시만, 규칙 불변)"]


async def check_hf_why(b, port: int) -> int:
    """UXUI 10/24 req-uxui-ce6484a5: 운용회의 HF 카드 진입 근거 펼침 줄 = 이름표(왜·값·펀더·내러·센티·약함) + 판정 배지(+·중립·−·미확인, 색 토큰).
    390·1300px · 가로 넘침 0(390px) · 배지 4종 색이 --up/--muted/--dn/--amber · 펼침 없는 날엔 블록 없음."""
    import json as _json
    bad = 0
    for w in (390, 1300):
        pg = await b.new_page(viewport={"width": w, "height": 844}, has_touch=w < 700, is_mobile=w < 700)
        errs: list[str] = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(f"http://127.0.0.1:{port}/index.html", wait_until="load")
        await pg.wait_for_timeout(2000)
        await pg.evaluate("setView('cmt')")
        await pg.wait_for_timeout(2500)
        r = await pg.evaluate("""(fix)=>{ if(typeof CMT!=='object'||!CMT||!CMT.hf||!(CMT.hf.lines||[]).length) return {nohf:true};
          const none=!document.querySelector('#root .hfwhy')===((CMT.hf.lines||[]).length<=4);
          CMT.hf.lines=CMT.hf.lines.slice(0,4).concat(fix); render();
          const box=document.querySelector('#root .hfwhy'); if(!box) return {none, box:false};
          const rows=[...box.querySelectorAll('.hfw')].map(d=>({k:d.querySelector('b').textContent, v:(d.querySelector('.hfv')||{}).textContent||'', c:d.querySelector('.hfv')?getComputedStyle(d.querySelector('.hfv')).color:''}));
          const css=n=>{const t=document.createElement('span'); t.style.color=`var(${n})`; document.body.appendChild(t); const c=getComputedStyle(t).color; t.remove(); return c;};
          const tok={'+':css('--up'),'−':css('--dn'),'중립':css('--muted'),'미확인':css('--amber')};
          const fs=[...box.querySelectorAll('*')].map(e=>parseFloat(getComputedStyle(e).fontSize));
          return {none, box:true, keys:rows.map(x=>x.k).join(','), vs:rows.filter(x=>x.v).map(x=>x.v).join(','), color:rows.filter(x=>x.v).every(x=>x.c===tok[x.v]),
            fs:[...new Set(fs)].sort(), over:document.scrollingElement.scrollWidth>innerWidth+1||[...box.querySelectorAll('*')].some(e=>e.getBoundingClientRect().right>innerWidth+1)}; }""", HF_WHY_FIX)
        ok = (r.get("nohf") or (r["box"] and r["none"] and r["keys"] == "왜,값,펀더,내러,센티,펀더,약함" and r["vs"] == "−,미확인,+,중립" and r["color"]
              and all(x in (11, 13, 16, 17) for x in r["fs"]) and not r["over"])) and not errs
        bad += not ok
        print(f"{'OK ' if ok else 'BAD'} HF 진입 근거 이름표·배지({w}px) " + ("HF 블록 없음(검사 건너뜀)" if r.get("nohf") else f"이름표 {r.get('keys')} · 배지 {r.get('vs')} · 색 {r.get('color')} · 글자 {r.get('fs')} · 넘침 {r.get('over')}")
              + (f" · 에러: {errs[0][:160]}" if errs else ""))
        await pg.close()
    return bad


async def check_xl_beyond(b, port: int) -> int:
    """UXUI 10/24 엑셀 스킨 재검수(docs/uxui/2026-10-24_xl_recheck.md) — skin_audit 자(글자 대비) 밖 그림·상태 4건, 1300px:
    ① 색 토큰 차트(#root lightweight-charts)는 반전 안 함(검정 상자 금지) — 첫 차트 화면 바탕이 밝은가 ② 대결 곡선 선 대비 ≥3:1(흰 바탕)
    ③ HOME 달력 선택일이 다른 날과 구별(테두리/외곽선) ④ 프로필 '더보기' 글자색 ≠ 바탕(흰 바탕 흰 글자 금지)."""
    import skin_audit as sa
    ctx, pg = await sa.page(b, port, 1300, "xl")
    errs: list[str] = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    res: dict = {}
    await pg.evaluate("setView('deriv')")
    await pg.wait_for_timeout(2500)
    res["토큰차트반전없음"] = await pg.evaluate("(()=>{ const c=[...document.querySelectorAll('#root .tv-lightweight-charts canvas')]; return c.length>0 && c.every(x=>getComputedStyle(x).filter==='none'); })()")
    await pg.evaluate("setView('score')")
    await pg.wait_for_timeout(2500)
    res["대결곡선3:1"] = await pg.evaluate(r"""(()=>{ const L=c=>{const f=v=>{v/=255; return v<=.03928?v/12.92:Math.pow((v+.055)/1.055,2.4)}; return .2126*f(c[0])+.7152*f(c[1])+.0722*f(c[2])};
      const ps=[...document.querySelectorAll('#root svg polyline')].filter(e=>e.getBoundingClientRect().width>0); if(!ps.length) return true;
      return ps.every(e=>{ const m=getComputedStyle(e).stroke.match(/\d+/g); if(!m) return true; const l=L(m.slice(0,3).map(Number)); return 1.05/(l+.05)>=3; }); })()""")
    await pg.evaluate("setView('home')")
    await pg.wait_for_timeout(2000)
    res["달력선택"] = await pg.evaluate("""(()=>{ const cs=[...document.querySelectorAll('.calc')]; const t=cs.find(x=>getComputedStyle(x).cursor==='pointer'); if(!t) return true; t.click();
      return new Promise(r=>setTimeout(()=>{ const s=[...document.querySelectorAll('.calc')].find(x=>x.dataset.d===t.dataset.d); r(!!s&&getComputedStyle(s).outlineStyle==='solid'); },400)); })()""")
    await pg.evaluate("setView('msg')")
    await pg.wait_for_timeout(2500)
    res["프로필더보기"] = await pg.evaluate("""(()=>{ const k=((typeof MG==='object'&&MG&&MG.profiles)||[]).map(p=>p.key)[0]; if(!k) return true; mgProf(k);
      const d=document.querySelector('[data-card] details'); if(!d) return false; d.open=true; const t=d.querySelector('div'); const c=getComputedStyle(t).color, bg=getComputedStyle(d).backgroundColor;
      const ok=c!==bg; document.querySelectorAll('[data-card]').forEach(e=>e.closest('div[style*="z-index:99"]')&&e.closest('div[style*="z-index:99"]').remove()); return ok; })()""")
    ok = all(res.values()) and not errs
    print(f"{'OK ' if ok else 'BAD'} 엑셀 스킨 그림·상태(1300px) " + " ".join(f"{k}={'O' if v else 'X'}" for k, v in res.items()) + (f" · 에러: {errs[0][:160]}" if errs else ""))
    await ctx.close()
    return not ok


async def check_xl(b, port: int) -> int:
    """엑셀 스킨(html.xl, localStorage mt_skin='xl') 상시 검사 — 10/24 겸이 "엑셀버전도 다 자동수정되는거지?"·"톡방이 검정색"(req-dev-0d1eee58).
    390·1300px 35개 화면 전부: 글자 대비 미달 0(본문 4.5·큰 글자/기호 3) · 가로 넘침 0 · 11px 미만 0 · 잘림 ≤ CLIP_BASE.
    + 사내톡 7개 구역 대비 0 · 머리(390): .top ≤110·💬/🔍 44px 같은 줄·시트 탭 하단 고정 · 목록 44px 규칙은 xl 제외(촘촘)
    + HF 근거 판정 배지는 색(xl --up=#000) 말고 글자(+·−·중립)로 구분 · 달력 K/S 두 줄. 측정 정의·전 화면 표는 scripts/skin_audit.py."""
    import skin_audit as sa
    bad = 0
    for w in (390, 1300):
        ctx, pg = await sa.page(b, port, w, "xl")
        errs: list[str] = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        res: dict = {}
        hd = await pg.evaluate("""(()=>{ const g=s=>{const e=document.querySelector(s); if(!e||!e.offsetWidth) return null; const r=e.getBoundingClientRect(); return {t:r.top|0,h:r.height|0,b:r.bottom|0}};
          return {xl:document.documentElement.classList.contains('xl'), top:g('.top'), fab:g('#mgfab'), sqb:g('#sqb'), tabs:g('.tabs'), tpos:getComputedStyle(document.querySelector('.tabs')).position}; })()""")
        res["xl켜짐"] = hd["xl"]
        res["머리"] = hd["top"]["h"] <= HEAD_MAX and hd["fab"] and hd["fab"]["h"] >= 44 and hd["tabs"]["b"] >= 840 and hd["tpos"] == "fixed" \
            and (w > 700 or (hd["sqb"] and hd["sqb"]["h"] >= 44 and hd["sqb"]["t"] == hd["fab"]["t"]))
        fail: dict = {}
        hc = await pg.evaluate(f"({sa.CONTRAST_JS})('.top *,.tape *,#subt *,.tabs *,#xlrib *,#xlfx *')")
        if hc["bad"]:
            fail["머리 대비"] = hc["bad"][:2]
        for v in await pg.evaluate(ALL_JS):
            await pg.evaluate(f"setView({v!r})")
            await pg.wait_for_timeout(1800)
            m = await sa.measure(pg, w)
            if m["contrast"] or m["over"] or m["small"] or m["emoji"] or m["clip"] > CLIP_BASE[w].get(v, 0):   # emoji = 회색 처리 안 된 컬러 이모지(req-dev-06b280d5)
                fail[v] = {k: m[k] for k in ("contrast", "over", "small", "clip", "emoji")} | {"ex": m["ex"][:2]}
            if v == "apt" and w == 390:
                h = await pg.evaluate("Math.max(0,...[...document.querySelectorAll('#root .sbtn')].filter(e=>e.offsetWidth).map(e=>e.getBoundingClientRect().height|0))")
                res["44px제외"] = 0 < h and await pg.evaluate("Math.min(...[...document.querySelectorAll('#root .sbtn')].filter(e=>e.offsetWidth).map(e=>e.getBoundingClientRect().height|0))") < 44
            if v == "cmt":
                res["HF배지글자"] = await pg.evaluate("""(()=>{ if(typeof cmtHFWhy!=='function') return false; const d=document.createElement('div');
                  d.innerHTML=cmtHFWhy(['근거 펀더 + 실적 상향','근거 내러 − 수급 이탈','근거 센티 중립']); document.getElementById('root').appendChild(d);
                  const t=[...d.querySelectorAll('.hfv')].map(e=>e.textContent.trim()); const c=[...d.querySelectorAll('.hfv')].map(e=>getComputedStyle(e).color); d.remove();
                  return t.join(',')==='+,−,중립'; })()""")
            if v == "home" and w == 390:
                res["달력KS"] = await pg.evaluate(r"""(()=>{ const c=[...document.querySelectorAll('.calc')].find(c=>/K[+\-−]/.test(c.innerText)&&/S[+\-−]/.test(c.innerText)); if(!c) return 'none';
                  const t=c.innerText.split('\n').map(x=>x.trim()); return t.some(x=>/^K[+\-−]/.test(x))&&t.some(x=>/^S[+\-−]/.test(x)); })()""") in (True, "none")
            if v == "msg":
                segs = await pg.evaluate("[...document.querySelectorAll('#root [data-mgs]')].map(b=>b.dataset.mgs)")
                for sg in segs:
                    await pg.click(f"#root [data-mgs='{sg}']")
                    await pg.wait_for_timeout(1500)
                    c = await pg.evaluate(f"({sa.CONTRAST_JS})('#root *')")
                    if c["bad"]:
                        fail[f"msg:{sg}"] = c["bad"][:2]
                await pg.click("#root [data-mgs='live']") if "live" in segs else None
        res["전화면"] = not fail
        ok = all(res.values()) and not errs
        bad += not ok
        print(f"{'OK ' if ok else 'BAD'} 엑셀스킨({w}px) " + " ".join(f"{k}={'O' if v else 'X'}" for k, v in res.items())
              + f" · 머리 {hd['top']['h']}px" + (f" · 실패 {fail}" if fail else "") + (f" · 에러: {errs[0][:160]}" if errs else ""))
        await ctx.close()
    return bad


async def check_links_pcr(b, port: int) -> int:
    """UXUI 10/24 엑셀 재검수 후속(req-dev-3d26f6e6·06b280d5):
    ① 기본 스킨 1300px 35화면: 문장 속 링크 중 밑줄 없이 색으로만 구분되는 것 0 (skin_audit LINK_JS, 점선 밑줄 a.il)
    ② 파생 PCR 차트 두 선 색이 기본·엑셀 둘 다 서로 다름(--ch1·--ch2) ③ 기본 스킨은 이모지 모양 그대로(.xe 회색은 엑셀만)."""
    import skin_audit as sa
    bad = 0
    fail: dict = {}
    ctx, pg = await sa.page(b, port, 1300, "def")
    for v in await pg.evaluate(ALL_JS):
        await pg.evaluate(f"setView({v!r})")
        await pg.wait_for_timeout(1500)
        lk = await pg.evaluate(sa.LINK_JS)
        if lk["bad"]:
            fail[v] = lk
    res = {"링크밑줄": not fail}
    res["기본이모지컬러"] = await pg.evaluate("(()=>{ const e=document.querySelector('#root .xe,body .xe'); return !e||!/grayscale/.test(getComputedStyle(e).filter); })()")
    await ctx.close()
    for skin in ("def", "xl"):
        ctx, pg = await sa.page(b, port, 1300, skin)
        c = await pg.evaluate("(()=>{ const cs=getComputedStyle(document.documentElement); return [cs.getPropertyValue('--ch1').trim(), cs.getPropertyValue('--ch2').trim()]; })()")
        res[f"PCR색({skin})"] = bool(c[0]) and c[0] != c[1]
        await ctx.close()
    ok = all(res.values())
    bad += not ok
    print(f"{'OK ' if ok else 'BAD'} 링크·PCR(1300px) " + " ".join(f"{k}={'O' if v else 'X'}" for k, v in res.items()) + (f" · 링크 미달 {fail}" if fail else ""))
    return bad


BOND_LATE = {"checked_at": "2026-10-21 12:00", "n": 21, "late": [{"id": "bonds", "path": "reports/bonds.json", "expected": "2026-10-21", "actual": "2026-10-20",
              "mode": "briefing", "fix": "gh workflow run briefing.yml -f mode=bonds", "desc": "채권 화면"}]}


async def check_macro_bond_top(b, port: int) -> int:
    """MARKET › MACRO 첫 화면(macro-tab, 10/23 원자재 macCmd·지정학 macGeo 패널 포함)·채권 '지금 채권 상황 3줄'(bonds-summary), 10/21 겸이: 390px 에서 첫 패널 · 결론(바람·격차 / 수준·방향·의미)이
    첫 화면(844px) 안(10/26 묶음 B: 상단 3칸 카드 #tabTop 높이만큼 허용 — 결론이 그 카드로 올라감) · 기준 배지 · 가로 넘침 없음 · 신선도 계약 late(bonds) 주입 시 ⚠ STALE · dataLag 판정(오래된 날짜만 늦음)."""
    import json as _json
    bad = 0
    for label, body in (("실파일", None), ("bonds 늦음 주입", _json.dumps(BOND_LATE, ensure_ascii=False))):
        pg = await b.new_page(viewport={"width": 390, "height": 844})
        errs: list[str] = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        if body:
            await pg.route("**/reports/freshness.json*", lambda r: r.fulfill(status=200, content_type="application/json", body=body))
        await pg.goto(f"http://127.0.0.1:{port}/index.html", wait_until="load")
        await pg.wait_for_timeout(2000)
        res: dict = {}
        await pg.evaluate("setView('macro')")
        await pg.wait_for_timeout(3000)
        # cmd(10/28): 원자재 패널 기본 = '많이 움직인 3개'만 보이고 나머지는 접힌 #macCmdAll(7e1c2b3c4) — innerText '구리'는 그날 시세 순위에 달려 흔들림.
        # → 구리 행이 패널 DOM 에 있고 + 보이는 줄 = 1주 변동 상위 min(3,대상) + 전체 접힘에 commodities.json 행 전부 (데이터와 화면 대조)
        m = await pg.evaluate("""(()=>{ const t=document.getElementById('macTop'), f=document.querySelector('#root .p'), g=document.getElementById('macGap'), w=document.getElementById('macWind'), gl=document.getElementById('macGlance');
          if(!t) return null; const tx=t.innerText; return {first:f===t, bot:Math.max(g?g.getBoundingClientRect().bottom:9999, w?w.getBoundingClientRect().bottom:9999),
          wind:tx.includes('매크로 바람'), gap:!!g&&tx.includes('격차'), asof:!!t.querySelector('.asof'), tiles:t.querySelectorAll('.mct').length,
          need:['금리','기준금리','환율','유가','다음 주요 일정','FOMC'].every(w=>tx.includes(w)), stale:tx.includes('STALE'),
          over:[...document.querySelectorAll('#root *')].some(e=>e.getBoundingClientRect().right>innerWidth+1&&!e.closest('table')),
          lag:dataLag('KR','2020-01-02',0)!==''&&dataLag('KR',mkPhase('KR').last,0)==='',
          glance:!!gl&&gl.querySelectorAll('.mgl').length>=5&&gl.getBoundingClientRect().bottom<=844&&gl.innerText.includes('데스크 해석'), cmd:(()=>{ const c=document.getElementById('macCmd'), cm=MCX.cm||{}; if(!c) return false;
            const n3=Math.min(3,(cm.rows||[]).filter(r=>r.status==='ok'&&r.group!=='파생'&&r.freq!=='월간'&&r.chg1w!=null).length);
            return c.textContent.includes('구리') && [...c.querySelectorAll('.mcc')].filter(e=>!e.closest('#macCmdAll')).length===n3 && c.querySelectorAll('#macCmdAll .mcc').length===(cm.rows||[]).length; })(), geo:((document.getElementById('macGeo')||{}).innerText||'').includes('호르무즈') }; })()""")
        res["MACRO"] = bool(m) and m["first"] and m["bot"] <= 844 and m["wind"] and m["gap"] and m["asof"] and m["tiles"] >= 5 and m["need"] and not m["over"] and m["lag"] and m["cmd"] and m["geo"] and m["glance"] and (m["stale"] if body else True)
        await pg.evaluate("setView('bond')")
        await pg.wait_for_timeout(3000)
        n = await pg.evaluate("""(()=>{ const t=document.getElementById('bondNow'), f=document.querySelector('#root .p'); if(!t) return null; const tx=t.innerText;
          return {first:f===t, bot:t.querySelector('.b').children[2].getBoundingClientRect().bottom, three:['수준','방향','의미','국고 3년','미 10년','10Y−3Y','손익분기'].every(w=>tx.includes(w)),
          asof:!!t.querySelector('.asof'), stale:tx.includes('STALE'), over:[...t.querySelectorAll('*')].some(e=>e.getBoundingClientRect().right>innerWidth+1)}; })()""")
        res["채권3줄"] = bool(n) and n["first"] and n["bot"] <= 844 and n["three"] and n["asof"] and not n["over"] and (n["stale"] if body else True)
        ok = all(res.values()) and not errs
        bad += not ok
        print(f"{'OK ' if ok else 'BAD'} MACRO·채권3줄(390px, {label}) " + " ".join(f"{k}={'O' if v else 'X'}" for k, v in res.items())
              + ("" if ok else f" · macro={m} · bond={n}") + (f" · 에러: {errs[0][:160]}" if errs else ""))
        await pg.close()
    return bad


async def check_all_top(b, port: int) -> int:
    """모든 탭 상단 3칸(묶음 B, 10/26 겸이 "모든 탭의 모든 내용들 다"): 전체 뷰마다 #root 안 .tl-top 에 ①②③ 3줄 + 원본 표기 ·
    390px·1300px × 기본(다크)·엑셀(라이트) 스킨 · 가로 넘침 없음 · 종목 상세 패널(#detTop)도 1회."""
    bad = 0
    for w, h in ((390, 844), (1300, 900)):
        for skin in ("", "xl"):
            pg = await b.new_page(viewport={"width": w, "height": h})
            errs: list[str] = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            await pg.add_init_script(f"try{{localStorage.setItem('mt_skin',{skin!r})}}catch(e){{}}")
            await pg.goto(f"http://127.0.0.1:{port}/index.html", wait_until="load")
            await pg.wait_for_timeout(2000)
            views = await pg.evaluate(ALL_JS)
            miss = []
            for v in views:
                await pg.evaluate(f"setView({v!r})")
                r = None
                for _ in range(8):
                    await pg.wait_for_timeout(500)
                    r = await pg.evaluate("""(()=>{ const t=document.querySelector('#root .tl-top'); if(!t) return null; const x=t.textContent;   // 390px 는 접힘(원본 줄 숨김) — DOM 존재로 확인
                      return {rows:t.querySelectorAll('.tl-row').length, ok:['What','So What','Now What','원본'].every(k=>x.includes(k)),
                      over:t.getBoundingClientRect().right>innerWidth+1}; })()""")
                    if r and r["rows"] == 3:
                        break
                if not r or r["rows"] != 3 or not r["ok"] or r["over"]:
                    miss.append(f"{v}:{r}")
            det = None
            if w == 1300 and not skin:
                await pg.evaluate("openDetail('005930','KR')")
                await pg.wait_for_timeout(3000)
                det = await pg.evaluate("!!document.querySelector('#dr-b #detTop .tl-top')")
                if not det:
                    miss.append("detail")
            ok = not miss and not errs
            bad += not ok
            print(f"{'OK ' if ok else 'BAD'} 모든 탭 상단 3칸({w}px, {skin or '기본'}) 뷰 {len(views)}개" + (" · 상세 O" if det else "")
                  + ("" if not miss else f" · 없음/불량: {' '.join(miss)[:400]}") + (f" · 에러: {errs[0][:160]}" if errs else ""))
            await pg.close()
    return bad


async def check_re_ga(b, port: int) -> int:
    """부동산 법정동 '가' 묶음(10/26 겸이 OK, 영등포구 실파일): 구 화면 = 문래동1가~6가가 '문래동' 하나로 묶임(지도 data-grp·라벨 1개, 목록 묶음 버튼, 건수 = 구성 동 합)
    → 묶음 누르면 data-lv=grp 확대 + 1가~N가 분리 목록 → 동 누르면 dong → 빵부스러기 grp·gu 원복. 390px·1300px."""
    import json as _j
    T = _j.loads((ROOT / "reports/realestate_trades/11560.json").read_text(encoding="utf-8"))
    nsum = sum(d["n"] for d in T["dongs"] if d["name"].startswith("문래동"))
    bad = 0
    for w in (390, 1300):
        pg = await b.new_page(viewport={"width": w, "height": 900})
        errs: list[str] = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(f"http://127.0.0.1:{port}/index.html", wait_until="load")
        await pg.wait_for_timeout(1500)
        await pg.evaluate("setView('re')")
        await pg.wait_for_timeout(2500)
        await pg.evaluate("reSel('영등포구')")
        await pg.wait_for_timeout(3500)
        r = {}
        st = await pg.evaluate("""(()=>{ const s=document.getElementById('rezsvg'), g=document.querySelector('#redr .regrp[data-grp="문래동"]');
          return {lv:s&&s.dataset.lv, grp:s?s.querySelectorAll('path[data-grp="문래동"]').length:0, lab:s?[...s.querySelectorAll('text')].filter(t=>t.textContent.startsWith('문래·')).length:0,
          btn:g?g.getAttribute('aria-label'):'', single:!!document.querySelector('#redr .redit[aria-label^="문래동3가"]')}; })()""")
        r["묶음"] = st["lv"] == "gu" and st["grp"] >= 2 and st["lab"] == 1 and f"매매 {nsum}건" in st["btn"] and not st["single"]
        await pg.evaluate("reDongP('문래동3가')")
        await pg.wait_for_timeout(1500)
        st2 = await pg.evaluate("""(()=>{ const s=document.getElementById('rezsvg'); return {lv:s&&s.dataset.lv, m:[...document.querySelectorAll('#redr .redit')].map(e=>e.getAttribute('aria-label')||'').filter(t=>/^문래동\\d가/.test(t)).length,
          crumb:(document.querySelector('#redr .recrumb')||{}).innerText||''}; })()""")
        r["분리"] = st2["lv"] == "grp" and st2["m"] >= 2 and "문래동" in st2["crumb"]
        await pg.evaluate("reDongP('문래동3가')")
        await pg.wait_for_timeout(1200)
        r["동"] = await pg.evaluate("document.getElementById('rezsvg').dataset.lv==='dong'")
        await pg.evaluate("reGo('grp')")
        await pg.wait_for_timeout(800)
        r["grp복귀"] = await pg.evaluate("document.getElementById('rezsvg').dataset.lv==='grp'")
        await pg.evaluate("reGo('gu')")
        await pg.wait_for_timeout(800)
        r["gu복귀"] = await pg.evaluate("document.getElementById('rezsvg').dataset.lv==='gu'")
        ok = all(r.values()) and not errs
        bad += not ok
        print(f"{'OK ' if ok else 'BAD'} 부동산 '가' 묶음({w}px) " + " ".join(f"{k}={'O' if v else 'X'}" for k, v in r.items())
              + ("" if ok else f" · {st} · {st2}") + (f" · 에러: {errs[0][:160]}" if errs else ""))
        await pg.close()
    return bad


def _intra_fixture(age_min: int = 2, session: str = "LIVE") -> str:
    """reports/intraday_last.json schema 2 합성 픽스처(계약 screener/intraday_last.py) — trade_date 는 먼 미래라 실데이터 날짜가 바뀌어도 '마지막 t < trade_date' 가 항상 참."""
    import json as _j
    from datetime import datetime, timedelta, timezone
    at = (datetime.now(timezone(timedelta(hours=9))) - timedelta(minutes=age_min)).strftime("%Y-%m-%d %H:%M KST")
    blk = lambda q: {"trade_date": "2099-01-02", "session": session, "asof": at, "n": len(q), "q": q}   # noqa: E731
    return _j.dumps({"schema": 2, "fields": ["o", "h", "l", "c", "v", "pc", "r1", "src", "x", "gap", "gk", "gf"], "gap_band": 0.005, "asof": at,
                     "KR": blk({"005930": [210000.0, 216000.0, 209000.0, 215000.0, 1000000, 200000.0, 0.075, "n", 1, 0.05, "U", 0]}),
                     "US": blk({"AAPL": [300.0, 305.0, 299.0, 304.0, 0, 301.0, 0.01, "y", 0, None, "0", None]})})


async def check_intraday_bar(b, port: int) -> int:
    """종목 상세 오늘 장중 잠정 봉(req-front-75d54530, 계약 schema 2): 픽스처 주입 → KR 005930 = 노트 '장중 HH:MM 네이버'·갭상 +5.0%·차트 봉 +1,
    US AAPL x=0 = '고저 관측 근사(5분)'·갭 배지 없음(gap null) · LIVE 인데 asof 30분 전이면 안 붙임 · 390px 가로 넘침 없음."""
    res: dict = {}
    for name, age in (("fresh", 2), ("stale", 30)):
        pg = await b.new_page(viewport={"width": 390, "height": 844})
        errs: list[str] = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        body = _intra_fixture(age)
        await pg.route("**/intraday_last.json*", lambda r, *_, _b=body: r.fulfill(status=200, content_type="application/json", body=_b))
        await pg.goto(f"http://127.0.0.1:{port}/index.html", wait_until="load")
        await pg.wait_for_timeout(1500)
        for sym, mk in (("005930", "KR"), ("AAPL", "US")):
            await pg.evaluate(f"INTRA_AT=0; openDetail({sym!r},{mk!r})")
            await pg.wait_for_timeout(2500)
            r = await pg.evaluate("""(()=>{ const n=document.querySelector('#ch-intra'); const L=LASTCH&&LASTCH[0]; const ib=L?intraBar(L):null;
              return {note:n?n.innerText:null, live:!!ib, over:document.documentElement.scrollWidth-document.documentElement.clientWidth,
                right:Math.max(0,...[...document.querySelectorAll('#ch-intra *')].map(e=>e.getBoundingClientRect().right))}; })()""")
            r["errs"] = errs[:1]
            res[f"{name}:{mk}"] = r
        await pg.close()
    kr, us, st = res["fresh:KR"], res["fresh:US"], res["stale:US"]
    ok = (kr["live"] and "장중" in (kr["note"] or "") and "네이버" in kr["note"] and "갭상 +5.0%" in kr["note"] and "관측 근사" not in kr["note"]
          and us["live"] and "관측 근사" in (us["note"] or "") and "갭" not in us["note"].replace("갭상", "").replace("갭하", "") and "야후" in us["note"]
          and not st["live"] and st["note"] == "" and not res["stale:KR"]["live"]
          and all(v["over"] <= 1 and v["right"] <= 391 and not v["errs"] for v in res.values()))
    print(f"{'OK ' if ok else 'BAD'} 장중 잠정 봉(390px) KR={kr['note'][:60] if kr['note'] else kr} · US={'근사' if us['live'] and '관측 근사' in (us['note'] or '') else us} · 20분 초과 안 붙임={'O' if not st['live'] else 'X'}"
          + "".join(f" · {k} 에러: {v['errs'][0][:120]}" for k, v in res.items() if v["errs"]) + "".join(f" · {k} 넘침 {v['over']}/{v['right']:.0f}" for k, v in res.items() if v["over"] > 1 or v["right"] > 391))
    return not ok


async def check_btc_detail(b, port: int) -> int:
    """BTC 상세(req-front-49f46a4c): openMacro('BTC') → '확정 일봉 · <closed_asof>' 와 '진행 중 봉 · <live_date>' 두 날짜 분리 · 추세·ATR14·지지/고점 · 390px 넘침 없음.
    btc.json 은 저장소 파일(raw 실패 시 상대경로) — raw 도 같은 파일이라 기대값은 저장소에서 읽는다."""
    import json as _j
    J0 = _j.loads((ROOT / "reports/btc.json").read_text(encoding="utf-8"))
    pg = await b.new_page(viewport={"width": 390, "height": 844})
    errs: list[str] = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    await pg.route("**/market-screener/main/reports/btc.json*", lambda r: r.fulfill(status=404, body=""))   # raw → 로컬 파일로(기대값 일치)
    await pg.goto(f"http://127.0.0.1:{port}/index.html", wait_until="load")
    await pg.wait_for_timeout(1500)
    await pg.evaluate("openMacro('BTC')")
    await pg.wait_for_timeout(3000)
    r = await pg.evaluate("""(()=>{ const e=document.querySelector('#btcB'); return {t:e?e.innerText:'', over:document.documentElement.scrollWidth-document.documentElement.clientWidth,
      right:Math.max(0,...[...document.querySelectorAll('#btcBox *')].map(x=>x.getBoundingClientRect().right))}; })()""")
    t = r["t"]
    ok = (f"확정 일봉 · {J0['closed_asof']}" in t and f"진행 중 봉 · {J0['live_date']}" in t and "ATR14" in t and "지지" in t and "고점" in t
          and str(J0.get("trend", "")) in t and r["over"] <= 1 and r["right"] <= 391 and not errs) if J0.get("ok") else ("데이터 없음" in t and not errs)
    print(f"{'OK ' if ok else 'BAD'} BTC 상세(390px) 확정={J0.get('closed_asof')} 진행={J0.get('live_date')} 넘침={r['over']}/{r['right']:.0f} {t[:50]!r}" + (f" · 에러: {errs[0][:160]}" if errs else ""))
    await pg.close()
    return not ok


async def check_deriv_tv(b, port: int) -> int:
    """파생 탭 코스피200 선물 라이브 차트(req-front-4e7ee8ad): 기본 접힘(iframe 0 — 다시 그릴 때 위젯 재로딩 방지) · 네이버 선물 대체 링크 항상 ·
    버튼 누르면 widgetembed KRX:K2I1! iframe 1개 · 390px 버튼 높이 ≥44(터치 기기) · 넘침 없음. 위젯 외부 요청은 막는다(표시만 확인)."""
    ctx = await b.new_context(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True)
    pg = await ctx.new_page()
    errs: list[str] = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    await pg.route("**/s.tradingview.com/**", lambda r: r.fulfill(status=200, content_type="text/html", body="<html><body>tv</body></html>"))
    await pg.goto(f"http://127.0.0.1:{port}/index.html", wait_until="load")
    await pg.wait_for_timeout(1500)
    await pg.evaluate("setView('deriv')")
    await pg.wait_for_timeout(2500)
    J = lambda js: pg.evaluate(js)   # noqa: E731
    r0 = await J("""(()=>{ const p=document.getElementById('dvTv'), bt=document.getElementById('dvTvBtn'); return p?{ifr:p.querySelectorAll('iframe').length, nv:!!p.querySelector('a[href*="naver.com/sise"]'),
      h:bt?bt.getBoundingClientRect().height:0}:null; })()""")
    if r0:
        await pg.click("#dvTvBtn")
        await pg.wait_for_timeout(500)
    r1 = await J("""(()=>{ const p=document.getElementById('dvTv'); const f=p&&p.querySelector('iframe'); return {src:f?f.src:'', nv:!!(p&&p.querySelector('a[href*="naver.com/sise"]')),
      over:document.documentElement.scrollWidth-document.documentElement.clientWidth, right:p?Math.max(0,...[...p.querySelectorAll('*')].map(x=>x.getBoundingClientRect().right)):999}; })()""")
    ok = bool(r0) and r0["ifr"] == 0 and r0["nv"] and r0["h"] >= 44 and "widgetembed" in r1["src"] and "K2I1" in r1["src"] and r1["nv"] \
        and r1["over"] <= 1 and r1["right"] <= 391 and not errs
    print(f"{'OK ' if ok else 'BAD'} 파생 K200 선물 차트(390px) 접힘={r0} 펼침={'O' if 'K2I1' in r1['src'] else 'X'} 넘침={r1['over']}/{r1['right']:.0f}" + (f" · 에러: {errs[0][:160]}" if errs else ""))
    await ctx.close()
    return not ok


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["--root"]:
        SERVE = Path(args[1]).resolve()
        args = args[2:]
    if args[:1] == ["--only"]:   # 체크 하나만(전체가 느릴 때): python3 scripts/ui_smoke.py --only check_re_drill
        fn_only = globals()[args[1]]

        async def _only(port: int) -> int:
            from playwright.async_api import async_playwright
            exe = (glob.glob("/opt/pw-browsers/chromium-*/chrome-linux*/chrome") or [None])[0]
            async with async_playwright() as p:
                b = await p.chromium.launch(args=["--no-sandbox"], **({"executable_path": exe} if exe else {}))
                n = await fn_only(b, port)
                await b.close()
            return n
        srv = _serve(0)
        try:
            sys.exit(1 if asyncio.run(_only(srv.server_address[1])) else 0)
        finally:
            srv.shutdown()
    srv = _serve(0)   # 빈 포트 자동
    try:
        sys.exit(1 if asyncio.run(run(args or VIEWS, srv.server_address[1])) else 0)
    finally:
        srv.shutdown()
