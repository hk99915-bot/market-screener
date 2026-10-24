"""KR 장중 히트맵 (보드 maint-heatmap, 2026-10-21 유지보수) — 등락 부호·소스 순서·커버리지 미달 시 이전 값 유지·창·asof 역행 방지."""
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from screener import heatmap_kr as H

KST = ZoneInfo("Asia/Seoul")


def item(code, close, ratio, sign, t="2026-10-21T10:50:00+09:00"):
    return {"itemCode": code, "closePrice": f"{close:,}", "fluctuationsRatio": str(ratio),
            "compareToPreviousPrice": {"code": sign}, "localTradedAt": t}


def test_parse_sign_rules():
    assert H.parse_item(item("005930", 70000, "4.10", "2"))[1]["r1"] == pytest.approx(0.041)
    assert H.parse_item(item("005930", 70000, "4.10", "5"))[1]["r1"] == pytest.approx(-0.041)
    assert H.parse_item(item("005930", 70000, "-1.5", "1"))[1]["r1"] == pytest.approx(0.015)   # 부호는 code 기준
    assert H.parse_item(item("005930", 70000, "0.3", "3"))[1]["r1"] == 0.0
    assert H.parse_item({"itemCode": "005930"}) is None
    assert H.parse_item({"itemCode": "KOSPI", "closePrice": "1", "fluctuationsRatio": "1"}) is None


def _peers(codes):
    return {"asof": "2026-10-20", "rows": [{"s": c, "mc": 1} for c in codes]}


def test_list_then_polling_then_basic():
    codes = [f"{i:06d}" for i in range(1, 11)]
    calls = []

    def get(url):
        calls.append(url)
        if "marketValue/KOSPI" in url and "page=1&" in url:
            return {"stocks": [item(c, 100, "1", "2") for c in codes[:5]]}
        if "marketValue" in url:
            return {"stocks": []}
        if "polling" in url:
            return {"datas": [item(c, 100, "2", "5") for c in codes[5:7]]}
        code = url.split("/stock/")[1].split("/")[0]
        return item(code, 100, "3", "2")
    out, used = H.collect(codes, get)
    assert set(out) == set(codes) and used == ["polling", "list", "basic"]   # 10/24 polling 먼저(당일 시가·고저·거래량)
    assert out["000007"]["r1"] == pytest.approx(-0.02)
    assert sum("/basic" in u for u in calls) == 3   # 80% 미만일 때 모자란 3종목만 종목별


def test_basic_skipped_when_coverage_ok():
    codes = [f"{i:06d}" for i in range(1, 11)]
    def get(url):
        if "marketValue/KOSPI" in url and "page=1&" in url:
            return {"stocks": [item(c, 100, "1", "2") for c in codes[:9]]}
        if "/basic" in url:
            raise AssertionError("basic 호출 안 해야 함")
        return {"stocks": [], "datas": []}
    out, _ = H.collect(codes, get)
    assert len(out) == 9


def test_plan_window():
    assert H.plan(datetime(2026, 10, 21, 10, 55, tzinfo=KST)) == ("2026-10-21", "LIVE")
    assert H.plan(datetime(2026, 10, 21, 15, 40, tzinfo=KST)) == ("2026-10-21", "CLOSE")
    assert H.plan(datetime(2026, 10, 21, 8, 50, tzinfo=KST)) is None
    assert H.plan(datetime(2026, 10, 21, 22, 30, tzinfo=KST)) is None   # 미장 루프 회차엔 안 돎
    assert H.plan(datetime(2026, 10, 9, 10, 0, tzinfo=KST)) is None     # 한글날 휴장
    assert H.plan(datetime(2026, 10, 21, 8, 50, tzinfo=KST), once=True) == ("2026-10-20", "CLOSE")


def test_run_writes_and_keeps_previous_on_low_coverage(tmp_path):
    codes = [f"{i:06d}" for i in range(1, 11)]
    (tmp_path / "peers_KR.json").write_text(json.dumps(_peers(codes)), encoding="utf-8")
    now = datetime(2026, 10, 21, 10, 55, tzinfo=KST)
    good = lambda url: {"stocks": [item(c, 100, "4", "2") for c in codes]} if "KOSPI" in url and "page=1&" in url else {"stocks": [], "datas": []}
    out = H.run(now=now, get=good, root=tmp_path)
    j = json.loads((tmp_path / "heatmap_KR.json").read_text(encoding="utf-8"))
    assert j["asof"] == "2026-10-21 10:55 KST" and j["session"] == "LIVE" and j["collected"] == 10 == out["expected"]
    assert j["base_asof"] == "2026-10-20" and j["rows"][0]["r1"] == pytest.approx(0.04)

    def bad(url):
        raise OSError("down")
    with pytest.raises(RuntimeError, match="coverage 0/10"):
        H.run(now=datetime(2026, 10, 21, 11, 0, tzinfo=KST), get=bad, root=tmp_path)
    assert json.loads((tmp_path / "heatmap_KR.json").read_text(encoding="utf-8"))["asof"] == j["asof"]   # 이전 값 유지


def test_stale_trade_rows_not_mixed():
    peers = _peers(["000001", "000002"])
    q = {"000001": {"r1": 0.01, "close": 1, "t": "2026-10-21T10:50"}, "000002": {"r1": 0.05, "close": 1, "t": "2026-10-20T15:30"}}
    out = H.build(peers, q, datetime(2026, 10, 21, 10, 55, tzinfo=KST), "2026-10-21", "LIVE", ["list"])
    assert [r["s"] for r in out["rows"]] == ["000001"] and out["collected"] == 1


def test_put_newer(tmp_path):
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    a.write_text(json.dumps({"asof": "2026-10-21 10:55 KST"}))
    b.write_text(json.dumps({"asof": "2026-10-21 11:00 KST"}))
    assert H.put_newer(a, b) is False and "11:00" in b.read_text()
    a.write_text(json.dumps({"asof": "2026-10-21 11:05 KST"}))
    assert H.put_newer(a, b) is True and "11:05" in b.read_text()
