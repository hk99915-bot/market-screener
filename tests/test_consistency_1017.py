"""정합성 감사 10/17 (docs/peer_reviews/2026-10-17_consistency_{data,ui}.md) 수정분 회귀 테스트."""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from screener import guard

ROOT = Path(__file__).resolve().parents[1]
KST = ZoneInfo("Asia/Seoul")


@pytest.fixture
def rep(tmp_path, monkeypatch):
    r = tmp_path / "reports"
    r.mkdir()
    monkeypatch.setattr(guard, "_report_dir", lambda: r)
    monkeypatch.delenv("SCREENER_ALLOW_REGRESS", raising=False)
    return r


# ── M1: drivers 캐시 만료는 파일 mtime 이 아니라 파일 안 asof/generated_at ──
def test_cache_age_uses_stored_stamp():
    from screener import drivers
    now = datetime.now(KST)
    assert drivers.cache_age_h({"asof": now.strftime("%Y-%m-%d %H:%M")}) < 0.1
    assert drivers.cache_age_h({"asof": (now - timedelta(days=2)).strftime("%Y-%m-%d %H:%M")}) > 40
    old_utc = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat(timespec="seconds")
    assert 29 < drivers.cache_age_h({"generated_at": old_utc, "asof": now.strftime("%Y-%m-%d %H:%M")}) < 31   # generated_at 우선
    assert drivers.cache_age_h({}) == float("inf")


def test_fetch_proxies_refetches_old_cache_even_with_fresh_mtime(tmp_path, monkeypatch):
    """CI checkout 처럼 mtime 이 '지금'이어도 asof 가 이틀 전이면 다시 받으러 간다(yfinance import 시도)."""
    from screener import drivers
    p = tmp_path / "reports" / "chains.json"
    p.parent.mkdir()
    series = {v[0]: [] for v in drivers.FACTORS.values()}
    old = (datetime.now(KST) - timedelta(days=2)).strftime("%Y-%m-%d %H:%M")
    p.write_text(json.dumps({"asof": old, "series": series}), encoding="utf-8")
    os.utime(p, (time.time(), time.time()))
    monkeypatch.setattr(drivers, "CACHE", p)

    class Boom(Exception):
        pass

    class FakeYF:
        def __getattr__(self, k):
            raise Boom(k)
    monkeypatch.setitem(sys.modules, "yfinance", FakeYF())
    with pytest.raises(Boom):
        drivers.fetch_proxies()
    fresh = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    p.write_text(json.dumps({"asof": fresh, "series": series}), encoding="utf-8")
    assert drivers.fetch_proxies()["asof"] == fresh   # 신선하면 캐시 그대로


def test_freshness_contract_has_chains_and_us_eps():
    items = {i["id"]: i for i in json.loads((ROOT / "ops" / "freshness.json").read_text(encoding="utf-8"))["items"]}
    for k, path in (("chains", "reports/chains.json"), ("us_eps", "reports/us_eps.json")):
        assert items[k]["path"] == path and items[k]["key"] == "asof" and items[k]["kind"] == "session"


# ── M2: accum·us_accum 쓰기는 guard.write_json 경유 (계약 + 역행 차단) ──
def test_accum_write_goes_through_guard(rep, monkeypatch):
    from screener import accum
    out = rep / "accum.json"
    monkeypatch.setattr(accum, "OUT", out)
    monkeypatch.setattr(accum, "archive", lambda o: None)
    base = {"generated_at": "2026-10-16 18:40", "status": "ok", "n": 3}
    assert accum.write({**base, "asof": "2026-10-16"}) is True
    assert json.loads(out.read_text(encoding="utf-8"))["schema_version"] == 1   # contracts.stamp
    assert accum.write({**base, "asof": "2026-10-15"}) is False                  # 역행 차단
    assert json.loads(out.read_text(encoding="utf-8"))["asof"] == "2026-10-16"
    assert accum.write({**base, "asof": "2026-10-17", "n": "x"}) is False         # 계약 위반(형)


def test_us_accum_main_goes_through_guard(rep, monkeypatch):
    from screener import us_accum
    out = rep / "us_accum.json"
    out.write_text(json.dumps({"asof": "2026-10-16"}), encoding="utf-8")
    monkeypatch.setattr(us_accum, "OUT", out)
    o = {"asof": "2026-10-15", "generated_at": "x", "status": "ok", "n_scanned": 1, "n_hits": 0, "hits": [], "reason": ""}
    monkeypatch.setattr(us_accum, "scan", lambda: o)
    us_accum.main()
    assert json.loads(out.read_text(encoding="utf-8"))["asof"] == "2026-10-16"   # 역행이라 그대로
    monkeypatch.setattr(us_accum, "scan", lambda: {**o, "asof": "2026-10-17"})
    us_accum.main()
    d = json.loads(out.read_text(encoding="utf-8"))
    assert d["asof"] == "2026-10-17" and d["schema_version"] == 1


