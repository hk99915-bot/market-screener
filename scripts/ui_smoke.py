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
