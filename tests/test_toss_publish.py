"""토스 publish(노트북 → toss-live 브랜치)·터미널 폴백·신선도 계약 (2026-10-21, 보드 toss-md-publish). 네트워크 없음."""
from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from screener import contracts, freshness, toss_live, toss_md
from tools.toss_md import collect, crosscheck, publish

KST = collect.KST
NOW = datetime(2026, 10, 20, 23, 40, tzinfo=KST)   # 화요일 장 마감 뒤


@pytest.fixture
def base(tmp_path):
    collect.run("all", dry_run=True, out=tmp_path, now=NOW)
    return tmp_path / "_dryrun"


# ── 요약 생성 ────────────────────────────────────────────────────────────
def test_build_summary_from_fixture(base):
    doc = publish.build(base, NOW)
    assert doc["source"] == "toss" and doc["date"] == "2026-10-20" and not doc["missing"]
    k = doc["indices"]["KOSPI"]
    assert k["bars"][0][:5] == ["15:26", 5552.22, 5553.22, 5551.22, 5552.22] and k["n"] == 5
    assert len(k["bars"][0]) == 6   # 6번째 = 거래량(없으면 None) — 팝업 거래량·VWAP
    assert k["last"] == 5552.74   # 현재값은 prices(캔들보다 빠름)
    assert set(doc["flows"]["KOSPI"]) >= {"개인", "외국인", "기관", "기타법인", "date", "unit"}
    assert doc["flows"]["KOSPI"]["외국인"] == -80.0 and doc["flows"]["KOSPI"]["date"] == "2026-10-20"
    assert doc["quotes"]["KR_BOND_3Y"]["last"] == 2.512
    assert doc["calendar"]["KR"]["closed_next"] == ["2026-10-24", "2026-10-25"]   # 실측 꼴: 전·다음 영업일 사이 = 휴장
    assert contracts.check(Path("reports") / publish.CONTRACT_PATH, doc) == []


def test_fx_uses_mid_rate_only(base):
    doc = publish.build(base, NOW)
    assert doc["fx"]["USDKRW"]["mid"] == 1326.5   # 픽스처 rate(매수환율)=1349.71 은 안 씀
    assert crosscheck.fx_rate({"result": {"rate": 1349.71}}) is None
    assert publish.fx_mid({"result": {"rate": 1349.71, "basePrice": 1300}}) is None


def test_premarket_keeps_previous_session_bars(base):
    # 다음 날 08:10: 오늘 폴더에도 전 거래일 봉만 있다 → 전 거래일 분을 유지(빈 화면 금지)
    nxt = base / "2026-10-21"
    shutil.copytree(base / "2026-10-20", nxt)
    doc = publish.build(base, datetime(2026, 10, 21, 8, 10, tzinfo=KST))
    assert doc["date"] == "2026-10-20" and doc["indices"]["KOSDAQ"]["n"] == 5


def test_flows_field_shape_and_unit():
    data = {"result": [{"baseDate": "2026-10-19", "individualNetBuyValue": 1e11},
                       {"baseDate": "2026-10-20", "individualNetBuyValue": 123_400_000_000,
                        "foreignNetBuyValue": -98_700_000_000, "institutionNetBuyValue": -20_000_000_000,
                        "otherCorporationNetBuyValue": -4_700_000_000, "institutionFinancialNetBuyValue": 1}]}
    f = publish.flows(data)
    assert f["date"] == "2026-10-20" and f["unit_basis"] == "원→억원"
    assert (f["개인"], f["외국인"], f["기관"], f["기타법인"]) == (1234.0, -987.0, -200.0, -47.0)
    assert publish.flows({"result": {"foo": 1}}) is None


# ── 공개 안전 ────────────────────────────────────────────────────────────
def _keys(x, out):
    if isinstance(x, dict):
        for k, v in x.items():
            out.add(str(k).lower())
            _keys(v, out)
    elif isinstance(x, list):
        for v in x:
            _keys(v, out)
    return out


def test_public_files_have_no_forbidden_fields(base):
    doc, xc = publish.build(base, NOW), publish.build_crosscheck(base, NOW)
    for d in (doc, xc):
        publish.assert_public(d)
        assert not (_keys(d, set()) & publish.FORBIDDEN_KEYS)
        txt = publish.render(d).lower()
        for bad in ("toss" + "invest", "bearer", "dry-run-id", "access_token", "orderbook", '"rate"'):
            assert bad not in txt