# ── M3·M4: 밸류에이션 asof = 가격일, 주식 수 = 상세와 같은 shares_map, PER 기준 명시 ──
def test_valuation_asof_is_price_date():
    from screener.valuation_daily import price_asof
    rows = [{"mk": "KR", "price_date": "2026-10-16"}, {"mk": "US", "price_date": "2026-10-15"}, {"mk": "KR", "price_date": None}]
    d, pa = price_asof(rows, [{"mk": "KR", "price_date": "2026-10-16"}])
    assert d == "2026-10-16" and pa == {"KR": "2026-10-16", "US": "2026-10-15"}
    assert price_asof([{"mk": "US", "price_date": "2026-10-15"}])[0] == "2026-10-15"
    assert price_asof([])[0] is None


def test_valuation_kr_shares_same_as_detail(monkeypatch):
    from screener import fin, shares, valuation_daily
    monkeypatch.setattr(shares, "shares_map", lambda: {"005930": {"n": 6_648_649_811.0, "src": "DART"}})
    monkeypatch.setattr(fin, "quarterly", lambda code: None)
    assert valuation_daily.kr_quarters("005930") == ([], 6_648_649_811.0)


def test_detail_valuation_states_per_basis():
    from screener import valuation
    q = [{"period": f"2025Q{i}", "ni": 100.0, "ni_owner": 100.0, "op": 50.0, "revenue": 500.0, "equity": 2000.0} for i in range(1, 5)]
    m = valuation.base_metrics(q, 10.0)
    if m is None:
        pytest.skip("base_metrics 입력 형식 변경")
    v = valuation.value(m, 100.0, None, {})
    assert v["per_basis"] == "핵심" and v["per_reported"] != v["per"]   # 순이익 400 > 영업이익 200×1.15 → 핵심이익


# ── 중-5·경-2: 라이브 티커 날짜 혼재 표시, 장외 CLOSE(거래일) ──
def test_live_flag_lag_nikkei():
    from screener.live import flag_lag
    items = [{"key": "NIKKEI", "chg": -0.049, "date": "2026-10-15"}, {"key": "TOPIX", "chg": 0.0176, "date": "2026-10-16"},
             {"key": "SPX", "date": "2026-10-16"}]
    flag_lag(items)
    assert items[0].get("lag") is True and not items[1].get("lag") and not items[2].get("lag")


@pytest.mark.parametrize("now,sess,day", [
    (datetime(2026, 10, 17, 16, 23, tzinfo=KST), "CLOSE", "2026-10-16"),   # 토요일
    (datetime(2026, 10, 19, 8, 0, tzinfo=KST), "CLOSE", "2026-10-16"),     # 월 개장 전
    (datetime(2026, 10, 19, 10, 0, tzinfo=KST), "LIVE", "2026-10-19"),
])
def test_live_session_label(now, sess, day):
    from screener.live import session_label
    assert session_label([], now) == (sess, day)


# ── 경-7: '서프라이즈' 는 컨센서스 병기 때만 ──
def test_surprise_guard():
    from screener.calendar_ev import SURP_NOTE, surprise_guard
    assert surprise_guard("실적 서프라이즈 예상").endswith(SURP_NOTE)
    assert surprise_guard("컨센서스 대비 어닝 서프라이즈") == "컨센서스 대비 어닝 서프라이즈"
    assert surprise_guard(surprise_guard("서프라이즈")) == "서프라이즈" + SURP_NOTE     # 두 번 붙이지 않음
    assert surprise_guard(None) is None and surprise_guard("호실적") == "호실적"


# ── 중-3·경-8: 옛 한도 문구·죽은 getter ──
def test_no_legacy_cap_wording_and_dead_getter():
    assert "상한(60%)" not in (ROOT / "reports" / "decisions.json").read_text(encoding="utf-8")
    assert "getDetail:" not in (ROOT / "scripts" / "build_pages.py").read_text(encoding="utf-8")
    assert "function getDetail(" not in (ROOT / "apps-script" / "Code.gs").read_text(encoding="utf-8")


def test_research_regime_terms_match_regime_tag():
    """리서치 국면 배지·필터는 regime_tag.classify 라벨(상승/조정/하락) 그대로 — '~장' 체계(결재 #3)와 섞지 않음."""
    t = (ROOT / "apps-script" / "tab_research.html").read_text(encoding="utf-8")
    assert "['상승','상승장']" not in t and "${g.l}장" not in t
    assert "const RGC={'상승':'up','조정':'am','하락':'dn'}" in t


def test_ui_smoke_defaults_to_all_views():
    sys.path.insert(0, str(ROOT / "scripts"))
    import ui_smoke
    assert ui_smoke.VIEWS == [] and ui_smoke.MIN_ALL >= 29
