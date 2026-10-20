"""토스 시세 전용 클라이언트 정책 (screener/toss_md.py · tools/toss_md) — 네트워크 없음, 가짜 transport.

감사 요구(10/20): 주문·계좌 경로 원천 차단 · 키 저장소 밖·권한 좁게 · 응답 원문 로그 금지 · 도메인은 두 곳에만.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from screener import toss_md
from tools.toss_md import collect, crosscheck

ROOT = Path(__file__).resolve().parents[1]
SECRET_MARK = "SECRET-BODY-MARKER-7f3a"
CFG = {"client_id": "cid-test-1234", "client_secret": "csec-" + "x" * 10, "base_url": "https://md.invalid"}


class FakeTransport:
    def __init__(self, responses=None):
        self.calls: list[tuple[str, str, dict]] = []
        self.responses = list(responses or [])

    def __call__(self, method, url, headers, data):
        self.calls.append((method, url, dict(headers)))
        if url.endswith(toss_md.TOKEN_PATH):
            return toss_md.Resp(200, {}, json.dumps({"access_token": "tok-" + str(len(self.calls)), "expires_in": 86400}).encode())
        if self.responses:
            return self.responses.pop(0)
        return toss_md.Resp(200, {}, b'{"result":{"ok":true}}')


@pytest.fixture
def client(tmp_path):
    t = FakeTransport()
    c = toss_md.TossMD(dict(CFG), transport=t, token_cache=tmp_path / "token.json", sleep=lambda s: None)
    return c, t


# ── 1. 금지 경로·메서드·헤더는 요청 전에 실패 ─────────────────────────────
FORBIDDEN = [
    "/api/v1/orders", "/api/v1/orders/123/cancel", "/api/v1/orders/modify", "/api/v1/conditional-orders",
    "/api/v1/accounts", "/api/v1/holdings", "/api/v1/buying-power", "/api/v1/sellable-quantity",
    "/api/v1/commissions", "/api/v1/ORDERS", "/api/v1/stocks/005930/orders",
    "/api/v1/prices/../orders", "/api/v1//orders", "/api/v1/%6Frders", "https://evil.invalid/api/v1/prices",
    "/api/v1/prices?x=/orders", "/api/v2/prices", "/api/v1/unknown",
]


@pytest.mark.parametrize("path", FORBIDDEN)
def test_forbidden_paths_raise_before_network(client, path):
    c, t = client
    with pytest.raises(toss_md.ForbiddenRequest):
        c.get(path)
    assert t.calls == []  # 토큰 발급조차 안 함


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH"])
def test_non_get_methods_refused(method):
    with pytest.raises(toss_md.ForbiddenRequest):
        toss_md.check_request(method, "/api/v1/prices", {})


def test_token_path_only_post():
    toss_md.check_request("POST", toss_md.TOKEN_PATH, {})
    with pytest.raises(toss_md.ForbiddenRequest):
        toss_md.check_request("GET", toss_md.TOKEN_PATH, {})


_ACC = "X-Toss" + "invest-Account"  # 문자열을 쪼갠 이유: 아래 도메인 검사가 이 파일도 본다


@pytest.mark.parametrize("hdr", [_ACC, _ACC.lower(), f" {_ACC.upper()} "])
def test_account_header_refused(client, hdr):
    c, t = client
    with pytest.raises(toss_md.ForbiddenRequest):
        toss_md.check_request("GET", "/api/v1/prices", {hdr: "1"})
    with pytest.raises(toss_md.ForbiddenRequest):  # 저수준 _send 로 우회해도 막힘
        c._send("GET", "/api/v1/prices", {hdr: "1"})
    assert t.calls == []


def test_client_has_no_post_or_order_methods():
    pub = {n for n in dir(toss_md.TossMD) if not n.startswith("_")}
    assert pub == {"get", "token"}


ALLOWED = [
    "/api/v1/prices", "/api/v1/orderbook", "/api/v1/trades", "/api/v1/price-limits", "/api/v1/candles",
    "/api/v1/stocks", "/api/v1/stocks/all", "/api/v1/stocks/005930/warnings", "/api/v1/stocks/AAPL/investor-trading",
    "/api/v1/stocks/005930/program-trades", "/api/v1/stocks/005930/short-selling",
    "/api/v1/stocks/005930/credit-trades", "/api/v1/stocks/005930/securities-lending", "/api/v1/exchange-rate",
    "/api/v1/market-calendar/KR", "/api/v1/market-calendar/US", "/api/v1/rankings", "/api/v1/sectors",
    "/api/v1/sectors/IT/stocks", "/api/v1/market-indicators/indices/KOSPI/candles",
]


@pytest.mark.parametrize("path", ALLOWED)
def test_allowed_paths_pass(client, path):
    c, t = client
    assert c.get(path, {"symbols": "005930"}) == {"result": {"ok": True}}
    m, url, h = t.calls[-1]
    assert m == "GET" and url.startswith(CFG["base_url"] + path)
    assert not any(k.lower() == toss_md.ACCOUNT_HEADER for k in h)


def test_collector_pilot_paths_are_whitelisted():
    for _n, _g, path, _p in collect.PILOT + [collect.STOCKS_ALL]:
        toss_md.check_request("GET", path, {})


# ── 2. 토스 API 도메인 문자열은 두 곳에만 ────────────────────────────────────
def test_domain_only_in_toss_md_modules():
    needle = "toss" + "invest"
    try:
        files = subprocess.run(["git", "ls-files", "-co", "--exclude-standard"], cwd=ROOT, capture_output=True,
                               text=True, check=True).stdout.splitlines()
    except Exception:
        pytest.skip("git 없음")
    allowed = ("screener/toss_md.py", "tools/toss_md/")
    bad = []
    for f in files:
        if f.startswith(allowed) or f.startswith(("data/", "reports/")) and f.endswith((".parquet", ".jsonl")):
            continue
        p = ROOT / f
        try:
            if p.stat().st_size > 5_000_000:
                continue
            txt = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if needle in txt.lower():
            bad.append(f)
    assert bad == [], f"토스 도메인이 허용 위치 밖에 있음: {bad}"


# ── 3. 키 파일 권한·위치 ──────────────────────────────────────────────────
@pytest.mark.skipif(os.name != "posix", reason="POSIX 권한 비트")
def test_env_file_permissions(tmp_path, monkeypatch):
    for k in ("TOSS_MD_CLIENT_ID", "TOSS_MD_CLIENT_SECRET", "TOSS_MD_BASE_URL"):
        monkeypatch.delenv(k, raising=False)
    f = tmp_path / "env"
    f.write_text("TOSS_MD_CLIENT_ID=a1\nTOSS_MD_CLIENT_SECRET=b2\n")
    os.chmod(f, 0o644)
    with pytest.raises(PermissionError):
        toss_md.load_config(f)
    os.chmod(f, 0o600)
    cfg = toss_md.load_config(f)
    assert cfg["client_id"] == "a1" and cfg["base_url"].startswith("https://")


def test_env_file_inside_repo_refused(tmp_path):
    with pytest.raises(PermissionError):
        toss_md.check_private_file(ROOT / "README.md")


def test_windows_acl_check():
    wide = "C:\\Users\\k\\.config\\toss_md\\env BUILTIN\\Users:(I)(RX)\n  DESKTOP\\k:(F)\n"
    narrow = "C:\\Users\\k\\.config\\toss_md\\env DESKTOP\\k:(F)\n"
    assert toss_md.windows_wide_principals(Path("env"), runner=lambda a: wide) == ["BUILTIN\\Users"]
    assert toss_md.windows_wide_principals(Path("env"), runner=lambda a: narrow) == []
    assert toss_md.windows_wide_principals(Path("env"), runner=lambda a: "Everyone:(R)")
    assert toss_md.windows_wide_principals(Path("env"), runner=lambda a: "")  # 검사 불가 = 거부


def test_base_url_must_be_https(monkeypatch):
    monkeypatch.setenv("TOSS_MD_CLIENT_ID", "a")
    monkeypatch.setenv("TOSS_MD_CLIENT_SECRET", "b")
    monkeypatch.setenv("TOSS_MD_BASE_URL", "http://plain.invalid")
    with pytest.raises(ValueError):
        toss_md.load_config(Path("/nonexistent"))


# ── 4. 응답 원문·키·토큰은 로그·예외에 없음 ───────────────────────────────
def test_error_body_not_logged(tmp_path, caplog):
    body = json.dumps({"code": "INTERNAL", "message": SECRET_MARK, "detail": SECRET_MARK}).encode()
    t = FakeTransport([toss_md.Resp(500, {}, body)])
    c = toss_md.TossMD(dict(CFG), transport=t, token_cache=tmp_path / "t.json", sleep=lambda s: None)
    caplog.set_level(logging.DEBUG)
    with pytest.raises(toss_md.TossMDError) as e:
        c.get("/api/v1/prices")
    assert e.value.code == "INTERNAL" and e.value.status == 500
    blob = caplog.text + str(e.value) + repr(c)
    assert SECRET_MARK not in blob
    assert CFG["client_secret"] not in blob and "tok-" not in blob


def test_collector_prints_no_body(tmp_path, capsys):
    rc = collect.main(["--group", "all", "--dry-run", "--out", str(tmp_path)])
    out = capsys.readouterr()
    assert rc == 0
    assert "candles" not in out.out + out.err and "netBuyValue" not in out.out + out.err


# ── 5. 토큰 캐시·429 ─────────────────────────────────────────────────────
def test_token_cached_and_reissued_on_expiry(tmp_path):
    now = [1_000_000.0]
    t = FakeTransport()
    cache = tmp_path / "token.json"
    c = toss_md.TossMD(dict(CFG), transport=t, token_cache=cache, sleep=lambda s: None, clock=lambda: now[0])
    c.get("/api/v1/prices")
    c.get("/api/v1/prices")
    assert sum(u.endswith(toss_md.TOKEN_PATH) for _, u, _ in t.calls) == 1
    if os.name == "posix":
        assert (cache.stat().st_mode & 0o077) == 0
    # 새 프로세스도 캐시 재사용
    c2 = toss_md.TossMD(dict(CFG), transport=t, token_cache=cache, sleep=lambda s: None, clock=lambda: now[0])
    c2.get("/api/v1/prices")
    assert sum(u.endswith(toss_md.TOKEN_PATH) for _, u, _ in t.calls) == 1
    now[0] += 24 * 3600 - 60  # 만료 5분 전 안쪽 → 재발급
    c2.get("/api/v1/prices")
    assert sum(u.endswith(toss_md.TOKEN_PATH) for _, u, _ in t.calls) == 2


def test_429_respects_retry_after(tmp_path):
    slept = []
    t = FakeTransport([toss_md.Resp(429, {"retry-after": "7"}, b"{}"), toss_md.Resp(200, {}, b'{"v":1}')])
    c = toss_md.TossMD(dict(CFG), transport=t, token_cache=tmp_path / "t.json", sleep=slept.append)
    assert c.get("/api/v1/prices") == {"v": 1}
    assert slept == [7.0]


def test_429_gives_up_when_retry_after_too_long(tmp_path):
    slept = []
    t = FakeTransport([toss_md.Resp(429, {"retry-after": "600"}, b'{"code":"RATE"}')])
    c = toss_md.TossMD(dict(CFG), transport=t, token_cache=tmp_path / "t.json", sleep=slept.append)
    with pytest.raises(toss_md.TossMDError) as e:
        c.get("/api/v1/prices")
    assert e.value.status == 429 and slept == []


# ── 6. 수집기·대조 ───────────────────────────────────────────────────────
def test_collect_dry_run_writes_outside_repo(tmp_path):
    now = datetime(2026, 10, 20, 23, 40, tzinfo=collect.KST)
    s = collect.run("all", dry_run=True, stocks_all=True, out=tmp_path, now=now)
    assert s["ok"] == len(collect.PILOT) + 1 and s["fail"] == 0
    day = tmp_path / "_dryrun" / "2026-10-20"
    rec = json.loads((day / "kospi_1m.json").read_text())
    assert rec["generated_at"] and rec["asof"].startswith("2026-10-20T15:30") and rec["asof_src"] == "response"
    hb = json.loads((tmp_path / "_dryrun" / "heartbeat.json").read_text())
    assert hb["last_success"] and hb["fail"] == 0
    assert not (tmp_path / "_dryrun" / "collector.lock").exists()
    # 두 번째 실행: 1분봉 병합(중복 없음)
    collect.run("intraday", dry_run=True, out=tmp_path, now=now)
    rows = json.loads((day / "kospi_1m.json").read_text())["data"]["result"]["candles"]
    assert len(rows) == 5


def test_collect_refuses_repo_output():
    with pytest.raises(SystemExit):
        collect.run("all", dry_run=True, out=ROOT / "reports")


def test_lock_blocks_second_collector(tmp_path):
    with collect.Lock(tmp_path / "l"):
        with pytest.raises(SystemExit):
            with collect.Lock(tmp_path / "l"):
                pass


def test_merge_rows_union():
    a = {"candles": [{"timestamp": "t1", "close": 1}, {"timestamp": "t2", "close": 2}]}
    b = {"candles": [{"timestamp": "t2", "close": 3}, {"timestamp": "t3", "close": 4}]}
    assert [r["close"] for r in collect.merge_rows(a, b)["candles"]] == [1, 3, 4]


def test_crosscheck_flags_breach(tmp_path):
    now = datetime(2026, 10, 20, 23, 40, tzinfo=collect.KST)
    collect.run("all", dry_run=True, out=tmp_path, now=now)
    day = tmp_path / "_dryrun" / "2026-10-20"
    rep = tmp_path / "reports"
    rep.mkdir()
    ms = {"series": {"KOSPI": [["2026-10-20", 0, 0, 0, 5550.0, 0]], "KOSDAQ": [["2026-10-20", 0, 0, 0, 700.0, 0]],
                     "USDKRW": [["2026-10-20", 0, 0, 0, 1326.0, 0]]}}
    (rep / "macro_series.json").write_text(json.dumps(ms))
    res = crosscheck.compare("2026-10-20", day, rep)
    st = {r["item"]: r["status"] for r in res["rows"]}
    assert st["KOSPI 종가"] == "ok" and st["KOSDAQ 종가"] == "breach" and st["USDKRW"] == "ok"
    assert st["KR 달력"] == "ok" and st["US 달력"] == "ok"
    assert res["tolerances"]["INDEX_CLOSE_TOL_PCT"] == crosscheck.INDEX_CLOSE_TOL_PCT