@pytest.mark.parametrize("bad", [{"bids": [1]}, {"fx": {"rate": 1349}}, {"x": {"access_token": "t"}},
                                 {"note": "https://evil.invalid"}, {"n": "Bearer abc"}])
def test_assert_public_refuses(bad):
    with pytest.raises(ValueError):
        publish.assert_public(bad)


def test_render_fixed_format_and_size_cap(base):
    doc = publish.build(base, NOW)
    t1 = publish.render(doc)
    assert t1 == publish.render(json.loads(t1)) and '["15:26", 5552.22, 5553.22, 5551.22, 5552.22, ' in t1
    big = json.loads(t1)
    big["indices"]["KOSPI"]["bars"] = [[f"b{i:04d}", 5000.0, 5001.0, 4999.0, 5000.5] for i in range(4000)]
    publish.fit_size(big, cap=60_000)
    assert len(publish.render(big).encode()) <= 60_000 and big["indices"]["KOSPI"]["thinned"] >= 2
    assert big["indices"]["KOSPI"]["bars"][-1][0] == "b3999"   # 마지막 봉 유지


def test_decide_rules():
    now = datetime(2026, 10, 21, 10, 0, tzinfo=KST)
    st = {"last_full": "a", "last_xc": "x", "last_publish_at": (now - timedelta(minutes=10)).isoformat()}
    assert publish.decide(st, "a", "x", now) == (False, "no_change")
    assert publish.decide({**st, "pending": True}, "a", "x", now) == (True, "retry_push")
    assert publish.decide(st, "b", "x", now) == (True, "intraday")              # 기본: 회차마다
    assert publish.decide(st, "b", "x", now, min_interval_min=30) == (False, "interval")
    assert publish.decide(st, "a", "y", datetime(2026, 10, 21, 18, 30, tzinfo=KST)) == (True, "us_pre")       # 05:30 ET 프리장
    assert publish.decide(st, "a", "y", datetime(2026, 10, 21, 1, 19, tzinfo=KST)) == (True, "us_regular")   # 10/21 01:19 첫 publish 가 off_session 으로 찍힌 것 수정
    assert publish.decide(st, "a", "y", datetime(2026, 10, 21, 10, 30, tzinfo=KST) - timedelta(hours=4)) == (True, "us_after")  # 06:30 KST = 17:30 ET
    assert publish.decide(st, "a", "y", datetime(2026, 10, 25, 12, 0, tzinfo=KST)) == (True, "off_session")   # 일요일


# ── git: toss-live 브랜치에 일반 push (실제 git, 로컬 bare 원격) ─────────────────
def _git(*a, cwd):
    # 훅(pre-push → pytest) 안에서 GIT_DIR 이 상속되면 tmp 가 아니라 실제 저장소를 건드린다(10/21 core.bare 사고) → 지운 env
    return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, check=True, env=publish.clean_git_env()).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    if not shutil.which("git"):
        pytest.skip("git 없음")
    bare = tmp_path / "remote.git"
    _git("init", "-q", "--bare", str(bare), cwd=tmp_path)
    work = tmp_path / "work"
    _git("init", "-q", "-b", "main", str(work), cwd=tmp_path)
    (work / "README").write_text("x")
    _git("add", "README", cwd=work)
    _git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init", cwd=work)
    _git("remote", "add", "origin", str(bare), cwd=work)
    _git("push", "-q", "origin", "main", cwd=work)
    return work, bare


