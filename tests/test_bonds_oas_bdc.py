"""FRED OAS 4종 · BDC 바스켓 · AI 인프라 신용 경보 문구 (11/14) — 네트워크 없이 mock.

왜: (1) 신용 스프레드는 그동안 ETF 가격비(HYG/IEF)로만 봤다 — 실제 OAS(ICE BofA)를 fredgraph.csv 로 받아
최신값·20거래일/1개월/3개월 변화·CCC−HY 격차를 남긴다(경보 점수·매매 룰은 불변).
(2) 경보 설명이 '실제로 점수를 준 항목'과 다른 지표를 이름 불렀다(HYG 0점인데 '하이일드까지 번지는 중').
"""
from datetime import date, timedelta

import pytest

from screener import bonds

WIDE = """observation_date,BAMLH0A0HYM2,BAMLC0A4CBBB
2026-11-10,3.25,1.14
2026-11-11,.,1.15
2026-11-12,3.18,.
"""
SINGLE = "observation_date,BAMLH0A3HYC\n2026-11-12,13.14\n"
WIDE_FULL = """observation_date,BAMLH0A0HYM2,BAMLC0A4CBBB,BAMLH0A3HYC,BAMLC0A0CM
2026-11-11,3.26,1.15,12.9,0.90
2026-11-12,3.18,1.14,13.14,0.89
"""


class _Resp:
    def __init__(self, text, code=200):
        self.text, self.code = text, code

    def raise_for_status(self):
        if self.code >= 400:
            raise RuntimeError(f"HTTP {self.code}")


# ── CSV 파싱 ──
def test_parse_wide_csv_drops_missing_values():
    d = bonds.parse_fred_oas_csv(WIDE)
    assert d["BAMLH0A0HYM2"] == {"2026-11-10": 3.25, "2026-11-12": 3.18}   # '.' = 휴일·결측 → 버림
    assert d["BAMLC0A4CBBB"] == {"2026-11-10": 1.14, "2026-11-11": 1.15}


def test_parse_single_and_empty_csv():
    assert bonds.parse_fred_oas_csv(SINGLE) == {"BAMLH0A3HYC": {"2026-11-12": 13.14}}
    assert bonds.parse_fred_oas_csv("") == {}
    assert bonds.parse_fred_oas_csv("observation_date\n") == {}


# ── 수집 ──
def test_fetch_oas_single_request_when_all_present(monkeypatch):
    calls = []

    def fake_get(url, timeout=None):
        calls.append(url)
        return _Resp(WIDE_FULL)
    monkeypatch.setattr("requests.get", fake_get)
    got = bonds.fetch_fred_oas()
    assert set(got) == {i for i, _ in bonds.OAS_IDS.values()}
    assert len(calls) == 1   # 한 번에 다 받히면 재시도 없음


def test_fetch_oas_retries_missing_series(monkeypatch):
    calls = []

    def fake_get(url, timeout=None):
        ids = url.split("id=")[1]
        calls.append(ids)
        return _Resp(SINGLE if "," not in ids else WIDE)   # 다중 응답에 CCC·IG 가 빠짐
    monkeypatch.setattr("requests.get", fake_get)
    got = bonds.fetch_fred_oas()
    assert got["BAMLH0A3HYC"]["2026-11-12"] == 13.14 and got["BAMLH0A0HYM2"]
    assert calls[0].count(",") == 3 and sorted(calls[1:]) == ["BAMLC0A0CM", "BAMLH0A3HYC"]   # 빠진 것만 개별 재시도


def test_fetch_oas_failure_raises_for_caller(monkeypatch):
    def boom(url, timeout=None):
        raise OSError("blocked")
    monkeypatch.setattr("requests.get", boom)
    with pytest.raises(RuntimeError) as e:
        bonds.fetch_fred_oas()
    assert "blocked" in str(e.value)


# ── 섹션(변화·CCC−HY) ──
def _days(n: int, start: str = "2026-06-01"):
    d0 = date.fromisoformat(start)
    return [str(d0 + timedelta(days=i)) for i in range(n)]


def _series(base: float, step: float, n: int = 100) -> dict[str, float]:
    return {d: round(base + i * step, 3) for i, d in enumerate(_days(n))}


