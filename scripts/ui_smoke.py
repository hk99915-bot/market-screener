"""화면 렌더 스모크 — 빌드된 index.html 을 로컬 서버 + 헤드리스 크롬으로 열어 탭별 렌더·콘솔 에러 확인.
사용: python3 scripts/ui_smoke.py [--root DIR] [view ...]   (기본: home edu apt rep deriv bond my)
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
VIEWS = ["home", "edu", "apt", "rep", "deriv", "bond", "my"]
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