def test_git_publish_branch_normal_push(repo, base):
    work, bare = repo
    rec = []

    def spy(args, cwd, data=None):
        rec.append(args)
        return publish.git_runner(args, cwd, data)

    r1 = publish.run(base, now=NOW, repo=work, git=spy, reports=work / "reports")
    assert r1["status"] == "pushed"
    files = _git("ls-tree", "--name-only", "toss-live", cwd=bare).split()
    assert files == ["crosscheck.json", "daily_today.json", "live.json"]   # 공개 요약만 — 과거 일봉은 07:20 백필 스냅샷이 있을 때만(10/21)
    who = _git("log", "-1", "--format=%an <%ae>|%s", "toss-live", cwd=bare)
    assert who.startswith("toss-md <toss-md-bot@users.noreply.github.com>|toss: ")
    assert _git("rev-parse", "HEAD", cwd=work) == _git("rev-parse", "main", cwd=bare)   # main 은 그대로
    assert _git("status", "--porcelain", cwd=work) == ""                                 # 작업 트리 무변경
    assert not any(a and a[0] == "push" and any(x in ("-f", "--force") or x.startswith("+") for x in a) for a in rec)
    live = json.loads(_git("show", "toss-live:live.json", cwd=bare))
    assert live["published_at"] and live["schema_version"] == 1 and live["fx"]["USDKRW"]["mid"] == 1326.5
    # 같은 내용 → 커밋 안 함
    r2 = publish.run(base, now=NOW + timedelta(minutes=10), repo=work, reports=work / "reports")
    assert r2["decision"] == "no_change" and _git("rev-list", "--count", "toss-live", cwd=bare) == "1"
    # 바뀐 내용 → 부모 있는 일반 커밋 (이력 유지)
    rec_file = base / "2026-10-20" / "usdkrw.json"
    j = json.loads(rec_file.read_text())
    j["data"]["result"]["midRate"] = 1327.1
    j["data"]["result"]["timestamp"] = "2026-10-20T23:50:00+09:00"
    rec_file.write_text(json.dumps(j))
    r3 = publish.run(base, now=NOW + timedelta(minutes=20), repo=work, reports=work / "reports")
    assert r3["status"] == "pushed" and _git("rev-list", "--count", "toss-live", cwd=bare) == "2"
    hb = json.loads((base / "heartbeat.json").read_text())
    assert hb["publish"]["status"] == "pushed" and hb["publish"]["pending"] is False


def test_publish_refuses_asof_regress(repo, base):
    work, bare = repo
    publish.run(base, now=NOW, repo=work, reports=work / "reports")
    old = json.dumps({"asof": "2026-10-22T10:00:00+09:00"})
    assert publish.check_doc({**publish.build(base, NOW), "published_at": "x"}, old)[-1].startswith("asof 역행")


def test_push_failure_marks_pending(base, tmp_path):
    def broken(args, cwd, data=None):
        if args[0] == "push":
            return 1, "", "rejected"
        return publish.git_runner(args, cwd, data) if args[0] != "fetch" else (1, "", "no remote")
    work = tmp_path / "w"
    subprocess.run(["git", "init", "-q", str(work)], check=True, env=publish.clean_git_env())
    r = publish.run(base, now=NOW, repo=work, git=broken, reports=work / "reports")
    assert r["status"] == "fail"
    st = json.loads((base / "heartbeat.json").read_text())["publish"]
    assert st["pending"] is True and "push" in st["error"]
    assert publish.decide(st, "same", "same", NOW)[0] is True   # 다음 회차 재시도


# ── 터미널: 신선도·폴백 ────────────────────────────────────────────────────
def _doc(asof, fx_asof=None, flows_date="2026-10-21", gen=None):
    return {"source": "toss", "asof": asof, "generated_at": gen or asof,
            "indices": {"KOSPI": {"last": 5600.0, "asof": asof, "prev_close": None},
                        "KOSDAQ": {"last": 790.0, "asof": asof, "prev_close": 780.0}},
            "fx": {"USDKRW": {"mid": 1330.0, "asof": fx_asof or asof}},
            "flows": {"KOSPI": {"date": flows_date, "개인": 1.0, "외국인": -1.0, "기관": 0.0, "기타법인": 0.0, "unit": "억원"}}}


def _items():
    return [{"key": "KOSPI", "last": 5500.0, "chg": 0.01, "src": "naver", "status": "OPEN"},
            {"key": "KOSDAQ", "last": 780.0, "chg": 0.0, "src": "naver"},
            {"key": "USDKRW", "last": 1320.0, "chg": 0.0, "src": "yahoo", "date": "2026-10-21"}]


def test_overlay_uses_fresh_toss_in_session():
    now = datetime(2026, 10, 21, 10, 30, tzinfo=KST)
    items, blk = toss_live.overlay(_items(), _doc("2026-10-21T10:15:00+09:00"), now)
    by = {x["key"]: x for x in items}
    assert blk["state"] == "fresh" and set(blk["used"]) == {"KOSPI", "KOSDAQ", "USDKRW"}
    assert by["KOSPI"]["src"] == "toss" and by["KOSPI"]["fallback_src"] == "naver" and by["KOSPI"]["status"] == "OPEN"
    assert by["KOSPI"]["chg"] == pytest.approx(5600 / (5500 / 1.01) - 1)   # 전일 종가 = 네이버 last/(1+chg)
    assert by["KOSDAQ"]["chg"] == pytest.approx(790 / 780 - 1)            # 토스 전일 종가 우선
    assert by["USDKRW"]["last"] == 1330.0 and by["USDKRW"]["src"] == "toss"
    assert blk["flows"]["KOSPI"]["외국인"] == -1.0