def test_oas_section_changes_and_spread():
    ser = {bonds.OAS_IDS["hy"][0]: _series(3.0, 0.01), bonds.OAS_IDS["ccc"][0]: _series(9.0, 0.01),
           bonds.OAS_IDS["bbb"][0]: _series(1.0, 0.0), bonds.OAS_IDS["ig"][0]: _series(0.8, 0.0)}
    sec = bonds.oas_section(ser)
    hy = sec["oas"]["hy"]
    assert hy["v"] == 3.99 and hy["date"] == _days(100)[-1]
    assert hy["d20"] == 20.0 and hy["m1"] == 30.0 and hy["m3"] == 90.0   # %p 차이 → bp
    assert hy["min1y"] == 3.0 and hy["max1y"] == 3.99
    assert sec["asof"] == _days(100)[-1] and sec["missing"] == []
    sp = sec["ccc_minus_hy"]
    assert sp["v"] == 6.0 and sp["d20"] == 0.0 and sp["n"] == 100   # 같은 폭으로 벌어지면 격차 불변
    assert "1%p=100bp" in sec["label"] and "경보 점수·매매 룰 불변" in sec["label"]


def test_oas_section_missing_series():
    sec = bonds.oas_section({"BAMLH0A0HYM2": {"2026-11-11": 3.3, "2026-11-12": 3.2}})
    assert list(sec["oas"]) == ["hy"] and set(sec["missing"]) == {"BAMLC0A4CBBB", "BAMLH0A3HYC", "BAMLC0A0CM"}
    assert "ccc_minus_hy" not in sec
    with pytest.raises(RuntimeError):
        bonds.oas_section({})


def test_attach_oas_ok_and_stale_fallback(monkeypatch):
    monkeypatch.setattr(bonds, "fetch_fred_oas", lambda ids=None: {bonds.OAS_IDS["hy"][0]: _series(3.0, 0.01)})
    o, src = {"asof": "2026-11-14"}, {}
    bonds.attach_oas(o, {}, src)
    assert o["credit_oas"]["oas"]["hy"]["v"] == 3.99 and src["fred_oas"].startswith("ok 1종")

    def boom(ids=None):
        raise RuntimeError("blocked")
    monkeypatch.setattr(bonds, "fetch_fred_oas", boom)
    monkeypatch.setattr("screener.guard.record_stale", lambda *a, **k: None)   # 실제 reports/ 쓰지 않게
    prev = {"asof": "2026-11-13", "credit_oas": {"asof": "2026-11-12", "oas": {"hy": {"v": 3.2}}}}
    o2, src2 = {"asof": "2026-11-14"}, {}
    bonds.attach_oas(o2, prev, src2)
    assert o2["credit_oas"] == prev["credit_oas"] and "이전 값 유지" in src2["fred_oas"]   # 조용한 대체 금지
    assert o2["stale"]["credit_oas"] == {"want": "2026-11-14", "got": "2026-11-12"}
    o3, src3 = {"asof": "2026-11-14"}, {}   # 이전 값도 없으면 키를 만들지 않고 상태만 남긴다
    bonds.attach_oas(o3, {}, src3)
    assert "credit_oas" not in o3 and src3["fred_oas"].startswith("실패")


# ── BDC 바스켓 ──
def test_bdc_basket_label_and_stats():
    px = {t: _series(10.0, 0.01) for t in bonds.BDC_BASKET}
    px["OBDC"] = _series(10.0, -0.05)   # 두 종목만 고점 대비 크게 하락 → 중앙값도 음수
    px["ARCC"] = _series(10.0, -0.02)
    o = bonds.bdc_credit(px)
    assert o["label"].startswith("BDC 주가 낙폭 기반 대용 지표") and "CDS" in o["label"]   # 대용 지표 라벨 명시
    assert len(o["basket"]) == 4 and o["missing"] == [] and o["asof"] == _days(100)[-1]
    assert [r["s"] for r in o["basket"]][0] == "OBDC"   # 낙폭 큰 순
    assert o["basket"][0]["dd"] < 0 and o["dd_median"] < 0 and o["basket"][1]["s"] == "ARCC"
    assert "주가 대용" in o["line"] and "OBDC" in o["line"]
    assert {r["s"] for r in o["basket"]} == set(bonds.BDC_BASKET)


