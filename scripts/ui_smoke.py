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
ALL_JS = "[...new Set(Object.values(GROUPS).flat().map(x=>x[0]))]"
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
        bad += await check_my_ledger(b, port)
        bad += await check_cmt_us(b, port)
        bad += await check_score(b, port)
        bad += await check_eng(b, port)
        bad += await check_macro_popup(b, port)
        bad += await check_syn(b, port)
        bad += await check_deriv_top(b, port)
        bad += await check_duel_toggle(b, port)
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
    """파생 탭 맨 위 '파생 한눈에'(10/20 겸이): 390px 에서 첫 패널 · 카드 4개+ · '그래서 겸이는?' · 버튼 44px · 가로 넘침 없음."""
    pg = await b.new_page(viewport={"width": 390, "height": 844})
    errs: list[str] = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    await pg.goto(f"http://127.0.0.1:{port}/index.html", wait_until="load")
    await pg.wait_for_timeout(1500)
    await pg.evaluate("setView('deriv')")
    await pg.wait_for_timeout(2500)
    r = await pg.evaluate("""(()=>{ const t=document.getElementById('dvTop'), f=document.querySelector('#root .p'); if(!t) return null;
      const bt=t.querySelector('button'); return {first:f===t, n:t.querySelectorAll('.dvtc').length, so:t.innerText.includes('그래서 겸이는?'),
      h:bt?bt.getBoundingClientRect().height:0, over:document.documentElement.scrollWidth-document.documentElement.clientWidth}; })()""")
    ok = bool(r) and r["first"] and r["n"] >= 4 and r["so"] and r["h"] >= 44 and r["over"] <= 1 and not errs
    print(f"{'OK ' if ok else 'BAD'} 파생 한눈에(390px) {r}" + (f" · 에러: {errs[0][:160]}" if errs else ""))
    await pg.close()
    return not ok


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
        miss = [x for x in need if x not in txt] + ([] if "성적표" in sub else ["하위 탭"]) + ([] if "성적표 전체" in dl else ["DAILY 대결 박스 링크"])
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
        pg = await b.new_page(viewport={"width": w, "height": 850})
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
    """RESEARCH 맨 위 '리서치 종합'(애널 research-synthesis): 390px 폭에서 카드 7장·라벨·가로 넘침 없음·리포트 목록이 아래에."""
    pg = await b.new_page(viewport={"width": 390, "height": 844})
    errs: list[str] = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    await pg.goto(f"http://127.0.0.1:{port}/index.html", wait_until="load")
    await pg.wait_for_timeout(1500)
    await pg.evaluate("try{localStorage.removeItem('mt_syn_open')}catch(e){}; RV.k='종목'; setView('rep')")
    await pg.wait_for_timeout(3000)
    J = pg.evaluate
    res = {
        "카드7": await J("document.querySelectorAll('#syn .syn').length") == 7,
        "라벨": "증권가 집계" in await J("(document.querySelector('#syn')||{}).innerText||''"),
        "목록아래": await J("(()=>{const s=document.querySelector('#syn'),r=document.querySelector('#rbody');return !!(s&&r&&(s.compareDocumentPosition(r)&Node.DOCUMENT_POSITION_FOLLOWING));})()"),
        "넘침없음": await J("[...document.querySelectorAll('#syn, #syn *')].every(e=>e.getBoundingClientRect().right<=innerWidth+1)"),
    }
    ok = all(res.values()) and not errs
    print(f"{'OK ' if ok else 'BAD'} 리서치종합(390px) " + " ".join(f"{k}={'O' if v else 'X'}" for k, v in res.items()) + (f" · 에러: {errs[0][:160]}" if errs else ""))
    await pg.close()
    return not ok


async def check_duel_toggle(b, port: int) -> int:
    """DAILY 상단 '진입 타점 대결' 접기(UXUI 10/21): 390px 에서 헤더 44px 이상·요약 1줄 보임·클릭하면 본문 토글·새로고침 뒤 상태 기억·가로 넘침 없음."""
    pg = await b.new_page(viewport={"width": 390, "height": 844})
    errs: list[str] = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    J = pg.evaluate

    async def open_daily(clear: bool) -> None:
        await pg.goto(f"http://127.0.0.1:{port}/index.html", wait_until="load")
        await pg.wait_for_timeout(1500)
        await J(("try{localStorage.removeItem('mt_duel_open')}catch(e){}; " if clear else "") + "setView('daily')")
        await pg.wait_for_timeout(3500)

    shown = "(()=>{const b=document.querySelector('#duelbody');return !!b&&b.style.display!=='none';})()"
    await open_daily(True)
    first = await J(shown)
    res = {
        "헤더44": await J("(document.querySelector('#dueltog')||{offsetHeight:0}).offsetHeight>=44"),
        "요약": "나:" in await J("(document.querySelector('#duelsum')||{}).innerText||''"),
    }
    await pg.click("#dueltog")
    await pg.wait_for_timeout(300)
    res["토글"] = await J(shown) == (not first)
    res["넘침없음"] = await J("[...document.querySelectorAll('#duelbox, #duelbox *')].every(e=>e.getBoundingClientRect().right<=innerWidth+1)")
    await open_daily(False)
    res["기억"] = await J(shown) == (not first)
    ok = all(res.values()) and not errs
    print(f"{'OK ' if ok else 'BAD'} 대결접기(390px) 기본={'펼침' if first else '접힘'} " + " ".join(f"{k}={'O' if v else 'X'}" for k, v in res.items()) + (f" · 에러: {errs[0][:160]}" if errs else ""))
    await pg.close()
    return not ok


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["--root"]:
        SERVE = Path(args[1]).resolve()
        args = args[2:]
    srv = _serve(0)   # 빈 포트 자동
    try:
        sys.exit(1 if asyncio.run(run(args or VIEWS, srv.server_address[1])) else 0)
    finally:
        srv.shutdown()