def test_overlay_falls_back_when_stale_or_missing():
    now = datetime(2026, 10, 21, 10, 30, tzinfo=KST)
    items, blk = toss_live.overlay(_items(), _doc("2026-10-21T10:05:00+09:00"), now)   # 25분 전 > 20분
    assert blk["state"] == "stale" and all(x["src"] != "toss" for x in items) and "KOSPI" in blk["skipped"]
    items, blk = toss_live.overlay(_items(), None, now)
    assert blk["state"] == "missing" and items[0]["src"] == "naver"


def test_fresh_rules_off_session():
    # 장 마감 뒤: 당일분이면 신선, 전일분이면 지연. 다음 날 08:30(개장 전): 전 거래일분이면 신선
    ok, _ = toss_live.fresh_ts("2026-10-21T15:30:00+09:00", datetime(2026, 10, 21, 19, 0, tzinfo=KST))
    assert ok
    ok, _ = toss_live.fresh_ts("2026-10-20T15:30:00+09:00", datetime(2026, 10, 21, 19, 0, tzinfo=KST))
    assert not ok
    ok, _ = toss_live.fresh_ts("2026-10-21T15:30:00+09:00", datetime(2026, 10, 22, 8, 30, tzinfo=KST))
    assert ok
    ok, _ = toss_live.fresh_ts("2026-10-23T15:30:00+09:00", datetime(2026, 10, 25, 12, 0, tzinfo=KST))   # 일요일
    assert ok
    ok, why = toss_live.fresh_flows({}, {"date": "2026-10-20"}, datetime(2026, 10, 21, 19, 0, tzinfo=KST))
    assert not ok


def test_live_snapshot_overlay_wiring():
    src = (Path(__file__).resolve().parents[1] / "screener" / "live.py").read_text(encoding="utf-8")
    assert "toss_live.overlay(items, toss_live.fetch(), now)" in src and '"toss": toss_blk' in src


# ── 신선도 계약 kind=toss_md ─────────────────────────────────────────────
IT = {"id": "toss_md", "path": "toss-live:live.json", "url": "u", "key": "published_at", "kind": "toss_md",
      "window": "09:30-15:40", "max_age_min": 30, "mode": "노트북", "fix": "f", "desc": "d"}


@pytest.mark.parametrize("now,pub,late", [
    (datetime(2026, 10, 21, 11, 0, tzinfo=KST), "2026-10-21T10:45:00+09:00", False),
    (datetime(2026, 10, 21, 11, 0, tzinfo=KST), "2026-10-21T10:15:00+09:00", True),    # 노트북 멈춤
    (datetime(2026, 10, 21, 8, 20, tzinfo=KST), "2026-10-20T19:50:00+09:00", False),   # 08:20 점검: 전 거래일분이면 정상
    (datetime(2026, 10, 21, 20, 10, tzinfo=KST), "2026-10-20T19:50:00+09:00", True),   # 20:10 점검: 오늘 publish 없음
    (datetime(2026, 10, 24, 12, 0, tzinfo=KST), "2026-10-23T19:50:00+09:00", False),   # 토요일
])
def test_freshness_toss_md(monkeypatch, now, pub, late):
    monkeypatch.setattr(toss_live, "fetch", lambda url=None, timeout=10: {"source": "toss", "published_at": pub})
    r = freshness.check_item(IT, now)
    assert (r is not None) == late
    monkeypatch.setattr(toss_live, "fetch", lambda url=None, timeout=10: None)
    assert freshness.check_item(IT, datetime(2026, 10, 21, 11, 0, tzinfo=KST))["actual"] == "원격 파일 없음/읽기 실패"


def test_freshness_contract_has_toss_md():
    items = freshness.load_contract()
    it = next(i for i in items if i["id"] == "toss_md")
    assert it["kind"] == "toss_md" and it["url"].endswith("/toss-live/live.json") and it["url"] == toss_live.RAW_URL