def test_bdc_missing_does_not_raise():
    o = bonds.bdc_credit({})
    assert o["basket"] == [] and sorted(o["missing"]) == sorted(bonds.BDC_BASKET) and o["dd_median"] is None
    assert o["asof"] is None and "데이터 없음" in o["line"]
    assert bonds.bdc_credit({"ARCC": _series(10.0, 0.01)})["basket"][0]["s"] == "ARCC"


# ── AI 인프라 신용 경보 문구 ──
def _basket(dd: float, r20: float, n: int = 4) -> list[dict]:
    return [{"s": f"T{i}", "dd": dd, "r20": r20} for i in range(n)]


def test_alert_thresholds_unchanged():
    """11/14 작업은 문구만 고친다 — 항목·문턱·점수는 그대로(규칙/경보 문턱 변경 없음)."""
    a = bonds.credit_alert(_basket(-0.1, 0.0), 0.0, 15.0)
    assert [c["k"] for c in a["checks"]] == ["basket_dd", "crash_n", "hy_m1", "vix"]
    assert [c["rule"] for c in a["checks"]] == ["−25% 이하 1점 · −40% 이하 2점", "2개 이상 1점 · 3개 이상 2점",
                                               "−1.5% 이하 1점 · −3% 이하 2점", "22 이상 1점 · 30 이상 2점"]
    assert a["level"] == "정상" and a["score"] == 0


def test_alert_lv2_with_quiet_credit_says_local_stress():
    """경계(lv2)인데 HYG·VIX 가 0점 — '번지는 중'이 아니라 '업종 국지'로 써야 한다(11/14 수정)."""
    a = bonds.credit_alert(_basket(-0.60, -0.25), 0.007, 18.3)
    assert a["level"] == "경계" and a["score"] == 4 and [c["pt"] for c in a["checks"]] == [2, 2, 0, 0]
    assert "번지는 중" not in a["explain"]
    assert "국지 스트레스" in a["explain"] and "하이일드·VIX는 평소 범위" in a["explain"]


def test_alert_names_only_contributing_indicators():
    """HYG 만 점수(VIX 0점) → '하이일드'만 부르고 VIX 는 조용하다고 적는다(반대도 같다)."""
    hy = bonds.credit_alert(_basket(-0.30, -0.05), -0.05, 18.0)
    assert hy["checks"][2]["pt"] > 0 and hy["checks"][3]["pt"] == 0
    assert "하이일드 지표까지 번지는 중" in hy["explain"] and "VIX(변동성)" not in hy["explain"]
    assert "VIX는 아직 조용" in hy["explain"]

    vx = bonds.credit_alert(_basket(-0.10, 0.0), 0.002, 33.0)
    assert vx["checks"][2]["pt"] == 0 and vx["checks"][3]["pt"] == 2
    assert "VIX(변동성) 지표까지 번지는 중" in vx["explain"] and "하이일드는 아직 조용" in vx["explain"]

    both = bonds.credit_alert(_basket(-0.30, -0.10), -0.05, 33.0)
    assert "하이일드·VIX(변동성) 지표까지 번지는 중" in both["explain"]


def test_alert_missing_credit_data_is_not_quiet():
    """HYG/VIX 가 없으면 0점이지 '조용함'이 아니다 — 문구가 미확인이라고 말해야 한다."""
    a = bonds.credit_alert(_basket(-0.30, -0.25), None, None)
    assert "데이터가 없어 신용시장 전이 여부는 미확인" in a["explain"] and "평소 범위" not in a["explain"]


# ── 해석 한 줄 ──
def test_interpret_adds_oas_line_only_when_present():
    empty = {"spreads": {}, "us": {"chg": {}}, "kr": {"chg": {}}}
    assert bonds.interpret(empty) == []
    o = dict(empty, credit_oas={"oas": {"hy": {"v": 3.2, "m1": 4.0, "m3": 53.0, "min1y": 2.6, "max1y": 3.48}},
                                "ccc_minus_hy": {"v": 9.94, "m1": 43.0}})
    line = [x for x in bonds.interpret(o) if "OAS" in x]
    assert len(line) == 1 and "3.20%" in line[0] and "+4bp" in line[0] and "CCC−HY 9.94%p" in line[0]
    assert "참고 지표" in line[0]