# ── 수집기: prices 경로·레이트리밋 기록 ─────────────────────────────────────
def test_prices_path_whitelisted_and_rate_limit_recorded(tmp_path):
    toss_md.check_request("GET", "/api/v1/market-indicators/prices", {})

    def tr(method, url, headers, data):
        if url.endswith(toss_md.TOKEN_PATH):
            return toss_md.Resp(200, {}, json.dumps({"access_token": "t", "expires_in": 86400}).encode())
        return toss_md.Resp(200, {"X-RateLimit-Limit": "100", "X-RateLimit-Remaining": "97", "X-RateLimit-Reset": "30"},
                            b'{"result":[]}')
    c = toss_md.TossMD({"client_id": "cid-1234", "client_secret": "s", "base_url": "https://md.invalid"}, transport=tr,
                       token_cache=tmp_path / "tok.json")
    collect.run("intraday", out=tmp_path, now=NOW, client=c)
    hb = json.loads((tmp_path / "heartbeat.json").read_text())
    assert hb["rate_limit"]["MARKET_INDICATOR"]["remaining"] == 97
    assert hb["rate_limit"]["MARKET_INDICATOR_CHART"]["limit"] == 100
    assert toss_md.rate_group("/api/v1/exchange-rate") == "MARKET_INFO"


# ── 10/21 수정: 원문 수급 꼴 · 환율 validFrom · 커밋 메시지 · us 블록 · sectors.json ─────────────
def test_flows_openapi_records_shape():
    rec = {"result": {"records": [{"date": "2026-10-20", "updatedAt": "2026-10-20T15:40:00+09:00",
                                   "individual": {"buyAmount": "500000000000", "sellAmount": "376600000000"},
                                   "foreigner": {"buyAmount": "100000000000", "sellAmount": "198700000000"},
                                   "institution": {"buyAmount": "50000000000", "sellAmount": "70000000000",
                                                   "breakdown": {"pension": {"buyAmount": "9", "sellAmount": "1"}}},
                                   "otherCorporation": {"buyAmount": "1000000000", "sellAmount": "5700000000"}}]}}
    f = publish.flows(rec)
    assert (f["개인"], f["외국인"], f["기관"], f["기타법인"]) == (1234.0, -987.0, -200.0, -47.0)
    assert f["date"] == "2026-10-20" and f["unit_basis"] == "원→억원"


def test_fx_asof_from_valid_from(base):
    doc = publish.build(base, NOW)
    assert doc["fx"]["USDKRW"]["asof"] == "2026-10-20T23:30:00+09:00"


def test_us_block(base):
    doc = publish.build(base, NOW)
    assert doc["us"]["quotes"]["SPY"]["chg_pct"] is None       # /prices 엔 기준가 없음 → 캐시 전엔 비움(0 으로 채우지 않음)
    assert doc["us"]["quotes"]["NVDA"]["chg_pct"] == -2.1 and doc["us"]["quotes"]["NVDA"]["base_src"] == "랭킹 basePrice"
    collect.run("sectors", dry_run=True, out=base.parent, now=NOW)   # 기준가 일봉 캐시
    doc = publish.build(base, NOW)
    assert doc["us"]["quotes"]["SPY"]["base_src"] == "일봉 캐시"
    us = doc["us"]
    assert us["quotes"]["SPY"]["last"] == 671.3 and us["quotes"]["SPY"]["chg_pct"] == -0.42
    assert us["spark"]["SPY"]["date"] == "2026-10-20" and us["spark"]["SPY"]["bars"][0][0] == "15:50"
    assert us["rank"]["amount"][0]["s"] == "NVDA" and len(us["rank"]["amount"]) <= publish.US_TOP
    assert us["sector_rank"][0]["name"] == "반도체"
    assert us["session"] and us["session"]["end"] == "2026-10-21T08:50:00+09:00"
    publish.assert_public(doc)
    assert "rate" not in _keys(doc, set())


def test_sectors_json_public_no_money_fields(base):
    collect.run("sectors", dry_run=True, out=base.parent, now=NOW)
    sec = publish.build_sectors(base, NOW)
    publish.assert_public(sec)
    ks = _keys(sec, set())
    assert not ks & {"volume", "tradingamount", "marketcapitalization", "currency", "price"}
    assert sec["members"]["KR"]["005930"] == ["S111", "S112", "S12", "S21"]
    assert {s["id"]: s["parent"] for s in sec["sectors"]}["S111"] == "S11"


def test_git_publish_sectors_kept_and_message(repo, base):
    work, bare = repo
    collect.run("sectors", dry_run=True, out=base.parent, now=NOW)
    assert publish.run(base, now=NOW, repo=work, reports=work / "reports")["status"] == "pushed"
    assert _git("ls-tree", "--name-only", "toss-live", cwd=bare).split() == ["crosscheck.json", "daily_bars.json", "daily_today.json", "live.json", "sectors.json"]
    assert _git("log", "-1", "--format=%s", "toss-live", cwd=bare).startswith("toss: published 2026-10-20T23:40 (asof 2026-10-20")
    (base / "2026-10-20" / "sectors.json").unlink()      # 로컬 스냅샷이 없어도 원격 sectors.json 은 지워지지 않는다
    f = base / "2026-10-20" / "usdkrw.json"
    j = json.loads(f.read_text())
    j["data"]["result"]["midRate"] = 1327.1
    f.write_text(json.dumps(j))
    assert publish.run(base, now=NOW + timedelta(minutes=10), repo=work, reports=work / "reports")["status"] == "pushed"
    assert "sectors.json" in _git("ls-tree", "--name-only", "toss-live", cwd=bare).split()


def test_git_env_ignores_hook_vars(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "real.git"))
    monkeypatch.setenv("GIT_INDEX_FILE", str(tmp_path / "idx"))
    env = publish.clean_git_env()
    assert "GIT_DIR" not in env and "GIT_INDEX_FILE" not in env


# ── 10/21 01:19 첫 실데이터 수정: 등락률 키·단위·이름/가격 중첩·KR 현재가 ───────────────────────
def test_row_fields_finds_nested_and_unknown_keys():
    r = publish.row_fields({"symbol": "SPY", "displayName": "SPDR S&P500", "price": {"close": "768.5", "previousClosePrice": "760.0"},
                            "tradingAmount": "1000"})
    assert r["name"] == "SPDR S&P500" and r["last"] == 768.5 and r["prev"] == 760.0 and r["amt"] == 1000.0
    assert publish.chg_pct(r, "ratio") == round((768.5 / 760 - 1) * 100, 3)    # 등락률 키 없으면 전일가로 계산
    r2 = publish.row_fields({"symbol": "X", "lastPrice": 10, "priceChangeRate": 0.05})
    assert publish.chg_pct(r2, "ratio") == 5.0 and publish.chg_pct(r2, "pct") == 0.05


def test_chg_unit_inference():
    rows = [{"chg_raw": 0.02, "last": 102.0, "prev": 100.0}, {"chg_raw": -0.01, "last": 99.0, "prev": 100.0}]
    assert publish.chg_unit(rows)[0] == "ratio"
    assert publish.chg_unit([{"chg_raw": 2.0, "last": 102.0, "prev": 100.0}])[0] == "pct"
    assert publish.chg_unit([{"chg_raw": 0.04}]) == (publish.DEFAULT_CHG_UNIT, "기본값(추정)")


def test_kr_quotes_and_keys_diagnostic(base):
    collect.run("sectors", dry_run=True, out=base.parent, now=NOW)
    doc = publish.build(base, NOW)
    assert doc["kr_quotes"]["069500"]["chg_pct"] == round((74210 / 76500 - 1) * 100, 3)
    assert doc["kr_quotes"]["005930"]["last"] == 95000.0
    assert "symbol" in doc["kr_meta"]["_keys"] and "069500" in doc["kr_meta"]["etfs"]
    assert doc["us"]["_keys"]["prices"] and doc["us"]["chg_unit"]["raw"] == "ratio"
    publish.assert_public(doc)


# ── 일봉 (10/21 "일봉도 토스데이터로 · 10분마다 최신화") ─────────────────────────────────────
def test_daily_bars_backfill_pagination_and_split(base):
    collect.run("sectors", dry_run=True, out=base.parent, now=NOW)        # 07:20 작업: 백필(2쪽)
    c = collect.daily_cache(base, "KOSPI")
    assert sorted(c["bars"]) == ["2026-10-14", "2026-10-15", "2026-10-16", "2026-10-19", "2026-10-20"]
    h, t = publish.build_daily(base, NOW)
    assert h["keys"]["KOSPI"]["bars"][-1][0] == "2026-10-19" and t["keys"]["KOSPI"]["bar"][0] == "2026-10-20"   # 과거·오늘 분리
    assert len(t["keys"]["KOSPI"]["bar"]) == 6 and h["keys"]["SPY"]["tz"] == "ET"
    assert isinstance(h["keys"]["KOSPI"]["bars"][0][5], int)                      # 거래량 정수
    publish.assert_public(h)
    publish.assert_public(t)
    assert len(publish.render(t).encode()) < 4000      # 10분마다 바뀌는 파일은 작게


def test_daily_today_capped_when_hist_snapshot_missing(base):
    """포니테일 검수 10/21 #7: 과거 스냅샷(_hist.json)이 비면 캐시 전체가 오늘 파일로 가지 않게 최근 2봉만."""
    collect.run("sectors", dry_run=True, out=base.parent, now=NOW)
    (base / "daily_bars" / "_hist.json").unlink(missing_ok=True)
    h, t = publish.build_daily(base, NOW)
    assert h is None or "KOSPI" not in h["keys"]
    assert [b[0] for b in t["keys"]["KOSPI"]["bars"]] == ["2026-10-19", "2026-10-20"]


def test_daily_hist_only_changes_at_backfill_and_rounding(base):
    collect.run("sectors", dry_run=True, out=base.parent, now=NOW)
    h1, _ = publish.build_daily(base, NOW)
    # 07:20 이후 회차에서 새 날짜(10/21) 봉이 생겨도 과거 파일은 그대로, 오늘 파일이 10/20·10/21 둘 다 덮는다
    c = collect.daily_cache(base, "KOSPI")
    c["bars"]["2026-10-21"] = [5600.123456, 5610.987, 5590.5555, 5605.4444, 1234.0]
    collect._save_daily(base, "KOSPI", c)
    h2, t2 = publish.build_daily(base, NOW + timedelta(hours=10))
    assert publish.render(h1) == publish.render(h2)
    assert [b[0] for b in t2["keys"]["KOSPI"]["bars"]] == ["2026-10-20", "2026-10-21"]
    assert t2["keys"]["KOSPI"]["bar"] == ["2026-10-21", 5600.12, 5610.99, 5590.56, 5605.44, 1234]   # 지수 2자리
    c3 = collect.daily_cache(base, "KR_BOND_3Y")
    c3["bars"]["2026-10-21"] = [3.123456, 3.2, 3.1, 3.15555, None]
    collect._save_daily(base, "KR_BOND_3Y", c3)
    _, t3 = publish.build_daily(base, NOW)
    assert t3["keys"]["KR_BOND_3Y"]["bar"][1] == 3.123 and t3["keys"]["KR_BOND_3Y"]["bar"][5] is None      # 국채 3자리


def test_daily_live_refresh_only_live_keys(tmp_path):
    seen = []

    class C:
        rate_limits = {}

        def get(self, path, params=None):
            seen.append((path, dict(params or {})))
            return collect.fixture_transport("GET", "https://x" + path + "?" + "&".join(f"{k}={v}" for k, v in (params or {}).items()), {}, None) and \
                json.loads(collect.fixture_transport("GET", "https://x" + path + "?" + "&".join(f"{k}={v}" for k, v in (params or {}).items()), {}, None).body)
    now = datetime(2026, 10, 20, 23, 40, tzinfo=KST)
    collect.run("us", dry_run=True, out=tmp_path, now=now, client=C())
    daily = [(p, q) for p, q in seen if q.get("interval") == "1d"]
    assert sorted(q["symbol"] for _p, q in daily) == sorted(collect.DAILY_LIVE_US) and all(q["count"] == 2 for _p, q in daily)


def test_dispatcher_heartbeat_published(base):
    """10/21 A2: 노트북 dispatcher 하트비트(dispatcher.json)를 live.json 에 3필드만 싣는다(done 목록 등은 비공개)."""
    (base / "dispatcher.json").write_text(json.dumps({"last_run": "2026-10-21T09:00:00+09:00", "done": ["x"],
                                                      "last_error": None}), encoding="utf-8")
    doc = publish.build(base, NOW)
    assert doc["dispatcher_heartbeat"] == {"last_run": "2026-10-21T09:00:00+09:00", "last_dispatch": None, "last_error": None}
